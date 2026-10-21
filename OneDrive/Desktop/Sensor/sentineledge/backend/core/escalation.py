# -*- coding: utf-8 -*-
"""
core/escalation.py — SentinelEdge alert delivery engine (simplified).

DELIVERY RULE: When a threshold breach fires, ALL FOUR channels
(Email, SMS, In-App WebSocket, Mobile Push) are sent to ALL active
subscribers simultaneously using asyncio.gather(). Failure of one
channel never blocks the others.

ONE-SHOT DELIVERY: Alerts fire exactly once (level 1) and stop.
No background re-alert timers. No level 2 or level 3.
The escalation_level column always stays at 1.

ACKNOWLEDGE: Admin can manually mark alerts as seen from the dashboard.
The system never calls acknowledge automatically.

DELIVERY RECEIPTS: Logged per alert per subscriber per channel.

PARALLEL ARCHITECTURE (post-upgrade):
- Email:  ThreadPoolExecutor(max_workers=20) — each subscriber gets their
          own SMTP connection; all emails fire simultaneously.
- SMS:    GSM dongle → single queue worker (hardware constraint, one COM port);
          ADB/gateway → asyncio.gather() concurrently.
- Email batch and SMS batch run in parallel via asyncio.gather().
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import database
from modules.email.smtp import send_alert_email_async, send_alert_email_to_all
from modules.email.smtp import send_email_async  # kept for daily reports / legacy
from modules.sms.sender import send_alert_sms_async, send_sms_to_all
from modules.inapp.broadcaster import send_push_async
from modules.mobilepush.expo_push import send_expo_push_async
from modules.mobilepush.fcm_direct import send_fcm_direct_async
from utils.formatter import format_alert_message   # used by _build_message (SMS body)
from utils.severity_router import get_routing
from config import ALERT_COOLDOWN_SECONDS, RUNTIME_THRESHOLDS, is_alert_enabled
from models import BreachEvent

logger = logging.getLogger("sentineledge.escalation")

# No background escalation tasks — kept as empty dict for API compatibility
active_escalations: dict[int, asyncio.Task] = {}


# ─── Message formatting ───────────────────────────────────────────────────────

def _build_message(
    parameter: str,
    value: float,
    threshold: float,
    direction: str,
    severity: str = "WARNING",
) -> str:
    """Build the SMS/plain-text alert body. Always level 1 language."""
    _units = {"temperature": "°C", "ph": ""}
    unit = _units.get(parameter.lower(), "")
    base = format_alert_message(parameter, value, threshold, direction, severity, unit)
    return f"SentinelEdge Alert: {base}. Please check the dashboard."


# ─── Per-subscriber channel dispatcher ───────────────────────────────────────

async def _notify_subscriber(
    alert_id: int,
    subscriber: dict,
    message: str,
    alert_meta: dict | None = None,
) -> None:
    """
    Fire ALL THREE channels (email, SMS, in-app) to one subscriber in parallel.
    Each channel failure is logged independently and never blocks the others.
    """
    sub_id = subscriber["id"]
    level  = 1  # always level 1

    # ── Channel 1: HTML Email ─────────────────────────────────────────────────
    async def _email() -> None:
        err: Optional[str] = None
        try:
            meta = alert_meta or {}
            ok = await send_alert_email_async(
                recipient_email=subscriber["email"],
                recipient_name=subscriber.get("name", "Operator"),
                temperature=float(meta.get("value", 0.0)),
                threshold=float(meta.get("threshold", 0.0)),
                direction=str(meta.get("direction", "high")),
                severity=str(meta.get("severity", "WARNING")),
                escalation_level=level,
                timestamp_utc=str(meta.get("timestamp", "") or ""),
            )
        except Exception as exc:
            ok = False
            err = str(exc)
        database.log_escalation(alert_id, level, sub_id, "email", ok)
        database.insert_receipt(alert_id, "email", sub_id, level, ok, err)
        if not ok:
            logger.warning(
                "Email to %s (sub %d) failed",
                subscriber["email"], sub_id,
            )

    # ── Channel 2: SMS ───────────────────────────────────────────────────────────
    async def _sms() -> None:
        err: Optional[str] = None
        try:
            meta = alert_meta or {}
            ok = await send_alert_sms_async(
                phone=subscriber["phone"],
                value=float(meta.get("value", 0.0)),
                threshold=float(meta.get("threshold", 0.0)),
                direction=str(meta.get("direction", "high")),
                timestamp_utc=str(meta.get("timestamp", "") or ""),
            )
        except Exception as exc:
            ok = False
            err = str(exc)
        database.log_escalation(alert_id, level, sub_id, "sms", ok)
        database.insert_receipt(alert_id, "sms", sub_id, level, ok, err)
        if not ok:
            logger.warning(
                "SMS to %s (sub %d) failed",
                subscriber["phone"], sub_id,
            )

    # ── Channel 3: In-App WebSocket push ─────────────────────────────────────
    async def _push() -> None:
        push_sub = subscriber.get("push_subscription")
        err: Optional[str] = None
        if not push_sub:
            database.insert_receipt(
                alert_id, "inapp", sub_id, level, False, "no active connection"
            )
            return
        try:
            subject = "SentinelEdge Alert"
            ok = await send_push_async(push_sub, subject, message, {"alert_id": alert_id})
        except Exception as exc:
            ok = False
            err = str(exc)
        database.log_escalation(alert_id, level, sub_id, "inapp", ok)
        database.insert_receipt(alert_id, "inapp", sub_id, level, ok, err)
        if not ok:
            logger.warning("In-app push to sub %d failed", sub_id)

    # ── Channel 4: Mobile push (Expo → data-only, drives the client's full-screen alarm) ──
    async def _mobile_push() -> None:
        expo_token = subscriber.get("expo_push_token")
        fcm_token  = subscriber.get("fcm_token")
        err: Optional[str] = None
        if not expo_token and not fcm_token:
            database.insert_receipt(
                alert_id, "mobile_push", sub_id, level, False, "no mobile push token"
            )
            return
        try:
            meta = alert_meta or {}
            payload = {
                "type":      "critical",
                "parameter": meta.get("parameter"),
                "value":     meta.get("value"),
                "threshold": meta.get("threshold"),
                "message":   message,
                "timestamp": meta.get("timestamp"),
                "alert_id":  alert_id,
            }
            tasks = []
            if fcm_token:
                tasks.append(send_fcm_direct_async(fcm_token, payload, subscriber_id=sub_id))
            if expo_token:
                tasks.append(send_expo_push_async(expo_token, payload))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            ok = any(r is True for r in results)
            errs = [str(r) for r in results if isinstance(r, Exception)]
            if errs:
                err = "; ".join(errs)
        except Exception as exc:
            ok = False
            err = str(exc)
        database.log_escalation(alert_id, level, sub_id, "mobile_push", ok)
        database.insert_receipt(alert_id, "mobile_push", sub_id, level, ok, err)
        if not ok:
            logger.warning("Mobile push to sub %d failed (both paths): %s", sub_id, err)

    # Fire all four in parallel — failure of one never blocks others
    await asyncio.gather(_email(), _sms(), _push(), _mobile_push(), return_exceptions=True)
    logger.info(
        "All channels dispatched to %s (sub %d, alert_id=%d)",
        subscriber["name"], sub_id, alert_id,
    )


# ─── Broadcast to all active subscribers ─────────────────────────────────────

async def _notify_all_subscribers(
    alert_id: int,
    parameter: str,
    value: float,
    threshold: float,
    direction: str,
) -> None:
    """
    Deliver alerts to every active subscriber simultaneously.

    Architecture (parallel):
    ─────────────────────────────────────────────────────────────────
    1. Email batch   — all emails fired at once via ThreadPoolExecutor
                       (up to 20 parallel SMTP connections)
    2. SMS batch     — all SMS queued simultaneously:
                       • gammu: single queue worker (serial port constraint)
                       • adb/gateway: asyncio.gather() concurrently
    3. In-app push   — per-subscriber WebSocket push, gathered concurrently
    4. Channels 1+2 run in parallel via asyncio.gather(email, sms)
    ─────────────────────────────────────────────────────────────────
    Always fires at escalation level 1. Receipts logged for every channel.
    """
    # Second gate: if the parameter was disabled between breach detection and
    # notification dispatch (e.g. admin disabled during cooldown window),
    # skip ALL channels so no email, SMS, or push reaches subscribers.
    if parameter == "temperature" and not is_alert_enabled("temperature"):   # others: per company, checked earlier
        logger.info(
            "Alert %d skipped — %s alerts are disabled", alert_id, parameter
        )
        return

    alert_meta = database.get_alert(alert_id) or {}
    severity   = alert_meta.get("severity", "WARNING")
    timestamp_utc = str(alert_meta.get("timestamp", "") or "")
    company_id = alert_meta.get("company_id")
    routing    = get_routing(company_id, severity)

    # Only the alerting company's own people are notified — never another company's
    subscribers = database.get_subscribers_ordered(company_id) if company_id is not None else []
    active_subs = [s for s in subscribers if s.get("is_active", s.get("active", True))]

    if not active_subs:
        logger.warning("No active subscribers to notify for alert %d", alert_id)
        return

    database.update_escalation_level(alert_id, 1)
    level = 1

    logger.info(
        "Parallel alert delivery: %d active subscriber(s) → alert %d",
        len(active_subs), alert_id,
    )

    # The company's own wording for this parameter (empty = the standard message)
    tpl, ctx_base = {"sms": "", "email_subject": "", "email_body": ""}, {}
    try:
        from services import message_templates as _mt
        tpl = _mt.get_templates(company_id, parameter)
        if tpl.get("sms") or tpl.get("email_subject") or tpl.get("email_body"):
            co = database.execute_read("SELECT name FROM companies WHERE id = %s", (company_id,))
            ctx_base = _mt.build_context(
                company=co[0]["name"] if co else "", parameter=tpl.get("name") or parameter, unit=tpl.get("unit", ""),
                value=value, limit=threshold, direction=direction, severity=severity,
                timestamp_utc=timestamp_utc, min_value=tpl.get("min"), max_value=tpl.get("max"))
    except Exception as exc:
        logger.warning("custom message wording unavailable for alert %d (standard wording used): %s", alert_id, exc)
        tpl = {"sms": "", "email_subject": "", "email_body": ""}
    custom_email = ({"subject": tpl["email_subject"], "body": tpl["email_body"], "ctx": ctx_base}
                    if (tpl.get("email_subject") or tpl.get("email_body")) else None)
    from services import company_email as _ce
    company_smtp = _ce.get_company_smtp(company_id)      # the company's own mailbox (None = platform mailbox)

    # ── Channel 1 (Batch): HTML Email to ALL subscribers simultaneously ────────
    async def _email_batch() -> None:
        try:
            results = await send_alert_email_to_all(
                subscribers=active_subs,
                value=value,
                threshold=threshold,
                direction=direction,
                severity=severity,
                timestamp_utc=timestamp_utc,
                parameter=parameter,
                custom=custom_email,
                smtp=company_smtp,
            )
            if results:
                bad = [r for r in results if r.get("status") != "sent"]
                _ce.record_result(company_id, not bad, (bad[0].get("error") if bad else None))
            # Log receipts for each subscriber
            for sub, res in zip(active_subs, results):
                ok  = res.get("status") == "sent"
                err = res.get("error")
                database.log_escalation(alert_id, level, sub["id"], "email", ok)
                database.insert_receipt(alert_id, "email", sub["id"], level, ok, err)
                if not ok:
                    logger.warning(
                        "Email to %s (sub %d) failed: %s",
                        sub["email"], sub["id"], err,
                    )
        except Exception as exc:
            logger.error("Email batch failed for alert %d: %s", alert_id, exc)
            for sub in active_subs:
                database.log_escalation(alert_id, level, sub["id"], "email", False)
                database.insert_receipt(alert_id, "email", sub["id"], level, False, str(exc))

    # ── Channel 2 (Batch): SMS to ALL subscribers simultaneously ──────────────
    async def _sms_batch() -> None:
        try:
            # Only send to subscribers that have a phone number stored.
            # send_sms_to_all already filters on phone, but we log skipped
            # subscribers here so operators can see exactly who gets SMS.
            sms_targets = [s for s in active_subs if s.get("phone")]
            skipped = len(active_subs) - len(sms_targets)
            if skipped:
                logger.info(
                    "SMS: skipping %d subscriber(s) with no phone number", skipped
                )

            if not sms_targets:
                logger.warning("SMS batch: no subscribers with a phone number — skipping")
                for sub in active_subs:
                    database.insert_receipt(
                        alert_id, "sms", sub["id"], level, False, "no phone number"
                    )
                return

            # Log each subscriber before handing off to the queue worker
            for sub in sms_targets:
                logger.info(
                    "SMS queued for subscriber %s — %s",
                    sub["name"], sub["phone"],
                )

            results = await send_sms_to_all(
                subscribers=sms_targets,
                value=value,
                threshold=threshold,
                direction=direction,
                timestamp_utc=timestamp_utc,
                parameter=parameter,
                sms_template=tpl.get("sms") or None,
                sms_ctx=ctx_base,
            )

            # Log receipts for targeted subscribers
            targeted_ids = {s["id"] for s in sms_targets}
            for sub, res in zip(sms_targets, results):
                ok  = res.get("status") in ("sent", "queued", "mock_sent")
                err = res.get("error")
                database.log_escalation(alert_id, level, sub["id"], "sms", ok)
                database.insert_receipt(alert_id, "sms", sub["id"], level, ok, err)
                if not ok:
                    logger.warning(
                        "SMS to %s (sub %d) failed: %s",
                        sub["phone"], sub["id"], err,
                    )

            # Mark no-phone subscribers as skipped in receipts
            for sub in active_subs:
                if sub["id"] not in targeted_ids:
                    database.insert_receipt(
                        alert_id, "sms", sub["id"], level, False, "no phone number"
                    )

        except Exception as exc:
            logger.error("SMS batch failed for alert %d: %s", alert_id, exc)
            for sub in active_subs:
                database.log_escalation(alert_id, level, sub["id"], "sms", False)
                database.insert_receipt(alert_id, "sms", sub["id"], level, False, str(exc))

    # ── Channel 3 (Per-subscriber): In-App WebSocket push ─────────────────────
    message = _build_message(parameter, value, threshold, direction, severity)

    async def _push_one(sub: dict) -> None:
        push_sub = sub.get("push_subscription")
        sub_id   = sub["id"]
        if not push_sub:
            database.insert_receipt(alert_id, "inapp", sub_id, level, False, "no active connection")
            return
        err: Optional[str] = None
        try:
            ok = await send_push_async(push_sub, "SentinelEdge Alert", message, {"alert_id": alert_id})
        except Exception as exc:
            ok  = False
            err = str(exc)
        database.log_escalation(alert_id, level, sub_id, "inapp", ok)
        database.insert_receipt(alert_id, "inapp", sub_id, level, ok, err)
        if not ok:
            logger.warning("In-app push to sub %d failed", sub_id)

    push_tasks = [_push_one(sub) for sub in active_subs]

    # ── Channel 4 (Per-subscriber): Mobile push — direct FCM + Expo relay ─────
    # Sent in parallel via BOTH paths when both tokens are known: direct FCM
    # (bypasses Expo's relay, explicit high-priority AndroidConfig — added
    # after confirming relay delivery reached FCM cleanly, per Expo's own
    # receipts, but still proved unreliable waking a fully-killed app on an
    # aggressive OEM device) and the Expo relay (kept as a second path — a
    # duplicate notification is a far better failure mode than a missed one
    # for a critical alert). Counted as delivered if EITHER path succeeds.
    async def _mobile_push_one(sub: dict) -> None:
        expo_token = sub.get("expo_push_token")
        fcm_token  = sub.get("fcm_token")
        sub_id = sub["id"]
        if not expo_token and not fcm_token:
            database.insert_receipt(alert_id, "mobile_push", sub_id, level, False, "no mobile push token")
            return
        payload = {
            "type":      "critical",
            "parameter": parameter,
            "value":     value,
            "threshold": threshold,
            "message":   message,
            "timestamp": timestamp_utc,
            "alert_id":  alert_id,
        }
        err: Optional[str] = None
        try:
            tasks = []
            if fcm_token:
                tasks.append(send_fcm_direct_async(fcm_token, payload, subscriber_id=sub_id))
            if expo_token:
                tasks.append(send_expo_push_async(expo_token, payload))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            ok = any(r is True for r in results)
            errs = [str(r) for r in results if isinstance(r, Exception)]
            if errs:
                err = "; ".join(errs)
        except Exception as exc:
            ok  = False
            err = str(exc)
        database.log_escalation(alert_id, level, sub_id, "mobile_push", ok)
        database.insert_receipt(alert_id, "mobile_push", sub_id, level, ok, err)
        if not ok:
            logger.warning("Mobile push to sub %d failed (both paths): %s", sub_id, err)

    mobile_push_tasks = [_mobile_push_one(sub) for sub in active_subs]

    # ── Severity routing: close push coroutines for disabled channels ─────────
    # push_tasks / mobile_push_tasks are already-created coroutine objects.
    # Closing them before gather avoids "coroutine never awaited" warnings.
    if not routing["push"]:
        for _c in push_tasks:        _c.close()
        for _c in mobile_push_tasks: _c.close()
        push_tasks, mobile_push_tasks = [], []

    # ── Fire enabled channels simultaneously ────────────────────────────────
    _ch: list = []
    if routing["email"]: _ch.append(_email_batch())
    if routing["sms"]:   _ch.append(_sms_batch())
    await asyncio.gather(*_ch, *push_tasks, *mobile_push_tasks, return_exceptions=True)

    logger.info(
        "Parallel alert delivery complete for alert %d — %d subscriber(s) notified "
        "(email=%s sms=%s push=%s)",
        alert_id, len(active_subs),
        routing["email"], routing["sms"], routing["push"],
    )


# ─── Public API ───────────────────────────────────────────────────────────────

async def trigger_alert(reading: dict, breaches: list, company_id=None) -> list:
    """
    Process all breach events from a single sensor reading.

    Persisting each alert (DB insert) is fast and happens here, synchronously,
    so callers get real alert_ids back immediately — the WebSocket broadcast
    loop needs these right away to include in the live payload (so the
    mobile app can later call POST /api/alerts/{id}/acknowledge). Notification
    delivery (email/SMS/push, which can take real time) is dispatched as a
    background task so it never blocks the live broadcast.

    Returns a list aligned 1:1 with *breaches* — each entry is the new
    alert's id, or None if that particular insert failed.
    """
    alert_ids: list = []
    persisted = []  # (alert_id, breach, live_threshold) — only successful inserts
    now = datetime.now(timezone.utc)
    cooldown_until = (now + timedelta(seconds=ALERT_COOLDOWN_SECONDS)).isoformat()

    for breach in breaches:
        # Gate: if this parameter's alerts were disabled between sensor read and
        # here, skip entirely — no DB insert, no notification on any channel.
        # Temperature keeps the server-wide on/off switch; every other parameter's on/off is
        # per company and was already applied before the breach was created.
        if breach.parameter == "temperature" and not is_alert_enabled("temperature"):
            logger.info(
                "Alert suppressed (gate 1) — %s alerts are disabled", breach.parameter
            )
            alert_ids.append(None)
            continue

        severity = getattr(breach, "severity", "WARNING")

        # For temperature use RUNTIME_THRESHOLDS so live edits are reflected;
        # for other parameters (pH, etc.) use the threshold from the breach itself.
        from services.sensor_company import get_sensor_company_id as _gsc
        if breach.parameter == "temperature" and (company_id is None or company_id == _gsc()):
            # the PC's main company: its live-editable server temperature limits
            rt = RUNTIME_THRESHOLDS.get("temperature", {})
            if breach.direction == "high":
                live_threshold = rt.get("high", breach.threshold)
            else:
                live_threshold = rt.get("low", breach.threshold)
        else:
            live_threshold = breach.threshold

        alert_id = database.insert_alert(
            parameter=breach.parameter,
            value=breach.value,
            threshold=live_threshold,
            direction=breach.direction,
            cooldown_until=cooldown_until,
            severity=severity,
            company_id=company_id,          # the company whose plant produced the reading
        )
        if alert_id == -1:
            logger.error("Failed to insert alert for breach: %s", breach)
            alert_ids.append(None)
            continue

        alert_ids.append(alert_id)
        persisted.append((alert_id, breach, live_threshold))
        logger.info(
            "Alert %d created: %s=%s (threshold %s, dir=%s, severity=%s)",
            alert_id, breach.parameter, breach.value,
            live_threshold, breach.direction, severity,
        )

    if persisted:
        asyncio.create_task(_notify_all_for_persisted(persisted))

    return alert_ids


async def _notify_all_for_persisted(persisted: list) -> None:
    """Background task: deliver notifications for already-persisted alerts."""
    for alert_id, breach, live_threshold in persisted:
        await _notify_all_subscribers(
            alert_id,
            breach.parameter, breach.value,
            live_threshold, breach.direction,
        )


async def acknowledge(alert_id: int, acknowledged_by: str) -> bool:
    """
    Mark an alert as seen (optional, manual action from dashboard).
    Broadcasts an 'acknowledgement' WebSocket event so dashboards update live.
    """
    from datetime import datetime, timezone

    ok = database.acknowledge_alert(alert_id, acknowledged_by)
    if ok:
        logger.info("Alert %d marked as seen by '%s'.", alert_id, acknowledged_by)
        # Fetch the updated alert to compute response_time_seconds
        alert = database.get_alert(alert_id)
        response_time: int | None = None
        if alert and alert.get("acknowledged_at") and alert.get("timestamp"):
            try:
                fmt = "%Y-%m-%dT%H:%M:%S.%f+00:00"
                # Try multiple ISO formats
                def _parse(s: str) -> datetime:
                    for fmt in (
                        "%Y-%m-%dT%H:%M:%S.%f+00:00",
                        "%Y-%m-%dT%H:%M:%S+00:00",
                        "%Y-%m-%dT%H:%M:%S.%fZ",
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S.%f",
                        "%Y-%m-%dT%H:%M:%S",
                    ):
                        try:
                            return datetime.strptime(s, fmt)
                        except ValueError:
                            continue
                    raise ValueError(f"Cannot parse datetime: {s}")

                ack_time   = _parse(alert["acknowledged_at"])
                alert_time = _parse(alert["timestamp"])
                response_time = max(0, int((ack_time - alert_time).total_seconds()))
            except Exception as exc:
                logger.warning("Could not compute response_time_seconds: %s", exc)

        # Broadcast to all connected WebSocket clients
        try:
            from modules.inapp.manager import broadcast as _broadcast
            await _broadcast({
                "type":                "acknowledgement",
                "alert_id":            alert_id,
                "acknowledged_by":     acknowledged_by,
                "acknowledged_at":     alert.get("acknowledged_at") if alert else None,
                "alert_timestamp":     alert.get("timestamp") if alert else None,
                "alert_value":         alert.get("value") if alert else None,
                "response_time_seconds": response_time,
            }, company_id=(alert or {}).get("company_id"))
        except Exception as exc:
            logger.warning("Ack broadcast failed: %s", exc)
    else:
        logger.error("Failed to mark alert %d as seen.", alert_id)
    return ok



async def resume_pending_escalations() -> None:
    """
    Called at startup — no-op in simplified delivery mode.
    Kept for API compatibility with main.py startup sequence.
    """
    logger.info("One-shot delivery mode: no escalation tasks to resume.")


async def shutdown_escalations() -> None:
    """
    Called at server shutdown — no-op in simplified delivery mode.
    """
    pass

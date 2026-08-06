"""
modules/sms/receiver.py — Incoming SMS handler for SentinelEdge.

Polls the GSM modem every 30 s for incoming SMS and processes ACK commands.
Only activates when SMS_METHOD=gammu and a modem is detected (not in mock mode).

ACK syntax (case-insensitive, whitespace-tolerant):
    ACK <alert_id>

Flow per poll cycle:
    1. Open gammu connection, read all MT-folder SMS, delete them from modem, close.
    2. For each: parse ACK <id>, verify phone→subscriber→company.
    3. Call escalation.acknowledge() — updates DB + broadcasts WebSocket event.
    4. Send confirmation SMS back to sender via run_in_executor (non-blocking).
"""

from __future__ import annotations

import asyncio
import re

from config import SMS_METHOD, SMS_GAMMU_PORT, SMS_GAMMU_BAUD
from database.connection import execute_read
from utils.logger import get_logger

logger = get_logger("sms.receiver")

_ACK_PATTERN = re.compile(r"^\s*ACK\s+(\d+)\s*$", re.IGNORECASE)


async def run_sms_receiver() -> None:
    """Background task: poll modem for incoming ACK SMS every 30 s."""
    method = (SMS_METHOD or "").lower().strip()
    if method != "gammu":
        logger.info(
            "SMS receiver not started (SMS_METHOD=%s — requires gammu)", SMS_METHOD
        )
        return

    # Read _mock_mode via module reference so we see the value set by initialize_gsm_modem()
    import modules.sms.sender as _sender_mod
    if _sender_mod._mock_mode:
        logger.info(
            "SMS receiver not started — no modem detected (running in mock mode). "
            "Plug in the GSM dongle and restart to enable two-way SMS."
        )
        return

    logger.info("SMS receiver started — polling every 30 s for incoming ACK messages")
    while True:
        await asyncio.sleep(30)
        try:
            loop = asyncio.get_running_loop()
            messages = await loop.run_in_executor(None, _poll_incoming_sms)
            for msg in messages:
                await _process_message(msg["phone"], msg["text"])
        except Exception as exc:
            logger.error("SMS receiver poll error: %s", exc)


def _poll_incoming_sms() -> list[dict]:
    """
    Open gammu connection, read all received SMS, delete them, close.
    Returns list of {phone, text} dicts.
    Never raises — all errors logged, returns [].
    Deletion happens immediately after read to prevent re-processing on next poll.
    """
    try:
        import gammu  # type: ignore
    except ImportError:
        logger.error(
            "gammu package not installed — SMS receiver cannot read messages. "
            "Install with: pip install python-gammu  (Windows) or  pip install gammu  (Linux)."
        )
        return []

    sm = gammu.StateMachine()
    sm.SetConfig(0, {
        "Device":     SMS_GAMMU_PORT,
        "Connection": "at",
        "BaudRate":   str(SMS_GAMMU_BAUD),
    })

    try:
        sm.Init()
    except Exception as exc:
        logger.debug(
            "SMS receiver: cannot connect to modem on %s (%s) — will retry next poll",
            SMS_GAMMU_PORT, exc,
        )
        return []

    messages: list[dict] = []
    to_delete: list[dict] = []   # collect (folder, location) for deferred deletion

    try:
        # Iterate through all messages in folder 0 (received/MT)
        try:
            sms_parts = sm.GetNextSMS(Folder=0, Start=True)
            while True:
                for part in sms_parts:
                    phone    = (part.get("Number") or "").strip()
                    text     = (part.get("Text")   or "").strip()
                    location = part.get("Location")
                    folder   = part.get("Folder", 0)
                    if phone and text:
                        messages.append({"phone": phone, "text": text})
                    if location is not None:
                        to_delete.append({"folder": folder, "location": location})
                sms_parts = sm.GetNextSMS(Folder=0, Start=False)
        except Exception:
            pass  # gammu.ERR_EMPTY or no more messages — normal loop exit

        # Delete processed messages so we don't re-process them next poll
        for entry in to_delete:
            try:
                sm.DeleteSMS({"Folder": entry["folder"], "Location": entry["location"]})
            except Exception as del_exc:
                logger.warning(
                    "SMS receiver: could not delete message at folder=%s location=%s: %s",
                    entry["folder"], entry["location"], del_exc,
                )

    finally:
        try:
            sm.Terminate()
        except Exception:
            pass

    if messages:
        logger.info(
            "SMS receiver: read and deleted %d incoming message(s) from modem",
            len(messages),
        )
    return messages


async def _process_message(phone: str, text: str) -> None:
    """Parse an incoming SMS and process ACK commands."""
    m = _ACK_PATTERN.match(text)
    if not m:
        logger.debug(
            "SMS receiver: unrecognized message from %s: %r (expected: ACK <id>)",
            phone, text[:60],
        )
        return

    alert_id = int(m.group(1))
    logger.info(
        "SMS receiver: ACK request — alert_id=%d from phone=%s", alert_id, phone
    )

    # Verify phone → active subscriber
    sub_rows = execute_read(
        "SELECT id, name, company_id FROM subscribers WHERE phone = %s AND is_active = 1 LIMIT 1",
        (phone,),
    )
    if not sub_rows:
        logger.warning(
            "SMS receiver: ACK from unrecognized/inactive phone %s for alert %d — ignored",
            phone, alert_id,
        )
        await _send_reply(
            phone,
            "SentinelEdge: Phone not recognized. Register this number as a subscriber to use ACK.",
        )
        return

    sub        = sub_rows[0]
    company_id = sub["company_id"]

    # Verify alert exists and belongs to this subscriber's company
    alert_rows = execute_read(
        "SELECT id, company_id, acknowledged FROM alerts WHERE id = %s LIMIT 1",
        (alert_id,),
    )
    if not alert_rows:
        logger.warning(
            "SMS receiver: ACK for non-existent alert %d from %s", alert_id, phone
        )
        await _send_reply(phone, f"SentinelEdge: Alert #{alert_id} not found.")
        return

    alert = alert_rows[0]

    if alert["company_id"] != company_id:
        logger.warning(
            "SMS receiver: company mismatch — alert %d belongs to company %d, "
            "subscriber %s (%s) is in company %d",
            alert_id, alert["company_id"], sub["name"], phone, company_id,
        )
        await _send_reply(
            phone,
            f"SentinelEdge: Alert #{alert_id} does not belong to your company.",
        )
        return

    if alert["acknowledged"]:
        logger.info(
            "SMS receiver: alert %d already acknowledged — reply sent to %s",
            alert_id, phone,
        )
        await _send_reply(
            phone,
            f"SentinelEdge: Alert #{alert_id} was already acknowledged.",
        )
        return

    # Acknowledge — reuse escalation.acknowledge() for DB update + WebSocket broadcast
    import core.escalation as _escalation
    ok = await _escalation.acknowledge(alert_id, f"SMS ({sub['name']})")

    if ok:
        logger.info(
            "SMS receiver: alert %d acknowledged by %s (%s)",
            alert_id, sub["name"], phone,
        )
        await _send_reply(
            phone,
            f"SentinelEdge: Alert #{alert_id} acknowledged. Thank you, {sub['name']}.",
        )
    else:
        logger.error(
            "SMS receiver: failed to acknowledge alert %d for %s", alert_id, phone
        )
        await _send_reply(
            phone,
            f"SentinelEdge: Could not acknowledge Alert #{alert_id}. Please try the app.",
        )


async def _send_reply(phone: str, message: str) -> None:
    """Send a confirmation/error SMS reply. Runs send_sms in executor to avoid blocking the loop."""
    try:
        from modules.sms.sender import send_sms
        loop = asyncio.get_running_loop()
        ok   = await loop.run_in_executor(None, send_sms, phone, message)
        if not ok:
            logger.warning("SMS receiver: reply to %s could not be delivered", phone)
    except Exception as exc:
        logger.error("SMS receiver: error sending reply to %s: %s", phone, exc)

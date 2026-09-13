"""
core/escalation_policy.py — Escalation Policy Engine — Notify Once, Mark Done.

Design:
    Every 60 seconds, check for alerts that:
        1. Were created > initial_wait_minutes ago
        2. Are NOT acknowledged
        3. Have NEVER been escalated (no entry in policy_escalation_log)

    For each such alert:
        Insert into policy_escalation_log FIRST (marks "done forever")
        Then send ONE reminder to all subscribers via email + SMS
        Never process this alert again — even if notification fails

    This gives subscribers a second chance if they missed the first
    notification. After this one reminder — silence. No repeats. No spam.

Column notes (vs. spec template):
    - alerts.timestamp (TEXT) not alerts.created_at (doesn't exist)
    - alerts.acknowledged = 0 not alerts.resolved = 0
    - policy_escalation_log has: id, alert_id, subscriber_id,
      escalation_level, notified_at, acknowledged, acknowledged_at
      (NO channel or success columns)
"""

from __future__ import annotations

import asyncio

from database.connection import execute_read, execute_write
from config import is_alert_enabled
from utils.logger import get_logger

logger = get_logger("sentineledge.core.escalation_policy")


async def run_escalation_check() -> None:
    """Background task — wakes every 60 s. Safe to run forever; will never spam."""
    logger.info("Escalation policy engine started (60 s interval) — notify-once mode")
    while True:
        await asyncio.sleep(60)
        try:
            await _check_and_notify_once()
        except Exception as exc:
            logger.error("escalation_policy error: %s", exc)


async def _check_and_notify_once() -> None:
    """
    Find alerts that need a one-time reminder and send it.
    At most 10 alerts per company per tick — prevents burst on backlog.
    """
    policies = execute_read("""
        SELECT ep.company_id, ep.initial_wait_minutes, c.name AS company_name
          FROM escalation_policy ep
          JOIN companies c ON c.id = ep.company_id
         WHERE ep.enabled = 1 AND c.is_active = 1
    """)

    if not policies:
        return

    for policy in policies:
        alerts = execute_read("""
            SELECT a.id, a.parameter, a.value, a.threshold,
                   a.direction, a.severity, a.timestamp, a.company_id
              FROM alerts a
             WHERE a.company_id = %s
               AND a.acknowledged = 0
               AND a.timestamp::timestamptz < NOW() - (%s * INTERVAL '1 minute')
               AND a.timestamp::timestamptz > NOW() - INTERVAL '24 hours'
               AND NOT EXISTS (
                       SELECT 1 FROM policy_escalation_log pel
                        WHERE pel.alert_id = a.id
                   )
             ORDER BY a.timestamp ASC
             LIMIT 10
        """, (policy["company_id"], policy["initial_wait_minutes"]))

        for alert in alerts:
            await _send_reminder_and_mark_done(alert, policy)


async def _send_reminder_and_mark_done(alert: dict, policy: dict) -> None:
    """
    Send exactly ONE reminder for this alert.
    The log entry is inserted BEFORE the notification fires so that
    any failure still prevents a retry — spam-proof by design.
    """
    from modules.email.smtp import send_alert_email_to_all
    from modules.sms.sender import send_sms_to_all
    from utils.severity_router import get_routing

    alert_id   = alert["id"]
    company_id = alert["company_id"]
    severity   = alert["severity"]
    parameter  = str(alert.get("parameter") or "temperature")

    # Gate: if this parameter's alerts are currently disabled, skip the reminder.
    # The log entry is still written so this alert is never retried.
    if not is_alert_enabled(parameter):
        execute_write(
            """INSERT INTO policy_escalation_log (alert_id, escalation_level, notified_at)
               VALUES (%s, 1, NOW())""",
            (alert_id,),
        )
        logger.info(
            "Escalation reminder suppressed for alert %d — %s alerts are disabled",
            alert_id, parameter,
        )
        return

    # Mark done first — alert will never be processed again
    execute_write(
        """INSERT INTO policy_escalation_log (alert_id, escalation_level, notified_at)
           VALUES (%s, 1, NOW())""",
        (alert_id,),
    )

    subscribers = execute_read(
        "SELECT * FROM subscribers WHERE company_id = %s AND is_active = 1",
        (company_id,),
    )
    if not subscribers:
        logger.debug(
            "Escalation reminder: alert %d — no active subscribers, logged as done",
            alert_id,
        )
        return

    logger.warning(
        "Escalation reminder: alert %d → %d subscriber(s) "
        "(unacked for >%d min, sending ONCE then never again)",
        alert_id, len(subscribers), policy["initial_wait_minutes"],
    )

    routing       = get_routing(company_id, severity)
    timestamp_utc = str(alert.get("timestamp", "") or "")

    tasks: list = []
    if routing["email"]:
        tasks.append(send_alert_email_to_all(
            subscribers=subscribers,
            value=float(alert["value"]),
            threshold=float(alert["threshold"]),
            direction=str(alert.get("direction", "high")),
            severity=severity,
            timestamp_utc=timestamp_utc,
            parameter=parameter,
        ))
    if routing["sms"]:
        tasks.append(send_sms_to_all(
            subscribers=subscribers,
            value=float(alert["value"]),
            threshold=float(alert["threshold"]),
            direction=str(alert.get("direction", "high")),
            timestamp_utc=timestamp_utc,
            parameter=parameter,
        ))

    if tasks:
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info(
                "Escalation reminder complete for alert %d — logged, will not fire again",
                alert_id,
            )
        except Exception as exc:
            logger.error(
                "Escalation reminder dispatch failed for alert %d: %s "
                "(log entry already written — will NOT retry)",
                alert_id, exc,
            )


async def disable_escalation_for_company(company_id: int) -> None:
    """Disable escalation for one company (sets escalation_policy.enabled = 0)."""
    execute_write(
        "UPDATE escalation_policy SET enabled = 0 WHERE company_id = %s",
        (company_id,),
    )
    logger.info("Escalation disabled for company %d", company_id)

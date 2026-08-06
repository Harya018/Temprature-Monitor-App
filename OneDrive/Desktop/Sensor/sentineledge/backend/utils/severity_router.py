"""
utils/severity_router.py — Severity-based channel routing for alert delivery.

Called from escalation.py before sending notifications.
Reads from severity_routing table; falls back to DEFAULT_ROUTING on any error.

Severity values match what threshold.py produces:
    WARNING   — 0-10% beyond threshold
    CRITICAL  — 10-25% beyond threshold
    EMERGENCY — >25% beyond threshold
"""
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_ROUTING: dict = {
    "WARNING":   {"email": True,  "sms": True,  "push": True,  "escalation": False},
    "CRITICAL":  {"email": True,  "sms": True,  "push": True,  "escalation": True},
    "EMERGENCY": {"email": True,  "sms": True,  "push": True,  "escalation": True},
}


def get_routing(company_id, severity: str) -> dict:
    """
    Return { email: bool, sms: bool, push: bool, escalation: bool } for
    a given company + severity.

    Falls back to DEFAULT_ROUTING when:
    - company_id is None / missing (single-tenant or no company set yet)
    - no DB row found for this company + severity
    - any database error
    """
    key = (severity or "WARNING").upper()
    fallback = {**DEFAULT_ROUTING.get(key, DEFAULT_ROUTING["WARNING"])}

    if not company_id:
        return fallback

    try:
        from database.connection import execute_read
        rows = execute_read(
            """SELECT use_email, use_sms, use_push, use_escalation
               FROM severity_routing
               WHERE company_id = %s AND severity = %s
               LIMIT 1""",
            (company_id, key),
        )
        if rows:
            r = rows[0]
            return {
                "email":      bool(r["use_email"]),
                "sms":        bool(r["use_sms"]),
                "push":       bool(r["use_push"]),
                "escalation": bool(r["use_escalation"]),
            }
    except Exception as exc:
        logger.warning("get_routing DB lookup failed (using defaults): %s", exc)

    return fallback

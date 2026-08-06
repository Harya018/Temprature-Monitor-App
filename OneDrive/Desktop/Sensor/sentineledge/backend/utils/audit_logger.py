"""
utils/audit_logger.py — Security-grade audit log writer.

Writes to the audit_log table (Migration 38). Never raises — all failures
are swallowed so audit logging never blocks the calling request.

Differs from activity_logger (admin_activity) in that it captures:
  - IP address of the caller
  - Severity (info / warning / critical)
  - Category (auth / config / data / security / admin)
  - Old and new values for change events

Usage:
    from utils.audit_logger import audit

    audit(
        action="login_success",
        category="auth",
        admin_id=13,
        ip_address="192.168.1.5",
    )

    audit(
        action="threshold_changed",
        category="config",
        admin_id=12,
        company_id=1,
        entity_type="threshold",
        old_value="90.0",
        new_value="85.0",
        severity="warning",
    )
"""

from __future__ import annotations

from database.connection import execute_write
from utils.logger import get_logger

logger = get_logger(__name__)

# Valid categories — used for filtering in the UI
CATEGORIES = ("auth", "config", "data", "security", "admin", "general")
SEVERITIES  = ("info", "warning", "critical")


def audit(
    action: str,
    *,
    category: str = "general",
    admin_id: int | None = None,
    company_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    ip_address: str | None = None,
    severity: str = "info",
) -> None:
    """Insert one row into audit_log. Never raises."""
    if category not in CATEGORIES:
        category = "general"
    if severity not in SEVERITIES:
        severity = "info"
    try:
        execute_write(
            """
            INSERT INTO audit_log
                (admin_id, company_id, category, action,
                 entity_type, entity_id, old_value, new_value,
                 ip_address, severity, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            (admin_id, company_id, category, action,
             entity_type, entity_id, old_value, new_value,
             ip_address, severity),
        )
    except Exception as exc:
        logger.warning("audit() failed (non-fatal): %s", exc)

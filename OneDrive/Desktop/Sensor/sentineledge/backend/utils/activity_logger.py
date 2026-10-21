"""utils/activity_logger.py — centralized activity logging for admin actions."""

from __future__ import annotations

from database.connection import execute_write
from utils.logger import get_logger

logger = get_logger(__name__)


def log_activity(
    admin_id: int,
    action: str,
    entity: str | None = None,
    details: str | None = None,
    company_id: int | None = None,
) -> None:
    """
    Insert one row into admin_activity. Never raises — failures are
    logged and silently swallowed so they never block the caller.
    """
    try:
        if company_id is None and admin_id:     # filed under the admin's company, so it shows up there
            from database.connection import execute_read
            r = execute_read("SELECT company_id, role FROM admins WHERE id = %s", (admin_id,))
            if r and r[0].get("role") != "super_admin":
                company_id = r[0].get("company_id")
        execute_write(
            """
            INSERT INTO admin_activity (admin_id, company_id, action, entity, details, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (admin_id, company_id, action, entity, details),
        )
    except Exception as exc:
        logger.warning("log_activity failed: %s", exc)

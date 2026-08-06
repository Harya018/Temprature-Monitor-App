"""
database/queries/sessions.py — Admin session token persistence.

Stores admin dashboard session tokens in PostgreSQL so they survive
server restarts. Sessions expire after 8 hours.

Functions:
    create_session(token, expires_at)      → None
    get_session(token)                     → dict | None  (updates last_used_at)
    delete_session(token)                  → None
    cleanup_expired_sessions()             → int  (rows deleted)
"""

from datetime import datetime
from typing import Optional

from database.connection import execute_write, execute_read
from utils.logger import get_logger

logger = get_logger(__name__)


def create_session(token: str, expires_at: datetime, admin_id: int = None) -> None:
    """
    Persist a new admin session token.

    Parameters
    ----------
    token      : 64-char hex token issued on login
    expires_at : UTC datetime when this session expires
    admin_id   : FK to admins.id — required so token→admin lookups work
    """
    try:
        execute_write(
            """
            INSERT INTO admin_sessions (token, expires_at, admin_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (token) DO NOTHING
            """,
            (token, expires_at, admin_id),
        )
    except Exception as exc:
        logger.error("create_session failed: %s", exc)


def get_session(token: str) -> Optional[dict]:
    """
    Look up a valid (non-expired) session by token.

    Touches last_used_at so the admin sessions view stays fresh.
    Returns the session dict or None if not found / expired.
    """
    try:
        # Read first — a pure SELECT is safe on any pool connection.
        rows = execute_read(
            """
            SELECT id, token, created_at, expires_at, last_used_at, admin_id
              FROM admin_sessions
             WHERE token = %s
               AND expires_at > NOW()
            """,
            (token,),
        )
        if not rows:
            return None
        # Fire-and-forget touch (execute_write commits).
        try:
            execute_write(
                "UPDATE admin_sessions SET last_used_at = NOW() WHERE token = %s",
                (token,),
            )
        except Exception as touch_exc:
            logger.warning("get_session: last_used_at update failed: %s", touch_exc)
        return rows[0]
    except Exception as exc:
        logger.error("get_session failed: %s", exc)
        return None


def delete_session(token: str) -> None:
    """Delete a session (called on logout)."""
    try:
        execute_write(
            "DELETE FROM admin_sessions WHERE token = %s",
            (token,),
        )
    except Exception as exc:
        logger.error("delete_session failed: %s", exc)


def cleanup_expired_sessions() -> int:
    """
    Delete all expired sessions. Safe to call on every server startup.

    Returns the number of rows deleted.
    """
    try:
        result = execute_write(
            "DELETE FROM admin_sessions WHERE expires_at <= NOW()"
        )
        count = result.rowcount
        if count:
            logger.info("Cleaned up %d expired admin session(s)", count)
        return count
    except Exception as exc:
        logger.error("cleanup_expired_sessions failed: %s", exc)
        return 0

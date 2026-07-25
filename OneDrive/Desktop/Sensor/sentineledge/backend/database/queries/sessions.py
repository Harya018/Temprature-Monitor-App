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


def create_session(token: str, expires_at: datetime) -> None:
    """
    Persist a new admin session token.

    Parameters
    ----------
    token      : 64-char hex token issued on login
    expires_at : UTC datetime when this session expires
    """
    try:
        execute_write(
            """
            INSERT INTO admin_sessions (token, expires_at)
            VALUES (%s, %s)
            ON CONFLICT (token) DO NOTHING
            """,
            (token, expires_at),
        )
    except Exception as exc:
        logger.error("create_session failed: %s", exc)


def get_session(token: str) -> Optional[dict]:
    """
    Look up a valid (non-expired) session by token.

    Also updates last_used_at = NOW() on successful lookup so we can
    track active sessions in the admin dashboard.

    Returns the session dict or None if not found / expired.
    """
    try:
        rows = execute_read(
            """
            UPDATE admin_sessions
            SET    last_used_at = NOW()
            WHERE  token = %s
              AND  expires_at  > NOW()
            RETURNING id, token, created_at, expires_at, last_used_at, admin_id
            """,
            (token,),
        )
        return rows[0] if rows else None
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

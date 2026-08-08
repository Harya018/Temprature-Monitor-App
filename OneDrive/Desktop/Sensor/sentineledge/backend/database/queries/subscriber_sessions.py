"""
database/queries/subscriber_sessions.py — Persistent mobile subscriber sessions.

Replaces the in-memory active_tokens dict in routers/auth.py so tokens
survive server restarts and can be explicitly revoked.

Functions:
    create_sub_session(token, subscriber_id, expires_at)  → None
    get_sub_session(token)                                → dict | None
    delete_sub_session(token)                             → None
    cleanup_expired_sub_sessions()                        → int
"""

from datetime import datetime
from typing import Optional

from database.connection import execute_write, execute_read
from utils.logger import get_logger

logger = get_logger(__name__)


def create_sub_session(token: str, subscriber_id: int, expires_at: datetime) -> None:
    try:
        execute_write(
            """
            INSERT INTO subscriber_sessions (token, subscriber_id, expires_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (token) DO NOTHING
            """,
            (token, subscriber_id, expires_at),
        )
    except Exception as exc:
        logger.error("create_sub_session failed: %s", exc)


def get_sub_session(token: str) -> Optional[dict]:
    """Return a valid (non-expired) session row, or None. Touches last_used_at."""
    try:
        rows = execute_read(
            """
            SELECT ss.id, ss.token, ss.subscriber_id, ss.expires_at,
                   s.name, s.escalation_order
              FROM subscriber_sessions ss
              JOIN subscribers s ON s.id = ss.subscriber_id
             WHERE ss.token = %s
               AND ss.expires_at > NOW()
            """,
            (token,),
        )
        if not rows:
            return None
        try:
            execute_write(
                "UPDATE subscriber_sessions SET last_used_at = NOW() WHERE token = %s",
                (token,),
            )
        except Exception as touch_exc:
            logger.warning("get_sub_session: last_used_at touch failed: %s", touch_exc)
        return rows[0]
    except Exception as exc:
        logger.error("get_sub_session failed: %s", exc)
        return None


def delete_sub_session(token: str) -> None:
    try:
        execute_write("DELETE FROM subscriber_sessions WHERE token = %s", (token,))
    except Exception as exc:
        logger.error("delete_sub_session failed: %s", exc)


def cleanup_expired_sub_sessions() -> int:
    try:
        result = execute_write("DELETE FROM subscriber_sessions WHERE expires_at <= NOW()")
        count = result.rowcount
        if count:
            logger.info("Cleaned up %d expired subscriber session(s)", count)
        return count
    except Exception as exc:
        logger.error("cleanup_expired_sub_sessions failed: %s", exc)
        return 0

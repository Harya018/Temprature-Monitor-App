"""
database/queries/subscribers.py — Subscriber CRUD queries.

PostgreSQL: ? → %s, cursor.lastrowid → RETURNING id.
Removed sqlite3 import (no longer needed; psycopg2.errors used instead).

Security upgrade: subscriber PINs now stored as bcrypt hashes (see utils/security.py).
"""

from datetime import datetime, timezone
from typing import Optional

import psycopg2.errors

from database.connection import execute_write, execute_read
from utils.logger import get_logger
from utils.security import hash_pin as _hash_pin_bcrypt, verify_pin as _verify_pin

logger = get_logger(__name__)


def get_subscribers_ordered() -> list:
    """Return ALL subscribers ordered by escalation_order ASC (active + disabled)."""
    try:
        return execute_read(
            "SELECT * FROM subscribers ORDER BY escalation_order ASC"
        )
    except Exception as exc:
        logger.error("get_subscribers_ordered failed: %s", exc)
        return []


def get_subscriber_by_order(order: int) -> Optional[dict]:
    """Return the subscriber at a specific escalation_order, or None."""
    try:
        rows = execute_read(
            "SELECT * FROM subscribers WHERE escalation_order = %s",
            (order,),
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("get_subscriber_by_order failed: %s", exc)
        return None


def get_subscriber_by_id(subscriber_id: int) -> Optional[dict]:
    """Return a subscriber by primary key, or None."""
    try:
        rows = execute_read(
            "SELECT * FROM subscribers WHERE id = %s",
            (subscriber_id,),
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("get_subscriber_by_id failed: %s", exc)
        return None


def get_subscriber_by_name_and_pin(name: str, pin: str) -> Optional[dict]:
    """
    Find an active subscriber whose name matches (case-insensitive) and whose
    stored bcrypt PIN hash matches the supplied plain-text PIN.

    Fetches by name first, then uses bcrypt comparison (timing-safe).
    Returns the subscriber dict on success, or None if not found / bad PIN.
    """
    try:
        rows = execute_read(
            """
            SELECT * FROM subscribers
            WHERE LOWER(name) = LOWER(%s)
              AND active = 1
            """,
            (name,),
        )
        if not rows:
            return None
        subscriber = rows[0]
        stored_pin = subscriber.get("pin")
        if not stored_pin or not _verify_pin(pin, stored_pin):
            return None
        return subscriber
    except Exception as exc:
        logger.error("get_subscriber_by_name_and_pin failed: %s", exc)
        return None


def add_subscriber(
    name: str, phone: str, email: str, escalation_order: int,
    pin: Optional[str] = None,
) -> int:
    """Insert a new subscriber and return its row id.

    If *pin* is provided it is stored as a bcrypt hash.
    Returns -1 on duplicate escalation_order or any other error.
    """
    try:
        ts = datetime.now(timezone.utc).isoformat()
        hashed_pin = _hash_pin_bcrypt(pin) if pin else None
        cur = execute_write(
            """
            INSERT INTO subscribers
                (name, phone, email, pin, escalation_order, active, created_at)
            VALUES (%s, %s, %s, %s, %s, 1, %s)
            RETURNING id
            """,
            (name, phone, email, hashed_pin, escalation_order, ts),
        )
        return cur.lastrowid or -1
    except psycopg2.errors.UniqueViolation as exc:
        logger.error("add_subscriber UNIQUE conflict: %s", exc)
        return -1
    except Exception as exc:
        logger.error("add_subscriber failed: %s", exc)
        return -1


def set_subscriber_pin(subscriber_id: int, pin: str) -> bool:
    """Bcrypt-hash and store a PIN for an existing subscriber. Returns True on success."""
    try:
        hashed = _hash_pin_bcrypt(pin)
        execute_write(
            "UPDATE subscribers SET pin = %s WHERE id = %s",
            (hashed, subscriber_id),
        )
        return True
    except Exception as exc:
        logger.error("set_subscriber_pin failed: %s", exc)
        return False


def update_push_subscription(subscriber_id: int, push_subscription_json: str) -> bool:
    """Save or update the Web Push subscription JSON for a subscriber."""
    try:
        execute_write(
            "UPDATE subscribers SET push_subscription = %s WHERE id = %s",
            (push_subscription_json, subscriber_id),
        )
        return True
    except Exception as exc:
        logger.error("update_push_subscription failed: %s", exc)
        return False


def delete_subscriber(subscriber_id: int) -> bool:
    """Hard-delete a subscriber by id. Returns True on success."""
    try:
        execute_write("DELETE FROM subscribers WHERE id = %s", (subscriber_id,))
        return True
    except Exception as exc:
        logger.error("delete_subscriber failed: %s", exc)
        return False


def disable_subscriber(subscriber_id: int) -> bool:
    """Set is_active=0 for a subscriber. Returns True on success."""
    try:
        execute_write(
            "UPDATE subscribers SET is_active = 0 WHERE id = %s",
            (subscriber_id,),
        )
        return True
    except Exception as exc:
        logger.error("disable_subscriber failed: %s", exc)
        return False


def enable_subscriber(subscriber_id: int) -> bool:
    """Set is_active=1 for a subscriber. Returns True on success."""
    try:
        execute_write(
            "UPDATE subscribers SET is_active = 1 WHERE id = %s",
            (subscriber_id,),
        )
        return True
    except Exception as exc:
        logger.error("enable_subscriber failed: %s", exc)
        return False


def update_subscriber(subscriber_id: int, fields: dict) -> Optional[dict]:
    """
    Partial update of subscriber profile fields.
    *fields* is a dict of {column_name: value} — only provided keys are updated.
    Returns the updated subscriber row, or None if not found or no fields given.
    """
    if not fields:
        return get_subscriber_by_id(subscriber_id)
    try:
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [subscriber_id]
        execute_write(
            f"UPDATE subscribers SET {set_clause} WHERE id = %s",
            tuple(values),
        )
        return get_subscriber_by_id(subscriber_id)
    except Exception as exc:
        logger.error("update_subscriber failed: %s", exc)
        return None


def get_acks_for_subscriber(subscriber_id: int) -> list:
    """
    Return acknowledgement records for a specific subscriber.
    Joins the alerts table to fetch breach metadata.
    response_time_seconds = (acknowledged_at - timestamp) in seconds.
    """
    try:
        rows = execute_read(
            """
            SELECT
                a.id,
                a.id            AS alert_id,
                a.parameter     AS sensor_id,
                a.severity      AS breach_severity,
                a.value         AS breach_value,
                a.acknowledged_at,
                CAST(
                    EXTRACT(
                        EPOCH FROM (
                            a.acknowledged_at::TIMESTAMPTZ - a.timestamp::TIMESTAMPTZ
                        )
                    ) AS INTEGER
                ) AS response_time_seconds
            FROM alerts a
            WHERE a.acknowledged = 1
              AND a.acknowledged_at IS NOT NULL
              AND a.acknowledged_by = (
                  SELECT name FROM subscribers WHERE id = %s
              )
            ORDER BY a.acknowledged_at DESC
            """,
            (subscriber_id,),
        )
        return rows
    except Exception as exc:
        logger.error("get_acks_for_subscriber failed: %s", exc)
        return []

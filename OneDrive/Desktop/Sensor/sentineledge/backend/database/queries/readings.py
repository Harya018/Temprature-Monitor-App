"""
database/queries/readings.py — Sensor reading queries.

Uses execute_write / execute_read from connection.py.
PostgreSQL: ? → %s, cursor.lastrowid → RETURNING id.
"""

import json
from database.connection import execute_write, execute_read
from utils.logger import get_logger

logger = get_logger(__name__)


def insert_reading(
    temperature: float,
    timestamp: str,
    is_valid: bool = True,
    extra_params: dict = None,
    company_id: int = None,
) -> int:
    """Insert a sensor reading including any extra sensor params. Returns new row id, or -1 on failure."""
    ep = json.dumps(extra_params or {})
    try:
        cur = execute_write(
            "INSERT INTO readings (temperature, timestamp, is_valid, extra_params, company_id) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (temperature, timestamp, int(is_valid), ep, company_id),
        )
        return cur.lastrowid or -1
    except Exception as exc:
        logger.error("insert_reading failed: %s", exc)
        return -1


def get_recent_readings(limit: int = 60, company_id: int | None = None) -> list:
    """Return the most recent `limit` readings, oldest first (one company's
    when company_id is given)."""
    try:
        if company_id is not None:
            rows = execute_read(
                "SELECT * FROM readings WHERE company_id = %s ORDER BY timestamp DESC LIMIT %s",
                (company_id, limit),
            )
        else:
            rows = execute_read(
                "SELECT * FROM readings ORDER BY id DESC LIMIT %s", (limit,)
            )
        return list(reversed(rows))
    except Exception as exc:
        logger.error("get_recent_readings failed: %s", exc)
        return []

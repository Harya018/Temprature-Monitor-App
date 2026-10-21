"""
database/queries/ack_log.py — Acknowledgement log queries.

Provides helpers to fetch acknowledged alerts with computed response_time_seconds.
PostgreSQL: julianday() replaced with EXTRACT(EPOCH FROM ...) arithmetic.
"""

from database.connection import execute_read
from utils.logger import get_logger

logger = get_logger(__name__)


def get_ack_log(limit: int = 100, company_id: int | None = None) -> list:
    """
    Return recent acknowledged alerts with response_time_seconds computed.
    response_time_seconds = (acknowledged_at - timestamp) in seconds.

    PostgreSQL: uses EXTRACT(EPOCH FROM ...) instead of SQLite julianday().
    Both acknowledged_at and timestamp are stored as ISO 8601 TEXT so we cast
    them to TIMESTAMPTZ for the arithmetic.
    """
    try:
        rows = execute_read(
            """
            SELECT
                id,
                parameter,
                value,
                threshold,
                direction,
                severity,
                timestamp,
                acknowledged_by,
                acknowledged_at,
                CAST(
                    EXTRACT(
                        EPOCH FROM (
                            acknowledged_at::TIMESTAMPTZ - timestamp::TIMESTAMPTZ
                        )
                    ) AS INTEGER
                ) AS response_time_seconds
            FROM alerts
            WHERE acknowledged = 1
              AND acknowledged_at IS NOT NULL
              AND acknowledged_by IS NOT NULL
              AND (%s::int IS NULL OR company_id = %s::int)
            ORDER BY acknowledged_at DESC
            LIMIT %s
            """,
            (company_id, company_id, limit),
        )
        return rows
    except Exception as exc:
        logger.error("get_ack_log failed: %s", exc)
        return []

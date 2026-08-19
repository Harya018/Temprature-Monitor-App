"""
database/queries/alerts.py — Alert CRUD queries.

PostgreSQL: ? → %s, cursor.lastrowid → RETURNING id.
SQLite date functions replaced with PostgreSQL equivalents:
  datetime('now', '-1 hour') → NOW() - INTERVAL '1 hour'
"""

from datetime import datetime, timezone
from typing import Optional

from database.connection import execute_write, execute_read, get_db_pool
from utils.logger import get_logger
import psycopg2.extras

logger = get_logger(__name__)


def _default_company_id() -> Optional[int]:
    """Return the id of the first company (any status), or None if no companies exist."""
    try:
        rows = execute_read("SELECT id FROM companies ORDER BY id LIMIT 1")
        return rows[0]["id"] if rows else None
    except Exception:
        return None


def insert_alert(
    parameter: str,
    value: float,
    threshold: float,
    direction: str,
    cooldown_until: str,
    severity: str = "WARNING",
    company_id: Optional[int] = None,
) -> int:
    """Insert a new alert and return its row id."""
    try:
        if company_id is None:
            company_id = _default_company_id()
        ts = datetime.now(timezone.utc).isoformat()
        cur = execute_write(
            """
            INSERT INTO alerts
                (parameter, value, threshold, direction, severity, timestamp,
                 acknowledged, escalation_level, max_escalated, cooldown_until,
                 company_id)
            VALUES (%s, %s, %s, %s, %s, %s, 0, 1, 0, %s, %s)
            RETURNING id
            """,
            (parameter, value, threshold, direction, severity, ts, cooldown_until,
             company_id),
        )
        return cur.lastrowid or -1
    except Exception as exc:
        logger.error("insert_alert failed: %s", exc)
        return -1


def get_alert(alert_id: int, company_id: Optional[int] = None) -> Optional[dict]:
    """Return a single alert by id, scoped to company_id when provided."""
    try:
        if company_id is not None:
            rows = execute_read(
                "SELECT * FROM alerts WHERE id = %s AND company_id = %s",
                (alert_id, company_id),
            )
        else:
            rows = execute_read("SELECT * FROM alerts WHERE id = %s", (alert_id,))
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("get_alert failed: %s", exc)
        return None


def get_unacknowledged_alerts() -> list:
    """Return all alerts that have not been acknowledged yet."""
    try:
        return execute_read(
            "SELECT * FROM alerts WHERE acknowledged = 0 ORDER BY id ASC"
        )
    except Exception as exc:
        logger.error("get_unacknowledged_alerts failed: %s", exc)
        return []


def acknowledge_alert(alert_id: int, acknowledged_by: str) -> bool:
    """Mark an alert as acknowledged. Returns True on success."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        execute_write(
            """
            UPDATE alerts
            SET acknowledged = 1, acknowledged_by = %s, acknowledged_at = %s
            WHERE id = %s
            """,
            (acknowledged_by, ts, alert_id),
        )
        return True
    except Exception as exc:
        logger.error("acknowledge_alert failed: %s", exc)
        return False


def update_escalation_level(alert_id: int, level: int) -> bool:
    """Update the current escalation level of an alert."""
    try:
        execute_write(
            "UPDATE alerts SET escalation_level = %s WHERE id = %s",
            (level, alert_id),
        )
        return True
    except Exception as exc:
        logger.error("update_escalation_level failed: %s", exc)
        return False


def set_max_escalated(alert_id: int) -> bool:
    """Mark that maximum escalation has been reached for an alert."""
    try:
        execute_write(
            "UPDATE alerts SET max_escalated = 1 WHERE id = %s", (alert_id,)
        )
        return True
    except Exception as exc:
        logger.error("set_max_escalated failed: %s", exc)
        return False


def get_recent_alerts(limit: int = 50, offset: int = 0, company_id: Optional[int] = None) -> list:
    """Return the most recent alerts, scoped to company_id when provided."""
    try:
        if company_id is not None:
            return execute_read(
                "SELECT * FROM alerts WHERE company_id = %s ORDER BY id DESC LIMIT %s OFFSET %s",
                (company_id, limit, offset),
            )
        return execute_read(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset)
        )
    except Exception as exc:
        logger.error("get_recent_alerts failed: %s", exc)
        return []


def get_alerts_today_count() -> int:
    """Return the number of alerts created today (UTC)."""
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        rows = execute_read(
            "SELECT COUNT(*) as cnt FROM alerts WHERE timestamp >= %s", (today,)
        )
        return rows[0]["cnt"] if rows else 0
    except Exception as exc:
        logger.error("get_alerts_today_count failed: %s", exc)
        return 0


def delete_alerts_by_period(period: str, company_id: Optional[int] = None) -> int:
    """
    Delete alerts (and their delivery_receipts) by time period.

    period: "1h" | "24h" | "7d" | "30d" | "all"
    company_id: when provided, only deletes alerts belonging to that company.
    Returns the number of alert rows deleted.
    """
    PERIOD_MAP = {
        "1h":  "NOW() - INTERVAL '1 hour'",
        "24h": "NOW() - INTERVAL '1 day'",
        "7d":  "NOW() - INTERVAL '7 days'",
        "30d": "NOW() - INTERVAL '30 days'",
    }

    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            company_clause = "AND company_id = %s" if company_id is not None else ""
            company_params = (company_id,) if company_id is not None else ()

            if period == "all":
                cur.execute(
                    f"SELECT COUNT(*) as cnt FROM alerts WHERE 1=1 {company_clause}",
                    company_params,
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    f"DELETE FROM delivery_receipts WHERE alert_id IN "
                    f"(SELECT id FROM alerts WHERE 1=1 {company_clause})",
                    company_params,
                )
                cur.execute(
                    f"DELETE FROM alerts WHERE 1=1 {company_clause}",
                    company_params,
                )
                conn.commit()
                return total
            else:
                cutoff_expr = PERIOD_MAP.get(period)
                if not cutoff_expr:
                    logger.warning("delete_alerts_by_period: unknown period %s", period)
                    return 0

                # SECURITY: cutoff_expr is from the hardcoded PERIOD_MAP, never raw user input.
                cur.execute(
                    f"SELECT id FROM alerts WHERE timestamp::TIMESTAMPTZ < {cutoff_expr} {company_clause}",
                    company_params,
                )
                ids = [row["id"] for row in cur.fetchall()]

                if not ids:
                    conn.commit()
                    return 0

                cur.execute(
                    "DELETE FROM delivery_receipts WHERE alert_id = ANY(%s)", (ids,)
                )
                cur.execute("DELETE FROM alerts WHERE id = ANY(%s)", (ids,))
                conn.commit()
                return len(ids)

    except Exception as exc:
        conn.rollback()
        logger.error("delete_alerts_by_period(%s) failed: %s", period, exc)
        return 0
    finally:
        pool.putconn(conn)

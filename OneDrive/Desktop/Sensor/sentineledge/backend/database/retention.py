"""
database/retention.py — Automatic data retention cleanup for SentinelEdge.

Prevents the PostgreSQL database from growing unboundedly by deleting old rows.
Runs daily at 2:00 AM UTC.

Retention policy:
    readings          → kept forever (set READINGS_RETENTION_DAYS to a number to enable)
    escalation_log    → 90 days
    delivery_receipts → 90 days

Alerts and config_changes are kept forever (audit trail).

PostgreSQL: datetime() / strftime() replaced with NOW() - INTERVAL '...'.
Database size uses pg_database_size() instead of file stat.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone, timedelta

from utils.logger import get_logger
from utils.time import now_iso

logger = get_logger(__name__)

RETENTION_DAYS_READINGS       = int(os.environ.get("READINGS_RETENTION_DAYS", "0"))   # 0 = never delete
RETENTION_DAYS_ESCALATION_LOG = 90
RETENTION_DAYS_RECEIPTS       = 90


# ── Core cleanup ──────────────────────────────────────────────────────────────

def cleanup_old_readings() -> None:
    """
    Delete readings, escalation_log, and delivery_receipts rows older
    than their respective retention windows.

    Alerts and config_changes are never deleted.
    PostgreSQL: uses NOW() - INTERVAL '...' for date arithmetic.
    """
    from database.connection import execute_write

    if RETENTION_DAYS_READINGS > 0:
        try:
            cur = execute_write(
                "DELETE FROM readings WHERE timestamp::TIMESTAMPTZ < NOW() - INTERVAL %s",
                (f"{RETENTION_DAYS_READINGS} days",),
            )
            logger.info("Retention: deleted %d readings older than %d days.",
                        cur.rowcount, RETENTION_DAYS_READINGS)
        except Exception as exc:
            logger.error("Retention: readings cleanup failed: %s", exc)

    try:
        cur = execute_write(
            "DELETE FROM escalation_log WHERE sent_at::TIMESTAMPTZ < NOW() - INTERVAL %s",
            (f"{RETENTION_DAYS_ESCALATION_LOG} days",),
        )
        logger.info(
            "Retention: deleted %d escalation_log rows older than %d days.",
            cur.rowcount, RETENTION_DAYS_ESCALATION_LOG,
        )
    except Exception as exc:
        logger.error("Retention: escalation_log cleanup failed: %s", exc)

    try:
        cur = execute_write(
            "DELETE FROM delivery_receipts WHERE sent_at::TIMESTAMPTZ < NOW() - INTERVAL %s",
            (f"{RETENTION_DAYS_RECEIPTS} days",),
        )
        logger.info(
            "Retention: deleted %d delivery_receipts rows older than %d days.",
            cur.rowcount, RETENTION_DAYS_RECEIPTS,
        )
    except Exception as exc:
        logger.error("Retention: delivery_receipts cleanup failed: %s", exc)


def get_database_stats() -> dict:
    """
    Return database statistics for the admin panel.

    Returns dict with:
        readings_count, oldest_reading, alerts_count,
        database_size_mb, backups_available
    """
    from database.connection import execute_read
    from database.backup import get_backup_list

    db_name = os.getenv("DATABASE_URL", "sentineledge").split("/")[-1].split("?")[0]

    stats: dict = {
        "readings_count":  0,
        "oldest_reading":  None,
        "alerts_count":    0,
        "database_size_mb": 0.0,
        "backups_available": 0,
    }

    try:
        # Use pg_class statistics for an instant estimate instead of COUNT(*) full scan.
        # reltuples is updated by autovacuum and accurate to ~1-2% on large tables.
        rows = execute_read(
            "SELECT reltuples::bigint AS estimate FROM pg_class WHERE relname = 'readings' AND relnamespace = current_schema()::regnamespace"
        )
        stats["readings_count"] = int(rows[0]["estimate"]) if rows else 0
    except Exception as exc:
        logger.error("stats: readings_count failed: %s", exc)

    try:
        rows = execute_read(
            "SELECT timestamp FROM readings ORDER BY timestamp ASC LIMIT 1"
        )
        stats["oldest_reading"] = rows[0]["timestamp"] if rows else None
    except Exception as exc:
        logger.error("stats: oldest_reading failed: %s", exc)

    try:
        rows = execute_read("SELECT COUNT(*) as cnt FROM alerts")
        stats["alerts_count"] = rows[0]["cnt"] if rows else 0
    except Exception as exc:
        logger.error("stats: alerts_count failed: %s", exc)

    try:
        rows = execute_read(
            "SELECT ROUND(pg_database_size(current_database()) / 1048576.0, 2) AS size_mb"
        )
        stats["database_size_mb"] = float(rows[0]["size_mb"]) if rows else 0.0
    except Exception as exc:
        logger.error("stats: database_size_mb failed: %s", exc)

    try:
        stats["backups_available"] = len(get_backup_list())
    except Exception as exc:
        logger.error("stats: backups_available failed: %s", exc)

    return stats


# ── Scheduler ─────────────────────────────────────────────────────────────────

async def schedule_retention_cleanup() -> None:
    """
    Asyncio background task — runs cleanup_old_readings() daily at 2:00 AM UTC.
    Loops forever; a single failure does not stop the scheduler.
    """
    logger.info("Retention scheduler started.")
    while True:
        now    = datetime.now(timezone.utc)
        target = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        logger.info("Next retention cleanup in %.0f seconds (at 02:00 UTC).", wait)
        await asyncio.sleep(wait)
        logger.info("Running retention cleanup...")
        try:
            cleanup_old_readings()
            logger.info("Retention cleanup completed at %s.", now_iso())
        except Exception as exc:
            logger.error("Retention cleanup failed: %s", exc)

"""
core/anomaly_detector.py — Background anomaly detection for SentinelEdge.

Runs every 5 minutes.  Detects three anomaly types:

  sensor_silence  — no readings for > 30 min (global; logged per active company)
  alert_spike     — alert count in last 1 h is > 3× the prior 1 h AND >= 5 alerts
  rapid_breach    — > 5 alerts in the last 30 min for any company

Results stored in anomaly_log (Migration 35).
Existing open anomalies of the same type are not duplicated.
"""

import asyncio
from datetime import datetime, timezone

from database.connection import execute_read, execute_write
from utils.logger import get_logger

logger = get_logger(__name__)

_CHECK_INTERVAL = 300  # seconds — run every 5 minutes


# ── helpers ───────────────────────────────────────────────────────────────────

def _active_companies() -> list[dict]:
    return execute_read("SELECT id FROM companies WHERE is_active = 1")


def _already_open(company_id: int, anomaly_type: str) -> bool:
    rows = execute_read(
        "SELECT id FROM anomaly_log WHERE company_id = %s AND anomaly_type = %s AND is_resolved = 0",
        (company_id, anomaly_type),
    )
    return bool(rows)


def _log(company_id: int, anomaly_type: str, severity: str, description: str) -> None:
    execute_write(
        """INSERT INTO anomaly_log (company_id, anomaly_type, severity, description)
           VALUES (%s, %s, %s, %s)""",
        (company_id, anomaly_type, severity, description),
    )


# ── check 1: sensor silence ───────────────────────────────────────────────────

def _live_source_companies() -> set:
    """Companies that actually own a live source on this server (live collector / Excel reader)."""
    try:
        from services.sensor_company import SOURCES, get_source_company_id
        return {c for c in (get_source_company_id(s) for s in SOURCES) if c is not None}
    except Exception:
        return set()


def check_sensor_silence() -> None:
    """Flag a company whose OWN live source has gone silent > 30 min. Only companies that own a
    live source are checked, each against its own last reading (a company with no sensor on this
    server can never be 'silent')."""
    for cid in _live_source_companies():
        rows = execute_read("SELECT MAX(timestamp::timestamptz) AS last_reading FROM readings WHERE company_id = %s", (cid,))
        if not rows or rows[0]["last_reading"] is None:
            continue
        last = rows[0]["last_reading"]
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        silence_secs = (datetime.now(timezone.utc) - last).total_seconds()

        if silence_secs < 1800:
            execute_write(
                "UPDATE anomaly_log SET is_resolved = 1, resolved_at = NOW() "
                "WHERE anomaly_type = 'sensor_silence' AND is_resolved = 0 AND company_id = %s", (cid,))
            continue
        if _already_open(cid, "sensor_silence"):
            continue
        silence_min = int(silence_secs / 60)
        _log(cid, "sensor_silence", "high",
             f"No sensor readings for {silence_min} minutes - possible sensor or network failure")
        logger.warning("anomaly: sensor_silence company_id=%s (%d min)", cid, silence_min)

    # a company that no longer owns a live source has nothing left to be silent about
    owners = _live_source_companies()
    if owners:
        execute_write(
            "UPDATE anomaly_log SET is_resolved = 1, resolved_at = NOW() "
            "WHERE anomaly_type = 'sensor_silence' AND is_resolved = 0 AND NOT (company_id = ANY(%s))",
            (sorted(owners),))


# ── check 2: alert spike ──────────────────────────────────────────────────────

def check_alert_spike() -> None:
    """Flag when alerts in the last 1 h are >3× the prior 1 h AND at least 5."""
    rows = execute_read(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE timestamp::timestamptz > NOW() - INTERVAL '1 hour'
            ) AS recent,
            COUNT(*) FILTER (
                WHERE timestamp::timestamptz BETWEEN NOW() - INTERVAL '2 hours'
                                              AND   NOW() - INTERVAL '1 hour'
            ) AS prev
        FROM alerts
        WHERE timestamp::timestamptz > NOW() - INTERVAL '2 hours'
          AND node_alert_id IS NULL
        """
    )
    if not rows:
        return

    recent = int(rows[0]["recent"] or 0)
    prev   = int(rows[0]["prev"]   or 0)

    if recent < 5 or prev == 0 or recent < prev * 3:
        return

    ratio = round(recent / prev, 1)
    for co in _active_companies():
        cid = co["id"]
        if _already_open(cid, "alert_spike"):
            continue
        _log(
            cid,
            "alert_spike",
            "critical",
            f"Alert spike: {recent} alerts in last hour vs {prev} in prior hour ({ratio}× increase)",
        )
        logger.warning(
            "anomaly: alert_spike company_id=%s recent=%d prev=%d ratio=%.1f",
            cid, recent, prev, ratio,
        )


# ── check 3: rapid breach ─────────────────────────────────────────────────────

def check_rapid_breach() -> None:
    """Flag per-company when more than 5 alerts fire in any 30-minute window."""
    rows = execute_read(
        """
        SELECT company_id, COUNT(*) AS cnt
          FROM alerts
         WHERE timestamp::timestamptz > NOW() - INTERVAL '30 minutes'
         GROUP BY company_id
        HAVING COUNT(*) > 5
        """
    )
    for r in rows:
        cid = r["company_id"]
        cnt = int(r["cnt"])
        if cid is None or _already_open(cid, "rapid_breach"):
            continue
        _log(
            cid,
            "rapid_breach",
            "high",
            f"{cnt} alerts in the last 30 minutes — possible rapid breach or sensor runaway",
        )
        logger.warning("anomaly: rapid_breach company_id=%s count=%d", cid, cnt)


# ── background loop ───────────────────────────────────────────────────────────

async def run_anomaly_detection() -> None:
    logger.info("Anomaly detection started (interval=%ds)", _CHECK_INTERVAL)
    while True:
        try:
            check_sensor_silence()
            check_alert_spike()
            check_rapid_breach()
        except Exception as exc:
            logger.error("Anomaly detection error: %s", exc)
        await asyncio.sleep(_CHECK_INTERVAL)

"""
services/node_rollup.py — hourly summaries a node reports to the hub (node role only).

Super Admin never sees raw readings from a company's server. Instead, once an hour has
finished, the node sends one small item per hour: for every parameter the number of
samples and the min / max / average. Hours are 'YYYY-MM-DDTHH' in UTC (readings are
stored as ISO UTC text). Progress is kept in app_settings so a restart neither skips
nor repeats hours, and the hub upserts, so a repeat would be harmless anyway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_KEY = "rollup_last_hour"
MAX_BACKFILL_HOURS = 24 * 366      # first run reports up to a year of existing history
MAX_HOURS_PER_RUN  = 24 * 14       # per run, so a long history is caught up in a few runs
_FMT = "%Y-%m-%dT%H"

_SQL = """
SELECT LEFT(timestamp, 13) AS hour, 'temperature' AS parameter,
       COUNT(*) AS samples, MIN(temperature) AS mn, MAX(temperature) AS mx, AVG(temperature) AS av
  FROM readings
 WHERE company_id = %(cid)s AND is_valid = 1 AND timestamp >= %(lo)s AND timestamp < %(hi)s
 GROUP BY 1
UNION ALL
SELECT LEFT(r.timestamp, 13), e.key, COUNT(*), MIN(e.value::float), MAX(e.value::float), AVG(e.value::float)
  FROM readings r, jsonb_each_text(r.extra_params) e
 WHERE r.company_id = %(cid)s AND r.is_valid = 1 AND r.timestamp >= %(lo)s AND r.timestamp < %(hi)s
   AND e.value ~ '^-?[0-9]+(\\.[0-9]+)?$'
 GROUP BY 1, 2
ORDER BY 1
"""


def _get() -> Optional[str]:
    from database.connection import execute_read
    r = execute_read("SELECT value FROM app_settings WHERE key = %s", (_KEY,))
    return r[0]["value"] if r else None


def _set(value: str) -> None:
    from database.connection import execute_write
    execute_write(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()", (_KEY, value))


def run_once(company_id: int, now: Optional[datetime] = None) -> int:
    """Queue the summaries of every finished hour not yet reported. Returns hours queued."""
    from database.connection import execute_read
    from services import outbox

    now = now or datetime.now(timezone.utc)
    current = now.replace(minute=0, second=0, microsecond=0)
    last = _get()
    if last:
        start = datetime.strptime(last, _FMT).replace(tzinfo=timezone.utc) + timedelta(hours=1)
    else:
        first = execute_read("SELECT MIN(timestamp) AS t FROM readings WHERE company_id = %s", (company_id,))
        t0 = first[0]["t"] if first and first[0]["t"] else None
        start = (datetime.fromisoformat(t0).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
                 if t0 else current)
    start = max(start, current - timedelta(hours=MAX_BACKFILL_HOURS))
    end = min(current, start + timedelta(hours=MAX_HOURS_PER_RUN))
    if start >= end:
        return 0

    rows = execute_read(_SQL, {"cid": company_id, "lo": start.strftime("%Y-%m-%dT%H"), "hi": end.strftime("%Y-%m-%dT%H")})
    by_hour: dict = {}
    for r in rows:
        by_hour.setdefault(r["hour"], []).append(
            {"parameter": r["parameter"], "samples": int(r["samples"]),
             "min": r["mn"], "max": r["mx"], "avg": r["av"]})
    for hour in sorted(by_hour):
        outbox.enqueue("hourly_summary", {"hour": hour, "parameters": by_hour[hour]})
    _set((end - timedelta(hours=1)).strftime(_FMT))
    return len(by_hour)

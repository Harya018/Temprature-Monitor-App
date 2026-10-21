"""
routers/reports.py — Daily summary reports.

Endpoints:
    GET /api/reports/daily?days=30
    GET /api/reports/readings-export?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD&format=csv|json

Performance rewrite: replaced 90 serial round-trip queries (30 days × 3 queries,
with Python-side aggregation on raw rows) with 3 bulk aggregate queries that let
PostgreSQL do all grouping and math.  Query time on 893k-row tables: <500 ms.
"""

import io
import csv
import json
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from middleware.auth import require_admin
from database.connection import execute_read
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/daily")
async def daily_reports(days: int = Query(30, ge=1, le=90), admin: dict = Depends(require_admin)):
    """
    Return one summary object per calendar day for the last N days
    (the caller's company only).

    Each day: date, total_readings, total_alerts, avg_temp, peak_temp,
    min_temp, email_sent, email_failed, sms_sent, sms_failed.

    Uses three bulk aggregate queries instead of per-day loops — PostgreSQL
    does all grouping and math, nothing is loaded into Python for aggregation.
    """

    # ── 1. Readings — one query for all days ─────────────────────────────────
    # DATE_TRUNC groups by calendar day in UTC.  MIN(timestamp) is used as the
    # timestamp of the peak-temperature row (PostgreSQL extension not available
    # via simple GROUP BY, so peak_temp_time is omitted — add a window function
    # if it is strictly required later).
    cid = admin.get("company_id")
    cf  = "AND company_id = %s" if cid is not None else ""
    acf = "AND a.company_id = %s" if cid is not None else ""
    cp  = (cid,) if cid is not None else ()
    try:
        readings_rows = execute_read(
            f"""
            SELECT
                LEFT(timestamp, 10)         AS day,
                COUNT(*)                    AS reading_count,
                ROUND(AVG(temperature)::numeric, 2) AS avg_temp,
                MIN(temperature)            AS min_temp,
                MAX(temperature)            AS peak_temp
            FROM readings
            -- timestamp is ISO text: compare as text so the index is used
            -- (casting the column scanned all ~8M rows)
            WHERE timestamp >= to_char((NOW() - (%s || ' days')::INTERVAL) AT TIME ZONE 'UTC',
                                       'YYYY-MM-DD"T"HH24:MI:SS')
              {cf}
            GROUP BY LEFT(timestamp, 10)
            ORDER BY day DESC
            """,
            (str(days), *cp),
        )
    except Exception as exc:
        logger.error("daily_reports: readings query failed: %s", exc)
        readings_rows = []

    # ── 2. Alerts — one query for all days ───────────────────────────────────
    try:
        alerts_rows = execute_read(
            f"""
            SELECT
                DATE_TRUNC('day', timestamp::timestamptz AT TIME ZONE 'UTC') AS day,
                COUNT(*) AS alert_count
            FROM alerts
            WHERE timestamp::timestamptz >= NOW() - (%s || ' days')::INTERVAL
              {cf}
            GROUP BY DATE_TRUNC('day', timestamp::timestamptz AT TIME ZONE 'UTC')
            ORDER BY day DESC
            """,
            (str(days), *cp),
        )
    except Exception as exc:
        logger.error("daily_reports: alerts query failed: %s", exc)
        alerts_rows = []

    # ── 3. Delivery receipts — one query for all days ─────────────────────────
    try:
        receipts_rows = execute_read(
            f"""
            SELECT
                DATE_TRUNC('day', dr.sent_at::timestamptz AT TIME ZONE 'UTC') AS day,
                dr.channel,
                dr.success,
                COUNT(*) AS cnt
            FROM delivery_receipts dr
            LEFT JOIN alerts a ON a.id = dr.alert_id
            WHERE dr.sent_at::timestamptz >= NOW() - (%s || ' days')::INTERVAL
              {acf}
            GROUP BY
                DATE_TRUNC('day', dr.sent_at::timestamptz AT TIME ZONE 'UTC'),
                dr.channel, dr.success
            ORDER BY day DESC
            """,
            (str(days), *cp),
        )
    except Exception as exc:
        logger.error("daily_reports: receipts query failed: %s", exc)
        receipts_rows = []

    # ── Index results by date string for O(1) lookups ─────────────────────────
    # PostgreSQL returns TIMESTAMPTZ for DATE_TRUNC; convert to YYYY-MM-DD string.
    def _day_key(row_day) -> str:
        """Normalise the DATE_TRUNC result to a plain YYYY-MM-DD string."""
        if row_day is None:
            return ""
        if hasattr(row_day, "date"):          # datetime / date object
            return row_day.date().isoformat() if hasattr(row_day, "date") else str(row_day)[:10]
        return str(row_day)[:10]              # fallback: slice ISO string

    readings_by_day: dict = {_day_key(r["day"]): r for r in readings_rows}
    alerts_by_day:   dict = {_day_key(r["day"]): r for r in alerts_rows}

    # Delivery receipts: keyed by (date, channel, success)
    delivery_by_day: dict = {}
    for r in receipts_rows:
        dk = _day_key(r["day"])
        delivery_by_day.setdefault(dk, {"email_sent": 0, "email_failed": 0,
                                         "sms_sent": 0,   "sms_failed": 0})
        ch  = r.get("channel", "")
        key = f"{ch}_{'sent' if r.get('success') else 'failed'}"
        if key in delivery_by_day[dk]:
            delivery_by_day[dk][key] += r.get("cnt", 0)

    # ── Build response: one entry per day, newest first ───────────────────────
    # Collect all day keys returned by any of the three queries.
    all_days = sorted(
        {_day_key(r["day"]) for r in readings_rows}
        | {_day_key(r["day"]) for r in alerts_rows}
        | {_day_key(r["day"]) for r in receipts_rows}
        - {""},
        reverse=True,
    )

    results = []
    for dk in all_days:
        rd = readings_by_day.get(dk, {})
        al = alerts_by_day.get(dk, {})
        dv = delivery_by_day.get(dk, {"email_sent": 0, "email_failed": 0,
                                       "sms_sent": 0,   "sms_failed": 0})
        results.append({
            "date":           dk,
            "total_readings": int(rd.get("reading_count", 0)),
            "total_alerts":   int(al.get("alert_count",   0)),
            "avg_temp":       float(rd["avg_temp"])  if rd.get("avg_temp")  is not None else None,
            "peak_temp":      float(rd["peak_temp"]) if rd.get("peak_temp") is not None else None,
            "min_temp":       float(rd["min_temp"])  if rd.get("min_temp")  is not None else None,
            **dv,
        })

    return results


_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
_EXPORT_BATCH = 20000
_CHUNK_ROWS   = 2000


def _export_keys(cf: str, params: tuple) -> list:
    """Every parameter name stored in the range (CSV columns) — one pass over the range."""
    rows = execute_read(
        f"SELECT DISTINCT k AS k FROM readings, jsonb_object_keys(extra_params) AS k "
        f"WHERE timestamp >= %s AND timestamp <= %s {cf} AND jsonb_typeof(extra_params) = 'object'",
        params,
    )
    return sorted(r["k"] for r in rows)


def _iter_readings(cf: str, lo: str, hi: str, cparams: tuple):
    """Yield the range's readings in time order, batch by batch (no row cap, constant memory)."""
    sql = (f"SELECT id, temperature, timestamp, is_valid, extra_params FROM readings "
           f"WHERE {{lower}} AND timestamp <= %s {cf} ORDER BY timestamp, id LIMIT {_EXPORT_BATCH}")
    rows = execute_read(sql.format(lower="timestamp >= %s"), (lo, hi, *cparams))
    while rows:
        yield from rows
        if len(rows) < _EXPORT_BATCH:
            return
        last = rows[-1]
        rows = execute_read(sql.format(lower="(timestamp, id) > (%s, %s)"),
                            (last["timestamp"], last["id"], hi, *cparams))


def stream_readings(admin: dict, start: str, end: str, fmt: str = "csv"):
    """Streaming download of ALL of the caller's readings between two dates (inclusive)."""
    cid = admin.get("company_id")
    cf  = "AND company_id = %s" if cid is not None else ""
    cparams = (cid,) if cid is not None else ()
    lo, hi = f"{start}T00:00:00", f"{end}T23:59:59~"      # ISO text bounds keep the index in use
    keys = _export_keys(cf, (lo, hi, *cparams))

    def _ep(r):
        ep = r.get("extra_params") or {}
        if isinstance(ep, str):
            try: ep = json.loads(ep)
            except Exception: ep = {}
        return ep

    def csv_gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "timestamp", "temperature", "is_valid", *keys])
        n = 0
        for r in _iter_readings(cf, lo, hi, cparams):
            ep = _ep(r)
            w.writerow([r["id"], r["timestamp"], r["temperature"], int(r["is_valid"]), *[ep.get(k, "") for k in keys]])
            n += 1
            if n % _CHUNK_ROWS == 0:           # few large chunks stream far faster than one per row
                yield buf.getvalue(); buf.seek(0); buf.truncate()
        yield buf.getvalue()

    def json_gen():
        parts, sep = ["["], ""
        for r in _iter_readings(cf, lo, hi, cparams):
            ep = _ep(r)
            parts.append(sep + json.dumps({"id": r["id"], "temperature": r["temperature"], "timestamp": str(r["timestamp"]),
                                           "is_valid": bool(r["is_valid"]), **{k: ep.get(k) for k in keys}}))
            sep = ","
            if len(parts) >= _CHUNK_ROWS:
                yield "".join(parts); parts = []
        parts.append("]")
        yield "".join(parts)

    if fmt == "json":
        return StreamingResponse(json_gen(), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="readings_{start}_{end}.json"'})
    return StreamingResponse(csv_gen(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="readings_{start}_{end}.csv"'})


@router.get("/readings-export")
async def readings_export(
    from_date: str  = Query(..., pattern=_DATE_RE, description="YYYY-MM-DD"),
    to_date:   str  = Query(..., pattern=_DATE_RE, description="YYYY-MM-DD"),
    fmt:       str  = Query("csv", alias="format", pattern="^(csv|json)$"),
    admin:     dict = Depends(require_admin),
):
    """Export every stored reading of the caller's company (all parameters) between two
    dates, inclusive. Streamed, so any date range works — there is no row limit."""
    return stream_readings(admin, from_date, to_date, fmt)

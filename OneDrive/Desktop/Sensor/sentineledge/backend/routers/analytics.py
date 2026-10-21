"""
routers/analytics.py — Analytics and CSV import endpoints for SentinelEdge.

Prefix : /api/analytics
Auth   : require_admin — returns {"admin_id": int, "company_id": int|None}
         All live-data queries are scoped to the authenticated admin's company_id.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse

from database.connection import execute_read, execute_write, get_db_pool
from middleware.auth import require_admin
from utils.activity_logger import log_activity
from utils.logger import get_logger

logger = get_logger(__name__)

from services.sensor_company import require_plant_owner
router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# ── In-memory analytics cache (TTL = 60 seconds) ──────────────────────────────
_ANALYTICS_CACHE_TTL = 60  # seconds
_cache_lock          = threading.Lock()
_live_trend_cache:  dict[tuple, tuple] = {}
_daily_avg_cache:   dict[tuple, tuple] = {}
_hourly_avg_cache:  dict[tuple, tuple] = {}


def _cache_get(store: dict, key: tuple):
    with _cache_lock:
        entry = store.get(key)
    if entry is None:
        return None
    result, ts = entry
    if time.monotonic() - ts < _ANALYTICS_CACHE_TTL:
        return result
    return None


def _cache_set(store: dict, key: tuple, result) -> None:
    with _cache_lock:
        store[key] = (result, time.monotonic())


def _csv_guard(company_id, source: str) -> str:
    """The imported CSV history has no owner column: it belongs to the company that owns this
    PC's sensor feed. Everyone else is limited to their own live readings."""
    if source == "live" or company_id is None:
        return source
    from services.sensor_company import owns_sensor_feed
    return source if owns_sensor_feed(company_id) else "live"


# ── datetime parsing ──────────────────────────────────────────────────────────

_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
]


def _parse_dt(s: str) -> Optional[datetime]:
    s = s.strip()
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _date_range(from_date: Optional[str], to_date: Optional[str]):
    today = date.today()
    try:
        end = datetime.strptime(to_date, "%Y-%m-%d").date() if to_date else today
    except ValueError:
        end = today
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date() if from_date else end - timedelta(days=7)
    except ValueError:
        start = end - timedelta(days=7)
    return str(start), str(end)


def _col_map(headers: list[str], candidates: list[str]) -> Optional[str]:
    lc = {h.lower() for h in headers}
    for c in candidates:
        if c.lower() in lc:
            for h in headers:
                if h.lower() == c.lower():
                    return h
    return None


def _batch_insert_csv(rows: list[tuple]) -> int:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO csv_sensor_history
                    (recorded_at, date_only, hour, week_number, temperature, pressure, ph)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        conn.commit()
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── shared query helpers ──────────────────────────────────────────────────────

import re as _re

def _safe_param(name: str) -> bool:
    return bool(_re.match(r'^[a-zA-Z0-9_ ]{1,100}$', name))

def _live_param_expr(parameter: str) -> Optional[str]:
    if parameter == "temperature":
        return "temperature"
    if _safe_param(parameter):
        return f"(extra_params->>'{parameter}')::float"
    return None

def _live_extra_filter(parameter: str) -> str:
    if parameter == "temperature":
        return ""
    return f"AND extra_params ? '{parameter}'"

# readings.timestamp is ISO-8601 TEXT. Comparing it to ISO text bounds lets
# PostgreSQL use the timestamp / (company_id, timestamp) indexes; casting the
# column (timestamp::timestamptz BETWEEN ...) forced full scans of ~8M rows.
# The '~' suffix keeps fractional-second rows at the upper bound.
_TS_RANGE_SQL = (
    "timestamp BETWEEN to_char((%s)::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS') "
    "AND to_char((%s)::timestamptz AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS') || '~'"
)


def _csv_param_col(parameter: str) -> Optional[str]:
    mapping = {"temperature": "temperature", "pressure": "pressure", "ph": "ph"}
    return mapping.get(parameter)


# ── CSV import endpoints ───────────────────────────────────────────────────────

@router.post("/csv/import", dependencies=[Depends(require_plant_owner)])
async def import_csv(file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    raw_headers = list(reader.fieldnames or [])
    headers_lc = [h.strip().lower() for h in raw_headers]

    dt_candidates = [
        "timestamp", "date only", "date_only", "recorded_at",
        "datetime", "date", "time",
    ]
    dt_col = None
    for cand in dt_candidates:
        if cand in headers_lc:
            dt_col = raw_headers[headers_lc.index(cand)]
            break
    if dt_col is None:
        dt_col = next(
            (raw_headers[i] for i, h in enumerate(headers_lc) if "date" in h or "time" in h),
            None,
        )
    if dt_col is None:
        return JSONResponse(
            status_code=422,
            content={"error": "No datetime column found in CSV headers", "headers": raw_headers},
        )

    def _find(candidates):
        for c in candidates:
            if c.lower() in headers_lc:
                return raw_headers[headers_lc.index(c.lower())]
        return None

    temp_col  = _find(["temperature", "temp"])
    press_col = _find(["pressure", "press"])
    ph_col    = _find(["ph", "p_h", "acidity"])
    hour_col  = _find(["hour"])
    week_col  = _find(["week number", "week_number", "weeknumber", "week"])

    imported = 0
    skipped = 0
    errors: list[str] = []
    batch: list[tuple] = []

    for i, row in enumerate(reader):
        row = {k.strip(): v for k, v in row.items()}

        raw_dt = (row.get(dt_col) or "").strip()
        if not raw_dt:
            skipped += 1
            continue

        dt = _parse_dt(raw_dt)
        if dt is None:
            errors.append(f"Row {i + 2}: unparseable datetime '{raw_dt}'")
            skipped += 1
            continue

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        dt_date = dt.date()

        hr_raw = (row.get(hour_col) or "") if hour_col else ""
        hr = int(hr_raw.strip()) if hr_raw.strip().lstrip("-").isdigit() else dt.hour

        wk_raw = (row.get(week_col) or "") if week_col else ""
        wk = int(wk_raw.strip()) if wk_raw.strip().lstrip("-").isdigit() else dt.isocalendar()[1]

        def _float(col):
            if not col:
                return None
            v = (row.get(col) or "").strip()
            if not v:
                return None
            try:
                return float(v)
            except ValueError:
                return None

        temp  = _float(temp_col)
        press = _float(press_col)
        ph    = _float(ph_col)

        batch.append((dt, dt_date, hr, wk, temp, press, ph))

        if len(batch) >= 500:
            try:
                imported += _batch_insert_csv(batch)
                batch.clear()
            except Exception as exc:
                errors.append(f"Batch insert error: {str(exc)[:120]}")
                skipped += len(batch)
                batch.clear()

    if batch:
        try:
            imported += _batch_insert_csv(batch)
        except Exception as exc:
            errors.append(f"Final batch error: {str(exc)[:120]}")
            skipped += len(batch)

    log_activity(0, "csv_imported", "csv_sensor_history", json.dumps({"row_count": imported}))
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


@router.get("/csv/status", dependencies=[Depends(require_plant_owner)])
def csv_status():
    rows = execute_read(
        """
        SELECT
            COUNT(*)                              AS row_count,
            MIN(recorded_at)::text                AS earliest_date,
            MAX(recorded_at)::text                AS latest_date,
            MAX(imported_at)::text                AS last_imported_at
        FROM csv_sensor_history
        """
    )
    r = rows[0] if rows else {}
    return {
        "row_count":        r.get("row_count", 0),
        "earliest_date":    r.get("earliest_date"),
        "latest_date":      r.get("latest_date"),
        "last_imported_at": r.get("last_imported_at"),
    }


@router.delete("/csv/clear", dependencies=[Depends(require_plant_owner)])
def csv_clear():
    execute_write("TRUNCATE csv_sensor_history RESTART IDENTITY")
    log_activity(0, "csv_cleared", "csv_sensor_history", None)
    return {"cleared": True}


# ── Chart 1 — Live trend ───────────────────────────────────────────────────────

@router.get("/charts/live-trend")
def chart_live_trend(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    limit: int = Query(60, ge=1, le=500),
    source: str = Query("live"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    _cache_key = (company_id, parameter, limit, source, from_date, to_date)
    cached = _cache_get(_live_trend_cache, _cache_key)
    if cached is not None:
        return cached
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)

    rows: list[dict] = []

    if source in ("live", "both") and live_col:
        cid_filter = "AND company_id = %s" if company_id else ""
        cid_params = (company_id,) if company_id else ()
        rows += execute_read(
            f"""
            SELECT ({live_col})::float AS value,
                   timestamp::timestamptz AS recorded_at
            FROM readings
            WHERE is_valid = 1
              {live_filter}
              {cid_filter}
              AND {_TS_RANGE_SQL}
            ORDER BY id DESC
            LIMIT %s
            """,
            (*cid_params, ts_start, ts_end, limit),
        )

    if source in ("csv", "both") and csv_col:
        rows += execute_read(
            f"""
            SELECT {csv_col}::float AS value,
                   recorded_at
            FROM csv_sensor_history
            WHERE {csv_col} IS NOT NULL
              AND recorded_at BETWEEN %s AND %s
            ORDER BY recorded_at DESC
            LIMIT %s
            """,
            (ts_start, ts_end, limit),
        )

    if source == "both":
        rows.sort(key=lambda r: str(r.get("recorded_at", "")), reverse=True)
        rows = rows[:limit]

    unit = "deg C" if parameter == "temperature" else "hPa" if parameter == "pressure" else ""
    result = [
        {
            "timestamp": str(r.get("recorded_at", "")),
            "value":     r.get("value"),
            "unit":      unit,
        }
        for r in reversed(rows)
    ]
    _cache_set(_live_trend_cache, _cache_key, result)
    return result


# ── Chart 2 — Daily average ────────────────────────────────────────────────────

@router.get("/charts/daily-avg")
def chart_daily_avg(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    source: str = Query("live"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    _cache_key = (company_id, parameter, source, from_date, to_date)
    cached = _cache_get(_daily_avg_cache, _cache_key)
    if cached is not None:
        return cached
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)
    rows: list[dict] = []

    if source in ("live", "both") and live_col:
        cid_filter = "AND company_id = %s" if company_id else ""
        cid_params = (company_id,) if company_id else ()
        rows += execute_read(
            f"""
            SELECT DATE(timestamp::timestamptz)::text               AS date,
                   ROUND(AVG(({live_col}))::numeric, 2)             AS avg,
                   ROUND(MIN(({live_col}))::numeric, 2)             AS min,
                   ROUND(MAX(({live_col}))::numeric, 2)             AS max,
                   COUNT(*)                                         AS reading_count
            FROM readings
            WHERE is_valid = 1
              {live_filter}
              {cid_filter}
              AND {_TS_RANGE_SQL}
            GROUP BY DATE(timestamp::timestamptz)
            ORDER BY DATE(timestamp::timestamptz)
            """,
            (*cid_params, ts_start, ts_end),
        )

    if source in ("csv", "both") and csv_col:
        rows += execute_read(
            f"""
            SELECT date_only::text                                   AS date,
                   ROUND(AVG({csv_col})::numeric, 2)                AS avg,
                   ROUND(MIN({csv_col})::numeric, 2)                AS min,
                   ROUND(MAX({csv_col})::numeric, 2)                AS max,
                   COUNT(*)                                         AS reading_count
            FROM csv_sensor_history
            WHERE {csv_col} IS NOT NULL
              AND recorded_at BETWEEN %s AND %s
            GROUP BY date_only
            ORDER BY date_only
            """,
            (ts_start, ts_end),
        )

    if source == "both":
        merged: dict[str, dict] = {}
        for r in rows:
            d = str(r.get("date", ""))
            if d not in merged:
                merged[d] = {**r, "_count": 1}
            else:
                m = merged[d]
                m["avg"]           = round((m["avg"] * m["_count"] + r["avg"]) / (m["_count"] + 1), 2)
                m["min"]           = min(m["min"], r["min"])
                m["max"]           = max(m["max"], r["max"])
                m["reading_count"] = m["reading_count"] + r["reading_count"]
                m["_count"]       += 1
        result = [{"date": d, "avg": v["avg"], "min": v["min"], "max": v["max"], "reading_count": v["reading_count"]}
                  for d, v in sorted(merged.items())]
    else:
        result = rows
    _cache_set(_daily_avg_cache, _cache_key, result)
    return result


# ── Chart 3 — Hourly average ───────────────────────────────────────────────────

@router.get("/charts/hourly-avg")
def chart_hourly_avg(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    source: str = Query("live"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    _cache_key = (company_id, parameter, source, from_date, to_date)
    cached = _cache_get(_hourly_avg_cache, _cache_key)
    if cached is not None:
        return cached
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)
    rows: list[dict] = []

    if source in ("live", "both") and live_col:
        cid_filter = "AND company_id = %s" if company_id else ""
        cid_params = (company_id,) if company_id else ()
        rows += execute_read(
            f"""
            SELECT EXTRACT(HOUR FROM timestamp::timestamptz)::int    AS hour,
                   ROUND(AVG(({live_col}))::numeric, 2)             AS avg,
                   COUNT(*)                                         AS reading_count
            FROM readings
            WHERE is_valid = 1
              {live_filter}
              {cid_filter}
              AND {_TS_RANGE_SQL}
            GROUP BY EXTRACT(HOUR FROM timestamp::timestamptz)
            ORDER BY hour
            """,
            (*cid_params, ts_start, ts_end),
        )

    if source in ("csv", "both") and csv_col:
        rows += execute_read(
            f"""
            SELECT hour,
                   ROUND(AVG({csv_col})::numeric, 2) AS avg,
                   COUNT(*)                          AS reading_count
            FROM csv_sensor_history
            WHERE {csv_col} IS NOT NULL
              AND recorded_at BETWEEN %s AND %s
            GROUP BY hour
            ORDER BY hour
            """,
            (ts_start, ts_end),
        )

    if source == "both":
        merged: dict[int, dict] = {}
        for r in rows:
            h = int(r.get("hour", 0))
            if h not in merged:
                merged[h] = {**r, "_n": 1}
            else:
                m = merged[h]
                m["avg"]           = round((m["avg"] * m["_n"] + r["avg"]) / (m["_n"] + 1), 2)
                m["reading_count"] = m["reading_count"] + r["reading_count"]
                m["_n"]           += 1
        result = [{"hour": h, "avg": v["avg"], "reading_count": v["reading_count"]}
                  for h, v in sorted(merged.items())]
    else:
        result = rows
    _cache_set(_hourly_avg_cache, _cache_key, result)
    return result


# ── Chart 4 — Weekly average ───────────────────────────────────────────────────

@router.get("/charts/weekly-avg")
def chart_weekly_avg(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    source: str = Query("live"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)
    rows: list[dict] = []

    if source in ("live", "both") and live_col:
        cid_filter = "AND company_id = %s" if company_id else ""
        cid_params = (company_id,) if company_id else ()
        rows += execute_read(
            f"""
            SELECT EXTRACT(WEEK FROM timestamp::timestamptz)::int    AS week_number,
                   ROUND(AVG(({live_col}))::numeric, 2)             AS avg,
                   ROUND(MIN(({live_col}))::numeric, 2)             AS min,
                   ROUND(MAX(({live_col}))::numeric, 2)             AS max
            FROM readings
            WHERE is_valid = 1
              {live_filter}
              {cid_filter}
              AND {_TS_RANGE_SQL}
            GROUP BY EXTRACT(WEEK FROM timestamp::timestamptz)
            ORDER BY week_number
            """,
            (*cid_params, ts_start, ts_end),
        )

    if source in ("csv", "both") and csv_col:
        rows += execute_read(
            f"""
            SELECT week_number,
                   ROUND(AVG({csv_col})::numeric, 2) AS avg,
                   ROUND(MIN({csv_col})::numeric, 2) AS min,
                   ROUND(MAX({csv_col})::numeric, 2) AS max
            FROM csv_sensor_history
            WHERE {csv_col} IS NOT NULL
              AND recorded_at BETWEEN %s AND %s
            GROUP BY week_number
            ORDER BY week_number
            """,
            (ts_start, ts_end),
        )

    if source == "both":
        merged: dict[int, dict] = {}
        for r in rows:
            wk = int(r.get("week_number", 0))
            if wk not in merged:
                merged[wk] = {**r, "_n": 1}
            else:
                m = merged[wk]
                m["avg"] = round((m["avg"] * m["_n"] + r["avg"]) / (m["_n"] + 1), 2)
                m["min"] = min(m["min"], r["min"])
                m["max"] = max(m["max"], r["max"])
                m["_n"] += 1
        rows = [{"week_number": wk, "avg": v["avg"], "min": v["min"], "max": v["max"]}
                for wk, v in sorted(merged.items())]

    return rows


# ── Chart 5 — Distribution ────────────────────────────────────────────────────

@router.get("/charts/distribution")
def chart_distribution(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    source: str = Query("live"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)

    def _bucket_sql(col: str) -> str:
        return f"""
            CASE
                WHEN {col} < 40  THEN '<40'
                WHEN {col} < 50  THEN '40-50'
                WHEN {col} < 60  THEN '50-60'
                WHEN {col} < 70  THEN '60-70'
                WHEN {col} < 80  THEN '70-80'
                WHEN {col} < 90  THEN '80-90'
                ELSE '>90'
            END
        """

    _bucket_order = {"<40": 0, "40-50": 1, "50-60": 2, "60-70": 3, "70-80": 4, "80-90": 5, ">90": 6}

    bucket_counts: dict[str, int] = {}

    if source in ("live", "both") and live_col:
        cid_filter = "AND company_id = %s" if company_id else ""
        cid_params = (company_id,) if company_id else ()
        for r in execute_read(
            f"""
            SELECT {_bucket_sql(live_col)} AS bucket_label, COUNT(*) AS count
            FROM readings
            WHERE is_valid = 1
              {live_filter}
              {cid_filter}
              AND {_TS_RANGE_SQL}
            GROUP BY bucket_label
            """,
            (*cid_params, ts_start, ts_end),
        ):
            bl = r["bucket_label"]
            bucket_counts[bl] = bucket_counts.get(bl, 0) + int(r["count"])

    if source in ("csv", "both") and csv_col:
        for r in execute_read(
            f"""
            SELECT {_bucket_sql(csv_col)} AS bucket_label, COUNT(*) AS count
            FROM csv_sensor_history
            WHERE {csv_col} IS NOT NULL
              AND recorded_at BETWEEN %s AND %s
            GROUP BY bucket_label
            """,
            (ts_start, ts_end),
        ):
            bl = r["bucket_label"]
            bucket_counts[bl] = bucket_counts.get(bl, 0) + int(r["count"])

    total = sum(bucket_counts.values()) or 1
    unit  = "°C" if parameter == "temperature" else "hPa" if parameter == "pressure" else ""
    labels = {
        "<40": f"<40{unit}", "40-50": f"40-50{unit}", "50-60": f"50-60{unit}",
        "60-70": f"60-70{unit}", "70-80": f"70-80{unit}", "80-90": f"80-90{unit}", ">90": f">90{unit}",
    }

    return [
        {
            "bucket_label": labels.get(k, k),
            "count":        bucket_counts.get(k, 0),
            "percentage":   round(100.0 * bucket_counts.get(k, 0) / total, 1),
        }
        for k in sorted(_bucket_order, key=_bucket_order.get)
        if bucket_counts.get(k, 0) > 0
    ]


# ── Chart 6 — Breach frequency ────────────────────────────────────────────────

@router.get("/charts/breach-frequency")
def chart_breach_frequency(
    admin: dict = Depends(require_admin),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    cid_filter = "AND company_id = %s" if company_id else ""
    cid_params = (company_id,) if company_id else ()

    rows = execute_read(
        f"""
        SELECT
            parameter,
            COUNT(*)                                          AS breach_count,
            COUNT(DISTINCT DATE(timestamp::timestamptz))      AS days_with_breach,
            DATE(timestamp::timestamptz)                      AS day,
            COUNT(*)                                          AS day_count
        FROM alerts
        WHERE timestamp::timestamptz BETWEEN %s AND %s
          {cid_filter}
        GROUP BY parameter, DATE(timestamp::timestamptz)
        ORDER BY parameter, DATE(timestamp::timestamptz)
        """,
        (ts_start, ts_end, *cid_params),
    )

    by_param: dict[str, dict] = {}
    for r in rows:
        p = r["parameter"]
        if p not in by_param:
            by_param[p] = {
                "parameter":       p,
                "breach_count":    0,
                "days_with_breach": 0,
                "worst_day":       None,
                "worst_day_count": 0,
                "days":            [],
            }
        by_param[p]["breach_count"]    += int(r["day_count"])
        by_param[p]["days_with_breach"] += 1
        by_param[p]["days"].append({"date": str(r["day"]), "count": int(r["day_count"])})
        if int(r["day_count"]) > by_param[p]["worst_day_count"]:
            by_param[p]["worst_day"]       = str(r["day"])
            by_param[p]["worst_day_count"] = int(r["day_count"])

    total_days = max((
        (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1
    ), 1)

    return [
        {
            "parameter":        v["parameter"],
            "breach_count":     v["breach_count"],
            "days_with_breach": v["days_with_breach"],
            "avg_per_day":      round(v["breach_count"] / total_days, 2),
            "worst_day":        v["worst_day"],
            "worst_day_count":  v["worst_day_count"],
            "daily_series":     v["days"],
        }
        for v in by_param.values()
    ]


# ── Chart 7 — Alert heatmap ───────────────────────────────────────────────────

@router.get("/charts/alert-heatmap")
def chart_alert_heatmap(
    admin: dict = Depends(require_admin),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    cid_filter = "AND company_id = %s" if company_id else ""
    cid_params = (company_id,) if company_id else ()

    rows = execute_read(
        f"""
        SELECT
            EXTRACT(HOUR FROM timestamp::timestamptz)::int    AS hour,
            ((EXTRACT(DOW FROM timestamp::timestamptz)::int + 6) %% 7) AS day_of_week,
            COUNT(*)                                          AS count
        FROM alerts
        WHERE timestamp::timestamptz BETWEEN %s AND %s
          {cid_filter}
        GROUP BY hour, day_of_week
        ORDER BY hour, day_of_week
        """,
        (ts_start, ts_end, *cid_params),
    )

    return [
        {"hour": int(r["hour"]), "day_of_week": int(r["day_of_week"]), "count": int(r["count"])}
        for r in rows
    ]


# ── Chart 8 — Subscriber response times ──────────────────────────────────────

@router.get("/charts/subscriber-response")
def chart_subscriber_response(
    admin: dict = Depends(require_admin),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    # REAL figures per person: only people who are switched on today; "total" = alerts that person was
    # actually notified about (a successful SMS / e-mail / push receipt); "acknowledged" = alerts THEY
    # acknowledged (their name is on the acknowledgement).
    sub_filter = "AND s.company_id = %s" if company_id else ""
    sub_params = (company_id,) if company_id else ()
    rows = execute_read(
        f"""
        SELECT s.id AS subscriber_id, s.name,
               COALESCE(n.total, 0)   AS notified,
               COALESCE(k.acked, 0)   AS acked,
               k.avg_min, k.fast_min, k.slow_min
          FROM subscribers s
          LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT dr.alert_id) AS total
                  FROM delivery_receipts dr
                  JOIN alerts a ON a.id = dr.alert_id AND a.company_id = s.company_id
                 WHERE dr.subscriber_id = s.id AND dr.success = 1
                   AND a.timestamp::timestamptz BETWEEN %s AND %s
          ) n ON TRUE
          LEFT JOIN LATERAL (
                SELECT COUNT(*) AS acked,
                       ROUND(AVG(x.secs)::numeric / 60, 1) AS avg_min,
                       ROUND(MIN(x.secs)::numeric / 60, 1) AS fast_min,
                       ROUND(MAX(x.secs)::numeric / 60, 1) AS slow_min
                  FROM (SELECT EXTRACT(EPOCH FROM (a.acknowledged_at::timestamptz - a.timestamp::timestamptz)) AS secs
                          FROM alerts a
                         WHERE a.company_id = s.company_id AND a.acknowledged = 1 AND a.acknowledged_at IS NOT NULL
                           AND (LOWER(a.acknowledged_by) = LOWER(s.name) OR LOWER(a.acknowledged_by) LIKE LOWER(s.name) || ' (%%')
                           AND a.timestamp::timestamptz BETWEEN %s AND %s) x
          ) k ON TRUE
         WHERE COALESCE(s.is_active, 1) = 1 AND COALESCE(s.active, 1) = 1 {sub_filter}
         ORDER BY s.escalation_order, s.name
        """,
        (ts_start, ts_end, ts_start, ts_end, *sub_params),
    )

    result = []
    for r in rows:
        acked = int(r["acked"] or 0)
        total = max(int(r["notified"] or 0), acked)      # never more acknowledged than notified
        result.append({
            "subscriber_id":      r["subscriber_id"],
            "name":               r["name"] or "Unknown",
            "avg_minutes":        float(r["avg_min"] or 0),
            "fastest_minutes":    float(r["fast_min"] or 0),
            "slowest_minutes":    float(r["slow_min"] or 0),
            "total_alerts":       total,
            "acknowledged_count": acked,
            "ack_rate_percent":   round(100.0 * acked / total, 1) if total > 0 else 0.0,
        })
    return result


# ── Chart 9 — Channel delivery rates ─────────────────────────────────────────

@router.get("/charts/delivery-rates")
def chart_delivery_rates(
    admin: dict = Depends(require_admin),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    # Scope by company via JOIN on alerts
    cid_join   = "JOIN alerts al ON al.id = dr.alert_id AND al.company_id = %s" if company_id else ""
    cid_params = (company_id,) if company_id else ()

    rows = execute_read(
        f"""
        SELECT
            dr.channel,
            COUNT(*)                                      AS sent,
            SUM(CASE WHEN dr.success = 1 THEN 1 ELSE 0 END) AS delivered
        FROM delivery_receipts dr
        {cid_join}
        WHERE dr.sent_at::timestamptz BETWEEN %s AND %s
        GROUP BY dr.channel
        """,
        (*cid_params, ts_start, ts_end),
    )

    if not rows:
        return {"available": False}

    result: dict = {}
    for r in rows:
        ch        = str(r.get("channel", "")).lower()
        sent      = int(r["sent"])
        delivered = int(r["delivered"])
        rate      = round(100.0 * delivered / sent, 1) if sent > 0 else 0.0
        result[ch] = {"sent": sent, "failed": sent - delivered, "rate_percent": rate}

    for ch in ("sms", "email", "push"):
        if ch not in result:
            result[ch] = {"sent": 0, "failed": 0, "rate_percent": 0.0}

    return result


# ── Chart 10 — Summary stats ──────────────────────────────────────────────────

@router.get("/charts/summary-stats")
def chart_summary_stats(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    source: str = Query("live"),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    start, end = _date_range(from_date, to_date)
    ts_start = f"{start}T00:00:00+00:00"
    ts_end   = f"{end}T23:59:59+00:00"

    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)

    cid_filter = "AND company_id = %s" if company_id else ""
    cid_params = (company_id,) if company_id else ()

    thr_rows = execute_read(
        "SELECT value FROM company_config WHERE field = %s LIMIT 1",
        (f"{parameter}_high",),
    )
    threshold_high = float(thr_rows[0]["value"]) if thr_rows else None

    # Aggregate in PostgreSQL (count, sum, sum of squares, min, max, above
    # threshold) — loading every reading into Python took minutes on 8M rows.
    agg_sql = ("SELECT COUNT(v) AS n, SUM(v) AS s, SUM(v * v) AS ss, MIN(v) AS mn, MAX(v) AS mx, "
               "COUNT(*) FILTER (WHERE v > %s) AS above FROM ({inner}) q WHERE v IS NOT NULL")
    parts = []
    if source in ("live", "both") and live_col:
        inner = (f"SELECT ({live_col})::float AS v FROM readings WHERE is_valid=1 "
                 f"{live_filter} {cid_filter} AND {_TS_RANGE_SQL}")
        parts += execute_read(agg_sql.format(inner=inner), (threshold_high, *cid_params, ts_start, ts_end))
    if source in ("csv", "both") and csv_col:
        inner = (f"SELECT {csv_col}::float AS v FROM csv_sensor_history WHERE {csv_col} IS NOT NULL "
                 f"AND recorded_at BETWEEN %s AND %s")
        parts += execute_read(agg_sql.format(inner=inner), (threshold_high, ts_start, ts_end))

    n = sum(int(r["n"] or 0) for r in parts)
    if n == 0:
        return []
    s     = sum(float(r["s"] or 0) for r in parts)
    ss    = sum(float(r["ss"] or 0) for r in parts)
    above = sum(int(r["above"] or 0) for r in parts)
    avg_val = round(s / n, 2)
    min_val = round(min(float(r["mn"]) for r in parts if r["mn"] is not None), 2)
    max_val = round(max(float(r["mx"]) for r in parts if r["mx"] is not None), 2)
    var     = (ss - s * s / n) / (n - 1) if n > 1 else 0.0
    std_val = round(max(var, 0.0) ** 0.5, 2)

    breach_rows = execute_read(
        f"SELECT COUNT(*) AS cnt FROM alerts WHERE parameter = %s "
        f"AND timestamp::timestamptz BETWEEN %s AND %s {cid_filter}",
        (parameter, ts_start, ts_end, *cid_params),
    )
    breach_count = int((breach_rows[0] or {}).get("cnt", 0))

    above_pct = round(100.0 * above / n, 1) if threshold_high is not None else 0.0

    unit = "°C" if parameter == "temperature" else "hPa" if parameter == "pressure" else ""

    return [{
        "parameter":                    parameter,
        "unit":                         unit,
        "avg":                          avg_val,
        "min":                          min_val,
        "max":                          max_val,
        "std_dev":                      std_val,
        "reading_count":                n,
        "breach_count":                 breach_count,
        "time_above_threshold_percent": above_pct,
    }]


# ── Incident Report ────────────────────────────────────────────────────────────

@router.get("/alerts/{alert_id}/incident-report")
def incident_report(
    alert_id: int,
    admin: dict = Depends(require_admin),
):
    company_id = admin.get("company_id")
    # Scope alert lookup to the requesting company
    cid_filter = "AND company_id = %s" if company_id else ""
    cid_params = (company_id,) if company_id else ()

    alert_rows = execute_read(
        f"SELECT * FROM alerts WHERE id = %s {cid_filter} LIMIT 1",
        (alert_id, *cid_params),
    )
    if not alert_rows:
        return JSONResponse(status_code=404, content={"error": "Alert not found"})

    alert = dict(alert_rows[0])

    delivery = execute_read(
        """
        SELECT
            dr.channel,
            dr.escalation_level,
            dr.sent_at,
            dr.success,
            dr.error_message,
            COALESCE(s.name, 'Unknown') AS subscriber_name
        FROM delivery_receipts dr
        LEFT JOIN subscribers s ON s.id = dr.subscriber_id
        WHERE dr.alert_id = %s
        ORDER BY dr.sent_at ASC
        """,
        (alert_id,),
    )

    escalations = execute_read(
        """
        SELECT
            pel.escalation_level,
            pel.notified_at,
            pel.acknowledged,
            pel.acknowledged_at,
            COALESCE(s.name, 'Unknown') AS subscriber_name
        FROM policy_escalation_log pel
        LEFT JOIN subscribers s ON s.id = pel.subscriber_id
        WHERE pel.alert_id = %s
        ORDER BY pel.escalation_level ASC, pel.notified_at ASC
        """,
        (alert_id,),
    )

    context_readings: list = []
    try:
        ctx_cid = "AND company_id = %s" if company_id else ""
        ctx_params = (company_id,) if company_id else ()
        ctx = execute_read(
            f"""
            (SELECT temperature, timestamp, 'before' AS side
               FROM readings
              WHERE timestamp < LEFT(%s, 19) AND is_valid = 1 {ctx_cid}
              ORDER BY timestamp DESC LIMIT 5)
            UNION ALL
            (SELECT temperature, timestamp, 'after' AS side
               FROM readings
              WHERE timestamp >= LEFT(%s, 19) AND is_valid = 1 {ctx_cid}
              ORDER BY timestamp ASC LIMIT 5)
            ORDER BY timestamp ASC
            """,
            (alert["timestamp"], *ctx_params, alert["timestamp"], *ctx_params),
        )
        context_readings = [dict(r) for r in ctx]
    except Exception as exc:
        logger.warning("incident_report: context readings error: %s", exc)

    return {
        "alert":            alert,
        "delivery":         [dict(r) for r in delivery],
        "escalations":      [dict(r) for r in escalations],
        "context_readings": context_readings,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }


# ── Chart 11 — Breach predictions ────────────────────────────────────────────

@router.get("/charts/predictions")
def chart_predictions(
    admin: dict = Depends(require_admin),
    parameter: str = Query("temperature"),
    source:    str = Query("live"),
):
    company_id = admin.get("company_id")
    source = _csv_guard(company_id, source)
    live_col    = _live_param_expr(parameter)
    live_filter = _live_extra_filter(parameter)
    csv_col     = _csv_param_col(parameter)
    unit        = "°C" if parameter == "temperature" else "hPa" if parameter == "pressure" else ""

    if source == "csv" and csv_col:
        rows = execute_read(
            f"""
            SELECT DISTINCT ON (DATE_TRUNC('minute', recorded_at))
                   {csv_col}::float AS v,
                   EXTRACT(EPOCH FROM recorded_at) AS ts
              FROM csv_sensor_history
             WHERE {csv_col} IS NOT NULL
             ORDER BY DATE_TRUNC('minute', recorded_at) DESC, recorded_at DESC
             LIMIT 20
            """
        )
    else:
        if not live_col:
            return []
        cid_filter = "AND company_id = %s" if company_id else ""
        cid_params = (company_id,) if company_id else ()
        rows = execute_read(
            f"""
            SELECT DISTINCT ON (DATE_TRUNC('minute', rts))
                   v, EXTRACT(EPOCH FROM rts) AS ts
              FROM (SELECT ({live_col})::float AS v, timestamp::timestamptz AS rts
                      FROM readings
                     WHERE is_valid = 1 {live_filter} {cid_filter}
                     ORDER BY timestamp DESC
                     LIMIT 3000) recent
             ORDER BY DATE_TRUNC('minute', rts) DESC, rts DESC
             LIMIT 20
            """,
            cid_params,
        )

    if len(rows) < 3:
        return []

    pts = [(float(r["ts"]), float(r["v"])) for r in reversed(rows)]
    t0  = pts[0][0]
    xs  = [p[0] - t0 for p in pts]
    ys  = [p[1]       for p in pts]

    n    = len(xs)
    sx   = sum(xs)
    sy   = sum(ys)
    sxx  = sum(x * x for x in xs)
    sxy  = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return []

    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    import config as _cfg
    rt = _cfg.RUNTIME_THRESHOLDS
    if parameter == "temperature":
        thr_high = rt.get("temp_high")
        thr_low  = rt.get("temp_low")
    else:
        thr_rows = execute_read(
            "SELECT field, value FROM company_config WHERE field IN (%s, %s)",
            (f"{parameter}_high", f"{parameter}_low"),
        )
        thresholds = {r["field"]: float(r["value"]) for r in thr_rows}
        thr_high = thresholds.get(f"{parameter}_high")
        thr_low  = thresholds.get(f"{parameter}_low")

    now_offset  = pts[-1][0] - t0
    current_val = slope * now_offset + intercept

    results = []
    for label, threshold, direction in [
        ("high", thr_high, "above"), ("low", thr_low, "below")
    ]:
        if threshold is None:
            continue
        if abs(slope) < 1e-9:
            continue
        t_breach      = (threshold - intercept) / slope
        secs_from_now = t_breach - now_offset
        if secs_from_now <= 0 or secs_from_now > 14400:
            continue

        hours_away = round(secs_from_now / 3600, 2)
        confidence = max(10, min(95, round(100 - hours_away * 15, 0)))

        results.append({
            "parameter":       parameter,
            "unit":            unit,
            "current_value":   round(current_val, 2),
            "threshold":       threshold,
            "direction":       direction,
            "hours_to_breach": hours_away,
            "confidence_pct":  int(confidence),
            "slope_per_min":   round(slope * 60, 4),
        })

    return results

"""
routers/phase4_analytics.py — Phase 4: Intelligence & Analytics.

All routes protected by require_super_admin.

Prefix: /api/super-admin/analytics
Routes:
  GET /summary                              Global totals: companies, alerts, readings
  GET /companies/health                     Health score (0-100) for every company
  GET /companies/{id}/health                Detailed health breakdown for one company
  GET /companies/compare                    Side-by-side alert/ack metrics table
  GET /anomalies                            Z-score scan on last 100 readings
  GET /trends                               Linear regression on last 30 readings

  -- Company analytics charts (Section A) --
  GET /companies/{id}/charts/breach-frequency    Daily breach counts for company
  GET /companies/{id}/charts/alert-heatmap       Hour x weekday alert heatmap
  GET /companies/{id}/charts/subscriber-response Subscriber ack rate table
  GET /companies/{id}/charts/delivery-rates      Channel delivery success rates
  GET /companies/{id}/charts/summary-stats       Alert & ack summary stats
  GET /companies/{id}/charts/severity-dist       Alert severity distribution
  GET /companies/{id}/charts/daily-trend         Daily open vs. acked alerts
  GET /companies/{id}/charts/hourly-pattern      Avg hourly alert volume
  GET /companies/{id}/charts/weekly-avg          Weekly alert volume
  GET /companies/{id}/charts/ack-time            Alert-to-ack time distribution

  -- Cross-company comparison (Section B) --
  GET /compare/parameter                    Compare companies by alert metric
  GET /compare/daily-trend                  Per-company daily alert trend
  GET /compare/breach-counts               Total breach count per company

  -- Benchmarks (Section C) --
  GET /benchmarks                           Fleet-wide aggregated stats

  -- Health scores v2 (Section D) --
  GET /health-scores                        Grade A-F health per company
"""

import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse



from database.connection import execute_read
from routers.super_admin import require_super_admin
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/analytics", tags=["Super Admin Analytics"])


# ─── Health score helper ─────────────────────────────────────────────────────

def _compute_health(company_id: int) -> dict:
    """
    Compute a 0-100 health score for one company from its alert state.
    Returns the score + component breakdown.
    """
    # Unacknowledged alerts by severity
    rows = execute_read(
        """
        SELECT severity, COUNT(*) AS cnt
          FROM alerts
         WHERE company_id = %s
           AND acknowledged = 0
         GROUP BY severity
        """,
        (company_id,),
    )
    unacked = {r["severity"].upper(): r["cnt"] for r in rows}
    emergency_unacked = unacked.get("EMERGENCY", 0)
    critical_unacked  = unacked.get("CRITICAL",  0)
    warning_unacked   = unacked.get("WARNING",   0)

    # Alerts fired in the last hour
    hour_rows = execute_read(
        """
        SELECT COUNT(*) AS cnt FROM alerts
         WHERE company_id = %s
           AND timestamp::timestamptz > NOW() - INTERVAL '1 hour'
        """,
        (company_id,),
    )
    alerts_last_hour = hour_rows[0]["cnt"] if hour_rows else 0

    # Deductions
    deduct_emergency = min(emergency_unacked * 20, 40)
    deduct_critical  = min(critical_unacked  * 10, 30)
    deduct_warning   = min(warning_unacked   *  5, 20)
    deduct_hourly    = min(alerts_last_hour  *  2, 10)

    score = max(0, 100 - deduct_emergency - deduct_critical - deduct_warning - deduct_hourly)

    if score >= 80:
        status = "healthy"
    elif score >= 50:
        status = "warning"
    elif score >= 20:
        status = "critical"
    else:
        status = "emergency"

    return {
        "score":              score,
        "status":             status,
        "emergency_unacked":  emergency_unacked,
        "critical_unacked":   critical_unacked,
        "warning_unacked":    warning_unacked,
        "alerts_last_hour":   alerts_last_hour,
        "deduct_emergency":   deduct_emergency,
        "deduct_critical":    deduct_critical,
        "deduct_warning":     deduct_warning,
        "deduct_hourly":      deduct_hourly,
    }


# ─── Simple linear regression (pure Python, no numpy) ────────────────────────

def _linear_regression(values: list[float]) -> tuple[float, float]:
    """Return (slope, intercept) for evenly-spaced x = 0, 1, 2, …"""
    n = len(values)
    if n < 2:
        return 0.0, values[0] if values else 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num   = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    denom = sum((xs[i] - mean_x) ** 2 for i in range(n))
    slope     = num / denom if denom else 0.0
    intercept = mean_y - slope * mean_x
    return slope, intercept


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/summary", summary="Global platform summary")
async def get_summary(_: dict = Depends(require_super_admin)):
    companies     = execute_read("SELECT COUNT(*) AS cnt FROM companies")
    total_alerts  = execute_read("SELECT COUNT(*) AS cnt FROM alerts")
    open_alerts   = execute_read("SELECT COUNT(*) AS cnt FROM alerts WHERE acknowledged = 0")
    emerg_alerts  = execute_read(
        "SELECT COUNT(*) AS cnt FROM alerts WHERE severity='EMERGENCY' AND acknowledged=0"
    )
    total_readings = execute_read("SELECT COUNT(*) AS cnt FROM readings")
    active_admins  = execute_read(
        "SELECT COUNT(*) AS cnt FROM admins WHERE is_active = 1 AND role != 'super_admin'"
    )

    # Top 3 companies by open alert count
    top_companies = execute_read(
        """
        SELECT c.id, c.name, COUNT(a.id) AS open_alerts
          FROM companies c
          LEFT JOIN alerts a ON a.company_id = c.id AND a.acknowledged = 0
         GROUP BY c.id, c.name
         ORDER BY open_alerts DESC
         LIMIT 3
        """
    )

    # Alerts in last 24 h
    alerts_24h = execute_read(
        """
        SELECT COUNT(*) AS cnt FROM alerts
         WHERE timestamp::timestamptz > NOW() - INTERVAL '24 hours'
        """
    )

    return {
        "companies":        companies[0]["cnt"]      if companies      else 0,
        "total_alerts":     total_alerts[0]["cnt"]   if total_alerts   else 0,
        "open_alerts":      open_alerts[0]["cnt"]    if open_alerts    else 0,
        "emergency_open":   emerg_alerts[0]["cnt"]   if emerg_alerts   else 0,
        "total_readings":   total_readings[0]["cnt"] if total_readings else 0,
        "active_admins":    active_admins[0]["cnt"]  if active_admins  else 0,
        "alerts_24h":       alerts_24h[0]["cnt"]     if alerts_24h     else 0,
        "top_offenders":    top_companies,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }


@router.get("/companies/health", summary="Health score for all companies")
async def get_all_health(_: dict = Depends(require_super_admin)):
    companies = execute_read("SELECT id, name FROM companies ORDER BY name")
    result = []
    for co in companies:
        h = _compute_health(co["id"])
        result.append({
            "company_id":   co["id"],
            "company_name": co["name"],
            **h,
        })
    result.sort(key=lambda r: r["score"])
    return result


@router.get("/companies/compare", summary="Side-by-side alert metrics for all companies")
async def compare_companies(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """
        SELECT
            c.id,
            c.name,
            COUNT(a.id)                                             AS total_alerts,
            COUNT(a.id) FILTER (WHERE a.acknowledged = 0)          AS open_alerts,
            COUNT(a.id) FILTER (WHERE a.severity = 'EMERGENCY')    AS emergency_count,
            COUNT(a.id) FILTER (WHERE a.severity = 'CRITICAL')     AS critical_count,
            COUNT(a.id) FILTER (WHERE a.severity = 'WARNING')      AS warning_count,
            COUNT(a.id) FILTER (WHERE a.acknowledged = 1
                AND a.acknowledged_at IS NOT NULL)                  AS acked_count,
            COUNT(a.id) FILTER (
                WHERE a.timestamp::timestamptz > NOW() - INTERVAL '24 hours'
            )                                                       AS alerts_24h,
            COUNT(a.id) FILTER (
                WHERE a.timestamp::timestamptz > NOW() - INTERVAL '7 days'
            )                                                       AS alerts_7d
          FROM companies c
          LEFT JOIN alerts a ON a.company_id = c.id
         GROUP BY c.id, c.name
         ORDER BY open_alerts DESC
        """
    )
    for r in rows:
        total = r["total_alerts"] or 1
        r["ack_rate_pct"] = round(r["acked_count"] / total * 100, 1)
    return rows


@router.get("/companies/{company_id}/health", summary="Detailed health for one company")
async def get_company_health(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    h = _compute_health(company_id)

    # Recent alert history (last 10)
    recent = execute_read(
        """
        SELECT id, parameter, value, threshold, direction, severity,
               timestamp, acknowledged, acknowledged_by
          FROM alerts
         WHERE company_id = %s
         ORDER BY timestamp DESC
         LIMIT 10
        """,
        (company_id,),
    )

    # Alert count by day for last 7 days
    daily = execute_read(
        """
        SELECT DATE_TRUNC('day', timestamp::timestamptz)::date AS day,
               COUNT(*) AS cnt
          FROM alerts
         WHERE company_id = %s
           AND timestamp::timestamptz > NOW() - INTERVAL '7 days'
         GROUP BY day
         ORDER BY day
        """,
        (company_id,),
    )
    for r in daily:
        if r.get("day"):
            r["day"] = str(r["day"])

    return {
        "company_id":   company_id,
        "company_name": cos[0]["name"],
        **h,
        "recent_alerts": recent,
        "daily_7d":      daily,
    }


@router.get("/anomalies", summary="Z-score anomaly detection on recent readings")
async def get_anomalies(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """
        SELECT id, temperature, timestamp
          FROM readings
         WHERE is_valid = 1
         ORDER BY id DESC
         LIMIT 100
        """
    )
    if len(rows) < 5:
        return {"anomalies": [], "note": "Not enough readings for anomaly detection (need ≥ 5)"}

    values = [r["temperature"] for r in rows]
    mean   = sum(values) / len(values)
    var    = sum((v - mean) ** 2 for v in values) / len(values)
    std    = math.sqrt(var) if var > 0 else 0.0

    anomalies = []
    if std > 0:
        for r in rows:
            z = abs(r["temperature"] - mean) / std
            if z >= 2.0:
                anomalies.append({
                    "reading_id":  r["id"],
                    "temperature": r["temperature"],
                    "timestamp":   r["timestamp"],
                    "z_score":     round(z, 2),
                    "deviation":   round(r["temperature"] - mean, 2),
                })
        anomalies.sort(key=lambda x: x["z_score"], reverse=True)

    return {
        "anomalies":    anomalies[:20],
        "readings_scanned": len(rows),
        "mean":         round(mean, 2),
        "std":          round(std, 2),
        "threshold_z":  2.0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/trends", summary="Linear regression trend on recent readings")
async def get_trends(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """
        SELECT temperature, timestamp
          FROM readings
         WHERE is_valid = 1
         ORDER BY id DESC
         LIMIT 30
        """
    )
    if len(rows) < 3:
        return {"error": "Not enough readings for trend analysis (need ≥ 3)"}

    # Most recent last for chronological regression
    rows_asc = list(reversed(rows))
    values   = [r["temperature"] for r in rows_asc]
    n        = len(values)

    slope, intercept = _linear_regression(values)

    projected_next = intercept + slope * n
    mean_temp = sum(values) / n

    if abs(slope) < 0.05:
        direction = "stable"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"

    from config import RUNTIME_THRESHOLDS
    high = RUNTIME_THRESHOLDS.get("temp_high", 90.0)
    low  = RUNTIME_THRESHOLDS.get("temp_low",  42.0)

    steps_to_high = None
    steps_to_low  = None
    if slope > 0 and projected_next < high:
        diff = high - values[-1]
        steps_to_high = int(diff / slope) if slope else None
    elif slope < 0 and projected_next > low:
        diff = values[-1] - low
        steps_to_low = int(diff / abs(slope)) if slope else None

    return {
        "readings_used":    n,
        "direction":        direction,
        "slope":            round(slope, 4),
        "mean_temperature": round(mean_temp, 2),
        "latest":           round(values[-1], 2),
        "projected_next":   round(projected_next, 2),
        "steps_to_high_threshold": steps_to_high,
        "steps_to_low_threshold":  steps_to_low,
        "high_threshold":   high,
        "low_threshold":    low,
        "recent_values":    [round(v, 2) for v in values[-10:]],
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section A — Per-company chart endpoints
# ═══════════════════════════════════════════════════════════════════════════════

def _dt_clause(col: str, from_date: Optional[str], to_date: Optional[str]) -> tuple[str, list]:
    """Return a WHERE fragment and param list for a date range filter on a timestamptz column."""
    parts, params = [], []
    if from_date:
        parts.append(f"{col} >= %s::date")
        params.append(from_date)
    if to_date:
        parts.append(f"{col} < (%s::date + INTERVAL '1 day')")
        params.append(to_date)
    clause = ("AND " + " AND ".join(parts)) if parts else ""
    return clause, params


def _check_company(company_id: int):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})
    return None


@router.get("/companies/{company_id}/charts/breach-frequency")
async def company_breach_frequency(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT DATE_TRUNC('day', a.timestamp::timestamptz)::date AS date,
               COUNT(*) AS breaches
          FROM alerts a
         WHERE a.company_id = %s {dt_clause}
         GROUP BY date
         ORDER BY date
        """,
        [company_id, *dt_params],
    )
    for r in rows:
        r["date"] = str(r["date"])
    return rows


@router.get("/companies/{company_id}/charts/alert-heatmap")
async def company_alert_heatmap(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT EXTRACT(hour FROM a.timestamp::timestamptz)::int   AS hour,
               EXTRACT(dow  FROM a.timestamp::timestamptz)::int   AS dow,
               COUNT(*) AS count
          FROM alerts a
         WHERE a.company_id = %s {dt_clause}
         GROUP BY hour, dow
        """,
        [company_id, *dt_params],
    )
    grid = [[0] * 7 for _ in range(24)]
    for r in rows:
        grid[r["hour"]][r["dow"]] = r["count"]
    return {"grid": grid, "hours": list(range(24)), "days": ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]}


@router.get("/companies/{company_id}/charts/subscriber-response")
async def company_subscriber_response(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT
            s.name,
            s.channel,
            COUNT(a.id)                                           AS total_alerts,
            COUNT(a.id) FILTER (WHERE a.acknowledged = 1)        AS acked,
            ROUND(
              100.0 * COUNT(a.id) FILTER (WHERE a.acknowledged = 1)
                    / NULLIF(COUNT(a.id), 0), 1
            )                                                     AS ack_rate_pct,
            ROUND(AVG(
              EXTRACT(EPOCH FROM (a.acknowledged_at::timestamptz - a.timestamp::timestamptz)) / 60.0
            ) FILTER (WHERE a.acknowledged = 1 AND a.acknowledged_at IS NOT NULL), 1) AS avg_ack_minutes
          FROM subscribers s
          JOIN alerts a ON a.company_id = s.company_id
         WHERE s.company_id = %s {dt_clause}
         GROUP BY s.id, s.name, s.channel
         ORDER BY ack_rate_pct DESC NULLS LAST
        """,
        [company_id, *dt_params],
    )
    return rows


@router.get("/companies/{company_id}/charts/delivery-rates")
async def company_delivery_rates(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT
            dr.channel,
            COUNT(*)                                     AS total,
            COUNT(*) FILTER (WHERE dr.success = 1)      AS delivered,
            ROUND(
              100.0 * COUNT(*) FILTER (WHERE dr.success = 1)
                    / NULLIF(COUNT(*), 0), 1
            )                                            AS success_rate
          FROM delivery_receipts dr
          JOIN alerts a ON a.id = dr.alert_id
         WHERE a.company_id = %s {dt_clause}
         GROUP BY dr.channel
         ORDER BY dr.channel
        """,
        [company_id, *dt_params],
    )
    if not rows:
        return {"available": False}
    return {"available": True, "channels": rows}


@router.get("/companies/{company_id}/charts/summary-stats")
async def company_summary_stats(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("timestamp::timestamptz", from_date, to_date)
    base = [company_id, *dt_params]
    totals = execute_read(
        f"SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE acknowledged=1) AS acked FROM alerts WHERE company_id=%s {dt_clause}",
        base,
    )
    by_sev = execute_read(
        f"SELECT severity, COUNT(*) AS cnt FROM alerts WHERE company_id=%s {dt_clause} GROUP BY severity",
        base,
    )
    sev_map = {r["severity"].upper(): r["cnt"] for r in by_sev}
    t = totals[0] if totals else {"total": 0, "acked": 0}
    ack_rate = round(100.0 * t["acked"] / t["total"], 1) if t["total"] else 0.0
    return {
        "total_alerts":    t["total"],
        "acked":           t["acked"],
        "open":            t["total"] - t["acked"],
        "ack_rate_pct":    ack_rate,
        "emergency_count": sev_map.get("EMERGENCY", 0),
        "critical_count":  sev_map.get("CRITICAL",  0),
        "warning_count":   sev_map.get("WARNING",   0),
    }


@router.get("/companies/{company_id}/charts/severity-dist")
async def company_severity_dist(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT severity, COUNT(*) AS count
          FROM alerts
         WHERE company_id = %s {dt_clause}
         GROUP BY severity
         ORDER BY CASE severity
           WHEN 'EMERGENCY' THEN 1
           WHEN 'CRITICAL'  THEN 2
           WHEN 'WARNING'   THEN 3 ELSE 4 END
        """,
        [company_id, *dt_params],
    )
    return rows


@router.get("/companies/{company_id}/charts/daily-trend")
async def company_daily_trend(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT
            DATE_TRUNC('day', timestamp::timestamptz)::date AS date,
            COUNT(*)                                        AS total,
            COUNT(*) FILTER (WHERE acknowledged = 1)       AS acked,
            COUNT(*) FILTER (WHERE acknowledged = 0)       AS open
          FROM alerts
         WHERE company_id = %s {dt_clause}
         GROUP BY date
         ORDER BY date
        """,
        [company_id, *dt_params],
    )
    for r in rows:
        r["date"] = str(r["date"])
    return rows


@router.get("/companies/{company_id}/charts/hourly-pattern")
async def company_hourly_pattern(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT EXTRACT(hour FROM timestamp::timestamptz)::int AS hour,
               COUNT(*) AS count
          FROM alerts
         WHERE company_id = %s {dt_clause}
         GROUP BY hour
         ORDER BY hour
        """,
        [company_id, *dt_params],
    )
    hour_map = {r["hour"]: r["count"] for r in rows}
    return [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]


@router.get("/companies/{company_id}/charts/weekly-avg")
async def company_weekly_avg(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT
            DATE_TRUNC('week', timestamp::timestamptz)::date AS week,
            COUNT(*) AS alerts
          FROM alerts
         WHERE company_id = %s {dt_clause}
         GROUP BY week
         ORDER BY week
        """,
        [company_id, *dt_params],
    )
    for r in rows:
        r["week"] = str(r["week"])
    return rows


@router.get("/companies/{company_id}/charts/ack-time")
async def company_ack_time(
    company_id: int,
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    err = _check_company(company_id)
    if err:
        return err
    dt_clause, dt_params = _dt_clause("timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT ROUND(
            EXTRACT(EPOCH FROM (acknowledged_at::timestamptz - timestamp::timestamptz)) / 60.0
        )::int AS minutes
          FROM alerts
         WHERE company_id = %s
           AND acknowledged = 1
           AND acknowledged_at IS NOT NULL {dt_clause}
        """,
        [company_id, *dt_params],
    )
    if not rows:
        return []
    buckets = {"<5 min": 0, "5–15 min": 0, "15–60 min": 0, "1–4 h": 0, ">4 h": 0}
    for r in rows:
        m = r["minutes"] or 0
        if m < 5:       buckets["<5 min"]    += 1
        elif m < 15:    buckets["5–15 min"]  += 1
        elif m < 60:    buckets["15–60 min"] += 1
        elif m < 240:   buckets["1–4 h"]     += 1
        else:           buckets[">4 h"]      += 1
    return [{"bucket": k, "count": v} for k, v in buckets.items()]


@router.get("/companies/{company_id}/live-trend")
async def company_live_trend(
    company_id: int,
    parameter: str = Query("temperature"),
    limit: int = Query(60, ge=1, le=500),
    _: dict = Depends(require_super_admin),
):
    """Last N sensor readings (global — readings table has no company_id)."""
    err = _check_company(company_id)
    if err:
        return err
    col = "temperature" if parameter == "temperature" else "temperature"
    unit = "°C" if parameter == "temperature" else "hPa"
    rows = execute_read(
        f"""
        SELECT timestamp::timestamptz AS ts, {col}::float AS value
          FROM readings
         WHERE is_valid = 1 AND {col} IS NOT NULL
         ORDER BY timestamp::timestamptz DESC
         LIMIT %s
        """,
        (limit,),
    )
    return [
        {"timestamp": r["ts"].isoformat(), "value": round(r["value"], 2), "unit": unit}
        for r in reversed(rows)
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Section B — Cross-company comparison endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/compare/parameter")
async def compare_by_parameter(
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT
            c.id,
            c.name,
            COUNT(a.id)                                             AS total_alerts,
            COUNT(a.id) FILTER (WHERE a.severity = 'EMERGENCY')    AS emergency,
            COUNT(a.id) FILTER (WHERE a.severity = 'CRITICAL')     AS critical,
            COUNT(a.id) FILTER (WHERE a.severity = 'WARNING')      AS warning,
            ROUND(
              100.0 * COUNT(a.id) FILTER (WHERE a.acknowledged = 1)
                    / NULLIF(COUNT(a.id), 0), 1
            )                                                       AS ack_rate_pct
          FROM companies c
          LEFT JOIN alerts a ON a.company_id = c.id {dt_clause}
         GROUP BY c.id, c.name
         ORDER BY total_alerts DESC
        """,
        dt_params,
    )
    return rows


@router.get("/compare/daily-trend")
async def compare_daily_trend(
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT
            DATE_TRUNC('day', a.timestamp::timestamptz)::date AS date,
            c.name AS company,
            COUNT(*) AS alerts
          FROM alerts a
          JOIN companies c ON c.id = a.company_id
         WHERE 1=1 {dt_clause}
         GROUP BY date, c.id, c.name
         ORDER BY date, c.name
        """,
        dt_params,
    )
    for r in rows:
        r["date"] = str(r["date"])
    return rows


@router.get("/compare/breach-counts")
async def compare_breach_counts(
    from_date: Optional[str] = Query(None),
    to_date:   Optional[str] = Query(None),
    _: dict = Depends(require_super_admin),
):
    dt_clause, dt_params = _dt_clause("a.timestamp::timestamptz", from_date, to_date)
    rows = execute_read(
        f"""
        SELECT c.name, COUNT(a.id) AS breaches
          FROM companies c
          LEFT JOIN alerts a ON a.company_id = c.id {dt_clause}
         GROUP BY c.id, c.name
         ORDER BY breaches DESC
        """,
        dt_params,
    )
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# Section C — Benchmarks
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/benchmarks")
async def get_benchmarks(_: dict = Depends(require_super_admin)):
    companies = execute_read("SELECT COUNT(*) AS cnt FROM companies")
    alert_rows = execute_read(
        """
        SELECT
            COUNT(*)                                             AS total,
            COUNT(*) FILTER (WHERE acknowledged = 1)            AS acked,
            COUNT(*) FILTER (WHERE severity = 'EMERGENCY')      AS emergency,
            COUNT(*) FILTER (WHERE severity = 'CRITICAL')       AS critical,
            COUNT(*) FILTER (WHERE severity = 'WARNING')        AS warning,
            COUNT(*) FILTER (
                WHERE timestamp::timestamptz > NOW() - INTERVAL '24 hours'
            )                                                   AS last_24h,
            COUNT(*) FILTER (
                WHERE timestamp::timestamptz > NOW() - INTERVAL '7 days'
            )                                                   AS last_7d
          FROM alerts
        """
    )
    dr_rows = execute_read(
        """
        SELECT
            COUNT(*)                                        AS total_deliveries,
            COUNT(*) FILTER (WHERE success = 1)             AS delivered,
            ROUND(100.0 * COUNT(*) FILTER (WHERE success=1) / NULLIF(COUNT(*),0), 1) AS delivery_rate
          FROM delivery_receipts
        """
    )
    n_co = companies[0]["cnt"] if companies else 0
    ar   = alert_rows[0] if alert_rows else {}
    dr   = dr_rows[0]   if dr_rows   else {}
    total = ar.get("total", 0) or 1
    fleet_ack = round(100.0 * (ar.get("acked", 0) or 0) / total, 1)
    alerts_per_co = round(total / n_co, 1) if n_co else 0
    return {
        "companies":            n_co,
        "fleet_total_alerts":   ar.get("total",     0),
        "fleet_acked":          ar.get("acked",     0),
        "fleet_ack_rate_pct":   fleet_ack,
        "fleet_emergency":      ar.get("emergency", 0),
        "fleet_critical":       ar.get("critical",  0),
        "fleet_warning":        ar.get("warning",   0),
        "alerts_last_24h":      ar.get("last_24h",  0),
        "alerts_last_7d":       ar.get("last_7d",   0),
        "avg_alerts_per_company": alerts_per_co,
        "total_deliveries":     dr.get("total_deliveries", 0),
        "fleet_delivery_rate":  dr.get("delivery_rate",    0),
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Section D — Health scores v2 (grade A-F)
# ═══════════════════════════════════════════════════════════════════════════════

def _grade(score: float) -> str:
    if score >= 90: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 40: return "D"
    return "F"


@router.get("/health-scores")
async def get_health_scores(_: dict = Depends(require_super_admin)):
    companies = execute_read("SELECT id, name FROM companies ORDER BY name")
    results = []
    for co in companies:
        cid = co["id"]

        # Breach score: penalise open emergency/critical/warning
        breach_rows = execute_read(
            """
            SELECT severity, COUNT(*) AS cnt FROM alerts
             WHERE company_id=%s AND acknowledged=0
             GROUP BY severity
            """,
            (cid,),
        )
        unacked = {r["severity"].upper(): r["cnt"] for r in breach_rows}
        breach_pen = min(
            unacked.get("EMERGENCY", 0) * 25
            + unacked.get("CRITICAL",  0) * 10
            + unacked.get("WARNING",   0) *  4,
            50,
        )
        breach_score = max(0, 100 - breach_pen)

        # Ack score: ack rate over last 30 days
        ack_rows = execute_read(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE acknowledged=1) AS acked
              FROM alerts
             WHERE company_id=%s
               AND timestamp::timestamptz > NOW() - INTERVAL '30 days'
            """,
            (cid,),
        )
        ar = ack_rows[0] if ack_rows else {"total": 0, "acked": 0}
        ack_score = round(100.0 * ar["acked"] / ar["total"], 1) if ar["total"] else 100.0

        # Delivery score: channel delivery success rate
        dr_rows = execute_read(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE dr.success=1) AS delivered
              FROM delivery_receipts dr
              JOIN alerts a ON a.id = dr.alert_id
             WHERE a.company_id=%s
            """,
            (cid,),
        )
        drr = dr_rows[0] if dr_rows else {"total": 0, "delivered": 0}
        delivery_score = (
            round(100.0 * drr["delivered"] / drr["total"], 1) if drr["total"] else 100.0
        )

        # Uptime score: no alerts in last 1 hour → 100, deduct 10 per alert
        uptime_rows = execute_read(
            """
            SELECT COUNT(*) AS cnt FROM alerts
             WHERE company_id=%s AND timestamp::timestamptz > NOW() - INTERVAL '1 hour'
            """,
            (cid,),
        )
        recent = (uptime_rows[0]["cnt"] if uptime_rows else 0) or 0
        uptime_score = max(0, 100 - recent * 10)

        composite = round(
            breach_score   * 0.40
            + ack_score    * 0.30
            + delivery_score * 0.15
            + uptime_score * 0.15,
            1,
        )

        results.append({
            "company_id":      cid,
            "company_name":    co["name"],
            "grade":           _grade(composite),
            "composite":       composite,
            "breach_score":    breach_score,
            "ack_score":       ack_score,
            "delivery_score":  delivery_score,
            "uptime_score":    uptime_score,
            "open_emergency":  unacked.get("EMERGENCY", 0),
            "open_critical":   unacked.get("CRITICAL",  0),
            "open_warning":    unacked.get("WARNING",   0),
        })

    results.sort(key=lambda r: r["composite"])
    return results

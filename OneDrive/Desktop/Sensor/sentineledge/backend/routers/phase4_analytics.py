"""
routers/phase4_analytics.py — Phase 4: Intelligence & Analytics.

All routes protected by require_super_admin.

Prefix: /api/super-admin/analytics
Routes:
  GET /summary                   Global totals: companies, alerts, readings
  GET /companies/health          Health score (0-100) for every company
  GET /companies/{id}/health     Detailed health breakdown for one company
  GET /companies/compare         Side-by-side alert/ack metrics table
  GET /anomalies                 Z-score scan on last 100 readings
  GET /trends                    Linear regression on last 30 readings
"""

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
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

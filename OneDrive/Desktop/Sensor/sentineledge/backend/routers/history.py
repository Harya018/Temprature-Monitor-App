"""
routers/history.py — Historical data and CSV export endpoints.

Endpoints:
    GET /api/history/stats?date=YYYY-MM-DD
    GET /api/history/alerts?date=YYYY-MM-DD
    GET /api/history/export/alerts?start=&end=
    GET /api/history/export/readings?start=&end=

Every query is scoped to the caller's company (a new company sees nothing
until its own data exists). Platform callers with no company see everything.

NOTE: All SQL placeholders use %s (psycopg2/PostgreSQL). Never use ? here.
"""



import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

import database
from middleware.auth import require_admin
from database.connection import execute_read
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/history", tags=["History"])


def _scope(admin: dict, col: str = "company_id"):
    """('AND <col> = %s', (cid,)) for a company admin; no filter for platform callers."""
    cid = admin.get("company_id")
    return (f"AND {col} = %s", (cid,)) if cid is not None else ("", ())


@router.get("/stats")
async def history_stats(date: str = Query(..., description="YYYY-MM-DD"),
                        admin: dict = Depends(require_admin)):
    """Daily stats for a specific date (UTC)."""
    try:
        start = f"{date}T00:00:00"
        end   = f"{date}T23:59:59~"
        rf, rp = _scope(admin)
        af, ap = _scope(admin, "a.company_id")

        readings = execute_read(
            f"SELECT temperature, timestamp FROM readings WHERE timestamp >= %s AND timestamp <= %s {rf}",
            (start, end, *rp),
        )
        alerts = execute_read(
            f"SELECT a.* FROM alerts a WHERE a.timestamp >= %s AND a.timestamp <= %s {af}",
            (start, end, *ap),
        )

        temps = [r["temperature"] for r in readings if r.get("temperature") is not None]

        # Find peak and min with time
        valid = [r for r in readings if r.get("temperature") is not None]
        peak_row = max(valid, key=lambda r: r["temperature"], default=None)
        min_row  = min(valid, key=lambda r: r["temperature"], default=None)

        # Delivery breakdown (receipts belong to the company of their alert)
        receipts = execute_read(
            "SELECT dr.channel, dr.success, COUNT(*) as cnt FROM delivery_receipts dr "
            "JOIN alerts a ON a.id = dr.alert_id "
            f"WHERE dr.sent_at >= %s AND dr.sent_at <= %s {af} GROUP BY dr.channel, dr.success",
            (start, end, *ap),
        )
        delivery = {"email": {"sent": 0, "failed": 0}, "sms": {"sent": 0, "failed": 0}}
        for r in receipts:
            ch = r["channel"]
            if ch in delivery:
                key = "sent" if r["success"] else "failed"
                delivery[ch][key] += r["cnt"]

        return {
            "date": date,
            "total_readings": len(readings),
            "total_alerts":   len(alerts),
            "avg_temp":  round(sum(temps) / len(temps), 2) if temps else None,
            "peak_temp": peak_row["temperature"] if peak_row else None,
            "peak_temp_time": peak_row.get("timestamp") if peak_row else None,
            "min_temp":  min_row["temperature"] if min_row else None,
            "min_temp_time": min_row.get("timestamp") if min_row else None,
            "delivery": delivery,
        }
    except Exception as exc:
        logger.error("history_stats failed: %s", exc)
        return {"error": str(exc)}


@router.get("/alerts")
async def history_alerts(date: str = Query(..., description="YYYY-MM-DD"),
                         admin: dict = Depends(require_admin)):
    """All alerts for a specific date."""
    try:
        f, p = _scope(admin)
        rows = execute_read(
            f"SELECT * FROM alerts WHERE timestamp >= %s AND timestamp <= %s {f} ORDER BY id DESC",
            (f"{date}T00:00:00", f"{date}T23:59:59~", *p),
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("history_alerts failed: %s", exc)
        return []


@router.get("/export/alerts")
async def export_alerts_csv(
    start: str = Query(..., description="YYYY-MM-DD"),
    end:   str = Query(..., description="YYYY-MM-DD"),
    admin: dict = Depends(require_admin),
):
    """Export alerts in a date range as CSV."""
    try:
        f, p = _scope(admin)
        rows = execute_read(
            f"SELECT * FROM alerts WHERE timestamp >= %s AND timestamp <= %s {f} ORDER BY id",
            (f"{start}T00:00:00", f"{end}T23:59:59~", *p),
        )
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        else:
            buf.write("id,parameter,value,threshold,direction,severity,timestamp,"
                      "acknowledged,acknowledged_by,acknowledged_at,escalation_level,"
                      "max_escalated,cooldown_until\n")
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=alerts_{start}_{end}.csv"},
        )
    except Exception as exc:
        logger.error("export_alerts_csv failed: %s", exc)
        return StreamingResponse(iter([f"error,{exc}\n"]), media_type="text/csv")


@router.get("/export/readings")
async def export_readings_csv(
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
    end:   str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD"),
    admin: dict = Depends(require_admin),
):
    """Export all sensor readings (every parameter) in a date range as CSV — streamed, no row limit."""
    from routers.reports import stream_readings
    return stream_readings(admin, start, end, "csv")

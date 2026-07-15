"""
routers/history.py — Historical data and CSV export endpoints.

Endpoints:
    GET /api/history/stats?date=YYYY-MM-DD
    GET /api/history/alerts?date=YYYY-MM-DD
    GET /api/history/export/alerts?start=&end=
    GET /api/history/export/readings?start=&end=

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


@router.get("/stats", dependencies=[Depends(require_admin)])
async def history_stats(date: str = Query(..., description="YYYY-MM-DD")):
    """Daily stats for a specific date (UTC)."""
    try:
        start = f"{date}T00:00:00"
        end   = f"{date}T23:59:59"

        readings = execute_read(
            "SELECT temperature, timestamp FROM readings WHERE timestamp >= %s AND timestamp <= %s",
            (start, end),
        )
        alerts = execute_read(
            "SELECT * FROM alerts WHERE timestamp >= %s AND timestamp <= %s",
            (start, end),
        )

        temps = [r["temperature"] for r in readings if r.get("temperature") is not None]

        # Find peak and min with time
        peak_row = max(readings, key=lambda r: r["temperature"], default=None) if readings else None
        min_row  = min(readings, key=lambda r: r["temperature"], default=None) if readings else None

        # Delivery breakdown
        receipts = execute_read(
            "SELECT channel, success, COUNT(*) as cnt FROM delivery_receipts "
            "WHERE sent_at >= %s AND sent_at <= %s GROUP BY channel, success",
            (start, end),
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


@router.get("/alerts", dependencies=[Depends(require_admin)])
async def history_alerts(date: str = Query(..., description="YYYY-MM-DD")):
    """All alerts for a specific date."""
    try:
        start = f"{date}T00:00:00"
        end   = f"{date}T23:59:59"
        rows = execute_read(
            "SELECT * FROM alerts WHERE timestamp >= %s AND timestamp <= %s ORDER BY id DESC",
            (start, end),
        )
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("history_alerts failed: %s", exc)
        return []


@router.get("/export/alerts", dependencies=[Depends(require_admin)])
async def export_alerts_csv(
    start: str = Query(..., description="YYYY-MM-DD"),
    end:   str = Query(..., description="YYYY-MM-DD"),
):
    """Export alerts in a date range as CSV."""
    try:
        rows = execute_read(
            "SELECT * FROM alerts WHERE timestamp >= %s AND timestamp <= %s ORDER BY id",
            (f"{start}T00:00:00", f"{end}T23:59:59"),
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


@router.get("/export/readings", dependencies=[Depends(require_admin)])
async def export_readings_csv(
    start: str = Query(..., description="YYYY-MM-DD"),
    end:   str = Query(..., description="YYYY-MM-DD"),
):
    """Export sensor readings in a date range as CSV."""
    try:
        rows = execute_read(
            "SELECT id, temperature, timestamp, is_valid FROM readings "
            "WHERE timestamp >= %s AND timestamp <= %s ORDER BY id",
            (f"{start}T00:00:00", f"{end}T23:59:59"),
        )
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["id", "temperature", "timestamp", "is_valid"])
        writer.writeheader()
        if rows:
            writer.writerows(rows)
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=readings_{start}_{end}.csv"},
        )
    except Exception as exc:
        logger.error("export_readings_csv failed: %s", exc)
        return StreamingResponse(iter([f"error,{exc}\n"]), media_type="text/csv")

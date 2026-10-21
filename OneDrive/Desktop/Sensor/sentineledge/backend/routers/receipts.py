"""
routers/receipts.py — Delivery receipt endpoints.

Endpoints:
    GET /api/receipts?limit=100&channel=all&status=all
"""



from fastapi import APIRouter, Depends, Query

from middleware.auth import require_admin
from database.connection import execute_read
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["Receipts"])


@router.get("/receipts")
async def get_receipts(
    limit:   int = Query(100, ge=1, le=500),
    channel: str = Query("all"),
    status:  str = Query("all"),
    admin:   dict = Depends(require_admin),
):
    """
    Return delivery receipts joined with alert and subscriber info.
    channel: all | email | sms
    status:  all | success | failed
    Scoped to the caller's company (a receipt belongs to its alert's company).
    """
    try:
        where_clauses = []
        params: list = []

        if admin.get("company_id") is not None:
            where_clauses.append("a.company_id = %s")
            params.append(admin["company_id"])

        if channel != "all":
            where_clauses.append("dr.channel = %s")
            params.append(channel)

        if status == "success":
            where_clauses.append("dr.success = true")
        elif status == "failed":
            where_clauses.append("dr.success = false")

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        rows = execute_read(
            f"""
            SELECT
                dr.id,
                dr.alert_id,
                dr.channel,
                dr.escalation_level,
                dr.sent_at,
                dr.success,
                dr.error_message,
                a.value         AS alert_value,
                a.parameter     AS alert_parameter,
                a.severity      AS alert_severity,
                a.timestamp     AS alert_time,
                s.name          AS subscriber_name
            FROM delivery_receipts dr
            LEFT JOIN alerts       a ON dr.alert_id = a.id
            LEFT JOIN subscribers  s ON dr.subscriber_id = s.id
            WHERE dr.sent_at::timestamptz >= NOW() - INTERVAL '30 days'
            {"AND " + " AND ".join(where_clauses) if where_clauses else ""}
            ORDER BY dr.id DESC
            LIMIT %s
            """,
            (*params, limit),
        )

        return [dict(r) for r in rows]

    except Exception as exc:
        logger.error("get_receipts failed: %s", exc)
        return []

"""
routers/alerts.py — /api/alerts endpoints.

Tags: Alerts
Rate limiting (slowapi):
  GET  /api/alerts                    → 60/minute per IP
  POST /api/alerts/{id}/acknowledge   → 30/minute per IP
  DELETE /api/alerts                  → admin only, 20/minute per IP
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import database
import core.escalation as escalation
from database.connection import execute_read
from middleware.auth import require_admin
from middleware.rate_limit import limiter
from models import AcknowledgeIn, AlertOut
from utils.logger import get_logger

router = APIRouter(prefix="/api", tags=["Alerts"])
logger = get_logger(__name__)


def _session_company_id(request: Request) -> int | None:
    """Return the company_id for the Bearer-token caller, or None for super_admin/unknown."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        rows = execute_read(
            """SELECT a.company_id FROM admins a
               JOIN admin_sessions s ON s.admin_id = a.id
               WHERE s.token = %s AND s.expires_at > NOW() LIMIT 1""",
            (token,),
        )
        return rows[0]["company_id"] if rows else None
    except Exception:
        return None


def _build_delivery_status(alert_id: int) -> dict:
    receipts = database.get_receipts_for_alert(alert_id)
    status: dict = {}
    for r in receipts:
        channel = r["channel"]
        if r["success"]:
            status[channel] = "delivered"
        else:
            if status.get(channel) != "delivered":
                status[channel] = "failed"
    return status


@router.get(
    "/alerts",
    response_model=list[AlertOut],
    summary="Get recent alerts",
    description="Returns alerts scoped to the authenticated admin's company. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("60/minute")
async def get_alerts(
    request: Request,
    limit: int = Query(50, ge=1, le=1000, description="Number of alerts per page"),
    page:  int = Query(1,  ge=1,           description="Page number (1-based)"),
):
    company_id = _session_company_id(request)
    offset = (page - 1) * limit
    rows = database.get_recent_alerts(limit=limit, offset=offset, company_id=company_id)
    result = []
    for r in rows:
        delivery_status = _build_delivery_status(r["id"])
        result.append(
            AlertOut(
                id=r["id"],
                parameter=r["parameter"],
                value=r["value"],
                threshold=r["threshold"],
                direction=r["direction"],
                severity=r.get("severity", "WARNING"),
                timestamp=r["timestamp"],
                acknowledged=bool(r["acknowledged"]),
                acknowledged_by=r.get("acknowledged_by"),
                acknowledged_at=r.get("acknowledged_at"),
                escalation_level=r["escalation_level"],
                max_escalated=bool(r["max_escalated"]),
                cooldown_until=r.get("cooldown_until"),
                delivery_status=delivery_status if delivery_status else None,
            )
        )
    return result


@router.get(
    "/alerts/{alert_id}",
    summary="Get a single alert",
    description="Returns one alert by ID. Scoped to the authenticated admin's company.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("60/minute")
async def get_alert(alert_id: int, request: Request):
    company_id = _session_company_id(request)
    row = database.get_alert(alert_id, company_id=company_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    delivery_status = _build_delivery_status(alert_id)
    return {**row, "delivery_status": delivery_status or None}


@router.post(
    "/alerts/{alert_id}/acknowledge",
    summary="Acknowledge an alert",
    description="Marks the alert as acknowledged. Scoped to the authenticated admin's company.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("30/minute")
async def acknowledge_alert(alert_id: int, body: AcknowledgeIn, request: Request):
    company_id = _session_company_id(request)
    # Verify the alert belongs to this company before acknowledging
    if company_id is not None:
        row = database.get_alert(alert_id, company_id=company_id)
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
    ok = await escalation.acknowledge(alert_id, f"{body.acknowledged_by} (app)")
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Alert {alert_id} not found or already acknowledged",
        )
    return {"status": "acknowledged", "alert_id": alert_id}


_VALID_PERIODS = {"1h", "24h", "7d", "30d", "all"}

_PERIOD_LABELS = {
    "1h":  "the last 1 hour",
    "24h": "the last 24 hours",
    "7d":  "the last 7 days",
    "30d": "the last 30 days",
    "all": "all time",
}


@router.delete(
    "/alerts",
    summary="Delete alerts by time period",
    description=(
        "Permanently deletes alerts (and their delivery receipts) for the specified "
        "period, scoped to the authenticated admin's company. "
        "period must be one of: 1h, 24h, 7d, 30d, all. Requires admin auth."
    ),
    dependencies=[Depends(require_admin)],
)
@limiter.limit("20/minute")
async def delete_alerts(
    request: Request,
    period: str = Query(
        ...,
        description="Time period to delete: 1h | 24h | 7d | 30d | all",
    )
):
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid period '{period}'. Must be one of: {', '.join(sorted(_VALID_PERIODS))}",
        )

    company_id = _session_company_id(request)
    try:
        deleted = database.delete_alerts_by_period(period, company_id=company_id)
        label   = _PERIOD_LABELS[period]
        msg     = f"{deleted} alert{'s' if deleted != 1 else ''} deleted ({label})"
        logger.info("DELETE /api/alerts: %s", msg)
        return {
            "deleted": deleted,
            "period":  period,
            "message": msg,
        }
    except Exception as exc:
        logger.error("DELETE /api/alerts failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred")

"""
routers/alerts.py — /api/alerts endpoints.

Tags: Alerts
Rate limiting (slowapi):
  GET  /api/alerts                    → 60/minute per IP
  POST /api/alerts/{id}/acknowledge   → 30/minute per IP
  DELETE /api/alerts                  → admin only, 20/minute per IP
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import database
import core.escalation as escalation
from database.connection import execute_read
from middleware.auth import require_admin, require_subscriber_auth
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
    row = database.get_alert(alert_id, company_id=company_id) if company_id is not None else database.get_alert(alert_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    if row.get("acknowledged"):
        # someone else was first: keep their name and time, tell this admin who it was
        return JSONResponse(status_code=409, content={
            "error": "AlreadyAcknowledged", "alert_id": alert_id,
            "acknowledged_by": row.get("acknowledged_by"), "acknowledged_at": row.get("acknowledged_at"),
            "message": f"Already acknowledged by {row.get('acknowledged_by') or 'someone else'}"})
    # recorded under the signed-in admin's own name (a typed name could be anybody's)
    from middleware.auth import session_admin
    me = session_admin(request.headers.get("authorization"))
    who = (me or {}).get("name") or body.acknowledged_by
    ok = await escalation.acknowledge(alert_id, f"{who} (dashboard)")
    if not ok:
        latest = database.get_alert(alert_id) or {}
        return JSONResponse(status_code=409, content={
            "error": "AlreadyAcknowledged", "alert_id": alert_id,
            "acknowledged_by": latest.get("acknowledged_by"), "acknowledged_at": latest.get("acknowledged_at"),
            "message": f"Already acknowledged by {latest.get('acknowledged_by') or 'someone else'}"})
    if me:
        from utils.activity_logger import log_activity
        log_activity(me["id"], "acknowledge_alert", "alert", f"alert:{alert_id} {row.get('parameter')}", row.get("company_id"))
    return {"status": "acknowledged", "alert_id": alert_id, "acknowledged_by": f"{who} (dashboard)"}


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
        try:   # with several admins, the company must be able to see who removed alert history
            from middleware.auth import session_admin
            from utils.activity_logger import log_activity
            from services import company_log
            me = session_admin(request.headers.get("authorization")) or {}
            if me:
                log_activity(me["id"], "delete_alerts", "alert", msg, company_id)
                company_log.log(company_id, f"{me['name']}: {msg}")
        except Exception as exc:
            logger.warning("DELETE /api/alerts: could not record who deleted: %s", exc)
        return {
            "deleted": deleted,
            "period":  period,
            "message": msg,
        }
    except Exception as exc:
        logger.error("DELETE /api/alerts failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred")


# ── Subscriber-facing alert endpoints (mobile app) ────────────────────────────
# These mirror the admin endpoints above but accept X-Auth-Token (subscriber
# session) instead of Authorization: Bearer (admin session).  The subscriber's
# company_id is derived from their own row so results are always scoped to
# their company.

@router.get(
    "/subscriber/alerts",
    response_model=list[AlertOut],
    summary="Get recent alerts (subscriber)",
    description="Returns alerts for the subscriber's company. Requires X-Auth-Token header.",
)
@limiter.limit("60/minute")
async def get_subscriber_alerts(
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
    page:  int = Query(1,  ge=1),
    sub_session: dict = Depends(require_subscriber_auth),
):
    sub = database.get_subscriber_by_id(sub_session["subscriber_id"])
    company_id = sub.get("company_id") if sub else None
    if company_id is None:          # a person with no company must never be shown every company's alerts
        return []
    offset = (page - 1) * limit
    rows = database.get_recent_alerts(limit=limit, offset=offset, company_id=company_id)
    result = []
    for r in rows:
        delivery_status = _build_delivery_status(r["id"])
        result.append(AlertOut(
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
        ))
    return result


@router.post(
    "/subscriber/alerts/{alert_id}/acknowledge",
    summary="Acknowledge an alert (subscriber)",
    description="Marks the alert as acknowledged. Requires X-Auth-Token header.",
)
@limiter.limit("30/minute")
async def subscriber_acknowledge_alert(
    alert_id: int,
    body: AcknowledgeIn,
    request: Request,
    sub_session: dict = Depends(require_subscriber_auth),
):
    # A person may only acknowledge their OWN company's alerts (same answer as "not found",
    # so alert numbers of other companies cannot be probed).
    sub = database.get_subscriber_by_id(sub_session["subscriber_id"])
    rows = execute_read("SELECT company_id FROM alerts WHERE id = %s", (alert_id,))
    if not sub or sub.get("company_id") is None or not rows or rows[0].get("company_id") != sub.get("company_id"):
        raise HTTPException(
            status_code=404,
            detail=f"Alert {alert_id} not found or already acknowledged",
        )
    who = sub_session.get("name") or body.acknowledged_by     # the signed-in person, not a typed name
    ok = await escalation.acknowledge(alert_id, f"{who} (app)")
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Alert {alert_id} not found or already acknowledged",
        )
    return {"status": "acknowledged", "alert_id": alert_id}

"""
routers/phase1_command.py — Phase 1: Real-Time Command Center.

All routes protected by require_super_admin (imported from super_admin.py).

Prefix: /api/super-admin/command
Routes:
  POST  /companies/{company_id}/maintenance      Toggle maintenance mode
  GET   /companies/{company_id}/maintenance      Current maintenance status
  POST  /alerts/{alert_id}/force-acknowledge     Force-acknowledge an alert
  GET   /live-map                                All companies + devices + live status
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from routers.super_admin import require_super_admin
from utils.activity_logger import log_activity
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/command", tags=["Super Admin Command"])


# ─── Pydantic bodies ──────────────────────────────────────────────────────────

class _MaintenanceIn(BaseModel):
    enabled: bool
    duration_minutes: int = Field(default=60, ge=1, le=10080)
    reason: str = Field(default="", max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, v):
        return v.strip() if isinstance(v, str) else v


class _ForceAckIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, v):
        return v.strip() if isinstance(v, str) else v


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("/companies/{company_id}/maintenance", summary="Toggle maintenance mode")
async def toggle_maintenance(
    company_id: int,
    body: _MaintenanceIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    if body.enabled:
        until = (datetime.now(timezone.utc) + timedelta(minutes=body.duration_minutes)).isoformat()
        execute_write(
            """
            UPDATE companies
               SET maintenance_mode = 1,
                   maintenance_until = %s,
                   maintenance_reason = %s
             WHERE id = %s
            """,
            (until, body.reason, company_id),
        )
        logger.info(
            "Maintenance ON for company %d (duration=%dmin, reason=%r) by super_admin id=%d",
            company_id, body.duration_minutes, body.reason, sa["id"],
        )
    else:
        execute_write(
            """
            UPDATE companies
               SET maintenance_mode = 0,
                   maintenance_until = NULL,
                   maintenance_reason = NULL
             WHERE id = %s
            """,
            (company_id,),
        )
        logger.info(
            "Maintenance OFF for company %d by super_admin id=%d",
            company_id, sa["id"],
        )

    log_activity(
        sa["id"],
        "maintenance_mode_toggled",
        "company",
        f"company_id:{company_id} enabled:{body.enabled} duration:{body.duration_minutes}min reason:{body.reason}",
        company_id,
    )
    return {
        "company_id":      company_id,
        "maintenance_mode": body.enabled,
        "message":         "Maintenance mode updated",
    }


@router.get("/companies/{company_id}/maintenance", summary="Get maintenance status")
async def get_maintenance(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT id, name, maintenance_mode, maintenance_until, maintenance_reason
          FROM companies WHERE id = %s
        """,
        (company_id,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Company not found"})
    c = rows[0]
    return {
        "company_id":         c["id"],
        "company_name":       c["name"],
        "maintenance_mode":   bool(c["maintenance_mode"]),
        "maintenance_until":  c["maintenance_until"].isoformat() if c["maintenance_until"] else None,
        "maintenance_reason": c["maintenance_reason"],
    }


@router.post("/alerts/{alert_id}/force-acknowledge", summary="Force acknowledge an alert")
async def force_acknowledge(
    alert_id: int,
    body: _ForceAckIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id, acknowledged FROM alerts WHERE id = %s", (alert_id,))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Alert not found"})

    acknowledged_by = f"superadmin [{body.reason}]"
    execute_write(
        """
        UPDATE alerts
           SET acknowledged = 1,
               acknowledged_by = %s,
               acknowledged_at = NOW()
         WHERE id = %s
        """,
        (acknowledged_by, alert_id),
    )

    log_activity(
        sa["id"],
        "force_acknowledge",
        "alert",
        f"alert_id:{alert_id} reason:{body.reason}",
        None,
    )
    logger.info("Alert %d force-acknowledged by super_admin id=%d (reason=%r)", alert_id, sa["id"], body.reason)
    return {
        "alert_id":        alert_id,
        "acknowledged":    True,
        "acknowledged_by": acknowledged_by,
    }


@router.get("/live-map", summary="Live system map — all companies, devices, and status")
async def live_map(_: dict = Depends(require_super_admin)):
    """
    Returns all companies with per-subscriber device status.
    Status is derived from the global latest reading vs RUNTIME_THRESHOLDS.
    A device is 'offline' when the last reading is older than 5 minutes.
    """
    from config import RUNTIME_THRESHOLDS

    now = datetime.now(timezone.utc)
    offline_age = timedelta(minutes=5)

    companies = execute_read(
        """
        SELECT id, name, maintenance_mode, maintenance_until, maintenance_reason
          FROM companies ORDER BY name
        """
    )

    # Latest global reading (shared sensor — schema has no per-company readings yet)
    latest_rows = execute_read(
        "SELECT temperature, timestamp FROM readings ORDER BY id DESC LIMIT 1"
    )
    lr = latest_rows[0] if latest_rows else None

    rt = RUNTIME_THRESHOLDS.get("temperature", {})
    high_t = float(rt.get("high", 90))
    low_t  = float(rt.get("low", 10))

    result = []
    for co in companies:
        # Unacknowledged alert count for this company
        ack_rows = execute_read(
            "SELECT COUNT(*) AS cnt FROM alerts WHERE company_id = %s AND acknowledged = 0",
            (co["id"],),
        )
        alert_count = int(ack_rows[0]["cnt"]) if ack_rows else 0

        # Subscribers as device proxies
        subs = execute_read(
            "SELECT id, name FROM subscribers WHERE company_id = %s AND is_active = 1",
            (co["id"],),
        )

        devices = []
        for sub in subs:
            last_ts = lr["timestamp"] if lr else None
            value   = float(lr["temperature"]) if lr else None

            # Offline check
            is_offline = True
            if last_ts:
                try:
                    ts_dt = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
                    if ts_dt.tzinfo is None:
                        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                    is_offline = (now - ts_dt) > offline_age
                except Exception:
                    is_offline = True

            if is_offline or value is None:
                status = "offline"
            elif value >= high_t * 1.1 or value <= low_t * 0.9:
                status = "critical"
            elif value >= high_t or value <= low_t:
                status = "warning"
            else:
                status = "normal"

            devices.append({
                "id":                sub["id"],
                "name":              sub["name"],
                "parameter":         "temperature",
                "latest_value":      value,
                "unit":              "°C",
                "status":            status,
                "last_reading_at":   last_ts,
                "active_alert_count": alert_count,
            })

        result.append({
            "id":                 co["id"],
            "name":               co["name"],
            "maintenance_mode":   bool(co["maintenance_mode"]),
            "maintenance_until":  co["maintenance_until"].isoformat() if co["maintenance_until"] else None,
            "maintenance_reason": co["maintenance_reason"],
            "devices":            devices,
        })

    return {"companies": result, "generated_at": now.isoformat()}

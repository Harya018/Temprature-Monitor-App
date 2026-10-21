"""
routers/sensor_owner.py — which company owns this server's sensor feed (hub role).

The Pro-Server live collector, the Excel reader and the global temperature limits belong to
ONE company per server. Until now that was always the oldest company (SRM). Super Admin can
move it to another company; that company's Settings then shows the Live / Excel switches and
receives the live readings.

  GET /api/super-admin/sensor-company        owner of each live source + the companies to choose from
  PUT /api/super-admin/sensor-company        {source: "collector"|"excel", company_id}
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.connection import execute_read, execute_write
from routers.super_admin_v2 import require_super_admin
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/super-admin/sensor-company", tags=["Super Admin — Sensor feed"])


@router.get("")
async def get_sensor_company(_admin: dict = Depends(require_super_admin)):
    from services.sensor_company import SOURCES, get_source_company_id, source_in_use
    companies = execute_read(
        "SELECT id, name FROM companies WHERE COALESCE(is_active, 1) != 0 ORDER BY id")
    from services.sensor_company import get_sensor_company_id
    explicit = execute_read("SELECT 1 FROM app_settings WHERE key = 'sensor_company_id' LIMIT 1")
    return {"sources": {s: {"company_id": get_source_company_id(s), "running": source_in_use(s)} for s in SOURCES},
            "plant": {"company_id": get_sensor_company_id(), "explicit": bool(explicit)},
            "companies": companies}


class _PlantIn(BaseModel):
    company_id: int


@router.put("/plant")
async def set_plant_company(body: _PlantIn, admin: dict = Depends(require_super_admin)):
    """Choose the 'main company' of this PC: the one that owns the sensor feed, the temperature engine, the
    backup button, the imported CSV history and the server's own e-mail account (.env)."""
    import asyncio
    from services.sensor_company import get_sensor_company_id, invalidate_caches
    from services import company_email
    co = execute_read("SELECT id, name FROM companies WHERE id = %s AND COALESCE(is_active, 1) != 0", (body.company_id,))
    if not co:
        raise HTTPException(status_code=404, detail="Company not found or switched off")
    old = get_sensor_company_id()
    if old != body.company_id:
        await asyncio.to_thread(company_email.handover_plant, old, body.company_id)
    execute_write("INSERT INTO app_settings (key, value, updated_at) VALUES ('sensor_company_id', %s, NOW()) "
                  "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()", (str(body.company_id),))
    invalidate_caches()
    try:
        from utils.activity_logger import log_activity
        log_activity(admin.get("id"), "plant_company_changed", "app_settings",
                     f"main company of this PC is now {body.company_id} ({co[0]['name']})", body.company_id)
    except Exception:
        pass
    logger.warning("Main (plant) company set to %s (%s) by super admin %s", body.company_id, co[0]["name"], admin.get("id"))
    return {"status": "saved", "company_id": body.company_id, "company_name": co[0]["name"]}


class _OwnerIn(BaseModel):
    source:     str          # "collector" | "excel"
    company_id: int


@router.put("")
async def set_sensor_company(body: _OwnerIn, admin: dict = Depends(require_super_admin)):
    from services.sensor_company import SOURCES, set_source_company_id
    if body.source not in SOURCES:
        raise HTTPException(status_code=422, detail="source must be 'collector' or 'excel'")
    co = execute_read("SELECT id, name FROM companies WHERE id = %s", (body.company_id,))
    if not co:
        raise HTTPException(status_code=404, detail="Company not found")
    set_source_company_id(body.source, body.company_id)
    try:
        from utils.activity_logger import log_activity
        log_activity(admin.get("id"), "sensor_source_owner_changed", "app_settings",
                     f"{body.source} now belongs to company {body.company_id} ({co[0]['name']})", body.company_id)
    except Exception:
        pass
    logger.warning("Live source %s set to company %s (%s) by super admin %s",
                   body.source, body.company_id, co[0]["name"], admin.get("id"))
    return {"status": "saved", "source": body.source, "company_id": body.company_id, "company_name": co[0]["name"]}

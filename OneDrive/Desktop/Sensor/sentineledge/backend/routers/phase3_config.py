"""
routers/phase3_config.py — Phase 3: Global Configuration Control.

All routes protected by require_super_admin.

Prefix: /api/super-admin/config
Routes:
  GET    /thresholds                              Current global thresholds
  POST   /thresholds                              Set global thresholds
  GET    /templates                               List threshold templates
  POST   /templates                               Create template
  DELETE /templates/{template_id}                 Delete template
  POST   /templates/{template_id}/apply           Apply template globally
  GET    /companies/{company_id}/config            List company config overrides
  POST   /companies/{company_id}/config            Set / update a config field
  DELETE /companies/{company_id}/config/{field}    Remove a config field
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from routers.super_admin import require_super_admin
from utils.activity_logger import log_activity
from utils.logger import get_logger
import config as _config
from config import RUNTIME_THRESHOLDS

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/config", tags=["Super Admin Config"])


# ─── Pydantic bodies ──────────────────────────────────────────────────────────

class _ThresholdIn(BaseModel):
    temp_high: float = Field(gt=0)
    temp_low: float  = Field(gt=0)

    @field_validator("temp_high", "temp_low", mode="before")
    @classmethod
    def must_be_positive(cls, v):
        return float(v)


class _TemplateIn(BaseModel):
    name: str        = Field(min_length=1, max_length=100)
    temp_high: float = Field(gt=0)
    temp_low: float  = Field(gt=0)
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v


class _CompanyConfigIn(BaseModel):
    field: str  = Field(min_length=1, max_length=100)
    value: str  = Field(min_length=0, max_length=500)
    locked: bool = False

    @field_validator("field", "value", mode="before")
    @classmethod
    def strip_str(cls, v):
        return v.strip() if isinstance(v, str) else v


# ─── Global thresholds ────────────────────────────────────────────────────────

@router.get("/thresholds", summary="Get current global thresholds")
async def get_global_thresholds(_: dict = Depends(require_super_admin)):
    return {
        "temp_high":    RUNTIME_THRESHOLDS["temp_high"],
        "temp_low":     RUNTIME_THRESHOLDS["temp_low"],
        "source":       _config.RUNTIME_SOURCE,
        "last_changed": _config.RUNTIME_LAST_CHANGED,
    }


@router.post("/thresholds", summary="Set global thresholds as super admin")
async def set_global_thresholds(
    body: _ThresholdIn,
    sa: dict = Depends(require_super_admin),
):
    if body.temp_low >= body.temp_high:
        return JSONResponse(
            status_code=422,
            content={"error": "temp_low must be less than temp_high"},
        )

    old_high = RUNTIME_THRESHOLDS["temp_high"]
    old_low  = RUNTIME_THRESHOLDS["temp_low"]

    RUNTIME_THRESHOLDS["temp_high"] = body.temp_high
    RUNTIME_THRESHOLDS["temp_low"]  = body.temp_low
    RUNTIME_THRESHOLDS["temperature"]["high"] = body.temp_high
    RUNTIME_THRESHOLDS["temperature"]["low"]  = body.temp_low

    now_iso = datetime.now(timezone.utc).isoformat()
    _config.RUNTIME_SOURCE       = "super_admin_override"
    _config.RUNTIME_LAST_CHANGED = now_iso

    log_activity(
        sa["id"], "global_thresholds_set", "config",
        f"temp_high:{old_high}->{body.temp_high} temp_low:{old_low}->{body.temp_low}",
        None,
    )
    logger.info(
        "Global thresholds updated by super_admin %d: high %s->%s, low %s->%s",
        sa["id"], old_high, body.temp_high, old_low, body.temp_low,
    )

    try:
        from modules.inapp.manager import broadcast as _broadcast
        import asyncio
        asyncio.create_task(_broadcast({
            "type": "config_update",
            "thresholds": {"temp_high": body.temp_high, "temp_low": body.temp_low},
            "source": "super_admin_override",
            "changed_at": now_iso,
        }))
    except Exception as exc:
        logger.warning("config_update broadcast failed: %s", exc)

    return {
        "temp_high":    body.temp_high,
        "temp_low":     body.temp_low,
        "source":       "super_admin_override",
        "last_changed": now_iso,
    }


# ─── Threshold templates ──────────────────────────────────────────────────────

@router.get("/templates", summary="List all threshold templates")
async def list_templates(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """
        SELECT t.id, t.name, t.temp_high, t.temp_low, t.description,
               t.created_by, a.name AS created_by_name, t.created_at
          FROM threshold_templates t
          LEFT JOIN admins a ON a.id = t.created_by
         ORDER BY t.created_at DESC
        """
    )
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return rows


@router.post("/templates", summary="Create a threshold template")
async def create_template(
    body: _TemplateIn,
    sa: dict = Depends(require_super_admin),
):
    if body.temp_low >= body.temp_high:
        return JSONResponse(
            status_code=422,
            content={"error": "temp_low must be less than temp_high"},
        )

    result = execute_write(
        """
        INSERT INTO threshold_templates (name, temp_high, temp_low, description, created_by)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (body.name, body.temp_high, body.temp_low, body.description, sa["id"]),
    )
    template_id = result.lastrowid

    log_activity(
        sa["id"], "template_created", "threshold_templates",
        f"id:{template_id} name:{body.name} high:{body.temp_high} low:{body.temp_low}",
        None,
    )
    logger.info(
        "Super admin %d created threshold template %d (%s)", sa["id"], template_id, body.name
    )
    return {
        "id":          template_id,
        "name":        body.name,
        "temp_high":   body.temp_high,
        "temp_low":    body.temp_low,
        "description": body.description,
    }


@router.delete("/templates/{template_id}", summary="Delete a threshold template")
async def delete_template(
    template_id: int,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, name FROM threshold_templates WHERE id = %s", (template_id,)
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Template not found"})

    execute_write("DELETE FROM threshold_templates WHERE id = %s", (template_id,))
    log_activity(
        sa["id"], "template_deleted", "threshold_templates",
        f"id:{template_id} name:{rows[0]['name']}",
        None,
    )
    return {"deleted": True, "template_id": template_id}


@router.post("/templates/{template_id}/apply", summary="Apply a template as global thresholds")
async def apply_template(
    template_id: int,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, name, temp_high, temp_low FROM threshold_templates WHERE id = %s",
        (template_id,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Template not found"})

    t = rows[0]
    old_high = RUNTIME_THRESHOLDS["temp_high"]
    old_low  = RUNTIME_THRESHOLDS["temp_low"]

    RUNTIME_THRESHOLDS["temp_high"] = t["temp_high"]
    RUNTIME_THRESHOLDS["temp_low"]  = t["temp_low"]
    RUNTIME_THRESHOLDS["temperature"]["high"] = t["temp_high"]
    RUNTIME_THRESHOLDS["temperature"]["low"]  = t["temp_low"]

    now_iso = datetime.now(timezone.utc).isoformat()
    _config.RUNTIME_SOURCE       = f"template:{t['name']}"
    _config.RUNTIME_LAST_CHANGED = now_iso

    log_activity(
        sa["id"], "template_applied", "threshold_templates",
        f"template_id:{template_id} name:{t['name']} high:{old_high}->{t['temp_high']} low:{old_low}->{t['temp_low']}",
        None,
    )
    logger.info(
        "Super admin %d applied template %d (%s): high %s->%s, low %s->%s",
        sa["id"], template_id, t["name"], old_high, t["temp_high"], old_low, t["temp_low"],
    )

    try:
        from modules.inapp.manager import broadcast as _broadcast
        import asyncio
        asyncio.create_task(_broadcast({
            "type": "config_update",
            "thresholds": {"temp_high": t["temp_high"], "temp_low": t["temp_low"]},
            "source": _config.RUNTIME_SOURCE,
            "changed_at": now_iso,
        }))
    except Exception as exc:
        logger.warning("config_update broadcast failed: %s", exc)

    return {
        "applied":      True,
        "template_id":  template_id,
        "template_name": t["name"],
        "temp_high":    t["temp_high"],
        "temp_low":     t["temp_low"],
        "source":       _config.RUNTIME_SOURCE,
        "last_changed": now_iso,
    }


# ─── Company config overrides ─────────────────────────────────────────────────

@router.get("/companies/{company_id}/config", summary="List config overrides for a company")
async def get_company_config(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT cc.id, cc.field, cc.value, cc.locked, cc.set_by,
               a.name AS set_by_name, cc.set_at
          FROM company_config cc
          LEFT JOIN admins a ON a.id = cc.set_by
         WHERE cc.company_id = %s
         ORDER BY cc.field
        """,
        (company_id,),
    )
    for r in rows:
        if r.get("set_at"):
            r["set_at"] = r["set_at"].isoformat()
    return rows


@router.post("/companies/{company_id}/config", summary="Set or update a company config field")
async def set_company_config(
    company_id: int,
    body: _CompanyConfigIn,
    sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    execute_write(
        """
        INSERT INTO company_config (company_id, field, value, locked, set_by, set_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (company_id, field)
        DO UPDATE SET value = EXCLUDED.value,
                      locked = EXCLUDED.locked,
                      set_by = EXCLUDED.set_by,
                      set_at = NOW()
        """,
        (company_id, body.field, body.value, 1 if body.locked else 0, sa["id"]),
    )

    log_activity(
        sa["id"], "company_config_set", "company_config",
        f"company_id:{company_id} field:{body.field} value:{body.value} locked:{body.locked}",
        company_id,
    )
    return {
        "company_id": company_id,
        "field":      body.field,
        "value":      body.value,
        "locked":     body.locked,
    }


@router.delete(
    "/companies/{company_id}/config/{field}",
    summary="Remove a company config override",
)
async def delete_company_config(
    company_id: int,
    field: str,
    sa: dict = Depends(require_super_admin),
):
    result = execute_write(
        "DELETE FROM company_config WHERE company_id = %s AND field = %s",
        (company_id, field),
    )
    if result.rowcount == 0:
        return JSONResponse(status_code=404, content={"error": "Config field not found"})

    log_activity(
        sa["id"], "company_config_removed", "company_config",
        f"company_id:{company_id} field:{field}",
        company_id,
    )
    return {"deleted": True, "company_id": company_id, "field": field}

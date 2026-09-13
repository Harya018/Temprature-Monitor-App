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


# ─── Company Parameters ───────────────────────────────────────────────────────

class _ParamIn(BaseModel):
    company_id: int
    name: str        = Field(min_length=1, max_length=100)
    unit: Optional[str] = Field(default=None, max_length=50)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v


class _ParamUpdateIn(BaseModel):
    unit: Optional[str] = Field(default=None, max_length=50)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    is_active: Optional[bool] = None


def _serialize_param(r: dict) -> dict:
    for ts in ("created_at", "updated_at"):
        if r.get(ts) and hasattr(r[ts], "isoformat"):
            r[ts] = r[ts].isoformat()
    return r


@router.get("/parameters", summary="List active parameters for a company")
async def list_parameters(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT id, company_id, name, unit, min_value, max_value, is_active,
               created_at, updated_at
          FROM company_parameters
         WHERE company_id = %s AND is_active = TRUE
         ORDER BY name
        """,
        (company_id,),
    )
    return [_serialize_param(r) for r in rows]


@router.get("/parameters/{param_id}", summary="Get a single company parameter")
async def get_parameter(
    param_id: int,
    _: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT id, company_id, name, unit, min_value, max_value, is_active,
               created_at, updated_at
          FROM company_parameters WHERE id = %s
        """,
        (param_id,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Parameter not found"})
    return _serialize_param(rows[0])


@router.post("/parameters", status_code=201, summary="Request a new company parameter (creates approval)")
async def request_parameter(
    body: _ParamIn,
    sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (body.company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    import json as _json
    payload = {
        "company_id": body.company_id,
        "name":       body.name,
        "unit":       body.unit,
        "min_value":  body.min_value,
        "max_value":  body.max_value,
    }
    result = execute_write(
        """
        INSERT INTO pending_approvals (admin_id, action_type, payload)
        VALUES (%s, 'add_parameter', %s) RETURNING id
        """,
        (sa["id"], _json.dumps(payload)),
    )
    log_activity(
        sa["id"], "parameter_requested", "company_parameters",
        f"company_id:{body.company_id} name:{body.name}",
        body.company_id,
    )
    logger.info(
        "Super admin %d requested add_parameter '%s' for company %d — approval #%s",
        sa["id"], body.name, body.company_id, result.lastrowid,
    )
    return {
        "status":      "pending",
        "approval_id": result.lastrowid,
        "action_type": "add_parameter",
        "payload":     payload,
    }


@router.patch("/parameters/{param_id}", summary="Update a company parameter (direct, no approval)")
async def update_parameter(
    param_id: int,
    body: _ParamUpdateIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, company_id, name FROM company_parameters WHERE id = %s", (param_id,)
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Parameter not found"})

    sets, params = [], []
    if body.unit is not None:
        sets.append("unit = %s"); params.append(body.unit)
    if body.min_value is not None:
        sets.append("min_value = %s"); params.append(body.min_value)
    if body.max_value is not None:
        sets.append("max_value = %s"); params.append(body.max_value)
    if body.is_active is not None:
        sets.append("is_active = %s"); params.append(body.is_active)
    if not sets:
        return JSONResponse(status_code=422, content={"error": "No fields to update"})

    sets.append("updated_at = NOW()")
    params.append(param_id)
    execute_write(
        f"UPDATE company_parameters SET {', '.join(sets)} WHERE id = %s",
        tuple(params),
    )
    log_activity(
        sa["id"], "parameter_updated", "company_parameters",
        f"param_id:{param_id} name:{rows[0]['name']}",
        rows[0]["company_id"],
    )
    return {"status": "updated", "param_id": param_id}


@router.delete("/parameters/{param_id}", summary="Soft-delete a company parameter")
async def delete_parameter(
    param_id: int,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, company_id, name FROM company_parameters WHERE id = %s", (param_id,)
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Parameter not found"})

    execute_write(
        "UPDATE company_parameters SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
        (param_id,),
    )
    log_activity(
        sa["id"], "parameter_deleted", "company_parameters",
        f"param_id:{param_id} name:{rows[0]['name']}",
        rows[0]["company_id"],
    )
    return {"status": "deleted", "param_id": param_id}


# ─── Companies + Parameters Overview (Config Page) ────────────────────────────

class _DirectParamIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    unit: Optional[str] = Field(default="", max_length=50)
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    @field_validator("name", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _TempThresholdIn(BaseModel):
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class _SamplingIn(BaseModel):
    sampling_interval_seconds: int


@router.get("/companies-params", summary="All companies with parameters and sampling interval")
async def all_companies_params(_: dict = Depends(require_super_admin)):
    from collections import defaultdict
    # sampling_interval_seconds is added by Migration 60 (deferred); fall back
    # gracefully if the column isn't present yet (lock-timeout on first start).
    try:
        companies = execute_read(
            "SELECT id, name, COALESCE(sampling_interval_seconds, 5) AS sampling_interval_seconds "
            "FROM companies ORDER BY name"
        )
    except Exception:
        companies = execute_read("SELECT id, name FROM companies ORDER BY name")
        for c in companies:
            c["sampling_interval_seconds"] = 5
    params = execute_read(
        "SELECT id, company_id, name, unit, min_value, max_value "
        "FROM company_parameters WHERE is_active = TRUE ORDER BY company_id, name"
    )
    temp_cfg = execute_read(
        "SELECT company_id, field, value FROM company_config "
        "WHERE field IN ('temp_high', 'temp_low')"
    )
    params_by_co: dict = defaultdict(list)
    for p in (params or []):
        params_by_co[p["company_id"]].append({
            "id": p["id"], "name": p["name"], "unit": p["unit"] or "",
            "min_value": float(p["min_value"]) if p.get("min_value") is not None else None,
            "max_value": float(p["max_value"]) if p.get("max_value") is not None else None,
            "builtin": False,
        })
    temp_by_co: dict = defaultdict(dict)
    for t in (temp_cfg or []):
        try:
            temp_by_co[t["company_id"]][t["field"]] = float(t["value"])
        except (TypeError, ValueError):
            pass
    result = []
    for co in companies:
        cid = co["id"]
        tt = temp_by_co.get(cid, {})
        result.append({
            "id": cid, "name": co["name"],
            "sampling_interval_seconds": co["sampling_interval_seconds"],
            "parameters": [
                {"id": None, "name": "Temperature", "unit": "°C",
                 "min_value": tt.get("temp_low"), "max_value": tt.get("temp_high"),
                 "builtin": True}
            ] + params_by_co.get(cid, []),
        })
    return result


@router.post("/companies/{company_id}/parameters/direct", status_code=201,
             summary="Directly add a parameter to a company (no approval)")
async def add_parameter_direct(
    company_id: int, body: _DirectParamIn, sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})
    result = execute_write(
        """
        INSERT INTO company_parameters (company_id, name, unit, min_value, max_value, is_active)
        VALUES (%s, %s, %s, %s, %s, TRUE)
        ON CONFLICT (company_id, name)
        DO UPDATE SET unit=EXCLUDED.unit, min_value=EXCLUDED.min_value,
                      max_value=EXCLUDED.max_value, is_active=TRUE, updated_at=NOW()
        RETURNING id
        """,
        (company_id, body.name, body.unit or "", body.min_value, body.max_value),
    )
    log_activity(sa["id"], "parameter_added", "company_parameters",
                 f"company_id:{company_id} name:{body.name}", company_id)
    return {"status": "created", "param_id": result.lastrowid}


@router.put("/companies/{company_id}/temperature",
            summary="Set per-company temperature thresholds")
async def set_company_temperature(
    company_id: int, body: _TempThresholdIn, sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})
    for field, val in [("temp_high", body.max_value), ("temp_low", body.min_value)]:
        if val is not None:
            execute_write(
                """
                INSERT INTO company_config (company_id, field, value, locked, set_by, set_at)
                VALUES (%s, %s, %s, 0, %s, NOW())
                ON CONFLICT (company_id, field)
                DO UPDATE SET value=EXCLUDED.value, set_by=EXCLUDED.set_by, set_at=NOW()
                """,
                (company_id, field, str(val), sa["id"]),
            )
    log_activity(sa["id"], "company_temp_threshold_set", "company_config",
                 f"company_id:{company_id}", company_id)
    return {"ok": True}


@router.put("/companies/{company_id}/sampling",
            summary="Set sampling interval for a company")
async def set_company_sampling(
    company_id: int, body: _SamplingIn, sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})
    interval = max(1, min(body.sampling_interval_seconds, 86400))
    try:
        execute_write(
            "UPDATE companies SET sampling_interval_seconds=%s WHERE id=%s",
            (interval, company_id),
        )
    except Exception:
        return JSONResponse(status_code=503,
                            content={"error": "sampling_interval_seconds column not ready yet — retry after server restart"})
    log_activity(sa["id"], "company_sampling_set", "companies",
                 f"company_id:{company_id} interval:{interval}s", company_id)
    return {"ok": True, "sampling_interval_seconds": interval}

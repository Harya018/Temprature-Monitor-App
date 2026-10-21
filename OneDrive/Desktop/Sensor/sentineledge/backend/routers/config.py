"""
routers/config.py — /api/config endpoints.

Additions:
  - Addition 6:  POST /api/config/thresholds logs audit trail
  - Addition 10: POST endpoints protected by require_admin
  - Addition 11: GET /api/config/thresholds returns detailed source info
                 POST /api/config/thresholds/reset resets to defaults
"""

import logging
from datetime import datetime, timezone

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import database
from config import (
    RUNTIME_THRESHOLDS,
    DEFAULT_THRESHOLDS,
    VAPID_PUBLIC_KEY,
)
import config as _config
from middleware.auth import require_admin
from models import ThresholdConfigIn, ThresholdConfigOut, ThresholdConfigDetailOut


class AlertSettingsIn(BaseModel):
    temp_alerts_enabled: Optional[bool]  = None
    ph_alerts_enabled:   Optional[bool]  = None
    ph_threshold_max:    Optional[float] = None
    ph_threshold_min:    Optional[float] = None
    ph_threshold:        Optional[float] = None  # legacy alias → treated as ph_threshold_max

router = APIRouter(prefix="/api")
logger = logging.getLogger("sentineledge.routers.config")


def _own_limits(company_id) -> dict:
    """{parameter: (min, max, alerts_enabled)} from this company's own Settings."""
    rows = database.execute_read(
        "SELECT LOWER(name) AS n, min_value, max_value, COALESCE(alerts_enabled, TRUE) AS en "
        "FROM company_parameters WHERE company_id = %s AND is_active = TRUE", (company_id,)) or []
    return {r["n"]: (r["min_value"], r["max_value"], bool(r["en"])) for r in rows}


def _who(admin: dict) -> str:
    """Name of the admin making a change (for the change history)."""
    try:
        r = database.execute_read("SELECT name FROM admins WHERE id = %s", (admin.get("admin_id"),))
        return r[0]["name"] if r else "admin"
    except Exception:
        return "admin"


@router.get("/config/thresholds")
async def get_thresholds(admin: dict = Depends(require_admin)):
    """
    Return current thresholds with source info (Addition 11).
    The sensor company sees the plant's values; every other company sees its own.
    """
    from services.sensor_company import owns_sensor_feed
    if not owns_sensor_feed(admin.get("company_id")):
        t = _own_limits(admin.get("company_id")).get("temperature")
        return {
            "temperature": {"high": float(t[1]) if t and t[1] is not None else None,
                            "low":  float(t[0]) if t and t[0] is not None else None,
                            "unit": "°C", "name": "Temperature"},
            "source": "company_settings",
            "last_changed": None,
        }
    return {
        "temperature": {
            "high": RUNTIME_THRESHOLDS["temp_high"],
            "low":  RUNTIME_THRESHOLDS["temp_low"],
            "unit": "°C",
            "name": "Temperature",
        },
        "source": _config.RUNTIME_SOURCE,
        "last_changed": _config.RUNTIME_LAST_CHANGED,
    }


@router.post(
    "/config/thresholds",
    response_model=ThresholdConfigOut,
)
async def update_thresholds(body: ThresholdConfigIn, admin: dict = Depends(require_admin)):
    """Update runtime thresholds and log changes (Additions 6 + 10).
    These are the live sensor's temperature limits, so only the company that
    owns the sensor feed may change them."""
    from services.sensor_company import owns_sensor_feed, get_sensor_company_id
    if not owns_sensor_feed(admin.get("company_id")):
        raise HTTPException(status_code=403, detail="These thresholds belong to another company's sensor")
    fields = {
        "temp_high": body.temp_high,
        "temp_low":  body.temp_low,
    }
    for field, new_val in fields.items():
        old_val = RUNTIME_THRESHOLDS[field]
        if old_val != new_val:
            database.log_config_change(
                changed_by=_who(admin),
                field_name=field,
                old_value=str(old_val),
                new_value=str(new_val),
            )
            RUNTIME_THRESHOLDS[field] = new_val
        # Always persist to DB so the value survives a server restart
        database.execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (f"threshold_{field}", str(new_val)),
        )

    _config.RUNTIME_SOURCE = "runtime_override"
    _config.RUNTIME_LAST_CHANGED = datetime.now(timezone.utc).isoformat()
    logger.info("Thresholds updated at runtime: %s", RUNTIME_THRESHOLDS)

    # Keep the sensor company's 'temperature' parameter limits in step
    try:
        database.execute_write(
            "UPDATE company_parameters SET min_value = %s, max_value = %s, updated_at = NOW() "
            "WHERE company_id = %s AND LOWER(name) = 'temperature'",
            (RUNTIME_THRESHOLDS["temp_low"], RUNTIME_THRESHOLDS["temp_high"], get_sensor_company_id()),
        )
    except Exception as exc:
        logger.warning("Could not sync temperature parameter limits: %s", exc)

    # Broadcast to all WebSocket clients (mobile app + web)
    try:
        from modules.inapp.manager import broadcast as _broadcast
        await _broadcast({
            "type":         "config_update",
            "thresholds": {
                "temp_high": RUNTIME_THRESHOLDS["temp_high"],
                "temp_low":  RUNTIME_THRESHOLDS["temp_low"],
            },
            "source":       _config.RUNTIME_SOURCE,
            "changed_at":   _config.RUNTIME_LAST_CHANGED,
        }, company_id=get_sensor_company_id())
    except Exception as exc:
        logger.warning("config_update broadcast failed: %s", exc)

    return ThresholdConfigOut(**RUNTIME_THRESHOLDS)


@router.post(
    "/config/thresholds/reset",
)
async def reset_thresholds(admin: dict = Depends(require_admin)):
    """
    Reset RUNTIME_THRESHOLDS back to the values from .env (Addition 11).
    Logs each changed field. Only the company that owns the sensor feed may do this.
    """
    from services.sensor_company import owns_sensor_feed, get_sensor_company_id
    if not owns_sensor_feed(admin.get("company_id")):
        raise HTTPException(status_code=403, detail="These thresholds belong to another company's sensor")
    for field, default_val in DEFAULT_THRESHOLDS.items():
        old_val = RUNTIME_THRESHOLDS[field]
        if old_val != default_val:
            database.log_config_change(
                changed_by=_who(admin),
                field_name=field,
                old_value=str(old_val),
                new_value=str(default_val),
            )
            RUNTIME_THRESHOLDS[field] = default_val

    _config.RUNTIME_SOURCE = "default"
    _config.RUNTIME_LAST_CHANGED = datetime.now(timezone.utc).isoformat()
    logger.info("Thresholds reset to defaults: %s", RUNTIME_THRESHOLDS)

    # Broadcast reset to all WebSocket clients
    try:
        from modules.inapp.manager import broadcast as _broadcast
        await _broadcast({
            "type":       "config_update",
            "thresholds": {
                "temp_high": RUNTIME_THRESHOLDS["temp_high"],
                "temp_low":  RUNTIME_THRESHOLDS["temp_low"],
            },
            "source":     _config.RUNTIME_SOURCE,
            "changed_at": _config.RUNTIME_LAST_CHANGED,
        }, company_id=get_sensor_company_id())
    except Exception as exc:
        logger.warning("config_update broadcast failed: %s", exc)

    return {
        "status": "reset",
        "thresholds": {
            "temperature": {
                "high": RUNTIME_THRESHOLDS["temp_high"],
                "low":  RUNTIME_THRESHOLDS["temp_low"],
            },
        },
        "source": _config.RUNTIME_SOURCE,
    }


@router.get("/config/vapid-public-key")
async def get_vapid_public_key():
    return {"vapid_public_key": VAPID_PUBLIC_KEY}


@router.get("/config/alert-settings")
async def get_alert_settings(admin: dict = Depends(require_admin)):
    """Return alert enable/disable flags and the pH min/max thresholds
    (the plant's for the sensor company, each company's own for everyone else)."""
    from services.sensor_company import owns_sensor_feed
    if not owns_sensor_feed(admin.get("company_id")):
        own = _own_limits(admin.get("company_id"))
        ph, tp = own.get("ph"), own.get("temperature")
        return {
            "temp_alerts_enabled": tp[2] if tp else False,
            "ph_alerts_enabled":   ph[2] if ph else False,
            "ph_threshold_max":    float(ph[1]) if ph and ph[1] is not None else 7.0,
            "ph_threshold_min":    float(ph[0]) if ph and ph[0] is not None else 5.5,
        }
    return {
        "temp_alerts_enabled": RUNTIME_THRESHOLDS.get("temp_alerts_enabled", True),
        "ph_alerts_enabled":   RUNTIME_THRESHOLDS.get("ph_alerts_enabled",   True),
        "ph_threshold_max":    RUNTIME_THRESHOLDS.get("ph_threshold_max",    7.0),
        "ph_threshold_min":    RUNTIME_THRESHOLDS.get("ph_threshold_min",    5.5),
    }


@router.post("/config/alert-settings")
async def update_alert_settings(body: AlertSettingsIn, admin: dict = Depends(require_admin)):
    """Enable/disable temperature or pH alerts, or change the pH threshold.
    These switches are server-wide, so only the company that owns the sensor feed may change them
    (every other company sets its own limits per parameter in Settings)."""
    from services.sensor_company import owns_sensor_feed
    if not owns_sensor_feed(admin.get("company_id")):
        raise HTTPException(status_code=403, detail="These alert settings belong to another company's sensor")
    if body.temp_alerts_enabled is not None:
        RUNTIME_THRESHOLDS["temp_alerts_enabled"] = body.temp_alerts_enabled
        database.log_config_change(
            changed_by=_who(admin),
            field_name="temp_alerts_enabled",
            old_value=str(not body.temp_alerts_enabled),
            new_value=str(body.temp_alerts_enabled),
        )
        database.execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("alert_temp_enabled", str(body.temp_alerts_enabled)),
        )
    if body.ph_alerts_enabled is not None:
        RUNTIME_THRESHOLDS["ph_alerts_enabled"] = body.ph_alerts_enabled
        database.log_config_change(
            changed_by=_who(admin),
            field_name="ph_alerts_enabled",
            old_value=str(not body.ph_alerts_enabled),
            new_value=str(body.ph_alerts_enabled),
        )
        database.execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("alert_ph_enabled", str(body.ph_alerts_enabled)),
        )
    # ph_threshold_max (also accept legacy ph_threshold as alias)
    new_max = body.ph_threshold_max if body.ph_threshold_max is not None else body.ph_threshold
    if new_max is not None:
        RUNTIME_THRESHOLDS["ph_threshold_max"] = new_max
        database.log_config_change(
            changed_by=_who(admin), field_name="ph_threshold_max",
            old_value="", new_value=str(new_max),
        )
        database.execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("alert_ph_threshold_max", str(new_max)),
        )
    if body.ph_threshold_min is not None:
        RUNTIME_THRESHOLDS["ph_threshold_min"] = body.ph_threshold_min
        database.log_config_change(
            changed_by=_who(admin), field_name="ph_threshold_min",
            old_value="", new_value=str(body.ph_threshold_min),
        )
        database.execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("alert_ph_threshold_min", str(body.ph_threshold_min)),
        )
    logger.info("Alert settings saved to DB: %s", {
        "temp_alerts_enabled": RUNTIME_THRESHOLDS.get("temp_alerts_enabled"),
        "ph_alerts_enabled":   RUNTIME_THRESHOLDS.get("ph_alerts_enabled"),
        "ph_threshold_min":    RUNTIME_THRESHOLDS.get("ph_threshold_min"),
        "ph_threshold_max":    RUNTIME_THRESHOLDS.get("ph_threshold_max"),
    })
    return {
        "temp_alerts_enabled": RUNTIME_THRESHOLDS.get("temp_alerts_enabled", True),
        "ph_alerts_enabled":   RUNTIME_THRESHOLDS.get("ph_alerts_enabled",   True),
        "ph_threshold_max":    RUNTIME_THRESHOLDS.get("ph_threshold_max",    7.0),
        "ph_threshold_min":    RUNTIME_THRESHOLDS.get("ph_threshold_min",    5.5),
    }

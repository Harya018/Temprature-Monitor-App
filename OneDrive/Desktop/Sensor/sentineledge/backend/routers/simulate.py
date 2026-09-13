"""
routers/simulate.py — /api/simulate/* endpoints.

POST /api/simulate/breach  — force a HIGH threshold breach for N ticks (testing)
POST /api/simulate/demo    — start accelerated CSV playback (demo)
POST /api/simulate/reset   — stop demo mode, rewind to start of data

Rate limiting (slowapi):
  POST /api/simulate/breach → 5/minute per IP
  POST /api/simulate/demo   → 10/minute per IP
"""

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import core.sensor as sensor
import core.threshold as threshold
import core.escalation as escalation
import database
from middleware.auth import require_admin
from middleware.rate_limit import limiter
from modules.inapp.manager import broadcast
from utils.logger import get_logger
from utils.time import now_iso
from config import ALERT_COOLDOWN_SECONDS

logger = get_logger("routers.simulate")

_IS_PRODUCTION = os.getenv("APP_ENV", "development").lower() == "production"


def _require_non_production() -> None:
    """Raise 403 if running in production — demo endpoints are dev/staging only."""
    if _IS_PRODUCTION:
        raise HTTPException(status_code=403, detail="This endpoint is not available in production")

router = APIRouter(prefix="/api", tags=["Testing"])


# ─── Breach simulation ────────────────────────────────────────────────────────

_BREACH_TEMP   = 92.0   # °C — above the 90.0°C HIGH threshold
_RECOVERY_TEMP = 55.0   # °C — well above LOW threshold, clears breach state


async def _inject_reading(temperature: float, *, label: str = "", extra_params: dict | None = None) -> list:
    """
    Inject a synthetic reading DIRECTLY into the pipeline — no spike validation.

    Writes to DB, runs threshold check, broadcasts over WebSocket,
    fires escalation tasks if any thresholds are breached.
    Returns the list of BreachEvent objects (may be empty).
    """
    ep = extra_params or {}
    reading = {"temperature": temperature, "timestamp": now_iso(), "extra_params": ep}

    # 1. Persist to database (marked valid=True — it's intentional)
    database.insert_reading(temperature, reading["timestamp"], is_valid=True, extra_params=ep)

    # 2. Threshold check
    breaches = threshold.check_threshold(reading)

    # 3. Persist alerts (fast — awaited so the WS payload below can include
    # each breach's real alert_id; notification delivery still happens in
    # the background inside trigger_alert() and is never awaited here).
    alert_ids = await escalation.trigger_alert(reading, breaches) if breaches else []

    # 4. Update health last_reading
    try:
        import routers.health as _health_mod
        _health_mod.last_reading = {
            "temperature": reading["temperature"],
            "timestamp":   reading["timestamp"],
        }
    except Exception:
        pass

    # 5. Broadcast to all WebSocket clients
    breach_dicts = []
    for b, aid in zip(breaches, alert_ids):
        d = b.model_dump()
        d["alert_id"] = aid
        breach_dicts.append(d)

    payload = {
        "temperature": reading["temperature"],
        "timestamp":   reading["timestamp"],
        "breaches":    breach_dicts,
        "is_valid":    True,
    }
    await broadcast(payload)

    if label:
        logger.info(
            "Injected %s reading: %.1f°C — %d breach(es)",
            label, temperature, len(breaches),
        )
    return breaches


@router.post(
    "/simulate/breach",
    summary="Simulate a threshold breach",
    description=(
        "Directly injects a 92.0°C reading into the alert pipeline, "
        "BYPASSING spike validation (since this is an intentional test trigger). "
        "Writes to DB, triggers threshold check, broadcasts via WebSocket, "
        "fires email/SMS/in-app alerts. "
        "After the configured cooldown, automatically injects a recovery reading. "
        "Requires admin auth. Rate limited to 5/min."
    ),
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def simulate_breach(request: Request):
    # Inject breach reading immediately
    breaches = await _inject_reading(_BREACH_TEMP, label="breach")

    # Schedule recovery after cooldown (non-blocking)
    asyncio.create_task(
        _schedule_recovery(ALERT_COOLDOWN_SECONDS),
        name="sim-recovery",
    )

    logger.info(
        "simulate/breach: injected %.1f°C — %d breach(es) fired, "
        "recovery scheduled in %ds",
        _BREACH_TEMP, len(breaches), ALERT_COOLDOWN_SECONDS,
    )

    return {
        "status":              "injected",
        "message":             f"92.0°C reading injected directly — bypassed spike validator",
        "temperature":         _BREACH_TEMP,
        "breaches_fired":      len(breaches),
        "recovery_in_seconds": ALERT_COOLDOWN_SECONDS,
    }


async def _schedule_recovery(wait_seconds: int) -> None:
    """Wait, then inject a recovery reading so the chart returns to normal."""
    await asyncio.sleep(wait_seconds)
    await _inject_reading(_RECOVERY_TEMP, label="recovery")
    logger.info("Breach simulation recovery complete.")


_PH_TEST_VALUE = 7.5555   # above the 7.0 production threshold


@router.post(
    "/simulate/ph-breach",
    summary="Simulate a pH threshold breach",
    description=(
        "Injects a synthetic pH=7.5555 reading into the alert pipeline. "
        "Fires threshold check, alert creation, email/SMS/in-app notifications. "
        "Requires admin auth. Rate limited to 5/min."
    ),
    dependencies=[Depends(require_admin)],
)
@limiter.limit("5/minute")
async def simulate_ph_breach(request: Request):
    # Use current temperature so the reading looks realistic
    try:
        import core.excel_sensor as _excel
        temp = _excel.current_temperature or 25.0
    except Exception:
        temp = 25.0

    breaches = await _inject_reading(
        temp,
        label="ph-breach",
        extra_params={"PH": _PH_TEST_VALUE},
    )
    logger.info(
        "simulate/ph-breach: injected pH=%.4f — %d breach(es) fired",
        _PH_TEST_VALUE, len(breaches),
    )
    return {
        "status":         "injected",
        "ph_value":       _PH_TEST_VALUE,
        "breaches_fired": len(breaches),
        "message":        f"pH {_PH_TEST_VALUE} injected — threshold check fired",
    }


# ─── Demo playback ────────────────────────────────────────────────────────────

class DemoSpeedIn(BaseModel):
    speed: int = Field(
        default=30,
        ge=1,
        le=100,
        description=(
            "Playback speed multiplier. "
            "1 = real time (~2.5 hrs), "
            "30 = ~5 min, "
            "50 = ~3 min."
        ),
    )


@router.post(
    "/simulate/demo",
    summary="Start accelerated demo playback",
    description=(
        "Rewinds to the first CSV reading and plays back at the requested speed. "
        "Not available in production (APP_ENV=production). "
        "Requires admin auth. Rate limited to 10/min."
    ),
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def simulate_demo(body: DemoSpeedIn, request: Request):
    _require_non_production()
    result = sensor.activate_demo(speed=body.speed)
    return result


# ─── Reset ───────────────────────────────────────────────────────────────────

@router.post(
    "/simulate/reset",
    summary="Reset sensor to beginning of data",
    description=(
        "Stops demo mode and rewinds CSV playback to the very first reading. "
        "Not available in production (APP_ENV=production). "
        "Requires admin auth."
    ),
    dependencies=[Depends(require_admin)],
)
async def simulate_reset():
    _require_non_production()
    return sensor.reset_sensor()

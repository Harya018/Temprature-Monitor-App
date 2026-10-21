"""
services/live_ingest.py — the one path a REAL live reading takes.

Used by every real source (Pro-Server EX live collector, the Excel reader's new rows,
OPC DA, a USB sensor): keep only the company's approved parameters, store the reading,
check each parameter against THAT company's own limits, raise alerts (which notify only
that company's subscribers), update the company's dashboards, and write the company's
own CSV table and activity log.

Nothing simulated or historical goes through here — callers pass only readings that were
just measured.
"""

from __future__ import annotations

import time
from typing import Optional

import database
import core.escalation as escalation
import core.threshold as threshold
from core.validator import validate_reading
from models import BreachEvent
from modules.inapp.manager import broadcast
from services import company_log
from utils.logger import get_logger

logger = get_logger(__name__)

PARAM_COOLDOWN_S = 300              # one alert per company / parameter / direction per 5 minutes
_param_cache: dict = {}             # company_id -> (expires, {lower name: row})
_cooldowns: dict = {}               # (company_id, name, direction) -> monotonic time of last alert


def _company_parameters(company_id) -> dict:
    """The company's active parameters by lower-case name (cached 20 s)."""
    hit = _param_cache.get(company_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from database.connection import execute_read
    rows = execute_read(
        "SELECT name, unit, min_value, max_value, COALESCE(alerts_enabled, TRUE) AS alerts_enabled "
        "FROM company_parameters WHERE company_id = %s AND is_active = TRUE", (company_id,))
    params = {str(r["name"]).lower(): r for r in rows}
    _param_cache[company_id] = (time.monotonic() + 20, params)
    return params


def forget_parameters(company_id=None) -> None:
    """Call after a company's parameters / limits change so they apply at once."""
    if company_id is None:
        _param_cache.clear()
    else:
        _param_cache.pop(company_id, None)


def _approved_parameters(company_id) -> set:
    return set(_company_parameters(company_id))


def _limit_breaches(company_id, values: dict, params: dict) -> list:
    """BreachEvents for every value outside its company's own min / max (alerts switched on)."""
    out = []
    now = time.monotonic()
    for name, value in values.items():
        cfg = params.get(name)
        if not cfg or not cfg["alerts_enabled"]:
            continue
        mn, mx = cfg["min_value"], cfg["max_value"]
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        direction = limit = None
        if mx is not None and value > float(mx):
            direction, limit = "high", float(mx)
        elif mn is not None and value < float(mn):
            direction, limit = "low", float(mn)
        if direction is None:
            continue
        key = (company_id, name, direction)
        if now - _cooldowns.get(key, -1e9) < PARAM_COOLDOWN_S:
            continue
        _cooldowns[key] = now
        try:
            sev = threshold._get_severity(value, limit, direction)
        except Exception:
            sev = "WARNING"
        out.append(BreachEvent(parameter=name, value=value, threshold=limit, direction=direction, severity=sev))
    return out


def _fmt(temp, ep: dict) -> str:
    parts = ([f"temperature={temp}"] if temp is not None else []) + [f"{k}={v}" for k, v in ep.items()]
    return ", ".join(parts) or "-"


async def ingest(reading: dict, extra: Optional[dict], company_id, *,
                 message_type: Optional[str] = None, extra_payload: Optional[dict] = None,
                 source: str = "sensor") -> dict:
    """Process one live reading. `reading` has temperature (may be None) + timestamp;
    `extra` holds the other parameters (pH, pressure, …) by name."""
    params = _company_parameters(company_id)
    # Only APPROVED parameters are kept. Extra columns in the plant's file (or collector) are
    # ignored until Super Admin approves them — they are never added automatically.
    from utils.column_match import match_parameter
    ep: dict = {}
    for k, v in sorted((extra or {}).items(), key=lambda kv: 0 if str(kv[0]).lower() in params else 1):   # an exact name wins
        if v is None:
            continue
        name = match_parameter(k, params)                 # "pH Value", "PH (pH)", "ph_value" -> ph
        if name and name != "temperature" and name not in ep:
            ep[name] = v
    reading = dict(reading)
    if "temperature" not in params:
        reading["temperature"] = None                     # e.g. a pH-only company
    if reading.get("temperature") is None and not ep:
        return {"valid": True, "stored": False}           # nothing this company has approved

    has_temp = reading.get("temperature") is not None
    is_valid, reason = validate_reading(reading, company_id) if has_temp else (True, "")

    database.insert_reading(reading["temperature"], reading["timestamp"],
                            is_valid=is_valid, extra_params=ep, company_id=company_id)

    base = {"timestamp": reading["timestamp"], "extra_params": ep, **(extra_payload or {})}
    if message_type:
        base["type"] = message_type

    if not is_valid:
        logger.warning("Invalid reading skipped: %s", reason)
        company_log.log(company_id, f"Reading rejected ({source}): {reason}", 30)
        await broadcast({**base, "temperature": reading["temperature"], "breaches": [],
                         "is_valid": False, "validation_error": reason}, company_id=company_id)
        return {"valid": False, "reason": reason}

    # ── limits: each parameter against THIS company's own settings ────────────
    breaches: list = []
    if has_temp and params.get("temperature", {}).get("alerts_enabled", True):
        from services.sensor_company import get_sensor_company_id
        if company_id == get_sensor_company_id():
            # The PC's main company keeps the full temperature engine (severity tiers, cooling-cycle
            # reset); its limits are the company's own temperature parameter, kept in step here.
            tp = params.get("temperature", {})
            if tp.get("min_value") is not None and tp.get("max_value") is not None:
                from config import RUNTIME_THRESHOLDS
                hi, lo = float(tp["max_value"]), float(tp["min_value"])
                if RUNTIME_THRESHOLDS.get("temp_high") != hi or RUNTIME_THRESHOLDS.get("temp_low") != lo:
                    RUNTIME_THRESHOLDS["temp_high"], RUNTIME_THRESHOLDS["temp_low"] = hi, lo
                    RUNTIME_THRESHOLDS.setdefault("temperature", {})
                    RUNTIME_THRESHOLDS["temperature"]["high"], RUNTIME_THRESHOLDS["temperature"]["low"] = hi, lo
            breaches += threshold.check_threshold({**reading, "extra_params": {}})
        else:
            breaches += _limit_breaches(company_id, {"temperature": reading["temperature"]}, params)
    breaches += _limit_breaches(company_id, ep, params)

    reading["extra_params"] = ep
    # Persist alerts first so the broadcast carries each breach's real alert_id (the mobile app
    # acknowledges by id). Notifications go out in the background — to this company only.
    alert_ids = await escalation.trigger_alert(reading, breaches, company_id) if breaches else []

    import routers.health as _health_mod
    _health_mod.last_reading = {"temperature": reading["temperature"], "timestamp": reading["timestamp"]}

    breach_dicts = []
    for b, aid in zip(breaches, alert_ids):
        if aid is None:
            continue
        d = b.model_dump()
        d["alert_id"] = aid
        breach_dicts.append(d)
        company_log.log(company_id, f"ALERT #{aid}: {b.parameter} {b.value} is {b.direction.upper()} "
                                    f"(limit {b.threshold}, {b.severity})", 30)

    await broadcast({**base, "temperature": reading["temperature"], "breaches": breach_dicts,
                     "is_valid": True}, company_id=company_id)

    company_log.log(company_id, f"Reading ({source}) {reading['timestamp']}: {_fmt(reading['temperature'], ep)}")
    from services.reading_csv import append_reading
    append_reading(reading["timestamp"], reading["temperature"], ep, source, company_id)
    return {"valid": True, "breaches": len(breach_dicts)}

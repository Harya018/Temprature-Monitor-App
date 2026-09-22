"""
core/threshold.py — SentinelEdge threshold checker.

Handles two distinct threshold layers:

1. check_threshold(reading) — temperature high/low + pH min/max.
   Reads RUNTIME_THRESHOLDS (config.py). Returns list[BreachEvent].
   Cooling-cycle direction logic prevents duplicate LOW alerts per run.

2. auto_register_extra_params(ep, company_id) — ensures every live
   custom sensor parameter exists in company_parameters (ON CONFLICT DO NOTHING).

3. check_extra_param_thresholds(extra_params, breach_dicts) — reads
   min/max from company_parameters and appends alert dicts to breach_dicts
   for any out-of-range custom parameters. 5-minute flat cooldown per param.

BREACH BOUNDARY (strict):
  temperature > HIGH  → high breach   (exactly HIGH is NOT a breach)
  temperature < LOW   → low breach    (exactly LOW  is NOT a breach)

Severity levels:
  WARNING   — value within 0-10% beyond threshold
  CRITICAL  — value within 10-25% beyond threshold
  EMERGENCY — value more than 25% beyond threshold
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone, timedelta

from config import RUNTIME_THRESHOLDS, ALERT_COOLDOWN_SECONDS, MODULE_STATUS, is_alert_enabled
from models import BreachEvent
from utils.logger import get_logger

_logger = get_logger(__name__)

# ─── Severity bands ───────────────────────────────────────────────────────────
_WARNING_PCT: float  = 0.05
_CRITICAL_PCT: float = 0.10
_EMERGENCY_PCT: float= 0.25

# Temperature above which the LOW-direction alert is "reset" for the next run.
# When machine heats back above this after a cooling cycle,
# we know a new run has started.
_LOW_DIRECTION_RESET_TEMP: float = 60.0


def _get_severity(value: float, threshold: float, direction: str) -> str:
    """
    Compute breach severity based on how far the value exceeds the threshold.
    Returns "WARNING", "CRITICAL", or "EMERGENCY".
    """
    if threshold == 0:
        return "WARNING"
    if direction == "high":
        pct = (value - threshold) / abs(threshold)
    else:
        pct = (threshold - value) / abs(threshold)

    if pct >= _EMERGENCY_PCT:
        return "EMERGENCY"
    elif pct >= _CRITICAL_PCT:
        return "CRITICAL"
    else:
        return "WARNING"


# ─── Cooldown tracker: keyed by direction ────────────────────────────────────
cooldown_tracker: dict[str, datetime | None] = {
    "temperature_high": None,
    "temperature_low":  None,
    "ph_high":          None,
    "ph_low":           None,
}

# ─── Direction tracker: prevents duplicate LOW alerts per cooling run ─────────
# Tracks whether the LOW direction has already fired in the current run.
# Reset when temperature rises back above _LOW_DIRECTION_RESET_TEMP.
last_breach_direction: dict[str, str | None] = {
    "temperature": None,   # last direction that fired: "high" | "low" | None
}


def check_threshold(reading: dict) -> list[BreachEvent]:
    """
    Compare a reading against current RUNTIME_THRESHOLDS (temperature only).

    Parameters
    ----------
    reading : dict
        Must contain 'temperature' (float).

    Returns
    -------
    list[BreachEvent]
        One entry per threshold currently breached and not in cooldown.
        Returns an empty list when no threshold is breached.
    """
    now = datetime.now(timezone.utc)
    cooldown_delta = timedelta(seconds=ALERT_COOLDOWN_SECONDS)
    breaches: list[BreachEvent] = []

    # ── Temperature checks ────────────────────────────────────────────────────
    if is_alert_enabled("temperature"):
        temp  = reading["temperature"]
        t_high = RUNTIME_THRESHOLDS["temp_high"]
        t_low  = RUNTIME_THRESHOLDS["temp_low"]

        # Reset LOW direction when machine heats back up (new cooling run)
        if temp > _LOW_DIRECTION_RESET_TEMP:
            last_breach_direction["temperature"] = None

        for parameter, value, threshold, direction in [
            ("temperature", temp, t_high, "high"),
            ("temperature", temp, t_low,  "low"),
        ]:
            if direction == "high" and value <= threshold:
                continue
            if direction == "low"  and value >= threshold:
                continue

            # Suppress duplicate LOW alert within the same cooling run
            if direction == "low" and last_breach_direction.get(parameter) == "low":
                continue

            key = f"{parameter}_{direction}"
            last_trigger = cooldown_tracker.get(key)
            if last_trigger is not None and (now - last_trigger) < cooldown_delta:
                continue

            severity = _get_severity(value, threshold, direction)
            cooldown_tracker[key] = now
            last_breach_direction[parameter] = direction
            breaches.append(BreachEvent(
                parameter=parameter, value=value,
                threshold=threshold, direction=direction, severity=severity,
            ))

    # ── pH range check (min / max) ─────────────────────────────────────────────
    if is_alert_enabled("ph"):
        extra = reading.get("extra_params") or {}
        ph_raw = next((v for k, v in extra.items() if k.lower() == "ph"), None)
        if ph_raw is not None:
            try:
                ph_val = float(ph_raw)
            except (TypeError, ValueError):
                ph_val = None

            if ph_val is not None:
                ph_max = float(RUNTIME_THRESHOLDS.get("ph_threshold_max", 7.0))
                ph_min = float(RUNTIME_THRESHOLDS.get("ph_threshold_min", 5.5))

                # HIGH breach: pH above maximum threshold
                if ph_val > ph_max:
                    key = "ph_high"
                    last_trigger = cooldown_tracker.get(key)
                    if last_trigger is None or (now - last_trigger) >= cooldown_delta:
                        cooldown_tracker[key] = now
                        breaches.append(BreachEvent(
                            parameter="ph",
                            value=ph_val,
                            threshold=ph_max,
                            direction="high",
                            severity=_get_severity(ph_val, ph_max, "high"),
                        ))

                # LOW breach: pH below minimum threshold
                if ph_val < ph_min:
                    key = "ph_low"
                    last_trigger = cooldown_tracker.get(key)
                    if last_trigger is None or (now - last_trigger) >= cooldown_delta:
                        cooldown_tracker[key] = now
                        breaches.append(BreachEvent(
                            parameter="ph",
                            value=ph_val,
                            threshold=ph_min,
                            direction="low",
                            severity=_get_severity(ph_val, ph_min, "low"),
                        ))

    # Update module status once we've processed at least one reading
    if "sensor" not in MODULE_STATUS or MODULE_STATUS.get("sensor") == "starting":
        MODULE_STATUS["sensor"] = "ok"

    return breaches


# ─── Custom / extra-parameter helpers ────────────────────────────────────────

# Cache so we don't hammer the DB with ON CONFLICT inserts every cycle.
_registered_params: set = set()

# Per-parameter cooldown: {param_name: monotonic_epoch}
_extra_param_cooldowns: dict = {}
_EXTRA_PARAM_COOLDOWN = 300  # 5 minutes between repeated alerts per param


def auto_register_extra_params(ep: dict, company_id: int) -> None:
    """Ensure every live extra-sensor parameter exists in company_parameters.

    Uses ON CONFLICT DO UPDATE so rows disabled by an admin get re-activated
    when the sensor starts sending them again.  Cached in _registered_params
    to avoid DB round-trips on every reading cycle.
    """
    from database.connection import execute_write as _ew
    for name in ep:
        key = (company_id, name)
        if key in _registered_params:
            continue
        try:
            _ew(
                """INSERT INTO company_parameters (company_id, name, is_active)
                   VALUES (%s, %s, TRUE)
                   ON CONFLICT (company_id, name) DO UPDATE SET is_active = TRUE
                   WHERE company_parameters.is_active = FALSE""",
                (company_id, name),
            )
            _registered_params.add(key)
        except Exception:
            pass


def check_extra_param_thresholds(extra_params: dict, breach_dicts: list) -> None:
    """Check custom-parameter readings against company_parameters min/max.

    Fetches configured ranges from company_parameters, inserts an alert row
    for any value outside [min_value, max_value], and appends it to
    breach_dicts so the caller can include it in the WebSocket payload.
    Uses a 5-minute per-parameter cooldown to prevent alert floods.
    """
    import database

    now = _time.monotonic()
    try:
        from database.connection import execute_read
        params = execute_read(
            "SELECT name, unit, min_value, max_value, company_id "
            "FROM company_parameters WHERE is_active = TRUE"
        )
    except Exception:
        return

    param_map = {p["name"]: p for p in (params or [])}

    for name, value in extra_params.items():
        cfg = param_map.get(name)
        if cfg is None:
            continue

        mn = cfg.get("min_value")
        mx = cfg.get("max_value")
        if mn is None or mx is None:
            continue

        try:
            mn_f, mx_f = float(mn), float(mx)
        except (TypeError, ValueError):
            continue

        if mn_f <= value <= mx_f:
            continue  # within range

        last_fired = _extra_param_cooldowns.get(name, 0)
        if now - last_fired < _EXTRA_PARAM_COOLDOWN:
            continue

        direction = "high" if value > mx_f else "low"
        threshold_val = mx_f if direction == "high" else mn_f
        cooldown_until = (
            datetime.now(timezone.utc) + timedelta(seconds=_EXTRA_PARAM_COOLDOWN)
        ).isoformat()

        try:
            alert_id = database.insert_alert(
                parameter=name,
                value=value,
                threshold=threshold_val,
                direction=direction,
                cooldown_until=cooldown_until,
                severity="WARNING",
                company_id=cfg.get("company_id"),
            )
            _extra_param_cooldowns[name] = now
            _logger.info(
                "Custom param alert: %s=%.3f %s threshold %.3f (alert_id=%s)",
                name, value, direction, threshold_val, alert_id,
            )
            breach_dicts.append({
                "parameter": name,
                "value":     value,
                "threshold": threshold_val,
                "direction": direction,
                "severity":  "WARNING",
                "alert_id":  alert_id,
            })
        except Exception as exc:
            _logger.warning("Failed to insert custom param alert for %s: %s", name, exc)

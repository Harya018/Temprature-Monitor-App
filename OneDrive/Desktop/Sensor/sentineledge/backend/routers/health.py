"""
routers/health.py — /api/health endpoint.

Returns status, timestamp, uptime_seconds, and a modules dict.
No credential values (passwords, usernames, etc.) are ever included.

Rate limiting (slowapi): 120/minute per IP (mobile app polls frequently).

SMS modem probe:
    A background thread probes the SIM7600 serial port every 30 seconds and
    caches the result.  /api/health reads from the cache — it never blocks
    on serial I/O.  Possible cached values:

        "live"          — modem found AND responded to AT with OK
        "not_connected" — no SIM7600-like port found on any COM port
        "error"         — port found but did not respond to AT command
        "unknown"       — probe has not run yet (startup grace period)
"""

import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request

import config
from config import MODULE_STATUS
from middleware.rate_limit import limiter
import database

router = APIRouter(prefix="/api")
logger = logging.getLogger("sentineledge.routers.health")

# Server start time for uptime calculation
_START_TIME = datetime.now(timezone.utc)

# Last sensor reading — updated by main.py WebSocket handler
last_reading: dict = {}


# ── SMS modem probe cache ──────────────────────────────────────────────────────

_sms_probe_lock   = threading.Lock()
_sms_probe_result = "unknown"   # "live" | "not_connected" | "error" | "unknown"
_sms_probe_ts     = 0.0         # epoch seconds of last completed probe

# Shared flag: sim7600_sender sets this True while a send is in progress so
# the probe skips that cycle (avoids opening the port concurrently).
# Imported lazily to avoid circular-import at module load.
_SMS_IS_SENDING_ATTR = "_gsm_send_in_progress"   # attribute name on the sender module


def _is_sms_sending() -> bool:
    """Return True if the GSM sender is currently holding the serial port."""
    try:
        import modules.sms.sim7600_sender as _s  # type: ignore
        return bool(getattr(_s, _SMS_IS_SENDING_ATTR, False))
    except Exception:
        return False


def _run_sms_probe() -> str:
    """
    Probe the SIM7600 modem once.

    Steps:
      1. Scan COM ports for SIM7600 keywords.
      2. For each candidate, open at 115200 baud, send b"AT\\r\\n",
         wait up to 3 seconds for "OK", close port immediately.
      3. Return "live" on first successful probe, "not_connected" if no
         candidates found, or "error" if candidates exist but none respond.

    Never raises.
    """
    try:
        import serial          # type: ignore
        import serial.tools.list_ports  # type: ignore
    except ImportError:
        return "not_connected"

    _SIM76XX_KW = ("sim7600", "sim76", "simcom", "qualcomm hs-usb", "at command")

    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception:
        return "not_connected"

    candidates = [
        p for p in ports
        if any(kw in (p.description or "").lower() or
               kw in (getattr(p, "manufacturer", None) or "").lower()
               for kw in _SIM76XX_KW)
    ]

    baud = getattr(config, "SMS_SIM7600_BAUD", 115200)

    if not candidates:
        # Brute-force: driver may use generic description ("USB Serial Device").
        # Probe all non-sensor ports with AT — accept the first that replies "OK".
        _SENSOR_KW = ("ch340", "cp210", "ft232", "arduino", "ftdi", "prolific",
                      "silicon labs", "audio", "microphone", "headset")
        for p in sorted(ports, key=lambda p: p.device):
            desc = (p.description or "").lower()
            if any(kw in desc for kw in _SENSOR_KW):
                continue
            ser = None
            try:
                ser = serial.Serial(port=p.device, baudrate=baud,
                                    timeout=1.5, write_timeout=1.5)
                ser.reset_input_buffer()
                ser.write(b"AT\r\n")
                deadline = time.monotonic() + 1.5
                response = ""
                while time.monotonic() < deadline:
                    time.sleep(0.05)
                    chunk = ser.read(ser.in_waiting or 32).decode("utf-8", errors="replace")
                    if chunk:
                        response += chunk
                    if "OK" in response:
                        return "live"
            except Exception:
                pass
            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
        return "not_connected"

    # Sort: prefer "at command" or "at" in description
    def _rank(p):
        d = (p.description or "").lower()
        if "at command" in d:
            return 0
        if " at " in d or d.startswith("at ") or d.endswith(" at"):
            return 1
        return 2
    candidates.sort(key=_rank)

    for p in candidates:
        ser = None
        try:
            ser = serial.Serial(port=p.device, baudrate=baud,
                                timeout=3.0, write_timeout=3.0)
            ser.reset_input_buffer()
            ser.write(b"AT\r\n")
            deadline = time.monotonic() + 3.0
            response = ""
            while time.monotonic() < deadline:
                time.sleep(0.05)
                chunk = ser.read(ser.in_waiting or 32).decode("utf-8", errors="replace")
                if chunk:
                    response += chunk
                if "OK" in response:
                    return "live"
        except Exception:
            pass
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    return "error"


def _sms_probe_loop() -> None:
    """Background thread: probe SIM7600 on startup then every 30 seconds."""
    global _sms_probe_result, _sms_probe_ts

    # First probe runs immediately (no initial delay)
    while True:
        if not _is_sms_sending():
            result = _run_sms_probe()
            with _sms_probe_lock:
                _sms_probe_result = result
                _sms_probe_ts     = time.monotonic()
            logger.debug("SMS modem probe result: %s", result)
        else:
            logger.debug("SMS modem probe skipped — send in progress")

        time.sleep(30)


# Start background probe thread at module import time.
# daemon=True ensures it doesn't block server shutdown.
_sms_probe_thread = threading.Thread(
    target=_sms_probe_loop,
    daemon=True,
    name="sms-modem-probe",
)
_sms_probe_thread.start()


# ── Status helpers ─────────────────────────────────────────────────────────────

def _overall_status() -> str:
    """
    Compute overall system status:
      "ok"       — all built modules reporting ok
      "degraded" — at least one built module in error
      "error"    — database or sensor is down
    """
    critical = {MODULE_STATUS.get("database"), MODULE_STATUS.get("sensor")}
    if any(s and s.startswith("error") for s in critical):
        return "error"

    has_error = any(
        v.startswith("error")
        for v in MODULE_STATUS.values()
        if v and v != "not_built"
    )
    return "degraded" if has_error else "ok"


def _probe_database() -> str:
    """Try a lightweight SELECT 1 through the pool. Returns 'ok' or 'error'."""
    try:
        from database.connection import execute_read
        execute_read("SELECT 1")
        return "ok"
    except Exception as exc:
        logger.warning("health: db probe failed: %s", exc)
        return "error"


def _probe_email() -> str:
    """Return 'configured' if SMTP_HOST and SMTP_USER are set, else 'not configured'."""
    if config.SMTP_HOST and config.SMTP_USER:
        return "configured"
    return "not configured"


def _probe_sms() -> str:
    """
    Return the cached SIM7600 modem probe result for sim7600 SMS method.

    For other SMS methods, return a descriptive static string (unchanged
    from the original behaviour so non-sim7600 setups are unaffected).
    """
    method = (config.SMS_METHOD or "").lower().strip()

    if method == "sim7600":
        with _sms_probe_lock:
            return _sms_probe_result     # "live" | "not_connected" | "error" | "unknown"

    if method == "gammu":
        return "configured"             # USB GSM dongle (non-SIM7600 path)
    if method == "adb":
        return "adb mode"
    if method == "gateway":
        return "gateway mode"
    return "not configured"


def _probe_websocket() -> str:
    """Return 'ok (N clients)' based on live connection count."""
    try:
        from modules.inapp.manager import active_connections
        count = len(active_connections)
        return f"ok ({count} client{'s' if count != 1 else ''} connected)"
    except Exception:
        return "ok"


def _probe_sensor() -> str:
    """Return 'live' or 'csv fallback' based on actual AdaptiveSensorReader state."""
    try:
        from core.sensor import player
        return "live" if player.is_live else "csv fallback"
    except Exception:
        return "unknown"


@router.get("/health")
@limiter.limit("120/minute")
async def health(request: Request):
    """Health check — returns status, timestamp, uptime_seconds, and module probes."""
    db_status     = _probe_database()
    email_status  = _probe_email()
    sms_status    = _probe_sms()
    ws_status     = _probe_websocket()
    sensor_status = _probe_sensor()

    alerts_today = database.get_alerts_today_count()

    return {
        "status":         _overall_status(),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - _START_TIME).total_seconds()),
        "alerts_today":   alerts_today,
        "modules": {
            "database":  {"status": db_status},
            "email":     {"status": email_status},
            "sms":       {"status": sms_status},
            "websocket": {"status": ws_status},
            "sensor":    {"status": sensor_status},
        },
    }

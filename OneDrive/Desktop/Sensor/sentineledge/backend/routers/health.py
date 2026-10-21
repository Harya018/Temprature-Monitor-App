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
from typing import Optional

import config
from config import MODULE_STATUS
from middleware.auth import require_admin
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
_sms_probe_port: Optional[str] = None   # COM port that answered AT, when live

# Sensor is shown as live only if the collector delivered a reading this recently
SENSOR_LIVE_WINDOW_S = 120

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
                        _remember_port(p.device)
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
                    _remember_port(p.device)
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


def _remember_port(device: str) -> None:
    global _sms_probe_port
    with _sms_probe_lock:
        _sms_probe_port = device


def _sms_probe_loop() -> None:
    """Background thread: probe SIM7600 on startup then every 30 seconds."""
    global _sms_probe_result, _sms_probe_ts, _sms_probe_port

    # First probe runs immediately (no initial delay)
    while True:
        if not _is_sms_sending():
            result = _run_sms_probe()
            with _sms_probe_lock:
                _sms_probe_result = result
                _sms_probe_ts     = time.monotonic()
                if result != "live":
                    _sms_probe_port = None
            logger.debug("SMS modem probe result: %s", result)
        else:
            logger.debug("SMS modem probe skipped — send in progress")

        time.sleep(30)


_sms_probe_thread: threading.Thread | None = None


def start_sms_probe() -> None:
    """Start the background SMS modem probe thread. Call once from lifespan startup."""
    global _sms_probe_thread
    if _sms_probe_thread is not None and _sms_probe_thread.is_alive():
        return
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


def _probe_sms() -> dict:
    """
    SMS module status for the Health page.

    sim7600: "connected" only when the background probe got "OK" to an AT
    command from the GSM modem; "not connected" when no modem answered;
    "checking" before the first probe has finished.
    Other methods keep a descriptive status (they cannot be probed).
    """
    method = (config.SMS_METHOD or "").lower().strip()

    if method == "sim7600":
        with _sms_probe_lock:
            raw, port = _sms_probe_result, _sms_probe_port
        if raw == "live":
            return {"status": "connected", "detail": f"GSM modem on {port}" if port else "GSM modem responding", "port": port}
        if raw == "unknown":
            return {"status": "checking", "detail": "Probing GSM modem…", "port": None}
        detail = "No GSM modem found on any COM port" if raw == "not_connected" else "Modem port found but it did not answer AT"
        return {"status": "not connected", "detail": detail, "port": None}

    if method == "gammu":
        return {"status": "configured", "detail": "Gammu USB dongle (not probed)", "port": None}
    if method == "adb":
        return {"status": "adb mode", "detail": "Android phone over ADB", "port": None}
    if method == "gateway":
        return {"status": "gateway mode", "detail": "SMS gateway app", "port": None}
    return {"status": "not configured", "detail": "SMS_METHOD not set", "port": None}


def _probe_websocket() -> str:
    """Return 'ok (N clients)' based on live connection count."""
    try:
        from modules.inapp.manager import active_connections
        count = len(active_connections)
        return f"ok ({count} client{'s' if count != 1 else ''} connected)"
    except Exception:
        return "ok"


def _probe_sensor(company_id=None) -> dict:
    """
    What feeds THIS company's dashboard right now. There is no demo / CSV playback in production:
      live        the Pro-Server EX live collector sent a reading in the last 2 minutes
      excel live  the Excel reader is on and new rows are arriving in the file
      no data     a live source is switched on but nothing new is arriving (the detail says why)
      no source   this company has no live source switched on
    Each company is shown only the source it owns (the collector / Excel reader on a shared PC can
    belong to different companies). company_id None = platform level: any source.
    """
    from services.sensor_company import get_source_company_id, get_sensor_company_id, collector_installed
    mine = lambda src: company_id is None or get_source_company_id(src) == company_id
    waiting = None            # a switched-on source that is not delivering

    # 1) Pro-Server EX live collector
    try:
        from services.data_sources import collector_enabled
        if collector_installed() and collector_enabled() and mine("collector"):
            from services.live_collector import state
            age = None
            if state.last_received_at:
                age = (datetime.now() - datetime.fromisoformat(state.last_received_at)).total_seconds()
            if age is not None and age <= SENSOR_LIVE_WINDOW_S:
                return {"status": "live", "source": "Live collector (Pro-Server EX)",
                        "detail": f"Last reading {int(age)} s ago", "last_reading_at": state.last_received_at,
                        "age_seconds": int(age)}
            if age is None:
                why = "Collector has not sent any reading since the server started"
            elif age < 3600:
                why = f"No collector reading for {int(age // 60)} min {int(age % 60)} s"
            else:
                why = f"No collector reading for {age / 3600:.1f} h"
            waiting = {"status": "no data", "source": "Live collector (Pro-Server EX)", "detail": why,
                       "last_reading_at": state.last_received_at, "age_seconds": int(age) if age is not None else None}
    except Exception:
        pass

    # 2) Excel reader (independent switch in Settings)
    try:
        import core.excel_sensor as xs
        if xs.EXCEL_LIVE_ENABLED and mine("excel"):
            fname = (xs.EXCEL_FILE_PATH or "").replace("\\", "/").rsplit("/", 1)[-1] or "the Excel file"
            if not xs.is_active() or (xs.current_temperature is None and not xs.extra_readings):
                return waiting or {"status": "no data", "source": "Excel file",
                                   "detail": f"Cannot read {fname} - check the file path in Settings",
                                   "last_reading_at": None, "age_seconds": None}
            st = xs.get_enabled_status()
            if not st["in_loop_mode"]:
                return {"status": "excel live", "source": "Excel file",
                        "detail": f"New rows arriving in {fname}", "last_reading_at": st["last_new_row_at"],
                        "age_seconds": None}
            return waiting or {"status": "no data", "source": "Excel file",
                               "detail": f"Excel reader is on but no new row has been added to {fname} - check the logger",
                               "last_reading_at": st["last_new_row_at"], "age_seconds": None}
    except Exception:
        pass

    # 3) A directly attached USB sensor (the PC's plant company only)
    try:
        from core.sensor import player
        if player.is_live and (company_id is None or company_id == get_sensor_company_id()):
            return {"status": "live", "source": "USB sensor", "detail": "USB sensor streaming",
                    "last_reading_at": None, "age_seconds": None}
    except Exception:
        pass

    if waiting:
        return waiting
    return {"status": "no source", "source": "None",
            "detail": "No live source is switched on for your company. Switch on the live collector or the Excel reader in Settings.",
            "last_reading_at": None, "age_seconds": None}


def _resolve_token(request: Request) -> Optional[dict]:
    """Return the admin session dict if a valid Bearer token is present, else None."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            try:
                return require_admin(authorization=auth)
            except Exception:
                pass
    return None


@router.get("/health")
@limiter.limit("120/minute")
async def health(request: Request):
    """
    Health check endpoint.

    Unauthenticated callers (uptime monitors) receive only platform-level
    status — no sensor data, no alert counts, no module internals.

    Authenticated admins receive the full module detail view.
    """
    session = _resolve_token(request)
    overall = _overall_status()
    now     = datetime.now(timezone.utc)

    base = {
        "status":         overall,
        "timestamp":      now.isoformat(),
        "uptime_seconds": int((now - _START_TIME).total_seconds()),
    }

    if session is None:
        return base

    db_status     = _probe_database()
    email_status  = _probe_email()
    sms_status    = _probe_sms()
    ws_status     = _probe_websocket()
    sensor_status = _probe_sensor(session.get("company_id"))
    alerts_today  = database.get_alerts_today_count(session.get("company_id"))

    return {
        **base,
        "alerts_today": alerts_today,
        "modules": {
            "database":  {"status": db_status},
            "email":     {"status": email_status},
            "sms":       sms_status,
            "websocket": {"status": ws_status},
            "sensor":    sensor_status,
        },
        "gsm_modem": {
            "mode": "live" if sms_status["status"] == "connected" else "mock",
            "port": sms_status.get("port"),
        },
    }

"""
routers/health.py — /api/health endpoint.

Returns status, timestamp, uptime_seconds, and a modules dict.
No credential values (passwords, usernames, etc.) are ever included.

Rate limiting (slowapi): 120/minute per IP (mobile app polls frequently).
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request

import config
from config import MODULE_STATUS
from middleware.rate_limit import limiter

router = APIRouter(prefix="/api")
logger = logging.getLogger("sentineledge.routers.health")

# Server start time for uptime calculation
_START_TIME = datetime.now(timezone.utc)

# Last sensor reading — updated by main.py WebSocket handler
last_reading: dict = {}


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
    """Map SMS_METHOD to a human-readable status string."""
    method = (config.SMS_METHOD or "").lower().strip()
    if method == "gammu":
        return "configured"          # USB GSM dongle (production path)
    if method == "adb":
        return "adb mode"            # Android phone via USB
    if method == "gateway":
        return "gateway mode"        # Android SMS Gateway REST API
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
    """Return 'demo mode' or 'live' based on DEMO_MODE flag — no hardware ping."""
    return "demo mode" if config.DEMO_MODE else "live"


@router.get("/health")
@limiter.limit("120/minute")
async def health(request: Request):
    """Health check — returns status, timestamp, uptime_seconds, and module probes."""
    db_status     = _probe_database()
    email_status  = _probe_email()
    sms_status    = _probe_sms()
    ws_status     = _probe_websocket()
    sensor_status = _probe_sensor()

    return {
        "status":         _overall_status(),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - _START_TIME).total_seconds()),
        "modules": {
            "database":  {"status": db_status},
            "email":     {"status": email_status},
            "sms":       {"status": sms_status},
            "websocket": {"status": ws_status},
            "sensor":    {"status": sensor_status},
        },
    }

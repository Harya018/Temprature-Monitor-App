"""
routers/collector.py — HTTP receiver for the Pro-Server EX live collector.

The collector script running on COE_AT Admin PC POSTs each reading here.
The backend validates the API key, stores the reading, and broadcasts it
to all connected WebSocket clients.

Endpoints:
  POST /api/collector/reading   — called by proserver_collector.py
  GET  /api/collector/status    — dashboard / admin status check
"""

from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/collector", tags=["Collector"])

# Shared secret between the collector script and this backend.
# Override with the COLLECTOR_API_KEY environment variable.
_API_KEY = os.environ.get("COLLECTOR_API_KEY", "proserver-live-2024")

# The collector runs on the same PC as the backend, so by default only
# loopback may post readings. Add other collector IPs (comma-separated) via
# COLLECTOR_ALLOWED_IPS if a collector ever runs on a different machine.
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_ALLOWED_IPS = _LOOPBACK | {
    ip.strip() for ip in os.environ.get("COLLECTOR_ALLOWED_IPS", "").split(",") if ip.strip()
}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ── Pydantic model ─────────────────────────────────────────────────────────────

class CollectorReading(BaseModel):
    api_key:     str
    timestamp:   str
    temperature: Optional[float] = None
    pressure:    Optional[float] = None
    ph:          Optional[float] = None
    source:      Optional[str]   = "proserver"
    extra:       Optional[dict]  = None   # any additional symbols


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/reading")
async def receive_reading(body: CollectorReading, request: Request):
    """
    Called by proserver_collector.py on the COE_AT Admin PC.
    Validates the API key, records the reading, and broadcasts via WebSocket.
    """
    source_ip = _client_ip(request)
    if source_ip not in _ALLOWED_IPS:
        logger.warning("[Collector] Rejected reading from non-allowed IP %s", source_ip)
        raise HTTPException(status_code=403, detail="Collector IP not allowed")
    if not hmac.compare_digest(body.api_key.encode(), _API_KEY.encode()):
        logger.warning("[Collector] Invalid API key from %s", source_ip)
        raise HTTPException(status_code=401, detail="Invalid API key")

    from services.live_collector import state

    data = {
        "timestamp":   body.timestamp,
        "temperature": body.temperature,
        "pressure":    body.pressure,
        "ph":          body.ph,
        "source":      body.source or "proserver",
    }
    if body.extra:
        data["extra"] = body.extra

    state.record(data, source_ip)

    # Collector switched off in Settings: keep its status up to date, but don't
    # feed its readings to the dashboard, the database or the CSV table.
    from services.data_sources import collector_enabled
    if not collector_enabled():
        return {"ok": True, "received": body.timestamp, "used": False,
                "reason": "Live collector is switched off in Settings"}

    if body.temperature is None and body.ph is None and body.pressure is None and not body.extra:
        return {"ok": True, "received": body.timestamp, "used": False, "reason": "reading has no values"}

    # A real live reading: store it, check limits, raise alerts, update dashboards, CSV table
    from services.live_ingest import ingest
    from services.sensor_company import get_source_company_id
    params = {"pressure": body.pressure, "ph": body.ph, **(body.extra or {})}
    await ingest({"temperature": body.temperature, "timestamp": body.timestamp}, params,
                 get_source_company_id("collector"),            # the company that owns the live collector message_type="live_collector_reading", source=data["source"],
                 extra_payload={"pressure": body.pressure, "ph": body.ph, "source": data["source"],
                                "sequence": state.total_received})

    logger.debug(
        "[Collector] %s → T=%s  P=%s  pH=%s",
        source_ip, body.temperature, body.pressure, body.ph,
    )
    return {"ok": True, "received": body.timestamp}


@router.get("/status")
async def get_collector_status(
    request: Request,
    authorization: Optional[str] = Header(default=None),
):
    """Return the latest reading and connection health.
    Open to the local machine (collector --test); otherwise needs an admin token."""
    if _client_ip(request) not in _LOOPBACK:
        from middleware.auth import require_admin
        from fastapi import HTTPException as _HE
        from services.sensor_company import get_source_company_id
        adm = require_admin(authorization)   # raises 401 if missing/invalid
        if adm.get("role") != "super_admin" and adm.get("company_id") != get_source_company_id("collector"):
            raise _HE(status_code=403, detail="The live collector belongs to another company")
    from services.live_collector import state
    return state.get_status()

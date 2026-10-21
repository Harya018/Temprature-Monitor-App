"""
modules/inapp/manager.py — WebSocket connection manager.

Manages the set of active WebSocket connections and provides
the broadcast helper used by the /ws endpoint in main.py.

Each connection remembers the company of the login that opened it, so a
broadcast can be limited to one company: live readings from this server's
sensor reach only the sensor company's dashboards, never another company's.
Connections with no company (platform / super admin) receive everything.
"""

import json
import logging
from typing import Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger("sentineledge.inapp.manager")

# Shared mutable set of live WebSocket connections.
active_connections: Set[WebSocket] = set()
# WebSocket -> company_id of its login (None = platform-level, sees all)
_conn_company: Dict[WebSocket, Optional[int]] = {}

# Mark WebSocket module as ready at import time
from config import MODULE_STATUS as _MS  # noqa: E402
_MS["websocket"] = "ok"

_ALL = object()   # broadcast(..., company_id=_ALL) → every connection


async def broadcast(payload: dict, company_id=_ALL) -> None:
    """Send JSON payload to connected clients.
    company_id omitted → everyone; an int → that company's connections plus
    platform-level ones; None → platform-level connections only."""
    if not active_connections:
        return
    message = json.dumps(payload)
    dead: Set[WebSocket] = set()
    for ws in list(active_connections):
        if company_id is not _ALL:
            conn_cid = _conn_company.get(ws)
            if conn_cid is not None and conn_cid != company_id:
                continue
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    active_connections.difference_update(dead)
    for ws in dead:
        _conn_company.pop(ws, None)


async def close_company_connections(company_id: int) -> None:
    """Disconnect every live dashboard / app of a company that was removed."""
    for ws in list(active_connections):
        if _conn_company.get(ws) == company_id:
            try:
                await ws.close(code=4001, reason="Company removed")
            except Exception:
                pass
            active_connections.discard(ws)
            _conn_company.pop(ws, None)


def add_connection(ws: WebSocket, company_id: Optional[int] = None) -> None:
    """Register a new WebSocket client and the company it belongs to."""
    active_connections.add(ws)
    _conn_company[ws] = company_id
    logger.info("WebSocket client connected. Total: %d", len(active_connections))


def remove_connection(ws: WebSocket) -> None:
    """Remove a WebSocket client on disconnect."""
    active_connections.discard(ws)
    _conn_company.pop(ws, None)
    logger.info("WebSocket cleaned up. Remaining: %d", len(active_connections))

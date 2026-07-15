"""
modules/inapp/manager.py — WebSocket connection manager.

Manages the set of active WebSocket connections and provides
the broadcast helper used by the /ws endpoint in main.py.
"""

import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger("sentineledge.inapp.manager")

# Shared mutable set of live WebSocket connections.
active_connections: Set[WebSocket] = set()

# Mark WebSocket module as ready at import time
from config import MODULE_STATUS as _MS  # noqa: E402
_MS["websocket"] = "ok"


async def broadcast(payload: dict) -> None:
    """Send JSON payload to all currently connected WebSocket clients."""
    if not active_connections:
        return
    message = json.dumps(payload)
    dead: Set[WebSocket] = set()
    for ws in list(active_connections):
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    active_connections.difference_update(dead)


def add_connection(ws: WebSocket) -> None:
    """Register a new WebSocket client."""
    active_connections.add(ws)
    logger.info("WebSocket client connected. Total: %d", len(active_connections))


def remove_connection(ws: WebSocket) -> None:
    """Remove a WebSocket client on disconnect."""
    active_connections.discard(ws)
    logger.info("WebSocket cleaned up. Remaining: %d", len(active_connections))

"""
services/outbox.py — node-side store-and-forward queue.

Anything the node wants the hub to know (an alert, a daily summary, a parameter
request …) is written to the local `outbox` table first, in the same database
as the event itself. The sync agent sends the rows to the hub and deletes each
one only after the hub confirms it. If the hub or the network is down, rows
simply wait — nothing is lost and nothing blocks the node.
"""

from __future__ import annotations

import json
from typing import Any

from utils.logger import get_logger

logger = get_logger(__name__)

MAX_QUEUE = 100_000   # safety cap: oldest rows are dropped beyond this


def enqueue(kind: str, payload: Any) -> None:
    """Queue one item for the hub. Never raises (must not break the caller)."""
    import config
    if config.SERVER_ROLE != "node":
        return
    try:
        from database.connection import execute_write
        execute_write(
            "INSERT INTO outbox (kind, payload) VALUES (%s, %s::jsonb)",
            (kind, json.dumps(payload, default=str)),
        )
        from services import node_agent
        node_agent.agent.wake()
    except Exception as exc:
        logger.warning("outbox enqueue(%s) failed: %s", kind, exc)


def pending_count() -> int:
    try:
        from database.connection import execute_read
        r = execute_read("SELECT COUNT(*) AS n FROM outbox")
        return int(r[0]["n"]) if r else 0
    except Exception:
        return -1


def trim_if_needed() -> None:
    try:
        from database.connection import execute_write
        execute_write(
            "DELETE FROM outbox WHERE id <= (SELECT MAX(id) - %s FROM outbox)", (MAX_QUEUE,)
        )
    except Exception:
        pass

"""
services/node_events.py — the hub's connection log for company servers (hub role only).

Records who connected, went offline, came back, sent data, had their licence changed or
was disconnected, so "what happened to company X's server and when" is always answerable
(Super Admin → company → Connection log, and the hub's log file).
"""

from __future__ import annotations

import asyncio
from typing import Optional

from database.connection import execute_read, execute_write
from utils.logger import get_logger

logger = get_logger(__name__)

OFFLINE_AFTER_S = 90          # no heartbeat for this long → logged as offline (heartbeat is every 15 s)
CHECK_EVERY_S   = 30


def log_event(company_id: int, event: str, detail: Optional[str] = None) -> None:
    """Never raises — logging must not break the request that triggered it."""
    try:
        execute_write("INSERT INTO node_events (company_id, event, detail) VALUES (%s, %s, %s)",
                      (company_id, event, detail))
        logger.info("node event: company %s %s%s", company_id, event, f" — {detail}" if detail else "")
    except Exception as exc:
        logger.warning("could not record node event %s for company %s: %s", event, company_id, exc)


def recent(company_id: int, limit: int = 60) -> list:
    rows = execute_read(
        "SELECT id, at, event, detail FROM node_events WHERE company_id = %s ORDER BY id DESC LIMIT %s",
        (company_id, limit))
    for r in rows:
        r["at"] = r["at"].isoformat()
    return rows


def check_offline_once() -> int:
    """Log 'offline' for paired nodes that stopped sending heartbeats (once per outage)."""
    rows = execute_read(
        """SELECT n.company_id, n.last_seen_at FROM nodes n
            WHERE n.key_hash IS NOT NULL AND n.last_seen_at < NOW() - (%s || ' seconds')::interval
              AND COALESCE((SELECT e.event FROM node_events e WHERE e.company_id = n.company_id
                             ORDER BY e.id DESC LIMIT 1), '') NOT IN ('offline', 'revoked')""",
        (str(OFFLINE_AFTER_S),))
    for r in rows:
        log_event(r["company_id"], "offline", f"no heartbeat since {r['last_seen_at'].isoformat()}")
    return len(rows)


async def watch_nodes() -> None:
    """Background task on the hub."""
    while True:
        await asyncio.sleep(CHECK_EVERY_S)
        try:
            await asyncio.to_thread(check_offline_once)
        except Exception as exc:
            logger.warning("node offline check failed: %s", exc)

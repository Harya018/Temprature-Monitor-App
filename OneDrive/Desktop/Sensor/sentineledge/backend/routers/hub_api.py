"""
routers/hub_api.py — the hub's HTTP API for company nodes (hub role only).

A node is a company's own server with its own database. It only ever makes
OUTGOING calls to these endpoints (over the local network or Tailscale), so the
hub never has to reach into the company's network.

  GET  /api/hub/ping        who are you? (used to check the hub address before pairing)
  POST /api/hub/register    pairing code -> long-lived node key
  POST /api/hub/heartbeat   "I'm alive" + status summary; returns anything for the node
  POST /api/hub/ingest      batch of queued items (alerts, summaries, requests …)

Authentication after pairing: header X-Node-Key. Only a SHA-256 hash of the key
is stored on the hub, so a database leak does not expose working keys.
"""

import hashlib
import json
import secrets
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from services import node_events
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/hub", tags=["Hub"])

HEARTBEAT_ONLINE_S = 60   # seen within this long → node counts as online


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_node(x_node_key: Optional[str] = Header(default=None)) -> dict:
    """Dependency: the calling node, identified by its key. Returns {company_id}."""
    if not x_node_key:
        raise HTTPException(status_code=401, detail="Missing X-Node-Key")
    rows = execute_read(
        "SELECT company_id FROM nodes WHERE key_hash = %s LIMIT 1", (_sha(x_node_key.strip()),)
    )
    if not rows:
        raise HTTPException(status_code=401, detail="Unknown or revoked node key")
    return {"company_id": rows[0]["company_id"]}


# ── pairing ──────────────────────────────────────────────────────────────────

class _RegisterIn(BaseModel):
    pairing_code: str = Field(min_length=8, max_length=40)
    node_name:    Optional[str] = Field(default=None, max_length=100)
    version:      Optional[str] = Field(default=None, max_length=40)


@router.get("/ping")
async def hub_ping():
    """Unauthenticated: confirms this is a SentinelEdge hub (no data returned)."""
    return {"service": "sentineledge-hub", "ok": True}


@router.post("/register")
@limiter.limit("10/minute")
async def register_node(body: _RegisterIn, request: Request):
    """Exchange a one-time pairing code (from Super Admin) for the node key."""
    code = body.pairing_code.strip().upper().replace(" ", "").replace("-", "")
    rows = execute_read(
        """SELECT n.company_id, c.name, c.slug
             FROM nodes n JOIN companies c ON c.id = n.company_id
            WHERE n.pairing_hash = %s AND n.pairing_expires > NOW()
            LIMIT 1""",
        (_sha(code),),
    )
    if not rows:
        logger.warning("Node pairing refused from %s (bad or expired code)",
                       request.client.host if request.client else "?")
        raise HTTPException(status_code=403, detail="Pairing code is invalid or has expired")

    company = rows[0]
    node_key = secrets.token_hex(32)
    ip = request.client.host if request.client else None
    execute_write(
        """UPDATE nodes
              SET key_hash = %s, pairing_hash = NULL, pairing_expires = NULL,
                  node_name = %s, node_version = %s, paired_at = NOW(),
                  last_seen_at = NOW(), last_ip = %s
            WHERE company_id = %s""",
        (_sha(node_key), body.node_name, body.version, ip, company["company_id"]),
    )
    logger.info("Node paired: company %s (%s) from %s", company["company_id"], company["name"], ip)
    node_events.log_event(company["company_id"], "paired", f"{body.node_name or 'node'} from {ip}")
    return {
        "node_key": node_key,       # shown once; only its hash is kept here
        "company": {"id": company["company_id"], "name": company["name"], "slug": company["slug"]},
    }


# ── heartbeat ────────────────────────────────────────────────────────────────

class _HeartbeatIn(BaseModel):
    status:  dict = Field(default_factory=dict)
    version: Optional[str] = Field(default=None, max_length=40)


@router.post("/heartbeat")
@limiter.limit("240/minute")
async def heartbeat(body: _HeartbeatIn, request: Request, node: dict = Depends(require_node)):
    """Node is alive. Stores its latest status summary; returns commands for it."""
    ip = request.client.host if request.client else None
    prev = execute_read(
        "SELECT EXTRACT(EPOCH FROM (NOW() - last_seen_at)) AS gap FROM nodes WHERE company_id = %s",
        (node["company_id"],))
    gap = float(prev[0]["gap"]) if prev and prev[0]["gap"] is not None else None
    if gap is None or gap > node_events.OFFLINE_AFTER_S:
        node_events.log_event(node["company_id"], "online",
                              f"back after {int(gap // 60)} min" if gap is not None else "first contact")
    execute_write(
        """UPDATE nodes SET last_seen_at = NOW(), last_ip = %s, status = %s::jsonb,
                            node_version = COALESCE(%s, node_version)
            WHERE company_id = %s""",
        (ip, json.dumps(body.status, default=str), body.version, node["company_id"]),
    )
    from services.hub_sync import build_commands_for
    return {"ok": True, "commands": build_commands_for(node["company_id"], body.status)}


# ── ingest (store-and-forward upload) ────────────────────────────────────────

class _Item(BaseModel):
    id:      int
    kind:    str = Field(min_length=1, max_length=60)
    payload: Any


class _IngestIn(BaseModel):
    items: List[_Item] = Field(max_length=200)


@router.post("/ingest")
@limiter.limit("240/minute")
async def ingest(body: _IngestIn, request: Request, node: dict = Depends(require_node)):
    """Accept a batch queued on the node. Idempotent: an item the node re-sends
    after a lost reply is recognised by (company, node item id) and not stored twice.
    Returns the ids it now has, so the node can delete them from its queue."""
    from services.hub_sync import process_item
    accepted: list[int] = []
    for it in body.items:
        res = execute_write(
            """INSERT INTO node_inbox (company_id, node_item_id, kind, payload)
               VALUES (%s, %s, %s, %s::jsonb)
               ON CONFLICT (company_id, node_item_id) DO NOTHING""",
            (node["company_id"], it.id, it.kind, json.dumps(it.payload, default=str)),
        )
        if res.rowcount:   # new row → act on it (store alert, record summary …)
            try:
                process_item(node["company_id"], it.kind, it.payload)
                execute_write(
                    "UPDATE node_inbox SET processed = TRUE WHERE company_id = %s AND node_item_id = %s",
                    (node["company_id"], it.id),
                )
            except Exception as exc:
                logger.error("Could not process %s from company %s: %s", it.kind, node["company_id"], exc)
        accepted.append(it.id)
    if accepted:
        kinds: dict = {}
        for it in body.items:
            kinds[it.kind] = kinds.get(it.kind, 0) + 1
        node_events.log_event(node["company_id"], "received",
                              ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    return {"accepted": accepted}

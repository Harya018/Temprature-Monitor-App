"""
routers/hub_admin.py — Super Admin controls for company nodes (hub role only).

  GET    /api/super-admin/nodes                      every company + its node state
  POST   /api/super-admin/nodes/{company_id}/pairing one-time code to pair a node
  POST   /api/super-admin/nodes/{company_id}/revoke  cut a node off (its key stops working)
"""

import hashlib
import secrets
import socket
import subprocess
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import config
from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from routers.hub_api import HEARTBEAT_ONLINE_S
from services import node_events
from routers.super_admin_v2 import require_super_admin
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/super-admin/nodes", tags=["Super Admin — Nodes"])

PAIRING_TTL_HOURS = 24
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I — easy to read out loud


def _new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def _hub_addresses() -> list[dict]:
    """Addresses a node could use to reach this hub (Tailscale first)."""
    port = config.SERVER_PORT
    out: list[dict] = []
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3)
        ip = (r.stdout or "").strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else None
        if ip:
            out.append({"label": "Tailscale", "url": f"http://{ip}:{port}"})
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")) and not any(a["url"].startswith(f"http://{ip}:") for a in out):
                out.append({"label": "Local network", "url": f"http://{ip}:{port}"})
    except Exception:
        pass
    return out


def _state(row: dict) -> str:
    if not row.get("key_hash"):
        return "pairing" if row.get("pairing_hash") else "not_paired"
    seen = row.get("last_seen_at")
    if seen and (datetime.now(timezone.utc) - seen).total_seconds() <= HEARTBEAT_ONLINE_S:
        return "online"
    return "offline"


@router.get("")
async def list_nodes(_admin: dict = Depends(require_super_admin)):
    """Every company with its node state. A company with no node row is served by
    this hub itself (the local node, e.g. SRM)."""
    rows = execute_read(
        """SELECT c.id AS company_id, c.name, c.slug,
                  n.key_hash, n.pairing_hash, n.pairing_expires, n.node_name, n.node_version,
                  n.paired_at, n.last_seen_at, n.last_ip, n.status,
                  n.license_active, n.license_expires, n.grace_days
             FROM companies c LEFT JOIN nodes n ON n.company_id = c.id
            ORDER BY c.id"""
    )
    out = []
    for r in rows:
        has_node = r["key_hash"] is not None or r["pairing_hash"] is not None
        out.append({
            "company_id":   r["company_id"],
            "name":         r["name"],
            "mode":         "remote" if has_node else "local",     # local = lives on this hub
            "state":        _state(r) if has_node else "local",
            "node_name":    r["node_name"],
            "node_version": r["node_version"],
            "paired_at":    r["paired_at"].isoformat() if r["paired_at"] else None,
            "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
            "last_ip":      r["last_ip"],
            "pairing_expires": r["pairing_expires"].isoformat() if r["pairing_expires"] else None,
            "status":       r["status"] or {},
            "license": {
                "active":     bool(r["license_active"]) if r["license_active"] is not None else True,
                "expires_at": r["license_expires"].isoformat() if r["license_expires"] else None,
                "grace_days": r["grace_days"] if r["grace_days"] is not None else 7,
            },
        })
    return out


@router.post("/{company_id}/pairing")
@limiter.limit("20/minute")
async def create_pairing_code(company_id: int, request: Request,
                              admin: dict = Depends(require_super_admin)):
    """Make a one-time code for pairing this company's own server to the hub.
    Shown once — only its hash is stored. Re-issuing replaces any earlier code."""
    if not execute_read("SELECT 1 FROM companies WHERE id = %s", (company_id,)):
        raise HTTPException(status_code=404, detail="Company not found")
    code = _new_code()
    h = hashlib.sha256(code.replace("-", "").encode()).hexdigest()
    # Codes are compared with dashes removed (the node strips spaces; see register)
    execute_write(
        """INSERT INTO nodes (company_id, pairing_hash, pairing_expires)
           VALUES (%s, %s, NOW() + (%s || ' hours')::interval)
           ON CONFLICT (company_id) DO UPDATE
              SET pairing_hash = EXCLUDED.pairing_hash, pairing_expires = EXCLUDED.pairing_expires""",
        (company_id, h, str(PAIRING_TTL_HOURS)),
    )
    logger.info("Pairing code issued for company %s by super admin %s", company_id, admin.get("id"))
    node_events.log_event(company_id, "pairing_code_issued", f"by super admin {admin.get('id')}, valid {PAIRING_TTL_HOURS} h")
    return {
        "code": code,
        "expires_in_hours": PAIRING_TTL_HOURS,
        "hub_addresses": _hub_addresses(),
        "note": "Enter the hub address and this code once on the company's server. "
                "The code works once and then expires.",
    }


class _LicenseIn(BaseModel):
    active:     bool = True
    expires_at: Optional[date] = None
    grace_days: int = Field(default=7, ge=0, le=365)


@router.put("/{company_id}/license")
async def set_license(company_id: int, body: _LicenseIn, admin: dict = Depends(require_super_admin)):
    """Switch a company's server on/off, or set an expiry. The node learns of it on its
    next heartbeat and blocks its own dashboard/API when inactive or expired — and when it
    cannot reach the hub for more than grace_days."""
    res = execute_write(
        "UPDATE nodes SET license_active = %s, license_expires = %s, grace_days = %s WHERE company_id = %s",
        (body.active, body.expires_at, body.grace_days, company_id),
    )
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Generate a pairing code for this company first")
    logger.warning("Licence of company %s set active=%s expires=%s grace=%s by super admin %s",
                   company_id, body.active, body.expires_at, body.grace_days, admin.get("id"))
    node_events.log_event(company_id, "license_changed",
                          f"active={body.active}, expires={body.expires_at or 'never'}, grace={body.grace_days} d, "
                          f"by super admin {admin.get('id')}")
    return {"status": "saved"}


def _summary_rows(company_id: int, hours: int) -> list:
    lo = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H")
    return execute_read(
        """SELECT hour, parameter, samples, min_value, max_value, avg_value
             FROM node_hourly WHERE company_id = %s AND hour >= %s ORDER BY parameter, hour""",
        (company_id, lo))


@router.get("/{company_id}/summary")
async def node_summary(company_id: int, hours: int = 24, _admin: dict = Depends(require_super_admin)):
    """What a company's server has reported: per parameter min / avg / max over the window,
    an hourly average series, and its alerts. No raw readings are ever stored on the hub."""
    hours = max(1, min(hours, 24 * 30))
    params: dict = {}
    for r in _summary_rows(company_id, hours):
        p = params.setdefault(r["parameter"], {"parameter": r["parameter"], "samples": 0, "min": None,
                                               "max": None, "_sum": 0.0, "series": []})
        p["samples"] += r["samples"]
        p["_sum"] += (r["avg_value"] or 0) * r["samples"]
        if r["min_value"] is not None:
            p["min"] = r["min_value"] if p["min"] is None else min(p["min"], r["min_value"])
        if r["max_value"] is not None:
            p["max"] = r["max_value"] if p["max"] is None else max(p["max"], r["max_value"])
        p["series"].append({"hour": r["hour"], "avg": r["avg_value"]})
    for p in params.values():
        p["avg"] = p["_sum"] / p["samples"] if p["samples"] else None
        del p["_sum"]
        p["latest"] = p["series"][-1]["avg"] if p["series"] else None

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    alerts = execute_read(
        """SELECT id, parameter, value, threshold, direction, severity, timestamp, acknowledged, acknowledged_by
             FROM alerts WHERE company_id = %s AND timestamp >= %s ORDER BY timestamp DESC LIMIT 200""",
        (company_id, since))
    by_param: dict = {}
    for a in alerts:
        by_param[a["parameter"]] = by_param.get(a["parameter"], 0) + 1
    last = execute_read("SELECT MAX(hour) AS h FROM node_hourly WHERE company_id = %s", (company_id,))
    return {
        "hours": hours,
        "parameters": sorted(params.values(), key=lambda x: x["parameter"]),
        "alerts": {"total": len(alerts), "unacknowledged": sum(1 for a in alerts if not a["acknowledged"]),
                   "by_parameter": by_param, "recent": alerts[:20]},
        "last_summary_hour": last[0]["h"] if last else None,
    }


@router.get("/{company_id}/summary.csv")
async def node_summary_csv(company_id: int, hours: int = 168, _admin: dict = Depends(require_super_admin)):
    import csv, io
    from fastapi.responses import Response
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["hour_utc", "parameter", "samples", "min", "avg", "max"])
    for r in _summary_rows(company_id, max(1, min(hours, 24 * 90))):
        w.writerow([r["hour"], r["parameter"], r["samples"], r["min_value"], r["avg_value"], r["max_value"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="company-{company_id}-summary.csv"'})


@router.get("/{company_id}/events")
async def node_connection_log(company_id: int, limit: int = 60, _admin: dict = Depends(require_super_admin)):
    return node_events.recent(company_id, max(1, min(limit, 500)))


@router.post("/{company_id}/revoke")
async def revoke_node(company_id: int, admin: dict = Depends(require_super_admin)):
    """Disconnect a node: its key stops working immediately (re-pair to reconnect)."""
    res = execute_write(
        "UPDATE nodes SET key_hash = NULL, pairing_hash = NULL, pairing_expires = NULL WHERE company_id = %s",
        (company_id,),
    )
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="No node for this company")
    logger.warning("Node of company %s revoked by super admin %s", company_id, admin.get("id"))
    node_events.log_event(company_id, "revoked", f"by super admin {admin.get('id')}")
    return {"status": "revoked", "company_id": company_id}

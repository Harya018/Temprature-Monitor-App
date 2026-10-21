"""
routers/tailscale.py — "connect this computer to the main server through Tailscale".

  GET  /api/admin/tailscale          what an admin sees: is Tailscale on, can the main server be reached,
                                     the invitation link, and a notice to show in the notification bell
  PUT  /api/admin/tailscale/invite   an admin saves the invitation link they were given
  GET/PUT /api/super-admin/tailscale (main server only) Super Admin pastes the invitation / share link once;
                                     it is sent to every company server with the next heartbeat

Tailscale itself is installed and signed in by a person (it needs their account); SentinelEdge only reads its
status and shows the steps.
"""

import asyncio
import os
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database.connection import execute_read, execute_write
from middleware.auth import require_admin
from services import tailscale_info
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Tailscale"])

_KEY_INVITE = "tailscale_invite_url"
_KEY_HUB_ADDR = "tailscale_hub_address"


def _get(key: str) -> str:
    r = execute_read("SELECT value FROM app_settings WHERE key = %s", (key,))
    return (r[0]["value"] if r else "") or ""


def _set(key: str, value: str) -> None:
    execute_write("INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
                  "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()", (key, value))


def _valid_link(url: str) -> Optional[str]:
    """An invitation / share link comes from tailscale.com. Anything else is refused."""
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not (u.hostname or "").lower().endswith("tailscale.com") or len(url) > 500:
        return "That does not look like a Tailscale link. It starts with https://login.tailscale.com/..."
    return None


def _notice(role: str, ts: dict, paired_hub: Optional[str], reachable: Optional[bool]) -> Optional[dict]:
    """The text for the notification bell, or None when everything is fine."""
    if role == "hub":
        why = "Company servers and phones reach this main server through Tailscale."
        if not ts["installed"]:
            return {"level": "warning", "title": "Install Tailscale on this computer", "text": why + " Download it and sign in."}
        if not ts["running"]:
            return {"level": "warning", "title": "Turn on Tailscale", "text": why + " Tailscale is installed but not connected."}
        return None
    why = "This server sends its data to the main (Super Admin) server through Tailscale."
    if not ts["installed"]:
        return {"level": "warning", "title": "Download Tailscale and connect to the main server", "text": why + " Install it, sign in and accept the invitation."}
    if not ts["running"]:
        return {"level": "warning", "title": "Turn on Tailscale", "text": why + " Tailscale is installed but not connected."}
    if paired_hub and reachable is False:
        return {"level": "warning", "title": "The main server cannot be reached",
                "text": "Tailscale is on, but the main server does not answer. Accept the invitation (or share link) from Super Admin and check that the main server is on."}
    return None


@router.get("/api/admin/tailscale", summary="Tailscale status for this computer + the notice for the notification bell")
async def tailscale_status(request: Request, admin: dict = Depends(require_admin)):
    from config import SERVER_ROLE
    ts = await asyncio.to_thread(tailscale_info.status)
    paired_hub, reachable = None, None
    if SERVER_ROLE == "node":
        try:
            from services.node_agent import load_pairing
            p = load_pairing()
            paired_hub = p["hub_url"] if p else None
        except Exception:
            paired_hub = None
        if paired_hub:
            reachable = await asyncio.to_thread(tailscale_info.hub_reachable, paired_hub)
    notice = _notice(SERVER_ROLE, ts, paired_hub, reachable)
    return {
        "role": SERVER_ROLE,
        "tailscale": ts,
        "hub_url": paired_hub,
        "hub_reachable": reachable,
        "hub_uses_tailscale": bool(paired_hub and tailscale_info.is_tailscale_address(paired_hub)),
        "invite_url": _get(_KEY_INVITE) or os.environ.get("TAILSCALE_INVITE_URL", ""),
        "hub_address": _get(_KEY_HUB_ADDR),
        "notice": notice,
    }


class _InviteIn(BaseModel):
    url: str = Field(default="", max_length=500)


@router.put("/api/admin/tailscale/invite", summary="Save the Tailscale invitation link given by Super Admin")
async def save_invite(body: _InviteIn, admin: dict = Depends(require_admin)):
    url = body.url.strip()
    if url:
        err = _valid_link(url)
        if err:
            return JSONResponse(status_code=422, content={"error": err})
    _set(_KEY_INVITE, url)
    return {"status": "saved", "invite_url": url}


# ── main server only: Super Admin ────────────────────────────────────────────────────────────

def sa_router_factory():
    from routers.super_admin_v2 import require_super_admin
    sa = APIRouter(prefix="/api/super-admin/tailscale", tags=["Super Admin — Tailscale"])

    @sa.get("")
    async def sa_get(_admin: dict = Depends(require_super_admin)):
        ts = await asyncio.to_thread(tailscale_info.status)
        port = int(os.environ.get("SERVER_PORT", "5000"))
        return {"tailscale": ts, "invite_url": _get(_KEY_INVITE),
                "hub_address": f"http://{ts['ip']}:{port}" if ts.get("ip") else ""}

    @sa.put("")
    async def sa_put(body: _InviteIn, _admin: dict = Depends(require_super_admin)):
        url = body.url.strip()
        if url:
            err = _valid_link(url)
            if err:
                return JSONResponse(status_code=422, content={"error": err})
        _set(_KEY_INVITE, url)
        ts = await asyncio.to_thread(tailscale_info.status)
        if ts.get("ip"):
            _set(_KEY_HUB_ADDR, f"http://{ts['ip']}:{int(os.environ.get('SERVER_PORT', '5000'))}")
        return {"status": "saved", "invite_url": url}

    return sa

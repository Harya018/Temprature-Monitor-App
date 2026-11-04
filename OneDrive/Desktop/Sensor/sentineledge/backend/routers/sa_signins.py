"""
routers/sa_signins.py — who signs in as Super Admin, from where (main server / every hub PC).

Every Super Admin sign-in is recorded (super_admin_v2.super_admin_login -> record_login):
  time, IP, local or remote, browser + Windows version (from the browser), the PC's name and Windows user
  (for a sign-in on the PC itself), this PC's Tailscale address.
After sign-in the panel adds what only the browser knows (screen, time zone, language) and - only if the
person allows it in the browser - the location (latitude / longitude / accuracy).

  POST /api/super-admin/sign-in-details   the browser's details for the sign-in it just made
  GET  /api/super-admin/sign-ins          the log (newest first)
"""

from __future__ import annotations

import os
import re
import socket
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database.connection import execute_read, execute_write
from routers.super_admin_v2 import require_super_admin
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/super-admin", tags=["Super Admin — sign-in log"])

_LOCAL = {"127.0.0.1", "::1", "localhost"}


def _browser_os(ua: str) -> tuple:
    ua = ua or ""
    browser = next((name for pat, name in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"Chrome/", "Chrome"),
                                           (r"Firefox/", "Firefox"), (r"Safari/", "Safari")) if re.search(pat, ua)), "Other")
    m = re.search(r"Windows NT (\d+\.\d+)", ua)
    osn = ("Windows 10/11" if m and m.group(1) == "10.0" else f"Windows NT {m.group(1)}") if m else \
        "Android" if "Android" in ua else "iPhone/iPad" if re.search(r"iPhone|iPad", ua) else "Mac" if "Mac OS" in ua else \
        "Linux" if "Linux" in ua else "Other"
    return browser, osn


def record_login(admin_id: int, request: Request) -> Optional[int]:
    """Called on every successful Super Admin sign-in. Returns the log row id (never raises)."""
    try:
        ip = request.client.host if request.client else "unknown"
        ua = request.headers.get("user-agent", "")[:400]
        browser, osn = _browser_os(ua)
        local = ip in _LOCAL
        try:
            from services import tailscale_info
            ts_ip = (tailscale_info.status() or {}).get("ip")
        except Exception:
            ts_ip = None
        r = execute_write(
            """INSERT INTO sa_login_log (admin_id, ip, is_local, user_agent, browser, os, computer, windows_user, tailscale_ip)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (admin_id, ip, local, ua, browser, osn,
             socket.gethostname() if local else None,        # a sign-in on this PC: its own name and Windows user
             os.environ.get("USERNAME") if local else None, ts_ip))
        return r.lastrowid
    except Exception as exc:
        logger.warning("sign-in log: could not record: %s", exc)
        return None


class _Loc(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy: Optional[float] = Field(default=None, ge=0, le=1e7)


class _DetailsIn(BaseModel):
    login_id: int
    screen: Optional[str] = Field(default=None, max_length=40)
    timezone: Optional[str] = Field(default=None, max_length=80)
    language: Optional[str] = Field(default=None, max_length=40)
    location: Optional[_Loc] = None
    location_status: Optional[str] = Field(default=None, max_length=20)   # allowed / denied / unavailable


@router.post("/sign-in-details", summary="Add the browser's details (and location, if allowed) to this sign-in")
async def sign_in_details(body: _DetailsIn, admin: dict = Depends(require_super_admin)):
    status = (body.location_status or ("allowed" if body.location else None))
    if status not in (None, "allowed", "denied", "unavailable"):
        status = "unavailable"
    res = execute_write(
        """UPDATE sa_login_log SET screen = COALESCE(%s, screen), timezone = COALESCE(%s, timezone),
                  language = COALESCE(%s, language),
                  lat = COALESCE(%s, lat), lon = COALESCE(%s, lon), accuracy_m = COALESCE(%s, accuracy_m),
                  location_status = COALESCE(%s, location_status)
            WHERE id = %s AND admin_id = %s AND at > NOW() - INTERVAL '30 minutes'""",
        (body.screen, body.timezone, body.language,
         body.location.lat if body.location else None, body.location.lon if body.location else None,
         body.location.accuracy if body.location else None, status, body.login_id, admin["id"]))
    if not res.rowcount:
        return JSONResponse(status_code=404, content={"error": "Sign-in not found (or older than 30 minutes)"})
    return {"status": "saved"}


@router.get("/sign-ins", summary="Super Admin sign-in log")
async def sign_ins(limit: int = 200, admin: dict = Depends(require_super_admin)):
    rows = execute_read(
        """SELECT l.id, l.at::TEXT AS at, a.name, l.ip, l.is_local, l.browser, l.os, l.computer, l.windows_user,
                  l.tailscale_ip, l.screen, l.timezone, l.language, l.lat, l.lon, l.accuracy_m, l.location_status
             FROM sa_login_log l LEFT JOIN admins a ON a.id = l.admin_id
            ORDER BY l.id DESC LIMIT %s""", (max(1, min(int(limit), 1000)),))
    return rows

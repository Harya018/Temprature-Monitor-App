"""
routers/mobile_app.py — what the phone app needs, whatever company it is connected to.

ONE app (one APK) serves every company. The app asks the server it is connected to who the signed-in
person is and what that company measures, and builds its screens from the answer - so a company with
only pH, one with temperature + pressure, and one with five parameters all see their own parameters.

  POST /api/app/login     name + PIN (a subscriber) or name + password (a company admin) -> token
  GET  /api/app/config    the company's name and its parameters (name, unit, min, max, alerts on/off)
  GET  /api/app/latest    the latest value of each parameter + how many alerts are still open

The token works for the live websocket (/ws?token=...) and for the alert endpoints, like the web
dashboard's. Everything is limited to the person's own company.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

import database
from database.connection import execute_read
from middleware.rate_limit import limiter
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/app", tags=["Mobile app"])


class _AppLoginIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    pin:  str = Field(min_length=1, max_length=200)


def _company_row(company_id):
    rows = execute_read("SELECT id, name, COALESCE(is_active, 1) AS active FROM companies WHERE id = %s", (company_id,))
    return rows[0] if rows else None


def app_user(
    x_auth_token: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """The signed-in person: a subscriber (X-Auth-Token) or a company admin (Bearer). Always has a company."""
    if x_auth_token:
        from database.queries.subscriber_sessions import get_sub_session
        sess = get_sub_session(x_auth_token)
        if sess:
            sub = database.get_subscriber_by_id(sess["subscriber_id"])
            if sub and sub.get("company_id") is not None:
                return {"kind": "subscriber", "name": sub["name"], "company_id": sub["company_id"], "subscriber_id": sub["id"]}
    if authorization and authorization.startswith("Bearer "):
        from middleware.auth import require_admin
        a = require_admin(authorization)
        if a.get("company_id") is not None:
            return {"kind": "admin", "name": None, "company_id": a["company_id"], "admin_id": a.get("admin_id")}
    raise HTTPException(status_code=401, detail="Please sign in again")


@router.post("/login", summary="Sign in from the phone app (subscriber name + PIN, or company admin)")
@limiter.limit("10/minute")
async def app_login(body: _AppLoginIn, request: Request):
    from utils.rate_limiter import check_rate_limit, record_attempt, clear_failed_attempts
    ip = request.client.host if request.client else "unknown"
    name, secret = body.name.strip(), body.pin.strip()
    lock_key = f"app:{name.lower()}"
    check_rate_limit(lock_key, ip)

    # 1) a subscriber: name + PIN
    sub = database.get_subscriber_by_name_and_pin(name, secret)
    if sub and sub.get("company_id") is not None:
        co = _company_row(sub["company_id"])
        if co and co["active"] != 0:
            token = secrets.token_hex(32)
            from database.queries.subscriber_sessions import create_sub_session
            create_sub_session(token, sub["id"], datetime.now(timezone.utc) + timedelta(days=30))
            clear_failed_attempts(lock_key, ip)
            return {"token": token, "kind": "subscriber", "name": sub["name"], "company": {"id": co["id"], "name": co["name"]}}

    # 2) a company admin: name + password
    cand = database.verify_admin_password(name, secret)
    if cand and cand.get("role") in ("main", "sub") and cand.get("company_id") and cand.get("is_active") != 0:
        co = _company_row(cand["company_id"])
        if co and co["active"] != 0:
            token = secrets.token_hex(32)
            database.create_session(token, datetime.now(timezone.utc) + timedelta(hours=8), cand["id"])
            clear_failed_attempts(lock_key, ip)
            return {"token": token, "kind": "admin", "name": cand["name"], "company": {"id": co["id"], "name": co["name"]}}

    record_attempt(lock_key, ip, False)
    raise HTTPException(status_code=401, detail={"error": "InvalidCredentials", "message": "Name or PIN is incorrect"})


@router.get("/config", summary="The company's name and its parameters")
async def app_config(user: dict = Depends(app_user)):
    co = _company_row(user["company_id"])
    params = execute_read(
        """SELECT name, unit, min_value, max_value, COALESCE(alerts_enabled, TRUE) AS alerts_enabled
             FROM company_parameters WHERE company_id = %s AND is_active = TRUE ORDER BY name""",
        (user["company_id"],))
    from config import APP_VERSION, SERVER_ROLE
    return {
        "company": {"id": co["id"], "name": co["name"]} if co else None,
        "user": {"kind": user["kind"], "name": user.get("name")},
        "parameters": [{"name": p["name"], "unit": p["unit"] or "",
                        "min": float(p["min_value"]) if p["min_value"] is not None else None,
                        "max": float(p["max_value"]) if p["max_value"] is not None else None,
                        "alerts_enabled": bool(p["alerts_enabled"])} for p in params],
        "server": {"role": SERVER_ROLE, "version": APP_VERSION},
    }


@router.get("/latest", summary="Latest value of each parameter (this company only)")
async def app_latest(user: dict = Depends(app_user)):
    cid = user["company_id"]
    names = [r["name"] for r in execute_read(
        "SELECT name FROM company_parameters WHERE company_id = %s AND is_active = TRUE", (cid,))]
    wanted = {n.lower(): n for n in names}
    values: dict = {}
    stamp = None
    rows = execute_read(
        "SELECT temperature, timestamp, extra_params FROM readings WHERE company_id = %s AND is_valid = 1 "
        "ORDER BY id DESC LIMIT 300", (cid,))
    for r in rows:                                   # newest first: the first value seen for a parameter is its latest
        if stamp is None:
            stamp = r["timestamp"]
        got = {}
        if r.get("temperature") is not None and "temperature" in wanted:
            got["temperature"] = r["temperature"]
        for k, v in (r.get("extra_params") or {}).items():
            if str(k).lower() in wanted and v is not None:
                got[str(k).lower()] = v
        for k, v in got.items():
            if wanted[k] not in values:
                values[wanted[k]] = {"value": float(v), "timestamp": r["timestamp"]}
        if len(values) == len(wanted):
            break
    open_alerts = execute_read("SELECT COUNT(*) AS n FROM alerts WHERE company_id = %s AND acknowledged = 0", (cid,))[0]["n"]
    return {"timestamp": stamp, "values": values, "open_alerts": int(open_alerts)}


@router.get("/server-address", summary="Addresses the phone app can use to reach this server (for the Settings page)")
async def app_server_address(user: dict = Depends(app_user)):
    """The addresses of THIS computer on its networks, to type into the phone app. Tailscale addresses
    (100.64.0.0/10) are marked, because they work from anywhere."""
    import ipaddress
    import socket
    import os
    addrs = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.append(info[4][0])
    except OSError:
        pass
    try:                                    # the address used to reach the outside world = the main network card
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.insert(0, s.getsockname()[0])
        s.close()
    except OSError:
        pass
    seen, out = set(), []
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if a in seen or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            continue
        seen.add(a)
        out.append({"address": a, "kind": "tailscale" if ip in ipaddress.ip_network("100.64.0.0/10") else "network"})
    port = int(os.environ.get("SERVER_PORT", "5000"))
    return {"port": port, "addresses": out}

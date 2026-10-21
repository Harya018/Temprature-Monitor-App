"""
services/tailscale_info.py — is Tailscale installed and connected on this computer, and can this company
server reach the main (Super Admin) server through it?

Company servers talk to the main server and phones talk to company servers over Tailscale (a private
network), so each computer must have it on. This only READS Tailscale's status (`tailscale status --json`);
it never changes anything.
"""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import time
from typing import Optional
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger(__name__)

_WIN_PATHS = (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe")
_cache: dict = {"at": 0.0, "data": None}


def find_cli() -> Optional[str]:
    env = os.environ.get("TAILSCALE_CLI")            # tests / unusual installs
    if env:
        return env if os.path.exists(env) else None
    p = shutil.which("tailscale")
    if p:
        return p
    for c in _WIN_PATHS:
        if os.path.exists(c):
            return c
    return None


def status(max_age: float = 10.0) -> dict:
    """{installed, state, running, ip, host, tailnet}. state: running | needs_login | stopped | not_installed | unknown."""
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < max_age:
        return _cache["data"]
    cli = find_cli()
    if not cli:
        data = {"installed": False, "state": "not_installed", "running": False, "ip": None, "host": None, "tailnet": None}
    else:
        data = {"installed": True, "state": "unknown", "running": False, "ip": None, "host": None, "tailnet": None}
        try:
            cmd = [cli, "status", "--json"]
            if cli.lower().endswith((".bat", ".cmd")):
                cmd = ["cmd", "/c", cli, "status", "--json"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            j = json.loads(out or "{}")
            be = str(j.get("BackendState", ""))
            data["state"] = {"Running": "running", "NeedsLogin": "needs_login", "NeedsMachineAuth": "needs_login",
                             "Stopped": "stopped"}.get(be, "stopped" if be else "unknown")
            data["running"] = be == "Running"
            me = j.get("Self") or {}
            ips = [i for i in (me.get("TailscaleIPs") or []) if ":" not in i]
            data["ip"] = ips[0] if ips else None
            data["host"] = me.get("HostName")
            data["tailnet"] = (j.get("CurrentTailnet") or {}).get("Name")
        except Exception as exc:
            logger.debug("tailscale status failed: %s", exc)
    _cache.update(at=now, data=data)
    return data


def is_tailscale_address(url: str) -> bool:
    """True for a Tailscale address: 100.64.0.0/10 or a *.ts.net name."""
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    if host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def hub_reachable(hub_url: str, timeout: float = 3.0) -> bool:
    """Can this computer reach the main server right now?"""
    import requests
    try:
        r = requests.get(hub_url.rstrip("/") + "/api/hub/ping", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False

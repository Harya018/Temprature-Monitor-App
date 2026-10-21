"""
services/node_agent.py — the node's connection to the hub (node role only).

A background thread that, every few seconds:
  1. sends a heartbeat with a small status summary (and receives any commands),
  2. uploads queued items from the local outbox, deleting each only after the
     hub confirms it (store-and-forward — nothing is lost while the hub is away).

Everything is an OUTGOING HTTP call, so a company's PC needs no open ports and
works the same over the local network or Tailscale.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests

import config
from utils.logger import get_logger

logger = get_logger(__name__)

HEARTBEAT_S   = 15      # between heartbeats when idle
FAST_S        = 2       # between rounds while the outbox still has items
BATCH         = 100
ROLLUP_EVERY_S = int(__import__("os").environ.get("NODE_ROLLUP_INTERVAL_S", "300"))
HTTP_TIMEOUT  = 8
_START        = time.monotonic()

# ── settings (app_settings) ──────────────────────────────────────────────────
_KEYS = ("hub_url", "node_key", "node_company_id", "node_company_name")


def _get_setting(key: str) -> Optional[str]:
    from database.connection import execute_read
    r = execute_read("SELECT value FROM app_settings WHERE key = %s", (key,))
    return r[0]["value"] if r else None


def _set_setting(key: str, value: Optional[str]) -> None:
    from database.connection import execute_write
    if value is None:
        execute_write("DELETE FROM app_settings WHERE key = %s", (key,))
    else:
        execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (key, value),
        )


def load_pairing() -> Optional[dict]:
    """The saved pairing, or None when this node is not paired."""
    try:
        hub, key = _get_setting("hub_url"), _get_setting("node_key")
        if not hub or not key:
            return None
        return {"hub_url": hub, "node_key": key,
                "company_id": int(_get_setting("node_company_id") or 0) or None,
                "company_name": _get_setting("node_company_name")}
    except Exception:
        return None


def normalise_hub_url(raw: str) -> str:
    """http(s)://host[:port] — rejects anything else (no paths, no credentials)."""
    u = urlparse(raw.strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("Hub address must look like http://100.x.y.z:5000")
    port = f":{u.port}" if u.port else ""
    return f"{u.scheme}://{u.hostname}{port}"


# ── pairing ──────────────────────────────────────────────────────────────────

def pair_with_hub(hub_url: str, pairing_code: str, node_name: str) -> dict:
    """Pair this node with the hub using a one-time code from Super Admin.
    Saves the node key and creates this company locally (same id as on the hub)."""
    base = normalise_hub_url(hub_url)
    try:
        ping = requests.get(f"{base}/api/hub/ping", timeout=HTTP_TIMEOUT)
        if ping.status_code != 200 or ping.json().get("service") != "sentineledge-hub":
            raise ValueError("That address is not a SentinelEdge hub")
        r = requests.post(f"{base}/api/hub/register", timeout=HTTP_TIMEOUT, json={
            "pairing_code": pairing_code, "node_name": node_name, "version": config.APP_VERSION})
    except requests.RequestException as exc:
        raise ConnectionError(f"Could not reach the hub at {base}: {exc.__class__.__name__}") from exc
    if r.status_code == 403:
        raise PermissionError("Pairing code is invalid or has expired — ask Super Admin for a new one")
    if r.status_code == 429:
        raise PermissionError("Too many attempts — wait a minute and try again")
    r.raise_for_status()
    data = r.json()
    co = data["company"]

    from database.connection import execute_write
    execute_write(
        """INSERT INTO companies (id, name, slug, is_active, created_at)
           VALUES (%s, %s, %s, 1, NOW())
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug""",
        (co["id"], co["name"], co["slug"]),
    )
    execute_write("SELECT setval(pg_get_serial_sequence('companies', 'id'), GREATEST((SELECT MAX(id) FROM companies), 1))")
    _set_setting("hub_url", base)
    _set_setting("node_key", data["node_key"])
    _set_setting("node_company_id", str(co["id"]))
    _set_setting("node_company_name", co["name"])
    _set_setting("sensor_company_id", str(co["id"]))   # this node's sensor feed belongs to this company
    try:
        from services import sensor_company
        sensor_company._cache.update(id=None, at=0.0)
    except Exception:
        pass
    agent.wake()
    logger.info("Paired with hub %s as company %s (%s)", base, co["id"], co["name"])
    return co


def unpair() -> None:
    for k in _KEYS + ("sync_version",):
        _set_setting(k, None)
    from services import license
    license.clear()
    agent.state.update(connected=False, error="Not paired")


# ── the agent ────────────────────────────────────────────────────────────────

class NodeAgent:
    def __init__(self) -> None:
        self.state = {"connected": False, "last_ok": None, "last_error": None,
                      "last_attempt": None, "sent_total": 0}
        self._stop  = threading.Event()
        self._wake  = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_rollup = -1e9

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="node-agent", daemon=True)
        self._thread.start()
        logger.info("Node agent started")

    def stop(self) -> None:
        self._stop.set(); self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    # status summary sent with every heartbeat
    def _status(self) -> dict:
        from database.connection import execute_read
        from services import outbox
        from services.node_commands import current_version
        from services.node_commands import APPLIED_ACKS
        st: dict = {"uptime_seconds": int(time.monotonic() - _START),
                    "acks_applied": list(APPLIED_ACKS),
                    "sync_version": current_version(),
                    "outbox_pending": outbox.pending_count(),
                    "time": datetime.now(timezone.utc).isoformat()}
        try:
            from services.live_collector import state as lc
            st["collector_last_reading_at"] = lc.last_received_at
            import core.excel_sensor as xs
            st["excel_enabled"] = xs.EXCEL_LIVE_ENABLED
            st["excel_last_row_at"] = xs.get_enabled_status().get("last_new_row_at") or None
            cid = (load_pairing() or {}).get("company_id")
            r = execute_read("SELECT MAX(timestamp) AS t FROM readings WHERE company_id = %s", (cid,))
            st["last_stored_reading_at"] = r[0]["t"] if r and r[0]["t"] else None
            p = execute_read("SELECT name FROM company_parameters WHERE is_active = TRUE AND company_id = %s ORDER BY name", (cid,))
            st["parameters"] = [x["name"] for x in p]
        except Exception as exc:
            st["status_error"] = str(exc)[:120]
        return st

    def _rollup(self, cfg: dict) -> None:
        """Queue finished-hour summaries (checked at most every 5 minutes)."""
        if time.monotonic() - self._last_rollup < ROLLUP_EVERY_S or not cfg.get("company_id"):
            return
        self._last_rollup = time.monotonic()
        try:
            from services import node_rollup
            node_rollup.run_once(cfg["company_id"])
        except Exception as exc:
            logger.warning("hourly rollup failed: %s", exc)

    def _round(self, cfg: dict) -> bool:
        """One heartbeat + one upload batch. Returns True if more items wait."""
        base, headers = cfg["hub_url"], {"X-Node-Key": cfg["node_key"]}
        self.state["last_attempt"] = datetime.now(timezone.utc).isoformat()

        hb = requests.post(f"{base}/api/hub/heartbeat", headers=headers, timeout=HTTP_TIMEOUT,
                           json={"status": self._status(), "version": config.APP_VERSION})
        if hb.status_code == 401:
            from services import license
            license.mark_revoked()
            raise PermissionError("Hub no longer accepts this node's key — re-pair with a new code")
        hb.raise_for_status()
        from services.node_commands import apply_commands
        apply_commands(hb.json().get("commands") or [])

        from database.connection import execute_read, execute_write
        rows = execute_read("SELECT id, kind, payload FROM outbox ORDER BY id LIMIT %s", (BATCH,))
        if rows:
            up = requests.post(f"{base}/api/hub/ingest", headers=headers, timeout=HTTP_TIMEOUT * 3,
                               json={"items": [{"id": r["id"], "kind": r["kind"], "payload": r["payload"]} for r in rows]})
            up.raise_for_status()
            ok = up.json().get("accepted") or []
            if ok:
                execute_write("DELETE FROM outbox WHERE id = ANY(%s)", (ok,))
                self.state["sent_total"] += len(ok)
            return len(rows) >= BATCH
        return False

    def _run(self) -> None:
        backoff = HEARTBEAT_S
        while not self._stop.is_set():
            more = False
            cfg = load_pairing()
            if cfg:
                try:
                    self._rollup(cfg)
                    more = self._round(cfg)
                    self.state.update(connected=True, last_ok=datetime.now(timezone.utc).isoformat(), last_error=None)
                    backoff = HEARTBEAT_S
                except Exception as exc:
                    self.state.update(connected=False, last_error=str(exc)[:200])
                    logger.warning("Hub sync failed: %s (retry in %ss)", exc, backoff)
                    backoff = min(backoff * 2, 120)
            else:
                self.state.update(connected=False, last_error="Not paired")
                backoff = HEARTBEAT_S
            self._wake.wait(FAST_S if more else (backoff if cfg else 5))
            self._wake.clear()


agent = NodeAgent()

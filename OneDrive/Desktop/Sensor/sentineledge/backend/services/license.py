"""
services/license.py — a node only works while the hub says it may (node role only).

The hub sends {active, expires_at, grace_days} with every heartbeat. The node is
blocked when the hub switched it off, the licence date has passed, it was revoked,
or it has not reached the hub for more than grace_days (so a copy cut off from the
hub stops working instead of running forever).
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from typing import Tuple

from utils.logger import get_logger

logger = get_logger(__name__)

_KEY = "license_state"
_cache = {"at": 0.0, "value": (True, "")}


def _read() -> dict:
    from database.connection import execute_read
    r = execute_read("SELECT value FROM app_settings WHERE key = %s", (_KEY,))
    try:
        return json.loads(r[0]["value"]) if r else {}
    except Exception:
        return {}


def _write(state: dict) -> None:
    from database.connection import execute_write
    execute_write(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        (_KEY, json.dumps(state)),
    )
    _cache["at"] = 0.0


def update_from_hub(lic: dict) -> None:
    """Store the licence the hub just sent; also records that the hub was reachable."""
    _write({"active": bool(lic.get("active", True)), "expires_at": lic.get("expires_at"),
            "grace_days": int(lic.get("grace_days") or 7), "revoked": False,
            "last_ok_at": datetime.now(timezone.utc).isoformat()})


def mark_revoked() -> None:
    st = _read()
    st["revoked"] = True
    _write(st)


def clear() -> None:
    from database.connection import execute_write
    execute_write("DELETE FROM app_settings WHERE key = %s", (_KEY,))
    _cache["at"] = 0.0


def check() -> Tuple[bool, str]:
    """(allowed, reason). Cached for 30 s — called on every request."""
    now = time.monotonic()
    if now - _cache["at"] < 30:
        return _cache["value"]
    value: Tuple[bool, str] = (True, "")
    try:
        from services.node_agent import load_pairing
        if load_pairing():
            st = _read()
            if st:
                if st.get("revoked"):
                    value = (False, "This server was disconnected by the hub. Ask Super Admin for a new pairing code.")
                elif not st.get("active", True):
                    value = (False, "This server has been switched off by the hub. Contact your provider.")
                elif st.get("expires_at") and date.fromisoformat(st["expires_at"]) < date.today():
                    value = (False, f"The licence for this server expired on {st['expires_at']}. Contact your provider.")
                elif st.get("last_ok_at"):
                    last = datetime.fromisoformat(st["last_ok_at"])
                    days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
                    if days > st.get("grace_days", 7):
                        value = (False, f"This server has not reached the hub for {int(days)} days. "
                                        "Restore the connection to continue.")
    except Exception as exc:
        logger.warning("licence check failed (allowing): %s", exc)
    _cache.update(at=now, value=value)
    return value

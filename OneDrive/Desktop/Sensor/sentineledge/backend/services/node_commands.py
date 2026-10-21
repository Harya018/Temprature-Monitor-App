"""
services/node_commands.py — apply what the hub returns in a heartbeat reply (node role).

  license     → services.license (kept in the database; checked on every request)
  sync_state  → makes this node's company, parameters, admin accounts and approval
                outcomes match the hub. The hub is the source of truth; the version
                is reported back in the next heartbeat so unchanged state is not resent.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from utils.logger import get_logger
from utils.time import now_iso

logger = get_logger(__name__)

LOOP: Optional[asyncio.AbstractEventLoop] = None     # main event loop (set at startup)
_VERSION_KEY = "sync_version"

_UPSERT_SETTING = ("INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
                   "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()")


def current_version() -> Optional[str]:
    try:
        from database.connection import execute_read
        r = execute_read("SELECT value FROM app_settings WHERE key = %s", (_VERSION_KEY,))
        return r[0]["value"] if r else None
    except Exception:
        return None


def _notify(company_id: int, event: dict) -> None:
    """Tell open dashboards of this company that parameters changed."""
    if LOOP is None:
        return
    try:
        from modules.inapp.manager import broadcast
        asyncio.run_coroutine_threadsafe(broadcast({**event, "company_id": company_id}, company_id=company_id), LOOP)
    except Exception as exc:
        logger.warning("node: broadcast failed: %s", exc)


def _apply_license(payload: dict) -> None:
    from services import license
    license.update_from_hub(payload or {})


def _params(cid: int) -> dict:
    from database.connection import execute_read
    return {r["name"]: (r["unit"], r["min_value"], r["max_value"], r["is_active"])
            for r in execute_read("SELECT name, unit, min_value, max_value, is_active "
                                  "FROM company_parameters WHERE company_id = %s", (cid,))}


def _apply_sync_state(p: dict) -> None:
    from database.connection import execute_write
    from services.node_agent import load_pairing
    pairing = load_pairing()
    if not pairing or not pairing.get("company_id"):
        return
    cid = pairing["company_id"]

    co = p.get("company") or {}
    if co:
        execute_write(
            """UPDATE companies SET name = %s, is_active = %s, maintenance_mode = %s,
                      maintenance_until = %s, maintenance_reason = %s WHERE id = %s""",
            (co.get("name"), co.get("is_active", 1), co.get("maintenance_mode", 0),
             co.get("maintenance_until"), co.get("maintenance_reason"), cid))
        execute_write(_UPSERT_SETTING, ("node_company_name", co.get("name")))

    # parameters — the hub's list replaces this node's list
    before = _params(cid)
    names = []
    for prm in p.get("parameters") or []:
        names.append(prm["name"])
        execute_write(
            """INSERT INTO company_parameters (company_id, name, unit, min_value, max_value, is_active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
               ON CONFLICT (company_id, name) DO UPDATE SET unit = EXCLUDED.unit,
                   min_value = EXCLUDED.min_value, max_value = EXCLUDED.max_value,
                   is_active = EXCLUDED.is_active, updated_at = NOW()""",
            (cid, prm["name"], prm.get("unit"), prm.get("min_value"), prm.get("max_value"), prm.get("is_active", True)))
    execute_write("DELETE FROM company_parameters WHERE company_id = %s AND NOT (name = ANY(%s))", (cid, names))

    # admin accounts (hash only) — login works offline and follows hub changes
    from database.connection import execute_read
    old = {r["name"]: r for r in (execute_read(
        "SELECT id, name, password_hash, role, COALESCE(is_active, 1) AS is_active FROM admins WHERE company_id = %s", (cid,)) or [])}
    keep = []
    for a in p.get("admins") or []:
        keep.append(a["name"])
        execute_write(
            """INSERT INTO admins (name, password_hash, role, created_at, company_id, is_active, email, requires_approval)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET password_hash = EXCLUDED.password_hash, role = EXCLUDED.role,
                   company_id = EXCLUDED.company_id, is_active = EXCLUDED.is_active,
                   email = EXCLUDED.email, requires_approval = EXCLUDED.requires_approval""",
            (a["name"], a["password_hash"], a["role"], now_iso(), cid, a.get("is_active", 1),
             a.get("email"), a.get("requires_approval", 0)))
    execute_write("UPDATE admins SET is_active = 0 WHERE company_id = %s AND NOT (name = ANY(%s))", (cid, keep))
    # Password reset, role change, switched off or removed on the main server: that admin's sign-ins on
    # THIS server end too (a leaked password must not keep working here for hours after the reset).
    new = {a["name"]: a for a in p.get("admins") or []}
    for name, o in old.items():
        n = new.get(name)
        if n is None or n.get("password_hash") != o["password_hash"] or n.get("role") != o["role"]                 or int(n.get("is_active", 1) or 0) == 0:
            ended = execute_write("DELETE FROM admin_sessions WHERE admin_id = %s", (o["id"],)).rowcount
            if ended:
                logger.info("node: ended %d sign-in(s) of %s (changed on the main server)", ended, name)

    # outcome of requests this node's admins sent up
    for r in p.get("approval_results") or []:
        execute_write(
            """UPDATE pending_approvals SET status = %s, review_note = %s, reviewed_at = NOW()
                WHERE status = 'pending' AND action_type = %s AND LOWER(payload->>'name') = LOWER(%s)
                  AND (payload->>'company_id')::int = %s""",
            (r["status"], r.get("review_note"), r["action_type"], r.get("name") or "", cid))

    # Super Admin broadcasts / direct messages (read-state of messages stays local)
    execute_write("DELETE FROM broadcasts")
    for b in p.get("broadcasts") or []:
        execute_write("INSERT INTO broadcasts (title, message, sent_by, created_at, status) "
                      "VALUES (%s, %s, 'super_admin', %s, 'sent')", (b["title"], b["message"], b["sent_at"]))
    for m in p.get("messages") or []:
        execute_write(
            """INSERT INTO company_messages (company_id, subject, body, sent_at)
               SELECT %s, %s, %s, %s::timestamptz WHERE NOT EXISTS (
                   SELECT 1 FROM company_messages WHERE company_id = %s AND subject = %s AND sent_at = %s::timestamptz)""",
            (cid, m["subject"], m["body"], m["sent_at"], cid, m["subject"], m["sent_at"]))

    execute_write(_UPSERT_SETTING, (_VERSION_KEY, p["version"]))

    if _params(cid) != before:
        _notify(cid, {"type": "parameter_added", "parameter": None})
    logger.info("node: applied hub state v%s (%d parameters, %d admins)", p["version"], len(names), len(keep))


def _apply_tailscale(p: dict) -> None:
    """The invitation link / main-server address Super Admin saved on the hub (shown in Settings and the bell)."""
    from database.connection import execute_write
    p = p or {}
    if p.get("invite_url") is not None:
        execute_write(_UPSERT_SETTING, ("tailscale_invite_url", p.get("invite_url") or ""))
    if p.get("hub_address") is not None:
        execute_write(_UPSERT_SETTING, ("tailscale_hub_address", p.get("hub_address") or ""))


APPLIED_ACKS: list = []          # ids of hub acknowledgements this server applied (reported in every heartbeat)


def _apply_ack_alerts(p: dict) -> None:
    """Super Admin acknowledged these alerts on the main server: acknowledge this server's own copies."""
    from database.connection import execute_read, execute_write
    from services.node_agent import load_pairing
    cid = (load_pairing() or {}).get("company_id")
    for it in (p or {}).get("items") or []:
        try:
            by = f"{it.get('by') or 'Super Admin'} (main server)"
            from datetime import datetime, timezone
            res = execute_write(
                "UPDATE alerts SET acknowledged = 1, acknowledged_by = %s, acknowledged_at = %s "
                "WHERE id = %s AND company_id = %s AND acknowledged = 0",
                (by, datetime.now(timezone.utc).isoformat(), int(it["alert_id"]), cid))
            if res.rowcount:
                from services import company_log
                company_log.log(cid, f"Alert #{it['alert_id']} acknowledged by {by}")
                _notify(cid, {"type": "acknowledgement", "alert_id": int(it["alert_id"]), "acknowledged_by": by})
            if it["id"] not in APPLIED_ACKS:
                APPLIED_ACKS.append(it["id"])
                del APPLIED_ACKS[:-200]
        except Exception as exc:
            logger.warning("node: could not apply acknowledgement %s: %s", it, exc)


HANDLERS: dict = {"license": _apply_license, "sync_state": _apply_sync_state, "tailscale": _apply_tailscale,
                  "ack_alerts": _apply_ack_alerts}


def apply_commands(commands: list) -> None:
    for cmd in commands:
        fn = HANDLERS.get(cmd.get("type"))
        if fn is None:
            logger.debug("node: ignoring unknown hub command %r", cmd.get("type"))
            continue
        try:
            fn(cmd.get("payload"))
        except Exception as exc:
            logger.error("node: command %r failed: %s", cmd.get("type"), exc)

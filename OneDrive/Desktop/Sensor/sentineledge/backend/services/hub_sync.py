"""
services/hub_sync.py — what the hub hands to a node, and what it does with what nodes send.

hub → node  (returned in every heartbeat reply)
    'license'     always: active flag, expiry, offline grace period
    'sync_state'  only when it changed since the version the node reports:
                  company profile + maintenance, parameters, admin accounts
                  (password hashes, so logins work offline), recent approval results

node → hub  (process_item)
    'parameter_request'         a company admin asks for a new parameter
    'parameter_delete_request'  … or to remove one
Both become normal pending approvals on the hub, so Super Admin sees them in the
usual Approvals tab; the decision flows back down in the next 'sync_state'.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from database.connection import execute_read, execute_write
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_GRACE_DAYS = 7
RESULT_WINDOW_DAYS = 30


# ── hub → node ───────────────────────────────────────────────────────────────

def license_for(company_id: int) -> dict:
    r = execute_read(
        "SELECT license_active, license_expires, grace_days FROM nodes WHERE company_id = %s",
        (company_id,),
    )
    row = r[0] if r else {}
    exp = row.get("license_expires")
    return {
        "active":     bool(row.get("license_active", True)),
        "expires_at": exp.isoformat() if exp else None,
        "grace_days": int(row.get("grace_days") or DEFAULT_GRACE_DAYS),
    }


def snapshot_for(company_id: int) -> dict:
    """Everything a node needs to run its company, as plain JSON."""
    co = execute_read(
        """SELECT name, slug, COALESCE(is_active, 1) AS is_active,
                  COALESCE(maintenance_mode, 0) AS maintenance_mode,
                  maintenance_until, maintenance_reason
             FROM companies WHERE id = %s""", (company_id,))
    company = dict(co[0]) if co else {}
    if company.get("maintenance_until") is not None:
        company["maintenance_until"] = company["maintenance_until"].isoformat()

    params = execute_read(
        """SELECT name, unit, min_value, max_value, COALESCE(is_active, TRUE) AS is_active
             FROM company_parameters WHERE company_id = %s ORDER BY name""", (company_id,))
    parameters = [{"name": p["name"], "unit": p["unit"],
                   "min_value": float(p["min_value"]) if p["min_value"] is not None else None,
                   "max_value": float(p["max_value"]) if p["max_value"] is not None else None,
                   "is_active": bool(p["is_active"])} for p in params]

    adm = execute_read(
        """SELECT name, password_hash, role, COALESCE(is_active, 1) AS is_active, email,
                  COALESCE(requires_approval, 0) AS requires_approval
             FROM admins WHERE company_id = %s AND role <> 'super_admin' ORDER BY name""",
        (company_id,))
    admins = [dict(a) for a in adm]

    res = execute_read(
        """SELECT pa.action_type, pa.payload->>'name' AS name, pa.status, pa.review_note
             FROM pending_approvals pa
            WHERE pa.status <> 'pending'
              AND pa.action_type IN ('add_parameter', 'delete_parameter')
              AND (pa.payload->>'company_id')::int = %s
              AND pa.reviewed_at > NOW() - (%s || ' days')::interval
            ORDER BY pa.reviewed_at""", (company_id, str(RESULT_WINDOW_DAYS)))
    results = [dict(r) for r in res]

    # what Super Admin has sent: broadcasts to everyone + direct messages to this company
    bc = execute_read(
        """SELECT title, message, COALESCE(scheduled_at, created_at) AS sent_at FROM broadcasts
            WHERE status = 'sent' ORDER BY COALESCE(scheduled_at, created_at) DESC LIMIT 10""")
    broadcasts = [{"title": b["title"], "message": b["message"], "sent_at": b["sent_at"].isoformat()} for b in bc]
    ms = execute_read(
        """SELECT subject, body, sent_at FROM company_messages WHERE company_id = %s
            ORDER BY sent_at DESC LIMIT 50""", (company_id,))
    messages = [{"subject": m["subject"], "body": m["body"], "sent_at": m["sent_at"].isoformat()} for m in ms]

    return {"company": company, "parameters": parameters, "admins": admins, "approval_results": results,
            "broadcasts": broadcasts, "messages": messages}


def _version(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()[:16]


def queue_node_ack(alert_id: int, acknowledged_by: str) -> bool:
    """Super Admin acknowledged an alert on the main server: if it belongs to a company server, make that
    server's own copy acknowledged too (sent with its next heartbeat). Returns True if queued."""
    try:
        r = execute_read("SELECT company_id, node_alert_id FROM alerts WHERE id = %s", (alert_id,))
        if not r or r[0].get("node_alert_id") is None or r[0].get("company_id") is None:
            return False
        execute_write("INSERT INTO node_ack_queue (company_id, node_alert_id, acknowledged_by) VALUES (%s, %s, %s)",
                      (r[0]["company_id"], r[0]["node_alert_id"], acknowledged_by))
        return True
    except Exception as exc:
        logger.warning("hub: could not queue the acknowledgement for the company server: %s", exc)
        return False


def mark_acks_delivered(company_id: int, ids) -> None:
    try:
        ids = [int(i) for i in (ids or [])][:500]
        if ids:
            execute_write("UPDATE node_ack_queue SET delivered_at = NOW() WHERE company_id = %s AND id = ANY(%s) AND delivered_at IS NULL",
                          (company_id, ids))
    except Exception as exc:
        logger.debug("hub: mark_acks_delivered failed: %s", exc)


def build_commands_for(company_id: int, node_status: dict) -> list:
    cmds: list = [{"type": "license", "payload": license_for(company_id)}]
    try:   # acknowledgements Super Admin made here for this company's alerts
        mark_acks_delivered(company_id, (node_status or {}).get("acks_applied"))
        pend = execute_read("SELECT id, node_alert_id, acknowledged_by FROM node_ack_queue "
                            "WHERE company_id = %s AND delivered_at IS NULL ORDER BY id LIMIT 50", (company_id,))
        if pend:
            cmds.append({"type": "ack_alerts", "payload": {"items": [
                {"id": r["id"], "alert_id": r["node_alert_id"], "by": r["acknowledged_by"]} for r in pend]}})
    except Exception as exc:
        logger.debug("hub: no acknowledgement commands: %s", exc)
    try:   # the Tailscale invitation link Super Admin saved: every company server shows it to its admins
        rows = execute_read("SELECT key, value FROM app_settings WHERE key IN ('tailscale_invite_url', 'tailscale_hub_address')")
        ts = {r["key"]: r["value"] for r in rows}
        if ts.get("tailscale_invite_url") or ts.get("tailscale_hub_address"):
            cmds.append({"type": "tailscale", "payload": {"invite_url": ts.get("tailscale_invite_url", ""),
                                                           "hub_address": ts.get("tailscale_hub_address", "")}})
    except Exception as exc:
        logger.debug("hub: tailscale setting unavailable: %s", exc)
    try:
        snap = snapshot_for(company_id)
        ver = _version(snap)
        if node_status.get("sync_version") != ver:
            cmds.append({"type": "sync_state", "payload": {"version": ver, **snap}})
    except Exception as exc:
        logger.error("hub: could not build sync state for company %s: %s", company_id, exc)
    return cmds


# ── node → hub ───────────────────────────────────────────────────────────────

def _requesting_admin(company_id: int, name: str | None) -> int | None:
    r = execute_read("SELECT id FROM admins WHERE company_id = %s AND name = %s LIMIT 1", (company_id, name or ""))
    if r:
        return r[0]["id"]
    r = execute_read("SELECT id FROM admins WHERE company_id = %s AND role = 'main' ORDER BY id LIMIT 1", (company_id,))
    return r[0]["id"] if r else None


def _parameter_request(company_id: int, p: dict) -> None:
    name = str(p.get("name") or "").strip()
    if not name:
        return
    if execute_read(
        """SELECT 1 FROM pending_approvals WHERE status = 'pending' AND action_type = 'add_parameter'
              AND (payload->>'company_id')::int = %s AND LOWER(payload->>'name') = LOWER(%s)""",
        (company_id, name)):
        return                                           # already waiting (retry-safe)
    admin_id = _requesting_admin(company_id, p.get("admin_name"))
    if admin_id is None:
        logger.warning("hub: parameter request from company %s dropped — no admin account", company_id)
        return
    payload = {"company_id": company_id, "name": name, "unit": p.get("unit"),
               "min_value": p.get("min_value"), "max_value": p.get("max_value")}
    execute_write("INSERT INTO pending_approvals (admin_id, action_type, payload) VALUES (%s, 'add_parameter', %s)",
                  (admin_id, json.dumps(payload)))


def _parameter_delete_request(company_id: int, p: dict) -> None:
    name = str(p.get("name") or "").strip()
    row = execute_read("SELECT id FROM company_parameters WHERE company_id = %s AND name = %s", (company_id, name))
    if not row:
        return
    pid = row[0]["id"]
    if execute_read(
        """SELECT 1 FROM pending_approvals WHERE status = 'pending' AND action_type = 'delete_parameter'
              AND (payload->>'parameter_id')::int = %s""", (pid,)):
        return
    admin_id = _requesting_admin(company_id, p.get("admin_name"))
    if admin_id is None:
        return
    execute_write("INSERT INTO pending_approvals (admin_id, action_type, payload) VALUES (%s, 'delete_parameter', %s)",
                  (admin_id, json.dumps({"parameter_id": pid, "name": name, "company_id": company_id})))


def _alert(company_id: int, p: dict) -> None:
    """A node's alert, stored in the hub's own alerts table so every Super Admin alert page
    and report includes it. max_escalated=1 + node_alert_id keep the hub from re-notifying."""
    execute_write(
        """INSERT INTO alerts (parameter, value, threshold, direction, severity, timestamp,
                              acknowledged, escalation_level, max_escalated, company_id, node_alert_id)
           VALUES (%s, %s, %s, %s, %s, %s, 0, 1, 1, %s, %s)
           ON CONFLICT (company_id, node_alert_id) WHERE node_alert_id IS NOT NULL DO NOTHING""",
        (p["parameter"], p["value"], p["threshold"], p["direction"], p.get("severity", "WARNING"),
         p["timestamp"], company_id, p["node_alert_id"]))


def _alert_ack(company_id: int, p: dict) -> None:
    execute_write(
        """UPDATE alerts SET acknowledged = 1, acknowledged_by = %s, acknowledged_at = %s
            WHERE company_id = %s AND node_alert_id = %s""",
        (p.get("acknowledged_by"), p.get("acknowledged_at"), company_id, p["node_alert_id"]))


def _hourly_summary(company_id: int, p: dict) -> None:
    for r in p.get("parameters") or []:
        execute_write(
            """INSERT INTO node_hourly (company_id, hour, parameter, samples, min_value, max_value, avg_value)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (company_id, hour, parameter) DO UPDATE SET
                   samples = EXCLUDED.samples, min_value = EXCLUDED.min_value,
                   max_value = EXCLUDED.max_value, avg_value = EXCLUDED.avg_value""",
            (company_id, p["hour"], r["parameter"], r["samples"], r.get("min"), r.get("max"), r.get("avg")))


_HANDLERS = {"parameter_request": _parameter_request,
             "parameter_delete_request": _parameter_delete_request,
             "alert": _alert, "alert_ack": _alert_ack, "hourly_summary": _hourly_summary}


def process_item(company_id: int, kind: str, payload: Any) -> None:
    """Act on one uploaded item. Unknown kinds are kept in node_inbox only."""
    fn = _HANDLERS.get(kind)
    if fn and isinstance(payload, dict):
        fn(company_id, payload)
    else:
        logger.debug("hub: company %s sent '%s'", company_id, kind)

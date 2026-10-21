"""
services/sensor_company.py — which company owns this server's live sensor feed.

One SentinelEdge server reads one plant (Pro-Server EX collector / Excel / USB
sensor). Everything that comes from that feed — live readings, the global
temperature thresholds and their change history, imported CSV history — belongs
to ONE company: the sensor company. Every other company starts empty and only
sees its own data.

Resolution: app_settings.sensor_company_id if set, otherwise the oldest active
company (the one the server was installed for). Cached for 60 s.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import Header

from utils.logger import get_logger

logger = get_logger(__name__)

_cache = {"id": None, "at": 0.0}


def get_sensor_company_id() -> Optional[int]:
    now = time.monotonic()
    if _cache["id"] is not None and now - _cache["at"] < 60:
        return _cache["id"]
    cid = None
    try:
        from database.connection import execute_read
        rows = execute_read("SELECT value FROM app_settings WHERE key = 'sensor_company_id' LIMIT 1")
        if rows and str(rows[0]["value"]).strip().isdigit():
            cid = int(rows[0]["value"])
        if cid is None:
            rows = execute_read(
                "SELECT id FROM companies WHERE COALESCE(is_active, 1) != 0 ORDER BY id LIMIT 1"
            )
            cid = rows[0]["id"] if rows else None
    except Exception as exc:
        logger.warning("Could not resolve sensor company: %s", exc)
    _cache.update(id=cid, at=now)
    return cid


def require_plant_owner(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency for plant-level routes (data source, Pro-Server/OPC
    settings, backups, imported CSV history): admin login required, and the
    caller's company must own this server's sensor feed."""
    from fastapi import HTTPException
    from middleware.auth import require_admin
    admin = require_admin(authorization)
    if not owns_sensor_feed(admin.get("company_id")):
        raise HTTPException(status_code=403, detail="Not available for your company")
    return admin


def require_feed_admin(authorization: Optional[str] = Header(default=None)) -> dict:
    """Any signed-in admin may see this PC's live-source settings (Live collector / Excel)."""
    from middleware.auth import require_admin
    return require_admin(authorization)


# ── Per-source owners ────────────────────────────────────────────────────────
# Each live source on this PC can belong to a different company at the same time:
#   collector — the Pro-Server EX live collector (e.g. SRM's PLC)
#   excel     — the Excel / CSV file reader, or OPC DA (e.g. Elroi's pH logger)
# Unset → the PC's main sensor company (above).
SOURCES = ("collector", "excel")
_src_cache: dict = {}


def collector_installed() -> bool:
    """The Pro-face / Pro-Server live collector exists only on PCs where it was installed
    (the sentineledge/collector folder WITH its 32-bit Python, venv32). A copy downloaded from
    GitHub has the folder but not venv32 - such PCs use the Excel reader."""
    import os
    coll = os.path.join(os.path.dirname(__file__), "..", "..", "collector")
    return os.path.isfile(os.path.join(coll, "venv32", "Scripts", "python.exe"))


def get_source_company_id(source: str) -> Optional[int]:
    now = time.monotonic()
    hit = _src_cache.get(source)
    if hit and now - hit[1] < 5:
        return hit[0]
    cid = None
    try:
        from database.connection import execute_read
        rows = execute_read("SELECT value FROM app_settings WHERE key = %s LIMIT 1", (f"{source}_company_id",))
        if rows and str(rows[0]["value"]).strip().isdigit():
            cid = int(rows[0]["value"])
            ok = execute_read("SELECT 1 FROM companies WHERE id = %s AND COALESCE(is_active, 1) != 0", (cid,))
            if not ok:
                # The owner was deleted or switched off: the feed belongs to NOBODY now. It must
                # never fall back to another company, or this logger's readings would be stored
                # under that company.
                return None
    except Exception as exc:
        logger.warning("Could not resolve %s owner: %s", source, exc)
    if cid is None:
        cid = get_sensor_company_id()
    if cid is not None:                 # never remember "nobody": a company may be created any moment
        _src_cache[source] = (cid, now)
    return cid


def set_source_company_id(source: str, company_id: int) -> None:
    if source not in SOURCES:
        raise ValueError(source)
    from database.connection import execute_write
    execute_write(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        (f"{source}_company_id", str(company_id)))
    _src_cache.pop(source, None)
    logger.warning("Live source '%s' now belongs to company %s", source, company_id)


def invalidate_caches() -> None:
    """Forget remembered owners (call after a company is switched on / off or removed)."""
    _src_cache.clear()
    _cache.update(id=None, at=0.0)


def sources_owned_by(company_id: int) -> list:
    """The live sources (collector / excel) that currently belong to this company. Ask BEFORE the company
    is deleted: afterwards the "main company of this PC" can no longer be worked out."""
    owned = []
    try:
        from database.connection import execute_read
        _cache.update(id=None, at=0.0)
        for src in SOURCES:
            rows = execute_read("SELECT value FROM app_settings WHERE key = %s LIMIT 1", (f"{src}_company_id",))
            explicit = str(rows[0]["value"]).strip() if rows else ""
            if explicit == str(company_id) or (not explicit and get_sensor_company_id() == company_id):
                owned.append(src)
    except Exception as exc:
        logger.warning("sources_owned_by(%s) failed: %s", company_id, exc)
    return owned


def release_company(company_id: int, owned_sources: Optional[list] = None) -> list:
    """A company is being removed: switch off every live source it owned (so its logger can never
    feed another company) and forget the ownership. Returns the sources that were switched off.
    `owned_sources` = what sources_owned_by() answered before the company was deleted."""
    stopped = []
    try:
        from database.connection import execute_write
        if owned_sources is None:
            owned_sources = sources_owned_by(company_id)
        for src in SOURCES:
            if src not in owned_sources:
                continue
            if src == "collector":
                from services import data_sources
                data_sources.set_collector_enabled(False)
            else:
                import core.excel_sensor as xs
                xs.set_excel_enabled(False)
            stopped.append(src)
            execute_write("DELETE FROM app_settings WHERE key = %s", (f"{src}_company_id",))
            _src_cache.pop(src, None)
        execute_write("DELETE FROM app_settings WHERE key = 'sensor_company_id' AND value = %s", (str(company_id),))
        _cache.update(id=None, at=0.0)
    except Exception as exc:
        logger.warning("release_company(%s) failed: %s", company_id, exc)
    return stopped


def source_in_use(source: str) -> bool:
    if source == "collector":
        from services.data_sources import collector_enabled
        return collector_enabled()
    import core.excel_sensor as xs
    return bool(xs.EXCEL_LIVE_ENABLED)


def claim_source(source: str, admin: dict) -> Optional[str]:
    """The caller's company takes this source. Refused (returns a message) while another
    company is actively using it, so one company can never switch off or take over another's
    running feed by accident. Platform-level callers (no company) change nothing."""
    cid = admin.get("company_id")
    if cid is None:
        return None
    owner = get_source_company_id(source)
    if owner == cid:
        return None
    if source_in_use(source):
        from database.connection import execute_read
        r = execute_read("SELECT name FROM companies WHERE id = %s", (owner,))
        who = r[0]["name"] if r else "another company"
        label = "live collector" if source == "collector" else "Excel reader"
        return f"The {label} on this PC is in use by {who}. Ask them (or Super Admin) to switch it off first."
    set_source_company_id(source, cid)
    return None


def owns_sensor_feed(company_id: Optional[int]) -> bool:
    """True for the sensor company — and for platform-level callers with no
    company (super admin), who may see everything."""
    return company_id is None or company_id == get_sensor_company_id()


def owns_any_source(company_id: Optional[int]) -> bool:
    return company_id is None or any(get_source_company_id(s) == company_id for s in SOURCES)

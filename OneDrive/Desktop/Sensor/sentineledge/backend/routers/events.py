"""
routers/events.py — Audit trail endpoint.

Merges events from config_changes, alerts, delivery_receipts tables
into a single sorted timeline.

Endpoints:
    GET /api/events?limit=100&type=all
"""



from fastapi import APIRouter, Depends, Query
from pathlib import Path

from middleware.auth import require_admin
from database.connection import execute_read
from database.backup import _BACKUP_DIR
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["Events"])


@router.get("/events", dependencies=[Depends(require_admin)])
async def get_events(
    limit: int = Query(100, ge=1, le=500),
    type:  str = Query("all"),
):
    """
    Merged audit timeline from:
      - config_changes  → type='config'
      - alerts          → type='alert'
      - delivery_receipts → type='delivery'
      - backup files    → type='backup'

    Returns events sorted by timestamp desc.
    """
    events = []

    try:
        # Config changes
        if type in ("all", "config"):
            rows = execute_read(
                "SELECT id, changed_at as ts, changed_by, field_name, old_value, new_value "
                "FROM config_changes ORDER BY id DESC LIMIT %s", (limit,)
            )
            for r in rows:
                events.append({
                    "type":        "config",
                    "timestamp":   r["ts"],
                    "description": f"Threshold changed: {r['field_name']} "
                                   f"{r['old_value']} → {r['new_value']}",
                    "details": {
                        "changed_by": r["changed_by"],
                        "field":      r["field_name"],
                        "old":        r["old_value"],
                        "new":        r["new_value"],
                    },
                })

        # Alerts
        if type in ("all", "alert"):
            rows = execute_read(
                "SELECT id, timestamp as ts, parameter, value, severity, "
                "direction, escalation_level, acknowledged, acknowledged_by "
                "FROM alerts ORDER BY id DESC LIMIT %s", (limit,)
            )
            for r in rows:
                events.append({
                    "type":        "alert",
                    "timestamp":   r["ts"],
                    "description": f"Alert fired: {r['parameter']} "
                                   f"{r['value']:.1f}°C ({r['severity']})",
                    "details": {
                        "parameter":        r["parameter"],
                        "value":            r["value"],
                        "severity":         r["severity"],
                        "direction":        r["direction"],
                        "escalation_level": r["escalation_level"],
                        "acknowledged":     bool(r["acknowledged"]),
                        "acknowledged_by":  r["acknowledged_by"],
                    },
                })

        # Backups from filesystem
        if type in ("all", "backup"):
            try:
                backup_dir = Path(_BACKUP_DIR)
                if backup_dir.exists():
                    for f in sorted(backup_dir.glob("sentineledge_*.sql"),
                                    key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
                        mtime = f.stat().st_mtime
                        from datetime import datetime, timezone
                        ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                        events.append({
                            "type":        "backup",
                            "timestamp":   ts,
                            "description": f"Backup created: {f.name}",
                            "details": {
                                "filename": f.name,
                                "size_mb":  round(f.stat().st_size / (1024 * 1024), 2),
                            },
                        })
            except Exception as exc:
                logger.warning("backup events listing failed: %s", exc)

    except Exception as exc:
        logger.error("get_events failed: %s", exc)

    # Sort all by timestamp desc, return first N
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return events[:limit]

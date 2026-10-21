"""
services/data_sources.py — the two independent live data sources.

  Pro-Server EX live collector (proserver_collector.py POSTing readings)
  Excel reader (core/excel_sensor.py reading the Excel/CSV file Pro-Server EX saves)

Each has its own on/off switch in Settings; they are stored in app_settings and
survive restarts. Defaults: collector ON, Excel reader OFF.

(Older installs stored one 'data_source' value — 'collector' or 'excel'. It is
read once on first start and converted to the two switches.)
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)

KEY_COLLECTOR = "live_collector_enabled"
KEY_EXCEL     = "excel_reader_enabled"

_collector_enabled = True


def collector_enabled() -> bool:
    return _collector_enabled


def _save(key: str, on: bool) -> None:
    from database.connection import execute_write
    execute_write(
        "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
        (key, "1" if on else "0"),
    )


def set_collector_enabled(on: bool) -> None:
    global _collector_enabled
    _collector_enabled = bool(on)
    _save(KEY_COLLECTOR, _collector_enabled)
    logger.info("Pro-Server EX live collector %s", "ENABLED" if on else "DISABLED")


def load_switches() -> bool:
    """Load both switches at startup. Returns whether the Excel reader is on."""
    global _collector_enabled
    from database.connection import execute_read, execute_write
    rows = execute_read(
        "SELECT key, value FROM app_settings WHERE key IN (%s, %s, 'data_source')",
        (KEY_COLLECTOR, KEY_EXCEL),
    ) or []
    vals = {r["key"]: r["value"] for r in rows}
    if KEY_COLLECTOR not in vals and KEY_EXCEL not in vals and "data_source" in vals:
        # One-time conversion of the old single switch
        excel_on = vals["data_source"] == "excel"
        _save(KEY_EXCEL, excel_on)
        _save(KEY_COLLECTOR, not excel_on)
        vals[KEY_EXCEL], vals[KEY_COLLECTOR] = ("1" if excel_on else "0"), ("0" if excel_on else "1")
        logger.info("Converted old data_source=%s to separate switches", vals["data_source"])
    _collector_enabled = vals.get(KEY_COLLECTOR, "1") != "0"
    return vals.get(KEY_EXCEL, "0") == "1"

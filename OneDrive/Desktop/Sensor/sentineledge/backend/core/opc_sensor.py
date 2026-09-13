"""
core/opc_sensor.py — OPC DA secondary sensor reader.

Connects to a Pro-Server EX OPC DA server and reads tag values as a
SECONDARY fallback alongside the Excel file reader.

Priority in main.py:
  1. excel_sensor  — primary  (Pro-Server EX XLS/CSV file polling)
  2. opc_sensor    — secondary (OPC DA direct connection) ← this file
  3. extra_sensor  — stub     (empty dict, always last resort)

OPC DA requires ONE of the following Python packages:
  pip install OpenOPC-Python3       (preferred — pure Python OPC DA client)
  pip install pywin32               (fallback — uses Graybox OPC Automation COM)

Configuration (env vars or Admin → Settings → OPC DA):
  OPC_SERVER_NAME   — OPC server ProgID, e.g. "Pro-face.ProServer"
  OPC_TEMP_TAG      — tag path for temperature, e.g. "Device1.Temperature"
  OPC_EXTRA_TAGS    — comma-separated "Label:TagPath" pairs
                      e.g. "pH:Device1.pH,DO:Device1.DO"
  OPC_POLL_INTERVAL — seconds between polls (default 2.0)
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

from utils.logger import get_logger
from utils.time import now_iso

logger = get_logger("sentineledge.opc_sensor")

# ── Configuration (mutable — updated by reload_settings) ──────────────────────
OPC_SERVER_NAME   : str   = os.environ.get("OPC_SERVER_NAME",   "").strip()
OPC_TEMP_TAG      : str   = os.environ.get("OPC_TEMP_TAG",      "").strip()
OPC_EXTRA_TAGS    : str   = os.environ.get("OPC_EXTRA_TAGS",    "").strip()
OPC_POLL_INTERVAL : float = float(os.environ.get("OPC_POLL_INTERVAL", "2.0"))

# ── Shared state — same public interface as excel_sensor ──────────────────────
current_temperature : Optional[float]  = None
current_timestamp   : str              = ""
extra_readings      : Dict[str, float] = {}

# ── Internal status ────────────────────────────────────────────────────────────
_active     : bool = False   # True when connected AND delivering valid data
_connected  : bool = False   # True when last OPC read succeeded
_last_error : str  = ""      # last error message, cleared on success

# ── Thread control ─────────────────────────────────────────────────────────────
_stop_evt   : threading.Event            = threading.Event()
_thread_ref : Optional[threading.Thread] = None


# ── Public helpers ─────────────────────────────────────────────────────────────

def is_active() -> bool:
    """True when OPC is configured, connected, and producing temperature data."""
    return _active


def get_status() -> dict:
    """Return OPC connection status for the Settings / Health pages."""
    return {
        "connected":      _connected,
        "active":         _active,
        "server_name":    OPC_SERVER_NAME,
        "temp_tag":       OPC_TEMP_TAG,
        "extra_tags":     OPC_EXTRA_TAGS,
        "poll_interval":  OPC_POLL_INTERVAL,
        "last_error":     _last_error,
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _parse_extra_tags(raw: str) -> Dict[str, str]:
    """
    Parse "pH:Device1.pH,DO:Device1.DO" → {"pH": "Device1.pH", "DO": "Device1.DO"}.
    Whitespace around separators is stripped.
    """
    result: Dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if ":" in part:
            label, tag = part.split(":", 1)
            label = label.strip()
            tag   = tag.strip()
            if label and tag:
                result[label] = tag
    return result


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── OPC DA client implementations (tried in order) ───────────────────────────

def _read_via_openopc(tags: list) -> Optional[Dict[str, object]]:
    """
    Read via OpenOPC-Python3 (pip install OpenOPC-Python3).
    Returns {tag_path: value} for Good-quality tags, or None on failure.
    """
    try:
        import OpenOPC  # type: ignore[import-untyped]
    except ImportError:
        return None

    opc = None
    try:
        opc = OpenOPC.client()
        opc.connect(OPC_SERVER_NAME)
        result: Dict[str, object] = {}
        for item in opc.read(tags):
            tag, val, quality = item[0], item[1], item[2]
            if "Good" in str(quality):
                result[tag] = val
        return result
    except Exception as exc:
        logger.debug("OPC OpenOPC read error: %s", exc)
        return None
    finally:
        if opc is not None:
            try:
                opc.close()
            except Exception:
                pass


def _read_via_win32com(tags: list) -> Optional[Dict[str, object]]:
    """
    Read via pywin32 + OPC DA Automation COM wrapper (Graybox 2.02 or similar).
    pip install pywin32  AND  install Graybox OPC DA Automation 2.02 from
    https://www.opcsupport.com/s/article/What-is-the-OPC-DA-Automation-Wrapper
    Returns {tag_path: value} for Good-quality tags, or None on failure.
    """
    try:
        import win32com.client  # type: ignore[import-untyped]
    except ImportError:
        return None

    opc = None
    try:
        opc = win32com.client.Dispatch("OPC.Automation.1")
        opc.Connect(OPC_SERVER_NAME)

        groups = opc.OPCGroups
        grp    = groups.Add("SentinelEdge_Read")
        items  = grp.OPCItems

        handle_map: Dict[int, str] = {}
        for i, tag in enumerate(tags, start=1):
            item = items.AddItem(tag, i)
            handle_map[i] = tag

        handles   = list(handle_map.keys())
        grp.SyncRead(1, len(handles), handles, None, None, None)

        result: Dict[str, object] = {}
        for handle, tag in handle_map.items():
            opc_item = items.Item(tag)
            if opc_item.Quality == 192:   # OPC_QUALITY_GOOD
                result[tag] = opc_item.Value

        return result

    except Exception as exc:
        logger.debug("OPC win32com read error: %s", exc)
        return None
    finally:
        if opc is not None:
            try:
                opc.Disconnect()
            except Exception:
                pass


def _read_tags(tags: list) -> Optional[Dict[str, object]]:
    """Try OpenOPC first, then win32com OPC Automation."""
    result = _read_via_openopc(tags)
    if result is not None:
        return result
    return _read_via_win32com(tags)


# ── Background polling thread ─────────────────────────────────────────────────

def _poll_loop(stop_evt: threading.Event) -> None:
    global current_temperature, current_timestamp, extra_readings
    global _active, _connected, _last_error

    extra_tag_map = _parse_extra_tags(OPC_EXTRA_TAGS)

    all_tags: list = []
    if OPC_TEMP_TAG:
        all_tags.append(OPC_TEMP_TAG)
    all_tags.extend(extra_tag_map.values())

    logger.info(
        "OPC DA secondary reader started: server='%s' tags=%s every %.1f s",
        OPC_SERVER_NAME, all_tags, OPC_POLL_INTERVAL,
    )

    while not stop_evt.is_set():
        try:
            if not all_tags:
                stop_evt.wait(OPC_POLL_INTERVAL)
                continue

            values = _read_tags(all_tags)

            if values is None:
                if _connected:
                    logger.warning("OPC DA: connection to '%s' lost — will retry", OPC_SERVER_NAME)
                _connected  = False
                _active     = False
                _last_error = f"Could not read from OPC server '{OPC_SERVER_NAME}'"
                stop_evt.wait(OPC_POLL_INTERVAL)
                continue

            _connected  = True
            _last_error = ""

            # ── Temperature ───────────────────────────────────────────────────
            if OPC_TEMP_TAG and OPC_TEMP_TAG in values:
                temp_val = _to_float(values[OPC_TEMP_TAG])
                if temp_val is not None:
                    current_temperature = round(temp_val, 3)
                    current_timestamp   = now_iso()
                    _active = True

            # ── Extra params (pH, DO, etc.) ────────────────────────────────────
            new_extras: Dict[str, float] = {}
            for label, tag in extra_tag_map.items():
                if tag in values:
                    val = _to_float(values[tag])
                    if val is not None:
                        new_extras[label] = round(val, 3)
            extra_readings.clear()
            extra_readings.update(new_extras)

            logger.debug(
                "OPC DA | T=%.3f ts=%s extras=%s",
                current_temperature or 0.0,
                current_timestamp,
                extra_readings,
            )

        except Exception as exc:
            _last_error = str(exc)[:200]
            logger.warning("OPC DA reader error: %s", exc)

        stop_evt.wait(OPC_POLL_INTERVAL)


# ── Hot-reload — called after saving settings in the UI ──────────────────────

def reload_settings(values: Dict[str, str]) -> None:
    """
    Apply new OPC settings from db_values and restart the polling thread.
    db_values keys: server_name, temp_tag, extra_tags, poll_interval
    """
    global OPC_SERVER_NAME, OPC_TEMP_TAG, OPC_EXTRA_TAGS, OPC_POLL_INTERVAL
    global current_temperature, current_timestamp, extra_readings
    global _active, _connected, _last_error
    global _stop_evt, _thread_ref

    def _s(k: str, default: str = "") -> str:
        v = values.get(k)
        return str(v).strip() if v is not None else default

    OPC_SERVER_NAME   = _s("server_name")
    OPC_TEMP_TAG      = _s("temp_tag")
    OPC_EXTRA_TAGS    = _s("extra_tags")
    try:
        OPC_POLL_INTERVAL = float(values.get("poll_interval") or 2.0)
    except (TypeError, ValueError):
        OPC_POLL_INTERVAL = 2.0

    # Stop the old thread
    old_stop  = _stop_evt
    _stop_evt = threading.Event()
    old_stop.set()
    if _thread_ref and _thread_ref.is_alive():
        _thread_ref.join(timeout=5.0)

    # Reset shared state
    current_temperature = None
    current_timestamp   = ""
    extra_readings      = {}
    _active     = False
    _connected  = False
    _last_error = ""

    if OPC_SERVER_NAME and (OPC_TEMP_TAG or OPC_EXTRA_TAGS):
        _thread_ref = threading.Thread(
            target=_poll_loop,
            args=(_stop_evt,),
            daemon=True,
            name="opc-da-reader",
        )
        _thread_ref.start()
        logger.info("OPC DA reader restarted: server=%s", OPC_SERVER_NAME)
    else:
        _thread_ref = None
        logger.info("OPC DA reader stopped (no server/tags configured)")


# ── Auto-start on import ───────────────────────────────────────────────────────
if OPC_SERVER_NAME and (OPC_TEMP_TAG or OPC_EXTRA_TAGS):
    _thread_ref = threading.Thread(
        target=_poll_loop,
        args=(_stop_evt,),
        daemon=True,
        name="opc-da-reader",
    )
    _thread_ref.start()
else:
    logger.debug(
        "OPC DA reader: OPC_SERVER_NAME not set — inactive "
        "(configure via Admin → Settings → OPC DA)"
    )

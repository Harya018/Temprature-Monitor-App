"""
core/extra_sensor.py — Secondary sensor reader for approved custom parameters.

Runs a background thread that:
  1. Waits 20 s at startup so the temperature sensor has priority.
  2. Scans all COM ports NOT used by the temperature sensor or GSM modem.
  3. Probes each port at 9600 / 115200 / 4800 baud.
  4. Tries to parse readings in multiple formats:
       • Bare float      "7.23\\n"
       • key:value       "ph:7.23\\n"
       • key=value       "pH=7.23\\n"
       • CSV (key,val)   "ph,7.23\\n"
       • Multi-CSV       "ph,7.23,temp,25.0\\n"
  5. Maps each reading to an approved company_parameter name via:
       (a) label substring match  →  best
       (b) value within param's min/max range
       (c) pH heuristic (0–14)   →  look for a param named "ph…"
       (d) first approved param   →  last resort
  6. Stores live values in `extra_readings` dict.

main.py merges `extra_readings` into every WebSocket payload as "extra_params".
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger("sentineledge.extra_sensor")

# Shared state — {parameter_name: float_value}
# Read by main.py on every broadcast; written by _read_continuous().
extra_readings: Dict[str, float] = {}

_STARTUP_DELAY  = 20   # seconds before first scan (temp sensor gets priority)
_SCAN_INTERVAL  = 12   # seconds between scans when no secondary sensor found
_BAUD_RATES     = (9600, 115200, 4800)
_MODEM_KW       = ("sim7600", "sim76", "simcom", "qualcomm hs-usb", "at command")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _excluded_ports() -> set:
    """Ports already claimed by the temperature sensor or GSM modem."""
    ex: set = set()
    try:
        from core.sensor import _confirmed_sensor_port as _t
        if _t:
            ex.add(_t)
    except Exception:
        pass
    try:
        from modules.sms.sim7600_sender import _confirmed_port as _g
        if _g:
            ex.add(_g)
    except Exception:
        pass
    return ex


def _approved_params() -> list:
    """Fetch active company_parameters rows from DB. Returns [] on any error."""
    try:
        from database.connection import execute_read
        rows = execute_read(
            "SELECT name, unit, min_value, max_value "
            "FROM company_parameters WHERE is_active = TRUE ORDER BY name"
        )
        return [dict(r) for r in (rows or [])]
    except Exception:
        return []


def _parse_line(raw: str) -> Optional[tuple]:
    """
    Parse one serial line into (label, float_value) or None.
    label is a lowercased string or None for bare floats.
    """
    line = raw.strip()
    if not line:
        return None

    # key:value or key=value
    for sep in (":", "="):
        if sep in line:
            k, _, v_part = line.partition(sep)
            k = k.strip().lower().replace(" ", "_")
            v_tok = v_part.strip().split()[0] if v_part.strip() else ""
            if k and v_tok:
                try:
                    return (k, float(v_tok))
                except ValueError:
                    pass

    # CSV: "label,float[,...]"  — only when first token is non-numeric
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 2:
        try:
            float(parts[0])           # numeric first token → not labeled CSV
        except ValueError:
            try:
                return (parts[0].lower().replace(" ", "_"), float(parts[1]))
            except (ValueError, IndexError):
                pass

    # Bare float
    try:
        return (None, float(line))
    except ValueError:
        return None


def _match_param(label: Optional[str], value: float, params: list) -> Optional[str]:
    """Map (label, value) → approved parameter name using priority rules."""
    if not params:
        return None

    # 1. Label substring match
    if label:
        for p in params:
            pn = p["name"].lower()
            if label in pn or pn in label:
                return p["name"]

    # 2. Value inside configured min/max range
    for p in params:
        try:
            mn, mx = float(p["min_value"]), float(p["max_value"])
            if mn <= value <= mx:
                return p["name"]
        except (TypeError, ValueError):
            pass

    # 3. pH heuristic — 0..14 range and a param named "ph*" exists
    if 0.0 <= value <= 14.0:
        for p in params:
            if "ph" in p["name"].lower():
                return p["name"]

    # 4. Last resort — first approved param
    return params[0]["name"]


def _probe_port(device: str, baud: int, timeout: float = 3.0) -> Optional[Dict[str, float]]:
    """
    Open port, read lines for `timeout` seconds.
    Returns {param_name: value} if any readings mapped, else None.
    """
    try:
        import serial  # type: ignore
    except ImportError:
        return None

    params = _approved_params()
    if not params:
        return None

    collected: Dict[str, float] = {}
    ser = None
    try:
        ser = serial.Serial(port=device, baudrate=baud, timeout=1.0)
        ser.reset_input_buffer()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = ser.readline()
                if not raw:
                    continue
                parsed = _parse_line(raw.decode("utf-8", errors="ignore"))
                if parsed is None:
                    continue
                label, value = parsed
                name = _match_param(label, value, params)
                if name:
                    collected[name] = round(value, 3)
            except Exception:
                continue
        return collected if collected else None
    except Exception:
        return None
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


# ── Background reader ─────────────────────────────────────────────────────────

class ExtraParamReader:
    """
    Daemon thread that auto-detects and continuously reads secondary sensors.
    Updates `extra_readings` so main.py can include values in WebSocket payloads.
    """

    def __init__(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="extra-param-reader"
        )
        self._thread.start()

    def _run(self) -> None:
        time.sleep(_STARTUP_DELAY)
        logger.info("ExtraParamReader: starting secondary sensor scan")

        while self._running:
            port, baud = self._scan()
            if port is None:
                time.sleep(_SCAN_INTERVAL)
                continue
            logger.info("ExtraParamReader: reading from %s @ %d baud", port, baud)
            self._read_continuous(port, baud)
            logger.info("ExtraParamReader: %s disconnected — scanning again", port)

    def _scan(self) -> tuple:
        """Return (device, baud) of the first secondary sensor found, or (None, 0)."""
        try:
            import serial.tools.list_ports  # type: ignore
            excluded  = _excluded_ports()
            all_ports = list(serial.tools.list_ports.comports())
            candidates = [
                p for p in all_ports
                if p.device not in excluded
                and not any(kw in (p.description or "").lower() for kw in _MODEM_KW)
            ]
            for baud in _BAUD_RATES:
                for p in candidates:
                    result = _probe_port(p.device, baud)
                    if result:
                        extra_readings.update(result)
                        return (p.device, baud)
        except Exception as exc:
            logger.debug("ExtraParamReader: scan error: %s", exc)
        return (None, 0)

    def _read_continuous(self, port: str, baud: int) -> None:
        try:
            import serial  # type: ignore
        except ImportError:
            return

        params = _approved_params()
        last_refresh = time.monotonic()

        try:
            with serial.Serial(port=port, baudrate=baud, timeout=1.0) as ser:
                errors = 0
                while self._running:
                    # Refresh param list every 60 s (new approvals may arrive)
                    if time.monotonic() - last_refresh > 60:
                        params = _approved_params()
                        last_refresh = time.monotonic()

                    # Stop if port is now claimed by another reader
                    if port in _excluded_ports():
                        break

                    try:
                        raw = ser.readline()
                        if not raw:
                            errors += 1
                            if errors > 15:
                                break
                            continue
                        errors = 0
                        parsed = _parse_line(raw.decode("utf-8", errors="ignore"))
                        if parsed is None:
                            continue
                        label, value = parsed
                        name = _match_param(label, value, params)
                        if name:
                            extra_readings[name] = round(value, 3)
                    except Exception:
                        errors += 1
                        if errors > 5:
                            break
        except Exception as exc:
            logger.debug("ExtraParamReader: serial error on %s: %s", port, exc)


# Singleton — background thread starts on first import of this module.
reader = ExtraParamReader()

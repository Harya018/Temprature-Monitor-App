# -*- coding: utf-8 -*-
"""
core/sensor.py — Real client CSV data playback.

Reads 9 CSV files of real machine cooling data from backend/data/.
Replays them row by row at 1 reading/second (normal mode) or
at an accelerated speed for demonstrations (demo mode).

CSV format: timestamp, temperature, reference_value
  Column 1: original timestamp  (ignored — we use current time)
  Column 2: temperature value   (used)
  Column 3: reference value     (ignored)

Fallback: if no CSV files are found a synthetic cooling curve is
generated so the system still works during initial setup.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Optional

from config import MODULE_STATUS, SENSOR_PORT, SENSOR_BAUD
from utils.time import now_iso

# ─── Data directory ───────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"

# Playback order for all client CSV files
_CSV_FILE_ORDER = [
    "01.04.2026_Run1.csv",
    "01.04.2026_Run2.csv",
    "01.04.2026_Run3.csv",
    "02.04.2026_Run1.csv",
    "02.04.2026_Run2.csv",
    "02.04.2026_Run3.csv",
    "06.04.2026_Run1.csv",
    "08.04.2026_Run1.csv",
    "08.04.2026_Run2.csv",
]


# ─── CSV Sensor Player ────────────────────────────────────────────────────────

class CSVSensorPlayer:
    """
    Plays back real client CSV data row by row.

    Normal mode : 1 reading per second (real-time, ~2.5 hrs per full cycle).
    Demo mode   : accelerated playback (e.g. 30x → ~5 minutes per cycle).
    """

    def __init__(self) -> None:
        self.readings:   list[float] = []
        self.index:      int         = 0
        self.demo_mode:  bool        = False
        self.demo_speed: int         = 30
        self._load_all_files()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load_all_files(self) -> None:
        """Load all CSV files in playback order."""
        for filename in _CSV_FILE_ORDER:
            filepath = DATA_DIR / filename
            if filepath.exists():
                self._load_file(filepath)

        if not self.readings:
            # Fallback: synthetic cooling curve if no CSV files present
            print("Sensor: no CSV files found -- using synthetic cooling curve")
            temp = 88.0
            for _ in range(9000):
                self.readings.append(round(temp, 1))
                temp -= 0.005 + (0.002 * (temp / 90.0))
                temp = max(35.0, temp)
        else:
            print(f"Sensor: loaded {len(self.readings)} readings from CSV")

    def _load_file(self, filepath: Path) -> None:
        """Parse a single CSV file and append valid temperature values."""
        loaded = 0
        try:
            with open(filepath, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(",")
                    if len(parts) < 2:
                        continue
                    try:
                        temp = float(parts[1].strip())
                        # Accept realistic machine temperatures only
                        if 20.0 <= temp <= 100.0:
                            self.readings.append(round(temp, 1))
                            loaded += 1
                    except ValueError:
                        continue  # skip header row or bad data
        except Exception as exc:
            print(f"Sensor: warning - could not load {filepath.name}: {exc}")
        else:
            if loaded:
                print(f"Sensor: {filepath.name} -> {loaded} readings")

    # ── Reading ───────────────────────────────────────────────────────────────

    def get_reading(self) -> dict:
        """Return the next temperature reading and advance the index."""
        if not self.readings:
            return {"temperature": 65.0, "timestamp": now_iso()}

        temp = self.readings[self.index]
        self.index = (self.index + 1) % len(self.readings)

        return {"temperature": temp, "timestamp": now_iso()}

    # ── Controls ──────────────────────────────────────────────────────────────

    def activate_demo(self, speed: int = 30) -> None:
        """Switch to accelerated demo playback and rewind to the beginning."""
        self.demo_mode  = True
        self.demo_speed = max(1, speed)
        self.index      = 0
        total_secs      = len(self.readings) / self.demo_speed
        print(
            f"Sensor: demo mode ON — {speed}x speed, "
            f"~{total_secs / 60:.1f} min for full cycle"
        )

    def reset(self) -> None:
        """Stop demo mode and rewind to the start of the data."""
        self.demo_mode = False
        self.index     = 0
        print("Sensor: reset to normal playback from beginning")


# ─── Serial Sensor Reader ─────────────────────────────────────────────────────

# Manufacturer/description keywords that suggest a USB temperature sensor
# (distinct from SIM7600 modem keywords used in sim7600_sender.py).
_SENSOR_KEYWORDS = (
    "usb serial", "usb-serial", "ch340", "cp210", "ft232",
    "arduino", "ftdi", "prolific", "silicon labs",
)
_SENSOR_CANDIDATE_BLACKLIST = (
    "sim7600", "sim76", "simcom", "qualcomm hs-usb", "at command",
    "audio", "microphone", "headset",
)

# Module-level confirmed sensor port cache — shared with health.py if needed.
_confirmed_sensor_port: Optional[str] = None


def _scan_sensor_port(baud: int, timeout: float = 2.0) -> Optional[str]:
    """
    Scan all COM ports for a USB temperature sensor.

    For each candidate:
      1. Open port at the configured baud rate.
      2. Read one line within *timeout* seconds.
      3. If the line parses as a float in the realistic range [0, 200], confirm.

    Returns the device string (e.g. 'COM3') or None if nothing found.
    Never raises.
    """
    global _confirmed_sensor_port

    try:
        import serial                          # type: ignore
        import serial.tools.list_ports        # type: ignore
    except ImportError:
        return None

    try:
        all_ports = list(serial.tools.list_ports.comports())
    except Exception:
        return None

    # Check configured port first (if SENSOR_PORT is set explicitly)
    configured = (SENSOR_PORT or "").strip()
    if configured:
        print(f"Sensor: trying configured port {configured}")
        candidates = [p for p in all_ports if p.device == configured]
        candidates += [p for p in all_ports if p.device != configured]
    else:
        # Sort: prefer ports whose description matches sensor keywords
        def _rank(p):
            desc = (p.description or "").lower()
            if any(kw in desc for kw in _SENSOR_KEYWORDS):
                return 0
            if any(kw in desc for kw in _SENSOR_CANDIDATE_BLACKLIST):
                return 99
            return 1
        candidates = sorted(all_ports, key=_rank)

    for p in candidates:
        desc = (p.description or "").lower()
        if any(kw in desc for kw in _SENSOR_CANDIDATE_BLACKLIST):
            continue  # skip modem/audio ports

        ser = None
        try:
            ser = serial.Serial(port=p.device, baudrate=baud, timeout=timeout)
            ser.reset_input_buffer()
            raw = ser.readline()
            if not raw:
                continue
            line_str = raw.decode("utf-8", errors="ignore").strip()
            temp = float(line_str)
            # 15.0 lower bound: excludes pH readings (0–14) and unrealistic ambient temps
            if 15.0 <= temp <= 200.0:
                print(f"Sensor: auto-detected on {p.device} ({p.description}) — reading {temp}°C")
                _confirmed_sensor_port = p.device
                return p.device
        except Exception:
            pass
        finally:
            if ser is not None and getattr(ser, "is_open", False):
                try:
                    ser.close()
                except Exception:
                    pass

    return None


class AdaptiveSensorReader:
    """
    Always-on sensor adapter — no DEMO_MODE flag required.

    • Starts immediately with CSV playback (no hardware needed).
    • Background thread scans all COM ports every 10 seconds.
    • When a USB temperature sensor is detected the reader switches
      seamlessly to live serial data — no server restart needed.
    • If the sensor disconnects, falls back to CSV and resumes scanning.

    get_reading() stamps every result with is_live=True (real sensor)
    or is_live=False (CSV fallback) so callers can gate alert logic.
    """

    _SCAN_INTERVAL = 10  # seconds between port scans when no sensor found

    def __init__(self) -> None:
        self._csv            = CSVSensorPlayer()
        self._live_temp: Optional[float] = None   # None → use CSV
        self._running        = True
        self._baud: int      = SENSOR_BAUD

        self._thread = threading.Thread(
            target=self._scan_loop, daemon=True, name="adaptive-sensor"
        )
        self._thread.start()

    # ── Public properties (API-compatible with CSVSensorPlayer) ──────────────

    @property
    def is_live(self) -> bool:
        """True while a real USB sensor is actively connected and reading."""
        return self._live_temp is not None

    @property
    def demo_mode(self) -> bool:
        return self._csv.demo_mode

    @property
    def demo_speed(self) -> int:
        return self._csv.demo_speed

    @property
    def readings(self) -> list:
        return self._csv.readings

    # ── Reading ───────────────────────────────────────────────────────────────

    def get_reading(self) -> dict:
        if self._live_temp is not None:
            return {"temperature": self._live_temp, "timestamp": now_iso(), "is_live": True}
        reading = self._csv.get_reading()
        reading["is_live"] = False
        return reading

    # ── Controls (delegated to CSV player) ────────────────────────────────────

    def activate_demo(self, speed: int = 30) -> None:
        self._csv.activate_demo(speed)

    def reset(self) -> None:
        self._csv.reset()

    # ── Background scan + read loop ───────────────────────────────────────────

    def _scan_loop(self) -> None:
        global _confirmed_sensor_port

        while self._running:
            # Phase 1 — scan for a sensor (blocks up to timeout per port)
            port = _scan_sensor_port(self._baud)
            if port is None:
                time.sleep(self._SCAN_INTERVAL)
                continue

            # Phase 2 — sensor found: read continuously until it errors/disconnects
            _confirmed_sensor_port = port
            print(f"Sensor: switching to LIVE mode on {port}")
            self._read_serial(port)

            # Phase 3 — sensor gone: reset and resume scanning
            self._live_temp        = None
            _confirmed_sensor_port = None
            print("Sensor: disconnected — resuming CSV fallback, scanning every 10 s")

    def _read_serial(self, port: str) -> None:
        """Read from the confirmed serial port until it errors or disconnects."""
        try:
            import serial  # type: ignore
        except ImportError:
            return

        try:
            with serial.Serial(port, self._baud, timeout=1.0) as ser:
                while self._running:
                    line = ser.readline()
                    if not line:
                        continue
                    line_str = line.decode("utf-8", errors="ignore").strip()
                    if not line_str:
                        continue
                    try:
                        temp = float(line_str)
                        if 15.0 <= temp <= 200.0:
                            self._live_temp = temp
                    except ValueError:
                        pass
        except Exception as exc:
            print(f"Sensor: serial error on {port}: {exc}")


# ─── Singleton instance ───────────────────────────────────────────────────────
# AdaptiveSensorReader always starts with CSV fallback and auto-detects
# a real USB sensor every 10 seconds — no DEMO_MODE flag required.
player = AdaptiveSensorReader()



# ─── Breach override (for /api/simulate/breach) ───────────────────────────────
_breach_override_remaining: int   = 0
_breach_override_value:     float = 92.0   # above 90.0 HIGH threshold


def set_breach_override(ticks: int = 10, value: float = 92.0) -> None:
    """Force temperature to `value` for the next `ticks` readings."""
    global _breach_override_remaining, _breach_override_value
    _breach_override_remaining = ticks
    _breach_override_value     = value


# ─── Public API ───────────────────────────────────────────────────────────────

def get_reading() -> dict:
    """
    Return one sensor reading.

    Priority:
      1. Breach override (forced value for N ticks — for testing)
      2. Normal CSV playback (or demo-speed CSV playback)
    """
    global _breach_override_remaining
    if _breach_override_remaining > 0:
        _breach_override_remaining -= 1
        return {"temperature": _breach_override_value, "timestamp": now_iso()}

    return player.get_reading()


def activate_demo(speed: int = 30) -> dict:
    """Activate demo mode at the given speed multiplier."""
    player.activate_demo(speed)
    total_readings = len(player.readings)
    duration_secs  = total_readings / speed
    return {
        "status":                     "demo_started",
        "speed":                      speed,
        "total_readings":             total_readings,
        "estimated_duration_minutes": round(duration_secs / 60, 1),
    }


def reset_sensor() -> dict:
    """Stop demo mode and rewind playback to the start."""
    player.reset()
    return {"status": "reset", "message": "Sensor reset to beginning of data"}


async def stream_readings():
    """Async generator — yields one reading per tick indefinitely."""
    MODULE_STATUS["sensor"] = "ok"
    while True:
        yield get_reading()
        # Normal: 1 second per reading (real machine speed)
        # Demo:   1/speed seconds per reading (compressed)
        # Live sensor: always 1 s (hardware rate).
        # CSV + demo mode: accelerated. CSV + normal: 1 s.
        delay = (1.0 / player.demo_speed) if (player.demo_mode and not player.is_live) else 1.0
        await asyncio.sleep(delay)

"""
backend/sms_dongle/dongle_detector.py
======================================
Auto-detects a GSM USB dongle by scanning COM1–COM20 on Windows.

Sends an AT command to each candidate port; the first port that
replies with "OK" is assumed to be the GSM modem.

Also provides a blocking monitor loop that logs plug/unplug events.

Standalone — zero imports from the main SentinelEdge project.
Requires: pyserial  (pip install pyserial)
"""

import logging
import time
from typing import Optional

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

logger = logging.getLogger("sms_dongle.detector")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Constants ──────────────────────────────────────────────────────────────────
BAUD_RATES        = [9600, 115200]    # try 9600 first, then 115200
AT_TIMEOUT        = 3                 # seconds to wait for AT response
MONITOR_INTERVAL  = 5                 # seconds between plug/unplug checks
MAX_COM_PORT      = 20                # scan COM1 to COM20


# ── Helpers ────────────────────────────────────────────────────────────────────

def _list_candidate_ports() -> list[str]:
    """
    Return a sorted list of COM port names that are currently available
    on the system (uses pyserial's port enumerator, capped at COM20).
    Falls back to COM1–COM20 brute-force scan if enumeration fails.
    """
    if not SERIAL_AVAILABLE:
        logger.error("pyserial is not installed. Run: pip install pyserial")
        return []

    try:
        ports = [p.device for p in serial.tools.list_ports.comports()]
        # Filter to COM1–COM20 only
        filtered = [
            p for p in ports
            if p.upper().startswith("COM") and
               p[3:].isdigit() and
               1 <= int(p[3:]) <= MAX_COM_PORT
        ]
        if filtered:
            logger.debug("Enumerated COM ports: %s", filtered)
            return sorted(filtered, key=lambda x: int(x[3:]))
    except Exception as exc:
        logger.warning("Port enumeration failed (%s), falling back to brute-force scan", exc)

    # Brute-force fallback
    return [f"COM{i}" for i in range(1, MAX_COM_PORT + 1)]


def _probe_port(port: str, baud: int) -> Optional[dict]:
    """
    Try to open `port` at `baud` and send an AT command.

    Returns a dict with port info if the dongle responds with "OK",
    otherwise returns None.

    Dict keys:
        port     (str)  — e.g. "COM3"
        baud     (int)  — baud rate that worked
        response (str)  — raw response from the modem
        model    (str)  — ATI response (model info), or empty string
    """
    try:
        with serial.Serial(
            port=port,
            baudrate=baud,
            timeout=AT_TIMEOUT,
            write_timeout=AT_TIMEOUT,
        ) as ser:
            # Flush any stale data
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Send basic AT ping
            ser.write(b"AT\r\n")
            time.sleep(0.5)
            response = ser.read(ser.in_waiting or 64).decode("utf-8", errors="replace").strip()

            if "OK" not in response:
                return None

            logger.debug("AT OK on %s @ %d baud — response: %r", port, baud, response)

            # Optionally fetch model info
            model = ""
            try:
                ser.write(b"ATI\r\n")
                time.sleep(0.5)
                raw = ser.read(ser.in_waiting or 256).decode("utf-8", errors="replace").strip()
                # ATI response contains model name between OK lines
                lines = [l.strip() for l in raw.splitlines() if l.strip() and l.strip() != "OK"]
                model = " ".join(lines)
            except Exception:
                pass

            return {
                "port":     port,
                "baud":     baud,
                "response": response,
                "model":    model,
            }

    except serial.SerialException as exc:
        logger.debug("Cannot open %s @ %d: %s", port, baud, exc)
        return None
    except Exception as exc:
        logger.debug("Unexpected error probing %s @ %d: %s", port, baud, exc)
        return None


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_dongle() -> Optional[dict]:
    """
    Scan COM1–COM20 and return info about the first GSM dongle found.

    Returns
    -------
    dict  if a dongle is detected::
        {
            "port":     "COM3",
            "baud":     9600,
            "response": "AT\\r\\nOK",
            "model":    "Manufacturer / Model string from ATI"
        }
    None  if no dongle was found (logs a clear error message).
    """
    if not SERIAL_AVAILABLE:
        logger.error(
            "pyserial not installed. Install it with:  pip install pyserial"
        )
        return None

    candidates = _list_candidate_ports()
    if not candidates:
        logger.warning("No COM ports found on this system.")
        return None

    logger.info("Scanning %d COM port(s): %s", len(candidates), candidates)

    for port in candidates:
        for baud in BAUD_RATES:
            result = _probe_port(port, baud)
            if result:
                logger.info(
                    "GSM Dongle detected on %s @ %d baud  (model: %s)",
                    result["port"], result["baud"], result["model"] or "unknown",
                )
                return result

    logger.error(
        "No GSM dongle found on COM1–COM%d. "
        "Make sure the dongle is plugged in and in MODEM mode "
        "(not storage/CD-ROM mode). See README.md for details.",
        MAX_COM_PORT,
    )
    return None


def monitor_dongle(
    on_connect=None,
    on_disconnect=None,
    interval: int = MONITOR_INTERVAL,
) -> None:
    """
    Blocking loop that monitors for GSM dongle plug/unplug events.

    Parameters
    ----------
    on_connect     : callable(dict) | None
        Called with the dongle info dict when a dongle is plugged in.
    on_disconnect  : callable() | None
        Called (no args) when the dongle is removed.
    interval       : int
        How often to check for changes (seconds). Default: 5.

    Logs:
        "GSM Dongle detected on COM3"  when plugged in.
        "GSM Dongle disconnected"       when removed.

    Press Ctrl+C to stop the monitor.
    """
    logger.info(
        "Dongle monitor started — checking every %ds. Press Ctrl+C to stop.", interval
    )

    known_port: Optional[str] = None

    try:
        while True:
            result = detect_dongle()
            current_port = result["port"] if result else None

            if current_port and current_port != known_port:
                # New dongle detected (or different port)
                known_port = current_port
                logger.info("GSM Dongle detected on %s", known_port)
                if callable(on_connect):
                    try:
                        on_connect(result)
                    except Exception as exc:
                        logger.error("on_connect callback raised: %s", exc)

            elif known_port and not current_port:
                # Previously detected dongle is gone
                logger.info("GSM Dongle disconnected (was on %s)", known_port)
                known_port = None
                if callable(on_disconnect):
                    try:
                        on_disconnect()
                    except Exception as exc:
                        logger.error("on_disconnect callback raised: %s", exc)

            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Dongle monitor stopped by user.")


# ── CLI quick-test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== GSM Dongle Detector ===\n")
    info = detect_dongle()
    if info:
        print(f"  Found : {info['port']}  @ {info['baud']} baud")
        print(f"  Model : {info['model'] or '(unknown)'}")
    else:
        print("  No dongle found.")

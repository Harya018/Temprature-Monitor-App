"""
backend/sms_dongle/at_commands.py
===================================
Low-level AT command interface for a GSM USB dongle.

All functions open the serial port, send a command, read back the
response, close the port, and return a clean result.  Every function
is safe — it catches all exceptions and never crashes the caller.

Standalone — zero imports from the main SentinelEdge project.
Requires: pyserial  (pip install pyserial)

AT command reference used here:
  AT          — basic ping; modem replies "OK"
  AT+CSQ      — signal quality (RSSI 0-31, 99=unknown)
  AT+CIMI     — IMSI; fails if SIM not present/locked
  AT+CPIN?    — SIM PIN status
  AT+COPS?    — registered network operator
  AT+CMGF=1   — set SMS to text mode (required before AT+CMGS)
  ATI         — device identification / model info
"""

import logging
import time
from typing import Optional

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

logger = logging.getLogger("sms_dongle.at_commands")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _open_port(port: str, baud: int = 9600, timeout: float = 3.0) -> Optional["serial.Serial"]:
    """
    Open and return a Serial connection to `port` at `baud`.
    Returns None and logs an error if the port cannot be opened.
    """
    if not SERIAL_AVAILABLE:
        logger.error("pyserial not installed. Run: pip install pyserial")
        return None
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            timeout=timeout,
            write_timeout=timeout,
        )
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        return ser
    except serial.SerialException as exc:
        logger.error("Cannot open port %s: %s", port, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error opening %s: %s", port, exc)
        return None


def _read_response(ser: "serial.Serial", wait: float = 0.8) -> str:
    """
    Read all available bytes from the serial port after waiting `wait` seconds.
    Returns the response as a decoded string (UTF-8, errors replaced).
    """
    time.sleep(wait)
    raw = ser.read(ser.in_waiting or 512)
    return raw.decode("utf-8", errors="replace").strip()


# ── Public API ─────────────────────────────────────────────────────────────────

def send_at(port: str, command: str, timeout: float = 3.0, baud: int = 9600) -> str:
    """
    Send a raw AT command to the dongle and return the full response string.

    Parameters
    ----------
    port    : str   — COM port, e.g. "COM3"
    command : str   — AT command WITHOUT trailing newline, e.g. "AT+CSQ"
    timeout : float — seconds to wait for response (default 3)
    baud    : int   — baud rate (default 9600)

    Returns
    -------
    str — raw response from the modem, or empty string on error.

    Examples
    --------
    >>> send_at("COM3", "AT")          # → "AT\\r\\n\\r\\nOK"
    >>> send_at("COM3", "AT+CSQ")      # → "AT+CSQ\\r\\n\\r\\n+CSQ: 18,0\\r\\n\\r\\nOK"
    """
    ser = _open_port(port, baud=baud, timeout=timeout)
    if ser is None:
        return ""
    try:
        cmd_bytes = (command.strip() + "\r\n").encode("utf-8")
        logger.debug(">> %s", command.strip())
        ser.write(cmd_bytes)
        response = _read_response(ser, wait=min(timeout, 1.0))
        logger.debug("<< %r", response)
        return response
    except Exception as exc:
        logger.error("send_at(%r) on %s failed: %s", command, port, exc)
        return ""
    finally:
        try:
            ser.close()
        except Exception:
            pass


def check_signal(port: str, baud: int = 9600) -> dict:
    """
    Query signal strength via AT+CSQ.

    Returns
    -------
    dict::
        {
            "ok":       True | False,
            "rssi":     int,      # 0-31  (99 = not known / not detectable)
            "ber":      int,      # bit error rate 0-7  (99 = not known)
            "percent":  int,      # approximate signal strength 0-100%
            "label":    str,      # "No Signal" / "Poor" / "Fair" / "Good" / "Excellent"
            "raw":      str,      # raw modem response
        }
    """
    response = send_at(port, "AT+CSQ", baud=baud)
    result = {
        "ok": False, "rssi": 99, "ber": 99,
        "percent": 0, "label": "Unknown", "raw": response,
    }

    if not response:
        result["label"] = "No response from modem"
        return result

    # Parse: +CSQ: <rssi>,<ber>
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("+CSQ:"):
            try:
                parts = line[5:].strip().split(",")
                rssi = int(parts[0].strip())
                ber  = int(parts[1].strip()) if len(parts) > 1 else 99
                result["rssi"] = rssi
                result["ber"]  = ber
                result["ok"]   = True

                # Convert RSSI → percentage and label
                if rssi == 99:
                    result["percent"] = 0
                    result["label"]   = "No Signal / Unknown"
                elif rssi == 0:
                    result["percent"] = 0
                    result["label"]   = "No Signal"
                elif rssi <= 9:
                    result["percent"] = int((rssi / 31) * 100)
                    result["label"]   = "Poor"
                elif rssi <= 14:
                    result["percent"] = int((rssi / 31) * 100)
                    result["label"]   = "Fair"
                elif rssi <= 19:
                    result["percent"] = int((rssi / 31) * 100)
                    result["label"]   = "Good"
                else:
                    result["percent"] = int((rssi / 31) * 100)
                    result["label"]   = "Excellent"
            except (ValueError, IndexError) as exc:
                logger.warning("Could not parse CSQ response %r: %s", line, exc)
            break

    logger.debug(
        "Signal on %s: RSSI=%d (%s, %d%%)",
        port, result["rssi"], result["label"], result["percent"],
    )
    return result


def check_sim(port: str, baud: int = 9600) -> dict:
    """
    Check SIM card status using AT+CPIN? and AT+CIMI.

    Returns
    -------
    dict::
        {
            "ok":     True | False,
            "status": "READY" | "SIM PIN" | "SIM PUK" | "NOT INSERTED" | "ERROR",
            "imsi":   str | None,   # IMSI number if SIM is ready, else None
            "raw":    str,
        }
    """
    pin_response = send_at(port, "AT+CPIN?", baud=baud)
    result = {
        "ok": False, "status": "ERROR",
        "imsi": None, "raw": pin_response,
    }

    if not pin_response:
        result["status"] = "No response from modem"
        return result

    # Parse +CPIN: <status>
    for line in pin_response.splitlines():
        line = line.strip()
        if line.startswith("+CPIN:"):
            cpin = line[6:].strip().upper()
            if cpin == "READY":
                result["ok"]     = True
                result["status"] = "READY"
            elif "SIM PIN" in cpin:
                result["status"] = "SIM PIN"
            elif "SIM PUK" in cpin:
                result["status"] = "SIM PUK"
            elif "NOT INSERTED" in cpin or "NO SIM" in cpin:
                result["status"] = "NOT INSERTED"
            else:
                result["status"] = cpin
            break

    if "ERROR" in pin_response and "+CPIN:" not in pin_response:
        result["status"] = "NOT INSERTED"

    # If SIM is ready, also fetch IMSI
    if result["ok"]:
        imsi_response = send_at(port, "AT+CIMI", baud=baud)
        for line in imsi_response.splitlines():
            line = line.strip()
            # IMSI is a 15-digit numeric string
            if line.isdigit() and 10 <= len(line) <= 20:
                result["imsi"] = line
                break

    logger.debug("SIM on %s: status=%s, IMSI=%s", port, result["status"], result["imsi"])
    return result


def check_network(port: str, baud: int = 9600) -> dict:
    """
    Query the registered network operator via AT+COPS?.

    Returns
    -------
    dict::
        {
            "ok":       True | False,
            "operator": str,   # e.g. "Airtel", "Jio", "BSNL"
            "mode":     str,   # e.g. "Automatic", "Manual"
            "format":   str,   # e.g. "Long alphanumeric"
            "raw":      str,
        }
    """
    response = send_at(port, "AT+COPS?", baud=baud)
    result = {
        "ok": False, "operator": "Unknown",
        "mode": "Unknown", "format": "Unknown", "raw": response,
    }

    if not response:
        result["operator"] = "No response from modem"
        return result

    # Parse: +COPS: <mode>,<format>,"<operator>"[,<AcT>]
    for line in response.splitlines():
        line = line.strip()
        if line.startswith("+COPS:"):
            try:
                content = line[6:].strip()
                parts = content.split(",")
                mode_map = {
                    "0": "Automatic", "1": "Manual",
                    "2": "Deregister", "3": "Set format only", "4": "Manual/Auto",
                }
                format_map = {
                    "0": "Long alphanumeric",
                    "1": "Short alphanumeric",
                    "2": "Numeric",
                }
                result["mode"]   = mode_map.get(parts[0].strip(), parts[0].strip())
                result["format"] = format_map.get(parts[1].strip(), parts[1].strip()) if len(parts) > 1 else "Unknown"
                if len(parts) > 2:
                    operator = parts[2].strip().strip('"')
                    if operator:
                        result["operator"] = operator
                        result["ok"]       = True
            except (IndexError, ValueError) as exc:
                logger.warning("Could not parse COPS response %r: %s", line, exc)
            break

    logger.debug("Network on %s: operator=%r mode=%s", port, result["operator"], result["mode"])
    return result


def set_sms_text_mode(port: str, baud: int = 9600) -> bool:
    """
    Switch the modem to SMS Text Mode by sending AT+CMGF=1.

    This MUST be called before sending an SMS via AT+CMGS.
    Returns True if the modem confirmed "OK", False otherwise.

    Parameters
    ----------
    port : str  — COM port name, e.g. "COM3"
    baud : int  — baud rate (default 9600)
    """
    response = send_at(port, "AT+CMGF=1", baud=baud)
    success = "OK" in response
    if success:
        logger.debug("SMS text mode set on %s", port)
    else:
        logger.error("Failed to set SMS text mode on %s. Response: %r", port, response)
    return success


def get_device_info(port: str, baud: int = 9600) -> dict:
    """
    Return basic modem identification via ATI.

    Returns
    -------
    dict::
        {
            "ok":           True | False,
            "manufacturer": str,
            "model":        str,
            "revision":     str,
            "imei":         str,
            "raw":          str,
        }
    """
    response = send_at(port, "ATI", baud=baud)
    result = {
        "ok": bool(response and "OK" in response),
        "manufacturer": "", "model": "", "revision": "", "imei": "",
        "raw": response,
    }

    lines = [l.strip() for l in response.splitlines() if l.strip() and l.strip() not in ("OK", "ATI")]
    if lines:
        result["manufacturer"] = lines[0] if len(lines) > 0 else ""
        result["model"]        = lines[1] if len(lines) > 1 else ""
        result["revision"]     = lines[2] if len(lines) > 2 else ""

    # IMEI via AT+GSN
    imei_resp = send_at(port, "AT+GSN", baud=baud)
    for line in imei_resp.splitlines():
        line = line.strip()
        if line.isdigit() and len(line) == 15:
            result["imei"] = line
            break

    return result

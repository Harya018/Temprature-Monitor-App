"""
modules/sms/sim7600_sender.py — Send SMS via SIM7600 EI 4G HAT over USB serial.

Mechanism:
    The SIM7600 is connected via USB and exposes a serial AT-command interface.
    This sender opens the port, runs preflight checks (SIM ready, signal), sets
    SMS text mode, and sends via AT+CMGS.  The port is opened fresh for each
    send and closed immediately afterwards — no persistent connection kept.

Requirements:
    pip install pyserial

Hardware:
    - SIM7600 EI 4G HAT connected via USB
    - Windows: appears as COM port (e.g. COM3, COM4)
      Linux:   appears as /dev/ttyUSB2 (the AT-command interface, NOT ttyUSB0)

Configuration (via .env or environment variables):
    SMS_SIM7600_PORT  — serial port to use (e.g. COM4 or /dev/ttyUSB2).
                        Leave empty to auto-detect from known VID/PID patterns.
    SMS_SIM7600_BAUD  — baud rate (default 115200 per SIM7600 spec).

Auto-detection:
    When SMS_SIM7600_PORT is empty, the module scans all COM ports for SIM76xx-
    series descriptors or the Qualcomm/SimCom USB VID.  The first match wins.
    On Windows the SIM7600 registers three serial ports; we look for the one
    whose description contains "AT" or pick the middle one (index 1).

Logging:
    Uses the same get_logger() helper and logger name convention as adb_sender.py
    (logger name: "sms.sim7600_sender") so all SMS-related logs appear under the
    same hierarchy in log files and the /api/health endpoint.
"""

from __future__ import annotations

import time
from typing import Optional

from config import MODULE_STATUS
from utils.logger import get_logger

logger = get_logger("sms.sim7600_sender")

# ── Runtime config (read lazily from config.py to avoid import-time side effects)
# Populated on first call to _get_config() below.
_port: Optional[str] = None
_baud: Optional[int] = None


def _get_config() -> tuple[str, int]:
    """
    Return (port, baud) from config, importing lazily so the module can be
    imported even if the config vars are not yet defined.
    """
    global _port, _baud
    if _port is not None and _baud is not None:
        return _port, _baud

    try:
        from config import SMS_SIM7600_PORT, SMS_SIM7600_BAUD  # type: ignore[attr-defined]
        _port = SMS_SIM7600_PORT or ""
        _baud = int(SMS_SIM7600_BAUD)
    except (ImportError, AttributeError):
        # Config vars not yet added — fall back to sensible defaults so the
        # module degrades gracefully instead of crashing at import time.
        _port = ""
        _baud = 115200

    return _port, _baud


# ── Constants ──────────────────────────────────────────────────────────────────
CTRL_Z            = chr(26)   # ASCII SUB — terminates AT+CMGS message body
AT_TIMEOUT        = 5         # seconds for a generic AT command response
SEND_TIMEOUT      = 30        # seconds to wait for +CMGS confirmation
MIN_SIGNAL_RSSI   = 2         # minimum acceptable RSSI (out of 31); 99 = no signal

# SIM7600 USB identifiers used during auto-detection
_SIM76XX_KEYWORDS = ("sim7600", "sim76", "simcom", "qualcomm hs-usb", "at command")


# ── Serial port auto-detection ─────────────────────────────────────────────────

def _detect_sim7600_port() -> Optional[str]:
    """
    Scan available serial ports for a SIM7600-like device.

    Priority:
      1. Port whose description contains an AT-command-specific keyword.
      2. Any port whose description matches a SIM76xx pattern.

    Returns the port device string (e.g. 'COM4') or None if not found.
    Never raises.
    """
    try:
        import serial.tools.list_ports  # type: ignore
    except ImportError:
        logger.warning("pyserial not installed — cannot auto-detect SIM7600 port")
        return None

    try:
        ports = list(serial.tools.list_ports.comports())
    except Exception as exc:
        logger.warning("Serial port scan failed: %s", exc)
        return None

    candidates = []
    for p in ports:
        desc = (p.description or "").lower()
        mfr  = (getattr(p, "manufacturer", None) or "").lower()
        combined = f"{desc} {mfr}"
        if any(kw in combined for kw in _SIM76XX_KEYWORDS):
            candidates.append(p)
            logger.debug("SIM7600 candidate port: %s (%s)", p.device, p.description)

    if not candidates:
        return None

    # Prefer the port whose description mentions "at" (AT-command interface)
    for p in candidates:
        if "at" in (p.description or "").lower():
            logger.debug("Selected AT-command port: %s", p.device)
            return p.device

    # Fall back to the second candidate if multiple found (SIM7600 on Windows
    # registers DM/AT/PPP ports in order; the AT port is usually index 1)
    if len(candidates) > 1:
        chosen = candidates[1].device
    else:
        chosen = candidates[0].device

    logger.debug("SIM7600 port auto-selected: %s", chosen)
    return chosen


def _resolve_port() -> Optional[str]:
    """
    Return the configured port or auto-detect one.
    Logs a warning if nothing is found.
    """
    configured_port, _ = _get_config()
    if configured_port:
        logger.debug("SIM7600 using configured port: %s", configured_port)
        return configured_port

    detected = _detect_sim7600_port()
    if detected:
        logger.info("SIM7600 port auto-detected: %s", detected)
    else:
        logger.error(
            "SIM7600 port not configured and auto-detection failed. "
            "Set SMS_SIM7600_PORT in your .env file (e.g. SMS_SIM7600_PORT=COM4)."
        )
    return detected


# ── Low-level serial helpers ───────────────────────────────────────────────────

def _send_at(ser: "serial.Serial", cmd: str, timeout: float = AT_TIMEOUT) -> str:
    """
    Send an AT command and collect the response within `timeout` seconds.

    Parameters
    ----------
    ser     : open serial.Serial instance
    cmd     : AT command string WITHOUT trailing \\r\\n (added automatically)
    timeout : seconds to wait for a complete response line

    Returns
    -------
    str — raw response text (may be empty on timeout)
    """
    ser.reset_input_buffer()
    full_cmd = (cmd + "\r\n").encode("utf-8")
    ser.write(full_cmd)
    logger.debug(">> %s", cmd)

    response = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.1)
        chunk = ser.read(ser.in_waiting or 256).decode("utf-8", errors="replace")
        if chunk:
            response += chunk
            logger.debug("<< %r", chunk)
        # Most AT responses end with OK, ERROR, or a result line
        stripped = response.strip()
        if stripped.endswith("OK") or "ERROR" in stripped or "+CPIN:" in stripped:
            break

    return response


def _wait_for_prompt(ser: "serial.Serial", timeout: float = 5.0) -> bool:
    """
    Wait for the '>' prompt that the modem sends after AT+CMGS="number".
    Returns True if '>' arrived within timeout, False otherwise.
    """
    collected = ""
    deadline  = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.1)
        chunk = ser.read(ser.in_waiting or 32).decode("utf-8", errors="replace")
        collected += chunk
        if ">" in collected:
            return True
    return False


def _wait_for_cmgs(ser: "serial.Serial", timeout: float = SEND_TIMEOUT) -> tuple[bool, str]:
    """
    Poll the port for up to `timeout` seconds waiting for '+CMGS:' (success)
    or 'ERROR' (failure).

    Returns
    -------
    (success: bool, full_response: str)
    """
    collected = ""
    deadline  = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.3)
        chunk = ser.read(ser.in_waiting or 256).decode("utf-8", errors="replace")
        if chunk:
            collected += chunk
            logger.debug("<< %r", chunk)
        if "+CMGS:" in collected:
            return True, collected
        if "ERROR" in collected.upper():
            return False, collected
    return False, collected  # timed out


# ── Phone number normalisation ─────────────────────────────────────────────────

def _format_phone(phone_number: str) -> str:
    """
    Normalise a phone number for use in AT+CMGS.

    Rules:
    - Already starts with '+'  → use as-is (international format)
    - 10-digit Indian number   → prepend +91
    - Anything else            → use as-is (caller's responsibility)

    Examples:
        "6385936224"    → "+916385936224"
        "+919876543210" → "+919876543210"
        "009876543210"  → "009876543210"
    """
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    if len(phone) == 10 and phone.isdigit():
        return f"+91{phone}"
    return phone


# ── Preflight checks ───────────────────────────────────────────────────────────

def _check_at(ser: "serial.Serial") -> bool:
    """Send plain AT and verify the modem responds with OK."""
    resp = _send_at(ser, "AT")
    ok   = "OK" in resp
    if not ok:
        logger.error("SIM7600: no AT response — check port and cable. Got: %r", resp)
    return ok


def _check_sim(ser: "serial.Serial") -> bool:
    """
    Query SIM status via AT+CPIN?.
    Returns True if SIM is READY, False for any other state (PIN required, absent…).
    """
    resp   = _send_at(ser, "AT+CPIN?")
    ready  = "+CPIN: READY" in resp
    if not ready:
        status = "unknown"
        for line in resp.splitlines():
            if "+CPIN:" in line:
                status = line.strip()
                break
        logger.error(
            "SIM7600: SIM not ready — status: %s. "
            "Check SIM is inserted and not PIN-locked.",
            status,
        )
    return ready


def _check_signal(ser: "serial.Serial") -> Optional[int]:
    """
    Query signal strength via AT+CSQ.
    Returns the RSSI integer (0-31, 99=no signal), or None on parse error.
    Logs a warning if signal is too weak.
    """
    resp = _send_at(ser, "AT+CSQ")
    for line in resp.splitlines():
        if "+CSQ:" in line:
            try:
                # "+CSQ: 18,0"  →  rssi=18
                rssi_str = line.split(":")[1].split(",")[0].strip()
                rssi     = int(rssi_str)
                logger.info("SIM7600: signal RSSI=%d/31", rssi)
                if rssi == 99:
                    logger.warning(
                        "SIM7600: no signal (RSSI=99). "
                        "Move antenna to a better location."
                    )
                elif rssi < MIN_SIGNAL_RSSI:
                    logger.warning(
                        "SIM7600: very weak signal (RSSI=%d). SMS may fail.", rssi
                    )
                return rssi
            except (IndexError, ValueError) as exc:
                logger.warning("SIM7600: could not parse AT+CSQ response: %r (%s)", resp, exc)
                return None
    logger.warning("SIM7600: no +CSQ line in response: %r", resp)
    return None


def _set_text_mode(ser: "serial.Serial") -> bool:
    """
    Set SMS text mode with AT+CMGF=1.
    Returns True if the modem acknowledges with OK.
    """
    resp = _send_at(ser, "AT+CMGF=1")
    ok   = "OK" in resp
    if not ok:
        logger.error(
            "SIM7600: failed to set SMS text mode (AT+CMGF=1). "
            "Response: %r", resp
        )
    return ok


# ── Public API ─────────────────────────────────────────────────────────────────

def send_sms(phone: str, message: str) -> bool:
    """
    Send an SMS via the SIM7600 EI 4G HAT over USB serial.

    Opens a fresh serial connection, runs preflight AT checks, sends the
    message, waits for +CMGS confirmation, then closes the port.

    Parameters
    ----------
    phone   : str — destination phone number (10-digit Indian or +E.164 format)
    message : str — plain-text SMS body; keep under 160 chars for single SMS

    Returns
    -------
    bool — True if the modem confirmed the send (+CMGS received), False otherwise.
           Never raises — all errors are caught, logged, and return False.
    """
    # ── Step 0: ensure pyserial is available ──────────────────────────────────
    try:
        import serial  # type: ignore
    except ImportError:
        logger.error(
            "pyserial not installed. Run: pip install pyserial  then restart the server."
        )
        MODULE_STATUS["sms"] = "error: pyserial not installed"
        return False

    # ── Step 1: resolve serial port ───────────────────────────────────────────
    port = _resolve_port()
    if not port:
        MODULE_STATUS["sms"] = "error: sim7600 port not found"
        return False

    _, baud = _get_config()
    formatted_phone = _format_phone(phone)

    logger.info(
        "Sending SMS via SIM7600 to %s (%d chars) on %s @ %d baud",
        formatted_phone, len(message), port, baud,
    )

    ser: Optional["serial.Serial"] = None
    try:
        # ── Step 2: open serial port ──────────────────────────────────────────
        ser = serial.Serial(
            port         = port,
            baudrate     = baud,
            timeout      = AT_TIMEOUT,
            write_timeout= AT_TIMEOUT,
        )
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # ── Step 3: AT — basic modem check ───────────────────────────────────
        if not _check_at(ser):
            MODULE_STATUS["sms"] = "error: sim7600 no AT response"
            return False

        # ── Step 4: AT+CPIN? — SIM status ────────────────────────────────────
        if not _check_sim(ser):
            MODULE_STATUS["sms"] = "error: sim7600 SIM not ready"
            return False

        # ── Step 5: AT+CSQ — signal check (non-blocking; warn only) ──────────
        rssi = _check_signal(ser)
        if rssi is not None and rssi == 99:
            # 99 = "not known or not detectable" — hard failure
            logger.error(
                "SIM7600: aborting SMS send — no signal at all (RSSI=99)."
            )
            MODULE_STATUS["sms"] = "error: sim7600 no signal"
            return False

        # ── Step 6: AT+CMGF=1 — text mode ────────────────────────────────────
        if not _set_text_mode(ser):
            MODULE_STATUS["sms"] = "error: sim7600 text mode failed"
            return False

        # ── Step 7: AT+CMGS="<number>" ───────────────────────────────────────
        cmgs_cmd = f'AT+CMGS="{formatted_phone}"'
        ser.write((cmgs_cmd + "\r\n").encode("utf-8"))
        logger.debug(">> %s", cmgs_cmd)

        if not _wait_for_prompt(ser, timeout=5.0):
            # Cancel the pending command
            ser.write(bytes([27]))   # ESC
            logger.error(
                "SIM7600: modem did not send '>' prompt after AT+CMGS — "
                "cancelled send to %s", formatted_phone
            )
            MODULE_STATUS["sms"] = "error: sim7600 no prompt"
            return False

        # ── Step 8: send message body + Ctrl-Z ───────────────────────────────
        body = (message + CTRL_Z).encode("utf-8")
        logger.debug(">> (message body + Ctrl-Z, %d bytes)", len(body))
        ser.write(body)

        # ── Step 9: wait for +CMGS confirmation ──────────────────────────────
        success, response = _wait_for_cmgs(ser, timeout=SEND_TIMEOUT)

        if success:
            logger.info("SMS sent via SIM7600 to %s", formatted_phone)
            MODULE_STATUS["sms"] = "ok -- sim7600"
            return True

        # ── Failure: extract reason from modem response ───────────────────────
        reason = "timeout — no +CMGS confirmation"
        for line in response.splitlines():
            if "ERROR" in line.upper():
                reason = f"modem error: {line.strip()}"
                break
        logger.error(
            "SIM7600: SMS failed to %s — %s (raw: %r)",
            formatted_phone, reason, response[:120],
        )
        MODULE_STATUS["sms"] = f"error: sim7600 {reason[:50]}"
        return False

    except serial.SerialException as exc:
        logger.error(
            "SIM7600: serial port error on %s — %s. "
            "Check the USB cable and that no other process has the port open.",
            port, exc,
        )
        MODULE_STATUS["sms"] = "error: sim7600 serial exception"
        return False

    except TimeoutError:
        logger.error(
            "SIM7600: serial timeout sending to %s on %s", formatted_phone, port
        )
        MODULE_STATUS["sms"] = "error: sim7600 timeout"
        return False

    except Exception as exc:
        logger.error("SIM7600: unexpected error sending to %s — %s", formatted_phone, exc)
        MODULE_STATUS["sms"] = f"error: sim7600 {str(exc)[:50]}"
        return False

    finally:
        # ── Step 10: always close the port ────────────────────────────────────
        if ser is not None and ser.is_open:
            try:
                ser.close()
                logger.debug("SIM7600: serial port %s closed", port)
            except Exception:
                pass  # Never let cleanup raise

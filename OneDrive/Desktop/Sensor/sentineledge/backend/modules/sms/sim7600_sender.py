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

Auto-detection (3-tier):
    When SMS_SIM7600_PORT is empty, the module scans all COM ports:
      Tier 1 — Among SIM76xx candidates, prefer the port whose description
               explicitly contains "AT" or "AT Command" (exact keyword).
      Tier 2 — For remaining candidates with no "AT" in the description,
               live-probe each one by opening the port and sending "AT\\r\\n"
               — only use a port that replies with "OK" within 1 second.
      Tier 3 — If no probe succeeds, fall back to the middle candidate
               (index 1) as before.
    The confirmed working port is cached for the entire server session so
    subsequent SMS sends skip the scan entirely.

Logging:
    Uses the same get_logger() helper and logger name convention as adb_sender.py
    (logger name: "sms.sim7600_sender") so all SMS-related logs appear under the
    same hierarchy in log files and the /api/health endpoint.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import serial  # only for IDE type resolution — runtime import stays lazy

from config import MODULE_STATUS
from utils.logger import get_logger

logger = get_logger("sms.sim7600_sender")

# ── Runtime config (read lazily from config.py to avoid import-time side effects)
# Populated on first call to _get_config() below.
_port: Optional[str] = None
_baud: Optional[int] = None

# ── Session cache for the confirmed AT-command port ───────────────────────────
# Set on first successful detection; avoids re-scanning on every SMS send.
_confirmed_port: Optional[str] = None

# ── Send-in-progress flag ─────────────────────────────────────────────────────
# Set True while the serial port is held open for a send.  The health.py
# background probe checks this flag and skips that probe cycle to avoid
# two threads fighting over the same COM port.
_gsm_send_in_progress: bool = False


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

    # Warn operators who have hardcoded the port — this defeats auto-detection.
    if _port:
        logger.warning(
            "SMS_SIM7600_PORT is hardcoded to '%s' — auto-detect disabled. "
            "Clear this value in .env for fully automatic port detection.",
            _port,
        )

    return _port, _baud


# ── Constants ──────────────────────────────────────────────────────────────────
CTRL_Z            = chr(26)   # ASCII SUB — terminates AT+CMGS message body
AT_TIMEOUT        = 5         # seconds for a generic AT command response
SEND_TIMEOUT      = 30        # seconds for the overall send attempt (legacy, kept for reference)
CMGS_TIMEOUT      = 15        # seconds to wait specifically for +CMGS confirmation
_CMGS_RETRIES     = 1         # number of retries after first +CMGS timeout/failure
MIN_SIGNAL_RSSI   = 2         # minimum acceptable RSSI (out of 31); 99 = no signal

# SIM7600 USB identifiers used during auto-detection
_SIM76XX_KEYWORDS = ("sim7600", "sim76", "simcom", "qualcomm hs-usb", "at command")


# ── Serial port auto-detection ─────────────────────────────────────────────────

# Words that, when found in a port description, strongly suggest the AT-command
# interface port (not the DM/diagnostic or PPP data port).
_AT_DESC_KEYWORDS = ("at command", "at port", "at interface", "enhanced at")


def _probe_port(device: str, baud: int, timeout: float = 1.0) -> bool:
    """
    Open *device* briefly, send 'AT\\r\\n', and return True if the modem
    responds with 'OK' within *timeout* seconds.

    Used during auto-detection to distinguish the AT-command port from the
    DM/diagnostic and PPP ports that the SIM7600 also registers on Windows.
    Never raises — returns False on any error.
    """
    try:
        import serial  # type: ignore
    except ImportError:
        return False

    ser = None
    try:
        ser = serial.Serial(
            port=device, baudrate=baud,
            timeout=timeout, write_timeout=timeout,
        )
        ser.reset_input_buffer()
        ser.write(b"AT\r\n")
        deadline = time.monotonic() + timeout
        response = ""
        while time.monotonic() < deadline:
            time.sleep(0.05)
            chunk = ser.read(ser.in_waiting or 32).decode("utf-8", errors="replace")
            if chunk:
                response += chunk
            if "OK" in response:
                logger.debug("Port probe OK: %s responded to AT", device)
                return True
        logger.debug("Port probe FAIL: %s did not respond to AT (got %r)", device, response[:40])
        return False
    except Exception as exc:
        logger.debug("Port probe error on %s: %s", device, exc)
        return False
    finally:
        if ser is not None and ser.is_open:
            try:
                ser.close()
            except Exception:
                pass


def _detect_sim7600_port() -> Optional[str]:
    """
    Scan available serial ports for the SIM7600 AT-command interface.

    Detection runs in three tiers:

    Tier 1 — Description keyword match
        Among all ports matching SIM76xx vendor patterns, prefer the one
        whose description explicitly contains an AT-command keyword
        (e.g. "AT Command", "AT Port", "Enhanced AT").  This is the most
        reliable signal on Windows where SimCom drivers label each sub-port.

    Tier 2 — Live AT probe
        For candidates whose description doesn’t contain an AT keyword,
        actually open each port and send 'AT\\r\\n'.  The first port that
        replies with 'OK' within 1 second wins.  This catches modems
        whose Windows driver uses a generic description that doesn’t
        include the word 'AT'.

    Tier 3 — Positional fallback
        If no probe succeeds (e.g. modem is sleeping or busy), fall back
        to the middle candidate (index 1), which is the AT port on most
        SIM7600 Windows driver installs.

    Returns the port device string (e.g. 'COM11') or None if no SIM7600-
    like device was found at all. Never raises.
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

    # ── Collect SIM76xx candidate ports ─────────────────────────────────────────
    candidates = []
    for p in ports:
        desc = (p.description or "").lower()
        mfr  = (getattr(p, "manufacturer", None) or "").lower()
        combined = f"{desc} {mfr}"
        if any(kw in combined for kw in _SIM76XX_KEYWORDS):
            candidates.append(p)
            logger.debug("SIM7600 candidate port: %s (%s)", p.device, p.description)

    if not candidates:
        # ── Tier 0: brute-force AT probe on all ports ─────────────────────────
        # Driver may use generic description (e.g. "USB Serial Device") with no
        # SimCom keywords — probe every non-sensor port and accept the first one
        # that responds to "AT" with "OK".
        _, baud = _get_config()
        probe_baud = baud if baud else 115200
        _SENSOR_KW = ("ch340", "cp210", "ft232", "arduino", "ftdi", "prolific",
                      "silicon labs", "audio", "microphone", "headset")
        for p in sorted(ports, key=lambda p: p.device):
            desc = (p.description or "").lower()
            if any(kw in desc for kw in _SENSOR_KW):
                continue  # skip known sensor/audio chips
            logger.debug("Brute-force AT probe on %s (%s)", p.device, p.description)
            if _probe_port(p.device, probe_baud, timeout=1.5):
                logger.info(
                    "SIM7600 found by brute-force AT probe: %s (%s) — "
                    "driver has no SimCom keywords",
                    p.device, p.description,
                )
                return p.device
        return None

    # ── Tier 1: explicit AT keyword in description ──────────────────────────────
    for p in candidates:
        desc_lower = (p.description or "").lower()
        if any(kw in desc_lower for kw in _AT_DESC_KEYWORDS):
            logger.info(
                "SIM7600 AT port selected by description: %s (%s)",
                p.device, p.description,
            )
            return p.device

    # ── Tier 2: live AT probe for remaining candidates ──────────────────────────
    # Candidates without an AT keyword in their description need to be probed.
    # Sort by device name so probing is deterministic (COM9 before COM11 etc).
    _, baud = _get_config()
    probe_baud = baud if baud else 115200

    non_at_candidates = [
        p for p in candidates
        if not any(kw in (p.description or "").lower() for kw in _AT_DESC_KEYWORDS)
    ]
    non_at_candidates.sort(key=lambda p: p.device)

    for p in non_at_candidates:
        logger.debug("Probing candidate port %s (%s) with AT command...", p.device, p.description)
        if _probe_port(p.device, probe_baud):
            logger.info(
                "SIM7600 AT port confirmed by live probe: %s (%s)",
                p.device, p.description,
            )
            return p.device

    # ── Tier 3: positional fallback ───────────────────────────────────────────────
    # No probe succeeded (modem may be sleeping). Use index 1 as the historic
    # best-guess: SIM7600 Windows drivers typically register ports in DM/AT/PPP
    # order, putting the AT port in the middle.
    fallback = candidates[1] if len(candidates) > 1 else candidates[0]
    logger.warning(
        "SIM7600: AT probe failed for all candidates — "
        "falling back to positional guess: %s (%s). "
        "If wrong, set SMS_SIM7600_PORT in .env explicitly.",
        fallback.device, fallback.description,
    )
    return fallback.device


def _resolve_port() -> Optional[str]:
    """
    Return the port to use for this SMS send, in priority order:

      1. SMS_SIM7600_PORT env var (explicit, always trusted).
      2. _confirmed_port session cache — validated with a live AT probe.
         If the cached port no longer responds, cache is cleared and
         a fresh scan runs (handles USB port changes and reconnects).
      3. Fresh auto-detection via _detect_sim7600_port().

    Works across USB port changes and different laptops — no hardcoded
    COM port numbers needed.
    """
    global _confirmed_port

    # Priority 1: explicit config (always trusted, no probe needed)
    configured_port, baud = _get_config()
    if configured_port:
        logger.debug("SIM7600 using configured port: %s", configured_port)
        return configured_port

    probe_baud = baud if baud else 115200

    # Priority 2: session cache — validate it's still alive before trusting it
    if _confirmed_port is not None:
        if _probe_port(_confirmed_port, probe_baud, timeout=1.0):
            logger.debug("SIM7600 cached port %s still alive", _confirmed_port)
            return _confirmed_port
        logger.info(
            "SIM7600 cached port %s no longer responding — "
            "device may have moved to a different USB port. Re-scanning...",
            _confirmed_port,
        )
        _confirmed_port = None

    # Priority 3: fresh detection (scans all COM ports)
    detected = _detect_sim7600_port()
    if detected:
        _confirmed_port = detected
        logger.info("SIM7600 port detected and cached: %s", detected)
    else:
        logger.error(
            "SIM7600 port not configured and auto-detection failed. "
            "Set SMS_SIM7600_PORT in your .env file (e.g. SMS_SIM7600_PORT=COM11)."
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

    Rules (applied in order):
    - Already starts with '+'  → use as-is (full international format)
    - 12-digit number starting with '91' (no '+') → prepend '+' only
      (avoids doubling +91 if the number was stored with the country code)
    - 10-digit Indian number   → prepend +91
    - Anything else            → use as-is (caller's responsibility)

    Examples:
        "9876543210"    → "+919876543210"
        "+919876543210" → "+919876543210"  (unchanged)
        "919876543210"  → "+919876543210"  (bare 91 prefix, not doubled)
        "009876543210"  → "009876543210"   (non-Indian; left as-is)
    """
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    # 12-digit number starting with "91" — already has country code, just add +
    if len(phone) == 12 and phone.startswith("91") and phone.isdigit():
        return f"+{phone}"
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
    message, waits for +CMGS confirmation (up to CMGS_TIMEOUT seconds), then
    closes the port.  Retries once on timeout/failure before giving up.

    Parameters
    ----------
    phone   : str — destination phone number (10-digit Indian or +E.164 format)
    message : str — plain-text SMS body; keep under 160 chars for single SMS

    Returns
    -------
    bool — True if the modem confirmed the send (+CMGS received), False otherwise.
           Never raises — all errors are caught, logged, and return False.
    """
    global _gsm_send_in_progress
    global _confirmed_port

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

    # ── Attempt loop: try once, retry once on failure ─────────────────────────
    for attempt in range(1, _CMGS_RETRIES + 2):   # +2 → attempts 1 and 2
        ser: Optional["serial.Serial"] = None
        try:
            if attempt > 1:
                logger.info(
                    "SIM7600: retry attempt %d/%d for %s",
                    attempt, _CMGS_RETRIES + 1, formatted_phone,
                )
                time.sleep(2)  # brief pause before retry lets modem settle

            _gsm_send_in_progress = True

            # ── Step 2: open serial port ──────────────────────────────────────
            ser = serial.Serial(
                port         = port,
                baudrate     = baud,
                timeout      = AT_TIMEOUT,
                write_timeout= AT_TIMEOUT,
            )
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # ── Step 3: AT — basic modem check ───────────────────────────────
            if not _check_at(ser):
                MODULE_STATUS["sms"] = "error: sim7600 no AT response"
                return False

            # ── Step 4: AT+CPIN? — SIM status ────────────────────────────────
            if not _check_sim(ser):
                MODULE_STATUS["sms"] = "error: sim7600 SIM not ready"
                return False

            # ── Step 5: AT+CSQ — signal check (non-blocking; warn only) ──────
            rssi = _check_signal(ser)
            if rssi is not None and rssi == 99:
                # 99 = "not known or not detectable" — hard failure
                logger.error(
                    "SIM7600: aborting SMS send — no signal at all (RSSI=99)."
                )
                MODULE_STATUS["sms"] = "error: sim7600 no signal"
                return False

            # ── Step 6: AT+CMGF=1 — text mode ────────────────────────────────
            if not _set_text_mode(ser):
                MODULE_STATUS["sms"] = "error: sim7600 text mode failed"
                return False

            # ── Step 7: AT+CMGS="<number>" ────────────────────────────────────
            cmgs_cmd = f'AT+CMGS="{formatted_phone}"'
            ser.write((cmgs_cmd + "\r\n").encode("utf-8"))
            logger.debug(">> %s", cmgs_cmd)

            if not _wait_for_prompt(ser, timeout=5.0):
                # Cancel the pending command
                ser.write(bytes([27]))   # ESC
                logger.error(
                    "SIM7600: modem did not send '>' prompt after AT+CMGS "
                    "(attempt %d) — cancelled send to %s",
                    attempt, formatted_phone,
                )
                MODULE_STATUS["sms"] = "error: sim7600 no prompt"
                # Prompt failure is likely transient — allow retry
                continue

            # ── Step 8: send message body + Ctrl-Z ───────────────────────────
            body = (message + CTRL_Z).encode("utf-8")
            logger.debug(">> (message body + Ctrl-Z, %d bytes)", len(body))
            ser.write(body)

            # ── Step 9: wait for +CMGS confirmation (CMGS_TIMEOUT seconds) ───
            success, raw_response = _wait_for_cmgs(ser, timeout=CMGS_TIMEOUT)

            if success:
                logger.info(
                    "SMS sent via SIM7600 to %s (attempt %d)",
                    formatted_phone, attempt,
                )
                MODULE_STATUS["sms"] = "ok -- sim7600"

                # ── Inbox cleanup: delete all read messages from SIM storage ─
                # Prevents SIM storage (SM) filling up which blocks future sends.
                try:
                    _send_at(ser, "AT+CMGD=1,4")   # delete all messages (read+unread)
                    logger.debug("SIM storage cleaned — inbox cleared after send")
                except Exception as _cleanup_exc:
                    logger.debug("SIM inbox cleanup skipped: %s", _cleanup_exc)

                return True

            # ── Failure: log full raw response then decide whether to retry ───
            reason = "timeout — no +CMGS confirmation"
            for line in raw_response.splitlines():
                if "ERROR" in line.upper():
                    reason = f"modem error: {line.strip()}"
                    break

            logger.error(
                "SIM7600: SMS to %s failed (attempt %d/%d) — %s | "
                "raw serial response: %r",
                formatted_phone, attempt, _CMGS_RETRIES + 1,
                reason, raw_response[:200],
            )

            if attempt <= _CMGS_RETRIES:
                # Will retry — continue loop
                continue

            # All attempts exhausted
            MODULE_STATUS["sms"] = f"error: sim7600 {reason[:50]}"
            return False

        except serial.SerialException as exc:
            logger.error(
                "SIM7600: serial port error on %s (attempt %d) — %s. "
                "Invalidating port cache and re-detecting before retry.",
                port, attempt, exc,
            )
            MODULE_STATUS["sms"] = "error: sim7600 serial exception"
            # Invalidate session cache so _resolve_port() re-scans on next call
            _confirmed_port = None
            if attempt <= _CMGS_RETRIES:
                # Re-detect and update port for the retry
                new_port = _resolve_port()
                if new_port and new_port != port:
                    logger.info(
                        "SIM7600 port changed — re-detected on %s, retrying SMS",
                        new_port,
                    )
                    port = new_port
                    continue
                elif not new_port:
                    logger.error("SIM7600: re-detection found no port — aborting")
                    return False
                # Same port — continue with retry
                continue
            return False

        except TimeoutError:
            logger.error(
                "SIM7600: serial timeout sending to %s on %s (attempt %d)",
                formatted_phone, port, attempt,
            )
            MODULE_STATUS["sms"] = "error: sim7600 timeout"
            # Timeout is transient — retry if attempts remain
            if attempt > _CMGS_RETRIES:
                return False
            continue

        except Exception as exc:
            logger.error(
                "SIM7600: unexpected error sending to %s (attempt %d) — %s",
                formatted_phone, attempt, exc,
            )
            MODULE_STATUS["sms"] = f"error: sim7600 {str(exc)[:50]}"
            return False

        finally:
            # ── Step 10: always close the port and clear in-progress flag ─────
            if ser is not None and ser.is_open:
                try:
                    ser.close()
                    logger.debug("SIM7600: serial port %s closed", port)
                except Exception:
                    pass  # Never let cleanup raise
            _gsm_send_in_progress = False

    # Should never reach here, but satisfy the type checker
    return False

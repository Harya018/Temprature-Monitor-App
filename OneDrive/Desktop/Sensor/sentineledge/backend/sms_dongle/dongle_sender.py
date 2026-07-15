"""
backend/sms_dongle/dongle_sender.py
=====================================
Sends SMS via a USB GSM dongle using raw AT commands.

Flow for every send:
  1. Auto-detect dongle port  (dongle_detector.detect_dongle)
  2. Verify SIM is ready      (AT+CPIN?)
  3. Verify signal > 0        (AT+CSQ)
  4. Set SMS text mode        (AT+CMGF=1)
  5. Open port — keep it open for the full send sequence
  6. Send AT+CMGS="+91<number>"  (or the number as-is if it starts with +)
  7. Send <message><Ctrl+Z>
  8. Wait up to SEND_TIMEOUT seconds for "+CMGS:" confirmation
  9. Log result and return structured dict

Standalone — zero imports from the main SentinelEdge project.
Requires: pyserial  (pip install pyserial)
"""

import logging
import time
from typing import Optional

try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

from dongle_detector import detect_dongle
from at_commands    import check_signal, check_sim, set_sms_text_mode

logger = logging.getLogger("sms_dongle.sender")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Constants ──────────────────────────────────────────────────────────────────
SEND_TIMEOUT   = 15    # seconds to wait for +CMGS confirmation
READ_CHUNK     = 0.5   # seconds between each poll while waiting
MIN_SIGNAL     = 2     # minimum RSSI required to attempt a send (out of 31)
CTRL_Z         = chr(26)   # ASCII SUB — terminates AT+CMGS body


# ── Internal helpers ───────────────────────────────────────────────────────────

def _format_phone(phone_number: str) -> str:
    """
    Normalise a phone number for AT+CMGS.

    Rules:
    - Already starts with '+' → use as-is
    - 10-digit Indian number  → prepend +91
    - Anything else           → use as-is (caller's responsibility)

    Examples:
        "6385936224"     → "+916385936224"
        "+919876543210"  → "+919876543210"
        "009876543210"   → "009876543210"
    """
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        return phone
    if len(phone) == 10 and phone.isdigit():
        return f"+91{phone}"
    return phone


def _wait_for_cmgs(ser: "serial.Serial", timeout: float = SEND_TIMEOUT) -> tuple[bool, str]:
    """
    Poll the open serial port for up to `timeout` seconds waiting for either:
      "+CMGS:"  → success
      "ERROR"   → failure
      "CMS ERROR" → failure

    Returns (success: bool, full_response: str).
    """
    collected = ""
    deadline  = time.monotonic() + timeout

    while time.monotonic() < deadline:
        time.sleep(READ_CHUNK)
        chunk = ser.read(ser.in_waiting or 256).decode("utf-8", errors="replace")
        if chunk:
            collected += chunk
            logger.debug("Modem response chunk: %r", chunk)

        if "+CMGS:" in collected:
            return True, collected
        if "ERROR" in collected.upper():
            return False, collected

    return False, collected  # timeout


# ── Public API ─────────────────────────────────────────────────────────────────

def send_sms_via_dongle(
    phone_number: str,
    message: str,
    baud: Optional[int] = None,
) -> dict:
    """
    Send an SMS to `phone_number` via a USB GSM dongle.

    Parameters
    ----------
    phone_number : str
        Destination number. 10-digit Indian numbers get +91 prepended automatically.
        International numbers must start with '+'.
    message      : str
        SMS body text. Must be ≤ 160 characters for a single SMS.
        Longer messages will be sent as-is (modem may split them).
    baud         : int | None
        Baud rate override. If None, uses the rate detected by dongle_detector.

    Returns
    -------
    dict::
        {
            "success":   True | False,
            "message":   str,          # human-readable result
            "phone":     str,          # formatted number used
            "port":      str | None,   # COM port used, or None
            "baud":      int | None,
        }

    Logs (INFO level):
        "Sending SMS to +916385936224 via COM3..."
        "SMS sent successfully to +916385936224 via COM3"
        "SMS failed to +916385936224: <reason>"
    """
    if not SERIAL_AVAILABLE:
        msg = "pyserial not installed. Run: pip install pyserial"
        logger.error(msg)
        return _fail(phone_number, None, None, msg)

    formatted_phone = _format_phone(phone_number)

    # ── Step 1: Detect dongle ─────────────────────────────────────────────────
    dongle = detect_dongle()
    if dongle is None:
        reason = (
            "GSM dongle not found. Plug in the dongle and ensure it is in MODEM mode "
            "(not storage/CD-ROM mode). See README.md."
        )
        logger.error("SMS failed to %s: %s", formatted_phone, reason)
        return _fail(formatted_phone, None, None, reason)

    port      = dongle["port"]
    use_baud  = baud or dongle["baud"]

    logger.info("Sending SMS to %s via %s (baud=%d)...", formatted_phone, port, use_baud)

    # ── Step 2: Check SIM ────────────────────────────────────────────────────
    sim = check_sim(port, baud=use_baud)
    if not sim["ok"]:
        reason = f"SIM not ready — status: {sim['status']}. Check SIM is inserted and not PIN-locked."
        logger.error("SMS failed to %s: %s", formatted_phone, reason)
        return _fail(formatted_phone, port, use_baud, reason)

    # ── Step 3: Check signal ─────────────────────────────────────────────────
    signal = check_signal(port, baud=use_baud)
    if signal["rssi"] == 99 or signal["rssi"] < MIN_SIGNAL:
        reason = (
            f"No signal or signal too weak (RSSI={signal['rssi']}, {signal['label']}). "
            "Move dongle to better location or check antenna."
        )
        logger.error("SMS failed to %s: %s", formatted_phone, reason)
        return _fail(formatted_phone, port, use_baud, reason)

    logger.info(
        "Pre-flight OK: SIM=%s, Signal=%d/31 (%s)",
        sim["status"], signal["rssi"], signal["label"],
    )

    # ── Step 4–8: Open port and send ─────────────────────────────────────────
    try:
        with serial.Serial(
            port=port, baudrate=use_baud,
            timeout=SEND_TIMEOUT, write_timeout=SEND_TIMEOUT,
        ) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            # Step 4: Set text mode (AT+CMGF=1)
            ser.write(b"AT+CMGF=1\r\n")
            time.sleep(0.8)
            r = ser.read(ser.in_waiting or 64).decode("utf-8", errors="replace")
            if "OK" not in r:
                reason = f"Failed to set SMS text mode. Response: {r!r}"
                logger.error("SMS failed to %s: %s", formatted_phone, reason)
                return _fail(formatted_phone, port, use_baud, reason)

            # Step 5: AT+CMGS="<number>"
            cmgs_cmd = f'AT+CMGS="{formatted_phone}"\r\n'
            logger.debug(">> %s", cmgs_cmd.strip())
            ser.write(cmgs_cmd.encode("utf-8"))

            # Wait for the '>' prompt from modem
            prompt_collected = ""
            prompt_deadline  = time.monotonic() + 5
            while time.monotonic() < prompt_deadline:
                time.sleep(0.2)
                chunk = ser.read(ser.in_waiting or 32).decode("utf-8", errors="replace")
                prompt_collected += chunk
                if ">" in prompt_collected:
                    break
            else:
                if ">" not in prompt_collected:
                    reason = f"Modem did not send '>' prompt after AT+CMGS. Got: {prompt_collected!r}"
                    logger.error("SMS failed to %s: %s", formatted_phone, reason)
                    ser.write(bytes([27]))  # ESC to cancel
                    return _fail(formatted_phone, port, use_baud, reason)

            # Step 6: Send message body + Ctrl+Z
            body = (message + CTRL_Z).encode("utf-8")
            logger.debug(">> (message body + Ctrl+Z, %d bytes)", len(body))
            ser.write(body)

            # Step 7: Wait for +CMGS: confirmation
            success, response = _wait_for_cmgs(ser, timeout=SEND_TIMEOUT)

        # ── Result ────────────────────────────────────────────────────────────
        if success:
            logger.info("SMS sent successfully to %s via %s", formatted_phone, port)
            return {
                "success": True,
                "message": f"SMS sent successfully to {formatted_phone} via {port}",
                "phone":   formatted_phone,
                "port":    port,
                "baud":    use_baud,
            }
        else:
            # Extract error detail from response
            reason = "Modem did not confirm send"
            for line in response.splitlines():
                if "ERROR" in line.upper() or "+CMS ERROR" in line:
                    reason = f"Modem error: {line.strip()}"
                    break
            if not response.strip():
                reason = f"Timeout — no response from modem after {SEND_TIMEOUT}s"

            logger.error("SMS failed to %s: %s", formatted_phone, reason)
            return _fail(formatted_phone, port, use_baud, reason)

    except serial.SerialException as exc:
        reason = f"Serial port error on {port}: {exc}"
        logger.error("SMS failed to %s: %s", formatted_phone, reason)
        return _fail(formatted_phone, port, use_baud, reason)
    except Exception as exc:
        reason = f"Unexpected error: {exc}"
        logger.error("SMS failed to %s: %s", formatted_phone, reason)
        return _fail(formatted_phone, port, use_baud, reason)


# ── Private factory ────────────────────────────────────────────────────────────

def _fail(phone: str, port: Optional[str], baud: Optional[int], reason: str) -> dict:
    """Return a standardised failure dict."""
    return {
        "success": False,
        "message": reason,
        "phone":   phone,
        "port":    port,
        "baud":    baud,
    }


# ── CLI quick-send ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python dongle_sender.py <phone_number> <message>")
        print('Example: python dongle_sender.py 6385936224 "Hello from SentinelEdge"')
        sys.exit(1)

    phone   = sys.argv[1]
    message = " ".join(sys.argv[2:])
    result  = send_sms_via_dongle(phone, message)
    print()
    print("Result:", "✓ SUCCESS" if result["success"] else "✗ FAILED")
    print("Detail:", result["message"])
    if result["port"]:
        print("Port  :", result["port"])

# SentinelEdge — GSM Dongle SMS Module

Standalone production SMS module that sends alerts through a USB GSM
dongle using raw AT commands.  No cloud service, no app, no Android phone
required — just a SIM card in a USB stick.

---

## Supported Dongles

Any dongle that supports standard AT commands:

| Manufacturer | Models |
|---|---|
| **Huawei** | E3372, E3531, E173, E1750, E3131 |
| **ZTE** | MF190, MF667, MF636, MF180 |
| **Sierra Wireless** | AirCard series |
| **Any generic** | USB AT-command modem |

Default baud rate: **9600** (auto-fallback to **115200**).

---

## Installation

### 1. Install Python dependency

```bash
pip install pyserial
```

That is the only external dependency.

---

## Finding the Dongle's COM Port on Windows

1. Plug in the dongle via USB
2. Open **Device Manager** (`Win+X` → Device Manager)
3. Expand **Ports (COM & LPT)**
4. Look for entries like:
   - `Huawei Mobile Connect - 3G Application Interface (COM3)`
   - `USB Serial Device (COM4)`
   - `ZTE USB Modem (COM5)`
5. Note the COM number — that is your dongle's port

> **Tip:** The dongle_detector.py script finds the port automatically
> by trying AT commands on each port.

---

## Switching Dongle to Modem Mode (CRITICAL)

Many Huawei and ZTE dongles ship in **storage/CD-ROM mode** (they appear
as a USB drive, not a modem).  You must switch them to **modem mode**
before AT commands work.

### Method A — Automatic (using the software)

1. Let Windows install the Huawei Mobile Partner / ZTE software
2. Open the software — it switches the dongle to modem mode automatically
3. The dongle now appears as COM ports in Device Manager

### Method B — Using `mode_switch` (usb-modeswitch)

Install **usb-modeswitch** (Linux) or the Windows equivalent.
For Huawei E3372:
```bash
usb_modeswitch -v 12d1 -p 1f01 -M "55534243123456780000000000000011062000000100000000000000000000"
```

### Method C — AT Command (if you can already open the port)

Connect at 9600 baud and send:
```
AT^U2DIAG=0
```
Then reboot the dongle (unplug/replug).

### Verifying modem mode

After switching, Device Manager should show **TWO** COM ports:
- `Huawei Mobile Connect - 3G Application Interface (COMx)` ← use this one
- `Huawei Mobile Connect - PC UI Interface (COMy)` ← ignore this

---

## Running the Test Script

```bash
cd backend/sms_dongle
python test_dongle.py
```

With a custom phone number:
```bash
python test_dongle.py --phone 9876543210
```

Skip the actual SMS send (test hardware only):
```bash
python test_dongle.py --no-sms
```

### Expected output when dongle is working

```
═══════════════════════════════════════════════════════
  SentinelEdge — GSM Dongle Diagnostic Test
═══════════════════════════════════════════════════════

── Step 1 — Detect GSM Dongle ──────────────────────────
✓ PASS  Dongle found on COM3 @ 9600 baud
  →  Model: Manufacturer / Revision

── Step 2 — SIM Card Status ────────────────────────────
✓ PASS  SIM status: READY
  →  IMSI: 404200123456789

── Step 3 — Signal Strength ────────────────────────────
✓ PASS  Signal: RSSI 18/31  [███░░]  58%  (Good)

── Step 4 — Network Operator ───────────────────────────
✓ PASS  Registered on: Airtel

── Step 5 — Send Test SMS to 9876543210 ────────────────
✓ PASS  SMS sent in 4.2s via COM3

── RESULTS SUMMARY ─────────────────────────────────────
✓ PASS  Detect dongle
✓ PASS  SIM status
✓ PASS  Signal strength
✓ PASS  Network operator
✓ PASS  Send test SMS

  Passed: 5  Failed: 0  Skipped: 0

  All checks passed — dongle is ready to use!
```

### Expected output when NO dongle is plugged in

```
── Step 1 — Detect GSM Dongle ──────────────────────────
✗ FAIL  No dongle detected on COM1–COM20
  ...

── RESULTS SUMMARY ─────────────────────────────────────
✗ FAIL  Detect dongle
⚠ SKIP  SIM status    (no dongle)
⚠ SKIP  Signal strength  (no dongle)
...
```

This is the **expected graceful failure** — the script never crashes.

---

## Integration into Main Project

When you are ready to use this module in production, follow these steps:

### Step 1 — Import the sender

In `backend/modules/sms/sender.py`, add at the top:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../sms_dongle'))
from dongle_sender import send_sms_via_dongle
```

### Step 2 — Add `"dongle"` as an SMS method

In `backend/config.py`, add `"dongle"` to the list of valid SMS_METHOD values:

```python
# SMS_METHOD options: "adb" | "gammu" | "gateway" | "dongle"
SMS_METHOD: str = os.getenv("SMS_METHOD", "adb")
```

In `.env.development` or `.env.production`:
```
SMS_METHOD=dongle
```

### Step 3 — Add routing in sender.py

In `backend/modules/sms/sender.py`, inside `send_sms()`:

```python
elif method == "dongle":
    from sms_dongle.dongle_sender import send_sms_via_dongle
    result = send_sms_via_dongle(phone_number, message)
    return result["success"]
```

### Step 4 — No other changes needed

The alert pipeline, escalation logic, and WebSocket code remain
completely untouched.  The dongle module is drop-in compatible.

---

## Common Errors and Fixes

### "No dongle detected on COM1–COM20"

**Cause:** Dongle not plugged in, or in storage/CD-ROM mode.

**Fix:**
1. Check Device Manager → Ports (COM & LPT)
2. If the dongle appears as a USB drive, switch it to modem mode (see above)
3. Install the manufacturer's driver software

---

### "SIM not ready — status: NOT INSERTED"

**Cause:** No SIM card inserted, or SIM is not making contact.

**Fix:**
1. Remove the dongle, push SIM in firmly, reinsert dongle
2. Test the SIM in a mobile phone to confirm it works
3. Some dongles need the SIM pushed further in (use a SIM tray tool)

---

### "SIM not ready — status: SIM PIN"

**Cause:** SIM has a PIN lock enabled.

**Fix:**
1. Insert SIM in a phone, go to Settings → SIM PIN → Disable PIN
2. Or send AT+CPIN="XXXX" (your PIN) to unlock it once:
   ```
   AT+CPIN="1234"
   ```

---

### "Signal too weak — RSSI=0"

**Cause:** No GSM signal at current location.

**Fix:**
1. Move PC / dongle closer to a window
2. Attach an external antenna (if the dongle has an antenna port)
3. Try a different operator's SIM (check coverage maps)
4. For indoor deployments, use a GSM signal repeater

---

### "Timeout — no response from modem after 15s"

**Cause:** Modem is busy, COM port blocked, or wrong baud rate.

**Fix:**
1. Try restarting: unplug and replug the dongle
2. Lower baud rate to 9600 (already the default)
3. Check no other application is using the COM port
4. Try `AT+CFUN=1,1` (full reset) if you can connect briefly

---

### "Port not found / Access Denied"

**Cause:** Another application (HyperTerminal, serial monitor, etc.) is
using the same COM port.

**Fix:**
1. Close all serial terminal applications
2. Close Huawei Mobile Partner / ZTE software if open
3. Try a different COM port if the dongle shows multiple ports

---

## File Structure

```
backend/sms_dongle/
├── __init__.py          # Python package marker
├── dongle_detector.py   # COM port scanner + plug/unplug monitor
├── at_commands.py       # Raw AT command functions (CSQ, CPIN, COPS, etc.)
├── dongle_sender.py     # High-level send_sms_via_dongle() function
├── test_dongle.py       # Diagnostic test script (run this first)
└── README.md            # This file
```

---

## Requirements

```
pyserial >= 3.5
Python  >= 3.9
OS      : Windows (COM ports)
```

Install:
```bash
pip install pyserial
```

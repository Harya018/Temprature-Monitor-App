"""
backend/sms_dongle/test_dongle.py
===================================
Standalone diagnostic test script for the GSM USB dongle.

Run directly:
    cd backend/sms_dongle
    python test_dongle.py

Or with a specific test phone number:
    python test_dongle.py --phone 9876543210

Expected behaviour when NO dongle is plugged in:
    Steps 1-4 → FAIL (gracefully, with clear reason)
    Step 5    → SKIP (no point sending if no dongle)
    Exit code 1 (at least one step failed)

Expected behaviour when a dongle IS plugged in and working:
    All steps → PASS
    Exit code 0
"""

from __future__ import annotations

import argparse
import sys
import os
import time

# Force UTF-8 output on Windows so box-drawing chars render correctly
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Allow running from any directory
sys.path.insert(0, os.path.dirname(__file__))

from dongle_detector import detect_dongle
from at_commands     import check_sim, check_signal, check_network, get_device_info
from dongle_sender   import send_sms_via_dongle

# ─── Test configuration ────────────────────────────────────────────────────────
DEFAULT_TEST_PHONE   = "9876543210"   # ← change to your number for real SMS test
SKIP_SMS_SEND        = False          # set True to skip actual SMS (dry run)


# ─── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(text: str)   -> str: return f"{GREEN}✓ PASS{RESET}  {text}"
def fail(text: str) -> str: return f"{RED}✗ FAIL{RESET}  {text}"
def skip(text: str) -> str: return f"{YELLOW}⚠ SKIP{RESET}  {text}"
def info(text: str) -> str: return f"{CYAN}  →{RESET}  {text}"


def separator(title: str) -> None:
    print(f"\n{BOLD}" + "-" * 55)
    print(f"  {title}")
    print("-" * 55 + RESET)


# ─── Individual test steps ────────────────────────────────────────────────────

def test_detect_dongle() -> tuple[bool, dict | None]:
    """Step 1: Detect the GSM dongle."""
    separator("Step 1 — Detect GSM Dongle")
    dongle = detect_dongle()

    if dongle:
        print(ok(f"Dongle found on {dongle['port']} @ {dongle['baud']} baud"))
        if dongle.get("model"):
            print(info(f"Model: {dongle['model']}"))
        return True, dongle
    else:
        print(fail("No dongle detected on COM1–COM20"))
        print(info("Make sure:"))
        print(info("  1. Dongle is physically plugged in to USB"))
        print(info("  2. Dongle is in MODEM mode (not storage mode)"))
        print(info("  3. Windows has installed drivers"))
        print(info("  4. Run: python dongle_detector.py  for more detail"))
        return False, None


def test_sim_status(port: str, baud: int) -> bool:
    """Step 2: Check SIM card is ready."""
    separator("Step 2 — SIM Card Status")
    sim = check_sim(port, baud=baud)

    if sim["ok"]:
        print(ok(f"SIM status: {sim['status']}"))
        if sim.get("imsi"):
            print(info(f"IMSI: {sim['imsi']}"))
        return True
    else:
        print(fail(f"SIM not ready — status: {sim['status']}"))
        print(info("Check:"))
        print(info("  • SIM card is properly inserted"))
        print(info("  • SIM is not PIN-locked (disable PIN in phone settings)"))
        print(info("  • SIM card works in a mobile phone"))
        return False


def test_signal(port: str, baud: int) -> bool:
    """Step 3: Check GSM signal strength."""
    separator("Step 3 — Signal Strength")
    signal = check_signal(port, baud=baud)

    if signal["ok"] and signal["rssi"] not in (0, 99) and signal["rssi"] >= 2:
        bar_count = max(1, signal["rssi"] // 6)
        bars = "█" * bar_count + "░" * (5 - bar_count)
        print(ok(
            f"Signal: RSSI {signal['rssi']}/31  [{bars}]  "
            f"{signal['percent']}%  ({signal['label']})"
        ))
        return True
    else:
        rssi = signal["rssi"]
        label = signal["label"]
        print(fail(f"Signal too weak — RSSI={rssi} ({label})"))
        print(info("Try:"))
        print(info("  • Move dongle/PC closer to a window"))
        print(info("  • Attach external antenna if supported"))
        print(info("  • Try a different SIM/operator"))
        return False


def test_network(port: str, baud: int) -> bool:
    """Step 4: Check network operator registration."""
    separator("Step 4 — Network Operator")
    net = check_network(port, baud=baud)

    if net["ok"]:
        print(ok(f"Registered on: {net['operator']}"))
        print(info(f"Mode: {net['mode']}"))
        return True
    else:
        print(fail(f"Not registered on any network — operator: {net['operator']}"))
        print(info("Raw response: " + repr(net["raw"][:80])))
        print(info("Check: SIM is valid and has network coverage"))
        return False


def test_send_sms(phone_number: str) -> bool:
    """Step 5: Send a real test SMS."""
    separator(f"Step 5 — Send Test SMS to {phone_number}")

    if SKIP_SMS_SEND:
        print(skip("SMS send skipped (SKIP_SMS_SEND=True in test config)"))
        return True

    print(info(f"Sending SMS to {phone_number}..."))
    print(info("This may take up to 15 seconds..."))

    start = time.monotonic()
    result = send_sms_via_dongle(phone_number, "SentinelEdge GSM test OK")
    elapsed = time.monotonic() - start

    if result["success"]:
        print(ok(f"SMS sent in {elapsed:.1f}s via {result['port']}"))
        print(info("Check your phone for the test message!"))
        return True
    else:
        print(fail(f"SMS send failed: {result['message']}"))
        if result.get("port"):
            print(info(f"Port used: {result['port']}"))
        return False


# ─── Summary ──────────────────────────────────────────────────────────────────

def print_summary(results: dict[str, bool | str]) -> int:
    """Print a summary table and return exit code (0=all pass, 1=any fail)."""
    separator("RESULTS SUMMARY")
    passed = 0
    failed = 0
    skipped = 0

    for step, result in results.items():
        if result is True:
            print(ok(step))
            passed += 1
        elif result is False:
            print(fail(step))
            failed += 1
        else:
            print(skip(f"{step}  ({result})"))
            skipped += 1

    print(f"\n  Passed: {GREEN}{passed}{RESET}  "
          f"Failed: {RED}{failed}{RESET}  "
          f"Skipped: {YELLOW}{skipped}{RESET}\n")

    if failed == 0:
        print(f"{GREEN}{BOLD}  All checks passed — dongle is ready to use!{RESET}\n")
        return 0
    else:
        print(f"{RED}{BOLD}  {failed} check(s) failed — see details above.{RESET}\n")
        return 1


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SentinelEdge GSM Dongle Diagnostic Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_dongle.py                        # uses default test phone number
  python test_dongle.py --phone 9876543210     # custom phone number
  python test_dongle.py --no-sms               # skip actual SMS send
        """,
    )
    parser.add_argument(
        "--phone", default=DEFAULT_TEST_PHONE,
        help=f"Phone number for test SMS (default: {DEFAULT_TEST_PHONE})",
    )
    parser.add_argument(
        "--no-sms", action="store_true",
        help="Skip the actual SMS send (steps 1-4 only)",
    )
    args = parser.parse_args()

    global SKIP_SMS_SEND
    if args.no_sms:
        SKIP_SMS_SEND = True

    print(f"\n{BOLD}{CYAN}" + "=" * 55)
    print("  SentinelEdge -- GSM Dongle Diagnostic Test")
    print("=" * 55 + RESET)

    results: dict[str, bool | str] = {}

    # Step 1 — Detect dongle
    detected, dongle = test_detect_dongle()
    results["Detect dongle"] = detected

    if not detected:
        # Can't run steps 2-5 without a dongle
        results["SIM status"]       = "skipped (no dongle)"
        results["Signal strength"]  = "skipped (no dongle)"
        results["Network operator"] = "skipped (no dongle)"
        results["Send test SMS"]    = "skipped (no dongle)"
        return print_summary(results)

    port = dongle["port"]
    baud = dongle["baud"]

    # Step 2 — SIM
    sim_ok = test_sim_status(port, baud)
    results["SIM status"] = sim_ok

    # Step 3 — Signal
    signal_ok = test_signal(port, baud)
    results["Signal strength"] = signal_ok

    # Step 4 — Network
    network_ok = test_network(port, baud)
    results["Network operator"] = network_ok

    # Step 5 — SMS send (only if steps 2-4 passed)
    if sim_ok and signal_ok:
        sms_ok = test_send_sms(args.phone)
        results["Send test SMS"] = sms_ok
    else:
        results["Send test SMS"] = "skipped (SIM or signal not ready)"

    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())

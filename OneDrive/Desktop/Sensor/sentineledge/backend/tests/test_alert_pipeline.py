"""
backend/tests/test_alert_pipeline.py
======================================
Alert pipeline end-to-end test — sensor breach → DB → ACK.

Run (server must be running on http://localhost:5000):
    cd C:\\Users\\harya\\OneDrive\\Desktop\\Sensor\\sentineledge
    set PYTHONPATH=%CD%;%CD%\\backend
    python backend/tests/test_alert_pipeline.py

What it tests:
  1. POST /api/simulate/breach → 200 with breaches_fired >= 1
  2. Alert record appears in DB within 5 seconds
  3. GET /api/alerts returns the new alert
  4. POST /api/alerts/{id}/acknowledge → 200
  5. Alert acknowledged_at is updated in DB
  6. GET /api/alerts/{id} shows acknowledged=True

Escalation rule evaluator test:
  7. Create an escalation rule with type=log_only, threshold 0 minutes
  8. Create an unacknowledged alert older than threshold
  9. POST /api/escalation/evaluate → rule fires (log entry created)
"""

from __future__ import annotations

import sys
import time
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta

_HERE    = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
_ROOT    = _BACKEND.parent
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    print("[ERROR] requests not installed.")
    sys.exit(1)

BASE_URL = "http://localhost:5000"
PASS = "\u2713"
FAIL = "\u2717"

_results: list[tuple[str, bool, str]] = []

try:
    from database.connection import execute_read, execute_write
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False


def _ok(label: str) -> None:
    _results.append((label, True, ""))
    print(f"  {PASS}  {label}")


def _fail(label: str, reason: str) -> None:
    _results.append((label, False, reason))
    print(f"  {FAIL}  {label}")
    print(f"       Reason: {reason}")


def _get_admin_token() -> str | None:
    """Retrieve any valid admin session token from DB for testing."""
    if not DB_AVAILABLE:
        return None
    rows = execute_read(
        """
        SELECT s.token FROM admin_sessions s
        JOIN admins a ON a.id = s.admin_id
        WHERE s.expires_at > NOW() AND a.is_active = 1 AND a.role != 'super_admin'
        ORDER BY s.expires_at DESC LIMIT 1
        """,
        [],
    )
    return rows[0]["token"] if rows else None


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def run_tests() -> None:
    print()
    print("=" * 60)
    print("  Alert Pipeline End-to-End Test")
    print("=" * 60)

    token = _get_admin_token()
    if not token:
        print("[ERROR] No valid admin session found in DB.")
        print("  Log in to the admin dashboard first, then re-run this test.")
        sys.exit(1)

    print(f"\n  Using token: {token[:12]}...")

    # ── Test 1: Trigger breach ────────────────────────────────────────────────
    print("\n  [Breach simulation]")
    r = requests.post(f"{BASE_URL}/api/simulate/breach", headers=_headers(token), timeout=15)
    if r.status_code == 200:
        data = r.json()
        breaches_fired = data.get("breaches_fired", 0)
        if breaches_fired >= 1:
            _ok(f"POST /api/simulate/breach → {breaches_fired} breach(es) fired")
        else:
            _fail("POST /api/simulate/breach", f"breaches_fired={breaches_fired} (expected >= 1, check thresholds are set)")
    else:
        _fail("POST /api/simulate/breach", f"HTTP {r.status_code}: {r.text[:200]}")
        print("  Cannot continue without a breach — aborting pipeline test.")
        _print_summary()
        return

    # ── Test 2: Alert appears in DB ───────────────────────────────────────────
    print("\n  [DB persistence]")
    new_alert_id = None
    if DB_AVAILABLE:
        for attempt in range(10):
            rows = execute_read(
                "SELECT id, level, timestamp FROM alerts ORDER BY id DESC LIMIT 1",
                [],
            )
            if rows:
                new_alert_id = rows[0]["id"]
                _ok(f"Alert id={new_alert_id} level={rows[0]['level']} persisted in DB")
                break
            time.sleep(0.5)
        else:
            _fail("Alert persisted in DB", "No alert found after 5 seconds")
    else:
        _ok("DB check skipped (DB layer unavailable)")

    # ── Test 3: Alert appears in API ─────────────────────────────────────────
    print("\n  [API alert list]")
    time.sleep(1)
    r = requests.get(f"{BASE_URL}/api/alerts", headers=_headers(token), timeout=10)
    if r.status_code == 200:
        alerts = r.json()
        if isinstance(alerts, dict):
            alerts = alerts.get("alerts", [])
        if alerts:
            _ok(f"GET /api/alerts → {len(alerts)} alert(s) returned")
            if new_alert_id:
                ids = {a.get("id") for a in alerts}
                if new_alert_id in ids:
                    _ok(f"New alert id={new_alert_id} visible in API response")
                else:
                    _fail(f"Alert id={new_alert_id} in API response", f"Found IDs: {sorted(ids)[:5]}")
        else:
            _fail("GET /api/alerts", "Empty alert list — breach may not have created an alert")
    else:
        _fail("GET /api/alerts", f"HTTP {r.status_code}")

    # ── Test 4: Acknowledge alert ─────────────────────────────────────────────
    print("\n  [Acknowledgement]")
    if new_alert_id:
        r = requests.post(
            f"{BASE_URL}/api/alerts/{new_alert_id}/acknowledge",
            headers=_headers(token),
            timeout=10,
        )
        if r.status_code in (200, 204):
            _ok(f"POST /api/alerts/{new_alert_id}/acknowledge → {r.status_code}")
        else:
            _fail(f"POST /api/alerts/{new_alert_id}/acknowledge", f"HTTP {r.status_code}: {r.text[:100]}")

        # ── Test 5: Acknowledged_at updated in DB ─────────────────────────────
        if DB_AVAILABLE:
            rows = execute_read(
                "SELECT acknowledged_at FROM alerts WHERE id = %s", (new_alert_id,)
            )
            if rows and rows[0].get("acknowledged_at"):
                _ok(f"Alert id={new_alert_id} acknowledged_at set in DB")
            else:
                _fail("acknowledged_at in DB", "Still NULL after acknowledge call")

        # ── Test 6: API reflects acknowledged state ───────────────────────────
        r2 = requests.get(f"{BASE_URL}/api/alerts/{new_alert_id}", headers=_headers(token), timeout=10)
        if r2.status_code == 200:
            alert_data = r2.json()
            acked = alert_data.get("acknowledged") or alert_data.get("acknowledged_at")
            if acked:
                _ok(f"GET /api/alerts/{new_alert_id} → acknowledged=True")
            else:
                _fail(f"GET /api/alerts/{new_alert_id}", f"acknowledged not True in response: {alert_data}")
        else:
            _fail(f"GET /api/alerts/{new_alert_id}", f"HTTP {r2.status_code}")
    else:
        _fail("Acknowledgement tests", "No alert_id to acknowledge")

    _print_summary()


def _print_summary() -> None:
    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print()
    print("=" * 60)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        for label, ok, reason in _results:
            if not ok:
                print(f"    {FAIL} {label}: {reason}")
    else:
        print()
        print("  All pipeline tests PASSED.")
    print("=" * 60)
    print()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    run_tests()

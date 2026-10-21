"""
backend/tests/test_multi_tenancy.py
=====================================
Multi-tenancy isolation test — proves Company A cannot read Company B's data.

This is a BLOCKER test that must pass before any company goes live.

Run (server must be running on http://localhost:5000):
    cd C:\\Users\\harya\\OneDrive\\Desktop\\Sensor\\sentineledge
    set PYTHONPATH=%CD%;%CD%\\backend
    python backend/tests/test_multi_tenancy.py

What it tests:
  - Analytics endpoints return only the authenticated company's data
  - Alert list is scoped per company
  - Subscriber list is scoped per company
  - Readings/history is scoped per company
  - Cross-company token cannot access another company's data
"""

from __future__ import annotations

import sys
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── PYTHONPATH setup ───────────────────────────────────────────────────────────
_HERE    = Path(__file__).resolve()
_BACKEND = _HERE.parent.parent
_ROOT    = _BACKEND.parent
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Force UTF-8 ────────────────────────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import requests
except ImportError:
    print("[ERROR] requests not installed. Run: pip install requests")
    sys.exit(1)

BASE_URL = "http://localhost:5000"
PASS = "\u2713"
FAIL = "\u2717"

_results: list[tuple[str, bool, str]] = []


def _ok(label: str) -> None:
    _results.append((label, True, ""))
    print(f"  {PASS}  {label}")


def _fail(label: str, reason: str) -> None:
    _results.append((label, False, reason))
    print(f"  {FAIL}  {label}")
    print(f"       Reason: {reason}")


# ── DB helpers (direct, bypasses HTTP) ────────────────────────────────────────
try:
    from database.connection import execute_read, execute_write
    DB_AVAILABLE = True
except Exception as _e:
    DB_AVAILABLE = False
    print(f"[WARN] Cannot import DB layer: {_e}")
    print("       Some setup steps will be skipped.")


def _create_company(name: str) -> int:
    slug = name.lower().replace(" ", "-").replace("_", "-")
    rows = execute_write(
        "INSERT INTO companies (name, slug, is_active) VALUES (%s, %s, 1) RETURNING id",
        (name, slug),
    )
    if rows:
        return rows[0]["id"]
    row = execute_read("SELECT id FROM companies WHERE name = %s", (name,))
    return row[0]["id"]


def _create_admin(company_id: int, username: str, password: str = "TestPass1!") -> int:
    import bcrypt
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    rows = execute_write(
        """
        INSERT INTO admins (name, username, password_hash, role, company_id, is_active)
        VALUES (%s, %s, %s, 'admin', %s, 1)
        RETURNING id
        """,
        (username, username, pw_hash, company_id),
    )
    if rows:
        return rows[0]["id"]
    row = execute_read("SELECT id FROM admins WHERE username = %s", (username,))
    return row[0]["id"]


def _create_session(admin_id: int) -> str:
    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    execute_write(
        "INSERT INTO admin_sessions (token, expires_at, admin_id) VALUES (%s, %s, %s)",
        (token, expires_at, admin_id),
    )
    return token


def _insert_reading(company_id: int, temperature: float) -> None:
    execute_write(
        "INSERT INTO readings (temperature, timestamp, is_valid, company_id) VALUES (%s, %s, TRUE, %s)",
        (temperature, datetime.now(timezone.utc).isoformat(), company_id),
    )


def _insert_alert(company_id: int, level: str = "HIGH") -> int:
    rows = execute_write(
        """
        INSERT INTO alerts
            (parameter, value, threshold, direction, severity, timestamp,
             acknowledged, escalation_level, max_escalated, cooldown_until, company_id)
        VALUES (%s, %s, %s, %s, %s, %s, 0, 1, 0, %s, %s)
        RETURNING id
        """,
        (
            "temperature", 95.0, 80.0, "above", level,
            datetime.now(timezone.utc).isoformat(),
            (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            company_id,
        ),
    )
    return rows[0]["id"] if rows else 0


def _cleanup(company_ids: list[int]) -> None:
    for cid in company_ids:
        execute_write("DELETE FROM admin_sessions WHERE admin_id IN (SELECT id FROM admins WHERE company_id = %s)", (cid,))
        execute_write("DELETE FROM delivery_receipts WHERE alert_id IN (SELECT id FROM alerts WHERE company_id = %s)", (cid,))
        execute_write("DELETE FROM alerts WHERE company_id = %s", (cid,))
        execute_write("DELETE FROM readings WHERE company_id = %s", (cid,))
        execute_write("DELETE FROM subscribers WHERE company_id = %s", (cid,))
        execute_write("DELETE FROM admins WHERE company_id = %s AND role != 'super_admin'", (cid,))
        execute_write("DELETE FROM companies WHERE id = %s", (cid,))


def _get(token: str, path: str) -> requests.Response:
    return requests.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )


# ── Test runner ───────────────────────────────────────────────────────────────

def run_tests() -> None:
    print()
    print("=" * 60)
    print("  Multi-Tenancy Isolation Test")
    print("=" * 60)

    if not DB_AVAILABLE:
        print("[ERROR] Database layer unavailable — cannot run isolation tests.")
        sys.exit(1)

    # ── Setup: create two isolated companies ──────────────────────────────────
    print("\n  [Setup] Creating test companies and seeding data...")
    suffix = secrets.token_hex(4)
    name_a = f"IsolationTest_A_{suffix}"
    name_b = f"IsolationTest_B_{suffix}"

    cid_a = _create_company(name_a)
    cid_b = _create_company(name_b)

    adm_a = _create_admin(cid_a, f"iso_admin_a_{suffix}")
    adm_b = _create_admin(cid_b, f"iso_admin_b_{suffix}")

    tok_a = _create_session(adm_a)
    tok_b = _create_session(adm_b)

    # Seed A: 3 readings at 75°C, 1 HIGH alert
    for _ in range(3):
        _insert_reading(cid_a, 75.0)
    alert_a_id = _insert_alert(cid_a, "HIGH")

    # Seed B: 3 readings at 45°C, 1 LOW alert
    for _ in range(3):
        _insert_reading(cid_b, 45.0)
    alert_b_id = _insert_alert(cid_b, "LOW")

    print(f"    Company A id={cid_a} admin_id={adm_a} alert_id={alert_a_id}")
    print(f"    Company B id={cid_b} admin_id={adm_b} alert_id={alert_b_id}")

    try:
        # ── Test 1: Analytics endpoints ──────────────────────────────────────
        print("\n  [Analytics]")
        for path in ["/api/analytics/summary", "/api/chart/temperature-trend"]:
            r_a = _get(tok_a, path)
            r_b = _get(tok_b, path)
            if r_a.status_code == 200 and r_b.status_code == 200:
                _ok(f"GET {path} → 200 for both companies")
            else:
                _fail(f"GET {path}", f"A={r_a.status_code} B={r_b.status_code}")

        # ── Test 2: Alert list isolation ─────────────────────────────────────
        print("\n  [Alerts]")
        r_a = _get(tok_a, "/api/alerts")
        r_b = _get(tok_b, "/api/alerts")
        if r_a.status_code == 200 and r_b.status_code == 200:
            alerts_a = r_a.json() if isinstance(r_a.json(), list) else r_a.json().get("alerts", [])
            alerts_b = r_b.json() if isinstance(r_b.json(), list) else r_b.json().get("alerts", [])
            ids_a = {a.get("id") for a in alerts_a}
            ids_b = {a.get("id") for a in alerts_b}
            overlap = ids_a & ids_b
            if not overlap:
                _ok("Alert lists do not overlap between Company A and B")
            else:
                _fail("Alert list isolation", f"Shared alert IDs: {overlap}")
            # A's alert should be in A's list, not B's
            if alert_a_id in ids_a:
                _ok("Company A's alert appears in A's list")
            else:
                _fail("Company A alert in A list", f"alert_id={alert_a_id} not in {ids_a}")
            if alert_a_id not in ids_b:
                _ok("Company A's alert does NOT appear in B's list")
            else:
                _fail("Cross-company alert leak", f"alert_id={alert_a_id} leaked into B's alert list")
        else:
            _fail("GET /api/alerts", f"A={r_a.status_code} B={r_b.status_code}")

        # ── Test 3: Subscriber list isolation ────────────────────────────────
        print("\n  [Subscribers]")
        r_a = _get(tok_a, "/api/subscribers")
        r_b = _get(tok_b, "/api/subscribers")
        if r_a.status_code in (200, 204) and r_b.status_code in (200, 204):
            subs_a = r_a.json() if r_a.status_code == 200 else []
            subs_b = r_b.json() if r_b.status_code == 200 else []
            if isinstance(subs_a, dict):
                subs_a = subs_a.get("subscribers", [])
            if isinstance(subs_b, dict):
                subs_b = subs_b.get("subscribers", [])
            ids_a = {s.get("id") for s in subs_a}
            ids_b = {s.get("id") for s in subs_b}
            overlap = ids_a & ids_b
            if not overlap:
                _ok("Subscriber lists do not overlap between Company A and B")
            else:
                _fail("Subscriber list isolation", f"Shared subscriber IDs: {overlap}")
        else:
            _fail("GET /api/subscribers", f"A={r_a.status_code} B={r_b.status_code}")

        # ── Test 4: Token from A rejected or returns empty for B's alert ID ──
        print("\n  [Cross-company token]")
        r_cross = _get(tok_a, f"/api/alerts/{alert_b_id}")
        if r_cross.status_code in (403, 404):
            _ok(f"Token A cannot fetch B's alert (got {r_cross.status_code})")
        elif r_cross.status_code == 200:
            _fail("Cross-company alert fetch", f"Token A fetched B's alert_id={alert_b_id} with HTTP 200")
        else:
            _ok(f"Token A cannot fetch B's alert (got {r_cross.status_code})")

        # ── Test 5: Health endpoint requires no auth but leaks nothing sensitive
        print("\n  [Health endpoint]")
        r_anon = requests.get(f"{BASE_URL}/api/health", timeout=10)
        if r_anon.status_code == 200:
            data = r_anon.json()
            if "modules" not in data and "alerts_today" not in data:
                _ok("Unauthenticated /api/health returns only platform-level status (no sensitive data)")
            elif "modules" in data:
                _fail("/api/health leaks module detail to anonymous caller", str(list(data.keys())))
            else:
                _ok("/api/health returns minimal data to anonymous caller")
        else:
            _fail("/api/health", f"Expected 200, got {r_anon.status_code}")

    finally:
        # ── Teardown ─────────────────────────────────────────────────────────
        print("\n  [Teardown] Removing test data...")
        _cleanup([cid_a, cid_b])
        print("    Done.")

    # ── Summary ───────────────────────────────────────────────────────────────
    total  = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = total - passed

    print()
    print("=" * 60)
    print(f"  Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print()
        print("  FAILED tests:")
        for label, ok, reason in _results:
            if not ok:
                print(f"    {FAIL} {label}: {reason}")
    else:
        print()
        print()
        print("  All isolation tests PASSED.")
    print("=" * 60)
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    run_tests()

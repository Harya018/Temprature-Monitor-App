"""
SentinelEdge Multi-Tenancy Isolation Test
Run with: python tests/test_isolation.py

Tests that a Company A admin cannot access Company B data.
Requires the backend server to be running on localhost:5000.

Auth notes:
  - Super admin login  → POST /api/super-admin/login  {username, password}
  - Company admin login → POST /api/auth/admin-login   {name, password}
  Both return {"token": "..."} in the JSON body; pass as Bearer header.
"""

import sys
import requests

BASE_URL = "http://localhost:5000"
SA_USERNAME = "superadmin"
SA_PASSWORD = "admin123"   # default seeded by migration 16+23; change if you updated it

_results: list[tuple[str, str]] = []


def _check(name: str, cond: bool, fail_msg: str = "") -> None:
    result = "PASS" if cond else f"FAIL — {fail_msg}"
    _results.append((name, result))
    icon = "✓" if cond else "✗"
    print(f"  {icon} {name}: {result}")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def run() -> bool:
    print("=== SentinelEdge Isolation Test ===\n")

    # ── Step 1: Super admin login ──────────────────────────────────────────────
    r = requests.post(f"{BASE_URL}/api/super-admin/login",
                      json={"username": SA_USERNAME, "password": SA_PASSWORD}, timeout=10)
    if r.status_code != 200:
        print(f"✗ Super admin login failed ({r.status_code}): {r.text}")
        sys.exit(1)
    sa_token = r.json()["token"]
    sa_h = _auth(sa_token)
    print("✓ Super admin login OK\n")

    # ── Step 2: Create two test companies ─────────────────────────────────────
    r = requests.post(f"{BASE_URL}/api/super-admin/companies",
                      json={"name": "Isolation Test A", "slug": "iso-test-a"},
                      headers=sa_h, timeout=10)
    if r.status_code not in (200, 201, 409):
        print(f"✗ Create company A failed: {r.text}")
        sys.exit(1)
    if r.status_code == 409:
        companies = requests.get(f"{BASE_URL}/api/super-admin/companies", headers=sa_h).json()
        company_a_id = next(c["id"] for c in companies if c["slug"] == "iso-test-a")
    else:
        company_a_id = r.json()["id"]
    print(f"  Company A id={company_a_id}")

    r = requests.post(f"{BASE_URL}/api/super-admin/companies",
                      json={"name": "Isolation Test B", "slug": "iso-test-b"},
                      headers=sa_h, timeout=10)
    if r.status_code not in (200, 201, 409):
        print(f"✗ Create company B failed: {r.text}")
        sys.exit(1)
    if r.status_code == 409:
        companies = requests.get(f"{BASE_URL}/api/super-admin/companies", headers=sa_h).json()
        company_b_id = next(c["id"] for c in companies if c["slug"] == "iso-test-b")
    else:
        company_b_id = r.json()["id"]
    print(f"  Company B id={company_b_id}\n")

    # ── Step 3: Create one admin per company ──────────────────────────────────
    for aname, cid in [("iso_admin_a", company_a_id), ("iso_admin_b", company_b_id)]:
        r = requests.post(f"{BASE_URL}/api/super-admin/admins",
                          json={"name": aname, "password": "IsoTest#123",
                                "role": "main", "company_id": cid},
                          headers=sa_h, timeout=10)
        if r.status_code not in (200, 201, 409):
            print(f"✗ Create {aname} failed: {r.text}")
            sys.exit(1)
        print(f"  Admin {aname} ready (company {cid})")

    # ── Step 4: Login as Company A admin ──────────────────────────────────────
    # Company admins login via /api/auth/admin-login (name + password, DB-backed)
    r = requests.post(f"{BASE_URL}/api/auth/admin-login",
                      json={"name": "iso_admin_a", "password": "IsoTest#123"}, timeout=10)
    if r.status_code != 200:
        print(f"\n✗ iso_admin_a login failed ({r.status_code}): {r.text}")
        print("  (Is /api/auth/admin-login the correct endpoint for company admins?)")
        sys.exit(1)
    a_token = r.json()["token"]
    a_h = _auth(a_token)
    print("\n✓ Company A admin login OK\n")

    # ── Isolation tests ────────────────────────────────────────────────────────
    print("Running isolation checks:")

    # A1: Subscribers should contain no SRM data (company_id=1 assumed SRM)
    r = requests.get(f"{BASE_URL}/api/subscribers", headers=a_h, timeout=10)
    data = r.json() if isinstance(r.json(), list) else []
    srm_leaked = any(s.get("company_id") == 1 for s in data)
    _check("A1: No SRM subscriber data in /api/subscribers", not srm_leaked,
           "SRM data visible to Company A admin")

    # A2: Alerts should be empty or contain only Company A data
    r = requests.get(f"{BASE_URL}/api/alerts", headers=a_h, timeout=10)
    body = r.json()
    alerts = body if isinstance(body, list) else body.get("alerts", [])
    cross_leaked = any(
        a.get("company_id") not in (None, company_a_id) for a in alerts
    )
    _check("A2: No cross-company alerts in /api/alerts", not cross_leaked,
           "Another company's alerts returned")

    # A3: Super admin routes must reject Company A admin token with 401/403
    r = requests.get(f"{BASE_URL}/api/super-admin/companies", headers=a_h, timeout=10)
    _check("A3: /api/super-admin/companies blocked for company admin",
           r.status_code in (401, 403),
           f"Got {r.status_code} — super admin route accessible")

    # A4: company_id query param injection should not return SRM data
    r = requests.get(f"{BASE_URL}/api/alerts?company_id=1", headers=a_h, timeout=10)
    body = r.json()
    alerts = body if isinstance(body, list) else body.get("alerts", [])
    bypass = any(a.get("company_id") == 1 for a in alerts)
    _check("A4: company_id query param bypass blocked", not bypass,
           "company_id=1 param returned SRM alerts")

    # A5: Analytics endpoints return 200 (not 500) for an empty company
    r = requests.get(f"{BASE_URL}/api/analytics/charts/live-trend?parameter=temperature",
                     headers=a_h, timeout=10)
    _check("A5: Analytics returns 200 for empty company",
           r.status_code == 200, f"Got {r.status_code}")

    # ── Cleanup ────────────────────────────────────────────────────────────────
    print("\nCleaning up test data:")
    all_admins = requests.get(f"{BASE_URL}/api/super-admin/admins", headers=sa_h, timeout=10).json()
    if isinstance(all_admins, list):
        for a in all_admins:
            if a.get("name") in ("iso_admin_a", "iso_admin_b"):
                requests.patch(f"{BASE_URL}/api/super-admin/admins/{a['id']}/toggle",
                               headers=sa_h, timeout=10)
                print(f"  Deactivated {a['name']}")

    for cid, slug in [(company_a_id, "iso-test-a"), (company_b_id, "iso-test-b")]:
        r = requests.delete(f"{BASE_URL}/api/super-admin/companies/{cid}",
                            headers=sa_h, timeout=10)
        print(f"  Company {slug}: {'deleted' if r.status_code == 200 else 'could not delete – ok'}")

    # ── Final report ───────────────────────────────────────────────────────────
    print("\n=== ISOLATION TEST RESULTS ===")
    all_pass = True
    for name, result in _results:
        icon = "✓" if result == "PASS" else "✗"
        print(f"  {icon} {name}: {result}")
        if result != "PASS":
            all_pass = False

    verdict = "ALL TESTS PASSED" if all_pass else "FAILURES FOUND — FIX BEFORE PHASE 3"
    print(f"\n{verdict}")
    return all_pass


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)

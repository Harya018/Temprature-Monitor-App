"""
backend/tests/test_tier_and_escalation.py
==========================================
Tests for tier limit enforcement and escalation rule evaluation.

Run (server must be running on http://localhost:5000):
    cd C:\\Users\\harya\\OneDrive\\Desktop\\Sensor\\sentineledge
    set PYTHONPATH=%CD%;%CD%\\backend
    python backend/tests/test_tier_and_escalation.py

Tests:
  Tier limits:
    1. check_subscriber_limit raises 403 when company is at max_subscribers
    2. check_sms_quota raises 429 when monthly_sms_quota is exhausted
    3. Adding subscriber via API → 403 when at limit

  Escalation:
    4. create_escalation_rule(log_only, threshold_minutes=0)
    5. POST /api/escalation/evaluate fires rule against unacknowledged alert
    6. Escalation log entry created in DB
"""

from __future__ import annotations

import sys
import secrets
import time
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
    from utils.tier_enforcer import check_subscriber_limit, check_sms_quota
    DB_AVAILABLE = True
except Exception as _e:
    DB_AVAILABLE = False
    print(f"[WARN] DB layer unavailable: {_e}")


def _ok(label: str) -> None:
    _results.append((label, True, ""))
    print(f"  {PASS}  {label}")


def _fail(label: str, reason: str) -> None:
    _results.append((label, False, reason))
    print(f"  {FAIL}  {label}")
    print(f"       Reason: {reason}")


def _get_super_token() -> str | None:
    if not DB_AVAILABLE:
        return None
    rows = execute_read(
        """
        SELECT s.token FROM admin_sessions s
        JOIN admins a ON a.id = s.admin_id
        WHERE s.expires_at > NOW() AND a.role = 'super_admin'
        ORDER BY s.expires_at DESC LIMIT 1
        """,
        [],
    )
    return rows[0]["token"] if rows else None


def _get_admin_token(company_id: int) -> str | None:
    if not DB_AVAILABLE:
        return None
    rows = execute_read(
        """
        SELECT s.token FROM admin_sessions s
        JOIN admins a ON a.id = s.admin_id
        WHERE s.expires_at > NOW() AND a.is_active = 1
          AND a.company_id = %s AND a.role != 'super_admin'
        ORDER BY s.expires_at DESC LIMIT 1
        """,
        (company_id,),
    )
    return rows[0]["token"] if rows else None


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def run_tests() -> None:
    print()
    print("=" * 60)
    print("  Tier Limit & Escalation Test")
    print("=" * 60)

    if not DB_AVAILABLE:
        print("[ERROR] Database layer unavailable.")
        sys.exit(1)

    suffix = secrets.token_hex(4)

    # ── Setup: create a tier with limit=1 ────────────────────────────────────
    print("\n  [Setup] Creating test tier, company, subscriber...")
    tier_rows = execute_write(
        """
        INSERT INTO subscription_tiers (name, max_subscribers, monthly_sms_quota, monthly_email_quota,
                                        max_devices, max_parameters, allowed_channels, price_inr)
        VALUES (%s, 1, 0, 0, 1, 5, 'email', 0)
        RETURNING id
        """,
        (f"TestTier_{suffix}",),
    )
    tier_id = tier_rows[0]["id"]

    import bcrypt
    pw_hash = bcrypt.hashpw(b"TestPass1!", bcrypt.gensalt()).decode()

    co_rows = execute_write(
        "INSERT INTO companies (name, slug, is_active, tier_id, sms_used_this_month) VALUES (%s, %s, 1, %s, 0) RETURNING id",
        (f"TierTestCo_{suffix}", f"tiertestco-{suffix}", tier_id),
    )
    cid = co_rows[0]["id"]

    adm_rows = execute_write(
        """
        INSERT INTO admins (name, username, password_hash, role, company_id, is_active)
        VALUES (%s, %s, %s, 'admin', %s, 1) RETURNING id
        """,
        (f"tier_admin_{suffix}", f"tier_admin_{suffix}", pw_hash, cid),
    )
    adm_id = adm_rows[0]["id"]

    from datetime import datetime, timezone, timedelta
    tok = secrets.token_hex(32)
    execute_write(
        "INSERT INTO admin_sessions (token, expires_at, admin_id) VALUES (%s, %s, %s)",
        (tok, datetime.now(timezone.utc) + timedelta(hours=1), adm_id),
    )

    # Add exactly 1 subscriber (at the limit)
    execute_write(
        "INSERT INTO subscribers (name, company_id, is_active) VALUES (%s, %s, 1)",
        (f"sub_limit_{suffix}", cid),
    )

    try:
        # ── Test 1: check_subscriber_limit raises 403 ─────────────────────────
        print("\n  [Tier — subscriber limit]")
        try:
            from fastapi import HTTPException
            try:
                check_subscriber_limit(cid)
                _fail("check_subscriber_limit raises 403", "No exception raised at limit")
            except HTTPException as e:
                if e.status_code == 403:
                    _ok("check_subscriber_limit raises HTTP 403 when at max_subscribers=1")
                else:
                    _fail("check_subscriber_limit HTTP 403", f"Got status {e.status_code}")
        except Exception as e:
            _fail("check_subscriber_limit", str(e))

        # ── Test 2: check_sms_quota raises 429 when quota=0 ──────────────────
        print("\n  [Tier — SMS quota]")
        # Set sms_used_this_month = 0, monthly_sms_quota = 0 → quota exhausted
        try:
            from fastapi import HTTPException
            try:
                check_sms_quota(cid)
                _fail("check_sms_quota raises 429", "No exception raised when quota=0")
            except HTTPException as e:
                if e.status_code == 429:
                    _ok("check_sms_quota raises HTTP 429 when monthly_sms_quota=0")
                else:
                    _fail("check_sms_quota HTTP 429", f"Got status {e.status_code}")
            except Exception as e:
                _fail("check_sms_quota", str(e))
        except Exception as e:
            _fail("check_sms_quota import", str(e))

        # ── Test 3: API → 403 when adding subscriber at limit ────────────────
        print("\n  [API tier enforcement]")
        r = requests.post(
            f"{BASE_URL}/api/subscribers",
            json={"name": f"overquota_{suffix}", "email": "test@example.com"},
            headers=_headers(tok),
            timeout=10,
        )
        if r.status_code == 403:
            _ok("POST /api/subscribers → 403 when at subscriber limit")
        elif r.status_code == 200:
            # Clean up the accidentally created subscriber
            subs = execute_read(
                "SELECT id FROM subscribers WHERE name = %s", (f"overquota_{suffix}",)
            )
            for s in subs:
                execute_write("DELETE FROM subscribers WHERE id = %s", (s["id"],))
            _fail("POST /api/subscribers tier enforcement", f"Expected 403, got 200 — subscriber was created!")
        else:
            _fail("POST /api/subscribers", f"HTTP {r.status_code}: {r.text[:100]}")

        # ── Escalation tests ─────────────────────────────────────────────────
        print("\n  [Escalation — rule evaluation]")

        # Check if escalation_rules table exists
        try:
            rule_rows = execute_write(
                """
                INSERT INTO escalation_rules
                    (name, company_id, severity_filter, threshold_minutes, action_type, action_target, is_active)
                VALUES (%s, %s, 'HIGH', 0, 'log_only', 'log', TRUE)
                RETURNING id
                """,
                (f"test_rule_{suffix}", cid),
            )
            rule_id = rule_rows[0]["id"] if rule_rows else None

            if rule_id:
                _ok(f"Escalation rule created with id={rule_id}")

                # Create an unacknowledged HIGH alert for this company
                alert_rows = execute_write(
                    """
                    INSERT INTO alerts
                        (parameter, value, threshold, direction, severity, timestamp,
                         acknowledged, escalation_level, max_escalated, cooldown_until, company_id)
                    VALUES (%s, %s, %s, %s, %s, %s, 0, 1, 0, %s, %s)
                    RETURNING id
                    """,
                    (
                        "temperature", 95.0, 80.0, "above", "HIGH",
                        (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                        (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                        cid,
                    ),
                )
                alert_id = alert_rows[0]["id"] if alert_rows else None

                if alert_id:
                    _ok(f"Unacknowledged HIGH alert created id={alert_id}")

                    # Trigger escalation evaluation via API
                    r_esc = requests.post(
                        f"{BASE_URL}/api/escalation/evaluate",
                        headers=_headers(tok),
                        timeout=15,
                    )
                    if r_esc.status_code in (200, 204):
                        _ok(f"POST /api/escalation/evaluate → {r_esc.status_code}")

                        # Check escalation log
                        time.sleep(1)
                        log_rows = execute_read(
                            """
                            SELECT id FROM escalation_log
                            WHERE rule_id = %s AND alert_id = %s
                            LIMIT 1
                            """,
                            (rule_id, alert_id),
                        )
                        if log_rows:
                            _ok("Escalation log entry created after evaluation")
                        else:
                            _fail("Escalation log entry", "No log entry found after evaluation")
                    else:
                        _fail(
                            "POST /api/escalation/evaluate",
                            f"HTTP {r_esc.status_code}: {r_esc.text[:100]}",
                        )

                    # Cleanup alert
                    execute_write("DELETE FROM alerts WHERE id = %s", (alert_id,))
                else:
                    _fail("Escalation test alert", "Could not insert alert")

                # Cleanup rule
                execute_write("DELETE FROM escalation_rules WHERE id = %s", (rule_id,))
            else:
                _fail("Escalation rule creation", "INSERT returned no id")

        except Exception as exc:
            _fail("Escalation test", str(exc))

    finally:
        # ── Teardown ─────────────────────────────────────────────────────────
        print("\n  [Teardown] Cleaning up...")
        execute_write("DELETE FROM admin_sessions WHERE admin_id = %s", (adm_id,))
        execute_write("DELETE FROM subscribers WHERE company_id = %s", (cid,))
        execute_write("DELETE FROM admins WHERE id = %s", (adm_id,))
        execute_write("DELETE FROM companies WHERE id = %s", (cid,))
        execute_write("DELETE FROM subscription_tiers WHERE id = %s", (tier_id,))
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
        for label, ok, reason in _results:
            if not ok:
                print(f"    {FAIL} {label}: {reason}")
    else:
        print()
        print("  All tier and escalation tests PASSED.")
    print("=" * 60)
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    run_tests()

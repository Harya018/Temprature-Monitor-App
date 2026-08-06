"""
utils/rate_limiter.py — Login rate limiting for SentinelEdge.

Uses the existing login_attempts table (created by Migration 29a).
No new packages — pure execute_read / execute_write from database.connection.

Public API
----------
check_rate_limit(username, ip)          → raises HTTP 429 if locked out
record_attempt(username, ip, success)   → records one attempt row
clear_failed_attempts(username, ip)     → deletes failed rows on good login
remaining_attempts(username, ip)        → int — attempts left before lockout
"""

from fastapi import HTTPException

MAX_ATTEMPTS: int = 5
LOCKOUT_MINUTES: int = 15

# Hardcoded interval string — safe because LOCKOUT_MINUTES is an internal constant.
_WINDOW = f"INTERVAL '{LOCKOUT_MINUTES} minutes'"


def _failed_count(username: str, ip: str) -> int:
    """Return the number of failed attempts in the lockout window."""
    from database.connection import execute_read
    rows = execute_read(
        f"""
        SELECT COUNT(*) AS cnt
          FROM login_attempts
         WHERE username = %s
           AND ip = %s
           AND success = 0
           AND attempted_at > NOW() - {_WINDOW}
        """,
        (username, ip),
    )
    return rows[0]["cnt"] if rows else 0


def check_rate_limit(username: str, ip: str) -> None:
    """
    Call at the START of any login route, before credential checks.
    Raises HTTP 429 if the account+IP has hit MAX_ATTEMPTS failures
    within the last LOCKOUT_MINUTES minutes.
    """
    if _failed_count(username, ip) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many failed login attempts. "
                f"Try again in {LOCKOUT_MINUTES} minutes."
            ),
        )


def record_attempt(username: str, ip: str, success: bool) -> None:
    """
    Call at the END of a login route after success/failure is determined.
    Swallowed silently — a logging failure must never break the login flow.
    """
    try:
        from database.connection import execute_write
        execute_write(
            "INSERT INTO login_attempts (username, ip, success) VALUES (%s, %s, %s)",
            (username, ip, 1 if success else 0),
        )
    except Exception:
        pass


def clear_failed_attempts(username: str, ip: str) -> None:
    """
    Call on successful login to clear prior failed rows.
    Prevents a user from being locked out after a legitimate recovery.
    Swallowed silently.
    """
    try:
        from database.connection import execute_write
        execute_write(
            "DELETE FROM login_attempts WHERE username = %s AND ip = %s AND success = 0",
            (username, ip),
        )
    except Exception:
        pass


def remaining_attempts(username: str, ip: str) -> int:
    """
    Return how many more failures are allowed before lockout.
    Safe to call at any time; returns MAX_ATTEMPTS on any error.
    """
    try:
        return max(0, MAX_ATTEMPTS - _failed_count(username, ip))
    except Exception:
        return MAX_ATTEMPTS

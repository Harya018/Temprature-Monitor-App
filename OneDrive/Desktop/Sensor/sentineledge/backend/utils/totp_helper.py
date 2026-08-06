"""
utils/totp_helper.py — TOTP (Time-based One-Time Password) helpers for 2FA.

Uses pyotp (RFC 6238 / Google Authenticator compatible).

Public API:
    generate_secret()                    → base32 secret string
    get_qr_uri(secret, admin_name)       → otpauth:// URI for QR code rendering
    verify_code(secret, code)            → True / False
    is_2fa_enabled(admin_id)             → bool  (secret row exists AND enabled=1)
    is_2fa_enforced(admin_id)            → bool  (enforced=1 on any company admin)
    get_or_create_secret(admin_id)       → (secret_str, already_existed: bool)
    mark_enabled(admin_id)               → None
    disable_2fa(admin_id)               → None
"""

from __future__ import annotations

import pyotp
from database.connection import execute_read, execute_write
from utils.logger import get_logger

logger = get_logger(__name__)

_ISSUER = "SentinelEdge"
_WINDOW = 1  # allow ±30 s drift (one token either side)


def generate_secret() -> str:
    """Return a fresh random base32 TOTP secret."""
    return pyotp.random_base32()


def get_qr_uri(secret: str, admin_name: str, issuer: str = _ISSUER) -> str:
    """Return the otpauth:// URI that encodes the QR code for an authenticator app."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=admin_name, issuer_name=issuer)


def verify_code(secret: str, code: str) -> bool:
    """Return True if the 6-digit TOTP code is valid (±1 window)."""
    if not secret or not code:
        return False
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(str(code).strip(), valid_window=_WINDOW)
    except Exception as exc:
        logger.warning("TOTP verify error: %s", exc)
        return False


def is_2fa_enabled(admin_id: int) -> bool:
    """Return True if this admin has 2FA set up and enabled."""
    rows = execute_read(
        "SELECT enabled FROM totp_secrets WHERE admin_id = %s",
        (admin_id,),
    )
    return bool(rows and rows[0]["enabled"])


def is_2fa_enforced(admin_id: int) -> bool:
    """Return True if the enforced flag is set for this admin's totp_secrets row."""
    rows = execute_read(
        "SELECT enforced FROM totp_secrets WHERE admin_id = %s",
        (admin_id,),
    )
    return bool(rows and rows[0]["enforced"])


def get_or_create_secret(admin_id: int) -> tuple[str, bool]:
    """
    Return the existing secret for admin_id, or generate and store a new one.
    Returns (secret, already_existed).
    The returned secret is always with enabled=0 until mark_enabled() is called.
    """
    rows = execute_read(
        "SELECT secret FROM totp_secrets WHERE admin_id = %s",
        (admin_id,),
    )
    if rows:
        return rows[0]["secret"], True

    secret = generate_secret()
    execute_write(
        "INSERT INTO totp_secrets (admin_id, secret, enabled, enforced) VALUES (%s, %s, 0, 0)",
        (admin_id, secret),
    )
    return secret, False


def mark_enabled(admin_id: int) -> None:
    """Mark 2FA as enabled after the user has verified their first code."""
    execute_write(
        "UPDATE totp_secrets SET enabled = 1 WHERE admin_id = %s",
        (admin_id,),
    )


def disable_2fa(admin_id: int) -> None:
    """Remove the TOTP secret entirely, effectively disabling 2FA."""
    execute_write(
        "DELETE FROM totp_secrets WHERE admin_id = %s",
        (admin_id,),
    )


def set_enforced(admin_id: int, enforced: bool) -> None:
    """Set the enforced flag on an existing totp_secrets row (creates row if missing)."""
    rows = execute_read(
        "SELECT admin_id FROM totp_secrets WHERE admin_id = %s", (admin_id,)
    )
    if rows:
        execute_write(
            "UPDATE totp_secrets SET enforced = %s WHERE admin_id = %s",
            (1 if enforced else 0, admin_id),
        )
    else:
        secret = generate_secret()
        execute_write(
            "INSERT INTO totp_secrets (admin_id, secret, enabled, enforced) VALUES (%s, %s, 0, %s)",
            (admin_id, secret, 1 if enforced else 0),
        )

"""
routers/auth.py — Mobile app authentication endpoints.

Provides name + PIN login for subscribers.
Tokens are stored in-memory; cleared on server restart.
Clients (React Native) store the token in AsyncStorage and re-login on restart.

Endpoints
---------
POST /api/auth/login    — public; returns a 64-char hex token (30-day TTL)
                          Rate limited: 10/minute per IP (brute-force protection)
POST /api/auth/logout   — requires X-Auth-Token header
GET  /api/auth/me       — requires X-Auth-Token header
POST /api/auth/admin-login  — sub-admin/admin dashboard login (uses DB sessions)
GET  /api/auth/admin-me     — returns current admin session info
"""



import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

import database
from models import LoginIn, LoginOut
from middleware.rate_limit import limiter
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# ── In-memory subscriber token store ─────────────────────────────────────────
# Key: token (64-char hex string)
# Value: {"subscriber_id": int, "name": str, "escalation_order": int,
#         "expires_at": datetime}
#
# Cleared on every server restart — clients must re-login.
active_tokens: dict[str, dict[str, Any]] = {}

_TOKEN_TTL_DAYS = 30


def _get_valid_token(x_auth_token: str | None) -> dict[str, Any]:
    """Validate a token header and return its payload, or raise HTTP 401."""
    if not x_auth_token or x_auth_token not in active_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "InvalidToken", "message": "Missing or invalid X-Auth-Token"},
        )
    payload = active_tokens[x_auth_token]
    if datetime.now(timezone.utc) > payload["expires_at"]:
        del active_tokens[x_auth_token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "TokenExpired", "message": "Token has expired — please log in again"},
        )
    return payload


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=LoginOut,
    summary="Subscriber login",
    description="Authenticate with name + PIN. Returns a 30-day bearer token. Rate limited: 10/min.",
)
@limiter.limit("10/minute")
async def login(body: LoginIn, request: Request) -> LoginOut:
    client_ip = request.client.host if request.client else "unknown"
    logger.info(f"Login attempt — name: {body.name}, ip: {client_ip}")

    subscriber = database.get_subscriber_by_name_and_pin(body.name, body.pin)
    if subscriber is None:
        logger.warning("Failed login attempt for name=%r", body.name)
        logger.warning(
            f"Login FAILED — name: {body.name}, ip: {client_ip}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "InvalidCredentials", "message": "Name or PIN is incorrect"},
        )

    token = secrets.token_hex(32)          # 64-char hex string
    expires_at = datetime.now(timezone.utc) + timedelta(days=_TOKEN_TTL_DAYS)
    active_tokens[token] = {
        "subscriber_id":    subscriber["id"],
        "name":             subscriber["name"],
        "escalation_order": subscriber["escalation_order"],
        "expires_at":       expires_at,
    }
    logger.info("Login successful for subscriber id=%d name=%r", subscriber["id"], subscriber["name"])
    logger.info(
        f"Login SUCCESS — name: {body.name}, "
        f"ip: {client_ip}, "
        f"time: {datetime.utcnow().isoformat()}"
    )
    return LoginOut(
        token=token,
        subscriber_id=subscriber["id"],
        name=subscriber["name"],
        escalation_order=subscriber["escalation_order"],
    )


@router.post(
    "/logout",
    summary="Subscriber logout",
    description="Invalidates the supplied token. Requires X-Auth-Token header.",
)
async def logout(x_auth_token: str = Header(default=None)):
    _get_valid_token(x_auth_token)   # raises 401 if bad
    del active_tokens[x_auth_token]
    logger.info("Token invalidated (logout)")
    return {"message": "Logged out"}


@router.get(
    "/me",
    summary="Current subscriber",
    description="Returns the subscriber details for the current token.",
)
async def me(x_auth_token: str = Header(default=None)):
    payload = _get_valid_token(x_auth_token)
    return {
        "subscriber_id":    payload["subscriber_id"],
        "name":             payload["name"],
        "escalation_order": payload["escalation_order"],
        "expires_at":       payload["expires_at"].isoformat(),
    }


# ── Sub-admin session login (DB-backed) ───────────────────────────────────────
# Sub-admins log in with name+password (stored in the admins table).
# Sessions are stored in admin_sessions PostgreSQL table and survive restarts.
# Session TTL: 8 hours.

class _AdminLoginIn(BaseModel):
    name:       str = Field(min_length=1, max_length=50)
    password:   str = Field(min_length=1, max_length=200)
    totp_code:  str | None = None          # 6-digit TOTP; required when 2FA is enabled

    @field_validator("name", "password", mode="before")
    @classmethod
    def strip_fields(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


@router.post(
    "/admin-login",
    summary="Sub-admin / Admin dashboard login",
    description=(
        "Authenticate a dashboard user (main admin or sub-admin) with "
        "name + password. Returns role so the client can route to the "
        "correct dashboard. Session TTL: 8 hours. Session persists across restarts. "
        "Rate limited: 10/minute per IP."
    ),
)
@limiter.limit("10/minute")
async def admin_login(body: _AdminLoginIn, request: Request):
    """Login for the admin dashboard (main or sub-admin)."""
    admin = database.verify_admin_password(body.name, body.password)
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "InvalidCredentials", "message": "Name or password is incorrect"},
        )

    # ── TOTP 2FA check ────────────────────────────────────────────────────────
    try:
        from utils.totp_helper import is_2fa_enabled, verify_code
        from database.connection import execute_read as _er
        _totp_row = _er(
            "SELECT secret, enabled, enforced FROM totp_secrets WHERE admin_id = %s",
            (admin["id"],),
        )
        _2fa_enabled  = bool(_totp_row and _totp_row[0]["enabled"])
        _2fa_enforced = bool(_totp_row and _totp_row[0]["enforced"])

        if _2fa_enabled:
            if not body.totp_code:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error":       "TotpRequired",
                        "requires_2fa": True,
                        "message":     "Enter your 6-digit authenticator code",
                    },
                )
            if not verify_code(_totp_row[0]["secret"], body.totp_code):
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error":       "TotpInvalid",
                        "requires_2fa": True,
                        "message":     "Invalid or expired TOTP code",
                    },
                )
    except HTTPException:
        raise
    except Exception as _totp_exc:
        logger.warning("TOTP check failed (non-fatal): %s", _totp_exc)

    token = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)

    # Persist session in PostgreSQL
    database.create_session(token, expires_at)

    logger.info("Admin login: name=%r role=%s", admin["name"], admin["role"])

    # Audit log — record successful login with IP
    try:
        from utils.audit_logger import audit
        _ip = request.client.host if request.client else "unknown"
        audit(
            action="login_success",
            category="auth",
            admin_id=admin["id"],
            company_id=admin.get("company_id"),
            ip_address=_ip,
            severity="info",
        )
    except Exception:
        pass

    return {
        "token":    token,
        "admin_id": admin["id"],
        "name":     admin["name"],
        "role":     admin["role"],
        "message":  "Login successful",
    }


@router.get(
    "/admin-me",
    summary="Current admin session info",
    description="Returns session info for the given admin token (X-Admin-Token header).",
)
async def admin_me(x_admin_token: str = Header(default=None)):
    """Return the current sub-admin session info."""
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Missing X-Admin-Token")

    session = database.get_session(x_admin_token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired X-Admin-Token")

    return {
        "token":       x_admin_token,
        "created_at":  session["created_at"].isoformat() if session.get("created_at") else None,
        "expires_at":  session["expires_at"].isoformat() if session.get("expires_at") else None,
        "last_used_at": session["last_used_at"].isoformat() if session.get("last_used_at") else None,
    }


# ── TOTP 2FA routes ───────────────────────────────────────────────────────────
# All require a valid Bearer session (X-Admin-Token header mapped via Depends).
# Super admin uses these for own setup; enforce route targets company admin IDs.

def _require_bearer(authorization: str | None = Header(default=None)) -> dict:
    """Resolve admin row from Authorization: Bearer <token>. Returns admins dict or raises 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token> header")
    token = authorization[7:].strip()
    from database.connection import execute_read
    rows = execute_read(
        """SELECT a.id, a.name, a.role, a.company_id
             FROM admins a
             JOIN admin_sessions s ON s.token = %s
            WHERE s.expires_at > NOW()
            LIMIT 1""",
        (token,),
    )
    if not rows:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return rows[0]


class _TotpVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class _TotpEnforceIn(BaseModel):
    admin_id: int
    enforced: bool = True


@router.get(
    "/admin/2fa/setup",
    summary="Get or create TOTP secret for the current admin",
    description=(
        "Returns a new (or existing pending) TOTP secret + QR URI. "
        "Call this to display a setup QR code. Does NOT enable 2FA — "
        "caller must POST /2fa/verify with a valid code to activate."
    ),
)
async def totp_setup(admin: dict = Depends(_require_bearer)):
    from utils.totp_helper import get_or_create_secret, get_qr_uri, is_2fa_enabled
    secret, existed = get_or_create_secret(admin["id"])
    uri = get_qr_uri(secret, admin["name"])
    return {
        "secret":    secret,
        "qr_uri":    uri,
        "enabled":   is_2fa_enabled(admin["id"]),
        "existed":   existed,
    }


@router.post(
    "/admin/2fa/verify",
    summary="Verify TOTP code and activate 2FA for the current admin",
    description="Verifies the 6-digit code against the pending secret. On success, marks 2FA enabled.",
)
async def totp_verify(body: _TotpVerifyIn, admin: dict = Depends(_require_bearer)):
    from utils.totp_helper import get_or_create_secret, verify_code, mark_enabled, is_2fa_enabled
    from utils.audit_logger import audit

    if is_2fa_enabled(admin["id"]):
        return {"ok": True, "message": "2FA already active"}

    secret, _ = get_or_create_secret(admin["id"])
    if not verify_code(secret, body.code):
        audit(action="2fa_verify_failed", category="security",
              admin_id=admin["id"], severity="warning")
        raise HTTPException(status_code=401, detail="Invalid TOTP code — check your authenticator app")

    mark_enabled(admin["id"])
    audit(action="2fa_enabled", category="security",
          admin_id=admin["id"], company_id=admin.get("company_id"), severity="info")
    return {"ok": True, "message": "2FA activated successfully"}


@router.post(
    "/admin/2fa/disable",
    summary="Disable 2FA for a given admin (super admin only)",
    description="Removes the TOTP secret for the target admin_id. Super admin only.",
)
async def totp_disable(body: _TotpEnforceIn, admin: dict = Depends(_require_bearer)):
    from utils.totp_helper import disable_2fa
    from utils.audit_logger import audit

    if admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin only")

    disable_2fa(body.admin_id)
    audit(action="2fa_disabled", category="security",
          admin_id=admin["id"], entity_type="admin", entity_id=body.admin_id,
          severity="warning")
    return {"ok": True, "admin_id": body.admin_id, "message": "2FA disabled"}


@router.post(
    "/admin/2fa/enforce",
    summary="Enforce 2FA for a company admin (super admin only)",
    description=(
        "Sets enforced=1 on the target admin's totp_secrets row. "
        "If the admin hasn't set up their secret yet, one is generated for them. "
        "Their next login will prompt for TOTP setup."
    ),
)
async def totp_enforce(body: _TotpEnforceIn, admin: dict = Depends(_require_bearer)):
    from utils.totp_helper import set_enforced, get_or_create_secret
    from utils.audit_logger import audit

    if admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin only")

    # Ensure a secret row exists before setting enforced
    get_or_create_secret(body.admin_id)
    set_enforced(body.admin_id, body.enforced)
    action = "2fa_enforced" if body.enforced else "2fa_unenforced"
    audit(action=action, category="security",
          admin_id=admin["id"], entity_type="admin", entity_id=body.admin_id,
          severity="warning" if body.enforced else "info")
    return {"ok": True, "admin_id": body.admin_id, "enforced": body.enforced}


@router.get(
    "/admin/2fa/status",
    summary="Get 2FA status for the current admin",
)
async def totp_status(admin: dict = Depends(_require_bearer)):
    from utils.totp_helper import is_2fa_enabled, is_2fa_enforced
    return {
        "admin_id": admin["id"],
        "enabled":  is_2fa_enabled(admin["id"]),
        "enforced": is_2fa_enforced(admin["id"]),
    }

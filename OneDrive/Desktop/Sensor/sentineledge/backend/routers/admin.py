"""
routers/admin.py — Admin-only endpoints.

Tags: Admin
All endpoints require X-Admin-Password header or Bearer session token.

Changes in this version:
  - POST /api/admin/login uses database.create_session() (PostgreSQL-backed)
  - _login_sessions in-memory dict removed entirely
  - Session TTL: 8 hours (not 24)
  - POST /api/admin/login rate limited to 10/minute (brute-force protection)
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional

import database
import config as _cfg
from middleware.auth import require_admin, require_platform_admin
from middleware.rate_limit import limiter
from models import ConfigChangeOut
from database.backup import create_backup, get_backup_list
from database.retention import get_database_stats
from modules.email.smtp import send_alert_email
from utils.logger import get_logger
from utils.time import now_iso
from utils.activity_logger import log_activity
from utils.rate_limiter import check_rate_limit, record_attempt, clear_failed_attempts, remaining_attempts

logger = get_logger(__name__)

from services.sensor_company import require_plant_owner, require_feed_admin
router = APIRouter(prefix="/api", tags=["Admin"])


# ─── Acknowledgement Log ──────────────────────────────────────────────────────

@router.get(
    "/ack-log",
    summary="Acknowledgement log",
    description=(
        "Returns acknowledged alerts with who acknowledged, when, and "
        "response_time_seconds (time between alert firing and acknowledgement). "
        "Requires admin auth."
    ),
)
async def get_ack_log(limit: int = 100, admin: dict = Depends(require_admin)):
    """Return the acknowledgement log with response time in seconds (caller's company)."""
    try:
        rows = database.get_ack_log(limit=limit, company_id=admin.get("company_id"))
        return rows
    except Exception as exc:
        logger.error("get_ack_log failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to fetch ack log", "detail": str(exc)},
        )


class _VerifyIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)

    @field_validator("password", mode="before")
    @classmethod
    def strip_password(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


@router.post(
    "/admin/verify-password",
    summary="Verify admin password",
    description="Checks whether the supplied password is the signed-in admin's OWN password "
                "(used to re-confirm sensitive actions). Requires a valid admin session token.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def verify_password(body: _VerifyIn, request: Request):
    """Used by the frontend admin modal to re-confirm the password for sensitive actions."""
    me = _me_or_401(request)
    return {"valid": _own_password_ok(me, body.password)}


def _me_or_401(request: Request) -> dict:
    from middleware.auth import session_admin
    me = session_admin(request.headers.get("authorization"))
    if not me:
        raise HTTPException(status_code=401, detail="Please sign in again")
    return me


def _is_builtin_login(me: dict) -> bool:
    """The account behind this PC's built-in dashboard login (ADMIN_USERNAME / ADMIN_PASSWORD in the
    settings file) — its password lives in that file as well as in the database."""
    return bool(_cfg.ADMIN_PASSWORD) and str(me.get("account_name") or "").lower() == \
        str(getattr(_cfg, "ADMIN_USERNAME", "admin")).lower() and me.get("role") != "super_admin"


def _own_password_ok(me: dict, password: str) -> bool:
    from utils.security import verify_pin
    from database.connection import execute_read
    rows = execute_read("SELECT password_hash FROM admins WHERE id = %s", (me["id"],))
    if rows and verify_pin(password, rows[0]["password_hash"]):
        return True
    return _is_builtin_login(me) and verify_pin(password, _cfg.ADMIN_PASSWORD)


def _change_own_password(me: dict, current: str, new: str):
    """Shared by PATCH /admin/profile and POST /admin/change-password. Returns a JSONResponse on error,
    else None. Only THIS admin's other sign-ins are ended (never another admin's or company's)."""
    from utils.security import hash_pin
    from database.connection import execute_write
    import config as _c
    if _c.SERVER_ROLE == "node":
        return JSONResponse(status_code=409, content={
            "error": "Passwords of this company server are managed on the main server. Ask the Super Admin to change it."})
    if me.get("role") == "super_admin":
        return JSONResponse(status_code=409, content={"error": "Super Admin changes the password in Super Admin -> Config."})
    if not _own_password_ok(me, current):
        return JSONResponse(status_code=401, content={"error": "Current password is incorrect"})
    new = (new or "").strip()
    try:   # the same rule Super Admin has to follow when giving an admin a password
        from routers.super_admin_v2 import _enforce_password_strength
        _enforce_password_strength(new)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": f"{exc} (10+ characters with a capital, a small letter, a number and a symbol)"})
    if new == current:
        return JSONResponse(status_code=422, content={"error": "The new password must be different from the current one"})
    hashed = hash_pin(new)
    execute_write("UPDATE admins SET password_hash = %s WHERE id = %s", (hashed, me["id"]))
    if _is_builtin_login(me):            # keep the settings-file login in step with the account
        try:
            from services.env_file import set_values
            set_values({"ADMIN_PASSWORD": hashed})
            _c.ADMIN_PASSWORD = hashed
        except Exception as exc:
            logger.warning("change password: could not update the settings file: %s", exc)
    execute_write("DELETE FROM admin_sessions WHERE admin_id = %s AND token <> %s", (me["id"], me["token"]))
    log_activity(me["id"], "change_own_password", "admin", f"name:{me['name']}", me.get("company_id"))
    try:
        from services import company_log as _clog
        _clog.log(me.get("company_id"), f"{me['name']} changed their password")
    except Exception:
        pass
    return None      # company servers receive the new password with the next sync


# ─── Admin Profile (GET + PATCH username/PIN) ─────────────────────────────────

class _ProfileUpdateIn(BaseModel):
    current_pin: str = Field(min_length=1, max_length=200)
    new_username: Optional[str] = Field(default=None, max_length=50)
    new_pin:      Optional[str] = Field(default=None, max_length=200)

    @field_validator("current_pin", "new_pin", mode="before")
    @classmethod
    def strip_pin_fields(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @field_validator("new_username", mode="before")
    @classmethod
    def strip_new_username(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v


@router.get(
    "/admin/profile",
    summary="Get admin profile",
    description="The signed-in admin's own name, role and company. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
async def get_admin_profile(request: Request):
    """Return the current admin's public profile (password never returned)."""
    from database.connection import execute_read
    me = _me_or_401(request)
    co = execute_read("SELECT name FROM companies WHERE id = %s", (me.get("company_id"),)) if me.get("company_id") else []
    last = execute_read("SELECT last_login_at::TEXT AS t FROM admins WHERE id = %s", (me["id"],))
    import config as _c
    return {"username": me["name"], "role": me.get("role"), "company_id": me.get("company_id"),
            "company_name": co[0]["name"] if co else None, "last_login_at": last[0]["t"] if last else None,
            "can_change_password": me.get("role") in ("main", "sub") and _c.SERVER_ROLE != "node"}


@router.patch(
    "/admin/profile",
    summary="Change my password",
    description="Change the signed-in admin's OWN password (current password required). "
                "Your other sign-ins end; other admins are not affected. Names are changed by Super Admin.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def update_admin_profile(body: _ProfileUpdateIn, request: Request):
    me = _me_or_401(request)
    if body.new_username and body.new_username.strip() and body.new_username.strip() != me["name"]:
        return JSONResponse(status_code=422, content={"detail": "Your sign-in name is set by the Super Admin. Ask them to change it."})
    if not (body.new_pin and body.new_pin.strip()):
        return JSONResponse(status_code=422, content={"detail": "Enter a new password"})
    err = _change_own_password(me, body.current_pin, body.new_pin)
    if err is not None:
        import json as _json
        e = _json.loads(err.body)
        return JSONResponse(status_code=err.status_code, content={"detail": e.get("error"), **e})
    return {"message": "Password changed. Your other sign-ins were ended."}


# ─── Username + PIN Login (DB-backed sessions) ────────────────────────────────

class _AdminLoginIn(BaseModel):
    username:  str = Field(min_length=1, max_length=50)
    # PIN for the platform admin, or the password Super Admin set for a company admin
    pin:       str = Field(min_length=4, max_length=200)
    totp_code: str | None = None          # 6-digit TOTP; required when 2FA is enforced

    @field_validator("username", "pin", mode="before")
    @classmethod
    def strip_fields(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


@router.post(
    "/admin/login",
    summary="Admin dashboard login",
    description=(
        "Login to the admin dashboard with username + PIN. "
        "Returns a Bearer token valid for 8 hours. "
        "Sessions are stored in PostgreSQL and survive server restarts. "
        "Rate limited: 10/minute per IP."
    ),
)
@limiter.limit("10/minute")
async def admin_login(body: _AdminLoginIn, request: Request):
    """Validate username + PIN and issue a DB-backed Bearer token (8h TTL)."""
    import secrets
    from datetime import datetime, timezone, timedelta
    import config as _cfg

    username = body.username.strip().lower()
    pin      = body.pin.strip()
    ip       = request.client.host if request.client else "unknown"

    check_rate_limit(username, ip)  # Task 1: raise 429 if account+IP is locked

    # Validate against runtime ADMIN_USERNAME and ADMIN_PASSWORD
    from utils.security import verify_pin
    stored_username = getattr(_cfg, "ADMIN_USERNAME", "admin").lower()
    # The plain dashboard login only exists where ADMIN_PASSWORD is configured (the original
    # plant PC). On a new company PC admins are created in Super Admin instead.
    valid = bool(_cfg.ADMIN_PASSWORD) and username == stored_username and verify_pin(pin, _cfg.ADMIN_PASSWORD)

    # Otherwise: a company's main admin (created by Super Admin) signs in with
    # the name + password Super Admin configured, and sees only their company.
    company_admin = None
    if not valid:
        cand = database.verify_admin_password(body.username.strip(), pin)
        if (cand and cand.get("role") in ("main", "sub") and cand.get("company_id")
                and cand.get("is_active") != 0):
            from database.connection import execute_read as _erc
            co = _erc("SELECT COALESCE(is_active, 1) AS active FROM companies WHERE id = %s",
                      (cand["company_id"],))
            if co and co[0]["active"] != 0:
                company_admin, valid = cand, True

    if not valid:
        record_attempt(username, ip, False)  # Task 1: log failed attempt
        try:
            from utils.audit_logger import audit
            audit(action="login_failed", category="auth", ip_address=ip, severity="warning")
        except Exception:
            pass
        return JSONResponse(
            status_code=401,
            content={
                "error": "InvalidCredentials",
                "message": "Invalid username or PIN",
                "remaining_attempts": remaining_attempts(username, ip),
            },
        )

    actual_username = company_admin["name"] if company_admin else getattr(_cfg, "ADMIN_USERNAME", "admin")

    # ── TOTP 2FA check (enforced company admins) ──────────────────────────────
    # Looks up the admin row by username to check totp_secrets.
    # Only blocks login when enabled=1 (enforced=1 and enabled=0 → setup pending, allow login).
    _2fa_required = False
    try:
        from database.connection import execute_read as _er
        _admin_rows = _er(
            "SELECT id FROM admins WHERE name = %s LIMIT 1",
            (actual_username,),
        )
        if _admin_rows:
            _aid = _admin_rows[0]["id"]
            _totp = _er(
                "SELECT secret, enabled FROM totp_secrets WHERE admin_id = %s",
                (_aid,),
            )
            if _totp and _totp[0]["enabled"]:
                _2fa_required = True
                from utils.totp_helper import verify_code as _tc   # imported only when needed
                if not body.totp_code:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error":        "TotpRequired",
                            "requires_2fa": True,
                            "message":      "Enter your 6-digit authenticator code",
                        },
                    )
                if not _tc(_totp[0]["secret"], body.totp_code):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error":        "TotpInvalid",
                            "requires_2fa": True,
                            "message":      "Invalid or expired TOTP code",
                        },
                    )
    except Exception as _totp_exc:
        if _2fa_required:
            # Fail closed: never let a 2FA-enabled admin in without a verified code
            logger.error("2FA verification unavailable — login denied: %s", _totp_exc)
            return JSONResponse(
                status_code=503,
                content={"error": "TotpUnavailable",
                         "message": "Two-factor verification is unavailable. Contact the administrator."},
            )
        logger.warning("admin.py TOTP check failed (non-fatal): %s", _totp_exc)

    token = secrets.token_hex(32)   # 64-char hex
    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)
    client_ip = ip

    # Resolve the super_admin DB row before creating the session so we can
    # link admin_id immediately. Look up by role (not name) to survive any
    # username rename applied by migrations (e.g. "admin" → "superadmin").
    _linked_aid: int | None = None
    _linked_company_id: int | None = None
    from database.connection import execute_read as _er2, execute_write as _ew2
    if company_admin:
        # Company admin: the session belongs to them → all data scoped to their company
        _linked_aid = company_admin["id"]
        _linked_company_id = company_admin["company_id"]
    else:
        # The dashboard "admin" login is the admin of this PC's own company (e.g. SRM). It gets a
        # real company account so it sees ONLY that company's data — never another company's
        # (a login with no company would receive every company's live readings).
        try:
            from utils.security import hash_pin as _hp
            from services.sensor_company import get_sensor_company_id as _plant
            _home_id = _plant()                       # this PC's main company
            _row = _er2("SELECT id, company_id, role, is_active FROM admins WHERE LOWER(name) = LOWER(%s) "
                        "ORDER BY id LIMIT 1", (actual_username,))
            if _row and _row[0]["role"] != "super_admin" and _row[0].get("is_active") == 0:
                # Super Admin switched this account off: the settings-file password must not undo that
                record_attempt(username, ip, False)
                return JSONResponse(status_code=401, content={
                    "error": "AccountSuspended", "message": "Your account has been suspended. Contact the Super Admin."})
            if _row and _row[0]["role"] != "super_admin":
                _linked_aid = _row[0]["id"]
                _linked_company_id = _row[0]["company_id"] or _home_id
                _ew2("UPDATE admins SET password_hash = %s, company_id = %s WHERE id = %s",
                     (_hp(pin), _linked_company_id, _linked_aid))
            elif not _row and _home_id is not None:
                _new = _ew2(
                    "INSERT INTO admins (name, password_hash, role, company_id, created_at, is_active) "
                    "VALUES (%s, %s, 'main', %s, NOW(), 1) RETURNING id",
                    (actual_username, _hp(pin), _home_id))
                _linked_aid, _linked_company_id = _new.lastrowid, _home_id
                logger.info("login: created company account '%s' for company %s", actual_username, _home_id)
            else:   # no company exists yet — fall back to the platform account
                _sa = _er2("SELECT id, company_id FROM admins WHERE role = 'super_admin' LIMIT 1")
                if _sa:
                    _linked_aid = _sa[0]["id"]
                    _linked_company_id = _sa[0].get("company_id")
        except Exception as _exc:
            logger.warning("login: could not resolve the admin account: %s", _exc)

    # Persist session with admin_id linked from the start (avoids NULL admin_id window)
    database.create_session(token, expires_at, _linked_aid)
    try:   # remember the name typed at login (the platform "admin" shares the super-admin DB row)
        _ew2("UPDATE admin_sessions SET login_name = %s WHERE token = %s", (actual_username, token))
    except Exception as _exc:
        logger.warning("login: could not store login name: %s", _exc)

    clear_failed_attempts(username, ip)  # Task 1: clear failures on success
    record_attempt(username, ip, True)   # Task 1: log successful attempt
    try:
        from utils.audit_logger import audit
        audit(action="login_success", category="auth", ip_address=ip, severity="info")
    except Exception:
        pass

    # Update last_login + prune stale sessions
    if _linked_aid is not None:
        try:
            _ew2(
                "UPDATE admins SET last_login_at = NOW(), last_login_ip = %s WHERE id = %s",
                (client_ip, _linked_aid),
            )
            _ew2(
                """DELETE FROM admin_sessions
                    WHERE admin_id = %s
                      AND token NOT IN (
                          SELECT token FROM admin_sessions
                           WHERE admin_id = %s
                           ORDER BY created_at DESC
                           LIMIT 3
                      )""",
                (_linked_aid, _linked_aid),
            )
            log_activity(_linked_aid, "login", "admin", f"ip:{client_ip}", _linked_company_id)
        except Exception as _exc:
            logger.warning("login tracking failed: %s", _exc)

    logger.info("Admin dashboard login: username=%s (session expires in 8h)", actual_username)
    from services import company_log as _clog
    _clog.log(_linked_company_id, f"Login: {actual_username} from {client_ip}")
    return {"token": token, "username": actual_username, "company_id": _linked_company_id}


@router.post("/admin/logout", summary="Sign out (ends this sign-in on the server)")
async def admin_logout(request: Request):
    """Ends the session behind the Bearer token, so the token cannot be reused after "Logout"
    (on a shared PC another person could otherwise carry on as this admin). Always answers OK."""
    from middleware.auth import session_admin
    from database.connection import execute_write
    me = None
    try:
        me = session_admin(request.headers.get("authorization"))
    except Exception:
        pass
    if me:
        execute_write("DELETE FROM admin_sessions WHERE token = %s", (me["token"],))
        try:
            from services import company_log as _clog
            _clog.log(me.get("company_id"), f"Logout: {me['name']}")
        except Exception:
            pass
    return {"status": "signed_out"}


# ─── Change Admin Password ────────────────────────────────────────────────────

class _ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=6, max_length=200)

    @field_validator("current_password", "new_password", mode="before")
    @classmethod
    def strip_passwords(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


@router.post(
    "/admin/change-password",
    summary="Change my password",
    description="Change the signed-in admin's OWN password. Only this admin's other sign-ins end.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def change_admin_password(body: _ChangePasswordIn, request: Request):
    me = _me_or_401(request)
    err = _change_own_password(me, body.current_password, body.new_password)
    if err is not None:
        return err
    return {"status": "changed", "message": "Password changed. Your other sign-ins were ended."}


# ─── Sub-Admin Management ─────────────────────────────────────────────────────

class _CreateAdminIn(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=6, max_length=200)

    @field_validator("name", "password", mode="before")
    @classmethod
    def strip_fields(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class _UpdateAdminPwdIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=200)

    @field_validator("new_password", mode="before")
    @classmethod
    def strip_new_password(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


def _require_admin_manager(auth: dict = Depends(require_admin)) -> dict:
    """Only the main admin (whose session links to the super_admin row) or a
    DB admin with role main/super_admin may manage admin accounts — never a sub-admin."""
    aid = auth.get("admin_id")
    if aid is None:
        return {"role": "main", "company_id": None}
    row = database.get_admin_by_id(aid)
    if not row or row.get("role") not in ("main", "super_admin"):
        raise HTTPException(status_code=403, detail="Only the main admin can manage admin accounts")
    # super_admin manages every company; a company's main admin only its own
    return {"role": row["role"],
            "company_id": None if row["role"] == "super_admin" else row.get("company_id")}


def _manageable_sub_admin(admin_id: int, caller: dict) -> dict:
    """Return the target if it is a sub-admin this caller may manage; raise otherwise.
    Main/super-admin accounts are never modifiable through these routes."""
    target = database.get_admin_by_id(admin_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")
    if caller["company_id"] is not None and target.get("company_id") != caller["company_id"]:
        raise HTTPException(status_code=404, detail="Admin not found")   # don't reveal other companies
    if target.get("role") != "sub":
        raise HTTPException(status_code=403, detail="Only sub-admin accounts can be modified here")
    return target


@router.get(
    "/admin/admins",
    summary="List all admin accounts",
    description="Returns the main and sub-admin accounts of the caller's company. Requires admin auth.",
)
async def list_admins(caller: dict = Depends(require_admin)):
    """List admin accounts of the caller's company (no password hashes returned). Every admin of the
    company - sub-admins too, read-only - may see who else can sign in; only Super Admin changes them."""
    if caller.get("role") == "super_admin":
        return database.get_all_admins()
    return database.get_all_admins(company_id=caller.get("company_id"))


def _accounts_are_managed_by_super_admin():
    raise HTTPException(status_code=403, detail="Admin accounts are created and managed by Super Admin only.")


@router.post(
    "/admin/admins",
    summary="Create a sub-admin",
    description="Creates a new sub-admin in the caller's company. Only the main admin can call this.",
)
async def create_sub_admin(body: _CreateAdminIn, caller: dict = Depends(_require_admin_manager)):
    """Disabled: new admins are added only by Super Admin."""
    _accounts_are_managed_by_super_admin()
    name = body.name.strip()
    if len(name) < 2:
        return JSONResponse(status_code=422, content={"error": "name must be at least 2 characters"})
    if len(body.password) < 6:
        return JSONResponse(status_code=422, content={"error": "password must be at least 6 characters"})
    admin_id = database.create_admin(name, body.password, role="sub", company_id=caller.get("company_id"))
    if admin_id is None:
        return JSONResponse(status_code=409, content={"error": f"Admin '{name}' already exists"})
    logger.info("Sub-admin created: name=%s id=%d", name, admin_id)
    return {"status": "created", "admin_id": admin_id, "name": name, "role": "sub"}


@router.delete(
    "/admin/admins/{admin_id}",
    summary="Delete a sub-admin",
    description="Deletes a sub-admin by id. Main admin cannot be deleted.",
)
async def delete_sub_admin(admin_id: int, caller: dict = Depends(_require_admin_manager)):
    """Disabled: accounts are managed by Super Admin only."""
    _accounts_are_managed_by_super_admin()
    admin = _manageable_sub_admin(admin_id, caller)
    database.delete_admin(admin_id)
    logger.info("Sub-admin deleted: id=%d name=%s", admin_id, admin.get("name"))
    return {"status": "deleted", "admin_id": admin_id}


@router.put(
    "/admin/admins/{admin_id}/password",
    summary="Change sub-admin password",
    description="Update a sub-admin's password. Requires main admin auth.",
)
async def update_sub_admin_password(
    admin_id: int,
    body: _UpdateAdminPwdIn,
    caller: dict = Depends(_require_admin_manager),
):
    """Disabled: passwords are set by Super Admin only."""
    _accounts_are_managed_by_super_admin()
    _manageable_sub_admin(admin_id, caller)
    if len(body.new_password) < 6:
        return JSONResponse(status_code=422, content={"error": "password must be at least 6 characters"})
    database.update_admin_password(admin_id, body.new_password)
    logger.info("Sub-admin password updated: id=%d", admin_id)
    return {"status": "updated", "admin_id": admin_id}


@router.get(
    "/admin/config-changes",
    response_model=list[ConfigChangeOut],
    summary="Get config change audit log",
    description="Returns the last 50 configuration changes. Requires admin auth.",
)
async def get_config_changes(admin: dict = Depends(require_admin)):
    # Threshold changes belong to the plant feed — only its company sees them
    from services.sensor_company import owns_sensor_feed
    if not owns_sensor_feed(admin.get("company_id")):
        return []
    rows = database.get_recent_config_changes(limit=50)
    return [
        ConfigChangeOut(
            id=r["id"],
            changed_by=r["changed_by"],
            field_name=r["field_name"],
            old_value=r["old_value"],
            new_value=r["new_value"],
            changed_at=r["changed_at"],
        )
        for r in rows
    ]


@router.get(
    "/admin/backups",
    summary="List database backups",
    description="Returns metadata for all available database backup files (.sql dumps).",
    dependencies=[Depends(require_plant_owner)],
)
async def list_backups():
    """Return a list of available database backup files."""
    try:
        backups = get_backup_list()
        return {
            "count":   len(backups),
            "backups": backups,
        }
    except Exception as exc:
        logger.error("list_backups failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to list backups", "detail": str(exc)},
        )


@router.post(
    "/admin/backup",
    summary="Trigger immediate backup",
    description="Creates a timestamped pg_dump .sql backup right now.",
    dependencies=[Depends(require_plant_owner)],
)
async def trigger_backup():
    """Create a database backup immediately."""
    try:
        path = create_backup()
        if path is None:
            return JSONResponse(
                status_code=500,
                content={"error": "Backup failed", "detail": "See server logs."},
            )
        backups = get_backup_list()
        latest = backups[0] if backups else {}
        return {
            "status":    "success",
            "filename":  latest.get("filename", "backup.sql"),
            "size_mb":   latest.get("size_mb", 0),
            "timestamp": now_iso(),
        }
    except Exception as exc:
        logger.error("trigger_backup failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Backup failed", "detail": str(exc)},
        )


@router.get(
    "/admin/database/stats",
    summary="Database statistics",
    description=(
        "Returns row counts, database size (via pg_database_size()), oldest reading, "
        "and number of available backups."
    ),
)
async def database_stats(admin: dict = Depends(require_admin)):
    """Return database size and content statistics — counts are the caller's company's."""
    try:
        stats = get_database_stats()
        from services.sensor_company import owns_sensor_feed
        cid = admin.get("company_id")
        if not owns_sensor_feed(cid):
            from database.connection import execute_read as _er
            r = _er("SELECT COUNT(*) AS n, MIN(timestamp) AS oldest FROM readings WHERE company_id = %s", (cid,))
            a = _er("SELECT COUNT(*) AS n FROM alerts WHERE company_id = %s", (cid,))
            stats["readings_count"] = int(r[0]["n"]) if r else 0
            stats["oldest_reading"] = r[0]["oldest"] if r else None
            stats["alerts_count"]   = int(a[0]["n"]) if a else 0
            stats["database_size_mb"] = 0.0      # the whole database / its backups are not this company's
            stats["backups_available"] = 0
        return stats
    except Exception as exc:
        logger.error("database_stats failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to get stats", "detail": str(exc)},
        )


def _recipient_is_mine(admin: dict, phone: str = "", email: str = "") -> bool:
    """A company admin may send a test message only to people on THEIR OWN subscriber list
    (otherwise the platform's SIM / mail account could be used to message anyone with any text).
    Super Admin (no company) is not limited."""
    cid = admin.get("company_id")
    if cid is None:
        return True
    from database.connection import execute_read as _er
    rows = _er("SELECT phone, email FROM subscribers WHERE company_id = %s", (cid,))
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    for r in rows:
        if digits and "".join(ch for ch in (r.get("phone") or "") if ch.isdigit())[-10:] == digits:
            return True
        if email and (r.get("email") or "").strip().lower() == email.strip().lower():
            return True
    return False


class _ImportCsvIn(BaseModel):
    filename: str  # absolute or relative path to the CSV file


@router.post(
    "/admin/import-csv",
    summary="Import historical readings from CSV",
    description=(
        "Reads a CSV file with columns: timestamp, temperature, reference_value. "
        "Inserts each valid row into the readings table. "
        "Skips rows with bad data gracefully. "
        "Requires admin auth. "
        "Body: {filename: 'path/to/file.csv'}"
    ),
    dependencies=[Depends(require_platform_admin)],
)
async def import_csv(body: _ImportCsvIn):
    """Import historical readings from a CSV file on the server."""
    try:
        from utils.import_csv import import_csv_file
        count = import_csv_file(body.filename)
        logger.info("CSV import: %d readings from %s", count, body.filename)
        return {
            "status":   "success",
            "imported": count,
            "filename": body.filename,
        }
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=404,
            content={"error": "File not found", "detail": str(exc)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": "Invalid CSV format", "detail": str(exc)},
        )
    except Exception as exc:
        logger.error("import_csv failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Import failed", "detail": str(exc)},
        )


class _TestEmailIn(BaseModel):
    email: str


@router.post(
    "/admin/test-email",
    summary="Send a test HTML alert email",
    description=(
        "Immediately sends a test HTML email to the given address using dummy "
        "data. Use this to verify the email template without triggering a breach. "
        "Requires admin auth."
    ),
    dependencies=[Depends(require_admin)],
)
async def test_email(body: _TestEmailIn, admin: dict = Depends(require_admin)):
    """Send a test HTML email to verify the email template."""
    import asyncio
    if not _recipient_is_mine(admin, email=body.email):
        return JSONResponse(status_code=403, content={"status": "refused",
                            "error": "Test messages can only go to people on your Subscribers list. Add the person first."})
    try:
        import functools
        from services.company_email import get_company_smtp
        ok = await asyncio.get_running_loop().run_in_executor(
            None,
            functools.partial(
                send_alert_email, body.email, "Test Operator", 37.5, 38.0, "low", "WARNING", 1, now_iso(),
                smtp=get_company_smtp(admin.get("company_id")),     # the company's own mailbox, if it set one
            ),
        )
        if ok:
            logger.info("Test email sent to %s", body.email)
            return {"status": "sent", "email": body.email}
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "error": "SMTP send returned False — check server logs"},
        )
    except Exception as exc:
        logger.error("test_email failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "error": str(exc)},
        )


# ─── Test SMS ─────────────────────────────────────────────────────────────────

class _TestSmsIn(BaseModel):
    phone:   str
    message: Optional[str] = None


@router.get(
    "/admin/me",
    summary="Current admin identity",
    description="Returns the authenticated admin's id, name, role, and company_id. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
async def get_me(request: Request):
    from database.connection import execute_read
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        rows = execute_read(
            """SELECT a.id, COALESCE(s.login_name, a.name) AS name, a.role, a.company_id
                 FROM admins a
                 JOIN admin_sessions s ON s.admin_id = a.id
                WHERE s.token = %s AND s.expires_at > NOW() LIMIT 1""",
            (token,),
        )
        if rows:
            row = dict(rows[0])
            # Super admin may have no company — fall back to the first active company
            # so the dashboard can load parameters and scope WebSocket data correctly.
            if not row.get("company_id"):
                fb = execute_read(
                    "SELECT id FROM companies WHERE is_active != 0 ORDER BY id LIMIT 1"
                )
                if fb:
                    row["company_id"] = fb[0]["id"]
            row["company_name"] = None
            if row.get("company_id"):
                co = execute_read("SELECT name FROM companies WHERE id = %s", (row["company_id"],))
                if co:
                    row["company_name"] = co[0]["name"]
            # Whether this company owns the plant feed (collector / Excel / USB
            # sensor) — the dashboard only shows data-source settings if so.
            from services.sensor_company import get_sensor_company_id
            row["owns_sensor_feed"] = row.get("company_id") == get_sensor_company_id()
            # Which company each live source on this PC currently feeds
            row["source_owners"] = _source_owners()
            from services.sensor_company import collector_installed as _ci, get_source_company_id as _gs
            row["collector_available"] = _ci() and (row.get("company_id") is None
                                                     or _gs("collector") == row.get("company_id"))
            return row
    return JSONResponse(status_code=401, content={"error": "Not authenticated"})


def _resolve_admin_identity(token: str):
    """
    Return (admin_id, company_id) for a valid Bearer token, or (None, None).
    Falls back through several strategies so old sessions and unlinked admins work.
    """
    from database.connection import execute_read

    # Step 1: standard JOIN via admin_sessions.admin_id
    rows = execute_read(
        """SELECT a.id AS admin_id, a.company_id
             FROM admins a
             JOIN admin_sessions s ON s.admin_id = a.id
            WHERE s.token = %s AND s.expires_at > NOW()
            LIMIT 1""",
        (token,),
    )
    logger.debug("_resolve step1 rows=%s", rows)
    if rows and rows[0].get("admin_id"):
        admin_id   = rows[0]["admin_id"]
        company_id = rows[0].get("company_id")
        if not company_id:
            fallback = execute_read("SELECT id FROM companies ORDER BY id LIMIT 1")
            company_id = fallback[0]["id"] if fallback else None
            logger.debug("_resolve step1 company fallback=%s", company_id)
        return admin_id, company_id

    # Step 2: session exists but admin_id is NULL — reject rather than fall back to any admin
    sess_rows = execute_read(
        "SELECT id, admin_id FROM admin_sessions WHERE token = %s AND expires_at > NOW() LIMIT 1",
        (token,),
    )
    logger.debug("_resolve step2 sess_rows=%s", sess_rows)
    if sess_rows:
        s_admin_id = sess_rows[0].get("admin_id")
        if s_admin_id:
            adm_rows = execute_read(
                "SELECT id, company_id FROM admins WHERE id = %s LIMIT 1", (s_admin_id,)
            )
            logger.debug("_resolve step2 adm_rows=%s", adm_rows)
            if adm_rows:
                admin_id   = adm_rows[0]["id"]
                company_id = adm_rows[0].get("company_id")
                if not company_id:
                    fallback = execute_read("SELECT id FROM companies ORDER BY id LIMIT 1")
                    company_id = fallback[0]["id"] if fallback else None
                    logger.debug("_resolve step2 company fallback=%s", company_id)
                return admin_id, company_id
        else:
            # Session has NULL admin_id — broken session, do not authenticate
            logger.warning("_resolve_admin_identity: session has NULL admin_id — rejecting (token prefix: %s)", token[:8])
            return None, None

    logger.warning("_resolve_admin_identity: token not found or expired")
    return None, None


@router.get(
    "/admin/parameters",
    summary="Active parameters for this admin's company",
    description="Returns all active company_parameters scoped to the authenticated admin's company. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
async def get_admin_parameters(request: Request):
    from database.connection import execute_read
    auth = request.headers.get("authorization", "")
    company_id = None
    if auth.startswith("Bearer "):
        _, company_id = _resolve_admin_identity(auth[7:].strip())
    if not company_id:
        return []
    params = execute_read(
        """SELECT id, company_id, name, unit, min_value, max_value, is_active,
                  COALESCE(alerts_enabled, TRUE) AS alerts_enabled,
                  COALESCE(sms_template, '') AS sms_template, COALESCE(email_subject, '') AS email_subject,
                  COALESCE(email_body, '') AS email_body, created_at, updated_at
             FROM company_parameters
            WHERE company_id = %s AND is_active = TRUE
            ORDER BY name""",
        (company_id,),
    )
    for r in params:
        for ts in ("created_at", "updated_at"):
            if r.get(ts) and hasattr(r[ts], "isoformat"):
                r[ts] = r[ts].isoformat()
    return params


def _queue_for_hub(kind: str, admin_id: int, payload: dict) -> None:
    """On a company node the Super Admin lives on the hub — send the request up (queued
    if the hub is unreachable). On the hub itself this does nothing."""
    from services import outbox
    from database.connection import execute_read
    r = execute_read("SELECT name FROM admins WHERE id = %s", (admin_id,))
    outbox.enqueue(kind, {**payload, "admin_name": r[0]["name"] if r else None})


class _ParamLimitsIn(BaseModel):
    min_value:      Optional[float] = None
    max_value:      Optional[float] = None
    alerts_enabled: bool = True


@router.put(
    "/admin/parameters/{parameter_id}/limits",
    summary="Set one of your company's parameters' alert range and alerts on/off",
    dependencies=[Depends(require_admin)],
)
async def set_parameter_limits(parameter_id: int, body: _ParamLimitsIn, request: Request):
    """Each company sets its OWN limits per parameter (temperature, pH, pressure, ...). Adding or
    removing a parameter still needs Super Admin approval; its range does not."""
    from database.connection import execute_read as _er, execute_write as _ew
    auth = request.headers.get("authorization", "")
    admin_id, company_id = _resolve_admin_identity(auth[7:].strip()) if auth.startswith("Bearer ") else (None, None)
    if not company_id:
        return JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    rows = _er("SELECT id, name FROM company_parameters WHERE id = %s AND company_id = %s AND is_active = TRUE",
               (parameter_id, company_id))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Parameter not found"})
    if body.min_value is not None and body.max_value is not None and body.min_value >= body.max_value:
        return JSONResponse(status_code=422, content={"error": "Minimum must be lower than maximum"})
    name = rows[0]["name"]
    _ew("UPDATE company_parameters SET min_value = %s, max_value = %s, alerts_enabled = %s, updated_at = NOW() "
        "WHERE id = %s", (body.min_value, body.max_value, body.alerts_enabled, parameter_id))
    from services.live_ingest import forget_parameters
    forget_parameters(company_id)
    # Temperature of the PC's main company also drives the live temperature engine
    if str(name).lower() == "temperature":
        try:
            from services.sensor_company import get_sensor_company_id
            if company_id == get_sensor_company_id() and body.min_value is not None and body.max_value is not None:
                from config import RUNTIME_THRESHOLDS
                RUNTIME_THRESHOLDS["temp_high"] = float(body.max_value)
                RUNTIME_THRESHOLDS["temp_low"] = float(body.min_value)
                RUNTIME_THRESHOLDS.setdefault("temperature", {})
                RUNTIME_THRESHOLDS["temperature"]["high"] = float(body.max_value)
                RUNTIME_THRESHOLDS["temperature"]["low"] = float(body.min_value)
                RUNTIME_THRESHOLDS["temp_alerts_enabled"] = bool(body.alerts_enabled)
                for k, v in (("threshold_temp_high", body.max_value), ("threshold_temp_low", body.min_value),
                             ("alert_temp_alerts_enabled", str(bool(body.alerts_enabled)).lower())):
                    _ew("INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()", (k, str(v)))
        except Exception as exc:
            logger.warning("could not sync temperature engine: %s", exc)
    from services import company_log
    state = "ON" if body.alerts_enabled else "OFF"
    company_log.log(company_id, f"Limits for {name} set to {body.min_value} - {body.max_value}, alerts {state} (admin {admin_id})")
    log_activity(admin_id, "parameter_limits", "company_parameters",
                 f"{name}: {body.min_value}-{body.max_value} alerts={body.alerts_enabled}", company_id)
    try:
        from modules.inapp.manager import broadcast as _bc
        await _bc({"type": "parameter_added", "company_id": company_id, "parameter": {"name": name}}, company_id=company_id)
    except Exception:
        pass
    return {"status": "saved", "name": name, "min_value": body.min_value, "max_value": body.max_value,
            "alerts_enabled": body.alerts_enabled}


class _MessagesIn(BaseModel):
    """Only the fields that are sent are changed; an empty text switches back to the standard message."""
    sms_template:  Optional[str] = None
    email_subject: Optional[str] = None
    email_body:    Optional[str] = None


def _my_parameter(request: Request, parameter_id: int):
    """(admin_id, company_id, row) of one of the caller's own parameters, or an error response."""
    from database.connection import execute_read as _er
    auth = request.headers.get("authorization", "")
    admin_id, company_id = _resolve_admin_identity(auth[7:].strip()) if auth.startswith("Bearer ") else (None, None)
    if not company_id:
        return None, None, JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    rows = _er("SELECT id, name, unit, min_value, max_value FROM company_parameters "
               "WHERE id = %s AND company_id = %s AND is_active = TRUE", (parameter_id, company_id))
    if not rows:
        return None, None, JSONResponse(status_code=404, content={"error": "Parameter not found"})
    return admin_id, company_id, rows[0]


def _check_messages(body: "_MessagesIn"):
    from services import message_templates as mt
    if body.sms_template is not None and len(body.sms_template) > mt.SMS_MAX_TEMPLATE:
        return f"The SMS text is longer than {mt.SMS_MAX_TEMPLATE} characters"
    if body.email_subject is not None and len(body.email_subject) > mt.SUBJECT_MAX:
        return f"The e-mail subject is longer than {mt.SUBJECT_MAX} characters"
    if body.email_body is not None and len(body.email_body) > mt.BODY_MAX:
        return f"The e-mail text is longer than {mt.BODY_MAX} characters"
    bad = mt.unknown_placeholders(body.sms_template, body.email_subject, body.email_body)
    if bad:
        return ("Unknown placeholder " + ", ".join("{" + b + "}" for b in bad) +
                ". You can use: " + ", ".join("{" + n + "}" for n in mt.PLACEHOLDERS))
    return None


@router.put(
    "/admin/parameters/{parameter_id}/messages",
    summary="Set the wording of the alert SMS / e-mail for one of your company's parameters",
    dependencies=[Depends(require_admin)],
)
async def set_parameter_messages(parameter_id: int, body: _MessagesIn, request: Request):
    """Each parameter has its own SMS text and its own e-mail (subject + body), written by the company.
    {placeholders} are filled in when the alert is sent. An empty text = the standard message."""
    from database.connection import execute_write as _ew
    admin_id, company_id, row = _my_parameter(request, parameter_id)
    if company_id is None:
        return row
    err = _check_messages(body)
    if err:
        return JSONResponse(status_code=422, content={"error": err})
    sets, vals, changed = [], [], []
    for col, val, label in (("sms_template", body.sms_template, "SMS"), ("email_subject", body.email_subject, "e-mail subject"),
                            ("email_body", body.email_body, "e-mail text")):
        if val is not None:
            sets.append(f"{col} = %s"); vals.append(val.strip() or None); changed.append(label)
    if not sets:
        return JSONResponse(status_code=422, content={"error": "Nothing to save"})
    _ew(f"UPDATE company_parameters SET {', '.join(sets)}, updated_at = NOW() WHERE id = %s", (*vals, parameter_id))
    from services import company_log
    company_log.log(company_id, f"Alert wording for {row['name']} changed: {', '.join(changed)} (admin {admin_id})")
    log_activity(admin_id, "parameter_messages", "company_parameters", f"{row['name']}: {', '.join(changed)}", company_id)
    return {"status": "saved", "name": row["name"], "changed": changed}


@router.post(
    "/admin/parameters/{parameter_id}/messages/preview",
    summary="Show how the SMS / e-mail would look with example values",
    dependencies=[Depends(require_admin)],
)
async def preview_parameter_messages(parameter_id: int, body: _MessagesIn, request: Request):
    from datetime import datetime, timezone
    from services import message_templates as mt
    from database.connection import execute_read as _er
    admin_id, company_id, row = _my_parameter(request, parameter_id)
    if company_id is None:
        return row
    err = _check_messages(body)
    if err:
        return JSONResponse(status_code=422, content={"error": err})
    co = _er("SELECT name FROM companies WHERE id = %s", (company_id,))
    lo, hi = row.get("min_value"), row.get("max_value")
    hi_f = float(hi) if hi is not None else (float(lo) + 1 if lo is not None else 10.0)
    value = hi_f + max(abs(hi_f) * 0.1, 0.5)
    ctx = mt.build_context(company=co[0]["name"] if co else "", parameter=row["name"], unit=row.get("unit") or "",
                           value=value, limit=hi_f, direction="high", severity="WARNING",
                           timestamp_utc=datetime.now(timezone.utc).isoformat(), min_value=lo, max_value=hi, name="Ravi")
    sms = mt.sms_text(body.sms_template, ctx) if (body.sms_template or "").strip() else ""
    subj = mt.render(body.email_subject, ctx) if (body.email_subject or "").strip() else ""
    mail = mt.render(body.email_body, ctx) if (body.email_body or "").strip() else ""
    return {"sms": sms, "sms_length": len(sms), "email_subject": subj, "email_body": mail,
            "note": "Example values; the real alert uses the reading that crossed the limit."}


# ── The company's own e-mail account (alerts are sent from it) ─────────────────────────────────

class _EmailAccountIn(BaseModel):
    provider:  str = "gmail"
    email:     str
    password:  Optional[str] = None          # blank = keep the saved one
    host:      Optional[str] = None         # only for provider "other"
    port:      Optional[int] = None
    security:  Optional[str] = "starttls"
    from_name: Optional[str] = None


class _EmailTestIn(BaseModel):
    to: Optional[str] = None


_email_test_last: dict = {}


def _company_of(request: Request):
    auth = request.headers.get("authorization", "")
    admin_id, company_id = _resolve_admin_identity(auth[7:].strip()) if auth.startswith("Bearer ") else (None, None)
    return admin_id, company_id


@router.get("/admin/email-account", summary="This company's own e-mail account for alerts (no password)",
            dependencies=[Depends(require_admin)])
async def get_email_account(request: Request):
    from services import company_email
    from config import SMTP_USER
    admin_id, company_id = _company_of(request)
    if not company_id:
        return JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    return company_email.get_public(company_id)


@router.put("/admin/email-account", summary="Save this company's e-mail account for alerts",
            dependencies=[Depends(require_admin)])
async def save_email_account(body: _EmailAccountIn, request: Request):
    import asyncio
    from services import company_email
    admin_id, company_id = _company_of(request)
    if not company_id:
        return JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    err = await asyncio.to_thread(company_email.save, company_id, body.provider.lower(), body.email, body.password,
                                  body.host or "", body.port, body.security or "starttls", body.from_name or "")
    if err:
        return JSONResponse(status_code=422, content={"error": err})
    from services import company_log
    company_log.log(company_id, f"E-mail account set to {body.email.strip()} ({body.provider}) by admin {admin_id}")
    log_activity(admin_id, "email_account_saved", "company_email_settings", body.email.strip(), company_id)
    return {"status": "saved", **company_email.get_public(company_id)}


@router.delete("/admin/email-account", summary="Remove this company's e-mail account (the platform mailbox is used again)",
               dependencies=[Depends(require_admin)])
async def remove_email_account(request: Request):
    from services import company_email, company_log
    admin_id, company_id = _company_of(request)
    if not company_id:
        return JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    removed = company_email.delete(company_id)
    if removed:
        company_log.log(company_id, f"E-mail account removed by admin {admin_id}")
        log_activity(admin_id, "email_account_removed", "company_email_settings", "", company_id)
    return {"status": "removed" if removed else "nothing to remove"}


@router.post("/admin/email-account/test", summary="Send a test e-mail from the saved account",
             dependencies=[Depends(require_admin)])
async def test_email_account(body: _EmailTestIn, request: Request):
    import asyncio, time
    from services import company_email
    from modules.email.smtp import send_email_with_error
    admin_id, company_id = _company_of(request)
    if not company_id:
        return JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    smtp = company_email.effective_smtp(company_id)       # the mailbox this company's alerts really use
    if not smtp:
        return JSONResponse(status_code=409, content={"error": "Save the e-mail account first"})
    if smtp.get("broken"):
        return JSONResponse(status_code=409, content={"error": "The saved password can no longer be read: type the app password again and press Save"})
    now = time.monotonic()
    if now - _email_test_last.get(company_id, -1e9) < 8:
        return JSONResponse(status_code=429, content={"error": "Wait a few seconds before testing again"})
    _email_test_last[company_id] = now
    to = (body.to or "").strip() or smtp["user"]
    if to.lower() != smtp["user"].lower() and not _recipient_is_mine({"company_id": company_id}, email=to):
        return JSONResponse(status_code=403, content={"error": "Send the test to your own address or to someone on your Subscribers list"})
    co = database.execute_read("SELECT name FROM companies WHERE id = %s", (company_id,))
    name = co[0]["name"] if co else "your company"
    ok, why = await asyncio.to_thread(
        send_email_with_error, to, f"SentinelEdge test e-mail - {name}",
        f"This is a test from SentinelEdge for {name}.\n\nIf you can read this, alert e-mails for {name} will be sent from this account ({smtp['user']}).\n", smtp)
    company_email.record_result(company_id, ok, why)
    from services import company_log
    company_log.log(company_id, f"Test e-mail to {to}: " + ("sent" if ok else f"FAILED ({why})"))
    if not ok:
        return JSONResponse(status_code=502, content={"status": "failed", "error": company_email.friendly_error(why), "detail": (why or "")[:200]})
    return {"status": "sent", "to": to}


@router.post(
    "/admin/parameters/{parameter_id}/test-alert",
    summary="Send a TEST alert for one of your company's parameters",
    dependencies=[Depends(require_admin)],
)
async def send_test_alert(parameter_id: int, request: Request):
    """Fires a real alert (stored, shown on the dashboard, sent by SMS / e-mail / app) for this
    company only, with a value just outside the parameter's range - to check that alerts reach
    the right people. Nothing is added to the readings."""
    from datetime import datetime, timezone
    from database.connection import execute_read as _er
    from models import BreachEvent
    import core.escalation as _esc
    auth = request.headers.get("authorization", "")
    admin_id, company_id = _resolve_admin_identity(auth[7:].strip()) if auth.startswith("Bearer ") else (None, None)
    if not company_id:
        return JSONResponse(status_code=401, content={"error": "Sign in as a company admin"})
    rows = _er("SELECT name, unit, min_value, max_value FROM company_parameters "
               "WHERE id = %s AND company_id = %s AND is_active = TRUE", (parameter_id, company_id))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Parameter not found"})
    p = rows[0]
    mn = float(p["min_value"]) if p["min_value"] is not None else None
    mx = float(p["max_value"]) if p["max_value"] is not None else None
    if mx is not None:
        direction, limit = "high", mx
        value = round(mx + max(abs(mx - (mn if mn is not None else mx - 10)) * 0.1, 1.0), 3)
    elif mn is not None:
        direction, limit = "low", mn
        value = round(mn - 1.0, 3)
    else:
        return JSONResponse(status_code=422, content={"error": "Set a minimum or maximum for this parameter first"})
    name = str(p["name"]).lower()
    breach = BreachEvent(parameter=name, value=value, threshold=limit, direction=direction, severity="WARNING")
    now = datetime.now(timezone.utc).isoformat()
    ids = await _esc.trigger_alert({"temperature": None, "timestamp": now, "extra_params": {name: value}}, [breach], company_id)
    if not ids or ids[0] is None:
        return JSONResponse(status_code=500, content={"error": "The test alert could not be created"})
    people = _er("SELECT COUNT(*) AS n FROM subscribers WHERE company_id = %s AND COALESCE(is_active, 1) = 1", (company_id,))[0]["n"]
    from services import company_log
    company_log.log(company_id, f"TEST alert #{ids[0]}: {name} {value} ({direction} limit {limit}) sent by admin {admin_id}", 30)
    try:
        from modules.inapp.manager import broadcast as _bc
        await _bc({"type": "test_alert", "company_id": company_id, "timestamp": now,
                   "breaches": [{**breach.model_dump(), "alert_id": ids[0]}]}, company_id=company_id)
    except Exception:
        pass
    return {"status": "sent", "alert_id": ids[0], "parameter": p["name"], "value": value,
            "direction": direction, "limit": limit, "subscribers": int(people)}


class _ParamRequestIn(BaseModel):
    name:      str = Field(min_length=1, max_length=100)
    unit:      str = Field(min_length=1, max_length=50)
    min_value: Optional[float] = None
    max_value: Optional[float] = None


@router.post(
    "/admin/parameters",
    status_code=201,
    summary="Request a new company parameter (pending super admin approval)",
    dependencies=[Depends(require_admin)],
)
async def request_admin_parameter(body: _ParamRequestIn, request: Request):
    from database.connection import execute_write, execute_read
    import json as _json

    auth = request.headers.get("authorization", "")
    admin_id, company_id = (None, None)
    if auth.startswith("Bearer "):
        admin_id, company_id = _resolve_admin_identity(auth[7:].strip())

    if not admin_id or not company_id:
        return JSONResponse(status_code=401, content={"error": "Cannot determine admin identity from token"})

    # Super admin: direct insert — no approval queue needed
    role_rows = execute_read("SELECT role FROM admins WHERE id = %s LIMIT 1", (admin_id,))
    role = role_rows[0]["role"] if role_rows else None
    if role == "super_admin":
        execute_write(
            """INSERT INTO company_parameters
                   (company_id, name, unit, min_value, max_value, is_active, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, TRUE, NOW(), NOW())
               ON CONFLICT (company_id, name) DO UPDATE
                 SET unit=EXCLUDED.unit, min_value=EXCLUDED.min_value,
                     max_value=EXCLUDED.max_value, is_active=TRUE, updated_at=NOW()""",
            (company_id, body.name, body.unit, body.min_value, body.max_value),
        )
        try:
            from modules.inapp.manager import broadcast as _bcast
            import asyncio as _asyncio
            _asyncio.create_task(_bcast({
                "type":       "parameter_added",
                "company_id": company_id,
                "parameter":  {"name": body.name, "unit": body.unit,
                               "min_value": body.min_value, "max_value": body.max_value},
            }, company_id=company_id))
        except Exception as _be:
            logger.warning("parameter_added broadcast failed: %s", _be)
        log_activity(admin_id, "parameter_added", "company_parameters",
                     f"company_id:{company_id} name:{body.name}", company_id)
        logger.info("Super admin %d added parameter '%s' for company %d", admin_id, body.name, company_id)
        return JSONResponse(
            status_code=201,
            content={"status": "added", "message": f"Parameter '{body.name}' added successfully."},
        )

    # Regular admin: submit for approval (one pending request per parameter name)
    dup = execute_read(
        """SELECT id FROM pending_approvals
            WHERE status = 'pending' AND action_type = 'add_parameter'
              AND (payload->>'company_id')::int = %s
              AND LOWER(payload->>'name') = LOWER(%s)
            LIMIT 1""",
        (company_id, body.name),
    )
    if dup:
        return JSONResponse(
            status_code=409,
            content={"error": f"A request to add '{body.name}' is already waiting for Super Admin approval."},
        )
    payload = {
        "company_id": company_id,
        "name":       body.name,
        "unit":       body.unit,
        "min_value":  body.min_value,
        "max_value":  body.max_value,
    }
    execute_write(
        """INSERT INTO pending_approvals (admin_id, action_type, payload)
           VALUES (%s, 'add_parameter', %s)""",
        (admin_id, _json.dumps(payload)),
    )
    log_activity(
        admin_id, "parameter_requested", "company_parameters",
        f"company_id:{company_id} name:{body.name}",
        company_id,
    )
    from services import company_log as _clog
    _clog.log(company_id, f"Parameter {body.name} ({body.unit}) requested - waiting for Super Admin approval")
    _queue_for_hub("parameter_request", admin_id, {"name": body.name, "unit": body.unit,
                                                   "min_value": body.min_value, "max_value": body.max_value})
    logger.info("Admin %d requested add_parameter '%s' for company %d", admin_id, body.name, company_id)
    return {"status": "pending", "message": f"Parameter '{body.name}' submitted for super admin approval."}


@router.delete(
    "/admin/parameters/{parameter_id}",
    status_code=202,
    summary="Request deletion of a company parameter (pending super admin approval)",
    dependencies=[Depends(require_admin)],
)
async def request_delete_parameter(parameter_id: int, request: Request):
    from database.connection import execute_write, execute_read as _er
    import json as _json

    auth = request.headers.get("authorization", "")
    admin_id, company_id = (None, None)
    if auth.startswith("Bearer "):
        admin_id, company_id = _resolve_admin_identity(auth[7:].strip())

    if not admin_id or not company_id:
        return JSONResponse(status_code=401, content={"error": "Cannot determine admin identity from token"})

    rows = _er(
        "SELECT id, name, unit FROM company_parameters WHERE id = %s AND company_id = %s",
        (parameter_id, company_id),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Parameter not found"})

    param = rows[0]
    dup = _er(
        """SELECT id FROM pending_approvals
            WHERE status = 'pending' AND action_type = 'delete_parameter'
              AND (payload->>'parameter_id')::int = %s
            LIMIT 1""",
        (parameter_id,),
    )
    if dup:
        return JSONResponse(
            status_code=409,
            content={"error": f"Deletion of '{param['name']}' is already waiting for Super Admin approval."},
        )
    payload = {"parameter_id": parameter_id, "name": param["name"], "company_id": company_id}
    execute_write(
        """INSERT INTO pending_approvals (admin_id, action_type, payload)
           VALUES (%s, 'delete_parameter', %s)""",
        (admin_id, _json.dumps(payload)),
    )
    log_activity(
        admin_id, "parameter_delete_requested", "company_parameters",
        f"company_id:{company_id} name:{param['name']} id:{parameter_id}",
        company_id,
    )
    from services import company_log as _clog
    _clog.log(company_id, "Removal of parameter " + str(param["name"]) + " requested - waiting for Super Admin approval")
    _queue_for_hub("parameter_delete_request", admin_id, {"name": param["name"]})
    logger.info("Admin %d requested delete_parameter '%s' (id=%d) for company %d",
                admin_id, param["name"], parameter_id, company_id)
    return {"status": "pending", "message": f"Deletion of '{param['name']}' submitted for super admin approval."}


@router.get(
    "/admin/approvals",
    summary="This company's approval requests and their outcome",
    description="Requests sent to the Super Admin (add/delete parameter) for the "
                "caller's company, newest first, with status and review note.",
    dependencies=[Depends(require_admin)],
)
async def list_my_approvals(request: Request):
    from database.connection import execute_read
    auth = request.headers.get("authorization", "")
    company_id = None
    if auth.startswith("Bearer "):
        _, company_id = _resolve_admin_identity(auth[7:].strip())
    if not company_id:
        return []
    rows = execute_read(
        """SELECT pa.id, pa.action_type, pa.status, pa.review_note,
                  pa.payload->>'name' AS parameter_name,
                  a.name  AS requested_by,
                  r.name  AS reviewed_by,
                  pa.created_at, pa.reviewed_at
             FROM pending_approvals pa
             LEFT JOIN admins a ON a.id = pa.admin_id
             LEFT JOIN admins r ON r.id = pa.reviewed_by
            WHERE (pa.payload->>'company_id')::int = %s
            ORDER BY pa.created_at DESC
            LIMIT 50""",
        (company_id,),
    )
    for r in rows:
        for ts in ("created_at", "reviewed_at"):
            if r.get(ts) and hasattr(r[ts], "isoformat"):
                r[ts] = r[ts].isoformat()
    return rows


@router.post(
    "/admin/test-sms",
    summary="Send a test SMS alert",
    description=(
        "Queues a test SMS to the given phone number through the GSM worker "
        "(same path as real alerts). Works in both LIVE mode (real modem) and "
        "MOCK mode (no modem — logs the SMS). "
        "Optional body field 'message' overrides the default test message. "
        "Requires admin auth. Body: {\"phone\": \"9876543210\"}"
    ),
    dependencies=[Depends(require_admin)],
)
async def test_sms(body: _TestSmsIn, admin: dict = Depends(require_admin)):
    """Send a test SMS via the GSM queue worker."""
    if not _recipient_is_mine(admin, phone=body.phone):
        return JSONResponse(status_code=403, content={"status": "refused",
                            "error": "Test messages can only go to people on your Subscribers list. Add the person first."})
    from config import SMS_METHOD
    from modules.sms.sender import (
        _mock_mode, _modem_port,
        _sms_queue,
        build_sms_message,
        send_sms,
    )
    import asyncio, time

    DEFAULT_MSG = "SentinelEdge Test: SMS delivery confirmed. System is working."

    try:
        method  = (SMS_METHOD or "adb").lower().strip()
        is_mock = _mock_mode and method == "gammu"
        mode    = "mock" if is_mock else "live"

        if body.message:
            message = body.message[:160]
        else:
            ts      = now_iso()
            message = build_sms_message(
                value=37.5, threshold=38.0, direction="low", timestamp_utc=ts,
            )

        # gammu path: push through the queue worker
        if method == "gammu":
            result_holder: dict = {"to": body.phone, "status": "queued", "error": None}
            _sms_queue.put((body.phone, message, result_holder))
            logger.info("Test SMS queued to %s (mode=%s)", body.phone, mode)

            loop = asyncio.get_running_loop()
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, _sms_queue.join),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                pass

            final_status = result_holder.get("status", "queued")
            return {
                "status":  final_status,
                "phone":   body.phone,
                "mode":    mode,
                "port":    _modem_port or "not detected",
                "message": "SMS queued for delivery" if is_mock
                           else "SMS sent — check your phone",
            }

        # adb / gateway path: direct send
        ok = send_sms(body.phone, message)
        if ok:
            logger.info("Test SMS sent to %s via %s", body.phone, SMS_METHOD)
            return {
                "status":  "sent",
                "phone":   body.phone,
                "mode":    "live",
                "method":  SMS_METHOD,
                "message": "SMS sent — check your phone",
            }
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "phone":  body.phone,
                "mode":   mode,
                "error":  "SMS transport returned False — check server logs",
            },
        )

    except Exception as exc:
        logger.error("test_sms failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "error": str(exc)},
        )


# ─── Pro-Server EX data-source settings ──────────────────────────────────────

class _ProServerSettingsIn(BaseModel):
    file_path:     str   = Field("",            max_length=1024)
    temp_col:      str   = Field("Temperature", max_length=100)
    date_col:      str   = Field("Date",        max_length=100)
    time_col:      str   = Field("Time",        max_length=100)
    timestamp_col: str   = Field("",            max_length=100)
    poll_interval: float = Field(1.0, ge=0.1, le=60.0)
    auto_save:     bool  = Field(False)


class _ProServerTestIn(BaseModel):
    file_path: str = Field(..., max_length=1024)


@router.get("/admin/proserver/settings", dependencies=[Depends(require_feed_admin)])
def api_get_proserver_settings():
    """Return the current Pro-Server EX file path and column settings."""
    rows = database.execute_read(
        "SELECT key, value FROM app_settings WHERE key LIKE %s",
        ("proserver_%",),
    ) or []
    out: dict = {
        "file_path":     "",
        "temp_col":      "TEMPERATURE",
        "date_col":      "DATE/TIME",
        "time_col":      "Time",
        "timestamp_col": "",
        "poll_interval": 1.0,
        "auto_save":     False,
    }
    for row in rows:
        k = row["key"].replace("proserver_", "", 1)
        v = row["value"]
        if k == "poll_interval":
            try:
                out[k] = float(v)
            except (ValueError, TypeError):
                pass
        elif k == "auto_save":
            out[k] = (v == "1")
        elif k in out:
            out[k] = v
    return JSONResponse(out)


@router.post("/admin/proserver/settings")
def api_save_proserver_settings(body: _ProServerSettingsIn, admin: dict = Depends(require_feed_admin)):
    """Save Pro-Server EX settings to DB and hot-reload the reader thread."""
    refused = _check_source_change("excel", True, admin)      # the Excel file belongs to the saving company
    if refused is not None:
        return refused
    from services import company_log as _clog
    _clog.log(admin.get("company_id"), "Excel reader settings saved: file=" + repr(body.file_path))
    file_path = body.file_path.strip()
    if file_path:
        import os.path as _osp
        # Only data files the reader supports — the CSV fallback would otherwise
        # display any text file on the server (e.g. .env) via the diagnostic view.
        if _osp.splitext(file_path)[1].lower() not in (".csv", ".txt", ".xls", ".xlsx", ".xlsm", ".xlsb"):
            return JSONResponse(status_code=422, content={"error": "File must be .xls, .xlsx, .xlsm, .xlsb or .csv"})
        # Network shares make Windows send the server's NTLM credentials to that host
        if file_path.startswith(("\\\\", "//")):
            return JSONResponse(status_code=422, content={"error": "Network share paths are not allowed"})
    vals = {
        "file_path":     file_path,
        "temp_col":      body.temp_col.strip() or "TEMPERATURE",
        "date_col":      body.date_col.strip() or "DATE/TIME",
        "time_col":      body.time_col.strip() or "Time",
        "timestamp_col": body.timestamp_col.strip(),
        "poll_interval": body.poll_interval,
    }
    for k, v in vals.items():
        database.execute_write(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (f"proserver_{k}", str(v)),
        )

    import core.excel_sensor as excel_sensor
    excel_sensor.reload_settings(vals)
    excel_sensor.set_auto_save(body.auto_save)

    return JSONResponse({"status": "saved", "active": excel_sensor.is_active(), "auto_save": body.auto_save})


@router.get("/admin/data-source", dependencies=[Depends(require_feed_admin)])
def api_get_data_source():
    """State of the two independent live sources."""
    import core.excel_sensor as excel_sensor
    from services.data_sources import collector_enabled
    return {
        "collector_enabled": collector_enabled(),
        "excel_enabled":     excel_sensor.EXCEL_LIVE_ENABLED,
        "file_path":         excel_sensor.EXCEL_FILE_PATH,
        "excel":             excel_sensor.get_enabled_status(),
        "owners":            _source_owners(),
    }


def _source_owners() -> dict:
    """Which company each live source on this PC belongs to."""
    from services.sensor_company import SOURCES, get_source_company_id
    from database.connection import execute_read as _er
    out = {}
    for src in SOURCES:
        cid = get_source_company_id(src)
        r = _er("SELECT name FROM companies WHERE id = %s", (cid,)) if cid else []
        out[src] = {"company_id": cid, "company_name": r[0]["name"] if r else None}
    return out


def _check_source_change(source: str, turning_on: bool, admin: dict):
    """None if allowed (claiming the source when it is switched on), else a 409 response."""
    from services.sensor_company import claim_source, get_source_company_id, source_in_use, collector_installed
    cid = admin.get("company_id")
    if source == "collector" and cid is not None:
        # The Pro-face live collector belongs to the company it was installed for; new companies
        # use the Excel reader. Super Admin can reassign it (Config -> Live sources on this PC).
        if not collector_installed():
            return JSONResponse(status_code=409, content={"error": "The Pro-Server live collector is not installed on this PC."})
        if get_source_company_id("collector") != cid:
            return JSONResponse(status_code=403, content={"error": "The live collector is not set up for your company. Use the Excel reader."})
    if turning_on:
        msg = claim_source(source, admin)
    elif cid is not None and get_source_company_id(source) != cid and source_in_use(source):
        msg = "This source is in use by another company — only that company (or Super Admin) can switch it off."
    else:
        msg = None
    return JSONResponse(status_code=409, content={"error": msg}) if msg else None


class _DataSourceIn(BaseModel):
    """Either or both switches; a missing one is left as it is."""
    collector: Optional[bool] = None
    excel:     Optional[bool] = None


@router.post("/admin/data-source")
async def api_set_data_source(body: _DataSourceIn, admin: dict = Depends(require_feed_admin)):
    """
    collector — the Pro-Server EX live collector feeds the dashboard.
    excel     — the dashboard follows the Excel/CSV file saved in Settings
                (last row; shows it again until the next row arrives).
    Each can be switched on or off on its own.
    """
    import asyncio
    from pathlib import Path as _Path
    import core.excel_sensor as excel_sensor
    from services import data_sources

    if body.excel:
        fp = (excel_sensor.EXCEL_FILE_PATH or "").strip()
        if not fp:
            return JSONResponse(status_code=422, content={
                "error": "Enter the Excel file path below and press Save Settings before switching the Excel reader on."})
        if not _Path(fp).exists():
            return JSONResponse(status_code=422, content={"error": f"Excel file not found: {fp}"})

    # Each source belongs to one company: switching it on makes it yours (unless another
    # company is using it right now); you cannot switch off another company's running source.
    for _src, _val in (("collector", body.collector), ("excel", body.excel)):
        if _val is not None:
            refused = _check_source_change(_src, bool(_val), admin)
            if refused is not None:
                return refused

    from services import company_log as _clog
    for _src, _val in (("Live collector", body.collector), ("Excel reader", body.excel)):
        if _val is not None:
            _clog.log(admin.get("company_id"), _src + " switched " + ("ON" if _val else "OFF"))

    if body.collector is not None:
        await asyncio.to_thread(data_sources.set_collector_enabled, body.collector)
    if body.excel is not None:
        # Restarting the reader thread can wait a few seconds — keep it off the event loop
        await asyncio.to_thread(excel_sensor.set_excel_enabled, body.excel)

    # Tell open dashboards so they drop values from a source that was switched off
    try:
        from modules.inapp.manager import broadcast as _broadcast
        await _broadcast({"type": "data_source_changed"})
    except Exception as exc:
        logger.warning("data_source_changed broadcast failed: %s", exc)

    return {"collector_enabled": data_sources.collector_enabled(),
            "excel_enabled": excel_sensor.EXCEL_LIVE_ENABLED,
            "file_path": excel_sensor.EXCEL_FILE_PATH,
            "owners": _source_owners()}


@router.get("/admin/proserver/reading-status", dependencies=[Depends(require_feed_admin)])
def api_proserver_reading_status():
    """Excel reader status: switch, whether it reads the file, last row, new-row count."""
    import core.excel_sensor as excel_sensor
    return JSONResponse(excel_sensor.get_enabled_status())

@router.get("/admin/proserver/diagnostic", dependencies=[Depends(require_feed_admin)])
def api_proserver_diagnostic():
    """Return a diagnostic snapshot: file existence, column matching, current readings."""
    import core.excel_sensor as excel_sensor
    return JSONResponse(excel_sensor.get_diagnostic())


@router.post("/admin/proserver/test", dependencies=[Depends(require_feed_admin)])
def api_test_proserver(body: _ProServerTestIn):
    """Read the latest row from the given file and return detected columns."""
    from pathlib import Path as _Path
    import core.excel_sensor as excel_sensor

    fp = body.file_path.strip()
    if not fp:
        return JSONResponse({"status": "error", "message": "file_path is required"}, status_code=400)

    if not _Path(fp).exists():
        return JSONResponse({"status": "error", "message": f"File not found: {fp}"})

    # Temporarily swap EXCEL_FILE_PATH so _read_latest_row uses the test path
    saved_path = excel_sensor.EXCEL_FILE_PATH
    excel_sensor.EXCEL_FILE_PATH = fp
    try:
        row = excel_sensor._read_latest_row()
    finally:
        excel_sensor.EXCEL_FILE_PATH = saved_path

    if row is None:
        return JSONResponse({
            "status": "error",
            "message": "File found but could not read data — check format/encoding/permissions",
        })

    columns = list(row.keys())
    preview = {k: str(v) for k, v in row.items()}
    return JSONResponse({
        "status":     "ok",
        "message":    f"Read {len(columns)} column(s) successfully",
        "columns":    columns,
        "latest_row": preview,
    })


# ─── OPC DA secondary sensor settings ─────────────────────────────────────────

class _OpcSettingsIn(BaseModel):
    server_name:   str   = Field("",  max_length=256)
    temp_tag:      str   = Field("",  max_length=512)
    extra_tags:    str   = Field("",  max_length=1024)
    poll_interval: float = Field(2.0, ge=0.5, le=60.0)


@router.get("/admin/opc/settings", dependencies=[Depends(require_feed_admin)])
def api_get_opc_settings():
    """Return the current OPC DA secondary sensor settings."""
    rows = database.execute_read(
        "SELECT key, value FROM app_settings WHERE key LIKE %s",
        ("opc_%",),
    ) or []
    out: dict = {
        "server_name":   "",
        "temp_tag":      "",
        "extra_tags":    "",
        "poll_interval": 2.0,
    }
    for row in rows:
        k = row["key"].replace("opc_", "", 1)
        v = row["value"]
        if k == "poll_interval":
            try:
                out[k] = float(v)
            except (ValueError, TypeError):
                pass
        elif k in out:
            out[k] = v

    import core.opc_sensor as opc_sensor
    out["status"] = opc_sensor.get_status()
    return JSONResponse(out)


@router.post("/admin/opc/settings")
def api_save_opc_settings(body: _OpcSettingsIn, admin: dict = Depends(require_feed_admin)):
    """Save OPC DA settings to DB and hot-reload the reader thread."""
    refused = _check_source_change("excel", True, admin)      # OPC DA is the same plant-reader slot
    if refused is not None:
        return refused
    vals = {
        "server_name":   body.server_name.strip(),
        "temp_tag":      body.temp_tag.strip(),
        "extra_tags":    body.extra_tags.strip(),
        "poll_interval": body.poll_interval,
    }
    for k, v in vals.items():
        database.execute_write(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (f"opc_{k}", str(v)),
        )

    import core.opc_sensor as opc_sensor
    opc_sensor.reload_settings(vals)

    return JSONResponse({
        "status":    "saved",
        "connected": opc_sensor._connected,
        "active":    opc_sensor.is_active(),
    })


@router.get("/admin/opc/status", dependencies=[Depends(require_feed_admin)])
def api_opc_status():
    """Return live OPC DA connection status."""
    import core.opc_sensor as opc_sensor
    return JSONResponse(opc_sensor.get_status())

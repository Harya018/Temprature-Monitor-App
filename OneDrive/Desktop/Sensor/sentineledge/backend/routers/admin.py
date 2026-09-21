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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional

import database
import config as _cfg
from config import ADMIN_PASSWORD, SMTP_USER
from middleware.auth import require_admin
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
    dependencies=[Depends(require_admin)],
)
async def get_ack_log(limit: int = 100):
    """Return the acknowledgement log with response time in seconds."""
    try:
        rows = database.get_ack_log(limit=limit)
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
    description="Checks whether the supplied password matches the authenticated admin's stored password. "
                "Requires a valid admin session token.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def verify_password(body: _VerifyIn, request: Request):
    """Used by the frontend admin modal to re-confirm the password for sensitive actions."""
    from utils.security import verify_pin
    return {"valid": verify_pin(body.password, ADMIN_PASSWORD)}


# ─── Admin Profile (GET + PATCH username/PIN) ─────────────────────────────────

class _ProfileUpdateIn(BaseModel):
    current_pin: str = Field(min_length=1, max_length=200)
    new_username: Optional[str] = Field(default=None, max_length=50)
    new_pin:      Optional[str] = Field(default=None, min_length=4, max_length=20)

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
    description="Returns current admin username. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
async def get_admin_profile():
    """Return the current admin's public profile (PIN never returned)."""
    import config as _cfg
    username = getattr(_cfg, "ADMIN_USERNAME", "admin")
    return {"username": username}


@router.patch(
    "/admin/profile",
    summary="Update admin profile",
    description="Update username/PIN for the main admin. current_pin must match. On success all sessions invalidated.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("10/minute")
async def update_admin_profile(body: _ProfileUpdateIn, request: Request):
    """Change admin username and/or PIN. Invalidates all DB sessions on success."""
    import re as _re
    import os as _os
    from utils.security import verify_pin, hash_pin

    if not verify_pin(body.current_pin, _cfg.ADMIN_PASSWORD):
        return JSONResponse(status_code=401, content={"detail": "Current PIN is incorrect"})

    new_username = None
    if body.new_username and body.new_username.strip():
        uname = body.new_username.strip()
        if not _re.match(r"^[a-zA-Z0-9_]{3,20}$", uname):
            return JSONResponse(status_code=422, content={"detail": "Username must be 3-20 chars (letters/digits/underscores)"})
        new_username = uname

    new_pin = None
    if body.new_pin and body.new_pin.strip():
        npin = body.new_pin.strip()
        if len(npin) < 4 or len(npin) > 20:
            return JSONResponse(status_code=422, content={"detail": "New PIN must be 4-20 characters"})
        new_pin = npin

    if not new_username and not new_pin:
        return JSONResponse(status_code=422, content={"detail": "Provide at least new_username or new_pin"})

    root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
    env_file = _os.path.join(root, f".env.{_cfg.APP_ENV}")
    if not _os.path.exists(env_file):
        env_file = _os.path.join(root, ".env")

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()
        if new_pin:
            hashed_pin = hash_pin(new_pin)
            if _re.search(r"^ADMIN_PASSWORD=.*$", content, flags=_re.MULTILINE):
                content = _re.sub(r"^ADMIN_PASSWORD=.*$", f"ADMIN_PASSWORD={hashed_pin}", content, flags=_re.MULTILINE)
            else:
                content = content.rstrip("\n") + f"\nADMIN_PASSWORD={hashed_pin}\n"
        if new_username:
            if _re.search(r"^ADMIN_USERNAME=.*$", content, flags=_re.MULTILINE):
                content = _re.sub(r"^ADMIN_USERNAME=.*$", f"ADMIN_USERNAME={new_username}", content, flags=_re.MULTILINE)
            else:
                content = content.rstrip("\n") + f"\nADMIN_USERNAME={new_username}\n"
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as exc:
        logger.error("update_admin_profile write error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": f"Failed to write .env: {exc}"})

    if new_pin:
        _cfg.ADMIN_PASSWORD = hashed_pin
    if new_username:
        _cfg.ADMIN_USERNAME = new_username

    # Invalidate ALL sessions in the DB (password changed)
    try:
        from database.queries.sessions import cleanup_expired_sessions
        from database.connection import execute_write
        execute_write("DELETE FROM admin_sessions")
        logger.info("Admin profile updated. All DB sessions cleared.")
    except Exception as exc:
        logger.warning("Failed to clear DB sessions after profile update: %s", exc)

    return {"message": "Profile updated. Please log in again."}


# ─── Username + PIN Login (DB-backed sessions) ────────────────────────────────

class _AdminLoginIn(BaseModel):
    username:  str = Field(min_length=1, max_length=50)
    pin:       str = Field(min_length=4, max_length=20)
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
    valid = (username == stored_username and verify_pin(pin, _cfg.ADMIN_PASSWORD))

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

    actual_username = getattr(_cfg, "ADMIN_USERNAME", "admin")

    # ── TOTP 2FA check (enforced company admins) ──────────────────────────────
    # Looks up the admin row by username to check totp_secrets.
    # Only blocks login when enabled=1 (enforced=1 and enabled=0 → setup pending, allow login).
    try:
        from database.connection import execute_read as _er
        from utils.totp_helper import verify_code as _tc
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
        logger.warning("admin.py TOTP check failed (non-fatal): %s", _totp_exc)

    token = secrets.token_hex(32)   # 64-char hex
    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)
    client_ip = ip

    # Resolve the super_admin DB row before creating the session so we can
    # link admin_id immediately. Look up by role (not name) to survive any
    # username rename applied by migrations (e.g. "admin" → "superadmin").
    _linked_aid: int | None = None
    _linked_company_id: int | None = None
    try:
        from database.connection import execute_read as _er2, execute_write as _ew2
        _sa = _er2("SELECT id, company_id FROM admins WHERE role = 'super_admin' LIMIT 1")
        if _sa:
            _linked_aid = _sa[0]["id"]
            _linked_company_id = _sa[0].get("company_id")
    except Exception as _exc:
        logger.warning("login: could not resolve super_admin row: %s", _exc)

    # Persist session with admin_id linked from the start (avoids NULL admin_id window)
    database.create_session(token, expires_at, _linked_aid)

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
    return {"token": token, "username": actual_username}


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
    summary="Change admin password",
    description=(
        "Validates current_password against ADMIN_PASSWORD, then writes the new "
        "password to the active .env file and updates the in-memory value — "
        "no server restart required. Requires admin auth header."
    ),
    dependencies=[Depends(require_admin)],
)
async def change_admin_password(body: _ChangePasswordIn):
    """Change the admin password in-place without restarting the server."""
    import re as _re
    from utils.security import verify_pin, hash_pin

    # 1. Verify current password
    if not verify_pin(body.current_password, _cfg.ADMIN_PASSWORD):
        return JSONResponse(
            status_code=401,
            content={"error": "Current password is incorrect"},
        )

    # 2. Validate new password
    new_pwd = body.new_password.strip()
    if len(new_pwd) < 6:
        return JSONResponse(
            status_code=422,
            content={"error": "New password must be at least 6 characters"},
        )

    # 3. Locate the active .env file
    import os as _os
    root = _os.path.abspath(
        _os.path.join(_os.path.dirname(__file__), "..", "..")
    )
    env_file = _os.path.join(root, f".env.{_cfg.APP_ENV}")
    if not _os.path.exists(env_file):
        env_file = _os.path.join(root, ".env")

    # 4. Rewrite ADMIN_PASSWORD line in the .env file
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()

        hashed_pwd = hash_pin(new_pwd)
        if _re.search(r"^ADMIN_PASSWORD=.*$", content, flags=_re.MULTILINE):
            new_content = _re.sub(
                r"^ADMIN_PASSWORD=.*$",
                f"ADMIN_PASSWORD={hashed_pwd}",
                content,
                flags=_re.MULTILINE,
            )
        else:
            new_content = content.rstrip("\n") + f"\nADMIN_PASSWORD={hashed_pwd}\n"

        with open(env_file, "w", encoding="utf-8") as f:
            f.write(new_content)

    except Exception as exc:
        logger.error("change_admin_password: failed to write .env: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to write .env file", "detail": str(exc)},
        )

    # 5. Update in-memory value — no restart needed
    _cfg.ADMIN_PASSWORD = hashed_pwd

    # 6. Invalidate all DB sessions (password changed — everyone must re-login)
    try:
        from database.connection import execute_write
        execute_write("DELETE FROM admin_sessions")
        logger.info("All admin sessions cleared after password change.")
    except Exception as exc:
        logger.warning("Failed to clear DB sessions after password change: %s", exc)

    logger.info("Admin password changed successfully (env: %s)", env_file)
    return {"status": "changed", "message": "Password updated successfully. All sessions have been invalidated."}


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


@router.get(
    "/admin/admins",
    summary="List all admin accounts",
    description="Returns all main and sub-admin accounts. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
async def list_admins():
    """List all admin accounts (no password hashes returned)."""
    return database.get_all_admins()


@router.post(
    "/admin/admins",
    summary="Create a sub-admin",
    description="Creates a new sub-admin account. Only the main admin can call this.",
    dependencies=[Depends(require_admin)],
)
async def create_sub_admin(body: _CreateAdminIn):
    """Create a new sub-admin."""
    name = body.name.strip()
    if len(name) < 2:
        return JSONResponse(status_code=422, content={"error": "name must be at least 2 characters"})
    if len(body.password) < 6:
        return JSONResponse(status_code=422, content={"error": "password must be at least 6 characters"})
    admin_id = database.create_admin(name, body.password, role="sub")
    if admin_id is None:
        return JSONResponse(status_code=409, content={"error": f"Admin '{name}' already exists"})
    logger.info("Sub-admin created: name=%s id=%d", name, admin_id)
    return {"status": "created", "admin_id": admin_id, "name": name, "role": "sub"}


@router.delete(
    "/admin/admins/{admin_id}",
    summary="Delete a sub-admin",
    description="Deletes a sub-admin by id. Main admin cannot be deleted.",
    dependencies=[Depends(require_admin)],
)
async def delete_sub_admin(admin_id: int):
    """Delete a sub-admin account."""
    admin = database.get_admin_by_id(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})
    if admin.get("role") == "main":
        return JSONResponse(status_code=403, content={"error": "Cannot delete the main admin"})
    database.delete_admin(admin_id)
    logger.info("Sub-admin deleted: id=%d name=%s", admin_id, admin.get("name"))
    return {"status": "deleted", "admin_id": admin_id}


@router.put(
    "/admin/admins/{admin_id}/password",
    summary="Change sub-admin password",
    description="Update a sub-admin's password. Requires main admin auth.",
    dependencies=[Depends(require_admin)],
)
async def update_sub_admin_password(admin_id: int, body: _UpdateAdminPwdIn):
    """Change the password for a sub-admin."""
    admin = database.get_admin_by_id(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})
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
    dependencies=[Depends(require_admin)],
)
async def get_config_changes():
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
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
async def database_stats():
    """Return database size and content statistics."""
    try:
        return get_database_stats()
    except Exception as exc:
        logger.error("database_stats failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to get stats", "detail": str(exc)},
        )


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
    dependencies=[Depends(require_admin)],
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
async def test_email(body: _TestEmailIn):
    """Send a test HTML email to verify the email template."""
    import asyncio
    try:
        ok = await asyncio.get_running_loop().run_in_executor(
            None,
            send_alert_email,
            body.email,
            "Test Operator",
            37.5,
            38.0,
            "low",
            "WARNING",
            1,
            now_iso(),
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
            """SELECT a.id, a.name, a.role, a.company_id
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
                  created_at, updated_at
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
            }))
        except Exception as _be:
            logger.warning("parameter_added broadcast failed: %s", _be)
        log_activity(admin_id, "parameter_added", "company_parameters",
                     f"company_id:{company_id} name:{body.name}", company_id)
        logger.info("Super admin %d added parameter '%s' for company %d", admin_id, body.name, company_id)
        return JSONResponse(
            status_code=201,
            content={"status": "added", "message": f"Parameter '{body.name}' added successfully."},
        )

    # Regular admin: submit for approval
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
    logger.info("Admin %d requested delete_parameter '%s' (id=%d) for company %d",
                admin_id, param["name"], parameter_id, company_id)
    return {"status": "pending", "message": f"Deletion of '{param['name']}' submitted for super admin approval."}


@router.post(
    "/admin/test-sms",
    summary="Send a test SMS alert",
    description=(
        "Queues a test SMS to the given phone number through the GSM worker "
        "(same path as real alerts). Works in both LIVE mode (real modem) and "
        "MOCK mode (no modem — logs the SMS). "
        "Optional body field 'message' overrides the default test message. "
        "Requires admin auth. Body: {\"phone\": \"6385936224\"}"
    ),
    dependencies=[Depends(require_admin)],
)
async def test_sms(body: _TestSmsIn):
    """Send a test SMS via the GSM queue worker."""
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


@router.get("/admin/proserver/settings", dependencies=[Depends(require_admin)])
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


@router.post("/admin/proserver/settings", dependencies=[Depends(require_admin)])
def api_save_proserver_settings(body: _ProServerSettingsIn):
    """Save Pro-Server EX settings to DB and hot-reload the reader thread."""
    vals = {
        "file_path":     body.file_path.strip(),
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


@router.get("/admin/proserver/reading-status", dependencies=[Depends(require_admin)])
def api_proserver_reading_status():
    """Return current Excel reading enabled state and live/loop status."""
    import core.excel_sensor as excel_sensor
    return JSONResponse(excel_sensor.get_enabled_status())


@router.post("/admin/proserver/reading-enabled", dependencies=[Depends(require_admin)])
def api_set_proserver_reading_enabled(body: dict):
    """Enable or disable Excel reading. Watchdog keeps running when disabled."""
    import core.excel_sensor as excel_sensor
    enabled = bool(body.get("enabled", True))
    excel_sensor.set_enabled(enabled)
    return JSONResponse({"enabled": enabled})


@router.post("/admin/proserver/test", dependencies=[Depends(require_admin)])
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


@router.get("/admin/opc/settings", dependencies=[Depends(require_admin)])
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


@router.post("/admin/opc/settings", dependencies=[Depends(require_admin)])
def api_save_opc_settings(body: _OpcSettingsIn):
    """Save OPC DA settings to DB and hot-reload the reader thread."""
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


@router.get("/admin/opc/status", dependencies=[Depends(require_admin)])
def api_opc_status():
    """Return live OPC DA connection status."""
    import core.opc_sensor as opc_sensor
    return JSONResponse(opc_sensor.get_status())

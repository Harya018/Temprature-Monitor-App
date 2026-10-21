"""
routers/super_admin_v2.py — All Super Admin endpoints (merged from super_admin.py).

All routes require role = 'super_admin', enforced by require_super_admin.

Prefix: /api/super-admin
Tags:   Super Admin

Core company/alert routes (originally in super_admin.py):
  POST   /api/super-admin/companies                           Create a company
  GET    /api/super-admin/companies                           List all companies
  PATCH  /api/super-admin/companies/{id}/toggle               Toggle is_active
  POST   /api/super-admin/companies/{id}/assign-admin         Assign admin to company
  GET    /api/super-admin/companies/{id}/subscribers          List company subscribers
  GET    /api/super-admin/alerts                              Global alert log
  GET    /api/super-admin/company-parameters                  All parameters per company

Extended routes:
  GET    /api/super-admin/overview
  PATCH  /api/super-admin/companies/{id}
  DELETE /api/super-admin/companies/{id}
  GET    /api/super-admin/companies/{id}/admins
  GET    /api/super-admin/admins  ...  (full admin CRUD + many more)
"""

import csv
import io as _io
import json
import os
import psycopg2.errors
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

import database
from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from models import AssignAdminIn, CompanyIn, CompanyOut
from utils.logger import get_logger, _LOGS_DIR
from utils.security import hash_pin
from utils.rate_limiter import check_rate_limit, record_attempt, clear_failed_attempts, remaining_attempts
from utils.time import now_iso

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin", tags=["Super Admin"])


# ─── Auth dependency ──────────────────────────────────────────────────────────

def require_super_admin(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Allow only admins whose role = 'super_admin'. Enforces IP whitelist and 2FA."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token> header",
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty token")

    from database.queries.sessions import get_session
    session = get_session(token)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session token")

    rows = execute_read(
        """
        SELECT a.id, a.name, a.role, a.company_id,
               a.email, COALESCE(a.requires_2fa, 0) AS requires_2fa,
               COALESCE(s.two_fa_verified, 0) AS two_fa_verified
        FROM admins a
        JOIN admin_sessions s ON s.admin_id = a.id AND s.token = %s AND s.expires_at > NOW()
        WHERE a.role = 'super_admin'
        LIMIT 1
        """,
        (token,),
    )
    if not rows:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin role required")

    admin = rows[0]

    # IP whitelist (only enforced when whitelist is non-empty)
    try:
        whitelist = execute_read("SELECT ip FROM ip_whitelist")
        if whitelist:
            client_ip = request.client.host if request.client else "unknown"
            allowed = {row["ip"] for row in whitelist}
            if client_ip not in allowed:
                logger.warning("IP %s blocked by super-admin whitelist", client_ip)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: IP {client_ip} is not whitelisted",
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("IP whitelist check failed (non-fatal): %s", exc)

    # 2FA check
    if admin["requires_2fa"] and not admin["two_fa_verified"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "2fa_required", "message": "Two-factor authentication required"},
        )

    return admin


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _company_with_counts(row: dict) -> dict:
    """Augment a raw company row with admin_count and subscriber_count."""
    admin_count = execute_read(
        "SELECT COUNT(*) AS cnt FROM admins WHERE company_id = %s", (row["id"],)
    )
    subscriber_count = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s AND COALESCE(is_active, 1) = 1", (row["id"],)
    )
    return {
        **row,
        "is_active":        bool(row["is_active"]),
        "admin_count":      admin_count[0]["cnt"] if admin_count else 0,
        "subscriber_count": subscriber_count[0]["cnt"] if subscriber_count else 0,
    }


# ─── Pydantic bodies ──────────────────────────────────────────────────────────

class _CompanyUpdateIn(BaseModel):
    name:             Optional[str] = None
    description:      Optional[str] = None
    max_subscribers:  Optional[int] = None
    max_devices:      Optional[int] = None
    allowed_channels: Optional[str] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v


def _enforce_password_strength(pwd: str) -> str:
    """Raise ValueError if the password does not meet minimum complexity requirements."""
    import re as _re
    if len(pwd) < 10:
        raise ValueError("Password must be at least 10 characters")
    if not _re.search(r"[A-Z]", pwd):
        raise ValueError("Password must contain at least one uppercase letter")
    if not _re.search(r"[a-z]", pwd):
        raise ValueError("Password must contain at least one lowercase letter")
    if not _re.search(r"\d", pwd):
        raise ValueError("Password must contain at least one number")
    if not _re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", pwd):
        raise ValueError("Password must contain at least one special character")
    return pwd


class _AdminCreateIn(BaseModel):
    name:       str = Field(min_length=2, max_length=50)
    password:   str = Field(min_length=10, max_length=200)
    role:       str = Field(default="sub")
    company_id: Optional[int] = None

    @field_validator("name", "password", mode="before")
    @classmethod
    def strip_fields(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("password", mode="after")
    @classmethod
    def check_password_strength(cls, v):
        return _enforce_password_strength(v)


class _AdminPasswordIn(BaseModel):
    new_password: str = Field(min_length=10, max_length=200)

    @field_validator("new_password", mode="before")
    @classmethod
    def strip_pwd(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("new_password", mode="after")
    @classmethod
    def check_password_strength(cls, v):
        return _enforce_password_strength(v)


class _AdminCompanyIn(BaseModel):
    company_id: Optional[int] = None


class _BroadcastIn(BaseModel):
    title:   str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("title", "message", mode="before")
    @classmethod
    def strip_fields(cls, v):
        return v.strip() if isinstance(v, str) else v


class _SuperAdminLoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("username", "password", mode="before")
    @classmethod
    def strip_fields(cls, v):
        return v.strip() if isinstance(v, str) else v


# ─── Super Admin Login ────────────────────────────────────────────────────────

@router.post("/login", summary="Super admin login (DB-backed)")
@limiter.limit("10/minute")
async def super_admin_login(body: _SuperAdminLoginIn, request: Request):
    """
    Authenticate against the admins table (role = 'super_admin').
    Returns {token, username, two_fa_required} on success; 401 on bad credentials.
    Completely independent of the config-based ADMIN_USERNAME/ADMIN_PASSWORD.
    Phase 7: tracks every attempt in login_attempts; signals two_fa_required.
    """
    import secrets
    from utils.security import verify_pin

    client_ip = request.client.host if request.client else "unknown"
    username  = body.username.strip().lower()

    check_rate_limit(username, client_ip)  # Task 1: 429 if locked out

    rows = execute_read(
        "SELECT id, name, password_hash, company_id, COALESCE(requires_2fa, 0) AS requires_2fa FROM admins WHERE LOWER(name) = %s AND role = 'super_admin'",
        (username,),
    )

    if not rows or not verify_pin(body.password.strip(), rows[0]["password_hash"]):
        record_attempt(username, client_ip, False)  # Task 1: log failure
        return JSONResponse(
            status_code=401,
            content={
                "error": "InvalidCredentials",
                "message": "Invalid username or password",
                "remaining_attempts": remaining_attempts(username, client_ip),
            },
        )

    admin      = rows[0]
    token      = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)

    execute_write(
        "INSERT INTO admin_sessions (token, expires_at, admin_id) VALUES (%s, %s, %s)",
        (token, expires_at, admin["id"]),
    )
    # Task 2C: keep only the 3 most-recent sessions per super admin
    execute_write(
        """DELETE FROM admin_sessions
            WHERE admin_id = %s
              AND token NOT IN (
                  SELECT token FROM admin_sessions
                   WHERE admin_id = %s
                   ORDER BY created_at DESC
                   LIMIT 3
              )""",
        (admin["id"], admin["id"]),
    )

    clear_failed_attempts(username, client_ip)   # Task 1: clear prior failures
    record_attempt(username, client_ip, True)    # Task 1: log success

    try:
        execute_write(
            "UPDATE admins SET last_login_at = NOW(), last_login_ip = %s WHERE id = %s",
            (client_ip, admin["id"]),
        )
        from utils.activity_logger import log_activity
        log_activity(admin["id"], "login", "admin", f"ip:{client_ip}", admin.get("company_id"))
    except Exception as exc:
        logger.warning("super_admin_login tracking failed: %s", exc)

    logger.info("Super admin login: username=%s ip=%s 2fa=%s", admin["name"], client_ip, admin["requires_2fa"])
    return {
        "token": token,
        "username": admin["name"],
        "two_fa_required": bool(admin["requires_2fa"]),
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _week_str() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")


def _get_company_or_404(company_id: int) -> dict:
    rows = execute_read(
        "SELECT id, name, slug, is_active, description, max_subscribers, max_devices, allowed_channels, created_at::TEXT FROM companies WHERE id = %s",
        (company_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return rows[0]


def _get_admin_or_404(admin_id: int) -> dict:
    rows = execute_read(
        """
        SELECT a.id, a.name, a.role, a.company_id, a.is_active,
               a.last_login_at::TEXT, a.last_login_ip, a.created_at,
               c.name AS company_name
        FROM admins a
        LEFT JOIN companies c ON c.id = a.company_id
        WHERE a.id = %s
        """,
        (admin_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Admin {admin_id} not found")
    return rows[0]


# ─── Core company routes (originally in super_admin.py) ──────────────────────

@router.post("/companies", status_code=201, summary="Create a company")
@limiter.limit("30/minute")
async def create_company(
    body: CompanyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            "INSERT INTO companies (name, slug, is_active, created_at) VALUES (%s, %s, 1, NOW()) RETURNING id",
            (body.name, body.slug),
        )
        company_id = result.lastrowid
        row = execute_read(
            "SELECT id, name, slug, is_active, created_at::TEXT FROM companies WHERE id = %s",
            (company_id,),
        )
        return _company_with_counts(row[0])
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"A company with slug '{body.slug}' already exists")
    except Exception as exc:
        logger.error("create_company failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/companies", summary="List all companies")
@limiter.limit("60/minute")
async def list_companies(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            "SELECT id, name, slug, is_active, COALESCE(maintenance_mode, 0) AS maintenance_mode, created_at::TEXT FROM companies ORDER BY id ASC"
        )
        return [_company_with_counts(r) for r in rows]
    except Exception as exc:
        logger.error("list_companies failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.patch("/companies/{company_id}/toggle", summary="Toggle company active status")
@limiter.limit("30/minute")
async def toggle_company(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        execute_write(
            "UPDATE companies SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = %s",
            (company_id,),
        )
        from services.sensor_company import invalidate_caches
        invalidate_caches()           # a switched-off company stops owning live feeds at once
        row = execute_read(
            "SELECT id, name, slug, is_active, created_at::TEXT FROM companies WHERE id = %s",
            (company_id,),
        )
        return _company_with_counts(row[0])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("toggle_company failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/companies/{company_id}/assign-admin", summary="Assign an admin to a company")
@limiter.limit("30/minute")
async def assign_admin(
    company_id: int,
    body: AssignAdminIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        admin_rows = execute_read("SELECT id, name, role FROM admins WHERE id = %s", (body.admin_id,))
        if not admin_rows:
            raise HTTPException(status_code=404, detail=f"Admin {body.admin_id} not found")
        if admin_rows[0].get("role") == "super_admin":
            raise HTTPException(status_code=422, detail="A Super Admin account cannot be tied to one company")
        execute_write("UPDATE admins SET company_id = %s WHERE id = %s", (company_id, body.admin_id))
        return {
            "message":    f"Admin '{admin_rows[0]['name']}' assigned to company {company_id}",
            "admin_id":   body.admin_id,
            "company_id": company_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("assign_admin failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/companies/{company_id}/subscribers", summary="List subscribers for a company")
@limiter.limit("60/minute")
async def list_company_subscribers(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        rows = execute_read(
            """SELECT id, name, phone, email, escalation_order, active, is_active, created_at, company_id
               FROM subscribers WHERE company_id = %s ORDER BY escalation_order ASC""",
            (company_id,),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_company_subscribers failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/alerts", summary="Global alert log (all companies)")
@limiter.limit("60/minute")
async def global_alerts(
    request: Request,
    limit: int = 100,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """SELECT a.id, a.parameter, a.value, a.threshold, a.direction, a.severity,
                      a.timestamp, a.acknowledged, a.acknowledged_by, a.company_id,
                      COALESCE(c.name, 'Unassigned') AS company_name,
                      COALESCE(c.slug, '')           AS company_slug
               FROM alerts a
               LEFT JOIN companies c ON c.id = a.company_id
               ORDER BY a.id DESC LIMIT %s""",
            (limit,),
        )
        return rows
    except Exception as exc:
        logger.error("global_alerts failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/company-parameters", summary="All parameters per company")
async def company_parameters(
    _admin: dict = Depends(require_super_admin),
):
    try:
        companies = execute_read("SELECT id, name, slug, is_active FROM companies ORDER BY id")
        if not companies:
            return []
        custom_rows = execute_read(
            """SELECT company_id, name, unit, min_value, max_value, created_at
               FROM company_parameters WHERE is_active = TRUE ORDER BY company_id, name"""
        )
        custom_by_company: dict = defaultdict(list)
        for r in (custom_rows or []):
            cid = r["company_id"]
            custom_by_company[cid].append({
                "name":       r["name"],
                "unit":       r["unit"] or "",
                "min_value":  float(r["min_value"]) if r.get("min_value") is not None else None,
                "max_value":  float(r["max_value"]) if r.get("max_value") is not None else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "builtin":    False,
            })
        result = []
        for co in companies:
            cid = co["id"]
            # Temperature is a normal per-company parameter now — no built-in row
            params = custom_by_company.get(cid, [])
            result.append({"company_id": cid, "company_name": co["name"],
                           "is_active": co["is_active"], "parameters": params})
        return result
    except Exception as exc:
        logger.error("company_parameters failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ─── Overview ─────────────────────────────────────────────────────────────────

@router.get("/overview", summary="Dashboard overview stats")
@limiter.limit("60/minute")
async def overview(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    today = _today_str()
    week  = _week_str()

    try:
        # All 10 scalar stats in one round trip (was 10 serial queries)
        s = execute_read(
            """
            SELECT
                (SELECT COUNT(*)::int FROM companies)                                              AS total_companies,
                (SELECT COUNT(*)::int FROM admins WHERE is_active = 1 OR is_active IS NULL)        AS active_admins,
                (SELECT COUNT(*)::int FROM admins WHERE is_active = 0)                             AS suspended_admins,
                (SELECT COUNT(*)::int FROM subscribers WHERE is_active = 1 OR is_active IS NULL)   AS total_subs,
                (SELECT COUNT(*)::int FROM alerts WHERE timestamp >= %s)                           AS alerts_today,
                (SELECT COUNT(*)::int FROM alerts WHERE timestamp >= %s)                           AS alerts_week,
                (SELECT COUNT(*)::int FROM pending_approvals WHERE status = 'pending')             AS pending_approvals,
                (SELECT COUNT(*)::int FROM admin_sessions WHERE expires_at > NOW())                AS active_sessions,
                (SELECT COUNT(*)::int FROM readings WHERE timestamp >= %s)                         AS readings_today,
                (SELECT COUNT(*)::int FROM companies WHERE COALESCE(maintenance_mode, 0) = 1)      AS maintenance_cos
            """,
            (today, week, today),
        )[0]

        # Company rows: use aggregated JOINs instead of correlated subqueries per row
        company_rows = execute_read(
            """
            SELECT c.id, c.name, c.is_active,
                   COALESCE(c.maintenance_mode, 0)    AS maintenance_mode,
                   COALESCE(c.maintenance_reason, '') AS maintenance_reason,
                   COALESCE(s_cnt.cnt, 0)             AS subscriber_count,
                   COALESCE(a_cnt.cnt, 0)             AS alerts_today
            FROM companies c
            LEFT JOIN (
                SELECT company_id, COUNT(*) AS cnt FROM subscribers WHERE COALESCE(is_active, 1) = 1 GROUP BY company_id
            ) s_cnt ON s_cnt.company_id = c.id
            LEFT JOIN (
                SELECT company_id, COUNT(*) AS cnt FROM alerts WHERE timestamp >= %s GROUP BY company_id
            ) a_cnt ON a_cnt.company_id = c.id
            ORDER BY c.id
            """,
            (today,),
        )

        recent_alerts = execute_read(
            """
            SELECT a.id, a.parameter, a.value, a.severity, a.direction,
                   a.timestamp::TEXT,
                   COALESCE(c.name, 'Unassigned') AS company_name
            FROM alerts a
            LEFT JOIN companies c ON c.id = a.company_id
            ORDER BY a.id DESC
            LIMIT 6
            """
        )

        pending_list = execute_read(
            """
            SELECT pa.id, pa.action_type, pa.payload, pa.created_at::TEXT,
                   a.name  AS admin_name,
                   co.name AS company_name
            FROM pending_approvals pa
            JOIN admins a ON a.id = pa.admin_id
            LEFT JOIN companies co ON co.id = a.company_id
            WHERE pa.status = 'pending'
            ORDER BY pa.created_at DESC
            LIMIT 5
            """
        )

        return {
            "total_companies":       s["total_companies"],
            "active_admins":         s["active_admins"],
            "total_subscribers":     s["total_subs"],
            "alerts_today":          s["alerts_today"],
            "alerts_week":           s["alerts_week"],
            "pending_approvals":     s["pending_approvals"],
            "active_sessions":       s["active_sessions"],
            "readings_today":        s["readings_today"],
            "suspended_admins":      s["suspended_admins"],
            "maintenance_companies": s["maintenance_cos"],
            "companies":             company_rows,
            "recent_alerts":         recent_alerts,
            "pending_list":          pending_list,
        }
    except Exception as exc:
        logger.error("overview failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Companies ────────────────────────────────────────────────────────────────

@router.patch("/companies/{company_id}", summary="Edit a company")
@limiter.limit("30/minute")
async def update_company(
    company_id: int,
    body: _CompanyUpdateIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        sets, params = [], []
        if body.name is not None:
            sets.append("name = %s"); params.append(body.name)
        if body.description is not None:
            sets.append("description = %s"); params.append(body.description)
        if body.max_subscribers is not None:
            sets.append("max_subscribers = %s"); params.append(body.max_subscribers)
        if body.max_devices is not None:
            sets.append("max_devices = %s"); params.append(body.max_devices)
        if body.allowed_channels is not None:
            sets.append("allowed_channels = %s"); params.append(body.allowed_channels)
        if not sets:
            return JSONResponse(status_code=422, content={"error": "No fields to update"})
        params.append(company_id)
        execute_write(f"UPDATE companies SET {', '.join(sets)} WHERE id = %s", tuple(params))
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], company_id, f"update_company:{company_id}", "company", "low",
                   f"fields={','.join(sets)}", ip)
        return _get_company_or_404(company_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_company failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/companies/{company_id}/detail", summary="Full company detail — all data end-to-end")
@limiter.limit("60/minute")
async def get_company_detail(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        today = _today_str()
        week  = _week_str()

        # Core company row
        rows = execute_read(
            """
            SELECT c.id, c.name, c.slug, c.description,
                   COALESCE(c.is_active, 0)         AS is_active,
                   COALESCE(c.maintenance_mode, 0)  AS maintenance_mode,
                   COALESCE(c.maintenance_reason,'') AS maintenance_reason,
                   COALESCE(c.max_subscribers, 100) AS max_subscribers,
                   COALESCE(c.max_devices, 10)       AS max_devices,
                   COALESCE(c.allowed_channels,'sms,email,push') AS allowed_channels,
                   c.created_at::TEXT,
                   COALESCE(st.name,'Free')          AS tier_name,
                   COALESCE(c.sms_used_this_month,0) AS sms_used,
                   COALESCE(c.email_used_this_month,0) AS email_used,
                   COALESCE(c.push_used_this_month,0)  AS push_used
            FROM companies c
            LEFT JOIN subscription_tiers st ON st.id = c.tier_id
            WHERE c.id = %s
            """,
            (company_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Company not found")
        company = rows[0]

        # Admins
        admins = execute_read(
            """
            SELECT id, name, role, email, COALESCE(is_active,1) AS is_active,
                   last_login_at::TEXT, last_login_ip, created_at::TEXT
            FROM admins WHERE company_id = %s ORDER BY id
            """,
            (company_id,),
        )

        # Subscribers
        subscribers = execute_read(
            """
            SELECT id, name, phone, email, escalation_order,
                   COALESCE(is_active,1) AS is_active, created_at::TEXT
            FROM subscribers WHERE company_id = %s ORDER BY escalation_order
            """,
            (company_id,),
        )

        # Parameters: Temperature (always built-in) + active company_parameters rows
        custom_params = execute_read(
            """
            SELECT id, name, unit, min_value, max_value,
                   COALESCE(is_active, false) AS is_active, created_at::TEXT
            FROM company_parameters WHERE company_id = %s AND is_active = TRUE ORDER BY name
            """,
            (company_id,),
        )
        # Exactly the company's own parameters (temperature included only if
        # the company has it) — a new company shows none.
        parameters = [dict(p, builtin=False) for p in custom_params]

        # Alert stats
        alert_stats = execute_read(
            """
            SELECT
                COUNT(*)                                                      AS total_alerts,
                SUM(CASE WHEN timestamp >= %s THEN 1 ELSE 0 END)             AS alerts_today,
                SUM(CASE WHEN timestamp >= %s THEN 1 ELSE 0 END)             AS alerts_week,
                SUM(CASE WHEN UPPER(severity) IN ('CRITICAL','EMERGENCY') THEN 1 ELSE 0 END) AS critical,
                SUM(CASE WHEN UPPER(severity) = 'WARNING' THEN 1 ELSE 0 END) AS warning,
                SUM(CASE WHEN acknowledged=1 THEN 1 ELSE 0 END)              AS acknowledged
            FROM alerts WHERE company_id = %s
            """,
            (today, week, company_id),
        )

        # Reading stats — readings has ~8M rows and no company index, so avoid
        # full scans: today's figures use the timestamp index (ISO text compares
        # in order), the last reading walks that index backwards, and the
        # all-time total is the planner's row estimate scaled by this company's
        # share of the last 7 days (exact counts took ~8 s per page load).
        reading_stats = execute_read(
            """
            SELECT
                COUNT(*)                                    AS readings_today,
                MIN(temperature)::FLOAT                     AS min_temp,
                MAX(temperature)::FLOAT                     AS max_temp,
                ROUND(AVG(temperature)::NUMERIC, 2)::FLOAT  AS avg_temp
            FROM readings WHERE timestamp >= %s AND company_id = %s
            """,
            (today, company_id),
        )
        reading_stats = dict(reading_stats[0]) if reading_stats else {}
        last = execute_read(
            "SELECT timestamp::TEXT AS ts FROM readings WHERE company_id = %s "
            "ORDER BY timestamp DESC LIMIT 1",
            (company_id,),
        )
        reading_stats["last_reading_at"] = last[0]["ts"] if last else None
        share = execute_read(
            """
            SELECT COUNT(*) FILTER (WHERE company_id = %s)::FLOAT / NULLIF(COUNT(*), 0) AS share,
                   (SELECT reltuples::BIGINT FROM pg_class WHERE relname = 'readings' AND relnamespace = current_schema()::regnamespace) AS est
            FROM readings WHERE timestamp >= %s
            """,
            (company_id, week),
        )
        if share and share[0]["est"] is not None:
            frac = share[0]["share"] if share[0]["share"] is not None else 1.0
            reading_stats["total_readings"] = int(max(share[0]["est"], 0) * frac)
        else:
            reading_stats["total_readings"] = None
        reading_stats["total_is_estimate"] = True

        # Active sessions for admins in this company
        sessions = execute_read(
            """
            SELECT s.id, s.created_at::TEXT, s.expires_at::TEXT, s.last_used_at::TEXT,
                   a.name AS admin_name, a.role AS admin_role
            FROM admin_sessions s
            JOIN admins a ON a.id = s.admin_id
            WHERE a.company_id = %s AND s.expires_at > NOW()
            ORDER BY s.last_used_at DESC LIMIT 20
            """,
            (company_id,),
        )

        # Recent alerts (last 10)
        recent_alerts = execute_read(
            """
            SELECT id, parameter, value, threshold, direction, severity,
                   timestamp::TEXT, acknowledged
            FROM alerts WHERE company_id = %s ORDER BY id DESC LIMIT 10
            """,
            (company_id,),
        )

        return {
            "company":       company,
            "admins":        admins,
            "subscribers":   subscribers,
            "parameters":    parameters,
            "alert_stats":   alert_stats[0] if alert_stats else {},
            "reading_stats": reading_stats,
            "sessions":      sessions,
            "recent_alerts": recent_alerts,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_company_detail failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.delete("/companies/{company_id}", summary="Delete a company")
@limiter.limit("10/minute")
async def delete_company(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        sub_count = execute_read("SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s", (company_id,))[0]["cnt"]
        adm_count = execute_read("SELECT COUNT(*) AS cnt FROM admins WHERE company_id = %s AND role != 'super_admin'", (company_id,))[0]["cnt"]
        if sub_count > 0 or adm_count > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete: company has {sub_count} subscriber(s) and {adm_count} admin(s). Reassign or delete them first.",
            )
        co = _get_company_or_404(company_id)
        execute_write("DELETE FROM companies WHERE id = %s", (company_id,))
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], None, f"delete_company:{company_id}", "company", "high",
                   f"name={co['name']}", ip)
        return {"status": "deleted", "company_id": company_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_company failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


def _archive_company_files(company_id: int, slug) -> None:
    """Move the company's CSV tables and activity log out of the live folders into
    data/offboarded/<name>_<time>/ (nothing is deleted, but nothing stays where another company's
    tools could pick it up)."""
    import shutil
    from datetime import datetime as _dt
    from pathlib import Path as _P
    from services import reading_csv, company_log
    stamp = _dt.now().strftime("%Y%m%d_%H%M%S")
    dest_root = _P(reading_csv.CSV_DIR).parent / "offboarded"
    moves = []
    folder = reading_csv.company_folder(company_id)
    if folder != reading_csv.CSV_DIR and _P(folder).is_dir():
        moves.append((_P(folder), dest_root / f"{_P(folder).name}_{stamp}"))
    log_dir = _P(company_log.LOG_DIR)
    for lf in log_dir.glob(f"company_{int(company_id)}.log*"):
        moves.append((lf, dest_root / f"company_{int(company_id)}_{stamp}" / lf.name))
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    company_log._loggers.pop(int(company_id), None)
    reading_csv._folder_cache.pop(company_id, None)


@router.delete("/companies/{company_id}/offboard", summary="Full cascade offboard — deletes all company data")
@limiter.limit("5/minute")
async def offboard_company(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Irreversibly purges all data belonging to the company in FK-safe order:
    subscriber sessions → delivery receipts → escalation log → retry queue
    → alerts → readings → subscribers → admin sessions → admins
    → remaining NO ACTION children → company row.

    Alert acknowledgements are columns on `alerts`, so they are removed with it.
    """
    from database.connection import get_db_pool
    pool = get_db_pool()
    conn = pool.getconn()
    cur = conn.cursor()

    def execute_write(sql, params=()):          # every step below runs in ONE transaction
        cur.execute(sql, params)

    try:
        co = _get_company_or_404(company_id)
        try:   # which live sources are this company's (must be known before it is deleted)
            from services.sensor_company import sources_owned_by
            _owned_sources = sources_owned_by(company_id)
        except Exception:
            _owned_sources = None

        # 1. Subscriber sessions for subscribers of this company
        execute_write(
            """
            DELETE FROM subscriber_sessions
             WHERE subscriber_id IN (SELECT id FROM subscribers WHERE company_id = %s)
            """,
            (company_id,),
        )

        # 2. Delivery receipts for alerts of this company
        execute_write(
            """
            DELETE FROM delivery_receipts
             WHERE alert_id IN (SELECT id FROM alerts WHERE company_id = %s)
            """,
            (company_id,),
        )

        # 3. Escalation log rows for subscribers of this company
        execute_write(
            """
            DELETE FROM escalation_log
             WHERE subscriber_id IN (SELECT id FROM subscribers WHERE company_id = %s)
            """,
            (company_id,),
        )

        # 4. Retry queue entries for alerts of this company
        execute_write(
            """
            DELETE FROM notification_retry_queue
             WHERE alert_id IN (SELECT id FROM alerts WHERE company_id = %s)
            """,
            (company_id,),
        )

        # 5. Alerts
        execute_write("DELETE FROM alerts WHERE company_id = %s", (company_id,))

        # 6. Readings
        execute_write("DELETE FROM readings WHERE company_id = %s", (company_id,))

        # 7. Subscribers
        execute_write("DELETE FROM subscribers WHERE company_id = %s", (company_id,))

        # 8. Admin sessions for admins of this company
        execute_write(
            """
            DELETE FROM admin_sessions
             WHERE admin_id IN (
                SELECT id FROM admins WHERE company_id = %s AND role != 'super_admin'
             )
            """,
            (company_id,),
        )

        # 8b. Approval requests made by (or about) this company
        execute_write(
            """
            DELETE FROM pending_approvals
             WHERE admin_id IN (SELECT id FROM admins WHERE company_id = %s AND role != 'super_admin')
                OR (payload->>'company_id') = %s
            """,
            (company_id, str(company_id)),
        )

        # 9. Admins (excluding super_admin, which has no company_id)
        execute_write(
            "DELETE FROM admins WHERE company_id = %s AND role != 'super_admin'",
            (company_id,),
        )

        # 10. Remaining company-owned rows whose FK is ON DELETE NO ACTION —
        # these would otherwise raise a foreign-key violation on step 11.
        # (CASCADE / SET NULL children are handled by PostgreSQL automatically.)
        for _tbl in (
            "company_config",
            "company_messages",
            "company_notes",
            "company_onboarding",
            "company_subscriptions",
            "incident_reports",
            "usage_snapshots",
        ):
            execute_write(f"DELETE FROM {_tbl} WHERE company_id = %s", (company_id,))

        # 10b. Activity rows have no foreign key, so they would stay behind
        execute_write("DELETE FROM admin_activity WHERE company_id = %s", (company_id,))

        # 11. Company row
        execute_write("DELETE FROM companies WHERE id = %s", (company_id,))
        conn.commit()                           # all-or-nothing

        # Outside the database: its live feeds, live dashboards, cached settings and files
        try:
            import asyncio as _aio
            from services.sensor_company import release_company
            stopped = await _aio.to_thread(release_company, company_id, _owned_sources)
            if stopped:
                logger.warning("Offboard company %s: switched off live source(s): %s", company_id, ", ".join(stopped))
            from services.live_ingest import forget_parameters
            forget_parameters(company_id)
            from modules.inapp.manager import close_company_connections
            await close_company_connections(company_id)
            _archive_company_files(company_id, co.get("slug"))
        except Exception as _post_exc:
            logger.warning("Offboard company %s: clean-up after delete was incomplete: %s", company_id, _post_exc)

        ip = request.client.host if request.client else "unknown"
        _log_audit(
            _admin["id"], None, f"offboard_company:{company_id}", "company", "critical",
            f"full cascade delete — name={co['name']}", ip,
        )
        logger.warning(
            "Company %d (%s) fully offboarded by super admin %d from %s",
            company_id, co["name"], _admin["id"], ip,
        )
        return {"status": "offboarded", "company_id": company_id, "company_name": co["name"]}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()                         # nothing is half-deleted
        logger.error("internal error: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"error": "An internal error occurred"})
    finally:
        pool.putconn(conn)


@router.get("/companies/{company_id}/admins", summary="List admins for a company")
@limiter.limit("60/minute")
async def list_company_admins(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        rows = execute_read(
            """
            SELECT id, name, role, is_active, last_login_at::TEXT, created_at
            FROM admins WHERE company_id = %s ORDER BY id
            """,
            (company_id,),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_company_admins failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Admins ───────────────────────────────────────────────────────────────────

@router.get("/admins", summary="List all admins")
@limiter.limit("60/minute")
async def list_admins(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    week = _week_str()
    try:
        rows = execute_read(
            """
            SELECT
                a.id, a.name, a.role,
                a.is_active,
                a.last_login_at::TEXT AS last_login_at,
                a.last_login_ip,
                a.created_at,
                a.company_id,
                c.name AS company_name,
                (
                    SELECT COUNT(*) FROM admin_activity act
                    WHERE act.admin_id = a.id AND act.created_at >= %s
                ) AS actions_7d
            FROM admins a
            LEFT JOIN companies c ON c.id = a.company_id
            ORDER BY a.role DESC, a.id ASC
            """,
            (week,),
        )
        return rows
    except Exception as exc:
        logger.error("list_admins failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


def _admin_name_problem(name: str) -> Optional[str]:
    """Sign-in names must be unique however they are typed ("Ravi" = "ravi" = "ravi ") and must not be
    one of the built-in sign-in names, or one person could end up signing in to another's account."""
    import config as _c
    n = (name or "").strip()
    reserved = {"superadmin", "super_admin", "super admin", str(getattr(_c, "ADMIN_USERNAME", "admin")).lower(), "admin"}
    if n.lower() in reserved:
        return f"'{n}' is reserved. Choose another sign-in name."
    if execute_read("SELECT 1 FROM admins WHERE LOWER(TRIM(name)) = LOWER(%s) LIMIT 1", (n,)):
        return f"Admin '{n}' already exists (names are not case-sensitive)."
    return None


@router.post("/admins", status_code=201, summary="Create an admin")
@limiter.limit("20/minute")
async def create_admin(
    body: _AdminCreateIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        if body.role not in ("main", "sub", "super_admin"):
            return JSONResponse(status_code=422, content={"error": "role must be main, sub, or super_admin"})
        problem = _admin_name_problem(body.name)
        if problem:
            return JSONResponse(status_code=409, content={"error": problem})
        # A company admin without a company would be treated as "no company = everything",
        # so every non-Super-Admin account must belong to an existing company.
        if body.role != "super_admin":
            if not body.company_id:
                return JSONResponse(status_code=422, content={"error": "Choose the company this admin belongs to"})
            if not execute_read("SELECT 1 FROM companies WHERE id = %s", (body.company_id,)):
                return JSONResponse(status_code=404, content={"error": "Company not found"})
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        result = execute_write(
            "INSERT INTO admins (name, password_hash, role, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
            (body.name, hash_pin(body.password), body.role, ts),
        )
        if body.company_id:
            execute_write("UPDATE admins SET company_id = %s WHERE id = %s", (body.company_id, result.lastrowid))
        logger.info("Admin created by super_admin: name=%s role=%s", body.name, body.role)
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], body.company_id, f"create_admin:{body.name}", "admin", "medium",
                   f"role={body.role}", ip)
        return _get_admin_or_404(result.lastrowid)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return JSONResponse(status_code=409, content={"error": f"Admin '{body.name}' already exists"})
        logger.error("create_admin failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/admins/{admin_id}", summary="Admin detail")
@limiter.limit("60/minute")
async def get_admin_detail(
    admin_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        admin = _get_admin_or_404(admin_id)
        company = None
        if admin.get("company_id"):
            rows = execute_read(
                "SELECT id, name, slug, description, max_subscribers, max_devices, allowed_channels FROM companies WHERE id = %s",
                (admin["company_id"],),
            )
            company = rows[0] if rows else None

        subs = []
        if admin.get("company_id"):
            subs = execute_read(
                """
                SELECT id, name, phone, email, escalation_order, is_active
                FROM subscribers WHERE company_id = %s ORDER BY escalation_order
                """,
                (admin["company_id"],),
            )

        return {**admin, "company": company, "subscribers": subs}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_admin_detail failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.patch("/admins/{admin_id}/toggle", summary="Toggle admin active status")
@limiter.limit("30/minute")
async def toggle_admin(
    admin_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        admin = _get_admin_or_404(admin_id)
        if admin.get("role") == "super_admin":
            return JSONResponse(status_code=403, content={"error": "Cannot deactivate a super_admin"})
        execute_write(
            "UPDATE admins SET is_active = CASE WHEN is_active = 1 OR is_active IS NULL THEN 0 ELSE 1 END WHERE id = %s",
            (admin_id,),
        )
        updated = _get_admin_or_404(admin_id)
        new_state = "disabled" if updated.get("is_active") == 0 else "enabled"
        if updated.get("is_active") == 0:
            execute_write("DELETE FROM admin_sessions WHERE admin_id = %s", (admin_id,))
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], admin.get("company_id"), f"toggle_admin:{admin_id}",
                   "admin", "medium", f"name={admin['name']} state={new_state}", ip)
        return updated
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("toggle_admin failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.put("/admins/{admin_id}/password", summary="Reset admin password")
@limiter.limit("20/minute")
async def reset_admin_password(
    admin_id: int,
    body: _AdminPasswordIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_admin_or_404(admin_id)
        execute_write(
            "UPDATE admins SET password_hash = %s WHERE id = %s",
            (hash_pin(body.new_password), admin_id),
        )
        execute_write("DELETE FROM admin_sessions WHERE admin_id = %s", (admin_id,))
        logger.info("Password reset for admin id=%d", admin_id)
        ip = request.client.host if request.client else "unknown"
        a = _get_admin_or_404(admin_id)
        _log_audit(_admin["id"], a.get("company_id"), f"reset_password:{admin_id}",
                   "admin", "high", f"name={a['name']}", ip)
        return {"status": "updated", "admin_id": admin_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reset_admin_password failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.patch("/admins/{admin_id}/company", summary="Assign admin to company")
@limiter.limit("30/minute")
async def assign_admin_company(
    admin_id: int,
    body: _AdminCompanyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        before = _get_admin_or_404(admin_id)
        if before.get("role") == "super_admin":
            return JSONResponse(status_code=403, content={"error": "The Super Admin does not belong to a company"})
        if body.company_id is None:
            return JSONResponse(status_code=422, content={"error": "Choose the company this admin belongs to"})
        rows = execute_read("SELECT id FROM companies WHERE id = %s", (body.company_id,))
        if not rows:
            raise HTTPException(status_code=404, detail=f"Company {body.company_id} not found")
        if before.get("company_id") == body.company_id:
            return before
        execute_write("UPDATE admins SET company_id = %s WHERE id = %s", (body.company_id, admin_id))
        # signed out everywhere: pages and live dashboards opened for the old company must not stay open
        execute_write("DELETE FROM admin_sessions WHERE admin_id = %s", (admin_id,))
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], body.company_id, f"move_admin:{admin_id}", "admin", "high",
                   f"name={before['name']} from_company={before.get('company_id')} to_company={body.company_id}", ip)
        return _get_admin_or_404(admin_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("assign_admin_company failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/admins/{admin_id}/activity", summary="Admin activity log")
@limiter.limit("60/minute")
async def admin_activity_log(
    admin_id: int,
    request: Request,
    action: Optional[str] = None,
    limit: int = 100,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_admin_or_404(admin_id)
        if action:
            rows = execute_read(
                "SELECT id, action, entity, details, created_at::TEXT FROM admin_activity WHERE admin_id = %s AND action = %s ORDER BY id DESC LIMIT %s",
                (admin_id, action, limit),
            )
        else:
            rows = execute_read(
                "SELECT id, action, entity, details, created_at::TEXT FROM admin_activity WHERE admin_id = %s ORDER BY id DESC LIMIT %s",
                (admin_id, limit),
            )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin_activity_log failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/admins/{admin_id}/subscribers", summary="Subscribers under admin's company")
@limiter.limit("60/minute")
async def admin_subscribers(
    admin_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        admin = _get_admin_or_404(admin_id)
        if not admin.get("company_id"):
            return []
        rows = execute_read(
            """
            SELECT id, name, phone, email, escalation_order, is_active
            FROM subscribers WHERE company_id = %s ORDER BY escalation_order
            """,
            (admin["company_id"],),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin_subscribers failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Broadcast ────────────────────────────────────────────────────────────────

@router.post("/broadcast", status_code=201, summary="Send a broadcast message")
@limiter.limit("10/minute")
async def send_broadcast(
    body: _BroadcastIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            "INSERT INTO broadcasts (title, message, sent_by, created_at) VALUES (%s, %s, %s, NOW()) RETURNING id",
            (body.title, body.message, _admin.get("name", "super_admin")),
        )
        row = execute_read("SELECT id, title, message, sent_by, created_at::TEXT FROM broadcasts WHERE id = %s", (result.lastrowid,))
        logger.info("Broadcast sent by %s: %s", _admin.get("name"), body.title)
        return row[0] if row else {"status": "sent"}
    except Exception as exc:
        logger.error("send_broadcast failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/broadcast", summary="Broadcast history")
@limiter.limit("60/minute")
async def broadcast_history(
    request: Request,
    limit: int = 20,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            "SELECT id, title, message, sent_by, created_at::TEXT FROM broadcasts ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return rows
    except Exception as exc:
        logger.error("broadcast_history failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Sessions ─────────────────────────────────────────────────────────────────

@router.get("/sessions", summary="Active admin sessions")
@limiter.limit("30/minute")
async def active_sessions(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT
                s.id, s.token,
                s.created_at::TEXT,
                s.expires_at::TEXT,
                s.last_used_at::TEXT,
                a.name AS admin_name,
                a.role AS admin_role,
                c.name AS company_name
            FROM admin_sessions s
            LEFT JOIN admins a ON a.last_login_ip IS NOT NULL
            LEFT JOIN companies c ON c.id = a.company_id
            WHERE s.expires_at > NOW()
            ORDER BY s.last_used_at DESC
            LIMIT 50
            """
        )
        # Mask the token — show only last 8 chars
        for r in rows:
            if r.get("token"):
                r["token"] = "…" + r["token"][-8:]
        return rows
    except Exception as exc:
        logger.error("active_sessions failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Live Feed ────────────────────────────────────────────────────────────────

@router.get("/live-feed", summary="Live sensor readings per company")
@limiter.limit("60/minute")
async def live_feed(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        latest = execute_read(
            "SELECT temperature, timestamp FROM readings ORDER BY id DESC LIMIT 1"
        )
        if not latest:
            return []

        reading = latest[0]
        companies = execute_read(
            "SELECT id, name FROM companies WHERE is_active = 1 ORDER BY id"
        )

        # Determine status based on global thresholds
        from config import RUNTIME_THRESHOLDS
        temp = reading["temperature"]
        t_high = RUNTIME_THRESHOLDS.get("temp_high")
        t_low  = RUNTIME_THRESHOLDS.get("temp_low")
        status = "normal"
        if t_high and temp > t_high:
            status = "critical" if temp > t_high * 1.1 else "warning"
        elif t_low and temp < t_low:
            status = "warning"

        return [
            {
                "company_id":   c["id"],
                "company_name": c["name"],
                "device":       "Temperature Sensor",
                "parameter":    "temperature",
                "value":        temp,
                "timestamp":    reading["timestamp"],
                "status":       status,
            }
            for c in companies
        ] or [
            {
                "company_id":   None,
                "company_name": "Global",
                "device":       "Temperature Sensor",
                "parameter":    "temperature",
                "value":        temp,
                "timestamp":    reading["timestamp"],
                "status":       status,
            }
        ]
    except Exception as exc:
        logger.error("live_feed failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 1: Audit log helper ─────────────────────────────────────────────────

def _log_audit(admin_id: int, company_id, action: str, category: str,
               severity: str, details: str, ip: str = "unknown"):
    try:
        execute_write(
            """INSERT INTO audit_log (admin_id, company_id, action, category, severity, details, ip_address)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (admin_id, company_id, action, category, severity, details, ip),
        )
    except Exception as exc:
        logger.warning("_log_audit failed (non-fatal): %s", exc)


# ─── Tier 1: Company Health Grid ─────────────────────────────────────────────

@router.get("/companies/health", summary="Traffic-light health status for every company")
@limiter.limit("60/minute")
async def companies_health(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Returns one row per company with:
      - last_reading_at + minutes_since_reading
      - flatline flag (active & !maintenance & no reading >30 min)
      - unack_critical / unack_warning / unack_total counts
      - alerts_today count
      - health: 'red' | 'yellow' | 'green'
    """
    try:
        today = _today_str()
        # Use CTEs so each table is aggregated independently before joining.
        # The old 4-way JOIN created a cross-product before GROUP BY which grew
        # exponentially with row counts, causing very slow or hanging queries.
        rows = execute_read(
            """
            WITH alert_stats AS (
                SELECT company_id,
                       COUNT(*) FILTER (WHERE (acknowledged = 0 OR acknowledged IS NULL)
                                          AND UPPER(severity) IN ('CRITICAL','EMERGENCY')) AS unack_critical,
                       COUNT(*) FILTER (WHERE (acknowledged = 0 OR acknowledged IS NULL)
                                          AND UPPER(severity) = 'WARNING') AS unack_warning,
                       COUNT(*) FILTER (WHERE  acknowledged = 0 OR acknowledged IS NULL) AS unack_total,
                       COUNT(*) FILTER (WHERE  timestamp >= %s)           AS alerts_today
                FROM   alerts
                GROUP  BY company_id
            ),
            sub_stats AS (
                SELECT company_id,
                       COUNT(*) FILTER (WHERE is_active IS NULL OR is_active = 1) AS subscriber_count
                FROM   subscribers
                GROUP  BY company_id
            ),
            admin_stats AS (
                SELECT company_id,
                       COUNT(*) FILTER (WHERE role != 'super_admin'
                                          AND (is_active IS NULL OR is_active = 1)) AS admin_count
                FROM   admins
                GROUP  BY company_id
            )
            SELECT c.id,
                   c.name,
                   c.slug,
                   COALESCE(c.is_active,        1)  AS is_active,
                   COALESCE(c.maintenance_mode,  0)  AS maintenance_mode,
                   COALESCE(c.maintenance_reason, '') AS maintenance_reason,
                   rs.last_reading_at,
                   EXTRACT(EPOCH FROM (NOW() - rs.last_reading_at)) / 60 AS minutes_since_reading,
                   COALESCE(als.unack_critical,  0)  AS unack_critical,
                   COALESCE(als.unack_warning,   0)  AS unack_warning,
                   COALESCE(als.unack_total,     0)  AS unack_total,
                   COALESCE(als.alerts_today,    0)  AS alerts_today,
                   COALESCE(ss.subscriber_count, 0)  AS subscriber_count,
                   COALESCE(asm.admin_count,     0)  AS admin_count
            FROM   companies c
            -- Latest reading per company via idx_readings_company_ts (a
            -- GROUP BY over the whole readings table took ~30 s).
            LEFT JOIN LATERAL (
                SELECT r.timestamp::timestamptz AS last_reading_at
                FROM   readings r
                WHERE  r.company_id = c.id
                ORDER  BY r.timestamp DESC
                LIMIT  1
            ) rs ON TRUE
            LEFT JOIN alert_stats   als ON als.company_id = c.id
            LEFT JOIN sub_stats     ss  ON ss.company_id  = c.id
            LEFT JOIN admin_stats   asm ON asm.company_id = c.id
            ORDER  BY c.id
            """,
            (today,),
        )

        result = []
        for r in rows:
            is_active  = bool(r.get("is_active", 1))
            in_maint   = bool(r.get("maintenance_mode", 0))
            unack_crit = int(r.get("unack_critical") or 0)
            unack_warn = int(r.get("unack_warning")  or 0)
            unack_tot  = int(r.get("unack_total")    or 0)
            minutes    = float(r["minutes_since_reading"] or 0) if r.get("last_reading_at") else None
            flatline   = is_active and not in_maint and (
                r.get("last_reading_at") is None or (minutes is not None and minutes > 30)
            )

            if unack_crit > 0 or flatline:
                health = "red"
            elif unack_warn > 0 or in_maint:
                health = "yellow"
            else:
                health = "green"

            result.append({
                "id":                    r["id"],
                "name":                  r["name"],
                "slug":                  r["slug"],
                "is_active":             is_active,
                "maintenance_mode":      in_maint,
                "maintenance_reason":    r.get("maintenance_reason", ""),
                "last_reading_at":       str(r["last_reading_at"]) if r.get("last_reading_at") else None,
                "minutes_since_reading": round(minutes, 1) if minutes is not None else None,
                "flatline":              flatline,
                "unack_critical":        unack_crit,
                "unack_warning":         unack_warn,
                "unack_total":           unack_tot,
                "alerts_today":          int(r.get("alerts_today") or 0),
                "subscriber_count":      int(r.get("subscriber_count") or 0),
                "admin_count":           int(r.get("admin_count") or 0),
                "health":                health,
            })

        return result
    except Exception as exc:
        logger.error("companies_health failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 1: Cross-company alert list (AlertsTab) ────────────────────────────

@router.get("/alerts", summary="All alerts across all companies")
@limiter.limit("60/minute")
async def list_all_alerts(
    request: Request,
    limit: int = 100,
    company_id: Optional[int] = None,
    severity:   Optional[str] = None,
    _admin: dict = Depends(require_super_admin),
):
    try:
        conditions, params = [], []
        if company_id:
            conditions.append("a.company_id = %s"); params.append(company_id)
        if severity:
            conditions.append("a.severity = %s"); params.append(severity.lower())
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = execute_read(
            f"""
            SELECT a.id, a.parameter, a.value, a.threshold, a.direction, a.severity,
                   COALESCE(a.acknowledged, 0) AS acknowledged,
                   a.timestamp::TEXT,
                   c.id   AS company_id,
                   c.name AS company_name
            FROM alerts a
            JOIN companies c ON c.id = a.company_id
            {where}
            ORDER BY a.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return rows
    except Exception as exc:
        logger.error("list_all_alerts failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 1: Alert Triage Board ──────────────────────────────────────────────

@router.get("/alerts/triage", summary="Cross-company triage feed — unacked critical first")
@limiter.limit("60/minute")
async def alerts_triage(
    request: Request,
    severity:   Optional[str] = None,
    company_id: Optional[int] = None,
    unack_only: bool = False,
    limit: int = 200,
    _admin: dict = Depends(require_super_admin),
):
    """
    Returns alerts sorted by urgency:
      1. Unacknowledged critical
      2. Unacknowledged warning
      3. Everything else (descending by time)
    Includes minutes_open (SLA age) for each alert.
    """
    try:
        conditions, params = [], []
        if severity:
            conditions.append("a.severity = %s"); params.append(severity.lower())
        if company_id:
            conditions.append("a.company_id = %s"); params.append(company_id)
        if unack_only:
            conditions.append("(a.acknowledged = 0 OR a.acknowledged IS NULL)")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        rows = execute_read(
            f"""
            SELECT
                a.id,
                a.parameter,
                a.value,
                a.threshold,
                a.direction,
                a.severity,
                a.timestamp                                 AS timestamp,
                COALESCE(a.acknowledged, 0)                AS acknowledged,
                a.acknowledged_at                          AS acknowledged_at,
                EXTRACT(EPOCH FROM (NOW() - a.timestamp::timestamptz)) / 60 AS minutes_open,
                c.id                                       AS company_id,
                COALESCE(c.name, 'Unassigned')             AS company_name,
                c.slug                                     AS company_slug
            FROM alerts a
            LEFT JOIN companies c ON c.id = a.company_id
            {where}
            ORDER BY
                CASE WHEN COALESCE(a.acknowledged, 0) = 0 THEN 0 ELSE 1 END,
                CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                a.timestamp DESC
            LIMIT %s
            """,
            tuple(params),
        )

        result = []
        for r in rows:
            result.append({
                **{k: v for k, v in r.items() if k != "minutes_open"},
                "acknowledged":  bool(r.get("acknowledged", 0)),
                "minutes_open":  round(float(r.get("minutes_open") or 0), 1),
            })
        return result
    except Exception as exc:
        logger.error("alerts_triage failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 1: Super Admin Acknowledge Alert ────────────────────────────────────

@router.post("/alerts/{alert_id}/acknowledge", summary="Super admin acknowledge any company's alert")
@limiter.limit("30/minute")
async def sa_acknowledge_alert(
    alert_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            "SELECT id, company_id, severity, acknowledged, acknowledged_by, acknowledged_at FROM alerts WHERE id = %s", (alert_id,)
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
        alert = rows[0]
        done = execute_write(
            """UPDATE alerts
               SET acknowledged = 1, acknowledged_at = NOW(), acknowledged_by = %s
               WHERE id = %s AND COALESCE(acknowledged, 0) = 0""",
            (_admin.get("name", "super_admin"), alert_id),
        )
        if not done.rowcount:   # someone was first: keep their name and time
            return {"status": "already_acknowledged", "alert_id": alert_id,
                    "acknowledged_by": alert.get("acknowledged_by"), "acknowledged_at": str(alert.get("acknowledged_at") or "")}
        ip = request.client.host if request.client else "unknown"
        _log_audit(
            _admin["id"], alert["company_id"],
            f"ack_alert:{alert_id}", "alerts", "medium",
            f"alert_id={alert_id} severity={alert['severity']}",
            ip,
        )
        try:   # if it is a company server's alert, that server's own copy is acknowledged too
            from services.hub_sync import queue_node_ack
            queue_node_ack(alert_id, _admin.get("name", "super_admin"))
        except Exception:
            pass
        # Tell open dashboards so the alert stops showing as active there too
        try:
            from modules.inapp.manager import broadcast as _broadcast
            await _broadcast({"type": "acknowledgement", "alert_id": alert_id,
                              "acknowledged_by": _admin.get("name", "super_admin")}, company_id=alert["company_id"])
        except Exception as exc:
            logger.warning("sa_acknowledge_alert: broadcast failed: %s", exc)
        return {"status": "acknowledged", "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("sa_acknowledge_alert failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Task 1 (Phase 4): Severity-based channel routing ────────────────────────

class _RoutingUpdateIn(BaseModel):
    use_email:      int = Field(ge=0, le=1)
    use_sms:        int = Field(ge=0, le=1)
    use_push:       int = Field(ge=0, le=1)
    use_escalation: int = Field(ge=0, le=1)


@router.get("/config/routing/{company_id}", summary="Get severity routing rules for a company")
@limiter.limit("60/minute")
async def get_severity_routing(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """SELECT severity, use_email, use_sms, use_push, use_escalation
               FROM severity_routing
               WHERE company_id = %s
               ORDER BY severity""",
            (company_id,),
        )
        return rows
    except Exception as exc:
        logger.error("get_severity_routing failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.patch(
    "/config/routing/{company_id}/{severity}",
    summary="Update a severity routing rule",
)
@limiter.limit("30/minute")
async def update_severity_routing(
    company_id: int,
    severity: str,
    body: _RoutingUpdateIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    severity = severity.upper()
    if severity not in ("WARNING", "CRITICAL", "EMERGENCY"):
        raise HTTPException(
            status_code=422,
            detail="severity must be WARNING, CRITICAL, or EMERGENCY",
        )
    try:
        execute_write(
            """INSERT INTO severity_routing
                   (company_id, severity, use_email, use_sms, use_push, use_escalation)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (company_id, severity) DO UPDATE SET
                   use_email      = EXCLUDED.use_email,
                   use_sms        = EXCLUDED.use_sms,
                   use_push       = EXCLUDED.use_push,
                   use_escalation = EXCLUDED.use_escalation""",
            (company_id, severity,
             body.use_email, body.use_sms, body.use_push, body.use_escalation),
        )
        execute_write(
            """INSERT INTO admin_activity (admin_id, company_id, action, entity, details)
               VALUES (%s, %s, %s, %s, %s)""",
            (_admin["id"], company_id, "routing_updated", "severity_routing",
             f"company={company_id} severity={severity}"),
        )
        return {"status": "updated", "company_id": company_id, "severity": severity}
    except Exception as exc:
        logger.error("update_severity_routing failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Task 2 (Phase 4): Escalation Policy ─────────────────────────────────────

class _EscalationPolicyIn(BaseModel):
    enabled:                 Optional[int] = Field(default=None, ge=0, le=1)
    initial_wait_minutes:    Optional[int] = Field(default=None, ge=1, le=1440)
    repeat_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    max_escalations:         Optional[int] = Field(default=None, ge=1, le=10)
    notify_super_admin:      Optional[int] = Field(default=None, ge=0, le=1)


@router.get("/escalation/policy/{company_id}", summary="Get escalation policy for a company")
@limiter.limit("60/minute")
async def get_escalation_policy(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """SELECT enabled, initial_wait_minutes, repeat_interval_minutes,
                      max_escalations, notify_super_admin, created_at
               FROM escalation_policy
               WHERE company_id = %s LIMIT 1""",
            (company_id,),
        )
        if not rows:
            return {
                "company_id": company_id,
                "enabled": 1,
                "initial_wait_minutes": 5,
                "repeat_interval_minutes": 10,
                "max_escalations": 3,
                "notify_super_admin": 0,
            }
        r = rows[0]
        if r.get("created_at") and hasattr(r["created_at"], "isoformat"):
            r["created_at"] = r["created_at"].isoformat()
        return {"company_id": company_id, **r}
    except Exception as exc:
        logger.error("get_escalation_policy failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.patch("/escalation/policy/{company_id}", summary="Update escalation policy for a company")
@limiter.limit("30/minute")
async def update_escalation_policy(
    company_id: int,
    body: _EscalationPolicyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields provided")
    try:
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values     = list(updates.values()) + [company_id]
        execute_write(
            f"""INSERT INTO escalation_policy (company_id) VALUES (%s)
                ON CONFLICT (company_id) DO NOTHING""",
            (company_id,),
        )
        execute_write(
            f"UPDATE escalation_policy SET {set_clause} WHERE company_id = %s",
            values,
        )
        execute_write(
            """INSERT INTO admin_activity (admin_id, company_id, action, entity, details)
               VALUES (%s, %s, %s, %s, %s)""",
            (_admin["id"], company_id, "escalation_policy_updated",
             "escalation_policy", str(updates)),
        )
        return {"status": "updated", "company_id": company_id, "changes": updates}
    except Exception as exc:
        logger.error("update_escalation_policy failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/escalation/log/{alert_id}", summary="Get policy escalation log for an alert")
@limiter.limit("60/minute")
async def get_escalation_log(
    alert_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """SELECT pel.escalation_level, pel.notified_at,
                      pel.acknowledged, pel.acknowledged_at,
                      s.name AS subscriber_name
               FROM policy_escalation_log pel
               LEFT JOIN subscribers s ON s.id = pel.subscriber_id
               WHERE pel.alert_id = %s
               ORDER BY pel.escalation_level, pel.notified_at""",
            (alert_id,),
        )
        for r in rows:
            for col in ("notified_at", "acknowledged_at"):
                if r.get(col) and hasattr(r[col], "isoformat"):
                    r[col] = r[col].isoformat()
        return rows
    except Exception as exc:
        logger.error("get_escalation_log failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Task 5: Alert unacknowledge ──────────────────────────────────────────────

class _UnackIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/alerts/{alert_id}/unacknowledge", summary="Unacknowledge an alert")
@limiter.limit("20/minute")
async def unacknowledge_alert(
    alert_id: int,
    body: _UnackIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Resets the acknowledged status of an alert back to unacknowledged.
    Only super admins may perform this action.
    Broadcasts a WebSocket event so all connected dashboards update live.
    """
    rows = execute_read(
        "SELECT id, acknowledged FROM alerts WHERE id = %s LIMIT 1", (alert_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    if not rows[0]["acknowledged"]:
        raise HTTPException(status_code=409, detail=f"Alert {alert_id} is not currently acknowledged")

    execute_write(
        """UPDATE alerts
              SET acknowledged    = 0,
                  acknowledged_by = NULL,
                  acknowledged_at = NULL
            WHERE id = %s""",
        (alert_id,),
    )

    reason_note = f" (reason: {body.reason})" if body.reason else ""
    try:
        from utils.activity_logger import log_activity
        log_activity(
            _admin.get("id"), "unacknowledge_alert", "alert",
            f"alert_id={alert_id}{reason_note}",
            _admin.get("company_id"),
        )
    except Exception as exc:
        logger.warning("unacknowledge_alert: activity log failed: %s", exc)

    try:
        from modules.inapp.manager import broadcast as _broadcast
        await _broadcast({
            "type":     "unacknowledged",
            "alert_id": alert_id,
            "by":       _admin.get("name", "super_admin"),
            "reason":   body.reason or "",
            "at":       datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning("unacknowledge_alert: broadcast failed: %s", exc)

    logger.info(
        "Alert %d unacknowledged by super admin %s%s",
        alert_id, _admin.get("name"), reason_note,
    )
    return {
        "status":   "unacknowledged",
        "alert_id": alert_id,
        "by":       _admin.get("name"),
        "reason":   body.reason,
    }


# ─── Task 7: Recent login attempts visibility ──────────────────────────────────

@router.get("/security/login-attempts", summary="Recent login attempts")
@limiter.limit("30/minute")
async def get_login_attempts(
    request: Request,
    limit: int = 50,
    failed_only: bool = False,
    _admin: dict = Depends(require_super_admin),
):
    """
    Returns recent login attempts for all accounts, newest first.
    Query params: ?limit=50&failed_only=true
    """
    try:
        where = "WHERE success = 0" if failed_only else ""
        rows = execute_read(
            f"SELECT username, ip, success, attempted_at FROM login_attempts {where} ORDER BY attempted_at DESC LIMIT %s",
            (limit,),
        )
        logger.debug("login-attempts viewed by ip=%s", request.client.host if request.client else "unknown")
        for r in rows:
            r["attempted_at"] = r["attempted_at"].isoformat() if hasattr(r["attempted_at"], "isoformat") else str(r["attempted_at"])
        return rows
    except Exception as exc:
        logger.error("get_login_attempts failed: %s", exc)


# ── Anomaly log routes ────────────────────────────────────────────────────────

@router.get("/anomalies", summary="List anomaly log entries")
async def get_anomaly_log(
    limit: int = Query(100, ge=1, le=500),
    resolved: bool = Query(False),
    _: dict = Depends(require_super_admin),
):
    where = "WHERE a.is_resolved = 0" if not resolved else ""
    rows = execute_read(
        f"""
        SELECT a.id, a.company_id, c.name AS company_name,
               a.anomaly_type, a.severity, a.description,
               a.detected_at, a.is_resolved, a.resolved_at
          FROM anomaly_log a
          JOIN companies c ON c.id = a.company_id
         {where}
         ORDER BY a.detected_at DESC
         LIMIT %s
        """,
        (limit,),
    )
    for r in rows:
        r["detected_at"] = r["detected_at"].isoformat() if hasattr(r["detected_at"], "isoformat") else str(r["detected_at"])
        r["resolved_at"] = r["resolved_at"].isoformat() if r["resolved_at"] and hasattr(r["resolved_at"], "isoformat") else (str(r["resolved_at"]) if r["resolved_at"] else None)
    return rows


@router.patch("/anomalies/{anomaly_id}/resolve", summary="Resolve an anomaly")
async def resolve_anomaly(
    anomaly_id: int,
    _: dict = Depends(require_super_admin),
):
    execute_write(
        "UPDATE anomaly_log SET is_resolved = 1, resolved_at = NOW() WHERE id = %s AND is_resolved = 0",
        (anomaly_id,),
    )
    return {"ok": True, "resolved": anomaly_id}


# ── Billing — tier assignment + usage tracking ────────────────────────────────

class _TierAssignIn(BaseModel):
    tier_id: int


class _GrantQuotaIn(BaseModel):
    channel:      str = Field(..., pattern="^(sms|email|push)$")
    extra_amount: int = Field(..., ge=1, le=100000)


@router.patch("/billing/companies/{company_id}/tier", summary="Assign subscription tier to company")
async def assign_company_tier(
    company_id: int,
    body: _TierAssignIn,
    _: dict = Depends(require_super_admin),
):
    tier = execute_read("SELECT id, name FROM subscription_tiers WHERE id = %s", (body.tier_id,))
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")
    execute_write(
        "UPDATE companies SET tier_id = %s WHERE id = %s",
        (body.tier_id, company_id),
    )
    from utils.activity_logger import log_activity
    log_activity(0, "tier_changed", "company", f"company {company_id} → tier {tier[0]['name']}")
    return {"ok": True, "company_id": company_id, "tier_id": body.tier_id, "tier_name": tier[0]["name"]}


@router.get("/billing/usage", summary="Usage vs quota for all companies")
async def billing_usage_all(
    _: dict = Depends(require_super_admin),
):
    from utils.tier_enforcer import get_usage_summary
    companies = execute_read("SELECT id, name FROM companies WHERE is_active = 1 ORDER BY name")
    result = []
    for co in companies:
        summary = get_usage_summary(co["id"])
        summary["company_id"]   = co["id"]
        summary["company_name"] = co["name"]
        result.append(summary)
    return result


@router.get("/billing/usage/{company_id}", summary="Usage vs quota for one company")
async def billing_usage_single(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    from utils.tier_enforcer import get_usage_summary
    summary = get_usage_summary(company_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Company not found or no tier assigned")
    return summary


@router.post("/billing/companies/{company_id}/grant-quota", summary="Grant extra quota (decrement usage counter)")
async def grant_quota(
    company_id: int,
    body: _GrantQuotaIn,
    _: dict = Depends(require_super_admin),
):
    col_map = {
        "sms":   "sms_used_this_month",
        "email": "email_used_this_month",
        "push":  "push_used_this_month",
    }
    col = col_map[body.channel]
    execute_write(
        f"UPDATE companies SET {col} = GREATEST(0, {col} - %s) WHERE id = %s",
        (body.extra_amount, company_id),
    )
    from utils.activity_logger import log_activity
    log_activity(0, "quota_granted", "company",
                 f"company {company_id} {body.channel} -{body.extra_amount}")
    return {"ok": True, "company_id": company_id, "channel": body.channel, "granted": body.extra_amount}


# ── Task 3: Monthly Usage Report ──────────────────────────────────────────────

@router.get(
    "/billing/companies/{company_id}/report",
    summary="Monthly usage report for a company",
    description=(
        "Returns alert, subscriber, and notification activity for a given company "
        "in the requested month/year. Defaults to the current month."
    ),
)
async def monthly_usage_report(
    company_id: int,
    month: int | None = None,
    year:  int | None = None,
    _: dict = Depends(require_super_admin),
):
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    m = month if month and 1 <= month <= 12 else now.month
    y = year  if year  and 2020 <= year  <= 2100 else now.year

    # Period boundaries (inclusive)
    period_start = _dt.datetime(y, m, 1, tzinfo=_dt.timezone.utc)
    if m == 12:
        period_end = _dt.datetime(y + 1, 1, 1, tzinfo=_dt.timezone.utc)
    else:
        period_end = _dt.datetime(y, m + 1, 1, tzinfo=_dt.timezone.utc)

    # Company info + tier
    comp_rows = execute_read("""
        SELECT c.id, c.name AS company_name, c.slug,
               st.name AS tier_name,
               c.sms_used_this_month, c.email_used_this_month, c.push_used_this_month,
               st.monthly_sms_quota, st.monthly_email_quota
          FROM companies c
          LEFT JOIN subscription_tiers st ON st.id = c.tier_id
         WHERE c.id = %s
    """, (company_id,))
    if not comp_rows:
        raise HTTPException(status_code=404, detail="Company not found")
    comp = comp_rows[0]

    # Alert counts for the month
    alert_rows = execute_read("""
        SELECT COUNT(*) AS total_alerts,
               SUM(CASE WHEN acknowledged = 1 THEN 1 ELSE 0 END) AS acknowledged,
               SUM(CASE WHEN UPPER(severity) IN ('CRITICAL','EMERGENCY') THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN UPPER(severity) = 'WARNING' THEN 1 ELSE 0 END) AS warning
          FROM alerts
         WHERE company_id = %s
           AND timestamp::timestamptz >= %s AND timestamp::timestamptz < %s
    """, (company_id, period_start, period_end))
    alerts = alert_rows[0] if alert_rows else {}

    # Subscriber count (active as of now)
    sub_rows = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s AND is_active = 1",
        (company_id,),
    )
    active_subs = int(sub_rows[0]["cnt"]) if sub_rows else 0

    # Escalation notifications sent this month
    esc_rows = execute_read("""
        SELECT COUNT(*) AS notifications_sent
          FROM policy_escalation_log pel
          JOIN alerts a ON a.id = pel.alert_id
         WHERE a.company_id = %s
           AND pel.notified_at >= %s AND pel.notified_at < %s
    """, (company_id, period_start, period_end))
    esc_count = int(esc_rows[0]["notifications_sent"]) if esc_rows else 0

    return {
        "company_id":   company_id,
        "company_name": comp["company_name"],
        "slug":         comp["slug"],
        "tier":         comp["tier_name"],
        "period":       {"month": m, "year": y,
                         "start": period_start.isoformat(),
                         "end":   period_end.isoformat()},
        "alerts": {
            "total":        int(alerts.get("total_alerts") or 0),
            "acknowledged": int(alerts.get("acknowledged") or 0),
            "critical":     int(alerts.get("critical") or 0),
            "warning":      int(alerts.get("warning") or 0),
        },
        "subscribers":  {"active": active_subs},
        "notifications_sent": esc_count,
        "quota": {
            "sms_used":    int(comp["sms_used_this_month"]  or 0),
            "sms_limit":   int(comp["monthly_sms_quota"]    or 0),
            "email_used":  int(comp["email_used_this_month"] or 0),
            "email_limit": int(comp["monthly_email_quota"]  or 0),
        },
    }


# ── Task 4: Onboarding Wizard ─────────────────────────────────────────────────

_ONBOARDING_STEPS = [
    {"step_index": 0, "step_title": "Company Profile",          "description": "Basic company information has been set up."},
    {"step_index": 1, "step_title": "Add First Subscriber",     "description": "Add at least one alert subscriber."},
    {"step_index": 2, "step_title": "Configure Escalation",     "description": "Set up escalation policy and notification timing."},
    {"step_index": 3, "step_title": "Test Breach Alert",        "description": "Trigger a simulated breach to verify the pipeline."},
    {"step_index": 4, "step_title": "Go Live",                  "description": "Onboarding complete — the system is live."},
]


def _upsert_onboarding_step(company_id: int, step_index: int, status: str) -> None:
    existing = execute_read(
        "SELECT id FROM company_onboarding WHERE company_id = %s AND step_index = %s",
        (company_id, step_index),
    )
    if existing:
        execute_write(
            """UPDATE company_onboarding
                  SET step_status = %s, done = %s,
                      completed_at = CASE WHEN %s = 'done' THEN NOW() ELSE completed_at END
                WHERE company_id = %s AND step_index = %s""",
            (status, 1 if status == "done" else 0, status, company_id, step_index),
        )
    else:
        step = next((s for s in _ONBOARDING_STEPS if s["step_index"] == step_index), {})
        execute_write(
            """INSERT INTO company_onboarding
                      (company_id, item, done, step_index, step_title, step_status, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                company_id,
                step.get("step_title", f"Step {step_index}"),
                1 if status == "done" else 0,
                step_index,
                step.get("step_title", f"Step {step_index}"),
                status,
                None if status != "done" else "NOW()",
            ),
        )


@router.post(
    "/onboarding/{company_id}/init",
    summary="Initialise onboarding steps for a company",
)
async def onboarding_init(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    # Check company exists
    co = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not co:
        raise HTTPException(status_code=404, detail="Company not found")

    # Seed all steps as 'pending' (skip if already exist)
    for step in _ONBOARDING_STEPS:
        existing = execute_read(
            "SELECT id FROM company_onboarding WHERE company_id = %s AND step_index = %s",
            (company_id, step["step_index"]),
        )
        if not existing:
            execute_write(
                """INSERT INTO company_onboarding
                          (company_id, item, done, step_index, step_title, step_status)
                   VALUES (%s, %s, 0, %s, %s, 'pending')""",
                (company_id, step["step_title"], step["step_index"], step["step_title"]),
            )

    # Step 0 (Company Profile) is auto-done when company exists
    _upsert_onboarding_step(company_id, 0, "done")

    # Check if subscriber already exists → auto-advance step 1
    sub_rows = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s AND is_active = 1",
        (company_id,),
    )
    if int(sub_rows[0]["cnt"] if sub_rows else 0) > 0:
        _upsert_onboarding_step(company_id, 1, "done")

    # Check if escalation policy already configured
    ep_rows = execute_read(
        "SELECT id FROM escalation_policy WHERE company_id = %s", (company_id,)
    )
    if ep_rows:
        _upsert_onboarding_step(company_id, 2, "done")

    from utils.activity_logger import log_activity
    log_activity(0, "onboarding_init", "company", f"company {company_id}")
    return {"ok": True, "company_id": company_id, "steps": len(_ONBOARDING_STEPS)}


@router.get(
    "/onboarding/{company_id}",
    summary="Get onboarding progress for a company",
)
async def onboarding_status(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    co = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not co:
        raise HTTPException(status_code=404, detail="Company not found")

    rows = execute_read(
        """SELECT step_index, step_title, step_status, completed_at, item
             FROM company_onboarding WHERE company_id = %s
            ORDER BY step_index ASC""",
        (company_id,),
    )
    # Build full step list (merge DB rows with template)
    db_map = {r["step_index"]: r for r in rows}
    steps = []
    for s in _ONBOARDING_STEPS:
        db = db_map.get(s["step_index"], {})
        completed_at = db.get("completed_at")
        steps.append({
            "step_index":   s["step_index"],
            "step_title":   db.get("step_title") or s["step_title"],
            "description":  s["description"],
            "step_status":  db.get("step_status", "pending"),
            "completed_at": completed_at.isoformat() if completed_at else None,
        })

    done_count = sum(1 for s in steps if s["step_status"] == "done")
    return {
        "company_id":   company_id,
        "company_name": co[0]["name"],
        "total_steps":  len(_ONBOARDING_STEPS),
        "done_steps":   done_count,
        "complete":     done_count == len(_ONBOARDING_STEPS),
        "steps":        steps,
    }


@router.patch(
    "/onboarding/{company_id}/step/{step_index}",
    summary="Mark an onboarding step done (or pending)",
)
async def onboarding_step_update(
    company_id: int,
    step_index: int,
    status: str = "done",
    _: dict = Depends(require_super_admin),
):
    if step_index not in [s["step_index"] for s in _ONBOARDING_STEPS]:
        raise HTTPException(status_code=400, detail="Invalid step_index")
    if status not in ("done", "pending", "skipped"):
        raise HTTPException(status_code=400, detail="status must be done, pending, or skipped")
    _upsert_onboarding_step(company_id, step_index, status)
    return {"ok": True, "company_id": company_id, "step_index": step_index, "status": status}


# ── Task 3: Audit Log ─────────────────────────────────────────────────────────

@router.get(
    "/audit-log",
    summary="Security audit log",
    description=(
        "Returns audit log entries for compliance review. "
        "Filterable by category, severity, admin_id, company_id, and date range. "
        "Super admin only."
    ),
)
async def get_audit_log(
    limit:      int = 200,
    offset:     int = 0,
    category:   str | None = None,
    severity:   str | None = None,
    admin_id:   int | None = None,
    company_id: int | None = None,
    days:       int = 30,
    _: dict = Depends(require_super_admin),
):
    conditions = ["al.created_at >= NOW() - INTERVAL '%(days)s days'" % {"days": int(days)}]
    params: list = []

    if category:
        conditions.append("al.category = %s")
        params.append(category)
    if severity:
        conditions.append("al.severity = %s")
        params.append(severity)
    if admin_id is not None:
        conditions.append("al.admin_id = %s")
        params.append(admin_id)
    if company_id is not None:
        conditions.append("al.company_id = %s")
        params.append(company_id)

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    rows = execute_read(
        f"""
        SELECT al.id, al.category, al.action, al.entity_type, al.entity_id,
               al.old_value, al.new_value, al.ip_address, al.severity,
               al.created_at,
               a.name   AS admin_name,
               c.name   AS company_name
          FROM audit_log al
          LEFT JOIN admins    a ON a.id = al.admin_id
          LEFT JOIN companies c ON c.id = al.company_id
         WHERE {where}
         ORDER BY al.created_at DESC
         LIMIT %s OFFSET %s
        """,
        params,
    )

    total_row = execute_read(
        f"SELECT COUNT(*) AS cnt FROM audit_log al WHERE {where}",
        params[:-2],  # exclude limit/offset
    )
    total = int(total_row[0]["cnt"]) if total_row else 0

    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()

    return {"total": total, "offset": offset, "limit": limit, "rows": rows}


@router.get(
    "/audit-log/summary",
    summary="Audit log summary counts by category and severity",
)
async def audit_log_summary(
    days: int = 7,
    _: dict = Depends(require_super_admin),
):
    by_cat = execute_read(
        """SELECT category, COUNT(*) AS cnt
             FROM audit_log
            WHERE created_at >= NOW() - INTERVAL '%(days)s days'
            GROUP BY category ORDER BY cnt DESC""" % {"days": int(days)},
    )
    by_sev = execute_read(
        """SELECT severity, COUNT(*) AS cnt
             FROM audit_log
            WHERE created_at >= NOW() - INTERVAL '%(days)s days'
            GROUP BY severity ORDER BY cnt DESC""" % {"days": int(days)},
    )
    critical_recent = execute_read(
        """SELECT al.action, al.category, al.ip_address, al.created_at,
                  a.name AS admin_name
             FROM audit_log al
             LEFT JOIN admins a ON a.id = al.admin_id
            WHERE al.severity = 'critical'
              AND al.created_at >= NOW() - INTERVAL '%(days)s days'
            ORDER BY al.created_at DESC LIMIT 10""" % {"days": int(days)},
    )
    for r in critical_recent:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()

    return {
        "days":            days,
        "by_category":     by_cat,
        "by_severity":     by_sev,
        "critical_recent": critical_recent,
    }


# ── Task 1: TOTP status list (super admin view of all admins' 2FA state) ──────

@router.get(
    "/2fa/status-all",
    summary="2FA status for all admins",
)
async def totp_status_all(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """SELECT a.id, a.name, a.role, a.email, a.company_id,
                  c.name AS company_name,
                  COALESCE(ts.enabled,  0) AS totp_enabled,
                  COALESCE(ts.enforced, 0) AS totp_enforced
             FROM admins a
             LEFT JOIN totp_secrets ts ON ts.admin_id = a.id
             LEFT JOIN companies    c  ON c.id = a.company_id
            ORDER BY a.role DESC, a.name
        """
    )
    return rows


# ─── FCM Token Health ─────────────────────────────────────────────────────────

@router.get(
    "/subscribers/fcm-health",
    summary="FCM token health for all subscribers",
    description=(
        "Returns every subscriber with their FCM token status so you can "
        "identify who has a stale or missing token and needs to re-register "
        "their device.  Requires super_admin role."
    ),
)
async def fcm_health(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Query all subscribers and report their FCM token status.

    Response fields per subscriber:
        id               — subscriber primary key
        name             — display name
        email            — contact email
        phone_number     — stored phone number, or null if not set
        escalation_order — alert escalation priority
        fcm_token_preview — first 20 chars of the token (for debugging),
                            null when no token is present
        has_expo_token — True if a non-null expo_push_token is stored
    """
    try:
        rows = execute_read(
            """
            SELECT
                id,
                name,
                email,
                phone,
                escalation_order,
                active,
                fcm_token,
                expo_push_token
            FROM subscribers
            ORDER BY escalation_order ASC
            """
        )

        result = []
        for row in rows:
            fcm  = row.get("fcm_token")
            expo = row.get("expo_push_token")
            result.append({
                "id":                row["id"],
                "name":              row["name"],
                "email":             row["email"],
                "phone_number":      row.get("phone") or None,
                "escalation_order":  row["escalation_order"],
                "active":            bool(row.get("active", True)),
                "has_fcm_token":     fcm is not None,
                "fcm_token_preview": (fcm[:20] + "…") if fcm else None,
                "has_expo_token":    expo is not None,
            })

        total     = len(result)
        with_fcm  = sum(1 for r in result if r["has_fcm_token"])
        without_fcm = total - with_fcm

        return {
            "summary": {
                "total_subscribers": total,
                "with_fcm_token":    with_fcm,
                "without_fcm_token": without_fcm,
            },
            "subscribers": result,
        }

    except Exception as exc:
        logger.error("fcm_health failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Stale FCM Token Cleanup (manual trigger) ─────────────────────────────

@router.delete(
    "/subscribers/fcm-tokens/stale",
    summary="Clear stale FCM tokens",
    description=(
        "Manual garbage-collection for FCM tokens. "
        "If subscriber_id is given, clears that specific subscriber's FCM token. "
        "If omitted, clears ALL rows where fcm_token is empty string "
        "(useful after NotRegistered auto-cleanup). "
        "Returns the count of tokens cleared. Requires super_admin role."
    ),
)
async def clear_stale_fcm_tokens(
    request: Request,
    subscriber_id: Optional[int] = None,
    _admin: dict = Depends(require_super_admin),
):
    """
    Manual FCM token garbage-collection.

    subscriber_id present — clears that subscriber's fcm_token unconditionally.
    subscriber_id absent  — clears fcm_token for every subscriber where it is
                           already NULL or an empty string (idempotent).

    Returns:
        { cleared_count, subscriber_id, message }
    """
    try:
        if subscriber_id is not None:
            # ── Targeted clear: specific subscriber ────────────────────────────
            sub_rows = execute_read(
                "SELECT id, name, fcm_token FROM subscribers WHERE id = %s",
                (subscriber_id,),
            )
            if not sub_rows:
                raise HTTPException(
                    status_code=404,
                    detail=f"Subscriber {subscriber_id} not found",
                )
            sub = sub_rows[0]
            execute_write(
                "UPDATE subscribers SET fcm_token = NULL WHERE id = %s",
                (subscriber_id,),
            )
            had_token = sub.get("fcm_token") is not None
            logger.info(
                "Manual FCM token clear: subscriber %d (%s) — token was %s",
                subscriber_id, sub["name"],
                "present (cleared)" if had_token else "already null (no-op)",
            )
            return {
                "cleared_count":   1 if had_token else 0,
                "subscriber_id":   subscriber_id,
                "subscriber_name": sub["name"],
                "message": (
                    f"FCM token cleared for subscriber {subscriber_id} ({sub['name']})"
                    if had_token
                    else f"Subscriber {subscriber_id} ({sub['name']}) had no FCM token — nothing to clear"
                ),
            }

        else:
            # ── Bulk GC: wipe rows where token is an empty string ─────────────
            # (Rows already NULL are already clean; this catches the edge case
            # where the token was saved as "" instead of NULL.)
            stale_rows = execute_read(
                """
                SELECT id, name
                FROM subscribers
                WHERE fcm_token IS NOT NULL AND TRIM(fcm_token) = ''
                """
            )
            stale_count = len(stale_rows)
            if stale_rows:
                execute_write(
                    """
                    UPDATE subscribers
                    SET fcm_token = NULL
                    WHERE fcm_token IS NOT NULL AND TRIM(fcm_token) = ''
                    """
                )
                logger.info(
                    "Bulk FCM GC: cleared %d empty token(s): %s",
                    stale_count,
                    [r["name"] for r in stale_rows],
                )
            else:
                logger.info("Bulk FCM GC: no empty/stale tokens found — nothing to clear")

            return {
                "cleared_count":  stale_count,
                "subscriber_id":  None,
                "message": (
                    f"Cleared {stale_count} empty FCM token(s)"
                    if stale_count
                    else "No stale tokens found — database is already clean"
                ),
            }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("clear_stale_fcm_tokens failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 2: Subscriber Coverage Check ───────────────────────────────────────

@router.get("/subscriber-coverage", summary="Companies with missing/low subscriber coverage")
@limiter.limit("60/minute")
async def subscriber_coverage(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Returns companies where active subscriber count < 2.
    - 0 subscribers → critical  (alert will reach no one)
    - 1 subscriber  → warning   (no failover if primary unreachable)
    """
    try:
        rows = execute_read(
            """
            SELECT c.id, c.name, c.slug,
                   COALESCE(c.is_active, 1)        AS is_active,
                   COALESCE(c.maintenance_mode, 0) AS maintenance_mode,
                   COUNT(s.id)                     AS subscriber_count
            FROM companies c
            LEFT JOIN subscribers s
                   ON s.company_id = c.id
                  AND (s.is_active IS NULL OR s.is_active = 1)
            GROUP BY c.id, c.name, c.slug, c.is_active, c.maintenance_mode
            HAVING COUNT(s.id) < 2
            ORDER BY COUNT(s.id), c.name
            """
        )
        result = []
        for r in rows:
            result.append({
                **r,
                "risk_level": "critical" if int(r["subscriber_count"] or 0) == 0 else "warning",
                "risk_label": "No subscribers — alerts reach nobody"
                              if int(r["subscriber_count"] or 0) == 0
                              else "Only 1 subscriber — no failover",
            })
        return result
    except Exception as exc:
        logger.error("subscriber_coverage failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 2: Bulk Company Operations ─────────────────────────────────────────

class _BulkCompanyIn(BaseModel):
    ids:    list[int] = Field(min_length=1)
    action: str       # enable | disable | maintenance_on | maintenance_off

    @field_validator("action")
    @classmethod
    def check_action(cls, v):
        if v not in ("enable", "disable", "maintenance_on", "maintenance_off"):
            raise ValueError("action must be enable | disable | maintenance_on | maintenance_off")
        return v


@router.post("/companies/bulk", summary="Bulk enable / disable / maintenance for multiple companies")
@limiter.limit("20/minute")
async def bulk_company_action(
    body: _BulkCompanyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        if not body.ids:
            return JSONResponse(status_code=422, content={"error": "No company IDs provided"})

        placeholders = ", ".join(["%s"] * len(body.ids))

        if body.action == "enable":
            execute_write(f"UPDATE companies SET is_active = 1 WHERE id IN ({placeholders})", tuple(body.ids))
        elif body.action == "disable":
            execute_write(f"UPDATE companies SET is_active = 0 WHERE id IN ({placeholders})", tuple(body.ids))
        elif body.action == "maintenance_on":
            execute_write(f"UPDATE companies SET maintenance_mode = 1 WHERE id IN ({placeholders})", tuple(body.ids))
        elif body.action == "maintenance_off":
            execute_write(f"UPDATE companies SET maintenance_mode = 0, maintenance_reason = NULL WHERE id IN ({placeholders})", tuple(body.ids))

        ip = request.client.host if request.client else "unknown"
        _log_audit(
            _admin["id"], None,
            f"bulk_{body.action}", "company", "medium",
            f"ids={body.ids}", ip,
        )
        return {"status": "ok", "action": body.action, "affected": len(body.ids), "ids": body.ids}
    except Exception as exc:
        logger.error("bulk_company_action failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 2: CSV Exports ──────────────────────────────────────────────────────

import csv
import io as _io
from fastapi.responses import StreamingResponse


@router.get("/export/companies.csv", summary="Download all companies as CSV")
@limiter.limit("10/minute")
async def export_companies_csv(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT c.id, c.name, c.slug,
                   COALESCE(c.is_active, 1)        AS is_active,
                   COALESCE(c.maintenance_mode, 0) AS maintenance_mode,
                   COALESCE(st.name, 'Free')        AS tier,
                   c.max_subscribers, c.max_devices, c.allowed_channels,
                   c.created_at::TEXT,
                   COUNT(DISTINCT a.id)             AS admin_count,
                   COUNT(DISTINCT s.id)             AS subscriber_count,
                   COUNT(DISTINCT al.id)            AS total_alerts
            FROM companies c
            LEFT JOIN subscription_tiers st ON st.id = c.tier_id
            LEFT JOIN admins      a  ON a.company_id  = c.id AND a.role != 'super_admin'
            LEFT JOIN subscribers s  ON s.company_id  = c.id
            LEFT JOIN alerts      al ON al.company_id = c.id
            GROUP BY c.id, c.name, c.slug, c.is_active, c.maintenance_mode,
                     st.name, c.max_subscribers, c.max_devices, c.allowed_channels, c.created_at
            ORDER BY c.id
            """
        )
        buf = _io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "Name", "Slug", "Active", "Maintenance", "Tier",
                    "Max Subscribers", "Max Devices", "Channels",
                    "Admins", "Subscribers", "Total Alerts", "Created At"])
        for r in rows:
            w.writerow([r["id"], r["name"], r["slug"], bool(r["is_active"]),
                        bool(r["maintenance_mode"]), r["tier"],
                        r["max_subscribers"], r["max_devices"], r["allowed_channels"],
                        r["admin_count"], r["subscriber_count"], r["total_alerts"], r["created_at"]])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="companies.csv"'},
        )
    except Exception as exc:
        logger.error("export_companies_csv failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/export/alerts.csv", summary="Download alerts as CSV")
@limiter.limit("10/minute")
async def export_alerts_csv(
    request: Request,
    days: int = 7,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT a.id, c.name AS company, a.parameter, a.value, a.threshold,
                   a.direction, a.severity,
                   COALESCE(a.acknowledged, 0) AS acknowledged,
                   a.acknowledged_at::TEXT,
                   a.timestamp::TEXT
            FROM alerts a
            JOIN companies c ON c.id = a.company_id
            WHERE a.timestamp::timestamptz >= NOW() - INTERVAL '%(days)s days'
            ORDER BY a.timestamp::timestamptz DESC
            """ % {"days": int(days)}
        )
        buf = _io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "Company", "Parameter", "Value", "Threshold", "Direction",
                    "Severity", "Acknowledged", "Acknowledged At", "Timestamp"])
        for r in rows:
            w.writerow([r["id"], r["company"], r["parameter"], r["value"], r["threshold"],
                        r["direction"], r["severity"], bool(r["acknowledged"]),
                        r["acknowledged_at"] or "", r["timestamp"]])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="alerts_{days}d.csv"'},
        )
    except Exception as exc:
        logger.error("export_alerts_csv failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.get("/export/subscribers.csv", summary="Download all subscribers as CSV")
@limiter.limit("10/minute")
async def export_subscribers_csv(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT s.id, c.name AS company, s.name, s.phone, s.email,
                   s.escalation_order,
                   COALESCE(s.is_active, 1) AS is_active,
                   s.created_at::TEXT
            FROM subscribers s
            JOIN companies c ON c.id = s.company_id
            ORDER BY c.name, s.escalation_order
            """
        )
        buf = _io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ID", "Company", "Name", "Phone", "Email",
                    "Escalation Order", "Active", "Created At"])
        for r in rows:
            w.writerow([r["id"], r["company"], r["name"], r["phone"] or "",
                        r["email"] or "", r["escalation_order"],
                        bool(r["is_active"]), r["created_at"]])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="subscribers.csv"'},
        )
    except Exception as exc:
        logger.error("export_subscribers_csv failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ─── Tier 2: New Company Wizard — step-by-step creation ──────────────────────

class _WizardCompanyIn(BaseModel):
    name:             str  = Field(min_length=2, max_length=100)
    slug:             str  = Field(min_length=2, max_length=60)
    description:      Optional[str] = None
    max_subscribers:  int  = Field(default=100, ge=1)
    max_devices:      int  = Field(default=10,  ge=1)
    allowed_channels: str  = Field(default="sms,email,push")

    @field_validator("name", "slug", mode="before")
    @classmethod
    def strip(cls, v): return v.strip() if isinstance(v, str) else v


class _WizardAdminIn(BaseModel):
    company_id: int
    name:       str  = Field(min_length=2, max_length=50)
    password:   str  = Field(min_length=10, max_length=200)
    role:       str  = Field(default="main")
    email:      Optional[str] = None

    @field_validator("name", "password", mode="before")
    @classmethod
    def strip(cls, v): return v.strip() if isinstance(v, str) else v

    @field_validator("password", mode="after")
    @classmethod
    def check_password_strength(cls, v):
        return _enforce_password_strength(v)


class _WizardSubscriberIn(BaseModel):
    company_id:        int
    name:              str  = Field(min_length=2, max_length=100)
    phone:             Optional[str] = None
    email:             Optional[str] = None
    escalation_order:  int  = Field(default=1, ge=1)

    @field_validator("name", mode="before")
    @classmethod
    def strip(cls, v): return v.strip() if isinstance(v, str) else v


@router.post("/wizard/company", status_code=201, summary="Wizard step 1 — create company")
@limiter.limit("20/minute")
async def wizard_create_company(
    body: _WizardCompanyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            """INSERT INTO companies (name, slug, description, max_subscribers, max_devices, allowed_channels, is_active, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 0, NOW()) RETURNING id""",
            (body.name, body.slug, body.description, body.max_subscribers, body.max_devices, body.allowed_channels),
        )
        company_id = result.lastrowid
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], company_id, f"wizard_create_company:{body.name}", "company", "medium",
                   f"slug={body.slug}", ip)
        rows = execute_read("SELECT id, name, slug, is_active, created_at::TEXT FROM companies WHERE id = %s", (company_id,))
        return rows[0] if rows else {"id": company_id, "name": body.name}
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return JSONResponse(status_code=409, content={"error": f"Slug '{body.slug}' already exists"})
        logger.error("wizard_create_company failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.post("/wizard/admin", status_code=201, summary="Wizard step 2 — create admin for company")
@limiter.limit("20/minute")
async def wizard_create_admin(
    body: _WizardAdminIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        if body.role not in ("main", "sub"):
            return JSONResponse(status_code=422, content={"error": "role must be main or sub"})
        problem = _admin_name_problem(body.name)
        if problem:
            return JSONResponse(status_code=409, content={"error": problem})
        if not execute_read("SELECT 1 FROM companies WHERE id = %s", (body.company_id,)):
            return JSONResponse(status_code=404, content={"error": "Company not found"})
        result = execute_write(
            "INSERT INTO admins (name, password_hash, role, company_id, created_at) VALUES (%s, %s, %s, %s, NOW()) RETURNING id",
            (body.name, hash_pin(body.password), body.role, body.company_id),
        )
        if body.email:
            try:
                execute_write("UPDATE admins SET email = %s WHERE id = %s", (body.email, result.lastrowid))
            except Exception: pass
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], body.company_id, f"wizard_create_admin:{body.name}", "admin", "medium",
                   f"role={body.role}", ip)
        return _get_admin_or_404(result.lastrowid)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return JSONResponse(status_code=409, content={"error": f"Admin '{body.name}' already exists"})
        logger.error("wizard_create_admin failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.post("/wizard/subscriber", status_code=201, summary="Wizard step 4 — add subscriber")
@limiter.limit("30/minute")
async def wizard_add_subscriber(
    body: _WizardSubscriberIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            """INSERT INTO subscribers (company_id, name, phone, email, escalation_order, is_active, created_at)
               VALUES (%s, %s, %s, %s, %s, 1, NOW()) RETURNING id""",
            (body.company_id, body.name, body.phone, body.email, body.escalation_order),
        )
        return {"id": result.lastrowid, "name": body.name, "escalation_order": body.escalation_order}
    except Exception as exc:
        logger.error("wizard_add_subscriber failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


@router.post("/wizard/enable/{company_id}", summary="Wizard final step — enable the company")
@limiter.limit("20/minute")
async def wizard_enable_company(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Company not found")
        execute_write("UPDATE companies SET is_active = 1 WHERE id = %s", (company_id,))
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], company_id, f"wizard_enable:{rows[0]['name']}", "company", "medium",
                   f"company_id={company_id}", ip)
        return {"status": "enabled", "company_id": company_id, "name": rows[0]["name"]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("wizard_enable_company failed: %s", exc)
        logger.error("internal error: %s", exc, exc_info=True); return JSONResponse(status_code=500, content={"error": "An internal error occurred"})


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 3 — Advanced Intelligence & Platform Management
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Tier 3 Pydantic models ───────────────────────────────────────────────────

class _TemplateParamItem(BaseModel):
    name:      str
    unit:      Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None

class _ParameterTemplateIn(BaseModel):
    name:        str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    params:      List[_TemplateParamItem] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v


class _EscalationRuleIn(BaseModel):
    name:               str  = Field(min_length=2, max_length=100)
    company_id:         Optional[int] = None   # None = applies to all companies
    severity_filter:    str  = Field(default="critical")
    threshold_minutes:  int  = Field(default=30, ge=1, le=10080)
    action_type:        str  = Field(default="webhook")          # webhook | log
    action_target:      Optional[str] = None                     # URL for webhook
    is_active:          bool = True

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("action_target", mode="before")
    @classmethod
    def validate_webhook_url(cls, v):
        if v is None:
            return v
        from urllib.parse import urlparse
        import ipaddress
        url = v.strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError("action_target must use http or https")
        hostname = parsed.hostname or ""
        # Block private/loopback/link-local ranges (SSRF protection)
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError("action_target must not point to a private/internal address")
        except ValueError as ip_exc:
            if "action_target" in str(ip_exc) or "private" in str(ip_exc):
                raise
            # hostname is a domain name, not an IP — check for localhost patterns
            if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("action_target must not point to localhost")
        return url


# ─── 1. Advanced Audit Explorer ───────────────────────────────────────────────

@router.get("/audit", summary="Tier 3: paginated, filtered audit log")
@limiter.limit("60/minute")
async def get_audit_log(
    request:    Request,
    company_id: Optional[int] = Query(None),
    category:   Optional[str] = Query(None),
    severity:   Optional[str] = Query(None),
    search:     Optional[str] = Query(None),
    date_from:  Optional[str] = Query(None),   # ISO date string e.g. 2026-01-01
    date_to:    Optional[str] = Query(None),
    page:       int           = Query(1, ge=1),
    limit:      int           = Query(50, ge=1, le=200),
    _admin: dict = Depends(require_super_admin),
):
    conditions = []
    params: List[Any] = []

    if company_id:
        conditions.append("al.company_id = %s"); params.append(company_id)
    if category:
        conditions.append("al.category = %s"); params.append(category)
    if severity:
        conditions.append("al.severity = %s"); params.append(severity)
    if search:
        conditions.append("(al.action ILIKE %s OR al.details ILIKE %s)")
        like = f"%{search}%"; params += [like, like]
    if date_from:
        conditions.append("al.created_at >= %s::timestamptz"); params.append(date_from)
    if date_to:
        conditions.append("al.created_at <= %s::timestamptz"); params.append(date_to + "T23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * limit

    rows = execute_read(
        f"""
        SELECT al.id, al.admin_id, a.name AS admin_name, al.company_id,
               c.name AS company_name, al.category, al.action,
               al.severity, al.details, al.ip_address,
               al.created_at
          FROM audit_log al
          LEFT JOIN admins   a ON a.id = al.admin_id
          LEFT JOIN companies c ON c.id = al.company_id
         {where}
         ORDER BY al.created_at DESC
         LIMIT %s OFFSET %s
        """,
        params + [limit, offset],
    )
    count_rows = execute_read(
        f"SELECT COUNT(*) AS total FROM audit_log al {where}",
        params,
    )
    total = count_rows[0]["total"] if count_rows else 0

    # Distinct categories for filter dropdowns
    cats = execute_read("SELECT DISTINCT category FROM audit_log ORDER BY category")

    return {
        "rows":       rows,
        "total":      total,
        "page":       page,
        "pages":      max(1, -(-total // limit)),   # ceiling division
        "categories": [r["category"] for r in cats],
    }


@router.get("/export/audit.csv", summary="Tier 3: export audit log as CSV")
@limiter.limit("10/minute")
async def export_audit_csv(
    request:    Request,
    company_id: Optional[int] = Query(None),
    date_from:  Optional[str] = Query(None),
    date_to:    Optional[str] = Query(None),
    _admin: dict = Depends(require_super_admin),
):
    conditions = []
    params: List[Any] = []
    if company_id:
        conditions.append("al.company_id = %s"); params.append(company_id)
    if date_from:
        conditions.append("al.created_at >= %s::timestamptz"); params.append(date_from)
    if date_to:
        conditions.append("al.created_at <= %s::timestamptz"); params.append(date_to + "T23:59:59")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = execute_read(
        f"""
        SELECT al.id, a.name AS admin_name, c.name AS company_name,
               al.category, al.action, al.severity, al.details,
               al.ip_address, al.created_at
          FROM audit_log al
          LEFT JOIN admins    a ON a.id = al.admin_id
          LEFT JOIN companies c ON c.id = al.company_id
         {where}
         ORDER BY al.created_at DESC
         LIMIT 10000
        """,
        params,
    )
    buf = _io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["ID", "Admin", "Company", "Category", "Action", "Severity", "Details", "IP", "Timestamp"])
    for r in rows:
        w.writerow([r["id"], r["admin_name"], r["company_name"], r["category"],
                    r["action"], r["severity"], r["details"], r["ip_address"], r["created_at"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit.csv"},
    )


# ─── 2. Cross-Company Analytics ───────────────────────────────────────────────

@router.get("/analytics/alerts", summary="Tier 3: daily alert counts per company (last N days)")
@limiter.limit("30/minute")
async def analytics_alerts(
    request: Request,
    days:    int = Query(14, ge=1, le=90),
    _admin: dict = Depends(require_super_admin),
):
    """Returns [{date, company_id, company_name, total, critical, warning, info}] for chart rendering."""
    rows = execute_read(
        """
        SELECT DATE(a.timestamp::timestamptz) AS day,
               a.company_id,
               c.name AS company_name,
               COUNT(*)                                                      AS total,
               COUNT(*) FILTER (WHERE UPPER(a.severity) IN ('CRITICAL','EMERGENCY')) AS critical,
               COUNT(*) FILTER (WHERE UPPER(a.severity) = 'WARNING')         AS warning,
               COUNT(*) FILTER (WHERE UPPER(a.severity) NOT IN ('CRITICAL','EMERGENCY','WARNING')) AS info
          FROM alerts a
          JOIN companies c ON c.id = a.company_id
         WHERE a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval
         GROUP BY day, a.company_id, c.name
         ORDER BY day, total DESC
        """,
        (days,),
    )
    return rows


@router.get("/analytics/platform", summary="Tier 3: platform-wide daily totals for trend charts")
@limiter.limit("30/minute")
async def analytics_platform(
    request: Request,
    days:    int = Query(30, ge=1, le=90),
    _admin: dict = Depends(require_super_admin),
):
    alert_trend = execute_read(
        """
        SELECT DATE(timestamp::timestamptz) AS day,
               COUNT(*)                                               AS total_alerts,
               COUNT(*) FILTER (WHERE UPPER(severity) IN ('CRITICAL','EMERGENCY')) AS critical,
               COUNT(*) FILTER (WHERE acknowledged = 1)               AS acknowledged
          FROM alerts
         WHERE timestamp::timestamptz >= NOW() - (%s || ' days')::interval
         GROUP BY day ORDER BY day
        """,
        (days,),
    )
    reading_trend = execute_read(
        """
        SELECT LEFT(timestamp, 10) AS day, COUNT(*) AS readings
          FROM readings
         WHERE timestamp >= to_char((NOW() - (%s || ' days')::interval) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
         GROUP BY 1 ORDER BY 1
        """,
        (days,),
    )
    session_trend = execute_read(
        """
        SELECT DATE(created_at) AS day, COUNT(*) AS sessions
          FROM admin_sessions
         WHERE created_at >= NOW() - (%s || ' days')::interval
         GROUP BY day ORDER BY day
        """,
        (days,),
    )
    return {
        "alert_trend":   alert_trend,
        "reading_trend": reading_trend,
        "session_trend": session_trend,
    }


@router.get("/analytics/top-companies", summary="Tier 3: companies ranked by activity metrics")
@limiter.limit("30/minute")
async def analytics_top_companies(
    request: Request,
    metric:  str = Query("alerts", pattern="^(alerts|readings|sessions)$"),
    days:    int = Query(7, ge=1, le=90),
    limit:   int = Query(10, ge=1, le=50),
    _admin: dict = Depends(require_super_admin),
):
    if metric == "alerts":
        rows = execute_read(
            """
            SELECT c.id, c.name, COUNT(a.id) AS value
              FROM companies c
              LEFT JOIN alerts a ON a.company_id = c.id
                AND a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval
             GROUP BY c.id, c.name
             ORDER BY value DESC
             LIMIT %s
            """,
            (days, limit),
        )
    elif metric == "readings":
        rows = execute_read(
            """
            SELECT c.id, c.name, COUNT(r.id) AS value
              FROM companies c
              LEFT JOIN readings r ON r.company_id = c.id
                AND r.timestamp >= to_char((NOW() - (%s || ' days')::interval) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')
             GROUP BY c.id, c.name
             ORDER BY value DESC
             LIMIT %s
            """,
            (days, limit),
        )
    else:  # sessions
        rows = execute_read(
            """
            SELECT c.id, c.name, COUNT(s.id) AS value
              FROM companies c
              LEFT JOIN admins ad ON ad.company_id = c.id
              LEFT JOIN admin_sessions s ON s.admin_id = ad.id
                AND s.created_at >= NOW() - (%s || ' days')::interval
             GROUP BY c.id, c.name
             ORDER BY value DESC
             LIMIT %s
            """,
            (days, limit),
        )
    return {"metric": metric, "days": days, "rows": rows}


@router.get("/analytics/compare", summary="Tier 3: side-by-side company comparison")
@limiter.limit("30/minute")
async def analytics_compare(
    request: Request,
    ids:     str = Query(..., description="Comma-separated company IDs"),
    days:    int = Query(7, ge=1, le=90),
    _admin: dict = Depends(require_super_admin),
):
    try:
        id_list = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    except ValueError:
        raise HTTPException(status_code=422, detail="ids must be comma-separated integers")
    if not id_list:
        return []
    if len(id_list) > 10:
        raise HTTPException(status_code=422, detail="Max 10 companies for comparison")

    placeholders = ", ".join(["%s"] * len(id_list))
    rows = execute_read(
        f"""
        SELECT
            c.id, c.name, c.slug, c.is_active, c.maintenance_mode,
            (SELECT COUNT(*) FROM alerts a
              WHERE a.company_id = c.id
                AND a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval) AS alerts_period,
            (SELECT COUNT(*) FROM alerts a
              WHERE a.company_id = c.id AND UPPER(a.severity) IN ('CRITICAL','EMERGENCY')
                AND a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval) AS critical_period,
            (SELECT COUNT(*) FROM alerts a
              WHERE a.company_id = c.id AND a.acknowledged = 0)                    AS unacked_now,
            (SELECT COUNT(*) FROM readings r
              WHERE r.company_id = c.id
                AND r.timestamp >= to_char((NOW() - (%s || ' days')::interval) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS')) AS readings_period,
            (SELECT COUNT(*) FROM subscribers s
              WHERE s.company_id = c.id AND s.is_active = 1)                       AS active_subscribers,
            (SELECT COUNT(*) FROM admins ad
              WHERE ad.company_id = c.id)                                           AS admin_count,
            (SELECT r2.timestamp::timestamptz FROM readings r2
              WHERE r2.company_id = c.id ORDER BY r2.timestamp DESC LIMIT 1)       AS last_reading_at
          FROM companies c
         WHERE c.id IN ({placeholders})
         ORDER BY alerts_period DESC
        """,
        [days, days, days] + id_list,
    )

    # Add uptime % (readings in period vs expected at 1/min)
    expected = days * 24 * 60
    result = []
    for r in rows:
        row = dict(r)
        rdgs = row.get("readings_period") or 0
        row["uptime_pct"] = round(min(100.0, rdgs / expected * 100), 1) if expected else 0
        if row.get("last_reading_at"):
            delta = (datetime.now(timezone.utc) - row["last_reading_at"]).total_seconds() / 60
            row["minutes_since_reading"] = round(delta, 1)
        else:
            row["minutes_since_reading"] = None
        result.append(row)
    return result


# ─── 3. Platform Health Monitor ───────────────────────────────────────────────

@router.get("/platform/health", summary="Tier 3: platform system vitals")
@limiter.limit("30/minute")
async def platform_health(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    from database.connection import get_db_pool, MODULE_STATUS

    pool = get_db_pool()
    pool_stats = {
        "min_conn": pool.minconn,
        "max_conn": pool.maxconn,
        "used":     len(pool._used),
        "free":     len(pool._pool),
    }

    active_sessions = execute_read(
        "SELECT COUNT(*) AS n FROM admin_sessions WHERE expires_at > NOW()", []
    )
    readings_last_hour = execute_read(
        "SELECT COUNT(*) AS n FROM readings WHERE timestamp >= "
        "to_char((NOW() - INTERVAL '1 hour') AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS')", []
    )
    alerts_last_hour = execute_read(
        "SELECT COUNT(*) AS n FROM alerts WHERE timestamp::timestamptz >= NOW() - INTERVAL '1 hour'", []
    )
    unacked_critical = execute_read(
        "SELECT COUNT(*) AS n FROM alerts WHERE acknowledged = 0 AND UPPER(severity) IN ('CRITICAL','EMERGENCY')", []
    )
    recent_audit_errors = execute_read(
        "SELECT COUNT(*) AS n FROM audit_log WHERE severity = 'critical' AND created_at >= NOW() - INTERVAL '1 hour'",
        [],
    )

    return {
        "db_pool":              pool_stats,
        "module_status":        MODULE_STATUS,
        "active_sessions":      active_sessions[0]["n"] if active_sessions else 0,
        "readings_last_hour":   readings_last_hour[0]["n"] if readings_last_hour else 0,
        "alerts_last_hour":     alerts_last_hour[0]["n"] if alerts_last_hour else 0,
        "unacked_critical":     unacked_critical[0]["n"] if unacked_critical else 0,
        "audit_errors_last_hour": recent_audit_errors[0]["n"] if recent_audit_errors else 0,
        "server_time_utc":      datetime.now(timezone.utc).isoformat(),
    }


# ─── 4. Parameter Template Library ───────────────────────────────────────────

@router.get("/parameter-templates", summary="Tier 3: list all parameter templates")
@limiter.limit("60/minute")
async def list_parameter_templates(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT pt.id, pt.name, pt.description, pt.params,
               a.name AS created_by_name, pt.created_at
          FROM parameter_templates pt
          LEFT JOIN admins a ON a.id = pt.created_by
         ORDER BY pt.created_at DESC
        """,
        [],
    )
    return rows


@router.post("/parameter-templates", status_code=201, summary="Tier 3: create parameter template")
@limiter.limit("20/minute")
async def create_parameter_template(
    body:    _ParameterTemplateIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    params_json = json.dumps([p.model_dump() for p in body.params])
    try:
        result = execute_write(
            """INSERT INTO parameter_templates (name, description, params, created_by)
               VALUES (%s, %s, %s::jsonb, %s) RETURNING id""",
            (body.name, body.description, params_json, _admin["id"]),
        )
        ip = request.client.host if request.client else "unknown"
        _log_audit(_admin["id"], None, f"create_template:{body.name}", "template", "low",
                   f"params={len(body.params)}", ip)
        return {"id": result.lastrowid, "name": body.name}
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"Template name '{body.name}' already exists")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/parameter-templates/{template_id}", summary="Tier 3: delete parameter template")
@limiter.limit("20/minute")
async def delete_parameter_template(
    template_id: int,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT name FROM parameter_templates WHERE id = %s", (template_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Template not found")
    execute_write("DELETE FROM parameter_templates WHERE id = %s", (template_id,))
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], None, f"delete_template:{rows[0]['name']}", "template", "medium",
               f"template_id={template_id}", ip)
    return {"status": "deleted"}


@router.post(
    "/parameter-templates/{template_id}/apply/{company_id}",
    summary="Tier 3: apply template to a company",
)
@limiter.limit("20/minute")
async def apply_parameter_template(
    template_id: int,
    company_id:  int,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    tpl_rows = execute_read(
        "SELECT id, name, description, params, created_by, created_at "
        "FROM parameter_templates WHERE id = %s",
        (template_id,),
    )
    if not tpl_rows:
        raise HTTPException(status_code=404, detail="Template not found")
    co_rows = execute_read("SELECT name FROM companies WHERE id = %s", (company_id,))
    if not co_rows:
        raise HTTPException(status_code=404, detail="Company not found")

    params = tpl_rows[0]["params"]
    if isinstance(params, str):
        params = json.loads(params)

    applied, skipped = 0, 0
    for p in params:
        try:
            execute_write(
                """INSERT INTO company_parameters (company_id, name, unit, min_value, max_value)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (company_id, name) DO NOTHING""",
                (company_id, p["name"], p.get("unit"), p.get("min_value"), p.get("max_value")),
            )
            applied += 1
        except Exception:
            skipped += 1

    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], company_id,
               f"apply_template:{tpl_rows[0]['name']}→{co_rows[0]['name']}",
               "template", "medium", f"applied={applied},skipped={skipped}", ip)
    return {"applied": applied, "skipped": skipped, "company": co_rows[0]["name"], "template": tpl_rows[0]["name"]}


# ─── 5. Escalation Rules Engine ──────────────────────────────────────────────

@router.get("/escalation-rules", summary="Tier 3: list escalation rules")
@limiter.limit("60/minute")
async def list_escalation_rules(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT er.id, er.name, er.company_id, c.name AS company_name,
               er.severity_filter, er.threshold_minutes, er.action_type,
               er.action_target, er.is_active, er.last_triggered_at, er.created_at
          FROM escalation_rules er
          LEFT JOIN companies c ON c.id = er.company_id
         ORDER BY er.created_at DESC
        """,
        [],
    )
    return rows


@router.post("/escalation-rules", status_code=201, summary="Tier 3: create escalation rule")
@limiter.limit("20/minute")
async def create_escalation_rule(
    body:    _EscalationRuleIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    result = execute_write(
        """INSERT INTO escalation_rules
               (name, company_id, severity_filter, threshold_minutes,
                action_type, action_target, is_active)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (body.name, body.company_id, body.severity_filter, body.threshold_minutes,
         body.action_type, body.action_target, body.is_active),
    )
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], body.company_id, f"create_rule:{body.name}", "escalation", "low",
               f"severity={body.severity_filter},threshold={body.threshold_minutes}m", ip)
    return {"id": result.lastrowid, "name": body.name}


@router.patch("/escalation-rules/{rule_id}", summary="Tier 3: update escalation rule")
@limiter.limit("20/minute")
async def update_escalation_rule(
    rule_id: int,
    body:    _EscalationRuleIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id FROM escalation_rules WHERE id = %s", (rule_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Rule not found")
    execute_write(
        """UPDATE escalation_rules
              SET name = %s, company_id = %s, severity_filter = %s,
                  threshold_minutes = %s, action_type = %s,
                  action_target = %s, is_active = %s
            WHERE id = %s""",
        (body.name, body.company_id, body.severity_filter, body.threshold_minutes,
         body.action_type, body.action_target, body.is_active, rule_id),
    )
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], body.company_id, f"update_rule:{body.name}", "escalation", "medium",
               f"rule_id={rule_id}", ip)
    return {"status": "updated", "id": rule_id}


@router.delete("/escalation-rules/{rule_id}", summary="Tier 3: delete escalation rule")
@limiter.limit("20/minute")
async def delete_escalation_rule(
    rule_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT name FROM escalation_rules WHERE id = %s", (rule_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Rule not found")
    execute_write("DELETE FROM escalation_rules WHERE id = %s", (rule_id,))
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], None, f"delete_rule:{rows[0]['name']}", "escalation", "medium",
               f"rule_id={rule_id}", ip)
    return {"status": "deleted"}


@router.post("/escalation-rules/evaluate", summary="Tier 3: manually trigger rule evaluation")
@limiter.limit("10/minute")
async def evaluate_escalation_rules(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Checks all active escalation rules against currently open (unacked) alerts.
    For alerts that have been open longer than the rule's threshold, fires the
    configured action (webhook POST or audit log entry).
    Returns a list of triggered rule/alert pairs.
    """
    import httpx

    rules = execute_read(
        "SELECT id, name, company_id, severity_filter, threshold_minutes, "
        "action_type, action_target, is_active, last_triggered_at "
        "FROM escalation_rules WHERE is_active = TRUE ORDER BY id",
        [],
    )
    triggered = []
    now = datetime.now(timezone.utc)

    for rule in rules:
        # Find unacked alerts matching this rule's severity + company filters
        conditions = ["acknowledged = 0", "severity = %s"]
        params: List[Any] = [rule["severity_filter"]]
        if rule["company_id"]:
            conditions.append("company_id = %s")
            params.append(rule["company_id"])

        alerts = execute_read(
            f"SELECT id, company_id, parameter, severity, timestamp FROM alerts WHERE {' AND '.join(conditions)}",
            params,
        )
        for alert in alerts:
            try:
                alert_ts = datetime.fromisoformat(str(alert["timestamp"]).replace("Z", "+00:00"))
                if alert_ts.tzinfo is None:
                    alert_ts = alert_ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            open_minutes = (now - alert_ts).total_seconds() / 60
            if open_minutes < rule["threshold_minutes"]:
                continue

            entry = {
                "rule_id":      rule["id"],
                "rule_name":    rule["name"],
                "alert_id":     alert["id"],
                "open_minutes": round(open_minutes, 1),
                "action":       rule["action_type"],
            }

            if rule["action_type"] == "webhook" and rule["action_target"]:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.post(rule["action_target"], json={
                            "rule":         rule["name"],
                            "alert_id":     alert["id"],
                            "company_id":   alert["company_id"],
                            "severity":     alert["severity"],
                            "open_minutes": round(open_minutes, 1),
                            "parameter":    alert["parameter"],
                        })
                    entry["webhook_status"] = "sent"
                except Exception as exc:
                    entry["webhook_status"] = f"failed: {exc}"
            else:
                entry["webhook_status"] = "logged"

            # Record the trigger
            _log_audit(
                _admin["id"], alert["company_id"],
                f"escalation_triggered:{rule['name']}",
                "escalation", "high",
                f"alert_id={alert['id']},open={round(open_minutes,1)}m",
                request.client.host if request.client else "unknown",
            )
            execute_write(
                "UPDATE escalation_rules SET last_triggered_at = NOW() WHERE id = %s",
                (rule["id"],),
            )
            triggered.append(entry)

    return {"evaluated": len(rules), "triggered": triggered}


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 4 — Operations Automation & Intelligence
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Tier 4 Pydantic models ───────────────────────────────────────────────────

class _MaintenanceWindowIn(BaseModel):
    company_id: int
    start_at:   str = Field(description="ISO 8601 datetime")
    end_at:     str = Field(description="ISO 8601 datetime")
    reason:     Optional[str] = None

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, v):
        return v.strip() if isinstance(v, str) else v


class _IncidentIn(BaseModel):
    company_id:  Optional[int] = None
    title:       str  = Field(min_length=3, max_length=200)
    description: Optional[str] = None
    severity:    str  = Field(default="medium")
    assignee_id: Optional[int] = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v):
        return v.strip() if isinstance(v, str) else v


class _IncidentUpdateIn(BaseModel):
    status:      Optional[str] = None   # open | investigating | resolved | closed
    severity:    Optional[str] = None
    assignee_id: Optional[int] = None
    title:       Optional[str] = None
    description: Optional[str] = None


class _IncidentNoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=4000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, v):
        return v.strip() if isinstance(v, str) else v


class _LinkAlertIn(BaseModel):
    alert_id: int


# ─── 1. Scheduled Maintenance Windows ────────────────────────────────────────

@router.get("/maintenance-windows", summary="Tier 4: list all maintenance windows")
@limiter.limit("60/minute")
async def list_maintenance_windows(
    request:    Request,
    company_id: Optional[int] = Query(None),
    include_past: bool        = Query(False),
    _admin: dict = Depends(require_super_admin),
):
    conditions = ["NOT is_cancelled"]
    params: List[Any] = []
    if company_id:
        conditions.append("mw.company_id = %s"); params.append(company_id)
    if not include_past:
        conditions.append("mw.end_at >= NOW()")
    where = "WHERE " + " AND ".join(conditions)
    rows = execute_read(
        f"""
        SELECT mw.id, mw.company_id, c.name AS company_name,
               mw.start_at, mw.end_at, mw.reason,
               a.name AS created_by_name, mw.created_at, mw.is_cancelled,
               CASE
                 WHEN NOW() < mw.start_at THEN 'upcoming'
                 WHEN NOW() BETWEEN mw.start_at AND mw.end_at THEN 'active'
                 ELSE 'expired'
               END AS window_status
          FROM maintenance_windows mw
          JOIN companies c ON c.id = mw.company_id
          LEFT JOIN admins a ON a.id = mw.created_by
         {where}
         ORDER BY mw.start_at DESC
         LIMIT 200
        """,
        params,
    )
    return rows


@router.post("/maintenance-windows", status_code=201, summary="Tier 4: schedule maintenance window")
@limiter.limit("20/minute")
async def create_maintenance_window(
    body:    _MaintenanceWindowIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    co = execute_read("SELECT name FROM companies WHERE id = %s", (body.company_id,))
    if not co:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        start = datetime.fromisoformat(body.start_at.replace("Z", "+00:00"))
        end   = datetime.fromisoformat(body.end_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid datetime format. Use ISO 8601.")
    if end <= start:
        raise HTTPException(status_code=422, detail="end_at must be after start_at")

    result = execute_write(
        """INSERT INTO maintenance_windows (company_id, start_at, end_at, reason, created_by)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (body.company_id, start.isoformat(), end.isoformat(), body.reason, _admin["id"]),
    )
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], body.company_id,
               f"schedule_maintenance:{co[0]['name']}",
               "maintenance", "medium",
               f"start={start.isoformat()},end={end.isoformat()}", ip)
    return {"id": result.lastrowid, "company": co[0]["name"], "start_at": start.isoformat(), "end_at": end.isoformat()}


@router.delete("/maintenance-windows/{window_id}", summary="Tier 4: cancel maintenance window")
@limiter.limit("20/minute")
async def cancel_maintenance_window(
    window_id: int,
    request:   Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT mw.*, c.name AS company_name FROM maintenance_windows mw JOIN companies c ON c.id = mw.company_id WHERE mw.id = %s",
        (window_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Window not found")
    execute_write("UPDATE maintenance_windows SET is_cancelled = TRUE WHERE id = %s", (window_id,))
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], rows[0]["company_id"],
               f"cancel_maintenance:{rows[0]['company_name']}",
               "maintenance", "medium", f"window_id={window_id}", ip)
    return {"status": "cancelled"}


@router.post("/maintenance-windows/apply", summary="Tier 4: sync company maintenance_mode with active windows")
@limiter.limit("10/minute")
async def apply_maintenance_windows(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    """
    Check active windows and toggle companies into/out of maintenance mode.
    Call this on a schedule (e.g., every minute from a cron job) or manually.
    """
    # Companies that should be in maintenance right now
    active = execute_read(
        """
        SELECT DISTINCT company_id FROM maintenance_windows
         WHERE NOT is_cancelled
           AND NOW() BETWEEN start_at AND end_at
        """,
        [],
    )
    active_ids = {r["company_id"] for r in active}

    # Companies that were auto-maintained but window expired
    should_exit = execute_read(
        """
        SELECT DISTINCT c.id, c.name
          FROM companies c
         WHERE c.maintenance_mode = 1
           AND c.id NOT IN (
               SELECT company_id FROM maintenance_windows
                WHERE NOT is_cancelled AND NOW() BETWEEN start_at AND end_at
           )
        """,
        [],
    ) if active_ids else execute_read(
        "SELECT id, name FROM companies WHERE maintenance_mode = 1",
        [],
    )

    entered, exited = [], []
    ip = request.client.host if request.client else "unknown"

    for cid in active_ids:
        co = execute_read("SELECT id, name, maintenance_mode FROM companies WHERE id = %s", (cid,))
        if co and not co[0]["maintenance_mode"]:
            execute_write("UPDATE companies SET maintenance_mode = 1 WHERE id = %s", (cid,))
            _log_audit(_admin["id"], cid, f"auto_maintenance_enter:{co[0]['name']}",
                       "maintenance", "low", "triggered by active window", ip)
            entered.append(co[0]["name"])

    for row in should_exit:
        execute_write("UPDATE companies SET maintenance_mode = 0 WHERE id = %s", (row["id"],))
        _log_audit(_admin["id"], row["id"], f"auto_maintenance_exit:{row['name']}",
                   "maintenance", "low", "window expired", ip)
        exited.append(row["name"])

    return {"entered_maintenance": entered, "exited_maintenance": exited}


# ─── 2. Incident Management ───────────────────────────────────────────────────

@router.get("/incidents", summary="Tier 4: list incidents")
@limiter.limit("60/minute")
async def list_incidents(
    request:    Request,
    company_id: Optional[int] = Query(None),
    status:     Optional[str] = Query(None),
    severity:   Optional[str] = Query(None),
    limit:      int           = Query(50, ge=1, le=200),
    _admin: dict = Depends(require_super_admin),
):
    conditions: List[str] = []
    params: List[Any] = []
    if company_id:
        conditions.append("i.company_id = %s"); params.append(company_id)
    if status:
        conditions.append("i.status = %s"); params.append(status)
    if severity:
        conditions.append("i.severity = %s"); params.append(severity)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = execute_read(
        f"""
        SELECT i.id, i.company_id, c.name AS company_name,
               i.title, i.description, i.severity, i.status,
               ass.name AS assignee_name, cr.name AS created_by_name,
               i.created_at, i.updated_at, i.resolved_at,
               (SELECT COUNT(*) FROM incident_notes n WHERE n.incident_id = i.id) AS note_count,
               (SELECT COUNT(*) FROM incident_alerts ia WHERE ia.incident_id = i.id) AS alert_count
          FROM incidents i
          LEFT JOIN companies c   ON c.id  = i.company_id
          LEFT JOIN admins    ass ON ass.id = i.assignee_id
          LEFT JOIN admins    cr  ON cr.id  = i.created_by
         {where}
         ORDER BY
           CASE i.status WHEN 'open' THEN 0 WHEN 'investigating' THEN 1 ELSE 2 END,
           CASE i.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
           i.created_at DESC
         LIMIT %s
        """,
        params + [limit],
    )
    return rows


@router.post("/incidents", status_code=201, summary="Tier 4: create incident")
@limiter.limit("20/minute")
async def create_incident(
    body:    _IncidentIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    result = execute_write(
        """INSERT INTO incidents (company_id, title, description, severity, assignee_id, created_by)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (body.company_id, body.title, body.description, body.severity, body.assignee_id, _admin["id"]),
    )
    inc_id = result.lastrowid
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], body.company_id, f"create_incident:{body.title}",
               "incident", "medium", f"severity={body.severity}", ip)
    return {"id": inc_id, "title": body.title, "severity": body.severity}


@router.get("/incidents/{incident_id}", summary="Tier 4: get incident detail with notes + linked alerts")
@limiter.limit("60/minute")
async def get_incident(
    incident_id: int,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT i.*, c.name AS company_name,
               ass.name AS assignee_name, cr.name AS created_by_name
          FROM incidents i
          LEFT JOIN companies c   ON c.id  = i.company_id
          LEFT JOIN admins    ass ON ass.id = i.assignee_id
          LEFT JOIN admins    cr  ON cr.id  = i.created_by
         WHERE i.id = %s
        """,
        (incident_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Incident not found")

    notes = execute_read(
        """
        SELECT n.id, n.note, a.name AS author_name, n.created_at
          FROM incident_notes n
          LEFT JOIN admins a ON a.id = n.author_id
         WHERE n.incident_id = %s
         ORDER BY n.created_at ASC
        """,
        (incident_id,),
    )
    linked_alerts = execute_read(
        """
        SELECT al.id, al.parameter, al.value, al.threshold, al.severity,
               al.timestamp, al.acknowledged, c.name AS company_name
          FROM incident_alerts ia
          JOIN alerts al ON al.id = ia.alert_id
          LEFT JOIN companies c ON c.id = al.company_id
         WHERE ia.incident_id = %s
         ORDER BY al.timestamp DESC
        """,
        (incident_id,),
    )
    return {**dict(rows[0]), "notes": notes, "linked_alerts": linked_alerts}


@router.patch("/incidents/{incident_id}", summary="Tier 4: update incident")
@limiter.limit("30/minute")
async def update_incident(
    incident_id: int,
    body:        _IncidentUpdateIn,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, title, description, status, severity, assignee_id, "
        "company_id, created_at, updated_at, resolved_at "
        "FROM incidents WHERE id = %s",
        (incident_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Incident not found")

    inc = rows[0]
    new_status   = body.status   or inc["status"]
    new_severity = body.severity or inc["severity"]
    new_assignee = body.assignee_id if body.assignee_id is not None else inc["assignee_id"]
    new_title    = body.title   or inc["title"]
    new_desc     = body.description if body.description is not None else inc["description"]

    resolved_at = inc["resolved_at"]
    if new_status in ("resolved", "closed") and not resolved_at:
        resolved_at = datetime.now(timezone.utc).isoformat()

    execute_write(
        """UPDATE incidents
              SET status = %s, severity = %s, assignee_id = %s,
                  title = %s, description = %s, resolved_at = %s,
                  updated_at = NOW()
            WHERE id = %s""",
        (new_status, new_severity, new_assignee, new_title, new_desc, resolved_at, incident_id),
    )
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], inc["company_id"],
               f"update_incident:{inc['title']}→{new_status}",
               "incident", "low", f"severity={new_severity}", ip)
    return {"status": "updated", "incident_id": incident_id, "new_status": new_status}


@router.post("/incidents/{incident_id}/notes", status_code=201, summary="Tier 4: add note to incident")
@limiter.limit("30/minute")
async def add_incident_note(
    incident_id: int,
    body:        _IncidentNoteIn,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id, title, company_id FROM incidents WHERE id = %s", (incident_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Incident not found")
    result = execute_write(
        "INSERT INTO incident_notes (incident_id, author_id, note) VALUES (%s, %s, %s) RETURNING id",
        (incident_id, _admin["id"], body.note),
    )
    execute_write("UPDATE incidents SET updated_at = NOW() WHERE id = %s", (incident_id,))
    return {"id": result.lastrowid, "incident_id": incident_id}


@router.post("/incidents/{incident_id}/link-alert", status_code=201, summary="Tier 4: link alert to incident")
@limiter.limit("30/minute")
async def link_alert_to_incident(
    incident_id: int,
    body:        _LinkAlertIn,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id FROM incidents WHERE id = %s", (incident_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Incident not found")
    try:
        execute_write(
            "INSERT INTO incident_alerts (incident_id, alert_id) VALUES (%s, %s)",
            (incident_id, body.alert_id),
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return {"status": "already_linked"}
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "linked", "incident_id": incident_id, "alert_id": body.alert_id}


@router.delete("/incidents/{incident_id}", summary="Tier 4: delete incident")
@limiter.limit("10/minute")
async def delete_incident(
    incident_id: int,
    request:     Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT title, company_id FROM incidents WHERE id = %s", (incident_id,))
    if not rows:
        raise HTTPException(status_code=404, detail="Incident not found")
    execute_write("DELETE FROM incidents WHERE id = %s", (incident_id,))
    ip = request.client.host if request.client else "unknown"
    _log_audit(_admin["id"], rows[0]["company_id"], f"delete_incident:{rows[0]['title']}",
               "incident", "medium", f"incident_id={incident_id}", ip)
    return {"status": "deleted"}


# ─── 3. SLA Performance Dashboard ────────────────────────────────────────────

@router.get("/sla/metrics", summary="Tier 4: per-company SLA metrics")
@limiter.limit("30/minute")
async def sla_metrics(
    request: Request,
    days:    int = Query(30, ge=1, le=90),
    _admin: dict = Depends(require_super_admin),
):
    """
    For each company: avg time-to-acknowledge (minutes), total alerts,
    acked alerts, ack rate, and a composite SLA score (0-100).
    """
    rows = execute_read(
        """
        SELECT
            c.id AS company_id,
            c.name AS company_name,
            c.is_active,
            COUNT(a.id)                                                 AS total_alerts,
            COUNT(a.id) FILTER (WHERE a.acknowledged = 1)               AS acked_alerts,
            COUNT(a.id) FILTER (WHERE a.acknowledged = 0)               AS unacked_alerts,
            COUNT(a.id) FILTER (WHERE UPPER(a.severity) IN ('CRITICAL','EMERGENCY')) AS critical_total,
            COUNT(a.id) FILTER (WHERE UPPER(a.severity) IN ('CRITICAL','EMERGENCY') AND a.acknowledged = 1) AS critical_acked,
            ROUND(
                AVG(
                    CASE WHEN a.acknowledged = 1 AND a.acknowledged_at IS NOT NULL
                         THEN EXTRACT(EPOCH FROM (
                                a.acknowledged_at::timestamptz - a.timestamp::timestamptz
                              )) / 60.0
                    END
                )::numeric, 1
            ) AS avg_ack_minutes,
            ROUND(
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY
                        CASE WHEN a.acknowledged = 1 AND a.acknowledged_at IS NOT NULL
                             THEN EXTRACT(EPOCH FROM (
                                    a.acknowledged_at::timestamptz - a.timestamp::timestamptz
                                  )) / 60.0
                        END
                )::numeric, 1
            ) AS median_ack_minutes
          FROM companies c
          LEFT JOIN alerts a
                 ON a.company_id = c.id
                AND a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval
         GROUP BY c.id, c.name, c.is_active
         ORDER BY total_alerts DESC
        """,
        (days,),
    )

    result = []
    for r in rows:
        row = dict(r)
        total = row["total_alerts"] or 0
        acked = row["acked_alerts"] or 0
        ack_rate = round(acked / total * 100, 1) if total else 100.0
        avg_min  = float(row["avg_ack_minutes"]) if row["avg_ack_minutes"] is not None else None

        # SLA score: 100 = perfect. Deductions: -1 per % unacked, -0.5 per min avg ack delay (capped at 30)
        score = 100.0
        score -= (100 - ack_rate)
        if avg_min is not None:
            score -= min(30.0, avg_min * 0.5)
        score = max(0.0, round(score, 1))

        row["ack_rate"]  = ack_rate
        row["sla_score"] = score
        row["sla_grade"] = (
            "A" if score >= 90 else
            "B" if score >= 75 else
            "C" if score >= 60 else
            "D" if score >= 40 else "F"
        )
        result.append(row)

    return result


@router.get("/sla/leaderboard", summary="Tier 4: SLA leaderboard (best to worst)")
@limiter.limit("30/minute")
async def sla_leaderboard(
    request: Request,
    days:    int = Query(30, ge=1, le=90),
    _admin: dict = Depends(require_super_admin),
):
    all_metrics = await sla_metrics(request=request, days=days, _admin=_admin)
    # Sort by sla_score desc, exclude companies with 0 alerts
    active = [r for r in all_metrics if r["total_alerts"] > 0]
    active.sort(key=lambda x: x["sla_score"], reverse=True)
    return {"days": days, "companies": active}


# ─── 4. Statistical Anomaly Detection ────────────────────────────────────────

@router.get("/anomaly-detection", summary="Tier 4: z-score outlier detection across companies")
@limiter.limit("20/minute")
async def detect_anomalies(
    request:   Request,
    window:    int = Query(7, ge=1, le=30, description="Recent window in days to compare against baseline"),
    baseline:  int = Query(30, ge=7, le=90, description="Baseline window in days"),
    threshold: float = Query(2.0, ge=1.0, le=5.0, description="Z-score threshold for anomaly"),
    _admin: dict = Depends(require_super_admin),
):
    """
    For each company, compare recent alert rate (last `window` days) against
    baseline rate (last `baseline` days). Flag companies whose recent rate
    deviates more than `threshold` standard deviations from the fleet mean.
    """
    rows = execute_read(
        """
        SELECT
            c.id AS company_id, c.name AS company_name,
            COUNT(a.id) FILTER (
                WHERE a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval
            ) AS recent_count,
            COUNT(a.id) FILTER (
                WHERE a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval
            ) AS baseline_count,
            COUNT(a.id) FILTER (
                WHERE UPPER(a.severity) IN ('CRITICAL','EMERGENCY')
                  AND a.timestamp::timestamptz >= NOW() - (%s || ' days')::interval
            ) AS recent_critical
          FROM companies c
          LEFT JOIN alerts a ON a.company_id = c.id
         WHERE c.is_active = 1
         GROUP BY c.id, c.name
        """,
        (window, baseline, window),
    )

    if not rows:
        return {"anomalies": [], "fleet_stats": {}}

    # Normalise baseline to same day-count as window for fair comparison
    rates = []
    for r in rows:
        bc = r["baseline_count"] or 0
        rc = r["recent_count"]   or 0
        baseline_daily = bc / baseline if baseline else 0
        recent_daily   = rc / window   if window   else 0
        rates.append({
            "company_id":   r["company_id"],
            "company_name": r["company_name"],
            "recent_count": rc,
            "recent_critical": r["recent_critical"] or 0,
            "recent_daily":    round(recent_daily,   2),
            "baseline_daily":  round(baseline_daily, 2),
        })

    # Fleet statistics
    vals = [r["recent_daily"] for r in rates]
    n = len(vals)
    if n < 2:
        return {"anomalies": [], "fleet_stats": {"n": n}}

    import statistics
    mean = statistics.mean(vals)
    std  = statistics.stdev(vals) if n > 1 else 0.0

    anomalies = []
    for r in rates:
        z = (r["recent_daily"] - mean) / std if std > 0 else 0.0
        r["z_score"] = round(z, 2)
        r["mean_daily"] = round(mean, 2)
        r["std_daily"]  = round(std, 2)
        if abs(z) >= threshold:
            r["direction"] = "spike" if z > 0 else "quiet"
            r["anomaly"]   = True
            anomalies.append(r)
        else:
            r["anomaly"] = False

    anomalies.sort(key=lambda x: abs(x["z_score"]), reverse=True)

    return {
        "anomalies":   anomalies,
        "all_companies": rates,
        "fleet_stats": {
            "n":           n,
            "mean_daily":  round(mean, 2),
            "std_daily":   round(std,  2),
            "window_days": window,
            "baseline_days": baseline,
            "threshold":   threshold,
        },
    }


# ─── 5. Export: Maintenance Windows CSV ──────────────────────────────────────

@router.get("/export/maintenance.csv", summary="Tier 4: export maintenance windows as CSV")
@limiter.limit("10/minute")
async def export_maintenance_csv(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT mw.id, c.name AS company, mw.start_at, mw.end_at, mw.reason,
               a.name AS created_by, mw.created_at, mw.is_cancelled
          FROM maintenance_windows mw
          JOIN companies c ON c.id = mw.company_id
          LEFT JOIN admins a ON a.id = mw.created_by
         ORDER BY mw.start_at DESC
         LIMIT 5000
        """,
        [],
    )
    buf = _io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["ID", "Company", "Start", "End", "Reason", "Created By", "Created At", "Cancelled"])
    for r in rows:
        w.writerow([r["id"], r["company"], r["start_at"], r["end_at"],
                    r["reason"], r["created_by"], r["created_at"], r["is_cancelled"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=maintenance_windows.csv"},
    )


@router.get("/export/incidents.csv", summary="Tier 4: export incidents as CSV")
@limiter.limit("10/minute")
async def export_incidents_csv(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    rows = execute_read(
        """
        SELECT i.id, c.name AS company, i.title, i.severity, i.status,
               ass.name AS assignee, cr.name AS created_by,
               i.created_at, i.resolved_at
          FROM incidents i
          LEFT JOIN companies c   ON c.id  = i.company_id
          LEFT JOIN admins    ass ON ass.id = i.assignee_id
          LEFT JOIN admins    cr  ON cr.id  = i.created_by
         ORDER BY i.created_at DESC
         LIMIT 5000
        """,
        [],
    )
    buf = _io.StringIO()
    w   = csv.writer(buf)
    w.writerow(["ID", "Company", "Title", "Severity", "Status", "Assignee", "Created By", "Created At", "Resolved At"])
    for r in rows:
        w.writerow([r["id"], r["company"], r["title"], r["severity"],
                    r["status"], r["assignee"], r["created_by"], r["created_at"], r["resolved_at"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=incidents.csv"},
    )


# ─── System Logs ─────────────────────────────────────────────────────────────

# Sourced from utils.logger so this can never drift from where logs are written
# (project root logs/, not backend/logs/).
_LOG_PATH = (_LOGS_DIR / "sentineledge.log").resolve()

_LEVEL_KEYWORDS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")

def _detect_level(line: str) -> str:
    u = line.upper()
    for lvl in _LEVEL_KEYWORDS:
        if lvl in u:
            return lvl
    return "INFO"


@router.get("/system-logs", summary="Read recent lines from the backend log file")
@limiter.limit("60/minute")
async def system_logs(
    request: Request,
    lines: int  = Query(default=200, ge=10, le=500),
    level: str  = Query(default=""),
    search: str = Query(default=""),
    _admin: dict = Depends(require_super_admin),
):
    """
    Return the last `lines` entries from sentineledge.log.
    Optional filters: level (INFO/WARNING/ERROR/CRITICAL/DEBUG), search (substring).
    Each entry: {text, level}.
    """
    if not _LOG_PATH.exists():
        return {"lines": [], "total": 0, "exists": False, "path": str(_LOG_PATH)}

    try:
        # Tail-read: read last 64 KB so we never load the whole file
        CHUNK = 1024 * 64
        with open(_LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(-min(size, CHUNK), 2)
            raw = f.read()

        all_lines = raw.decode("utf-8", errors="replace").splitlines()
        all_lines = [l for l in all_lines if l.strip()]

        level_upper  = level.upper().strip()
        search_lower = search.lower().strip()

        result = []
        for line in all_lines[-lines:]:
            lvl = _detect_level(line)
            if level_upper and level_upper not in lvl:
                continue
            if search_lower and search_lower not in line.lower():
                continue
            result.append({"text": line, "level": lvl})

        return {"lines": result, "total": len(result), "exists": True}

    except Exception as exc:
        logger.error("system_logs failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

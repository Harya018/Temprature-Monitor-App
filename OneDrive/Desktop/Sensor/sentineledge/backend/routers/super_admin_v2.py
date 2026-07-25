"""
routers/super_admin_v2.py — Extended Super Admin endpoints.

All routes require role = 'super_admin', enforced by require_super_admin
imported from the existing super_admin.py (unchanged).

Prefix: /api/super-admin
Tags:   Super Admin

New routes (supplements super_admin.py which is left untouched):
  GET    /api/super-admin/overview
  PATCH  /api/super-admin/companies/{id}
  DELETE /api/super-admin/companies/{id}
  GET    /api/super-admin/companies/{id}/admins
  GET    /api/super-admin/admins
  POST   /api/super-admin/admins
  GET    /api/super-admin/admins/{id}
  PATCH  /api/super-admin/admins/{id}/toggle
  PUT    /api/super-admin/admins/{id}/password
  PATCH  /api/super-admin/admins/{id}/company
  GET    /api/super-admin/admins/{id}/activity
  GET    /api/super-admin/admins/{id}/subscribers
  POST   /api/super-admin/broadcast
  GET    /api/super-admin/broadcast
  GET    /api/super-admin/sessions
  GET    /api/super-admin/live-feed
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from routers.super_admin import require_super_admin
from utils.logger import get_logger
from utils.security import hash_pin

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin", tags=["Super Admin"])


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


class _AdminCreateIn(BaseModel):
    name:       str = Field(min_length=2, max_length=50)
    password:   str = Field(min_length=6, max_length=200)
    role:       str = Field(default="sub")
    company_id: Optional[int] = None

    @field_validator("name", "password", mode="before")
    @classmethod
    def strip_fields(cls, v):
        return v.strip() if isinstance(v, str) else v


class _AdminPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=200)

    @field_validator("new_password", mode="before")
    @classmethod
    def strip_pwd(cls, v):
        return v.strip() if isinstance(v, str) else v


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

    rows = execute_read(
        "SELECT id, name, password_hash, company_id, COALESCE(requires_2fa, 0) AS requires_2fa FROM admins WHERE LOWER(name) = %s AND role = 'super_admin'",
        (body.username.strip().lower(),),
    )

    if not rows or not verify_pin(body.password.strip(), rows[0]["password_hash"]):
        try:
            execute_write(
                "INSERT INTO login_attempts (ip, username, success) VALUES (%s, %s, 0)",
                (client_ip, body.username.strip()),
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=401,
            content={"error": "InvalidCredentials", "message": "Invalid username or password"},
        )

    admin      = rows[0]
    token      = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)

    execute_write(
        "INSERT INTO admin_sessions (token, expires_at, admin_id) VALUES (%s, %s, %s)",
        (token, expires_at, admin["id"]),
    )

    try:
        execute_write(
            "INSERT INTO login_attempts (ip, username, success) VALUES (%s, %s, 1)",
            (client_ip, admin["name"]),
        )
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
        total_companies  = execute_read("SELECT COUNT(*) AS cnt FROM companies")[0]["cnt"]
        active_admins    = execute_read("SELECT COUNT(*) AS cnt FROM admins WHERE is_active = 1 OR is_active IS NULL")[0]["cnt"]
        total_subs       = execute_read("SELECT COUNT(*) AS cnt FROM subscribers WHERE is_active = 1 OR is_active IS NULL")[0]["cnt"]
        alerts_today     = execute_read("SELECT COUNT(*) AS cnt FROM alerts WHERE timestamp >= %s", (today,))[0]["cnt"]
        alerts_week      = execute_read("SELECT COUNT(*) AS cnt FROM alerts WHERE timestamp >= %s", (week,))[0]["cnt"]

        company_rows = execute_read(
            """
            SELECT c.id, c.name, c.is_active,
                   (SELECT COUNT(*) FROM subscribers WHERE company_id = c.id) AS subscriber_count,
                   (SELECT COUNT(*) FROM alerts WHERE company_id = c.id AND timestamp >= %s) AS alerts_today
            FROM companies c ORDER BY c.id
            """,
            (today,),
        )

        return {
            "total_companies":  total_companies,
            "active_admins":    active_admins,
            "total_subscribers": total_subs,
            "alerts_today":     alerts_today,
            "alerts_week":      alerts_week,
            "companies":        company_rows,
        }
    except Exception as exc:
        logger.error("overview failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return _get_company_or_404(company_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_company failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        execute_write("DELETE FROM companies WHERE id = %s", (company_id,))
        return {"status": "deleted", "company_id": company_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_company failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat()
        result = execute_write(
            "INSERT INTO admins (name, password_hash, role, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
            (body.name, hash_pin(body.password), body.role, ts),
        )
        if body.company_id:
            execute_write("UPDATE admins SET company_id = %s WHERE id = %s", (body.company_id, result.lastrowid))
        logger.info("Admin created by super_admin: name=%s role=%s", body.name, body.role)
        return _get_admin_or_404(result.lastrowid)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return JSONResponse(status_code=409, content={"error": f"Admin '{body.name}' already exists"})
        logger.error("create_admin failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return _get_admin_or_404(admin_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("toggle_admin failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        # Invalidate all sessions for this admin
        execute_write("DELETE FROM admin_sessions")
        logger.info("Password reset for admin id=%d", admin_id)
        return {"status": "updated", "admin_id": admin_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reset_admin_password failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.patch("/admins/{admin_id}/company", summary="Assign admin to company")
@limiter.limit("30/minute")
async def assign_admin_company(
    admin_id: int,
    body: _AdminCompanyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_admin_or_404(admin_id)
        if body.company_id is not None:
            rows = execute_read("SELECT id FROM companies WHERE id = %s", (body.company_id,))
            if not rows:
                raise HTTPException(status_code=404, detail=f"Company {body.company_id} not found")
        execute_write("UPDATE admins SET company_id = %s WHERE id = %s", (body.company_id, admin_id))
        return _get_admin_or_404(admin_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("assign_admin_company failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        from core.threshold import get_thresholds
        thresholds = get_thresholds()
        temp = reading["temperature"]
        status = "normal"
        if thresholds:
            t_high = thresholds.get("temp_high")
            t_low  = thresholds.get("temp_low")
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
        return JSONResponse(status_code=500, content={"error": str(exc)})

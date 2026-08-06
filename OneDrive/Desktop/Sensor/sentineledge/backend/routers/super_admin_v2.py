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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from routers.super_admin import require_super_admin
from utils.logger import get_logger
from utils.security import hash_pin
from utils.rate_limiter import check_rate_limit, record_attempt, clear_failed_attempts, remaining_attempts

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
        updated = _get_admin_or_404(admin_id)
        if updated.get("is_active") == 0:
            # Task 2A: kill all active sessions immediately on deactivation
            execute_write("DELETE FROM admin_sessions WHERE admin_id = %s", (admin_id,))
        return updated
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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
               SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) AS critical,
               SUM(CASE WHEN severity = 'warning'  THEN 1 ELSE 0 END) AS warning
          FROM alerts
         WHERE company_id = %s
           AND timestamp >= %s AND timestamp < %s
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
        return JSONResponse(status_code=500, content={"error": str(exc)})


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
        return JSONResponse(status_code=500, content={"error": str(exc)})

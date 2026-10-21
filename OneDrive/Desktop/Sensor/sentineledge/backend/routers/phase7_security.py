"""
routers/phase7_security.py â€” Phase 7: Security & Compliance.

All routes require super_admin role.
Login-attempt & audit routes use full require_super_admin (IP whitelist + 2FA).
2FA OTP routes use _require_sa_skip2fa (skips 2FA check so user can complete verification).

Prefix: /api/super-admin/security
"""

import csv
import hashlib
import io
import random
import smtplib
import string
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from routers.super_admin_v2 import require_super_admin
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/security", tags=["Security"])


# â”€â”€â”€ Light dependency â€” validates token + super_admin role, SKIPS 2FA check â”€â”€
# Used by 2FA routes so the user can complete OTP verification before the flag
# is set on their session (would otherwise deadlock).

def _require_sa_skip2fa(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token> header")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    from database.queries.sessions import get_session
    session = get_session(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")

    rows = execute_read(
        """
        SELECT a.id, a.name, a.role, a.company_id,
               a.email, COALESCE(a.requires_2fa, 0) AS requires_2fa,
               COALESCE(s.two_fa_verified, 0) AS two_fa_verified,
               s.id AS session_id
        FROM admins a
        JOIN admin_sessions s ON s.admin_id = a.id AND s.token = %s AND s.expires_at > NOW()
        WHERE a.role = 'super_admin'
        LIMIT 1
        """,
        (token,),
    )
    if not rows:
        raise HTTPException(status_code=403, detail="Super admin role required")

    # Phase 7: IP whitelist check (same logic as require_super_admin)
    try:
        whitelist = execute_read("SELECT ip FROM ip_whitelist")
        if whitelist:
            client_ip = request.client.host if request.client else "unknown"
            allowed = {row["ip"] for row in whitelist}
            if client_ip not in allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied: IP {client_ip} is not whitelisted",
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("IP whitelist check failed (non-fatal): %s", exc)

    return rows[0]


# â”€â”€â”€ Pydantic bodies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _WhitelistIn(BaseModel):
    ip:   str = Field(min_length=7, max_length=45)
    note: Optional[str] = None

    @field_validator("ip", mode="before")
    @classmethod
    def strip_ip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _RetentionIn(BaseModel):
    entity:   str = Field(min_length=1, max_length=80)
    max_days: int = Field(ge=1, le=3650)
    enabled:  int = Field(default=1, ge=0, le=1)


class _IncidentIn(BaseModel):
    title:       str = Field(min_length=2, max_length=200)
    description: Optional[str] = None
    severity:    str = Field(default="medium")
    company_id:  Optional[int] = None

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v):
        allowed = {"low", "medium", "high", "critical"}
        v = str(v).lower().strip()
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class _IncidentUpdateIn(BaseModel):
    status:      Optional[str] = None
    title:       Optional[str] = None
    description: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return v
        allowed = {"open", "investigating", "resolved", "closed"}
        v = str(v).lower().strip()
        if v not in allowed:
            raise ValueError(f"status must be one of {allowed}")
        return v


class _TwoFASetupIn(BaseModel):
    admin_id: int
    email:    str = Field(min_length=5, max_length=200)
    enabled:  int = Field(default=1, ge=0, le=1)

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, v):
        return v.strip() if isinstance(v, str) else v


class _OTPVerifyIn(BaseModel):
    otp: str = Field(min_length=6, max_length=8)


# â”€â”€â”€ Login Attempts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/login-attempts", summary="Login attempt log")
@limiter.limit("30/minute")
async def list_login_attempts(
    request: Request,
    days: int = 7,
    ip: Optional[str] = None,
    success: Optional[int] = None,
    limit: int = 200,
    _admin: dict = Depends(require_super_admin),
):
    try:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))
        if ip is not None and success is not None:
            rows = execute_read(
                "SELECT id, ip, username, success, attempted_at::TEXT FROM login_attempts WHERE attempted_at >= %s AND ip = %s AND success = %s ORDER BY id DESC LIMIT %s",
                (since, ip, success, limit),
            )
        elif ip is not None:
            rows = execute_read(
                "SELECT id, ip, username, success, attempted_at::TEXT FROM login_attempts WHERE attempted_at >= %s AND ip = %s ORDER BY id DESC LIMIT %s",
                (since, ip, limit),
            )
        elif success is not None:
            rows = execute_read(
                "SELECT id, ip, username, success, attempted_at::TEXT FROM login_attempts WHERE attempted_at >= %s AND success = %s ORDER BY id DESC LIMIT %s",
                (since, success, limit),
            )
        else:
            rows = execute_read(
                "SELECT id, ip, username, success, attempted_at::TEXT FROM login_attempts WHERE attempted_at >= %s ORDER BY id DESC LIMIT %s",
                (since, limit),
            )
        return rows
    except Exception as exc:
        logger.error("list_login_attempts failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/login-attempts/blocked", summary="IPs with repeated failures (last 15 min)")
@limiter.limit("30/minute")
async def blocked_ips(
    request: Request,
    threshold: int = 5,
    _admin: dict = Depends(require_super_admin),
):
    try:
        since = datetime.now(timezone.utc) - timedelta(minutes=15)
        rows = execute_read(
            """
            SELECT ip, COUNT(*) AS failures, MAX(attempted_at)::TEXT AS last_attempt
            FROM login_attempts
            WHERE success = 0 AND attempted_at >= %s
            GROUP BY ip
            HAVING COUNT(*) >= %s
            ORDER BY failures DESC
            """,
            (since, threshold),
        )
        return rows
    except Exception as exc:
        logger.error("blocked_ips failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


# â”€â”€â”€ IP Whitelist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/ip-whitelist", summary="List whitelisted IPs")
@limiter.limit("30/minute")
async def list_whitelist(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT w.id, w.ip, w.note, w.added_at::TEXT,
                   a.name AS added_by_name
            FROM ip_whitelist w
            LEFT JOIN admins a ON a.id = w.added_by
            ORDER BY w.id DESC
            """
        )
        return rows
    except Exception as exc:
        logger.error("list_whitelist failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/ip-whitelist", status_code=201, summary="Add IP to whitelist")
@limiter.limit("20/minute")
async def add_whitelist(
    body: _WhitelistIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            "INSERT INTO ip_whitelist (ip, note, added_by) VALUES (%s, %s, %s) RETURNING id",
            (body.ip, body.note, _admin["id"]),
        )
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "ip_whitelist_add", "ip_whitelist", f"ip:{body.ip}", _admin.get("company_id"))
        row = execute_read("SELECT id, ip, note, added_at::TEXT FROM ip_whitelist WHERE id = %s", (result.lastrowid,))
        return row[0] if row else {"status": "created"}
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return JSONResponse(status_code=409, content={"error": f"IP {body.ip} already whitelisted"})
        logger.error("add_whitelist failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.delete("/ip-whitelist/{entry_id}", summary="Remove IP from whitelist")
@limiter.limit("20/minute")
async def remove_whitelist(
    entry_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read("SELECT ip FROM ip_whitelist WHERE id = %s", (entry_id,))
        if not rows:
            raise HTTPException(status_code=404, detail=f"Whitelist entry {entry_id} not found")
        execute_write("DELETE FROM ip_whitelist WHERE id = %s", (entry_id,))
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "ip_whitelist_remove", "ip_whitelist", f"ip:{rows[0]['ip']}", _admin.get("company_id"))
        return {"status": "deleted", "id": entry_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("remove_whitelist failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


# â”€â”€â”€ Audit Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/audit", summary="Admin activity audit log")
@limiter.limit("30/minute")
async def audit_log(
    request: Request,
    from_date: Optional[str] = None,
    to_date:   Optional[str] = None,
    admin_id:  Optional[int] = None,
    action:    Optional[str] = None,
    limit: int = 200,
    _admin: dict = Depends(require_super_admin),
):
    try:
        clauses, params = [], []
        if from_date:
            clauses.append("act.created_at >= %s"); params.append(from_date)
        if to_date:
            clauses.append("act.created_at <= %s"); params.append(to_date)
        if admin_id:
            clauses.append("act.admin_id = %s"); params.append(admin_id)
        if action:
            clauses.append("act.action = %s"); params.append(action)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = execute_read(
            f"""
            SELECT act.id, act.action, act.entity, act.details,
                   act.created_at::TEXT, act.admin_id, a.name AS admin_name,
                   act.company_id
            FROM admin_activity act
            LEFT JOIN admins a ON a.id = act.admin_id
            {where}
            ORDER BY act.id DESC LIMIT %s
            """,
            tuple(params),
        )
        return rows
    except Exception as exc:
        logger.error("audit_log failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/audit/export", summary="Export audit log as CSV")
@limiter.limit("5/minute")
async def audit_export(
    request: Request,
    days: int = 30,
    _admin: dict = Depends(require_super_admin),
):
    try:
        since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
        rows = execute_read(
            """
            SELECT act.id, act.action, act.entity, act.details,
                   act.created_at::TEXT, a.name AS admin_name, act.company_id
            FROM admin_activity act
            LEFT JOIN admins a ON a.id = act.admin_id
            WHERE act.created_at >= %s
            ORDER BY act.id DESC
            """,
            (since,),
        )

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "action", "entity", "details", "created_at", "admin_name", "company_id"])
        for r in rows:
            writer.writerow([
                r.get("id"), r.get("action"), r.get("entity"),
                r.get("details"), r.get("created_at"),
                r.get("admin_name"), r.get("company_id"),
            ])

        buf.seek(0)
        filename = f"audit_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        logger.error("audit_export failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


# â”€â”€â”€ Retention Policies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/retention", summary="List retention policies")
@limiter.limit("30/minute")
async def list_retention(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            "SELECT id, entity, max_days, enabled, updated_at::TEXT FROM retention_policies ORDER BY entity"
        )
        return rows
    except Exception as exc:
        logger.error("list_retention failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/retention", summary="Upsert a retention policy")
@limiter.limit("20/minute")
async def upsert_retention(
    body: _RetentionIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        execute_write(
            """
            INSERT INTO retention_policies (entity, max_days, enabled, set_by, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (entity) DO UPDATE
              SET max_days = EXCLUDED.max_days,
                  enabled  = EXCLUDED.enabled,
                  set_by   = EXCLUDED.set_by,
                  updated_at = NOW()
            """,
            (body.entity, body.max_days, body.enabled, _admin["id"]),
        )
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "retention_update", "retention_policies", f"{body.entity}:{body.max_days}d", _admin.get("company_id"))
        row = execute_read("SELECT id, entity, max_days, enabled, updated_at::TEXT FROM retention_policies WHERE entity = %s", (body.entity,))
        return row[0] if row else {"status": "upserted"}
    except Exception as exc:
        logger.error("upsert_retention failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


# â”€â”€â”€ Incident Reports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/incidents", summary="List incident reports")
@limiter.limit("30/minute")
async def list_incidents(
    request: Request,
    company_id: Optional[int] = None,
    status:     Optional[str] = None,
    limit: int = 100,
    _admin: dict = Depends(require_super_admin),
):
    try:
        clauses, params = [], []
        if company_id:
            clauses.append("ir.company_id = %s"); params.append(company_id)
        if status:
            clauses.append("ir.status = %s"); params.append(status)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = execute_read(
            f"""
            SELECT ir.id, ir.company_id, ir.title, ir.description,
                   ir.severity, ir.status,
                   ir.created_at::TEXT, ir.resolved_at::TEXT,
                   c.name AS company_name,
                   a.name AS created_by_name,
                   r.name AS resolved_by_name
            FROM incident_reports ir
            LEFT JOIN companies c ON c.id = ir.company_id
            LEFT JOIN admins a ON a.id = ir.created_by
            LEFT JOIN admins r ON r.id = ir.resolved_by
            {where}
            ORDER BY ir.id DESC LIMIT %s
            """,
            tuple(params),
        )
        return rows
    except Exception as exc:
        logger.error("list_incidents failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/incidents", status_code=201, summary="Create incident report")
@limiter.limit("20/minute")
async def create_incident(
    body: _IncidentIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            """
            INSERT INTO incident_reports (company_id, title, description, severity, created_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (body.company_id, body.title, body.description, body.severity, _admin["id"]),
        )
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "incident_create", "incident_reports", f"{body.severity}:{body.title}", _admin.get("company_id"))
        rows = execute_read("SELECT id, title, severity, status, created_at::TEXT FROM incident_reports WHERE id = %s", (result.lastrowid,))
        return rows[0] if rows else {"status": "created"}
    except Exception as exc:
        logger.error("create_incident failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.put("/incidents/{incident_id}", summary="Update incident report")
@limiter.limit("20/minute")
async def update_incident(
    incident_id: int,
    body: _IncidentUpdateIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read("SELECT id, status FROM incident_reports WHERE id = %s", (incident_id,))
        if not rows:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

        sets, params = [], []
        if body.title is not None:
            sets.append("title = %s"); params.append(body.title)
        if body.description is not None:
            sets.append("description = %s"); params.append(body.description)
        if body.status is not None:
            sets.append("status = %s"); params.append(body.status)
            if body.status in ("resolved", "closed"):
                sets.append("resolved_at = NOW()")
                sets.append("resolved_by = %s"); params.append(_admin["id"])

        if not sets:
            return JSONResponse(status_code=422, content={"error": "No fields to update"})

        params.append(incident_id)
        execute_write(f"UPDATE incident_reports SET {', '.join(sets)} WHERE id = %s", tuple(params))
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "incident_update", "incident_reports", f"id:{incident_id} status:{body.status}", _admin.get("company_id"))
        row = execute_read("SELECT id, title, severity, status, created_at::TEXT, resolved_at::TEXT FROM incident_reports WHERE id = %s", (incident_id,))
        return row[0] if row else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_incident failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


# â”€â”€â”€ 2FA Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/2fa/setup", summary="Configure 2FA for an admin")
@limiter.limit("10/minute")
async def setup_2fa(
    body: _TwoFASetupIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read("SELECT id, name, role FROM admins WHERE id = %s", (body.admin_id,))
        if not rows:
            raise HTTPException(status_code=404, detail=f"Admin {body.admin_id} not found")
        if rows[0]["role"] != "super_admin":
            raise HTTPException(status_code=400, detail="2FA is only supported for super_admin accounts")

        execute_write(
            "UPDATE admins SET email = %s, requires_2fa = %s WHERE id = %s",
            (body.email, body.enabled, body.admin_id),
        )
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "2fa_setup", "admins", f"admin:{body.admin_id} enabled:{body.enabled}", _admin.get("company_id"))
        return {"status": "updated", "admin_id": body.admin_id, "requires_2fa": body.enabled, "email": body.email}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("setup_2fa failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


def _send_otp_email(to_email: str, otp: str, admin_name: str) -> None:
    import config as _cfg
    msg = MIMEText(
        f"Hello {admin_name},\n\n"
        f"Your SentinelEdge super-admin verification code is:\n\n"
        f"    {otp}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you did not request this, please contact your security team immediately.",
        "plain",
    )
    msg["Subject"] = "SentinelEdge 2FA Verification Code"
    msg["From"]    = getattr(_cfg, "SMTP_FROM", getattr(_cfg, "SMTP_USER", "no-reply@sentineledge.com"))
    msg["To"]      = to_email

    smtp_host = getattr(_cfg, "SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(getattr(_cfg, "SMTP_PORT", 587))
    smtp_user = getattr(_cfg, "SMTP_USER", "")
    smtp_pass = getattr(_cfg, "SMTP_PASSWORD", "")

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(msg["From"], [to_email], msg.as_string())


@router.post("/2fa/send-otp", summary="Send OTP to admin email")
@limiter.limit("5/minute")
async def send_otp(
    request: Request,
    _admin: dict = Depends(_require_sa_skip2fa),
):
    try:
        if not _admin.get("email"):
            raise HTTPException(status_code=400, detail="2FA email not configured for this account. Run setup first.")
        if not _admin.get("requires_2fa"):
            raise HTTPException(status_code=400, detail="2FA is not enabled for this account.")

        # Invalidate any existing unused OTP for this admin
        execute_write(
            "UPDATE super_admin_otp SET used = 1 WHERE admin_id = %s AND used = 0",
            (_admin["id"],),
        )

        otp = "".join(random.choices(string.digits, k=6))
        otp_hash   = hashlib.sha256(otp.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        execute_write(
            "INSERT INTO super_admin_otp (admin_id, otp_hash, expires_at) VALUES (%s, %s, %s)",
            (_admin["id"], otp_hash, expires_at),
        )

        _send_otp_email(_admin["email"], otp, _admin["name"])
        logger.info("2FA OTP sent to admin id=%d email=%s", _admin["id"], _admin["email"])
        return {"status": "sent", "email": _admin["email"], "expires_in_minutes": 10}
    except HTTPException:
        raise
    except smtplib.SMTPException as exc:
        logger.error("2FA email send failed: %s", exc)
        return JSONResponse(status_code=502, content={"error": "Failed to send email", "detail": str(exc)})
    except Exception as exc:
        logger.error("send_otp failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/2fa/verify-otp", summary="Verify OTP and mark session as 2FA-verified")
@limiter.limit("10/minute")
async def verify_otp(
    body: _OTPVerifyIn,
    request: Request,
    _admin: dict = Depends(_require_sa_skip2fa),
    authorization: Optional[str] = Header(default=None),
):
    try:
        if not _admin.get("requires_2fa"):
            raise HTTPException(status_code=400, detail="2FA is not enabled for this account.")

        otp_hash = hashlib.sha256(body.otp.strip().encode()).hexdigest()
        rows = execute_read(
            """
            SELECT id FROM super_admin_otp
            WHERE admin_id = %s AND otp_hash = %s AND used = 0 AND expires_at > NOW()
            ORDER BY id DESC LIMIT 1
            """,
            (_admin["id"], otp_hash),
        )
        if not rows:
            raise HTTPException(status_code=401, detail="Invalid or expired OTP")

        # Mark OTP as used
        execute_write("UPDATE super_admin_otp SET used = 1 WHERE id = %s", (rows[0]["id"],))

        # Mark the current session as 2FA-verified
        token = authorization[7:].strip()
        execute_write(
            "UPDATE admin_sessions SET two_fa_verified = 1 WHERE token = %s",
            (token,),
        )

        logger.info("2FA verified for admin id=%d", _admin["id"])
        from utils.activity_logger import log_activity
        log_activity(_admin["id"], "2fa_verify", "admin_sessions", "success", _admin.get("company_id"))
        return {"status": "verified", "two_fa_verified": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("verify_otp failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get("/2fa/status", summary="Get 2FA status for all super admins")
@limiter.limit("30/minute")
async def twofa_status(
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT id, name, email, COALESCE(requires_2fa, 0) AS requires_2fa
            FROM admins WHERE role = 'super_admin'
            ORDER BY id
            """
        )
        return rows
    except Exception as exc:
        logger.error("twofa_status failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


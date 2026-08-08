"""
routers/super_admin.py — Super Admin endpoints for SentinelEdge multi-tenancy.

All routes require role = 'super_admin' on the admins table (enforced by the
require_super_admin dependency below — a self-contained guard that does NOT
touch any existing auth middleware).

Prefix: /api/super-admin
Tags:   Super Admin

Routes
------
POST   /api/super-admin/companies                           Create a company
GET    /api/super-admin/companies                           List all companies (with counts)
PATCH  /api/super-admin/companies/{company_id}/toggle       Toggle is_active
POST   /api/super-admin/companies/{company_id}/assign-admin Assign an admin to a company
GET    /api/super-admin/companies/{company_id}/subscribers  List subscribers for a company
GET    /api/super-admin/alerts                              All alerts across all companies
"""

from typing import Optional

import psycopg2.errors
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from models import AssignAdminIn, CompanyIn, CompanyOut
from utils.logger import get_logger
from utils.time import now_iso

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin", tags=["Super Admin"])


# ─── Auth dependency (self-contained, does NOT modify existing middleware) ─────

def require_super_admin(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """
    FastAPI dependency — allows only admins whose role = 'super_admin'.

    Phase 7 additions (additive, backward-compatible):
    - IP whitelist enforcement: if ip_whitelist has entries, rejects IPs not on it
    - 2FA session check: if admin has requires_2fa=1, session must have two_fa_verified=1
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token> header",
        )

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty token",
        )

    # Validate session token against existing admin_sessions table
    from database.queries.sessions import get_session
    session = get_session(token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    # Look up the admin and verify role = 'super_admin', include 2FA fields
    rows = execute_read(
        """
        SELECT a.id, a.name, a.role, a.company_id,
               a.email, COALESCE(a.requires_2fa, 0) AS requires_2fa,
               COALESCE(s.two_fa_verified, 0) AS two_fa_verified
        FROM admins a
        JOIN admin_sessions s ON s.token = %s
        WHERE a.role = 'super_admin'
        LIMIT 1
        """,
        (token,),
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin role required",
        )

    admin = rows[0]

    # Phase 7: IP whitelist check — only enforced when whitelist is non-empty
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

    # Phase 7: 2FA check — only enforced when admin has requires_2fa=1
    if admin["requires_2fa"] and not admin["two_fa_verified"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "2fa_required", "message": "Two-factor authentication required"},
        )

    return admin


# ─── Helper queries (raw psycopg2, matching project style) ────────────────────

def _get_company_or_404(company_id: int) -> dict:
    """Return a company dict or raise HTTP 404."""
    rows = execute_read(
        "SELECT id, name, slug, is_active, created_at::TEXT FROM companies WHERE id = %s",
        (company_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")
    return rows[0]


def _company_with_counts(row: dict) -> dict:
    """Augment a raw company row with admin_count and subscriber_count."""
    admin_count = execute_read(
        "SELECT COUNT(*) AS cnt FROM admins WHERE company_id = %s",
        (row["id"],),
    )
    subscriber_count = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s",
        (row["id"],),
    )
    return {
        **row,
        "is_active": bool(row["is_active"]),
        "admin_count": admin_count[0]["cnt"] if admin_count else 0,
        "subscriber_count": subscriber_count[0]["cnt"] if subscriber_count else 0,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post(
    "/companies",
    status_code=201,
    summary="Create a company",
    description="Create a new tenant company. Requires super_admin role.",
)
@limiter.limit("30/minute")
async def create_company(
    body: CompanyIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        result = execute_write(
            """
            INSERT INTO companies (name, slug, is_active, created_at)
            VALUES (%s, %s, 1, NOW())
            RETURNING id
            """,
            (body.name, body.slug),
        )
        company_id = result.lastrowid
        row = execute_read(
            "SELECT id, name, slug, is_active, created_at::TEXT FROM companies WHERE id = %s",
            (company_id,),
        )
        return _company_with_counts(row[0])
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail=f"A company with slug '{body.slug}' already exists",
        )
    except Exception as exc:
        logger.error("create_company failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/companies",
    summary="List all companies",
    description="Returns all companies with admin_count and subscriber_count. Requires super_admin role.",
)
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


@router.patch(
    "/companies/{company_id}/toggle",
    summary="Toggle company active status",
    description="Enable or disable a company (flips is_active). Requires super_admin role.",
)
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


@router.post(
    "/companies/{company_id}/assign-admin",
    summary="Assign an admin to a company",
    description=(
        "Sets admins.company_id for the given admin_id. "
        "Requires super_admin role."
    ),
)
@limiter.limit("30/minute")
async def assign_admin(
    company_id: int,
    body: AssignAdminIn,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        # Verify admin exists
        admin_rows = execute_read(
            "SELECT id, name, role FROM admins WHERE id = %s", (body.admin_id,)
        )
        if not admin_rows:
            raise HTTPException(status_code=404, detail=f"Admin {body.admin_id} not found")
        execute_write(
            "UPDATE admins SET company_id = %s WHERE id = %s",
            (company_id, body.admin_id),
        )
        return {
            "message": f"Admin '{admin_rows[0]['name']}' assigned to company {company_id}",
            "admin_id": body.admin_id,
            "company_id": company_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("assign_admin failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/companies/{company_id}/subscribers",
    summary="List subscribers for a company",
    description="Returns all subscribers belonging to the given company. Requires super_admin role.",
)
@limiter.limit("60/minute")
async def list_company_subscribers(
    company_id: int,
    request: Request,
    _admin: dict = Depends(require_super_admin),
):
    try:
        _get_company_or_404(company_id)
        rows = execute_read(
            """
            SELECT id, name, phone, email, escalation_order, active,
                   is_active, created_at, company_id
            FROM subscribers
            WHERE company_id = %s
            ORDER BY escalation_order ASC
            """,
            (company_id,),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_company_subscribers failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/alerts",
    summary="Global alert log (all companies)",
    description=(
        "Returns alerts across ALL companies, newest first. "
        "Includes company name via LEFT JOIN. Requires super_admin role."
    ),
)
@limiter.limit("60/minute")
async def global_alerts(
    request: Request,
    limit: int = 100,
    _admin: dict = Depends(require_super_admin),
):
    try:
        rows = execute_read(
            """
            SELECT
                a.id,
                a.parameter,
                a.value,
                a.threshold,
                a.direction,
                a.severity,
                a.timestamp,
                a.acknowledged,
                a.acknowledged_by,
                a.company_id,
                COALESCE(c.name, 'Unassigned') AS company_name,
                COALESCE(c.slug, '')           AS company_slug
            FROM alerts a
            LEFT JOIN companies c ON c.id = a.company_id
            ORDER BY a.id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return rows
    except Exception as exc:
        logger.error("global_alerts failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.get(
    "/company-parameters",
    summary="All parameters per company",
    description=(
        "Returns each company with its full list of monitored parameters — "
        "always includes 'Temperature' (built-in) plus any approved custom parameters. "
        "Requires super_admin role."
    ),
)
async def company_parameters(
    _admin: dict = Depends(require_super_admin),
):
    """
    Returns a list of company objects, each with a 'parameters' array.
    Built-in temperature parameter is always present.
    Custom parameters come from company_parameters table.
    """
    try:
        companies = execute_read(
            "SELECT id, name, slug, is_active FROM companies ORDER BY id"
        )
        if not companies:
            return []

        # Fetch all active custom parameters, grouped by company_id
        custom_rows = execute_read(
            """
            SELECT company_id, name, unit, min_value, max_value, created_at
              FROM company_parameters
             WHERE is_active = TRUE
             ORDER BY company_id, name
            """
        )
        # Build {company_id: [param, ...]} map
        from collections import defaultdict
        custom_by_company: dict = defaultdict(list)
        for r in (custom_rows or []):
            cid = r["company_id"]
            custom_by_company[cid].append({
                "name":      r["name"],
                "unit":      r["unit"] or "",
                "min_value": float(r["min_value"]) if r.get("min_value") is not None else None,
                "max_value": float(r["max_value"]) if r.get("max_value") is not None else None,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "builtin":   False,
            })

        result = []
        for co in companies:
            cid = co["id"]
            params = [
                {
                    "name":      "Temperature",
                    "unit":      "°C",
                    "min_value": None,
                    "max_value": None,
                    "created_at": None,
                    "builtin":   True,
                }
            ] + custom_by_company.get(cid, [])
            result.append({
                "company_id": cid,
                "company_name": co["name"],
                "is_active":  co["is_active"],
                "parameters": params,
            })
        return result

    except Exception as exc:
        logger.error("company_parameters failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

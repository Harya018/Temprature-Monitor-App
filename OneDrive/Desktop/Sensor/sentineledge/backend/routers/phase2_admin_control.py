"""
routers/phase2_admin_control.py — Phase 2: Absolute Control Over Admins.

All routes protected by require_super_admin (imported from super_admin.py).

Prefix: /api/super-admin/admin-control
Routes:
  POST   /{admin_id}/lock                     Lock admin (is_active=0, invalidate sessions)
  POST   /{admin_id}/unlock                   Unlock admin (is_active=1)
  POST   /{admin_id}/require-approval         Toggle approval requirement
  POST   /{admin_id}/impersonate              Create impersonation session
  DELETE /{admin_id}/impersonate              End impersonation
  GET    /approvals                           List approvals (filter by status)
  GET    /approvals/pending                   Pending approvals only
  POST   /approvals/{approval_id}/approve     Approve a pending request
  POST   /approvals/{approval_id}/reject      Reject a pending request
"""

import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from routers.super_admin import require_super_admin
from utils.activity_logger import log_activity
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/admin-control", tags=["Super Admin Control"])

_PROTECTED_ROLES = ("super_admin",)


# ─── Pydantic bodies ──────────────────────────────────────────────────────────

class _LockIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _RequireApprovalIn(BaseModel):
    enabled: bool


class _NoteIn(BaseModel):
    note: str = Field(default="", max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_admin_or_404(admin_id: int) -> dict:
    rows = execute_read("SELECT id, name, role, is_active FROM admins WHERE id = %s", (admin_id,))
    return rows[0] if rows else None


# ─── Lock / Unlock ────────────────────────────────────────────────────────────

@router.post("/{admin_id}/lock", summary="Lock an admin account")
async def lock_admin(
    admin_id: int,
    body: _LockIn,
    sa: dict = Depends(require_super_admin),
):
    admin = _get_admin_or_404(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})
    if admin["role"] in _PROTECTED_ROLES:
        return JSONResponse(status_code=403, content={"error": "Cannot lock the super admin account"})

    execute_write("UPDATE admins SET is_active = 0 WHERE id = %s", (admin_id,))

    # Invalidate any DB sessions that carry this admin_id (Migration 25 sessions only)
    result = execute_write(
        "DELETE FROM admin_sessions WHERE admin_id = %s", (admin_id,)
    )
    invalidated = result.rowcount

    log_activity(
        sa["id"], "admin_locked", "admin",
        f"admin_id:{admin_id} name:{admin['name']} reason:{body.reason} sessions_cleared:{invalidated}",
        None,
    )
    logger.info(
        "Admin %d (%s) locked by super_admin %d — reason: %r — %d session(s) invalidated",
        admin_id, admin["name"], sa["id"], body.reason, invalidated,
    )
    return {"admin_id": admin_id, "locked": True, "sessions_invalidated": invalidated}


@router.post("/{admin_id}/unlock", summary="Unlock an admin account")
async def unlock_admin(
    admin_id: int,
    sa: dict = Depends(require_super_admin),
):
    admin = _get_admin_or_404(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})

    execute_write("UPDATE admins SET is_active = 1 WHERE id = %s", (admin_id,))

    log_activity(
        sa["id"], "admin_unlocked", "admin",
        f"admin_id:{admin_id} name:{admin['name']}",
        None,
    )
    logger.info("Admin %d (%s) unlocked by super_admin %d", admin_id, admin["name"], sa["id"])
    return {"admin_id": admin_id, "locked": False}


# ─── Require-approval toggle ──────────────────────────────────────────────────

@router.post("/{admin_id}/require-approval", summary="Toggle approval requirement for an admin")
async def set_require_approval(
    admin_id: int,
    body: _RequireApprovalIn,
    sa: dict = Depends(require_super_admin),
):
    admin = _get_admin_or_404(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})
    if admin["role"] in _PROTECTED_ROLES:
        return JSONResponse(status_code=403, content={"error": "Cannot modify super admin"})

    flag = 1 if body.enabled else 0
    execute_write("UPDATE admins SET requires_approval = %s WHERE id = %s", (flag, admin_id))

    log_activity(
        sa["id"], "approval_requirement_changed", "admin",
        f"admin_id:{admin_id} name:{admin['name']} requires_approval:{body.enabled}",
        None,
    )
    return {"admin_id": admin_id, "requires_approval": body.enabled}


# ─── Impersonation ────────────────────────────────────────────────────────────

@router.post("/{admin_id}/impersonate", summary="Start impersonation session for an admin")
async def start_impersonation(
    admin_id: int,
    sa: dict = Depends(require_super_admin),
):
    admin = _get_admin_or_404(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})
    if admin["role"] in _PROTECTED_ROLES:
        return JSONResponse(status_code=403, content={"error": "Cannot impersonate the super admin"})

    token      = secrets.token_hex(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

    # Create a session linked to the target admin so their routes work
    execute_write(
        "INSERT INTO admin_sessions (token, expires_at, admin_id) VALUES (%s, %s, %s)",
        (token, expires_at, admin_id),
    )

    # Record that this admin is currently being impersonated
    execute_write(
        """
        UPDATE admins
           SET impersonated_by = %s,
               impersonation_expires_at = %s
         WHERE id = %s
        """,
        (sa["id"], expires_at, admin_id),
    )

    log_activity(
        sa["id"], "impersonate_start", "admin",
        f"superadmin acting as admin_id:{admin_id} name:{admin['name']}",
        None,
    )
    logger.info(
        "Super admin %d started impersonation of admin %d (%s) — expires %s",
        sa["id"], admin_id, admin["name"], expires_at.isoformat(),
    )
    return {
        "impersonation_token": token,
        "admin_id":            admin_id,
        "admin_name":          admin["name"],
        "expires_at":          expires_at.isoformat(),
        "note": (
            "Use this token as 'Authorization: Bearer <token>' to act as this admin. "
            "Valid for 1 hour. All actions are logged as 'superadmin acting as <name>'."
        ),
    }


@router.delete("/{admin_id}/impersonate", summary="End impersonation for an admin")
async def end_impersonation(
    admin_id: int,
    sa: dict = Depends(require_super_admin),
):
    admin = _get_admin_or_404(admin_id)
    if not admin:
        return JSONResponse(status_code=404, content={"error": "Admin not found"})

    # Clear impersonation flag
    execute_write(
        "UPDATE admins SET impersonated_by = NULL, impersonation_expires_at = NULL WHERE id = %s",
        (admin_id,),
    )

    log_activity(
        sa["id"], "impersonate_end", "admin",
        f"superadmin ended impersonation of admin_id:{admin_id} name:{admin['name']}",
        None,
    )
    return {"admin_id": admin_id, "impersonation_ended": True}


# ─── Approval queue ───────────────────────────────────────────────────────────

@router.get("/approvals/pending", summary="List pending approvals")
async def list_pending_approvals(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """
        SELECT
            pa.id,
            pa.admin_id,
            a.name  AS admin_name,
            co.name AS company_name,
            pa.action_type,
            pa.payload,
            pa.status,
            pa.created_at
          FROM pending_approvals pa
          JOIN admins a ON a.id = pa.admin_id
          LEFT JOIN companies co ON co.id = a.company_id
         WHERE pa.status = 'pending'
         ORDER BY pa.created_at DESC
        """
    )
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return rows


@router.get("/approvals", summary="List approvals with optional status filter")
async def list_approvals(
    status: Optional[str] = None,
    _: dict = Depends(require_super_admin),
):
    if status and status not in ("pending", "approved", "rejected"):
        return JSONResponse(status_code=422, content={"error": "status must be pending, approved, or rejected"})

    where = "WHERE pa.status = %s" if status else ""
    params = (status,) if status else ()

    rows = execute_read(
        f"""
        SELECT
            pa.id,
            pa.admin_id,
            a.name   AS admin_name,
            co.name  AS company_name,
            pa.action_type,
            pa.payload,
            pa.status,
            pa.review_note,
            pa.reviewed_by,
            pa.created_at,
            pa.reviewed_at
          FROM pending_approvals pa
          JOIN admins a ON a.id = pa.admin_id
          LEFT JOIN companies co ON co.id = a.company_id
         {where}
         ORDER BY pa.created_at DESC
         LIMIT 200
        """,
        params,
    )
    for r in rows:
        for ts_col in ("created_at", "reviewed_at"):
            if r.get(ts_col):
                r[ts_col] = r[ts_col].isoformat()
    return rows


@router.post("/approvals/{approval_id}/approve", summary="Approve a pending request")
async def approve_approval(
    approval_id: int,
    body: _NoteIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, admin_id, action_type, payload, status FROM pending_approvals WHERE id = %s",
        (approval_id,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Approval not found"})
    if rows[0]["status"] != "pending":
        return JSONResponse(status_code=409, content={"error": f"Approval is already {rows[0]['status']}"})

    execute_write(
        """
        UPDATE pending_approvals
           SET status      = 'approved',
               reviewed_by = %s,
               review_note = %s,
               reviewed_at = NOW()
         WHERE id = %s
        """,
        (sa["id"], body.note, approval_id),
    )

    log_activity(
        sa["id"], "approval_approved", "pending_approvals",
        f"approval_id:{approval_id} action:{rows[0]['action_type']} note:{body.note}",
        None,
    )
    logger.info("Approval %d approved by super_admin %d", approval_id, sa["id"])

    # ── Execute the approved action ───────────────────────────────────────────
    action_type = rows[0]["action_type"]
    payload     = rows[0].get("payload") or {}

    if action_type == "add_parameter":
        try:
            execute_write(
                """
                INSERT INTO company_parameters
                    (company_id, name, unit, min_value, max_value)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (company_id, name) DO UPDATE SET
                    unit       = EXCLUDED.unit,
                    min_value  = EXCLUDED.min_value,
                    max_value  = EXCLUDED.max_value,
                    updated_at = NOW()
                """,
                (
                    payload.get("company_id"),
                    payload.get("name"),
                    payload.get("unit"),
                    payload.get("min_value"),
                    payload.get("max_value"),
                ),
            )
            logger.info(
                "Approval %d executed: add_parameter '%s' for company %s",
                approval_id, payload.get("name"), payload.get("company_id"),
            )
            try:
                from modules.inapp.manager import broadcast as _broadcast
                import asyncio
                asyncio.create_task(_broadcast({
                    "type":       "parameter_added",
                    "company_id": payload.get("company_id"),
                    "parameter": {
                        "name":      payload.get("name"),
                        "unit":      payload.get("unit"),
                        "min_value": payload.get("min_value"),
                        "max_value": payload.get("max_value"),
                    },
                }))
            except Exception as _bcast_exc:
                logger.warning("parameter_added broadcast failed: %s", _bcast_exc)
        except Exception as _exec_exc:
            logger.error(
                "Approval %d: add_parameter execution failed: %s", approval_id, _exec_exc
            )
    else:
        logger.warning(
            "Approval %d approved but action_type '%s' has no executor — skipped",
            approval_id, action_type,
        )

    return {
        "approval_id": approval_id,
        "status":      "approved",
        "action_type": action_type,
        "reviewed_by": sa["id"],
        "note":        body.note,
    }


@router.post("/approvals/{approval_id}/reject", summary="Reject a pending request")
async def reject_approval(
    approval_id: int,
    body: _NoteIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, admin_id, action_type, status FROM pending_approvals WHERE id = %s",
        (approval_id,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Approval not found"})
    if rows[0]["status"] != "pending":
        return JSONResponse(status_code=409, content={"error": f"Approval is already {rows[0]['status']}"})

    execute_write(
        """
        UPDATE pending_approvals
           SET status      = 'rejected',
               reviewed_by = %s,
               review_note = %s,
               reviewed_at = NOW()
         WHERE id = %s
        """,
        (sa["id"], body.note, approval_id),
    )

    log_activity(
        sa["id"], "approval_rejected", "pending_approvals",
        f"approval_id:{approval_id} action:{rows[0]['action_type']} note:{body.note}",
        None,
    )
    logger.info("Approval %d rejected by super_admin %d", approval_id, sa["id"])
    return {
        "approval_id": approval_id,
        "status":      "rejected",
        "reviewed_by": sa["id"],
        "note":        body.note,
    }

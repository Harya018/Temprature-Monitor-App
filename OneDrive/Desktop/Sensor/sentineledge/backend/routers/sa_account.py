"""
routers/sa_account.py — the Super Admin's own account (main server only).

  POST /api/super-admin/change-password   current password + a new strong one; all OTHER sign-ins of this
                                          account are signed out.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from database.connection import execute_read, execute_write
from middleware.rate_limit import limiter
from routers.super_admin_v2 import require_super_admin, _enforce_password_strength, _log_audit
from utils.logger import get_logger
from utils.security import hash_pin, verify_pin

logger = get_logger(__name__)
router = APIRouter(prefix="/api/super-admin", tags=["Super Admin — account"])


class _ChangePwdIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password:     str = Field(min_length=10, max_length=200)


@router.post("/change-password", summary="Change the Super Admin password")
@limiter.limit("5/minute")
async def change_super_admin_password(
    body: _ChangePwdIn,
    request: Request,
    admin: dict = Depends(require_super_admin),
    authorization: Optional[str] = Header(default=None),
):
    rows = execute_read("SELECT password_hash FROM admins WHERE id = %s", (admin["id"],))
    if not rows or not verify_pin(body.current_password.strip(), rows[0]["password_hash"]):
        return JSONResponse(status_code=401, content={"error": "The current password is not correct"})
    new = body.new_password.strip()
    try:
        _enforce_password_strength(new)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    if verify_pin(new, rows[0]["password_hash"]):
        return JSONResponse(status_code=422, content={"error": "Choose a password different from the current one"})
    execute_write("UPDATE admins SET password_hash = %s WHERE id = %s", (hash_pin(new), admin["id"]))
    keep = (authorization or "")[7:].strip()
    execute_write("DELETE FROM admin_sessions WHERE admin_id = %s AND token <> %s", (admin["id"], keep))
    ip = request.client.host if request.client else "unknown"
    _log_audit(admin["id"], None, "super_admin_password_changed", "auth", "high", "password changed by the account itself", ip)
    logger.warning("Super Admin password changed from %s (other sessions signed out)", ip)
    return {"status": "changed"}

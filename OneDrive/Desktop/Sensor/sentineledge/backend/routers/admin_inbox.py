"""
routers/admin_inbox.py — what a company admin receives from the super admin.

Super admin writes these from the Super Admin panel; this is the read side
for the company admin's dashboard:
  - direct messages to the admin's company   (company_messages)
  - platform-wide broadcasts that were sent   (broadcasts, status = 'sent')
  - the company's maintenance mode status     (companies.maintenance_*)

Endpoints:
  GET  /api/admin/inbox                        — everything above, for this admin's company
  POST /api/admin/inbox/messages/{id}/read     — mark a direct message read
"""

from fastapi import APIRouter, Depends, HTTPException

from database.connection import execute_read, execute_write
from middleware.auth import require_admin

router = APIRouter(prefix="/api/admin/inbox", tags=["Admin Inbox"])


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


@router.get("", summary="Messages, broadcasts and maintenance status from the super admin")
async def get_inbox(auth: dict = Depends(require_admin)):
    company_id = auth.get("company_id")

    broadcasts = execute_read(
        """
        SELECT id, title, message, COALESCE(scheduled_at, created_at) AS sent_at
          FROM broadcasts
         WHERE status = 'sent'
         ORDER BY COALESCE(scheduled_at, created_at) DESC
         LIMIT 10
        """
    )

    messages, maintenance = [], None
    if company_id is not None:
        messages = execute_read(
            """
            SELECT id, subject, body, sent_at, read_at
              FROM company_messages
             WHERE company_id = %s
             ORDER BY sent_at DESC
             LIMIT 50
            """,
            (company_id,),
        )
        co = execute_read(
            "SELECT maintenance_mode, maintenance_reason, maintenance_until "
            "FROM companies WHERE id = %s",
            (company_id,),
        )
        if co and co[0]["maintenance_mode"]:
            maintenance = {
                "reason": co[0]["maintenance_reason"],
                "until":  _iso(co[0]["maintenance_until"]),
            }

    for r in broadcasts:
        r["sent_at"] = _iso(r["sent_at"])
    for r in messages:
        r["sent_at"] = _iso(r["sent_at"])
        r["read_at"] = _iso(r["read_at"])

    return {
        "maintenance":  maintenance,
        "broadcasts":   broadcasts,
        "messages":     messages,
        "unread_count": sum(1 for m in messages if not m["read_at"]),
    }


@router.post("/messages/{message_id}/read", summary="Mark a super-admin message as read")
async def mark_message_read(message_id: int, auth: dict = Depends(require_admin)):
    company_id = auth.get("company_id")
    if company_id is None:
        raise HTTPException(status_code=404, detail="Message not found")
    # Scoped to the admin's own company so one company can't touch another's messages
    result = execute_write(
        "UPDATE company_messages SET read_at = NOW() "
        "WHERE id = %s AND company_id = %s AND read_at IS NULL",
        (message_id, company_id),
    )
    if result.rowcount == 0:
        rows = execute_read(
            "SELECT 1 FROM company_messages WHERE id = %s AND company_id = %s",
            (message_id, company_id),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Message not found")
    return {"id": message_id, "read": True}

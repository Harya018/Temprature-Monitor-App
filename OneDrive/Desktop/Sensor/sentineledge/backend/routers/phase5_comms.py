"""
routers/phase5_comms.py â€” Phase 5: Communication & Relationship Management.

All routes protected by require_super_admin.

Prefix: /api/super-admin/comms
Routes:
  POST   /messages/{company_id}           Send direct message to company
  GET    /messages/{company_id}           List messages for company
  POST   /broadcast/scheduled             Schedule a broadcast
  GET    /broadcast/scheduled             List pending scheduled broadcasts
  DELETE /broadcast/scheduled/{id}        Cancel scheduled broadcast
  GET    /notes/{company_id}              List CRM notes for company
  POST   /notes/{company_id}              Create note
  PUT    /notes/{note_id}                 Update note
  DELETE /notes/{note_id}                 Delete note
  GET    /onboarding/{company_id}         List onboarding checklist
  POST   /onboarding/{company_id}         Add checklist item
  PATCH  /onboarding/{item_id}            Toggle done
  DELETE /onboarding/{item_id}            Remove item
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from database.connection import execute_read, execute_write
from routers.super_admin_v2 import require_super_admin
from utils.activity_logger import log_activity
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/comms", tags=["Super Admin Comms"])


# â”€â”€â”€ Pydantic bodies â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _MessageIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str    = Field(min_length=1, max_length=5000)

    @field_validator("subject", "body", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _ScheduledBroadcastIn(BaseModel):
    title:        str      = Field(min_length=1, max_length=200)
    message:      str      = Field(min_length=1, max_length=5000)
    scheduled_at: str      = Field(description="ISO 8601 datetime string")
    company_id:   Optional[int] = None

    @field_validator("title", "message", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _NoteIn(BaseModel):
    content: str = Field(min_length=1, max_length=10000)

    @field_validator("content", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _OnboardingItemIn(BaseModel):
    item: str = Field(min_length=1, max_length=500)

    @field_validator("item", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _ToggleDoneIn(BaseModel):
    done: bool


# â”€â”€â”€ Helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _company_or_404(company_id: int):
    rows = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    return rows[0] if rows else None


# â”€â”€â”€ Direct Messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/messages/{company_id}", status_code=201, summary="Send direct message to a company")
async def send_message(
    company_id: int,
    body: _MessageIn,
    sa: dict = Depends(require_super_admin),
):
    co = _company_or_404(company_id)
    if not co:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    result = execute_write(
        """
        INSERT INTO company_messages (company_id, subject, body, sent_by)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (company_id, body.subject, body.body, sa["id"]),
    )

    log_activity(
        sa["id"], "message_sent", "company_messages",
        f"company_id:{company_id} company:{co['name']} subject:{body.subject[:60]}",
        company_id,
    )
    logger.info(
        "Super admin %d sent message to company %d (%s): %r",
        sa["id"], company_id, co["name"], body.subject,
    )
    return {
        "id":         result.lastrowid,
        "company_id": company_id,
        "subject":    body.subject,
        "sent_at":    datetime.now(timezone.utc).isoformat(),
    }


@router.get("/messages/{company_id}", summary="List messages for a company")
async def list_messages(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    co = _company_or_404(company_id)
    if not co:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    rows = execute_read(
        """
        SELECT m.id, m.subject, m.body, m.sent_at, m.read_at,
               a.name AS sent_by_name
          FROM company_messages m
          LEFT JOIN admins a ON a.id = m.sent_by
         WHERE m.company_id = %s
         ORDER BY m.sent_at DESC
         LIMIT 100
        """,
        (company_id,),
    )
    for r in rows:
        for ts in ("sent_at", "read_at"):
            if r.get(ts):
                r[ts] = r[ts].isoformat()
    return rows


# â”€â”€â”€ Scheduled Broadcasts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/broadcast/scheduled", status_code=201, summary="Schedule a broadcast")
async def create_scheduled_broadcast(
    body: _ScheduledBroadcastIn,
    sa: dict = Depends(require_super_admin),
):
    try:
        scheduled_dt = datetime.fromisoformat(body.scheduled_at.replace("Z", "+00:00"))
    except ValueError:
        return JSONResponse(status_code=422, content={"error": "Invalid scheduled_at â€” use ISO 8601"})

    if scheduled_dt <= datetime.now(timezone.utc):
        return JSONResponse(status_code=422, content={"error": "scheduled_at must be in the future"})

    result = execute_write(
        """
        INSERT INTO broadcasts (title, message, sent_by, status, scheduled_at)
        VALUES (%s, %s, %s, 'pending', %s) RETURNING id
        """,
        (body.title, body.message, f"superadmin:{sa['name']}", scheduled_dt),
    )

    log_activity(
        sa["id"], "broadcast_scheduled", "broadcasts",
        f"title:{body.title[:60]} scheduled_at:{body.scheduled_at}",
        None,
    )
    return {
        "id":           result.lastrowid,
        "title":        body.title,
        "status":       "pending",
        "scheduled_at": scheduled_dt.isoformat(),
    }


@router.get("/broadcast/scheduled", summary="List pending scheduled broadcasts")
async def list_scheduled_broadcasts(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        """
        SELECT id, title, message, sent_by, status, scheduled_at, created_at
          FROM broadcasts
         WHERE status = 'pending'
         ORDER BY scheduled_at ASC
        """
    )
    for r in rows:
        for ts in ("scheduled_at", "created_at"):
            if r.get(ts):
                r[ts] = r[ts].isoformat()
    return rows


@router.delete("/broadcast/scheduled/{broadcast_id}", summary="Cancel a scheduled broadcast")
async def cancel_scheduled_broadcast(
    broadcast_id: int,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, title, status FROM broadcasts WHERE id = %s", (broadcast_id,)
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Broadcast not found"})
    if rows[0]["status"] != "pending":
        return JSONResponse(
            status_code=409,
            content={"error": f"Broadcast is already {rows[0]['status']} â€” cannot cancel"},
        )

    execute_write(
        "UPDATE broadcasts SET status = 'cancelled' WHERE id = %s", (broadcast_id,)
    )
    log_activity(
        sa["id"], "broadcast_cancelled", "broadcasts",
        f"broadcast_id:{broadcast_id} title:{rows[0]['title'][:60]}",
        None,
    )
    return {"cancelled": True, "broadcast_id": broadcast_id}


# â”€â”€â”€ Company Notes (CRM) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/notes/{company_id}", summary="List CRM notes for a company")
async def list_notes(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    co = _company_or_404(company_id)
    if not co:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    rows = execute_read(
        """
        SELECT n.id, n.content, n.created_at, n.updated_at,
               a.name AS created_by_name
          FROM company_notes n
          LEFT JOIN admins a ON a.id = n.created_by
         WHERE n.company_id = %s
         ORDER BY n.created_at DESC
        """,
        (company_id,),
    )
    for r in rows:
        for ts in ("created_at", "updated_at"):
            if r.get(ts):
                r[ts] = r[ts].isoformat()
    return rows


@router.post("/notes/{company_id}", status_code=201, summary="Create a CRM note")
async def create_note(
    company_id: int,
    body: _NoteIn,
    sa: dict = Depends(require_super_admin),
):
    co = _company_or_404(company_id)
    if not co:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    result = execute_write(
        "INSERT INTO company_notes (company_id, content, created_by) VALUES (%s, %s, %s) RETURNING id",
        (company_id, body.content, sa["id"]),
    )
    log_activity(
        sa["id"], "note_created", "company_notes",
        f"company_id:{company_id} company:{co['name']}",
        company_id,
    )
    return {
        "id":         result.lastrowid,
        "company_id": company_id,
        "content":    body.content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@router.put("/notes/{note_id}", summary="Update a CRM note")
async def update_note(
    note_id: int,
    body: _NoteIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id, company_id FROM company_notes WHERE id = %s", (note_id,))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Note not found"})

    execute_write(
        "UPDATE company_notes SET content = %s, updated_at = NOW() WHERE id = %s",
        (body.content, note_id),
    )
    log_activity(
        sa["id"], "note_updated", "company_notes",
        f"note_id:{note_id} company_id:{rows[0]['company_id']}",
        rows[0]["company_id"],
    )
    return {"id": note_id, "content": body.content, "updated_at": datetime.now(timezone.utc).isoformat()}


@router.delete("/notes/{note_id}", summary="Delete a CRM note")
async def delete_note(
    note_id: int,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read("SELECT id, company_id FROM company_notes WHERE id = %s", (note_id,))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Note not found"})

    execute_write("DELETE FROM company_notes WHERE id = %s", (note_id,))
    log_activity(
        sa["id"], "note_deleted", "company_notes",
        f"note_id:{note_id} company_id:{rows[0]['company_id']}",
        rows[0]["company_id"],
    )
    return {"deleted": True, "note_id": note_id}


# â”€â”€â”€ Onboarding Checklist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/onboarding/{company_id}", summary="Get onboarding checklist for a company")
async def list_onboarding(
    company_id: int,
    _: dict = Depends(require_super_admin),
):
    co = _company_or_404(company_id)
    if not co:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    rows = execute_read(
        """
        SELECT o.id, o.item, o.done, o.created_at,
               a.name AS created_by_name
          FROM company_onboarding o
          LEFT JOIN admins a ON a.id = o.created_by
         WHERE o.company_id = %s
         ORDER BY o.created_at ASC
        """,
        (company_id,),
    )
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    total = len(rows)
    done  = sum(1 for r in rows if r["done"])
    return {
        "company_id":   company_id,
        "company_name": co["name"],
        "total":        total,
        "done":         done,
        "progress_pct": round(done / total * 100) if total else 0,
        "items":        rows,
    }


@router.post("/onboarding/{company_id}", status_code=201, summary="Add onboarding item")
async def add_onboarding_item(
    company_id: int,
    body: _OnboardingItemIn,
    sa: dict = Depends(require_super_admin),
):
    co = _company_or_404(company_id)
    if not co:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    result = execute_write(
        "INSERT INTO company_onboarding (company_id, item, created_by) VALUES (%s, %s, %s) RETURNING id",
        (company_id, body.item, sa["id"]),
    )
    log_activity(
        sa["id"], "onboarding_item_added", "company_onboarding",
        f"company_id:{company_id} item:{body.item[:60]}",
        company_id,
    )
    return {"id": result.lastrowid, "item": body.item, "done": False}


@router.patch("/onboarding/{item_id}", summary="Toggle onboarding item done")
async def toggle_onboarding(
    item_id: int,
    body: _ToggleDoneIn,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, company_id, item FROM company_onboarding WHERE id = %s", (item_id,)
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Item not found"})

    execute_write(
        "UPDATE company_onboarding SET done = %s WHERE id = %s",
        (1 if body.done else 0, item_id),
    )
    log_activity(
        sa["id"], "onboarding_toggled", "company_onboarding",
        f"item_id:{item_id} company_id:{rows[0]['company_id']} done:{body.done}",
        rows[0]["company_id"],
    )
    return {"id": item_id, "done": body.done}


@router.delete("/onboarding/{item_id}", summary="Remove onboarding item")
async def delete_onboarding_item(
    item_id: int,
    sa: dict = Depends(require_super_admin),
):
    rows = execute_read(
        "SELECT id, company_id FROM company_onboarding WHERE id = %s", (item_id,)
    )
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Item not found"})

    execute_write("DELETE FROM company_onboarding WHERE id = %s", (item_id,))
    log_activity(
        sa["id"], "onboarding_item_removed", "company_onboarding",
        f"item_id:{item_id} company_id:{rows[0]['company_id']}",
        rows[0]["company_id"],
    )
    return {"deleted": True, "item_id": item_id}


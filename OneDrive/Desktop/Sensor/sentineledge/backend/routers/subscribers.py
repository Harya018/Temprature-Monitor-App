"""
routers/subscribers.py — /api/subscribers endpoints.

Tags: Subscribers
Rate limiting (slowapi):
  GET  /api/subscribers → 30/minute per IP
  POST /api/subscribers → 10/minute per IP
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

import database
from middleware.auth import require_admin
from middleware.rate_limit import limiter
from models import PushSubscriptionIn, SetPinIn, SubscriberIn, SubscriberOut, SubscriberUpdate

router = APIRouter(prefix="/api", tags=["Subscribers"])


def _row_to_out(r: dict) -> SubscriberOut:
    """Convert a DB row dict to SubscriberOut, hiding the raw PIN."""
    # Support both old 'active' and new 'is_active' columns gracefully
    is_active = bool(r.get("is_active", r.get("active", 1)))
    return SubscriberOut(
        id=r["id"],
        name=r["name"],
        phone=r["phone"],
        email=r["email"],
        escalation_order=r["escalation_order"],
        active=is_active,
        has_pin=bool(r.get("pin")),
        created_at=r["created_at"],
        employee_id=r.get("employee_id"),
        department=r.get("department"),
        designation=r.get("designation"),
        shift_timing=r.get("shift_timing"),
        address=r.get("address"),
    )


@router.get(
    "/subscribers",
    response_model=list[SubscriberOut],
    summary="List all subscribers",
    description="Returns all subscribers ordered by escalation_order.",
)
@limiter.limit("30/minute")
async def get_subscribers(request: Request):
    rows = database.get_subscribers_ordered()
    return [_row_to_out(r) for r in rows]


@router.post(
    "/subscribers",
    response_model=SubscriberOut,
    status_code=201,
    summary="Add a subscriber",
    description="Creates a new alert subscriber. Requires admin auth. Rate limited to 30/min.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("30/minute")
async def add_subscriber(body: SubscriberIn, request: Request):
    sub_id = database.add_subscriber(
        body.name, body.phone, body.email, body.escalation_order,
        pin=body.pin,           # optional; hashed inside the query layer
    )
    if sub_id == -1:
        raise HTTPException(
            status_code=409,
            detail="Escalation order already in use or database error",
        )
    row = database.get_subscriber_by_id(sub_id)
    return _row_to_out(row)


@router.delete(
    "/subscribers/{subscriber_id}",
    summary="Remove a subscriber",
    description="Permanently removes a subscriber by ID. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("30/minute")
async def delete_subscriber(subscriber_id: int, request: Request):
    ok = database.delete_subscriber(subscriber_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {"status": "deleted", "id": subscriber_id}


@router.patch(
    "/subscribers/{subscriber_id}/disable",
    summary="Disable a subscriber",
    description="Temporarily disables a subscriber (is_active=0). They will not receive alerts. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("30/minute")
async def disable_subscriber(subscriber_id: int, request: Request):
    ok = database.disable_subscriber(subscriber_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {"status": "disabled", "id": subscriber_id}


@router.patch(
    "/subscribers/{subscriber_id}/enable",
    summary="Enable a subscriber",
    description="Re-enables a disabled subscriber (is_active=1). They will resume receiving alerts. Requires admin auth.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("30/minute")
async def enable_subscriber(subscriber_id: int, request: Request):
    ok = database.enable_subscriber(subscriber_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {"status": "enabled", "id": subscriber_id}


@router.post(
    "/subscribers/{subscriber_id}/push",
    summary="Save push subscription",
    description="Stores a Web Push subscription for in-app notifications.",
    dependencies=[Depends(require_admin)],
)
async def save_push_subscription(subscriber_id: int, body: PushSubscriptionIn):
    ok = database.update_push_subscription(subscriber_id, body.subscription_json)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {"status": "saved"}


@router.post(
    "/subscribers/{subscriber_id}/set-pin",
    summary="Set subscriber PIN",
    description=(
        "Admin endpoint to set or update a subscriber's 4-6 digit numeric PIN. "
        "PIN is stored as a SHA-256 hash — never in plain text."
    ),
    dependencies=[Depends(require_admin)],
)
async def set_subscriber_pin(subscriber_id: int, body: SetPinIn):
    if body.subscriber_id != subscriber_id:
        raise HTTPException(
            status_code=400,
            detail="subscriber_id in path and body must match",
        )
    ok = database.set_subscriber_pin(subscriber_id, body.pin)
    if not ok:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {"status": "pin_set", "subscriber_id": subscriber_id}


# ── New profile endpoints ──────────────────────────────────────────────────────

@router.get(
    "/subscribers/{subscriber_id}",
    response_model=SubscriberOut,
    summary="Get single subscriber",
    description="Returns the full subscriber record including profile fields.",
)
@limiter.limit("30/minute")
async def get_subscriber(subscriber_id: int, request: Request):
    row = database.get_subscriber_by_id(subscriber_id)
    if not row:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return _row_to_out(row)


@router.put(
    "/subscribers/{subscriber_id}",
    response_model=SubscriberOut,
    summary="Update subscriber profile",
    description="Partial update of subscriber fields. Only supplied fields are written.",
    dependencies=[Depends(require_admin)],
)
@limiter.limit("30/minute")
async def update_subscriber(subscriber_id: int, body: SubscriberUpdate, request: Request):
    # Check subscriber exists first
    existing = database.get_subscriber_by_id(subscriber_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    # Build dict of only the non-None fields that were explicitly supplied
    fields = {k: v for k, v in body.model_dump().items() if v is not None}

    updated = database.update_subscriber(subscriber_id, fields)
    if not updated:
        raise HTTPException(status_code=500, detail="Update failed")
    return _row_to_out(updated)


@router.get(
    "/subscribers/{subscriber_id}/acknowledgements",
    summary="Get acknowledgement history for a subscriber",
    description=(
        "Returns all alerts acknowledged by this subscriber, with breach metadata "
        "and computed response_time_seconds. Returns empty list if none found."
    ),
)
@limiter.limit("30/minute")
async def get_subscriber_acknowledgements(subscriber_id: int, request: Request):
    # Return empty list gracefully if subscriber not found
    sub = database.get_subscriber_by_id(subscriber_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    rows = database.get_acks_for_subscriber(subscriber_id)
    return rows

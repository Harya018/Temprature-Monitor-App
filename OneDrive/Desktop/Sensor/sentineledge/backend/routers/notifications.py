"""
routers/notifications.py — Push token registration endpoints for SentinelEdge.

Allows authenticated subscribers (mobile app) to register and deregister their
FCM / Expo push tokens. The actual push sending logic is in core/escalation.py.

Endpoints
---------
POST   /api/notifications/push-token   Register / update push token (type field: expo|fcm)
DELETE /api/notifications/push-token   Clear push token (logout / unsubscribe)
POST   /api/workers/push-token         Legacy alias — same as notifications endpoint
                                       (accepts pushToken + optional fcmToken fields)

Auth: X-Auth-Token header (require_subscriber_auth dependency)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import database
from database.connection import execute_write
from middleware.auth import require_subscriber_auth
from middleware.rate_limit import limiter
from models import PushTokenIn
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Notifications"])


@router.post(
    "/api/notifications/push-token",
    status_code=200,
    summary="Register push token",
    description=(
        "Store the caller's Expo or FCM push token against their subscriber record. "
        "Supply type='expo' for an Expo push token (ExponentPushToken[...]) "
        "or type='fcm' for a raw FCM registration token. "
        "Requires X-Auth-Token header (subscriber login)."
    ),
)
@limiter.limit("20/minute")
async def register_push_token(
    body: PushTokenIn,
    request: Request,
    session: dict = Depends(require_subscriber_auth),
):
    """Store the FCM or Expo push token for the authenticated subscriber."""
    subscriber_id = session.get("subscriber_id")
    if not subscriber_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not resolve subscriber_id from token",
        )

    try:
        if body.type == "fcm":
            execute_write(
                "UPDATE subscribers SET fcm_token = %s WHERE id = %s",
                (body.token, subscriber_id),
            )
            logger.info("FCM token registered for subscriber id=%d", subscriber_id)
        else:
            # default: expo
            execute_write(
                "UPDATE subscribers SET expo_push_token = %s WHERE id = %s",
                (body.token, subscriber_id),
            )
            logger.info("Expo push token registered for subscriber id=%d", subscriber_id)

        return {
            "message": f"{body.type.upper()} push token registered successfully",
            "subscriber_id": subscriber_id,
            "type": body.type,
        }

    except Exception as exc:
        logger.error("register_push_token failed for subscriber %d: %s", subscriber_id, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to save push token", "detail": str(exc)},
        )


@router.delete(
    "/api/notifications/push-token",
    status_code=200,
    summary="Deregister push token",
    description=(
        "Clears both fcm_token and expo_push_token for the caller's subscriber record. "
        "Call this on logout so stale tokens don't receive alerts. "
        "Requires X-Auth-Token header (subscriber login)."
    ),
)
@limiter.limit("20/minute")
async def deregister_push_token(
    request: Request,
    session: dict = Depends(require_subscriber_auth),
):
    """Clear all push tokens for the authenticated subscriber (used on logout)."""
    subscriber_id = session.get("subscriber_id")
    if not subscriber_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not resolve subscriber_id from token",
        )

    try:
        execute_write(
            "UPDATE subscribers SET fcm_token = NULL, expo_push_token = NULL WHERE id = %s",
            (subscriber_id,),
        )
        logger.info("Push tokens cleared for subscriber id=%d", subscriber_id)
        return {
            "message": "Push tokens cleared successfully",
            "subscriber_id": subscriber_id,
        }

    except Exception as exc:
        logger.error("deregister_push_token failed for subscriber %d: %s", subscriber_id, exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to clear push tokens", "detail": str(exc)},
        )


# ── Legacy alias: /api/workers/push-token ─────────────────────────────────────
# Kept for backward compatibility with older mobile clients that used the
# workers path. Accepts camelCase pushToken + optional fcmToken fields.

class _WorkersPushTokenIn(BaseModel):
    pushToken: str = Field(min_length=1, max_length=200)
    fcmToken: str | None = Field(default=None, max_length=500)


@router.post(
    "/api/workers/push-token",
    status_code=200,
    summary="Register push token (workers alias)",
    description=(
        "Legacy path — identical to POST /api/notifications/push-token. "
        "Accepts camelCase pushToken (Expo) and optional fcmToken (FCM). "
        "Requires X-Auth-Token header (subscriber login)."
    ),
)
@limiter.limit("20/minute")
async def workers_push_token(
    body: _WorkersPushTokenIn,
    request: Request,
    session: dict = Depends(require_subscriber_auth),
):
    subscriber_id = session.get("subscriber_id")
    if not subscriber_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not resolve subscriber_id from token",
        )
    ok = database.update_expo_push_token(subscriber_id, body.pushToken)
    if body.fcmToken:
        ok = database.update_fcm_token(subscriber_id, body.fcmToken) and ok
    return {"status": "saved" if ok else "failed"}

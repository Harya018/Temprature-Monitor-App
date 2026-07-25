"""
routers/notifications.py — Push token registration endpoints for SentinelEdge.

Allows authenticated subscribers (mobile app) to register and deregister their
FCM / Expo push tokens. The actual push sending logic is already implemented
in core/escalation.py — this file only handles token storage.

Endpoints
---------
POST   /api/notifications/push-token   Register / update push token
DELETE /api/notifications/push-token   Clear push token (logout / unsubscribe)

Auth: X-Auth-Token header (existing require_subscriber_auth dependency)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from database.connection import execute_write
from middleware.auth import require_subscriber_auth
from middleware.rate_limit import limiter
from models import PushTokenIn
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.post(
    "/push-token",
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
    "/push-token",
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

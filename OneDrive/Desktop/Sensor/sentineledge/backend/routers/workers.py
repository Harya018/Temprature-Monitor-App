"""
routers/workers.py — /api/workers endpoints.

Lets the React Native worker app register its Expo push token so the
server can ring the device for critical alerts (see core/escalation.py's
mobile push channel). "Workers" are subscriber rows — there is no separate
workers table — authenticated the same way as any other subscriber-facing
endpoint (X-Auth-Token, see middleware.auth.require_subscriber_auth).

Tags: Workers
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import database
from middleware.auth import require_subscriber_auth

router = APIRouter(prefix="/api", tags=["Workers"])


class PushTokenIn(BaseModel):
    pushToken: str = Field(min_length=1, max_length=200)
    # Raw FCM registration token (from @react-native-firebase/messaging's
    # getToken()), optional — lets the server deliver via direct FCM HTTP v1
    # in addition to the Expo relay, for maximum delivery reliability.
    fcmToken: str | None = Field(default=None, max_length=500)


@router.post(
    "/workers/push-token",
    summary="Register mobile push token",
    description="Saves the caller's Expo push token (and optional raw FCM token) so critical alerts can ring this device.",
)
async def set_push_token(body: PushTokenIn, payload: dict = Depends(require_subscriber_auth)):
    ok = database.update_expo_push_token(payload["subscriber_id"], body.pushToken)
    if body.fcmToken:
        ok = database.update_fcm_token(payload["subscriber_id"], body.fcmToken) and ok
    return {"status": "saved" if ok else "failed"}

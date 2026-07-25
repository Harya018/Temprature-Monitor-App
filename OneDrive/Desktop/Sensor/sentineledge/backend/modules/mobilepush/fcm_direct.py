"""
modules/mobilepush/fcm_direct.py — Direct FCM HTTP v1 push sender.

Sends data-only pushes straight to Google's FCM API using our own Firebase
service account, bypassing Expo's push relay (server -> Expo -> FCM -> device).
Built specifically to squeeze out every delivery-priority option Android
exposes for the "app fully killed" case, after confirming (via Expo's own
delivery receipts) that relay-based delivery was reaching FCM cleanly but
still proved unreliable on an aggressive OEM (Vivo/OriginOS) device — this
removes one hop and sets AndroidConfig priority explicitly rather than
trusting an intermediary to pass it through.

Mirrors modules/mobilepush/expo_push.py's shape: sync send_*() + async
wrapper via run_in_executor, never raises, returns bool. Firebase Admin SDK
is initialized lazily (once) on first use.
"""

import asyncio
import logging
import time
from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging as fcm_messaging

from config import FCM_SERVICE_ACCOUNT_PATH

logger = logging.getLogger("sentineledge.mobilepush.fcm_direct")

_app: Optional[firebase_admin.App] = None


def _get_app() -> Optional[firebase_admin.App]:
    """Lazily initialize the Firebase Admin app. Returns None if the service
    account file is missing (e.g. not configured on this deployment) rather
    than raising, so callers can fall back to the Expo relay."""
    global _app
    if _app is not None:
        return _app
    try:
        cred = credentials.Certificate(FCM_SERVICE_ACCOUNT_PATH)
        _app = firebase_admin.initialize_app(cred, name="sentineledge-fcm")
        logger.info("Firebase Admin initialized for direct FCM delivery")
        return _app
    except FileNotFoundError:
        logger.warning(
            "FCM service account not found at %s — direct FCM delivery unavailable, "
            "will fall back to Expo relay", FCM_SERVICE_ACCOUNT_PATH,
        )
        return None
    except Exception as exc:
        logger.error("Failed to initialize Firebase Admin: %s", exc)
        return None


_RETRY_ATTEMPTS = 2  # one retry — covers "slow" without masking "unreachable"


def send_fcm_direct(fcm_token: str, data: dict) -> bool:
    """
    Send a data-only, high-priority FCM message directly to a device.

    All data values are coerced to strings — FCM's data payload requires
    string values only. Returns True on success, False on any failure
    (logs the error). Never raises. Retries once on failure — a slow-but-
    present connection (e.g. a weak hotspot) can plausibly take longer than
    a single attempt's default transport timeout to complete.
    """
    if not fcm_token:
        logger.warning("send_fcm_direct: no FCM token — skipped.")
        return False

    app = _get_app()
    if app is None:
        return False

    message = fcm_messaging.Message(
        token=fcm_token,
        data={str(k): str(v) for k, v in data.items()},
        android=fcm_messaging.AndroidConfig(
            priority="high",
            ttl=None,  # deliver ASAP, don't let FCM defer it
        ),
    )

    last_exc: Optional[Exception] = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            message_id = fcm_messaging.send(message, app=app)
            logger.info("Direct FCM push sent — id: %s", message_id)
            return True
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Direct FCM attempt %d/%d failed: %s", attempt, _RETRY_ATTEMPTS, exc,
            )
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(1)

    logger.error("Direct FCM push failed after %d attempts: %s", _RETRY_ATTEMPTS, last_exc)
    return False


async def send_fcm_direct_async(fcm_token: str, data: dict) -> bool:
    """Async wrapper around send_fcm_direct() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_fcm_direct, fcm_token, data)

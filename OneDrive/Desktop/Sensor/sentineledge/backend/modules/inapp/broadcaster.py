"""
modules/inapp/broadcaster.py — Web Push notification broadcaster.

Wraps pywebpush to deliver push notifications to browsers via VAPID.
Extracted from the original notifier.py (send_push / send_push_async).
"""

import asyncio
import json
import logging
from typing import Optional

from pywebpush import webpush, WebPushException

from config import (
    VAPID_PUBLIC_KEY,
    VAPID_PRIVATE_KEY,
    VAPID_CLAIM_EMAIL,
)

logger = logging.getLogger("sentineledge.inapp.broadcaster")


def send_push(
    push_subscription_json: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """
    Send a Web Push notification using VAPID authentication.

    The notification TTL is 86 400 s (24 h) so the push server holds
    the notification if the device is temporarily offline.

    Returns True on success, False on any failure (logs the error).
    Never raises.
    """
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        logger.warning("VAPID keys not configured — push notification skipped.")
        return False

    try:
        subscription = json.loads(push_subscription_json)
        notification_data = {"title": title, "body": body}
        if data:
            notification_data["data"] = data

        webpush(
            subscription_info=subscription,
            data=json.dumps(notification_data),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_CLAIM_EMAIL}"},
            ttl=86400,
        )
        logger.info("Web Push sent — title: %s", title)
        return True
    except WebPushException as exc:
        logger.error(
            "WebPush failed (HTTP %s): %s",
            getattr(exc.response, "status_code", "?") if exc.response else "no response",
            exc,
        )
        return False
    except json.JSONDecodeError as exc:
        logger.error("Invalid push subscription JSON: %s", exc)
        return False
    except Exception as exc:
        logger.exception("Unexpected error sending push notification: %s", exc)
        return False


async def send_push_async(
    push_subscription_json: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """Async wrapper around send_push() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, send_push, push_subscription_json, title, body, data
    )

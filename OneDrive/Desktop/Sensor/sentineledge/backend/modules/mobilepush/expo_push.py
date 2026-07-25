"""
modules/mobilepush/expo_push.py — Expo push notification sender.

Sends data-only pushes via Expo's push relay to the React Native worker app.
Data-only (no top-level title/body) so Android doesn't auto-display a plain
system-tray notification — the client's background task owns presentation
(full-screen alarm UI via notifee) instead.

Mirrors modules/inapp/broadcaster.py's shape: sync send_*() + async wrapper
via run_in_executor, never raises, returns bool.
"""

import asyncio
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger("sentineledge.mobilepush.expo_push")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

# A slow-but-present connection (e.g. a weak hotspot at a demo site) can
# legitimately take longer than a snappy home connection to complete a
# small POST — 10s was too tight and indistinguishable from "no internet at
# all". One retry with a longer timeout covers "slow" without covering for
# "genuinely unreachable" (which still fails fast-ish, twice, and returns).
_TIMEOUTS = (10, 25)


def send_expo_push(push_token: str, data: dict) -> bool:
    """
    Send a data-only Expo push notification.

    Returns True on success, False on any failure (logs the error).
    Never raises.
    """
    if not push_token:
        logger.warning("send_expo_push: no push token — skipped.")
        return False

    last_exc: Optional[Exception] = None
    for attempt, timeout in enumerate(_TIMEOUTS, start=1):
        try:
            resp = requests.post(
                EXPO_PUSH_URL,
                json={
                    "to": push_token,
                    "data": data,
                    "priority": "high",
                    "channelId": "critical-alerts",
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            ticket = (body.get("data") or {})
            if ticket.get("status") == "error":
                logger.error("Expo push ticket error: %s", ticket.get("message"))
                return False
            logger.info("Expo push sent — token: %s...", push_token[:20])
            return True
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "Expo push attempt %d/%d failed (timeout=%ds): %s",
                attempt, len(_TIMEOUTS), timeout, exc,
            )
            if attempt < len(_TIMEOUTS):
                time.sleep(1)
        except Exception as exc:
            logger.exception("Unexpected error sending Expo push: %s", exc)
            return False

    logger.error("Expo push failed after %d attempts: %s", len(_TIMEOUTS), last_exc)
    return False


async def send_expo_push_async(push_token: str, data: dict) -> bool:
    """Async wrapper around send_expo_push() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_expo_push, push_token, data)

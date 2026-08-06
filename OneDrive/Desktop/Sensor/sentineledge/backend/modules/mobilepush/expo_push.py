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
_TIMEOUTS     = (10, 25, 25)  # slot 3 is consumed only by SSL/Connection retries
_SSL_BACKOFFS = (3, 6)        # exponential waits before attempts 2 and 3 (SSL only)


def _build_notification_body(data: dict) -> str:
    """Build a human-readable push notification body from the alert data dict."""
    # Use the pre-built message string if the backend already composed one
    message = data.get("message", "")
    if message:
        return message
    # Fallback: compose from numeric fields
    value     = data.get("value")
    threshold = data.get("threshold")
    if value is not None and threshold is not None:
        return f"Value: {value} | Threshold: {threshold}"
    return "Sensor threshold breached — check dashboard immediately."


def send_expo_push(push_token: str, data: dict) -> bool:
    """
    Send an Expo push notification with a visible notification block.

    Returns True on success, False on any failure (logs the error).
    Never raises.
    """
    if not push_token:
        logger.warning("send_expo_push: no push token — skipped.")
        return False

    title = "🚨 SentinelEdge Alert"
    body  = _build_notification_body(data)
    # Mirror title/body into data so OEMs that strip the notification block
    # on killed-app delivery still surface them via the data payload
    enriched_data = {**data, "title": title, "body": body}

    last_exc: Optional[Exception] = None
    for attempt, timeout in enumerate(_TIMEOUTS, start=1):
        try:
            resp = requests.post(
                EXPO_PUSH_URL,
                json={
                    "to": push_token,
                    "notification": {
                        "title": title,
                        "body":  body,
                        "sound": "alarm",
                    },
                    "data": enriched_data,
                    "priority": "high",
                    "channelId": "critical-alerts",
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            resp_json = resp.json()
            ticket = (resp_json.get("data") or {})
            if ticket.get("status") == "error":
                logger.error("Expo push ticket error: %s", ticket.get("message"))
                return False
            logger.info(
                "Expo push sent on attempt %d/%d — token: %s...",
                attempt, len(_TIMEOUTS), push_token[:20],
            )
            return True

        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt <= len(_SSL_BACKOFFS):
                backoff = _SSL_BACKOFFS[attempt - 1]
                logger.warning(
                    "Expo push attempt %d/%d — SSL/Connection error (retrying in %ds): %s",
                    attempt, len(_TIMEOUTS), backoff, exc,
                )
                time.sleep(backoff)
            else:
                logger.warning(
                    "Expo push attempt %d/%d — SSL/Connection error, retries exhausted: %s",
                    attempt, len(_TIMEOUTS), exc,
                )

        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "Expo push attempt %d/%d failed (timeout=%ds): %s",
                attempt, len(_TIMEOUTS), timeout, exc,
            )
            if attempt == 1:
                time.sleep(1)
            else:
                break  # non-SSL errors: stop after 2 attempts

        except Exception as exc:
            logger.exception("Unexpected error sending Expo push: %s", exc)
            return False

    logger.error("Expo push failed after %d attempt(s): %s", attempt, last_exc)
    return False


async def send_expo_push_async(push_token: str, data: dict) -> bool:
    """Async wrapper around send_expo_push() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_expo_push, push_token, data)

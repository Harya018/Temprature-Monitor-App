"""
modules/sms/gateway.py — Android SMS Gateway REST client.

Uses the REST API exposed by the android-sms-gateway app
(github.com/capcom6/android-sms-gateway) running on an Android phone
on the same LAN.  No cloud service is involved.

Extracted from the original sms_gateway.py — identical logic.
"""

import asyncio
import logging

import requests

from config import SMS_GATEWAY_URL, SMS_GATEWAY_USER, SMS_GATEWAY_PASS

logger = logging.getLogger("sentineledge.sms.gateway")

_ENDPOINT = "/api/v1/message"
_TIMEOUT = 10  # seconds


def send_sms(phone_number: str, message: str) -> bool:
    """
    Send an SMS via the Android SMS Gateway REST API.

    Parameters
    ----------
    phone_number : str
        Destination phone number in E.164 format (e.g. "+15551234567").
    message : str
        Plain-text message body.

    Returns
    -------
    bool
        True if the gateway accepted the message (HTTP 200 or 202).
        False on any error — the error is logged but never re-raised.
    """
    url = f"{SMS_GATEWAY_URL.rstrip('/')}{_ENDPOINT}"
    payload = {
        "message": message,
        "phoneNumbers": [phone_number],
    }
    try:
        response = requests.post(
            url,
            json=payload,
            auth=(SMS_GATEWAY_USER, SMS_GATEWAY_PASS),
            timeout=_TIMEOUT,
        )
        if response.status_code in (200, 202):
            logger.info("SMS sent to %s via gateway (status %d)", phone_number, response.status_code)
            return True
        else:
            logger.warning(
                "SMS gateway returned unexpected status %d for %s: %s",
                response.status_code,
                phone_number,
                response.text[:200],
            )
            return False
    except requests.exceptions.Timeout:
        logger.error("SMS gateway timed out after %ds (phone: %s)", _TIMEOUT, phone_number)
        return False
    except requests.exceptions.ConnectionError as exc:
        logger.error("SMS gateway connection error for %s: %s", phone_number, exc)
        return False
    except Exception as exc:
        logger.exception("Unexpected error sending SMS to %s: %s", phone_number, exc)
        return False


async def send_sms_async(phone_number: str, message: str) -> bool:
    """Async wrapper around send_sms() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_sms, phone_number, message)

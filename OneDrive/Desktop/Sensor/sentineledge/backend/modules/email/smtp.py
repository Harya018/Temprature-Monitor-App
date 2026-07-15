# -*- coding: utf-8 -*-
"""
modules/email/smtp.py — SMTP email sender (Module 2 — HTML email upgrade).

Public API
----------
send_alert_email(recipient_email, recipient_name, temperature, threshold,
                 direction, severity, escalation_level, timestamp_utc) -> bool

send_email(to_address, subject, body) -> bool          # plain-text (legacy)
send_email_async(to_address, subject, body) -> bool    # async plain-text wrapper

send_alert_email_async(...)  -> bool                   # async HTML email
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MODULE_STATUS
from modules.email.templates import build_alert_email

logger = logging.getLogger("sentineledge.email.smtp")


# ── Internal SMTP transport ───────────────────────────────────────────────────

def _connect_and_send(msg: MIMEMultipart | MIMEText, to_address: str) -> bool:
    """
    Open an SMTP connection, authenticate, send, and close.
    Returns True on success, False on any failure (never raises).
    """
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to_address], msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed: %s", exc)
        return False
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending to %s: %s", to_address, exc)
        return False
    except Exception as exc:
        logger.exception("Unexpected error sending email to %s: %s", to_address, exc)
        return False


# ── HTML alert email (Module 2) ───────────────────────────────────────────────

def send_alert_email(
    recipient_email: str,
    recipient_name: str,
    temperature: float,
    threshold: float,
    direction: str,
    severity: str,
    escalation_level: int,
    timestamp_utc: str,
) -> bool:
    """
    Build a professional HTML email and send it via SMTP.

    Returns True on success, False on failure.  Never raises.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — email skipped.")
        return False

    try:
        content = build_alert_email(
            temperature=temperature,
            threshold=threshold,
            direction=direction,
            severity=severity,
            escalation_level=escalation_level,
            timestamp_utc=timestamp_utc,
            subscriber_name=recipient_name,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = content["subject"]
        msg["From"]    = SMTP_USER
        msg["To"]      = recipient_email

        # Attach plain-text first (lower priority), HTML second (preferred)
        msg.attach(MIMEText(content["text_body"], "plain", "utf-8"))
        msg.attach(MIMEText(content["html_body"], "html",  "utf-8"))

        ok = _connect_and_send(msg, recipient_email)
        if ok:
            logger.info("Email sent to %s — subject: %s", recipient_email, content["subject"])
            MODULE_STATUS["email"] = "ok"
        return ok

    except Exception as exc:
        logger.exception("send_alert_email failed for %s: %s", recipient_email, exc)
        return False


async def send_alert_email_async(
    recipient_email: str,
    recipient_name: str,
    temperature: float,
    threshold: float,
    direction: str,
    severity: str,
    escalation_level: int,
    timestamp_utc: str,
) -> bool:
    """Async wrapper around send_alert_email() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        send_alert_email,
        recipient_email, recipient_name,
        temperature, threshold, direction,
        severity, escalation_level, timestamp_utc,
    )


# ── Legacy plain-text sender (kept for backward compat / daily reports) ───────

def send_email(to_address: str, subject: str, body: str) -> bool:
    """
    Send a plain-text email using smtplib with STARTTLS.
    Used for daily reports and any other non-alert emails.
    Returns True on success, False on any failure.  Never raises.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured — email skipped.")
        return False

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = to_address

        ok = _connect_and_send(msg, to_address)
        if ok:
            logger.info("Email sent to %s — subject: %s", to_address, subject)
        return ok
    except Exception as exc:
        logger.exception("send_email failed for %s: %s", to_address, exc)
        return False


async def send_email_async(to_address: str, subject: str, body: str) -> bool:
    """Async wrapper around send_email() using a thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, send_email, to_address, subject, body)


# ── Parallel batch sender (all subscribers simultaneously) ────────────────────

async def send_alert_email_to_all(
    subscribers: list,
    value: float,
    threshold: float,
    direction: str,
    severity: str,
    timestamp_utc: str,
) -> list:
    """
    Send the HTML alert email to ALL active subscribers simultaneously.

    Uses a bounded ThreadPoolExecutor (max 20 workers) so each subscriber
    gets their own SMTP connection opened and closed in a separate thread.
    All emails fire at the same instant — subscriber #10 does NOT wait for #1.

    Parameters
    ----------
    subscribers   : list of subscriber dicts (must have 'email', 'name',
                    and either 'is_active' or 'active' key)
    value         : float — sensor reading that triggered the breach
    threshold     : float — the threshold value that was breached
    direction     : str   — "low" | "high"
    severity      : str   — "WARNING" | "CRITICAL" | "EMERGENCY"
    timestamp_utc : str   — UTC ISO 8601 timestamp of the breach

    Returns
    -------
    list of dicts: [{"to": email, "name": name, "status": "sent"|"failed", "error": str|None}, ...]
    """
    from concurrent.futures import ThreadPoolExecutor

    # Filter to active subscribers with a valid email address
    targets = [
        s for s in subscribers
        if s.get("email") and bool(s.get("is_active", s.get("active", True)))
    ]

    if not targets:
        logger.warning("send_alert_email_to_all: no active subscribers with email")
        return []

    def _send_one(sub: dict) -> dict:
        """Send to a single subscriber — runs in its own thread."""
        result = {"to": sub["email"], "name": sub.get("name", ""), "status": "unknown", "error": None}
        try:
            ok = send_alert_email(
                recipient_email=sub["email"],
                recipient_name=sub.get("name", "Operator"),
                temperature=value,
                threshold=threshold,
                direction=direction,
                severity=severity,
                escalation_level=1,
                timestamp_utc=timestamp_utc,
            )
            result["status"] = "sent" if ok else "failed"
            if not ok:
                result["error"] = "SMTP send returned False"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            logger.error("Email batch: failed to %s: %s", sub["email"], exc)
        return result

    loop = asyncio.get_running_loop()
    max_workers = min(len(targets), 20)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="email_batch") as executor:
        coros = [
            loop.run_in_executor(executor, _send_one, sub)
            for sub in targets
        ]
        raw_results = await asyncio.gather(*coros, return_exceptions=True)

    results = []
    for sub, res in zip(targets, raw_results):
        if isinstance(res, Exception):
            results.append({"to": sub["email"], "name": sub.get("name", ""), "status": "failed", "error": str(res)})
        else:
            results.append(res)

    sent   = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")
    logger.info("Email batch complete: %d sent, %d failed (of %d)", sent, failed, len(targets))
    return results

"""
modules/sms/sender.py — SentinelEdge Module 3: SMS Alert Sender.

Routes SMS delivery to the correct transport based on SMS_METHOD in config:

    SMS_METHOD=adb      → adb_sender.py     (Android phone via Termux HTTP — demo/dev)
    SMS_METHOD=gammu    → gammu_sender.py   (USB GSM modem via Gammu — production)
    SMS_METHOD=gateway  → gateway.py        (Android SMS Gateway REST API — LAN)
    SMS_METHOD=sim7600  → sim7600_sender.py (SIM7600 EI 4G HAT via USB serial AT cmds)

Public API
----------
    send_sms(phone, message)                    → bool  (sync)
    build_sms_message(value, threshold,
                      direction, timestamp_utc) → str
    send_alert_sms(phone, value, threshold,
                   direction, timestamp_utc)    → bool  (sync)
    send_alert_sms_async(...)                   → bool  (async, non-blocking)
"""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import SMS_METHOD, SMS_GAMMU_PORT
from utils.logger import get_logger

logger = get_logger("sms.sender")

# ─── GSM Modem detection & mock mode ─────────────────────────────────────────
# When SMS_METHOD=gammu and no physical modem is attached, the module switches
# to MOCK MODE automatically — logging the SMS instead of crashing.

_modem_port: Optional[str] = None   # detected/configured COM port, or None
_mock_mode:  bool          = True   # True until a modem is confirmed present


def detect_gsm_modem() -> Optional[str]:
    """
    Scan for an attached GSM modem.

    Strategy:
      1. If SMS_GAMMU_PORT is set in config, verify it exists in the port list.
      2. Otherwise scan all COM ports for GSM-related descriptions.

    Returns the port string (e.g. 'COM3') or None if nothing found.
    Never raises.
    """
    try:
        import serial.tools.list_ports  # type: ignore
    except ImportError:
        logger.warning("pyserial not installed — cannot scan for GSM modem")
        return None

    try:
        available = {p.device: p for p in serial.tools.list_ports.comports()}
    except Exception as exc:
        logger.warning("COM port scan failed: %s", exc)
        return None

    # ── Strategy 1: use hardcoded config port if it shows up ─────────────────
    if SMS_GAMMU_PORT and SMS_GAMMU_PORT in available:
        logger.debug("Config port %s is present in system", SMS_GAMMU_PORT)
        return SMS_GAMMU_PORT

    # ── Strategy 2: keyword scan across all ports ─────────────────────────────
    GSM_KEYWORDS = (
        "modem", "gsm", "sim", "huawei", "sierra", "zte",
        "quectel", "simcom", "usb serial", "at command",
    )
    for port, info in available.items():
        desc = (info.description or "").lower()
        mfr  = (getattr(info, "manufacturer", None) or "").lower()
        if any(kw in desc or kw in mfr for kw in GSM_KEYWORDS):
            logger.debug("GSM modem auto-detected on %s (%s)", port, info.description)
            return port

    return None


def initialize_gsm_modem() -> None:
    """
    Detect the GSM modem and set mock mode accordingly.
    Called once at server startup (inside start_gsm_worker).
    """
    global _modem_port, _mock_mode

    method = (SMS_METHOD or "adb").lower().strip()
    if method not in ("gammu", "sim7600"):
        # Only gammu/sim7600 use a physical serial modem; other methods are always live
        _mock_mode  = False
        _modem_port = None
        logger.debug("GSM modem init skipped — SMS_METHOD=%s (not gammu/sim7600)", SMS_METHOD)
        return

    _modem_port = detect_gsm_modem()

    if _modem_port:
        _mock_mode = False
        logger.info(
            "GSM modem detected on %s — LIVE MODE active",
            _modem_port,
        )
    else:
        _mock_mode = True
        logger.warning(
            "GSM modem NOT detected — running in MOCK MODE. "
            "SMS will be logged but NOT sent. "
            "Plug in the GSM dongle and restart the server to enable real SMS."
        )


def _mock_send_sms(phone: str, message: str) -> bool:
    """Log a simulated SMS send when running in mock mode."""
    preview = message[:50] + ("..." if len(message) > 50 else "")
    logger.info(
        "[MOCK SMS] To: %s | Message: %s | Status: SIMULATED (no modem connected)",
        phone, preview,
    )
    return True  # treat as success so receipts aren't spammed with failures

# IST = UTC + 05:30
_IST_OFFSET = timedelta(hours=5, minutes=30)


# ─── Message building ─────────────────────────────────────────────────────────

def _utc_to_ist(timestamp_utc: str) -> str:
    """Convert a UTC ISO string to IST formatted as 'HH:MM IST DD-Mon-YYYY'."""
    try:
        dt = datetime.fromisoformat(timestamp_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ist = dt + _IST_OFFSET
        return ist.strftime("%H:%M IST %d-%b-%Y")
    except Exception:
        return timestamp_utc  # fallback: return as-is


def build_sms_message(
    value: float,
    threshold: float,
    direction: str,
    timestamp_utc: str,
    parameter: str = "temperature",
) -> str:
    """
    Build a formatted SMS alert message strictly under 160 characters.

    Parameters
    ----------
    value         : float  — measured sensor value
    threshold     : float  — the threshold that was breached
    direction     : str    — "low" or "high"
    timestamp_utc : str    — UTC ISO 8601 timestamp of the breach
    parameter     : str    — "temperature" | "ph" | …

    Returns
    -------
    str — formatted message, always under 160 chars
    """
    time_ist = _utc_to_ist(timestamp_utc)
    p = parameter.lower()

    if p == "temperature":
        val_str = f"{value:.1f}"
        thr_str = f"{threshold:.1f}"
        if direction.lower() == "low":
            message = (
                f"SentinelEdge Alert\n"
                f"Machine READY: {val_str}C\n"
                f"Below threshold {thr_str}C\n"
                f"Time: {time_ist}\n"
                f"-SentinelEdge"
            )
        else:
            message = (
                f"SentinelEdge Alert\n"
                f"HIGH TEMP: {val_str}C\n"
                f"Above threshold {thr_str}C\n"
                f"Time: {time_ist}\n"
                f"-SentinelEdge"
            )
    elif p == "ph":
        val_str = f"{value:.4f}"
        thr_str = f"{threshold:.1f}"
        message = (
            f"SentinelEdge Alert\n"
            f"HIGH pH: {val_str}\n"
            f"Above threshold {thr_str}\n"
            f"Time: {time_ist}\n"
            f"-SentinelEdge"
        )
    else:
        # Generic fallback for any future parameter
        val_str = f"{value}"
        thr_str = f"{threshold}"
        label   = parameter.upper()
        message = (
            f"SentinelEdge Alert\n"
            f"HIGH {label}: {val_str}\n"
            f"Above threshold {thr_str}\n"
            f"Time: {time_ist}\n"
            f"-SentinelEdge"
        )

    # Safety check — SMS standard is 160 chars for GSM-7 encoding
    if len(message) > 160:
        short_time = time_ist[:8]
        if p == "temperature" and direction.lower() == "low":
            message = (
                f"SentinelEdge: Machine READY {val_str}C "
                f"(below {thr_str}C) at {short_time} -SentinelEdge"
            )
        elif p == "temperature":
            message = (
                f"SentinelEdge: HIGH TEMP {val_str}C "
                f"(above {thr_str}C) at {short_time} -SentinelEdge"
            )
        elif p == "ph":
            message = (
                f"SentinelEdge: HIGH pH {val_str} "
                f"(above {thr_str}) at {short_time} -SentinelEdge"
            )
        else:
            message = (
                f"SentinelEdge: {parameter.upper()} {val_str} "
                f"(above {thr_str}) at {short_time} -SentinelEdge"
            )
        logger.warning(
            "SMS message truncated to fit 160 chars (%d chars original)",
            len(message),
        )

    logger.debug("SMS message built (%d chars): %r", len(message), message[:60])
    return message


# ─── Transport router ─────────────────────────────────────────────────────────

def send_sms(phone: str, message: str) -> bool:
    """
    Route an SMS to the correct transport based on SMS_METHOD.

    Parameters
    ----------
    phone   : str — destination phone number
    message : str — plain-text SMS body (should be under 160 chars)

    Returns
    -------
    bool — True if SMS was accepted by the transport, False otherwise.
           Never raises — all transport errors are logged and return False.
    """
    method = (SMS_METHOD or "adb").lower().strip()
    logger.info("send_sms called: phone=%s method=%s", phone, method)

    if method == "adb":
        from modules.sms.adb_sender import send_sms_adb
        return send_sms_adb(phone, message)

    elif method == "gammu":
        from modules.sms.gammu_sender import send_sms_gammu
        return send_sms_gammu(phone, message)

    elif method == "gateway":
        from modules.sms.gateway import send_sms as send_sms_gateway
        return send_sms_gateway(phone, message)

    elif method == "sim7600":
        from modules.sms.sim7600_sender import send_sms as send_sms_sim7600
        return send_sms_sim7600(phone, message)

    else:
        logger.error(
            "Unknown SMS_METHOD: '%s'. Valid values: adb, gammu, gateway, sim7600. "
            "Check your .env file.",
            SMS_METHOD,
        )
        return False


# ─── Alert helpers ────────────────────────────────────────────────────────────

def send_alert_sms(
    phone: str,
    value: float,
    threshold: float,
    direction: str,
    timestamp_utc: str,
    parameter: str = "temperature",
) -> bool:
    """
    Build and send an alert SMS synchronously.

    Parameters
    ----------
    phone         : str   — destination phone number
    value         : float — current sensor reading
    threshold     : float — breached threshold
    direction     : str   — "low" or "high"
    timestamp_utc : str   — UTC ISO timestamp of the breach
    parameter     : str   — "temperature" | "ph" | …

    Returns
    -------
    bool — True on success
    """
    message = build_sms_message(value, threshold, direction, timestamp_utc, parameter)
    return send_sms(phone, message)


async def send_alert_sms_async(
    phone: str,
    value: float,
    threshold: float,
    direction: str,
    timestamp_utc: str,
    parameter: str = "temperature",
) -> bool:
    """
    Build and send an alert SMS asynchronously (non-blocking).

    Runs `send_alert_sms` in a thread-pool executor so it never blocks
    the async event loop during USB/serial I/O.
    """
    import functools
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(
            send_alert_sms,
            phone, value, threshold, direction, timestamp_utc, parameter,
        ),
    )


# ─── GSM Queue Worker (parallel-safe serial access) ──────────────────────────
# The GSM dongle uses a SINGLE serial port — it cannot be shared across threads.
# Solution: one background worker thread owns the port exclusively and drains
# an asyncio-safe queue. Callers push jobs simultaneously; the worker sends
# them as fast as the modem hardware allows (~2-5s per SMS).

import queue as _queue
import threading as _threading

_sms_queue: _queue.Queue = _queue.Queue()
_worker_thread: _threading.Thread | None = None
_worker_running: bool = False


def _gsm_worker() -> None:
    """
    Single worker thread that owns the GSM serial port and drains the queue.
    Each job is a tuple: (phone: str, message: str, result_holder: dict).
    result_holder is mutated in-place so the caller can inspect the outcome.
    Respects _mock_mode — in mock mode no serial port is touched.
    """
    global _worker_running
    _worker_running = True
    logger.info("GSM SMS queue worker started")

    while _worker_running:
        try:
            job = _sms_queue.get(timeout=1.0)
        except _queue.Empty:
            continue

        if job is None:          # shutdown sentinel
            _sms_queue.task_done()
            break

        phone, message, result_holder = job
        try:
            method = (SMS_METHOD or "adb").lower().strip()

            # ── Mock mode: log and return success without touching serial port ──
            if method in ("gammu", "sim7600") and _mock_mode:
                ok = _mock_send_sms(phone, message)
                result_holder["status"] = "mock_sent"
                result_holder["mock"]   = True
            else:
                ok = send_sms(phone, message)
                result_holder["status"] = "sent" if ok else "failed"
                if ok:
                    logger.info("GSM queue: SMS sent to %s", phone)
                else:
                    result_holder["error"] = "send_sms returned False"
                    logger.warning("GSM queue: SMS failed to %s", phone)
        except Exception as exc:
            result_holder["status"] = "failed"
            result_holder["error"] = str(exc)
            logger.error("GSM queue: SMS error to %s: %s", phone, exc)
        finally:
            _sms_queue.task_done()

    _worker_running = False
    logger.info("GSM SMS queue worker stopped")


def start_gsm_worker() -> None:
    """
    Start the GSM SMS queue worker thread (call once at server startup).
    Runs modem detection first to set live vs. mock mode.
    Safe to call multiple times — only starts one thread.
    """
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        logger.debug("GSM SMS worker already running — skipping start")
        return
    # Detect modem and set mock mode before starting the worker thread
    initialize_gsm_modem()
    _worker_thread = _threading.Thread(
        target=_gsm_worker, daemon=True, name="gsm-sms-worker"
    )
    _worker_thread.start()
    logger.info("GSM SMS worker thread started (thread id: %s)", _worker_thread.ident)


def stop_gsm_worker() -> None:
    """
    Gracefully stop the GSM SMS queue worker (call at server shutdown).
    Sends a None sentinel to wake the worker and exit its loop.
    """
    global _worker_running
    _worker_running = False
    _sms_queue.put(None)     # sentinel — wakes the worker to stop
    logger.info("GSM SMS worker stop signal sent")


async def send_sms_to_all(
    subscribers: list,
    value: float,
    threshold: float,
    direction: str,
    timestamp_utc: str,
    parameter: str = "temperature",
) -> list:
    """
    Queue SMS alerts for ALL active subscribers simultaneously.

    For the GSM dongle (SMS_METHOD=gammu), jobs are pushed to the queue at once
    and the single worker drains them as fast as the hardware allows.
    For ADB / gateway, each SMS is dispatched via run_in_executor concurrently.

    Parameters
    ----------
    subscribers   : list of subscriber dicts (must have 'phone' and
                    'is_active'/'active' keys)
    value         : float — sensor reading
    threshold     : float — breached threshold
    direction     : str   — "low" | "high"
    timestamp_utc : str   — UTC ISO 8601 timestamp

    Returns
    -------
    list of dicts: [{"to": phone, "status": "queued"|"sent"|"failed", "error": str|None}, ...]
    """
    method = (SMS_METHOD or "adb").lower().strip()

    targets = [
        s for s in subscribers
        if s.get("phone") and bool(s.get("is_active", s.get("active", True)))
    ]

    if not targets:
        logger.warning("send_sms_to_all: no active subscribers with phone")
        return []

    message = build_sms_message(value, threshold, direction, timestamp_utc, parameter)

    # ── Serial modem path: use the queue worker ─────────────────────────────
    # Both gammu and sim7600 own a single physical serial port — cannot be
    # shared across threads.  Push all jobs onto the queue and let the single
    # worker drain them in order.
    if method in ("gammu", "sim7600"):
        results: list[dict] = []
        for sub in targets:
            holder: dict = {"to": sub["phone"], "status": "queued", "error": None}
            _sms_queue.put((sub["phone"], message, holder))
            results.append(holder)

        logger.info(
            "SMS batch: queued %d messages for serial worker (method=%s)",
            len(results), method,
        )

        # Wait for all queued jobs to finish (non-blocking via executor)
        timeout = len(results) * 15 + 30   # 15s per SMS + 30s buffer
        try:
            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, _sms_queue.join),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("SMS delivery timed out after %ds — continuing without SMS", timeout)
        except Exception as exc:
            logger.error("SMS batch join error: %s", exc)

        sent   = sum(1 for r in results if r["status"] == "sent")
        failed = sum(1 for r in results if r["status"] == "failed")
        logger.info(
            "SMS batch complete (gammu): %d sent, %d failed (of %d)",
            sent, failed, len(targets),
        )
        return results

    # ── ADB / gateway path: concurrent via executor ───────────────────────────
    # These transports do NOT share a physical port — safe to call concurrently.
    async def _send_one(sub: dict) -> dict:
        holder: dict = {"to": sub["phone"], "status": "unknown", "error": None}
        try:
            ok = await send_alert_sms_async(
                phone=sub["phone"],
                value=value,
                threshold=threshold,
                direction=direction,
                timestamp_utc=timestamp_utc,
                parameter=parameter,
            )
            holder["status"] = "sent" if ok else "failed"
            if not ok:
                holder["error"] = "send_sms returned False"
        except Exception as exc:
            holder["status"] = "failed"
            holder["error"] = str(exc)
            logger.error("SMS batch (%s): failed to %s: %s", method, sub["phone"], exc)
        return holder

    raw = await asyncio.gather(
        *[_send_one(sub) for sub in targets],
        return_exceptions=True,
    )
    results = []
    for sub, res in zip(targets, raw):
        if isinstance(res, Exception):
            results.append({"to": sub["phone"], "status": "failed", "error": str(res)})
        else:
            results.append(res)

    sent   = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")
    logger.info(
        "SMS batch complete (%s): %d sent, %d failed (of %d)",
        method, sent, failed, len(targets),
    )
    return results

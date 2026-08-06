"""
main.py — SentinelEdge FastAPI application entry point.

Production upgrades in this version:
  - Structured error handlers (SentinelEdgeError, 404, 500)
  - Full OpenAPI documentation with descriptions, tags, and version
  - Startup tasks: DB backup + data retention schedulers
  - All timestamps UTC ISO 8601
  - PostgreSQL connection pool (psycopg2 ThreadedConnectionPool)
  - slowapi rate limiting on all public endpoints
  - Persistent admin sessions (PostgreSQL admin_sessions table)
"""

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# ── Windows asyncio fix ────────────────────────────────────────────────────────
# The default ProactorEventLoop on Windows emits noisy ConnectionResetError
# (WinError 10054) when a WebSocket/SSL client disconnects abruptly.
# Switching to SelectorEventLoopPolicy silences this cosmetic noise without
# any functional change. Must be set before FastAPI/uvicorn starts the loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
# ──────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, APIRouter
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import database
import core.sensor as sensor
import core.threshold as threshold
import core.escalation as escalation
import core.extra_sensor as extra_sensor  # secondary sensor reader (pH, etc.)
from core.escalation_policy import run_escalation_check
from core.anomaly_detector import run_anomaly_detection
from modules.sms.receiver import run_sms_receiver
from core.validator import validate_reading
from core.daily_report import schedule_daily_report
from config import (
    APP_ENV, DEMO_MODE, SERVER_PORT, MODULE_STATUS,
    SMTP_USER, SMTP_PASSWORD, SMS_GATEWAY_URL, ADMIN_PASSWORD,
    APP_VERSION,
)
from models import ReadingOut
from utils.errors import SentinelEdgeError
from utils.logger import get_logger
from utils.time import now_iso

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.responses import JSONResponse as _JSONResponse

from middleware.cors import configure_cors
from middleware.logger import log_requests
from middleware.rate_limit import limiter

from modules.inapp.manager import (
    add_connection, remove_connection, broadcast, active_connections,
)

from routers.alerts import router as alerts_router
from routers.subscribers import router as subscribers_router
from routers.config import router as config_router
from routers.simulate import router as simulate_router
from routers.health import router as health_router
from routers.admin import router as admin_router
from routers.auth import router as auth_router
from routers.history import router as history_router
from routers.reports import router as reports_router
from routers.receipts import router as receipts_router
from routers.events import router as events_router
from routers.workers import router as workers_router
from routers.super_admin import router as super_admin_router
from routers.notifications import router as notifications_router
from routers.super_admin_v2 import router as super_admin_v2_router
from routers.phase1_command import router as phase1_command_router
from routers.phase2_admin_control import router as phase2_admin_control_router
from routers.phase3_config import router as phase3_config_router
from routers.phase4_analytics import router as phase4_analytics_router
from routers.phase5_comms import router as phase5_comms_router
from routers.phase6_billing import router as phase6_billing_router
from routers.phase7_security import router as phase7_security_router

from database.backup import schedule_daily_backup
from database.retention import schedule_retention_cleanup

logger = get_logger(__name__)


# ─── Background tasks ────────────────────────────────────────────────────────

async def _maintenance_expiry_task() -> None:
    """Every 60 s: auto-clear maintenance mode for companies past their end time."""
    while True:
        await asyncio.sleep(60)
        try:
            from database.connection import execute_read, execute_write
            from utils.activity_logger import log_activity
            expired = execute_read(
                """
                SELECT id, name FROM companies
                 WHERE maintenance_mode = 1
                   AND maintenance_until IS NOT NULL
                   AND maintenance_until < NOW()
                """
            )
            for co in expired:
                execute_write(
                    """
                    UPDATE companies
                       SET maintenance_mode = 0,
                           maintenance_until = NULL,
                           maintenance_reason = NULL
                     WHERE id = %s
                    """,
                    (co["id"],),
                )
                logger.info("Maintenance mode auto-expired for company %d (%s)", co["id"], co["name"])
        except Exception as exc:
            logger.warning("Maintenance expiry task error: %s", exc)


async def _scheduled_broadcast_task() -> None:
    """Every 60 s: publish any scheduled broadcasts whose time has arrived."""
    while True:
        await asyncio.sleep(60)
        try:
            from database.connection import execute_read, execute_write
            due = execute_read(
                """
                SELECT id, title FROM broadcasts
                 WHERE status = 'pending'
                   AND scheduled_at IS NOT NULL
                   AND scheduled_at <= NOW()
                """
            )
            for b in due:
                execute_write(
                    "UPDATE broadcasts SET status = 'sent' WHERE id = %s",
                    (b["id"],),
                )
                logger.info("Scheduled broadcast %d (%r) published", b["id"], b["title"])
        except Exception as exc:
            logger.warning("Scheduled broadcast task error: %s", exc)


async def _monthly_snapshot_task() -> None:
    """Every hour: ensure a usage snapshot exists for each company for the current month."""
    while True:
        await asyncio.sleep(3600)
        try:
            from database.connection import execute_read
            from routers.phase6_billing import _capture_snapshot
            companies = execute_read("SELECT id FROM companies WHERE is_active = 1")
            import datetime as _dt
            month = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m")
            for co in companies:
                existing = execute_read(
                    "SELECT id FROM usage_snapshots WHERE company_id = %s AND month = %s",
                    (co["id"], month),
                )
                if not existing:
                    _capture_snapshot(co["id"])
                    logger.info("Auto-captured usage snapshot for company %d (%s)", co["id"], month)
        except Exception as exc:
            logger.warning("Monthly snapshot task error: %s", exc)


async def _monthly_quota_reset_task() -> None:
    """Sleeps until the 1st of next month midnight UTC, then resets all usage counters."""
    import datetime as _dt
    while True:
        now = _dt.datetime.now(_dt.timezone.utc)
        if now.month == 12:
            next_reset = _dt.datetime(now.year + 1, 1, 1, tzinfo=_dt.timezone.utc)
        else:
            next_reset = _dt.datetime(now.year, now.month + 1, 1, tzinfo=_dt.timezone.utc)
        wait_seconds = (next_reset - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        try:
            from utils.tier_enforcer import reset_monthly_quotas
            reset_monthly_quotas()
            logger.info("Monthly SMS/email/push usage quotas reset for all companies")
        except Exception as exc:
            logger.warning("Monthly quota reset failed: %s", exc)


async def _retention_policy_task() -> None:
    """Every 6 hours: apply DB-driven retention policies from the retention_policies table."""
    while True:
        await asyncio.sleep(21600)
        try:
            from database.connection import execute_read, execute_write
            policies = execute_read(
                "SELECT entity, max_days FROM retention_policies WHERE enabled = 1"
            )
            for p in policies:
                entity   = p["entity"]
                max_days = p["max_days"]
                if entity == "readings":
                    execute_write(
                        "DELETE FROM readings WHERE timestamp < NOW() - INTERVAL '%s days'",
                        (max_days,),
                    )
                elif entity == "login_attempts":
                    execute_write(
                        "DELETE FROM login_attempts WHERE attempted_at < NOW() - INTERVAL '%s days'",
                        (max_days,),
                    )
                elif entity == "admin_activity":
                    execute_write(
                        "DELETE FROM admin_activity WHERE created_at < NOW() - INTERVAL '%s days'",
                        (max_days,),
                    )
                logger.info("Retention policy applied: entity=%s max_days=%d", entity, max_days)
        except Exception as exc:
            logger.warning("Retention policy task error: %s", exc)


# ─── Startup / shutdown ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────

    # 1. Initialise PostgreSQL connection pool + schema + admin password migration
    database.get_db_pool()
    database.init_db()

    from utils.security import migrate_env_admin_password
    migrate_env_admin_password()

    # 2. Clean up any stale admin sessions from previous server runs
    try:
        from database.queries.sessions import cleanup_expired_sessions
        expired = cleanup_expired_sessions()
        if expired:
            logger.info("Startup: cleaned up %d expired admin session(s)", expired)
    except Exception as exc:
        logger.warning("Startup: session cleanup failed: %s", exc)

    # 3. Resume any pending escalations from before last shutdown
    await escalation.resume_pending_escalations()

    # 4. Background tasks
    asyncio.create_task(schedule_daily_report(),      name="daily-report-scheduler")
    asyncio.create_task(schedule_daily_backup(),      name="daily-backup-scheduler")
    asyncio.create_task(schedule_retention_cleanup(), name="retention-cleanup-scheduler")
    asyncio.create_task(_maintenance_expiry_task(),    name="maintenance-expiry")
    asyncio.create_task(_scheduled_broadcast_task(),   name="scheduled-broadcast")
    asyncio.create_task(_monthly_snapshot_task(),      name="monthly-snapshot")
    asyncio.create_task(_retention_policy_task(),      name="retention-policy")
    asyncio.create_task(run_escalation_check(),        name="escalation-policy")
    asyncio.create_task(run_anomaly_detection(),       name="anomaly-detector")
    asyncio.create_task(_monthly_quota_reset_task(),   name="monthly-quota-reset")

    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = "127.0.0.1"
    logger.info(
        "SentinelEdge v%s started -- http://%s:%d  (DEMO_MODE=%s, ENV=%s)",
        APP_VERSION, lan_ip, SERVER_PORT, DEMO_MODE, APP_ENV,
    )

    # ── Startup validation ────────────────────────────────────────────────────
    if APP_ENV == "production":
        if not SMTP_USER:
            logger.warning("SMTP_USER not set — email alerts will fail")
        if not SMTP_PASSWORD:
            logger.warning("SMTP_PASSWORD not set — email alerts will fail")
        if not SMS_GATEWAY_URL:
            logger.warning("SMS_GATEWAY_URL not set — SMS alerts will fail")
        if ADMIN_PASSWORD == "admin123":
            logger.warning("ADMIN_PASSWORD is default — change before deployment")
    else:
        logger.info("Running in DEVELOPMENT mode — using test configuration")

    # 5. Start GSM SMS queue worker — owns the serial port for the server lifetime
    from modules.sms.sender import start_gsm_worker
    start_gsm_worker()
    asyncio.create_task(run_sms_receiver(), name="sms-receiver")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("SentinelEdge shutting down...")

    shutdown_msg = json.dumps({"type": "server_shutdown"})
    dead = set()
    for ws in list(active_connections):
        try:
            await ws.send_text(shutdown_msg)
            await ws.close()
        except Exception:
            dead.add(ws)
    active_connections.difference_update(dead)
    active_connections.clear()

    await escalation.shutdown_escalations()
    from modules.sms.sender import stop_gsm_worker
    stop_gsm_worker()

    # Close PostgreSQL connection pool
    database.close_db_pool()
    logger.info("Shutdown complete.")


# ─── Application ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="SentinelEdge",
    description="""
## SentinelEdge Monitoring System

Real-time IoT sensor monitoring with multi-channel threshold alerts.

### Alert Channels
- **In-App** — WebSocket real-time dashboard
- **Email** — Gmail SMTP delivery
- **SMS** — Android Gateway cellular delivery

### Authentication
Admin endpoints require header:
`X-Admin-Password: your_password`

### Severity Levels
- **WARNING** — 5% over threshold
- **CRITICAL** — 10% over threshold
- **EMERGENCY** — 25% over threshold
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

configure_cors(app)
app.add_middleware(BaseHTTPMiddleware, dispatch=log_requests)

# ── Security headers (Task 6) ─────────────────────────────────────────────────
class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

app.add_middleware(_SecurityHeadersMiddleware)

# ── Rate limiting (slowapi) ───────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)  # required for @limiter.limit() to work


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Return a structured JSON 429 response instead of the default plain text."""
    return _JSONResponse(
        status_code=429,
        content={
            "error":   "RateLimitExceeded",
            "message": "Too many requests. Please slow down.",
            "limit":   str(exc.detail),
        },
        headers={"Retry-After": "60"},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


# ─── Global error handlers ────────────────────────────────────────────────────

@app.exception_handler(SentinelEdgeError)
async def sentinel_error_handler(request: Request, exc: SentinelEdgeError):
    """Convert SentinelEdge domain errors to structured JSON 400 responses."""
    return JSONResponse(
        status_code=400,
        content={
            "error":     exc.__class__.__name__,
            "message":   exc.message,
            "details":   exc.details,
            "timestamp": now_iso(),
            "path":      str(request.url),
        },
    )


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — never expose stack traces to clients."""
    logger.error("Unhandled error on %s: %s", request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error":     "InternalServerError",
            "message":   "An unexpected error occurred",
            "timestamp": now_iso(),
            "path":      str(request.url),
        },
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error":     "NotFound",
            "message":   f"Path {request.url.path} not found",
            "timestamp": now_iso(),
        },
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    logger.exception("Internal server error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ─── Custom parameter threshold helper ───────────────────────────────────────

# Per-parameter cooldown: {param_name: cooldown_epoch_seconds}
_extra_param_cooldowns: dict = {}
_EXTRA_PARAM_COOLDOWN = 300   # 5-minute cooldown between repeated alerts per param

def _check_extra_param_thresholds(extra_params: dict, breach_dicts: list) -> None:
    """
    For each live custom-parameter reading, fetch its configured min/max from
    company_parameters and insert an alert if the value is strictly outside range.
    Appends alert dicts to breach_dicts so they ride the same WebSocket payload.
    Uses a 5-minute per-parameter cooldown to avoid alert floods.
    """
    import time as _time
    from datetime import datetime, timezone, timedelta
    from database.connection import execute_read
    import database

    now = _time.monotonic()
    try:
        params = execute_read(
            "SELECT name, unit, min_value, max_value, company_id "
            "FROM company_parameters WHERE is_active = TRUE"
        )
    except Exception:
        return

    param_map = {p["name"]: p for p in (params or [])}

    for name, value in extra_params.items():
        cfg = param_map.get(name)
        if cfg is None:
            continue

        mn = cfg.get("min_value")
        mx = cfg.get("max_value")
        if mn is None or mx is None:
            continue

        try:
            mn_f, mx_f = float(mn), float(mx)
        except (TypeError, ValueError):
            continue

        if mn_f <= value <= mx_f:
            continue   # within range — no alert

        # Check cooldown
        last_fired = _extra_param_cooldowns.get(name, 0)
        if now - last_fired < _EXTRA_PARAM_COOLDOWN:
            continue

        direction = "high" if value > mx_f else "low"
        threshold_val = mx_f if direction == "high" else mn_f
        cooldown_until = (
            datetime.now(timezone.utc) + timedelta(seconds=_EXTRA_PARAM_COOLDOWN)
        ).isoformat()

        try:
            alert_id = database.insert_alert(
                parameter=name,
                value=value,
                threshold=threshold_val,
                direction=direction,
                cooldown_until=cooldown_until,
                severity="WARNING",
                company_id=cfg.get("company_id"),
            )
            _extra_param_cooldowns[name] = now
            logger.info(
                "Custom param alert: %s=%.3f %s threshold %.3f (alert_id=%s)",
                name, value, direction, threshold_val, alert_id,
            )
            breach_dicts.append({
                "parameter": name,
                "value":     value,
                "threshold": threshold_val,
                "direction": direction,
                "severity":  "WARNING",
                "alert_id":  alert_id,
            })
        except Exception as exc:
            logger.warning("Failed to insert custom param alert for %s: %s", name, exc)


# ─── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    add_connection(ws)
    MODULE_STATUS["websocket"] = "ok"

    try:
        async for reading in sensor.stream_readings():

            is_valid, reason = validate_reading(reading)

            database.insert_reading(
                reading["temperature"],
                reading["timestamp"],
                is_valid=is_valid,
            )

            if not is_valid:
                logger.warning("Invalid reading skipped: %s", reason)
                payload = {
                    "temperature":      reading["temperature"],
                    "timestamp":        reading["timestamp"],
                    "breaches":         [],
                    "is_valid":         False,
                    "validation_error": reason,
                    "extra_params":     dict(extra_sensor.extra_readings),
                }
                await broadcast(payload)
                continue

            # CSV fallback readings never trigger alerts — only real sensor data does.
            # Manual breach override (settings page) has no is_live key → defaults True.
            breaches = threshold.check_threshold(reading) if reading.get("is_live", True) else []

            # Persisting alerts (DB insert) is fast — await it so the live
            # broadcast below can include each breach's real alert_id (the
            # mobile app needs this to POST /api/alerts/{id}/acknowledge).
            # Notification delivery (email/SMS/push) still happens in the
            # background inside trigger_alert() and is never awaited here.
            alert_ids = await escalation.trigger_alert(reading, breaches) if breaches else []

            import routers.health as _health_mod
            _health_mod.last_reading = {
                "temperature": reading["temperature"],
                "timestamp":   reading["timestamp"],
            }

            breach_dicts = []
            for b, aid in zip(breaches, alert_ids):
                d = b.model_dump()
                d["alert_id"] = aid
                breach_dicts.append(d)

            # ── Custom parameter threshold enforcement ────────────────────────
            # For each live extra_param value, check against company_parameters
            # min/max and fire an alert if it falls outside the configured range.
            ep = dict(extra_sensor.extra_readings)
            if ep:
                _check_extra_param_thresholds(ep, breach_dicts)

            payload = {
                "temperature":  reading["temperature"],
                "timestamp":    reading["timestamp"],
                "breaches":     breach_dicts,
                "is_valid":     True,
                "extra_params": ep,
            }
            await broadcast(payload)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as exc:
        logger.exception("WebSocket error: %s", exc)
        MODULE_STATUS["websocket"] = f"error: {exc}"
    finally:
        remove_connection(ws)


# ─── Live log WebSocket ──────────────────────────────────────────────────────

@app.websocket("/ws/logs")
async def log_stream(websocket: WebSocket):
    """Stream sentineledge.log in real time to the admin dashboard."""
    await websocket.accept()

    # Resolve log path relative to this file so it works regardless of CWD
    log_path = Path(os.path.join(os.path.dirname(__file__), "..", "logs", "sentineledge.log")).resolve()

    # Send last 200 lines on connect — tail-read from end of file so we
    # never load the full log into memory (O(chunk) not O(file)).
    if log_path.exists():
        try:
            _LOG_TAIL_LINES  = 200
            _LOG_CHUNK_BYTES = 1024 * 32  # 32 KB — enough for 200 typical log lines

            with open(log_path, "rb") as _f:
                _f.seek(0, 2)                         # seek to end
                _file_size = _f.tell()
                _read_bytes = min(_file_size, _LOG_CHUNK_BYTES)
                _f.seek(-_read_bytes, 2)              # back up by chunk
                _chunk = _f.read(_read_bytes)

            _text_lines = _chunk.decode("utf-8", errors="replace").splitlines()
            initial_lines = _text_lines[-_LOG_TAIL_LINES:]
            for line in initial_lines:
                if line.strip():
                    await websocket.send_text(line)
        except Exception as exc:
            logger.warning("log_stream: error reading initial lines: %s", exc)


    last_size = log_path.stat().st_size if log_path.exists() else 0
    try:
        while True:
            await asyncio.sleep(0.5)
            if log_path.exists():
                size = log_path.stat().st_size
                if size > last_size:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_size)
                        new_content = f.read()
                    last_size = size
                    for line in new_content.splitlines():
                        if line.strip():
                            await websocket.send_text(line)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("log_stream error: %s", exc)



# ─── Readings endpoint ────────────────────────────────────────────────────────

_readings_router = APIRouter(prefix="/api", tags=["Readings"])


@_readings_router.get(
    "/readings/recent",
    response_model=list[ReadingOut],
    summary="Get recent readings",
    description="Returns the last 60 sensor readings in reverse-chronological order.",
)
@limiter.limit("60/minute")
async def get_recent_readings(request: Request):
    rows = database.get_recent_readings(limit=60)
    return [
        ReadingOut(
            temperature=r["temperature"],
            timestamp=r["timestamp"],
            is_valid=bool(r.get("is_valid", True)),
            breaches=[],
        )
        for r in rows
    ]


# ─── Include all routers ──────────────────────────────────────────────────────

app.include_router(_readings_router)
app.include_router(alerts_router)
app.include_router(subscribers_router)
app.include_router(config_router)
app.include_router(simulate_router)
app.include_router(health_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(reports_router)
app.include_router(receipts_router)
app.include_router(events_router)
app.include_router(workers_router)
app.include_router(super_admin_router)
app.include_router(notifications_router)
app.include_router(super_admin_v2_router)
from routers.analytics import router as analytics_router
app.include_router(analytics_router)
app.include_router(phase1_command_router)
app.include_router(phase2_admin_control_router)
app.include_router(phase3_config_router)
app.include_router(phase4_analytics_router)
app.include_router(phase5_comms_router)
app.include_router(phase6_billing_router)
app.include_router(phase7_security_router)

# ─── Static files (built React app) ──────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(_static_dir):
    # Serve /assets/* (JS, CSS) as static files
    _assets_dir = os.path.join(_static_dir, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    # SPA catch-all — MUST be last; returns index.html for every unknown path
    # so React Router can handle /dashboard, /alerts, /settings on hard refresh.
    from fastapi.responses import FileResponse as _FR

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = os.path.join(_static_dir, "index.html")
        if os.path.exists(index):
            return _FR(index)
        return {"error": "Frontend not built. Run npm run build in frontend-web/"}

else:
    logger.warning(
        "Static dir '%s' not found. Run 'npm run build' in frontend-web/ first.",
        _static_dir,
    )

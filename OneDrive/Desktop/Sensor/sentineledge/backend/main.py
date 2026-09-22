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
from core.threshold import auto_register_extra_params, check_extra_param_thresholds
import core.escalation as escalation
import core.extra_sensor as extra_sensor  # tertiary stub (empty dict fallback)
import core.excel_sensor as excel_sensor  # primary  sensor (Pro-Server EX file)
import core.opc_sensor   as opc_sensor    # secondary sensor (OPC DA direct)
from core.escalation_policy import run_escalation_check
from core.anomaly_detector import run_anomaly_detection
from modules.sms.receiver import run_sms_receiver
from core.validator import validate_reading
from core.daily_report import schedule_daily_report
from config import (
    APP_ENV, DEMO_MODE, SERVER_PORT, MODULE_STATUS,
    SMTP_USER, SMTP_PASSWORD, ADMIN_PASSWORD,
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
from routers.health import router as health_router, start_sms_probe
from routers.admin import router as admin_router
from routers.auth import router as auth_router
from routers.history import router as history_router
from routers.reports import router as reports_router
from routers.receipts import router as receipts_router
from routers.events import router as events_router
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

# ── Sentry error tracking ──────────────────────────────────────────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    try:
        import sentry_sdk  # type: ignore[import-untyped]
        from sentry_sdk.integrations.fastapi import FastApiIntegration  # type: ignore[import-untyped]
        from sentry_sdk.integrations.starlette import StarletteIntegration  # type: ignore[import-untyped]
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            environment=os.getenv("APP_ENV", "development"),
            integrations=[StarletteIntegration(), FastApiIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry error tracking enabled (env=%s)", os.getenv("APP_ENV"))
    except Exception as _se:
        logger.warning("Sentry init failed: %s", _se)
else:
    logger.debug("SENTRY_DSN not set — error tracking disabled")


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


async def _session_cleanup_task() -> None:
    """Every hour: delete expired admin and subscriber sessions to keep tables lean."""
    while True:
        await asyncio.sleep(3600)
        try:
            from database.connection import execute_write
            adm = execute_write(
                "DELETE FROM admin_sessions WHERE expires_at < NOW() - INTERVAL '7 days'"
            )
            sub = execute_write(
                "DELETE FROM subscriber_sessions WHERE expires_at < NOW() - INTERVAL '7 days'"
            )
            logger.info(
                "Session cleanup: removed %d expired admin session(s), %d subscriber session(s)",
                adm.rowcount, sub.rowcount,
            )
        except Exception as exc:
            logger.warning("Session cleanup task error: %s", exc)


async def _notification_retry_task() -> None:
    """Every 5 minutes: attempt redelivery of failed notifications in the retry queue."""
    while True:
        await asyncio.sleep(300)
        try:
            from database.connection import execute_read, execute_write
            import json as _json

            due = execute_read(
                """
                SELECT id, alert_id, subscriber_id, channel, attempt_count, payload
                  FROM notification_retry_queue
                 WHERE next_retry_at <= NOW()
                   AND attempt_count < 5
                 ORDER BY next_retry_at
                 LIMIT 20
                """
            )
            for item in due:
                rid       = item["id"]
                channel   = item["channel"]
                attempts  = item["attempt_count"] + 1
                payload   = item.get("payload") or {}
                success   = False
                last_error = None

                try:
                    if channel == "email":
                        from modules.email.smtp import send_email_async
                        sub_rows = execute_read(
                            "SELECT email FROM subscribers WHERE id = %s LIMIT 1",
                            (item["subscriber_id"],),
                        )
                        if sub_rows and sub_rows[0].get("email"):
                            await send_email_async(
                                sub_rows[0]["email"],
                                payload.get("subject", "Alert Retry"),
                                payload.get("body", ""),
                            )
                            success = True
                    elif channel == "sms":
                        from modules.sms.sender import send_sms_async
                        sub_rows = execute_read(
                            "SELECT phone FROM subscribers WHERE id = %s LIMIT 1",
                            (item["subscriber_id"],),
                        )
                        if sub_rows and sub_rows[0].get("phone"):
                            await send_sms_async(
                                sub_rows[0]["phone"],
                                payload.get("message", ""),
                            )
                            success = True
                except Exception as send_exc:
                    last_error = str(send_exc)[:500]

                if success:
                    execute_write(
                        "DELETE FROM notification_retry_queue WHERE id = %s", (rid,)
                    )
                    logger.info("Retry succeeded: queue_id=%d channel=%s", rid, channel)
                else:
                    # Exponential back-off: 5m, 10m, 20m, 40m, 80m
                    backoff_minutes = 5 * (2 ** (attempts - 1))
                    execute_write(
                        """
                        UPDATE notification_retry_queue
                           SET attempt_count = %s,
                               next_retry_at = NOW() + (%s || ' minutes')::interval,
                               last_error    = %s
                         WHERE id = %s
                        """,
                        (attempts, backoff_minutes, last_error, rid),
                    )
        except Exception as exc:
            logger.warning("Notification retry task error: %s", exc)


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

    # Write PID file so start.bat can reliably kill this exact process on restart
    _pid_file = os.path.join(os.path.dirname(__file__), "server.pid")
    try:
        with open(_pid_file, "w") as _f:
            _f.write(str(os.getpid()))
    except Exception:
        pass

    # 1. Initialise PostgreSQL connection pool + schema + admin password migration
    database.get_db_pool()
    database.init_db()

    from utils.security import migrate_env_admin_password
    migrate_env_admin_password()

    # 1a. Load Pro-Server EX settings from DB (overrides env-var defaults if a
    #     file path was previously saved via Admin → Settings → Pro-Server EX).
    try:
        _ps_rows = database.execute_read(
            "SELECT key, value FROM app_settings WHERE key LIKE %s",
            ("proserver_%",),
        ) or []
        _ps_vals = {r["key"].replace("proserver_", "", 1): r["value"] for r in _ps_rows}
        if _ps_vals.get("file_path", "").strip():
            import core.excel_sensor as _excel_sensor
            _excel_sensor.reload_settings(_ps_vals)
            logger.info(
                "Startup: Pro-Server EX path loaded from DB: %s",
                _ps_vals["file_path"],
            )
        # Restore persisted enable/disable (live-only) state across restarts
        import core.excel_sensor as _excel_sensor
        _excel_sensor.load_persistent_settings()
    except Exception as _exc:
        import traceback as _tb
        logger.warning("Startup: could not load proserver settings from DB: %s\n%s", _exc, _tb.format_exc())

    # 1b. Load OPC DA settings from DB (secondary sensor)
    try:
        _opc_rows = database.execute_read(
            "SELECT key, value FROM app_settings WHERE key LIKE %s",
            ("opc_%",),
        ) or []
        _opc_vals = {r["key"].replace("opc_", "", 1): r["value"] for r in _opc_rows}
        if _opc_vals.get("server_name", "").strip():
            opc_sensor.reload_settings(_opc_vals)
            logger.info(
                "Startup: OPC DA server loaded from DB: %s",
                _opc_vals["server_name"],
            )
    except Exception as _exc:
        import traceback as _tb
        logger.warning("Startup: could not load OPC settings from DB: %s\n%s", _exc, _tb.format_exc())

    # 1c. Load alert settings from DB (pH threshold, enable flags)
    try:
        _alert_rows = database.execute_read(
            "SELECT key, value FROM app_settings WHERE key LIKE %s",
            ("alert_%",),
        ) or []
        for _r in _alert_rows:
            _k, _v = _r["key"], _r["value"]
            if _k in ("alert_ph_threshold", "alert_ph_threshold_max"):
                from config import RUNTIME_THRESHOLDS
                try:
                    RUNTIME_THRESHOLDS["ph_threshold_max"] = float(_v)
                except ValueError:
                    pass
            elif _k == "alert_ph_threshold_min":
                from config import RUNTIME_THRESHOLDS
                try:
                    RUNTIME_THRESHOLDS["ph_threshold_min"] = float(_v)
                except ValueError:
                    pass
            elif _k == "alert_ph_enabled":
                from config import RUNTIME_THRESHOLDS
                RUNTIME_THRESHOLDS["ph_alerts_enabled"] = _v.lower() == "true"
            elif _k == "alert_temp_enabled":
                from config import RUNTIME_THRESHOLDS
                RUNTIME_THRESHOLDS["temp_alerts_enabled"] = _v.lower() == "true"
        if _alert_rows:
            logger.info("Startup: alert settings loaded from DB")
    except Exception as _exc:
        logger.warning("Startup: could not load alert settings from DB: %s", _exc)

    # 1d. Load temperature thresholds from DB (persisted by POST /api/config/thresholds)
    try:
        _thresh_rows = database.execute_read(
            "SELECT key, value FROM app_settings WHERE key IN (%s, %s)",
            ("threshold_temp_high", "threshold_temp_low"),
        ) or []
        for _r in _thresh_rows:
            _k, _v = _r["key"], _r["value"]
            from config import RUNTIME_THRESHOLDS
            try:
                if _k == "threshold_temp_high":
                    RUNTIME_THRESHOLDS["temp_high"] = float(_v)
                elif _k == "threshold_temp_low":
                    RUNTIME_THRESHOLDS["temp_low"] = float(_v)
            except ValueError:
                pass
        if _thresh_rows:
            logger.info(
                "Startup: temperature thresholds loaded from DB — high=%.1f low=%.1f",
                RUNTIME_THRESHOLDS["temp_high"], RUNTIME_THRESHOLDS["temp_low"],
            )
    except Exception as _exc:
        logger.warning("Startup: could not load temperature thresholds from DB: %s", _exc)

    # 2. Clean up any stale sessions from previous server runs
    try:
        from database.queries.sessions import cleanup_expired_sessions
        expired = cleanup_expired_sessions()
        if expired:
            logger.info("Startup: cleaned up %d expired admin session(s)", expired)
    except Exception as exc:
        logger.warning("Startup: admin session cleanup failed: %s", exc)

    try:
        from database.queries.subscriber_sessions import cleanup_expired_sub_sessions
        expired_sub = cleanup_expired_sub_sessions()
        if expired_sub:
            logger.info("Startup: cleaned up %d expired subscriber session(s)", expired_sub)
    except Exception as exc:
        logger.warning("Startup: subscriber session cleanup failed: %s", exc)

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
    asyncio.create_task(_session_cleanup_task(),       name="session-cleanup")
    asyncio.create_task(_notification_retry_task(),    name="notification-retry")

    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = "127.0.0.1"
    logger.info(
        "SentinelEdge v%s started -- http://%s:%d  (DEMO_MODE=%s, ENV=%s)",
        APP_VERSION, lan_ip, SERVER_PORT, DEMO_MODE, APP_ENV,
    )

    # ── Startup validation ────────────────────────────────────────────────────
    _WARN = logger.warning
    if not SMTP_USER or not SMTP_PASSWORD:
        _WARN("SECURITY: SMTP_USER/SMTP_PASSWORD not set — email alerts will fail")
    if ADMIN_PASSWORD in ("admin123", "sentineledge-admin", "password", ""):
        _WARN("SECURITY: ADMIN_PASSWORD is a known default — change it before exposing to a network")
    from config import VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        _WARN("SECURITY: VAPID keys not set — web push notifications will not work")
    _default_db = "postgresql://sentineledge:sentineledge123@localhost"
    import os as _os
    if _os.getenv("DATABASE_URL", "").startswith(_default_db) or not _os.getenv("DATABASE_URL"):
        _WARN("SECURITY: DATABASE_URL uses default credentials — set a strong password in .env")
    if APP_ENV != "production":
        logger.info("Running in %s mode — set APP_ENV=production for production checks", APP_ENV)

    # 5. Start GSM SMS queue worker + background SMS modem probe thread
    from modules.sms.sender import start_gsm_worker
    start_gsm_worker()
    asyncio.create_task(run_sms_receiver(), name="sms-receiver")
    start_sms_probe()

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    try:
        os.unlink(_pid_file)
    except Exception:
        pass
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
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(BaseHTTPMiddleware, dispatch=log_requests)

# ── Security headers ──────────────────────────────────────────────────────────
class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none';"
        )
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
    detail = getattr(exc, "detail", None)
    message = str(detail) if detail and detail != "Not Found" else f"Path {request.url.path} not found"
    return JSONResponse(
        status_code=404,
        content={
            "error":     "NotFound",
            "message":   message,
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


# Custom parameter threshold helpers live in core/threshold.py:
#   auto_register_extra_params(ep, company_id)
#   check_extra_param_thresholds(extra_params, breach_dicts)


# ─── WebSocket ───────────────────────────────────────────────────────────────

def _ws_authenticate(token: str) -> dict | None:
    """Validate a WebSocket token. Accepts both admin sessions and subscriber sessions."""
    if not token:
        return None
    try:
        from database.queries.sessions import get_session
        from database.connection import execute_read

        # 1. Try admin session (dashboard / web clients)
        session = get_session(token)
        if session is not None:
            admin_id = session.get("admin_id")
            if admin_id is not None:
                rows = execute_read(
                    "SELECT is_active, company_id FROM admins WHERE id = %s LIMIT 1", (admin_id,)
                )
                if rows and rows[0].get("is_active") != 0:
                    return {"admin_id": admin_id, "company_id": rows[0].get("company_id")}

        # 2. Try subscriber session (mobile app)
        from database.queries.subscriber_sessions import get_sub_session
        sub_session = get_sub_session(token)
        if sub_session is not None:
            sub = database.get_subscriber_by_id(sub_session["subscriber_id"])
            company_id = sub.get("company_id") if sub else None
            return {"admin_id": None, "company_id": company_id}

        return None
    except Exception as exc:
        logger.warning("WS auth error: %s", exc)
        return None


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    # Authenticate before accepting the connection
    admin_ctx = _ws_authenticate(token)
    if admin_ctx is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    company_id = admin_ctx.get("company_id")

    await ws.accept()
    add_connection(ws)
    MODULE_STATUS["websocket"] = "ok"

    try:
        async for reading in sensor.stream_readings():

            # ── Excel mode: substitute live file values for serial-sensor values ─
            # When EXCEL_FILE_PATH is set, the excel_sensor background thread
            # keeps current_temperature / current_timestamp / extra_readings
            # up to date from the pro-server Excel file.  We use those values
            # instead of the CSV/serial fallback so each column maps exactly to
            # the correct parameter (temperature → temp, pH → pH, no interchange).
            if excel_sensor.is_active() and excel_sensor.current_temperature is not None:
                # Primary: Excel/CSV file from Pro-Server EX
                # is_live = False when replaying historical loop rows → no alerts fire
                reading = {
                    "temperature": excel_sensor.current_temperature,
                    "timestamp":   excel_sensor.current_timestamp or reading["timestamp"],
                    "is_live":     excel_sensor.is_live_data(),
                }
            elif opc_sensor.is_active() and opc_sensor.current_temperature is not None:
                # Secondary: OPC DA direct connection (used when file reader is not active)
                reading = {
                    "temperature": opc_sensor.current_temperature,
                    "timestamp":   opc_sensor.current_timestamp or reading["timestamp"],
                    "is_live":     True,
                }
            # Live-only idle: Excel sensor enabled but no recent live data →
            # broadcast NULL so dashboard shows "—", skip DB insert entirely.
            if (excel_sensor.is_active()
                    and not excel_sensor._excel_enabled
                    and excel_sensor.current_temperature is None):
                await broadcast({
                    "temperature":    None,
                    "timestamp":      reading.get("timestamp", ""),
                    "breaches":       [],
                    "is_valid":       False,
                    "extra_params":   {},
                    "live_only_idle": True,
                })
                continue

            if excel_sensor.is_active():
                # Start with fallback values (humidity, vibration, etc.) then
                # overlay real Excel readings so ph/pressure overwrite the fallback.
                ep = dict(extra_sensor.extra_readings)
                ep.update(excel_sensor.extra_readings)
            elif opc_sensor.is_active():
                ep = dict(opc_sensor.extra_readings)
            else:
                ep = dict(extra_sensor.extra_readings)
            # Normalize keys to lowercase so DB queries (analytics) match regardless
            # of how Pro-Server EX capitalizes column headers (pH vs ph vs PH)
            ep = {k.lower(): v for k, v in ep.items()}

            # Auto-register any new extra-sensor parameters so they appear in
            # the Super Admin company detail count and Config > Parameters tab.
            if ep and company_id:
                auto_register_extra_params(ep, company_id)

            is_valid, reason = validate_reading(reading)

            database.insert_reading(
                reading["temperature"],
                reading["timestamp"],
                is_valid=is_valid,
                extra_params=ep,
                company_id=company_id,
            )

            if not is_valid:
                logger.warning("Invalid reading skipped: %s", reason)
                payload = {
                    "temperature":      reading["temperature"],
                    "timestamp":        reading["timestamp"],
                    "breaches":         [],
                    "is_valid":         False,
                    "validation_error": reason,
                    "extra_params":     ep,
                }
                await broadcast(payload)
                continue

            # CSV fallback readings never trigger alerts — only real sensor data does.
            # Manual breach override (settings page) has no is_live key → defaults True.
            reading["extra_params"] = ep
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
            if ep:
                check_extra_param_thresholds(ep, breach_dicts)

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

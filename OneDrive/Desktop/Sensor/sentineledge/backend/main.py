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

from database.backup import schedule_daily_backup
from database.retention import schedule_retention_cleanup

logger = get_logger(__name__)


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
                }
                await broadcast(payload)
                continue

            breaches = threshold.check_threshold(reading)

            if breaches:
                asyncio.create_task(escalation.trigger_alert(reading, breaches))

            import routers.health as _health_mod
            _health_mod.last_reading = {
                "temperature": reading["temperature"],
                "timestamp":   reading["timestamp"],
            }

            payload = {
                "temperature": reading["temperature"],
                "timestamp":   reading["timestamp"],
                "breaches":    [b.model_dump() for b in breaches],
                "is_valid":    True,
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

    # Send last 100 lines on connect — silently skip if file missing or unreadable
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            initial_lines = lines[-100:] if len(lines) > 100 else lines
            for line in initial_lines:
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

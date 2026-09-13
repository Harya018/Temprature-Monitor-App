"""
watchdog_config.py — SentinelEdge Watchdog Configuration
Edit these values before deploying to client.
"""

# ── Server location ───────────────────────────────────────────────────────────
SERVER_HOST = "localhost"
SERVER_PORT = 5000

# NOTE: SentinelEdge runs HTTPS (self-signed cert). The watchdog uses
# verify=False so it can reach the health endpoint without CA validation.
HEALTH_ENDPOINT = f"http://{SERVER_HOST}:{SERVER_PORT}/api/health"

# ── Timing ───────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SECONDS         = 30   # ping server every 30 s
FAILURE_RETRY_SECONDS          = 10   # wait before confirming down
CONSECUTIVE_FAILURES_TO_RESTART = 2   # 2 consecutive failures → restart

# ── Server start command (matches start_server.bat exactly) ──────────────────
SERVER_COMMAND = [
    "venv\\Scripts\\uvicorn", "backend.main:app",
    "--host",          "0.0.0.0",
    "--port",          "5000",
]
SERVER_WORKING_DIR     = os.path.dirname(os.path.abspath(__file__))
SERVER_ENV_PYTHONPATH  = os.path.join(SERVER_WORKING_DIR, "backend")

# ── Developer alert settings ──────────────────────────────────────────────────
ALERT_EMAIL = True           # send email when server restarts
import os
# These are loaded from .env at runtime; set fallbacks here.
WATCHDOG_ALERT_EMAIL = os.getenv("WATCHDOG_ALERT_EMAIL", "")
WATCHDOG_ALERT_PHONE = os.getenv("WATCHDOG_ALERT_PHONE", "")

# ── Watchdog log file ─────────────────────────────────────────────────────────
LOG_FILE = os.path.join(SERVER_WORKING_DIR, "logs", "watchdog.log")

# ── Restart limits ────────────────────────────────────────────────────────────
MAX_RESTART_ATTEMPTS      = 5    # give up after 5 consecutive restart failures
RESTART_COOLDOWN_SECONDS  = 60   # wait 60 s between restart attempts

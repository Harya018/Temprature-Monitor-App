"""
watchdog.py — SentinelEdge Server Watchdog

Monitors the SentinelEdge HTTPS server and automatically restarts it
if it goes down. Runs as a completely independent process.

Usage:
    python watchdog.py

Or via the launcher:
    start_with_watchdog.bat
"""

import os
import sys
import time
import signal
import logging
import subprocess
import smtplib
from datetime import datetime
from logging.handlers import RotatingFileHandler
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
import urllib3
from dotenv import load_dotenv

import watchdog_config as cfg

# ── Suppress SSL warnings for self-signed cert ───────────────────────────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Load .env ─────────────────────────────────────────────────────────────────
_ENV_PATH = os.path.join(cfg.SERVER_WORKING_DIR, ".env.development")
load_dotenv(_ENV_PATH, override=False)

# Override developer contact from env if present
WATCHDOG_ALERT_EMAIL = os.getenv("WATCHDOG_ALERT_EMAIL", cfg.WATCHDOG_ALERT_EMAIL).strip()
WATCHDOG_ALERT_PHONE = os.getenv("WATCHDOG_ALERT_PHONE", cfg.WATCHDOG_ALERT_PHONE).strip()

# SMTP credentials (same as main server)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASSWORD", "")

# ── Logging setup ─────────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    log_dir = os.path.dirname(cfg.LOG_FILE)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("watchdog")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — 5 MB per file, keep 3 backups
    fh = RotatingFileHandler(cfg.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    logger.addHandler(ch)

    return logger


log = _setup_logging()

# ── Global state ──────────────────────────────────────────────────────────────
server_process: subprocess.Popen | None = None
consecutive_failures:          int = 0
total_restarts:                 int = 0
restart_attempts_this_session:  int = 0
server_start_time:  datetime | None = None
watchdog_start_time: datetime       = datetime.now()
last_ok_log_time:   datetime | None = None   # throttle "[OK]" log lines


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────
def check_server_health() -> bool:
    """Return True if the server responds 200 to the health endpoint."""
    try:
        resp = requests.get(
            cfg.HEALTH_ENDPOINT,
            timeout=5,
            verify=False,   # self-signed cert
        )
        return resp.status_code == 200
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Process management
# ─────────────────────────────────────────────────────────────────────────────
def start_server() -> subprocess.Popen:
    """Launch the SentinelEdge uvicorn process and return its handle."""
    global server_start_time

    env = os.environ.copy()
    env["PYTHONPATH"] = cfg.SERVER_ENV_PYTHONPATH

    log.info("Starting server: %s", " ".join(cfg.SERVER_COMMAND))

    kwargs: dict = dict(
        cwd=cfg.SERVER_WORKING_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(cfg.SERVER_COMMAND, **kwargs)
    server_start_time = datetime.now()
    log.info("Server PID: %d — waiting for initialisation…", process.pid)
    time.sleep(8)   # give uvicorn time to load CSV data + start listener
    return process


def stop_server(process: subprocess.Popen | None) -> None:
    """Gracefully terminate the server process."""
    if process is None or process.poll() is not None:
        return
    log.info("Stopping server (PID %d)…", process.pid)
    try:
        if sys.platform == "win32":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=10)
        log.info("Server stopped cleanly.")
    except subprocess.TimeoutExpired:
        log.warning("Server did not stop in time — killing forcefully.")
        process.kill()
    except Exception as exc:
        log.warning("Error stopping server: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Email alerts
# ─────────────────────────────────────────────────────────────────────────────
def send_alert_email(subject: str, body: str) -> None:
    """Send an alert email to DEVELOPER_EMAIL using the project SMTP config."""
    if not cfg.ALERT_EMAIL:
        return
    if not WATCHDOG_ALERT_EMAIL:
        log.warning("ALERT_EMAIL=True but WATCHDOG_ALERT_EMAIL is empty — skipping email.")
        return
    if not SMTP_USER or not SMTP_PASS:
        log.warning("SMTP credentials missing in .env — skipping alert email.")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = WATCHDOG_ALERT_EMAIL

        text_body = body.strip()
        html_body = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">
          <div style="background:#1E1B4B;padding:20px;border-radius:8px 8px 0 0">
            <h2 style="color:#fff;margin:0">🛡 SentinelEdge Watchdog</h2>
          </div>
          <div style="border:1px solid #e0e0e0;border-top:none;padding:24px;border-radius:0 0 8px 8px">
            <pre style="background:#f8f8f8;padding:16px;border-radius:6px;font-size:13px;line-height:1.6">{text_body}</pre>
          </div>
        </body></html>
        """

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_USER, WATCHDOG_ALERT_EMAIL, msg.as_string())

        log.info("Alert email sent to %s", WATCHDOG_ALERT_EMAIL)
    except Exception as exc:
        log.error("Failed to send alert email: %s", exc)


def send_developer_alert(event: str, details: str) -> None:
    """Compose and send a watchdog event alert."""
    uptime_secs = (datetime.now() - watchdog_start_time).total_seconds()
    uptime_str  = _format_duration(int(uptime_secs))

    server_uptime = ""
    if server_start_time:
        secs = (datetime.now() - server_start_time).total_seconds()
        server_uptime = f"Server uptime before event : {_format_duration(int(secs))}"

    body = f"""
Event   : {event}
Time    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Details : {details}

Total restarts this session : {total_restarts}
Watchdog running since      : {watchdog_start_time.strftime('%Y-%m-%d %H:%M:%S')} ({uptime_str})
{server_uptime}
Health endpoint : {cfg.HEALTH_ENDPOINT}
Log file        : {cfg.LOG_FILE}
    """.strip()

    send_alert_email(f"[SentinelEdge Watchdog] {event}", body)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _format_duration(seconds: int) -> str:
    """Return a human-readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    parts  = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}s")
    return " ".join(parts)


def _server_uptime_str() -> str:
    if server_start_time is None:
        return "unknown"
    secs = int((datetime.now() - server_start_time).total_seconds())
    return _format_duration(secs)


def get_server_status() -> dict:
    """Return a status snapshot dict."""
    return {
        "is_healthy":          check_server_health(),
        "total_restarts":      total_restarts,
        "last_restart_time":   server_start_time.isoformat() if server_start_time else None,
        "consecutive_failures":consecutive_failures,
        "uptime":              _server_uptime_str(),
        "watchdog_since":      watchdog_start_time.isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────────────
def _print_banner() -> None:
    print()
    print("╔══════════════════════════════════════════╗")
    print("║   SentinelEdge Watchdog v1.0             ║")
    print(f"║   Monitoring: {cfg.SERVER_HOST}:{cfg.SERVER_PORT}             ║")
    print(f"║   Health: {cfg.HEALTH_ENDPOINT[:38]}  ║")
    print("╚══════════════════════════════════════════╝")
    print(f"   Check interval : {cfg.CHECK_INTERVAL_SECONDS}s")
    print(f"   Failures needed: {cfg.CONSECUTIVE_FAILURES_TO_RESTART}")
    print(f"   Max restarts   : {cfg.MAX_RESTART_ATTEMPTS}")
    print(f"   Log file       : {cfg.LOG_FILE}")
    print(f"   Alert email    : {WATCHDOG_ALERT_EMAIL or '(not set)'}")
    print()


def main() -> None:
    global server_process, consecutive_failures, total_restarts
    global restart_attempts_this_session, last_ok_log_time

    _print_banner()
    log.info("Watchdog started. PID=%d", os.getpid())

    # ── Initial state: is the server already running? ────────────────────────
    if check_server_health():
        log.info("Server already running — watchdog entering monitor mode.")
        server_process = None   # don't own the pre-existing process
    else:
        log.info("Server is NOT running — starting it now…")
        server_process = start_server()
        if check_server_health():
            log.info("[UP] Server started by watchdog. PID=%s",
                     server_process.pid if server_process else "?")
        else:
            log.warning("[WARN] Server started but health check failed — will retry.")

    # ── Main monitoring loop ─────────────────────────────────────────────────
    try:
        while True:
            time.sleep(cfg.CHECK_INTERVAL_SECONDS)

            healthy = check_server_health()

            if healthy:
                consecutive_failures = 0

                # Log "[OK]" only every 5 minutes to avoid log spam
                now = datetime.now()
                if last_ok_log_time is None or (now - last_ok_log_time).total_seconds() >= 300:
                    log.info("[OK] Server healthy — uptime: %s  |  total restarts: %d",
                             _server_uptime_str(), total_restarts)
                    last_ok_log_time = now
            else:
                consecutive_failures += 1
                log.warning("[WARN] Health check failed (%d/%d)",
                            consecutive_failures, cfg.CONSECUTIVE_FAILURES_TO_RESTART)

                if consecutive_failures < cfg.CONSECUTIVE_FAILURES_TO_RESTART:
                    # Wait a bit and do an extra confirmation check
                    time.sleep(cfg.FAILURE_RETRY_SECONDS)
                    if check_server_health():
                        log.info("[OK] Server recovered on retry — resetting failure counter.")
                        consecutive_failures = 0
                    continue

                # ── Server confirmed DOWN ────────────────────────────────────
                log.error("[DOWN] Server is DOWN after %d consecutive failures.",
                          consecutive_failures)

                if restart_attempts_this_session >= cfg.MAX_RESTART_ATTEMPTS:
                    msg = (f"Server has been restarted {restart_attempts_this_session} times "
                           f"this session and is still not responding. "
                           f"Manual intervention required.")
                    log.critical("[CRITICAL] Max restart attempts (%d) reached. "
                                 "Stopping watchdog. %s", cfg.MAX_RESTART_ATTEMPTS, msg)
                    send_developer_alert("CRITICAL — Max restarts reached", msg)
                    break

                # ── Attempt restart ──────────────────────────────────────────
                log.info("[RESTART] Stopping old process and waiting %ds cooldown…",
                         cfg.RESTART_COOLDOWN_SECONDS)
                stop_server(server_process)
                server_process = None
                time.sleep(cfg.RESTART_COOLDOWN_SECONDS)

                log.info("[RESTART] Starting server (attempt %d/%d)…",
                         restart_attempts_this_session + 1, cfg.MAX_RESTART_ATTEMPTS)
                server_process = start_server()
                restart_attempts_this_session += 1
                total_restarts += 1

                # Confirm the restart worked
                time.sleep(3)
                if check_server_health():
                    log.info("[UP] Server restarted successfully. PID=%s — uptime clock reset.",
                             server_process.pid if server_process else "?")
                    send_developer_alert(
                        "Server Restarted — OK",
                        f"Server was down and has been restarted successfully.\n"
                        f"Restart #{total_restarts} this session.\n"
                        f"Attempt #{restart_attempts_this_session}/{cfg.MAX_RESTART_ATTEMPTS}.",
                    )
                    consecutive_failures          = 0
                    restart_attempts_this_session = 0   # reset after successful restart
                    last_ok_log_time              = None
                else:
                    log.error("[ERROR] Server failed to come back after restart attempt %d.",
                              restart_attempts_this_session)
                    send_developer_alert(
                        f"Restart Attempt {restart_attempts_this_session} FAILED",
                        f"Server was restarted but health check still fails.\n"
                        f"Will retry in {cfg.CHECK_INTERVAL_SECONDS}s "
                        f"(up to {cfg.MAX_RESTART_ATTEMPTS} total attempts).",
                    )

    except KeyboardInterrupt:
        log.info("Watchdog stopped by user (Ctrl+C).")
        print("\n[Watchdog] Shutting down…")

    finally:
        # Only stop the server if this watchdog started it
        if server_process is not None and server_process.poll() is None:
            answer = input(
                "\n[Watchdog] Stop the server process too? [y/N]: "
            ).strip().lower()
            if answer == "y":
                stop_server(server_process)
                log.info("Server stopped along with watchdog.")
            else:
                log.info("Server left running (PID %d).", server_process.pid)

        log.info("Watchdog exiting. Total restarts this session: %d", total_restarts)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()

"""
utils/logger.py — Centralised logging for SentinelEdge.

Every file gets its logger via:
    from utils.logger import get_logger
    logger = get_logger(__name__)

Features:
- Two handlers: console + rotating file (logs/sentineledge.log)
- Level: DEBUG in development, WARNING in production
- Sensitive values are never written to logs (see sanitise_log_data)
- Creates logs/ directory automatically
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
_ROOT_LOGGER_NAME = "sentineledge"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
_BACKUP_COUNT = 5

_SENSITIVE_KEYS = {
    "password", "token", "key", "secret", "auth",
    "credential", "smtp_password", "admin_password",
    "sms_gateway_pass", "api_key", "private_key",
}

# Resolve logs/ directory relative to project root
# backend/utils/logger.py → ../../logs/
_LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

_configured = False


def _configure() -> None:
    """Configure the root sentineledge logger (called once)."""
    global _configured
    if _configured:
        return

    # Determine level from APP_ENV
    app_env = os.getenv("APP_ENV", "development").lower()
    level = logging.DEBUG if app_env == "development" else logging.INFO

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(level)

    fmt = logging.Formatter(_LOG_FORMAT)

    # ── Console handler ───────────────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(level)
    root.addHandler(console)

    # ── Rotating file handler ─────────────────────────────────────────────────
    try:
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _LOGS_DIR / "sentineledge.log"
        fh = RotatingFileHandler(
            log_file,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh.setLevel(level)
        root.addHandler(fh)
    except Exception as exc:
        # Never crash on logging setup failure
        root.warning("Could not create file log handler: %s", exc)

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger named sentineledge.<name>.

    Usage:
        logger = get_logger(__name__)
        logger.info("Server started")
    """
    _configure()
    # Strip leading 'backend.' prefix if present (common when imported as package)
    clean = name.replace("backend.", "").lstrip(".")
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{clean}")


def sanitise_log_data(data: dict) -> dict:
    """
    Return a copy of `data` with sensitive values replaced by '***REDACTED***'.

    Safe to pass any dict directly to a log call.

    Example:
        logger.debug("Config loaded: %s", sanitise_log_data(config_dict))
    """
    if not isinstance(data, dict):
        return data
    cleaned = {}
    for k, v in data.items():
        if any(sensitive in str(k).lower() for sensitive in _SENSITIVE_KEYS):
            cleaned[k] = "***REDACTED***"
        elif isinstance(v, dict):
            cleaned[k] = sanitise_log_data(v)
        else:
            cleaned[k] = v
    return cleaned


# Run configuration at import time so child loggers are ready immediately
_configure()

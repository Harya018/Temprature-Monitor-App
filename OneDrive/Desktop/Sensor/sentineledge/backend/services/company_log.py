"""
services/company_log.py — a separate activity log for every company.

Each company gets its own file, logs/companies/company_<id>.log (rotated at 5 MB, 3 kept),
in the same line format as the server log, so the dashboard's Live Logs page shows a
company only ITS readings, alerts, acknowledgements, logins and settings changes — never
another company's. (Platform-level logins still see the full server log.)
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from typing import Optional

LOG_DIR = os.environ.get("COMPANY_LOG_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs", "companies"))
_FMT = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_loggers: dict = {}
_lock = threading.Lock()


def log_path(company_id: int) -> str:
    return os.path.join(LOG_DIR, f"company_{int(company_id)}.log")


def get(company_id: Optional[int]) -> Optional[logging.Logger]:
    if company_id is None:
        return None
    cid = int(company_id)
    with _lock:
        lg = _loggers.get(cid)
        if lg is None:
            os.makedirs(LOG_DIR, exist_ok=True)
            lg = logging.getLogger(f"sentineledge.company.{cid}")
            lg.setLevel(logging.INFO)
            lg.propagate = False                 # keeps the main server log quiet
            h = RotatingFileHandler(log_path(cid), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            h.setFormatter(_FMT)
            lg.addHandler(h)
            _loggers[cid] = lg
        return lg


def log(company_id: Optional[int], message: str, level: int = logging.INFO) -> None:
    """Never raises — logging must not break the action being logged."""
    try:
        lg = get(company_id)
        if lg is not None:
            lg.log(level, message)
    except Exception:
        pass

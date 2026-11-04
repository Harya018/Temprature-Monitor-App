"""
services/keep_safe.py — a protected copy of this PC's own secrets OUTSIDE the program folder.

Deleting the SentinelEdge folder (e.g. to install a fresh copy from GitHub) must not lose:
  env.backup         the settings file (database password, the main company's e-mail account)
  settings.key       the key that unlocks each company's saved e-mail password
  postgres_password  written by FIRST_TIME_SETUP when it installed PostgreSQL
They are copied to C:\\ProgramData\\SentinelEdge (only Administrators, SYSTEM and this user can open it);
FIRST_TIME_SETUP and the server put them back when the program folder has none. The database itself
lives in PostgreSQL and is not affected by deleting the folder.

Tests (SENTINEL_ENV_FILE / SETTINGS_KEY_FILE set) never touch the real copy; SENTINEL_KEEP_DIR overrides it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


def keep_dir() -> str:
    return os.environ.get("SENTINEL_KEEP_DIR") or os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "SentinelEdge")


def _active() -> bool:
    if os.environ.get("SENTINEL_KEEP_DIR"):
        return True
    return not (os.environ.get("SENTINEL_ENV_FILE") or os.environ.get("SETTINGS_KEY_FILE"))


def _ensure_dir() -> Optional[str]:
    d = keep_dir()
    try:
        new = not os.path.isdir(d)
        os.makedirs(d, exist_ok=True)
        if new and os.name == "nt" and not os.environ.get("SENTINEL_KEEP_DIR"):
            user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
            subprocess.run(["icacls", d, "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
                            f"{user}:(OI)(CI)F"], capture_output=True, timeout=20)
        return d
    except Exception as exc:
        logger.debug("keep_safe: no folder %s: %s", d, exc)
        return None


def save(src: str, name: str) -> None:
    """Copy a secret file into the protected folder (best effort, never raises)."""
    if not _active() or not os.path.isfile(src):
        return
    d = _ensure_dir()
    if not d:
        return
    try:
        dst = os.path.join(d, name)
        if not os.path.exists(dst) or open(src, "rb").read() != open(dst, "rb").read():
            shutil.copyfile(src, dst)
    except Exception as exc:
        logger.debug("keep_safe: could not copy %s: %s", name, exc)


def restore(dst: str, name: str) -> bool:
    """Put a secret back into the program folder when it is missing there. True if restored."""
    if not _active() or os.path.exists(dst):
        return False
    src = os.path.join(keep_dir(), name)
    if not os.path.isfile(src):
        return False
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        logger.warning("keep_safe: %s restored from %s (the program folder had none)", name, keep_dir())
        return True
    except Exception as exc:
        logger.warning("keep_safe: could not restore %s: %s", name, exc)
        return False


def backup_all() -> None:
    """At server start: keep the protected copy up to date."""
    try:
        from services.env_file import env_path
        save(env_path(), "env.backup")
        from services.company_email import _key_path
        save(str(_key_path()), "settings.key")
        pg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secrets", "postgres_password.txt")
        save(pg, "postgres_password.txt")
    except Exception as exc:
        logger.debug("keep_safe: backup_all failed: %s", exc)

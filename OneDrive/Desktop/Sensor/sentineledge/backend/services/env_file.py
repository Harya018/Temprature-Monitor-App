"""
services/env_file.py — change values in the server's settings file (.env.development / .env) from the
Settings page, so nobody has to edit the file by hand.

Only the keys given are changed; every other line (and its order) stays as it is. The file is replaced
atomically, so a crash cannot leave it half written.
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


def env_path() -> str:
    """The settings file the server was started with (SENTINEL_ENV_FILE overrides it, for tests)."""
    override = os.environ.get("SENTINEL_ENV_FILE")
    if override:
        return override
    import config as _cfg
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    p = os.path.join(root, f".env.{_cfg.APP_ENV}")
    return p if os.path.exists(p) else os.path.join(root, ".env")


def _quote(value: str) -> str:
    """Written so python-dotenv reads back exactly the same text (spaces, #, quotes, backslashes)."""
    if value == "" or re.fullmatch(r"[A-Za-z0-9_@.\-+/:]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_values(values: dict, path: Optional[str] = None) -> str:
    """Set KEY=value for every key in `values` (None / '' writes an empty value). Returns the file path."""
    path = path or env_path()
    text = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            text = f.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl) if text else []
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in values:
            lines[i] = f"{m.group(1)}={_quote(str(values[m.group(1)] or ''))}"
            done.add(m.group(1))
    missing = [k for k in values if k not in done]
    if missing:
        while lines and lines[-1] == "":
            lines.pop()
        lines += [f"{k}={_quote(str(values[k] or ''))}" for k in missing]
        lines.append("")
    out = nl.join(lines)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(out)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path

"""
services/reading_csv.py — Append every live sensor reading to a daily CSV table.

Files: sentineledge/data/readings_csv/readings_YYYY-MM-DD.csv
Columns: timestamp, received_at, source, temperature, <one column per parameter>

Parameter columns are the company's configured parameters (company_parameters)
plus any extra value the reading carries, so each parameter has its own column.
If a new parameter appears mid-day, a new part file is started
(readings_YYYY-MM-DD_part2.csv …) with the wider header, so rows never shift
under the wrong column.

Only real (live) readings are written — CSV playback / demo data is not.
Never raises: a CSV problem must not interrupt monitoring.
"""

from __future__ import annotations

import csv
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

CSV_DIR = Path(os.environ["READINGS_CSV_DIR"]) if os.environ.get("READINGS_CSV_DIR") else Path(__file__).resolve().parent.parent.parent / "data" / "readings_csv"

_FIXED = ["timestamp", "received_at", "source", "temperature"]

_lock = threading.Lock()
_state: dict = {}                 # company folder -> {"day", "part", "columns"}
_param_cache: dict = {}           # company_id -> (expires, [names])
_folder_cache: dict = {}          # company_id -> folder name


def _configured_params(company_id) -> list[str]:
    """The company's active parameter names (lower-case, excluding temperature), cached a minute."""
    hit = _param_cache.get(company_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    names: list[str] = []
    try:
        from database.connection import execute_read
        rows = execute_read(
            "SELECT DISTINCT LOWER(name) AS name FROM company_parameters "
            "WHERE is_active = TRUE AND (%s::int IS NULL OR company_id = %s::int) ORDER BY 1",
            (company_id, company_id))
        names = [r["name"] for r in rows if r["name"] and r["name"] != "temperature"]
    except Exception as exc:
        logger.debug("reading_csv: could not load parameters: %s", exc)
    _param_cache[company_id] = (time.monotonic() + 60, names)
    return names


def company_folder(company_id) -> Path:
    """data/readings_csv/<company>/ — each company's tables are kept apart."""
    if company_id is None:
        return CSV_DIR
    name = _folder_cache.get(company_id)
    if name is None:
        slug = ""
        try:
            from database.connection import execute_read
            r = execute_read("SELECT slug FROM companies WHERE id = %s", (company_id,))
            slug = (r[0]["slug"] or "") if r else ""
        except Exception:
            pass
        safe = "".join(ch for ch in slug if ch.isalnum() or ch in "-_")
        name = f"company_{int(company_id)}" + (f"_{safe}" if safe else "")
        _folder_cache[company_id] = name
    return CSV_DIR / name


def _path(folder: Path, day: str, part: int) -> Path:
    suffix = "" if part == 1 else f"_part{part}"
    return folder / f"readings_{day}{suffix}.csv"


def _existing_header(path: Path) -> list[str] | None:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            return next(csv.reader(f), None)
    except FileNotFoundError:
        return None


def append_reading(timestamp: str, temperature, params: dict | None, source: str, company_id=None) -> None:
    """Append one reading to the company's own daily table. `params` maps parameter -> value."""
    try:
        values = {str(k).lower(): v for k, v in (params or {}).items() if v is not None}
        values.pop("temperature", None)
        wanted = sorted(set(_configured_params(company_id)) | set(values))
        received = datetime.now(timezone.utc).isoformat(timespec="seconds")
        day = datetime.now().strftime("%Y-%m-%d")   # local day, matches the plant's clock
        folder = company_folder(company_id)
        key = str(folder)

        with _lock:
            folder.mkdir(parents=True, exist_ok=True)
            st = _state.setdefault(key, {"day": None, "part": 1, "columns": None})

            if st["day"] != day:
                # New day (or first write since start): continue today's latest part file
                part = 1
                while _path(folder, day, part + 1).exists():
                    part += 1
                st.update(day=day, part=part, columns=_existing_header(_path(folder, day, part)))

            cols = st["columns"]
            if cols is not None and not set(_FIXED + wanted) <= set(cols):
                st["part"] += 1          # a parameter appeared that this file has no column for
                cols = None

            path = _path(folder, day, st["part"])
            if cols is None:
                cols = _FIXED + wanted
                st["columns"] = cols
                write_header = not path.exists() or path.stat().st_size == 0
            else:
                write_header = False

            row = {"timestamp": timestamp, "received_at": received, "source": source,
                   "temperature": "" if temperature is None else temperature, **values}
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                if write_header:
                    w.writeheader()
                w.writerow(row)
    except Exception as exc:
        logger.warning("reading_csv: could not append reading: %s", exc)

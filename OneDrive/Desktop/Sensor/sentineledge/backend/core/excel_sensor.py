"""
core/excel_sensor.py — Pro-face Pro-Server EX live data reader.

Reads the CSV or Excel file that Pro-Server EX writes to and feeds the
latest row into the SentinelEdge sensor pipeline in real time.

Pro-Server EX output format
---------------------------
CSV (most common):
    Date,Time,Temperature,pH,DO,...
    26/08/19,14:32:05,87.30,7.21,6.40,...

Excel (.xlsx):
    Same column layout, one data row per second appended to the sheet.

Column mapping (case-insensitive, configurable via admin Settings page)
-----------------------------------------------------------------------
  EXCEL_DATE_COL    (default "Date")        → combined into timestamp
  EXCEL_TIME_COL    (default "Time")        → combined into timestamp
  EXCEL_TEMP_COL    (default "Temperature") → current_temperature
  Everything else   (pH, DO, …)             → extra_readings[col_name]

If your software outputs a single combined timestamp column, set
  EXCEL_TIMESTAMP_COL=<header name>  and leave DATE/TIME cols blank.

Settings can be changed at runtime via Admin → Settings → Pro-Server EX
without restarting the server.  env vars are the startup default; DB
values saved through the UI override them via reload_settings().
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger
from utils.time import now_iso

logger = get_logger("sentineledge.excel_sensor")

# ── Configuration (mutable — updated by reload_settings) ──────────────────────
EXCEL_FILE_PATH     : str   = os.environ.get("EXCEL_FILE_PATH",     "").strip()
EXCEL_TEMP_COL      : str   = os.environ.get("EXCEL_TEMP_COL",      "Temperature").strip()
EXCEL_TIMESTAMP_COL : str   = os.environ.get("EXCEL_TIMESTAMP_COL", "").strip()
EXCEL_DATE_COL      : str   = os.environ.get("EXCEL_DATE_COL",      "Date").strip()
EXCEL_TIME_COL      : str   = os.environ.get("EXCEL_TIME_COL",      "Time").strip()
EXCEL_SHEET         : str   = os.environ.get("EXCEL_SHEET",         "0").strip()
EXCEL_POLL_INTERVAL : float = float(os.environ.get("EXCEL_POLL_INTERVAL", "1.0"))
EXCEL_ENCODING      : str   = os.environ.get("EXCEL_ENCODING",      "").strip()

# Encoding candidates tried in order when EXCEL_ENCODING is not forced.
_ENCODINGS = ["utf-8-sig", "utf-8", "shift-jis", "cp932", "latin-1"]

# ── Shared state (written by background thread, read by main.py) ──────────────
current_temperature : Optional[float]  = None
current_timestamp   : str              = ""
extra_readings      : Dict[str, float] = {}

# ── Internal state ────────────────────────────────────────────────────────────
_last_mtime     : float = 0.0
_last_file_size : int   = 0
_last_row_sig   : str   = ""
_active         : bool  = False

# ── Thread control ─────────────────────────────────────────────────────────────
_stop_evt   : threading.Event            = threading.Event()
_thread_ref : Optional[threading.Thread] = None


def is_active() -> bool:
    """True when EXCEL_FILE_PATH is configured and the file currently exists."""
    return _active


# ═══════════════════════════════════════════════════════════════════════════════
# Encoding helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _encodings() -> List[str]:
    """Return the list of encodings to try, forced encoding first if set."""
    if EXCEL_ENCODING:
        return [EXCEL_ENCODING] + [e for e in _ENCODINGS if e != EXCEL_ENCODING]
    return _ENCODINGS


# ═══════════════════════════════════════════════════════════════════════════════
# CSV reader
# ═══════════════════════════════════════════════════════════════════════════════

def _read_csv(filepath: str) -> Optional[Dict[str, str]]:
    """
    Read the last non-empty data row from a CSV file.

    Returns a dict of {column_header: raw_string_value} or None.
    Tries multiple encodings and auto-detects the delimiter (comma or semicolon).
    Safe to call while Pro-Server EX is appending to the file — reads a
    snapshot by loading the entire file into memory first.
    """
    raw_bytes: Optional[bytes] = None

    # ── Read raw bytes (snapshot avoids mid-write corruption) ─────────────────
    try:
        with open(filepath, "rb") as f:
            raw_bytes = f.read()
    except PermissionError:
        # File exclusively locked — try a temp copy
        try:
            fd, tmp = tempfile.mkstemp(suffix=".csv")
            os.close(fd)
            shutil.copy2(filepath, tmp)
            with open(tmp, "rb") as f:
                raw_bytes = f.read()
            os.unlink(tmp)
        except Exception as exc:
            logger.debug("CSV: locked + copy failed: %s", exc)
            return None
    except Exception as exc:
        logger.debug("CSV: read error: %s", exc)
        return None

    if not raw_bytes:
        return None

    # ── Try each encoding ─────────────────────────────────────────────────────
    for enc in _encodings():
        try:
            text = raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

        try:
            # Auto-detect delimiter from first line
            first_line = text.split("\n")[0] if "\n" in text else text
            try:
                dialect = csv.Sniffer().sniff(first_line, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel  # default to comma

            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            rows   = list(reader)

            if not rows:
                return None

            # Strip whitespace from keys and values; skip empty rows
            cleaned = []
            for row in rows:
                r = {k.strip(): v.strip() for k, v in row.items() if k}
                if any(v for v in r.values()):
                    cleaned.append(r)

            if not cleaned:
                return None

            if not _active:
                logger.info(
                    "Pro-Server EX CSV detected. Columns: %s",
                    list(cleaned[0].keys()),
                )

            return cleaned[-1]   # last non-empty row

        except Exception as exc:
            logger.debug("CSV parse error with %s: %s", enc, exc)
            continue

    logger.warning("CSV: could not decode %s with any known encoding", filepath)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Excel (.xlsx / .xls) reader
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_xlsx_copy(src: str) -> Tuple[Optional[str], str]:
    """
    Copy the xlsx file to a temp location to avoid Windows lock conflicts.
    Returns (tmp_path, read_path_to_use).
    """
    try:
        fd, tmp = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        shutil.copy2(src, tmp)
        return tmp, tmp
    except Exception as exc:
        logger.debug("XLSX copy failed (%s) — reading original", exc)
        return None, src


def _read_xlsx(filepath: str) -> Optional[Dict[str, object]]:
    """
    Read the last non-empty data row from an xlsx file.
    Returns a dict of {column_header: cell_value} or None.
    """
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl not installed — run: pip install openpyxl==3.1.2")
        return None

    tmp_path, read_path = _safe_xlsx_copy(filepath)
    wb = None
    try:
        wb = openpyxl.load_workbook(read_path, read_only=True, data_only=True)

        # Resolve sheet
        ref = EXCEL_SHEET
        if ref.isdigit() and int(ref) < len(wb.worksheets):
            ws = wb.worksheets[int(ref)]
        elif ref in wb.sheetnames:
            ws = wb[ref]
        else:
            ws = wb.active

        # Headers from row 1
        raw_hdr = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not raw_hdr:
            return None
        headers = [
            str(h).strip() if h is not None else f"col_{i}"
            for i, h in enumerate(raw_hdr)
        ]

        # Last non-empty data row
        last_row: Optional[tuple] = None
        max_r = ws.max_row

        if max_r and max_r > 1:
            candidate = next(
                ws.iter_rows(min_row=max_r, max_row=max_r, values_only=True), None
            )
            if candidate and any(v is not None for v in candidate):
                last_row = candidate

        if last_row is None:
            for row in ws.iter_rows(min_row=2, values_only=True):
                if any(v is not None for v in row):
                    last_row = row

        if last_row is None:
            return None

        n = min(len(headers), len(last_row))
        if not _active:
            logger.info("Pro-Server EX XLSX detected. Columns: %s", headers)

        return {headers[i]: last_row[i] for i in range(n)}

    except Exception as exc:
        logger.warning("XLSX read error: %s", exc)
        return None
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# Value parsers
# ═══════════════════════════════════════════════════════════════════════════════

def _to_float(value) -> Optional[float]:
    """Convert any cell value to float; return None if not numeric."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_proserver_datetime(date_raw, time_raw) -> str:
    """
    Parse Pro-Server EX's separate Date + Time cells into an ISO string.

    Date formats seen in the wild:
      yy/mm/dd   → 26/08/19   (Pro-Server EX default)
      dd/mm/yy   → 19/08/26
      yyyy/mm/dd → 2026/08/19
      mm/dd/yy   → 08/19/26

    Time format is always hh:mm:ss (or hh:mm:ss.000 for 100 ms sampling).
    openpyxl returns Python datetime/date/time objects for formatted cells.
    """
    import datetime as _dt

    if isinstance(date_raw, (_dt.datetime, _dt.date)):
        d = date_raw.date() if isinstance(date_raw, _dt.datetime) else date_raw
        if isinstance(time_raw, _dt.time):
            return _dt.datetime.combine(d, time_raw).isoformat()
        return d.isoformat()

    date_s = str(date_raw).strip() if date_raw is not None else ""
    time_s = str(time_raw).strip() if time_raw is not None else ""

    if not date_s and not time_s:
        return now_iso()

    _date_formats = [
        "%y/%m/%d", "%d/%m/%y", "%Y/%m/%d",
        "%m/%d/%y", "%y-%m-%d", "%Y-%m-%d",
        "%d-%m-%Y", "%m/%d/%Y",
    ]
    parsed_date: Optional[_dt.date] = None
    for fmt in _date_formats:
        try:
            parsed_date = _dt.datetime.strptime(date_s, fmt).date()
            break
        except ValueError:
            continue

    parsed_time: Optional[_dt.time] = None
    for fmt in ("%H:%M:%S.%f", "%H:%M:%S", "%H:%M"):
        try:
            parsed_time = _dt.datetime.strptime(time_s, fmt).time()
            break
        except ValueError:
            continue

    if parsed_date and parsed_time:
        return _dt.datetime.combine(parsed_date, parsed_time).isoformat()
    if parsed_date:
        return parsed_date.isoformat()

    combined = f"{date_s} {time_s}".strip()
    return combined if combined else now_iso()


def _extract_single_timestamp(value) -> str:
    """Parse a single combined timestamp cell (when EXCEL_TIMESTAMP_COL is set)."""
    import datetime as _dt
    if value is None:
        return now_iso()
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    s = str(value).strip()
    return s if s else now_iso()


# ═══════════════════════════════════════════════════════════════════════════════
# Column matching (case-insensitive)
# ═══════════════════════════════════════════════════════════════════════════════

def _col_match(header: str, target: str) -> bool:
    """Case-insensitive column header comparison."""
    return header.strip().lower() == target.strip().lower()


def _is_skip_col(header: str) -> bool:
    """True if this column should not go into extra_readings."""
    h = header.strip().lower()
    skip = {
        EXCEL_TEMP_COL.lower(),
        EXCEL_DATE_COL.lower(),
        EXCEL_TIME_COL.lower(),
        EXCEL_TIMESTAMP_COL.lower(),
    }
    return h in skip


# ═══════════════════════════════════════════════════════════════════════════════
# Main dispatcher — picks CSV or Excel based on file extension
# ═══════════════════════════════════════════════════════════════════════════════

def _read_latest_row() -> Optional[Dict]:
    """
    Dispatch to the correct reader based on file extension.
    Returns {column_header: raw_value} or None.
    """
    ext = Path(EXCEL_FILE_PATH).suffix.lower()
    if ext in (".xls", ".xlsx"):
        return _read_xlsx(EXCEL_FILE_PATH)
    else:
        return _read_csv(EXCEL_FILE_PATH)


# ═══════════════════════════════════════════════════════════════════════════════
# Value routing — maps a row dict to shared state
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_row(row: Dict) -> None:
    """
    Route each column in `row` to the correct shared variable:
      - temperature column  → current_temperature
      - date + time columns → current_timestamp
      - everything else     → extra_readings[col_name]
    """
    global current_temperature, current_timestamp

    new_extras: Dict[str, float] = {}

    # ── Timestamp ─────────────────────────────────────────────────────────────
    if EXCEL_TIMESTAMP_COL:
        ts_val = next(
            (v for k, v in row.items() if _col_match(k, EXCEL_TIMESTAMP_COL)), None
        )
        current_timestamp = _extract_single_timestamp(ts_val)
    else:
        date_val = next(
            (v for k, v in row.items() if _col_match(k, EXCEL_DATE_COL)), None
        )
        time_val = next(
            (v for k, v in row.items() if _col_match(k, EXCEL_TIME_COL)), None
        )
        current_timestamp = _parse_proserver_datetime(date_val, time_val)

    # ── Sensor columns ────────────────────────────────────────────────────────
    for col_header, raw_value in row.items():

        if _col_match(col_header, EXCEL_TEMP_COL):
            val = _to_float(raw_value)
            if val is not None:
                current_temperature = round(val, 3)
            continue

        if _is_skip_col(col_header):
            continue

        val = _to_float(raw_value)
        if val is not None:
            new_extras[col_header] = round(val, 3)

    extra_readings.clear()
    extra_readings.update(new_extras)


# ═══════════════════════════════════════════════════════════════════════════════
# Background polling thread
# ═══════════════════════════════════════════════════════════════════════════════

def _poll_loop() -> None:
    """
    Daemon thread: checks the file every EXCEL_POLL_INTERVAL seconds.
    Reads EXCEL_FILE_PATH dynamically each iteration so reload_settings()
    changes are picked up without restarting the process.
    Exits cleanly when _stop_evt is set by reload_settings().
    """
    global _last_mtime, _last_file_size, _last_row_sig, _active

    logger.info(
        "Pro-Server EX reader started: '%s' every %.1f s",
        EXCEL_FILE_PATH, EXCEL_POLL_INTERVAL,
    )

    while not _stop_evt.is_set():
        try:
            fp_str = EXCEL_FILE_PATH   # read module global each iteration
            if not fp_str:
                _stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            file_path = Path(fp_str)

            # ── File existence check ──────────────────────────────────────────
            if not file_path.exists():
                if _active:
                    logger.warning(
                        "Pro-Server EX file disappeared: %s — waiting",
                        file_path,
                    )
                    _active = False
                _stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            stat      = file_path.stat()
            mtime     = stat.st_mtime
            file_size = stat.st_size

            # ── Skip if nothing changed ───────────────────────────────────────
            if mtime == _last_mtime and file_size == _last_file_size:
                _active = True
                _stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            _last_mtime     = mtime
            _last_file_size = file_size
            _active         = True

            # ── Read latest row ───────────────────────────────────────────────
            row = _read_latest_row()
            if row is None:
                _stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            # ── Duplicate suppression ─────────────────────────────────────────
            sig = "|".join(str(v) for v in row.values())
            if sig == _last_row_sig:
                _stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue
            _last_row_sig = sig

            # ── Route values to shared state ──────────────────────────────────
            _apply_row(row)

            logger.debug(
                "ProFace | T=%.3f  ts=%s  extras=%s",
                current_temperature or 0.0,
                current_timestamp,
                extra_readings,
            )

        except Exception as exc:
            logger.warning("Pro-Server EX reader error: %s", exc)

        _stop_evt.wait(EXCEL_POLL_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════════
# Hot-reload — called by admin API after saving settings in the UI
# ═══════════════════════════════════════════════════════════════════════════════

def reload_settings(db_values: Dict[str, str]) -> None:
    """
    Apply new settings from db_values and restart the polling thread.

    db_values keys: file_path, temp_col, date_col, time_col,
                    timestamp_col, sheet, poll_interval, encoding
    Missing or empty keys keep their current value (env var defaults).
    Called by POST /api/admin/proserver/settings after saving to DB.
    """
    global EXCEL_FILE_PATH, EXCEL_TEMP_COL, EXCEL_TIMESTAMP_COL, EXCEL_DATE_COL
    global EXCEL_TIME_COL, EXCEL_SHEET, EXCEL_POLL_INTERVAL, EXCEL_ENCODING
    global current_temperature, current_timestamp, extra_readings
    global _last_mtime, _last_file_size, _last_row_sig, _active
    global _stop_evt, _thread_ref

    def _s(key: str, default: str = "") -> str:
        v = db_values.get(key)
        return str(v).strip() if v is not None else default

    EXCEL_FILE_PATH     = _s("file_path")
    EXCEL_TEMP_COL      = _s("temp_col",      "Temperature")
    EXCEL_DATE_COL      = _s("date_col",       "Date")
    EXCEL_TIME_COL      = _s("time_col",       "Time")
    EXCEL_TIMESTAMP_COL = _s("timestamp_col",  "")
    EXCEL_SHEET         = _s("sheet",          "0")
    EXCEL_ENCODING      = _s("encoding",       "")
    try:
        EXCEL_POLL_INTERVAL = float(db_values.get("poll_interval") or 1.0)
    except (ValueError, TypeError):
        EXCEL_POLL_INTERVAL = 1.0

    # Signal old thread to exit
    _stop_evt.set()
    if _thread_ref and _thread_ref.is_alive():
        _thread_ref.join(timeout=5.0)

    # Reset shared state
    current_temperature = None
    current_timestamp   = ""
    extra_readings      = {}
    _last_mtime         = 0.0
    _last_file_size     = 0
    _last_row_sig       = ""
    _active             = False

    # New stop event for the new thread
    _stop_evt = threading.Event()

    if EXCEL_FILE_PATH:
        _thread_ref = threading.Thread(
            target=_poll_loop,
            daemon=True,
            name="proserver-reader",
        )
        _thread_ref.start()
        logger.info("Pro-Server EX reader restarted: %s", EXCEL_FILE_PATH)
    else:
        _thread_ref = None
        logger.info("Pro-Server EX reader stopped (no file path configured)")


# ═══════════════════════════════════════════════════════════════════════════════
# Auto-start (only when EXCEL_FILE_PATH is configured via env var)
# ═══════════════════════════════════════════════════════════════════════════════

if EXCEL_FILE_PATH:
    _thread_ref = threading.Thread(
        target=_poll_loop,
        daemon=True,
        name="proserver-reader",
    )
    _thread_ref.start()
else:
    logger.debug("Pro-Server EX reader: EXCEL_FILE_PATH not set — inactive (configure via Admin → Settings)")

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

print("EXCEL_SENSOR LOADED FROM:", __file__)

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
EXCEL_TEMP_COL      : str   = os.environ.get("EXCEL_TEMP_COL",      "TEMPERATURE").strip()
EXCEL_TIMESTAMP_COL : str   = os.environ.get("EXCEL_TIMESTAMP_COL", "").strip()
EXCEL_DATE_COL      : str   = os.environ.get("EXCEL_DATE_COL",      "DATE/TIME").strip()
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
# True = replaying historical rows → alerts suppressed in main.py
# False = new live rows → alerts fire normally
_in_loop_mode   : bool  = True

# User-controlled: when False, playback stops and only the watchdog runs.
# The watchdog checks every poll cycle for new rows whose timestamp is recent
# (within LIVE_STALE_SECONDS of now), then temporarily serves those live rows
# without looping historical data.  Alerts fire only for live rows.
_excel_enabled   : bool  = True
_auto_save_enabled: bool  = False   # auto-save .xls via COM every 5 s

AUTO_SAVE_INTERVAL: int = 5    # seconds between COM force-saves
REPLAY_WINDOW     : int = 20   # rows cycled when idle (no new live data)
LIVE_STALE_SECONDS: int = 300  # rows timestamped within 5 min of now = live

# ── Thread control ─────────────────────────────────────────────────────────────
_stop_evt   : threading.Event            = threading.Event()
_thread_ref : Optional[threading.Thread] = None


def is_live_data() -> bool:
    """True when the background thread is serving newly-written rows (alerts fire).
    False during the idle loop through the last REPLAY_WINDOW rows (alerts suppressed)."""
    return not _in_loop_mode


def is_active() -> bool:
    """True when EXCEL_FILE_PATH is configured and the file currently exists."""
    return _active


def set_enabled(enabled: bool) -> None:
    """
    Enable or disable Excel reading and persist the choice to DB.
    Enabled  = normal loop + live detection.
    Disabled = live-only mode: show NULL when no recent data, show live when present.
    Survives server restarts (stored in app_settings).
    """
    global _excel_enabled
    _excel_enabled = enabled
    try:
        from database.connection import execute_write
        execute_write(
            "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("proserver_live_only", "0" if enabled else "1"),
        )
    except Exception as exc:
        logger.warning("Could not persist proserver_live_only setting: %s", exc)
    logger.info(
        "Pro-Server EX reading %s by user — persisted to DB",
        "ENABLED (loop+live)" if enabled else "DISABLED (live-only, NULL when idle)",
    )


def load_persistent_settings() -> None:
    """Load persisted enable/disable state and auto-save flag from DB — called at startup."""
    global _excel_enabled, _auto_save_enabled
    try:
        from database.connection import execute_read
        rows = execute_read(
            "SELECT key, value FROM app_settings WHERE key IN ('proserver_live_only', 'proserver_auto_save')",
        )
        for row in (rows or []):
            if row["key"] == "proserver_live_only" and row["value"] == "1":
                _excel_enabled = False
                logger.info("Pro-Server EX: loaded live-only mode (disabled loop) from DB")
            elif row["key"] == "proserver_auto_save" and row["value"] == "1":
                _auto_save_enabled = True
                logger.info("Pro-Server EX: auto-save enabled from DB")
    except Exception as exc:
        logger.debug("Could not load proserver persistent settings from DB: %s", exc)


def set_auto_save(enabled: bool) -> None:
    """Enable or disable COM auto-save and persist to DB."""
    global _auto_save_enabled
    _auto_save_enabled = enabled
    try:
        from database.connection import execute_write
        execute_write(
            "INSERT INTO app_settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("proserver_auto_save", "1" if enabled else "0"),
        )
    except Exception as exc:
        logger.warning("Could not persist proserver_auto_save setting: %s", exc)


def get_enabled_status() -> dict:
    return {
        "enabled":             _excel_enabled,
        "auto_save":           _auto_save_enabled,
        "is_active":           _active,
        "in_loop_mode":        _in_loop_mode,
        "current_temperature": current_temperature,
        "current_timestamp":   current_timestamp,
    }


def get_diagnostic() -> dict:
    """
    Return a diagnostic snapshot: file existence, raw columns, column matching,
    and current reading state — to help debug why temperature is not showing.
    """
    fp = EXCEL_FILE_PATH
    if not fp:
        return {
            "status": "no_path",
            "message": "No file path configured — go to Settings → Pro-Server EX and set the file path.",
            "file_path": "",
        }

    from pathlib import Path as _Path
    p = _Path(fp)
    if not p.exists():
        return {
            "status": "file_not_found",
            "message": f"File not found on disk: {fp}",
            "file_path": fp,
        }

    # Try to read the last row fresh from disk/COM
    try:
        row = _read_latest_row()
    except Exception as exc:
        row = None
        read_error = str(exc)
    else:
        read_error = None

    if row is None:
        return {
            "status": "read_failed",
            "message": read_error or "Could not read any rows from the file.",
            "file_path": fp,
            "configured_temp_col": EXCEL_TEMP_COL,
        }

    raw_cols = list(row.keys())
    # Find which column matched temperature
    temp_col_match = next((k for k in row if _col_match(k, EXCEL_TEMP_COL)), None)
    temp_raw       = row.get(temp_col_match) if temp_col_match else None
    temp_float     = _to_float(temp_raw) if temp_raw is not None else None

    return {
        "status":              "ok",
        "file_path":           fp,
        "file_exists":         True,
        "columns_in_file":     raw_cols,
        "configured_temp_col": EXCEL_TEMP_COL,
        "temp_col_matched":    temp_col_match,
        "temp_raw_value":      str(temp_raw) if temp_raw is not None else None,
        "temp_float":          temp_float,
        "current_temperature": current_temperature,
        "is_active":           _active,
        "in_loop_mode":        _in_loop_mode,
        "last_timestamp":      current_timestamp,
        "last_row_preview":    {k: str(v) for k, v in list(row.items())[:8]},
    }


def _clear_readings() -> None:
    """Set all shared readings to None — signals 'no live data' to main.py."""
    global current_temperature, current_timestamp
    current_temperature = None
    current_timestamp   = ""
    extra_readings.clear()


def _com_read_last_row() -> Optional[Dict[str, object]]:
    """
    Read only the LAST written row from the running Excel COM session.
    This is the key detection method for Pro-Server EX live-only mode:
    - Attaches to the running Excel process via GetObject (no file save needed)
    - Finds the current write position via End(XL_UP) + UsedRange
    - Returns just that one row as a dict
    Returns None if COM is unavailable or Excel is not open.
    """
    if not EXCEL_FILE_PATH or Path(EXCEL_FILE_PATH).suffix.lower() != ".xls":
        return None
    try:
        import win32com.client
        import pythoncom
        import datetime as _dt
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            abs_path  = os.path.abspath(EXCEL_FILE_PATH)
            wb        = win32com.client.GetObject(abs_path)
            ws        = wb.Sheets(1)
            XL_UP     = -4162
            last_row  = max(
                ws.Cells(ws.Rows.Count, 2).End(XL_UP).Row,
                ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1,
            )
            used_cols = ws.UsedRange.Columns.Count

            # Find header row (first row with string text values)
            header_row = 2
            for r in range(1, min(11, last_row + 1)):
                if any(
                    isinstance(ws.Cells(r, c).Value, str)
                    and str(ws.Cells(r, c).Value).strip()
                    for c in range(1, used_cols + 1)
                ):
                    header_row = r
                    break

            if last_row <= header_row:
                return None

            headers = [
                str(ws.Cells(header_row, c).Value or "").strip() or f"col_{c - 1}"
                for c in range(1, used_cols + 1)
            ]

            # Read the entire last row in a single COM round-trip
            rng = ws.Range(ws.Cells(last_row, 1), ws.Cells(last_row, used_cols))
            raw = rng.Value
            if raw is None:
                return None
            # A single-row range returns a flat tuple in win32com
            vals = raw if not isinstance(raw[0], (list, tuple)) else raw[0]

            row_dict: Dict[str, object] = {}
            for i, header in enumerate(headers):
                val = vals[i] if i < len(vals) else None
                if hasattr(val, "year") and hasattr(val, "hour"):
                    try:
                        val = _dt.datetime(
                            val.year, val.month, val.day,
                            val.hour, val.minute, val.second,
                        )
                    except Exception:
                        pass
                row_dict[header] = val
            return row_dict

        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    except Exception:
        return None


def _com_force_save() -> bool:
    """
    Force-save the Excel workbook via COM so Pro-Server EX data is flushed to disk.
    This makes the on-disk .xls reflect in-memory rows, allowing xlrd to read them
    without waiting for Pro-Server EX to trigger its own save.
    Returns True on success, False if COM is unavailable or the file is not .xls.
    """
    if not EXCEL_FILE_PATH or Path(EXCEL_FILE_PATH).suffix.lower() != ".xls":
        return False
    try:
        import win32com.client
        import pythoncom
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            abs_path = os.path.abspath(EXCEL_FILE_PATH)
            wb = win32com.client.GetObject(abs_path)
            wb.Save()
            logger.debug("Pro-Server EX: auto-saved workbook via COM")
            return True
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("COM auto-save failed: %s", exc)
        return False


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

def _read_csv(filepath: str, row_idx: Optional[int] = None) -> Optional[Dict[str, str]]:
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

            if row_idx is not None:
                if row_idx >= len(cleaned):
                    return None
                return cleaned[row_idx]
            return cleaned[-1]   # last non-empty row (live mode)

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


def _read_xlsx(filepath: str, row_idx: Optional[int] = None) -> Optional[Dict[str, object]]:
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

        if not _active:
            logger.info("Pro-Server EX XLSX detected. Columns: %s", headers)

        if row_idx is not None:
            # Playback: specific data row (2-indexed in sheet, row 1 = headers)
            target_sheet_row = 2 + row_idx
            if target_sheet_row > (max_r or 1):
                return None
            last_row = next(ws.iter_rows(min_row=target_sheet_row, max_row=target_sheet_row, values_only=True), None)
            if last_row is None or not any(v is not None for v in last_row):
                return None

        n = min(len(headers), len(last_row))
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

    if isinstance(date_raw, _dt.datetime):
        # Full datetime from xlrd (combined DATE/TIME cell) — preserve the time part
        if isinstance(time_raw, _dt.time):
            return _dt.datetime.combine(date_raw.date(), time_raw).isoformat()
        return date_raw.isoformat()
    if isinstance(date_raw, _dt.date):
        if isinstance(time_raw, _dt.time):
            return _dt.datetime.combine(date_raw, time_raw).isoformat()
        return date_raw.isoformat()

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

def _read_latest_row(row_idx: Optional[int] = None) -> Optional[Dict]:
    """
    Dispatch to the correct reader based on file extension.
    row_idx=None  → read last row (live mode)
    row_idx=int   → read that specific data row, 0-indexed from first data row
                    returns None when index is past end of file (caller loops back)
    """
    ext = Path(EXCEL_FILE_PATH).suffix.lower()
    if ext == ".xlsx":
        return _read_xlsx(EXCEL_FILE_PATH, row_idx=row_idx)
    elif ext == ".xls":
        return _read_xls(EXCEL_FILE_PATH, row_idx=row_idx)
    else:
        return _read_csv(EXCEL_FILE_PATH, row_idx=row_idx)


# ═══════════════════════════════════════════════════════════════════════════════
# Legacy Excel (.xls) reader — xlrd only, openpyxl cannot open .xls files
# ═══════════════════════════════════════════════════════════════════════════════

def _read_xls(filepath: str, row_idx: Optional[int] = None) -> Optional[Dict[str, object]]:
    """
    Read the last non-empty data row from a legacy .xls file using xlrd.
    Pro-Server EX on older Windows systems often saves in .xls format.
    Uses a temp-copy to handle Windows file locking (same as xlsx reader).
    """
    try:
        import xlrd
    except ImportError:
        logger.error("xlrd not installed — run: pip install xlrd==2.0.1")
        return None

    # Copy to temp file to avoid Windows lock conflicts
    tmp_path: Optional[str] = None
    read_path = filepath
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".xls")
        os.close(fd)
        shutil.copy2(filepath, tmp_path)
        read_path = tmp_path
    except Exception as exc:
        logger.debug("XLS copy failed (%s) — reading original", exc)
        tmp_path = None

    try:
        wb = xlrd.open_workbook(read_path)

        # Resolve sheet (index or name, same logic as xlsx reader)
        ref = EXCEL_SHEET
        if ref.isdigit() and int(ref) < wb.nsheets:
            ws = wb.sheet_by_index(int(ref))
        else:
            try:
                ws = wb.sheet_by_name(ref)
            except Exception:
                ws = wb.sheet_by_index(0)

        if ws.nrows < 2:
            return None

        # Auto-detect header row: Pro-Server EX often puts a title/blank row first.
        # Scan the first 10 rows for the first one that has actual text cell values.
        # xlrd ctype: 0=EMPTY, 1=TEXT, 2=NUMBER, 3=DATE, 4=BOOL, 5=ERROR
        header_row_idx = 0
        for r in range(min(ws.nrows, 10)):
            if any(
                ws.cell(r, c).ctype == 1 and str(ws.cell_value(r, c)).strip()
                for c in range(ws.ncols)
            ):
                header_row_idx = r
                break

        # Must have at least one data row after the header
        if ws.nrows <= header_row_idx + 1:
            return None

        headers = [
            str(ws.cell_value(header_row_idx, c)).strip() or f"col_{c}"
            for c in range(ws.ncols)
        ]

        if not _active:
            logger.info("Pro-Server EX XLS detected. Columns: %s", headers)

        # Resolve which sheet row to read
        if row_idx is not None:
            # Playback mode: specific data row (0-indexed from first data row)
            target = header_row_idx + 1 + row_idx
            if target >= ws.nrows:
                return None  # past end of file — caller resets to row 0
            last_row_idx = target
        else:
            # Live mode: find last non-empty data row (scan from bottom)
            last_row_idx = None
            for r in range(ws.nrows - 1, header_row_idx, -1):
                if any(ws.cell(r, c).ctype not in (0, 5) for c in range(ws.ncols)):
                    last_row_idx = r
                    break
            if last_row_idx is None:
                return None

        import datetime as _dt
        row_data: Dict[str, object] = {}
        for c, header in enumerate(headers):
            cell = ws.cell(last_row_idx, c)
            val = cell.value
            if cell.ctype == 3:
                try:
                    val = xlrd.xldate_as_datetime(val, wb.datemode)
                except Exception:
                    pass
            row_data[header] = val

        return row_data

    except Exception as exc:
        logger.warning("XLS read error: %s", exc)
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


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
    import datetime as _dt
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
        # Auto-detect: if the configured date column didn't match any header
        # (e.g. DB has "Date" but XLS has "DATE/TIME"), scan for any cell that
        # xlrd already converted to a Python datetime/date object.
        if date_val is None and time_val is None:
            for v in row.values():
                if isinstance(v, (_dt.datetime, _dt.date)):
                    date_val = v
                    break
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

    if new_extras:
        extra_readings.clear()
        extra_readings.update(new_extras)
    # if new_extras is empty (live row with blank PH/PRESSURE cells),
    # keep the previous values so the dashboard doesn't blank out


# ═══════════════════════════════════════════════════════════════════════════════
# Bulk row loader — reads ALL data rows at once for playback
# ═══════════════════════════════════════════════════════════════════════════════

def _load_all_rows() -> List[Dict]:
    """
    Read every data row from the configured file into a list of dicts.
    Called once when the file is detected as static so playback can step
    through the full history without relying on per-call row indexing.

    Falls back to the single-row reader when bulk loaders return nothing.
    This handles XLS files where COM and BIFF parsing both fail but
    xlrd direct-read still works (e.g. when Excel is not running).
    """
    ext = Path(EXCEL_FILE_PATH).suffix.lower()
    if ext == ".xlsx":
        rows = _load_all_xlsx(EXCEL_FILE_PATH)
    elif ext == ".xls":
        rows = _load_all_xls(EXCEL_FILE_PATH)
    else:
        rows = _load_all_csv(EXCEL_FILE_PATH)

    if not rows:
        # All bulk loaders returned empty — try the single-row reader as a fallback.
        # This succeeds when xlrd can read the file directly even though COM/BIFF
        # parsing failed (e.g. Excel is not open, file has no ring-buffer blocks).
        row = _read_latest_row()
        if row:
            logger.info(
                "ProFace | Bulk load returned 0 rows — seeding cache from single-row reader"
            )
            rows = [row]

    return rows


def _load_all_xls(filepath: str) -> List[Dict[str, object]]:
    """
    Load all rows from a Pro-Server EX .xls file.

    WHY WE RUN MULTIPLE READERS AND PICK THE MAX:
    Pro-Server EX uses a "not-clear, restart" ring-buffer: when the configured
    row range fills (e.g. 9000 rows), it wraps back to row 1 and writes new rows
    there — BUT it updates DIMENSIONS.rwMac to the current ring-buffer position
    (e.g. 18), not the physical row count.

      • Excel 2003 (other laptop)  → lenient BIFF8 parser; scans ALL physical
                                     CELL records → sees all 9000+ rows ✓
      • Excel 2016+ (new Excel)    → strict parser; trusts DIMENSIONS.rwMac = 18
                                     → stops at row 18 ✗
      • COM (UsedRange / End(XL_UP)) → also DIMENSIONS-limited → returns 18-19 ✗
      • xlrd                       → reads ALL physical ROW/CELL records, ignores
                                     DIMENSIONS → sees all 9000+ rows ✓

    Strategy: run COM and xlrd in parallel; return whichever found MORE rows.
    COM wins ties (it reads the live Excel session when Pro-Server EX is running).
    VBS is the fallback when both COM and xlrd return 0.
    """
    com_rows  = _load_all_xls_com(filepath)
    xlrd_rows = _load_all_xls_xlrd(filepath)

    com_count  = len(com_rows)
    xlrd_count = len(xlrd_rows)

    if com_count > 0 or xlrd_count > 0:
        if com_count != xlrd_count:
            logger.info(
                "ProFace | XLS row counts — COM: %d, xlrd: %d — using %s (%d rows). "
                "%s",
                com_count, xlrd_count,
                "COM" if com_count >= xlrd_count else "xlrd",
                max(com_count, xlrd_count),
                "Ring-buffer detected: xlrd sees physical rows beyond DIMENSIONS limit."
                if xlrd_count > com_count else
                "COM attached to running Excel session (live data)."
                if com_count > xlrd_count else "",
            )
        # xlrd wins when it sees more rows (ring-buffer / DIMENSIONS mismatch).
        # COM wins on ties (it may have the live in-memory session).
        if xlrd_count > com_count:
            return xlrd_rows
        return com_rows

    # Both returned 0 — try PowerShell COM as a last resort
    vbs_rows = _load_all_xls_vbs(filepath)
    if vbs_rows:
        logger.info("ProFace | XLS PS load: %d rows (COM and xlrd both returned 0)", len(vbs_rows))
        return vbs_rows

    logger.warning("ProFace | All XLS readers returned 0 rows")
    return []


def _load_all_xls_com(filepath: str) -> List[Dict[str, object]]:
    """
    Read XLS via Excel COM automation.

    Pro-Server EX feeds live data into an already-open Excel session via DDE/OPC.
    The physical file on disk may only have the initial rows; the running Excel
    instance has all accumulated data in memory.  GetObject() attaches to that
    running instance; Dispatch() + Open() opens a fresh session from disk only.
    """
    try:
        import win32com.client
        import pythoncom
        import datetime as _dt
    except ImportError:
        return []

    XL_UP = -4162  # xlDirection.xlUp

    excel      = None
    wb         = None
    opened_new = False   # True when WE opened Excel; False when we attached to existing
    coinit     = False
    try:
        # COM must be initialised on each thread that uses it
        try:
            pythoncom.CoInitialize()
            coinit = True
        except Exception:
            pass

        abs_path = os.path.abspath(filepath)
        # ── Prefer attaching to the running Excel instance ────────────────────
        # GetObject returns the already-open workbook with live Pro-Server EX data.
        try:
            wb    = win32com.client.GetObject(abs_path)
            excel = wb.Application
        except Exception:
            # File not open in any running Excel — open it ourselves from disk.
            excel               = win32com.client.Dispatch("Excel.Application")
            excel.Visible       = False
            excel.DisplayAlerts = False
            wb                  = excel.Workbooks.Open(abs_path, ReadOnly=True, UpdateLinks=False)
            opened_new          = True

        ws = wb.Sheets(1)

        used_rows = ws.UsedRange.Rows.Count
        used_cols = ws.UsedRange.Columns.Count

        # Find header row (first row with string values)
        header_row = 2
        for r in range(1, min(11, used_rows + 1)):
            vals = [ws.Cells(r, c).Value for c in range(1, used_cols + 1)]
            if any(isinstance(v, str) and v.strip() for v in vals):
                header_row = r
                break

        headers = [
            str(ws.Cells(header_row, c).Value or "").strip() or f"col_{c - 1}"
            for c in range(1, used_cols + 1)
        ]

        # Find the actual last non-blank row.
        # End(XL_UP) is DIMENSIONS-limited in newer Excel — it stops at the row
        # reported by the BIFF DIMENSIONS record, which Pro-Server EX sets to the
        # current ring-buffer write position (not the physical row count).
        # To catch all physical rows we also check ws.UsedRange.Rows.Count and
        # take the maximum.
        last_row_endup   = ws.Cells(ws.Rows.Count, 2).End(XL_UP).Row
        last_row_usedrange = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1
        last_row = max(last_row_endup, last_row_usedrange)
        if last_row <= header_row:
            return []

        data_count = last_row - header_row
        logger.info(
            "ProFace | XLS COM load: %d data rows (Excel rows %d–%d, "
            "End(XL_UP)=%d UsedRange=%d), columns: %s",
            data_count, header_row + 1, last_row,
            last_row_endup, last_row_usedrange, headers,
        )

        # Bulk-read the entire data range at once (fast — one COM round-trip)
        data_range = ws.Range(
            ws.Cells(header_row + 1, 1),
            ws.Cells(last_row, used_cols),
        )
        # .Value returns a tuple-of-tuples; single-row files return a flat tuple
        raw = data_range.Value
        if raw is None:
            return []
        # Normalise to list of tuples
        if not isinstance(raw[0], (tuple, list)):
            raw = (raw,)

        rows: List[Dict[str, object]] = []
        for row_tuple in raw:
            if not any(v is not None for v in row_tuple):
                continue  # skip blank rows
            row_dict: Dict[str, object] = {}
            for c, header in enumerate(headers):
                val = row_tuple[c]
                # pywintypes.datetime → naive Python datetime (strip tz; value is IST)
                if hasattr(val, "year") and hasattr(val, "hour"):
                    try:
                        val = _dt.datetime(
                            val.year, val.month, val.day,
                            val.hour, val.minute, val.second,
                        )
                    except Exception:
                        pass
                row_dict[header] = val
            rows.append(row_dict)

        return rows

    except Exception as exc:
        logger.warning("ProFace | XLS COM load error: %s", exc)
        return []
    finally:
        # Only close/quit what WE opened — never touch the user's running Excel session
        if opened_new:
            if wb is not None:
                try:
                    wb.Close(False)
                except Exception:
                    pass
        if opened_new and excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
        if coinit:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _load_all_xls_vbs(filepath: str) -> List[Dict[str, object]]:
    """
    Read all rows from a Pro-Server EX .xls via PowerShell + Excel COM.
    Requires no Python packages — PowerShell and Excel are always present on
    any Windows machine that runs Pro-Server EX.

    Writes output to a temp TSV file (not stdout) so 38K+ rows transfer
    reliably without pipe-buffer limits.
    """
    import subprocess
    import datetime as _dt

    # PowerShell: opens XLS via Excel COM, writes TSV to $outFile.
    # One COM call reads the entire data range as a 2-D array (fast).
    ps1_lines = [
        "param([string]$filepath, [string]$outFile)",
        "$ErrorActionPreference = 'Stop'",
        "$ic = [System.Globalization.CultureInfo]::InvariantCulture",
        "$xl = $null; $wb = $null",
        "try {",
        "    $xl = New-Object -ComObject Excel.Application",
        "    $xl.Visible = $false",
        "    $xl.DisplayAlerts = $false",
        "    $wb = $xl.Workbooks.Open([System.IO.Path]::GetFullPath($filepath), $false, $true)",
        "    $ws = $wb.Sheets.Item(1)",
        "    $usedRows = $ws.UsedRange.Rows.Count",
        "    $lastCol  = $ws.UsedRange.Columns.Count",
        "    $lastRow  = $ws.Cells.Item($ws.Rows.Count, 2).End(-4162).Row",
        "    $hdrRow = 2",
        "    for ($r = 1; $r -le [Math]::Min(10, $usedRows); $r++) {",
        "        $hitStr = $false",
        "        for ($c = 1; $c -le $lastCol; $c++) {",
        "            $v = $ws.Cells.Item($r, $c).Value()",
        "            if ($v -is [string] -and $v.Trim() -ne '') { $hdrRow = $r; $hitStr = $true; break }",
        "        }",
        "        if ($hitStr) { break }",
        "    }",
        "    $hdrs = @()",
        "    for ($c = 1; $c -le $lastCol; $c++) {",
        '        $h = $ws.Cells.Item($hdrRow, $c).Value()',
        '        if ($h -eq $null -or "$h".Trim() -eq \'\') { $hdrs += "col_$($c - 1)" }',
        '        else { $hdrs += "$h".Trim() }',
        "    }",
        "    $lines = [System.Collections.Generic.List[string]]::new()",
        '    $lines.Add(($hdrs -join "`t"))',
        "    if ($lastRow -le $hdrRow) {",
        "        $enc = New-Object System.Text.UTF8Encoding($false)",
        "        [System.IO.File]::WriteAllLines($outFile, $lines, $enc)",
        "        exit 0",
        "    }",
        "    $numRows = $lastRow - $hdrRow",
        "    $numCols = $lastCol",
        "    $rng = $ws.Range($ws.Cells.Item($hdrRow + 1, 1), $ws.Cells.Item($lastRow, $numCols))",
        "    $raw = $rng.Value(10)",
        "    if ($null -eq $raw) {",
        "        $enc = New-Object System.Text.UTF8Encoding($false)",
        "        [System.IO.File]::WriteAllLines($outFile, $lines, $enc)",
        "        exit 0",
        "    }",
        "    $is2D = ($raw.Rank -eq 2)",
        "    for ($r = 1; $r -le $numRows; $r++) {",
        "        $hasData = $false",
        "        for ($c = 1; $c -le $numCols; $c++) {",
        "            $v = if ($is2D) { $raw[$r, $c] } else { $raw[$c] }",
        "            if ($v -ne $null) { $hasData = $true; break }",
        "        }",
        "        if (-not $hasData) { continue }",
        "        $parts = [System.Collections.Generic.List[string]]::new()",
        "        for ($c = 1; $c -le $numCols; $c++) {",
        "            $v = if ($is2D) { $raw[$r, $c] } else { $raw[$c] }",
        "            if ($null -eq $v) { $parts.Add('') }",
        "            elseif ($v -is [DateTime]) { $parts.Add($v.ToString('yyyy-MM-ddTHH:mm:ss')) }",
        '            else { try { $parts.Add(([double]$v).ToString($ic)) } catch { $parts.Add("$v") } }',
        "        }",
        '        $lines.Add(($parts -join "`t"))',
        "    }",
        "    $enc = New-Object System.Text.UTF8Encoding($false)",
        "    [System.IO.File]::WriteAllLines($outFile, $lines, $enc)",
        "} catch {",
        '    [Console]::Error.WriteLine("PS-XLS error: $_")',
        "    exit 1",
        "} finally {",
        "    if ($wb -ne $null) { try { $wb.Close($false) } catch {} }",
        "    if ($xl -ne $null) { try { $xl.Quit() } catch {} }",
        "}",
    ]
    ps1 = "\n".join(ps1_lines) + "\n"

    tmp_ps1: Optional[str] = None
    tmp_tsv: Optional[str] = None
    try:
        fd, tmp_tsv = tempfile.mkstemp(suffix=".tsv")
        os.close(fd)

        fd, tmp_ps1 = tempfile.mkstemp(suffix=".ps1")
        os.close(fd)
        with open(tmp_ps1, "w", encoding="utf-8") as f:
            f.write(ps1)

        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", tmp_ps1,
             os.path.abspath(filepath), os.path.abspath(tmp_tsv)],
            capture_output=True, text=True, timeout=300,
        )

        if result.returncode != 0:
            if result.stderr.strip():
                logger.warning("ProFace | PS xls stderr: %s", result.stderr.strip()[:300])
            return []

        # Read from temp file (avoids stdout pipe-buffer limits with 38K+ rows)
        if not os.path.exists(tmp_tsv) or os.path.getsize(tmp_tsv) == 0:
            logger.warning("ProFace | PS xls: output file empty or missing")
            return []

        with open(tmp_tsv, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) < 2:
            return []

        headers = [h.strip() for h in lines[0].split("\t")]

        rows: List[Dict[str, object]] = []
        for raw_line in lines[1:]:
            raw_line = raw_line.rstrip("\r\n")
            if not raw_line.strip():
                continue
            parts = raw_line.split("\t")
            row_dict: Dict[str, object] = {}
            has_data = False
            for i, header in enumerate(headers):
                val_str = parts[i].strip() if i < len(parts) else ""
                if not val_str:
                    row_dict[header] = None
                elif len(val_str) == 19 and val_str[10] == "T":
                    try:
                        row_dict[header] = _dt.datetime.fromisoformat(val_str)
                        has_data = True
                    except Exception:
                        row_dict[header] = val_str
                else:
                    try:
                        row_dict[header] = float(val_str)
                        has_data = True
                    except ValueError:
                        row_dict[header] = val_str
                        has_data = True
            if has_data:
                rows.append(row_dict)

        if rows:
            logger.info(
                "ProFace | XLS PS load: %d data rows, columns: %s",
                len(rows), headers,
            )
        return rows

    except Exception as exc:
        logger.warning("ProFace | PS xls load failed: %s", exc)
        return []
    finally:
        if tmp_ps1:
            try:
                os.unlink(tmp_ps1)
            except Exception:
                pass
        if tmp_tsv:
            try:
                os.unlink(tmp_tsv)
            except Exception:
                pass


def _extract_biff_stream(filepath: str) -> "Optional[bytes]":
    """Return the raw BIFF Workbook byte-stream from an OLE2 .xls file."""
    import io as _io
    # Method 1: olefile (optional install, most reliable)
    try:
        import olefile
        with olefile.OleFileIO(filepath) as ole:
            for name in ("Workbook", "Book"):
                if ole.exists(name):
                    return ole.openstream(name).read()
        return None
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("ProFace | olefile error: %s", exc)
    # Method 2: xlrd's own compdoc reader (always available when xlrd is installed)
    try:
        import xlrd.compdoc as _cd
        with open(filepath, "rb") as f:
            raw = f.read()
        cd = _cd.CompDoc(raw, logfile=_io.StringIO())
        for name in ("Workbook", "Book"):
            try:
                mem = cd.get_stream(name)
                if mem is not None:
                    return bytes(mem)
            except Exception:
                pass
    except Exception as exc:
        logger.debug("ProFace | xlrd compdoc error: %s", exc)
    return None


def _find_biff8_blocks(stream: bytes) -> "List[tuple]":
    """
    Scan a raw BIFF stream and return (start, end) byte offsets for each
    complete BIFF8 Workbook block (BOF subtype 0x0005 … matching EOF).
    Pro-Server EX concatenates multiple such blocks into one Workbook stream.
    """
    import struct
    blocks: List[tuple] = []
    i = 0
    n = len(stream)
    while i + 8 <= n:
        rec_type = struct.unpack_from("<H", stream, i)[0]
        rec_len  = struct.unpack_from("<H", stream, i + 2)[0]
        if rec_type == 0x0809 and rec_len >= 8 and i + 4 + rec_len <= n:
            biff_ver  = struct.unpack_from("<H", stream, i + 4)[0]
            biff_type = struct.unpack_from("<H", stream, i + 6)[0]
            if biff_ver == 0x0600 and biff_type == 0x0005:   # BIFF8 workbook BOF
                start = i
                depth = 1
                j = i + 4 + rec_len
                while j + 4 <= n and depth > 0:
                    r_type = struct.unpack_from("<H", stream, j)[0]
                    r_len  = struct.unpack_from("<H", stream, j + 2)[0]
                    if r_type == 0x0809:
                        depth += 1
                    elif r_type == 0x000A:   # EOF
                        depth -= 1
                    j += 4 + max(0, r_len)
                blocks.append((start, j))
                i = j
                continue
        i += max(1, 4 + rec_len)
    return blocks


def _load_all_xls_xlrd(filepath: str) -> List[Dict[str, object]]:
    """
    XLS reader via xlrd — handles Pro-Server EX BIFF8 files.

    Extracts the full OLE2 Workbook stream via olefile (follows the complete
    FAT chain, including sectors Pro-Server EX appends as data grows), then
    splits the stream at every BIFF8 Workbook BOF (0x0005) and passes each
    block to xlrd independently.  Rows from all blocks are combined.
    """
    try:
        import xlrd
        import datetime as _dt
        import io as _io
    except ImportError:
        logger.error("xlrd not installed")
        return []

    tmp_path: Optional[str] = None
    read_path = filepath
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".xls")
        os.close(fd)
        shutil.copy2(filepath, tmp_path)
        read_path = tmp_path
    except Exception as exc:
        logger.debug("XLS copy failed (%s) — reading original", exc)
        tmp_path = None

    try:
        # ── Extract the complete BIFF Workbook stream via olefile ────────────────
        biff_stream = _extract_biff_stream(read_path)

        workbooks: List = []
        if biff_stream:
            blocks = _find_biff8_blocks(biff_stream)
            logger.info(
                "ProFace | XLS xlrd: stream %d bytes, %d BIFF8 block(s) found",
                len(biff_stream), len(blocks),
            )
            for start, end in blocks:
                try:
                    wb = xlrd.open_workbook(
                        file_contents=biff_stream[start:end],
                        logfile=_io.StringIO(),
                        formatting_info=False,
                    )
                    workbooks.append(wb)
                except Exception as exc:
                    logger.warning("ProFace | XLS xlrd block [%d:%d] error: %s", start, end, exc)

            if not workbooks:
                # Block slices failed (e.g. BUNDLESHEET points outside slice) —
                # fall back to passing the entire raw stream to xlrd.
                logger.warning("ProFace | XLS xlrd: block slices failed — trying full stream")
                try:
                    wb_full = xlrd.open_workbook(
                        file_contents=biff_stream,
                        logfile=_io.StringIO(),
                        formatting_info=False,
                    )
                    workbooks = [wb_full]
                except Exception as exc:
                    logger.warning("ProFace | XLS xlrd full-stream error: %s", exc)

        if not workbooks:
            # Last resort: let xlrd open the file directly (reads only original sectors)
            logger.warning("ProFace | XLS xlrd: stream extract failed; reading file directly")
            try:
                wb_single = xlrd.open_workbook(read_path, logfile=_io.StringIO())
                workbooks = [wb_single]
            except Exception as exc:
                logger.warning("ProFace | XLS xlrd open error: %s", exc)
                return []

        # ── Collect rows ─────────────────────────────────────────────────────────
        headers: Optional[List[str]] = None
        all_rows: List[Dict[str, object]] = []

        for wb_b in workbooks:
            ws = wb_b.sheet_by_index(0)
            if ws.nrows == 0:
                continue

            # Find header row (first row that has a non-empty string cell)
            hdr_row = 0
            for r in range(min(10, ws.nrows)):
                if any(ws.cell_type(r, c) == xlrd.XL_CELL_TEXT
                       and ws.cell_value(r, c).strip()
                       for c in range(ws.ncols)):
                    hdr_row = r
                    break

            if headers is None:
                headers = [
                    ws.cell_value(hdr_row, c).strip()
                    if ws.cell_type(hdr_row, c) == xlrd.XL_CELL_TEXT
                    else f"col_{c}"
                    for c in range(ws.ncols)
                ]

            for r in range(hdr_row + 1, ws.nrows):
                # Skip blank rows
                if not any(ws.cell_type(r, c) not in
                           (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
                           for c in range(ws.ncols)):
                    continue
                # Skip repeated header rows (col 1 is text = header, not a date)
                if len(headers) > 1 and ws.cell_type(r, 1) == xlrd.XL_CELL_TEXT:
                    continue

                row_dict: Dict[str, object] = {}
                for c, header in enumerate(headers):
                    if c >= ws.ncols:
                        row_dict[header] = None
                        continue
                    cell = ws.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            tup = xlrd.xldate_as_tuple(cell.value, wb_b.datemode)
                            row_dict[header] = _dt.datetime(
                                int(tup[0]), int(tup[1]), int(tup[2]),
                                int(tup[3]), int(tup[4]), int(tup[5]),
                            )
                        except Exception:
                            row_dict[header] = cell.value
                    elif cell.ctype == xlrd.XL_CELL_NUMBER:
                        row_dict[header] = cell.value
                    elif cell.ctype == xlrd.XL_CELL_TEXT:
                        row_dict[header] = cell.value
                    else:
                        row_dict[header] = None
                all_rows.append(row_dict)

        if all_rows:
            logger.info(
                "ProFace | XLS xlrd load: %d block(s) → %d rows, columns: %s",
                len(workbooks), len(all_rows), headers,
            )
        else:
            logger.warning(
                "ProFace | XLS xlrd load: %d block(s) found but 0 rows extracted",
                len(workbooks),
            )
        return all_rows

    except Exception as exc:
        logger.warning("XLS xlrd load error: %s", exc)
        return []
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _load_all_xlsx(filepath: str) -> List[Dict[str, object]]:
    try:
        import openpyxl
    except ImportError:
        return []
    tmp_path, read_path = _safe_xlsx_copy(filepath)
    wb = None
    try:
        wb = openpyxl.load_workbook(read_path, read_only=True, data_only=True)
        ref = EXCEL_SHEET
        if ref.isdigit() and int(ref) < len(wb.worksheets):
            ws = wb.worksheets[int(ref)]
        elif ref in wb.sheetnames:
            ws = wb[ref]
        else:
            ws = wb.active
        raw_hdr = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not raw_hdr:
            return []
        headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(raw_hdr)]
        rows: List[Dict[str, object]] = []
        for vals in ws.iter_rows(min_row=2, values_only=True):
            if not any(v is not None for v in vals):
                continue
            n = min(len(headers), len(vals))
            rows.append({headers[i]: vals[i] for i in range(n)})
        logger.info("ProFace | XLSX bulk load: %d data rows, columns: %s", len(rows), headers)
        return rows
    except Exception as exc:
        logger.warning("XLSX bulk load error: %s", exc)
        return []
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


def _load_all_csv(filepath: str) -> List[Dict[str, str]]:
    raw_bytes: Optional[bytes] = None
    try:
        with open(filepath, "rb") as f:
            raw_bytes = f.read()
    except Exception:
        return []
    if not raw_bytes:
        return []
    for enc in _encodings():
        try:
            text = raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        try:
            first_line = text.split("\n")[0] if "\n" in text else text
            try:
                dialect = csv.Sniffer().sniff(first_line, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(text), dialect=dialect)
            rows = []
            for row in reader:
                r = {k.strip(): v.strip() for k, v in row.items() if k}
                if any(v for v in r.values()):
                    rows.append(r)
            if rows:
                logger.info("ProFace | CSV bulk load: %d data rows", len(rows))
                return rows
        except Exception:
            continue
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# Background polling thread
# ═══════════════════════════════════════════════════════════════════════════════

def _is_recent_timestamp(ts_str: str, max_age_seconds: int = LIVE_STALE_SECONDS) -> bool:
    """True if ts_str is within max_age_seconds of local now — i.e. it's live data."""
    import datetime as _dt
    try:
        if not ts_str:
            return False
        # Strip timezone suffix so we compare in local time (Pro-Server EX writes local)
        clean = ts_str.replace(" ", "T").split("+")[0].rstrip("Z")
        ts  = _dt.datetime.fromisoformat(clean)
        age = abs((_dt.datetime.now() - ts).total_seconds())
        return age <= max_age_seconds
    except Exception:
        return False


def _get_row_timestamp(row: Dict) -> str:
    """Extract the timestamp string from a row dict using configured column names."""
    import datetime as _dt
    if EXCEL_TIMESTAMP_COL:
        ts_val = next(
            (v for k, v in row.items() if _col_match(k, EXCEL_TIMESTAMP_COL)), None
        )
        return _extract_single_timestamp(ts_val)
    date_val = next((v for k, v in row.items() if _col_match(k, EXCEL_DATE_COL)), None)
    time_val = next((v for k, v in row.items() if _col_match(k, EXCEL_TIME_COL)), None)
    if date_val is None and time_val is None:
        for v in row.values():
            if isinstance(v, (_dt.datetime, _dt.date)):
                date_val = v
                break
    return _parse_proserver_datetime(date_val, time_val)


def _com_live_row_count() -> int:
    """
    Query the running Excel COM session for the current data-row count.
    Returns the count, or -1 if COM is unavailable / file not open in Excel.

    Pro-Server EX writes rows into Excel's in-memory session via DDE/OPC
    without saving to disk, so the file's mtime never changes.  This function
    bypasses the file entirely and reads directly from the live Excel process.
    """
    if not EXCEL_FILE_PATH or Path(EXCEL_FILE_PATH).suffix.lower() != ".xls":
        return -1
    try:
        import win32com.client
        import pythoncom
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            abs_path = os.path.abspath(EXCEL_FILE_PATH)
            wb = win32com.client.GetObject(abs_path)
            ws = wb.Sheets(1)
            XL_UP      = -4162
            last_endup = ws.Cells(ws.Rows.Count, 2).End(XL_UP).Row
            last_used  = ws.UsedRange.Row + ws.UsedRange.Rows.Count - 1
            last_row   = max(last_endup, last_used)
            # Subtract header row — Pro-Server EX always has at least one header row
            return max(0, last_row - 1)
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    except Exception:
        return -1


def _poll_loop(stop_evt: threading.Event) -> None:
    """
    Daemon thread — checks the file every EXCEL_POLL_INTERVAL seconds.

    Startup  : jumps to the last REPLAY_WINDOW rows, plays them in a loop.
               _in_loop_mode = True  → main.py marks is_live=False → no alerts.

    New data : when the file grows OR the COM session has more rows (for .xls
               files where Pro-Server EX writes without saving), switches to
               live mode.
               _in_loop_mode = False → main.py marks is_live=True → alerts fire.

    End      : once new rows are exhausted, loops back through the last
               REPLAY_WINDOW rows of the updated cache with alerts off.
    """
    global _last_mtime, _last_file_size, _active, _in_loop_mode

    _playback_idx: int        = 0
    _cached_rows:  List[Dict] = []
    _live_from:    int        = 0   # rows at index >= _live_from are live rows
    _last_save_ts: float      = 0.0  # monotonic time of last COM auto-save

    logger.info(
        "Pro-Server EX reader started: '%s' every %.1f s",
        EXCEL_FILE_PATH, EXCEL_POLL_INTERVAL,
    )

    while not stop_evt.is_set():
        try:
            fp_str = EXCEL_FILE_PATH
            if not fp_str:
                stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            file_path = Path(fp_str)

            # ── File existence check ──────────────────────────────────────────
            if not file_path.exists():
                if _active:
                    logger.warning("Pro-Server EX file disappeared: %s — waiting", file_path)
                    _active = False
                stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            stat      = file_path.stat()
            mtime     = stat.st_mtime
            file_size = stat.st_size
            _active   = True

            file_changed = (mtime != _last_mtime or file_size != _last_file_size)
            if file_changed:
                _last_mtime     = mtime
                _last_file_size = file_size

            # ── COM auto-save (every AUTO_SAVE_INTERVAL seconds when enabled) ─
            import time as _time
            _now = _time.monotonic()
            if _auto_save_enabled and (_now - _last_save_ts) >= AUTO_SAVE_INTERVAL:
                if _com_force_save():
                    _last_save_ts = _now
                    # Re-check file stat so the next iteration detects the new mtime
                    try:
                        stat      = file_path.stat()
                        mtime     = stat.st_mtime
                        file_size = stat.st_size
                        if mtime != _last_mtime or file_size != _last_file_size:
                            file_changed    = True
                            _last_mtime     = mtime
                            _last_file_size = file_size
                    except OSError:
                        pass
                else:
                    _last_save_ts = _now  # avoid hammering COM on repeated failures

            # ── First load ────────────────────────────────────────────────────
            if not _cached_rows:
                _cached_rows = _load_all_rows()
                if not _cached_rows:
                    logger.warning("ProFace | Could not load rows — retrying")
                    stop_evt.wait(EXCEL_POLL_INTERVAL)
                    continue
                n             = len(_cached_rows)
                _live_from    = n                          # nothing is live yet
                _playback_idx = max(0, n - REPLAY_WINDOW)  # start of last-20 window
                _in_loop_mode = True
                logger.info(
                    "ProFace | Loaded %d rows — starting at row %d "
                    "(last %d rows). LOOP mode ON — alerts suppressed until live data arrives.",
                    n, _playback_idx, REPLAY_WINDOW,
                )

            # ── Live-only mode (disabled loop): show NULL or live, never loop ──
            # When the user disables looping via Settings:
            #   1. Read the LAST row from COM session (.xls) or disk (.csv/.xlsx)
            #   2. If its timestamp is within LIVE_STALE_SECONDS → live data: apply it
            #   3. If timestamp is old → no live data: clear all readings (NULL shown)
            # This cycle repeats every second.  Alerts fire only during live windows.
            # When Pro-Server EX stops writing, values return to NULL automatically.
            if not _excel_enabled:
                _in_loop_mode = True   # default: no alerts
                # Try running Excel COM session first (catches unsaved .xls rows)
                row = _com_read_last_row()
                # Fallback: last row from disk (covers .csv and .xlsx)
                if row is None:
                    row = _read_latest_row()

                if row is not None:
                    ts = _get_row_timestamp(row)
                    if _is_recent_timestamp(ts):
                        _apply_row(row)
                        _in_loop_mode = False   # live data → alerts fire
                        logger.debug(
                            "ProFace | LIVE-ONLY ● LIVE | T=%.3f ts=%s extras=%s",
                            current_temperature or 0.0, ts, extra_readings,
                        )
                    else:
                        _clear_readings()
                        logger.debug(
                            "ProFace | LIVE-ONLY ○ IDLE (last ts=%s — too old)", ts,
                        )
                else:
                    _clear_readings()

                stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue   # skip all loop/replay logic below

            # ── File grew → new live rows (disk-based detection) ─────────────
            elif file_changed:
                new_cache = _load_all_rows()
                if len(new_cache) > len(_cached_rows):
                    old_len      = len(_cached_rows)
                    _cached_rows = new_cache
                    new_count    = len(_cached_rows) - old_len
                    _live_from   = old_len    # rows from old_len onward are live
                    _playback_idx = old_len   # jump to first new row
                    _in_loop_mode = False
                    logger.info(
                        "ProFace | %d new live row(s) from row %d — "
                        "LIVE mode ON, alerts enabled.",
                        new_count, old_len,
                    )

            # ── COM session check for .xls (Pro-Server EX writes without saving) ──
            # Pro-Server EX pushes rows into Excel's in-memory session via DDE/OPC.
            # The file on disk never changes, so mtime detection misses new rows.
            # We query the running Excel COM object directly to catch them.
            elif not file_changed:
                com_count = _com_live_row_count()
                if com_count > len(_cached_rows):
                    new_cache = _load_all_rows()
                    if len(new_cache) > len(_cached_rows):
                        old_len       = len(_cached_rows)
                        _cached_rows  = new_cache
                        new_count     = len(_cached_rows) - old_len
                        _live_from    = old_len
                        _playback_idx = old_len
                        _in_loop_mode = False
                        logger.info(
                            "ProFace | COM session: %d new live row(s) at row %d — "
                            "LIVE mode ON (detected without file save).",
                            new_count, old_len,
                        )

            # ── End-of-data: loop back through last REPLAY_WINDOW rows ──────────
            total = len(_cached_rows)
            if _playback_idx >= total:
                _live_from    = total
                _playback_idx = max(0, total - REPLAY_WINDOW)
                _in_loop_mode = True
                logger.debug(
                    "ProFace | End of data — looping to row %d. "
                    "LOOP mode ON — alerts suppressed.",
                    _playback_idx,
                )

            # ── Determine live/loop for this specific row ─────────────────────
            # Rows below _live_from = historical/loop  → alerts OFF
            # Rows >= _live_from    = newly written    → alerts ON
            _in_loop_mode = (_playback_idx < _live_from)

            # ── Apply row and advance ─────────────────────────────────────────
            row = _cached_rows[_playback_idx] if _cached_rows else None
            if row is None:
                stop_evt.wait(EXCEL_POLL_INTERVAL)
                continue

            _apply_row(row)
            logger.debug(
                "ProFace | %s row %-6d | T=%.3f  ts=%s  extras=%s",
                "LOOP   " if _in_loop_mode else "LIVE   ",
                _playback_idx,
                current_temperature or 0.0,
                current_timestamp,
                extra_readings,
            )
            _playback_idx += 1

        except Exception as exc:
            logger.warning("Pro-Server EX reader error: %s", exc)

        stop_evt.wait(EXCEL_POLL_INTERVAL)


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
    EXCEL_TEMP_COL      = _s("temp_col",      "TEMPERATURE")
    EXCEL_DATE_COL      = _s("date_col",       "DATE/TIME")
    EXCEL_TIME_COL      = _s("time_col",       "Time")
    EXCEL_TIMESTAMP_COL = _s("timestamp_col",  "")
    EXCEL_SHEET         = _s("sheet",          "0")
    EXCEL_ENCODING      = _s("encoding",       "")
    try:
        EXCEL_POLL_INTERVAL = float(db_values.get("poll_interval") or 1.0)
    except (ValueError, TypeError):
        EXCEL_POLL_INTERVAL = 1.0

    # Signal old thread to exit using the OLD event (before replacing it)
    old_stop = _stop_evt
    _stop_evt = threading.Event()   # new event for the new thread
    old_stop.set()                  # stop the old thread
    if _thread_ref and _thread_ref.is_alive():
        _thread_ref.join(timeout=5.0)

    # Reset shared state
    current_temperature = None
    current_timestamp   = ""
    extra_readings      = {}
    _last_mtime         = 0.0
    _last_file_size     = 0
    _active             = False

    if EXCEL_FILE_PATH:
        _thread_ref = threading.Thread(
            target=_poll_loop,
            args=(_stop_evt,),      # pass the new event so old thread can't interfere
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
        args=(_stop_evt,),
        daemon=True,
        name="proserver-reader",
    )
    _thread_ref.start()
else:
    logger.debug("Pro-Server EX reader: EXCEL_FILE_PATH not set — inactive (configure via Admin → Settings)")

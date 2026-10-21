"""
services/live_excel_reader.py — Live Microsoft Excel COM reader (live-tail mode).

Reads data directly from a workbook that is currently open in Excel — WITHOUT
requiring the file to be saved to disk.

Live-tail behaviour
-------------------
When the reader starts it immediately finds the CURRENT last complete row,
emits that row to the dashboard, and then waits for the NEXT row.  The user
sees current data instantly rather than waiting for Pro-Server EX to write a
new row.

  current_last = find_last_valid_row()   # scan backward from End(XL_UP)
  emit(current_last)                     # show immediately
  next_expected = current_last + 1

  loop:
      row = try_read(next_expected)
      if row is complete:
          emit(row)
          next_expected += 1
      else:
          wait(poll_interval)            # same row checked again next cycle

Row completeness
----------------
All four configured fields (DATE/TIME, TEMPERATURE, PRESSURE, PH) must be
non-None before a row is emitted.  If Pro-Server EX is mid-write the row is
skipped until the next poll cycle.

Exact values
------------
Raw float values from Excel are forwarded as-is.  No rounding is applied.

Safety
------
Read-only.  Never writes to, modifies, saves, or closes Excel or the workbook.

Threading model
---------------
All COM calls run on a single dedicated daemon thread that calls
pythoncom.CoInitialize() once.  Results are forwarded to the asyncio event
loop via asyncio.run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import os
import threading
import datetime as _dt
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("sentineledge.live_excel")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _col_idx(letter: str) -> int:
    """Convert Excel column letter(s) to 1-based index.  'A'→1, 'B'→2, 'AA'→27."""
    result = 0
    for ch in letter.strip().upper():
        if not ch.isalpha():
            raise ValueError(f"Invalid column letter: {letter!r}")
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


def _to_float(val) -> Optional[float]:
    """Convert any COM cell value to float — exact, no rounding."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_cell_datetime(val) -> str:
    """Convert a COM cell value to an ISO-8601 timestamp string."""
    if val is None:
        return ""
    if isinstance(val, (_dt.datetime, _dt.date)):
        return val.isoformat()
    if isinstance(val, (int, float)):
        try:
            import xlrd as _xlrd
            return _xlrd.xldate_as_datetime(float(val), 0).isoformat()
        except Exception:
            pass
    return str(val).strip()


# ── Settings defaults ──────────────────────────────────────────────────────────

_DEFAULTS: dict[str, str] = {
    "enabled":      "false",
    "workbook":     "",
    "worksheet":    "",      # empty → Sheet 1
    "header_row":   "2",
    "data_start":   "3",
    "datetime_col": "B",
    "temp_col":     "C",
    "pressure_col": "D",
    "ph_col":       "E",
    "poll_ms":      "1000",
}

_DB_PREFIX = "live_excel_"
_XL_UP     = -4162   # xlDirection.xlUp


# ── Reader ─────────────────────────────────────────────────────────────────────

class LiveExcelReader:
    """
    Singleton service.  Call load_settings_from_db() at startup, then
    start(loop) to begin reading.
    """

    def __init__(self) -> None:
        self.settings: dict[str, str] = dict(_DEFAULTS)

        # ── Status (readable from any thread) ─────────────────────────────────
        self.running:                bool          = False
        self.connection_status:      str           = "disconnected"
        # "live"               → currently displaying data, watching next row
        # "waiting_for_new_data" → waiting for next_expected_row to become complete
        # "connecting"         → trying to attach to Excel
        # "disconnected" / "error"
        self.live_status:            str           = "disconnected"
        self.currently_displaying_row: int         = 0
        self.next_expected_row:      int           = 0
        self.current_last_row:       int           = 0   # as reported by End(XL_UP)
        self.rows_processed:         int           = 0
        self.latest_reading:         Optional[dict] = None

        # ── Thread control ────────────────────────────────────────────────────
        self._stop_evt: threading.Event            = threading.Event()
        self._thread:   Optional[threading.Thread] = None
        self._loop:     Optional[asyncio.AbstractEventLoop] = None

        # ── COM objects (polling thread only) ─────────────────────────────────
        self._xl:  Any = None
        self._wb:  Any = None
        self._ws:  Any = None

    # ── Settings ──────────────────────────────────────────────────────────────

    def load_settings_from_db(self) -> None:
        """Load all live_excel_* keys from app_settings.  Called at startup."""
        try:
            from database.connection import execute_read
            rows = execute_read(
                "SELECT key, value FROM app_settings WHERE key LIKE %s",
                (f"{_DB_PREFIX}%",),
            ) or []
            for r in rows:
                short_key = r["key"].replace(_DB_PREFIX, "", 1)
                self.settings[short_key] = r["value"]
            logger.info("[LiveExcel] Settings loaded from DB")
        except Exception as exc:
            logger.warning("[LiveExcel] Could not load settings from DB: %s", exc)

    def save_settings_to_db(self, updates: dict[str, str]) -> None:
        """Persist {short_key: value} pairs to app_settings."""
        try:
            from database.connection import execute_write
            for short_key, value in updates.items():
                execute_write(
                    """
                    INSERT INTO app_settings (key, value, updated_at)
                         VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE
                          SET value = EXCLUDED.value,
                              updated_at = EXCLUDED.updated_at
                    """,
                    (f"{_DB_PREFIX}{short_key}", str(value)),
                )
        except Exception as exc:
            logger.warning("[LiveExcel] Could not save settings to DB: %s", exc)

    # ── Start / stop ──────────────────────────────────────────────────────────

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start the background polling thread."""
        if self.running:
            return
        self._loop = loop
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="live-excel-reader",
        )
        self._thread.start()
        self.running  = True
        self.live_status = "connecting"
        logger.info("[LiveExcel] Reader started")

    def stop(self) -> None:
        """Stop the polling thread."""
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self.running         = False
        self.live_status     = "disconnected"
        self.connection_status = "disconnected"
        logger.info("[LiveExcel] Reader stopped")

    def restart(self, loop: asyncio.AbstractEventLoop) -> None:
        self.stop()
        self.start(loop)

    # ── COM helpers (polling thread only) ─────────────────────────────────────

    def _connect(self) -> bool:
        """Attach to running Excel.Application and locate workbook + worksheet."""
        try:
            import win32com.client as _win32
        except ImportError:
            self.connection_status = "pywin32_not_installed"
            logger.warning("[LiveExcel] pywin32 not installed — run: pip install pywin32")
            return False

        wb_name = self.settings.get("workbook", "").strip()
        if not wb_name:
            self.connection_status = "workbook_not_configured"
            return False

        try:
            xl = _win32.GetActiveObject("Excel.Application")
        except Exception:
            self.connection_status = "excel_not_running"
            return False

        self._xl = xl

        # Extract just the filename — user may have configured a full path
        wb_basename = os.path.basename(wb_name) if (os.sep in wb_name or "/" in wb_name) else wb_name

        wb = None
        try:
            count = xl.Workbooks.Count
            for i in range(1, count + 1):
                candidate = xl.Workbooks(i)
                try:
                    logger.info(
                        "[LiveExcel] Open workbook #%d: Name=%r  FullName=%r  ReadOnly=%s",
                        i, candidate.Name, candidate.FullName, candidate.ReadOnly,
                    )
                except Exception:
                    pass
                # Primary: exact filename match (case-insensitive)
                try:
                    if candidate.Name.lower() == wb_basename.lower():
                        wb = candidate
                        break
                except Exception:
                    pass
            # Secondary: normalized FullName match if primary failed and a full path was given
            if wb is None and (os.sep in wb_name or "/" in wb_name):
                norm_target = os.path.normcase(os.path.normpath(wb_name))
                for i in range(1, count + 1):
                    try:
                        if os.path.normcase(os.path.normpath(xl.Workbooks(i).FullName)) == norm_target:
                            wb = xl.Workbooks(i)
                            break
                    except Exception:
                        pass
        except Exception as exc:
            self.connection_status = "error"
            logger.warning("[LiveExcel] Workbook search error: %s", exc)
            return False

        if wb is None:
            self.connection_status = "workbook_not_found"
            logger.warning(
                "[LiveExcel] Workbook %r not found. Looking for basename=%r",
                wb_name, wb_basename,
            )
            return False

        self._wb = wb
        logger.info("[LiveExcel] Workbook found: %s", wb.Name)

        ws_name = self.settings.get("worksheet", "").strip()
        try:
            ws = wb.Sheets(ws_name) if ws_name else wb.Sheets(1)
        except Exception:
            self.connection_status = "worksheet_not_found"
            logger.warning("[LiveExcel] Worksheet %r not found", ws_name)
            return False

        self._ws = ws
        self.connection_status = "connected"
        logger.info("[LiveExcel] Worksheet: %s", ws.Name)
        return True

    def _disconnect(self) -> None:
        self._xl = self._wb = self._ws = None

    def _find_excel_last_row(self) -> int:
        """Return the row index End(XL_UP) finds on the DATE/TIME column."""
        dt_col     = _col_idx(self.settings.get("datetime_col", "B"))
        data_start = int(self.settings.get("data_start", "3") or "3")
        last       = self._ws.Cells(self._ws.Rows.Count, dt_col).End(_XL_UP).Row
        return max(last, data_start - 1)

    def _read_row(self, row_num: int) -> Optional[dict]:
        """
        Try to read one row.  Returns a dict with exact float values if the row
        is complete, or None if any required field is missing/null.
        """
        dt_col   = _col_idx(self.settings.get("datetime_col",  "B"))
        temp_col = _col_idx(self.settings.get("temp_col",      "C"))
        pres_col = _col_idx(self.settings.get("pressure_col",  "D"))
        ph_col   = _col_idx(self.settings.get("ph_col",        "E"))

        dt_val   = self._ws.Cells(row_num, dt_col).Value
        temp_val = self._ws.Cells(row_num, temp_col).Value
        pres_val = self._ws.Cells(row_num, pres_col).Value
        ph_val   = self._ws.Cells(row_num, ph_col).Value

        if any(v is None for v in (dt_val, temp_val, pres_val, ph_val)):
            return None

        temp_f = _to_float(temp_val)
        pres_f = _to_float(pres_val)
        ph_f   = _to_float(ph_val)

        if temp_f is None or pres_f is None or ph_f is None:
            return None

        # Return exact values — no rounding
        return {
            "row_number":  row_num,
            "timestamp":   _parse_cell_datetime(dt_val),
            "temperature": temp_f,
            "pressure":    pres_f,
            "ph":          ph_f,
        }

    def _find_last_valid_row(self) -> Optional[dict]:
        """
        Scan backward from End(XL_UP) to find the last complete (valid) row.
        Returns the row dict, or None if no valid row found above data_start.
        """
        data_start = int(self.settings.get("data_start", "3") or "3")
        last_row   = self._find_excel_last_row()

        # Scan up to 50 rows back in case the very last row is still being written
        for row_num in range(last_row, max(data_start - 1, last_row - 50), -1):
            row = self._read_row(row_num)
            if row is not None:
                return row
        return None

    def _broadcast_row(self, row_data: dict) -> None:
        """Schedule a broadcast to all WebSocket clients from the asyncio loop."""
        if self._loop is None:
            return
        try:
            from modules.inapp.manager import broadcast
            from services.sensor_company import get_source_company_id
            asyncio.run_coroutine_threadsafe(
                broadcast({"type": "live_excel_row", **row_data}, company_id=get_source_company_id("excel")),
                self._loop,
            )
        except Exception as exc:
            logger.debug("[LiveExcel] broadcast error: %s", exc)

    # ── Poll loop ─────────────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """
        Background daemon thread — live-tail behaviour:

        1. Connect to Excel.
        2. Find the current last valid row and emit it IMMEDIATELY.
        3. Set next_expected_row = that_row + 1.
        4. Each poll cycle: try to read next_expected_row.
           - Complete → emit, increment next_expected_row.
           - Incomplete → wait (Pro-Server EX still writing), retry next cycle.
        """
        try:
            import pythoncom
            pythoncom.CoInitialize()
            coinit = True
        except ImportError:
            coinit = False

        logger.info("[LiveExcel] Connecting to Excel...")

        # Whether we have already done the initial "seed" emit for this connection
        seeded = False

        try:
            while not self._stop_evt.is_set():

                # ── (Re)connect ───────────────────────────────────────────────
                if self._ws is None:
                    self.live_status = "connecting"
                    seeded = False
                    if not self._connect():
                        self._stop_evt.wait(5.0)
                        continue
                    logger.info("[LiveExcel] Excel connected")

                try:
                    # ── Seed: emit current last valid row immediately ──────────
                    if not seeded:
                        seed_row = self._find_last_valid_row()
                        if seed_row is None:
                            # No valid data yet — wait and retry
                            self.live_status = "waiting_for_new_data"
                            self._stop_evt.wait(
                                int(self.settings.get("poll_ms", "1000") or "1000") / 1000.0
                            )
                            continue

                        self.currently_displaying_row = seed_row["row_number"]
                        self.next_expected_row        = seed_row["row_number"] + 1
                        self.current_last_row         = seed_row["row_number"]
                        self.rows_processed          += 1
                        self.latest_reading           = seed_row
                        self.live_status              = "live"
                        seeded = True

                        self._broadcast_row(seed_row)
                        logger.info(
                            "[LiveExcel] Seeded from row %d — "
                            "T=%s  P=%s  pH=%s  next_expected=%d",
                            seed_row["row_number"],
                            seed_row["temperature"],
                            seed_row["pressure"],
                            seed_row["ph"],
                            self.next_expected_row,
                        )

                    # ── Live-tail: watch only next_expected_row ───────────────
                    else:
                        # Also update current_last_row from Excel (for status display)
                        try:
                            self.current_last_row = self._find_excel_last_row()
                        except Exception:
                            pass

                        row = self._read_row(self.next_expected_row)

                        if row is not None:
                            # Row is complete — emit and advance cursor
                            self.currently_displaying_row = row["row_number"]
                            self.rows_processed          += 1
                            self.latest_reading           = row
                            self.live_status              = "live"
                            self._broadcast_row(row)
                            logger.info(
                                "[LiveExcel] New row detected: %d",
                                row["row_number"],
                            )
                            logger.info(
                                "[LiveExcel] Row %d processed — "
                                "T=%s  P=%s  pH=%s",
                                row["row_number"],
                                row["temperature"],
                                row["pressure"],
                                row["ph"],
                            )
                            self.next_expected_row += 1
                        else:
                            # Row not ready yet (partially written or doesn't exist)
                            self.live_status = "waiting_for_new_data"

                except Exception as exc:
                    logger.warning("[LiveExcel] Connection lost: %s", exc)
                    self.connection_status = "error"
                    self.live_status       = "error"
                    self._disconnect()
                    seeded = False
                    self._stop_evt.wait(5.0)
                    logger.info("[LiveExcel] Reconnecting...")
                    continue

                self._stop_evt.wait(
                    int(self.settings.get("poll_ms", "1000") or "1000") / 1000.0
                )

        finally:
            self._disconnect()
            if coinit:
                try:
                    import pythoncom as _pc
                    _pc.CoUninitialize()
                except Exception:
                    pass
            logger.info("[LiveExcel] Polling thread exited")

    # ── Status (any thread) ───────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "running":                  self.running,
            "connection_status":        self.connection_status,
            "live_status":              self.live_status,
            "currently_displaying_row": self.currently_displaying_row,
            "next_expected_row":        self.next_expected_row,
            "current_last_row":         self.current_last_row,
            "rows_processed":           self.rows_processed,
            "latest_reading":           self.latest_reading,
            "workbook":                 self.settings.get("workbook", ""),
            "worksheet":                self.settings.get("worksheet", ""),
        }

    # ── Utility (any thread — creates short-lived COM connection) ─────────────

    def list_open_workbooks(self) -> list[str]:
        """Return the Name (filename only) of each workbook open in Excel."""
        names: list[str] = []
        coinit = False
        try:
            import pythoncom, win32com.client as _win32
            pythoncom.CoInitialize()
            coinit = True
            xl = _win32.GetActiveObject("Excel.Application")
            for i in range(1, xl.Workbooks.Count + 1):
                try:
                    names.append(xl.Workbooks(i).Name)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if coinit:
                try:
                    import pythoncom as _pc; _pc.CoUninitialize()
                except Exception:
                    pass
        return names

    def test_connection(self) -> dict:
        """
        Synchronous diagnostic — creates a short-lived COM connection.
        Returns a dict with ok, status, message and diagnostics.
        Workbook is matched by filename (basename), not full path.
        ReadOnly workbooks are supported — we only read, never write.
        """
        coinit = False
        try:
            import pythoncom, win32com.client as _win32
            pythoncom.CoInitialize()
            coinit = True
        except ImportError:
            return {"ok": False, "status": "pywin32_not_installed",
                    "message": "pywin32 is not installed — run: pip install pywin32"}

        result: dict = {}
        try:
            try:
                xl = _win32.GetActiveObject("Excel.Application")
            except Exception:
                return {"ok": False, "status": "excel_not_running",
                        "message": "Excel is not running. Start Excel and open the workbook."}

            # Log all open workbooks for diagnostics
            count = xl.Workbooks.Count
            open_wbs = []
            for i in range(1, count + 1):
                try:
                    c = xl.Workbooks(i)
                    open_wbs.append({
                        "name":      c.Name,
                        "full_name": c.FullName,
                        "read_only": bool(c.ReadOnly),
                    })
                except Exception:
                    pass
            result["open_workbooks"] = [w["name"] for w in open_wbs]
            result["open_workbooks_detail"] = open_wbs

            wb_name = self.settings.get("workbook", "").strip()
            if not wb_name:
                return {"ok": False, "status": "workbook_not_configured",
                        "message": "No workbook name configured.", **result}

            # Extract just the filename so full-path configs still match
            wb_basename = os.path.basename(wb_name) if (os.sep in wb_name or "/" in wb_name) else wb_name
            result["configured_workbook"] = wb_name
            result["matching_by_name"]    = wb_basename

            wb = None
            # Primary: exact Name match (case-insensitive)
            for w in open_wbs:
                if w["name"].lower() == wb_basename.lower():
                    wb = xl.Workbooks(w["name"])
                    break
            # Secondary: normalized FullName match
            if wb is None and (os.sep in wb_name or "/" in wb_name):
                norm_target = os.path.normcase(os.path.normpath(wb_name))
                for i in range(1, count + 1):
                    try:
                        if os.path.normcase(os.path.normpath(xl.Workbooks(i).FullName)) == norm_target:
                            wb = xl.Workbooks(i)
                            break
                    except Exception:
                        pass

            if wb is None:
                return {"ok": False, "status": "workbook_not_found",
                        "message": (
                            f"Workbook '{wb_basename}' not found in the running Excel instance. "
                            f"Open workbooks: {', '.join(result['open_workbooks']) or 'none'}"
                        ), **result}

            result["workbook_found"]    = wb.Name
            result["workbook_fullname"] = wb.FullName
            result["workbook_readonly"] = bool(wb.ReadOnly)

            ws_name = self.settings.get("worksheet", "").strip()
            try:
                ws = wb.Sheets(ws_name) if ws_name else wb.Sheets(1)
            except Exception:
                sheets = [wb.Sheets(i).Name for i in range(1, wb.Sheets.Count + 1)]
                return {"ok": False, "status": "worksheet_not_found",
                        "message": f"Worksheet '{ws_name}' not found.",
                        "available_sheets": sheets, **result}

            result["worksheet_found"] = ws.Name

            dt_col     = _col_idx(self.settings.get("datetime_col",  "B"))
            temp_col   = _col_idx(self.settings.get("temp_col",      "C"))
            pres_col   = _col_idx(self.settings.get("pressure_col",  "D"))
            ph_col     = _col_idx(self.settings.get("ph_col",        "E"))
            data_start = int(self.settings.get("data_start", "3") or "3")

            last_row = ws.Cells(ws.Rows.Count, dt_col).End(_XL_UP).Row
            result["current_last_row"] = last_row

            if last_row >= data_start:
                dt_raw   = ws.Cells(last_row, dt_col).Value
                temp_raw = ws.Cells(last_row, temp_col).Value
                pres_raw = ws.Cells(last_row, pres_col).Value
                ph_raw   = ws.Cells(last_row, ph_col).Value
                result["last_row_preview"] = {
                    "row":         last_row,
                    "date_time":   str(dt_raw),
                    "temperature": str(temp_raw),
                    "pressure":    str(pres_raw),
                    "ph":          str(ph_raw),
                }
                result["latest_timestamp"]   = _parse_cell_datetime(dt_raw)
                result["latest_temperature"] = _to_float(temp_raw)
                result["latest_pressure"]    = _to_float(pres_raw)
                result["latest_ph"]          = _to_float(ph_raw)

            return {"ok": True, "status": "connected",
                    "message": (
                        f"Connected — {wb.Name} ({'ReadOnly' if wb.ReadOnly else 'ReadWrite'}) "
                        f"/ sheet '{ws.Name}' / last row {last_row}"
                    ), **result}

        finally:
            if coinit:
                try:
                    import pythoncom as _pc; _pc.CoUninitialize()
                except Exception:
                    pass


# ── Singleton ──────────────────────────────────────────────────────────────────
reader = LiveExcelReader()

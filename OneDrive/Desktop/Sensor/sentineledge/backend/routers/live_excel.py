"""
routers/live_excel.py — Live Excel COM reader settings and control.

Prefix: /api/admin/live-excel
All endpoints require admin auth.

Endpoints:
  GET  /settings           — current settings
  POST /settings           — save settings (hot-reload)
  GET  /status             — current reader status
  GET  /workbooks          — list workbooks currently open in Excel
  POST /test               — test COM connection
  POST /start              — start reader
  POST /stop               — stop reader
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from middleware.auth import require_admin
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/admin/live-excel", tags=["Live Excel"])


# ── Pydantic models ────────────────────────────────────────────────────────────

class LiveExcelSettingsIn(BaseModel):
    enabled:       bool   = False
    workbook:      str    = Field(default="",  max_length=260)
    worksheet:     str    = Field(default="",  max_length=260)
    header_row:    int    = Field(default=2,   ge=1, le=1000)
    data_start:    int    = Field(default=3,   ge=1, le=1000)
    datetime_col:  str    = Field(default="B", min_length=1, max_length=3)
    temp_col:      str    = Field(default="C", min_length=1, max_length=3)
    pressure_col:  str    = Field(default="D", min_length=1, max_length=3)
    ph_col:        str    = Field(default="E", min_length=1, max_length=3)
    poll_ms:       int    = Field(default=1000, ge=200, le=30000)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/settings", dependencies=[Depends(require_admin)])
async def get_settings():
    """Return the current Live Excel reader settings."""
    from services.live_excel_reader import reader
    s = reader.settings
    return {
        "enabled":      s.get("enabled", "false") == "true",
        "workbook":     s.get("workbook",     ""),
        "worksheet":    s.get("worksheet",    ""),
        "header_row":   int(s.get("header_row",   "2") or "2"),
        "data_start":   int(s.get("data_start",   "3") or "3"),
        "datetime_col": s.get("datetime_col",  "B"),
        "temp_col":     s.get("temp_col",      "C"),
        "pressure_col": s.get("pressure_col",  "D"),
        "ph_col":       s.get("ph_col",        "E"),
        "poll_ms":      int(s.get("poll_ms",  "1000") or "1000"),
    }


@router.post("/settings", dependencies=[Depends(require_admin)])
async def save_settings(body: LiveExcelSettingsIn, request: Request):
    """Save Live Excel settings and hot-reload the reader."""
    import asyncio
    from services.live_excel_reader import reader

    updates = {
        "enabled":      "true" if body.enabled else "false",
        "workbook":     body.workbook.strip(),
        "worksheet":    body.worksheet.strip(),
        "header_row":   str(body.header_row),
        "data_start":   str(body.data_start),
        "datetime_col": body.datetime_col.strip().upper(),
        "temp_col":     body.temp_col.strip().upper(),
        "pressure_col": body.pressure_col.strip().upper(),
        "ph_col":       body.ph_col.strip().upper(),
        "poll_ms":      str(body.poll_ms),
    }
    reader.settings.update(updates)
    reader.save_settings_to_db(updates)

    loop = asyncio.get_event_loop()
    if body.enabled:
        if reader.running:
            reader.stop()
        reader.start(loop)
        logger.info("[LiveExcel] Settings saved and reader (re)started")
    else:
        if reader.running:
            reader.stop()
            logger.info("[LiveExcel] Settings saved and reader stopped")

    return {
        "saved":   True,
        "running": reader.running,
        "enabled": body.enabled,
    }


@router.get("/status", dependencies=[Depends(require_admin)])
async def get_status():
    """Return current reader status."""
    from services.live_excel_reader import reader
    return reader.get_status()


@router.get("/workbooks", dependencies=[Depends(require_admin)])
async def list_workbooks():
    """Return a list of workbooks currently open in Excel."""
    import asyncio
    from services.live_excel_reader import reader
    loop = asyncio.get_event_loop()
    names = await loop.run_in_executor(None, reader.list_open_workbooks)
    return {"workbooks": names}


@router.post("/test", dependencies=[Depends(require_admin)])
async def test_connection():
    """Test the COM connection and return a diagnostic report."""
    import asyncio
    from services.live_excel_reader import reader
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, reader.test_connection)
    return result


@router.post("/start", dependencies=[Depends(require_admin)])
async def start_reader():
    """Start the Live Excel reader."""
    import asyncio
    from services.live_excel_reader import reader
    if reader.running:
        return {"started": False, "message": "Already running"}
    if not reader.settings.get("workbook", "").strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Workbook name must be configured before starting."},
        )
    loop = asyncio.get_event_loop()
    reader.start(loop)
    reader.save_settings_to_db({"enabled": "true"})
    reader.settings["enabled"] = "true"
    logger.info("[LiveExcel] Reader started via API")
    return {"started": True, "message": "Live Excel reader started"}


@router.post("/stop", dependencies=[Depends(require_admin)])
async def stop_reader():
    """Stop the Live Excel reader."""
    from services.live_excel_reader import reader
    if not reader.running:
        return {"stopped": False, "message": "Not running"}
    reader.stop()
    reader.save_settings_to_db({"enabled": "false"})
    reader.settings["enabled"] = "false"
    logger.info("[LiveExcel] Reader stopped via API")
    return {"stopped": True, "message": "Live Excel reader stopped"}

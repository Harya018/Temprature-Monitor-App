"""
config.py — SentinelEdge configuration loader.

Loads .env.<APP_ENV> (default: .env.development) via python-dotenv.
RUNTIME_THRESHOLDS is a mutable dict updated at runtime without restart.
MODULE_STATUS tracks per-module health for the /api/health endpoint.

Alert modules: In-app WebSocket, Email (SMTP), SMS (Android Gateway).

Sensor modes:
  DEMO_MODE=true  → CSVSensorPlayer (CSV file playback, no hardware needed)
  DEMO_MODE=false → SerialSensorReader (live USB temp sensor via SENSOR_PORT)
"""

import os
from dotenv import load_dotenv

# ── Environment selection ─────────────────────────────────────────────────────
APP_ENV: str = os.getenv("APP_ENV", "development")
APP_VERSION: str = "1.0.0"

# Resolve path relative to project root (two levels up from backend/config.py)
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(dotenv_path=os.path.join(_root, f".env.{APP_ENV}"))

# ── Threshold defaults ────────────────────────────────────────────────────────
# Industrial cooling process:
#   HIGH = 90.0°C  — overheating danger
#   LOW  = 42.0°C  — machine cooled and ready for next process
TEMP_THRESHOLD_HIGH: float = float(os.getenv("TEMP_THRESHOLD_HIGH", "90.0"))
TEMP_THRESHOLD_LOW: float  = float(os.getenv("TEMP_THRESHOLD_LOW",  "42.0"))

# ── SMTP ──────────────────────────────────────────────────────────────────────
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")

# ── Android SMS Gateway ───────────────────────────────────────────────────────
SMS_GATEWAY_URL: str = os.getenv("SMS_GATEWAY_URL", "http://192.168.1.100:8080")
SMS_GATEWAY_USER: str = os.getenv("SMS_GATEWAY_USER", "admin")
SMS_GATEWAY_PASS: str = os.getenv("SMS_GATEWAY_PASS", "password")

# ── SMS Transport Method ───────────────────────────────────────────────────────
# "adb"     — Android phone via Termux HTTP (demo / development)
# "gammu"   — USB GSM modem via Gammu library (production)
# "gateway" — Android SMS Gateway REST API
# "sim7600" — SIM7600 EI 4G HAT via USB serial AT commands (production)
SMS_METHOD: str      = os.getenv("SMS_METHOD", "adb")
SMS_ADB_SERIAL: str  = os.getenv("SMS_ADB_SERIAL", "")        # e.g. "emulator-5554" or ""
SMS_GAMMU_PORT: str  = os.getenv("SMS_GAMMU_PORT", "COM3")    # Windows: COM3, Linux: /dev/ttyUSB0
SMS_GAMMU_BAUD: int  = int(os.getenv("SMS_GAMMU_BAUD", "9600"))

# ── SIM7600 EI 4G HAT (USB serial / AT commands) ──────────────────────────────
# Used when SMS_METHOD=sim7600.
# Leave SMS_SIM7600_PORT empty to enable auto-detection (scans for SimCom USB device).
# Windows typical: COM4, COM5  |  Linux typical: /dev/ttyUSB2
SMS_SIM7600_PORT: str = os.getenv("SMS_SIM7600_PORT", "")      # empty → auto-detect
SMS_SIM7600_BAUD: int = int(os.getenv("SMS_SIM7600_BAUD", "115200"))  # SIM7600 default

# ── Escalation / Cooldown ─────────────────────────────────────────────────────
ESCALATION_TIMEOUT_SECONDS: int = int(os.getenv("ESCALATION_TIMEOUT_SECONDS", "60"))
DEMO_ESCALATION_TIMEOUT: int     = int(os.getenv("DEMO_ESCALATION_TIMEOUT", "15"))
ALERT_COOLDOWN_SECONDS: int      = int(os.getenv("ALERT_COOLDOWN_SECONDS", "10"))

# ── VAPID (Web Push) ──────────────────────────────────────────────────────────
VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIM_EMAIL: str = os.getenv("VAPID_CLAIM_EMAIL", "admin@sentineledge.local")

# ── FCM (direct, mobile app alarm push) ────────────────────────────────────────
# Service account key downloaded from Firebase Console → Project Settings →
# Service Accounts. Same credential uploaded to EAS for build-time push
# config — this is the server-side copy used to call FCM's HTTP v1 API
# directly (bypassing Expo's push relay) for maximum delivery priority.
FCM_SERVICE_ACCOUNT_PATH: str = os.getenv(
    "FCM_SERVICE_ACCOUNT_PATH",
    os.path.join(os.path.dirname(__file__), "secrets", "firebase-adminsdk.json"),
)

# ── Server ────────────────────────────────────────────────────────────────────
SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "5000"))

# ── Demo mode ─────────────────────────────────────────────────────────────────
DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")

# ── USB Temperature Sensor (Serial/COM port) ──────────────────────────────────
# Only used when DEMO_MODE=false. Set to the COM port of the USB sensor.
# Windows: COM3, COM4, etc.   Linux: /dev/ttyUSB0, /dev/ttyACM0
SENSOR_PORT: str = os.getenv("SENSOR_PORT", "COM3")
SENSOR_BAUD: int = int(os.getenv("SENSOR_BAUD", "9600"))

# ── Excel file sensor (pro-server / HMI data via .xlsx) ──────────────────────
# Leave EXCEL_FILE_PATH empty to use the normal serial/CSV sensor.
# Set it to the absolute path of the Excel file the pro server is writing to
# (e.g. C:\ProServer\data\readings.xlsx) to switch to Excel mode.
# ── Pro-face Pro-Server EX live data reader ───────────────────────────────────
# Set EXCEL_FILE_PATH to the absolute path of the CSV or Excel file that
# Pro-Server EX is writing to.  Leave it empty to use the normal serial sensor.
#
# Pro-Server EX default CSV columns:
#   Date | Time | <your item names configured in GP-Pro EX>
#
# Match EXCEL_TEMP_COL exactly to the temperature column header in your file.
# EXCEL_DATE_COL and EXCEL_TIME_COL are used to reconstruct the timestamp.
# All other numeric columns become extra parameters (pH, DO, etc.) automatically.
EXCEL_FILE_PATH     : str   = os.getenv("EXCEL_FILE_PATH",     "")
EXCEL_TEMP_COL      : str   = os.getenv("EXCEL_TEMP_COL",      "Temperature")
EXCEL_DATE_COL      : str   = os.getenv("EXCEL_DATE_COL",      "Date")
EXCEL_TIME_COL      : str   = os.getenv("EXCEL_TIME_COL",      "Time")
EXCEL_TIMESTAMP_COL : str   = os.getenv("EXCEL_TIMESTAMP_COL", "")   # leave blank for Pro-Server EX
EXCEL_SHEET         : str   = os.getenv("EXCEL_SHEET",         "0")  # Excel only
EXCEL_POLL_INTERVAL : float = float(os.getenv("EXCEL_POLL_INTERVAL", "1.0"))
EXCEL_ENCODING      : str   = os.getenv("EXCEL_ENCODING",      "")   # auto-detect if blank

# ── Admin credentials ─────────────────────────────────────────────────────────
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "sentineledge-admin")
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")

# ── Runtime-mutable thresholds ────────────────────────────────────────────────
# Updated via POST /api/config/thresholds without restarting the server.
# Flat format used internally by the threshold engine.
RUNTIME_THRESHOLDS: dict = {
    "temp_high": TEMP_THRESHOLD_HIGH,
    "temp_low":  TEMP_THRESHOLD_LOW,
    # Nested view for convenience (mirrors flat keys above)
    "temperature": {
        "high": TEMP_THRESHOLD_HIGH,
        "low":  TEMP_THRESHOLD_LOW,
    },
}

# Tracks whether RUNTIME_THRESHOLDS have been overridden at runtime
RUNTIME_SOURCE: str = "default"        # "default" | "runtime_override"
RUNTIME_LAST_CHANGED: str = ""         # ISO timestamp, set on override

# Default threshold snapshot for reset
DEFAULT_THRESHOLDS: dict = {
    "temp_high": TEMP_THRESHOLD_HIGH,
    "temp_low":  TEMP_THRESHOLD_LOW,
}

# ── Module health status ───────────────────────────────────────────────────────
# Three alert modules: in-app WebSocket, email, SMS.
MODULE_STATUS: dict = {
    "sensor": "starting",
    "database": "starting",
    "email": "not_built",
    "sms": "not_built",
    "websocket": "starting",
}

# ── Live counters (updated by WebSocket manager) ──────────────────────────────
CONNECTED_CLIENTS: int = 0

# ── Server start time (used for /api/health uptime calculation) ───────────────
import datetime as _dt
SERVER_START_TIME: _dt.datetime = _dt.datetime.utcnow()

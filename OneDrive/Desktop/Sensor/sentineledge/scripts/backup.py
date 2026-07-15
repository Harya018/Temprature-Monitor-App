"""
SentinelEdge — Nightly PostgreSQL Backup to Google Drive
---------------------------------------------------------
Runs pg_dump, saves a timestamped .sql file locally,
uploads it to a Google Drive folder, then deletes local
backups older than 7 days.

SETUP (fill in before deploying to client machine):
  1. GDRIVE_EMAIL     — Google account email
  2. GDRIVE_PASSWORD  — App Password (NOT the Gmail login password)
                        Generate at: myaccount.google.com/apppasswords
                        (Requires 2FA enabled on the Google account)
  3. GDRIVE_FOLDER_ID — Google Drive folder ID
                        Open the folder in browser, copy the ID from URL:
                        drive.google.com/drive/folders/THIS_PART_IS_THE_ID
"""

import os
import sys
import subprocess
import datetime
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

# Load from .env if present (navigate up from scripts/ to project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.development")

# PostgreSQL connection details
PG_HOST     = os.getenv("DB_HOST", "localhost")
PG_PORT     = os.getenv("DB_PORT", "5432")
PG_DB       = os.getenv("DB_NAME", "sentineledge")
PG_USER     = os.getenv("DB_USER", "postgres")
PG_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

# rclone settings
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE", "gdrive")
RCLONE_PATH   = os.getenv("RCLONE_PATH", "sentineledge-backups")

# pg_dump path
PG_DUMP_PATH = os.getenv("PG_DUMP_PATH", r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe")

# Local backup folder (keeps last 7 days)
BACKUP_DIR = PROJECT_ROOT / "backups"

# Developer email for error notifications
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "")


def log(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}")


def send_error_email(subject: str, body: str):
    """Send error notification to developer if backup fails."""
    if not ALERT_EMAIL:
        log("ALERT_EMAIL not configured — skipping error notification.")
        return
        
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASSWORD", "")
    
    if not SMTP_USER or not SMTP_PASS:
        log("SMTP credentials missing in .env — skipping error notification.")
        return

    try:
        msg = MIMEText(body)
        msg["Subject"] = f"[SentinelEdge] Backup FAILED — {subject}"
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        log("Error notification sent to developer.")
    except Exception as e:
        log(f"Could not send error email: {e}")


def run_pg_dump() -> Path:
    """Run pg_dump and return path to the .sql file."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"sentineledge_backup_{timestamp}.sql"

    env = os.environ.copy()
    env["PGPASSWORD"] = PG_PASSWORD

    log(f"Running pg_dump → {backup_file.name}")
    result = subprocess.run(
        [
            PG_DUMP_PATH,
            "-h", PG_HOST,
            "-p", PG_PORT,
            "-U", PG_USER,
            "-d", PG_DB,
            "-f", str(backup_file),
            "--no-password"
        ],
        env=env,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed:\n{result.stderr}")

    size_kb = backup_file.stat().st_size // 1024
    log(f"pg_dump complete — {size_kb} KB")
    return backup_file






def upload_via_rclone(backup_file: Path):
    """
    Upload using rclone — simpler and more reliable than OAuth.
    rclone must be configured once with: rclone config
    Remote name must be 'gdrive' pointing to Google Drive folder.
    """
    log(f"Uploading via rclone → {RCLONE_REMOTE}:{RCLONE_PATH}/")
    result = subprocess.run(
        [
            "rclone", "copy",
            str(backup_file),
            f"{RCLONE_REMOTE}:{RCLONE_PATH}/",
            "--log-level", "INFO"
        ],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"rclone upload failed:\n{result.stderr}")
    log(f"Upload complete: {backup_file.name}")


def delete_old_backups(keep_days: int = 7):
    """Delete local backups older than keep_days."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
    deleted = 0
    if not BACKUP_DIR.exists():
        return
        
    for f in BACKUP_DIR.glob("sentineledge_backup_*.sql"):
        if f.is_file():
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
    if deleted:
        log(f"Deleted {deleted} old backup(s) older than {keep_days} days.")


def main():
    log("=" * 50)
    log("SentinelEdge Nightly Backup Starting")
    log("=" * 50)

    try:
        # Step 1: pg_dump
        backup_file = run_pg_dump()

        # Step 2: Upload to Google Drive via rclone
        # rclone is simpler than OAuth — configure once with: rclone config
        upload_via_rclone(backup_file)

        # Step 3: Clean up old local backups
        delete_old_backups(keep_days=7)

        log("=" * 50)
        log("Backup completed successfully.")
        log("=" * 50)

    except Exception as e:
        log(f"BACKUP FAILED: {e}")
        send_error_email(str(e), str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()

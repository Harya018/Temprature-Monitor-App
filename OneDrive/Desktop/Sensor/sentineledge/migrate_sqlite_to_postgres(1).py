"""
migrate_sqlite_to_postgres.py — One-time data migration from SQLite → PostgreSQL.

Reads all data from the existing sentineledge.db SQLite file and inserts it
into the PostgreSQL database in the correct order (respecting foreign key
relationships).

Usage:
    python migrate_sqlite_to_postgres.py

Safe to run multiple times — uses INSERT ... ON CONFLICT DO NOTHING so
re-running will not create duplicates.

Migration order (FK dependencies):
    1. admins          (no FK)
    2. subscribers     (no FK)
    3. config_changes  (no FK)
    4. readings        (no FK)
    5. alerts          (no FK, but logically first)
    6. escalation_log  → alerts.id
    7. delivery_receipts → alerts.id
    8. admin_sessions  (no FK — new table, likely empty in SQLite)
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

# ── Resolve paths ─────────────────────────────────────────────────────────────
_SCRIPT_DIR  = Path(__file__).resolve().parent
_SQLITE_PATH = _SCRIPT_DIR / "database" / "sentineledge.db"

_PG_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sentineledge:sentineledge123@localhost:5432/sentineledge",
)


def _check_sqlite() -> None:
    if not _SQLITE_PATH.exists():
        print(f"[ERROR] SQLite database not found at: {_SQLITE_PATH}")
        print("        Migration aborted — nothing to migrate.")
        sys.exit(1)


def _get_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _get_pg_conn() -> psycopg2.extensions.connection:
    try:
        conn = psycopg2.connect(_PG_URL)
        conn.autocommit = False
        return conn
    except psycopg2.OperationalError as exc:
        print(f"[ERROR] Could not connect to PostgreSQL: {exc}")
        print(f"        URL: {_PG_URL}")
        print("        Is PostgreSQL running? Did you run setup_postgres.bat?")
        sys.exit(1)


def _migrate_table(
    lite_conn: sqlite3.Connection,
    pg_conn: psycopg2.extensions.connection,
    table: str,
    columns: list[str],
    conflict_target: str = "id",
) -> int:
    """
    Copy all rows from a SQLite table into the matching PostgreSQL table.

    Uses INSERT ... ON CONFLICT (conflict_target) DO NOTHING so this is
    safe to run multiple times without creating duplicates.

    Returns the number of rows inserted.
    """
    print(f"  Migrating {table}...", end=" ", flush=True)

    # Read all rows from SQLite
    cur = lite_conn.cursor()
    cur.execute(f"SELECT {', '.join(columns)} FROM {table}")
    rows = cur.fetchall()

    if not rows:
        print("0 rows (table is empty)")
        return 0

    print(f"{len(rows)} rows...", end=" ", flush=True)

    col_list   = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    sql = (
        f"INSERT INTO {table} ({col_list}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_target}) DO NOTHING"
    )

    with pg_conn.cursor() as pg_cur:
        # Use executemany for bulk insert
        pg_cur.executemany(sql, [tuple(row) for row in rows])

    pg_conn.commit()
    print("done ✓")
    return len(rows)


def _table_exists(lite_conn: sqlite3.Connection, table: str) -> bool:
    cur = lite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def _get_columns(lite_conn: sqlite3.Connection, table: str) -> list[str]:
    """Return column names that actually exist in the SQLite table."""
    cur = lite_conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def migrate() -> None:
    print()
    print("=" * 60)
    print("  SentinelEdge — SQLite → PostgreSQL Data Migration")
    print("=" * 60)
    print(f"  Source : {_SQLITE_PATH}")
    print(f"  Target : {_PG_URL}")
    print()

    _check_sqlite()

    lite = _get_sqlite_conn()
    pg   = _get_pg_conn()

    total = 0

    # ── 1. admins ─────────────────────────────────────────────────────────────
    if _table_exists(lite, "admins"):
        cols = _get_columns(lite, "admins")
        # Only include columns that exist in both SQLite and PG schema
        wanted = ["id", "name", "password_hash", "role", "created_at"]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "admins", actual)

    # ── 2. subscribers ────────────────────────────────────────────────────────
    if _table_exists(lite, "subscribers"):
        cols = _get_columns(lite, "subscribers")
        # is_active may not exist in old SQLite schema
        wanted = ["id", "name", "phone", "email", "pin",
                  "escalation_order", "active", "is_active", "created_at"]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "subscribers", actual)

    # ── 3. config_changes ─────────────────────────────────────────────────────
    if _table_exists(lite, "config_changes"):
        cols = _get_columns(lite, "config_changes")
        wanted = ["id", "changed_by", "field_name", "old_value", "new_value", "changed_at"]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "config_changes", actual)

    # ── 4. readings ───────────────────────────────────────────────────────────
    if _table_exists(lite, "readings"):
        cols = _get_columns(lite, "readings")
        wanted = ["id", "temperature", "timestamp", "is_valid"]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "readings", actual)

    # ── 5. alerts ─────────────────────────────────────────────────────────────
    if _table_exists(lite, "alerts"):
        cols = _get_columns(lite, "alerts")
        wanted = [
            "id", "parameter", "value", "threshold", "direction", "severity",
            "timestamp", "acknowledged", "acknowledged_by", "acknowledged_at",
            "escalation_level", "max_escalated", "cooldown_until",
        ]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "alerts", actual)

    # ── 6. escalation_log ─────────────────────────────────────────────────────
    if _table_exists(lite, "escalation_log"):
        cols = _get_columns(lite, "escalation_log")
        wanted = ["id", "alert_id", "escalation_level", "subscriber_id",
                  "sent_at", "channel", "success"]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "escalation_log", actual)

    # ── 7. delivery_receipts ──────────────────────────────────────────────────
    if _table_exists(lite, "delivery_receipts"):
        cols = _get_columns(lite, "delivery_receipts")
        wanted = ["id", "alert_id", "channel", "subscriber_id",
                  "escalation_level", "sent_at", "success", "error_message"]
        actual = [c for c in wanted if c in cols]
        total += _migrate_table(lite, pg, "delivery_receipts", actual)

    # ── 8. Reset sequences so new rows get correct IDs ─────────────────────────
    print("\n  Resetting PostgreSQL sequences...", end=" ", flush=True)
    tables_with_serial = [
        "admins", "subscribers", "config_changes", "readings",
        "alerts", "escalation_log", "delivery_receipts",
    ]
    with pg.cursor() as cur:
        for tbl in tables_with_serial:
            cur.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{tbl}', 'id'),
                    COALESCE((SELECT MAX(id) FROM {tbl}), 0) + 1,
                    false
                )
                """
            )
    pg.commit()
    print("done ✓")

    lite.close()
    pg.close()

    print()
    print("=" * 60)
    print(f"  Migration complete! {total} total rows migrated.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    migrate()

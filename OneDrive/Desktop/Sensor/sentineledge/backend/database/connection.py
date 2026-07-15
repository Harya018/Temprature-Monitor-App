"""
database/connection.py — PostgreSQL connection pool for SentinelEdge.

Replaces the SQLite single-connection approach with a psycopg2
ThreadedConnectionPool (min=2, max=20) so 100+ concurrent workers
never exhaust connections.

All queries use RealDictCursor so rows are returned as plain dicts —
identical behaviour to the old sqlite3.Row factory.

Public API:
    get_db_pool()       → ThreadedConnectionPool (initialises on first call)
    close_db_pool()     → closes all pool connections on app shutdown
    execute_write()     → thread-safe INSERT/UPDATE/DELETE, returns _WriteResult
    execute_read()      → thread-safe SELECT, returns list[dict]
    init_db()           → create schema + indexes on startup
"""

from __future__ import annotations

import os
import threading
from typing import Optional

import psycopg2
import psycopg2.pool
import psycopg2.extras
import psycopg2.extensions

from utils.logger import get_logger
from config import MODULE_STATUS

logger = get_logger(__name__)

# ── Database URL ──────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://sentineledge:sentineledge123@localhost:5432/sentineledge",
)

# ── Connection Pool ───────────────────────────────────────────────────────────
_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


class _WriteResult:
    """
    Thin result wrapper returned by execute_write().

    Captures rowcount and lastrowid (from RETURNING id) before the
    cursor is closed, so callers use the same API as before:
        cur = execute_write(...)
        return cur.lastrowid   # for INSERTs
        cur.rowcount           # for UPDATE/DELETE
    """
    __slots__ = ("rowcount", "lastrowid")

    def __init__(self, rowcount: int, lastrowid: Optional[int]) -> None:
        self.rowcount = rowcount
        self.lastrowid = lastrowid


def get_db_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Return the shared connection pool, initialising it on first call."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                logger.info("Initialising PostgreSQL connection pool ...")
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=20,
                    dsn=DATABASE_URL,
                )
                logger.info("PostgreSQL connection pool ready (min=2, max=20, dsn=%s)", DATABASE_URL)
    return _pool


def close_db_pool() -> None:
    """Close all connections in the pool. Call on application shutdown."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")


def execute_write(sql: str, params: tuple = ()) -> _WriteResult:
    """
    Execute an INSERT, UPDATE, or DELETE inside a transaction.

    If the SQL contains RETURNING, the first column of the first
    returned row is captured as `lastrowid` (typically `id`).

    Returns a _WriteResult with `.lastrowid` and `.rowcount`.
    Rolls back automatically on any exception.
    """
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rowcount = cur.rowcount
            lastrowid: Optional[int] = None
            if "RETURNING" in sql.upper():
                row = cur.fetchone()
                if row:
                    row_dict = dict(row)
                    # Grab 'id' if present; otherwise first column value
                    lastrowid = row_dict.get("id") or next(iter(row_dict.values()), None)
            conn.commit()
        return _WriteResult(rowcount=rowcount, lastrowid=lastrowid)
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def execute_read(sql: str, params: tuple = ()) -> list[dict]:
    """
    Execute a SELECT (or UPDATE ... RETURNING) and return all rows as
    a list of plain dicts.
    """
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        pool.putconn(conn)


# ── Schema (PostgreSQL syntax) ────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    id          SERIAL          PRIMARY KEY,
    temperature DOUBLE PRECISION NOT NULL,
    timestamp   TEXT            NOT NULL,
    is_valid    INTEGER         DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
    id               SERIAL           PRIMARY KEY,
    parameter        TEXT             NOT NULL,
    value            DOUBLE PRECISION NOT NULL,
    threshold        DOUBLE PRECISION NOT NULL,
    direction        TEXT             NOT NULL,
    severity         TEXT             NOT NULL DEFAULT 'WARNING',
    timestamp        TEXT             NOT NULL,
    acknowledged     INTEGER          DEFAULT 0,
    acknowledged_by  TEXT,
    acknowledged_at  TEXT,
    escalation_level INTEGER          DEFAULT 1,
    max_escalated    INTEGER          DEFAULT 0,
    cooldown_until   TEXT
);

CREATE TABLE IF NOT EXISTS subscribers (
    id               SERIAL  PRIMARY KEY,
    name             TEXT    NOT NULL,
    phone            TEXT    NOT NULL,
    email            TEXT    NOT NULL,
    pin              TEXT    DEFAULT NULL,
    escalation_order INTEGER NOT NULL UNIQUE,
    active           INTEGER DEFAULT 1,
    is_active        INTEGER DEFAULT 1,
    created_at       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS escalation_log (
    id               SERIAL  PRIMARY KEY,
    alert_id         INTEGER NOT NULL,
    escalation_level INTEGER NOT NULL,
    subscriber_id    INTEGER NOT NULL,
    sent_at          TEXT    NOT NULL,
    channel          TEXT    NOT NULL,
    success          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_receipts (
    id               SERIAL  PRIMARY KEY,
    alert_id         INTEGER NOT NULL,
    channel          TEXT    NOT NULL,
    subscriber_id    INTEGER NOT NULL,
    escalation_level INTEGER NOT NULL,
    sent_at          TEXT    NOT NULL,
    success          INTEGER NOT NULL,
    error_message    TEXT
);

CREATE TABLE IF NOT EXISTS config_changes (
    id          SERIAL PRIMARY KEY,
    changed_by  TEXT   NOT NULL,
    field_name  TEXT   NOT NULL,
    old_value   TEXT   NOT NULL,
    new_value   TEXT   NOT NULL,
    changed_at  TEXT   NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    id            SERIAL PRIMARY KEY,
    name          TEXT   NOT NULL UNIQUE,
    password_hash TEXT   NOT NULL,
    role          TEXT   NOT NULL DEFAULT 'sub',
    created_at    TEXT   NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id           SERIAL      PRIMARY KEY,
    token        TEXT        NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_alerts_timestamp
    ON alerts(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged
    ON alerts(acknowledged);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp
    ON readings(timestamp);
CREATE INDEX IF NOT EXISTS idx_subscribers_order
    ON subscribers(escalation_order);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_token
    ON admin_sessions(token);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires
    ON admin_sessions(expires_at);
"""


def _run_migrations(pool: psycopg2.pool.ThreadedConnectionPool) -> None:
    """
    Apply schema migrations using PostgreSQL information_schema.

    Adds any columns or tables that were introduced after the initial
    deployment without touching existing data.
    """
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:

            # Helper: check if a column exists in a table
            def col_exists(table: str, column: str) -> bool:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = %s AND column_name = %s
                    """,
                    (table, column),
                )
                return cur.fetchone() is not None

            # Helper: check if a table exists
            def table_exists(table: str) -> bool:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = %s
                    """,
                    (table,),
                )
                return cur.fetchone() is not None

            # Migration 1: readings.is_valid
            if table_exists("readings") and not col_exists("readings", "is_valid"):
                cur.execute("ALTER TABLE readings ADD COLUMN is_valid INTEGER DEFAULT 1")
                logger.info("Migration: added is_valid column to readings")

            # Migration 2: alerts.severity
            if table_exists("alerts") and not col_exists("alerts", "severity"):
                cur.execute(
                    "ALTER TABLE alerts ADD COLUMN severity TEXT NOT NULL DEFAULT 'WARNING'"
                )
                logger.info("Migration: added severity column to alerts")

            # Migration 3: alerts.max_escalated
            if table_exists("alerts") and not col_exists("alerts", "max_escalated"):
                cur.execute(
                    "ALTER TABLE alerts ADD COLUMN max_escalated INTEGER DEFAULT 0"
                )
                logger.info("Migration: added max_escalated column to alerts")

            # Migration 4: alerts.cooldown_until
            if table_exists("alerts") and not col_exists("alerts", "cooldown_until"):
                cur.execute("ALTER TABLE alerts ADD COLUMN cooldown_until TEXT")
                logger.info("Migration: added cooldown_until column to alerts")

            # Migration 5: subscribers.pin
            if table_exists("subscribers") and not col_exists("subscribers", "pin"):
                cur.execute("ALTER TABLE subscribers ADD COLUMN pin TEXT DEFAULT NULL")
                logger.info("Migration: added pin column to subscribers")

            # Migration 6: subscribers.is_active
            if table_exists("subscribers") and not col_exists("subscribers", "is_active"):
                cur.execute(
                    "ALTER TABLE subscribers ADD COLUMN is_active INTEGER DEFAULT 1"
                )
                cur.execute("UPDATE subscribers SET is_active = active")
                logger.info("Migration: added is_active column to subscribers")

            # Migration 8: subscriber profile fields
            _sub_profile_cols = [
                ("employee_id",  "TEXT"),
                ("department",   "TEXT"),
                ("designation",  "TEXT"),
                ("shift_timing", "TEXT"),
                ("address",      "TEXT"),
            ]
            if table_exists("subscribers"):
                for _col, _ctype in _sub_profile_cols:
                    if not col_exists("subscribers", _col):
                        cur.execute(
                            f"ALTER TABLE subscribers ADD COLUMN {_col} {_ctype}"
                        )
                        logger.info("Migration: added %s column to subscribers", _col)

            # Migration 7: admin_sessions table
            if not table_exists("admin_sessions"):
                cur.execute("""
                    CREATE TABLE admin_sessions (
                        id           SERIAL      PRIMARY KEY,
                        token        TEXT        NOT NULL UNIQUE,
                        created_at   TIMESTAMPTZ DEFAULT NOW(),
                        expires_at   TIMESTAMPTZ NOT NULL,
                        last_used_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE INDEX idx_admin_sessions_token ON admin_sessions(token)"
                )
                cur.execute(
                    "CREATE INDEX idx_admin_sessions_expires ON admin_sessions(expires_at)"
                )
                logger.info("Migration: created admin_sessions table")

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning("Migration warning: %s", exc)
    finally:
        pool.putconn(conn)


def init_db() -> None:
    """Create all tables and indexes if they do not already exist."""
    try:
        pool = get_db_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                # Execute each statement individually (executescript not available in psycopg2)
                for statement in _SCHEMA_SQL.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        cur.execute(stmt)
            conn.commit()
        finally:
            pool.putconn(conn)

        _run_migrations(pool)
        migrate_pins_to_bcrypt()  # idempotent: skips already-bcrypt rows
        logger.info("Database initialised (PostgreSQL).")
        MODULE_STATUS["database"] = "ok"
    except Exception as exc:
        logger.exception("Failed to initialise database: %s", exc)
        MODULE_STATUS["database"] = f"error: {exc}"
        raise


def migrate_pins_to_bcrypt() -> None:
    """
    One-time migration: upgrade any SHA-256 (or plain-text) stored credentials
    to bcrypt.  Idempotent — bcrypt hashes start with '$2b$' so already-migrated
    rows are skipped automatically.

    Covers:
      - admins.password_hash  (sub-admin accounts)
      - subscribers.pin       (subscriber mobile-app PINs)

    Called at the end of init_db() on every startup; safe to call multiple times.
    """
    # Late import to avoid circular import at module load time
    from utils.security import hash_pin, verify_pin  # noqa: F401

    pool = get_db_pool()

    # ── Admins ────────────────────────────────────────────────────────────────
    try:
        rows = execute_read(
            "SELECT id, password_hash FROM admins"
        )
        migrated_admins = 0
        for row in rows:
            ph = row.get("password_hash", "")
            if ph and not ph.startswith("$2b$"):
                # Hash the currently stored value (plain or sha256 hex)
                new_hash = hash_pin(ph)
                execute_write(
                    "UPDATE admins SET password_hash = %s WHERE id = %s",
                    (new_hash, row["id"]),
                )
                migrated_admins += 1
        if migrated_admins:
            logger.info("Migrated %d admin password(s) to bcrypt", migrated_admins)
    except Exception as exc:
        logger.warning("migrate_pins_to_bcrypt (admins) failed: %s", exc)

    # ── Subscribers ──────────────────────────────────────────────────────────
    try:
        rows = execute_read(
            "SELECT id, pin FROM subscribers WHERE pin IS NOT NULL"
        )
        migrated_subs = 0
        for row in rows:
            stored = row.get("pin", "")
            if stored and not stored.startswith("$2b$"):
                new_hash = hash_pin(stored)
                execute_write(
                    "UPDATE subscribers SET pin = %s WHERE id = %s",
                    (new_hash, row["id"]),
                )
                migrated_subs += 1
        if migrated_subs:
            logger.info("Migrated %d subscriber PIN(s) to bcrypt", migrated_subs)
    except Exception as exc:
        logger.warning("migrate_pins_to_bcrypt (subscribers) failed: %s", exc)


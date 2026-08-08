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
import time
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

_DB_RECONNECT_ATTEMPTS = 10
_DB_RECONNECT_DELAY    = 5
_DB_HEALTH_INTERVAL    = 60


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


def get_db_pool() -> Optional[psycopg2.pool.ThreadedConnectionPool]:
    """
    Return the shared connection pool, initialising it on first call.

    On failure, retries up to _DB_RECONNECT_ATTEMPTS times with
    _DB_RECONNECT_DELAY seconds between each attempt.  After all attempts
    fail, logs CRITICAL and returns None.  Callers must handle None.
    """
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        for attempt in range(1, _DB_RECONNECT_ATTEMPTS + 1):
            try:
                logger.info("DB reconnect attempt %d/%d...", attempt, _DB_RECONNECT_ATTEMPTS)
                new_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=2,
                    maxconn=20,
                    dsn=DATABASE_URL,
                )
                _pool = new_pool
                MODULE_STATUS["database"] = "ok"
                logger.info(
                    "DB reconnected successfully (pool ready, min=2, max=20, dsn=%s)",
                    DATABASE_URL,
                )
                return _pool
            except Exception as exc:
                logger.warning(
                    "DB reconnect attempt %d/%d failed: %s",
                    attempt, _DB_RECONNECT_ATTEMPTS, exc,
                )
                if attempt < _DB_RECONNECT_ATTEMPTS:
                    time.sleep(_DB_RECONNECT_DELAY)

        logger.critical(
            "DB: all %d reconnect attempts failed — "
            "server will keep running but DB queries will fail.",
            _DB_RECONNECT_ATTEMPTS,
        )
        MODULE_STATUS["database"] = "error: connection failed after max retries"
        return None


def close_db_pool() -> None:
    """Close all connections in the pool. Call on application shutdown."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed.")


def _invalidate_pool() -> None:
    """
    Discard the current broken pool so the next call to get_db_pool()
    triggers a fresh connection attempt.
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
            logger.warning("DB pool invalidated — will reconnect on next query")


def _db_health_ping_loop() -> None:
    """Background thread: ping DB every _DB_HEALTH_INTERVAL seconds."""
    while True:
        time.sleep(_DB_HEALTH_INTERVAL)
        pool = get_db_pool()
        if pool is None:
            continue   # already in failed state; get_db_pool() will retry on next query
        conn = None
        try:
            conn = pool.getconn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()
            if MODULE_STATUS.get("database") != "ok":
                MODULE_STATUS["database"] = "ok"
                logger.info("DB health ping: connection restored")
        except Exception as exc:
            logger.warning("DB health ping failed: %s — invalidating pool", exc)
            MODULE_STATUS["database"] = "error: ping failed"
            _invalidate_pool()
        finally:
            if conn is not None and pool is not None:
                try:
                    pool.putconn(conn)
                except Exception:
                    pass


# Start background health-ping thread at import time.
_db_health_thread = threading.Thread(
    target=_db_health_ping_loop,
    daemon=True,
    name="db-health-ping",
)
_db_health_thread.start()


def execute_write(sql: str, params: tuple = ()) -> _WriteResult:
    """
    Execute an INSERT, UPDATE, or DELETE inside a transaction.

    If the SQL contains RETURNING, the first column of the first
    returned row is captured as `lastrowid` (typically `id`).

    Returns a _WriteResult with `.lastrowid` and `.rowcount`.
    Rolls back automatically on any exception.
    Returns a zero-result WriteResult if the pool is unavailable.
    """
    pool = get_db_pool()
    if pool is None:
        logger.error("execute_write: DB pool unavailable — query skipped: %.80s", sql)
        return _WriteResult(rowcount=0, lastrowid=None)
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
    except psycopg2.OperationalError as exc:
        conn.rollback()
        logger.warning("execute_write: OperationalError — invalidating pool: %s", exc)
        _invalidate_pool()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def execute_read(sql: str, params: tuple = ()) -> list[dict]:
    """
    Execute a SELECT (or UPDATE ... RETURNING) and return all rows as
    a list of plain dicts.

    Always commits (harmless for pure SELECTs; required for UPDATE RETURNING)
    and rolls back on error so the pooled connection is always returned in a
    clean, ready-to-use state.
    Returns an empty list if the pool is unavailable.
    """
    pool = get_db_pool()
    if pool is None:
        logger.error("execute_read: DB pool unavailable — returning []: %.80s", sql)
        return []
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
        conn.commit()
        return rows
    except psycopg2.OperationalError as exc:
        conn.rollback()
        logger.warning("execute_read: OperationalError — invalidating pool: %s", exc)
        _invalidate_pool()
        raise
    except Exception:
        conn.rollback()
        raise
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

            # Migration 9: subscribers.expo_push_token (mobile app push notifications)
            if table_exists("subscribers") and not col_exists("subscribers", "expo_push_token"):
                cur.execute("ALTER TABLE subscribers ADD COLUMN expo_push_token TEXT DEFAULT NULL")
                logger.info("Migration: added expo_push_token column to subscribers")

            # Migration 10: subscribers.push_subscription (Web Push VAPID — was
            # referenced by core/escalation.py and database/queries/subscribers.py
            # but never actually added to the live schema, silently killing that channel)
            if table_exists("subscribers") and not col_exists("subscribers", "push_subscription"):
                cur.execute("ALTER TABLE subscribers ADD COLUMN push_subscription TEXT DEFAULT NULL")
                logger.info("Migration: added push_subscription column to subscribers")

            # Migration 11: subscribers.fcm_token — raw FCM registration token
            # (distinct from expo_push_token) for direct FCM HTTP v1 delivery,
            # bypassing Expo's push relay for maximum delivery priority.
            if table_exists("subscribers") and not col_exists("subscribers", "fcm_token"):
                cur.execute("ALTER TABLE subscribers ADD COLUMN fcm_token TEXT DEFAULT NULL")
                logger.info("Migration: added fcm_token column to subscribers")

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

            # Migration 12: companies table (multi-tenancy)
            if not table_exists("companies"):
                cur.execute("""
                    CREATE TABLE companies (
                        id         SERIAL PRIMARY KEY,
                        name       TEXT    NOT NULL,
                        slug       TEXT    NOT NULL UNIQUE,
                        is_active  INTEGER NOT NULL DEFAULT 1,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_slug ON companies(slug)"
                )
                logger.info("Migration 12: created companies table")

            # Migration 13: admins.company_id — which company this admin manages
            if table_exists("admins") and not col_exists("admins", "company_id"):
                cur.execute(
                    "ALTER TABLE admins ADD COLUMN company_id INTEGER REFERENCES companies(id)"
                )
                logger.info("Migration 13: added company_id to admins")

            # Migration 14: subscribers.company_id — which company this subscriber belongs to
            if table_exists("subscribers") and not col_exists("subscribers", "company_id"):
                cur.execute(
                    "ALTER TABLE subscribers ADD COLUMN company_id INTEGER REFERENCES companies(id)"
                )
                logger.info("Migration 14: added company_id to subscribers")

            # Migration 15: alerts.company_id — which company generated this alert
            if table_exists("alerts") and not col_exists("alerts", "company_id"):
                cur.execute(
                    "ALTER TABLE alerts ADD COLUMN company_id INTEGER REFERENCES companies(id)"
                )
                logger.info("Migration 15: added company_id to alerts")

            # Migration 16: seed default super admin
            cur.execute("SELECT COUNT(*) FROM admins WHERE role = 'super_admin'")
            res = cur.fetchone()
            count = res[0] if res else 0
            if count == 0:
                from utils.security import hash_pin
                from datetime import datetime, timezone
                hashed = hash_pin("admin123")
                ts = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "INSERT INTO admins (name, password_hash, role, created_at) VALUES (%s, %s, %s, %s)",
                    ("admin", hashed, "super_admin", ts),
                )
                logger.info("Migration 16: seeded default super_admin (admin / admin123)")

            # Migration 17: companies extra fields
            _company_extra_cols = [
                ("description",      "TEXT"),
                ("max_subscribers",  "INTEGER DEFAULT 100"),
                ("max_devices",      "INTEGER DEFAULT 10"),
                ("allowed_channels", "TEXT DEFAULT 'sms,email,push'"),
            ]
            if table_exists("companies"):
                for _col, _ctype in _company_extra_cols:
                    if not col_exists("companies", _col):
                        cur.execute(f"ALTER TABLE companies ADD COLUMN {_col} {_ctype}")
                        logger.info("Migration 17: added %s column to companies", _col)

            # Migrations 18-20: admin tracking columns
            _admin_track_cols = [
                ("is_active",     "INTEGER DEFAULT 1"),
                ("last_login_at", "TIMESTAMPTZ"),
                ("last_login_ip", "TEXT"),
            ]
            if table_exists("admins"):
                for _col, _ctype in _admin_track_cols:
                    if not col_exists("admins", _col):
                        cur.execute(f"ALTER TABLE admins ADD COLUMN {_col} {_ctype}")
                        logger.info("Migration 18-20: added %s column to admins", _col)

            # Migration 21: admin_activity table
            if not table_exists("admin_activity"):
                cur.execute("""
                    CREATE TABLE admin_activity (
                        id         SERIAL PRIMARY KEY,
                        admin_id   INTEGER NOT NULL,
                        company_id INTEGER,
                        action     TEXT NOT NULL,
                        entity     TEXT,
                        details    TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_admin_activity_admin ON admin_activity(admin_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_admin_activity_ts ON admin_activity(created_at)"
                )
                logger.info("Migration 21: created admin_activity table")

            # Migration 22: broadcasts table
            if not table_exists("broadcasts"):
                cur.execute("""
                    CREATE TABLE broadcasts (
                        id         SERIAL PRIMARY KEY,
                        title      TEXT NOT NULL,
                        message    TEXT NOT NULL,
                        sent_by    TEXT NOT NULL DEFAULT 'super_admin',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                logger.info("Migration 22: created broadcasts table")

            # Migration 23: rename default super_admin username from 'admin' to 'superadmin'
            cur.execute("SELECT name FROM admins WHERE role = 'super_admin' AND name = 'admin'")
            if cur.fetchone():
                cur.execute("UPDATE admins SET name = 'superadmin' WHERE role = 'super_admin' AND name = 'admin'")
                logger.info("Migration 23: renamed super_admin username from 'admin' to 'superadmin'")

            # Migration 24: companies maintenance mode (Phase 1 Command Center)
            _maintenance_cols = [
                ("maintenance_mode",   "INTEGER DEFAULT 0"),
                ("maintenance_until",  "TIMESTAMPTZ DEFAULT NULL"),
                ("maintenance_reason", "TEXT DEFAULT NULL"),
            ]
            if table_exists("companies"):
                for _col, _ctype in _maintenance_cols:
                    if not col_exists("companies", _col):
                        cur.execute(f"ALTER TABLE companies ADD COLUMN {_col} {_ctype}")
                        logger.info("Migration 24: added %s column to companies", _col)

            # Migration 25: Phase 2 Admin Control
            # 25a: pending_approvals table
            if not table_exists("pending_approvals"):
                cur.execute("""
                    CREATE TABLE pending_approvals (
                        id          SERIAL PRIMARY KEY,
                        admin_id    INTEGER NOT NULL REFERENCES admins(id),
                        action_type TEXT    NOT NULL,
                        payload     JSONB   NOT NULL DEFAULT '{}',
                        status      TEXT    NOT NULL DEFAULT 'pending',
                        reviewed_by INTEGER REFERENCES admins(id),
                        review_note TEXT,
                        created_at  TIMESTAMPTZ DEFAULT NOW(),
                        reviewed_at TIMESTAMPTZ
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_pending_approvals_admin ON pending_approvals(admin_id)"
                )
                logger.info("Migration 25a: created pending_approvals table")

            # 25b: admins approval + impersonation columns
            _phase2_admin_cols = [
                ("requires_approval",       "INTEGER DEFAULT 0"),
                ("impersonated_by",         "INTEGER REFERENCES admins(id)"),
                ("impersonation_expires_at","TIMESTAMPTZ"),
            ]
            if table_exists("admins"):
                for _col, _ctype in _phase2_admin_cols:
                    if not col_exists("admins", _col):
                        cur.execute(f"ALTER TABLE admins ADD COLUMN {_col} {_ctype}")
                        logger.info("Migration 25b: added %s column to admins", _col)

            # 25c: admin_sessions.admin_id — link sessions to the admin who created them
            if table_exists("admin_sessions") and not col_exists("admin_sessions", "admin_id"):
                cur.execute(
                    "ALTER TABLE admin_sessions ADD COLUMN admin_id INTEGER REFERENCES admins(id)"
                )
                logger.info("Migration 25c: added admin_id column to admin_sessions")

            # Migration 26: Phase 3 Global Configuration Control
            # 26a: named threshold templates
            if not table_exists("threshold_templates"):
                cur.execute("""
                    CREATE TABLE threshold_templates (
                        id          SERIAL PRIMARY KEY,
                        name        TEXT NOT NULL,
                        temp_high   REAL NOT NULL,
                        temp_low    REAL NOT NULL,
                        description TEXT DEFAULT NULL,
                        created_by  INTEGER DEFAULT NULL,
                        created_at  TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                logger.info("Migration 26a: created threshold_templates table")

            # 26b: per-company field-level config overrides (advisory locks)
            if not table_exists("company_config"):
                cur.execute("""
                    CREATE TABLE company_config (
                        id         SERIAL PRIMARY KEY,
                        company_id INTEGER REFERENCES companies(id),
                        field      TEXT NOT NULL,
                        value      TEXT NOT NULL,
                        locked     INTEGER DEFAULT 0,
                        set_by     INTEGER DEFAULT NULL,
                        set_at     TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(company_id, field)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_company_config_company ON company_config(company_id)"
                )
                logger.info("Migration 26b: created company_config table")

            # Migration 27: Phase 5 Communication & Relationship Management
            # 27a: direct messages per company
            if not table_exists("company_messages"):
                cur.execute("""
                    CREATE TABLE company_messages (
                        id         SERIAL PRIMARY KEY,
                        company_id INTEGER REFERENCES companies(id),
                        subject    TEXT NOT NULL,
                        body       TEXT NOT NULL,
                        sent_by    INTEGER REFERENCES admins(id),
                        sent_at    TIMESTAMPTZ DEFAULT NOW(),
                        read_at    TIMESTAMPTZ DEFAULT NULL
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_company_messages_company ON company_messages(company_id)"
                )
                logger.info("Migration 27a: created company_messages table")

            # 27b: CRM notes per company
            if not table_exists("company_notes"):
                cur.execute("""
                    CREATE TABLE company_notes (
                        id         SERIAL PRIMARY KEY,
                        company_id INTEGER REFERENCES companies(id),
                        content    TEXT NOT NULL,
                        created_by INTEGER REFERENCES admins(id),
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_company_notes_company ON company_notes(company_id)"
                )
                logger.info("Migration 27b: created company_notes table")

            # 27c: onboarding checklist per company
            if not table_exists("company_onboarding"):
                cur.execute("""
                    CREATE TABLE company_onboarding (
                        id         SERIAL PRIMARY KEY,
                        company_id INTEGER REFERENCES companies(id),
                        item       TEXT NOT NULL,
                        done       INTEGER DEFAULT 0,
                        created_by INTEGER REFERENCES admins(id),
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_company_onboarding_company ON company_onboarding(company_id)"
                )
                logger.info("Migration 27c: created company_onboarding table")

            # 27d: broadcasts scheduling columns
            if table_exists("broadcasts"):
                if not col_exists("broadcasts", "scheduled_at"):
                    cur.execute(
                        "ALTER TABLE broadcasts ADD COLUMN scheduled_at TIMESTAMPTZ DEFAULT NULL"
                    )
                    logger.info("Migration 27d: added scheduled_at to broadcasts")
                if not col_exists("broadcasts", "status"):
                    cur.execute(
                        "ALTER TABLE broadcasts ADD COLUMN status TEXT DEFAULT 'sent'"
                    )
                    logger.info("Migration 27d: added status to broadcasts")

            # Migration 28: Phase 6 Billing & Business Layer
            # 28a: subscription tiers
            if not table_exists("subscription_tiers"):
                cur.execute("""
                    CREATE TABLE subscription_tiers (
                        id               SERIAL PRIMARY KEY,
                        name             TEXT NOT NULL UNIQUE,
                        max_subscribers  INTEGER NOT NULL DEFAULT 100,
                        max_devices      INTEGER NOT NULL DEFAULT 10,
                        allowed_channels TEXT NOT NULL DEFAULT 'sms,email,push',
                        price_monthly    TEXT DEFAULT '0',
                        description      TEXT DEFAULT NULL,
                        created_at       TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                # Seed default tiers
                _default_tiers = [
                    ("Free",         10,   2,  "push",             "0",    "Up to 10 subscribers, push only"),
                    ("Basic",        50,   5,  "sms,push",         "29",   "Up to 50 subscribers, SMS + push"),
                    ("Professional", 200,  20, "sms,email,push",   "99",   "Up to 200 subscribers, all channels"),
                    ("Enterprise",   1000, 100,"sms,email,push",   "299",  "Unlimited scale, all channels, priority support"),
                ]
                cur.executemany(
                    """
                    INSERT INTO subscription_tiers
                        (name, max_subscribers, max_devices, allowed_channels, price_monthly, description)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    _default_tiers,
                )
                logger.info("Migration 28a: created subscription_tiers table with 4 default tiers")

            # 28b: per-company subscription history
            if not table_exists("company_subscriptions"):
                cur.execute("""
                    CREATE TABLE company_subscriptions (
                        id         SERIAL PRIMARY KEY,
                        company_id INTEGER REFERENCES companies(id),
                        tier_id    INTEGER REFERENCES subscription_tiers(id),
                        started_at TIMESTAMPTZ DEFAULT NOW(),
                        ends_at    TIMESTAMPTZ DEFAULT NULL,
                        status     TEXT NOT NULL DEFAULT 'active',
                        created_by INTEGER REFERENCES admins(id)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_company_subs_company ON company_subscriptions(company_id)"
                )
                logger.info("Migration 28b: created company_subscriptions table")

            # 28c: monthly usage snapshots
            if not table_exists("usage_snapshots"):
                cur.execute("""
                    CREATE TABLE usage_snapshots (
                        id               SERIAL PRIMARY KEY,
                        company_id       INTEGER REFERENCES companies(id),
                        month            TEXT NOT NULL,
                        alert_count      INTEGER DEFAULT 0,
                        subscriber_count INTEGER DEFAULT 0,
                        admin_count      INTEGER DEFAULT 0,
                        captured_at      TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(company_id, month)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_usage_snapshots_company ON usage_snapshots(company_id)"
                )
                logger.info("Migration 28c: created usage_snapshots table")

            # Migration 29: Phase 7 Security & Compliance
            # 29a: login attempt tracking
            if not table_exists("login_attempts"):
                cur.execute("""
                    CREATE TABLE login_attempts (
                        id           SERIAL PRIMARY KEY,
                        ip           TEXT NOT NULL,
                        username     TEXT NOT NULL,
                        success      INTEGER DEFAULT 0,
                        attempted_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_at ON login_attempts(attempted_at)")
                logger.info("Migration 29a: created login_attempts table")

            # 29b: IP whitelist
            if not table_exists("ip_whitelist"):
                cur.execute("""
                    CREATE TABLE ip_whitelist (
                        id       SERIAL PRIMARY KEY,
                        ip       TEXT NOT NULL UNIQUE,
                        note     TEXT DEFAULT NULL,
                        added_by INTEGER REFERENCES admins(id),
                        added_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                logger.info("Migration 29b: created ip_whitelist table")

            # 29c: configurable retention policies
            if not table_exists("retention_policies"):
                cur.execute("""
                    CREATE TABLE retention_policies (
                        id         SERIAL PRIMARY KEY,
                        entity     TEXT NOT NULL UNIQUE,
                        max_days   INTEGER NOT NULL,
                        enabled    INTEGER DEFAULT 1,
                        set_by     INTEGER DEFAULT NULL,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.executemany(
                    "INSERT INTO retention_policies (entity, max_days) VALUES (%s, %s)",
                    [("readings", 30), ("login_attempts", 30), ("admin_activity", 365)],
                )
                logger.info("Migration 29c: created retention_policies table with defaults")

            # 29d: incident reports
            if not table_exists("incident_reports"):
                cur.execute("""
                    CREATE TABLE incident_reports (
                        id          SERIAL PRIMARY KEY,
                        company_id  INTEGER REFERENCES companies(id),
                        title       TEXT NOT NULL,
                        description TEXT DEFAULT NULL,
                        severity    TEXT NOT NULL DEFAULT 'medium',
                        status      TEXT NOT NULL DEFAULT 'open',
                        created_by  INTEGER REFERENCES admins(id),
                        created_at  TIMESTAMPTZ DEFAULT NOW(),
                        resolved_at TIMESTAMPTZ DEFAULT NULL,
                        resolved_by INTEGER REFERENCES admins(id)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_incidents_company ON incident_reports(company_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_incidents_status ON incident_reports(status)"
                )
                logger.info("Migration 29d: created incident_reports table")

            # 29e: 2FA OTP storage
            if not table_exists("super_admin_otp"):
                cur.execute("""
                    CREATE TABLE super_admin_otp (
                        id         SERIAL PRIMARY KEY,
                        admin_id   INTEGER REFERENCES admins(id),
                        otp_hash   TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        used       INTEGER DEFAULT 0,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                logger.info("Migration 29e: created super_admin_otp table")

            # 29f: admin email + 2FA flag
            if table_exists("admins"):
                if not col_exists("admins", "email"):
                    cur.execute("ALTER TABLE admins ADD COLUMN email TEXT DEFAULT NULL")
                    logger.info("Migration 29f: added email to admins")
                if not col_exists("admins", "requires_2fa"):
                    cur.execute("ALTER TABLE admins ADD COLUMN requires_2fa INTEGER DEFAULT 0")
                    logger.info("Migration 29f: added requires_2fa to admins")

            # 29g: session 2FA verification flag
            if table_exists("admin_sessions") and not col_exists("admin_sessions", "two_fa_verified"):
                cur.execute(
                    "ALTER TABLE admin_sessions ADD COLUMN two_fa_verified INTEGER DEFAULT 0"
                )
                logger.info("Migration 29g: added two_fa_verified to admin_sessions")

            # Migration 30: csv_sensor_history — imported historical CSV data
            if not table_exists("csv_sensor_history"):
                cur.execute("""
                    CREATE TABLE csv_sensor_history (
                        id          SERIAL PRIMARY KEY,
                        recorded_at TIMESTAMPTZ NOT NULL,
                        date_only   DATE,
                        hour        INTEGER,
                        week_number INTEGER,
                        temperature NUMERIC(8,2),
                        pressure    NUMERIC(10,4),
                        source      TEXT DEFAULT 'csv',
                        imported_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_csv_history_recorded_at ON csv_sensor_history(recorded_at)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_csv_history_date_only ON csv_sensor_history(date_only)"
                )
                logger.info("Migration 30: created csv_sensor_history table")

            # Migration 31: seed SRM as the default company and assign all
            # existing data to it.  Guarded by slug='srm' so it is fully
            # idempotent — safe to run on every restart.
            cur.execute("SELECT COUNT(*) FROM companies WHERE slug = 'srm'")
            if cur.fetchone()[0] == 0:
                cur.execute("""
                    INSERT INTO companies (name, slug, description, is_active)
                    VALUES ('SRM Institute of Science and Technology',
                            'srm',
                            'SRM Institute — Chennai Campus IoT Monitoring',
                            1)
                    RETURNING id
                """)
                srm_id = cur.fetchone()[0]

                # Assign all existing non-super-admin admins to SRM
                cur.execute("""
                    UPDATE admins
                       SET company_id = %s
                     WHERE company_id IS NULL
                       AND role != 'super_admin'
                """, (srm_id,))

                # Assign all existing subscribers to SRM
                cur.execute("""
                    UPDATE subscribers
                       SET company_id = %s
                     WHERE company_id IS NULL
                """, (srm_id,))

                # Assign all existing alerts to SRM
                cur.execute("""
                    UPDATE alerts
                       SET company_id = %s
                     WHERE company_id IS NULL
                """, (srm_id,))

                logger.info(
                    "Migration 31: seeded SRM company (id=%s) and assigned "
                    "all existing admins, subscribers, and alerts to it",
                    srm_id,
                )

            # Migration 32: severity_routing — per-company channel routing rules
            if not table_exists("severity_routing"):
                cur.execute("""
                    CREATE TABLE severity_routing (
                        id             SERIAL PRIMARY KEY,
                        company_id     INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                        severity       TEXT NOT NULL,
                        use_email      INTEGER DEFAULT 1,
                        use_sms        INTEGER DEFAULT 1,
                        use_push       INTEGER DEFAULT 1,
                        use_escalation INTEGER DEFAULT 0,
                        created_at     TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(company_id, severity)
                    )
                """)
                # Seed default routing for every existing company
                # WARNING: email + push only (no SMS — LOW-urgency, no wake-up calls)
                # CRITICAL: all channels + escalation
                # EMERGENCY: all channels + escalation
                for _sev, _email, _sms, _push, _esc in [
                    ("WARNING",   1, 0, 1, 0),
                    ("CRITICAL",  1, 1, 1, 1),
                    ("EMERGENCY", 1, 1, 1, 1),
                ]:
                    cur.execute("""
                        INSERT INTO severity_routing
                            (company_id, severity, use_email, use_sms, use_push, use_escalation)
                        SELECT id, %s, %s, %s, %s, %s FROM companies
                        ON CONFLICT DO NOTHING
                    """, (_sev, _email, _sms, _push, _esc))
                logger.info("Migration 32: created severity_routing table with default rules")

            # Migration 33: escalation_policy — per-company re-notification rules
            if not table_exists("escalation_policy"):
                cur.execute("""
                    CREATE TABLE escalation_policy (
                        id                      SERIAL PRIMARY KEY,
                        company_id              INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                        enabled                 INTEGER DEFAULT 1,
                        initial_wait_minutes    INTEGER DEFAULT 5,
                        repeat_interval_minutes INTEGER DEFAULT 10,
                        max_escalations         INTEGER DEFAULT 3,
                        notify_super_admin      INTEGER DEFAULT 0,
                        created_at              TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(company_id)
                    )
                """)
                cur.execute("""
                    INSERT INTO escalation_policy
                        (company_id, enabled, initial_wait_minutes,
                         repeat_interval_minutes, max_escalations)
                    SELECT id, 1, 5, 10, 3 FROM companies
                    ON CONFLICT DO NOTHING
                """)
                logger.info("Migration 33: created escalation_policy table with default policies")

            # Migration 34: policy_escalation_log — re-notification events
            # Named separately from the existing escalation_log table (different schema/purpose)
            if not table_exists("policy_escalation_log"):
                cur.execute("""
                    CREATE TABLE policy_escalation_log (
                        id               SERIAL PRIMARY KEY,
                        alert_id         INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
                        subscriber_id    INTEGER REFERENCES subscribers(id) ON DELETE SET NULL,
                        escalation_level INTEGER DEFAULT 1,
                        notified_at      TIMESTAMPTZ DEFAULT NOW(),
                        acknowledged     INTEGER DEFAULT 0,
                        acknowledged_at  TIMESTAMPTZ
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_pel_alert ON policy_escalation_log(alert_id)"
                )
                logger.info("Migration 34: created policy_escalation_log table")

            # Migration 35: anomaly_log — background anomaly detection results
            if not table_exists("anomaly_log"):
                cur.execute("""
                    CREATE TABLE anomaly_log (
                        id            SERIAL PRIMARY KEY,
                        company_id    INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                        anomaly_type  TEXT    NOT NULL,
                        severity      TEXT    NOT NULL DEFAULT 'medium',
                        description   TEXT,
                        detected_at   TIMESTAMPTZ DEFAULT NOW(),
                        is_resolved   INTEGER     DEFAULT 0,
                        resolved_at   TIMESTAMPTZ
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_anomaly_company ON anomaly_log(company_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_anomaly_resolved ON anomaly_log(is_resolved)"
                )
                logger.info("Migration 35: created anomaly_log table")

            # Migration 36: subscription_tiers quota columns + companies usage tracking
            cur.execute("ALTER TABLE subscription_tiers ADD COLUMN IF NOT EXISTS monthly_sms_quota INTEGER DEFAULT 100")
            cur.execute("ALTER TABLE subscription_tiers ADD COLUMN IF NOT EXISTS monthly_email_quota INTEGER DEFAULT 500")
            cur.execute("ALTER TABLE subscription_tiers ADD COLUMN IF NOT EXISTS max_parameters INTEGER DEFAULT 5")
            cur.execute("ALTER TABLE subscription_tiers ADD COLUMN IF NOT EXISTS price_inr INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS tier_id INTEGER REFERENCES subscription_tiers(id) DEFAULT 1")
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS sms_used_this_month INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS email_used_this_month INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS push_used_this_month INTEGER DEFAULT 0")
            cur.execute("UPDATE companies SET tier_id = 2 WHERE slug = 'srm' AND tier_id IS DISTINCT FROM 2")
            logger.info("Migration 36: extended subscription_tiers and companies with quota tracking")

            # Migration 37: onboarding wizard step columns on company_onboarding
            cur.execute("ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS step_index INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS step_title TEXT")
            cur.execute("ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS step_status TEXT DEFAULT 'pending'")
            cur.execute("ALTER TABLE company_onboarding ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
            logger.info("Migration 37: added wizard step columns to company_onboarding")

            # Migration 38: audit_log — security-grade event log with IP, severity, old/new values
            if not table_exists("audit_log"):
                cur.execute("""
                    CREATE TABLE audit_log (
                        id          SERIAL PRIMARY KEY,
                        admin_id    INTEGER REFERENCES admins(id) ON DELETE SET NULL,
                        company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,
                        category    TEXT NOT NULL DEFAULT 'general',
                        action      TEXT NOT NULL,
                        entity_type TEXT,
                        entity_id   INTEGER,
                        old_value   TEXT,
                        new_value   TEXT,
                        ip_address  TEXT,
                        severity    TEXT NOT NULL DEFAULT 'info',
                        created_at  TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_log_admin ON audit_log(admin_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_log_company ON audit_log(company_id)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_audit_log_category ON audit_log(category)"
                )
                logger.info("Migration 38: created audit_log table")

            # Migration 39: totp_secrets — TOTP 2FA for admins
            if not table_exists("totp_secrets"):
                cur.execute("""
                    CREATE TABLE totp_secrets (
                        admin_id    INTEGER PRIMARY KEY REFERENCES admins(id) ON DELETE CASCADE,
                        secret      TEXT NOT NULL,
                        enabled     INTEGER DEFAULT 0,
                        enforced    INTEGER DEFAULT 0,
                        created_at  TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                logger.info("Migration 39: created totp_secrets table")

            # Migration 40: company_parameters — per-company custom sensor parameters
            if not table_exists("company_parameters"):
                cur.execute("""
                    CREATE TABLE company_parameters (
                        id          SERIAL PRIMARY KEY,
                        company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                        name        VARCHAR(100) NOT NULL,
                        unit        VARCHAR(50),
                        min_value   NUMERIC,
                        max_value   NUMERIC,
                        is_active   BOOLEAN DEFAULT TRUE,
                        created_at  TIMESTAMPTZ DEFAULT NOW(),
                        updated_at  TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(company_id, name)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_company_parameters_company_id "
                    "ON company_parameters(company_id)"
                )
                logger.info("Migration 40: created company_parameters table")

            # Migration 41: backfill alerts.company_id — set NULL rows to first company
            cur.execute("""
                UPDATE alerts
                   SET company_id = (SELECT id FROM companies ORDER BY id LIMIT 1)
                 WHERE company_id IS NULL
                   AND EXISTS (SELECT 1 FROM companies)
            """)
            if cur.rowcount > 0:
                logger.info("Migration 41: backfilled company_id on %d alerts", cur.rowcount)

            # Migration 42: extra_params on readings — stores live custom sensor values per reading
            cur.execute(
                "ALTER TABLE readings ADD COLUMN IF NOT EXISTS extra_params JSONB DEFAULT '{}'"
            )

            # Migration 43: delete_parameter support in pending_approvals — no schema change needed
            # (action_type='delete_parameter' reuses the existing pending_approvals table)

            # Migration 44: ensure companies that have admins are is_active=1
            # (guards against accidental toggle-off or legacy 0 defaults)
            cur.execute(
                """
                UPDATE companies
                   SET is_active = 1
                 WHERE is_active = 0
                   AND id IN (SELECT DISTINCT company_id FROM admins WHERE company_id IS NOT NULL)
                """
            )

            # Migration 46: subscriber_sessions — persistent mobile auth tokens (replaces in-memory dict)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriber_sessions (
                    id            SERIAL      PRIMARY KEY,
                    token         TEXT        NOT NULL UNIQUE,
                    subscriber_id INTEGER     NOT NULL,
                    created_at    TIMESTAMPTZ DEFAULT NOW(),
                    expires_at    TIMESTAMPTZ NOT NULL,
                    last_used_at  TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sub_sessions_token ON subscriber_sessions(token)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sub_sessions_expires ON subscriber_sessions(expires_at)"
            )

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


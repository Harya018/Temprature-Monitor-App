-- schema.sql — SentinelEdge database schema (PostgreSQL reference copy)
-- The actual schema is applied via database/connection.py:init_db()
-- This file is kept in sync for documentation and migration planning.
-- System monitors temperature only. Humidity removed.

CREATE TABLE IF NOT EXISTS readings (
    id          SERIAL           PRIMARY KEY,
    temperature DOUBLE PRECISION NOT NULL,
    timestamp   TEXT             NOT NULL,
    is_valid    INTEGER          DEFAULT 1
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

-- Persistent admin sessions (survives server restarts)
CREATE TABLE IF NOT EXISTS admin_sessions (
    id           SERIAL      PRIMARY KEY,
    token        TEXT        NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Phase 4: Distributed hub-and-spoke aggregation (Migration 59) ─────────────
-- These tables live on the SuperAdmin server and store data synced from remote
-- company node installations.  Ingest API + sync agent are deferred to production.

CREATE TABLE IF NOT EXISTS company_nodes (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    node_name       TEXT    NOT NULL,
    api_key         TEXT    NOT NULL UNIQUE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    contact_email   TEXT,
    location        TEXT,
    backend_version TEXT
);

CREATE TABLE IF NOT EXISTS company_heartbeats (
    node_id        INTEGER PRIMARY KEY REFERENCES company_nodes(id) ON DELETE CASCADE,
    last_seen_at   TIMESTAMPTZ NOT NULL,
    sensor_status  TEXT NOT NULL DEFAULT 'unknown',
    readings_today INTEGER DEFAULT 0,
    alerts_today   INTEGER DEFAULT 0,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS synced_readings (
    id           BIGSERIAL PRIMARY KEY,
    node_id      INTEGER NOT NULL REFERENCES company_nodes(id) ON DELETE CASCADE,
    temperature  DOUBLE PRECISION,
    extra_params JSONB DEFAULT '{}',
    recorded_at  TIMESTAMPTZ NOT NULL,
    received_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS synced_alerts (
    id              BIGSERIAL PRIMARY KEY,
    node_id         INTEGER NOT NULL REFERENCES company_nodes(id) ON DELETE CASCADE,
    remote_alert_id INTEGER,
    parameter       TEXT    NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    threshold       DOUBLE PRECISION NOT NULL,
    direction       TEXT    NOT NULL,
    severity        TEXT    NOT NULL DEFAULT 'WARNING',
    acknowledged    BOOLEAN DEFAULT FALSE,
    fired_at        TIMESTAMPTZ NOT NULL,
    received_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_error_log (
    id            SERIAL PRIMARY KEY,
    node_id       INTEGER REFERENCES company_nodes(id) ON DELETE SET NULL,
    error_type    TEXT NOT NULL,
    error_message TEXT,
    payload_size  INTEGER,
    occurred_at   TIMESTAMPTZ DEFAULT NOW(),
    resolved      BOOLEAN DEFAULT FALSE
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

-- Phase 4 indexes
CREATE INDEX IF NOT EXISTS idx_company_nodes_company   ON company_nodes(company_id);
CREATE INDEX IF NOT EXISTS idx_heartbeats_last_seen    ON company_heartbeats(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_synced_readings_node_ts ON synced_readings(node_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_synced_alerts_node_ts   ON synced_alerts(node_id, fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_synced_alerts_ack       ON synced_alerts(acknowledged);
CREATE INDEX IF NOT EXISTS idx_sync_errors_node        ON sync_error_log(node_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_sync_errors_resolved    ON sync_error_log(resolved);

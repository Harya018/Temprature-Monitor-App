"""
database/sync_schema.py — tables for hub <-> node synchronisation.

Hub:   nodes        one row per paired company node (key hash, pairing code, status)
       node_inbox   everything nodes send up, stored as received (kind + JSON)
Node:  outbox       store-and-forward queue: rows waiting to be sent to the hub
Both:  created idempotently at startup (CREATE TABLE IF NOT EXISTS).
"""

from utils.logger import get_logger

logger = get_logger(__name__)

# Both roles: alerts a node reported to the hub carry the node's own alert id, so the
# hub's escalation engine can leave them alone (the node already notified its own people).
COMMON_DDL = """
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS node_alert_id BIGINT;
ALTER TABLE admin_sessions ADD COLUMN IF NOT EXISTS login_name TEXT;
-- a plant that measures only pH (no temperature) must still be able to store its readings
ALTER TABLE readings ALTER COLUMN temperature DROP NOT NULL;
-- each company switches alerts on/off per parameter
ALTER TABLE company_parameters ADD COLUMN IF NOT EXISTS alerts_enabled BOOLEAN NOT NULL DEFAULT TRUE;
-- each company's own wording of the alert SMS / e-mail, per parameter (empty = standard message)
ALTER TABLE company_parameters ADD COLUMN IF NOT EXISTS sms_template TEXT;
ALTER TABLE company_parameters ADD COLUMN IF NOT EXISTS email_subject TEXT;
ALTER TABLE company_parameters ADD COLUMN IF NOT EXISTS email_body TEXT;
-- a company's own e-mail account for sending its alerts (password stored encrypted)
CREATE TABLE IF NOT EXISTS company_email_settings (
    company_id    INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    provider      TEXT NOT NULL DEFAULT 'other',
    host          TEXT NOT NULL,
    port          INTEGER NOT NULL DEFAULT 587,
    security      TEXT NOT NULL DEFAULT 'starttls',
    username      TEXT NOT NULL,
    password_enc  TEXT NOT NULL,
    from_name     TEXT,
    last_status   TEXT,
    last_error    TEXT,
    last_at       TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
-- every company has its own 1st / 2nd / 3rd contact (the order was unique server-wide before)
ALTER TABLE subscribers DROP CONSTRAINT IF EXISTS subscribers_escalation_order_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscribers_company_order ON subscribers(company_id, escalation_order);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_node_alert
    ON alerts(company_id, node_alert_id) WHERE node_alert_id IS NOT NULL;
"""

HUB_DDL = """
-- acknowledgements made on the main server for alerts that belong to a company server: delivered with the
-- next heartbeat and removed from the queue once that server confirms it applied them
CREATE TABLE IF NOT EXISTS node_ack_queue (
    id              SERIAL PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    node_alert_id   BIGINT  NOT NULL,
    acknowledged_by TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    delivered_at    TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS nodes (
    id               SERIAL PRIMARY KEY,
    company_id       INTEGER NOT NULL UNIQUE REFERENCES companies(id) ON DELETE CASCADE,
    key_hash         TEXT,                      -- sha256 of the node key (never the key itself)
    pairing_hash     TEXT,                      -- sha256 of the one-time pairing code
    pairing_expires  TIMESTAMPTZ,
    node_name        TEXT,
    node_version     TEXT,
    paired_at        TIMESTAMPTZ,
    last_seen_at     TIMESTAMPTZ,
    last_ip          TEXT,
    status           JSONB NOT NULL DEFAULT '{}'::jsonb,   -- latest heartbeat summary
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS node_inbox (
    id           BIGSERIAL PRIMARY KEY,
    company_id   INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    node_item_id BIGINT NOT NULL,               -- id in the node's outbox (dedupe on retry)
    kind         TEXT NOT NULL,
    payload      JSONB NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed    BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (company_id, node_item_id)
);
CREATE INDEX IF NOT EXISTS idx_node_inbox_company ON node_inbox(company_id, id);
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS license_active  BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS license_expires DATE;
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS grace_days      INTEGER NOT NULL DEFAULT 7;
CREATE TABLE IF NOT EXISTS node_events (
    id         BIGSERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event      TEXT NOT NULL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_node_events_company ON node_events(company_id, id DESC);
CREATE TABLE IF NOT EXISTS node_hourly (
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    hour       TEXT    NOT NULL,                 -- 'YYYY-MM-DDTHH' (UTC)
    parameter  TEXT    NOT NULL,
    samples    INTEGER NOT NULL,
    min_value  DOUBLE PRECISION,
    max_value  DOUBLE PRECISION,
    avg_value  DOUBLE PRECISION,
    PRIMARY KEY (company_id, hour, parameter)
);
"""

NODE_DDL = """
CREATE TABLE IF NOT EXISTS outbox (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attempts    INTEGER NOT NULL DEFAULT 0
);
"""


def ensure_tables(role: str) -> None:
    """Create the sync tables for this server's role. Safe to call every start."""
    from database.connection import execute_write
    try:
        ddl = COMMON_DDL + (HUB_DDL if role == "hub" else NODE_DDL)
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            execute_write(stmt)
        logger.info("Sync tables ready (role=%s)", role)
    except Exception as exc:
        logger.error("Could not create sync tables: %s", exc)

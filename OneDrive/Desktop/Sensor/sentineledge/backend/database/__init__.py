"""
database — SQLite → PostgreSQL persistence layer.
Re-exports every public function so callers can do:
    from database import insert_reading, get_alert, insert_receipt, ...
"""

from database.connection import get_db_pool, close_db_pool, execute_write, execute_read, init_db
from database.queries.readings import insert_reading, get_recent_readings
from database.queries.alerts import (
    insert_alert,
    get_alert,
    get_unacknowledged_alerts,
    acknowledge_alert,
    update_escalation_level,
    set_max_escalated,
    get_recent_alerts,
    get_alerts_today_count,
    delete_alerts_by_period,
)
from database.queries.subscribers import (
    get_subscribers_ordered,
    get_subscriber_by_order,
    get_subscriber_by_id,
    get_subscriber_by_name_and_pin,
    add_subscriber,
    set_subscriber_pin,
    update_push_subscription,
    update_expo_push_token,
    update_fcm_token,
    clear_fcm_token,
    delete_subscriber,
    disable_subscriber,
    enable_subscriber,
    update_subscriber,
    get_acks_for_subscriber,
)
from database.queries.escalation_log import log_escalation
from database.queries.receipts import (
    insert_receipt,
    get_receipts_for_alert,
    get_delivery_stats_today,
)
from database.queries.config_log import log_config_change, get_recent_config_changes
from database.queries.ack_log import get_ack_log
from database.queries.admins import (
    verify_admin_password,
    create_admin,
    delete_admin,
    update_admin_password,
    get_all_admins,
    get_admin_by_id,
)
from database.queries.sessions import (
    create_session,
    get_session,
    delete_session,
    cleanup_expired_sessions,
)

__all__ = [
    # connection
    "init_db", "get_db_pool", "close_db_pool", "execute_write", "execute_read",
    # readings
    "insert_reading", "get_recent_readings",
    # alerts
    "insert_alert", "get_alert", "get_unacknowledged_alerts",
    "acknowledge_alert", "update_escalation_level",
    "set_max_escalated", "get_recent_alerts", "get_alerts_today_count",
    "delete_alerts_by_period",
    # subscribers
    "get_subscribers_ordered", "get_subscriber_by_order", "get_subscriber_by_id",
    "get_subscriber_by_name_and_pin", "set_subscriber_pin",
    "add_subscriber", "update_push_subscription", "update_expo_push_token",
    "update_fcm_token", "clear_fcm_token", "delete_subscriber",
    "disable_subscriber", "enable_subscriber",
    "update_subscriber", "get_acks_for_subscriber",
    # escalation log
    "log_escalation",
    # delivery receipts
    "insert_receipt", "get_receipts_for_alert", "get_delivery_stats_today",
    # config audit
    "log_config_change", "get_recent_config_changes",
    # acknowledgement log
    "get_ack_log",
    # admin accounts
    "verify_admin_password", "create_admin", "delete_admin",
    "update_admin_password", "get_all_admins", "get_admin_by_id",
    # admin sessions
    "create_session", "get_session", "delete_session", "cleanup_expired_sessions",
]

# Initialise the database when this package is first imported.
init_db()

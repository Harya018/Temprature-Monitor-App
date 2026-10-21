"""
services/live_collector.py — In-memory state for the Pro-Server EX live collector.

The collector script (sentineledge/collector/proserver_collector.py) runs on
the COE_AT Admin PC alongside Pro-Server EX.  It reads symbols via
ProEasyDotNet.dll and POSTs each reading to POST /api/collector/reading.
This module holds the latest received reading so the dashboard can display it.
"""

from __future__ import annotations

import datetime
from typing import Optional


class LiveCollectorState:
    def __init__(self) -> None:
        self.latest_reading:    Optional[dict] = None
        self.last_received_at:  Optional[str]  = None
        self.total_received:    int             = 0
        self.collector_ip:      Optional[str]  = None

    def record(self, data: dict, source_ip: str) -> None:
        self.latest_reading   = data
        self.last_received_at = datetime.datetime.now().isoformat()
        self.total_received  += 1
        self.collector_ip     = source_ip

    def is_stale(self, max_seconds: int = 30) -> bool:
        if not self.last_received_at:
            return True
        try:
            last = datetime.datetime.fromisoformat(self.last_received_at)
            return (datetime.datetime.now() - last).total_seconds() > max_seconds
        except Exception:
            return True

    def get_status(self) -> dict:
        if self.last_received_at is None:
            connection_state = "never_connected"
        elif self.is_stale():
            connection_state = "stale"
        else:
            connection_state = "live"

        return {
            "connection_state":           connection_state,
            "connected":                  connection_state == "live",
            "latest_reading":             self.latest_reading,
            "last_received_at":           self.last_received_at,
            "total_received":             self.total_received,
            "sequence":                   self.total_received,
            "latest_collector_timestamp": (self.latest_reading or {}).get("timestamp"),
            "collector_ip":               self.collector_ip,
        }


# Module-level singleton
state = LiveCollectorState()

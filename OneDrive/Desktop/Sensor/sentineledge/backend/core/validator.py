"""
core/validator.py — Sensor reading validator (temperature only).

Validates every reading from the sensor before it is processed.
Checks for:
  1. Required fields present (temperature, timestamp)
  2. No null / None values
  3. Temperature within physically valid range (-50 to 150°C)
  4. Timestamp is a valid ISO-8601 string
  5. Temperature spike vs previous reading (max 10°C/s)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sentineledge.validator")

# ─── Physical valid range ─────────────────────────────────────────────────────
TEMP_MIN: float = -50.0
TEMP_MAX: float = 150.0

# ─── Maximum allowed change per second ───────────────────────────────────────
MAX_TEMP_SPIKE: float = 10.0


class ReadingValidator:
    """Stateful validator that tracks the previous reading for spike detection."""

    def __init__(self) -> None:
        self.prev_reading: Optional[dict] = None

    def validate(self, reading: dict) -> tuple[bool, str]:
        """
        Validate a sensor reading.

        Parameters
        ----------
        reading : dict
            Must contain 'temperature' and 'timestamp'.

        Returns
        -------
        tuple[bool, str]
            (True, "") if valid.
            (False, "reason string") if invalid.
        """
        # Check 1: required fields present
        for field in ("temperature", "timestamp"):
            if field not in reading:
                self._update_prev(reading)
                return False, f"missing field: {field}"

        # Check 2: no null values
        for field in ("temperature", "timestamp"):
            if reading[field] is None:
                self._update_prev(reading)
                return False, f"null value for field: {field}"

        temp = reading["temperature"]

        # Check 3: temperature in valid range
        if not (TEMP_MIN <= temp <= TEMP_MAX):
            self._update_prev(reading)
            return False, f"temperature {temp} out of range [{TEMP_MIN}, {TEMP_MAX}]"

        # Check 4: timestamp is a valid ISO string
        try:
            datetime.fromisoformat(reading["timestamp"])
        except (ValueError, TypeError):
            self._update_prev(reading)
            return False, f"invalid timestamp: {reading['timestamp']!r}"

        # Check 5: temperature spike (only when we have a previous reading)
        if self.prev_reading is not None:
            prev_temp = self.prev_reading.get("temperature")
            if prev_temp is not None:
                if abs(temp - prev_temp) > MAX_TEMP_SPIKE:
                    self._update_prev(reading)
                    return (
                        False,
                        f"temperature spike: {prev_temp} -> {temp} "
                        f"(max {MAX_TEMP_SPIKE}/s)",
                    )

        self._update_prev(reading)
        return True, ""

    def _update_prev(self, reading: dict) -> None:
        """Store current reading as previous for next spike check."""
        self.prev_reading = reading


# ─── Module-level singleton ───────────────────────────────────────────────────
validator = ReadingValidator()
_per_company: dict = {}      # company_id -> its own validator (spike check compares a company's
                             # reading only with that company's previous one)


def validate_reading(reading: dict, company_id=None) -> tuple[bool, str]:
    """Validate a sensor reading. With company_id, the spike check is per company."""
    if company_id is None:
        return validator.validate(reading)
    v = _per_company.get(company_id)
    if v is None:
        v = _per_company[company_id] = ReadingValidator()
    return v.validate(reading)

"""
core/extra_sensor.py — Fallback sensor parameter store.

When excel_sensor or opc_sensor is active, extra_readings is populated by
those modules instead.  This module provides dummy values (with realistic
drift) for all expected parameters so they auto-register in the DB and
appear in the Super Admin even when no hardware sensor is connected.

Parameters provided:
  pressure   — realistic-looking pressure value  (CSV fallback)
  ph         — realistic-looking pH value        (CSV fallback)
  humidity   — random drift                      (dummy)
  vibration  — random drift                      (dummy)
"""

import random
import threading
import time

# ── Baseline values — realistic starting points ───────────────────────────────
_state = {
    "pressure":  1.8,    # bar
    "ph":        7.0,    # pH
    "humidity":  55.0,   # %
    "vibration": 1.5,    # mm/s
}

# ── Drift limits ──────────────────────────────────────────────────────────────
_LIMITS = {
    "pressure":  (1.0, 3.0),
    "ph":        (6.0, 8.5),
    "humidity":  (40.0, 80.0),
    "vibration": (0.5, 4.0),
}

# ── Drift step per update cycle ────────────────────────────────────────────────
_STEP = {
    "pressure":  0.05,
    "ph":        0.02,
    "humidity":  0.3,
    "vibration": 0.08,
}

# Public dict — always up-to-date; main.py reads this by reference.
extra_readings: dict = dict(_state)


def _drift_loop() -> None:
    """Background thread: apply small random drift to each parameter every 3 s."""
    while True:
        for key in _state:
            lo, hi = _LIMITS[key]
            step = _STEP[key]
            _state[key] = round(
                max(lo, min(hi, _state[key] + random.uniform(-step, step))), 3
            )
        extra_readings.update(_state)
        time.sleep(3)


_thread = threading.Thread(target=_drift_loop, name="extra_sensor_drift", daemon=True)
_thread.start()

"""
utils/column_match.py — read a plant's file even when its column names differ a little.

A logger may call a column "pH", "ph", "PH Value", "pH_value", "pH (pH)" or "Temperature (C)". The reader
matches column names ignoring capitals, spaces, punctuation, common filler words (value, reading, level ...)
and the parameter's own unit, so the same file works without renaming anything. Nothing is guessed from
values: only the NAME of a column is compared, and a column that matches no parameter of the company is
ignored (as before).
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
# words that only describe a reading: "pH Value", "Pressure Reading", "Temp Sensor 1" -> pH, Pressure, Temp
_FILLER = {"value", "values", "val", "reading", "readings", "level", "data", "pv", "sensor", "current", "actual",
           "measured", "live", "now", "probe", "avg", "average", "rate"}
_TEMP_NAMES = {"temperature", "temp", "tempc", "temperaturec", "tempdegc", "temperaturedegc", "tmp", "temperaturecelsius"}


def norm(text) -> str:
    """lower case, letters and digits only: 'pH (Value)' -> 'phvalue'."""
    return _NON_ALNUM.sub("", str(text or "").lower())


def _tokens(text) -> list:
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text or ""))        # camelCase -> words
    return [x for x in _NON_ALNUM.split(t.lower()) if x]


def match_parameter(key, params: dict) -> Optional[str]:
    """The company parameter (lower-case name) a file column belongs to, or None.
    `params` = {lower-case name: row} where a row may carry "unit"."""
    kl = str(key or "").strip().lower()
    if not kl:
        return None
    if kl in params:
        return kl
    nk = norm(kl)
    for name in params:                                   # same letters, other punctuation / spaces
        if norm(name) == nk:
            return name
    toks = _tokens(key)
    for name, row in params.items():
        unit = norm((row or {}).get("unit") if isinstance(row, dict) else "")
        words = [t for t in toks if t not in _FILLER]
        no_unit = [t for t in words if not (unit and t == unit)]        # "Pressure (bar)" -> pressure
        if norm(name) in ("".join(words), "".join(no_unit)) and "".join(words):
            return name
    return None


def is_temperature_header(header) -> bool:
    return norm(header) in _TEMP_NAMES or "".join(t for t in _tokens(header) if t not in _FILLER and t not in ("c", "degc", "celsius")) in _TEMP_NAMES


def find_time_columns(headers: Iterable[str]) -> dict:
    """Which headers carry the time of a reading: {"timestamp": h | None, "date": h | None, "time": h | None}."""
    ts = date = tm = None
    for h in headers:
        n = norm(h)
        if not n:
            continue
        if ts is None and ("timestamp" in n or n in ("datetime", "datetimestamp", "recordedat", "loggedat", "logdatetime")):
            ts = h
        elif date is None and (n == "date" or n.endswith("date") or n == "day"):
            date = h
        elif tm is None and (n == "time" or (n.endswith("time") and "millis" not in n and "elapsed" not in n and "uptime" not in n)):
            tm = h
    return {"timestamp": ts, "date": date, "time": tm}

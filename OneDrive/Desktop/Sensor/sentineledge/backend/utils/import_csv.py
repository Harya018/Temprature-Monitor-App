"""
backend/utils/import_csv.py — Import historical sensor readings from a CSV file.

CSV format expected:
    timestamp,temperature,reference_value
    2026-06-01T08:00:00+00:00,82.5,82.3
    2026-06-01T08:00:01+00:00,81.9,81.7
    ...

  - 'timestamp'       : ISO-8601 datetime string (required)
  - 'temperature'     : float (required)
  - 'reference_value' : float (optional, ignored if missing)

Usage as script:
    python backend/utils/import_csv.py path/to/file.csv
"""

import csv
import os
import sys
from pathlib import Path


def import_csv_file(filepath: str) -> int:
    """
    Read a CSV of historical readings and insert each row into the
    readings table via the database layer.

    Parameters
    ----------
    filepath : str
        Absolute or relative path to the CSV file.

    Returns
    -------
    int
        Number of rows successfully imported.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the CSV is missing required columns.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {filepath}")

    # Ensure the backend is on sys.path when run as a script
    _backend_dir = str(path.resolve().parent.parent / "backend")
    if _backend_dir not in sys.path:
        sys.path.insert(0, _backend_dir)

    import database

    count = 0
    skipped = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # Validate required columns exist
        if reader.fieldnames is None:
            raise ValueError("CSV file appears to be empty.")
        lower_fields = [c.strip().lower() for c in reader.fieldnames]
        if "temperature" not in lower_fields:
            raise ValueError(
                f"CSV must have a 'temperature' column. Found: {reader.fieldnames}"
            )
        if "timestamp" not in lower_fields:
            raise ValueError(
                f"CSV must have a 'timestamp' column. Found: {reader.fieldnames}"
            )

        for row_num, row in enumerate(reader, start=2):  # start=2 (header is row 1)
            try:
                # Normalise column names (strip whitespace, lowercase)
                clean = {k.strip().lower(): v.strip() for k, v in row.items() if k}

                temp_str = clean.get("temperature", "")
                ts_str   = clean.get("timestamp", "")

                if not temp_str or not ts_str:
                    skipped += 1
                    continue

                temperature = float(temp_str)
                timestamp   = ts_str  # stored as-is; DB expects ISO string

                # Basic sanity check — same bounds as validator
                if not (-50.0 <= temperature <= 200.0):
                    skipped += 1
                    continue

                database.insert_reading(temperature, timestamp, valid=True)
                count += 1

            except (ValueError, KeyError):
                skipped += 1
                continue

    if skipped:
        print(f"  Skipped {skipped} rows (bad data or missing fields)")

    return count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_csv.py <path/to/file.csv>")
        sys.exit(1)

    # Add project root and backend to path when run standalone
    _here = Path(__file__).resolve().parent
    _backend = _here.parent
    _root    = _backend.parent
    for _p in [str(_root), str(_backend)]:
        if _p not in sys.path:
            sys.path.insert(0, _p)

    os.environ.setdefault("APP_ENV", "development")

    csv_path = sys.argv[1]
    print(f"Importing from: {csv_path}")
    try:
        imported = import_csv_file(csv_path)
        print(f"Imported {imported} readings")
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)

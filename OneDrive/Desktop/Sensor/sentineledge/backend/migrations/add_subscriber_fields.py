"""
migrations/add_subscriber_fields.py
Adds employee_id, department, designation, shift_timing, address columns
to the subscribers table using PostgreSQL information_schema (safe to re-run).

Usage:
    python -m backend.migrations.add_subscriber_fields
    # or from the sentineledge root:
    python backend/migrations/add_subscriber_fields.py
"""

import os
import sys

# Allow running from repo root or from within backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg2

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://sentineledge:sentineledge123@localhost:5432/sentineledge",
)

NEW_COLUMNS = [
    ("employee_id",  "TEXT"),
    ("department",   "TEXT"),
    ("designation",  "TEXT"),
    ("shift_timing", "TEXT"),
    ("address",      "TEXT"),
]


def col_exists(cur, column: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'subscribers' AND column_name = %s
        """,
        (column,),
    )
    return cur.fetchone() is not None


def run_migration() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            for col_name, col_type in NEW_COLUMNS:
                if col_exists(cur, col_name):
                    print(f"  Skipped  (already exists): {col_name}")
                else:
                    cur.execute(
                        f"ALTER TABLE subscribers ADD COLUMN {col_name} {col_type}"
                    )
                    print(f"  Added column: {col_name} {col_type}")
        conn.commit()
        print("Migration complete.")
    except Exception as exc:
        conn.rollback()
        print(f"Migration FAILED: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("Running add_subscriber_fields migration …")
    run_migration()

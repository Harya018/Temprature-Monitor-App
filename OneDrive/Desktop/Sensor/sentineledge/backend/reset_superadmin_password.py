"""
reset_superadmin_password.py - put the STANDARD Super Admin password back on this PC.

Every SentinelEdge PC uses the same Super Admin password. Use this on a PC that was set up
before that rule (or where the password was changed): it sets the standard password's hash
on this PC's Super Admin, switches the account on and ends its open sign-ins. Company admins
are not touched. The password itself is not in this file - only its hash.

    python reset_superadmin_password.py        (run from sentineledge\\backend)
"""

import os
import sys

import psycopg2

import config  # noqa: F401  (loads this PC's settings file into the environment)
from utils.security import STANDARD_SUPER_ADMIN_HASH


def main() -> int:
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
    except Exception as exc:
        print(f"Could not open this PC's database: {exc}")
        print("Is PostgreSQL running, and was FIRST_TIME_SETUP.bat run on this PC?")
        return 1
    try:
        with conn, conn.cursor() as cur:
            try:
                cur.execute("SELECT id, name FROM admins WHERE role = 'super_admin'")
            except psycopg2.errors.UndefinedTable:
                print("The database is still empty: start SentinelEdge once - the Super Admin is then")
                print("created with the standard password automatically.")
                return 0
            rows = cur.fetchall()
            if not rows:
                print("No Super Admin yet: it is created with the standard password when SentinelEdge starts.")
                return 0
            cur.execute("UPDATE admins SET password_hash = %s, is_active = 1 WHERE role = 'super_admin'",
                        (STANDARD_SUPER_ADMIN_HASH,))
            cur.execute("DELETE FROM admin_sessions WHERE admin_id IN "
                        "(SELECT id FROM admins WHERE role = 'super_admin')")
            ended = cur.rowcount
        names = ", ".join(r[1] for r in rows)
        print(f"Super Admin ({names}): password set to the standard Super Admin password.")
        print(f"Open Super Admin sign-ins ended: {ended}. Sign in again with the standard password.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

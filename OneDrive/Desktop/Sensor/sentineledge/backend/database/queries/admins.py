"""
database/queries/admins.py — Admin account CRUD queries.

Stores sub-admin accounts with bcrypt-hashed passwords.
PostgreSQL: ? → %s, cursor.lastrowid → RETURNING id.

Security upgrade: SHA-256 replaced by bcrypt (see utils/security.py).
"""

from datetime import datetime, timezone
from typing import Optional

from database.connection import execute_write, execute_read
from utils.logger import get_logger
from utils.security import hash_pin, verify_pin

logger = get_logger(__name__)


def verify_admin_password(name: str, plain: str) -> Optional[dict]:
    """
    Verify admin login credentials using bcrypt.
    Returns the admin row if valid, None otherwise.
    """
    try:
        rows = execute_read(
            "SELECT * FROM admins WHERE name = %s",
            (name,),
        )
        if not rows:
            return None
        admin = rows[0]
        if not verify_pin(plain, admin["password_hash"]):
            return None
        return admin
    except Exception as exc:
        logger.error("verify_admin_password failed: %s", exc)
        return None


def create_admin(name: str, plain_password: str, role: str = "sub") -> Optional[int]:
    """
    Create a new admin account. Returns the new row id, or None if the name
    already exists (UniqueViolation) or on any other database error.
    role must be 'main' or 'sub'.
    Password is stored as a bcrypt hash.
    """
    try:
        ts = datetime.now(timezone.utc).isoformat()
        # execute_write() captures the RETURNING id into _WriteResult.lastrowid.
        # Do NOT call .fetchone() — _WriteResult is not a cursor.
        result = execute_write(
            "INSERT INTO admins (name, password_hash, role, created_at) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (name, hash_pin(plain_password), role, ts),
        )
        return result.lastrowid
    except Exception as exc:
        # Log with repr() so the exception *type* (e.g. UniqueViolation) is always visible.
        logger.error("create_admin failed for name=%r: %r", name, exc)
        return None


def delete_admin(admin_id: int) -> bool:
    """Delete a sub-admin by id. Returns True on success."""
    try:
        execute_write(
            "DELETE FROM admins WHERE id = %s AND role != 'main'", (admin_id,)
        )
        return True
    except Exception as exc:
        logger.error("delete_admin failed: %s", exc)
        return False


def update_admin_password(admin_id: int, new_plain: str) -> bool:
    """Update a sub-admin's password with a bcrypt hash. Returns True on success."""
    try:
        execute_write(
            "UPDATE admins SET password_hash = %s WHERE id = %s",
            (hash_pin(new_plain), admin_id),
        )
        return True
    except Exception as exc:
        logger.error("update_admin_password failed: %s", exc)
        return False


def get_all_admins() -> list:
    """Return all admin accounts (password_hash excluded from result)."""
    try:
        return execute_read(
            "SELECT id, name, role, created_at FROM admins ORDER BY role DESC, id ASC"
        )
    except Exception as exc:
        logger.error("get_all_admins failed: %s", exc)
        return []


def get_admin_by_id(admin_id: int) -> Optional[dict]:
    """Return a single admin by id (no password_hash)."""
    try:
        rows = execute_read(
            "SELECT id, name, role, created_at FROM admins WHERE id = %s",
            (admin_id,),
        )
        return rows[0] if rows else None
    except Exception as exc:
        logger.error("get_admin_by_id failed: %s", exc)
        return None


"""
utils/security.py — Credential hashing utilities for SentinelEdge.

Uses bcrypt for all PIN / password storage.  bcrypt automatically:
  - Generates a unique salt per call (no separate salt management).
  - Embeds the cost factor in the hash string ($2b$12$...).
  - Is slow enough to resist offline brute-force attacks.

Public API
----------
hash_pin(plain_pin)          → bcrypt hash string (stored in DB)
verify_pin(plain_pin, hash)  → True if plain matches the stored hash
"""

import bcrypt

from utils.logger import get_logger

logger = get_logger(__name__)

# The Super Admin password is the same on every SentinelEdge PC. Only its bcrypt hash is kept
# (here and in sentineledge\setup_secrets.ps1) - the password itself is not written anywhere.
STANDARD_SUPER_ADMIN_HASH = "$2b$12$NWQahEeIQgOFbYrDSSDc1eZc8JJwHJyMgxLCdrAwt/VgN.mVoKIJO"


def is_bcrypt_hash(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}", value or ""))


def hash_pin(plain_pin: str) -> str:
    """Hash a PIN (or password) using bcrypt.

    Returns the hashed string suitable for storage in the database.
    The returned value always starts with '$2b$' (bcrypt identifier).
    """
    hashed = bcrypt.hashpw(plain_pin.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Verify a plain-text PIN against a stored bcrypt hash.

    Returns True if *plain_pin* matches *hashed_pin*, False otherwise.
    Never raises — returns False on any error (e.g. malformed hash).
    """
    try:
        return bcrypt.checkpw(plain_pin.encode("utf-8"), hashed_pin.encode("utf-8"))
    except Exception as exc:
        logger.warning("verify_pin: comparison error: %s", exc)
        return False


def migrate_env_admin_password() -> None:
    """
    Reads the active .env file and hashes ADMIN_PASSWORD if it's plain text.
    Called once during startup.
    """
    import os
    import re
    import config as _cfg

    if not _cfg.ADMIN_PASSWORD or _cfg.ADMIN_PASSWORD.startswith("$2b$"):
        return

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env_file = os.path.join(root, f".env.{_cfg.APP_ENV}")
    if not os.path.exists(env_file):
        env_file = os.path.join(root, ".env")
        if not os.path.exists(env_file):
            return

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()

        hashed_pwd = hash_pin(_cfg.ADMIN_PASSWORD)
        
        if re.search(r"^ADMIN_PASSWORD=.*$", content, flags=re.MULTILINE):
            new_content = re.sub(
                r"^ADMIN_PASSWORD=.*$",
                f"ADMIN_PASSWORD={hashed_pwd}",
                content,
                flags=re.MULTILINE,
            )
        else:
            new_content = content.rstrip("\n") + f"\nADMIN_PASSWORD={hashed_pwd}\n"

        with open(env_file, "w", encoding="utf-8") as f:
            f.write(new_content)

        _cfg.ADMIN_PASSWORD = hashed_pwd
        logger.info("Migrated ADMIN_PASSWORD in .env to bcrypt")
    except Exception as exc:
        logger.error("Failed to migrate ADMIN_PASSWORD in .env: %s", exc)

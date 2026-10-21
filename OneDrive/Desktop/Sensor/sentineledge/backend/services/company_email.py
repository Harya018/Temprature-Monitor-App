"""
services/company_email.py — each company's own e-mail account for sending its alerts.

A company enters its e-mail address and an app password in Settings; its alert e-mails and daily report
are sent from THAT mailbox. Nothing is set by default, and a company never sends from another company's
mailbox.

  * The PLANT company (the one that owns this PC's sensor feed, e.g. SRM) uses the server's own mailbox:
    Settings reads and writes SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD in the settings file
    (.env) and applies them at once - no restart, no hand editing.
  * Every other company keeps its account in the database, the password encrypted (Fernet); the key
    lives in backend/secrets/settings.key (never part of a package or a backup).

The password is never sent back to the browser.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

PRESETS = {
    "gmail":     {"label": "Gmail / Google Workspace",    "host": "smtp.gmail.com",         "port": 587, "security": "starttls"},
    "outlook":   {"label": "Outlook.com / Hotmail",       "host": "smtp-mail.outlook.com",  "port": 587, "security": "starttls"},
    "office365": {"label": "Microsoft 365 (work account)", "host": "smtp.office365.com",     "port": 587, "security": "starttls"},
    "yahoo":     {"label": "Yahoo Mail",                  "host": "smtp.mail.yahoo.com",    "port": 587, "security": "starttls"},
    "other":     {"label": "Other (type the server)",     "host": "",                       "port": 587, "security": "starttls"},
}
ALLOWED_PORTS = (25, 465, 587, 2525)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HOST = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$")


# ── encryption ───────────────────────────────────────────────────────────────

def _key_path() -> Path:
    env = os.environ.get("SETTINGS_KEY_FILE")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "secrets" / "settings.key"


def _fernet():
    from cryptography.fernet import Fernet
    kp = _key_path()
    if not kp.exists():
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_bytes(Fernet.generate_key())
    return Fernet(kp.read_bytes().strip())


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt(token: str) -> Optional[str]:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None            # key missing / changed (e.g. a restored backup): the password must be typed again


# ── validation ───────────────────────────────────────────────────────────────

def host_problem(host: str) -> Optional[str]:
    """Only real public mail servers: a company must not be able to point the server at an internal address."""
    if not _HOST.match(host or ""):
        return "Enter the mail server name, for example smtp.example.com"
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return f"The mail server '{host}' was not found - check the spelling and the internet connection"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "That mail server address is not a public one"
    return None


def resolve_settings(provider: str, host: str = "", port: Optional[int] = None, security: str = "starttls") -> tuple:
    """(host, port, security, error)"""
    provider = (provider or "other").lower()
    if provider not in PRESETS:
        return "", 0, "", "Unknown mail provider"
    if provider != "other":
        p = PRESETS[provider]
        return p["host"], p["port"], p["security"], None
    host = (host or "").strip().lower()
    port = int(port or 587)
    security = (security or "starttls").lower()
    if port not in ALLOWED_PORTS:
        return "", 0, "", "Port must be one of " + ", ".join(map(str, ALLOWED_PORTS))
    if security not in ("starttls", "ssl"):
        return "", 0, "", "Security must be STARTTLS or SSL (a connection without encryption is not allowed)"
    err = host_problem(host)
    return host, port, security, err


def clean_password(provider: str, password: str) -> str:
    """Google / Yahoo show app passwords in groups ('abcd efgh ijkl mnop'): the spaces are not part of it."""
    password = (password or "").strip()
    return re.sub(r"\s+", "", password) if provider in ("gmail", "yahoo", "outlook") else password


# ── which mailbox does a company use? ────────────────────────────────────────────

def is_plant(company_id) -> bool:
    """True for the company that owns this PC's sensor feed: it uses the server's own mailbox (.env)."""
    if company_id is None:
        return False
    try:
        from services.sensor_company import get_sensor_company_id
        return company_id == get_sensor_company_id()
    except Exception:
        return False


def _platform() -> dict:
    import config
    return {"host": config.SMTP_HOST, "port": int(config.SMTP_PORT), "security": "ssl" if int(config.SMTP_PORT) == 465 else "starttls",
            "user": config.SMTP_USER, "password": config.SMTP_PASSWORD, "from_name": getattr(config, "SMTP_FROM_NAME", "")}


def _apply_platform(host: str, port: int, user: str, password: str, from_name: str) -> None:
    """Make the new server mailbox active straight away (the file is written separately)."""
    import config
    import modules.email.smtp as smtpmod
    for mod in (config, smtpmod):
        mod.SMTP_HOST, mod.SMTP_PORT, mod.SMTP_USER, mod.SMTP_PASSWORD, mod.SMTP_FROM_NAME = host, int(port), user, password, from_name
    os.environ.update({"SMTP_HOST": host, "SMTP_PORT": str(port), "SMTP_USER": user, "SMTP_PASSWORD": password, "SMTP_FROM_NAME": from_name})


def _provider_for(host: str) -> str:
    for k, v in PRESETS.items():
        if v["host"] and v["host"] == (host or "").lower():
            return k
    return "other"


def effective_smtp(company_id) -> Optional[dict]:
    """The mailbox this company's alerts really use, ready to log in with, or None if it has none."""
    if is_plant(company_id):
        pl = _platform()
        return pl if pl["user"] and pl["password"] else None
    d = get_company_smtp(company_id)
    return d if d and not d.get("missing") else None


def get_company_smtp(company_id) -> Optional[dict]:
    """What the sender must use for this company:
         None            the server's own mailbox (the plant company, or no company at all)
         {"missing"}     the company has no account of its own, so nothing is sent for it
         {"broken"}      its saved password cannot be read any more (type it again)
         {host, ...}     its own account."""
    if company_id is None or is_plant(company_id):
        return None
    try:
        from database.connection import execute_read
        rows = execute_read(
            "SELECT host, port, security, username, password_enc, from_name FROM company_email_settings WHERE company_id = %s",
            (company_id,))
        if not rows:
            return {"missing": True}
        r = rows[0]
        pw = _decrypt(r["password_enc"])
        if pw is None:
            logger.warning("Company %s: stored e-mail password cannot be decrypted - enter it again in Settings", company_id)
            return {"broken": True, "user": r["username"]}
        return {"host": r["host"], "port": int(r["port"]), "security": r["security"], "user": r["username"],
                "password": pw, "from_name": r["from_name"] or ""}
    except Exception as exc:
        logger.warning("could not read company e-mail settings: %s", exc)
        return {"missing": True}


# ── what Settings shows ──────────────────────────────────────────────────────────

def _providers() -> dict:
    return {k: {"label": v["label"], "host": v["host"], "port": v["port"]} for k, v in PRESETS.items()}


def _last(company_id) -> dict:
    try:
        import json
        from database.connection import execute_read
        r = execute_read("SELECT value FROM app_settings WHERE key = %s", (f"email_last_{company_id}",))
        return json.loads(r[0]["value"]) if r else {}
    except Exception:
        return {}


def get_public(company_id: int) -> dict:
    """What the Settings page may show (never the password)."""
    last = _last(company_id)
    base = {"providers": _providers(), "last_status": last.get("status"), "last_error": last.get("error"), "last_at": last.get("at")}
    if is_plant(company_id):
        pl = _platform()
        if not (pl["user"] and pl["password"]):
            return {**base, "configured": False, "where": "env"}
        return {**base, "configured": True, "where": "env", "provider": _provider_for(pl["host"]), "host": pl["host"], "port": pl["port"],
                "security": pl["security"], "email": pl["user"], "from_name": pl["from_name"], "password_ok": True}
    from database.connection import execute_read
    rows = execute_read(
        "SELECT provider, host, port, security, username, password_enc, from_name FROM company_email_settings WHERE company_id = %s",
        (company_id,))
    if not rows:
        return {**base, "configured": False, "where": "database"}
    r = rows[0]
    return {**base, "configured": True, "where": "database", "provider": r["provider"], "host": r["host"], "port": r["port"],
            "security": r["security"], "email": r["username"], "from_name": r["from_name"] or "",
            "password_ok": _decrypt(r["password_enc"]) is not None}


# ── saving ───────────────────────────────────────────────────────────────────

def _save_plant(provider: str, email: str, password: Optional[str], h: str, p: int, sec: str, from_name: str) -> Optional[str]:
    if (sec == "ssl") != (p == 465):
        return "SSL uses port 465; STARTTLS uses port 587 (or 25 / 2525)"
    pw = clean_password(provider, password or "") or _platform()["password"]
    if not pw:
        return "Enter the app password"
    if len(pw) > 200:
        return "The password is too long"
    from services import env_file
    name = (from_name or "").strip()[:80]
    try:
        env_file.set_values({"SMTP_HOST": h, "SMTP_PORT": p, "SMTP_USER": email, "SMTP_PASSWORD": pw, "SMTP_FROM_NAME": name})
    except OSError as exc:
        logger.error("could not write the settings file: %s", exc)
        return "The settings file could not be written (is it open or read-only?)"
    _apply_platform(h, p, email, pw, name)
    return None


def save(company_id: int, provider: str, email: str, password: Optional[str], host: str, port, security: str, from_name: str) -> Optional[str]:
    """Store (create or update). A blank password keeps the saved one. Returns an error text or None.
    The plant company's account goes into the settings file (.env); everyone else's into the database."""
    from database.connection import execute_read, execute_write
    email = (email or "").strip()
    if not _EMAIL.match(email) or len(email) > 254:
        return "Enter a valid e-mail address"
    h, p, sec, err = resolve_settings(provider, host, port, security)
    if err:
        return err
    if is_plant(company_id):
        err = _save_plant(provider, email, password, h, p, sec, from_name)
        if not err:
            execute_write("DELETE FROM company_email_settings WHERE company_id = %s", (company_id,))   # one place only
            _clear_last(company_id)
        return err
    existing = execute_read("SELECT password_enc FROM company_email_settings WHERE company_id = %s", (company_id,))
    pw = clean_password(provider, password or "")
    if pw:
        if len(pw) > 200:
            return "The password is too long"
        enc = _encrypt(pw)
    elif existing and _decrypt(existing[0]["password_enc"]) is not None:
        enc = existing[0]["password_enc"]
    else:
        return "Enter the app password"
    execute_write(
        """INSERT INTO company_email_settings (company_id, provider, host, port, security, username, password_enc, from_name, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
           ON CONFLICT (company_id) DO UPDATE SET provider = EXCLUDED.provider, host = EXCLUDED.host, port = EXCLUDED.port,
               security = EXCLUDED.security, username = EXCLUDED.username, password_enc = EXCLUDED.password_enc,
               from_name = EXCLUDED.from_name, updated_at = NOW()""",
        (company_id, provider, h, p, sec, email, enc, (from_name or "").strip()[:80] or None))
    _clear_last(company_id)
    return None


def handover_plant(old_id, new_id) -> None:
    """The 'main company' of this PC is changing: the server's own mailbox (.env) must follow its owner.
    The old main company's account is kept (moved into the database, encrypted) and the settings file is
    emptied, so the new main company never sends from the old one's mailbox; if the new main company
    already had an account in the database, it moves into the settings file."""
    from database.connection import execute_read, execute_write
    carry = None
    if new_id is not None:
        rows = execute_read("SELECT host, port, username, password_enc, from_name FROM company_email_settings WHERE company_id = %s", (new_id,))
        if rows:
            pw = _decrypt(rows[0]["password_enc"])
            if pw:
                carry = (rows[0]["host"], int(rows[0]["port"]), rows[0]["username"], pw, rows[0]["from_name"] or "")
    pl = _platform()
    if old_id is not None and pl["user"] and pl["password"] and old_id != new_id:
        execute_write(
            """INSERT INTO company_email_settings (company_id, provider, host, port, security, username, password_enc, from_name, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (company_id) DO UPDATE SET provider = EXCLUDED.provider, host = EXCLUDED.host, port = EXCLUDED.port,
                   security = EXCLUDED.security, username = EXCLUDED.username, password_enc = EXCLUDED.password_enc,
                   from_name = EXCLUDED.from_name, updated_at = NOW()""",
            (old_id, _provider_for(pl["host"]), pl["host"], pl["port"], pl["security"], pl["user"], _encrypt(pl["password"]), pl["from_name"] or None))
    from services import env_file
    if carry:
        env_file.set_values({"SMTP_HOST": carry[0], "SMTP_PORT": carry[1], "SMTP_USER": carry[2], "SMTP_PASSWORD": carry[3], "SMTP_FROM_NAME": carry[4]})
        _apply_platform(*carry)
        execute_write("DELETE FROM company_email_settings WHERE company_id = %s", (new_id,))
    elif pl["user"] or pl["password"]:
        env_file.set_values({"SMTP_USER": "", "SMTP_PASSWORD": "", "SMTP_FROM_NAME": ""})
        _apply_platform(pl["host"], pl["port"], "", "", "")


def delete(company_id: int) -> bool:
    from database.connection import execute_write
    if is_plant(company_id):
        pl = _platform()
        if not (pl["user"] or pl["password"]):
            return False
        from services import env_file
        env_file.set_values({"SMTP_USER": "", "SMTP_PASSWORD": "", "SMTP_FROM_NAME": ""})
        _apply_platform(pl["host"], pl["port"], "", "", "")
        _clear_last(company_id)
        return True
    removed = execute_write("DELETE FROM company_email_settings WHERE company_id = %s", (company_id,)).rowcount > 0
    _clear_last(company_id)
    return removed


def _clear_last(company_id) -> None:
    try:
        from database.connection import execute_write
        execute_write("DELETE FROM app_settings WHERE key = %s", (f"email_last_{company_id}",))
    except Exception:
        pass


def record_result(company_id, ok: bool, error: Optional[str] = None) -> None:
    """Remember whether the last send worked, so Settings can show it."""
    if company_id is None:
        return
    try:
        import json
        from datetime import datetime, timezone
        from database.connection import execute_write
        val = json.dumps({"status": "ok" if ok else "failed", "error": None if ok else (error or "unknown error")[:300],
                          "at": datetime.now(timezone.utc).isoformat()})
        execute_write(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()", (f"email_last_{company_id}", val))
    except Exception as exc:
        logger.debug("record_result failed: %s", exc)


def friendly_error(exc_text: str) -> str:
    """A short explanation a non-technical admin can act on."""
    t = (exc_text or "").lower()
    if "534" in t or "535" in t or "authentication" in t or "username and password" in t or "application-specific" in t:
        return "The mail server refused the sign-in. Use an APP PASSWORD (not your normal password) and check the address."
    if "timed out" in t or "timeout" in t:
        return "The mail server did not answer. Check the internet connection, server name and port."
    if "name or service not known" in t or "getaddrinfo" in t or "11001" in t:
        return "The mail server name was not found. Check the spelling and the internet connection."
    if "certificate" in t or "ssl" in t:
        return "A secure connection could not be made. Try the other security option (SSL / STARTTLS) or port."
    return (exc_text or "unknown error")[:200]

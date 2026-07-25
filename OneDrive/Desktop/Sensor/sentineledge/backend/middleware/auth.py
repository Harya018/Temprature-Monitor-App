"""
middleware/auth.py — Authentication dependencies for SentinelEdge.

Provides two FastAPI dependency functions:
  - require_admin         — enforces X-Admin-Password header OR Authorization: Bearer <token>
  - require_subscriber_auth — enforces X-Auth-Token header (subscriber JWT-lite)

Admin session tokens are now stored in PostgreSQL (admin_sessions table) so
they survive server restarts. The in-memory _login_sessions dict has been removed.
"""

from typing import Any, Optional

from fastapi import Header, HTTPException, Request, status

from config import ADMIN_PASSWORD


def require_admin(
    request: Request,
    x_admin_password: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
) -> bool:
    """
    FastAPI dependency — enforces admin auth on protected endpoints.

    Accepts EITHER:
      - X-Admin-Password: <password>   (always works — direct password check)
      - Authorization: Bearer <token>  (session token from POST /api/admin/login)

    Session tokens are validated against the admin_sessions PostgreSQL table.
    Raises HTTP 401 if neither is valid.
    Returns True on success.
    """
    from datetime import datetime, timezone

    from utils.security import verify_pin
    # 1. Check X-Admin-Password header (always valid regardless of sessions)
    if x_admin_password and verify_pin(x_admin_password, ADMIN_PASSWORD):
        return True

    # 2. Check Authorization: Bearer <token> against DB sessions
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token:
            # Lazy import to avoid circular dependency
            from database.queries.sessions import get_session
            session = get_session(token)
            if session is not None:
                # Phase 2: is_active check — only applies to sessions that have
                # admin_id set (i.e. created after Migration 25). Legacy sessions
                # with NULL admin_id pass through unchanged.
                admin_id = session.get("admin_id")
                if admin_id is not None:
                    from database.connection import execute_read
                    admin_rows = execute_read(
                        "SELECT is_active FROM admins WHERE id = %s", (admin_id,)
                    )
                    if admin_rows and admin_rows[0].get("is_active") == 0:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Your account has been suspended. Contact your administrator.",
                        )
                return True

    # 3. Dev-mode bypass: if no ADMIN_PASSWORD configured, allow all
    if not ADMIN_PASSWORD:
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing admin credentials (X-Admin-Password or Authorization: Bearer token).",
        headers={"WWW-Authenticate": "X-Admin-Password"},
    )


def require_subscriber_auth(
    x_auth_token: str = Header(default=None),
) -> dict[str, Any]:
    """
    FastAPI dependency — enforces subscriber token on mobile-app endpoints.

    Imports active_tokens lazily to avoid a circular import (auth router
    imports models; models don't import middleware).

    Usage:
        @router.get("/my-alerts", dependencies=[Depends(require_subscriber_auth)])

    Raises HTTP 401 if the token is missing, unknown, or expired.
    Returns the token payload dict on success:
        {"subscriber_id": int, "name": str, "escalation_order": int, "expires_at": datetime}
    """
    from datetime import datetime, timezone
    from routers.auth import active_tokens   # lazy import avoids circular dep

    if not x_auth_token or x_auth_token not in active_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "InvalidToken", "message": "Missing or invalid X-Auth-Token"},
        )
    payload = active_tokens[x_auth_token]
    if datetime.now(timezone.utc) > payload["expires_at"]:
        del active_tokens[x_auth_token]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "TokenExpired", "message": "Token has expired — please log in again"},
        )
    return payload

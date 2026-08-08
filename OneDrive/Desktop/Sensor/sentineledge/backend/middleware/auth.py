"""
middleware/auth.py — Authentication dependencies for SentinelEdge.

Provides two FastAPI dependency functions:
  - require_admin           — enforces Authorization: Bearer <token> only
  - require_subscriber_auth — enforces X-Auth-Token header (DB-backed)

X-Admin-Password raw header support has been removed. All admin endpoints
now require a session token obtained from POST /api/auth/admin-login.
"""

from typing import Any, Optional

from fastapi import Header, HTTPException, status


def require_admin(
    authorization: Optional[str] = Header(default=None),
) -> bool:
    """
    FastAPI dependency — enforces admin auth on protected endpoints.

    Accepts ONLY:
      - Authorization: Bearer <token>  (session token from POST /api/auth/admin-login)

    Session tokens are validated against the admin_sessions PostgreSQL table.
    Raises HTTP 401 if the token is missing, invalid, or the account is suspended.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token:
            from database.queries.sessions import get_session
            session = get_session(token)
            if session is not None:
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

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing admin session. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_subscriber_auth(
    x_auth_token: str = Header(default=None),
) -> dict[str, Any]:
    """
    FastAPI dependency — enforces subscriber token on mobile-app endpoints.

    Tokens are validated against the subscriber_sessions PostgreSQL table.
    Raises HTTP 401 if the token is missing, unknown, or expired.
    Returns the session payload dict on success.
    """
    from database.queries.subscriber_sessions import get_sub_session

    if not x_auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "InvalidToken", "message": "Missing X-Auth-Token header"},
        )
    session = get_sub_session(x_auth_token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "TokenExpired", "message": "Token not found or expired — please log in again"},
        )
    return {
        "subscriber_id":    session["subscriber_id"],
        "name":             session["name"],
        "escalation_order": session["escalation_order"],
        "expires_at":       session["expires_at"],
    }

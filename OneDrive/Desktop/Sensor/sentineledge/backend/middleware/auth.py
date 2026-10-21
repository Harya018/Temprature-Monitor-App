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
) -> dict:
    """
    FastAPI dependency — enforces admin auth on protected endpoints.

    Accepts ONLY:
      - Authorization: Bearer <token>  (session token from POST /api/auth/admin-login)

    Session tokens are validated against the admin_sessions PostgreSQL table.
    Raises HTTP 401 if the token is missing, invalid, or the account is suspended.
    Returns {"admin_id": int, "company_id": int|None} on success.
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
                        "SELECT a.is_active, a.company_id, a.role, c.is_active AS company_active "
                        "FROM admins a LEFT JOIN companies c ON c.id = a.company_id WHERE a.id = %s", (admin_id,)
                    )
                    if admin_rows:
                        row = admin_rows[0]
                        if row.get("is_active") == 0:
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Your account has been suspended. Contact your administrator.",
                            )
                        if row.get("role") != "super_admin":
                            # An admin with no company would otherwise be treated as "platform-wide"
                            # (every company's data); a switched-off company is locked out completely.
                            if row.get("company_id") is None:
                                raise HTTPException(
                                    status_code=status.HTTP_403_FORBIDDEN,
                                    detail="This account is not assigned to a company. Contact the Super Admin.",
                                )
                            if row.get("company_active") == 0:
                                raise HTTPException(
                                    status_code=status.HTTP_403_FORBIDDEN,
                                    detail="This company is switched off. Contact the Super Admin.",
                                )
                        return {
                            "admin_id":   admin_id,
                            "company_id": row.get("company_id"),
                            "role":       row.get("role"),
                        }
                # a session that is not tied to an existing admin must never act as "no company"
                # (which would mean every company's data)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing admin session. Please log in.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def session_admin(authorization: Optional[str]) -> Optional[dict]:
    """The admin behind a Bearer token: {id, name, role, company_id, token} or None.
    `name` is the name used to sign in, so actions are recorded under the person who did them."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    from database.connection import execute_read
    rows = execute_read(
        "SELECT a.id, COALESCE(s.login_name, a.name) AS name, a.name AS account_name, a.role, a.company_id "
        "FROM admin_sessions s JOIN admins a ON a.id = s.admin_id "
        "WHERE s.token = %s AND s.expires_at > NOW() LIMIT 1", (token,))
    if not rows:
        return None
    return {**rows[0], "token": token}


def require_platform_admin(
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Super Admin session only (never a company admin): for test / import tools that act on
    the whole server."""
    admin = require_admin(authorization)
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin only")
    return admin


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

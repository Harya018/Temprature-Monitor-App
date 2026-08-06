"""
utils/tier_enforcer.py — Subscription tier limit enforcement.

Call check_* functions before actions that have tier limits.
Raises HTTPException with a clear message if a limit is exceeded.

Usage columns live on companies (sms_used_this_month, email_used_this_month,
push_used_this_month) and are reset on the 1st of each month by the
monthly_quota_reset background task in main.py.
"""

from fastapi import HTTPException
from database.connection import execute_read, execute_write


def get_company_tier(company_id: int) -> dict | None:
    """Return tier limits + current usage for a company, or None if not found."""
    rows = execute_read("""
        SELECT st.id AS tier_id, st.name AS tier_name,
               st.max_subscribers, st.max_devices, st.max_parameters,
               st.monthly_sms_quota, st.monthly_email_quota,
               st.allowed_channels, st.price_inr,
               c.sms_used_this_month, c.email_used_this_month, c.push_used_this_month
          FROM companies c
          LEFT JOIN subscription_tiers st ON st.id = c.tier_id
         WHERE c.id = %s
    """, (company_id,))
    return rows[0] if rows else None


def check_subscriber_limit(company_id: int) -> None:
    """Raise 403 if company is at or above their subscriber limit."""
    if company_id is None:
        return
    tier = get_company_tier(company_id)
    if not tier:
        return

    row = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s AND is_active = 1",
        (company_id,),
    )
    current = int(row[0]["cnt"]) if row else 0
    limit   = tier["max_subscribers"] or 0

    if limit > 0 and current >= limit:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Subscriber limit reached ({current}/{limit}). "
                "Upgrade your plan to add more subscribers."
            ),
        )


def check_sms_quota(company_id: int) -> None:
    """Raise 429 if monthly SMS quota is exhausted."""
    if company_id is None:
        return
    tier = get_company_tier(company_id)
    if not tier:
        return

    used  = int(tier["sms_used_this_month"] or 0)
    limit = int(tier["monthly_sms_quota"] or 0)
    if limit > 0 and used >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly SMS quota exceeded ({used}/{limit}). "
                "Quota resets on the 1st of next month."
            ),
        )


def check_email_quota(company_id: int) -> None:
    """Raise 429 if monthly email quota is exhausted."""
    if company_id is None:
        return
    tier = get_company_tier(company_id)
    if not tier:
        return

    used  = int(tier["email_used_this_month"] or 0)
    limit = int(tier["monthly_email_quota"] or 0)
    if limit > 0 and used >= limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly email quota exceeded ({used}/{limit}). "
                "Quota resets on the 1st of next month."
            ),
        )


def increment_sms_count(company_id: int) -> None:
    """Call after a successful SMS send."""
    if company_id is None:
        return
    execute_write(
        "UPDATE companies SET sms_used_this_month = sms_used_this_month + 1 WHERE id = %s",
        (company_id,),
    )


def increment_email_count(company_id: int) -> None:
    """Call after a successful email send."""
    if company_id is None:
        return
    execute_write(
        "UPDATE companies SET email_used_this_month = email_used_this_month + 1 WHERE id = %s",
        (company_id,),
    )


def reset_monthly_quotas() -> None:
    """Reset all usage counters to 0. Called on the 1st of each month."""
    execute_write(
        "UPDATE companies SET sms_used_this_month = 0, email_used_this_month = 0, push_used_this_month = 0"
    )


def get_usage_summary(company_id: int) -> dict:
    """Return current usage vs limits for a company."""
    tier = get_company_tier(company_id)
    if not tier:
        return {}

    sub_row = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s AND is_active = 1",
        (company_id,),
    )
    sub_used = int(sub_row[0]["cnt"]) if sub_row else 0

    def _pct(used, limit):
        return round(used / limit * 100) if limit and limit > 0 else 0

    sms_used   = int(tier["sms_used_this_month"]   or 0)
    email_used = int(tier["email_used_this_month"]  or 0)
    sms_limit  = int(tier["monthly_sms_quota"]      or 0)
    email_limit= int(tier["monthly_email_quota"]    or 0)
    sub_limit  = int(tier["max_subscribers"]        or 0)

    return {
        "tier_name":   tier["tier_name"],
        "subscribers": {"used": sub_used,   "limit": sub_limit,   "percent": _pct(sub_used,   sub_limit)},
        "sms":         {"used": sms_used,   "limit": sms_limit,   "percent": _pct(sms_used,   sms_limit)},
        "email":       {"used": email_used, "limit": email_limit, "percent": _pct(email_used, email_limit)},
    }

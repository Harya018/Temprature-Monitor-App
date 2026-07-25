"""
routers/phase6_billing.py — Phase 6: Billing & Business Layer.

All routes protected by require_super_admin.

Prefix: /api/super-admin/billing
Routes:
  GET    /tiers                              List subscription tiers
  POST   /tiers                              Create tier
  DELETE /tiers/{tier_id}                    Delete tier
  POST   /companies/{company_id}/subscribe   Assign tier → update company quotas
  GET    /companies/{company_id}/subscription Current tier + live usage vs quota
  POST   /companies/{company_id}/quota       Manual quota override
  GET    /companies/{company_id}/usage       Monthly snapshot history
  POST   /companies/{company_id}/usage/snapshot  Capture snapshot now
  GET    /report/{company_id}               Monthly breakdown report
  GET    /overview                           All companies: tier, usage, quota
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from database.connection import execute_read, execute_write
from routers.super_admin import require_super_admin
from utils.activity_logger import log_activity
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/super-admin/billing", tags=["Super Admin Billing"])


# ─── Pydantic bodies ──────────────────────────────────────────────────────────

class _TierIn(BaseModel):
    name:             str   = Field(min_length=1, max_length=100)
    max_subscribers:  int   = Field(ge=1, le=100000)
    max_devices:      int   = Field(ge=1, le=10000)
    allowed_channels: str   = Field(min_length=1, max_length=100)
    price_monthly:    str   = Field(default="0", max_length=20)
    description:      Optional[str] = Field(default=None, max_length=500)

    @field_validator("name", "allowed_channels", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class _SubscribeIn(BaseModel):
    tier_id: int


class _QuotaIn(BaseModel):
    max_subscribers:  Optional[int] = Field(default=None, ge=1, le=100000)
    max_devices:      Optional[int] = Field(default=None, ge=1, le=10000)
    allowed_channels: Optional[str] = Field(default=None, max_length=100)

    @field_validator("allowed_channels", mode="before")
    @classmethod
    def strip(cls, v):
        return v.strip() if isinstance(v, str) else v


# ─── Helper: live usage for a company ────────────────────────────────────────

def _live_usage(company_id: int) -> dict:
    subscribers = execute_read(
        "SELECT COUNT(*) AS cnt FROM subscribers WHERE company_id = %s AND is_active = 1",
        (company_id,),
    )
    admins = execute_read(
        "SELECT COUNT(*) AS cnt FROM admins WHERE company_id = %s AND is_active = 1 AND role != 'super_admin'",
        (company_id,),
    )
    alerts_30d = execute_read(
        """
        SELECT COUNT(*) AS cnt FROM alerts
         WHERE company_id = %s
           AND timestamp::timestamptz > NOW() - INTERVAL '30 days'
        """,
        (company_id,),
    )
    alerts_total = execute_read(
        "SELECT COUNT(*) AS cnt FROM alerts WHERE company_id = %s", (company_id,)
    )
    open_alerts = execute_read(
        "SELECT COUNT(*) AS cnt FROM alerts WHERE company_id = %s AND acknowledged = 0",
        (company_id,),
    )
    return {
        "subscribers":   subscribers[0]["cnt"]  if subscribers  else 0,
        "admins":        admins[0]["cnt"]        if admins        else 0,
        "alerts_30d":    alerts_30d[0]["cnt"]    if alerts_30d    else 0,
        "alerts_total":  alerts_total[0]["cnt"]  if alerts_total  else 0,
        "open_alerts":   open_alerts[0]["cnt"]   if open_alerts   else 0,
    }


def _current_tier(company_id: int) -> Optional[dict]:
    rows = execute_read(
        """
        SELECT cs.id AS sub_id, cs.started_at, cs.status,
               t.id AS tier_id, t.name AS tier_name,
               t.max_subscribers, t.max_devices, t.allowed_channels, t.price_monthly
          FROM company_subscriptions cs
          JOIN subscription_tiers t ON t.id = cs.tier_id
         WHERE cs.company_id = %s AND cs.status = 'active'
         ORDER BY cs.started_at DESC
         LIMIT 1
        """,
        (company_id,),
    )
    if rows:
        r = rows[0]
        if r.get("started_at"):
            r["started_at"] = r["started_at"].isoformat()
    return rows[0] if rows else None


# ─── Subscription tiers ───────────────────────────────────────────────────────

@router.get("/tiers", summary="List all subscription tiers")
async def list_tiers(_: dict = Depends(require_super_admin)):
    rows = execute_read(
        "SELECT id, name, max_subscribers, max_devices, allowed_channels, price_monthly, description, created_at FROM subscription_tiers ORDER BY max_subscribers ASC"
    )
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return rows


@router.post("/tiers", status_code=201, summary="Create a subscription tier")
async def create_tier(body: _TierIn, sa: dict = Depends(require_super_admin)):
    existing = execute_read(
        "SELECT id FROM subscription_tiers WHERE name = %s", (body.name,)
    )
    if existing:
        return JSONResponse(status_code=409, content={"error": "Tier with that name already exists"})

    result = execute_write(
        """
        INSERT INTO subscription_tiers
            (name, max_subscribers, max_devices, allowed_channels, price_monthly, description)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (body.name, body.max_subscribers, body.max_devices,
         body.allowed_channels, body.price_monthly, body.description),
    )
    log_activity(
        sa["id"], "tier_created", "subscription_tiers",
        f"name:{body.name} subs:{body.max_subscribers} price:{body.price_monthly}",
        None,
    )
    return {"id": result.lastrowid, "name": body.name, "max_subscribers": body.max_subscribers}


@router.delete("/tiers/{tier_id}", summary="Delete a subscription tier")
async def delete_tier(tier_id: int, sa: dict = Depends(require_super_admin)):
    rows = execute_read("SELECT id, name FROM subscription_tiers WHERE id = %s", (tier_id,))
    if not rows:
        return JSONResponse(status_code=404, content={"error": "Tier not found"})

    in_use = execute_read(
        "SELECT COUNT(*) AS cnt FROM company_subscriptions WHERE tier_id = %s AND status = 'active'",
        (tier_id,),
    )
    if in_use and in_use[0]["cnt"] > 0:
        return JSONResponse(
            status_code=409,
            content={"error": f"Tier is assigned to {in_use[0]['cnt']} active company/companies — reassign first"},
        )

    execute_write("DELETE FROM subscription_tiers WHERE id = %s", (tier_id,))
    log_activity(sa["id"], "tier_deleted", "subscription_tiers", f"id:{tier_id} name:{rows[0]['name']}", None)
    return {"deleted": True, "tier_id": tier_id}


# ─── Company subscription ─────────────────────────────────────────────────────

@router.post("/companies/{company_id}/subscribe", summary="Assign a tier to a company")
async def subscribe_company(
    company_id: int,
    body: _SubscribeIn,
    sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    tier = execute_read(
        "SELECT id, name, max_subscribers, max_devices, allowed_channels FROM subscription_tiers WHERE id = %s",
        (body.tier_id,),
    )
    if not tier:
        return JSONResponse(status_code=404, content={"error": "Tier not found"})
    t = tier[0]

    # Deactivate current active subscriptions
    execute_write(
        "UPDATE company_subscriptions SET status = 'superseded', ends_at = NOW() WHERE company_id = %s AND status = 'active'",
        (company_id,),
    )

    # Create new subscription record
    result = execute_write(
        "INSERT INTO company_subscriptions (company_id, tier_id, status, created_by) VALUES (%s, %s, 'active', %s) RETURNING id",
        (company_id, body.tier_id, sa["id"]),
    )

    # Apply quota limits from the tier to the company
    execute_write(
        """
        UPDATE companies
           SET max_subscribers  = %s,
               max_devices      = %s,
               allowed_channels = %s
         WHERE id = %s
        """,
        (t["max_subscribers"], t["max_devices"], t["allowed_channels"], company_id),
    )

    log_activity(
        sa["id"], "company_subscribed", "company_subscriptions",
        f"company_id:{company_id} company:{cos[0]['name']} tier:{t['name']}",
        company_id,
    )
    logger.info(
        "Super admin %d assigned tier '%s' to company %d (%s)",
        sa["id"], t["name"], company_id, cos[0]["name"],
    )
    return {
        "subscription_id": result.lastrowid,
        "company_id":      company_id,
        "tier_id":         body.tier_id,
        "tier_name":       t["name"],
        "quotas_applied":  {
            "max_subscribers":  t["max_subscribers"],
            "max_devices":      t["max_devices"],
            "allowed_channels": t["allowed_channels"],
        },
    }


@router.get("/companies/{company_id}/subscription", summary="Current subscription and live usage")
async def get_subscription(company_id: int, _: dict = Depends(require_super_admin)):
    cos = execute_read(
        "SELECT id, name, max_subscribers, max_devices, allowed_channels FROM companies WHERE id = %s",
        (company_id,),
    )
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    co     = cos[0]
    tier   = _current_tier(company_id)
    usage  = _live_usage(company_id)

    sub_pct = round(usage["subscribers"] / co["max_subscribers"] * 100) if co["max_subscribers"] else 0

    return {
        "company_id":       company_id,
        "company_name":     co["name"],
        "current_tier":     tier,
        "quota": {
            "max_subscribers":  co["max_subscribers"],
            "max_devices":      co["max_devices"],
            "allowed_channels": co["allowed_channels"],
        },
        "usage":            usage,
        "subscriber_usage_pct": sub_pct,
    }


@router.post("/companies/{company_id}/quota", summary="Manually override quota settings")
async def set_quota(
    company_id: int,
    body: _QuotaIn,
    sa: dict = Depends(require_super_admin),
):
    cos = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    if body.max_subscribers is None and body.max_devices is None and body.allowed_channels is None:
        return JSONResponse(status_code=422, content={"error": "Provide at least one field to update"})

    updates, params = [], []
    if body.max_subscribers  is not None: updates.append("max_subscribers = %s");  params.append(body.max_subscribers)
    if body.max_devices       is not None: updates.append("max_devices = %s");       params.append(body.max_devices)
    if body.allowed_channels  is not None: updates.append("allowed_channels = %s");  params.append(body.allowed_channels)

    params.append(company_id)
    execute_write(f"UPDATE companies SET {', '.join(updates)} WHERE id = %s", tuple(params))

    log_activity(
        sa["id"], "quota_overridden", "companies",
        f"company_id:{company_id} {' '.join(updates)}",
        company_id,
    )
    return {"company_id": company_id, "updated": True}


# ─── Usage snapshots ──────────────────────────────────────────────────────────

def _capture_snapshot(company_id: int) -> dict:
    """Capture a usage snapshot for the current month. Upserts on conflict."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = _live_usage(company_id)
    execute_write(
        """
        INSERT INTO usage_snapshots (company_id, month, alert_count, subscriber_count, admin_count)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (company_id, month)
        DO UPDATE SET
            alert_count      = EXCLUDED.alert_count,
            subscriber_count = EXCLUDED.subscriber_count,
            admin_count      = EXCLUDED.admin_count,
            captured_at      = NOW()
        """,
        (company_id, month, usage["alerts_total"], usage["subscribers"], usage["admins"]),
    )
    return {"month": month, **usage}


@router.get("/companies/{company_id}/usage", summary="Monthly usage snapshot history")
async def get_usage(company_id: int, _: dict = Depends(require_super_admin)):
    cos = execute_read("SELECT id FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    rows = execute_read(
        """
        SELECT month, alert_count, subscriber_count, admin_count, captured_at
          FROM usage_snapshots
         WHERE company_id = %s
         ORDER BY month DESC
         LIMIT 24
        """,
        (company_id,),
    )
    for r in rows:
        if r.get("captured_at"):
            r["captured_at"] = r["captured_at"].isoformat()
    return rows


@router.post("/companies/{company_id}/usage/snapshot", summary="Capture usage snapshot now")
async def capture_snapshot(company_id: int, sa: dict = Depends(require_super_admin)):
    cos = execute_read("SELECT id, name FROM companies WHERE id = %s", (company_id,))
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    result = _capture_snapshot(company_id)
    log_activity(
        sa["id"], "usage_snapshot_captured", "usage_snapshots",
        f"company_id:{company_id} month:{result['month']}",
        company_id,
    )
    return {"captured": True, "company_id": company_id, **result}


# ─── Monthly report ───────────────────────────────────────────────────────────

@router.get("/report/{company_id}", summary="Monthly breakdown report for a company")
async def get_report(company_id: int, _: dict = Depends(require_super_admin)):
    cos = execute_read(
        "SELECT id, name, max_subscribers, max_devices, allowed_channels FROM companies WHERE id = %s",
        (company_id,),
    )
    if not cos:
        return JSONResponse(status_code=404, content={"error": "Company not found"})

    co = cos[0]

    # Last 12 months of usage snapshots
    snapshots = execute_read(
        """
        SELECT month, alert_count, subscriber_count, admin_count, captured_at
          FROM usage_snapshots WHERE company_id = %s ORDER BY month DESC LIMIT 12
        """,
        (company_id,),
    )
    for r in snapshots:
        if r.get("captured_at"):
            r["captured_at"] = r["captured_at"].isoformat()

    # Alerts by severity all time
    by_severity = execute_read(
        "SELECT severity, COUNT(*) AS cnt FROM alerts WHERE company_id = %s GROUP BY severity",
        (company_id,),
    )

    # Alerts by month last 12
    by_month = execute_read(
        """
        SELECT TO_CHAR(timestamp::timestamptz, 'YYYY-MM') AS month, COUNT(*) AS cnt
          FROM alerts WHERE company_id = %s
            AND timestamp::timestamptz > NOW() - INTERVAL '12 months'
          GROUP BY month ORDER BY month DESC
        """,
        (company_id,),
    )

    tier      = _current_tier(company_id)
    usage     = _live_usage(company_id)
    sub_pct   = round(usage["subscribers"] / co["max_subscribers"] * 100) if co["max_subscribers"] else 0

    return {
        "company_id":       company_id,
        "company_name":     co["name"],
        "current_tier":     tier,
        "quota": {
            "max_subscribers":  co["max_subscribers"],
            "max_devices":      co["max_devices"],
            "allowed_channels": co["allowed_channels"],
        },
        "live_usage":           usage,
        "subscriber_usage_pct": sub_pct,
        "alerts_by_severity":   by_severity,
        "alerts_by_month":      by_month,
        "usage_snapshots":      snapshots,
        "generated_at":         datetime.now(timezone.utc).isoformat(),
    }


# ─── Overview ─────────────────────────────────────────────────────────────────

@router.get("/overview", summary="All companies: tier, quota, live usage")
async def get_overview(_: dict = Depends(require_super_admin)):
    companies = execute_read(
        "SELECT id, name, max_subscribers, max_devices, allowed_channels, is_active FROM companies ORDER BY name"
    )
    result = []
    for co in companies:
        tier  = _current_tier(co["id"])
        usage = _live_usage(co["id"])
        sub_pct = round(usage["subscribers"] / co["max_subscribers"] * 100) if co["max_subscribers"] else 0
        result.append({
            "company_id":           co["id"],
            "company_name":         co["name"],
            "is_active":            co["is_active"],
            "tier_name":            tier["tier_name"] if tier else None,
            "max_subscribers":      co["max_subscribers"],
            "max_devices":          co["max_devices"],
            "allowed_channels":     co["allowed_channels"],
            "subscribers":          usage["subscribers"],
            "subscriber_usage_pct": sub_pct,
            "alerts_30d":           usage["alerts_30d"],
            "open_alerts":          usage["open_alerts"],
        })
    return result

"""
core/daily_report.py — Daily summary report generator and scheduler.

One report per company, sent only to that company's own subscribers:
  generate_daily_report(company_id) — today's stats for that company (every parameter)
  send_daily_report()               — builds and emails each active company's report
  schedule_daily_report()           — asyncio task that fires once at midnight UTC each day
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import database
from database.connection import execute_read
from modules.email.smtp import send_email_async

logger = logging.getLogger("sentineledge.daily_report")


# ─── Data collection ──────────────────────────────────────────────────────────

async def generate_daily_report(company_id: Optional[int] = None) -> dict:
    """Today's readings / alerts / deliveries for one company (all companies if None)."""
    today = datetime.now(timezone.utc).date().isoformat()
    cf, cp = ("AND company_id = %s", (company_id,)) if company_id is not None else ("", ())

    total_readings = 0
    params: dict = {}            # name -> {"avg", "min", "max", "count"}
    total_alerts = 0
    alerts_by_type: dict = {}
    total_escalations = 0

    try:
        r = execute_read(
            f"""SELECT COUNT(*) AS n, AVG(temperature) AS av, MIN(temperature) AS mn, MAX(temperature) AS mx,
                       COUNT(temperature) AS nt
                  FROM readings WHERE timestamp >= %s AND is_valid = 1 {cf}""", (today, *cp))
        if r:
            total_readings = int(r[0]["n"] or 0)
            if r[0]["nt"]:
                params["temperature"] = {"avg": round(float(r[0]["av"]), 2), "min": r[0]["mn"],
                                         "max": r[0]["mx"], "count": int(r[0]["nt"])}
        rows = execute_read(
            f"""SELECT e.key AS name, AVG(e.value::float) AS av, MIN(e.value::float) AS mn,
                       MAX(e.value::float) AS mx, COUNT(*) AS n
                  FROM readings r, jsonb_each_text(r.extra_params) e
                 WHERE r.timestamp >= %s AND r.is_valid = 1 {cf.replace('company_id', 'r.company_id')}
                   AND e.value ~ '^-?[0-9]+(\\.[0-9]+)?$'
                 GROUP BY e.key ORDER BY e.key""", (today, *cp))
        for x in rows:
            params[x["name"]] = {"avg": round(float(x["av"]), 3), "min": x["mn"], "max": x["mx"], "count": int(x["n"])}

        alerts = execute_read(f"SELECT parameter, direction FROM alerts WHERE timestamp >= %s {cf}", (today, *cp))
        total_alerts = len(alerts)
        for a in alerts:
            key = f"{a['parameter']}_{a['direction']}"
            alerts_by_type[key] = alerts_by_type.get(key, 0) + 1

        esc = execute_read(
            f"""SELECT COUNT(*) AS cnt FROM escalation_log el
                 WHERE el.sent_at >= %s
                   {'AND el.alert_id IN (SELECT id FROM alerts WHERE company_id = %s)' if company_id is not None else ''}""",
            (today, *cp))
        total_escalations = esc[0]["cnt"] if esc else 0
    except Exception as exc:
        logger.exception("generate_daily_report DB error: %s", exc)

    delivery_stats = {"email": {"sent": 0, "failed": 0}, "sms": {"sent": 0, "failed": 0}}
    try:
        rows = execute_read(
            f"""SELECT dr.channel, dr.success, COUNT(*) AS cnt FROM delivery_receipts dr
                 WHERE dr.sent_at >= %s
                   {'AND dr.alert_id IN (SELECT id FROM alerts WHERE company_id = %s)' if company_id is not None else ''}
                 GROUP BY dr.channel, dr.success""", (today, *cp))
        for r in rows:
            ch = str(r["channel"]).lower()
            if ch in delivery_stats:
                delivery_stats[ch]["sent" if r["success"] else "failed"] += int(r["cnt"])
    except Exception as exc:
        logger.warning("daily report delivery stats failed: %s", exc)

    t = params.get("temperature")
    return {
        "date":              today,
        "company_id":        company_id,
        "total_readings":    total_readings,
        "parameters":        params,
        "total_alerts":      total_alerts,
        "alerts_by_type":    alerts_by_type,
        # kept for older callers
        "avg_temperature":   t["avg"] if t else None,
        "peak_temperature":  t["max"] if t else None,
        "total_escalations": total_escalations,
        "delivery_stats":    delivery_stats,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
    }


def _format_daily_report(report: dict, company_name: str = "") -> str:
    lines = [
        f"SentinelEdge — Daily Summary Report{(' — ' + company_name) if company_name else ''}",
        f"Date: {report['date']}",
        f"Generated at: {report['generated_at']}",
        "",
        "=== READINGS ===",
        f"Total valid readings : {report['total_readings']}",
    ]
    for name, p in report.get("parameters", {}).items():
        lines.append(f"  {name:12s}: avg {p['avg']}  min {p['min']}  max {p['max']}  ({p['count']} values)")
    lines += ["", "=== ALERTS ===", f"Total alerts today   : {report['total_alerts']}"]
    for key, count in report.get("alerts_by_type", {}).items():
        lines.append(f"  {key}: {count}")
    lines += [f"Total escalations    : {report['total_escalations']}", "", "=== DELIVERY STATS ==="]
    for channel, stats in report.get("delivery_stats", {}).items():
        lines.append(f"  {channel:12s}: sent={stats.get('sent', 0)}, failed={stats.get('failed', 0)}")
    lines += ["", "-- SentinelEdge automated report"]
    return "\n".join(lines)


# ─── Send ─────────────────────────────────────────────────────────────────────

async def send_daily_report() -> None:
    """Email each active company its own report — only to that company's subscribers."""
    try:
        companies = execute_read("SELECT id, name FROM companies WHERE COALESCE(is_active, 1) != 0 ORDER BY id")
    except Exception as exc:
        logger.exception("send_daily_report: could not list companies: %s", exc)
        return
    for co in companies:
        try:
            report = await generate_daily_report(co["id"])
            body = _format_daily_report(report, co["name"])
            subject = f"SentinelEdge Daily Report — {co['name']} — {report['date']}"
            subs = [s for s in database.get_subscribers_ordered(co["id"])
                    if s.get("is_active", 1) and s.get("email")]
            if not subs:
                logger.info("Daily report: %s has no subscribers with e-mail.", co["name"])
                continue
            from services.company_email import get_company_smtp
            smtp = get_company_smtp(co["id"])
            for sub in subs:
                ok = await send_email_async(sub["email"], subject, body, smtp)
                (logger.info if ok else logger.warning)(
                    "Daily report for %s %s to %s", co["name"], "sent" if ok else "FAILED", sub["email"])
        except Exception as exc:
            logger.exception("send_daily_report failed for company %s: %s", co.get("id"), exc)


# ─── Scheduler ────────────────────────────────────────────────────────────────

async def schedule_daily_report() -> None:
    """Asyncio background task — fires send_daily_report() once at midnight UTC, forever."""
    logger.info("Daily report scheduler started.")
    while True:
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        wait_seconds = (tomorrow - now).total_seconds()
        logger.info("Daily report scheduled in %.0f seconds (at %s UTC).", wait_seconds, tomorrow.isoformat())
        await asyncio.sleep(wait_seconds)
        await send_daily_report()

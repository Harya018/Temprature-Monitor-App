"""
services/message_templates.py — the wording of alert SMS and e-mail, per company and per parameter.

Each parameter of a company can have its own SMS text and its own e-mail (subject + body). A
template is plain text with {placeholders}; an empty template means "use the standard message".

    {name}       the person receiving it          {company}    the company's name
    {parameter}  e.g. pH, Temperature             {unit}       e.g. C, pH, bar
    {value}      the reading that broke the limit {limit}      the limit that was crossed
    {direction}  "above" or "below"               {severity}   WARNING / CRITICAL / EMERGENCY
    {time}       when it happened (IST)           {min} {max}  the parameter's allowed range
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

PLACEHOLDERS = ("name", "company", "parameter", "unit", "value", "limit", "direction", "severity", "time", "min", "max")
SMS_MAX_TEMPLATE = 300      # what the admin may type
SMS_MAX_SENT = 160          # one SMS; longer text is cut (the modem sends single messages)
SUBJECT_MAX = 150
BODY_MAX = 3000

_TOKEN = re.compile(r"\{(\w+)\}")

# Characters a GSM modem in text mode cannot carry: replace with plain look-alikes
_ASCII_MAP = {"°": "", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", " ": " ", "µ": "u", "±": "+/-"}


def unknown_placeholders(*templates: Optional[str]) -> list:
    """Names used in {braces} that are not one of PLACEHOLDERS (a typo would otherwise be sent as-is)."""
    bad = []
    for t in templates:
        for m in _TOKEN.findall(t or ""):
            if m not in PLACEHOLDERS and m not in bad:
                bad.append(m)
    return bad


def render(template: str, ctx: dict) -> str:
    """Fill the {placeholders}. Unknown ones are left untouched; nothing else is evaluated."""
    return _TOKEN.sub(lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), template or "")


def fmt_value(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:.1f}" if abs(f) >= 100 else f"{f:.2f}"


def _ist(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt + timedelta(hours=5, minutes=30)).strftime("%H:%M IST %d-%b-%Y")
    except Exception:
        return str(ts or "")


def build_context(*, company: str, parameter: str, unit: str, value, limit, direction: str, severity: str,
                  timestamp_utc: str, min_value=None, max_value=None, name: str = "") -> dict:
    return {
        "name": name or "Operator",
        "company": company or "",
        "parameter": parameter,
        "unit": unit or "",
        "value": fmt_value(value),
        "limit": fmt_value(limit),
        "direction": "below" if str(direction).lower() == "low" else "above",
        "severity": str(severity or "WARNING").upper(),
        "time": _ist(timestamp_utc),
        "min": "" if min_value is None else fmt_value(min_value),
        "max": "" if max_value is None else fmt_value(max_value),
    }


def sms_text(template: str, ctx: dict) -> str:
    """The SMS to send: placeholders filled, plain characters only, at most one SMS long."""
    text = render(template, ctx)
    for a, b in _ASCII_MAP.items():
        text = text.replace(a, b)
    text = text.encode("ascii", "replace").decode("ascii").replace("\r\n", "\n").strip()
    if len(text) > SMS_MAX_SENT:
        logger.warning("Custom SMS is %d characters; cut to %d", len(text), SMS_MAX_SENT)
        text = text[:SMS_MAX_SENT]
    return text


def email_content(subject_tpl: Optional[str], body_tpl: Optional[str], ctx: dict, default: dict) -> dict:
    """{"subject", "html_body", "text_body"}. A part left empty keeps the standard one."""
    subject = render(subject_tpl, ctx).replace("\r", " ").replace("\n", " ").strip() if (subject_tpl or "").strip() else default["subject"]
    if not (body_tpl or "").strip():
        return {"subject": subject, "html_body": default["html_body"], "text_body": default["text_body"]}
    text = render(body_tpl, ctx).replace("\r\n", "\n").strip()
    sev = ctx.get("severity", "WARNING")
    colour = {"EMERGENCY": "#b91c1c", "CRITICAL": "#c2410c"}.get(sev, "#a16207")
    paras = "".join(f"<p style='margin:0 0 12px'>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n"))
    html_body = (
        "<div style='font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.5;color:#1f2937;max-width:560px'>"
        f"<div style='border-left:4px solid {colour};padding:2px 0 2px 14px;margin-bottom:16px'>{paras}</div>"
        f"<div style='font-size:12px;color:#6b7280'>{html.escape(ctx.get('company') or 'SentinelEdge')} · sent by SentinelEdge</div></div>"
    )
    return {"subject": subject, "html_body": html_body, "text_body": text + "\n\n-- SentinelEdge"}


# ── storage ──────────────────────────────────────────────────────────────────

def get_templates(company_id, parameter: str) -> dict:
    """{"sms", "email_subject", "email_body"} for this company's parameter ('' when not customised)."""
    out = {"sms": "", "email_subject": "", "email_body": ""}
    if company_id is None:
        return out
    try:
        from database.connection import execute_read
        rows = execute_read(
            "SELECT name, sms_template, email_subject, email_body, unit, min_value, max_value FROM company_parameters "
            "WHERE company_id = %s AND LOWER(name) = LOWER(%s) AND is_active = TRUE LIMIT 1",
            (company_id, parameter))
        if rows:
            r = rows[0]
            out = {"sms": r.get("sms_template") or "", "email_subject": r.get("email_subject") or "",
                   "email_body": r.get("email_body") or "", "unit": r.get("unit") or "", "name": r.get("name") or parameter,
                   "min": r.get("min_value"), "max": r.get("max_value")}
    except Exception as exc:
        logger.warning("could not read message templates: %s", exc)
    return out

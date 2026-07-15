# -*- coding: utf-8 -*-
"""
modules/email/templates.py — Professional HTML email builder (Module 2).

Public API
----------
build_alert_email(temperature, threshold, direction, severity,
                  escalation_level, timestamp_utc, subscriber_name)
    -> {"subject": str, "html_body": str, "text_body": str}

Also preserves the old format_alert_message() for backward-compat with
any callers that still use it (escalation._build_message uses formatter.py,
so this is just a safety net — it is NOT used by the HTML email path).
"""

from datetime import datetime, timezone, timedelta


# ── Severity styling ──────────────────────────────────────────────────────────

_SEV_STYLES: dict[str, dict[str, str]] = {
    "WARNING":   {"bg": "#FFFBEB", "color": "#F59E0B", "border": "#F59E0B"},
    "CRITICAL":  {"bg": "#FFF7ED", "color": "#F97316", "border": "#F97316"},
    "EMERGENCY": {"bg": "#FEF2F2", "color": "#EF4444", "border": "#EF4444"},
}

_DEFAULT_STYLE = _SEV_STYLES["WARNING"]


def _sev_style(severity: str) -> dict[str, str]:
    return _SEV_STYLES.get(str(severity).upper(), _DEFAULT_STYLE)


# ── Timestamp conversion ──────────────────────────────────────────────────────

def _to_ist(timestamp_utc: str) -> str:
    """
    Convert a UTC ISO-8601 string to IST (UTC+5:30).
    Returns a human-friendly string: "04 Jun 2026, 01:25:30 PM IST"
    Falls back gracefully if the timestamp is malformed.
    """
    try:
        # Handle both "+00:00" and "Z" suffixes
        ts = timestamp_utc.rstrip("Z")
        if "+" in ts[10:]:
            ts = ts[:ts.rfind("+")]
        dt_utc = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        dt_ist = dt_utc + timedelta(hours=5, minutes=30)
        return dt_ist.strftime("%-d %b %Y, %I:%M:%S %p IST")
    except Exception:
        try:
            # Windows fallback (no %-d support)
            dt_utc = datetime.fromisoformat(
                timestamp_utc.rstrip("Z").split("+")[0]
            ).replace(tzinfo=timezone.utc)
            dt_ist = dt_utc + timedelta(hours=5, minutes=30)
            return dt_ist.strftime("%d %b %Y, %I:%M:%S %p IST").lstrip("0")
        except Exception:
            return timestamp_utc  # raw fallback


# ── Level labels & subjects ───────────────────────────────────────────────────

def _level_label(direction: str) -> str:
    if direction == "low":
        return "⚠️ ALERT — MACHINE READY"
    return "⚠️ ALERT — HIGH TEMPERATURE"


def _direction_label(direction: str) -> str:
    return "Machine Ready" if direction == "low" else "Overheating Danger"


def _build_subject(
    temperature: float,
    direction: str,
    level: int,
) -> str:
    temp_str = f"{temperature}°C"
    dir_label = _direction_label(direction)
    if level == 1:
        return f"SentinelEdge Alert — {dir_label} ({temp_str})"
    elif level == 2:
        return f"SentinelEdge ESCALATION L2 — No Response ({temp_str})"
    else:
        return "SentinelEdge CRITICAL L3 FINAL — Immediate Action Required"


# ── Alert body message ────────────────────────────────────────────────────────

def _alert_body_message(temperature: float, threshold: float, direction: str) -> str:
    if direction == "low":
        return (
            f"Machine has cooled to {temperature}°C and is ready "
            f"for the next process. The temperature has dropped below "
            f"the low threshold of {threshold}°C."
        )
    else:
        return (
            f"Temperature has exceeded {temperature}°C — overheating danger. "
            f"The high threshold of {threshold}°C has been breached. "
            f"Immediate attention required."
        )


# ── Plain-text fallback ───────────────────────────────────────────────────────

def _build_text_body(
    temperature: float,
    threshold: float,
    direction: str,
    severity: str,
    escalation_level: int,
    timestamp_ist: str,
    subscriber_name: str,
) -> str:
    dir_label = _direction_label(direction)
    lines = [
        "SentinelEdge — Industrial Temperature Monitoring",
        "=" * 50,
        "",
        f"Hello {subscriber_name},",
        "",
        f"ALERT ({severity}): {_direction_label(direction)}",
        f"Current Temperature : {temperature}°C",
        f"Threshold           : {threshold}°C ({direction})",
        f"Severity            : {severity}",
        f"Alert Time (IST)    : {timestamp_ist}",
        "",
    ]
    if escalation_level > 1:
        lines += [
            "⚠ No acknowledgement received.",
            f"This alert has been escalated to Level {escalation_level}.",
            "Please acknowledge immediately from the SentinelEdge dashboard.",
            "",
        ]
    lines += [
        "-" * 50,
        "SentinelEdge v1.0.0 — Industrial Monitoring",
        "This is an automated alert. Do not reply to this email.",
    ]
    return "\n".join(lines)


# ── HTML builder ──────────────────────────────────────────────────────────────

def _build_html_body(
    temperature: float,
    threshold: float,
    direction: str,
    severity: str,
    escalation_level: int,
    timestamp_ist: str,
    subscriber_name: str,
) -> str:
    style  = _sev_style(severity)
    bg     = style["bg"]
    color  = style["color"]
    border = style["border"]
    lvl_lbl  = _level_label(direction)
    body_msg = _alert_body_message(temperature, threshold, direction)
    dir_str  = direction.capitalize()

    # Escalation warning block (only for level 2+)
    escalation_block = ""
    if escalation_level > 1:
        escalation_block = f"""
  <!-- Escalation warning -->
  <div style="background:#FEF2F2;border-radius:8px;
              margin:0 20px 20px;padding:16px 20px;">
    <p style="color:#991B1B;margin:0;font-size:13px;line-height:1.5;">
      <strong>⚠️ No acknowledgement received.</strong><br>
      This alert has been escalated to Level {escalation_level}.
      Please acknowledge immediately from the SentinelEdge dashboard.
    </p>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SentinelEdge Alert</title>
</head>
<body style="margin:0;padding:0;background:#F8F9FC;font-family:Arial,Helvetica,sans-serif;">

  <!-- Header bar -->
  <div style="background:#1E1B4B;padding:20px 30px;">
    <h1 style="color:white;margin:0;font-size:20px;font-weight:bold;">
      🌡 SentinelEdge
    </h1>
    <p style="color:#A5B4FC;margin:4px 0 0;font-size:13px;">
      Industrial Temperature Monitoring System
    </p>
  </div>

  <!-- Alert banner -->
  <div style="background:{bg};border-left:4px solid {border};
              padding:20px 30px;margin:20px;">

    <p style="color:{color};font-weight:bold;margin:0 0 4px;
              font-size:13px;text-transform:uppercase;letter-spacing:1px;">
      {lvl_lbl}
    </p>

    <!-- Big temperature display -->
    <div style="font-size:56px;font-weight:bold;color:{color};
                line-height:1;margin:12px 0;letter-spacing:-1px;">
      {temperature}°C
    </div>

    <p style="color:#374151;margin:8px 0 0;font-size:15px;line-height:1.5;">
      {body_msg}
    </p>
  </div>

  <!-- Details card -->
  <div style="background:white;border-radius:8px;margin:0 20px 20px;
              padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

    <h3 style="color:#1F2937;margin:0 0 16px;font-size:14px;
               text-transform:uppercase;letter-spacing:0.5px;">
      Alert Details
    </h3>

    <table style="width:100%;border-collapse:collapse;">
      <tr style="border-bottom:1px solid #F3F4F6;">
        <td style="padding:8px 0;color:#6B7280;font-size:13px;width:40%;">Parameter</td>
        <td style="padding:8px 0;color:#1F2937;font-size:13px;font-weight:bold;">Temperature</td>
      </tr>
      <tr style="border-bottom:1px solid #F3F4F6;">
        <td style="padding:8px 0;color:#6B7280;font-size:13px;">Current Reading</td>
        <td style="padding:8px 0;color:#1F2937;font-size:13px;font-weight:bold;">{temperature}°C</td>
      </tr>
      <tr style="border-bottom:1px solid #F3F4F6;">
        <td style="padding:8px 0;color:#6B7280;font-size:13px;">Threshold</td>
        <td style="padding:8px 0;color:#1F2937;font-size:13px;">{threshold}°C ({dir_str})</td>
      </tr>
      <tr style="border-bottom:1px solid #F3F4F6;">
        <td style="padding:8px 0;color:#6B7280;font-size:13px;">Severity</td>
        <td style="padding:8px 0;color:{color};font-size:13px;font-weight:bold;">{severity}</td>
      </tr>
      <tr style="border-bottom:1px solid #F3F4F6;">
        <td style="padding:8px 0;color:#6B7280;font-size:13px;">Alert Time (IST)</td>
        <td style="padding:8px 0;color:#1F2937;font-size:13px;">{timestamp_ist}</td>
      </tr>
    </table>
  </div>
{escalation_block}
  <!-- Footer -->
  <div style="padding:20px 30px;text-align:center;border-top:1px solid #E5E7EB;">
    <p style="color:#9CA3AF;font-size:12px;margin:0;">
      SentinelEdge v1.0.0 — Industrial Monitoring
    </p>
    <p style="color:#9CA3AF;font-size:11px;margin:4px 0 0;">
      This is an automated alert. Do not reply to this email.
    </p>
  </div>

</body>
</html>"""


# ── Public API ────────────────────────────────────────────────────────────────

def build_alert_email(
    temperature: float,
    threshold: float,
    direction: str,
    severity: str,
    escalation_level: int,
    timestamp_utc: str,
    subscriber_name: str = "Operator",
) -> dict:
    """
    Build a complete professional HTML alert email.

    Parameters
    ----------
    temperature      : current sensor reading (e.g. 37.5)
    threshold        : breach threshold value (e.g. 38.0)
    direction        : "low" | "high"
    severity         : "WARNING" | "CRITICAL" | "EMERGENCY"
    escalation_level : 1 | 2 | 3
    timestamp_utc    : ISO-8601 UTC string (e.g. "2026-06-04T08:15:00Z")
    subscriber_name  : recipient's name for the plain-text salutation

    Returns
    -------
    {
        "subject":   str,   # e.g. "SentinelEdge Alert — Machine Ready (37.5°C)"
        "html_body": str,   # full HTML email
        "text_body": str,   # plain-text fallback
    }
    """
    timestamp_ist = _to_ist(timestamp_utc)

    subject = _build_subject(temperature, direction, escalation_level)

    html_body = _build_html_body(
        temperature=temperature,
        threshold=threshold,
        direction=direction,
        severity=severity,
        escalation_level=escalation_level,
        timestamp_ist=timestamp_ist,
        subscriber_name=subscriber_name,
    )

    text_body = _build_text_body(
        temperature=temperature,
        threshold=threshold,
        direction=direction,
        severity=severity,
        escalation_level=escalation_level,
        timestamp_ist=timestamp_ist,
        subscriber_name=subscriber_name,
    )

    return {
        "subject":   subject,
        "html_body": html_body,
        "text_body": text_body,
    }


# ── Backward-compat shim ──────────────────────────────────────────────────────
# escalation._build_message() uses utils/formatter.py directly, not this.
# Kept here for any legacy callers that imported from this module.

def format_alert_message(
    parameter: str,
    value: float,
    threshold: float,
    direction: str,
) -> str:
    """Legacy plain-text alert message (no severity prefix, no HTML)."""
    label = parameter.capitalize()
    unit  = "°C" if parameter == "temperature" else "%"
    if direction == "high":
        return f"{label} is {value}{unit} — exceeds high threshold of {threshold}{unit}"
    return f"{label} is {value}{unit} — below low threshold of {threshold}{unit}"

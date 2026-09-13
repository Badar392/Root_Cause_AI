"""
alerts.py

Auto-notification sinks for confirmed High/Critical findings. Follows the
same "infrastructure is configured out-of-band, never typed into the UI"
pattern as groq_client.py: every setting here is resolved from
st.secrets / environment variables, never from a text box.

Two sinks are supported, either or both may be configured:
  - Slack, via an Incoming Webhook URL (SLACK_WEBHOOK_URL)
  - Email, via SMTP (ALERT_SMTP_HOST / _PORT / _USERNAME / _PASSWORD /
    _FROM / _TO, and optionally ALERT_SMTP_USE_TLS)

Sending is best-effort: a failed webhook or SMTP call is caught, reported
back as a structured result, and never allowed to crash the analysis run
that triggered it.
"""

import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage

import streamlit as st

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


def _setting(name: str, default=None):
    """Resolve configuration with st.secrets taking priority over environment
    (mirrors groq_client._setting so alert config follows the same pattern)."""
    try:
        value = st.secrets.get(name, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    except Exception:
        pass
    env_value = os.environ.get(name)
    if env_value is not None and str(env_value).strip():
        return str(env_value).strip()
    return default


@dataclass(frozen=True)
class AlertConfig:
    slack_webhook_url: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_username: str | None
    smtp_password: str | None
    smtp_from: str | None
    smtp_to: str | None
    smtp_use_tls: bool

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_webhook_url)

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_port and self.smtp_from and self.smtp_to)

    @property
    def any_configured(self) -> bool:
        return self.slack_configured or self.email_configured


def get_alert_config() -> AlertConfig:
    port_raw = _setting("ALERT_SMTP_PORT")
    try:
        port = int(port_raw) if port_raw else None
    except ValueError:
        port = None
    use_tls_raw = (_setting("ALERT_SMTP_USE_TLS", "true") or "true").lower()
    return AlertConfig(
        slack_webhook_url=_setting("SLACK_WEBHOOK_URL"),
        smtp_host=_setting("ALERT_SMTP_HOST"),
        smtp_port=port,
        smtp_username=_setting("ALERT_SMTP_USERNAME"),
        smtp_password=_setting("ALERT_SMTP_PASSWORD"),
        smtp_from=_setting("ALERT_SMTP_FROM"),
        smtp_to=_setting("ALERT_SMTP_TO"),
        smtp_use_tls=use_tls_raw not in ("false", "0", "no"),
    )


@dataclass
class AlertResult:
    sink: str
    sent: bool
    detail: str = ""
    errors: list = field(default_factory=list)


def _format_alert_text(ai_result: dict, filenames: list) -> tuple[str, str]:
    """Build a short (Slack-friendly) and longer (email-friendly) message body
    from the confirmed finding, quoting only what the AI itself returned."""
    impact = ai_result.get("impact_assessment") or {}
    severity = impact.get("severity", "Unknown")
    category = impact.get("category", "Unknown")
    summary = ai_result.get("summary", "")
    top_anomalies = [a for a in (ai_result.get("anomalies") or [])
                      if str(a.get("severity", "")).lower() in ("high", "critical")]

    short = (
        f"🚨 Root Cause AI — *{severity}* finding confirmed ({category})\n"
        f"{summary}\n"
        f"Source files: {', '.join(filenames) if filenames else 'N/A'}"
    )

    lines = [
        f"Root Cause AI has confirmed a {severity} severity finding.",
        f"Category: {category}",
        f"Source files: {', '.join(filenames) if filenames else 'N/A'}",
        "",
        "Summary:",
        summary,
    ]
    if top_anomalies:
        lines.append("\nHigh/Critical anomalies:")
        for a in top_anomalies:
            lines.append(f"  - [{a.get('severity')}] {a.get('description', '')}")
    long_body = "\n".join(lines)
    return short, long_body


def send_slack_alert(config: AlertConfig, ai_result: dict, filenames: list) -> AlertResult:
    if not config.slack_configured:
        return AlertResult(sink="slack", sent=False, detail="Slack webhook not configured.")
    if requests is None:
        return AlertResult(sink="slack", sent=False, detail="The 'requests' package is not installed.")
    short_text, _ = _format_alert_text(ai_result, filenames)
    try:
        resp = requests.post(config.slack_webhook_url, json={"text": short_text}, timeout=10)
        if resp.status_code >= 300:
            return AlertResult(sink="slack", sent=False, detail=f"Slack returned HTTP {resp.status_code}: {resp.text[:200]}")
        return AlertResult(sink="slack", sent=True, detail="Sent to Slack.")
    except Exception as e:
        return AlertResult(sink="slack", sent=False, detail=f"Slack webhook failed: {e}")


def send_email_alert(config: AlertConfig, ai_result: dict, filenames: list) -> AlertResult:
    if not config.email_configured:
        return AlertResult(sink="email", sent=False, detail="Email/SMTP not configured.")
    _, long_body = _format_alert_text(ai_result, filenames)
    impact = ai_result.get("impact_assessment") or {}
    msg = EmailMessage()
    msg["Subject"] = f"[Root Cause AI] {impact.get('severity', 'High')} severity finding confirmed"
    msg["From"] = config.smtp_from
    msg["To"] = config.smtp_to
    msg.set_content(long_body)
    try:
        if config.smtp_use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as server:
                server.starttls(context=context)
                if config.smtp_username and config.smtp_password:
                    server.login(config.smtp_username, config.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as server:
                if config.smtp_username and config.smtp_password:
                    server.login(config.smtp_username, config.smtp_password)
                server.send_message(msg)
        return AlertResult(sink="email", sent=True, detail=f"Sent to {config.smtp_to}.")
    except Exception as e:
        return AlertResult(sink="email", sent=False, detail=f"Email send failed: {e}")


def maybe_send_alerts(ai_result: dict, filenames: list, high_severity_confirmed: bool) -> list:
    """
    Entry point called right after a run completes. Sends to every configured
    sink when a High/Critical finding was confirmed; returns a list of
    AlertResult so the UI can show what happened without crashing the run
    if a webhook/SMTP call fails.
    """
    if not high_severity_confirmed:
        return []
    config = get_alert_config()
    if not config.any_configured:
        return []
    results = []
    if config.slack_configured:
        results.append(send_slack_alert(config, ai_result, filenames))
    if config.email_configured:
        results.append(send_email_alert(config, ai_result, filenames))
    return results

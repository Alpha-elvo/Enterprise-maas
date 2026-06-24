"""
services/email_service.py — SMTP Email Alert Service
======================================================
Sends escalation alerts and report notifications via SMTP.
Gracefully skips sending if SMTP credentials are not configured.
"""

import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from config import config
from core.logger import get_logger
from core.models import OrchestratorRun, RoutingDecision

log = get_logger(__name__)


class EmailService:
    """
    SMTP-based email alert service.
    Configure via .env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_RECIPIENTS
    """

    def __init__(self) -> None:
        self._configured = bool(
            config.SMTP_HOST
            and config.SMTP_USER
            and config.SMTP_PASS
            and config.ALERT_RECIPIENTS
        )
        if not self._configured:
            log.info("Email service not configured — alerts disabled.")

    def is_configured(self) -> bool:
        return self._configured

    def send_run_summary(
        self,
        run: OrchestratorRun,
        pdf_bytes: Optional[bytes] = None,
    ) -> bool:
        """
        Send a run completion alert with optional PDF attachment.
        Returns True on success, False on failure or skip.
        """
        if not self._configured:
            log.info("Email skipped — SMTP not configured.")
            return False

        summary     = run.summary or {}
        escalated   = summary.get("escalated_records", 0)
        subject     = (
            f"[CRITICAL] {escalated} Escalations Detected — Run {run.run_id[:8].upper()}"
            if escalated > 0
            else f"[INFO] Analysis Complete — Run {run.run_id[:8].upper()}"
        )

        body_html = self._build_html(run, summary)
        msg       = self._build_message(subject, body_html, pdf_bytes)

        return self._send(msg)

    def send_critical_alert(
        self,
        record_id: str,
        domain: str,
        urgency: str,
        brief: str,
        action: str,
    ) -> bool:
        """
        Fire an immediate alert for a single CRITICAL-urgency record.
        Called inline during orchestration without waiting for run completion.
        """
        if not self._configured:
            return False

        subject  = f"[URGENT] CRITICAL Detection — {domain} / {record_id}"
        body_html = f"""
        <html><body style="font-family:Arial,sans-serif;padding:20px;">
        <div style="background:#7f1d1d;color:white;padding:16px;border-radius:8px;">
            <h2 style="margin:0;">⚠ CRITICAL ALERT</h2>
            <p style="margin:4px 0;">{domain} | {record_id} | Urgency: {urgency}</p>
        </div>
        <div style="padding:16px;background:#f8fafc;margin-top:12px;border-radius:8px;">
            <h3>Situation</h3><p>{brief}</p>
            <h3>Recommended Action</h3><p>{action}</p>
        </div>
        <p style="color:#64748b;font-size:12px;margin-top:20px;">
            Sent by Enterprise Decision Intelligence Platform
        </p>
        </body></html>
        """
        msg = self._build_message(subject, body_html)
        return self._send(msg)

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_html(self, run: OrchestratorRun, summary: dict) -> str:
        rows = ""
        for rec in run.records:
            if not rec.triage:
                continue
            color = {"CRITICAL": "#7f1d1d", "HIGH": "#78350f"}.get(
                rec.triage.urgency, "#1e3a5f"
            )
            rows += (
                f"<tr>"
                f"<td style='padding:8px;'>{rec.record_id}</td>"
                f"<td style='padding:8px;'>{rec.domain}</td>"
                f"<td style='padding:8px;text-align:center;"
                f"background:{color};color:white;font-weight:bold;'>"
                f"{rec.triage.impact_score}/10</td>"
                f"<td style='padding:8px;'>{rec.triage.urgency}</td>"
                f"<td style='padding:8px;'>{rec.routing_decision}</td>"
                f"</tr>"
            )

        return f"""
        <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;padding:20px;">
        <div style="background:#0f172a;color:white;padding:20px;border-radius:8px;">
            <h1 style="margin:0;font-size:20px;">Enterprise Decision Intelligence Platform</h1>
            <p style="margin:4px 0;color:#94a3b8;">Run ID: {run.run_id[:16].upper()}</p>
        </div>
        <div style="display:flex;gap:12px;margin:16px 0;">
            <div style="flex:1;background:#f0fdf4;border:1px solid #86efac;
                        border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:#065f46;">
                    {summary.get("total_records_processed",0)}</div>
                <div style="color:#64748b;font-size:12px;">Records</div>
            </div>
            <div style="flex:1;background:#fff7ed;border:1px solid #fcd34d;
                        border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:#92400e;">
                    {summary.get("escalated_records",0)}</div>
                <div style="color:#64748b;font-size:12px;">Escalated</div>
            </div>
            <div style="flex:1;background:#fef2f2;border:1px solid #fca5a5;
                        border-radius:8px;padding:12px;text-align:center;">
                <div style="font-size:24px;font-weight:bold;color:#991b1b;">
                    {summary.get("errors_encountered",0)}</div>
                <div style="color:#64748b;font-size:12px;">Errors</div>
            </div>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <tr style="background:#0f172a;color:white;">
                <th style="padding:10px;text-align:left;">Record</th>
                <th style="padding:10px;text-align:left;">Domain</th>
                <th style="padding:10px;text-align:center;">Score</th>
                <th style="padding:10px;text-align:left;">Urgency</th>
                <th style="padding:10px;text-align:left;">Decision</th>
            </tr>
            {rows}
        </table>
        <p style="color:#64748b;font-size:11px;margin-top:20px;">
            This is an automated alert from the Enterprise Decision Intelligence Platform.
            Review full findings at your dashboard.
        </p>
        </body></html>
        """

    def _build_message(
        self,
        subject:   str,
        body_html: str,
        pdf_bytes: Optional[bytes] = None,
    ) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"]    = config.SMTP_USER
        msg["To"]      = ", ".join(config.ALERT_RECIPIENTS)
        msg["Subject"] = subject

        msg.attach(MIMEText(body_html, "html"))

        if pdf_bytes:
            pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition", "attachment", filename="intelligence_report.pdf"
            )
            msg.attach(pdf_part)

        return msg

    def _send(self, msg: MIMEMultipart) -> bool:
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(config.SMTP_USER, config.SMTP_PASS)
                server.sendmail(
                    config.SMTP_USER,
                    config.ALERT_RECIPIENTS,
                    msg.as_string(),
                )
            log.info(
                "Email sent",
                extra={"recipients": config.ALERT_RECIPIENTS, "subject": msg["Subject"]},
            )
            return True
        except Exception as exc:
            log.error(f"Email failed: {exc}")
            return False

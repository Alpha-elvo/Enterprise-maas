"""
services/csv_exporter.py — CSV Export Service
===============================================
Pure stdlib implementation (csv module). No third-party dependencies.
Produces separate CSV strings for each data type; caller can bundle as ZIP.

Exports available:
  domain_scores_csv()    — one row per record, triage metadata
  risk_matrix_csv()      — risk categories per domain
  escalations_csv()      — executive briefs and actions
  recommendations_csv()  — prioritised recommendation list
  audit_trail_csv()      — filtered audit events
  export_all_as_zip()    — ZIP archive containing all CSVs
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone
from typing import Optional

from core.logger import get_logger
from core.models import OrchestratorRun, RoutingDecision

log = get_logger(__name__)


class CSVExporter:
    """Stateless CSV exporter. All methods return UTF-8 strings."""

    def domain_scores_csv(self, run: OrchestratorRun) -> str:
        """Impact scores and urgency for all records."""
        fields = [
            "record_id", "domain", "impact_score", "urgency",
            "routing_decision", "overall_risk", "validation_status",
            "confidence", "execution_ms",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in run.records:
            t = rec.triage
            writer.writerow({
                "record_id":        rec.record_id,
                "domain":           rec.domain,
                "impact_score":     t.impact_score if t else 0,
                "urgency":          t.urgency if t else "N/A",
                "routing_decision": rec.routing_decision,
                "overall_risk":     rec.risk.overall_risk_level if rec.risk else "N/A",
                "validation_status": rec.evidence.validation_status if rec.evidence else "N/A",
                "confidence":       (
                    f"{t.explainability.confidence_score:.2f}"
                    if t and t.explainability else "N/A"
                ),
                "execution_ms":     rec.total_execution_ms,
            })
        return buf.getvalue()

    def risk_matrix_csv(self, run: OrchestratorRun) -> str:
        """Risk levels across all categories per domain."""
        cats = ["operational", "financial", "reputational", "regulatory", "strategic"]
        fields = ["record_id", "domain", "overall_risk", "risk_score"] + cats
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in run.records:
            if not rec.risk:
                continue
            row = {
                "record_id":    rec.record_id,
                "domain":       rec.domain,
                "overall_risk": rec.risk.overall_risk_level,
                "risk_score":   rec.risk.risk_score,
            }
            row.update({c: rec.risk.risk_categories.get(c, "N/A") for c in cats})
            writer.writerow(row)
        return buf.getvalue()

    def escalations_csv(self, run: OrchestratorRun) -> str:
        """Executive briefs and actions for all escalated records."""
        fields = [
            "record_id", "domain", "impact_score",
            "executive_brief", "recommended_action",
            "action_link", "escalation_tier", "deadline",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in run.records:
            if rec.routing_decision != RoutingDecision.ESCALATED_TO_AGENTS:
                continue
            e = rec.executive
            writer.writerow({
                "record_id":         rec.record_id,
                "domain":            rec.domain,
                "impact_score":      rec.triage.impact_score if rec.triage else 0,
                "executive_brief":   e.executive_brief    if e else "",
                "recommended_action": e.recommended_action if e else "",
                "action_link":       e.action_link        if e else "",
                "escalation_tier":   e.escalation_tier    if e else "",
                "deadline":          e.response_deadline  if e else "",
            })
        return buf.getvalue()

    def recommendations_csv(self, run: OrchestratorRun) -> str:
        """All recommendations across all escalated records."""
        fields = ["priority", "record_id", "domain", "recommendation", "immediate_next_step"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        counter = 1
        for rec in run.records:
            if not rec.report:
                continue
            for rec_text in rec.report.recommendations:
                writer.writerow({
                    "priority":           counter,
                    "record_id":          rec.record_id,
                    "domain":             rec.domain,
                    "recommendation":     rec_text,
                    "immediate_next_step": (
                        rec.report.next_steps[0] if rec.report.next_steps else ""
                    ),
                })
                counter += 1
        return buf.getvalue()

    def audit_trail_csv(
        self,
        run:         Optional[OrchestratorRun] = None,
        limit:       int = 500,
        filter_severity: Optional[str] = None,
    ) -> str:
        """Audit trail entries, optionally filtered by run and severity."""
        from core.logger import AuditLogger
        entries = AuditLogger.read_all()
        if run:
            entries = [e for e in entries if e.get("run_id") == run.run_id]
        if filter_severity:
            entries = [e for e in entries if e.get("severity") == filter_severity]
        entries = entries[-limit:]

        fields = ["timestamp", "event_type", "severity", "run_id",
                  "record_id", "agent_name", "data"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for e in entries:
            import json
            writer.writerow({
                "timestamp":  e.get("timestamp", ""),
                "event_type": e.get("event_type", ""),
                "severity":   e.get("severity", ""),
                "run_id":     e.get("run_id", ""),
                "record_id":  e.get("record_id", ""),
                "agent_name": e.get("agent_name", ""),
                "data":       json.dumps(e.get("data", {}), default=str)[:200],
            })
        return buf.getvalue()

    def summary_csv(self, run: OrchestratorRun) -> str:
        """Single-row run summary — useful for data warehouse ingestion."""
        summary = run.summary or {}
        fields = list(summary.keys()) + ["run_id", "tenant_id", "model_id", "status"]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        row = dict(summary)
        row.update({
            "run_id": run.run_id, "tenant_id": run.tenant_id,
            "model_id": run.model_id, "status": run.status,
        })
        writer.writerow(row)
        return buf.getvalue()

    def export_all_as_zip(self, run: OrchestratorRun) -> bytes:
        """
        Bundle all CSV exports into a single ZIP archive.
        Returns raw bytes for download or file storage.
        """
        ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            exports = {
                f"run_{run.run_id[:8]}_{ts}_domain_scores.csv":    self.domain_scores_csv(run),
                f"run_{run.run_id[:8]}_{ts}_risk_matrix.csv":      self.risk_matrix_csv(run),
                f"run_{run.run_id[:8]}_{ts}_escalations.csv":      self.escalations_csv(run),
                f"run_{run.run_id[:8]}_{ts}_recommendations.csv":  self.recommendations_csv(run),
                f"run_{run.run_id[:8]}_{ts}_audit_trail.csv":      self.audit_trail_csv(run),
                f"run_{run.run_id[:8]}_{ts}_summary.csv":          self.summary_csv(run),
            }
            for name, content in exports.items():
                zf.writestr(name, content.encode("utf-8"))
        zip_bytes = buf.getvalue()
        buf.close()
        log.info(
            "CSV ZIP export generated",
            extra={"run_id": run.run_id, "bytes": len(zip_bytes), "files": len(exports)},
        )
        return zip_bytes

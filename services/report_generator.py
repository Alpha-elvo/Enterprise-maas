"""
services/report_generator.py — Structured Report Builder
==========================================================
Assembles plain-text and JSON-formatted reports from OrchestratorRun data.
Used by the Streamlit UI for the in-page report viewer and JSON export.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from core.models import OrchestratorRun, RecordResult, RoutingDecision
from core.logger import get_logger

log = get_logger(__name__)


class ReportGenerator:
    """Converts OrchestratorRun into multiple report formats."""

    # ── JSON Export ───────────────────────────────────────────────────────────

    def to_json(self, run: OrchestratorRun, pretty: bool = True) -> str:
        """Full machine-readable export of all agent outputs."""
        try:
            data = run.to_dict()
            return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False, default=str)
        except Exception as exc:
            log.error(f"JSON export failed: {exc}")
            return json.dumps({"error": str(exc)})

    # ── Executive Text Report ─────────────────────────────────────────────────

    def to_executive_text(self, run: OrchestratorRun) -> str:
        """C-suite formatted plain-text report."""
        summary = run.summary or {}
        ts      = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
        lines   = [
            "=" * 72,
            "  ENTERPRISE DECISION INTELLIGENCE REPORT",
            f"  Run ID: {run.run_id[:16].upper()}  |  {ts}",
            "=" * 72,
            "",
            "EXECUTIVE SUMMARY",
            "─" * 40,
            f"  Records Analysed    : {summary.get('total_records_processed', 0)}",
            f"  Escalated           : {summary.get('escalated_records', 0)}",
            f"  Errors              : {summary.get('errors_encountered', 0)}",
            f"  Highest Impact      : {summary.get('highest_impact_record', '—')}",
            f"  Total Tokens Used   : {summary.get('total_tokens_used', 0):,}",
            "",
        ]

        for rec in run.records:
            if rec.routing_decision != RoutingDecision.ESCALATED_TO_AGENTS:
                continue
            lines += self._record_text_block(rec)

        lines += [
            "=" * 72,
            "  END OF REPORT — CONFIDENTIAL",
            "=" * 72,
        ]
        return "\n".join(lines)

    def _record_text_block(self, rec: RecordResult) -> list[str]:
        lines = [
            f"{'─' * 72}",
            f"  DOMAIN: {rec.domain.upper()}  |  RECORD: {rec.record_id}",
            f"{'─' * 72}",
        ]
        if rec.triage:
            lines += [
                f"  Impact Score   : {rec.triage.impact_score}/10",
                f"  Urgency        : {rec.triage.urgency}",
                f"  Risk Flags     : {', '.join(rec.triage.primary_risk_flags)}",
                f"  Summary        : {rec.triage.triage_summary}",
                "",
            ]
        if rec.executive:
            lines += [
                "  RECOMMENDED ACTION:",
                f"  {rec.executive.recommended_action}",
                f"  Deadline       : {rec.executive.response_deadline}",
                f"  Escalation     : {rec.executive.escalation_tier}",
                f"  Resource       : {rec.executive.action_link}",
                "",
            ]
        if rec.risk:
            lines += [
                "  RISK ASSESSMENT:",
                f"  Level: {rec.risk.overall_risk_level}  |  Score: {rec.risk.risk_score:.1f}/10",
                "",
            ]
        if rec.report:
            if rec.report.key_findings:
                lines.append("  KEY FINDINGS:")
                for f_ in rec.report.key_findings:
                    lines.append(f"    • {f_}")
            if rec.report.next_steps:
                lines.append("  NEXT STEPS:")
                for step in rec.report.next_steps:
                    lines.append(f"    → {step}")
            lines.append("")
        return lines

    # ── Board Summary ─────────────────────────────────────────────────────────

    def to_board_summary(self, run: OrchestratorRun) -> str:
        """Ultra-condensed board-level summary (one paragraph per domain)."""
        lines = [
            f"BOARD INTELLIGENCE BRIEF  |  Run {run.run_id[:8].upper()}",
            f"Generated: {datetime.now(timezone.utc).strftime('%d %B %Y')}",
            "─" * 60,
            "",
        ]
        for rec in run.records:
            if rec.routing_decision != RoutingDecision.ESCALATED_TO_AGENTS:
                continue
            if rec.report and rec.report.board_summary:
                lines.append(f"[{rec.domain.upper()}]")
                lines.append(rec.report.board_summary)
                lines.append("")
        return "\n".join(lines)

    # ── Domain Score Index ────────────────────────────────────────────────────

    def score_index(self, run: OrchestratorRun) -> list[dict]:
        """Flat list of domain scores for chart rendering."""
        result = []
        for rec in run.records:
            if rec.triage:
                result.append({
                    "record_id":    rec.record_id,
                    "domain":       rec.domain,
                    "impact_score": rec.triage.impact_score,
                    "urgency":      rec.triage.urgency,
                    "risk_level":   rec.risk.overall_risk_level if rec.risk else "N/A",
                    "confidence":   (rec.triage.explainability.confidence_score
                                     if rec.triage.explainability else 0.0),
                    "escalated":    rec.routing_decision == RoutingDecision.ESCALATED_TO_AGENTS,
                })
        return result

"""
services/pdf_exporter.py — Enterprise PDF Report Generator
============================================================
Produces a multi-page, professionally typeset PDF from an OrchestratorRun.

Report sections:
  1. Cover page   — title, run metadata, classification stamp
  2. Executive Summary  — highest-impact brief for CEO/Board
  3. Domain Analysis    — one section per escalated record
  4. Risk Matrix        — consolidated risk table
  5. Recommendations    — prioritised action list
  6. Audit Metadata     — run stats, token usage, timestamps

Dependency: reportlab (pip install reportlab)
"""

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import config
from core.logger import get_logger
from core.models import OrchestratorRun, RecordResult, RoutingDecision

log = get_logger(__name__)

# ── ReportLab Imports (graceful fallback if not installed) ────────────────────
try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        HRFlowable,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.flowables import KeepTogether
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    log.warning("reportlab not installed — PDF export unavailable. pip install reportlab")


# ── Colour palette (consistent with Streamlit UI) ────────────────────────────
_NAVY      = colors.HexColor("#0f172a")
_INDIGO    = colors.HexColor("#6366f1")
_SLATE     = colors.HexColor("#334155")
_MUTED     = colors.HexColor("#64748b")
_WHITE     = colors.white
_DANGER    = colors.HexColor("#ef4444")
_WARNING   = colors.HexColor("#f59e0b")
_SUCCESS   = colors.HexColor("#10b981")
_INFO      = colors.HexColor("#3b82f6")
_LIGHT_BG  = colors.HexColor("#f8fafc")
_BORDER    = colors.HexColor("#e2e8f0")

_URGENCY_COLORS = {
    "CRITICAL": _DANGER,
    "HIGH":     _WARNING,
    "MEDIUM":   _INFO,
    "LOW":      _SUCCESS,
}


def _urgency_color(urgency: str):
    return _URGENCY_COLORS.get(urgency.upper(), _MUTED)


class PDFExporter:
    """
    Stateless PDF builder. Call export_run() to produce bytes.

    Usage:
        exporter = PDFExporter()
        pdf_bytes = exporter.export_run(orchestrator_run)
        with open("report.pdf", "wb") as f:
            f.write(pdf_bytes)
    """

    PAGE_W, PAGE_H = A4

    def __init__(self) -> None:
        if not REPORTLAB_AVAILABLE:
            raise RuntimeError(
                "reportlab is required for PDF export. "
                "Install with: pip install reportlab"
            )
        self._styles = self._build_styles()

    # ── Public ────────────────────────────────────────────────────────────────

    def export_run(self, run: OrchestratorRun) -> bytes:
        """
        Generate a complete PDF report for the given OrchestratorRun.
        Returns raw bytes suitable for Streamlit st.download_button().
        """
        buffer = io.BytesIO()
        doc = self._build_doc(buffer, run)
        story = self._build_story(run)

        doc.build(story)
        pdf_bytes = buffer.getvalue()
        buffer.close()

        log.info(
            "PDF generated",
            extra={
                "run_id":      run.run_id,
                "size_bytes":  len(pdf_bytes),
                "pages_est":   len(story) // 20,
            },
        )
        return pdf_bytes

    def export_run_to_file(self, run: OrchestratorRun, path: Optional[Path] = None) -> Path:
        """Save PDF to disk and return the file path."""
        if path is None:
            config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = config.REPORTS_DIR / f"report_{run.run_id[:8]}_{ts}.pdf"
        pdf_bytes = self.export_run(run)
        path.write_bytes(pdf_bytes)
        log.info("PDF saved", extra={"path": str(path)})
        return path

    # ── Document Setup ────────────────────────────────────────────────────────

    def _build_doc(self, buffer, run: OrchestratorRun) -> BaseDocTemplate:
        doc = BaseDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
            title=f"Intelligence Report — Run {run.run_id[:8]}",
            author="Enterprise Decision Intelligence Platform",
            subject="Multi-Agent Analysis Report",
        )

        # Cover page (no header/footer)
        cover_frame = Frame(
            doc.leftMargin, doc.bottomMargin,
            doc.width, doc.height,
            id="cover",
        )
        # Normal pages with header + footer
        body_frame = Frame(
            doc.leftMargin,
            doc.bottomMargin + 1.2 * cm,
            doc.width,
            doc.height - 1.5 * cm,
            id="body",
        )

        def _header_footer(canvas, doc):
            canvas.saveState()
            # Header bar
            canvas.setFillColor(_NAVY)
            canvas.rect(
                doc.leftMargin - 0.5 * cm,
                self.PAGE_H - 1.8 * cm,
                doc.width + 1 * cm,
                0.8 * cm,
                fill=1, stroke=0,
            )
            canvas.setFillColor(_WHITE)
            canvas.setFont("Helvetica-Bold", 8)
            canvas.drawString(
                doc.leftMargin,
                self.PAGE_H - 1.35 * cm,
                "ENTERPRISE DECISION INTELLIGENCE PLATFORM  |  CONFIDENTIAL",
            )
            canvas.drawRightString(
                doc.leftMargin + doc.width,
                self.PAGE_H - 1.35 * cm,
                f"Run: {run.run_id[:8].upper()}",
            )
            # Footer
            canvas.setFillColor(_MUTED)
            canvas.setFont("Helvetica", 7)
            canvas.drawString(
                doc.leftMargin,
                0.8 * cm,
                f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  "
                f"Model: {run.model_id}",
            )
            canvas.drawRightString(
                doc.leftMargin + doc.width,
                0.8 * cm,
                f"Page {doc.page}",
            )
            canvas.restoreState()

        doc.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame]),
            PageTemplate(id="normal", frames=[body_frame], onPage=_header_footer),
        ])
        return doc

    # ── Story Builder ─────────────────────────────────────────────────────────

    def _build_story(self, run: OrchestratorRun) -> list:
        story = []
        story += self._cover_page(run)
        story += [NextPageTemplate("normal"), PageBreak()]
        story += self._executive_summary_section(run)
        story += self._domain_analysis_sections(run)
        story += self._risk_matrix_section(run)
        story += self._recommendations_section(run)
        story += self._audit_section(run)
        return story

    # ── Cover Page ────────────────────────────────────────────────────────────

    def _cover_page(self, run: OrchestratorRun) -> list:
        S = self._styles
        ts = datetime.now(timezone.utc).strftime("%d %B %Y  |  %H:%M UTC")
        summary = run.summary or {}

        elements = [
            Spacer(1, 3 * cm),
            Paragraph("ENTERPRISE DECISION", S["cover_super"]),
            Paragraph("INTELLIGENCE REPORT", S["cover_title"]),
            Spacer(1, 0.4 * cm),
            HRFlowable(width="100%", thickness=3, color=_INDIGO, spaceAfter=0.3 * cm),
            Paragraph(f"Multi-Domain Agentic Analysis  ·  8-Agent Pipeline  ·  {ts}", S["cover_sub"]),
            Spacer(1, 2.5 * cm),
        ]

        # Metadata table
        meta_data = [
            ["Run ID",             run.run_id[:16].upper()],
            ["Tenant",             run.tenant_id],
            ["Records Analysed",   str(summary.get("total_records_processed", 0))],
            ["Escalated",          str(summary.get("escalated_records", 0))],
            ["Model",              run.model_id],
            ["Status",             run.status.upper()],
            ["Completed",          run.completed_at or "—"],
        ]
        meta_table = Table(meta_data, colWidths=[5 * cm, 10 * cm])
        meta_table.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (0, -1), _LIGHT_BG),
            ("TEXTCOLOR",   (0, 0), (0, -1), _SLATE),
            ("TEXTCOLOR",   (1, 0), (1, -1), _NAVY),
            ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",    (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("GRID",        (0, 0), (-1, -1), 0.5, _BORDER),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [_WHITE, _LIGHT_BG]),
            ("LEFTPADDING",  (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING",   (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 3 * cm))

        # Classification stamp
        stamp_data = [["⚠  CONFIDENTIAL — INTERNAL USE ONLY  ⚠"]]
        stamp = Table(stamp_data, colWidths=[15 * cm])
        stamp.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), _DANGER),
            ("TEXTCOLOR",    (0, 0), (-1, -1), _WHITE),
            ("FONTNAME",     (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ]))
        elements.append(stamp)
        return elements

    # ── Executive Summary ─────────────────────────────────────────────────────

    def _executive_summary_section(self, run: OrchestratorRun) -> list:
        S = self._styles
        summary = run.summary or {}
        elements = [
            Paragraph("Executive Summary", S["h1"]),
            HRFlowable(width="100%", thickness=1.5, color=_INDIGO, spaceAfter=0.3 * cm),
        ]

        # KPI summary box
        escalated   = summary.get("escalated_records", 0)
        total       = summary.get("total_records_processed", 0)
        errors      = summary.get("errors_encountered", 0)
        tokens      = summary.get("total_tokens_used", 0)
        highest     = summary.get("highest_impact_record", "—")

        kpi_data = [
            ["Records Processed", "Escalated", "Errors", "Tokens Used", "Highest Impact"],
            [str(total), str(escalated), str(errors), f"{tokens:,}", highest],
        ]
        kpi_table = Table(kpi_data, colWidths=[3 * cm] * 5)
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), _WHITE),
            ("BACKGROUND",   (0, 1), (-1, 1), _LIGHT_BG),
            ("TEXTCOLOR",    (0, 1), (-1, 1), _NAVY),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",     (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("GRID",         (0, 0), (-1, -1), 0.5, _BORDER),
            ("TOPPADDING",   (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ]))
        elements.append(kpi_table)
        elements.append(Spacer(1, 0.5 * cm))

        # Per-record executive briefs
        for rec in run.records:
            if rec.routing_decision != RoutingDecision.ESCALATED_TO_AGENTS:
                continue
            if rec.report and rec.report.executive_summary:
                elements.append(KeepTogether([
                    Paragraph(f"{rec.domain}  ·  {rec.record_id}", S["h3"]),
                    Paragraph(rec.report.executive_summary, S["body"]),
                    Spacer(1, 0.3 * cm),
                ]))

        return elements

    # ── Domain Analysis ───────────────────────────────────────────────────────

    def _domain_analysis_sections(self, run: OrchestratorRun) -> list:
        S = self._styles
        elements = [
            PageBreak(),
            Paragraph("Domain Analysis", S["h1"]),
            HRFlowable(width="100%", thickness=1.5, color=_INDIGO, spaceAfter=0.4 * cm),
        ]

        for rec in run.records:
            elements += self._single_record_section(rec, S)

        return elements

    def _single_record_section(self, rec: RecordResult, S: dict) -> list:
        elements = []
        triage   = rec.triage
        if not triage:
            return elements

        urg_color = _urgency_color(triage.urgency)

        # Domain header bar
        header_data = [[
            f"{rec.domain.upper()}  |  {rec.record_id}",
            f"Score: {triage.impact_score}/10  |  {triage.urgency}",
        ]]
        header_table = Table(header_data, colWidths=[10 * cm, 5 * cm])
        header_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), _NAVY),
            ("TEXTCOLOR",    (0, 0), (-1, -1), _WHITE),
            ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",     (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE",     (0, 0), (-1, -1), 10),
            ("ALIGN",        (1, 0), (1, -1), "RIGHT"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING",   (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 8),
        ]))
        elements.append(KeepTogether([header_table]))
        elements.append(Spacer(1, 0.2 * cm))

        # Triage summary
        elements.append(Paragraph("Triage Assessment", S["h3"]))
        elements.append(Paragraph(triage.triage_summary or "—", S["body"]))

        # Risk flags
        if triage.primary_risk_flags:
            flags_text = "  ·  ".join(triage.primary_risk_flags)
            elements.append(Paragraph(f"Risk Flags: {flags_text}", S["caption"]))

        elements.append(Spacer(1, 0.2 * cm))

        # Executive action
        if rec.executive:
            elements.append(Paragraph("Recommended Action", S["h3"]))
            elements.append(Paragraph(rec.executive.recommended_action or "—", S["body"]))
            if rec.executive.action_link:
                elements.append(
                    Paragraph(f"Resource: {rec.executive.action_link}", S["link"])
                )
            elements.append(Paragraph(
                f"Escalation: {rec.executive.escalation_tier}  |  "
                f"Deadline: {rec.executive.response_deadline}",
                S["caption"],
            ))

        # Risk
        if rec.risk:
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph("Risk Assessment", S["h3"]))
            elements.append(Paragraph(
                f"Overall Level: {rec.risk.overall_risk_level}  |  "
                f"Score: {rec.risk.risk_score:.1f}/10",
                S["body"],
            ))
            if rec.risk.mitigation_steps:
                for step in rec.risk.mitigation_steps[:3]:
                    elements.append(Paragraph(f"• {step}", S["bullet"]))

        # Explainability
        if rec.explanation and rec.explanation.decision_rationale:
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph("Decision Rationale", S["h3"]))
            elements.append(Paragraph(rec.explanation.decision_rationale, S["body"]))
            elements.append(Paragraph(
                f"Overall Confidence: {rec.explanation.overall_confidence:.0%}",
                S["caption"],
            ))

        elements.append(Spacer(1, 0.4 * cm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=_BORDER))
        elements.append(Spacer(1, 0.2 * cm))
        return elements

    # ── Risk Matrix ───────────────────────────────────────────────────────────

    def _risk_matrix_section(self, run: OrchestratorRun) -> list:
        S = self._styles
        elements = [
            PageBreak(),
            Paragraph("Consolidated Risk Matrix", S["h1"]),
            HRFlowable(width="100%", thickness=1.5, color=_INDIGO, spaceAfter=0.4 * cm),
        ]

        rows = [["Record", "Domain", "Impact", "Urgency", "Risk Level", "Validation"]]
        for rec in run.records:
            if not rec.triage:
                continue
            rows.append([
                rec.record_id,
                rec.domain,
                str(rec.triage.impact_score) + "/10",
                rec.triage.urgency,
                rec.risk.overall_risk_level if rec.risk else "N/A",
                rec.evidence.validation_status if rec.evidence else "N/A",
            ])

        if len(rows) > 1:
            col_widths = [3 * cm, 3.5 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm]
            table = Table(rows, colWidths=col_widths)
            style = [
                ("BACKGROUND",   (0, 0), (-1, 0), _NAVY),
                ("TEXTCOLOR",    (0, 0), (-1, 0), _WHITE),
                ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",     (0, 0), (-1, -1), 8),
                ("GRID",         (0, 0), (-1, -1), 0.5, _BORDER),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LIGHT_BG]),
                ("ALIGN",        (2, 0), (-1, -1), "CENTER"),
                ("TOPPADDING",   (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ]
            # Colour urgency cells
            for i, rec in enumerate(run.records, start=1):
                if rec.triage and i < len(rows):
                    uc = _urgency_color(rec.triage.urgency)
                    style.append(("TEXTCOLOR", (3, i), (3, i), uc))
                    style.append(("FONTNAME",  (3, i), (3, i), "Helvetica-Bold"))
            table.setStyle(TableStyle(style))
            elements.append(table)
        else:
            elements.append(Paragraph("No triage data available.", S["body"]))

        return elements

    # ── Recommendations ───────────────────────────────────────────────────────

    def _recommendations_section(self, run: OrchestratorRun) -> list:
        S = self._styles
        elements = [
            PageBreak(),
            Paragraph("Prioritised Recommendations", S["h1"]),
            HRFlowable(width="100%", thickness=1.5, color=_INDIGO, spaceAfter=0.4 * cm),
        ]

        counter = 1
        for rec in run.records:
            if rec.routing_decision != RoutingDecision.ESCALATED_TO_AGENTS:
                continue
            if rec.report and rec.report.recommendations:
                elements.append(Paragraph(
                    f"{rec.domain}  ·  {rec.record_id}", S["h3"]
                ))
                for r in rec.report.recommendations:
                    elements.append(Paragraph(f"{counter}. {r}", S["bullet"]))
                    counter += 1
                if rec.report.next_steps:
                    elements.append(Paragraph("Next Steps:", S["caption"]))
                    for step in rec.report.next_steps:
                        elements.append(Paragraph(f"   → {step}", S["bullet"]))
                elements.append(Spacer(1, 0.3 * cm))

        return elements

    # ── Audit Metadata ────────────────────────────────────────────────────────

    def _audit_section(self, run: OrchestratorRun) -> list:
        S = self._styles
        summary = run.summary or {}
        elements = [
            PageBreak(),
            Paragraph("Run Audit Metadata", S["h1"]),
            HRFlowable(width="100%", thickness=1.5, color=_INDIGO, spaceAfter=0.4 * cm),
        ]

        meta = [
            ["Field",                "Value"],
            ["Run ID",               run.run_id],
            ["Tenant",               run.tenant_id],
            ["Model",                run.model_id],
            ["Status",               run.status],
            ["Started",              run.run_timestamp],
            ["Completed",            run.completed_at or "—"],
            ["Total Tokens Used",    f"{summary.get('total_tokens_used', 0):,}"],
            ["Execution Time (ms)",  f"{summary.get('total_execution_ms', 0):,}"],
            ["Total Records",        str(summary.get("total_records_processed", 0))],
            ["Escalated",            str(summary.get("escalated_records", 0))],
            ["Errors",               str(summary.get("errors_encountered", 0))],
        ]

        table = Table(meta, colWidths=[6 * cm, 9 * cm])
        table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), _INDIGO),
            ("TEXTCOLOR",    (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",     (0, 1), (0, -1), "Helvetica-Bold"),
            ("BACKGROUND",   (0, 1), (0, -1), _LIGHT_BG),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("GRID",         (0, 0), (-1, -1), 0.5, _BORDER),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [_WHITE, _LIGHT_BG]),
            ("TOPPADDING",   (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(Paragraph(
            "This document was generated automatically by the Enterprise Decision "
            "Intelligence Platform. All findings should be reviewed by qualified "
            "professionals before operational decisions are made.",
            S["caption"],
        ))
        return elements

    # ── Style Definitions ─────────────────────────────────────────────────────

    def _build_styles(self) -> dict:
        base = getSampleStyleSheet()
        return {
            "cover_super": ParagraphStyle(
                "cover_super", fontSize=14, textColor=_INDIGO,
                fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=4,
            ),
            "cover_title": ParagraphStyle(
                "cover_title", fontSize=32, textColor=_NAVY,
                fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=6,
            ),
            "cover_sub": ParagraphStyle(
                "cover_sub", fontSize=10, textColor=_MUTED,
                fontName="Helvetica", alignment=TA_CENTER,
            ),
            "h1": ParagraphStyle(
                "h1", fontSize=18, textColor=_NAVY,
                fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6,
            ),
            "h2": ParagraphStyle(
                "h2", fontSize=14, textColor=_SLATE,
                fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4,
            ),
            "h3": ParagraphStyle(
                "h3", fontSize=11, textColor=_SLATE,
                fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3,
            ),
            "body": ParagraphStyle(
                "body", fontSize=9, textColor=_SLATE,
                fontName="Helvetica", leading=14, spaceAfter=4,
            ),
            "bullet": ParagraphStyle(
                "bullet", fontSize=9, textColor=_SLATE,
                fontName="Helvetica", leftIndent=14, spaceAfter=2,
            ),
            "caption": ParagraphStyle(
                "caption", fontSize=8, textColor=_MUTED,
                fontName="Helvetica-Oblique", spaceAfter=3,
            ),
            "link": ParagraphStyle(
                "link", fontSize=8, textColor=_INDIGO,
                fontName="Helvetica", spaceAfter=3,
            ),
        }

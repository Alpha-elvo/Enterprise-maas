"""
core/orchestrator.py — Multi-Agent Pipeline Orchestrator
=========================================================
Coordinates all 8 agents across all domain records.
Implements the full state machine:

  [Record] → Agent1(Triage) → gate(score>=7?) → Agents 2-8 (parallel concept)
                                     ↓ NO
                               [Log & Continue]

All results are aggregated into OrchestratorRun and persisted.
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from config import config
from core.logger import get_logger, AuditLogger
from core.models import (
    DomainRecord, OrchestratorRun, RecordResult,
    RoutingDecision, AgentStatus,
)
from agents.strategic_triage import StrategicTriageAgent
from agents.all_agents import (
    ExecutiveEngineAgent,
    RiskAssessorAgent,
    EvidenceValidatorAgent,
    RecommendationQualityAgent,
    ExplainabilityAgent,
    MemoryManagerAgent,
    ReportGeneratorAgent,
)
from services.groq_client import get_client
from storage.database import Database

log = get_logger(__name__)

# Default 5-domain input matrix
DEFAULT_INPUT_MATRIX = [
    DomainRecord(
        record_id="HLTH-001", domain="Health",
        payload=(
            "Patient ID 7734-B, 67-year-old male, ICU admission 14:32 UTC. "
            "Vitals: BP 88/52 mmHg (critical hypotension), HR 121 bpm, SpO2 91% on 6L O2, "
            "Temp 39.8C, GCS 11. Labs: Lactate 4.2 mmol/L, WBC 18.4 x10^9/L, "
            "Procalcitonin 22 ng/mL. Suspected septic shock. Vasopressor initiation pending. "
            "Triage nurse flagged delayed antibiotic administration >3 hrs. "
            "Hospital bed occupancy at 97%. Nearest ICU transfer option: 42 km."
        ),
    ),
    DomainRecord(
        record_id="EDUC-002", domain="Education",
        payload=(
            "District 14 secondary school cohort, Grade 10, n=340 students. "
            "Mid-term diagnostic: Mathematics pass rate 38% (target 70%), "
            "Reading comprehension 54%, STEM project completion 29%. "
            "Teacher-to-student ratio: 1:52 (recommended 1:30). "
            "Three modules show >60% failure rates. 71% of failing students "
            "have >15% absenteeism. 44% lack home internet. Remedial budget: USD 0."
        ),
    ),
    DomainRecord(
        record_id="ENTR-003", domain="Entertainment",
        payload=(
            "Indie artist Mara Osei, Afrobeats-Soul fusion. "
            "Q3 streaming: Spotify 1.2M, Apple Music 340K, YouTube 4.7M views. "
            "Royalty disbursement: USD 1,840 (rate: USD 0.0011/stream). "
            "3 sync licensing inquiries pending, 0 converted. TikTok 22K shares. "
            "Contract clause 7.3 restricts playlist pitching 90 days post-release. "
            "Merchandise: USD 620. Label advance outstanding: USD 14,500. "
            "Breakeven at current rate: 13.2M streams."
        ),
    ),
    DomainRecord(
        record_id="SPRT-004", domain="Sports",
        payload=(
            "Athlete J. Kimani, 400m sprinter, 22 yrs. Pre-season biometric report. "
            "VO2 Max: 58.4 mL/kg/min (elite threshold: 62+). HRV 7-day avg: 41 ms "
            "(baseline 67 ms, 39% decline, overtraining marker). Sleep: 4.1/10. "
            "Left quad 12% weaker than right. Hamstring Grade 1 strain flag. "
            "Training load: 2.3x above periodized plan. Nationals in 18 days. "
            "Physiotherapist: mandatory 5-day rest. Coach override: active."
        ),
    ),
    DomainRecord(
        record_id="POLI-005", domain="Politics/Institutions",
        payload=(
            "Public sentiment, National Housing Policy Draft v2.1. "
            "30-day window, n=184,000 signals. Sentiment: Positive 18%, Neutral 31%, "
            "Negative 51%. Top negatives: affordability (34%), displacement (22%), "
            "corruption in land allocation (19%), rural coverage (25%). "
            "47,200 petition signatures in 12 days. Parliamentary debate in 9 days. "
            "Opposition: 6 legislators against. Coalition margin: 4 seats."
        ),
    ),
]


class Orchestrator:
    """
    Enterprise Multi-Agent Pipeline Orchestrator.

    Usage:
        orc = Orchestrator(tenant_id="acme_corp")
        run = orc.execute(records=DEFAULT_INPUT_MATRIX, progress_cb=my_callback)
    """

    def __init__(
        self,
        tenant_id:   str = "default",
        db:          Optional[Database] = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._db        = db or Database()
        self._client    = get_client()
        self._run_id    = ""

    # ── Public ────────────────────────────────────────────────────────────────

    def execute(
        self,
        records:     list[DomainRecord]  = None,
        progress_cb: Optional[Callable]  = None,
    ) -> OrchestratorRun:
        """
        Run the full 8-agent pipeline over the provided records.

        Args:
            records:     List of DomainRecord inputs (defaults to DEFAULT_INPUT_MATRIX).
            progress_cb: Optional callback(stage: str, pct: float, msg: str)
                         called at each major step for UI progress bars.

        Returns:
            OrchestratorRun with all results and summary statistics.
        """
        records   = records or DEFAULT_INPUT_MATRIX
        run_id    = str(uuid.uuid4())
        self._run_id = run_id
        t_global  = time.monotonic()

        run = OrchestratorRun(
            run_id      = run_id,
            tenant_id   = self._tenant_id,
            model_id    = config.MODEL_ID,
            status      = "running",
        )

        log.info(
            "Orchestrator started",
            extra={
                "run_id":         run_id,
                "tenant_id":      self._tenant_id,
                "record_count":   len(records),
                "model":          config.MODEL_ID,
                "impact_gate":    config.HIGH_IMPACT_THRESHOLD,
            },
        )
        AuditLogger.log(
            event_type = "ORCHESTRATOR_START",
            event_data = {"record_count": len(records), "model": config.MODEL_ID},
            severity   = "INFO",
            run_id     = run_id,
        )

        self._db.create_run(run_id, self._tenant_id, len(records))
        total_steps = len(records)

        for idx, record in enumerate(records, start=1):
            pct = (idx - 1) / total_steps
            self._progress(
                progress_cb, "triage",
                pct, f"[{idx}/{total_steps}] Triaging {record.record_id}…",
            )

            record_result = self._process_record(record, idx, run_id, progress_cb, idx, total_steps)
            run.records.append(record_result)
            run.total_tokens_used  += record_result.total_tokens_used
            run.total_execution_ms += record_result.total_execution_ms

            self._db.save_record_result(run_id, record_result)

        # Finalise run
        run.status       = "completed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        summary          = run.build_summary()

        self._db.complete_run(run_id, summary)
        self._persist_global_state(run)

        self._progress(progress_cb, "done", 1.0, "Analysis complete.")

        AuditLogger.log(
            event_type = "ORCHESTRATOR_COMPLETE",
            event_data = summary,
            severity   = "INFO",
            run_id     = run_id,
        )
        log.info(
            "Orchestrator complete",
            extra={
                "run_id":          run_id,
                "total_tokens":    run.total_tokens_used,
                "elapsed_ms":      int((time.monotonic() - t_global) * 1000),
                "escalated":       summary.get("escalated_records", 0),
                "errors":          summary.get("errors_encountered", 0),
            },
        )
        return run

    # ── Private ───────────────────────────────────────────────────────────────

    def _process_record(
        self,
        record:      DomainRecord,
        idx:         int,
        run_id:      str,
        progress_cb: Optional[Callable],
        current:     int,
        total:       int,
    ) -> RecordResult:
        """Run Agent 1, then conditionally Agents 2-8 for one record."""

        result = RecordResult(
            record_id       = record.record_id,
            domain          = record.domain,
            processing_order = idx,
            routing_decision = RoutingDecision.ERROR_SKIP,
        )
        t0 = time.monotonic()

        # ── Agent 1: Strategic Triage ─────────────────────────────────────────
        agent1 = StrategicTriageAgent(client=self._client, run_id=run_id)
        triage = agent1.run(
            record_id    = record.record_id,
            domain       = record.domain,
            user_message = (
                f"RECORD_ID: {record.record_id}\n"
                f"DOMAIN: {record.domain}\n"
                f"PAYLOAD:\n{record.payload}"
            ),
        )
        result.triage = triage

        if triage.agent_status == AgentStatus.FAILED:
            result.error            = triage.triage_summary
            result.routing_decision = RoutingDecision.ERROR_SKIP
            result.total_execution_ms = int((time.monotonic() - t0) * 1000)
            return result

        log.info(
            "Triage complete",
            extra={
                "record_id":    record.record_id,
                "impact_score": triage.impact_score,
                "urgency":      triage.urgency,
            },
        )

        # ── Routing Gate ──────────────────────────────────────────────────────
        if triage.impact_score < config.HIGH_IMPACT_THRESHOLD:
            result.routing_decision = RoutingDecision.BELOW_THRESHOLD
            result.total_execution_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                f"Score {triage.impact_score} < {config.HIGH_IMPACT_THRESHOLD} — below threshold",
                extra={"record_id": record.record_id},
            )
            return result

        result.routing_decision = RoutingDecision.ESCALATED_TO_AGENTS
        log.info(
            f"Score {triage.impact_score} >= {config.HIGH_IMPACT_THRESHOLD} — escalating",
            extra={"record_id": record.record_id},
        )

        # Build consolidated context for downstream agents
        context_msg = self._build_context(record, triage)

        # ── Agent 2: Executive Brief ──────────────────────────────────────────
        self._progress(progress_cb, "executive",
                       current/total, f"Executive brief: {record.record_id}…")
        agent2 = ExecutiveEngineAgent(client=self._client, run_id=run_id)
        result.executive = agent2.run(record.record_id, record.domain, context_msg)

        # ── Agent 3: Risk Assessment ──────────────────────────────────────────
        self._progress(progress_cb, "risk",
                       current/total, f"Risk assessment: {record.record_id}…")
        agent3 = RiskAssessorAgent(client=self._client, run_id=run_id)
        result.risk = agent3.run(record.record_id, record.domain, context_msg)

        # ── Agent 4: Evidence Validation ──────────────────────────────────────
        self._progress(progress_cb, "evidence",
                       current/total, f"Evidence validation: {record.record_id}…")
        agent4 = EvidenceValidatorAgent(client=self._client, run_id=run_id)
        result.evidence = agent4.run(record.record_id, record.domain, context_msg)

        # ── Agent 5: Recommendation Quality ───────────────────────────────────
        self._progress(progress_cb, "quality",
                       current/total, f"Quality assessment: {record.record_id}…")
        agent5 = RecommendationQualityAgent(client=self._client, run_id=run_id)
        quality_ctx = context_msg
        if result.executive:
            quality_ctx += f"\n\nRECOMMENDED ACTION:\n{result.executive.recommended_action}"
        result.recommendation_quality = agent5.run(record.record_id, record.domain, quality_ctx)

        # ── Agent 6: Explainability ───────────────────────────────────────────
        self._progress(progress_cb, "explain",
                       current/total, f"Building explainability: {record.record_id}…")
        agent6 = ExplainabilityAgent(client=self._client, run_id=run_id)
        explain_ctx = self._build_synthesis_context(record, result)
        result.explanation = agent6.run(record.record_id, record.domain, explain_ctx)

        # ── Agent 7: Memory ───────────────────────────────────────────────────
        self._progress(progress_cb, "memory",
                       current/total, f"Learning patterns: {record.record_id}…")
        agent7 = MemoryManagerAgent(client=self._client, run_id=run_id)
        result.memory = agent7.run(record.record_id, record.domain, context_msg)

        # ── Agent 8: Report Generation ────────────────────────────────────────
        self._progress(progress_cb, "report",
                       current/total, f"Generating report: {record.record_id}…")
        agent8 = ReportGeneratorAgent(client=self._client, run_id=run_id)
        result.report = agent8.run(record.record_id, record.domain, explain_ctx)

        # Aggregate token counts
        result.total_execution_ms = int((time.monotonic() - t0) * 1000)
        return result

    def _build_context(self, record: DomainRecord, triage) -> str:
        return (
            f"RECORD_ID: {record.record_id}\n"
            f"DOMAIN: {record.domain}\n"
            f"ORIGINAL PAYLOAD:\n{record.payload}\n\n"
            f"TRIAGE RESULT:\n"
            f"  Impact Score: {triage.impact_score}/10\n"
            f"  Urgency: {triage.urgency}\n"
            f"  Risk Flags: {', '.join(triage.primary_risk_flags)}\n"
            f"  Summary: {triage.triage_summary}"
        )

    def _build_synthesis_context(self, record: DomainRecord, result: RecordResult) -> str:
        parts = [f"RECORD_ID: {record.record_id}", f"DOMAIN: {record.domain}",
                 f"PAYLOAD:\n{record.payload}\n"]
        if result.triage:
            parts.append(f"TRIAGE: Score={result.triage.impact_score}, "
                         f"Urgency={result.triage.urgency}")
        if result.executive:
            parts.append(f"EXECUTIVE BRIEF:\n{result.executive.executive_brief}")
            parts.append(f"ACTION: {result.executive.recommended_action}")
        if result.risk:
            parts.append(f"RISK: Level={result.risk.overall_risk_level}, "
                         f"Score={result.risk.risk_score}")
        if result.evidence:
            parts.append(f"EVIDENCE: Status={result.evidence.validation_status}, "
                         f"Quality={result.evidence.data_quality_score:.2f}")
        if result.recommendation_quality:
            parts.append(f"REC QUALITY: {result.recommendation_quality.quality_score:.2f}, "
                         f"Feasibility={result.recommendation_quality.feasibility_rating}")
        return "\n\n".join(parts)

    def _persist_global_state(self, run: OrchestratorRun) -> None:
        state_file = config.STORAGE_DIR / "global_state.json"
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(run.to_dict(), f, indent=2, ensure_ascii=False)
            log.info("Global state persisted", extra={"file": str(state_file)})
        except IOError as exc:
            log.error(f"Failed to write global_state.json: {exc}")

    @staticmethod
    def _progress(
        cb: Optional[Callable],
        stage: str,
        pct: float,
        msg: str,
    ) -> None:
        if cb:
            try:
                cb(stage=stage, pct=min(pct, 1.0), msg=msg)
            except Exception:
                pass

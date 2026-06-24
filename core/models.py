"""
core/models.py — Enterprise Data Models
========================================
Single source of truth for all data structures flowing through
the multi-agent pipeline. Uses Python dataclasses for zero-dependency
serialisation with full type safety.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class Urgency(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"

class EscalationTier(str, Enum):
    BOARD           = "BOARD"
    C_SUITE         = "C-SUITE"
    DEPARTMENT_HEAD = "DEPARTMENT-HEAD"
    OPERATIONS      = "OPERATIONS"

class RiskLevel(str, Enum):
    CRITICAL    = "CRITICAL"
    HIGH        = "HIGH"
    MODERATE    = "MODERATE"
    LOW         = "LOW"
    NEGLIGIBLE  = "NEGLIGIBLE"

class ValidationStatus(str, Enum):
    VERIFIED   = "VERIFIED"
    PARTIAL    = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"
    FLAGGED    = "FLAGGED"

class RoutingDecision(str, Enum):
    ESCALATED_TO_AGENTS  = "ESCALATED_TO_AGENTS"
    BELOW_THRESHOLD      = "BELOW_THRESHOLD"
    ERROR_SKIP           = "ERROR_SKIP"

class AgentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"
    SKIPPED = "SKIPPED"


# ── Input ─────────────────────────────────────────────────────────────────────

@dataclass
class DomainRecord:
    """A single raw domain input submitted to the pipeline."""
    record_id:  str
    domain:     str
    payload:    str
    tenant_id:  str  = "default"
    submitted_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict:
        return asdict(self)


# ── Agent Outputs ─────────────────────────────────────────────────────────────

@dataclass
class ExplainabilityBlock:
    """Attached to any agent output to explain its reasoning."""
    reasoning:          str
    confidence_score:   float          # 0.0 – 1.0
    supporting_evidence: list[str]     = field(default_factory=list)
    sources:            list[str]      = field(default_factory=list)
    risks_of_inaction:  list[str]      = field(default_factory=list)
    expected_outcomes:  list[str]      = field(default_factory=list)
    limitations:        str            = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TriageResult:
    """Output from Agent 1 — Strategic Context Triage."""
    record_id:          str
    domain:             str
    impact_score:       int            # 1 – 10
    score_rationale:    str
    primary_risk_flags: list[str]
    structural_validity: str
    validity_notes:     str
    urgency:            str
    stakeholder_tier:   str
    data_freshness:     str
    triage_summary:     str
    explainability:     Optional[ExplainabilityBlock] = None
    agent_status:       str            = AgentStatus.SUCCESS
    execution_time_ms:  int            = 0
    token_usage:        int            = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class ExecutiveBrief:
    """Output from Agent 2 — Executive Content Engine."""
    record_id:          str
    domain:             str
    executive_brief:    str
    recommended_action: str
    action_link:        str
    escalation_tier:    str
    response_deadline:  str
    key_metrics:        list[str]      = field(default_factory=list)
    stakeholders:       list[str]      = field(default_factory=list)
    explainability:     Optional[ExplainabilityBlock] = None
    agent_status:       str            = AgentStatus.SUCCESS
    execution_time_ms:  int            = 0
    token_usage:        int            = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskAssessment:
    """Output from Agent 3 — Risk Assessment Agent."""
    record_id:           str
    domain:              str
    overall_risk_level:  str
    risk_score:          float          # 0.0 – 10.0
    risk_categories:     dict[str, str] = field(default_factory=dict)
    risk_matrix:         list[dict]     = field(default_factory=list)
    mitigation_steps:    list[str]      = field(default_factory=list)
    residual_risks:      list[str]      = field(default_factory=list)
    risk_timeline:       str            = ""
    explainability:      Optional[ExplainabilityBlock] = None
    agent_status:        str            = AgentStatus.SUCCESS
    execution_time_ms:   int            = 0
    token_usage:         int            = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EvidenceValidation:
    """Output from Agent 4 — Evidence Validation Agent."""
    record_id:           str
    domain:              str
    validation_status:   str
    data_quality_score:  float          # 0.0 – 1.0
    verified_claims:     list[str]      = field(default_factory=list)
    disputed_claims:     list[str]      = field(default_factory=list)
    missing_evidence:    list[str]      = field(default_factory=list)
    data_gaps:           list[str]      = field(default_factory=list)
    reliability_notes:   str            = ""
    explainability:      Optional[ExplainabilityBlock] = None
    agent_status:        str            = AgentStatus.SUCCESS
    execution_time_ms:   int            = 0
    token_usage:         int            = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendationQuality:
    """Output from Agent 5 — Recommendation Quality Agent."""
    record_id:           str
    domain:              str
    quality_score:       float          # 0.0 – 1.0
    feasibility_rating:  str
    implementation_steps: list[str]    = field(default_factory=list)
    resource_requirements: list[str]   = field(default_factory=list)
    success_metrics:     list[str]      = field(default_factory=list)
    timeline_estimate:   str            = ""
    quality_flags:       list[str]      = field(default_factory=list)
    explainability:      Optional[ExplainabilityBlock] = None
    agent_status:        str            = AgentStatus.SUCCESS
    execution_time_ms:   int            = 0
    token_usage:         int            = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExplanationReport:
    """Output from Agent 6 — Explainability Agent."""
    record_id:           str
    domain:              str
    decision_rationale:  str
    chain_of_reasoning:  list[str]      = field(default_factory=list)
    key_assumptions:     list[str]      = field(default_factory=list)
    confidence_breakdown: dict[str, float] = field(default_factory=dict)
    alternative_scenarios: list[str]   = field(default_factory=list)
    bias_checks:         list[str]      = field(default_factory=list)
    overall_confidence:  float          = 0.0
    agent_status:        str            = AgentStatus.SUCCESS
    execution_time_ms:   int            = 0
    token_usage:         int            = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MemoryEntry:
    """Output from Agent 7 — Memory and Learning Agent."""
    record_id:           str
    domain:              str
    learned_patterns:    list[str]      = field(default_factory=list)
    historical_matches:  list[str]      = field(default_factory=list)
    trend_signals:       list[str]      = field(default_factory=list)
    anomalies_detected:  list[str]      = field(default_factory=list)
    knowledge_updates:   list[str]      = field(default_factory=list)
    recurrence_score:    float          = 0.0
    agent_status:        str            = AgentStatus.SUCCESS
    execution_time_ms:   int            = 0
    token_usage:         int            = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GeneratedReport:
    """Output from Agent 8 — Report Generation Agent."""
    record_id:              str
    domain:                 str
    executive_summary:      str
    board_summary:          str
    operational_summary:    str
    key_findings:           list[str]   = field(default_factory=list)
    recommendations:        list[str]   = field(default_factory=list)
    next_steps:             list[str]   = field(default_factory=list)
    report_metadata:        dict        = field(default_factory=dict)
    agent_status:           str         = AgentStatus.SUCCESS
    execution_time_ms:      int         = 0
    token_usage:            int         = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Orchestrator Result ───────────────────────────────────────────────────────

@dataclass
class RecordResult:
    """Complete result for a single domain record through all agents."""
    record_id:              str
    domain:                 str
    processing_order:       int
    routing_decision:       str
    triage:                 Optional[TriageResult]           = None
    executive:              Optional[ExecutiveBrief]         = None
    risk:                   Optional[RiskAssessment]         = None
    evidence:               Optional[EvidenceValidation]     = None
    recommendation_quality: Optional[RecommendationQuality] = None
    explanation:            Optional[ExplanationReport]      = None
    memory:                 Optional[MemoryEntry]            = None
    report:                 Optional[GeneratedReport]        = None
    error:                  Optional[str]                    = None
    total_tokens_used:      int                              = 0
    total_execution_ms:     int                              = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OrchestratorRun:
    """Complete result of one full orchestrator execution."""
    run_id:                 str         = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id:              str         = "default"
    run_timestamp:          str         = field(default_factory=lambda: _now())
    model_id:               str         = ""
    status:                 str         = "running"
    records:                list[RecordResult] = field(default_factory=list)
    summary:                dict        = field(default_factory=dict)
    total_tokens_used:      int         = 0
    total_execution_ms:     int         = 0
    completed_at:           Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def build_summary(self) -> dict:
        """Compute aggregate statistics across all processed records."""
        processed     = len(self.records)
        errors        = sum(1 for r in self.records if r.routing_decision == RoutingDecision.ERROR_SKIP)
        escalated     = sum(1 for r in self.records if r.routing_decision == RoutingDecision.ESCALATED_TO_AGENTS)
        below         = sum(1 for r in self.records if r.routing_decision == RoutingDecision.BELOW_THRESHOLD)

        scored_records = [
            r for r in self.records
            if r.triage and r.routing_decision != RoutingDecision.ERROR_SKIP
        ]

        domain_index: dict[str, Any] = {}
        for r in scored_records:
            if r.triage:
                domain_index[r.record_id] = {
                    "domain":       r.domain,
                    "impact_score": r.triage.impact_score,
                    "urgency":      r.triage.urgency,
                    "risk_level":   r.risk.overall_risk_level if r.risk else "N/A",
                }

        highest = max(
            scored_records,
            key=lambda x: x.triage.impact_score if x.triage else 0,
            default=None,
        )

        self.summary = {
            "total_records_processed":  processed,
            "escalated_records":        escalated,
            "below_threshold_records":  below,
            "errors_encountered":       errors,
            "total_tokens_used":        self.total_tokens_used,
            "total_execution_ms":       self.total_execution_ms,
            "highest_impact_record":    highest.record_id if highest else "None",
            "domain_score_index":       domain_index,
            "run_timestamp":            self.run_timestamp,
            "completed_at":             self.completed_at,
        }
        return self.summary


# ── Agent Execution Trace ─────────────────────────────────────────────────────

@dataclass
class AgentTrace:
    """Low-level execution trace for a single agent call."""
    trace_id:       str     = field(default_factory=lambda: str(uuid.uuid4())[:8])
    run_id:         str     = ""
    record_id:      str     = ""
    agent_name:     str     = ""
    agent_version:  str     = "1.0.0"
    status:         str     = AgentStatus.SUCCESS
    input_tokens:   int     = 0
    output_tokens:  int     = 0
    execution_ms:   int     = 0
    error_detail:   str     = ""
    timestamp:      str     = field(default_factory=lambda: _now())

    def to_dict(self) -> dict:
        return asdict(self)


# ── Utility ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def urgency_color(urgency: str) -> str:
    """Return a hex color for a given urgency level (used in UI)."""
    return {
        "CRITICAL": "#FF1744",
        "HIGH":     "#FF6D00",
        "MEDIUM":   "#FFD600",
        "LOW":      "#00E676",
    }.get(urgency.upper(), "#90A4AE")


def score_to_bar(score: int, width: int = 10) -> str:
    """ASCII progress bar for impact scores."""
    filled = "#" * score
    empty  = "-" * (width - score)
    return f"[{filled}{empty}] {score:>2}/10"

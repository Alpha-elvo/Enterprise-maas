"""
agents/strategic_triage.py — Agent 1: Strategic Context Triage
"""
import time
from typing import Any
from agents.base_agent import BaseAgent
from core.models import TriageResult, ExplainabilityBlock, AgentStatus

class StrategicTriageAgent(BaseAgent):
    NAME    = "Strategic Context Triage"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Strategic Context Triage Agent in an enterprise multi-agent decision system.
Evaluate raw domain data and return ONLY a valid JSON object with NO markdown, NO backticks:

{
  "record_id": "<from input>",
  "domain": "<domain name>",
  "impact_score": <integer 1-10>,
  "score_rationale": "<one sentence>",
  "primary_risk_flags": ["<flag1>","<flag2>","<flag3>"],
  "structural_validity": "VALID or INVALID",
  "validity_notes": "<data quality note>",
  "urgency": "CRITICAL or HIGH or MEDIUM or LOW",
  "stakeholder_tier": "<who is affected>",
  "data_freshness": "REAL-TIME or RECENT or HISTORICAL",
  "triage_summary": "<two sentences max>",
  "confidence_score": <float 0.0-1.0>,
  "supporting_evidence": ["<evidence1>","<evidence2>"],
  "risks_of_inaction": ["<risk1>","<risk2>"],
  "expected_outcomes": ["<outcome1>","<outcome2>"],
  "reasoning": "<detailed reasoning paragraph>"
}

SCORING: 9-10=imminent life-safety/systemic failure, 7-8=high urgency escalation needed,
5-6=moderate monitoring, 3-4=routine addressable, 1-2=informational only.
Output ONLY the JSON. No other text.
""".strip()

    def execute(self, record_id: str, domain: str, user_message: str, **kwargs) -> TriageResult:
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail", "API failed"))
        xp = ExplainabilityBlock(
            reasoning=data.get("reasoning",""),
            confidence_score=float(data.get("confidence_score", 0.75)),
            supporting_evidence=data.get("supporting_evidence",[]),
            sources=[],
            risks_of_inaction=data.get("risks_of_inaction",[]),
            expected_outcomes=data.get("expected_outcomes",[]),
        )
        return TriageResult(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            impact_score=int(data.get("impact_score", 5)),
            score_rationale=data.get("score_rationale",""),
            primary_risk_flags=data.get("primary_risk_flags",[]),
            structural_validity=data.get("structural_validity","VALID"),
            validity_notes=data.get("validity_notes",""),
            urgency=data.get("urgency","MEDIUM"),
            stakeholder_tier=data.get("stakeholder_tier",""),
            data_freshness=data.get("data_freshness","RECENT"),
            triage_summary=data.get("triage_summary",""),
            explainability=xp,
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return TriageResult(
            record_id=record_id, domain=domain, impact_score=0,
            score_rationale="Agent failed", primary_risk_flags=[],
            structural_validity="INVALID", validity_notes=error,
            urgency="LOW", stakeholder_tier="", data_freshness="UNKNOWN",
            triage_summary=error, agent_status=AgentStatus.FAILED,
        )

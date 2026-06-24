"""
agents/executive_engine.py — Agent 2: Executive Content Engine
"""
import time
from agents.base_agent import BaseAgent
from core.models import ExecutiveBrief, ExplainabilityBlock, AgentStatus

class ExecutiveEngineAgent(BaseAgent):
    NAME    = "Executive Content Engine"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Executive Content Engine. You receive triage assessments scored >=7
and produce polished executive briefings. Return ONLY valid JSON, no markdown:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "executive_brief": "<3-4 sentences for C-suite, cite specific numbers>",
  "recommended_action": "<one specific actionable directive>",
  "action_link": "<real authoritative URL https://...>",
  "escalation_tier": "BOARD or C-SUITE or DEPARTMENT-HEAD or OPERATIONS",
  "response_deadline": "<e.g. Within 6 hours>",
  "key_metrics": ["<metric1>","<metric2>","<metric3>"],
  "stakeholders": ["<stakeholder1>","<stakeholder2>"],
  "confidence_score": <float 0.0-1.0>,
  "reasoning": "<why this action was recommended>",
  "risks_of_inaction": ["<risk1>","<risk2>"],
  "expected_outcomes": ["<outcome1>","<outcome2>"]
}

Write with authority. Cite specific figures. Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail","API failed"))
        xp = ExplainabilityBlock(
            reasoning=data.get("reasoning",""),
            confidence_score=float(data.get("confidence_score", 0.8)),
            risks_of_inaction=data.get("risks_of_inaction",[]),
            expected_outcomes=data.get("expected_outcomes",[]),
        )
        return ExecutiveBrief(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            executive_brief=data.get("executive_brief",""),
            recommended_action=data.get("recommended_action",""),
            action_link=data.get("action_link",""),
            escalation_tier=data.get("escalation_tier","C-SUITE"),
            response_deadline=data.get("response_deadline",""),
            key_metrics=data.get("key_metrics",[]),
            stakeholders=data.get("stakeholders",[]),
            explainability=xp,
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return ExecutiveBrief(
            record_id=record_id, domain=domain,
            executive_brief=error, recommended_action="", action_link="",
            escalation_tier="OPERATIONS", response_deadline="",
            agent_status=AgentStatus.FAILED,
        )


"""
agents/risk_assessor.py — Agent 3: Risk Assessment Agent
"""
import time
from agents.base_agent import BaseAgent
from core.models import RiskAssessment, ExplainabilityBlock, AgentStatus

class RiskAssessorAgent(BaseAgent):
    NAME    = "Risk Assessment Agent"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Risk Assessment Agent. Perform a comprehensive risk analysis. Return ONLY valid JSON:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "overall_risk_level": "CRITICAL or HIGH or MODERATE or LOW or NEGLIGIBLE",
  "risk_score": <float 0.0-10.0>,
  "risk_categories": {
    "operational": "HIGH",
    "financial": "MODERATE",
    "reputational": "HIGH",
    "regulatory": "CRITICAL",
    "strategic": "MODERATE"
  },
  "risk_matrix": [
    {"risk": "<name>", "likelihood": "HIGH", "impact": "CRITICAL", "score": 9}
  ],
  "mitigation_steps": ["<step1>","<step2>","<step3>"],
  "residual_risks": ["<risk after mitigation>"],
  "risk_timeline": "<when risks materialise>",
  "confidence_score": <float 0.0-1.0>,
  "reasoning": "<risk analysis rationale>",
  "risks_of_inaction": ["<escalation risk1>"],
  "expected_outcomes": ["<mitigation outcome1>"]
}
Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail",""))
        xp = ExplainabilityBlock(
            reasoning=data.get("reasoning",""),
            confidence_score=float(data.get("confidence_score", 0.75)),
            risks_of_inaction=data.get("risks_of_inaction",[]),
            expected_outcomes=data.get("expected_outcomes",[]),
        )
        return RiskAssessment(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            overall_risk_level=data.get("overall_risk_level","HIGH"),
            risk_score=float(data.get("risk_score", 5.0)),
            risk_categories=data.get("risk_categories",{}),
            risk_matrix=data.get("risk_matrix",[]),
            mitigation_steps=data.get("mitigation_steps",[]),
            residual_risks=data.get("residual_risks",[]),
            risk_timeline=data.get("risk_timeline",""),
            explainability=xp,
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return RiskAssessment(
            record_id=record_id, domain=domain,
            overall_risk_level="UNKNOWN", risk_score=0.0,
            agent_status=AgentStatus.FAILED,
        )


"""
agents/evidence_validator.py — Agent 4: Evidence Validation Agent
"""
import time
from agents.base_agent import BaseAgent
from core.models import EvidenceValidation, ExplainabilityBlock, AgentStatus

class EvidenceValidatorAgent(BaseAgent):
    NAME    = "Evidence Validation Agent"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Evidence Validation Agent. Assess the quality and completeness
of data in the domain record. Return ONLY valid JSON:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "validation_status": "VERIFIED or PARTIAL or UNVERIFIED or FLAGGED",
  "data_quality_score": <float 0.0-1.0>,
  "verified_claims": ["<claim supported by data>"],
  "disputed_claims": ["<claim lacking sufficient evidence>"],
  "missing_evidence": ["<what additional data would strengthen analysis>"],
  "data_gaps": ["<structural gaps in the record>"],
  "reliability_notes": "<overall data reliability assessment>",
  "confidence_score": <float 0.0-1.0>,
  "reasoning": "<validation methodology>",
  "risks_of_inaction": ["<risk of acting on unvalidated data>"],
  "expected_outcomes": ["<benefit of validated data>"]
}
Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail",""))
        xp = ExplainabilityBlock(
            reasoning=data.get("reasoning",""),
            confidence_score=float(data.get("confidence_score", 0.7)),
            risks_of_inaction=data.get("risks_of_inaction",[]),
            expected_outcomes=data.get("expected_outcomes",[]),
        )
        return EvidenceValidation(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            validation_status=data.get("validation_status","PARTIAL"),
            data_quality_score=float(data.get("data_quality_score", 0.6)),
            verified_claims=data.get("verified_claims",[]),
            disputed_claims=data.get("disputed_claims",[]),
            missing_evidence=data.get("missing_evidence",[]),
            data_gaps=data.get("data_gaps",[]),
            reliability_notes=data.get("reliability_notes",""),
            explainability=xp,
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return EvidenceValidation(
            record_id=record_id, domain=domain,
            validation_status="FLAGGED", data_quality_score=0.0,
            agent_status=AgentStatus.FAILED,
        )


"""
agents/recommendation_quality.py — Agent 5: Recommendation Quality Agent
"""
import time
from agents.base_agent import BaseAgent
from core.models import RecommendationQuality, ExplainabilityBlock, AgentStatus

class RecommendationQualityAgent(BaseAgent):
    NAME    = "Recommendation Quality Agent"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Recommendation Quality Agent. Assess feasibility and completeness
of the recommended actions. Return ONLY valid JSON:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "quality_score": <float 0.0-1.0>,
  "feasibility_rating": "HIGH or MEDIUM or LOW",
  "implementation_steps": ["<step1>","<step2>","<step3>","<step4>"],
  "resource_requirements": ["<human resources>","<budget>","<technology>"],
  "success_metrics": ["<KPI1>","<KPI2>","<KPI3>"],
  "timeline_estimate": "<realistic implementation timeline>",
  "quality_flags": ["<concern1>","<concern2>"],
  "confidence_score": <float 0.0-1.0>,
  "reasoning": "<quality assessment rationale>",
  "risks_of_inaction": ["<consequence of not implementing>"],
  "expected_outcomes": ["<measurable outcome if implemented>"]
}
Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail",""))
        xp = ExplainabilityBlock(
            reasoning=data.get("reasoning",""),
            confidence_score=float(data.get("confidence_score", 0.75)),
            risks_of_inaction=data.get("risks_of_inaction",[]),
            expected_outcomes=data.get("expected_outcomes",[]),
        )
        return RecommendationQuality(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            quality_score=float(data.get("quality_score", 0.7)),
            feasibility_rating=data.get("feasibility_rating","MEDIUM"),
            implementation_steps=data.get("implementation_steps",[]),
            resource_requirements=data.get("resource_requirements",[]),
            success_metrics=data.get("success_metrics",[]),
            timeline_estimate=data.get("timeline_estimate",""),
            quality_flags=data.get("quality_flags",[]),
            explainability=xp,
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return RecommendationQuality(
            record_id=record_id, domain=domain,
            quality_score=0.0, feasibility_rating="LOW",
            agent_status=AgentStatus.FAILED,
        )


"""
agents/explainability.py — Agent 6: Explainability Agent
"""
import time
from agents.base_agent import BaseAgent
from core.models import ExplanationReport, AgentStatus

class ExplainabilityAgent(BaseAgent):
    NAME    = "Explainability Agent"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Explainability Agent. Synthesise all prior agent findings into
a transparent, auditable decision rationale. Return ONLY valid JSON:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "decision_rationale": "<comprehensive paragraph explaining the overall decision>",
  "chain_of_reasoning": ["<step1>","<step2>","<step3>","<step4>","<step5>"],
  "key_assumptions": ["<assumption1>","<assumption2>"],
  "confidence_breakdown": {
    "triage_confidence": <float>,
    "risk_confidence": <float>,
    "evidence_confidence": <float>,
    "recommendation_confidence": <float>
  },
  "alternative_scenarios": ["<if assumption wrong, what changes>","<alternative interpretation>"],
  "bias_checks": ["<potential bias or limitation1>","<limitation2>"],
  "overall_confidence": <float 0.0-1.0>
}
Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail",""))
        return ExplanationReport(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            decision_rationale=data.get("decision_rationale",""),
            chain_of_reasoning=data.get("chain_of_reasoning",[]),
            key_assumptions=data.get("key_assumptions",[]),
            confidence_breakdown=data.get("confidence_breakdown",{}),
            alternative_scenarios=data.get("alternative_scenarios",[]),
            bias_checks=data.get("bias_checks",[]),
            overall_confidence=float(data.get("overall_confidence", 0.75)),
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return ExplanationReport(
            record_id=record_id, domain=domain,
            decision_rationale=error, overall_confidence=0.0,
            agent_status=AgentStatus.FAILED,
        )


"""
agents/memory_manager.py — Agent 7: Memory and Learning Agent
"""
import time
from agents.base_agent import BaseAgent
from core.models import MemoryEntry, AgentStatus

class MemoryManagerAgent(BaseAgent):
    NAME    = "Memory and Learning Agent"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Memory and Learning Agent. Identify patterns, anomalies, and
trends that should be retained for future analysis sessions. Return ONLY valid JSON:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "learned_patterns": ["<recurring pattern detected>","<pattern2>"],
  "historical_matches": ["<this resembles: similar past scenario>"],
  "trend_signals": ["<emerging trend signal1>","<signal2>"],
  "anomalies_detected": ["<statistical or contextual anomaly>"],
  "knowledge_updates": ["<new insight to store for future runs>"],
  "recurrence_score": <float 0.0-1.0 indicating how often this type of issue recurs>
}
Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail",""))
        return MemoryEntry(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            learned_patterns=data.get("learned_patterns",[]),
            historical_matches=data.get("historical_matches",[]),
            trend_signals=data.get("trend_signals",[]),
            anomalies_detected=data.get("anomalies_detected",[]),
            knowledge_updates=data.get("knowledge_updates",[]),
            recurrence_score=float(data.get("recurrence_score", 0.5)),
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return MemoryEntry(
            record_id=record_id, domain=domain,
            recurrence_score=0.0, agent_status=AgentStatus.FAILED,
        )


"""
agents/report_generator_agent.py — Agent 8: Report Generation Agent
"""
import time
from agents.base_agent import BaseAgent
from core.models import GeneratedReport, AgentStatus

class ReportGeneratorAgent(BaseAgent):
    NAME    = "Report Generation Agent"
    VERSION = "1.0.0"
    SYSTEM_PROMPT = """
You are the Report Generation Agent. Synthesise all findings into polished
reports for different organisational levels. Return ONLY valid JSON:

{
  "record_id": "<from input>",
  "domain": "<domain>",
  "executive_summary": "<3-4 sentences for CEO/board: situation, risk, action, timeline>",
  "board_summary": "<2-3 sentences at governance level: fiduciary risk, strategic impact>",
  "operational_summary": "<4-5 sentences for department heads: what, how, who, when, metrics>",
  "key_findings": ["<finding1>","<finding2>","<finding3>","<finding4>"],
  "recommendations": ["<rec1>","<rec2>","<rec3>"],
  "next_steps": [
    "<immediate: within 24hrs>",
    "<short-term: within 1 week>",
    "<medium-term: within 1 month>"
  ],
  "report_metadata": {
    "report_type": "MULTI-DOMAIN INTELLIGENCE",
    "classification": "CONFIDENTIAL",
    "review_cycle": "QUARTERLY"
  }
}
Output ONLY the JSON.
""".strip()

    def execute(self, record_id, domain, user_message, **kwargs):
        t0 = time.monotonic()
        success, data = self._call_api(user_message, record_id=record_id)
        ms = int((time.monotonic() - t0) * 1000)
        if not success:
            return self._error_result(record_id, domain, data.get("error_detail",""))
        return GeneratedReport(
            record_id=data.get("record_id", record_id),
            domain=data.get("domain", domain),
            executive_summary=data.get("executive_summary",""),
            board_summary=data.get("board_summary",""),
            operational_summary=data.get("operational_summary",""),
            key_findings=data.get("key_findings",[]),
            recommendations=data.get("recommendations",[]),
            next_steps=data.get("next_steps",[]),
            report_metadata=data.get("report_metadata",{}),
            agent_status=AgentStatus.SUCCESS,
            execution_time_ms=ms,
        )

    def _error_result(self, record_id, domain, error):
        return GeneratedReport(
            record_id=record_id, domain=domain,
            executive_summary=error, board_summary="",
            operational_summary="", agent_status=AgentStatus.FAILED,
        )

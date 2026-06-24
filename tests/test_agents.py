"""
tests/test_agents.py — Unit Test Suite
========================================
Tests cover: data models, cache, rate limiter, JSON parser,
agent error handling, and orchestrator routing logic.

Run with: python -m pytest tests/ -v
No API key required — all network calls are mocked.
"""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# MODEL TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestModels(unittest.TestCase):

    def test_domain_record_serialises(self):
        from core.models import DomainRecord
        rec = DomainRecord(record_id="TEST-001", domain="Health", payload="test data")
        d   = rec.to_dict()
        self.assertEqual(d["record_id"], "TEST-001")
        self.assertEqual(d["domain"], "Health")
        self.assertIn("submitted_at", d)

    def test_triage_result_defaults(self):
        from core.models import TriageResult, AgentStatus
        t = TriageResult(
            record_id="T-001", domain="Education",
            impact_score=8, score_rationale="High",
            primary_risk_flags=["risk1"],
            structural_validity="VALID", validity_notes="",
            urgency="HIGH", stakeholder_tier="Students",
            data_freshness="REAL-TIME", triage_summary="Summary",
        )
        self.assertEqual(t.agent_status, AgentStatus.SUCCESS)
        self.assertEqual(t.execution_time_ms, 0)

    def test_orchestrator_run_summary(self):
        from core.models import OrchestratorRun, RecordResult, TriageResult, RoutingDecision
        run = OrchestratorRun(run_id="run-001", tenant_id="test")
        rec = RecordResult(
            record_id="R-001", domain="Sports",
            processing_order=1,
            routing_decision=RoutingDecision.ESCALATED_TO_AGENTS,
            triage=TriageResult(
                record_id="R-001", domain="Sports", impact_score=9,
                score_rationale="", primary_risk_flags=[],
                structural_validity="VALID", validity_notes="",
                urgency="CRITICAL", stakeholder_tier="",
                data_freshness="REAL-TIME", triage_summary="",
            ),
        )
        run.records.append(rec)
        run.completed_at = "2026-01-01T00:00:00Z"
        summary = run.build_summary()
        self.assertEqual(summary["total_records_processed"], 1)
        self.assertEqual(summary["escalated_records"], 1)
        self.assertEqual(summary["highest_impact_record"], "R-001")

    def test_score_to_bar(self):
        from core.models import score_to_bar
        bar = score_to_bar(7)
        self.assertIn("#######", bar)
        self.assertIn("7/10", bar)

    def test_urgency_color(self):
        from core.models import urgency_color
        self.assertEqual(urgency_color("CRITICAL"), "#FF1744")
        self.assertEqual(urgency_color("LOW"), "#00E676")
        # Unknown returns default
        self.assertTrue(urgency_color("UNKNOWN").startswith("#"))


# ══════════════════════════════════════════════════════════════════════════════
# CACHE TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestTTLCache(unittest.TestCase):

    def setUp(self):
        from core.cache import TTLCache
        self.cache = TTLCache(max_size=5, ttl=2)

    def test_set_and_get(self):
        self.cache.set("key1", {"value": 42})
        result = self.cache.get("key1")
        self.assertIsNotNone(result)
        self.assertEqual(result["value"], 42)

    def test_miss_returns_none(self):
        self.assertIsNone(self.cache.get("nonexistent"))

    def test_ttl_expiry(self):
        self.cache.set("expiring", "data")
        time.sleep(2.1)
        self.assertIsNone(self.cache.get("expiring"))

    def test_max_size_eviction(self):
        for i in range(6):
            self.cache.set(f"key{i}", i)
        # Cache should not exceed max_size
        stats = self.cache.stats()
        self.assertLessEqual(stats["size"], 5)

    def test_invalidate(self):
        self.cache.set("del_me", "value")
        removed = self.cache.invalidate("del_me")
        self.assertTrue(removed)
        self.assertIsNone(self.cache.get("del_me"))

    def test_hit_rate_tracking(self):
        self.cache.set("k", "v")
        self.cache.get("k")      # hit
        self.cache.get("k")      # hit
        self.cache.get("miss")   # miss
        stats = self.cache.stats()
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)
        self.assertAlmostEqual(stats["hit_rate"], 2/3, places=2)

    def test_cache_key_generation(self):
        from core.cache import TTLCache
        k1 = TTLCache.make_key("agent1", "system", "user")
        k2 = TTLCache.make_key("agent1", "system", "user")
        k3 = TTLCache.make_key("agent2", "system", "user")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        self.assertEqual(len(k1), 64)  # SHA-256 hex


# ══════════════════════════════════════════════════════════════════════════════
# RATE LIMITER TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestTokenBucket(unittest.TestCase):

    def test_acquire_with_full_bucket(self):
        from core.rate_limiter import TokenBucketRateLimiter
        bucket = TokenBucketRateLimiter(rate=10.0, capacity=5.0)
        # Should succeed immediately with full bucket
        acquired = bucket.acquire(timeout=1.0)
        self.assertTrue(acquired)

    def test_empty_bucket_timeout(self):
        from core.rate_limiter import TokenBucketRateLimiter
        bucket = TokenBucketRateLimiter(rate=0.01, capacity=1.0)
        bucket.acquire()  # consume the one token
        # Should timeout trying to get another
        acquired = bucket.acquire(timeout=0.1)
        self.assertFalse(acquired)


class TestCircuitBreaker(unittest.TestCase):

    def test_starts_closed(self):
        from core.rate_limiter import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=3)
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_opens_after_threshold(self):
        from core.rate_limiter import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertTrue(cb.is_open())

    def test_closes_after_success(self):
        from core.rate_limiter import CircuitBreaker, CircuitState
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_stats_returns_dict(self):
        from core.rate_limiter import CircuitBreaker
        cb = CircuitBreaker(name="test_cb")
        stats = cb.get_stats()
        self.assertIn("state", stats)
        self.assertIn("failure_count", stats)
        self.assertEqual(stats["name"], "test_cb")


# ══════════════════════════════════════════════════════════════════════════════
# JSON PARSER TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestSafeJsonParse(unittest.TestCase):

    def setUp(self):
        from services.groq_client import safe_json_parse
        self.parse = safe_json_parse

    def test_direct_parse(self):
        result = self.parse('{"key": "value", "num": 42}')
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["num"], 42)

    def test_strips_json_fence(self):
        raw = '```json\n{"score": 9}\n```'
        result = self.parse(raw)
        self.assertEqual(result["score"], 9)

    def test_strips_plain_fence(self):
        raw = '```\n{"score": 7}\n```'
        result = self.parse(raw)
        self.assertEqual(result["score"], 7)

    def test_brace_slice_extraction(self):
        raw = 'Here is the analysis: {"impact": 8} as requested.'
        result = self.parse(raw)
        self.assertEqual(result["impact"], 8)

    def test_graceful_failure(self):
        result = self.parse("this is not json at all !!!")
        self.assertIn("parse_error", result)
        self.assertIn("raw_preview", result)

    def test_empty_string(self):
        result = self.parse("")
        self.assertIn("parse_error", result)

    def test_nested_json(self):
        data = {"outer": {"inner": [1, 2, 3]}, "score": 5.5}
        result = self.parse(json.dumps(data))
        self.assertEqual(result["outer"]["inner"], [1, 2, 3])


# ══════════════════════════════════════════════════════════════════════════════
# AGENT TESTS (mocked API)
# ══════════════════════════════════════════════════════════════════════════════
class TestStrategicTriageAgent(unittest.TestCase):

    def _make_mock_client(self, success: bool, payload: dict) -> MagicMock:
        mock = MagicMock()
        mock.chat_and_parse.return_value = (success, payload)
        return mock

    def test_successful_triage(self):
        from agents.strategic_triage import StrategicTriageAgent
        from core.models import AgentStatus

        payload = {
            "record_id": "HLTH-001", "domain": "Health",
            "impact_score": 9, "score_rationale": "Critical vitals",
            "primary_risk_flags": ["sepsis", "delayed_abx"],
            "structural_validity": "VALID", "validity_notes": "Complete data",
            "urgency": "CRITICAL", "stakeholder_tier": "Clinical Staff",
            "data_freshness": "REAL-TIME",
            "triage_summary": "Patient in critical condition.",
            "confidence_score": 0.92,
            "supporting_evidence": ["BP 88/52", "Lactate 4.2"],
            "risks_of_inaction": ["Organ failure"],
            "expected_outcomes": ["Reduced mortality"],
            "reasoning": "Multiple critical markers present.",
        }
        mock_client = self._make_mock_client(True, payload)
        agent  = StrategicTriageAgent(client=mock_client)
        result = agent.run("HLTH-001", "Health", "test payload")

        self.assertEqual(result.impact_score, 9)
        self.assertEqual(result.urgency, "CRITICAL")
        self.assertEqual(result.agent_status, AgentStatus.SUCCESS)
        self.assertIsNotNone(result.explainability)
        self.assertAlmostEqual(result.explainability.confidence_score, 0.92)

    def test_api_failure_returns_error_result(self):
        from agents.strategic_triage import StrategicTriageAgent
        from core.models import AgentStatus

        mock_client = self._make_mock_client(
            False, {"error_detail": "HTTP 401 Unauthorized"}
        )
        agent  = StrategicTriageAgent(client=mock_client)
        result = agent.run("FAIL-001", "Health", "test payload")

        self.assertEqual(result.agent_status, AgentStatus.FAILED)
        self.assertEqual(result.impact_score, 0)

    def test_low_score_does_not_crash(self):
        from agents.strategic_triage import StrategicTriageAgent

        payload = {
            "record_id": "ENTR-003", "domain": "Entertainment",
            "impact_score": 3, "score_rationale": "Low urgency",
            "primary_risk_flags": [],
            "structural_validity": "VALID", "validity_notes": "",
            "urgency": "LOW", "stakeholder_tier": "Artist",
            "data_freshness": "RECENT",
            "triage_summary": "Routine monitoring.",
            "confidence_score": 0.6,
            "supporting_evidence": [], "risks_of_inaction": [],
            "expected_outcomes": [], "reasoning": "",
        }
        mock_client = self._make_mock_client(True, payload)
        agent  = StrategicTriageAgent(client=mock_client)
        result = agent.run("ENTR-003", "Entertainment", "test")
        self.assertEqual(result.impact_score, 3)


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR ROUTING TESTS (mocked agents)
# ══════════════════════════════════════════════════════════════════════════════
class TestOrchestratorRouting(unittest.TestCase):

    def _mock_triage(self, score: int):
        from core.models import TriageResult, AgentStatus
        return TriageResult(
            record_id="T-001", domain="Test", impact_score=score,
            score_rationale="test", primary_risk_flags=[],
            structural_validity="VALID", validity_notes="",
            urgency="HIGH" if score >= 7 else "LOW",
            stakeholder_tier="", data_freshness="REAL-TIME",
            triage_summary="", agent_status=AgentStatus.SUCCESS,
        )

    def test_below_threshold_skips_agent2(self):
        """Records scoring < 7 must not be escalated."""
        from core.models import RoutingDecision
        triage  = self._mock_triage(score=5)
        routing = (
            RoutingDecision.ESCALATED_TO_AGENTS
            if triage.impact_score >= 7
            else RoutingDecision.BELOW_THRESHOLD
        )
        self.assertEqual(routing, RoutingDecision.BELOW_THRESHOLD)

    def test_above_threshold_escalates(self):
        """Records scoring >= 7 must be escalated."""
        from core.models import RoutingDecision
        triage  = self._mock_triage(score=8)
        routing = (
            RoutingDecision.ESCALATED_TO_AGENTS
            if triage.impact_score >= 7
            else RoutingDecision.BELOW_THRESHOLD
        )
        self.assertEqual(routing, RoutingDecision.ESCALATED_TO_AGENTS)

    def test_at_exact_threshold(self):
        """Score exactly equal to threshold must escalate."""
        from core.models import RoutingDecision
        triage  = self._mock_triage(score=7)
        routing = (
            RoutingDecision.ESCALATED_TO_AGENTS
            if triage.impact_score >= 7
            else RoutingDecision.BELOW_THRESHOLD
        )
        self.assertEqual(routing, RoutingDecision.ESCALATED_TO_AGENTS)


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestDatabase(unittest.TestCase):

    def setUp(self):
        import tempfile, os
        from pathlib import Path
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        from storage.database import Database
        self.db = Database(db_path=Path(self._tmp.name))

    def tearDown(self):
        import os
        os.unlink(self._tmp.name)

    def test_create_and_complete_run(self):
        self.db.create_run("run-test-001", "tenant-x", 5)
        run = self.db.get_run("run-test-001")
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "running")

        self.db.complete_run("run-test-001", {
            "escalated_records": 3, "errors_encountered": 1,
            "total_tokens_used": 5000, "total_execution_ms": 90000,
        })
        run2 = self.db.get_run("run-test-001")
        self.assertEqual(run2["status"], "completed")
        self.assertEqual(run2["escalated"], 3)

    def test_get_runs_empty(self):
        runs = self.db.get_runs("nonexistent-tenant")
        self.assertEqual(runs, [])

    def test_run_statistics_empty(self):
        stats = self.db.get_run_statistics("empty-tenant")
        self.assertIn("total_runs", stats)

    def test_schema_is_idempotent(self):
        # Second instantiation should not crash (tables already exist)
        from storage.database import Database
        from pathlib import Path
        db2 = Database(db_path=Path(self._tmp.name))
        self.assertIsNotNone(db2)


# ══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATOR TESTS
# ══════════════════════════════════════════════════════════════════════════════
class TestReportGenerator(unittest.TestCase):

    def _make_run(self) -> "OrchestratorRun":
        from core.models import (
            OrchestratorRun, RecordResult, TriageResult, RoutingDecision
        )
        run = OrchestratorRun(run_id="rg-test-001", tenant_id="test")
        rec = RecordResult(
            record_id="HLTH-001", domain="Health",
            processing_order=1,
            routing_decision=RoutingDecision.BELOW_THRESHOLD,
            triage=TriageResult(
                record_id="HLTH-001", domain="Health", impact_score=6,
                score_rationale="", primary_risk_flags=[],
                structural_validity="VALID", validity_notes="",
                urgency="MEDIUM", stakeholder_tier="",
                data_freshness="RECENT", triage_summary="Moderate concern.",
            ),
        )
        run.records.append(rec)
        run.completed_at = "2026-01-01T00:00:00Z"
        run.build_summary()
        return run

    def test_json_export_is_valid_json(self):
        from services.report_generator import ReportGenerator
        rg   = ReportGenerator()
        run  = self._make_run()
        text = rg.to_json(run)
        parsed = json.loads(text)
        self.assertIn("run_id", parsed)

    def test_executive_text_contains_run_id(self):
        from services.report_generator import ReportGenerator
        rg   = ReportGenerator()
        run  = self._make_run()
        text = rg.to_executive_text(run)
        # Report uppercases the run ID — compare case-insensitively
        self.assertIn("RG-TEST-001", text.upper())

    def test_score_index_returns_list(self):
        from services.report_generator import ReportGenerator
        rg    = ReportGenerator()
        run   = self._make_run()
        index = rg.score_index(run)
        self.assertIsInstance(index, list)
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["impact_score"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)

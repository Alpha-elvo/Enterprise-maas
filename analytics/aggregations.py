"""
analytics/aggregations.py — Time-Series and Cross-Tenant Aggregations
======================================================================
Produces rollup datasets ready for chart rendering in the Streamlit
dashboard and REST API responses.

All functions return plain Python dicts/lists — no Pandas required
at the call site, though Pandas is used internally for efficiency.

Public API:
  daily_run_volume(tenant_id, days)      → [{date, runs, records, escalated}]
  weekly_score_trends(tenant_id, weeks)  → [{week, avg_score, max_score, count}]
  agent_performance_summary(tenant_id)   → [{agent, avg_ms, p95_ms, calls}]
  domain_heatmap_data(tenant_id)         → {domain → {urgency → count}}
  token_consumption_timeline(tenant_id)  → [{date, tokens, runs}]
  cross_tenant_comparison(tenant_ids)    → [{tenant, avg_score, runs, esc_rate}]
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger
from storage.database import Database

log = get_logger(__name__)


class AggregationEngine:
    """
    Produces aggregated, chart-ready datasets from the platform database.
    Stateless — all state is in the injected Database.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or Database()

    # ── Daily run volume ──────────────────────────────────────────────────────

    def daily_run_volume(
        self,
        tenant_id: str = "default",
        days:      int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Daily run volume timeseries for the last `days` days.

        Returns:
            [{date: "2026-01-15", runs: 3, records: 15, escalated: 8}]
        """
        runs = self._db.get_runs(tenant_id, limit=500)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Bucket by calendar date
        buckets: Dict[str, Dict[str, int]] = {}
        for r in runs:
            raw_ts = r.get("started_at", "")
            if not raw_ts:
                continue
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            date_key = ts.strftime("%Y-%m-%d")
            b = buckets.setdefault(date_key, {"runs": 0, "records": 0, "escalated": 0})
            b["runs"]     += 1
            b["records"]  += r.get("total_records", 0)
            b["escalated"] += r.get("escalated", 0)

        # Fill in zero-days so charts show a continuous axis
        result = []
        for i in range(days):
            d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            b = buckets.get(d, {"runs": 0, "records": 0, "escalated": 0})
            result.append({"date": d, **b})

        return result

    # ── Weekly score trends ───────────────────────────────────────────────────

    def weekly_score_trends(
        self,
        tenant_id: str = "default",
        weeks:     int = 12,
    ) -> List[Dict[str, Any]]:
        """
        Weekly average/max impact score for trend charts.

        Returns:
            [{week: "2026-W03", avg_score: 6.8, max_score: 9, count: 14}]
        """
        history = self._db.get_domain_score_history(tenant_id)
        cutoff  = datetime.now(timezone.utc) - timedelta(weeks=weeks)

        week_buckets: Dict[str, List[int]] = defaultdict(list)
        for row in history:
            raw_ts = row.get("created_at", "")
            if not raw_ts:
                continue
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            score = row.get("impact_score", 0)
            week_key = ts.strftime("%Y-W%W")
            week_buckets[week_key].append(score)

        result = []
        for week_key in sorted(week_buckets.keys()):
            scores = week_buckets[week_key]
            result.append({
                "week":      week_key,
                "avg_score": round(statistics.mean(scores), 2) if scores else 0.0,
                "max_score": max(scores) if scores else 0,
                "min_score": min(scores) if scores else 0,
                "count":     len(scores),
            })
        return result

    # ── Agent performance ─────────────────────────────────────────────────────

    def agent_performance_summary(
        self,
        tenant_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """
        Per-agent execution statistics derived from stored record results.

        Returns:
            [{agent: "Strategic Triage", avg_ms: 4200, p95_ms: 6800, calls: 47}]
        """
        records = self._db.get_records_for_run_range(tenant_id, limit=200)

        agent_timings: Dict[str, List[int]] = defaultdict(list)
        agent_names = [
            "Strategic Context Triage", "Executive Content Engine",
            "Risk Assessment Agent", "Evidence Validation Agent",
            "Recommendation Quality Agent", "Explainability Agent",
            "Memory and Learning Agent", "Report Generation Agent",
        ]

        for rec in records:
            result_data = rec.get("result", {})
            agent_map = {
                "triage":                   "Strategic Context Triage",
                "executive":                "Executive Content Engine",
                "risk":                     "Risk Assessment Agent",
                "evidence":                 "Evidence Validation Agent",
                "recommendation_quality":   "Recommendation Quality Agent",
                "explanation":              "Explainability Agent",
                "memory":                   "Memory and Learning Agent",
                "report":                   "Report Generation Agent",
            }
            for key, agent_name in agent_map.items():
                agent_data = result_data.get(key)
                if agent_data and isinstance(agent_data, dict):
                    ms = agent_data.get("execution_time_ms", 0)
                    if ms > 0:
                        agent_timings[agent_name].append(ms)

        result = []
        for agent_name in agent_names:
            timings = agent_timings.get(agent_name, [])
            if not timings:
                result.append({
                    "agent":   agent_name, "calls": 0,
                    "avg_ms":  0, "p95_ms": 0, "p50_ms": 0,
                })
                continue
            sorted_t = sorted(timings)
            p95_idx  = max(0, int(len(sorted_t) * 0.95) - 1)
            p50_idx  = max(0, int(len(sorted_t) * 0.50) - 1)
            result.append({
                "agent":   agent_name,
                "calls":   len(timings),
                "avg_ms":  round(statistics.mean(timings)),
                "p50_ms":  sorted_t[p50_idx],
                "p95_ms":  sorted_t[p95_idx],
            })
        return result

    # ── Domain urgency heatmap ────────────────────────────────────────────────

    def domain_heatmap_data(
        self,
        tenant_id: str = "default",
    ) -> Dict[str, Dict[str, int]]:
        """
        Domain × Urgency count matrix for heatmap rendering.

        Returns:
            {"Health": {"CRITICAL": 3, "HIGH": 2}, "Education": {...}}
        """
        history = self._db.get_domain_score_history(tenant_id)
        result:  Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in history:
            domain  = row.get("domain", "Unknown")
            urgency = row.get("urgency", "UNKNOWN")
            result[domain][urgency] += 1
        # Convert defaultdict to plain dict for serialisation
        return {d: dict(u) for d, u in result.items()}

    # ── Token consumption timeline ────────────────────────────────────────────

    def token_consumption_timeline(
        self,
        tenant_id: str = "default",
        days:      int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Daily token consumption for cost monitoring charts.

        Returns:
            [{date: "2026-01-15", tokens: 12450, runs: 3}]
        """
        runs   = self._db.get_runs(tenant_id, limit=500)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        buckets: Dict[str, Dict[str, int]] = {}
        for r in runs:
            raw_ts = r.get("started_at", "")
            if not raw_ts:
                continue
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts < cutoff:
                continue
            date_key = ts.strftime("%Y-%m-%d")
            b = buckets.setdefault(date_key, {"tokens": 0, "runs": 0})
            b["tokens"] += r.get("total_tokens", 0)
            b["runs"]   += 1

        result = []
        for i in range(days):
            d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            b = buckets.get(d, {"tokens": 0, "runs": 0})
            result.append({"date": d, **b})
        return result

    # ── Cross-tenant comparison ───────────────────────────────────────────────

    def cross_tenant_comparison(
        self,
        tenant_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Multi-tenant KPI comparison — for super-admin dashboards only.

        Returns:
            [{tenant_id, avg_score, total_runs, esc_rate, error_rate}]
        """
        from analytics.metrics_engine import MetricsEngine
        engine = MetricsEngine(self._db)
        result = []
        for tid in tenant_ids:
            stats = engine.run_statistics(tenant_id=tid)
            result.append({
                "tenant_id":      tid,
                "total_runs":     stats["total_runs"],
                "total_records":  stats["total_records"],
                "avg_score":      stats["avg_impact_score"],
                "escalation_rate": stats["escalation_rate"],
                "error_rate":     stats["error_rate"],
            })
        return sorted(result, key=lambda x: x["avg_score"], reverse=True)

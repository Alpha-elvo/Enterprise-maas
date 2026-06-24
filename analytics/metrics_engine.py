"""
analytics/metrics_engine.py — Platform Analytics Engine
=========================================================
Computes aggregate business metrics from the storage layer.
Pure Python + pandas (already a project dependency).
No network calls. Thread-safe read-only operations.

All public methods return plain dicts or DataFrames — never
dataclasses — so callers can serialise to JSON or render charts
without additional transformation.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.logger import get_logger
from storage.database import Database

log = get_logger(__name__)


class MetricsEngine:
    """
    Query engine for platform analytics.
    Instantiate with a Database; all methods are stateless.
    """

    def __init__(self, db: Optional[Database] = None) -> None:
        self._db = db or Database()

    # ── Run statistics ────────────────────────────────────────────────────────

    def run_statistics(
        self,
        tenant_id: str = "default",
        days:      int = 30,
    ) -> Dict[str, Any]:
        """
        Aggregate run statistics for the dashboard KPI row.

        Returns:
            dict with keys: total_runs, total_records, total_escalated,
            total_errors, total_tokens, avg_impact_score, escalation_rate,
            error_rate, avg_tokens_per_run, period_days
        """
        stats  = self._db.get_run_statistics(tenant_id)
        scores = self._db.get_domain_score_history(tenant_id)

        total_runs    = stats.get("total_runs", 0)
        total_records = stats.get("total_records", 0)
        total_esc     = stats.get("total_escalated", 0)
        total_err     = stats.get("total_errors", 0)
        total_tokens  = stats.get("total_tokens", 0)

        all_scores = [s["impact_score"] for s in scores if s.get("impact_score")]
        avg_score  = round(statistics.mean(all_scores), 2) if all_scores else 0.0

        return {
            "period_days":         days,
            "tenant_id":           tenant_id,
            "total_runs":          total_runs,
            "total_records":       total_records,
            "total_escalated":     total_esc,
            "total_errors":        total_err,
            "total_tokens":        total_tokens,
            "avg_impact_score":    avg_score,
            "escalation_rate":     round(total_esc / max(total_records, 1), 3),
            "error_rate":          round(total_err / max(total_records, 1), 3),
            "avg_tokens_per_run":  round(total_tokens / max(total_runs, 1)),
        }

    # ── Domain breakdown ──────────────────────────────────────────────────────

    def domain_breakdown(self, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """
        Per-domain summary: count, avg score, escalation rate, urgency mix.

        Returns:
            List of dicts, sorted by avg_score descending.
        """
        history = self._db.get_domain_score_history(tenant_id)
        if not history:
            return []

        buckets: Dict[str, List] = {}
        for row in history:
            domain = row.get("domain", "Unknown")
            buckets.setdefault(domain, []).append(row)

        result = []
        for domain, rows in buckets.items():
            scores  = [r["impact_score"] for r in rows if r.get("impact_score")]
            urgency_counts: Dict[str, int] = {}
            for r in rows:
                u = r.get("urgency", "UNKNOWN")
                urgency_counts[u] = urgency_counts.get(u, 0) + 1

            escalated = sum(1 for r in rows if r.get("impact_score", 0) >= 7)
            result.append({
                "domain":          domain,
                "record_count":    len(rows),
                "avg_score":       round(statistics.mean(scores), 2) if scores else 0.0,
                "max_score":       max(scores) if scores else 0,
                "min_score":       min(scores) if scores else 0,
                "escalation_rate": round(escalated / max(len(rows), 1), 3),
                "urgency_mix":     urgency_counts,
            })

        return sorted(result, key=lambda x: x["avg_score"], reverse=True)

    # ── Impact score distribution ─────────────────────────────────────────────

    def score_distribution(self, tenant_id: str = "default") -> Dict[str, Any]:
        """
        Histogram-ready score distribution data.

        Returns:
            dict with buckets (0-2, 3-4, 5-6, 7-8, 9-10) and percentages.
        """
        history = self._db.get_domain_score_history(tenant_id)
        scores  = [r["impact_score"] for r in history if r.get("impact_score")]

        if not scores:
            return {"total": 0, "buckets": {}, "percentages": {}}

        buckets = {"0-2": 0, "3-4": 0, "5-6": 0, "7-8": 0, "9-10": 0}
        for s in scores:
            if   s <= 2:  buckets["0-2"]  += 1
            elif s <= 4:  buckets["3-4"]  += 1
            elif s <= 6:  buckets["5-6"]  += 1
            elif s <= 8:  buckets["7-8"]  += 1
            else:         buckets["9-10"] += 1

        total       = len(scores)
        percentages = {k: round(v / total * 100, 1) for k, v in buckets.items()}

        return {
            "total":       total,
            "mean":        round(statistics.mean(scores), 2),
            "median":      round(statistics.median(scores), 2),
            "stdev":       round(statistics.stdev(scores), 2) if len(scores) > 1 else 0.0,
            "buckets":     buckets,
            "percentages": percentages,
        }

    # ── Workflow analytics ────────────────────────────────────────────────────

    def workflow_analytics(self, tenant_id: str = "default") -> Dict[str, Any]:
        """Per-status count and resolution rate for workflows."""
        try:
            from storage.workflow_db import WorkflowDatabase
            wf_db  = WorkflowDatabase()
            counts = wf_db.count_by_status(tenant_id)
        except Exception:
            counts = {}

        total      = sum(counts.values())
        resolved   = counts.get("APPROVED", 0) + counts.get("REJECTED", 0)
        resolution = round(resolved / max(total, 1), 3)

        return {
            "total_workflows":   total,
            "by_status":         counts,
            "resolution_rate":   resolution,
            "pending_count":     counts.get("PENDING_REVIEW", 0),
            "approved_count":    counts.get("APPROVED", 0),
            "rejected_count":    counts.get("REJECTED", 0),
        }

    # ── Top risk records ──────────────────────────────────────────────────────

    def top_risk_records(
        self,
        tenant_id: str = "default",
        limit:     int = 10,
    ) -> List[Dict[str, Any]]:
        """Return the N records with the highest impact scores."""
        history = self._db.get_domain_score_history(tenant_id)
        sorted_history = sorted(
            history,
            key=lambda x: x.get("impact_score", 0),
            reverse=True,
        )
        return [
            {
                "record_id":    r.get("run_id", "")[:8],
                "domain":       r.get("domain", ""),
                "impact_score": r.get("impact_score", 0),
                "urgency":      r.get("urgency", ""),
                "recorded_at":  r.get("created_at", ""),
            }
            for r in sorted_history[:limit]
        ]

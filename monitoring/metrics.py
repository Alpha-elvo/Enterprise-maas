"""
monitoring/metrics.py — Prometheus Metrics Instrumentation
===========================================================
Defines all platform metrics as module-level singletons.
Gracefully degrades to no-op stubs when prometheus_client is absent,
so the rest of the platform never crashes due to missing monitoring.

Metric taxonomy:
  Counters   — monotonically increasing (runs started, errors)
  Gauges     — point-in-time values (active sessions, circuit state)
  Histograms — distributions (latency, token usage)
  Info       — static labels (build version, model)

Usage:
    from monitoring.metrics import metrics
    metrics.runs_total.inc()
    with metrics.agent_duration.labels(agent="Strategic Triage").time():
        result = agent.run(...)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Optional

from core.logger import get_logger

log = get_logger(__name__)

# ── Optional prometheus_client ────────────────────────────────────────────────
try:
    from prometheus_client import (
        Counter, Gauge, Histogram, Info,
        CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
        start_http_server,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False
    log.info("prometheus_client not installed — metrics are no-op stubs.")


# ── No-op stub classes (used when prometheus_client absent) ───────────────────

class _NoOpCounter:
    def inc(self, amount: float = 1) -> None: pass
    def labels(self, **kw) -> "_NoOpCounter": return self

class _NoOpGauge:
    def set(self, v: float) -> None: pass
    def inc(self, v: float = 1) -> None: pass
    def dec(self, v: float = 1) -> None: pass
    def labels(self, **kw) -> "_NoOpGauge": return self

class _NoOpHistogram:
    def observe(self, v: float) -> None: pass
    def labels(self, **kw) -> "_NoOpHistogram": return self
    @contextmanager
    def time(self):
        yield

class _NoOpInfo:
    def info(self, d: dict) -> None: pass


# ── Platform Metrics Registry ─────────────────────────────────────────────────

class PlatformMetrics:
    """
    Single registry of all Prometheus metrics for the platform.
    Instantiate once (module-level singleton `metrics`).
    """

    def __init__(self) -> None:
        if _HAS_PROMETHEUS:
            self._init_prometheus()
        else:
            self._init_stubs()

    def _init_prometheus(self) -> None:
        """Register all real Prometheus metrics."""

        # ── Counters ──────────────────────────────────────────────────────────
        self.runs_total = Counter(
            "platform_runs_total",
            "Total number of orchestrator pipeline runs",
            ["tenant_id", "status"],
        )
        self.records_processed = Counter(
            "platform_records_processed_total",
            "Total domain records processed",
            ["tenant_id", "domain", "routing"],
        )
        self.agent_calls_total = Counter(
            "platform_agent_calls_total",
            "Total agent API calls (Groq)",
            ["agent_name", "status"],
        )
        self.api_requests_total = Counter(
            "platform_api_requests_total",
            "Total REST API requests",
            ["method", "endpoint", "status_code"],
        )
        self.auth_events_total = Counter(
            "platform_auth_events_total",
            "Authentication events",
            ["event_type", "tenant_id"],
        )
        self.workflow_transitions_total = Counter(
            "platform_workflow_transitions_total",
            "Workflow state transitions",
            ["action", "from_state", "to_state"],
        )
        self.tokens_consumed_total = Counter(
            "platform_tokens_consumed_total",
            "Total LLM tokens consumed",
            ["tenant_id", "model"],
        )
        self.export_requests_total = Counter(
            "platform_export_requests_total",
            "Report export requests",
            ["format", "tenant_id"],
        )

        # ── Gauges ────────────────────────────────────────────────────────────
        self.active_sessions = Gauge(
            "platform_active_sessions",
            "Current number of active JWT sessions",
            ["tenant_id"],
        )
        self.circuit_breaker_state = Gauge(
            "platform_circuit_breaker_open",
            "1 if circuit breaker is OPEN, 0 otherwise",
        )
        self.cache_size = Gauge(
            "platform_cache_entries",
            "Current number of cached entries",
        )
        self.cache_hit_rate = Gauge(
            "platform_cache_hit_rate",
            "Cache hit rate (0.0 – 1.0)",
        )
        self.pending_workflows = Gauge(
            "platform_pending_workflows",
            "Workflows awaiting review",
            ["tenant_id"],
        )

        # ── Histograms ────────────────────────────────────────────────────────
        self.run_duration_seconds = Histogram(
            "platform_run_duration_seconds",
            "End-to-end pipeline run duration",
            ["tenant_id"],
            buckets=[10, 30, 60, 120, 300, 600, 1200],
        )
        self.agent_duration_seconds = Histogram(
            "platform_agent_duration_seconds",
            "Individual agent execution duration",
            ["agent_name"],
            buckets=[1, 2, 5, 10, 20, 30, 60],
        )
        self.api_response_seconds = Histogram(
            "platform_api_response_seconds",
            "REST API response time",
            ["endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
        )
        self.impact_score_distribution = Histogram(
            "platform_impact_score",
            "Distribution of domain impact scores",
            ["domain"],
            buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        )
        self.token_usage_per_run = Histogram(
            "platform_token_usage_per_run",
            "Token usage per pipeline run",
            ["tenant_id"],
            buckets=[100, 500, 1000, 2500, 5000, 10000, 25000],
        )

        # ── Info ──────────────────────────────────────────────────────────────
        from config import config
        self.build_info = Info(
            "platform_build",
            "Platform build information",
        )
        self.build_info.info({
            "version": config.APP_VERSION,
            "model":   config.MODEL_ID,
        })

        log.info("Prometheus metrics registered.")

    def _init_stubs(self) -> None:
        """Assign no-op stubs so callers never need to check availability."""
        self.runs_total               = _NoOpCounter()
        self.records_processed        = _NoOpCounter()
        self.agent_calls_total        = _NoOpCounter()
        self.api_requests_total       = _NoOpCounter()
        self.auth_events_total        = _NoOpCounter()
        self.workflow_transitions_total = _NoOpCounter()
        self.tokens_consumed_total    = _NoOpCounter()
        self.export_requests_total    = _NoOpCounter()
        self.active_sessions          = _NoOpGauge()
        self.circuit_breaker_state    = _NoOpGauge()
        self.cache_size               = _NoOpGauge()
        self.cache_hit_rate           = _NoOpGauge()
        self.pending_workflows        = _NoOpGauge()
        self.run_duration_seconds     = _NoOpHistogram()
        self.agent_duration_seconds   = _NoOpHistogram()
        self.api_response_seconds     = _NoOpHistogram()
        self.impact_score_distribution = _NoOpHistogram()
        self.token_usage_per_run      = _NoOpHistogram()
        self.build_info               = _NoOpInfo()

    # ── Scrape helpers ────────────────────────────────────────────────────────

    def collect_system_snapshot(self) -> None:
        """
        Refresh gauge values from live system state.
        Call periodically (e.g. every 15 s) from a background thread.
        """
        try:
            from core.rate_limiter import groq_circuit_breaker
            cb = groq_circuit_breaker.get_stats()
            self.circuit_breaker_state.set(1 if cb["state"] == "OPEN" else 0)
        except Exception:
            pass

        try:
            from core.cache import get_cache
            stats = get_cache().stats()
            self.cache_size.set(stats.get("size", 0))
            self.cache_hit_rate.set(stats.get("hit_rate", 0.0))
        except Exception:
            pass

    def render(self) -> tuple[bytes, str]:
        """Return (output, content_type) for a /metrics HTTP endpoint."""
        if not _HAS_PROMETHEUS:
            return b"# prometheus_client not installed\n", "text/plain"
        return generate_latest(), CONTENT_TYPE_LATEST

    def start_metrics_server(self, port: int = 9090) -> None:
        """Start a standalone HTTP server for Prometheus scraping."""
        if not _HAS_PROMETHEUS:
            log.warning("Cannot start metrics server — prometheus_client not installed.")
            return
        start_http_server(port)
        log.info(f"Prometheus metrics server started on :{port}")

    @property
    def available(self) -> bool:
        return _HAS_PROMETHEUS


# ── Module-level singleton ────────────────────────────────────────────────────
metrics = PlatformMetrics()

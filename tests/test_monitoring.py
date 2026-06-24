"""
tests/test_monitoring.py — Stage 26 Monitoring Test Suite
=========================================================
26 tests across 4 classes.
Prometheus metric tests skip gracefully when prometheus_client is absent.
Health and no-op stub tests always run (stdlib only).

TestNoOpStubs           (8)  — metrics degrade gracefully without prometheus
TestHealthCheck         (10) — component probes, aggregation, status mapping
TestMetricsCollector    (4)  — snapshot collection, render output  [skips w/o prometheus]
TestPrometheusMetrics   (4)  — counter/gauge/histogram registration [skips w/o prometheus]
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    import prometheus_client
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False

_SKIP_PROM = unittest.skipUnless(_HAS_PROMETHEUS, "prometheus_client not installed")


# ══════════════════════════════════════════════════════════════════════════════
# NO-OP STUBS (always runs — no prometheus_client needed)
# ══════════════════════════════════════════════════════════════════════════════
class TestNoOpStubs(unittest.TestCase):

    def setUp(self):
        from monitoring.metrics import _NoOpCounter, _NoOpGauge, _NoOpHistogram, _NoOpInfo
        self.counter   = _NoOpCounter()
        self.gauge     = _NoOpGauge()
        self.histogram = _NoOpHistogram()
        self.info      = _NoOpInfo()

    def test_counter_inc_does_not_raise(self):
        self.counter.inc()
        self.counter.inc(5)

    def test_counter_labels_returns_self(self):
        result = self.counter.labels(agent="test", status="ok")
        self.assertIsInstance(result, type(self.counter))

    def test_gauge_set_does_not_raise(self):
        self.gauge.set(42.0)

    def test_gauge_inc_dec(self):
        self.gauge.inc(1)
        self.gauge.dec(1)

    def test_histogram_observe_does_not_raise(self):
        self.histogram.observe(0.5)

    def test_histogram_time_context_manager(self):
        import time
        with self.histogram.time():
            time.sleep(0.01)    # must complete without error

    def test_info_does_not_raise(self):
        self.info.info({"version": "1.0", "model": "test"})

    def test_metrics_singleton_is_always_accessible(self):
        from monitoring.metrics import metrics
        # These must never raise, regardless of prometheus availability
        metrics.runs_total.inc()
        metrics.agent_calls_total.labels(agent_name="test", status="ok").inc()
        metrics.active_sessions.set(0)
        metrics.run_duration_seconds.observe(10.0)


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════════
class TestHealthCheck(unittest.TestCase):

    def test_liveness_always_returns_true(self):
        from monitoring.health import liveness_check
        self.assertTrue(liveness_check())

    def test_health_check_returns_platform_health(self):
        from monitoring.health import health_check, PlatformHealth
        result = health_check()
        self.assertIsInstance(result, PlatformHealth)

    def test_health_check_has_status(self):
        from monitoring.health import health_check
        result = health_check()
        self.assertIn(result.status, ["healthy", "degraded", "unhealthy"])

    def test_health_check_has_version(self):
        from monitoring.health import health_check
        from config import config
        result = health_check()
        self.assertEqual(result.version, config.APP_VERSION)

    def test_health_check_has_timestamp(self):
        from monitoring.health import health_check
        result = health_check()
        self.assertIsNotNone(result.timestamp)
        self.assertGreater(len(result.timestamp), 10)

    def test_health_check_has_components(self):
        from monitoring.health import health_check
        result = health_check()
        self.assertGreater(len(result.components), 0)

    def test_to_dict_is_json_serialisable(self):
        import json
        from monitoring.health import health_check
        result = health_check()
        d = result.to_dict()
        serialised = json.dumps(d, default=str)
        self.assertIn("status", serialised)

    def test_component_health_ok_method(self):
        from monitoring.health import ComponentHealth
        c_ok  = ComponentHealth(name="db",    status="ok")
        c_err = ComponentHealth(name="cache", status="error")
        self.assertTrue(c_ok.is_ok())
        self.assertFalse(c_err.is_ok())

    def test_readiness_check_returns_tuple(self):
        from monitoring.health import readiness_check
        ready, report = readiness_check()
        self.assertIsInstance(ready, bool)
        self.assertIsInstance(report, dict)
        self.assertIn("status", report)

    def test_unhealthy_status_is_not_ready(self):
        from monitoring.health import PlatformHealth, ComponentHealth
        ph = PlatformHealth(
            status="unhealthy", version="1.0",
            timestamp="2026-01-01T00:00:00Z",
        )
        self.assertFalse(ph.is_ready)

    def test_healthy_status_is_ready(self):
        from monitoring.health import PlatformHealth
        ph = PlatformHealth(
            status="healthy", version="1.0",
            timestamp="2026-01-01T00:00:00Z",
        )
        self.assertTrue(ph.is_ready)


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM SNAPSHOT COLLECTOR (works with stubs)
# ══════════════════════════════════════════════════════════════════════════════
class TestMetricsCollector(unittest.TestCase):

    def test_collect_system_snapshot_does_not_raise(self):
        from monitoring.metrics import metrics
        metrics.collect_system_snapshot()    # must not raise even if deps missing

    def test_render_returns_bytes_and_content_type(self):
        from monitoring.metrics import metrics
        data, ct = metrics.render()
        self.assertIsInstance(data, bytes)
        self.assertIsInstance(ct, str)

    def test_available_property_is_bool(self):
        from monitoring.metrics import metrics
        self.assertIsInstance(metrics.available, bool)

    def test_start_metrics_server_no_crash_without_prometheus(self):
        from monitoring.metrics import metrics, _HAS_PROMETHEUS
        if not _HAS_PROMETHEUS:
            metrics.start_metrics_server(port=19999)   # should log warning, not raise


# ══════════════════════════════════════════════════════════════════════════════
# REAL PROMETHEUS METRICS (skip without prometheus_client)
# ══════════════════════════════════════════════════════════════════════════════
@_SKIP_PROM
class TestPrometheusMetrics(unittest.TestCase):

    def setUp(self):
        from monitoring.metrics import PlatformMetrics
        self.m = PlatformMetrics()

    def test_counter_is_prometheus_counter(self):
        from prometheus_client import Counter
        self.assertIsInstance(self.m.runs_total, Counter)

    def test_gauge_is_prometheus_gauge(self):
        from prometheus_client import Gauge
        self.assertIsInstance(self.m.active_sessions, Gauge)

    def test_histogram_is_prometheus_histogram(self):
        from prometheus_client import Histogram
        self.assertIsInstance(self.m.run_duration_seconds, Histogram)

    def test_render_produces_metric_output(self):
        self.m.runs_total.labels(tenant_id="test", status="completed").inc()
        data, ct = self.m.render()
        self.assertIn(b"platform_runs_total", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)

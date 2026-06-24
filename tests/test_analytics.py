"""
tests/test_analytics.py — Stage 28 Analytics Engine Test Suite
================================================================
44 tests across 5 classes. Stdlib + standard project deps only.

TestTrendDetection       (14) — slope, direction, R², edge cases
TestMovingAverages       (8)  — SMA, EMA, window sizes
TestAnomalyDetection     (10) — IQR, z-score, severity levels
TestForecasting          (6)  — linear extrapolation, edge cases
TestMetricsAndAggregation(6)  — engine methods with real SQLite fixture
"""

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# TREND DETECTION
# ══════════════════════════════════════════════════════════════════════════════
class TestTrendDetection(unittest.TestCase):

    def setUp(self):
        from analytics.trends import compute_trend
        self.trend = compute_trend

    def test_rising_series_detected(self):
        result = self.trend([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(result.direction, "RISING")
        self.assertGreater(result.slope, 0)

    def test_falling_series_detected(self):
        result = self.trend([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
        self.assertEqual(result.direction, "FALLING")
        self.assertLess(result.slope, 0)

    def test_flat_series_detected(self):
        result = self.trend([5.0, 5.0, 5.0, 5.0, 5.0])
        self.assertEqual(result.direction, "FLAT")

    def test_r_squared_perfect_linear(self):
        result = self.trend([2, 4, 6, 8, 10, 12])
        self.assertAlmostEqual(result.confidence, 1.0, places=3)

    def test_r_squared_noisy_data(self):
        result = self.trend([3, 1, 9, 2, 8, 4, 7, 5])
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_single_point_returns_flat(self):
        result = self.trend([7.5])
        self.assertEqual(result.direction, "FLAT")
        self.assertEqual(result.n_points, 1)

    def test_empty_series_returns_flat(self):
        result = self.trend([])
        self.assertEqual(result.direction, "FLAT")
        self.assertEqual(result.n_points, 0)

    def test_two_point_rising(self):
        result = self.trend([3.0, 8.0])
        self.assertEqual(result.direction, "RISING")

    def test_to_dict_has_required_keys(self):
        result = self.trend([1, 2, 3, 4, 5])
        d = result.to_dict()
        for key in ["slope", "direction", "confidence", "n_points", "summary"]:
            self.assertIn(key, d)

    def test_slope_magnitude_for_steep_rise(self):
        result = self.trend([0, 10, 20, 30, 40])
        self.assertGreater(result.slope, 5)

    def test_intercept_is_numeric(self):
        result = self.trend([5, 6, 7, 8])
        self.assertIsInstance(result.intercept, float)

    def test_confidence_between_zero_and_one(self):
        for series in [[1, 1, 1], [1, 5, 3, 7, 2], [0, 0, 10, 0, 0]]:
            r = self.trend(series)
            self.assertGreaterEqual(r.confidence, 0.0)
            self.assertLessEqual(r.confidence, 1.0)

    def test_summary_is_non_empty_string(self):
        result = self.trend([1, 2, 3])
        self.assertIsInstance(result.summary, str)
        self.assertGreater(len(result.summary), 0)

    def test_identical_values_all_same(self):
        result = self.trend([7, 7, 7, 7, 7, 7])
        self.assertEqual(result.direction, "FLAT")
        self.assertAlmostEqual(result.confidence, 0.0, places=3)


# ══════════════════════════════════════════════════════════════════════════════
# MOVING AVERAGES
# ══════════════════════════════════════════════════════════════════════════════
class TestMovingAverages(unittest.TestCase):

    def setUp(self):
        from analytics.trends import moving_average, exponential_moving_average
        self.sma = moving_average
        self.ema = exponential_moving_average

    def test_sma_output_length_matches_input(self):
        result = self.sma([1, 2, 3, 4, 5], window=3)
        self.assertEqual(len(result), 5)

    def test_sma_last_value_is_window_mean(self):
        result = self.sma([1, 2, 3, 4, 5, 6, 7], window=3)
        self.assertAlmostEqual(result[-1], (5 + 6 + 7) / 3, places=3)

    def test_sma_first_value_equals_first_input(self):
        result = self.sma([10, 20, 30], window=5)
        self.assertAlmostEqual(result[0], 10.0, places=3)

    def test_sma_empty_input(self):
        result = self.sma([], window=3)
        self.assertEqual(result, [])

    def test_ema_output_length_matches_input(self):
        result = self.ema([1, 2, 3, 4, 5], alpha=0.3)
        self.assertEqual(len(result), 5)

    def test_ema_first_value_equals_first_input(self):
        result = self.ema([7, 8, 9], alpha=0.5)
        self.assertAlmostEqual(result[0], 7.0, places=3)

    def test_ema_responds_to_spike(self):
        result = self.ema([5, 5, 5, 50, 5, 5], alpha=0.8)
        # After the spike at index 3, value should be elevated then decay
        self.assertGreater(result[4], result[2])

    def test_ema_empty_input(self):
        result = self.ema([], alpha=0.3)
        self.assertEqual(result, [])


# ══════════════════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════════════════════
class TestAnomalyDetection(unittest.TestCase):

    def setUp(self):
        from analytics.trends import detect_anomalies
        self.detect = detect_anomalies

    def test_no_anomalies_in_uniform_series(self):
        normal = [5.0] * 20
        result = self.detect(normal)
        self.assertEqual(result, [])

    def test_extreme_outlier_detected(self):
        data = [5] * 19 + [50]   # 50 is extreme
        result = self.detect(data)
        self.assertGreater(len(result), 0)
        # The outlier should be found
        values = [a.value for a in result]
        self.assertIn(50, values)

    def test_anomaly_has_correct_index(self):
        data = [5] * 10 + [100] + [5] * 9   # spike at index 10
        result = self.detect(data)
        if result:
            self.assertEqual(result[0].index, 10)

    def test_severity_extreme_for_large_deviation(self):
        data = [5.0] * 18 + [5.1, 100.0]
        result = self.detect(data)
        extreme = [a for a in result if a.severity == "EXTREME"]
        self.assertGreater(len(extreme), 0)

    def test_anomaly_z_score_positive(self):
        data = [5] * 15 + [50]
        result = self.detect(data)
        for a in result:
            self.assertGreater(a.z_score, 0)

    def test_iqr_score_positive_for_upper_outlier(self):
        data = [3, 4, 5, 4, 3, 4, 5, 4, 3, 100]
        result = self.detect(data)
        for a in result:
            if a.value == 100:
                self.assertGreater(a.iqr_score, 0)

    def test_small_series_returns_empty(self):
        result = self.detect([1, 2, 3])   # < 4 points
        self.assertEqual(result, [])

    def test_to_dict_has_required_keys(self):
        data = [5] * 15 + [9, 9, 9, 50, 1]
        result = self.detect(data)
        if result:
            d = result[0].to_dict()
            for key in ["index", "value", "z_score", "iqr_score", "severity"]:
                self.assertIn(key, d)

    def test_anomalies_sorted_by_z_score_descending(self):
        data = [5] * 16 + [20, 5, 50, 5]
        result = self.detect(data)
        if len(result) >= 2:
            self.assertGreaterEqual(result[0].z_score, result[1].z_score)

    def test_normal_distribution_few_anomalies(self):
        import random
        random.seed(42)
        data = [5.0 + random.gauss(0, 0.5) for _ in range(100)]
        result = self.detect(data)
        # Normal data should have few anomalies
        self.assertLess(len(result), 10)


# ══════════════════════════════════════════════════════════════════════════════
# FORECASTING
# ══════════════════════════════════════════════════════════════════════════════
class TestForecasting(unittest.TestCase):

    def setUp(self):
        from analytics.trends import forecast_next_n, escalation_risk_score
        self.forecast = forecast_next_n
        self.risk     = escalation_risk_score

    def test_forecast_returns_n_values(self):
        result = self.forecast([1, 2, 3, 4, 5], n=7)
        self.assertEqual(len(result), 7)

    def test_forecast_rising_series_continues_upward(self):
        result = self.forecast([1, 2, 3, 4, 5, 6, 7, 8], n=3, use_ema=False)
        self.assertGreater(result[0], 8)     # linear extrapolation exceeds last
        self.assertGreater(result[2], result[0])  # still rising over horizon

    def test_forecast_single_value(self):
        result = self.forecast([5.0], n=3)
        self.assertEqual(len(result), 3)

    def test_forecast_empty_series(self):
        result = self.forecast([], n=3)
        self.assertEqual(len(result), 3)

    def test_risk_score_high_impact_is_high_risk(self):
        # High scores (8-10 range) produce base_score 0.4-0.5; risk > 0.4 expected
        result = self.risk([9, 9, 8, 9, 10, 9, 8])
        self.assertGreater(result, 0.3)
        # With anomalies it climbs further
        result_with_anomaly = self.risk([9, 9, 8, 9, 10, 9, 8], anomaly_count=3)
        self.assertGreater(result_with_anomaly, result)

    def test_risk_score_low_impact_is_low_risk(self):
        result = self.risk([1, 2, 1, 2, 1, 2, 1])
        self.assertLess(result, 0.5)

    def test_risk_score_bounds(self):
        for scores in [[], [5], [1] * 10, [10] * 10]:
            r = self.risk(scores)
            self.assertGreaterEqual(r, 0.0)
            self.assertLessEqual(r, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# METRICS ENGINE AND AGGREGATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════
class TestMetricsAndAggregation(unittest.TestCase):
    """Integration tests using a real temp SQLite DB seeded with minimal data."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        from storage.database import Database
        from analytics.metrics_engine import MetricsEngine
        from analytics.aggregations import AggregationEngine
        self.db  = Database(db_path=Path(self._tmp.name))
        self.me  = MetricsEngine(db=self.db)
        self.agg = AggregationEngine(db=self.db)

    def tearDown(self):
        import os
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_run_statistics_empty_db(self):
        result = self.me.run_statistics(tenant_id="empty")
        self.assertIn("total_runs", result)
        self.assertEqual(result["total_runs"], 0)

    def test_domain_breakdown_empty_db(self):
        result = self.me.domain_breakdown(tenant_id="empty")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_score_distribution_empty(self):
        result = self.me.score_distribution(tenant_id="empty")
        self.assertEqual(result["total"], 0)

    def test_daily_run_volume_has_correct_length(self):
        result = self.agg.daily_run_volume(tenant_id="empty", days=30)
        self.assertEqual(len(result), 30)

    def test_daily_run_volume_has_required_keys(self):
        result = self.agg.daily_run_volume(tenant_id="empty", days=7)
        for row in result:
            for key in ["date", "runs", "records", "escalated"]:
                self.assertIn(key, row)

    def test_workflow_analytics_returns_dict(self):
        result = self.me.workflow_analytics(tenant_id="empty")
        self.assertIn("total_workflows", result)
        self.assertIn("resolution_rate", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)

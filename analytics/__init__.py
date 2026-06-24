"""
analytics/__init__.py — Analytics Package
==========================================
"""
from analytics.metrics_engine import MetricsEngine
from analytics.aggregations   import AggregationEngine
from analytics.trends import (
    compute_trend, moving_average, exponential_moving_average,
    detect_anomalies, forecast_next_n,
    escalation_risk_score, full_trend_report,
    TrendResult, AnomalyPoint,
)

__all__ = [
    "MetricsEngine", "AggregationEngine",
    "compute_trend", "moving_average", "exponential_moving_average",
    "detect_anomalies", "forecast_next_n",
    "escalation_risk_score", "full_trend_report",
    "TrendResult", "AnomalyPoint",
]

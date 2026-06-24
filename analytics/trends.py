"""
analytics/trends.py — Trend Detection and Anomaly Scoring
==========================================================
Statistical analysis of platform time-series data.
Pure stdlib + minimal Pandas. No scipy/numpy required.

Public API:
  compute_trend(values)       → TrendResult (slope, direction, confidence)
  moving_average(values, n)   → List[float]
  detect_anomalies(scores)    → List[AnomalyPoint]
  forecast_next_n(values, n)  → List[float]
  escalation_risk_score(...)  → float  (0.0–1.0 composite risk signal)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class TrendResult:
    """Result of linear trend analysis over a numeric series."""
    slope:        float          # change per period (positive = upward)
    intercept:    float
    direction:    str            # "RISING" | "FALLING" | "FLAT"
    confidence:   float          # R² value 0.0–1.0
    n_points:     int
    summary:      str            # human-readable description

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slope":       round(self.slope, 4),
            "intercept":   round(self.intercept, 4),
            "direction":   self.direction,
            "confidence":  round(self.confidence, 3),
            "n_points":    self.n_points,
            "summary":     self.summary,
        }


@dataclass
class AnomalyPoint:
    """A data point identified as statistically anomalous."""
    index:      int
    value:      float
    z_score:    float            # standard deviations from mean
    iqr_score:  float            # IQR-based score (>1.5 = outlier, >3.0 = extreme)
    severity:   str              # "EXTREME" | "HIGH" | "MODERATE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index":     self.index,
            "value":     self.value,
            "z_score":   round(self.z_score, 3),
            "iqr_score": round(self.iqr_score, 3),
            "severity":  self.severity,
        }


# ── Trend detection ───────────────────────────────────────────────────────────

def compute_trend(values: List[float], flat_threshold: float = 0.05) -> TrendResult:
    """
    Fit a linear regression over `values` using the OLS closed form.

    Args:
        values:          Time-ordered numeric series (equal intervals assumed).
        flat_threshold:  Normalised |slope| below which trend is FLAT.

    Returns:
        TrendResult with slope, direction, R², and a human summary.
    """
    n = len(values)
    if n < 2:
        return TrendResult(
            slope=0.0, intercept=values[0] if values else 0.0,
            direction="FLAT", confidence=0.0, n_points=n,
            summary="Insufficient data points for trend analysis.",
        )

    xs = list(range(n))
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(values)

    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    ss_xx = sum((x - x_mean) ** 2 for x in xs)

    if ss_xx == 0:
        return TrendResult(
            slope=0.0, intercept=y_mean, direction="FLAT",
            confidence=0.0, n_points=n, summary="All x-values identical.",
        )

    slope     = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean

    # R² calculation
    y_predicted = [slope * x + intercept for x in xs]
    ss_res = sum((y - yp) ** 2 for y, yp in zip(values, y_predicted))
    ss_tot = sum((y - y_mean) ** 2 for y in values)
    r2     = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Normalise slope by value range for direction classification
    val_range = max(values) - min(values) if max(values) != min(values) else 1.0
    norm_slope = abs(slope) / val_range

    if norm_slope < flat_threshold:
        direction = "FLAT"
    elif slope > 0:
        direction = "RISING"
    else:
        direction = "FALLING"

    summary = (
        f"Impact scores are {direction.lower()} "
        f"(slope={slope:+.3f}/period, R²={r2:.2f}, n={n})."
    )

    return TrendResult(
        slope=slope, intercept=intercept, direction=direction,
        confidence=max(0.0, min(1.0, r2)), n_points=n, summary=summary,
    )


# ── Moving average ────────────────────────────────────────────────────────────

def moving_average(values: List[float], window: int = 7) -> List[float]:
    """
    Simple moving average with edge-handling (shrinking window at start).

    Returns a list of the same length as `values`.
    """
    if not values:
        return []
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_vals = values[start: i + 1]
        result.append(round(statistics.mean(window_vals), 3))
    return result


def exponential_moving_average(
    values: List[float], alpha: float = 0.3
) -> List[float]:
    """
    EMA with smoothing factor alpha (0 < alpha ≤ 1).
    Higher alpha → more responsive to recent values.
    """
    if not values:
        return []
    ema = [values[0]]
    for v in values[1:]:
        ema.append(alpha * v + (1 - alpha) * ema[-1])
    return [round(e, 3) for e in ema]


# ── Anomaly detection ─────────────────────────────────────────────────────────

def detect_anomalies(
    values:         List[float],
    z_threshold:    float = 2.5,
    iqr_multiplier: float = 1.5,
) -> List[AnomalyPoint]:
    """
    Identify statistical outliers using both Z-score and IQR methods.
    A point is flagged if it exceeds either threshold.

    Args:
        values:         Numeric series to analyse.
        z_threshold:    |z-score| above which a point is anomalous.
        iqr_multiplier: IQR fence multiplier (1.5 = mild, 3.0 = extreme).

    Returns:
        List of AnomalyPoint sorted by severity.
    """
    if len(values) < 4:
        return []

    mean = statistics.mean(values)
    try:
        stdev = statistics.stdev(values)
    except statistics.StatisticsError:
        stdev = 0.0

    sorted_vals = sorted(values)
    q1_idx = len(sorted_vals) // 4
    q3_idx = 3 * len(sorted_vals) // 4
    q1  = sorted_vals[q1_idx]
    q3  = sorted_vals[min(q3_idx, len(sorted_vals) - 1)]
    iqr = q3 - q1
    lower_fence = q1 - iqr_multiplier * iqr
    upper_fence = q3 + iqr_multiplier * iqr

    anomalies = []
    for i, v in enumerate(values):
        z = abs(v - mean) / stdev if stdev > 0 else 0.0
        iqr_score = 0.0
        if iqr > 0:
            if v < q1:
                iqr_score = (q1 - v) / iqr
            elif v > q3:
                iqr_score = (v - q3) / iqr

        is_anomaly = z > z_threshold or v < lower_fence or v > upper_fence
        if not is_anomaly:
            continue

        if z > z_threshold * 1.5 or iqr_score > 3.0:
            severity = "EXTREME"
        elif z > z_threshold or iqr_score > 1.5:
            severity = "HIGH"
        else:
            severity = "MODERATE"

        anomalies.append(AnomalyPoint(
            index=i, value=v, z_score=z,
            iqr_score=iqr_score, severity=severity,
        ))

    return sorted(anomalies, key=lambda a: a.z_score, reverse=True)


# ── Forecasting ───────────────────────────────────────────────────────────────

def forecast_next_n(
    values:    List[float],
    n:         int = 7,
    use_ema:   bool = True,
) -> List[float]:
    """
    Simple linear extrapolation (or EMA-smoothed) forecast for next N periods.

    Not a replacement for proper ML forecasting — useful for lightweight
    "expected trajectory" indicators on dashboards.

    Returns:
        List of N forecast values.
    """
    if len(values) < 2:
        return [values[0]] * n if values else [0.0] * n

    if use_ema:
        smoothed = exponential_moving_average(values, alpha=0.3)
    else:
        smoothed = values

    trend = compute_trend(smoothed)
    last_x = len(smoothed) - 1

    return [
        round(trend.slope * (last_x + i + 1) + trend.intercept, 2)
        for i in range(n)
    ]


# ── Composite escalation risk signal ─────────────────────────────────────────

def escalation_risk_score(
    recent_scores:      List[float],
    historical_mean:    float = 5.0,
    trend_result:       Optional[TrendResult] = None,
    anomaly_count:      int = 0,
) -> float:
    """
    Composite 0.0–1.0 risk signal for the escalation probability dashboard.

    Formula:
      risk = 0.5 × (current_mean / 10)
            + 0.3 × trend_factor
            + 0.2 × anomaly_factor

    Args:
        recent_scores:   Recent impact scores (last 7–30 periods).
        historical_mean: Long-term baseline average score.
        trend_result:    Pre-computed TrendResult (computed if None).
        anomaly_count:   Number of anomalies detected in recent window.

    Returns:
        Float in [0.0, 1.0]. Above 0.7 = high risk, above 0.5 = elevated.
    """
    if not recent_scores:
        return 0.0

    current_mean = statistics.mean(recent_scores)
    base_score   = current_mean / 10.0

    if trend_result is None:
        trend_result = compute_trend(recent_scores)
    trend_factor = {
        "RISING":  1.0,
        "FLAT":    0.5,
        "FALLING": 0.0,
    }.get(trend_result.direction, 0.5) * trend_result.confidence

    anomaly_factor = min(1.0, anomaly_count / 5.0)

    risk = (0.5 * base_score) + (0.3 * trend_factor) + (0.2 * anomaly_factor)
    return round(max(0.0, min(1.0, risk)), 3)


# ── Convenience: full analytics report ───────────────────────────────────────

def full_trend_report(
    scores: List[float],
    domain: str = "",
) -> Dict[str, Any]:
    """
    Run all trend analyses on a score series and return a combined report.
    Suitable for embedding in PDF reports or API responses.
    """
    if not scores:
        return {
            "domain": domain, "n": 0,
            "trend": None, "anomalies": [], "forecast_7d": [],
            "risk_score": 0.0, "summary": "No data available.",
        }

    trend     = compute_trend(scores)
    anomalies = detect_anomalies(scores)
    forecast  = forecast_next_n(scores, n=7)
    risk      = escalation_risk_score(
        scores, trend_result=trend, anomaly_count=len(anomalies)
    )

    return {
        "domain":       domain,
        "n":            len(scores),
        "trend":        trend.to_dict(),
        "anomalies":    [a.to_dict() for a in anomalies],
        "anomaly_count": len(anomalies),
        "forecast_7d":  forecast,
        "risk_score":   risk,
        "risk_level":   (
            "HIGH" if risk > 0.7
            else "ELEVATED" if risk > 0.5
            else "NORMAL"
        ),
        "moving_avg_7d": moving_average(scores, window=7),
        "summary":       trend.summary,
    }

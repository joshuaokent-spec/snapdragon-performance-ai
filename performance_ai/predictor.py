from __future__ import annotations

import time
from collections import deque
from statistics import fmean

from .config import AppConfig
from .models import PressurePrediction, TelemetrySnapshot


class ResourcePressurePredictor:
    """Predict near-future memory pressure from a rolling telemetry window.

    v0.2 uses a tiny statistical trend model because it is deterministic,
    cheap, and produces training labels immediately. The interface is designed
    so a learned ONNX model can replace this implementation later without
    changing the rest of the application.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._history: deque[tuple[float, float]] = deque()

    def _trim_history(self, now: float) -> None:
        cutoff = now - max(30, self.config.pressure_prediction_window_seconds)
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    @staticmethod
    def _linear_slope(points: list[tuple[float, float]]) -> float:
        """Return memory-percent change per second via least-squares slope."""
        if len(points) < 2:
            return 0.0

        t0 = points[0][0]
        xs = [t - t0 for t, _ in points]
        ys = [value for _, value in points]
        x_mean = fmean(xs)
        y_mean = fmean(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator <= 0:
            return 0.0
        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        return numerator / denominator

    def update(self, snap: TelemetrySnapshot) -> PressurePrediction | None:
        if not self.config.pressure_predictor_enabled:
            return None

        now = time.monotonic()
        current = float(snap.memory_percent)
        self._history.append((now, current))
        self._trim_history(now)

        min_samples = max(2, self.config.pressure_prediction_min_samples)
        if len(self._history) < min_samples:
            return None

        points = list(self._history)
        span = points[-1][0] - points[0][0]
        if span < max(5.0, self.config.telemetry_interval_seconds * (min_samples - 1) * 0.7):
            return None

        slope_per_second = self._linear_slope(points)
        horizon = max(30, self.config.pressure_prediction_horizon_seconds)
        predicted = max(0.0, min(100.0, current + slope_per_second * horizon))
        slope_per_minute = slope_per_second * 60.0

        # Confidence rises with sample count and observed time span. We cap it
        # below 1.0 because a straight-line extrapolation is never certain.
        sample_factor = min(1.0, len(points) / max(min_samples * 2, 6))
        span_factor = min(1.0, span / max(60.0, self.config.pressure_prediction_window_seconds * 0.6))
        confidence = round(min(0.90, 0.35 + 0.35 * sample_factor + 0.20 * span_factor), 2)

        if predicted >= self.config.memory_critical_percent:
            risk = "critical"
        elif predicted >= self.config.pressure_prediction_warn_percent:
            risk = "high"
        elif slope_per_minute >= 1.0:
            risk = "rising"
        else:
            risk = "stable"

        return PressurePrediction(
            timestamp=snap.timestamp,
            horizon_seconds=horizon,
            current_memory_percent=round(current, 1),
            predicted_memory_percent=round(predicted, 1),
            memory_slope_percent_per_minute=round(slope_per_minute, 2),
            risk=risk,
            confidence=confidence,
            source="statistical",
        )

from performance_ai.config import AppConfig
from performance_ai.models import TelemetrySnapshot
from performance_ai.predictor import ResourcePressurePredictor


def snap(memory: float) -> TelemetrySnapshot:
    return TelemetrySnapshot(
        timestamp="2026-01-01T00:00:00+00:00",
        cpu_percent=10.0,
        memory_percent=memory,
        disk_percent=50.0,
        battery_percent=100.0,
        plugged_in=True,
        foreground_process="WindowsTerminal.exe",
        power_scheme="Balanced",
        npu_percent=0.0,
        top_processes=[],
    )


def test_predictor_needs_minimum_samples(monkeypatch):
    config = AppConfig(
        pressure_prediction_min_samples=4,
        pressure_prediction_window_seconds=300,
    )
    predictor = ResourcePressurePredictor(config)
    times = iter([0.0, 10.0, 20.0])
    monkeypatch.setattr("performance_ai.predictor.time.monotonic", lambda: next(times))

    assert predictor.update(snap(70.0)) is None
    assert predictor.update(snap(71.0)) is None
    assert predictor.update(snap(72.0)) is None


def test_predictor_detects_rising_memory(monkeypatch):
    config = AppConfig(
        telemetry_interval_seconds=5,
        pressure_prediction_min_samples=4,
        pressure_prediction_horizon_seconds=120,
        pressure_prediction_window_seconds=300,
        pressure_prediction_warn_percent=88.0,
        memory_critical_percent=92.0,
    )
    predictor = ResourcePressurePredictor(config)
    times = iter([0.0, 10.0, 20.0, 30.0])
    monkeypatch.setattr("performance_ai.predictor.time.monotonic", lambda: next(times))

    predictor.update(snap(70.0))
    predictor.update(snap(72.0))
    predictor.update(snap(74.0))
    prediction = predictor.update(snap(76.0))

    assert prediction is not None
    assert prediction.predicted_memory_percent > 76.0
    assert prediction.memory_slope_percent_per_minute > 0
    assert prediction.risk in {"high", "critical"}


def test_predictor_stable_memory_stays_stable(monkeypatch):
    config = AppConfig(pressure_prediction_min_samples=4)
    predictor = ResourcePressurePredictor(config)
    times = iter([0.0, 10.0, 20.0, 30.0])
    monkeypatch.setattr("performance_ai.predictor.time.monotonic", lambda: next(times))

    predictor.update(snap(65.0))
    predictor.update(snap(65.1))
    predictor.update(snap(64.9))
    prediction = predictor.update(snap(65.0))

    assert prediction is not None
    assert prediction.risk == "stable"

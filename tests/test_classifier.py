from performance_ai.classifier import RuleClassifier
from performance_ai.models import ProcessSample, TelemetrySnapshot


def snap(**overrides):
    data = dict(
        timestamp="2026-01-01T00:00:00+00:00",
        cpu_percent=10.0,
        memory_percent=30.0,
        disk_percent=50.0,
        battery_percent=80.0,
        plugged_in=True,
        foreground_process="explorer.exe",
        power_scheme="Balanced",
        npu_percent=0.0,
        top_processes=[],
    )
    data.update(overrides)
    return TelemetrySnapshot(**data)


def test_low_battery_wins():
    rec = RuleClassifier().classify(
        snap(battery_percent=15.0, plugged_in=False)
    )
    assert rec.profile == "BATTERY_SAVER"


def test_npu_activity_detects_ai():
    rec = RuleClassifier().classify(snap(npu_percent=35.0))
    assert rec.workload == "AI_INFERENCE"
    assert rec.profile == "LOCAL_AI"


def test_development_detection():
    rec = RuleClassifier().classify(
        snap(
            foreground_process="Code.exe",
            top_processes=[
                ProcessSample(1, "python.exe", 20.0, 5.0)
            ],
        )
    )
    assert rec.profile == "DEVELOPMENT"

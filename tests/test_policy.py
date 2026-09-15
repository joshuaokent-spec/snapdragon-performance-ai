from performance_ai.config import AppConfig
from performance_ai.models import ProcessSample, Recommendation, TelemetrySnapshot
from performance_ai.policy import PolicyEngine


def snap(battery=80.0, plugged=True, cpu=90.0, memory=60.0, foreground="python.exe", top=None):
    return TelemetrySnapshot(
        timestamp="2026-01-01T00:00:00+00:00",
        cpu_percent=cpu,
        memory_percent=memory,
        disk_percent=50.0,
        battery_percent=battery,
        plugged_in=plugged,
        foreground_process=foreground,
        power_scheme="Balanced",
        npu_percent=0.0,
        top_processes=top or [],
    )


def test_very_low_battery_forces_saver():
    config = AppConfig(very_low_battery_percent=15)
    rec = Recommendation(
        "HEAVY_COMPUTE", "PERFORMANCE", 0.9, "Heavy compute.", "test"
    )
    out = PolicyEngine(config).validate(snap(10.0, False), rec)
    assert out.profile == "BATTERY_SAVER"
    assert out.source == "policy"


def test_low_battery_blocks_performance():
    config = AppConfig(low_battery_percent=25)
    rec = Recommendation(
        "HEAVY_COMPUTE", "PERFORMANCE", 0.9, "Heavy compute.", "test"
    )
    out = PolicyEngine(config).validate(snap(20.0, False), rec)
    assert out.profile == "BALANCED"


def test_low_confidence_ai_override_keeps_rule_baseline():
    config = AppConfig()
    telemetry = snap(
        cpu=8.0,
        memory=84.0,
        foreground="WindowsTerminal.exe",
        top=[ProcessSample(10, "msedge.exe", 2.0, 5.0)],
    )
    baseline = Recommendation(
        "MULTITASKING", "BALANCED", 0.72, "Memory pressure.", "rules"
    )
    ai = Recommendation(
        "DATA_WORK", "BALANCED", 0.72, "Data workload.", "foundry-local-http"
    )
    out = PolicyEngine(config).validate(telemetry, ai, baseline=baseline)
    assert out.workload == "MULTITASKING"
    assert out.profile == "BALANCED"
    assert out.source == "policy-fusion"


def test_high_confidence_supported_ai_override_is_allowed():
    config = AppConfig()
    telemetry = snap(
        cpu=45.0,
        memory=82.0,
        foreground="python.exe",
        top=[ProcessSample(11, "python.exe", 18.0, 10.0)],
    )
    baseline = Recommendation(
        "MULTITASKING", "BALANCED", 0.72, "Memory pressure.", "rules"
    )
    ai = Recommendation(
        "DATA_WORK", "DATA_SCIENCE", 0.88, "Python data workload.", "foundry-local-http"
    )
    out = PolicyEngine(config).validate(telemetry, ai, baseline=baseline)
    assert out.workload == "DATA_WORK"
    assert out.profile == "DATA_SCIENCE"
    assert out.source == "foundry-local-http"

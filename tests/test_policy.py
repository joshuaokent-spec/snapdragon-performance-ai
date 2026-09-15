from performance_ai.config import AppConfig
from performance_ai.models import Recommendation, TelemetrySnapshot
from performance_ai.policy import PolicyEngine


def snap(battery=80.0, plugged=True):
    return TelemetrySnapshot(
        timestamp="2026-01-01T00:00:00+00:00",
        cpu_percent=90.0,
        memory_percent=60.0,
        disk_percent=50.0,
        battery_percent=battery,
        plugged_in=plugged,
        foreground_process="python.exe",
        power_scheme="Balanced",
        npu_percent=0.0,
        top_processes=[],
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

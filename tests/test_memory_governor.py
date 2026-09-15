from performance_ai.config import AppConfig
from performance_ai.memory_governor import MemoryGovernor
from performance_ai.models import TelemetrySnapshot


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


def test_governor_stays_quiet_below_high_threshold():
    config = AppConfig(
        advisor_mode=True,
        memory_high_percent=85.0,
        memory_critical_percent=92.0,
    )
    results = MemoryGovernor(config).evaluate(snap(84.9))
    assert results == []


def test_governor_reports_high_pressure_in_advisor_mode():
    config = AppConfig(
        advisor_mode=True,
        memory_high_percent=85.0,
        memory_critical_percent=92.0,
        memory_priority_allowlist=[],
    )
    results = MemoryGovernor(config).evaluate(snap(86.0))
    assert len(results) == 1
    assert results[0].action == "memory_governor"
    assert results[0].requested == "high"
    assert results[0].applied is False


def test_governor_reports_critical_pressure_in_advisor_mode():
    config = AppConfig(
        advisor_mode=True,
        memory_high_percent=85.0,
        memory_critical_percent=92.0,
        memory_priority_allowlist=[],
    )
    results = MemoryGovernor(config).evaluate(snap(94.0))
    assert len(results) == 1
    assert results[0].requested == "critical"
    assert results[0].applied is False

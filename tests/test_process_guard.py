from performance_ai.config import AppConfig
from performance_ai.process_guard import GuardCandidate, ProcessGuard


class FakeProcess:
    def __init__(self, pid: int, name: str):
        self.pid = pid
        self._name = name

    def name(self):
        return self._name

    def children(self, recursive=True):
        return []


def test_advisor_mode_never_closes_candidate():
    config = AppConfig(advisor_mode=True)
    guard = ProcessGuard(config)
    fake = FakeProcess(1234, "steam.exe")
    results = guard._close_candidate(
        GuardCandidate(fake, "startup guard test", 500.0)
    )
    assert len(results) == 1
    assert results[0].action == "process_guard"
    assert results[0].applied is False
    assert "Advisor Mode" in results[0].detail


def test_startup_guard_requires_allowlist(monkeypatch):
    config = AppConfig(
        advisor_mode=True,
        startup_guard_enabled=True,
        startup_guard_grace_seconds=45,
        startup_guard_window_seconds=600,
        startup_close_allowlist=["steam.exe"],
    )
    guard = ProcessGuard(config)
    fake = FakeProcess(1234, "steam.exe")
    monkeypatch.setattr(guard, "_safe_processes", lambda: [fake])
    monkeypatch.setattr("performance_ai.process_guard.time.time", lambda: 1000.0)
    monkeypatch.setattr("performance_ai.process_guard.psutil.boot_time", lambda: 900.0)
    monkeypatch.setattr("performance_ai.process_guard._rss_mb", lambda proc: 500.0)

    candidates = guard._startup_candidates(100.0)
    assert len(candidates) == 1
    assert candidates[0].proc.name() == "steam.exe"


def test_background_guard_respects_idle_time(monkeypatch):
    config = AppConfig(
        advisor_mode=True,
        background_guard_enabled=True,
        background_close_allowlist=["Discord.exe"],
        background_close_idle_seconds=1800,
        background_close_min_memory_mb=100.0,
    )
    guard = ProcessGuard(config)
    fake = FakeProcess(2222, "Discord.exe")
    guard._first_seen[2222] = 0.0
    guard._last_foreground[2222] = 100.0
    monkeypatch.setattr(guard, "_safe_processes", lambda: [fake])
    monkeypatch.setattr("performance_ai.process_guard._rss_mb", lambda proc: 400.0)

    assert guard._background_candidates(1800.0) == []
    candidates = guard._background_candidates(1901.0)
    assert len(candidates) == 1
    assert candidates[0].proc.name() == "Discord.exe"

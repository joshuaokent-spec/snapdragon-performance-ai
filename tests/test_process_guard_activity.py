from performance_ai.activity_tracker import ProcessActivity
from performance_ai.config import AppConfig
from performance_ai.process_guard import ProcessGuard


class FakeProcess:
    def __init__(self, pid: int, name: str):
        self.pid = pid
        self._name = name

    def name(self):
        return self._name

    def children(self, recursive=True):
        return []


def sample(pid=2222, **overrides):
    values = dict(
        pid=pid,
        name="Discord.exe",
        rss_mb=400.0,
        cpu_percent=0.0,
        io_kbps=0.0,
        observation_seconds=1901.0,
        seconds_since_foreground=1801.0,
        has_baseline=True,
        foreground=False,
    )
    values.update(overrides)
    return ProcessActivity(**values)


def make_guard(monkeypatch):
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
    monkeypatch.setattr(
        "performance_ai.process_guard._rss_mb",
        lambda proc: 400.0,
    )
    return guard


def test_cpu_activity_protects_background_candidate(monkeypatch):
    guard = make_guard(monkeypatch)
    candidates = guard._background_candidates(
        1901.0,
        {2222: sample(cpu_percent=3.0)},
    )
    assert candidates == []


def test_disk_activity_protects_background_candidate(monkeypatch):
    guard = make_guard(monkeypatch)
    candidates = guard._background_candidates(
        1901.0,
        {2222: sample(io_kbps=2048.0)},
    )
    assert candidates == []


def test_recent_use_protects_background_candidate(monkeypatch):
    guard = make_guard(monkeypatch)
    candidates = guard._background_candidates(
        1901.0,
        {2222: sample(seconds_since_foreground=120.0)},
    )
    assert candidates == []


def test_idle_activity_allows_background_candidate(monkeypatch):
    guard = make_guard(monkeypatch)
    candidates = guard._background_candidates(
        1901.0,
        {2222: sample()},
    )
    assert len(candidates) == 1
    assert candidates[0].proc.name() == "Discord.exe"
    assert candidates[0].activity is not None

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    advisor_mode: bool = True
    foundry_enabled: bool = True
    foundry_model: str = "qwen2.5-0.5b"
    telemetry_interval_seconds: int = 5
    ai_interval_seconds: int = 180
    database_path: str = "data/performance_ai.db"

    # Existing CPU-priority allowlist.
    background_priority_allowlist: list[str] = field(default_factory=list)

    # Adaptive memory governor. All mutating actions remain gated by
    # advisor_mode and explicit process allowlists.
    memory_governor_enabled: bool = True
    memory_high_percent: float = 85.0
    memory_critical_percent: float = 92.0
    memory_recovery_percent: float = 78.0
    memory_priority_allowlist: list[str] = field(default_factory=list)
    memory_lower_cpu_priority: bool = True
    memory_max_managed_processes: int = 4

    # Predictive pressure framework. v0.2 uses a deterministic trend model;
    # the stored data is intended to train a future ONNX/NPU predictor.
    pressure_predictor_enabled: bool = True
    pressure_prediction_horizon_seconds: int = 120
    pressure_prediction_window_seconds: int = 300
    pressure_prediction_min_samples: int = 4
    pressure_prediction_warn_percent: float = 88.0
    pressure_predictive_actions_enabled: bool = True
    pressure_predictive_min_confidence: float = 0.65

    # Working-set trimming is intentionally opt-in. It can create extra page
    # faults if an application immediately needs those pages again.
    working_set_trim_enabled: bool = False
    working_set_trim_allowlist: list[str] = field(default_factory=list)
    working_set_trim_min_mb: float = 512.0
    working_set_trim_cooldown_seconds: int = 300

    # Process guards. Closing apps is always allowlist-only. Startup Guard is
    # for apps that silently launch at login; Background Guard is for apps the
    # user has not foregrounded for a configured idle period.
    startup_guard_enabled: bool = True
    startup_guard_window_seconds: int = 600
    startup_guard_grace_seconds: int = 45
    startup_close_allowlist: list[str] = field(default_factory=list)

    background_guard_enabled: bool = False
    background_close_allowlist: list[str] = field(default_factory=list)
    background_close_idle_seconds: int = 1800
    background_close_min_memory_mb: float = 100.0

    process_close_timeout_seconds: int = 6
    process_force_kill_enabled: bool = False

    low_battery_percent: int = 25
    very_low_battery_percent: int = 15
    top_process_count: int = 8

    @classmethod
    def load(cls, path: str | Path = "config.json") -> "AppConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in allowed}
        return cls(**filtered)

    def save(self, path: str | Path = "config.json") -> None:
        p = Path(path)
        p.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

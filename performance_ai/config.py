from __future__ import annotations

import json
from dataclasses import dataclass, field
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

    # Working-set trimming is intentionally opt-in. It can create extra page
    # faults if an application immediately needs those pages again.
    working_set_trim_enabled: bool = False
    working_set_trim_allowlist: list[str] = field(default_factory=list)
    working_set_trim_min_mb: float = 512.0
    working_set_trim_cooldown_seconds: int = 300

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

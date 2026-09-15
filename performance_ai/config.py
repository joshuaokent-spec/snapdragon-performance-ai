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
    background_priority_allowlist: list[str] = field(default_factory=list)
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

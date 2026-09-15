from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


WORKLOADS = {
    "IDLE",
    "LIGHT_WORK",
    "DEVELOPMENT",
    "DATA_WORK",
    "AI_INFERENCE",
    "HEAVY_COMPUTE",
    "BATTERY_LOW",
    "MULTITASKING",
}

PROFILES = {
    "EFFICIENCY",
    "BALANCED",
    "DEVELOPMENT",
    "DATA_SCIENCE",
    "LOCAL_AI",
    "PERFORMANCE",
    "BATTERY_SAVER",
}


@dataclass(slots=True)
class ProcessSample:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float


@dataclass(slots=True)
class TelemetrySnapshot:
    timestamp: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    battery_percent: float | None
    plugged_in: bool | None
    foreground_process: str | None
    power_scheme: str | None
    npu_percent: float | None
    top_processes: list[ProcessSample] = field(default_factory=list)

    @classmethod
    def now(cls, **kwargs: Any) -> "TelemetrySnapshot":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        return result


@dataclass(slots=True)
class Recommendation:
    workload: str
    profile: str
    confidence: float
    reason: str
    source: str = "rules"

    def normalized(self) -> "Recommendation":
        workload = self.workload.upper().strip()
        profile = self.profile.upper().strip()
        if workload not in WORKLOADS:
            raise ValueError(f"Unknown workload: {workload}")
        if profile not in PROFILES:
            raise ValueError(f"Unknown profile: {profile}")
        confidence = max(0.0, min(1.0, float(self.confidence)))
        return Recommendation(
            workload=workload,
            profile=profile,
            confidence=confidence,
            reason=self.reason.strip()[:500],
            source=self.source,
        )


@dataclass(slots=True)
class ActionResult:
    action: str
    requested: str
    applied: bool
    detail: str

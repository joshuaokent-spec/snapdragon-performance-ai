from __future__ import annotations

from .config import AppConfig
from .models import Recommendation, TelemetrySnapshot


class PolicyEngine:
    """Deterministic safety and consistency layer.

    The AI may refine the rule classifier, but low-confidence workload changes
    must be supported by telemetry. This prevents a small local model from
    turning weak evidence into an optimization action.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    @staticmethod
    def _supports_workload(snap: TelemetrySnapshot, workload: str) -> bool:
        workload = workload.upper().strip()
        foreground = (snap.foreground_process or "").lower()
        process_samples = snap.top_processes
        names = {p.name.lower() for p in process_samples}

        def any_named(prefixes: tuple[str, ...], min_cpu: float = 0.0) -> bool:
            for proc in process_samples:
                name = proc.name.lower()
                if any(name.startswith(prefix) for prefix in prefixes):
                    if proc.cpu_percent >= min_cpu:
                        return True
            return False

        if workload == "BATTERY_LOW":
            return (
                snap.battery_percent is not None
                and snap.plugged_in is False
                and snap.battery_percent <= self.config.low_battery_percent
            )

        if workload == "HEAVY_COMPUTE":
            return snap.cpu_percent >= 65.0

        if workload == "MULTITASKING":
            return snap.cpu_percent >= 35.0 or snap.memory_percent >= 75.0

        if workload == "IDLE":
            return snap.cpu_percent <= 15.0 and snap.memory_percent <= 60.0

        if workload == "AI_INFERENCE":
            return (
                (snap.npu_percent or 0.0) >= 5.0
                or any_named(("foundry", "onnxruntime", "ollama", "lmstudio"), 1.0)
            )

        if workload == "DEVELOPMENT":
            dev_prefixes = (
                "code", "devenv", "pycharm", "git", "node", "java", "wsl"
            )
            return (
                any(foreground.startswith(prefix) for prefix in dev_prefixes)
                or any_named(dev_prefixes, 0.5)
            )

        if workload == "DATA_WORK":
            data_prefixes = (
                "python", "jupyter", "sqlservr", "postgres", "duckdb"
            )
            return (
                any(foreground.startswith(prefix) for prefix in data_prefixes)
                or any_named(data_prefixes, 1.0)
            ) and (snap.cpu_percent >= 20.0 or snap.memory_percent >= 70.0)

        if workload == "LIGHT_WORK":
            return snap.cpu_percent < 35.0

        return False

    def validate(
        self,
        snap: TelemetrySnapshot,
        rec: Recommendation,
        baseline: Recommendation | None = None,
    ) -> Recommendation:
        rec = rec.normalized()
        baseline = baseline.normalized() if baseline is not None else None

        # Hard battery override regardless of model output.
        if (
            snap.battery_percent is not None
            and snap.plugged_in is False
            and snap.battery_percent <= self.config.very_low_battery_percent
        ):
            return Recommendation(
                workload="BATTERY_LOW",
                profile="BATTERY_SAVER",
                confidence=1.0,
                reason=(
                    f"Safety override: battery is {snap.battery_percent:.0f}% "
                    "and the laptop is unplugged."
                ),
                source="policy",
            )

        # Hybrid rule/AI fusion: an AI workload change needs either reasonable
        # confidence and telemetry evidence, or we keep the deterministic base.
        if (
            baseline is not None
            and rec.source.startswith("foundry-local")
            and rec.workload != baseline.workload
        ):
            supported = self._supports_workload(snap, rec.workload)
            if rec.confidence < 0.75 or not supported:
                return Recommendation(
                    workload=baseline.workload,
                    profile=baseline.profile,
                    confidence=baseline.confidence,
                    reason=(
                        f"Hybrid policy kept the rule baseline ({baseline.workload}) "
                        f"instead of AI suggestion {rec.workload}: "
                        "confidence/evidence threshold was not met."
                    ),
                    source="policy-fusion",
                )

        # Avoid performance-oriented profiles on low battery.
        if (
            snap.battery_percent is not None
            and snap.plugged_in is False
            and snap.battery_percent <= self.config.low_battery_percent
            and rec.profile in {"PERFORMANCE", "DATA_SCIENCE", "LOCAL_AI"}
        ):
            return Recommendation(
                workload=rec.workload,
                profile="BALANCED",
                confidence=rec.confidence,
                reason=(
                    f"Policy adjusted {rec.profile} to BALANCED because battery "
                    f"is {snap.battery_percent:.0f}% and unplugged."
                ),
                source="policy",
            )

        return rec

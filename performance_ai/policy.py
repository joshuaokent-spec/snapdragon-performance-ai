from __future__ import annotations

from .config import AppConfig
from .models import Recommendation, TelemetrySnapshot


class PolicyEngine:
    """Deterministic safety layer. Model output cannot bypass these rules."""

    def __init__(self, config: AppConfig):
        self.config = config

    def validate(
        self,
        snap: TelemetrySnapshot,
        rec: Recommendation,
    ) -> Recommendation:
        rec = rec.normalized()

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

        # Avoid performance mode on low battery.
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

from __future__ import annotations

import json
import re
from typing import Any

from .models import Recommendation, TelemetrySnapshot


DEV_PROCESSES = {
    "code.exe", "devenv.exe", "pycharm64.exe", "python.exe", "pythonw.exe",
    "git.exe", "node.exe", "java.exe", "wsl.exe", "wslhost.exe",
}
DATA_PROCESSES = {
    "python.exe", "pythonw.exe", "jupyter.exe", "jupyter-lab.exe",
    "sqlservr.exe", "postgres.exe", "duckdb.exe",
}
AI_PROCESSES = {
    "foundry.exe", "onnxruntime.exe", "ollama.exe", "lmstudio.exe",
}


class RuleClassifier:
    def classify(self, snap: TelemetrySnapshot) -> Recommendation:
        names = {p.name.lower() for p in snap.top_processes}
        fg = (snap.foreground_process or "").lower()
        cpu = snap.cpu_percent
        mem = snap.memory_percent

        if (
            snap.battery_percent is not None
            and snap.plugged_in is False
            and snap.battery_percent <= 25
        ):
            return Recommendation(
                "BATTERY_LOW", "BATTERY_SAVER", 0.99,
                f"Battery is {snap.battery_percent:.0f}% and the laptop is unplugged.",
                "rules",
            )

        if (snap.npu_percent or 0) >= 8 or names.intersection(AI_PROCESSES):
            return Recommendation(
                "AI_INFERENCE", "LOCAL_AI", 0.88,
                "NPU/local-AI activity is present.",
                "rules",
            )

        if fg in DATA_PROCESSES and (cpu >= 35 or mem >= 60):
            return Recommendation(
                "DATA_WORK", "DATA_SCIENCE", 0.82,
                "A data/Python process is foreground with meaningful compute or memory pressure.",
                "rules",
            )

        if fg in DEV_PROCESSES or names.intersection(DEV_PROCESSES):
            return Recommendation(
                "DEVELOPMENT", "DEVELOPMENT", 0.78,
                "Development tooling is active.",
                "rules",
            )

        if cpu >= 75:
            return Recommendation(
                "HEAVY_COMPUTE", "PERFORMANCE", 0.80,
                f"CPU utilization is sustained at {cpu:.0f}%.",
                "rules",
            )

        if cpu >= 35 or mem >= 75:
            return Recommendation(
                "MULTITASKING", "BALANCED", 0.72,
                "The system is under moderate CPU or memory pressure.",
                "rules",
            )

        if cpu <= 12 and mem <= 55:
            return Recommendation(
                "IDLE", "EFFICIENCY", 0.72,
                "System load is light.",
                "rules",
            )

        return Recommendation(
            "LIGHT_WORK", "BALANCED", 0.70,
            "Normal interactive workload detected.",
            "rules",
        )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        raise ValueError("Model did not return a JSON object.")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Model JSON was not an object.")
    return value


class FoundryClassifier:
    """Small Foundry Local model used only as a recommendation/classification layer."""

    def __init__(self, model_alias: str = "qwen2.5-0.5b"):
        self.model_alias = model_alias
        self.manager = None
        self.model = None
        self.client = None

    def start(self) -> None:
        if self.client is not None:
            return

        from foundry_local_sdk import Configuration, FoundryLocalManager

        FoundryLocalManager.initialize(
            Configuration(app_name="snapdragon-performance-ai")
        )
        self.manager = FoundryLocalManager.instance

        self.manager.download_and_register_eps()

        self.model = self.manager.catalog.get_model(self.model_alias)
        self.model.download()
        self.model.load()
        self.client = self.model.get_chat_client()

    def close(self) -> None:
        if self.model is not None:
            try:
                self.model.unload()
            except Exception:
                pass
        self.client = None
        self.model = None

    def classify(
        self,
        snap: TelemetrySnapshot,
        fallback: Recommendation,
    ) -> Recommendation:
        self.start()

        payload = snap.to_dict()
        system = """
You are a local Windows performance workload classifier running on a Copilot+ PC.

You do NOT execute commands and you do NOT recommend arbitrary commands.
Choose exactly one workload and exactly one profile from the allowed values.

Allowed workloads:
IDLE, LIGHT_WORK, DEVELOPMENT, DATA_WORK, AI_INFERENCE,
HEAVY_COMPUTE, BATTERY_LOW, MULTITASKING

Allowed profiles:
EFFICIENCY, BALANCED, DEVELOPMENT, DATA_SCIENCE,
LOCAL_AI, PERFORMANCE, BATTERY_SAVER

Important rules:
- If unplugged and battery is low, favor BATTERY_SAVER.
- Do not assume missing NPU telemetry means the NPU is unavailable.
- LOCAL_AI is appropriate when local model/NPU inference is occurring.
- DATA_SCIENCE is appropriate for sustained Python/data/ETL workloads.
- DEVELOPMENT is appropriate for coding/building with developer tools.
- PERFORMANCE should be reserved for heavy sustained compute, especially while plugged in.
- Return JSON only.

Schema:
{
  "workload": "ONE_ALLOWED_WORKLOAD",
  "profile": "ONE_ALLOWED_PROFILE",
  "confidence": 0.0,
  "reason": "one short sentence"
}
""".strip()

        user = {
            "telemetry": payload,
            "rule_baseline": {
                "workload": fallback.workload,
                "profile": fallback.profile,
                "confidence": fallback.confidence,
                "reason": fallback.reason,
            },
        }

        response = self.client.complete_chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ]
        )
        content = response.choices[0].message.content
        parsed = _extract_json(content)

        rec = Recommendation(
            workload=str(parsed["workload"]),
            profile=str(parsed["profile"]),
            confidence=float(parsed.get("confidence", 0.5)),
            reason=str(parsed.get("reason", "Foundry Local recommendation.")),
            source="foundry-local",
        )
        return rec.normalized()

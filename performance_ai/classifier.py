from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any

from .models import PressurePrediction, Recommendation, TelemetrySnapshot


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

CREATE_NO_WINDOW = 0x08000000


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
    cleaned = (text or "").strip()
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
        preview = cleaned[:240] if cleaned else "<empty response>"
        raise ValueError(f"Model did not return a JSON object. Output: {preview!r}")
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        preview = match.group(0)[:240]
        raise ValueError(f"Model returned invalid JSON. Output: {preview!r}") from exc
    if not isinstance(value, dict):
        raise ValueError("Model JSON was not an object.")
    return value


def _run_foundry(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    foundry = shutil.which("foundry")
    if not foundry:
        raise RuntimeError("Foundry Local CLI was not found on PATH.")

    result = subprocess.run(
        [foundry, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"Foundry command failed ({' '.join(args)}): {detail or result.returncode}"
        )
    return result


def _walk_for_local_url(value: Any) -> str | None:
    if isinstance(value, str):
        match = re.search(r"https?://(?:127\.0\.0\.1|localhost):\d+", value)
        return match.group(0) if match else None
    if isinstance(value, dict):
        for child in value.values():
            found = _walk_for_local_url(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _walk_for_local_url(child)
            if found:
                return found
    return None


def _foundry_base_url() -> str:
    try:
        result = _run_foundry(["server", "status", "--output", "json"], timeout=20)
        raw = (result.stdout or "").strip()
        if raw:
            parsed = json.loads(raw)
            url = _walk_for_local_url(parsed)
            if url:
                return url.rstrip("/")
    except (RuntimeError, json.JSONDecodeError):
        pass

    result = _run_foundry(["server", "status"], timeout=20)
    url = _walk_for_local_url(result.stdout or "")
    if not url:
        raise RuntimeError("Foundry server is running but its localhost URL was not found.")
    return url.rstrip("/")


def _http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Foundry HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Foundry Local server: {exc}") from exc


def _resolve_loaded_model_id(base_url: str, alias: str) -> str:
    try:
        payload = _http_json(f"{base_url}/v1/models")
        models = payload.get("data", []) if isinstance(payload, dict) else []
        ids = [str(item.get("id", "")) for item in models if isinstance(item, dict)]
        for model_id in ids:
            if model_id == alias:
                return model_id
        alias_norm = alias.lower().replace("_", "-")
        for model_id in ids:
            if alias_norm in model_id.lower().replace("_", "-"):
                return model_id
    except Exception:
        pass
    return alias


class FoundryClassifier:
    """Classify workloads through the local Foundry HTTP server."""

    def __init__(self, model_alias: str = "qwen2.5-0.5b"):
        self.model_alias = model_alias
        self.base_url: str | None = None
        self.model_id: str | None = None

    def start(self) -> None:
        if self.base_url and self.model_id:
            return
        _run_foundry(["model", "load", self.model_alias], timeout=180)
        self.base_url = _foundry_base_url()
        self.model_id = _resolve_loaded_model_id(self.base_url, self.model_alias)

    def close(self) -> None:
        return

    def classify(
        self,
        snap: TelemetrySnapshot,
        fallback: Recommendation,
        prediction: PressurePrediction | None = None,
    ) -> Recommendation:
        self.start()
        assert self.base_url is not None
        assert self.model_id is not None

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
- A pressure forecast is contextual evidence, not permission to close or modify a process.
- Return exactly one compact JSON object and no markdown or commentary.

Schema:
{
  "workload": "ONE_ALLOWED_WORKLOAD",
  "profile": "ONE_ALLOWED_PROFILE",
  "confidence": 0.0,
  "reason": "one short sentence"
}
""".strip()

        user: dict[str, Any] = {
            "telemetry": snap.to_dict(),
            "rule_baseline": {
                "workload": fallback.workload,
                "profile": fallback.profile,
                "confidence": fallback.confidence,
                "reason": fallback.reason,
            },
        }
        if prediction is not None:
            user["pressure_prediction"] = prediction.to_dict()

        response = _http_json(
            f"{self.base_url}/v1/chat/completions",
            method="POST",
            payload={
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
                ],
                "temperature": 0.0,
                "max_tokens": 160,
                "stream": False,
            },
        )

        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            preview = json.dumps(response, ensure_ascii=False)[:500]
            raise ValueError(f"Unexpected Foundry response: {preview}") from exc

        parsed = _extract_json(str(content))
        rec = Recommendation(
            workload=str(parsed["workload"]),
            profile=str(parsed["profile"]),
            confidence=float(parsed.get("confidence", 0.5)),
            reason=str(parsed.get("reason", "Foundry Local recommendation.")),
            source="foundry-local-http",
        )
        return rec.normalized()

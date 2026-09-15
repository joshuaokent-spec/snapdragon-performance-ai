from __future__ import annotations

import csv
import io
import re
import shutil
import subprocess
from functools import lru_cache


CREATE_NO_WINDOW = 0x08000000
_NPU_TOKEN_RE = re.compile(r"(?<![A-Za-z])NPU(?:\b|(?=\d))", re.IGNORECASE)


def _run(args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only diagnostic command without allowing console encoding to crash us.

    Foundry and Windows command-line tools can emit bytes that are not representable
    in the active Windows ANSI code page. Force a tolerant UTF-8 decode so diagnostic
    output may contain replacement characters rather than terminating the program.
    """
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _safe_output(result: subprocess.CompletedProcess[str] | None) -> str | None:
    if result is None:
        return None
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return stdout.strip() or stderr.strip() or f"exit {result.returncode}"


def _looks_like_npu_counter(counter: str) -> bool:
    """Return True only when NPU appears as a hardware token, not inside a word.

    For example, ``TextInputHost`` contains the letters ``npu`` across ``input``;
    that must not be mistaken for a Neural Processing Unit counter.
    """
    if not _NPU_TOKEN_RE.search(counter):
        return False

    lower = counter.lower()
    return any(
        marker in lower
        for marker in ("utilization", "% processor", "usage", "engine")
    )


@lru_cache(maxsize=1)
def discover_npu_counters() -> tuple[str, ...]:
    """Best-effort discovery of Windows NPU utilization performance counters.

    Counter names vary across Windows / driver versions, and some NPU data
    visible in Task Manager is not exposed as a conventional typeperf counter.
    Failure to find a counter therefore does not imply that the NPU is absent.
    """
    result = _run(["typeperf", "-qx"], timeout=15)
    if not result or result.returncode != 0:
        return ()

    candidates: list[str] = []
    for line in (result.stdout or "").splitlines():
        clean = line.strip()
        if _looks_like_npu_counter(clean):
            candidates.append(clean)

    candidates.sort(key=lambda s: (s.count("("), len(s)))
    return tuple(candidates[:12])


def read_npu_percent() -> float | None:
    counters = discover_npu_counters()
    if not counters:
        return None

    for counter in counters:
        result = _run(["typeperf", counter, "-sc", "1"], timeout=6)
        if not result or result.returncode != 0:
            continue

        rows = list(csv.reader(io.StringIO(result.stdout or "")))
        if len(rows) < 2:
            continue

        values: list[float] = []
        for value in rows[-1][1:]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number >= 0:
                values.append(number)

        if values:
            return round(min(100.0, sum(values)), 1)

    return None


def foundry_npu_diagnostics() -> dict[str, object]:
    """Return non-destructive diagnostics for NPU/Foundry availability."""
    foundry_path = shutil.which("foundry")
    diagnostics: dict[str, object] = {
        "typeperf_npu_counters": list(discover_npu_counters()),
        "foundry_cli": foundry_path,
        "foundry_server": None,
        "foundry_npu_models": None,
    }

    if not foundry_path:
        return diagnostics

    status = _run([foundry_path, "server", "status"], timeout=15)
    diagnostics["foundry_server"] = _safe_output(status)

    models = _run(
        [
            foundry_path,
            "model",
            "list",
            "--device",
            "npu",
            "--variants",
            "--limit",
            "10",
        ],
        timeout=60,
    )
    diagnostics["foundry_npu_models"] = _safe_output(models)

    return diagnostics

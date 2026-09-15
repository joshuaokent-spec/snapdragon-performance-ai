from __future__ import annotations

import csv
import io
import shutil
import subprocess
from functools import lru_cache


CREATE_NO_WINDOW = 0x08000000


def _run(args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


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
    for line in result.stdout.splitlines():
        clean = line.strip()
        lower = clean.lower()
        if "npu" in lower and (
            "utilization" in lower
            or "% processor" in lower
            or "usage" in lower
            or "engine" in lower
        ):
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

        rows = list(csv.reader(io.StringIO(result.stdout)))
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
    if status is not None:
        diagnostics["foundry_server"] = (
            status.stdout.strip() or status.stderr.strip() or f"exit {status.returncode}"
        )

    models = _run(
        [foundry_path, "model", "list", "--device", "npu", "--variants", "--limit", "10"],
        timeout=60,
    )
    if models is not None:
        diagnostics["foundry_npu_models"] = (
            models.stdout.strip() or models.stderr.strip() or f"exit {models.returncode}"
        )

    return diagnostics

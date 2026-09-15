from __future__ import annotations

import csv
import io
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

    Counter names vary across Windows / driver versions, so failure is normal.
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
        ):
            candidates.append(clean)

    candidates.sort(key=lambda s: (s.count("("), len(s)))
    return tuple(candidates[:8])


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

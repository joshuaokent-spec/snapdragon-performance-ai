from __future__ import annotations

import ctypes
import os
import re
import subprocess

import psutil

from .models import ProcessSample, TelemetrySnapshot
from .npu import read_npu_percent


CREATE_NO_WINDOW = 0x08000000


def _foreground_process_name() -> str | None:
    if not hasattr(ctypes, "windll"):
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        return psutil.Process(pid.value).name()
    except (OSError, psutil.Error, AttributeError):
        return None


def _active_power_scheme() -> str | None:
    try:
        result = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    match = re.search(r"\(([^)]+)\)", result.stdout)
    return match.group(1).strip() if match else result.stdout.strip() or None


def _top_processes(limit: int) -> list[ProcessSample]:
    """Return Task-Manager-like process CPU plus resident-memory usage.

    psutil intentionally allows Process.cpu_percent() to exceed 100% when a
    process uses multiple logical CPUs. Normalize by logical CPU count for a
    human-facing dashboard. The optimizer itself is excluded from workload
    telemetry so it does not classify its own Python process as user activity.
    """
    logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)
    ignored_names = {"system idle process", "idle"}
    current_pid = os.getpid()

    processes: list[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").strip().lower()
            if proc.pid in {0, current_pid} or name in ignored_names:
                continue
            proc.cpu_percent(None)
            processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    psutil.cpu_percent(interval=0.25)

    samples: list[ProcessSample] = []
    for proc in processes:
        try:
            raw_cpu = float(proc.cpu_percent(None))
            cpu = min(100.0, raw_cpu / logical_cpus)
            mem = float(proc.memory_percent())
            rss_mb = float(proc.memory_info().rss) / (1024 * 1024)
            if cpu <= 0 and mem <= 0:
                continue
            samples.append(
                ProcessSample(
                    pid=proc.pid,
                    name=proc.name(),
                    cpu_percent=round(cpu, 1),
                    memory_percent=round(mem, 2),
                    rss_mb=round(rss_mb, 1),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Keep compute-heavy processes visible while still surfacing large working
    # sets. The second key makes high-RAM apps bubble up when CPU use is similar.
    samples.sort(key=lambda p: (p.cpu_percent, p.rss_mb), reverse=True)
    return samples[:limit]


class TelemetryCollector:
    def __init__(self, top_process_count: int = 8):
        self.top_process_count = max(1, top_process_count)

    def collect(self) -> TelemetrySnapshot:
        cpu = psutil.cpu_percent(interval=0.4)
        memory = psutil.virtual_memory().percent
        disk = psutil.disk_usage("C:\\").percent

        battery = psutil.sensors_battery()
        battery_percent = None if battery is None else round(float(battery.percent), 1)
        plugged_in = None if battery is None else bool(battery.power_plugged)

        return TelemetrySnapshot.now(
            cpu_percent=round(float(cpu), 1),
            memory_percent=round(float(memory), 1),
            disk_percent=round(float(disk), 1),
            battery_percent=battery_percent,
            plugged_in=plugged_in,
            foreground_process=_foreground_process_name(),
            power_scheme=_active_power_scheme(),
            npu_percent=read_npu_percent(),
            top_processes=_top_processes(self.top_process_count),
        )

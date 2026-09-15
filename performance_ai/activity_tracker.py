from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass

import psutil


@dataclass(slots=True)
class ProcessActivity:
    pid: int
    name: str
    rss_mb: float
    cpu_percent: float
    io_kbps: float
    observation_seconds: float
    seconds_since_foreground: float | None
    has_baseline: bool
    foreground: bool

    def protection_reason(
        self,
        *,
        cpu_threshold: float,
        io_threshold_kbps: float,
        recent_foreground_seconds: float,
        min_observation_seconds: float,
    ) -> str | None:
        if self.foreground:
            return "foreground"
        if not self.has_baseline or self.observation_seconds < min_observation_seconds:
            return "warming_up"
        if (
            self.seconds_since_foreground is not None
            and self.seconds_since_foreground < recent_foreground_seconds
        ):
            return "recently_used"
        if self.cpu_percent >= cpu_threshold:
            return "cpu_active"
        if self.io_kbps >= io_threshold_kbps:
            return "io_active"
        return None


@dataclass(slots=True)
class _SampleState:
    create_time: float
    first_seen: float
    last_seen: float
    cpu_seconds: float
    io_bytes: int
    last_foreground: float | None


def foreground_pid() -> int | None:
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None
    except OSError:
        return None


def _total_io_bytes(proc: psutil.Process) -> int:
    try:
        io = proc.io_counters()
        return int(io.read_bytes) + int(io.write_bytes)
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, AttributeError):
        return 0


def _total_cpu_seconds(proc: psutil.Process) -> float:
    times = proc.cpu_times()
    return float(times.user) + float(times.system)


class ActivityTracker:
    """Track short-term per-process CPU / disk-I/O activity safely.

    The tracker intentionally does not interpret an open network connection as
    proof of active work. Apps such as Steam and Discord can maintain idle
    connections for hours. CPU and disk-I/O deltas are stronger evidence that a
    hidden app is actually doing something useful, such as installing,
    downloading, indexing, or updating.
    """

    def __init__(self) -> None:
        self._states: dict[int, _SampleState] = {}
        self._logical_cpus = max(1, psutil.cpu_count(logical=True) or 1)

    def sample(self, executable_names: set[str]) -> dict[int, ProcessActivity]:
        wanted = {name.lower() for name in executable_names if name}
        if not wanted:
            return {}

        now = time.monotonic()
        fg_pid = foreground_pid()
        current_pid = os.getpid()
        output: dict[int, ProcessActivity] = {}
        seen: set[int] = set()

        for proc in psutil.process_iter(["pid", "name", "memory_info", "create_time"]):
            try:
                pid = int(proc.info["pid"])
                name = (proc.info.get("name") or "").strip()
                if pid in {0, current_pid} or name.lower() not in wanted:
                    continue

                create_time = float(proc.info.get("create_time") or proc.create_time())
                mem = proc.info.get("memory_info")
                rss_mb = float(mem.rss) / (1024 * 1024) if mem else 0.0
                cpu_seconds = _total_cpu_seconds(proc)
                io_bytes = _total_io_bytes(proc)
                is_foreground = pid == fg_pid

                prior = self._states.get(pid)
                if prior is not None and abs(prior.create_time - create_time) > 0.001:
                    # PID reuse: never mix activity from an old process with a new one.
                    prior = None

                if prior is None:
                    state = _SampleState(
                        create_time=create_time,
                        first_seen=now,
                        last_seen=now,
                        cpu_seconds=cpu_seconds,
                        io_bytes=io_bytes,
                        last_foreground=now if is_foreground else None,
                    )
                    self._states[pid] = state
                    cpu_percent = 0.0
                    io_kbps = 0.0
                    has_baseline = False
                else:
                    elapsed = max(0.001, now - prior.last_seen)
                    cpu_delta = max(0.0, cpu_seconds - prior.cpu_seconds)
                    io_delta = max(0, io_bytes - prior.io_bytes)
                    cpu_percent = min(
                        100.0,
                        100.0 * cpu_delta / elapsed / self._logical_cpus,
                    )
                    io_kbps = io_delta / elapsed / 1024.0
                    has_baseline = True
                    state = prior
                    state.last_seen = now
                    state.cpu_seconds = cpu_seconds
                    state.io_bytes = io_bytes
                    if is_foreground:
                        state.last_foreground = now

                seconds_since_foreground = (
                    None
                    if state.last_foreground is None
                    else max(0.0, now - state.last_foreground)
                )
                output[pid] = ProcessActivity(
                    pid=pid,
                    name=name,
                    rss_mb=round(rss_mb, 1),
                    cpu_percent=round(cpu_percent, 2),
                    io_kbps=round(io_kbps, 1),
                    observation_seconds=max(0.0, now - state.first_seen),
                    seconds_since_foreground=seconds_since_foreground,
                    has_baseline=has_baseline,
                    foreground=is_foreground,
                )
                seen.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
                continue

        # Keep state bounded; dead / no-longer-watched processes are discarded.
        for pid in list(self._states):
            if pid not in seen:
                self._states.pop(pid, None)

        return output

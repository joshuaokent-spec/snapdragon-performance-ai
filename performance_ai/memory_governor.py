from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass

import psutil

from .config import AppConfig
from .models import ActionResult, TelemetrySnapshot


# Windows access rights / API constants.
PROCESS_SET_INFORMATION = 0x0200
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_MEMORY_PRIORITY = 0

MEMORY_PRIORITY_VERY_LOW = 1
MEMORY_PRIORITY_LOW = 2
MEMORY_PRIORITY_MEDIUM = 3
MEMORY_PRIORITY_BELOW_NORMAL = 4
MEMORY_PRIORITY_NORMAL = 5

# Processes that should never be manipulated by this project even if a user
# accidentally puts one in an allowlist.
PROTECTED_PROCESS_NAMES = {
    "system",
    "registry",
    "memory compression",
    "secure system",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "fontdrvhost.exe",
    "dwm.exe",
    "explorer.exe",
    "foundry.exe",
}


class MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("MemoryPriority", ctypes.c_ulong)]


@dataclass(slots=True)
class ManagedProcessState:
    pid: int
    name: str
    original_cpu_priority: int | None
    original_memory_priority: int | None


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _psapi():
    return ctypes.WinDLL("psapi", use_last_error=True)


def _open_process(pid: int, access: int):
    kernel32 = _kernel32()
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    return kernel32.OpenProcess(access, False, pid)


def _close_handle(handle) -> None:
    if not handle:
        return
    kernel32 = _kernel32()
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle(handle)


def _get_memory_priority(pid: int) -> int | None:
    if os.name != "nt":
        return None

    handle = _open_process(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return None

    try:
        kernel32 = _kernel32()
        kernel32.GetProcessInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        kernel32.GetProcessInformation.restype = ctypes.c_int

        info = MEMORY_PRIORITY_INFORMATION()
        ok = kernel32.GetProcessInformation(
            handle,
            PROCESS_MEMORY_PRIORITY,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        return int(info.MemoryPriority) if ok else None
    finally:
        _close_handle(handle)


def _set_memory_priority(pid: int, priority: int) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Memory priority control is Windows-only."

    priority = max(MEMORY_PRIORITY_VERY_LOW, min(MEMORY_PRIORITY_NORMAL, priority))
    handle = _open_process(
        pid,
        PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
    )
    if not handle:
        return False, f"OpenProcess failed with Windows error {ctypes.get_last_error()}."

    try:
        kernel32 = _kernel32()
        kernel32.SetProcessInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        kernel32.SetProcessInformation.restype = ctypes.c_int

        info = MEMORY_PRIORITY_INFORMATION(priority)
        ok = kernel32.SetProcessInformation(
            handle,
            PROCESS_MEMORY_PRIORITY,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if ok:
            return True, f"Memory priority set to {priority}."
        return False, f"SetProcessInformation failed with Windows error {ctypes.get_last_error()}."
    finally:
        _close_handle(handle)


def _trim_working_set(pid: int) -> tuple[bool, str]:
    """Best-effort emergency working-set trim for an explicitly approved app."""
    if os.name != "nt":
        return False, "Working-set trimming is Windows-only."

    handle = _open_process(
        pid,
        PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
    )
    if not handle:
        return False, f"OpenProcess failed with Windows error {ctypes.get_last_error()}."

    try:
        psapi = _psapi()
        psapi.EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        psapi.EmptyWorkingSet.restype = ctypes.c_int
        ok = psapi.EmptyWorkingSet(handle)
        if ok:
            return True, "Working set trimmed. Pages may fault back in if the app needs them again."
        return False, f"EmptyWorkingSet failed with Windows error {ctypes.get_last_error()}."
    finally:
        _close_handle(handle)


def _foreground_pid() -> int | None:
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


class MemoryGovernor:
    """Adaptive, allowlisted memory-pressure controller.

    The governor does not attempt to 'allocate RAM' to applications. Instead it
    gives Windows memory-priority hints, optionally lowers CPU priority for
    background apps, and can perform an emergency working-set trim only for an
    explicit trim allowlist.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._managed: dict[int, ManagedProcessState] = {}
        self._last_trim: dict[int, float] = {}

    def _candidate_processes(self) -> list[tuple[psutil.Process, float]]:
        allow = {
            name.lower()
            for name in (
                list(self.config.memory_priority_allowlist)
                + list(self.config.background_priority_allowlist)
            )
        }
        if not allow:
            return []

        fg_pid = _foreground_pid()
        current_pid = os.getpid()
        candidates: list[tuple[psutil.Process, float]] = []

        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                pid = int(proc.info["pid"])
                name = (proc.info.get("name") or "").lower()
                if (
                    pid in {0, current_pid, fg_pid}
                    or name in PROTECTED_PROCESS_NAMES
                    or name not in allow
                ):
                    continue

                rss = proc.info.get("memory_info")
                rss_mb = float(rss.rss) / (1024 * 1024) if rss else 0.0
                candidates.append((proc, rss_mb))
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue

        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates

    def _remember_original_state(self, proc: psutil.Process) -> None:
        if proc.pid in self._managed:
            return
        try:
            cpu_priority = int(proc.nice())
        except (psutil.Error, OSError, TypeError, ValueError):
            cpu_priority = None

        self._managed[proc.pid] = ManagedProcessState(
            pid=proc.pid,
            name=proc.name(),
            original_cpu_priority=cpu_priority,
            original_memory_priority=_get_memory_priority(proc.pid),
        )

    def _restore_managed(self) -> list[ActionResult]:
        results: list[ActionResult] = []
        for pid, state in list(self._managed.items()):
            try:
                proc = psutil.Process(pid)
                if proc.name().lower() != state.name.lower():
                    self._managed.pop(pid, None)
                    continue

                if state.original_memory_priority is not None:
                    ok, detail = _set_memory_priority(pid, state.original_memory_priority)
                    results.append(
                        ActionResult(
                            action="restore_memory_priority",
                            requested=state.name,
                            applied=ok,
                            detail=f"PID {pid}: {detail}",
                        )
                    )

                if state.original_cpu_priority is not None:
                    try:
                        proc.nice(state.original_cpu_priority)
                        results.append(
                            ActionResult(
                                action="restore_cpu_priority",
                                requested=state.name,
                                applied=True,
                                detail=f"PID {pid}: restored original CPU priority.",
                            )
                        )
                    except (psutil.Error, OSError) as exc:
                        results.append(
                            ActionResult(
                                action="restore_cpu_priority",
                                requested=state.name,
                                applied=False,
                                detail=f"PID {pid}: {exc}",
                            )
                        )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            finally:
                self._managed.pop(pid, None)
                self._last_trim.pop(pid, None)
        return results

    def evaluate(self, snap: TelemetrySnapshot) -> list[ActionResult]:
        if not self.config.memory_governor_enabled:
            return []

        memory = float(snap.memory_percent)
        candidates = self._candidate_processes()

        if memory <= self.config.memory_recovery_percent:
            if self.config.advisor_mode:
                return []
            return self._restore_managed()

        if memory < self.config.memory_high_percent:
            return []

        level = (
            "critical"
            if memory >= self.config.memory_critical_percent
            else "high"
        )
        target_priority = (
            MEMORY_PRIORITY_LOW if level == "critical" else MEMORY_PRIORITY_BELOW_NORMAL
        )

        if self.config.advisor_mode:
            if not candidates:
                return [
                    ActionResult(
                        action="memory_governor",
                        requested=level,
                        applied=False,
                        detail=(
                            f"Memory pressure is {memory:.1f}% ({level}), but no approved "
                            "background processes are in memory_priority_allowlist."
                        ),
                    )
                ]

            preview = ", ".join(
                f"{proc.name()} ({rss_mb:.0f} MB)"
                for proc, rss_mb in candidates[:3]
            )
            return [
                ActionResult(
                    action="memory_governor",
                    requested=level,
                    applied=False,
                    detail=(
                        f"Memory pressure is {memory:.1f}% ({level}). Would reprioritize: "
                        f"{preview}. Advisor Mode prevents changes."
                    ),
                )
            ]

        results: list[ActionResult] = []
        trim_allow = {name.lower() for name in self.config.working_set_trim_allowlist}
        now = time.monotonic()

        for proc, rss_mb in candidates[: self.config.memory_max_managed_processes]:
            try:
                self._remember_original_state(proc)
                ok, detail = _set_memory_priority(proc.pid, target_priority)
                results.append(
                    ActionResult(
                        action="set_memory_priority",
                        requested=proc.name(),
                        applied=ok,
                        detail=(
                            f"PID {proc.pid}, {rss_mb:.0f} MB RSS, pressure {memory:.1f}%: {detail}"
                        ),
                    )
                )

                if self.config.memory_lower_cpu_priority:
                    priority = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", None)
                    if priority is not None:
                        try:
                            proc.nice(priority)
                            results.append(
                                ActionResult(
                                    action="lower_cpu_priority",
                                    requested=proc.name(),
                                    applied=True,
                                    detail=f"PID {proc.pid}: set BELOW_NORMAL CPU priority.",
                                )
                            )
                        except (psutil.Error, OSError) as exc:
                            results.append(
                                ActionResult(
                                    action="lower_cpu_priority",
                                    requested=proc.name(),
                                    applied=False,
                                    detail=f"PID {proc.pid}: {exc}",
                                )
                            )

                can_trim = (
                    level == "critical"
                    and self.config.working_set_trim_enabled
                    and proc.name().lower() in trim_allow
                    and rss_mb >= self.config.working_set_trim_min_mb
                    and now - self._last_trim.get(proc.pid, 0.0)
                    >= self.config.working_set_trim_cooldown_seconds
                )
                if can_trim:
                    ok, detail = _trim_working_set(proc.pid)
                    if ok:
                        self._last_trim[proc.pid] = now
                    results.append(
                        ActionResult(
                            action="trim_working_set",
                            requested=proc.name(),
                            applied=ok,
                            detail=f"PID {proc.pid}, {rss_mb:.0f} MB RSS: {detail}",
                        )
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
                results.append(
                    ActionResult(
                        action="memory_governor",
                        requested="process",
                        applied=False,
                        detail=str(exc),
                    )
                )

        return results

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass

import psutil

from .config import AppConfig
from .models import ActionResult, TelemetrySnapshot


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
    "taskmgr.exe",
    "foundry.exe",
    "python.exe",
    "python3.exe",
    "python3.13.exe",
    "pythonw.exe",
}


@dataclass(slots=True)
class GuardCandidate:
    proc: psutil.Process
    reason: str
    rss_mb: float


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


def _rss_mb(proc: psutil.Process) -> float:
    try:
        return float(proc.memory_info().rss) / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return 0.0


class ProcessGuard:
    """Allowlist-only startup and background application closer.

    Startup Guard closes explicitly approved applications that silently launch
    shortly after Windows boots. Background Guard can close explicitly approved
    applications only after they have remained outside the foreground for a
    configured idle period.

    Advisor Mode never terminates anything; it only reports what would happen.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._first_seen: dict[int, float] = {}
        self._last_foreground: dict[int, float] = {}
        self._already_handled_startup: set[int] = set()

    def _update_presence(self, now: float, foreground_pid: int | None) -> None:
        active_pids: set[int] = set()
        for proc in psutil.process_iter(["pid"]):
            try:
                pid = int(proc.info["pid"])
                active_pids.add(pid)
                self._first_seen.setdefault(pid, now)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, TypeError):
                continue

        if foreground_pid is not None:
            self._last_foreground[foreground_pid] = now

        for mapping in (self._first_seen, self._last_foreground):
            for pid in list(mapping):
                if pid not in active_pids:
                    mapping.pop(pid, None)
        self._already_handled_startup.intersection_update(active_pids)

    def _safe_processes(self) -> list[psutil.Process]:
        foreground_pid = _foreground_pid()
        current_pid = os.getpid()
        result: list[psutil.Process] = []

        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid = int(proc.info["pid"])
                name = (proc.info.get("name") or "").strip().lower()
                if (
                    pid in {0, current_pid, foreground_pid}
                    or name in PROTECTED_PROCESS_NAMES
                ):
                    continue
                result.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, TypeError):
                continue
        return result

    def _startup_candidates(self, now: float) -> list[GuardCandidate]:
        if not self.config.startup_guard_enabled:
            return []

        uptime = max(0.0, time.time() - psutil.boot_time())
        if uptime < self.config.startup_guard_grace_seconds:
            return []
        if uptime > self.config.startup_guard_window_seconds:
            return []

        allow = {name.lower() for name in self.config.startup_close_allowlist}
        if not allow:
            return []

        candidates: list[GuardCandidate] = []
        for proc in self._safe_processes():
            try:
                name = proc.name().lower()
                if name not in allow or proc.pid in self._already_handled_startup:
                    continue
                candidates.append(
                    GuardCandidate(
                        proc=proc,
                        reason=f"startup guard during first {self.config.startup_guard_window_seconds}s after boot",
                        rss_mb=_rss_mb(proc),
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return candidates

    def _background_candidates(self, now: float) -> list[GuardCandidate]:
        if not self.config.background_guard_enabled:
            return []

        allow = {name.lower() for name in self.config.background_close_allowlist}
        if not allow:
            return []

        idle_required = max(60, self.config.background_close_idle_seconds)
        candidates: list[GuardCandidate] = []
        for proc in self._safe_processes():
            try:
                name = proc.name().lower()
                if name not in allow:
                    continue

                rss_mb = _rss_mb(proc)
                if rss_mb < self.config.background_close_min_memory_mb:
                    continue

                first_seen = self._first_seen.get(proc.pid, now)
                last_foreground = self._last_foreground.get(proc.pid, first_seen)
                idle_seconds = now - max(first_seen, last_foreground)
                if idle_seconds < idle_required:
                    continue

                candidates.append(
                    GuardCandidate(
                        proc=proc,
                        reason=f"background for {idle_seconds / 60:.0f} min",
                        rss_mb=rss_mb,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return candidates

    def _process_tree(self, root: psutil.Process) -> list[psutil.Process]:
        procs = [root]
        if not self.config.process_close_children:
            return procs
        try:
            for child in root.children(recursive=True):
                try:
                    name = child.name().lower()
                    if name not in PROTECTED_PROCESS_NAMES and child.pid != os.getpid():
                        procs.append(child)
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
        return procs

    def _close_candidate(self, candidate: GuardCandidate) -> list[ActionResult]:
        proc = candidate.proc
        try:
            root_name = proc.name()
            tree = self._process_tree(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
            return [
                ActionResult("close_process", "unknown", False, str(exc))
            ]

        if self.config.advisor_mode:
            return [
                ActionResult(
                    action="process_guard",
                    requested=root_name,
                    applied=False,
                    detail=(
                        f"Would close {root_name} (PID {proc.pid}, {candidate.rss_mb:.0f} MB) "
                        f"and {max(0, len(tree)-1)} child process(es): {candidate.reason}. "
                        "Advisor Mode prevents changes."
                    ),
                )
            ]

        # Terminate children first, then the root. terminate() is graceful on
        # Windows compared with an unconditional kill.
        targets = list(reversed(tree))
        signaled: list[psutil.Process] = []
        results: list[ActionResult] = []
        for target in targets:
            try:
                target.terminate()
                signaled.append(target)
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError) as exc:
                results.append(
                    ActionResult(
                        action="close_process",
                        requested=root_name,
                        applied=False,
                        detail=f"PID {target.pid}: {exc}",
                    )
                )

        if signaled:
            gone, alive = psutil.wait_procs(
                signaled,
                timeout=max(1, self.config.process_close_timeout_seconds),
            )
            results.append(
                ActionResult(
                    action="close_process",
                    requested=root_name,
                    applied=bool(gone),
                    detail=(
                        f"Requested graceful close for {root_name}: {len(gone)} process(es) exited; "
                        f"{len(alive)} remain. Reason: {candidate.reason}."
                    ),
                )
            )

            if alive and self.config.process_force_kill_enabled:
                killed = 0
                for target in alive:
                    try:
                        target.kill()
                        killed += 1
                    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                        continue
                results.append(
                    ActionResult(
                        action="force_kill_process",
                        requested=root_name,
                        applied=killed > 0,
                        detail=f"Force-killed {killed} remaining process(es).",
                    )
                )

        return results

    def evaluate(self, snap: TelemetrySnapshot) -> list[ActionResult]:
        now = time.monotonic()
        foreground_pid = _foreground_pid()
        self._update_presence(now, foreground_pid)

        by_pid: dict[int, GuardCandidate] = {}
        for candidate in self._startup_candidates(now):
            by_pid[candidate.proc.pid] = candidate
        for candidate in self._background_candidates(now):
            by_pid.setdefault(candidate.proc.pid, candidate)

        results: list[ActionResult] = []
        for pid, candidate in by_pid.items():
            results.extend(self._close_candidate(candidate))
            if "startup guard" in candidate.reason:
                self._already_handled_startup.add(pid)
        return results

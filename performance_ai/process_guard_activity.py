from __future__ import annotations

import ctypes
import os
import time

import psutil

from .activity_tracker import ActivityTracker, ProcessActivity, foreground_pid
from .config import AppConfig
from .models import ActionResult, TelemetrySnapshot


WM_CLOSE = 0x0010

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


def _post_wm_close(pid: int) -> int:
    """Ask top-level windows owned by PID to close. Returns windows signaled."""
    if os.name != "nt":
        return 0
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:
        return 0

    count = 0
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @WNDENUMPROC
    def callback(hwnd, _lparam):
        nonlocal count
        owner_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if int(owner_pid.value) == pid:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            count += 1
        return True

    try:
        user32.EnumWindows(callback, 0)
    except OSError:
        return count
    return count


def _rss_mb(proc: psutil.Process) -> float:
    try:
        return float(proc.memory_info().rss) / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return 0.0


class ProcessGuard:
    """Allowlist-only startup/background process closer.

    Startup Guard follows the user's explicit close-on-login preference.
    Background Guard is more conservative: an app must be allowlisted, hidden,
    sufficiently old/unused, large enough to matter, and show no meaningful CPU
    or disk-I/O activity before it becomes eligible.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._started = time.monotonic()
        self._activity = ActivityTracker()
        self._already_requested: set[tuple[int, str]] = set()

    def _is_protected(self, proc: psutil.Process, fg_pid: int | None) -> bool:
        try:
            name = proc.name().lower()
            return (
                proc.pid in {0, os.getpid(), fg_pid}
                or name in PROTECTED_PROCESS_NAMES
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return True

    def _request_close(self, proc: psutil.Process, reason: str) -> ActionResult:
        try:
            name = proc.name()
            pid = proc.pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return ActionResult("close_process", "unknown", False, "Process disappeared.")

        if self.config.advisor_mode:
            return ActionResult(
                action="close_process",
                requested=name,
                applied=False,
                detail=f"Advisor Mode: would close PID {pid} ({reason}).",
            )

        targets: list[psutil.Process] = []
        if getattr(self.config, "process_close_children", True):
            try:
                targets.extend(proc.children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        targets.append(proc)

        # First ask application windows to close normally. Do not immediately
        # TerminateProcess merely because an app is hidden in the tray.
        windows = 0
        for target in targets:
            windows += _post_wm_close(target.pid)

        timeout = max(1, int(getattr(self.config, "process_close_timeout_seconds", 6)))
        _, alive = psutil.wait_procs(targets, timeout=timeout)
        if not alive:
            return ActionResult(
                action="close_process",
                requested=name,
                applied=True,
                detail=f"Closed PID {pid} ({reason}); signaled {windows} window(s).",
            )

        if not getattr(self.config, "process_force_kill_enabled", False):
            return ActionResult(
                action="close_process",
                requested=name,
                applied=False,
                detail=(
                    f"PID {pid} stayed open after {timeout}s. Force-kill is disabled; "
                    "left the application running."
                ),
            )

        killed = 0
        for target in alive:
            try:
                target.kill()
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return ActionResult(
            action="close_process",
            requested=name,
            applied=killed > 0,
            detail=f"Force-killed {killed} process(es) after graceful close timed out.",
        )

    def _iter_named(self, names: set[str]) -> list[psutil.Process]:
        wanted = {name.lower() for name in names if name}
        if not wanted:
            return []
        found: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in wanted:
                    found.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return found

    def _startup_actions(self, fg_pid: int | None) -> list[ActionResult]:
        if not getattr(self.config, "startup_guard_enabled", True):
            return []
        allow = {name.lower() for name in getattr(self.config, "startup_close_allowlist", [])}
        if not allow:
            return []

        elapsed = time.monotonic() - self._started
        grace = max(0, int(getattr(self.config, "startup_guard_grace_seconds", 45)))
        window = max(grace, int(getattr(self.config, "startup_guard_window_seconds", 600)))
        if elapsed < grace or elapsed > window:
            return []

        results: list[ActionResult] = []
        for proc in self._iter_named(allow):
            if self._is_protected(proc, fg_pid):
                continue
            try:
                key = (proc.pid, "startup")
                if key in self._already_requested and self.config.advisor_mode:
                    continue
                self._already_requested.add(key)
                results.append(self._request_close(proc, "startup guard allowlist"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return results

    def _background_actions(
        self,
        fg_pid: int | None,
        activities: dict[int, ProcessActivity],
    ) -> list[ActionResult]:
        if not getattr(self.config, "background_guard_enabled", False):
            return []

        allow = {
            name.lower()
            for name in getattr(self.config, "background_close_allowlist", [])
        }
        if not allow:
            return []

        idle_required = max(
            0,
            int(getattr(self.config, "background_close_idle_seconds", 1800)),
        )
        min_memory = max(
            0.0,
            float(getattr(self.config, "background_close_min_memory_mb", 100.0)),
        )
        cpu_threshold = max(
            0.0,
            float(getattr(self.config, "background_activity_cpu_percent", 1.0)),
        )
        io_threshold = max(
            0.0,
            float(getattr(self.config, "background_activity_io_kbps", 256.0)),
        )
        recent_fg = max(
            0,
            int(getattr(self.config, "background_recent_foreground_seconds", 900)),
        )
        min_observation = max(
            0,
            int(getattr(self.config, "background_activity_min_observation_seconds", 60)),
        )

        results: list[ActionResult] = []
        for proc in self._iter_named(allow):
            if self._is_protected(proc, fg_pid):
                continue
            activity = activities.get(proc.pid)
            if activity is None:
                continue

            if getattr(self.config, "background_activity_protection_enabled", True):
                protect = activity.protection_reason(
                    cpu_threshold=cpu_threshold,
                    io_threshold_kbps=io_threshold,
                    recent_foreground_seconds=recent_fg,
                    min_observation_seconds=min_observation,
                )
                if protect is not None:
                    continue

            idle_seconds = (
                activity.observation_seconds
                if activity.seconds_since_foreground is None
                else activity.seconds_since_foreground
            )
            if idle_seconds < idle_required or activity.rss_mb < min_memory:
                continue

            key = (proc.pid, "background")
            if key in self._already_requested and self.config.advisor_mode:
                continue
            self._already_requested.add(key)
            results.append(
                self._request_close(
                    proc,
                    (
                        f"background idle {idle_seconds / 60:.0f} min, "
                        f"{activity.rss_mb:.0f} MB RSS, "
                        f"CPU {activity.cpu_percent:.2f}%, "
                        f"I/O {activity.io_kbps:.0f} KB/s"
                    ),
                )
            )
        return results

    def evaluate(
        self,
        snap: TelemetrySnapshot | None = None,
        *_args,
        **_kwargs,
    ) -> list[ActionResult]:
        del snap  # foreground PID is resolved directly to avoid name ambiguity.
        fg_pid = foreground_pid()
        startup_names = set(getattr(self.config, "startup_close_allowlist", []))
        background_names = set(getattr(self.config, "background_close_allowlist", []))
        activities = self._activity.sample(startup_names | background_names)

        results = self._startup_actions(fg_pid)
        results.extend(self._background_actions(fg_pid, activities))
        return results

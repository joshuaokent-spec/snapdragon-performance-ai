from __future__ import annotations

import re
import subprocess

import psutil

from .config import AppConfig
from .models import ActionResult, Recommendation
from .profiles import PROFILE_POWER_SCHEME_PREFERENCE


CREATE_NO_WINDOW = 0x08000000


def _run_powercfg(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["powercfg", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def installed_power_schemes() -> dict[str, str]:
    """Return {scheme_name_lower: guid} for schemes already installed."""
    result = _run_powercfg(["/list"])
    if not result or result.returncode != 0:
        return {}

    schemes: dict[str, str] = {}
    pattern = re.compile(
        r"([0-9a-fA-F-]{36})\s+\(([^)]+)\)"
    )
    for guid, name in pattern.findall(result.stdout):
        schemes[name.strip().lower()] = guid
    return schemes


class Optimizer:
    def __init__(self, config: AppConfig):
        self.config = config

    def _choose_scheme(self, profile: str) -> tuple[str, str] | None:
        schemes = installed_power_schemes()
        preferences = PROFILE_POWER_SCHEME_PREFERENCE.get(profile, ())
        for keyword in preferences:
            for name, guid in schemes.items():
                if keyword in name:
                    return name, guid
        return None

    def _apply_power_scheme(self, profile: str) -> ActionResult:
        target = self._choose_scheme(profile)
        if target is None:
            return ActionResult(
                action="set_power_scheme",
                requested=profile,
                applied=False,
                detail="No compatible installed Windows power scheme was found.",
            )

        name, guid = target
        result = _run_powercfg(["/setactive", guid])
        if result and result.returncode == 0:
            return ActionResult(
                action="set_power_scheme",
                requested=profile,
                applied=True,
                detail=f"Activated existing Windows power scheme: {name}.",
            )

        detail = "powercfg failed."
        if result and result.stderr.strip():
            detail = result.stderr.strip()
        return ActionResult(
            action="set_power_scheme",
            requested=profile,
            applied=False,
            detail=detail,
        )

    def _lower_allowlisted_background_processes(self) -> list[ActionResult]:
        allow = {name.lower() for name in self.config.background_priority_allowlist}
        if not allow:
            return []

        results: list[ActionResult] = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                name = (proc.info["name"] or "").lower()
                if name not in allow:
                    continue

                priority = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", None)
                if priority is None:
                    results.append(
                        ActionResult(
                            "lower_process_priority",
                            name,
                            False,
                            "Windows priority constants are unavailable.",
                        )
                    )
                    continue

                proc.nice(priority)
                results.append(
                    ActionResult(
                        "lower_process_priority",
                        name,
                        True,
                        f"Set PID {proc.pid} to BELOW_NORMAL priority.",
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
                results.append(
                    ActionResult(
                        "lower_process_priority",
                        proc.info.get("name") or "unknown",
                        False,
                        str(exc),
                    )
                )
        return results

    def apply(self, rec: Recommendation) -> list[ActionResult]:
        if self.config.advisor_mode:
            return [
                ActionResult(
                    action="advisor_mode",
                    requested=rec.profile,
                    applied=False,
                    detail="Advisor Mode is enabled; no system setting was changed.",
                )
            ]

        results = [self._apply_power_scheme(rec.profile)]

        if rec.profile in {"LOCAL_AI", "DATA_SCIENCE", "PERFORMANCE"}:
            results.extend(self._lower_allowlisted_background_processes())

        return results

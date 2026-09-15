from __future__ import annotations

import psutil

from .config import AppConfig


def _yes_no(value: bool) -> str:
    return "ON" if value else "OFF"


def _edit_list(label: str, current: list[str]) -> list[str]:
    print(f"\n{label}")
    print("Current:", ", ".join(current) if current else "(empty)")
    print("Enter executable names separated by commas, or press Enter to keep current.")
    raw = input("> ").strip()
    if not raw:
        return current
    return sorted({item.strip() for item in raw.split(",") if item.strip()}, key=str.lower)


def _edit_number(label: str, current, cast):
    raw = input(f"{label} [{current}]: ").strip()
    if not raw:
        return current
    try:
        return cast(raw)
    except ValueError:
        print("Invalid value; keeping current setting.")
        return current


def _show_detected_apps() -> None:
    totals: dict[str, tuple[float, int]] = {}
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = (proc.info.get("name") or "unknown").strip()
            mem = proc.info.get("memory_info")
            rss_mb = float(mem.rss) / (1024 * 1024) if mem else 0.0
            old_mb, old_count = totals.get(name, (0.0, 0))
            totals[name] = (old_mb + rss_mb, old_count + 1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue

    ranked = sorted(totals.items(), key=lambda item: item[1][0], reverse=True)[:20]
    print("\nDetected applications by resident memory:")
    for name, (rss_mb, count) in ranked:
        print(f"  {name:<30} {rss_mb:8.0f} MB  ({count} proc)")


def _summary(config: AppConfig) -> None:
    print("\n=== Snapdragon Performance AI settings ===")
    print(f"Advisor Mode:        {_yes_no(config.advisor_mode)}")
    print(f"Foundry AI:          {_yes_no(config.foundry_enabled)} ({config.foundry_model})")
    print(f"Memory Governor:     {_yes_no(config.memory_governor_enabled)}")
    print(f"Pressure Predictor:  {_yes_no(config.pressure_predictor_enabled)}")
    print(f"Startup Guard:       {_yes_no(config.startup_guard_enabled)}")
    print(f"Background Guard:    {_yes_no(config.background_guard_enabled)}")
    print(f"Working-set trim:    {_yes_no(config.working_set_trim_enabled)}")
    print("Startup close list:  " + (", ".join(config.startup_close_allowlist) or "(empty)"))
    print("Background close:    " + (", ".join(config.background_close_allowlist) or "(empty)"))
    print("Memory priority:     " + (", ".join(config.memory_priority_allowlist) or "(empty)"))


def run_settings(path: str = "config.json") -> None:
    config = AppConfig.load(path)

    while True:
        _summary(config)
        print(
            """
1) Toggle Advisor Mode
2) Startup Guard
3) Background Guard
4) Memory Governor
5) Pressure Predictor
6) Working-set emergency trim
7) Show detected running apps
8) Save and exit
9) Exit without saving
""".strip()
        )
        choice = input("\nChoose: ").strip()

        if choice == "1":
            config.advisor_mode = not config.advisor_mode
        elif choice == "2":
            config.startup_guard_enabled = not config.startup_guard_enabled
            print(f"Startup Guard is now {_yes_no(config.startup_guard_enabled)}")
            config.startup_close_allowlist = _edit_list(
                "Startup apps allowed to close",
                config.startup_close_allowlist,
            )
            config.startup_guard_window_seconds = _edit_number(
                "Startup guard window (seconds)", config.startup_guard_window_seconds, int
            )
            config.startup_guard_grace_seconds = _edit_number(
                "Startup grace period (seconds)", config.startup_guard_grace_seconds, int
            )
        elif choice == "3":
            config.background_guard_enabled = not config.background_guard_enabled
            print(f"Background Guard is now {_yes_no(config.background_guard_enabled)}")
            config.background_close_allowlist = _edit_list(
                "Apps allowed to close after long background idle",
                config.background_close_allowlist,
            )
            config.background_close_idle_seconds = _edit_number(
                "Background idle threshold (seconds)", config.background_close_idle_seconds, int
            )
            config.background_close_min_memory_mb = _edit_number(
                "Minimum RAM before closing (MB)", config.background_close_min_memory_mb, float
            )
        elif choice == "4":
            config.memory_governor_enabled = not config.memory_governor_enabled
            print(f"Memory Governor is now {_yes_no(config.memory_governor_enabled)}")
            config.memory_priority_allowlist = _edit_list(
                "Apps Windows may deprioritize under memory pressure",
                config.memory_priority_allowlist,
            )
            config.memory_high_percent = _edit_number(
                "High-memory threshold (%)", config.memory_high_percent, float
            )
            config.memory_critical_percent = _edit_number(
                "Critical-memory threshold (%)", config.memory_critical_percent, float
            )
            config.memory_recovery_percent = _edit_number(
                "Recovery threshold (%)", config.memory_recovery_percent, float
            )
        elif choice == "5":
            config.pressure_predictor_enabled = not config.pressure_predictor_enabled
            print(f"Pressure Predictor is now {_yes_no(config.pressure_predictor_enabled)}")
            config.pressure_prediction_horizon_seconds = _edit_number(
                "Prediction horizon (seconds)", config.pressure_prediction_horizon_seconds, int
            )
            config.pressure_prediction_warn_percent = _edit_number(
                "Predicted-memory warning threshold (%)",
                config.pressure_prediction_warn_percent,
                float,
            )
        elif choice == "6":
            config.working_set_trim_enabled = not config.working_set_trim_enabled
            print(f"Working-set trim is now {_yes_no(config.working_set_trim_enabled)}")
            config.working_set_trim_allowlist = _edit_list(
                "Apps allowed to receive emergency working-set trims",
                config.working_set_trim_allowlist,
            )
            print("Note: leave this OFF unless you have tested the app under pressure.")
        elif choice == "7":
            _show_detected_apps()
        elif choice == "8":
            config.save(path)
            print(f"Saved settings to {path}")
            return
        elif choice == "9":
            print("No changes saved.")
            return
        else:
            print("Unknown choice.")

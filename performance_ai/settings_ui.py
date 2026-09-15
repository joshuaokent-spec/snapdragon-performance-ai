from __future__ import annotations

import psutil

from .config import AppConfig


class SettingsExit(Exception):
    """Internal control-flow exception for leaving the settings UI."""


class SettingsBack(Exception):
    """Internal control-flow exception for returning to the main settings menu."""


def _yes_no(value: bool) -> str:
    return "ON" if value else "OFF"


def _prompt(prompt: str, *, allow_back: bool = False) -> str:
    """Read one settings value with consistent escape commands.

    At any prompt:
      :q / :quit / :exit -> leave settings without saving
      :back             -> return to the main settings menu (when allowed)
      Ctrl+C / EOF      -> leave settings without saving
    """
    try:
        raw = input(prompt)
    except (KeyboardInterrupt, EOFError) as exc:
        raise SettingsExit from exc

    cleaned = raw.strip()
    lowered = cleaned.lower()
    if lowered in {":q", ":quit", ":exit"}:
        raise SettingsExit
    if allow_back and lowered in {":back", ":b"}:
        raise SettingsBack
    return cleaned


def _edit_bool(label: str, current: bool) -> bool:
    default = "on" if current else "off"
    raw = _prompt(
        f"{label} [on/off, current={default}] (:back to menu): ",
        allow_back=True,
    ).lower()
    if not raw:
        return current
    if raw in {"on", "yes", "y", "true", "1"}:
        return True
    if raw in {"off", "no", "n", "false", "0"}:
        return False
    print("Unrecognized value; keeping current setting.")
    return current


def _edit_list(label: str, current: list[str], examples: str | None = None) -> list[str]:
    print(f"\n{label}")
    print("Current:", ", ".join(current) if current else "(empty)")
    if examples:
        print(f"Examples: {examples}")
    print("Enter executable names separated by commas.")
    print("Press Enter to keep current, :back for menu, or :q to exit settings.")
    raw = _prompt("> ", allow_back=True)
    if not raw:
        return current
    return sorted({item.strip() for item in raw.split(",") if item.strip()}, key=str.lower)


def _edit_number(label: str, current, cast):
    raw = _prompt(
        f"{label} [{current}] (:back to menu): ",
        allow_back=True,
    )
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
    print(f"Force-kill fallback: {_yes_no(config.process_force_kill_enabled)}")
    print("Startup close list:  " + (", ".join(config.startup_close_allowlist) or "(empty)"))
    print("Background close:    " + (", ".join(config.background_close_allowlist) or "(empty)"))
    print("Memory priority:     " + (", ".join(config.memory_priority_allowlist) or "(empty)"))


def run_settings(path: str = "config.json") -> None:
    config = AppConfig.load(path)

    print("Settings controls: q/quit/exit/0 = exit without saving, 9 = save and exit.")
    print("At nested prompts, :back returns to this menu and :q exits without saving.")

    try:
        while True:
            _summary(config)
            print(
                """
1) Advisor / automation mode
2) Startup Guard
3) Background Guard
4) Memory Governor
5) Pressure Predictor
6) Working-set emergency trim
7) Process close behavior
8) Show detected running apps
9) Save and exit
0) Exit without saving
""".strip()
            )
            choice = _prompt("\nChoose: ").strip().lower()

            if choice == "1":
                config.advisor_mode = _edit_bool("Advisor Mode", config.advisor_mode)
            elif choice == "2":
                try:
                    config.startup_guard_enabled = _edit_bool(
                        "Enable Startup Guard", config.startup_guard_enabled
                    )
                    config.startup_close_allowlist = _edit_list(
                        "Startup apps allowed to close",
                        config.startup_close_allowlist,
                        "btweb.exe, steam.exe, Discord.exe",
                    )
                    config.startup_guard_window_seconds = _edit_number(
                        "Startup guard window (seconds)", config.startup_guard_window_seconds, int
                    )
                    config.startup_guard_grace_seconds = _edit_number(
                        "Startup grace period (seconds)", config.startup_guard_grace_seconds, int
                    )
                except SettingsBack:
                    continue
            elif choice == "3":
                try:
                    config.background_guard_enabled = _edit_bool(
                        "Enable Background Guard", config.background_guard_enabled
                    )
                    config.background_close_allowlist = _edit_list(
                        "Apps allowed to close after long background idle",
                        config.background_close_allowlist,
                        "btweb.exe, steam.exe, Discord.exe",
                    )
                    config.background_close_idle_seconds = _edit_number(
                        "Background idle threshold (seconds)", config.background_close_idle_seconds, int
                    )
                    config.background_close_min_memory_mb = _edit_number(
                        "Minimum RAM before closing (MB)", config.background_close_min_memory_mb, float
                    )
                except SettingsBack:
                    continue
            elif choice == "4":
                try:
                    config.memory_governor_enabled = _edit_bool(
                        "Enable Memory Governor", config.memory_governor_enabled
                    )
                    config.memory_priority_allowlist = _edit_list(
                        "Apps Windows may deprioritize under memory pressure",
                        config.memory_priority_allowlist,
                        "msedge.exe, Discord.exe, steamwebhelper.exe",
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
                except SettingsBack:
                    continue
            elif choice == "5":
                try:
                    config.pressure_predictor_enabled = _edit_bool(
                        "Enable Pressure Predictor", config.pressure_predictor_enabled
                    )
                    config.pressure_predictive_actions_enabled = _edit_bool(
                        "Allow predictive preemptive memory actions",
                        config.pressure_predictive_actions_enabled,
                    )
                    config.pressure_prediction_horizon_seconds = _edit_number(
                        "Prediction horizon (seconds)", config.pressure_prediction_horizon_seconds, int
                    )
                    config.pressure_prediction_warn_percent = _edit_number(
                        "Predicted-memory warning threshold (%)",
                        config.pressure_prediction_warn_percent,
                        float,
                    )
                except SettingsBack:
                    continue
            elif choice == "6":
                try:
                    config.working_set_trim_enabled = _edit_bool(
                        "Enable emergency working-set trim", config.working_set_trim_enabled
                    )
                    config.working_set_trim_allowlist = _edit_list(
                        "Apps allowed to receive emergency working-set trims",
                        config.working_set_trim_allowlist,
                    )
                    print("Note: leave this OFF unless you have tested the app under pressure.")
                except SettingsBack:
                    continue
            elif choice == "7":
                try:
                    config.process_close_children = _edit_bool(
                        "Close approved app child/helper processes", config.process_close_children
                    )
                    config.process_force_kill_enabled = _edit_bool(
                        "Allow force-kill if graceful close times out",
                        config.process_force_kill_enabled,
                    )
                    config.process_close_timeout_seconds = _edit_number(
                        "Graceful close timeout (seconds)", config.process_close_timeout_seconds, int
                    )
                except SettingsBack:
                    continue
            elif choice == "8":
                _show_detected_apps()
            elif choice in {"9", "s", "save"}:
                config.save(path)
                print(f"Saved settings to {path}")
                return
            elif choice in {"0", "q", "quit", "exit"}:
                print("No changes saved.")
                return
            else:
                print("Unknown choice. Use 0/q to exit or 9 to save and exit.")
    except SettingsExit:
        print("\nSettings closed without saving.")
        return

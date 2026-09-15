from __future__ import annotations

import os
import sys
from pathlib import Path


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not available; Windows Startup folder could not be resolved.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _launcher_path() -> Path:
    return _startup_dir() / "SnapdragonPerformanceAI.cmd"


def install_autostart() -> Path:
    """Create a per-user Startup-folder launcher for monitor mode.

    This is intentionally reversible and avoids registry or scheduled-task
    changes. It uses the active virtual environment's pythonw.exe when present.
    """
    project_root = Path(__file__).resolve().parents[1]
    main_py = project_root / "main.py"
    python_exe = Path(sys.executable)
    pythonw = python_exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else python_exe

    startup = _startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    launcher = _launcher_path()

    log_path = project_root / "data" / "startup.log"
    content = (
        "@echo off\n"
        f"cd /d \"{project_root}\"\n"
        f"if not exist \"{project_root / 'data'}\" mkdir \"{project_root / 'data'}\"\n"
        f"start \"\" /min \"{runner}\" \"{main_py}\" monitor >> \"{log_path}\" 2>&1\n"
    )
    launcher.write_text(content, encoding="utf-8")
    return launcher


def remove_autostart() -> bool:
    launcher = _launcher_path()
    if not launcher.exists():
        return False
    launcher.unlink()
    return True


def autostart_status() -> tuple[bool, Path]:
    launcher = _launcher_path()
    return launcher.exists(), launcher

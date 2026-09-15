# Snapdragon Performance AI

A Windows 11 / Snapdragon Copilot+ PC performance governor that combines:

- live Windows telemetry (`psutil` + Windows APIs),
- local AI inference through **Microsoft Foundry Local**,
- Qualcomm QNN / Snapdragon NPU acceleration when an NPU model variant is available,
- deterministic safety policies,
- predictive memory-pressure analysis,
- an adaptive Windows memory governor,
- startup/background application guards,
- SQLite telemetry and prediction history,
- optional, allowlisted, reversible optimization actions.

> **Current status: v0.2 development**
>
> The program defaults to **Advisor Mode**. It can predict, classify, and tell you what it *would* change, but it cannot modify or close anything until Advisor Mode is explicitly disabled.

## Architecture

```text
Windows telemetry
      |
      +------------------------------+
      |                              |
      v                              v
Rule classifier              Pressure predictor
      |                              |
      |                       2-minute forecast
      |                              |
      +------------+-----------------+
                   |
                   v
          Foundry Local server
          127.0.0.1:<port>
                   |
            QNN / Hexagon NPU
                   |
                   v
            AI recommendation
                   |
                   v
            Deterministic policy
                   |
       +-----------+------------+
       |           |            |
       v           v            v
 Power/profile  Memory       Process guards
 optimizer      governor     startup/background
       |           |            |
       +-----------+------------+
                   |
                   v
              SQLite history
```

The local language model is **never allowed to execute commands**. It may classify the workload and reason about telemetry/predictions. Windows changes are performed only by deterministic Python code with explicit allowlists.

## Current capabilities

- CPU utilization
- total memory utilization
- per-process resident memory (RSS) in MB
- aggregated high-memory process diagnostics
- foreground application detection
- battery / charging state
- active Windows power scheme
- local Foundry/QNN NPU workload classification
- rolling near-future RAM-pressure prediction
- SQLite prediction logging for future model training
- adaptive memory-pressure tiers with hysteresis
- Windows process memory-priority control
- optional CPU-priority reduction for approved background apps
- automatic priority restoration when RAM pressure recovers
- immediate priority restoration when a managed process becomes foreground
- optional emergency working-set trimming with a second allowlist
- Startup Guard for unwanted login/startup apps
- Background Guard for approved apps left unfocused for a long period
- graceful process termination first; force-kill disabled by default
- interactive settings menu
- reversible per-user Windows login autostart helper

## Memory governor

The program does **not** transfer RAM between applications. Windows owns physical page placement. The governor influences Windows more safely:

1. **High pressure** (default 85%+): approved background apps may receive lower memory priority.
2. **Critical pressure** (default 92%+): approved apps may be lowered further.
3. **Predictive pressure**: if the trend model forecasts high RAM pressure soon with enough confidence, the governor may act preemptively.
4. **Recovery** (default below 78%): changed priorities are restored.
5. If a managed application becomes foreground, its saved priorities are restored immediately.

Working-set trimming is disabled by default because aggressively forcing pages out can increase page faults and make an application slower.

## Resource-pressure predictor

v0.2 includes a lightweight rolling trend predictor. It runs every telemetry cycle and forecasts RAM usage over the next two minutes by default.

Example:

```text
RAM now:      79.0%
RAM forecast: 89.4%
Trend:        +5.2%/min
Risk:         high
Confidence:   73%
```

This first predictor is intentionally statistical rather than ML-heavy. Every prediction is stored in SQLite so the project can later train a custom workload/pressure model and export it to ONNX for Windows ML / Qualcomm QNN execution on the NPU.

## Startup Guard and Background Guard

### Startup Guard

Designed for applications such as Steam, Discord, or BitTorrent Web that may launch silently at login.

Only exact executable names in `startup_close_allowlist` are eligible. Example **only**:

```json
"startup_close_allowlist": [
  "btweb.exe",
  "steam.exe",
  "Discord.exe"
]
```

Startup Guard only acts during the configured post-boot window and never closes the foreground application.

### Background Guard

This is separate from Startup Guard. It can close explicitly approved applications after they have remained out of the foreground for a configured duration and exceed a minimum memory footprint.

Example **only**:

```json
"background_guard_enabled": true,
"background_close_allowlist": ["Discord.exe"],
"background_close_idle_seconds": 1800,
"background_close_min_memory_mb": 100
```

A process you actively return to is not treated as idle. Graceful termination is attempted first. Force-kill remains disabled unless explicitly enabled.

## Settings area

Run:

```powershell
python main.py settings
```

The interactive settings menu controls:

- Advisor / automation mode
- Startup Guard
- Background Guard
- Memory Governor
- pressure-prediction settings
- working-set trimming
- graceful-close / force-kill behavior
- process allowlists
- thresholds
- a live list of currently detected applications and their RAM use

## Run automatically at login

Startup Guard is only useful after login if the optimizer itself starts automatically.

Install the reversible per-user Startup-folder launcher:

```powershell
python main.py install-startup
```

Remove it with:

```powershell
python main.py remove-startup
```

This does not modify the registry or create a scheduled task.

## Safety model

By default:

```json
"advisor_mode": true
```

Even with Advisor Mode disabled:

1. AI output is parsed as data and never executed.
2. Process closing is exact-name allowlist-only.
3. Core Windows processes, Explorer, Foundry, Task Manager, and the optimizer's own Python process are protected.
4. The foreground process is excluded from process closing and memory deprioritization.
5. Memory/CPU priority changes require explicit allowlists.
6. Working-set trimming requires a separate allowlist and is disabled by default.
7. Process closing uses graceful termination first.
8. Force-kill is disabled by default.
9. BIOS, firmware, drivers, registry, services, Windows Update, security software, clocks, voltages, and thermal protections are untouched.

## Requirements

- Windows 11
- Python 3.11+
- Snapdragon X Elite / Copilot+ PC recommended
- Microsoft Foundry Local CLI available as `foundry`
- `psutil`

The Python process does **not** load the native Foundry Python SDK. It talks to the already-running Foundry Local server over localhost, keeping the hardware runtime isolated from the monitoring process.

## Install

```powershell
cd C:\AI
git clone https://github.com/joshuaokent-spec/snapdragon-performance-ai.git
cd snapdragon-performance-ai

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Safe first run

```powershell
pytest
python main.py diagnose
python main.py settings
python main.py once
```

Then monitor continuously in Advisor Mode:

```powershell
python main.py monitor
```

Stop with `Ctrl+C`.

## Key configuration defaults

```json
{
  "advisor_mode": true,

  "memory_governor_enabled": true,
  "memory_high_percent": 85.0,
  "memory_critical_percent": 92.0,
  "memory_recovery_percent": 78.0,
  "memory_priority_allowlist": [],

  "pressure_predictor_enabled": true,
  "pressure_prediction_horizon_seconds": 120,
  "pressure_prediction_warn_percent": 88.0,
  "pressure_predictive_actions_enabled": true,

  "startup_guard_enabled": true,
  "startup_close_allowlist": [],

  "background_guard_enabled": false,
  "background_close_allowlist": [],
  "background_close_idle_seconds": 1800,

  "working_set_trim_enabled": false,
  "working_set_trim_allowlist": [],

  "process_force_kill_enabled": false
}
```

Nothing is approved for closing, trimming, or memory deprioritization by default.

## Database

Runtime data is stored at:

```text
data/performance_ai.db
```

Tables:

- `telemetry`
- `predictions`
- `recommendations`
- `actions`

The `predictions` table is the beginning of the future training dataset for a custom resource-pressure model.

## Project layout

```text
snapdragon-performance-ai/
├── main.py
├── config.json
├── requirements.txt
├── pyproject.toml
├── performance_ai/
│   ├── app.py
│   ├── autostart.py
│   ├── classifier.py
│   ├── config.py
│   ├── memory_governor.py
│   ├── models.py
│   ├── npu.py
│   ├── optimizer.py
│   ├── policy.py
│   ├── predictor.py
│   ├── process_guard.py
│   ├── profiles.py
│   ├── settings_ui.py
│   ├── storage.py
│   └── telemetry.py
└── tests/
    ├── test_classifier.py
    ├── test_memory_governor.py
    ├── test_npu.py
    ├── test_policy.py
    ├── test_predictor.py
    └── test_process_guard.py
```

## Roadmap

### v0.2
- tune prediction thresholds using real Lenovo telemetry
- measure whether interventions actually improve responsiveness
- add richer application importance/history scoring
- add tray UI and Windows notifications
- improve Lenovo/Snapdragon NPU telemetry mapping

### v0.3
- train a custom resource-pressure/workload model from the SQLite history
- export it to ONNX
- run it through Windows ML / Qualcomm QNN on the Hexagon NPU
- keep the LLM for unusual cases and explanations

### v0.4
- learned per-user policy
- CPU/GPU/NPU energy/performance benchmarking
- intervention effectiveness scoring
- graphical historical dashboard

## License

MIT

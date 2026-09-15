# Snapdragon Performance AI

A Windows 11 / Snapdragon Copilot+ PC performance advisor that combines:

- live system telemetry (`psutil` + Windows APIs),
- local AI inference through **Microsoft Foundry Local**,
- Qualcomm QNN / Snapdragon NPU acceleration when an NPU model variant is available,
- deterministic safety policies,
- an adaptive Windows memory governor,
- SQLite telemetry history,
- optional, allowlisted and reversible optimization actions.

> **Current status: v0.2 development**
>
> The program defaults to **Advisor Mode**. The AI can recommend a profile and the memory governor can identify pressure/candidates, but no system setting is changed until Advisor Mode is explicitly disabled.

## Architecture

The app deliberately uses Foundry Local's localhost HTTP service instead of loading Foundry's native Python CFFI runtime into the monitoring process. This keeps the system monitor isolated from hardware-runtime crashes while inference remains entirely on the local PC.

```text
Windows telemetry
      |
      v
Rule classifier ----+
      |              |
      |       Foundry Local server
      |       127.0.0.1:<port>
      |              |
      |       QNN / Hexagon NPU
      |              |
      +-------> AI recommendation
                       |
                       v
                  Policy engine
                       |
              +--------+--------+
              |                 |
              v                 v
        Profile optimizer   Memory governor
              |                 |
              +--------+--------+
                       |
                       v
                   SQLite log
```

The application asks the Foundry CLI to load the configured model alias, discovers the local server URL, and sends an OpenAI-compatible `/v1/chat/completions` request over localhost. No cloud inference is required.

The language model is **not** allowed to execute commands. It may only choose from known workload categories and optimization profiles. All Windows changes are implemented by deterministic, allowlisted Python code.

## Current capabilities

- CPU utilization
- total memory utilization
- per-process resident memory (RSS) in MB
- aggregated high-memory process diagnostics
- disk capacity utilization
- battery percentage / charging state
- foreground application
- top CPU-consuming processes
- active Windows power scheme
- best-effort NPU utilization discovery through Windows performance counters
- deterministic workload classification fallback
- Foundry Local workload classification through localhost
- policy validation and battery safety override
- adaptive memory-pressure tiers with hysteresis
- Windows process memory-priority control
- optional CPU-priority reduction for approved background apps
- optional emergency working-set trimming for an explicit second allowlist
- automatic restoration of priorities after memory pressure recovers
- SQLite history
- optional Windows power-scheme switching

## What the memory governor actually does

The program does **not** literally transfer RAM from one application to another. Windows owns physical-page placement. The governor influences Windows' decisions in safer ways:

1. **High pressure** (default: 85%+ RAM used): approved background processes can be assigned a lower Windows memory priority, causing their pages to be preferred for trimming before higher-priority pages.
2. **Critical pressure** (default: 92%+): approved processes can be lowered further. If working-set trimming is explicitly enabled, only processes in a second trim allowlist are eligible.
3. **Recovery** (default: below 78%): priorities changed by the governor are restored to the values captured before management began.
4. The foreground process, the optimizer itself, Foundry, Explorer, and core Windows processes are protected.

Working-set trimming is intentionally disabled by default. It can free resident pages quickly, but those pages may fault back in immediately if the application still needs them, so aggressive trimming can make performance worse.

## Safety model

By default:

```json
"advisor_mode": true
```

This means no Windows setting is changed.

Even when Advisor Mode is disabled:

1. Model output is parsed as data, never executed.
2. Only known profiles are accepted.
3. Power schemes must already exist on Windows.
4. The app does not create/delete power schemes.
5. Memory/CPU priority changes only target executable names placed in an explicit allowlist.
6. Working-set trimming requires a separate explicit allowlist and is disabled by default.
7. Foreground, protected Windows, Foundry, Explorer, and the optimizer's own process are never memory-managed.
8. BIOS, drivers, registry, services, Windows Update, security software, voltages, clocks, and thermal controls are untouched.

## Requirements

- Windows 11
- Python 3.11+
- Snapdragon X Elite / Copilot+ PC recommended
- Microsoft Foundry Local CLI installed and available as `foundry`
- `psutil`

The Python application does **not** require the native `foundry-local-sdk` package. Foundry owns the model runtime in its separate local server process.

The application can still run without Foundry Local by using:

```powershell
python main.py once --no-ai
```

## Install

From PowerShell:

```powershell
cd C:\AI
git clone https://github.com/joshuaokent-spec/snapdragon-performance-ai.git
cd snapdragon-performance-ai

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## First run

Keep Advisor Mode enabled.

Run the tests:

```powershell
pytest
```

Inspect the local hardware / Foundry setup:

```powershell
python main.py diagnose
```

Test one cycle:

```powershell
python main.py once
```

To monitor continuously:

```powershell
python main.py monitor
```

Stop it with `Ctrl+C`.

## Configuration

Important settings in `config.json`:

```json
{
  "advisor_mode": true,
  "foundry_enabled": true,
  "foundry_model": "qwen2.5-0.5b",
  "telemetry_interval_seconds": 5,
  "ai_interval_seconds": 180,

  "memory_governor_enabled": true,
  "memory_high_percent": 85.0,
  "memory_critical_percent": 92.0,
  "memory_recovery_percent": 78.0,

  "memory_priority_allowlist": [],
  "memory_lower_cpu_priority": true,
  "memory_max_managed_processes": 4,

  "working_set_trim_enabled": false,
  "working_set_trim_allowlist": [],
  "working_set_trim_min_mb": 512.0,
  "working_set_trim_cooldown_seconds": 300
}
```

### Advisor Mode

Recommended while testing:

```json
"advisor_mode": true
```

At high memory pressure the program will report the largest memory consumers and tell you which approved processes it *would* reprioritize, but it will not change them.

### Approving background applications

After observing the advisor output, add only applications you are comfortable deprioritizing when they are in the background. Example only:

```json
"memory_priority_allowlist": [
  "msedge.exe",
  "Discord.exe"
]
```

The currently foreground PID is excluded even if its executable name is allowlisted.

### Automatic application

Only switch this after reviewing several monitor cycles:

```json
"advisor_mode": false
```

The memory governor then runs every telemetry cycle (5 seconds by default), while the AI model can remain on the slower 180-second cadence.

### Emergency working-set trimming

Leave this disabled initially:

```json
"working_set_trim_enabled": false
```

If it is ever enabled, an app must also appear in `working_set_trim_allowlist`, exceed `working_set_trim_min_mb`, the system must be at the critical memory threshold, and the per-process cooldown must have expired.

## NPU telemetry

Windows performance counter naming varies by device/driver version. The app performs a best-effort search for an NPU utilization counter.

If none is available, it reports:

```text
NPU: counter unavailable
```

This does **not** mean the NPU is broken. Foundry's model catalog and Task Manager provide independent confirmation of NPU support and activity.

## Power schemes

The app reads schemes that already exist using `powercfg /list`. It never creates or deletes one.

Profiles request a *kind* of scheme:

- Efficiency -> Power saver if installed
- Balanced / Development -> Balanced if installed
- Data Science / Local AI / Performance -> High performance or Ultimate Performance if installed

If the Lenovo only exposes Balanced, the action becomes a no-op rather than forcing an unsupported configuration.

## Database

Runtime data is stored in:

```text
data/performance_ai.db
```

This is ignored by Git so personal usage history is not accidentally committed.

Tables:

- `telemetry`
- `recommendations`
- `actions`

That dataset can later be used to train a custom workload-classification model and learn which memory interventions actually improve responsiveness.

## Project layout

```text
snapdragon-performance-ai/
├── main.py
├── config.json
├── requirements.txt
├── pyproject.toml
├── performance_ai/
│   ├── app.py
│   ├── classifier.py
│   ├── config.py
│   ├── memory_governor.py
│   ├── models.py
│   ├── npu.py
│   ├── optimizer.py
│   ├── policy.py
│   ├── profiles.py
│   ├── storage.py
│   └── telemetry.py
└── tests/
    ├── test_classifier.py
    ├── test_memory_governor.py
    ├── test_npu.py
    └── test_policy.py
```

## Roadmap

### v0.2
- tune the adaptive memory governor from real Lenovo telemetry
- add per-process memory history and intervention effectiveness scoring
- add a tray UI and Windows notifications
- add profile-learning from user approvals/rejections
- richer process classification
- Lenovo/Snapdragon-specific NPU telemetry mapping
- temperature data where the device exposes it

### v0.3
- train a lightweight workload / pressure classifier from collected telemetry
- export the classifier to ONNX
- run it through Windows ML / Qualcomm QNN
- reserve the LLM for explanations and unusual cases

### v0.4
- energy/performance benchmarking
- compare CPU, GPU, and NPU inference
- learned per-user optimization policy
- dashboard and historical charts

## License

MIT

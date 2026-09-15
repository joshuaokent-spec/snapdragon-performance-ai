# Snapdragon Performance AI

A Windows 11 / Snapdragon Copilot+ PC performance advisor that combines:

- live system telemetry (`psutil` + Windows APIs),
- local AI inference through **Microsoft Foundry Local**,
- Windows ML / Qualcomm NPU acceleration when a compatible model variant is available,
- deterministic safety policies,
- SQLite telemetry history,
- optional, allowlisted and reversible optimization actions.

> **Current status: v0.1 MVP**
>
> The program defaults to **Advisor Mode**. The AI can recommend a profile, but it cannot invent or execute arbitrary shell commands.

## Why this exists

The Snapdragon X Elite includes a dedicated Hexagon NPU, but normal Python programs do not automatically make use of it. This project uses a small Foundry Local model as a local decision layer while ordinary Python code collects telemetry and enforces safety rules.

```text
Windows telemetry
      |
      v
Rule classifier ----+
      |              |
      |         Foundry Local model
      |              |
      +-------> recommendation
                       |
                       v
                  Policy engine
                       |
                       v
                Advisor / Optimizer
                       |
                       v
                   SQLite log
```

The language model is **not** allowed to execute commands. It may only choose from known workload categories and optimization profiles.

## v0.1 capabilities

- CPU utilization
- memory utilization
- disk utilization
- battery percentage / charging state
- foreground application
- top CPU-consuming processes
- active Windows power scheme
- best-effort NPU utilization discovery through Windows performance counters
- deterministic workload classification fallback
- Foundry Local workload classification
- policy validation and battery safety override
- SQLite history
- optional Windows power-scheme switching
- optional process-priority reduction for an explicit allowlist

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
5. Process priority can only be changed for executable names you explicitly place in `background_priority_allowlist`.
6. BIOS, drivers, registry, services, Windows Update, security software, voltages, clocks, and thermal controls are untouched.

## Requirements

- Windows 11
- Python 3.11+
- Snapdragon X Elite / Copilot+ PC recommended
- Microsoft Foundry Local
- `foundry-local-sdk-winml`
- `psutil`

The application still runs without Foundry Local by falling back to its deterministic classifier.

## Install

From PowerShell:

```powershell
cd C:\AI\FoundryLocal
git clone <your-github-repo-url> snapdragon-performance-ai
cd snapdragon-performance-ai

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you already have an activated virtual environment, just run:

```powershell
pip install -r requirements.txt
```

## First run

Keep Advisor Mode enabled.

```powershell
python main.py once
```

That collects one snapshot and prints the recommendation.

To skip the AI model and test only the deterministic system:

```powershell
python main.py once --no-ai
```

To monitor continuously:

```powershell
python main.py monitor
```

Stop it with `Ctrl+C`.

## Configuration

Copy the included settings or edit `config.json` directly.

Important settings:

```json
{
  "advisor_mode": true,
  "foundry_enabled": true,
  "foundry_model": "qwen2.5-0.5b",
  "telemetry_interval_seconds": 5,
  "ai_interval_seconds": 180,
  "background_priority_allowlist": []
}
```

### Advisor Mode

Recommended while testing:

```json
"advisor_mode": true
```

No system changes will be made.

### Automatic application

Only switch this after reviewing the recommendations produced on your machine:

```json
"advisor_mode": false
```

The optimizer still remains restricted to the hard-coded action allowlist.

## NPU telemetry

Windows performance counter naming varies by device/driver version. The app performs a best-effort search for an NPU utilization counter.

If none is available, it reports:

```text
NPU: unavailable
```

This does **not** mean the NPU is broken. Task Manager remains the most reliable visual check while we refine device-specific NPU telemetry support.

## Power schemes

The app reads schemes that already exist using:

```powershell
powercfg /list
```

It never creates or deletes one.

Profiles request a *kind* of scheme:

- Efficiency -> Power saver if installed
- Balanced / Development -> Balanced if installed
- Data Science / Local AI / Performance -> High performance or Ultimate Performance if installed

If your Lenovo only exposes Balanced, the action becomes a no-op rather than forcing an unsupported configuration.

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

That dataset can later be used to train your own workload-classification model.

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
│   ├── models.py
│   ├── npu.py
│   ├── optimizer.py
│   ├── policy.py
│   ├── profiles.py
│   ├── storage.py
│   └── telemetry.py
└── tests/
    ├── test_classifier.py
    └── test_policy.py
```

## Roadmap

### v0.2
- Lenovo/Snapdragon-specific NPU counter mapping
- tray UI
- Windows notifications
- profile-learning from user approvals/rejections
- richer process classification
- temperature data where the device exposes it

### v0.3
- train a lightweight workload classifier from collected telemetry
- export neural classifier to ONNX
- run classifier through Windows ML / Qualcomm QNN
- reserve the LLM for explanations and unusual cases

### v0.4
- energy/performance benchmarking
- compare CPU, GPU, and NPU inference
- learned per-user optimization policy
- dashboard and historical charts

## License

MIT

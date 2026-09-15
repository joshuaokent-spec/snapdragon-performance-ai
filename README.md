# Snapdragon Performance AI

A Windows 11 / Snapdragon Copilot+ PC performance advisor that combines:

- live system telemetry (`psutil` + Windows APIs),
- local AI inference through **Microsoft Foundry Local**,
- Qualcomm QNN / Snapdragon NPU acceleration when an NPU model variant is available,
- deterministic safety policies,
- SQLite telemetry history,
- optional, allowlisted and reversible optimization actions.

> **Current status: v0.1 MVP**
>
> The program defaults to **Advisor Mode**. The AI can recommend a profile, but it cannot invent or execute arbitrary shell commands.

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
                       v
                Advisor / Optimizer
                       |
                       v
                   SQLite log
```

The application asks the Foundry CLI to load the configured model alias, discovers the local server URL, and sends an OpenAI-compatible `/v1/chat/completions` request over localhost. No cloud inference is required.

The language model is **not** allowed to execute commands. It may only choose from known workload categories and optimization profiles.

## v0.1 capabilities

- CPU utilization
- memory utilization
- disk capacity utilization
- battery percentage / charging state
- foreground application
- top CPU-consuming processes
- active Windows power scheme
- best-effort NPU utilization discovery through Windows performance counters
- deterministic workload classification fallback
- Foundry Local workload classification through localhost
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

Test the telemetry-only path:

```powershell
python main.py once --no-ai
```

Then test local AI inference:

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

That dataset can later be used to train a custom workload-classification model.

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
    ├── test_npu.py
    └── test_policy.py
```

## Roadmap

### v0.2
- Lenovo/Snapdragon-specific NPU telemetry mapping
- tray UI
- Windows notifications
- profile-learning from user approvals/rejections
- richer process classification
- temperature data where the device exposes it

### v0.3
- train a lightweight workload classifier from collected telemetry
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

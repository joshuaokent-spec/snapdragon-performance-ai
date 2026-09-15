from __future__ import annotations

import argparse
import os
import platform
import sys
import sysconfig
import time
from importlib import metadata

from .classifier import FoundryClassifier, RuleClassifier
from .config import AppConfig
from .models import Recommendation, TelemetrySnapshot
from .npu import foundry_npu_diagnostics
from .optimizer import Optimizer
from .policy import PolicyEngine
from .storage import Storage
from .telemetry import TelemetryCollector


def _package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def _print_snapshot(snap: TelemetrySnapshot) -> None:
    npu = (
        "counter unavailable"
        if snap.npu_percent is None
        else f"{snap.npu_percent:.1f}%"
    )
    battery = (
        "unavailable"
        if snap.battery_percent is None
        else f"{snap.battery_percent:.0f}% "
        f"({'plugged in' if snap.plugged_in else 'battery'})"
    )

    print("\n=== System snapshot ===")
    print(f"CPU:        {snap.cpu_percent:5.1f}%")
    print(f"Memory:     {snap.memory_percent:5.1f}%")
    print(f"Disk used:  {snap.disk_percent:5.1f}%")
    print(f"NPU:        {npu}")
    print(f"Battery:    {battery}")
    print(f"Foreground: {snap.foreground_process or 'unknown'}")
    print(f"Power:      {snap.power_scheme or 'unknown'}")

    if snap.npu_percent is None:
        print("            (Task Manager may still expose NPU usage normally.)")

    if snap.top_processes:
        print("\nTop processes:")
        for proc in snap.top_processes[:5]:
            print(
                f"  {proc.name:<26} "
                f"CPU {proc.cpu_percent:5.1f}%  "
                f"RAM {proc.rss_mb:7.0f} MB ({proc.memory_percent:4.1f}%)"
            )


def _print_recommendation(rec: Recommendation) -> None:
    print("\n=== Recommendation ===")
    print(f"Workload:   {rec.workload}")
    print(f"Profile:    {rec.profile}")
    print(f"Confidence: {rec.confidence:.0%}")
    print(f"Source:     {rec.source}")
    print(f"Reason:     {rec.reason}")


def run_diagnostics() -> None:
    print("=== Snapdragon Performance AI diagnostics ===")

    process_arch = platform.machine() or "unknown"
    processor_arch = os.environ.get("PROCESSOR_ARCHITECTURE", "unset")
    processor_arch_w6432 = os.environ.get("PROCESSOR_ARCHITEW6432", "unset")
    print("\nPython runtime:")
    print(f"  Version:        {platform.python_version()}")
    print(f"  Executable:     {sys.executable}")
    print(f"  Process arch:   {process_arch}")
    print(f"  Platform tag:   {sysconfig.get_platform()}")
    print(f"  Env arch:       {processor_arch}")
    print(f"  Env WOW64 arch: {processor_arch_w6432}")

    print("\nPython packages:")
    print(f"  foundry-local-sdk:       {_package_version('foundry-local-sdk')}")
    print(f"  foundry-local-sdk-winml: {_package_version('foundry-local-sdk-winml')}")
    print(f"  onnxruntime-core:        {_package_version('onnxruntime-core')}")

    data = foundry_npu_diagnostics()

    counters = data.get("typeperf_npu_counters") or []
    print(f"\nWindows NPU performance counters: {len(counters)} found")
    for counter in counters[:8]:
        print(f"  {counter}")
    if not counters:
        print("  None found. This is not proof that the NPU is unavailable.")

    print(f"\nFoundry CLI: {data.get('foundry_cli') or 'not found on PATH'}")
    print(f"Foundry CLI version: {data.get('foundry_version') or 'unavailable'}")

    print("\nFoundry server status:")
    print(data.get("foundry_server") or "  unavailable")

    print("\nFoundry NPU model variants:")
    print(data.get("foundry_npu_models") or "  none reported")


class PerformanceAI:
    def __init__(self, config: AppConfig, use_ai: bool = True):
        self.config = config
        self.collector = TelemetryCollector(config.top_process_count)
        self.rules = RuleClassifier()
        self.policy = PolicyEngine(config)
        self.optimizer = Optimizer(config)
        self.storage = Storage(config.database_path)
        self.use_ai = bool(use_ai and config.foundry_enabled)
        self.ai = (
            FoundryClassifier(config.foundry_model)
            if self.use_ai
            else None
        )

    def evaluate(self, use_foundry: bool = True) -> tuple[
        TelemetrySnapshot, Recommendation
    ]:
        snap = self.collector.collect()
        baseline = self.rules.classify(snap)
        rec = baseline

        if use_foundry and self.ai is not None:
            try:
                rec = self.ai.classify(snap, baseline)
            except Exception as exc:
                detail = str(exc).strip().replace("\n", " ")[:240]
                suffix = f": {detail}" if detail else ""
                rec = Recommendation(
                    workload=baseline.workload,
                    profile=baseline.profile,
                    confidence=baseline.confidence,
                    reason=(
                        f"{baseline.reason} AI fallback: "
                        f"{type(exc).__name__}{suffix}."
                    ),
                    source="rules-fallback",
                )

        rec = self.policy.validate(snap, rec, baseline=baseline)

        self.storage.log_snapshot(snap)
        self.storage.log_recommendation(snap.timestamp, rec)

        results = self.optimizer.apply(rec, snap)
        self.storage.log_actions(results)

        _print_snapshot(snap)
        _print_recommendation(rec)

        print("\n=== Actions ===")
        for result in results:
            state = "APPLIED" if result.applied else "NO CHANGE"
            print(f"{state:<10} {result.action}: {result.detail}")

        return snap, rec

    def close(self) -> None:
        if self.ai is not None:
            self.ai.close()
        self.storage.close()


def run_once(config: AppConfig, use_ai: bool) -> None:
    app = PerformanceAI(config, use_ai=use_ai)
    try:
        app.evaluate(use_foundry=use_ai)
    finally:
        app.close()


def run_monitor(config: AppConfig, use_ai: bool) -> None:
    app = PerformanceAI(config, use_ai=use_ai)
    last_ai = 0.0

    print(
        "Monitoring started. "
        f"Advisor Mode={'ON' if config.advisor_mode else 'OFF'}. "
        "Press Ctrl+C to stop."
    )

    try:
        while True:
            now = time.monotonic()
            call_ai = use_ai and (
                last_ai == 0.0
                or now - last_ai >= config.ai_interval_seconds
            )
            app.evaluate(use_foundry=call_ai)
            if call_ai:
                last_ai = now
            time.sleep(max(1, config.telemetry_interval_seconds))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        app.close()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="NPU-aware local performance advisor for Windows Copilot+ PCs."
    )
    parser.add_argument(
        "command",
        choices=["once", "monitor", "diagnose"],
        nargs="?",
        default="once",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to configuration JSON.",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Disable Foundry Local and use deterministic rules only.",
    )
    args = parser.parse_args()

    if args.command == "diagnose":
        run_diagnostics()
        return

    config = AppConfig.load(args.config)
    use_ai = not args.no_ai

    if args.command == "once":
        run_once(config, use_ai)
    else:
        run_monitor(config, use_ai)

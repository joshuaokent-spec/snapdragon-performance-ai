from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import ActionResult, PressurePrediction, Recommendation, TelemetrySnapshot


class Storage:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self._initialize()

    def _initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cpu_percent REAL NOT NULL,
                memory_percent REAL NOT NULL,
                disk_percent REAL NOT NULL,
                battery_percent REAL,
                plugged_in INTEGER,
                foreground_process TEXT,
                power_scheme TEXT,
                npu_percent REAL,
                top_processes_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                workload TEXT NOT NULL,
                profile TEXT NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                source TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                horizon_seconds INTEGER NOT NULL,
                current_memory_percent REAL NOT NULL,
                predicted_memory_percent REAL NOT NULL,
                memory_slope_percent_per_minute REAL NOT NULL,
                risk TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                action TEXT NOT NULL,
                requested TEXT NOT NULL,
                applied INTEGER NOT NULL,
                detail TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def log_snapshot(self, snap: TelemetrySnapshot) -> None:
        self.conn.execute(
            """
            INSERT INTO telemetry (
                timestamp, cpu_percent, memory_percent, disk_percent,
                battery_percent, plugged_in, foreground_process,
                power_scheme, npu_percent, top_processes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snap.timestamp,
                snap.cpu_percent,
                snap.memory_percent,
                snap.disk_percent,
                snap.battery_percent,
                None if snap.plugged_in is None else int(snap.plugged_in),
                snap.foreground_process,
                snap.power_scheme,
                snap.npu_percent,
                json.dumps([vars_for_slots(p) for p in snap.top_processes]),
            ),
        )
        self.conn.commit()

    def log_recommendation(self, timestamp: str, rec: Recommendation) -> None:
        self.conn.execute(
            """
            INSERT INTO recommendations (
                timestamp, workload, profile, confidence, reason, source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                rec.workload,
                rec.profile,
                rec.confidence,
                rec.reason,
                rec.source,
            ),
        )
        self.conn.commit()

    def log_prediction(self, prediction: PressurePrediction | None) -> None:
        if prediction is None:
            return
        self.conn.execute(
            """
            INSERT INTO predictions (
                timestamp, horizon_seconds, current_memory_percent,
                predicted_memory_percent, memory_slope_percent_per_minute,
                risk, confidence, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction.timestamp,
                prediction.horizon_seconds,
                prediction.current_memory_percent,
                prediction.predicted_memory_percent,
                prediction.memory_slope_percent_per_minute,
                prediction.risk,
                prediction.confidence,
                prediction.source,
            ),
        )
        self.conn.commit()

    def log_actions(self, results: list[ActionResult]) -> None:
        if not results:
            return
        self.conn.executemany(
            """
            INSERT INTO actions (action, requested, applied, detail)
            VALUES (?, ?, ?, ?)
            """,
            [
                (r.action, r.requested, int(r.applied), r.detail)
                for r in results
            ],
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def vars_for_slots(obj):
    return {
        name: getattr(obj, name)
        for name in obj.__dataclass_fields__
    }

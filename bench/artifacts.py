from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench import __version__
from bench.config import Scenario
from bench.krpc_client import KRPCConfig
from bench.scoring import ScoreResult
from bench.telemetry import TelemetrySample


class RunArtifacts:
    def __init__(self, run_dir: Path, *, exist_ok: bool = False) -> None:
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=exist_ok)

    @classmethod
    def create(cls, root_dir: str | Path, run_id: str) -> RunArtifacts:
        return cls(Path(root_dir) / run_id)

    @classmethod
    def open(cls, run_dir: str | Path) -> RunArtifacts:
        path = Path(run_dir)
        if not path.is_dir():
            raise FileNotFoundError(f"run directory does not exist: {path}")
        return cls(path, exist_ok=True)

    def write_manifest(
        self,
        scenario: Scenario,
        agent: dict[str, str | None],
        krpc: KRPCConfig | None = None,
    ) -> None:
        manifest = {
            "run_id": self.run_dir.name,
            "created_at": datetime.now(UTC).isoformat(),
            "benchmark_version": scenario.benchmark_version,
            "harness_version": __version__,
            "agent": agent,
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "git_commit": _git_commit(),
                "uv_lock_sha256": _file_sha256(Path("uv.lock")),
            },
            "krpc": asdict(krpc or KRPCConfig.from_env()),
        }
        self.write_json("manifest.json", manifest)

    def copy_scenario(self, scenario: Scenario) -> None:
        if scenario.source_path is None:
            raise ValueError("scenario source path is required for run artifacts")
        shutil.copyfile(scenario.source_path, self.run_dir / "scenario.toml")

    def write_run_config(self, agent: dict[str, str | None], **extra: Any) -> None:
        payload = {"agent": agent, "tool_api_version": "0.0.1", **extra}
        self.write_json("run_config.json", payload)

    def append_event(self, event: dict[str, Any]) -> None:
        self.append_jsonl("events.jsonl", event)

    def append_action(self, action: dict[str, Any]) -> None:
        self.append_jsonl("action_log.jsonl", action)

    def append_telemetry_sample(self, sample: TelemetrySample) -> None:
        self.append_jsonl("telemetry.jsonl", sample.to_dict())

    def write_telemetry(self, samples: list[TelemetrySample]) -> None:
        """Write the canonical trace once.

        Earlier runs wrote both telemetry.jsonl and telemetry.csv, duplicating
        the highest-volume artifact. JSONL is easier to stream during a run and
        retains types, so it is now the sole canonical raw record.
        """
        path = self.run_dir / "telemetry.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for sample in samples:
                handle.write(json.dumps(sample.to_dict(), sort_keys=True) + "\n")

    def write_telemetry_waypoints(
        self,
        samples: list[TelemetrySample],
        *,
        interval_s: float = 10.0,
    ) -> None:
        waypoints = telemetry_waypoints(samples, interval_s=interval_s)
        self.write_json(
            "flight.json",
            {
                "schema_version": 1,
                "interval_s": interval_s,
                # Compact public/visualization trace.  Field names are kept in
                # one place; individual points are positional tuples.
                "columns": ["t", "alt", "apo", "peri", "lat", "lon", "speed", "stage", "fuel", "q"],
                "points": [
                    [
                        round(sample.mission_elapsed_s, 2),
                        round(sample.altitude_m, 1),
                        round(sample.apoapsis_m, 1),
                        round(sample.periapsis_m, 1),
                        None if sample.latitude_deg is None else round(sample.latitude_deg, 5),
                        None if sample.longitude_deg is None else round(sample.longitude_deg, 5),
                        round(sample.orbital_speed_m_s, 1),
                        sample.stage,
                        round(sample.liquid_fuel + sample.oxidizer + sample.solid_fuel, 2),
                        round(sample.dynamic_pressure_pa, 1),
                    ]
                    for sample in waypoints
                ],
            },
        )

    def write_score(self, score: ScoreResult) -> None:
        self.write_json("score.json", score.to_dict())

    def write_summary(self, score: ScoreResult) -> None:
        lines = [
            f"Run: {score.run_id}",
            f"Instance: {score.instance_id}",
            f"Score: {score.score}",
            "",
            "Final orbit:",
        ]
        lines.extend(f"- {name}: {value}" for name, value in score.final_orbit.items())
        lines.extend(["", "Fuel remaining:"])
        lines.extend(f"- {name}: {value}" for name, value in score.fuel_remaining.items())
        lines.extend(["", "Time:"])
        lines.extend(f"- {name}: {value}" for name, value in score.time.items())
        lines.extend(["", "Diagnostics:"])
        lines.extend(f"- {name}: {value}" for name, value in score.diagnostics.items())
        (self.run_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_json(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.run_dir / filename
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def append_jsonl(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.run_dir / filename
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")


def default_run_id(prefix: str | None = None) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{prefix}" if prefix else stamp


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def telemetry_waypoints(
    samples: list[TelemetrySample],
    *,
    interval_s: float = 10.0,
) -> list[TelemetrySample]:
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if not samples:
        return []

    waypoints: list[TelemetrySample] = []
    next_met = samples[0].mission_elapsed_s
    for sample in samples:
        if not waypoints:
            waypoints.append(sample)
            next_met = sample.mission_elapsed_s + interval_s
            continue
        if sample.mission_elapsed_s >= next_met:
            waypoints.append(sample)
            while next_met <= sample.mission_elapsed_s:
                next_met += interval_s
    if waypoints[-1] is not samples[-1]:
        waypoints.append(samples[-1])
    return waypoints

from __future__ import annotations

import csv
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

from kspbench import __version__
from kspbench.config import Scenario
from kspbench.scoring import ScoreResult
from kspbench.telemetry import TELEMETRY_COLUMNS, TelemetrySample


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

    def write_manifest(self, scenario: Scenario, agent: dict[str, str | None]) -> None:
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
            "krpc": asdict(scenario.krpc),
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

    def write_telemetry(self, samples: list[TelemetrySample]) -> None:
        with (self.run_dir / "telemetry.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=TELEMETRY_COLUMNS)
            writer.writeheader()
            for sample in samples:
                writer.writerow(sample.to_dict())

    def write_score(self, score: ScoreResult) -> None:
        self.write_json("score.json", score.to_dict())

    def write_summary(self, score: ScoreResult) -> None:
        lines = [
            f"Run: {score.run_id}",
            f"Instance: {score.instance_id}",
            f"Success: {score.success}",
            f"Score: {score.score}",
            f"Failure reason: {score.failure_reason or 'none'}",
            "",
            "Milestones:",
        ]
        lines.extend(f"- {name}: {value}" for name, value in score.milestones.items())
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

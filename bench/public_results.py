"""Publish the compact, static dataset consumed by the benchmark website."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.scoring import ScoreResult

DEFAULT_PUBLIC_DATA_DIR = Path(__file__).resolve().parents[1] / "web" / "public" / "data"


def publish_run(
    *,
    run_dir: Path,
    score: ScoreResult,
    public_data_dir: Path = DEFAULT_PUBLIC_DATA_DIR,
) -> bool:
    """Publish only an improved result for its model/thinking-level entry."""
    manifest = _read_json(run_dir / "manifest.json")
    agent_process = _read_json(run_dir / "agent_process.json")
    flight = _read_json(run_dir / "flight.json")
    agent = manifest.get("agent", {}) if isinstance(manifest.get("agent"), dict) else {}
    model = str(agent.get("model") or score.agent.get("model") or "unknown-model")
    thinking_level = agent.get("thinking_level") or score.agent.get("thinking_level")
    candidate = _public_summary(score, manifest, agent_process.get("usage"), model, thinking_level)
    index_path = public_data_dir / "index.json"
    index = _read_index(index_path)

    matching_index = next(
        (position for position, existing in enumerate(index["runs"])
         if _benchmark_key(existing) == _benchmark_key(candidate)),
        None,
    )
    previous_run_id = ""
    if matching_index is not None:
        existing = index["runs"][matching_index]
        if float(existing.get("score", 0.0)) > score.score:
            return False
        previous_run_id = str(existing.get("runId", ""))
        index["runs"][matching_index] = candidate
    else:
        index["runs"].append(candidate)

    public_data_dir.mkdir(parents=True, exist_ok=True)
    (public_data_dir / "runs").mkdir(exist_ok=True)
    (public_data_dir / "flights").mkdir(exist_ok=True)
    _write_json(
        public_data_dir / "runs" / f"{score.run_id}.json",
        {
            "manifest": manifest,
            "score": score.to_dict(),
            "usage": agent_process.get("usage"),
            "flightUrl": candidate["flightUrl"],
        },
    )
    _write_json(public_data_dir / "flights" / f"{score.run_id}.json", flight)

    if previous_run_id and previous_run_id != score.run_id:
        (public_data_dir / "runs" / f"{previous_run_id}.json").unlink(missing_ok=True)
        (public_data_dir / "flights" / f"{previous_run_id}.json").unlink(missing_ok=True)

    index["generatedAt"] = datetime.now(UTC).isoformat()
    index["runs"].sort(key=lambda item: float(item["score"]), reverse=True)
    _write_json(index_path, index)
    return True


def _public_summary(
    score: ScoreResult,
    manifest: dict[str, Any],
    usage: Any,
    model: str,
    thinking_level: object,
) -> dict[str, Any]:
    return {
        "runId": score.run_id,
        "createdAt": manifest.get("created_at"),
        "model": model,
        "thinkingLevel": thinking_level if isinstance(thinking_level, str) else None,
        "adapter": score.agent.get("adapter"),
        "score": score.score,
        "benchmarkVersion": score.benchmark_version,
        "harnessVersion": score.harness_version,
        "instanceId": score.instance_id,
        "finalOrbit": score.final_orbit,
        "fuelRemaining": score.fuel_remaining,
        "remainingDeltaVMs": score.remaining_delta_v_m_s,
        "time": score.time,
        "diagnostics": score.diagnostics,
        "usage": usage if isinstance(usage, dict) else None,
        "flightUrl": f"/data/flights/{score.run_id}.json",
        "detailUrl": f"/data/runs/{score.run_id}.json",
    }


def _benchmark_key(run: dict[str, Any]) -> tuple[str, str]:
    return (
        str(run.get("model", "")),
        str(run.get("thinkingLevel") or ""),
    )


def _read_index(path: Path) -> dict[str, Any]:
    loaded = _read_json(path)
    runs = loaded.get("runs")
    return {
        "generatedAt": str(loaded.get("generatedAt", "")),
        "sourceRoot": "benchmark-runs",
        "runs": runs if isinstance(runs, list) else [],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

from __future__ import annotations

import json
from pathlib import Path

from bench.public_results import publish_run
from bench.scoring import ScoreResult


def _score(run_id: str, score: float) -> ScoreResult:
    return ScoreResult(
        run_id=run_id,
        instance_id="kerbin_orbit_80km_fixed_rocket_v0",
        benchmark_version="0.1.0",
        harness_version="test",
        agent={
            "name": "ksp",
            "model": "openai/test",
            "thinking_level": "high",
            "adapter": "test",
        },
        score=score,
        final_orbit={"body": "Kerbin"},
        fuel_remaining={"liquid_fuel": 1.0},
        remaining_delta_v_m_s=710.0,
        time={"mission_elapsed_s": 1.0},
        diagnostics={"stable_orbit": True},
    )


def _run_dir(tmp_path: Path, run_id: str) -> Path:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps({"created_at": "2026-07-10T00:00:00Z", "agent": _score(run_id, 0).agent}),
        encoding="utf-8",
    )
    (run_dir / "agent_process.json").write_text(
        json.dumps({"usage": {"total_tokens": 42}}), encoding="utf-8"
    )
    (run_dir / "flight.json").write_text(
        json.dumps({"schema_version": 1, "columns": ["t", "alt"], "points": [[0, 0]]}),
        encoding="utf-8",
    )
    return run_dir


def test_publishes_only_the_best_model_and_thinking_level_run(tmp_path: Path) -> None:
    public_data_dir = tmp_path / "public-data"
    first_dir = _run_dir(tmp_path, "first")

    assert publish_run(
        run_dir=first_dir,
        score=_score("first", 50),
        public_data_dir=public_data_dir,
    )
    index = json.loads((public_data_dir / "index.json").read_text(encoding="utf-8"))
    assert index["runs"][0]["runId"] == "first"
    assert index["benchmarkVersion"] == "0.1.0"
    assert index["runs"][0]["flightUrl"] == "/data/flights/first.json"
    assert (public_data_dir / "runs" / "first.json").exists()
    assert (public_data_dir / "flights" / "first.json").exists()

    worse_dir = _run_dir(tmp_path, "worse")
    assert not publish_run(
        run_dir=worse_dir,
        score=_score("worse", 49),
        public_data_dir=public_data_dir,
    )
    assert not (public_data_dir / "runs" / "worse.json").exists()

    better_dir = _run_dir(tmp_path, "better")
    assert publish_run(
        run_dir=better_dir,
        score=_score("better", 51),
        public_data_dir=public_data_dir,
    )
    index = json.loads((public_data_dir / "index.json").read_text(encoding="utf-8"))
    assert index["runs"][0]["runId"] == "better"
    assert not (public_data_dir / "runs" / "first.json").exists()
    assert not (public_data_dir / "flights" / "first.json").exists()


def test_does_not_publish_invalid_run(tmp_path: Path) -> None:
    public_data_dir = tmp_path / "public-data"
    run_dir = _run_dir(tmp_path, "invalid")
    score = _score("invalid", 100)
    score.diagnostics["valid_run"] = False

    assert not publish_run(run_dir=run_dir, score=score, public_data_dir=public_data_dir)
    assert not (public_data_dir / "index.json").exists()


def test_drops_results_from_an_older_benchmark_version(tmp_path: Path) -> None:
    public_data_dir = tmp_path / "public-data"
    public_data_dir.mkdir()
    (public_data_dir / "index.json").write_text(
        json.dumps({"benchmarkVersion": "0.0.4", "runs": [{"benchmarkVersion": "0.0.4"}]}),
        encoding="utf-8",
    )
    run_dir = _run_dir(tmp_path, "current")

    assert publish_run(
        run_dir=run_dir,
        score=_score("current", 50),
        public_data_dir=public_data_dir,
    )
    index = json.loads((public_data_dir / "index.json").read_text(encoding="utf-8"))
    assert index["benchmarkVersion"] == "0.1.0"
    assert [run["runId"] for run in index["runs"]] == ["current"]

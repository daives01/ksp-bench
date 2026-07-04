from __future__ import annotations

import argparse
import json
import shutil

import pytest

from kspbench.cli import _score, build_parser


def test_only_opencode_execution_command_is_registered() -> None:
    parser = build_parser()

    assert parser.parse_args(["run", "scenario.toml"]).scenario == "scenario.toml"
    with pytest.raises(SystemExit):
        parser.parse_args(["live", "scenario.toml"])
    with pytest.raises(SystemExit):
        parser.parse_args(["live-external", "scenario.toml"])


def test_score_handles_missing_telemetry_csv(tmp_path) -> None:
    run_dir = tmp_path / "incomplete-run"
    run_dir.mkdir()
    shutil.copyfile("scenarios/kerbin_orbit_80km.toml", run_dir / "scenario.toml")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "agent": {
                    "name": "opencode",
                    "model": "test-model",
                    "adapter": "opencode",
                }
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "action_log.jsonl").write_text(
        json.dumps({"allowed": True, "ok": False}) + "\n",
        encoding="utf-8",
    )

    exit_code = _score(argparse.Namespace(run_dir=str(run_dir)))

    assert exit_code == 0
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    assert score["failure_reason"] == "no_telemetry"
    assert score["diagnostics"]["invalid_actions"] == 1
    assert (run_dir / "telemetry.csv").exists()
    assert (run_dir / "telemetry_waypoints.json").exists()

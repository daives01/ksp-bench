from __future__ import annotations

import argparse
import json
import shutil

import pytest

from bench.cli import _batch, _has_run_terminated, _run_artifacts_root, _score, build_parser


def test_only_opencode_execution_command_is_registered() -> None:
    parser = build_parser()

    assert parser.parse_args(["run", "scenario.toml"]).scenario == "scenario.toml"
    with pytest.raises(SystemExit):
        parser.parse_args(["live", "scenario.toml"])
    with pytest.raises(SystemExit):
        parser.parse_args(["live-external", "scenario.toml"])


def test_run_command_exposes_simplified_timeout_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "run",
            "scenario.toml",
            "--execution-timeout",
            "5",
            "--task-timeout",
            "30",
            "--max-sleep",
            "60",
        ]
    )

    assert args.execution_timeout == 5
    assert args.task_timeout == 30
    assert args.max_sleep == 60
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "scenario.toml", "--warp-threshold", "10"])


def test_batch_command_accepts_repeated_models_and_model_file(tmp_path) -> None:
    models_file = tmp_path / "models.toml"
    models_file.write_text('models = ["openai/gpt-5.4", "anthropic/claude"]\n', encoding="utf-8")
    parser = build_parser()

    args = parser.parse_args(
        [
            "batch",
            "scenario.toml",
            "--model",
            "openai/gpt-5.3",
            "--models-file",
            str(models_file),
            "--repeat",
            "2",
        ]
    )

    assert args.model == ["openai/gpt-5.3"]
    assert args.models_file == str(models_file)
    assert args.repeat == 2


def test_batch_resets_around_each_run(monkeypatch) -> None:
    calls = []

    def fake_reset(_scenario):
        calls.append("reset")
        return True

    def fake_run(args):
        calls.append(("run", args.model, args.run_id, args.thinking_level))
        return 0

    monkeypatch.setattr("bench.cli._reset_launchpad", fake_reset)
    monkeypatch.setattr("bench.cli._run", fake_run)

    exit_code = _batch(
        argparse.Namespace(
            scenario="scenarios/kerbin_orbit_80km.toml",
            model=["openai/gpt-5.3", "openai/gpt-5.4"],
            thinking_level="high",
            models_file=None,
            repeat=1,
            no_reset=False,
            executable=None,
            agent_arg=[],
            agent_timeout=None,
            execution_timeout=15.0,
            task_timeout=180.0,
            max_sleep=240.0,
            poll_interval=0.5,
            telemetry_waypoint_interval=10.0,
            no_stream_agent=False,
        )
    )

    assert exit_code == 0
    assert calls[0] == "reset"
    assert calls[2] == "reset"
    assert calls[3] == "reset"
    assert calls[5] == "reset"
    assert [call[1] for call in calls if isinstance(call, tuple)] == [
        "openai/gpt-5.3",
        "openai/gpt-5.4",
    ]
    assert "openai_gpt_5" not in calls[1][2]
    assert [call[0] for call in calls if isinstance(call, tuple)] == ["run", "run"]
    assert [call[3] for call in calls if isinstance(call, tuple)] == ["high", "high"]


def test_model_runs_are_grouped_by_safe_model_directory() -> None:
    assert _run_artifacts_root("openai/gpt-5.4").as_posix() == "runs/openai_gpt_5_4"
    assert (
        _run_artifacts_root("openai/gpt-5.4", "high").as_posix()
        == "runs/openai_gpt_5_4/high"
    )
    assert _run_artifacts_root(None).as_posix() == "runs"


def test_run_terminated_event_is_detected_for_finalization(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    assert _has_run_terminated(run_dir) is False
    (run_dir / "events.jsonl").write_text(
        json.dumps({"type": "run_terminated", "reason": "dead_stick"}) + "\n",
        encoding="utf-8",
    )

    assert _has_run_terminated(run_dir) is True


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
    assert "success" not in score
    assert "failure_reason" not in score
    assert score["final_orbit"]["situation"] == "no_telemetry"
    assert score["diagnostics"]["invalid_actions"] == 1
    assert (run_dir / "telemetry.csv").exists()
    assert (run_dir / "telemetry_waypoints.json").exists()

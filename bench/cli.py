from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from bench import __version__
from bench.agent_adapters import (
    PROJECT_ROOT,
    REFERENCE_DIR,
    ExternalAgentResult,
    OpenCodeAgentAdapter,
    extract_usage,
    prepare_opencode_workspace,
)
from bench.artifacts import RunArtifacts, default_run_id
from bench.config import Scenario, load_scenario
from bench.krpc_client import (
    KRPCConfig,
    KRPCController,
    check_krpc_package,
    check_krpc_reachable,
)
from bench.scoring import score_trace
from bench.telemetry import TelemetrySample

RUNS_DIR = Path("runs")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kspbench")
    parser.add_argument("--version", action="version", version=f"kspbench {__version__}")
    subparsers = parser.add_subparsers(required=True)

    doctor = subparsers.add_parser(
        "doctor",
        help="check local harness and optional KSP connectivity",
    )
    doctor.add_argument("scenario", nargs="?", default="scenarios/kerbin_orbit_80km.toml")
    doctor.set_defaults(func=_doctor)

    prepare_agent = subparsers.add_parser(
        "prepare-agent",
        help="prepare the reusable OpenCode KSP agent reference tree",
    )
    prepare_agent.add_argument(
        "--krpc-repo",
        help="path to an upstream krpc/krpc checkout; defaults to KSPBENCH_KRPC_REPO or /tmp",
    )
    prepare_agent.set_defaults(func=_prepare_agent)

    agent = subparsers.add_parser(
        "agent",
        help="open the reusable OpenCode KSP agent against the live KSP MCP server",
    )
    agent.add_argument("scenario", nargs="?", default="scenarios/kerbin_orbit_80km.toml")
    agent.add_argument("--model", help="OpenCode model name, for example openai/gpt-5.4")
    agent.add_argument(
        "--executable",
        help="OpenCode executable path; defaults to opencode",
    )
    agent.add_argument(
        "--agent-arg",
        action="append",
        default=[],
        help="extra argument to pass to opencode; repeat for multiple args",
    )
    agent.add_argument(
        "--prompt",
        help="optional initial prompt for the OpenCode TUI",
    )
    agent.add_argument("--run-id")
    agent.add_argument(
        "--execution-timeout",
        type=float,
        default=15.0,
        help="default max wall-clock seconds for each ksp_execute_python call",
    )
    agent.add_argument(
        "--task-timeout",
        type=float,
        default=180.0,
        help="default max wall-clock seconds for the background control task",
    )
    agent.add_argument(
        "--max-sleep",
        type=float,
        default=240.0,
        help="max seconds allowed for ksp_execute_python sleep/wait helpers",
    )
    agent.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between telemetry samples during sleep/wait helpers",
    )
    agent.set_defaults(func=_agent)

    run = subparsers.add_parser(
        "run",
        help="run a live benchmark with the reusable OpenCode KSP agent",
    )
    run.add_argument("scenario")
    run.add_argument("--model", help="OpenCode model name, for example openai/gpt-5.4")
    run.add_argument(
        "--executable",
        help="OpenCode executable path; defaults to opencode",
    )
    run.add_argument(
        "--agent-arg",
        action="append",
        default=[],
        help="extra argument to pass to opencode run; repeat for multiple args",
    )
    run.add_argument("--run-id")
    run.add_argument(
        "--agent-timeout",
        type=float,
        help="max wall-clock seconds for the OpenCode process",
    )
    run.add_argument(
        "--execution-timeout",
        type=float,
        default=15.0,
        help="default max wall-clock seconds for each ksp_execute_python call",
    )
    run.add_argument(
        "--task-timeout",
        type=float,
        default=180.0,
        help="default max wall-clock seconds for the background control task",
    )
    run.add_argument(
        "--max-sleep",
        type=float,
        default=240.0,
        help="max seconds allowed for ksp_execute_python sleep/wait helpers",
    )
    run.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between telemetry samples during sleep/wait helpers",
    )
    run.add_argument(
        "--telemetry-waypoint-interval",
        type=float,
        default=10.0,
        help="mission seconds between downsampled telemetry waypoints",
    )
    run.add_argument(
        "--no-stream-agent",
        action="store_true",
        help="capture OpenCode output without streaming it live",
    )
    run.set_defaults(func=_run)

    batch = subparsers.add_parser(
        "batch",
        help="queue multiple live benchmark runs across one or more OpenCode models",
    )
    batch.add_argument("scenario")
    batch.add_argument(
        "--model",
        action="append",
        default=[],
        help="OpenCode model name to run; repeat for multiple models",
    )
    batch.add_argument(
        "--models-file",
        help="TOML file with a models = [...] list",
    )
    batch.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="number of runs per model",
    )
    batch.add_argument(
        "--no-reset",
        action="store_true",
        help="do not revert to launch before and after each run",
    )
    batch.add_argument(
        "--executable",
        help="OpenCode executable path; defaults to opencode",
    )
    batch.add_argument(
        "--agent-arg",
        action="append",
        default=[],
        help="extra argument to pass to opencode run; repeat for multiple args",
    )
    batch.add_argument(
        "--agent-timeout",
        type=float,
        help="max wall-clock seconds for each OpenCode process",
    )
    batch.add_argument(
        "--execution-timeout",
        type=float,
        default=15.0,
        help="default max wall-clock seconds for each ksp_execute_python call",
    )
    batch.add_argument(
        "--task-timeout",
        type=float,
        default=180.0,
        help="default max wall-clock seconds for the background control task",
    )
    batch.add_argument(
        "--max-sleep",
        type=float,
        default=240.0,
        help="max seconds allowed for ksp_execute_python sleep/wait helpers",
    )
    batch.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between telemetry samples during sleep/wait helpers",
    )
    batch.add_argument(
        "--telemetry-waypoint-interval",
        type=float,
        default=10.0,
        help="mission seconds between downsampled telemetry waypoints",
    )
    batch.add_argument(
        "--no-stream-agent",
        action="store_true",
        help="capture OpenCode output without streaming it live",
    )
    batch.set_defaults(func=_batch)

    score = subparsers.add_parser("score", help="score an existing run artifact directory")
    score.add_argument("run_dir")
    score.set_defaults(func=_score)

    summarize = subparsers.add_parser(
        "summarize",
        help="summarize score.json files under a directory",
    )
    summarize.add_argument("root")
    summarize.set_defaults(func=_summarize)

    return parser


def _doctor(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    checks = [
        ("scenario", True, f"loaded {scenario.instance_id}"),
        ("python", sys.version_info >= (3, 12), sys.version.split()[0]),
        _doctor_tuple(check_krpc_package()),
        _doctor_tuple(check_krpc_reachable(KRPCConfig.from_env())),
    ]
    for name, ok, detail in checks:
        marker = "ok" if ok else "fail"
        print(f"{marker:4} {name}: {detail}")
    required_ok = checks[0][1] and checks[1][1]
    return 0 if required_ok else 1


def _prepare_agent(args: argparse.Namespace) -> int:
    krpc_repo = Path(args.krpc_repo) if args.krpc_repo else None
    counts = prepare_opencode_workspace(PROJECT_ROOT, krpc_repo=krpc_repo)
    reference_root = PROJECT_ROOT / REFERENCE_DIR
    print(f"Prepared OpenCode KSP agent reference at {reference_root}")
    if counts:
        for name, count in sorted(counts.items()):
            print(f"ok   {name}: {count} files")
    else:
        print("warn no kRPC source copied; install krpc or pass --krpc-repo")
    return 0


def _agent(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    run_id = args.run_id or default_run_id("opencode_agent")
    artifacts = RunArtifacts.create(RUNS_DIR, run_id)
    agent = {
        "name": "ksp",
        "model": args.model,
        "adapter": "opencode_tui_ksp_agent",
    }
    artifacts.write_manifest(scenario, agent)
    artifacts.copy_scenario(scenario)
    artifacts.write_run_config(
        agent,
        tool_api_version="1.0.0",
        python_timeout_s=args.execution_timeout,
        task_timeout_s=args.task_timeout,
        max_wait_s=args.max_sleep,
        poll_interval_s=args.poll_interval,
        opencode_agent="ksp",
        opencode_mode="tui",
    )
    artifacts.append_event({"type": "agent_started", "mode": "opencode_tui"})

    prepare_opencode_workspace(PROJECT_ROOT)
    executable = args.executable or "opencode"
    command = [executable, str(PROJECT_ROOT), "--agent", "ksp", "--auto"]
    if args.model:
        command.extend(["--model", args.model])
    if args.prompt:
        command.extend(["--prompt", args.prompt])
    command.extend(args.agent_arg)

    env = dict(os.environ)
    env["KSPBENCH_SCENARIO"] = (
        str(scenario.source_path.resolve()) if scenario.source_path else args.scenario
    )
    env["KSPBENCH_REFERENCE_ROOT"] = str((PROJECT_ROOT / REFERENCE_DIR).resolve())
    env["KSPBENCH_RUN_DIR"] = str(artifacts.run_dir.resolve())
    env["KSPBENCH_EXECUTION_TIMEOUT"] = str(args.execution_timeout)
    env["KSPBENCH_TASK_TIMEOUT"] = str(args.task_timeout)
    env["KSPBENCH_MAX_SLEEP"] = str(args.max_sleep)
    env["KSPBENCH_POLL_INTERVAL"] = str(args.poll_interval)
    env.setdefault("KSPBENCH_PYTHON", sys.executable)
    print(f"Starting OpenCode KSP agent. Artifacts: {artifacts.run_dir}")
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)

    artifacts.write_json(
        "agent_process.json",
        {
            "command": command,
            "returncode": completed.returncode,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "usage": None,
        },
    )
    telemetry = _read_telemetry_artifact(artifacts.run_dir)
    _append_final_telemetry_sample(artifacts, scenario, telemetry)
    artifacts.write_telemetry(telemetry)
    artifacts.write_telemetry_waypoints(telemetry)
    artifacts.append_event({"type": "agent_finished", "exit_code": completed.returncode})
    print(f"Wrote interactive agent artifacts to {artifacts.run_dir}")
    return completed.returncode


def _run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    adapter = OpenCodeAgentAdapter(
        model=args.model,
        executable=args.executable,
        extra_args=args.agent_arg,
    )
    run_id = args.run_id or default_run_id("opencode_live")
    artifacts = RunArtifacts.create(RUNS_DIR, run_id)
    agent = adapter.agent_metadata

    artifacts.write_manifest(scenario, agent)
    artifacts.copy_scenario(scenario)
    artifacts.write_run_config(
        agent,
        tool_api_version="0.5.0",
        python_timeout_s=args.execution_timeout,
        task_timeout_s=args.task_timeout,
        max_wait_s=args.max_sleep,
        poll_interval_s=args.poll_interval,
        telemetry_waypoint_interval_s=args.telemetry_waypoint_interval,
        agent_timeout_s=args.agent_timeout or scenario.timeout_s,
        opencode_permissions="agent_scoped_virtual_bash_no_edits",
        opencode_agent="ksp",
    )
    artifacts.append_event({"type": "run_started", "mode": "opencode"})

    exit_code = 0
    result: ExternalAgentResult | None = None

    try:
        result = adapter.run(
            scenario=scenario,
            run_dir=artifacts.run_dir,
            timeout_s=args.agent_timeout or scenario.timeout_s,
            execution_timeout_s=args.execution_timeout,
            task_timeout_s=args.task_timeout,
            max_sleep_s=args.max_sleep,
            poll_interval_s=args.poll_interval,
            stream_output=not args.no_stream_agent,
        )
        if result.returncode != 0:
            artifacts.append_event(
                {
                    "type": "run_failed",
                    "reason": "agent_process_failed",
                    "returncode": result.returncode,
                    "timed_out": result.timed_out,
                }
            )
            exit_code = 3
    except Exception as exc:
        artifacts.append_event({"type": "run_failed", "reason": "agent_error", "detail": str(exc)})
        print(f"OpenCode agent failed: {exc}")
        exit_code = 3

    if result is not None:
        artifacts.write_json(
            "agent_process.json",
            {
                "command": result.command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": result.timed_out,
                "usage": extract_usage(result.stdout, result.stderr),
            },
        )
    else:
        artifacts.write_json(
            "agent_process.json",
            {
                "command": [],
                "returncode": None,
                "stdout": "",
                "stderr": "",
                "timed_out": False,
                "usage": None,
            },
        )

    telemetry = _read_telemetry_artifact(artifacts.run_dir)
    _append_final_telemetry_sample(artifacts, scenario, telemetry)
    actions = _read_jsonl(artifacts.run_dir / "action_log.jsonl")
    invalid_actions = sum(
        1
        for action in actions
        if not action.get("allowed", True) or action.get("ok") is False
    )

    score = _finalize_run(
        artifacts=artifacts,
        run_id=run_id,
        scenario=scenario,
        agent=agent,
        telemetry=telemetry,
        invalid_actions=invalid_actions,
        action_count=len(actions),
        exit_code=exit_code,
        telemetry_waypoint_interval=args.telemetry_waypoint_interval,
    )
    print(f"Wrote run artifacts to {artifacts.run_dir}")
    print(f"success={score.success} score={score.score} failure_reason={score.failure_reason}")
    return exit_code


def _batch(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    models = _batch_models(args)
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1")
    if not models:
        raise ValueError("provide at least one --model or a --models-file with models = [...]")

    runs: list[tuple[str, int, int]] = []
    for model in models:
        for repeat_index in range(1, args.repeat + 1):
            runs.append((model, repeat_index, args.repeat))

    exit_code = 0
    for index, (model, repeat_index, repeat_count) in enumerate(runs, start=1):
        print(
            f"== Run {index}/{len(runs)} model={model} repeat={repeat_index}/{repeat_count} =="
        )
        if not args.no_reset and not _reset_launchpad(scenario):
            return 2

        run_args = argparse.Namespace(
            scenario=args.scenario,
            model=model,
            executable=args.executable,
            agent_arg=args.agent_arg,
            run_id=default_run_id(_run_id_prefix(model, repeat_index)),
            agent_timeout=args.agent_timeout,
            execution_timeout=args.execution_timeout,
            task_timeout=args.task_timeout,
            max_sleep=args.max_sleep,
            poll_interval=args.poll_interval,
            telemetry_waypoint_interval=args.telemetry_waypoint_interval,
            no_stream_agent=args.no_stream_agent,
        )
        exit_code = max(exit_code, _run(run_args))

        if not args.no_reset and not _reset_launchpad(scenario):
            return max(exit_code, 2)

    return exit_code


def _batch_models(args: argparse.Namespace) -> list[str]:
    models = list(args.model)
    if args.models_file:
        with Path(args.models_file).open("rb") as handle:
            data = tomllib.load(handle)
        file_models = data.get("models")
        if not isinstance(file_models, list) or not all(
            isinstance(model, str) and model for model in file_models
        ):
            raise TypeError("--models-file must contain models = [\"provider/model\", ...]")
        models.extend(file_models)
    return models


def _reset_launchpad(scenario: Scenario) -> bool:
    try:
        controller = KRPCController.connect(scenario)
        controller.prepare_for_launchpad_run()
    except Exception as exc:
        print(f"Could not reset KSP to launchpad: {exc}")
        return False
    return True


def _run_id_prefix(model: str, repeat_index: int) -> str:
    safe_model = "".join(char if char.isalnum() else "_" for char in model).strip("_")
    return f"opencode_live_{safe_model}_r{repeat_index}"


def _finalize_run(
    *,
    artifacts: RunArtifacts,
    run_id: str,
    scenario: Scenario,
    agent: dict[str, str | None],
    telemetry: list[TelemetrySample],
    invalid_actions: int,
    action_count: int,
    exit_code: int,
    telemetry_waypoint_interval: float,
):
    artifacts.write_telemetry(telemetry)
    artifacts.write_telemetry_waypoints(
        telemetry,
        interval_s=telemetry_waypoint_interval,
    )
    score = score_trace(
        run_id=run_id,
        scenario=scenario,
        telemetry=telemetry,
        agent=agent,
        harness_version=__version__,
        invalid_actions=invalid_actions,
        action_count=action_count,
    )
    artifacts.write_score(score)
    artifacts.write_summary(score)
    artifacts.append_event(
        {
            "type": "run_finished",
            "success": score.success,
            "score": score.score,
            "exit_code": exit_code,
        }
    )
    return score


def _score(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    scenario = load_scenario(run_dir / "scenario.toml")
    telemetry_path = run_dir / "telemetry.csv"
    telemetry = _read_telemetry(telemetry_path) if telemetry_path.exists() else []
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    actions = _read_jsonl(run_dir / "action_log.jsonl")
    invalid_actions = sum(
        1
        for action in actions
        if not action.get("allowed", True) or action.get("ok") is False
    )
    result = score_trace(
        run_id=run_dir.name,
        scenario=scenario,
        telemetry=telemetry,
        agent=manifest["agent"],
        harness_version=__version__,
        invalid_actions=invalid_actions,
        action_count=len(actions),
    )
    artifacts = RunArtifacts.open(run_dir)
    if not telemetry_path.exists():
        artifacts.append_event(
            {
                "type": "telemetry_read_missing",
                "path": str(telemetry_path),
            }
        )
        artifacts.write_telemetry([])
        artifacts.write_telemetry_waypoints([])
    artifacts.write_score(result)
    artifacts.write_summary(result)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


def _summarize(args: argparse.Namespace) -> int:
    root = Path(args.root)
    scores = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("**/score.json"))
        if path.is_file()
    ]
    if not scores:
        print("No score.json files found.")
        return 1

    successes = sum(1 for score in scores if score["success"])
    mean_score = sum(float(score["score"]) for score in scores) / len(scores)
    failure_reasons: dict[str, int] = {}
    for score in scores:
        reason = score.get("failure_reason") or "success"
        failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    aggregate = {
        "runs": len(scores),
        "pass_rate": successes / len(scores),
        "mean_score": round(mean_score, 3),
        "failure_reasons": failure_reasons,
    }
    print(json.dumps(aggregate, indent=2, sort_keys=True))
    return 0


def _read_telemetry(path: Path) -> list[TelemetrySample]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [TelemetrySample.from_mapping(_coerce_row(row)) for row in reader]


def _read_telemetry_artifact(run_dir: Path) -> list[TelemetrySample]:
    jsonl = run_dir / "telemetry.jsonl"
    if jsonl.exists():
        return [
            TelemetrySample.from_mapping(json.loads(line))
            for line in jsonl.read_text(encoding="utf-8").splitlines()
            if line
        ]
    csv_path = run_dir / "telemetry.csv"
    return _read_telemetry(csv_path) if csv_path.exists() else []


def _append_final_telemetry_sample(
    artifacts: RunArtifacts,
    scenario: Scenario,
    telemetry: list[TelemetrySample],
) -> None:
    try:
        controller = KRPCController.connect(scenario)
        sample = controller.read_telemetry()
        controller.close()
    except Exception as exc:
        artifacts.append_event({"type": "telemetry_read_failed", "error": str(exc)})
        return
    telemetry.append(sample)
    artifacts.append_telemetry_sample(sample)


def _coerce_row(row: dict[str, str]) -> dict[str, object]:
    bool_fields = {"controllable", "intact"}
    str_fields = {"situation", "body"}
    result: dict[str, object] = {}
    for key, value in row.items():
        if key in bool_fields:
            result[key] = value == "True"
        elif key in str_fields:
            result[key] = value
        elif key == "stage":
            result[key] = int(value)
        else:
            result[key] = float(value)
    return result


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _doctor_tuple(check: object) -> tuple[str, bool, str]:
    return (check.name, check.ok, check.detail)  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(main())

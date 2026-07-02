from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from kspbench import __version__
from kspbench.artifacts import RunArtifacts, default_run_id
from kspbench.config import Scenario, load_scenario
from kspbench.krpc_client import KRPCController, check_krpc_package, check_krpc_reachable
from kspbench.scoring import score_trace
from kspbench.sdk import MissionContext
from kspbench.telemetry import TelemetrySample


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
    doctor.add_argument("scenario", nargs="?", default="scenarios/kerbin_orbit_80km.yaml")
    doctor.set_defaults(func=_doctor)

    run = subparsers.add_parser("run", help="run a scenario with a local Python baseline agent")
    run.add_argument("scenario")
    run.add_argument("--agent", required=True, help="path to a local Python agent module")
    run.add_argument("--run-id")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="use fake telemetry instead of live KSP",
    )
    run.set_defaults(func=_run)

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
        _doctor_tuple(check_krpc_reachable(scenario.krpc)),
    ]
    for name, ok, detail in checks:
        marker = "ok" if ok else "fail"
        print(f"{marker:4} {name}: {detail}")
    required_ok = checks[0][1] and checks[1][1]
    return 0 if required_ok else 1


def _run(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    agent_path = Path(args.agent)
    run_id = args.run_id or default_run_id(agent_path.stem)
    agent = {"name": agent_path.stem, "model": None, "adapter": "local_python"}
    artifacts = RunArtifacts.create(scenario.artifacts.root_dir, run_id)

    artifacts.write_manifest(scenario, agent)
    artifacts.copy_scenario(scenario)
    artifacts.write_run_config(agent)
    artifacts.append_event({"type": "run_started", "dry_run": args.dry_run})

    if args.dry_run:
        context = MissionContext(scenario=scenario)
        for sample in _fake_ascent_telemetry(scenario):
            context.record_telemetry(sample)
    else:
        try:
            controller = KRPCController.connect(scenario)
        except Exception as exc:
            artifacts.append_event(
                {"type": "run_failed", "reason": "no_connection", "detail": str(exc)}
            )
            print(f"Could not start live kRPC run: {exc}")
            return 2
        context = MissionContext(
            scenario=scenario,
            action_executor=controller.apply_action,
            telemetry_provider=controller.read_telemetry,
        )
        context.record_telemetry(controller.read_telemetry())

    module = _load_agent(agent_path)
    if not hasattr(module, "run"):
        raise AttributeError(f"{agent_path} must define run(context)")
    module.run(context)

    for action in context.actions:
        artifacts.append_action(action)
    artifacts.write_telemetry(context.telemetry)
    result = score_trace(
        run_id=run_id,
        scenario=scenario,
        telemetry=context.telemetry,
        agent=agent,
        harness_version=__version__,
        invalid_actions=context.invalid_actions,
        action_count=len(context.actions),
    )
    artifacts.write_score(result)
    artifacts.write_summary(result)
    artifacts.append_event(
        {"type": "run_finished", "success": result.success, "score": result.score}
    )
    print(f"Wrote run artifacts to {artifacts.run_dir}")
    print(f"success={result.success} score={result.score} failure_reason={result.failure_reason}")
    return 0


def _score(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    scenario = load_scenario(run_dir / "scenario.yaml")
    telemetry = _read_telemetry(run_dir / "telemetry.csv")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    actions = _read_jsonl(run_dir / "action_log.jsonl")
    invalid_actions = sum(1 for action in actions if not action.get("allowed", True))
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


def _load_agent(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load agent at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_ascent_telemetry(scenario: Scenario) -> list[TelemetrySample]:
    return [
        TelemetrySample(
            mission_elapsed_s=0.0,
            altitude_m=90.0,
            surface_altitude_m=0.0,
            apoapsis_m=0.0,
            periapsis_m=-600000.0,
            surface_speed_m_s=0.0,
            orbital_speed_m_s=174.0,
            vertical_speed_m_s=0.0,
            pitch_deg=90.0,
            heading_deg=90.0,
            roll_deg=0.0,
            stage=0,
            liquid_fuel=1000.0,
            oxidizer=1220.0,
            solid_fuel=300.0,
            dynamic_pressure_pa=0.0,
            situation="pre_launch",
            body=scenario.body,
            controllable=True,
            intact=True,
        ),
        TelemetrySample(
            mission_elapsed_s=75.0,
            altitude_m=12000.0,
            surface_altitude_m=11910.0,
            apoapsis_m=45000.0,
            periapsis_m=-590000.0,
            surface_speed_m_s=620.0,
            orbital_speed_m_s=760.0,
            vertical_speed_m_s=340.0,
            pitch_deg=55.0,
            heading_deg=90.0,
            roll_deg=0.0,
            stage=1,
            liquid_fuel=680.0,
            oxidizer=820.0,
            solid_fuel=0.0,
            dynamic_pressure_pa=18000.0,
            situation="flying",
            body=scenario.body,
            controllable=True,
            intact=True,
        ),
        TelemetrySample(
            mission_elapsed_s=260.0,
            altitude_m=76000.0,
            surface_altitude_m=75910.0,
            apoapsis_m=82000.0,
            periapsis_m=71000.0,
            surface_speed_m_s=2100.0,
            orbital_speed_m_s=2260.0,
            vertical_speed_m_s=4.0,
            pitch_deg=0.0,
            heading_deg=90.0,
            roll_deg=0.0,
            stage=2,
            liquid_fuel=120.0,
            oxidizer=145.0,
            solid_fuel=0.0,
            dynamic_pressure_pa=0.0,
            situation="orbiting",
            body=scenario.body,
            controllable=True,
            intact=True,
        ),
    ]


def _read_telemetry(path: Path) -> list[TelemetrySample]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [TelemetrySample.from_mapping(_coerce_row(row)) for row in reader]


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

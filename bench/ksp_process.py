from __future__ import annotations

import contextlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.artifacts import RunArtifacts
from bench.config import Scenario, load_scenario
from bench.krpc_client import KRPCController
from bench.live import LiveKRPCTools


def load_process_context() -> tuple[Scenario, RunArtifacts]:
    scenario_path = os.environ.get("KSPBENCH_SCENARIO", "scenarios/kerbin_orbit_80km.toml")
    scenario = load_scenario(scenario_path)
    artifacts = _artifacts(scenario, os.environ.get("KSPBENCH_RUN_DIR"))
    return scenario, artifacts


def make_tools(
    *,
    controller: KRPCController,
    scenario: Scenario,
    artifacts: RunArtifacts,
) -> LiveKRPCTools:
    return LiveKRPCTools(
        controller=controller,
        scenario=scenario,
        artifacts=artifacts,
        python_timeout_s=_float_env("KSPBENCH_EXECUTION_TIMEOUT", 15.0),
        task_timeout_s=_float_env("KSPBENCH_TASK_TIMEOUT", 180.0),
        max_wait_s=_float_env("KSPBENCH_MAX_SLEEP", 240.0),
        max_sync_python_s=_float_env("KSPBENCH_MAX_SYNC_PYTHON", 8.0),
        poll_interval_s=_float_env("KSPBENCH_POLL_INTERVAL", 0.5),
        live_events=True,
        task_controller_factory=lambda: controller,
    )


def apply_selected_vehicle(
    controller: KRPCController,
    selected_vehicle: dict[str, Any] | None,
) -> None:
    if selected_vehicle is None:
        return
    name = _optional_str(selected_vehicle, "name")
    index = _optional_int(selected_vehicle, "index")
    if name is None and index is None:
        return
    controller.select_vessel(
        name=name,
        index=index,
        make_active=_optional_bool(selected_vehicle, "make_active", default=False),
    )


def call_tool(tools: LiveKRPCTools, method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "observe":
        return tools.observe()
    if method == "throttle":
        return tools.set_throttle(_number(params, "value"))
    if method == "stage":
        return tools.stage()
    if method == "list_vehicles":
        return tools.list_vehicles()
    if method == "reset_launchpad":
        if not _truthy_env("KSPBENCH_ENABLE_RESET_TOOL"):
            raise PermissionError("reset_launchpad is disabled for this MCP session")
        return tools.reset_launchpad(wait_s=_optional_number(params, "wait_s") or 2.0)
    if method == "set_vehicle":
        return tools.set_vehicle(
            name=_optional_str(params, "name"),
            index=_optional_int(params, "index"),
            make_active=_optional_bool(params, "make_active", default=True),
        )
    if method == "attitude":
        mode = params.get("mode")
        if not isinstance(mode, str):
            raise TypeError("mode must be a string")
        frame = params.get("reference_frame", "orbital")
        if not isinstance(frame, str):
            raise TypeError("reference_frame must be a string")
        return tools.set_attitude(
            mode,
            pitch=_optional_number(params, "pitch"),
            heading=_optional_number(params, "heading"),
            reference_frame=frame,
        )
    if method == "wait":
        return tools.wait(_number(params, "seconds"))
    if method == "execute_python":
        code = params.get("code")
        if not isinstance(code, str):
            raise TypeError("code must be a string")
        return tools.execute_python(code, timeout_s=_optional_number(params, "timeout_s"))
    raise ValueError(f"unknown foreground method: {method}")


def read_json_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("stdin payload must be an object")
    return payload


def write_json_stdout(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def error_payload(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def _artifacts(scenario: Scenario, run_dir: str | None) -> RunArtifacts:
    if run_dir:
        artifacts = RunArtifacts(Path(run_dir), exist_ok=True)
        manifest = artifacts.run_dir / "manifest.json"
        if not manifest.exists():
            artifacts.write_manifest(
                scenario,
                {"name": "ksp", "model": None, "adapter": "opencode_mcp_direct"},
            )
            with contextlib.suppress(Exception):
                artifacts.copy_scenario(scenario)
        return artifacts

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    artifacts = RunArtifacts.create("runs", f"{stamp}_{uuid.uuid4().hex[:8]}_opencode_agent")
    artifacts.write_manifest(
        scenario,
        {"name": "ksp", "model": None, "adapter": "opencode_mcp_direct"},
    )
    artifacts.copy_scenario(scenario)
    return artifacts


def _number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _optional_number(params: dict[str, Any], key: str) -> float | None:
    if key not in params or params[key] is None:
        return None
    return _number(params, key)


def _optional_int(params: dict[str, Any], key: str) -> int | None:
    if key not in params or params[key] is None:
        return None
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value


def _optional_str(params: dict[str, Any], key: str) -> str | None:
    if key not in params or params[key] is None:
        return None
    value = params[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _optional_bool(params: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in params or params[key] is None:
        return default
    value = params[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None else float(value)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}

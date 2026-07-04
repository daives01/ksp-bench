from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bench.artifacts import RunArtifacts
from bench.config import load_scenario
from bench.krpc_client import KRPCController
from bench.live import LiveKRPCTools


class Worker:
    def __init__(self) -> None:
        scenario_path = os.environ.get("KSPBENCH_SCENARIO", "scenarios/kerbin_orbit_80km.toml")
        run_dir = os.environ.get("KSPBENCH_RUN_DIR")

        self.scenario = load_scenario(scenario_path)
        self.artifacts = _artifacts(self.scenario, run_dir)
        self.controller = KRPCController.connect(self.scenario)
        self.tools = LiveKRPCTools(
            controller=self.controller,
            scenario=self.scenario,
            artifacts=self.artifacts,
            python_timeout_s=_float_env("KSPBENCH_EXECUTION_TIMEOUT", 15.0),
            task_timeout_s=_float_env("KSPBENCH_TASK_TIMEOUT", 180.0),
            max_wait_s=_float_env("KSPBENCH_MAX_SLEEP", 240.0),
            poll_interval_s=_float_env("KSPBENCH_POLL_INTERVAL", 0.5),
            live_events=True,
        )
        self.artifacts.append_event({"type": "ksp_mcp_worker_started"})

    def close(self) -> None:
        self.artifacts.append_event({"type": "ksp_mcp_worker_stopped"})
        self.controller.close()

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "observe":
            return self.tools.observe()
        if method == "throttle":
            return self.tools.set_throttle(_number(params, "value"))
        if method == "stage":
            return self.tools.stage()
        if method == "pitch_heading":
            return self.tools.set_pitch_heading(
                _number(params, "pitch"),
                _number(params, "heading"),
            )
        if method == "prograde":
            frame = params.get("reference_frame", "orbital")
            if not isinstance(frame, str):
                raise TypeError("reference_frame must be a string")
            return self.tools.hold_prograde(frame)
        if method == "wait":
            return self.tools.wait(_number(params, "seconds"))
        if method == "execute_python":
            code = params.get("code")
            if not isinstance(code, str):
                raise TypeError("code must be a string")
            return self.tools.execute_python(code, timeout_s=_optional_number(params, "timeout_s"))
        if method == "start_task":
            code = params.get("code")
            if not isinstance(code, str):
                raise TypeError("code must be a string")
            return self.tools.start_task(code, timeout_s=_optional_number(params, "timeout_s"))
        if method == "check_task":
            return self.tools.check_task()
        if method == "stop_task":
            return self.tools.stop_task()
        raise ValueError(f"unknown method: {method}")


def main() -> int:
    try:
        worker = Worker()
    except Exception as exc:
        _write({"id": None, "error": _error(exc)})
        return 1

    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise TypeError("request must be an object")
                request_id = request.get("id")
                method = request.get("method")
                params = request.get("params", {})
                if not isinstance(method, str):
                    raise TypeError("method must be a string")
                if not isinstance(params, dict):
                    raise TypeError("params must be an object")
                _write({"id": request_id, "result": worker.call(method, params)})
            except Exception as exc:
                _write(
                    {
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "error": _error(exc),
                    }
                )
    finally:
        worker.close()
    return 0


def _artifacts(scenario: Any, run_dir: str | None) -> RunArtifacts:
    if run_dir:
        return RunArtifacts.open(Path(run_dir))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifacts = RunArtifacts.create("runs", f"{stamp}_opencode_agent")
    artifacts.write_manifest(
        scenario,
        {"name": "ksp", "model": None, "adapter": "opencode_mcp_direct"},
    )
    artifacts.copy_scenario(scenario)
    return artifacts


def _write(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def _error(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def _number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _optional_number(params: dict[str, Any], key: str) -> float | None:
    if key not in params or params[key] is None:
        return None
    return _number(params, key)


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None else float(value)


if __name__ == "__main__":
    raise SystemExit(main())

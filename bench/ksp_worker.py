from __future__ import annotations

import contextlib
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
        self.controller: KRPCController | None = None
        self.tools: LiveKRPCTools | None = None
        self.selected_vehicle: dict[str, Any] | None = None
        self._connect_tools()
        self.artifacts.append_event({"type": "ksp_mcp_worker_started"})

    def _connect_tools(self) -> None:
        self.controller = KRPCController.connect(self.scenario, strict_vessel=False)
        self.tools = LiveKRPCTools(
            controller=self.controller,
            scenario=self.scenario,
            artifacts=self.artifacts,
            python_timeout_s=_float_env("KSPBENCH_EXECUTION_TIMEOUT", 15.0),
            task_timeout_s=_float_env("KSPBENCH_TASK_TIMEOUT", 180.0),
            max_wait_s=_float_env("KSPBENCH_MAX_SLEEP", 240.0),
            poll_interval_s=_float_env("KSPBENCH_POLL_INTERVAL", 0.5),
            live_events=True,
            task_controller_factory=lambda: KRPCController.connect(
                self.scenario,
                strict_vessel=False,
            ),
        )

    def close(self) -> None:
        self.artifacts.append_event({"type": "ksp_mcp_worker_stopped"})
        if self.controller is not None:
            self.controller.close()

    def reconnect(self) -> None:
        old_controller = self.controller
        try:
            if old_controller is not None:
                old_controller.close()
        finally:
            self._connect_tools()
            if self.selected_vehicle is not None and self.controller is not None:
                with contextlib.suppress(Exception):
                    self.controller.select_vessel(**self.selected_vehicle)
            self.artifacts.append_event({"type": "ksp_mcp_worker_reconnected"})

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._call_once(method, params)
        except Exception as exc:
            if not _looks_like_connection_failure(exc):
                raise
            self.reconnect()
            return self._call_once(method, params)
        if _result_is_connection_failure(result):
            self.reconnect()
            retry = self._call_once(method, params)
            if isinstance(retry, dict):
                retry.setdefault("reconnected", True)
            if method == "set_vehicle" and retry.get("ok"):
                self.selected_vehicle = _selection_params(params)
            return retry
        if method == "set_vehicle" and result.get("ok"):
            self.selected_vehicle = _selection_params(params)
        return result

    def _call_once(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.tools is None:
            raise RuntimeError("KSP tools are not connected")
        if method == "observe":
            return self.tools.observe()
        if method == "throttle":
            return self.tools.set_throttle(_number(params, "value"))
        if method == "stage":
            return self.tools.stage()
        if method == "list_vehicles":
            return self.tools.list_vehicles()
        if method == "reset_launchpad":
            if not _truthy_env("KSPBENCH_ENABLE_RESET_TOOL"):
                raise PermissionError("reset_launchpad is disabled for this MCP session")
            self.selected_vehicle = None
            return self.tools.reset_launchpad(wait_s=_optional_number(params, "wait_s") or 2.0)
        if method == "set_vehicle":
            return self.tools.set_vehicle(
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
            return self.tools.set_attitude(
                mode,
                pitch=_optional_number(params, "pitch"),
                heading=_optional_number(params, "heading"),
                reference_frame=frame,
            )
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
            return self.tools.check_task(task_id=_optional_str(params, "task_id"))
        if method == "stop_task":
            return self.tools.stop_task(task_id=_optional_str(params, "task_id"))
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


def _result_is_connection_failure(result: dict[str, Any]) -> bool:
    if result.get("ok") is not False:
        return False
    error = str(result.get("error", ""))
    error_type = str(result.get("error_type", ""))
    return (
        error_type
        in {
            "ConnectionError",
            "ConnectionRefusedError",
            "ConnectionResetError",
            "BrokenPipeError",
            "EOFError",
            "TimeoutError",
        }
        or _connection_failure_text(error)
    )


def _looks_like_connection_failure(exc: Exception) -> bool:
    return _connection_failure_text(str(exc)) or type(exc).__name__ in {
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "BrokenPipeError",
        "EOFError",
        "TimeoutError",
    }


def _connection_failure_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "connection",
            "broken pipe",
            "connection reset",
            "connection refused",
            "connection aborted",
            "no route to host",
            "socket",
            "eof",
        )
    )


def _selection_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _optional_str(params, "name"),
        "index": _optional_int(params, "index"),
        "make_active": _optional_bool(params, "make_active", default=True),
    }


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


if __name__ == "__main__":
    raise SystemExit(main())

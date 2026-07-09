from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from bench.krpc_client import KRPCController
from bench.ksp_process import (
    apply_selected_vehicle,
    load_process_context,
    make_tools,
    read_json_stdin,
)


def main() -> int:
    controller: KRPCController | None = None
    request: dict[str, Any] = {}
    try:
        request = read_json_stdin()
        task_id = _required_str(request, "task_id")
        code = _required_str(request, "code")
        timeout_s = _number(request, "timeout_s")
        status_path = Path(_required_str(request, "status_path"))
        stop_path = Path(_required_str(request, "stop_path"))
        selected_vehicle = request.get("selected_vehicle")
        if selected_vehicle is not None and not isinstance(selected_vehicle, dict):
            raise TypeError("selected_vehicle must be an object")

        scenario, artifacts = load_process_context()
        controller = KRPCController.connect(scenario, strict_vessel=False)
        apply_selected_vehicle(controller, selected_vehicle)
        tools = make_tools(controller=controller, scenario=scenario, artifacts=artifacts)
        artifacts.append_event({"type": "ksp_mcp_task_process_started", "task_id": task_id})

        started = tools.start_task(code, timeout_s=timeout_s, event_task_id=task_id)
        if not started.get("ok"):
            task = {
                "task_id": task_id,
                "status": "failed",
                "running": False,
                "error_type": started.get("error_type"),
                "error": started.get("error"),
            }
            status = {
                "ok": False,
                "task": task,
                "tasks": [task],
                "latest_telemetry": None,
            }
            _write_status(status_path, status)
            return 0

        internal_task_id = str(started["task_id"])
        stop_requested = False
        while True:
            if stop_path.exists() and not stop_requested:
                tools.stop_task(task_id=internal_task_id)
                stop_requested = True

            snapshot = tools.task_snapshot(task_id=internal_task_id)
            status = _externalized_snapshot(snapshot, task_id=task_id)
            _write_status(status_path, {"ok": True, **status})

            task = status["task"]
            if not task or not task.get("running"):
                artifacts.append_event(
                    {
                        "type": "ksp_mcp_task_process_finished",
                        "task_id": task_id,
                        "status": task.get("status") if task else None,
                    }
                )
                return 0
            time.sleep(_float_env("KSPBENCH_TASK_STATUS_INTERVAL", 0.25))
    except Exception as exc:
        with contextlib.suppress(Exception):
            task_id = str(request.get("task_id", "task"))
            task = {
                "task_id": task_id,
                "status": "failed",
                "running": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            payload = {
                "ok": False,
                "task": task,
                "tasks": [task],
                "latest_telemetry": None,
            }
            status_path = Path(str(request.get("status_path", "")))
            if str(status_path):
                _write_status(status_path, payload)
        return 1
    finally:
        if controller is not None:
            with contextlib.suppress(Exception):
                controller.close()


def _externalized_snapshot(snapshot: dict[str, Any], *, task_id: str) -> dict[str, Any]:
    tasks = [_externalized_task(task, task_id=task_id) for task in snapshot["tasks"]]
    task = _externalized_task(snapshot["task"], task_id=task_id)
    return {
        "task": task,
        "tasks": tasks,
        "latest_telemetry": snapshot["latest_telemetry"],
    }


def _externalized_task(task: dict[str, Any] | None, *, task_id: str) -> dict[str, Any] | None:
    if task is None:
        return None
    return {**task, "task_id": task_id}


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _required_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _number(params: dict[str, Any], key: str) -> float:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{key} must be a number")
    return float(value)


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    return default if value is None else float(value)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import contextlib
import json
import sys
from typing import Any

from bench.krpc_client import KRPCController
from bench.ksp_process import (
    apply_selected_vehicle,
    call_tool,
    error_payload,
    load_process_context,
    make_tools,
)


class Worker:
    def __init__(self) -> None:
        self.scenario, self.artifacts = load_process_context()
        self.controller: KRPCController | None = None
        self.tools: Any = None
        self._connect()
        self.artifacts.append_event({"type": "ksp_mcp_worker_started"})

    def _connect(self) -> None:
        self.controller = KRPCController.connect(self.scenario, strict_vessel=False)
        self.tools = make_tools(
            controller=self.controller,
            scenario=self.scenario,
            artifacts=self.artifacts,
        )

    def reconnect(self) -> None:
        if self.controller is not None:
            with contextlib.suppress(Exception):
                self.controller.close()
        self._connect()
        self.artifacts.append_event({"type": "ksp_mcp_worker_reconnected"})

    def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = call_tool(self.tools, method, params)
        except Exception as exc:
            if not _connection_failure(type(exc).__name__, str(exc)):
                raise
            self.reconnect()
            return call_tool(self.tools, method, params)
        if result.get("ok") is False and _connection_failure(
            str(result.get("error_type", "")), str(result.get("error", ""))
        ):
            self.reconnect()
            result = call_tool(self.tools, method, params)
            result.setdefault("reconnected", True)
        return result

    def close(self) -> None:
        self.artifacts.append_event({"type": "ksp_mcp_worker_stopped"})
        if self.controller is not None:
            with contextlib.suppress(Exception):
                self.controller.close()


def main() -> int:
    try:
        worker = Worker()
    except Exception as exc:
        _write({"id": None, "error": error_payload(exc)})
        return 1
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            request: Any = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise TypeError("request must be an object")
                request_id = request.get("id")
                method = request.get("method")
                params = request.get("params", {})
                selected_vehicle = request.get("selected_vehicle")
                if not isinstance(method, str):
                    raise TypeError("method must be a string")
                if not isinstance(params, dict):
                    raise TypeError("params must be an object")
                apply_selected_vehicle(worker.controller, selected_vehicle)
                _write({"id": request_id, "result": worker.call(method, params)})
            except Exception as exc:
                request_id = request.get("id") if isinstance(request, dict) else None
                _write({"id": request_id, "error": error_payload(exc)})
    finally:
        worker.close()
    return 0


def _connection_failure(error_type: str, message: str) -> bool:
    if error_type in {
        "BrokenPipeError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "EOFError",
        "TimeoutError",
    }:
        return True
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in ("broken pipe", "connection", "eof", "no route to host", "socket")
    )


def _write(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

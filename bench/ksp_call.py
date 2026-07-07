from __future__ import annotations

import contextlib
from typing import Any

from bench.krpc_client import KRPCController
from bench.ksp_process import (
    apply_selected_vehicle,
    call_tool,
    error_payload,
    load_process_context,
    make_tools,
    read_json_stdin,
    write_json_stdout,
)


def main() -> int:
    controller: KRPCController | None = None
    try:
        request = read_json_stdin()
        method = request.get("method")
        params = request.get("params", {})
        selected_vehicle = request.get("selected_vehicle")
        if not isinstance(method, str):
            raise TypeError("method must be a string")
        if not isinstance(params, dict):
            raise TypeError("params must be an object")
        if selected_vehicle is not None and not isinstance(selected_vehicle, dict):
            raise TypeError("selected_vehicle must be an object")

        scenario, artifacts = load_process_context()
        controller = KRPCController.connect(scenario, strict_vessel=False)
        if method not in {"reset_launchpad", "set_vehicle"}:
            apply_selected_vehicle(controller, _typed_dict(selected_vehicle))
        tools = make_tools(controller=controller, scenario=scenario, artifacts=artifacts)
        artifacts.append_event({"type": "ksp_mcp_process_call_started", "method": method})
        result = call_tool(tools, method, params)
        artifacts.append_event({"type": "ksp_mcp_process_call_finished", "method": method})
        write_json_stdout({"result": result})
        return 0
    except Exception as exc:
        write_json_stdout({"error": error_payload(exc)})
        return 1
    finally:
        if controller is not None:
            with contextlib.suppress(Exception):
                controller.close()


def _typed_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())

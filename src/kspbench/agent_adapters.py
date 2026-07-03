from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kspbench.config import Scenario
from kspbench.live import LiveKRPCTools

AGENT_PROMPT_TEMPLATE = """You are flying a Kerbal Space Program benchmark mission.

Goal:
- Reach a stable orbit around {body}.
- Target apoapsis between {apoapsis_min_m:.0f}m and {apoapsis_max_m:.0f}m.
- Target periapsis at least {periapsis_min_m:.0f}m.
- Complete within {timeout_s:.0f}s mission elapsed time.

Use only the OpenCode KSP tools exposed by the benchmark harness:
- ksp_telemetry: read the latest telemetry snapshot.
- ksp_vehicle: inspect the current vessel state.
- ksp_execute: run a short kRPC Python snippet.
- ksp_wait: advance mission time while the harness records telemetry. The harness
  may use KSP time warp for longer waits.

The ksp_execute code runs inside the harness with these names available:
- conn, space_center, vessel
- getTelemetry(), getVehicleState()
- sleep(seconds), wait(seconds), wait_until(condition, timeout_s=seconds)
- math is already available; imports are not allowed.

Do not create or modify files for this mission. Interact with KSP only through the
KSP tools. Use short execute snippets, inspect telemetry after maneuvers, and stop
when the vehicle is in the target orbit or cannot continue safely.
Do not call KSP reset/load APIs such as revert_to_launch, revert_to_editor, quickload,
quicksave, or load. The benchmark harness handles all resets between runs.
KSP manual controls like vessel.control.pitch are stick deflections, not attitude targets;
use vessel.auto_pilot.target_pitch_and_heading(...) when you need a specific pitch/heading.
Prefer orbital_speed_m_s for speed checks; surface_speed_m_s may be zero for some
KSP reference-frame states.
"""


@dataclass(frozen=True)
class ExternalAgentResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class OpenCodeAgentAdapter:
    def __init__(
        self,
        *,
        model: str | None = None,
        executable: str | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        self.model = model
        self.executable = executable or "opencode"
        self.extra_args = extra_args or []

    @property
    def agent_metadata(self) -> dict[str, str | None]:
        return {
            "name": "opencode",
            "model": self.model,
            "adapter": "opencode_cli_custom_tools_live_krpc",
        }

    def run(
        self,
        *,
        scenario: Scenario,
        bridge_url: str,
        timeout_s: float,
        stream_output: bool = True,
    ) -> ExternalAgentResult:
        prompt = build_agent_prompt(scenario=scenario)
        with tempfile.TemporaryDirectory(prefix="kspbench-opencode-") as workspace:
            workspace_path = Path(workspace)
            write_opencode_workspace(workspace_path, bridge_url=bridge_url, model=self.model)
            command = self._command(prompt, workspace=workspace_path)
            if stream_output:
                return _run_streaming(command, cwd=workspace_path, timeout_s=timeout_s)
            try:
                completed = subprocess.run(
                    command,
                    cwd=workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                return ExternalAgentResult(
                    command=command,
                    returncode=124,
                    stdout=exc.stdout or "",
                    stderr=exc.stderr or "",
                    timed_out=True,
                )
            return ExternalAgentResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )

    def _command(self, prompt: str, *, workspace: Path) -> list[str]:
        command = [
            self.executable,
            "run",
            "--dir",
            str(workspace),
            "--agent",
            "kspbench",
            "--auto",
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(self.extra_args)
        command.append(prompt)
        return command


def write_opencode_workspace(
    workspace: Path,
    *,
    bridge_url: str,
    model: str | None = None,
) -> None:
    tools_dir = workspace / ".opencode" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (workspace / "opencode.json").write_text(
        json.dumps(_opencode_config(model), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (tools_dir / "ksp.ts").write_text(_opencode_tools_source(bridge_url), encoding="utf-8")


def _opencode_config(model: str | None) -> dict[str, Any]:
    permissions: dict[str, str] = {
        "*": "deny",
        "bash": "deny",
        "edit": "deny",
        "read": "deny",
        "grep": "deny",
        "glob": "deny",
        "lsp": "deny",
        "skill": "deny",
        "task": "deny",
        "todowrite": "deny",
        "webfetch": "deny",
        "websearch": "deny",
        "question": "deny",
        "external_directory": "deny",
        "doom_loop": "deny",
        "ksp_*": "allow",
    }
    agent_config: dict[str, Any] = {
        "description": "Fly a KSP benchmark vessel using only harness-provided kRPC tools.",
        "mode": "primary",
        "permission": permissions,
    }
    if model:
        agent_config["model"] = model
    return {
        "$schema": "https://opencode.ai/config.json",
        "permission": permissions,
        "agent": {"kspbench": agent_config},
    }


def _opencode_tools_source(bridge_url: str) -> str:
    bridge_literal = json.dumps(bridge_url)
    return f"""import {{ tool }} from "@opencode-ai/plugin"

const BRIDGE_URL = {bridge_literal}

async function bridge(path: string, init?: RequestInit): Promise<string> {{
  const response = await fetch(`${{BRIDGE_URL}}${{path}}`, init)
  const body = await response.text()
  if (!response.ok) return body || `bridge request failed: ${{response.status}}`
  return body
}}

async function post(path: string, payload: unknown): Promise<string> {{
  return bridge(path, {{
    method: "POST",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(payload),
  }})
}}

export const telemetry = tool({{
  description: "Read the latest KSP telemetry snapshot.",
  args: {{}},
  async execute() {{
    return bridge("/telemetry")
  }},
}})

export const vehicle = tool({{
  description: "Read the current vessel state and controllable parts summary.",
  args: {{}},
  async execute() {{
    return bridge("/vehicle")
  }},
}})

export const execute = tool({{
  description: "Run a short, sandboxed kRPC Python snippet in the benchmark harness.",
  args: {{
    code: tool.schema.string().describe(
      "Python code using conn, space_center, vessel, telemetry helpers, and wait helpers.",
    ),
    timeout_s: tool.schema.number().optional().describe(
      "Optional wall-clock timeout in seconds.",
    ),
  }},
  async execute(args) {{
    return post("/execute", args)
  }},
}})

export const wait = tool({{
  description:
    "Advance mission time while the harness records telemetry. Long waits may use KSP time warp.",
  args: {{
    seconds: tool.schema.number().describe("Mission seconds to wait."),
    poll_interval_s: tool.schema.number().optional().describe(
      "Optional telemetry polling interval in seconds.",
    ),
  }},
  async execute(args) {{
    return post("/wait", args)
  }},
}})
"""


class ToolBridgeServer:
    def __init__(self, tools: LiveKRPCTools) -> None:
        self.tools = tools
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> ToolBridgeServer:
        self._thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        tools = self.tools

        class Handler(BaseHTTPRequestHandler):
            server_version = "KSPBenchToolBridge/0.1"

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                if path == "/telemetry":
                    self._send_json(tools.getTelemetry())
                    return
                if path == "/vehicle":
                    self._send_json(tools.getVehicleState())
                    return
                if path == "/health":
                    self._send_json({"ok": True})
                    return
                self._send_json({"error": "not found"}, status=404)

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if path == "/wait":
                    self._handle_wait()
                    return
                if path != "/execute":
                    self._send_json({"error": "not found"}, status=404)
                    return
                try:
                    payload = self._read_json()
                    code = payload.get("code")
                    if not isinstance(code, str):
                        raise TypeError("code must be a string")
                    timeout = payload.get("timeout_s")
                    if timeout is not None and not isinstance(timeout, int | float):
                        raise TypeError("timeout_s must be a number")
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self._send_json(
                    tools.executeKRPC(code, timeout_s=float(timeout) if timeout else None)
                )

            def _handle_wait(self) -> None:
                try:
                    payload = self._read_json()
                    seconds = payload.get("seconds")
                    if not isinstance(seconds, int | float):
                        raise TypeError("seconds must be a number")
                    poll_interval = payload.get("poll_interval_s")
                    if poll_interval is not None and not isinstance(poll_interval, int | float):
                        raise TypeError("poll_interval_s must be a number")
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self._send_json(
                    tools.wait(
                        float(seconds),
                        poll_interval_s=float(poll_interval) if poll_interval else None,
                    )
                )

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise TypeError("request body must be a JSON object")
                return payload

            def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
                body = json.dumps(payload, sort_keys=True).encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except BrokenPipeError:
                    return

        return Handler


def build_agent_prompt(*, scenario: Scenario) -> str:
    return AGENT_PROMPT_TEMPLATE.format(
        body=scenario.body,
        apoapsis_min_m=scenario.target_orbit.apoapsis_min_m,
        apoapsis_max_m=scenario.target_orbit.apoapsis_max_m,
        periapsis_min_m=scenario.target_orbit.periapsis_min_m,
        timeout_s=scenario.timeout_s,
    )


def _run_streaming(command: list[str], *, cwd: Path, timeout_s: float) -> ExternalAgentResult:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return ExternalAgentResult(command=command, returncode=127, stdout="", stderr=str(exc))

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    threads = [
        threading.Thread(
            target=_tee_stream,
            args=(process.stdout, sys.stdout, stdout_chunks),
            daemon=True,
        ),
        threading.Thread(
            target=_tee_stream,
            args=(process.stderr, sys.stderr, stderr_chunks),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = 124
        timed_out = True
    for thread in threads:
        thread.join(timeout=2.0)
    return ExternalAgentResult(
        command=command,
        returncode=returncode,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        timed_out=timed_out,
    )


def _tee_stream(stream: Any, target: Any, chunks: list[str]) -> None:
    if stream is None:
        return
    for chunk in iter(stream.readline, ""):
        chunks.append(chunk)
        target.write(chunk)
        target.flush()

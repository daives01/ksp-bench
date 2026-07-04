from __future__ import annotations

import json
import re
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

AGENT_PROMPT_TEMPLATE = """You are in charge of flying the Kerbal X rocket in KSP in realtime. it is
a multistage rocket with more than enough fuel, with the right pilot. (hint: it uses onion staging)

The goal:
- Reach a stable orbit around {body}.
- Target apoapsis between {apoapsis_min_m:.0f}m and {apoapsis_max_m:.0f}m.
- Target periapsis at least {periapsis_min_m:.0f}m.
- Complete within {timeout_s:.0f}s mission elapsed time.

To accomplish this, you can use the following tools:
- read/grep/glob: inspect the read-only krpc_reference/ files for kRPC Python API names and
  benchmark helper names, telemetry fields, examples, and kRPC API names before using unfamiliar
  vessel, autopilot, orbit, flight, or staging calls.
- ksp_execute: run Python code with kRPC. This is your main interface: read telemetry, inspect the
  vessel, stage, steer, throttle, and run short control loops from inside this tool.
- ksp_execute_async: start a background kRPC Python script and immediately get a script id.
- ksp_check: check background script status, recent stdout, result, errors, and latest telemetry.
- ksp_kill: request cooperative stop for a background script.

KSP is running in real wall-clock time. If you run a synchronous ksp_execute script that takes a
while, the rocket keeps flying while you wait and you cannot issue another command until it returns.
Use ksp_execute for quick observations and short actions. Use ksp_execute_async for longer control
loops, threshold guards such as cutting throttle at an apoapsis target, or monitor scripts you want
running while you keep thinking. Multiple async scripts are allowed, but control scripts can fight
each other because throttle, staging, and autopilot are shared; coordinate them deliberately.

The ksp_execute and ksp_execute_async code runs inside the harness with these names available:
- conn, space_center, vessel
- getTelemetry(), getVehicleState(), getOrbitState()
- sleep(seconds), wait(seconds), wait_until(condition, timeout_s=seconds).
  Long waits are rejected in atmosphere; use small closed-loop sleeps there.
- In async scripts only, should_stop() returns True after ksp_kill requests cooperative stop.
- math is already available; any other imports are not allowed.

It is fine to write longer Python snippets that perform several related actions.
Start by reading or grepping krpc_reference/. Before using an unfamiliar kRPC API, grep
krpc_reference/ for it. Prefer the documented target_pitch_and_heading and reference-frame
direction APIs over guessed autopilot properties.
"""

AGENT_SYSTEM_PROMPT = "\n".join(
    [
        (
            "You are the KSP-bench flight agent. Your only job is to fly the active "
            "Kerbal Space Program vessel to the target orbit using the benchmark tools."
        ),
        "",
        (
            "Use only the custom tools named ksp_execute, ksp_execute_async, ksp_check, "
            "and ksp_kill, plus read/grep/glob for the local krpc_reference/ directory. "
            "Do not use shell commands, edit files, browse the web, ask the user "
            "questions, or call non-benchmark tools."
        ),
        "",
        (
            "Use read/grep/glob on krpc_reference/ for the reference. Use ksp_execute "
            "for quick KSP interaction and ksp_execute_async for longer background "
            "control loops. Check krpc_reference/ before trying unfamiliar kRPC APIs. "
            "Inside snippets, use getTelemetry() and getVehicleState() to observe the "
            "rocket, including current_stage_resources for current-stage fuel. KSP "
            "continues in real wall-clock time while synchronous ksp_execute is running. "
            "Long sleeps are rejected in atmosphere because they miss critical flight "
            "events."
        ),
    ]
)

KRPC_REFERENCE_README = """# kRPC reference for KSP-bench

These files are here so you can use read/grep/glob instead of a docs tool or guessed
kRPC API names. The executable snippets still run only through ksp_execute or
ksp_execute_async.

Useful searches:

- `grep target_ krpc_reference/*`
- `grep auto_pilot krpc_reference/*`
- `grep resources_in_decouple_stage krpc_reference/*`
- `grep reference_frame krpc_reference/*`
- `grep getTelemetry krpc_reference/*`

Benchmark tools:

- `ksp_execute`: run sandboxed kRPC Python synchronously. Use it for quick observations,
  staging, steering, throttle changes, and short control loops.
- `ksp_execute_async`: start sandboxed kRPC Python in the background and immediately get
  a script id. Use it for longer control loops, threshold guards, and monitors.
- `ksp_check`: check one async script by script_id, or list all async scripts. It also returns
  latest telemetry recorded by the harness, so use it to monitor async scripts without blocking
  behind a running control loop.
- `ksp_kill`: request cooperative stop for an async script.

Snippet globals:

- `conn`, `space_center`, `vessel`
- `getTelemetry()`, `getVehicleState()`, `getOrbitState()`
- `sleep(seconds)`, `wait(seconds)`, `wait_until(condition, timeout_s=seconds)`
- async scripts also get `should_stop()`
- `math` is already available; other imports are blocked

Telemetry fields returned by `getTelemetry()`:

`mission_elapsed_s`, `altitude_m`, `surface_altitude_m`, `apoapsis_m`, `periapsis_m`,
`time_to_apoapsis_s`, `time_to_periapsis_s`, `eccentricity`, `inclination_deg`,
`surface_speed_m_s`, `orbital_speed_m_s`, `vertical_speed_m_s`, `pitch_deg`,
`heading_deg`, `roll_deg`, `stage`, `liquid_fuel`, `oxidizer`, `solid_fuel`,
`dynamic_pressure_pa`, `situation`, `body`, `controllable`, `intact`.

`getOrbitState()` returns a compact orbit/control snapshot for timing coast and burns.

`getVehicleState()` includes total resources, current-stage resources, stages, engines,
active engines, decouplers, and atmospheric status. Use `current_stage_resources` to
see fuel left in the current stage.

Common working calls:

```python
vessel.control.throttle = 1.0
vessel.control.activate_next_stage()

vessel.auto_pilot.engage()
vessel.auto_pilot.target_pitch_and_heading(80, 90)
vessel.auto_pilot.wait()
vessel.auto_pilot.disengage()

flight = vessel.flight(vessel.orbit.body.reference_frame)
prograde = flight.prograde
retrograde = tuple(-x for x in prograde)
vessel.auto_pilot.reference_frame = vessel.orbit.body.reference_frame
vessel.auto_pilot.target_direction = prograde

resources = vessel.resources_in_decouple_stage(stage, cumulative=False)
liquid_fuel = resources.amount("LiquidFuel")
oxidizer = resources.amount("Oxidizer")
```

Avoid these guessed APIs; they are not kRPC Python autopilot properties:

```python
vessel.auto_pilot.attitude_control
vessel.auto_pilot.target_prograde = True
vessel.auto_pilot.target_retrograde = True
```

Flight notes:

- KSP continues in real wall-clock time while synchronous `ksp_execute` is running.
- In atmosphere, long `sleep`, `wait`, and `wait_until` calls are rejected. Use short
  closed-loop sleeps and re-check telemetry.
- Manual `vessel.control.pitch`, `yaw`, and `roll` are stick deflections, not attitude
  targets.
- Use `orbital_speed_m_s` for orbital checks; `surface_speed_m_s` can be misleading in
  some reference frames.
- If a synchronous `ksp_execute` monitor times out, treat it as a failed action and
  switch to short `ksp_execute` calls or async control. The vessel may still be
  controllable.
"""

KRPC_SPACE_CENTER_STUBS = '''"""Searchable kRPC SpaceCenter declarations for KSP-bench agents.

This is a compact reference, not an importable module. It lists the kRPC Python
members most useful for the Kerbin orbit benchmark.
"""

from typing import Any


class Vessel:
    name: str
    control: "Control"
    auto_pilot: "AutoPilot"
    orbit: "Orbit"
    parts: Any
    resources: "Resources"

    def flight(self, reference_frame: Any = ...) -> "Flight": ...
    def resources_in_decouple_stage(self, stage: int, cumulative: bool = ...) -> "Resources": ...


class Control:
    throttle: float
    pitch: float
    yaw: float
    roll: float
    sas: bool
    rcs: bool
    gear: bool
    lights: bool
    brakes: bool
    current_stage: int

    def activate_next_stage(self) -> list[Any]: ...


class AutoPilot:
    reference_frame: Any
    target_direction: tuple[float, float, float]
    target_pitch: float
    target_heading: float
    target_roll: float
    stopping_time: tuple[float, float, float]
    deceleration_time: tuple[float, float, float]
    attenuation_angle: tuple[float, float, float]
    error: float

    def engage(self) -> None: ...
    def disengage(self) -> None: ...
    def wait(self) -> None: ...
    def target_pitch_and_heading(self, pitch: float, heading: float) -> None: ...


class Orbit:
    body: "CelestialBody"
    apoapsis_altitude: float
    periapsis_altitude: float
    semi_major_axis: float
    eccentricity: float
    inclination: float
    time_to_apoapsis: float
    time_to_periapsis: float


class CelestialBody:
    name: str
    reference_frame: Any
    non_rotating_reference_frame: Any
    orbital_reference_frame: Any
    gravitational_parameter: float
    equatorial_radius: float
    atmosphere_depth: float


class Flight:
    prograde: tuple[float, float, float]
    retrograde: tuple[float, float, float]
    normal: tuple[float, float, float]
    anti_normal: tuple[float, float, float]
    radial: tuple[float, float, float]
    anti_radial: tuple[float, float, float]
    pitch: float
    heading: float
    roll: float
    mean_altitude: float
    surface_altitude: float
    vertical_speed: float
    horizontal_speed: float
    speed: float
    dynamic_pressure: float


class Resources:
    names: list[str]

    def amount(self, name: str) -> float: ...
    def max(self, name: str) -> float: ...
    def has_resource(self, name: str) -> bool: ...
'''


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
    write_krpc_reference(workspace)


def write_krpc_reference(workspace: Path) -> None:
    reference_dir = workspace / "krpc_reference"
    reference_dir.mkdir(parents=True, exist_ok=True)
    (reference_dir / "README.md").write_text(KRPC_REFERENCE_README, encoding="utf-8")
    (reference_dir / "space_center_stubs.py").write_text(
        KRPC_SPACE_CENTER_STUBS,
        encoding="utf-8",
    )


def _opencode_config(model: str | None) -> dict[str, Any]:
    permissions: dict[str, str] = {
        "*": "deny",
        "bash": "deny",
        "edit": "deny",
        "read": "allow",
        "grep": "allow",
        "glob": "allow",
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
        "prompt": AGENT_SYSTEM_PROMPT,
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

export const execute = tool({{
  description:
    "Run sandboxed kRPC Python synchronously. KSP keeps flying in real wall-clock " +
    "time while this blocks; use for quick telemetry, staging, steering, and short loops.",
  args: {{
    code: tool.schema.string().describe(
      "Python code using conn, space_center, vessel, getTelemetry(), " +
      "getVehicleState(), getOrbitState(), math, and short wait helpers.",
    ),
    timeout_s: tool.schema.number().optional().describe(
      "Optional wall-clock timeout in seconds.",
    ),
  }},
  async execute(args) {{
    return post("/execute", args)
  }},
}})

export const execute_async = tool({{
  description:
    "Start sandboxed kRPC Python in the background and immediately return a script id. " +
    "Use for longer control loops, guards, and monitors while you keep reasoning. " +
    "Multiple scripts may run and can fight over shared controls, so coordinate them.",
  args: {{
    code: tool.schema.string().describe(
      "Python code using conn, space_center, vessel, getTelemetry(), " +
      "getVehicleState(), getOrbitState(), math, short wait helpers, and should_stop().",
    ),
    timeout_s: tool.schema.number().optional().describe(
      "Optional wall-clock timeout in seconds.",
    ),
  }},
  async execute(args) {{
    return post("/execute_async", args)
  }},
}})

export const check = tool({{
  description:
    "Check async script status. Omit script_id to list all scripts. Returns status, " +
    "elapsed time, recent stdout, result, latest telemetry, and any error.",
  args: {{
    script_id: tool.schema.string().optional().describe("Async script id to inspect."),
  }},
  async execute(args) {{
    return post("/check", args)
  }},
}})

export const kill = tool({{
  description:
    "Request cooperative stop for an async script. Scripts using sleep/wait/should_stop " +
    "stop promptly; a blocking kRPC call may only stop at timeout.",
  args: {{
    script_id: tool.schema.string().describe("Async script id to stop."),
  }},
  async execute(args) {{
    return post("/kill", args)
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
                if path == "/health":
                    self._send_json({"ok": True})
                    return
                self._send_json({"error": "not found"}, status=404)

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                if path not in {"/execute", "/execute_async", "/check", "/kill"}:
                    self._send_json({"error": "not found"}, status=404)
                    return
                try:
                    payload = self._read_json()
                    if path in {"/execute", "/execute_async"}:
                        code = payload.get("code")
                        if not isinstance(code, str):
                            raise TypeError("code must be a string")
                        timeout = payload.get("timeout_s")
                        if timeout is not None and not isinstance(timeout, int | float):
                            raise TypeError("timeout_s must be a number")
                    else:
                        code = ""
                        timeout = None
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                if path == "/execute":
                    self._send_json(
                        tools.executeKRPC(code, timeout_s=float(timeout) if timeout else None)
                    )
                    return
                if path == "/execute_async":
                    self._send_json(
                        tools.executeKRPCAsync(code, timeout_s=float(timeout) if timeout else None)
                    )
                    return
                if path == "/check":
                    script_id = payload.get("script_id")
                    if script_id is not None and not isinstance(script_id, str):
                        self._send_json(
                            {"ok": False, "error": "script_id must be a string"},
                            status=400,
                        )
                        return
                    self._send_json(tools.checkAsync(script_id))
                    return
                script_id = payload.get("script_id")
                if not isinstance(script_id, str):
                    self._send_json(
                        {"ok": False, "error": "script_id must be a string"},
                        status=400,
                    )
                    return
                self._send_json(tools.killAsync(script_id))

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
            stderr=subprocess.STDOUT,
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
            args=(process.stdout, sys.stdout, stdout_chunks, _format_opencode_terminal_chunk),
            daemon=True,
        )
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


def _tee_stream(stream: Any, target: Any, chunks: list[str], formatter: Any = None) -> None:
    if stream is None:
        return
    for chunk in iter(stream.readline, ""):
        chunks.append(chunk)
        target.write(formatter(chunk) if formatter else chunk)
        target.flush()


def _format_opencode_terminal_chunk(chunk: str) -> str:
    return "".join(_format_opencode_terminal_line(line) for line in chunk.splitlines(keepends=True))


def _format_opencode_terminal_line(line: str) -> str:
    line_body, line_end = _split_line_ending(line)
    clean = _strip_ansi(line_body).strip()
    clean = clean.removeprefix("> ").strip()
    if not clean:
        return ""
    match = re.fullmatch(r"⚙\s+(ksp_(?:execute_async|execute|check|kill))(?:\s+(.*))?", clean)
    if not match:
        return line

    tool = match.group(1)
    payload = (match.group(2) or "").strip()
    if tool in {"ksp_check", "ksp_kill"}:
        return f"[agent] {tool}{(' ' + payload) if payload else ''}{line_end}"

    if not payload:
        return f"[agent] {tool}{line_end}"

    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return f"[agent] {tool} {payload}{line_end}"

    if not isinstance(decoded, dict):
        return f"[agent] {tool} {json.dumps(decoded, sort_keys=True)}{line_end}"

    lines = [f"[agent] {tool}"]
    code = decoded.get("code")
    if isinstance(code, str):
        lines.append("  code:")
        lines.extend(f"    {code_line}" for code_line in code.rstrip().splitlines())
    timeout = decoded.get("timeout_s")
    if timeout is not None:
        lines.append(f"  timeout_s: {timeout}")
    extras = {key: value for key, value in decoded.items() if key not in {"code", "timeout_s"}}
    for key, value in sorted(extras.items()):
        lines.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
    return "\n".join(lines) + line_end


def _split_line_ending(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body) :]


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def extract_usage(stdout: str, stderr: str) -> dict[str, int | float | None]:
    text = f"{stdout}\n{stderr}"
    return {
        "input_tokens": _extract_int(text, r"(?:input|prompt)\s+tokens?[:=\s]+([\d,]+)"),
        "output_tokens": _extract_int(text, r"(?:output|completion)\s+tokens?[:=\s]+([\d,]+)"),
        "total_tokens": _extract_int(text, r"total\s+tokens?[:=\s]+([\d,]+)"),
        "cost_usd": _extract_float(text, r"(?:cost|total\s+cost)[:=\s]+\$?([0-9]+(?:\.[0-9]+)?)"),
    }


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _extract_float(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))

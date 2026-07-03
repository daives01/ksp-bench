from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kspbench.config import Scenario
from kspbench.live import LiveKRPCTools


@dataclass(frozen=True)
class ExternalAgentResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class ExternalAgentAdapter:
    def __init__(
        self,
        *,
        provider: str,
        model: str | None = None,
        executable: str | None = None,
        extra_args: list[str] | None = None,
        workspace: Path | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.executable = executable or provider
        self.extra_args = extra_args or []
        self.workspace = workspace or Path.cwd()

    @property
    def agent_metadata(self) -> dict[str, str | None]:
        return {
            "name": self.provider,
            "model": self.model,
            "adapter": f"{self.provider}_cli_live_krpc",
        }

    def run(
        self,
        *,
        scenario: Scenario,
        bridge_url: str,
        timeout_s: float,
        stream_output: bool = True,
    ) -> ExternalAgentResult:
        prompt = build_agent_prompt(scenario=scenario, bridge_url=bridge_url)
        command = self._command(prompt)
        if stream_output:
            return _run_streaming(command, cwd=self.workspace, timeout_s=timeout_s)
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
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

    def _command(self, prompt: str) -> list[str]:
        if self.provider == "codex":
            command = [
                self.executable,
                "exec",
                "--sandbox",
                "workspace-write",
                "--skip-git-repo-check",
                "--ephemeral",
                "--cd",
                str(self.workspace),
            ]
            if self.model:
                command.extend(["--model", self.model])
            command.extend(self.extra_args)
            command.append(prompt)
            return command
        if self.provider == "opencode":
            command = [self.executable, "run", "--dir", str(self.workspace)]
            if self.model:
                command.extend(["--model", self.model])
            command.extend(self.extra_args)
            command.append(prompt)
            return command
        raise ValueError(f"unsupported external adapter: {self.provider}")


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


def build_agent_prompt(*, scenario: Scenario, bridge_url: str) -> str:
    example_payload = json.dumps(
        {
            "code": "\n".join(
                [
                    "vessel.control.throttle = 1.0",
                    "vessel.control.activate_next_stage()",
                    "sleep(5)",
                    "result = getTelemetry()",
                ]
            )
        },
        separators=(",", ":"),
    )
    template = resources.files("kspbench.prompts").joinpath("live_external.md").read_text()
    return template.format(
        body=scenario.body,
        apoapsis_min_m=scenario.target_orbit.apoapsis_min_m,
        apoapsis_max_m=scenario.target_orbit.apoapsis_max_m,
        periapsis_min_m=scenario.target_orbit.periapsis_min_m,
        timeout_s=scenario.timeout_s,
        bridge_url=bridge_url,
        example_payload=example_payload,
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

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from bench.agent_adapters import (
    AGENT_NAME,
    PROJECT_ROOT,
    REFERENCE_DIR,
    OpenCodeAgentAdapter,
    _build_krpc_api_index,
    _format_krpc_api_markdown,
    _format_opencode_json_line,
    _format_opencode_terminal_chunk,
    _format_opencode_terminal_line,
    _run_captured,
    build_agent_prompt,
    extract_usage,
    prepare_opencode_workspace,
)
from bench.config import load_scenario


def test_build_krpc_api_index_extracts_public_python_surface(tmp_path) -> None:
    service = tmp_path / "spacecenter.py"
    service.write_text(
        "class Engine:\n"
        "    @property\n"
        "    def available_thrust(self) -> float:\n"
        "        \"\"\"Available thrust in Newtons. More detail.\"\"\"\n"
        "        return 0.0\n"
        "    @available_thrust.setter\n"
        "    def available_thrust(self, value: float):\n"
        "        pass\n"
        "    def activate(self) -> None:\n"
        "        pass\n"
        "    def _build_call_activate(self):\n"
        "        pass\n",
        encoding="utf-8",
    )

    index = _build_krpc_api_index(service)
    members = index["classes"]["Engine"]["members"]
    markdown = _format_krpc_api_markdown(index)

    assert [member["name"] for member in members] == ["available_thrust", "activate"]
    assert members[0]["signature"] == "available_thrust -> float"
    assert "Available thrust in Newtons" in markdown


def test_opencode_command_uses_project_ksp_agent(tmp_path) -> None:
    adapter = OpenCodeAgentAdapter(
        model="openai/gpt-5.4",
        executable="opencode-test",
        extra_args=["--format", "json"],
        project_root=tmp_path,
    )

    command = adapter._command("fly the rocket")

    assert command[:2] == ["opencode-test", "run"]
    assert "--dir" in command
    assert str(tmp_path) in command
    assert "--agent" in command
    assert AGENT_NAME in command
    assert "--auto" in command
    assert "--format" in command
    assert "json" in command
    assert command[command.index("--variant") + 1] == "low"
    assert command[-1] == "fly the rocket"


def test_opencode_command_passes_requested_thinking_level_as_variant(tmp_path) -> None:
    adapter = OpenCodeAgentAdapter(
        model="openai/gpt-5.4",
        thinking_level="high",
        project_root=tmp_path,
    )

    command = adapter._command("fly the rocket")

    assert command[command.index("--variant") + 1] == "high"


def test_opencode_agent_metadata_includes_thinking_level() -> None:
    adapter = OpenCodeAgentAdapter(model="openai/gpt-5.4", thinking_level="high")

    assert adapter.agent_metadata["model"] == "openai/gpt-5.4"
    assert adapter.agent_metadata["thinking_level"] == "high"


def test_ksp_agent_does_not_force_sampling_temperature() -> None:
    agent_config = (PROJECT_ROOT / ".opencode/agents/ksp.md").read_text(encoding="utf-8")

    assert "temperature:" not in agent_config


def test_opencode_environment_disables_privileged_reset_tool(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KSPBENCH_ENABLE_RESET_TOOL", "1")
    adapter = OpenCodeAgentAdapter(model="openai/gpt-5.4", project_root=tmp_path)
    scenario = load_scenario("scenarios/kerbin_orbit_80km.toml")

    env = adapter._environment(
        scenario=scenario,
        run_dir=None,
        execution_timeout_s=15.0,
        task_timeout_s=180.0,
        max_sleep_s=240.0,
        poll_interval_s=0.5,
    )

    assert env["KSPBENCH_ENABLE_RESET_TOOL"] == "0"
    assert env["KSPBENCH_MODEL"] == "openai/gpt-5.4"


def test_agent_process_stops_when_run_terminated_event_appears(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    def terminate_run() -> None:
        time.sleep(0.2)
        (run_dir / "events.jsonl").write_text(
            json.dumps({"type": "run_terminated", "reason": "test"}) + "\n",
            encoding="utf-8",
        )

    thread = threading.Thread(target=terminate_run)
    thread.start()
    started = time.monotonic()

    result = _run_captured(
        [sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"],
        cwd=tmp_path,
        timeout_s=10.0,
        env=os.environ.copy(),
        run_dir=run_dir,
    )

    thread.join(timeout=2.0)
    assert result.terminated is True
    assert result.timed_out is False
    assert result.stdout == "started\n"
    assert time.monotonic() - started < 5.0


def test_agent_process_can_run_without_a_deadline(tmp_path) -> None:
    result = _run_captured(
        [sys.executable, "-c", "print('finished')"],
        cwd=tmp_path,
        timeout_s=None,
        env=os.environ.copy(),
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.stdout == "finished\n"


def test_prepare_opencode_workspace_copies_literal_krpc_sources(tmp_path) -> None:
    repo = tmp_path / "krpc"
    (repo / "client/python/krpc").mkdir(parents=True)
    (repo / "client/python/krpc/client.py").write_text("class Client: pass\n", encoding="utf-8")
    (repo / "service/SpaceCenter/src/Services").mkdir(parents=True)
    (repo / "service/SpaceCenter/src/Services/Vessel.cs").write_text(
        "class Vessel {}\n",
        encoding="utf-8",
    )
    (repo / "doc/api/space-center").mkdir(parents=True)
    (repo / "doc/api/space-center/vessel.tmpl").write_text(
        "resources_in_decouple_stage\n",
        encoding="utf-8",
    )

    counts = prepare_opencode_workspace(
        tmp_path,
        krpc_repo=repo,
        include_installed=False,
    )
    reference_dir = tmp_path / REFERENCE_DIR

    assert counts == {
        "upstream_docs": 1,
        "upstream_python_client": 1,
        "upstream_spacecenter_service": 1,
    }
    assert (reference_dir / "upstream_python_client/krpc/client.py").exists()
    assert (reference_dir / "upstream_spacecenter_service/Vessel.cs").exists()
    assert (reference_dir / "upstream_docs/api/space-center/vessel.tmpl").exists()
    assert "kRPC source and Python client reference material" in (
        reference_dir / "README.md"
    ).read_text(encoding="utf-8")
    assert "upstream_spacecenter_service" in (
        reference_dir / "SOURCE_INDEX.md"
    ).read_text(encoding="utf-8")


def test_prompt_is_flight_focused_without_internal_leaks() -> None:
    scenario = load_scenario("scenarios/kerbin_orbit_80km.toml")

    prompt = build_agent_prompt(scenario=scenario)

    assert "KSP flight agent" in prompt
    assert "available KSP tools" in prompt
    assert "krpc_reference" in prompt
    assert "ksp_krpc_api" in prompt
    assert "real wall-clock time" in prompt
    assert "ksp_observe" not in prompt
    assert "ksp_throttle" in prompt
    assert "ksp_execute_async" not in prompt
    assert "ksp_docs" not in prompt
    assert "ksp_telemetry" not in prompt
    assert "getDocs" not in prompt
    assert "curl" not in prompt
    assert "benchmark" not in prompt.lower()
    assert "harness" not in prompt.lower()
    assert "wrapper" not in prompt.lower()
    assert "bash" not in prompt.lower()
    assert "vessel" in prompt


def test_ksp_mcp_lists_flight_tools() -> None:
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            "",
        ]
    )

    completed = subprocess.run(
        ["bun", "run", "mcp/server.ts"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    tools = responses[1]["result"]["tools"]
    names = {tool["name"] for tool in tools}
    descriptions = {tool["name"]: tool["description"] for tool in tools}
    assert {
        "observe",
        "throttle",
        "stage",
        "attitude",
        "wait",
        "execute_python",
        "start_task",
        "check_task",
        "stop_task",
        "krpc_api",
    } <= names
    assert "must return quickly" in descriptions["execute_python"]
    assert "Use start_task" in descriptions["execute_python"]
    assert "longer-running" in descriptions["start_task"]
    assert "list_vehicles" not in names
    assert "set_vehicle" not in names
    assert "reset_launchpad" not in names


def test_ksp_mcp_rejects_vehicle_selection_tools() -> None:
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "list_vehicles", "arguments": {}},
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "set_vehicle", "arguments": {"index": 1}},
                }
            ),
            "",
        ]
    )

    completed = subprocess.run(
        ["bun", "run", "mcp/server.ts"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    assert responses[1]["error"]["message"] == "unknown KSP tool: list_vehicles"
    assert responses[2]["error"]["message"] == "unknown KSP tool: set_vehicle"


def test_ksp_mcp_lists_reset_tool_only_when_enabled() -> None:
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
            "",
        ]
    )

    env = {**os.environ, "KSPBENCH_ENABLE_RESET_TOOL": "1"}
    completed = subprocess.run(
        ["bun", "run", "mcp/server.ts"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env=env,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    names = {tool["name"] for tool in responses[1]["result"]["tools"]}
    assert "reset_launchpad" in names


def test_ksp_mcp_rejects_reset_tool_when_disabled() -> None:
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "reset_launchpad", "arguments": {}},
                }
            ),
            "",
        ]
    )

    completed = subprocess.run(
        ["bun", "run", "mcp/server.ts"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    assert responses[1]["error"]["message"] == "unknown KSP tool: reset_launchpad"


def test_ksp_mcp_times_out_hung_foreground_process_and_uses_fresh_next_process(
    tmp_path,
) -> None:
    python = tmp_path / "fake_python.py"
    python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "marker = os.environ['KSPBENCH_HANG_MARKER']\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    if not os.path.exists(marker):\n"
        "        handle = open(marker, 'w')\n"
        "        handle.close()\n"
        "        time.sleep(60)\n"
        "    print(json.dumps({'id': request['id'], 'result': "
        "{'ok': True, 'method': request['method']}}), flush=True)\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    marker = tmp_path / "hung-once"
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "observe", "arguments": {}},
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "observe", "arguments": {}},
                }
            ),
            "",
        ]
    )

    env = {
        **os.environ,
        "KSPBENCH_PYTHON": str(python),
        "KSPBENCH_MCP_TOOL_TIMEOUT": "0.75",
        "KSPBENCH_OBSERVE_TIMEOUT": "0.75",
        "KSPBENCH_HANG_MARKER": str(marker),
    }
    completed = subprocess.run(
        ["bun", "run", "mcp/server.ts"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env=env,
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    assert responses[1]["error"]["code"] == -32000
    assert "timed out" in responses[1]["error"]["message"]
    assert json.loads(responses[2]["result"]["content"][0]["text"]) == {
        "ok": True,
        "method": "observe",
    }


def test_ksp_mcp_supervises_async_task_processes(tmp_path) -> None:
    python = tmp_path / "fake_python.py"
    python.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys, time\n"
        "request = json.loads(sys.stdin.read())\n"
        "status_path = pathlib.Path(request['status_path'])\n"
        "stop_path = pathlib.Path(request['stop_path'])\n"
        "status_path.parent.mkdir(parents=True, exist_ok=True)\n"
        "status_path.write_text(json.dumps({\n"
        "    'ok': True,\n"
        "    'task': {'task_id': request['task_id'], 'status': 'running', 'running': True},\n"
        "    'tasks': [{'task_id': request['task_id'], 'status': 'running', 'running': True}],\n"
        "    'latest_telemetry': None,\n"
        "}))\n"
        "while not stop_path.exists():\n"
        "    time.sleep(0.05)\n"
        "status_path.write_text(json.dumps({\n"
        "    'ok': True,\n"
        "    'task': {'task_id': request['task_id'], 'status': 'stopped', 'running': False},\n"
        "    'tasks': [{'task_id': request['task_id'], 'status': 'stopped', 'running': False}],\n"
        "    'latest_telemetry': None,\n"
        "}))\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    payload = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "start_task",
                        "arguments": {"code": "while True: pass", "timeout_s": 5},
                    },
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "check_task", "arguments": {"task_id": "task-1"}},
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "stop_task", "arguments": {"task_id": "task-1"}},
                }
            ),
            "",
        ]
    )

    completed = subprocess.run(
        ["bun", "run", "mcp/server.ts"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env={
            **os.environ,
            "KSPBENCH_PYTHON": str(python),
            "KSPBENCH_RUN_DIR": str(tmp_path / "run"),
            "KSPBENCH_TASK_STOP_GRACE": "0.2",
        },
    )

    assert completed.returncode == 0
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line]
    assert json.loads(responses[1]["result"]["content"][0]["text"]) == {
        "ok": True,
        "task_id": "task-1",
        "status": "running",
    }
    checked = json.loads(responses[2]["result"]["content"][0]["text"])
    stopped = json.loads(responses[3]["result"]["content"][0]["text"])
    assert checked["task"]["running"] is True
    assert stopped["task"]["running"] is False


def test_extract_usage_parses_common_opencode_text() -> None:
    usage = extract_usage(
        "Prompt tokens: 1,234\nCompletion tokens: 567\nTotal tokens: 1,801\nCost: $0.42",
        "",
    )

    assert usage == {
        "input_tokens": 1234,
        "output_tokens": 567,
        "total_tokens": 1801,
        "cost_usd": 0.42,
    }


def test_format_opencode_terminal_line_pretty_prints_execute_call() -> None:
    line = (
        '⚙ ksp_execute_python {"code":"telemetry = getTelemetry()\\n'
        'vehicle = getVehicleState()\\nprint(\\"Telemetry:\\", telemetry)\\n"}\n'
    )

    formatted = _format_opencode_terminal_line(line)

    assert formatted == (
        "[agent] ksp_execute_python\n"
        "  code:\n"
        "    telemetry = getTelemetry()\n"
        "    vehicle = getVehicleState()\n"
        '    print("Telemetry:", telemetry)\n'
    )


def test_format_opencode_json_line_pretty_prints_python_tool_input() -> None:
    line = json.dumps(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "ksp_start_task",
                "state": {
                    "status": "completed",
                    "input": {
                        "code": "while not should_stop():\n    sleep(0.5)",
                        "timeout_s": 180,
                    },
                },
            },
        }
    )

    assert _format_opencode_json_line(line) == (
        "[agent] ksp_start_task\n"
        "  code:\n"
        "    while not should_stop():\n"
        "        sleep(0.5)\n"
        "  timeout_s: 180\n"
    )


def test_format_opencode_json_line_keeps_non_python_tool_compact() -> None:
    line = json.dumps(
        {
            "type": "tool_use",
            "part": {
                "tool": "ksp_throttle",
                "state": {"input": {"value": 1.0}},
            },
        }
    )

    assert _format_opencode_json_line(line) == "[agent] ksp_throttle\n"


def test_format_opencode_terminal_line_leaves_non_ksp_tool_lines_alone() -> None:
    assert _format_opencode_terminal_line("⚙ ksp_help Unknown\n") == "⚙ ksp_help Unknown\n"
    assert (
        _format_opencode_terminal_line("\x1b[2K\r> ⚙ ksp_help Unknown\r\n")
        == "\x1b[2K\r> ⚙ ksp_help Unknown\r\n"
    )
    assert _format_opencode_terminal_line("plain output\n") == "plain output\n"


def test_format_opencode_terminal_chunk_handles_carriage_return_lines() -> None:
    chunk = (
        '\x1b[2K\r> ⚙ ksp_execute_python {"code":"t = getTelemetry()\\nprint(t)"}\r\n'
    )

    assert _format_opencode_terminal_chunk(chunk) == (
        "[agent] ksp_execute_python\n"
        "  code:\n"
        "    t = getTelemetry()\n"
        "    print(t)\r\n"
    )

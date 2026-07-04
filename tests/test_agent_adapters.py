from __future__ import annotations

import json
import subprocess

from bench.agent_adapters import (
    AGENT_NAME,
    REFERENCE_DIR,
    OpenCodeAgentAdapter,
    _format_opencode_terminal_chunk,
    _format_opencode_terminal_line,
    build_agent_prompt,
    extract_usage,
    prepare_opencode_workspace,
)
from bench.config import load_scenario


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
    assert command[-1] == "fly the rocket"


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
    assert {
        "observe",
        "throttle",
        "stage",
        "list_vehicles",
        "set_vehicle",
        "attitude",
        "wait",
        "execute_python",
        "start_task",
        "check_task",
        "stop_task",
    } <= names


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

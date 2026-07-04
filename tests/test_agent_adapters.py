from __future__ import annotations

import json
import urllib.request
from types import SimpleNamespace

from kspbench.agent_adapters import (
    OpenCodeAgentAdapter,
    ToolBridgeServer,
    _format_opencode_terminal_chunk,
    _format_opencode_terminal_line,
    build_agent_prompt,
    extract_usage,
    write_opencode_workspace,
)
from kspbench.artifacts import RunArtifacts
from kspbench.config import load_scenario
from kspbench.live import LiveKRPCTools
from kspbench.telemetry import TelemetrySample


class FakeController:
    def __init__(self) -> None:
        self.space_center = SimpleNamespace(
            active_vessel=None,
            ut=100.0,
            warp_calls=[],
        )
        self.space_center.warp_to = self._warp_to
        self.vessel = SimpleNamespace(
            name="Kerbal X",
            control=SimpleNamespace(throttle=0.0),
            orbit=SimpleNamespace(body=SimpleNamespace(atmosphere_depth=0.0)),
        )
        self.space_center.active_vessel = self.vessel
        self.conn = SimpleNamespace(
            space_center=self.space_center,
        )
        self.met = 0.0

    def _warp_to(
        self,
        ut: float,
        *,
        max_rails_rate: int,
        max_physics_rate: int,
    ) -> None:
        self.space_center.warp_calls.append(
            {
                "ut": ut,
                "max_rails_rate": max_rails_rate,
                "max_physics_rate": max_physics_rate,
            }
        )
        self.space_center.ut = ut

    def read_telemetry(self) -> TelemetrySample:
        self.met += 1.0
        return TelemetrySample(
            mission_elapsed_s=self.met,
            altitude_m=100.0 + self.met,
            surface_altitude_m=100.0 + self.met,
            apoapsis_m=1000.0,
            periapsis_m=-500000.0,
            surface_speed_m_s=10.0,
            orbital_speed_m_s=100.0,
            vertical_speed_m_s=1.0,
            pitch_deg=90.0,
            heading_deg=90.0,
            roll_deg=0.0,
            stage=1,
            liquid_fuel=100.0,
            oxidizer=120.0,
            solid_fuel=0.0,
            dynamic_pressure_pa=0.0,
            situation="pre_launch",
            body="Kerbin",
            controllable=True,
            intact=True,
        )

    def read_vehicle_state(self) -> dict[str, object]:
        return {
            "name": self.vessel.name,
            "current_stage": 1,
            "throttle": self.vessel.control.throttle,
            "current_stage_resources": {"LiquidFuel": 42.0, "Oxidizer": 50.0},
        }


def test_opencode_command_uses_locked_agent_and_isolated_workspace(tmp_path) -> None:
    adapter = OpenCodeAgentAdapter(
        model="openai/gpt-5.4",
        executable="opencode-test",
        extra_args=["--format", "json"],
    )

    command = adapter._command("fly the rocket", workspace=tmp_path)

    assert command[:2] == ["opencode-test", "run"]
    assert "--dir" in command
    assert str(tmp_path) in command
    assert "--agent" in command
    assert "kspbench" in command
    assert "--auto" not in command
    assert "--format" in command
    assert "json" in command
    assert command[-1] == "fly the rocket"


def test_opencode_workspace_denies_builtin_tools(tmp_path) -> None:
    write_opencode_workspace(
        tmp_path,
        bridge_url="http://127.0.0.1:1234",
        model="openai/gpt-5.4",
    )

    config = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    tool_source = (tmp_path / ".opencode" / "tools" / "ksp.ts").read_text(encoding="utf-8")
    reference_dir = tmp_path / "krpc_reference"
    reference = (reference_dir / "space_center_stubs.py").read_text(
        encoding="utf-8"
    )

    assert config["permission"]["*"] == "deny"
    assert config["permission"]["bash"] == "deny"
    assert config["permission"]["read"] == "allow"
    assert config["permission"]["grep"] == "allow"
    assert config["permission"]["glob"] == "allow"
    assert config["permission"]["edit"] == "deny"
    assert config["permission"]["external_directory"] == "deny"
    assert config["permission"]["ksp_*"] == "allow"
    assert config["agent"]["kspbench"]["permission"]["ksp_*"] == "allow"
    assert config["agent"]["kspbench"]["model"] == "openai/gpt-5.4"
    assert config["agent"]["kspbench"]["prompt"]
    assert "http://127.0.0.1:1234" in tool_source
    assert "export const help" not in tool_source
    assert "export const observe" in tool_source
    assert "export const throttle" in tool_source
    assert "export const stage" in tool_source
    assert "export const pitch_heading" in tool_source
    assert "export const prograde" in tool_source
    assert "export const wait" in tool_source
    assert "export const execute" in tool_source
    assert "export const start_task" in tool_source
    assert "export const check_task" in tool_source
    assert "export const stop_task" in tool_source
    assert "export const execute_async" not in tool_source
    assert "export const telemetry" not in tool_source
    assert "export const vehicle" not in tool_source
    assert "target_pitch_and_heading" in reference
    assert "target_prograde" not in reference
    assert "getTelemetry()" in (reference_dir / "README.md").read_text(encoding="utf-8")
    source_index = reference_dir / "PYTHON_CLIENT_SOURCE.md"
    if source_index.exists():
        source_text = source_index.read_text(encoding="utf-8")
        spacecenter_source = reference_dir / "python_client" / "services" / "spacecenter.py"
        assert "python_client/services/spacecenter.py" in source_text
        assert spacecenter_source.exists()
        assert "class Vessel" in spacecenter_source.read_text(encoding="utf-8")


def test_prompt_names_custom_tools_not_raw_http() -> None:
    scenario = load_scenario("scenarios/kerbin_orbit_80km.toml")

    prompt = build_agent_prompt(scenario=scenario)

    assert "ksp_help" not in prompt
    assert "ksp_observe" in prompt
    assert "ksp_throttle" in prompt
    assert "ksp_stage" in prompt
    assert "ksp_pitch_heading" in prompt
    assert "ksp_prograde" in prompt
    assert "ksp_wait" in prompt
    assert "ksp_execute" in prompt
    assert "ksp_start_task" in prompt
    assert "ksp_check_task" in prompt
    assert "ksp_stop_task" in prompt
    assert "ksp_execute_async" not in prompt
    assert "krpc_reference/" in prompt
    assert "real wall-clock time" in prompt
    assert "ksp_docs" not in prompt
    assert "ksp_telemetry" not in prompt
    assert "getDocs" not in prompt
    assert "curl" not in prompt
    assert "vessel" in prompt


def test_tool_bridge_exposes_ksp_tools(tmp_path) -> None:
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=RunArtifacts.create(tmp_path, "bridge"),
    )

    with ToolBridgeServer(tools) as bridge:
        observe = _post_json(f"{bridge.url}/observe", {})
        throttle = _post_json(f"{bridge.url}/throttle", {"value": 0.7})
        execute = _post_json(
            f"{bridge.url}/execute",
            {
                "code": (
                    "result = {'throttle': vessel.control.throttle, "
                    "'body': getTelemetry()['body']}"
                )
            },
        )
        syntax_error = _post_json(f"{bridge.url}/execute", {"code": "if True print('bad')"})
        task_started = _post_json(
            f"{bridge.url}/start_task",
            {"code": "result = {'ok': True}"},
        )
        check = _post_json(f"{bridge.url}/check_task", {})
        stop = _post_json(f"{bridge.url}/stop_task", {})

    assert observe["ok"] is True
    assert throttle["ok"] is True
    assert execute["ok"] is True
    assert execute["result"] == {"throttle": 0.7, "body": "Kerbin"}
    assert syntax_error["ok"] is False
    assert syntax_error["error_type"] == "FlightToolError"
    assert "invalid syntax" in syntax_error["error"]
    assert task_started["ok"] is True
    assert check["ok"] is True
    assert "task" in check
    assert stop["ok"] is True
    assert tools.actions[0]["type"] == "observe"
    assert tools.actions[1]["type"] == "set_throttle"
    assert "execute_python" in [action["type"] for action in tools.actions]


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
        '⚙ ksp_execute {"code":"telemetry = getTelemetry()\\n'
        'vehicle = getVehicleState()\\nprint(\\"Telemetry:\\", telemetry)\\n"}\n'
    )

    formatted = _format_opencode_terminal_line(line)

    assert formatted == (
        "[agent] ksp_execute\n"
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
        '\x1b[2K\r> ⚙ ksp_execute {"code":"t = getTelemetry()\\nprint(t)"}\r\n'
    )

    assert _format_opencode_terminal_chunk(chunk) == (
        "[agent] ksp_execute\n"
        "  code:\n"
        "    t = getTelemetry()\n"
        "    print(t)\r\n"
    )


def _get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=2.0) as response:
        payload = response.read().decode("utf-8")
    result = json.loads(payload)
    assert isinstance(result, dict)
    return result


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2.0) as response:
        response_payload = response.read().decode("utf-8")
    result = json.loads(response_payload)
    assert isinstance(result, dict)
    return result

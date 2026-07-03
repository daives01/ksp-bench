from __future__ import annotations

import json
import urllib.request
from types import SimpleNamespace

from kspbench.agent_adapters import (
    OpenCodeAgentAdapter,
    ToolBridgeServer,
    build_agent_prompt,
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
    assert "--auto" in command
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

    assert config["permission"]["*"] == "deny"
    assert config["permission"]["bash"] == "deny"
    assert config["permission"]["read"] == "deny"
    assert config["permission"]["edit"] == "deny"
    assert config["permission"]["external_directory"] == "deny"
    assert config["permission"]["ksp_*"] == "allow"
    assert config["agent"]["kspbench"]["permission"]["ksp_*"] == "allow"
    assert config["agent"]["kspbench"]["model"] == "openai/gpt-5.4"
    assert "http://127.0.0.1:1234" in tool_source
    assert "export const telemetry" in tool_source
    assert "export const execute" in tool_source


def test_prompt_names_custom_tools_not_raw_http() -> None:
    scenario = load_scenario("scenarios/kerbin_orbit_80km.toml")

    prompt = build_agent_prompt(scenario=scenario)

    assert "ksp_telemetry" in prompt
    assert "ksp_execute" in prompt
    assert "curl" not in prompt
    assert "vessel" in prompt


def test_tool_bridge_exposes_telemetry_and_execute(tmp_path) -> None:
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=RunArtifacts.create(tmp_path, "bridge"),
    )

    with ToolBridgeServer(tools) as bridge:
        telemetry = _get_json(f"{bridge.url}/telemetry")
        execute = _post_json(
            f"{bridge.url}/execute",
            {"code": "vessel.control.throttle = 0.7\nresult = vessel.control.throttle"},
        )
        wait = _post_json(f"{bridge.url}/wait", {"seconds": 10})

    assert telemetry["body"] == "Kerbin"
    assert execute["ok"] is True
    assert execute["result"] == 0.7
    assert wait["ok"] is True
    assert wait["time_warp_used"] is True
    assert tools.actions[0]["type"] == "execute_krpc"
    assert tools.actions[1]["type"] == "wait"


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

from __future__ import annotations

from types import SimpleNamespace

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


def test_execute_krpc_runs_snippet_and_logs_action(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    result = tools.executeKRPC(
        "vessel.control.throttle = 0.5\nresult = {'throttle': vessel.control.throttle}"
    )

    assert result["ok"] is True
    assert result["result"] == {"throttle": 0.5}
    assert tools.actions[0]["type"] == "execute_krpc"
    assert (artifacts.run_dir / "action_log.jsonl").exists()


def test_execute_krpc_rejects_imports(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    result = tools.executeKRPC("import os")

    assert result["ok"] is False
    assert result["error_type"] == "KRPCExecutionError"
    assert tools.invalid_actions == 1


def test_execute_krpc_rejects_harness_reset_calls(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    result = tools.executeKRPC("space_center.revert_to_launch()")

    assert result["ok"] is False
    assert result["error_type"] == "KRPCExecutionError"
    assert "reserved for the benchmark harness" in result["error"]
    assert tools.invalid_actions == 1


def test_observation_tools_return_snapshots(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    telemetry = tools.getTelemetry()
    state = tools.getVehicleState()

    assert telemetry["body"] == "Kerbin"
    assert state["name"] == "Kerbal X"
    assert len(tools.telemetry) == 1


def test_wait_uses_time_warp_above_threshold(tmp_path) -> None:
    controller = FakeController()
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=controller,
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        warp_threshold_s=5.0,
    )

    result = tools.wait(10.0)

    assert result["ok"] is True
    assert result["time_warp_used"] is True
    assert controller.space_center.warp_calls == [
        {"ut": 110.0, "max_rails_rate": 100000, "max_physics_rate": 4}
    ]
    assert tools.actions[0]["type"] == "wait"

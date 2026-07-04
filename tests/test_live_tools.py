from __future__ import annotations

import threading
import time
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


class CrashedController(FakeController):
    def read_telemetry(self) -> TelemetrySample:
        sample = super().read_telemetry()
        return TelemetrySample(
            **{
                **sample.to_dict(),
                "controllable": False,
                "intact": False,
                "situation": "crashed",
            }
        )


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


def test_execute_krpc_allows_import_math(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    result = tools.executeKRPC("import math\nresult = round(math.sqrt(9))")

    assert result["ok"] is True
    assert result["result"] == 3


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
    assert state["current_stage_resources"]["LiquidFuel"] == 42.0
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


def test_wait_does_not_time_warp_in_atmosphere(tmp_path) -> None:
    controller = FakeController()
    controller.vessel.orbit.body.atmosphere_depth = 70000.0
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=controller,
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        warp_threshold_s=0.05,
        poll_interval_s=0.2,
    )

    result = tools.wait(0.1)

    assert result["ok"] is True
    assert result["time_warp_used"] is False
    assert controller.space_center.warp_calls == []


def test_wait_rejects_long_atmospheric_wait(tmp_path) -> None:
    controller = FakeController()
    controller.vessel.orbit.body.atmosphere_depth = 70000.0
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=controller,
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        max_atmospheric_sleep_s=2.0,
    )

    result = tools.wait(10.0)

    assert result["ok"] is False
    assert result["error_type"] == "AtmosphericWaitDisallowed"
    assert tools.invalid_actions == 1


def test_execute_krpc_rejects_long_atmospheric_sleep(tmp_path) -> None:
    controller = FakeController()
    controller.vessel.orbit.body.atmosphere_depth = 70000.0
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=controller,
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        max_atmospheric_sleep_s=2.0,
    )

    result = tools.executeKRPC("sleep(10)")

    assert result["ok"] is False
    assert result["error_type"] == "AtmosphericWaitDisallowed"


def test_execute_krpc_timeout_works_from_worker_thread(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )
    result_holder: list[dict[str, object]] = []

    thread = threading.Thread(
        target=lambda: result_holder.append(
            tools.executeKRPC("while True:\n    x = 1 + 1", timeout_s=0.05)
        )
    )
    thread.start()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert result_holder[0]["ok"] is False
    assert result_holder[0]["error_type"] == "KRPCExecutionTimeout"
    assert tools.terminated is False
    assert tools.termination_reason is None


def test_execute_krpc_allows_calls_after_timeout(tmp_path) -> None:
    controller = FakeController()
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=controller,
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    timeout = tools.executeKRPC("while True:\n    x = 1 + 1", timeout_s=0.05)
    retry = tools.executeKRPC("result = getTelemetry()")

    assert timeout["error_type"] == "KRPCExecutionTimeout"
    assert retry["ok"] is True
    assert retry["result"]["mission_elapsed_s"] >= 1.0


def test_execute_krpc_allows_exception_handlers(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
    )

    result = tools.executeKRPC(
        "try:\n    raise Exception('debug')\nexcept Exception as exc:\n    result = str(exc)"
    )

    assert result["ok"] is True
    assert result["result"] == "debug"


def test_execute_krpc_async_completes_and_reports_status(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        poll_interval_s=0.01,
    )

    started = tools.executeKRPCAsync(
        "sleep(0.02)\nprint('done')\nresult = {'met': getTelemetry()['mission_elapsed_s']}"
    )
    script_id = started["script_id"]

    deadline = time.monotonic() + 1.0
    status = tools.checkAsync(script_id)
    while status["script"]["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        status = tools.checkAsync(script_id)

    assert started["ok"] is True
    assert status["ok"] is True
    assert status["script"]["status"] == "done"
    assert status["script"]["result"]["met"] >= 1.0
    assert "done" in status["script"]["stdout"]


def test_kill_async_requests_cooperative_stop(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=FakeController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        poll_interval_s=0.01,
    )

    started = tools.executeKRPCAsync(
        "while not should_stop():\n    sleep(0.02)\nprint('stopping')",
        timeout_s=1.0,
    )
    script_id = started["script_id"]
    killed = tools.killAsync(script_id)

    deadline = time.monotonic() + 1.0
    status = tools.checkAsync(script_id)
    while status["script"]["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        status = tools.checkAsync(script_id)

    assert killed["ok"] is True
    assert status["script"]["status"] == "stopped"
    assert status["script"]["error_type"] == "AsyncScriptStopped"


def test_wait_stops_when_vessel_is_destroyed(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "live")
    tools = LiveKRPCTools(
        controller=CrashedController(),
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=artifacts,
        poll_interval_s=0.01,
    )

    result = tools.wait(10.0)

    assert result["ok"] is False
    assert result["error_type"] == "KSPRunTerminated"
    assert result["error"] == "vessel_not_intact"
    assert tools.terminated is True

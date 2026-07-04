from __future__ import annotations

import json
import time
from types import SimpleNamespace

from bench.artifacts import RunArtifacts
from bench.config import load_scenario
from bench.krpc_client import KRPCController
from bench.live import FlightSession
from bench.telemetry import TelemetrySample


class FakeAutoPilot:
    def __init__(self) -> None:
        self.engaged = False
        self.pitch = None
        self.heading = None
        self.reference_frame = None
        self.target_direction = None

    def engage(self) -> None:
        self.engaged = True

    def target_pitch_and_heading(self, pitch: float, heading: float) -> None:
        self.pitch = pitch
        self.heading = heading


class FakeController:
    def __init__(self) -> None:
        self.body = SimpleNamespace(
            atmosphere_depth=0.0,
            reference_frame="surface-frame",
            non_rotating_reference_frame="orbital-frame",
        )
        self.vessel = SimpleNamespace(
            name="Kerbal X",
            control=SimpleNamespace(
                throttle=0.0,
                current_stage=1,
                activate_next_stage=lambda: ["part"],
            ),
            auto_pilot=FakeAutoPilot(),
            orbit=SimpleNamespace(body=self.body),
            surface_reference_frame="vessel-surface-frame",
            type="ship",
            situation="pre_launch",
            met=0.0,
            flight=lambda _frame: SimpleNamespace(
                prograde=(1.0, 0.0, 0.0),
                retrograde=(-1.0, 0.0, 0.0),
                normal=(0.0, 1.0, 0.0),
                anti_normal=(0.0, -1.0, 0.0),
                radial=(0.0, 0.0, 1.0),
                anti_radial=(0.0, 0.0, -1.0),
            ),
        )
        self.conn = SimpleNamespace(
            space_center=SimpleNamespace(active_vessel=self.vessel, vessels=[self.vessel])
        )
        self.met = 0.0

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
            time_to_apoapsis_s=30.0,
            time_to_periapsis_s=120.0,
            eccentricity=0.1,
            inclination_deg=0.0,
        )

    def read_vehicle_state(self) -> dict[str, object]:
        return {
            "name": self.vessel.name,
            "current_stage": 1,
            "throttle": self.vessel.control.throttle,
            "current_stage_resources": {"LiquidFuel": 42.0, "Oxidizer": 50.0},
        }

    def list_vessels(self) -> dict[str, object]:
        vehicles = [
            {"index": index, "name": vessel.name, "current": vessel is self.vessel}
            for index, vessel in enumerate(self.conn.space_center.vessels)
        ]
        return {
            "current_index": next(
                (vehicle["index"] for vehicle in vehicles if vehicle["current"]),
                None,
            ),
            "current": next(
                (vehicle for vehicle in vehicles if vehicle["current"]),
                None,
            ),
            "vehicles": vehicles,
        }

    def select_vessel(
        self,
        *,
        name: str | None = None,
        index: int | None = None,
        make_active: bool = True,
    ) -> dict[str, object]:
        if index is None:
            matches = [
                (candidate_index, vessel)
                for candidate_index, vessel in enumerate(self.conn.space_center.vessels)
                if vessel.name == name
            ]
            index, vessel = matches[0]
        else:
            vessel = self.conn.space_center.vessels[index]
        self.vessel = vessel
        if make_active:
            self.conn.space_center.active_vessel = vessel
        return {
            "selected": {"index": index, "name": vessel.name, "current": True},
            "made_active": make_active,
        }

    def close(self) -> None:
        return


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


class LostVesselController(FakeController):
    def read_telemetry(self) -> TelemetrySample:
        raise RuntimeError("Error receiving message\r\nInstance not found")


class PadFuelDrainController(FakeController):
    def __init__(self) -> None:
        super().__init__()
        self.vessel.control.throttle = 1.0

    def read_telemetry(self) -> TelemetrySample:
        sample = super().read_telemetry()
        if self.met < 2.0:
            return sample
        return TelemetrySample(
            **{
                **sample.to_dict(),
                "mission_elapsed_s": 11.0,
                "altitude_m": 80.0,
                "surface_altitude_m": 7.0,
                "surface_speed_m_s": 0.0,
                "vertical_speed_m_s": 0.0,
                "liquid_fuel": 10.0,
                "oxidizer": 10.0,
                "situation": "landed",
            }
        )


class VacuumWarpController(FakeController):
    def __init__(self) -> None:
        super().__init__()
        self.conn.space_center.ut = 100.0
        self.conn.space_center.warp_calls = []
        self.conn.space_center.warp_to = self._warp_to

    def _warp_to(
        self,
        ut: float,
        *,
        max_rails_rate: int,
        max_physics_rate: int,
    ) -> None:
        self.conn.space_center.warp_calls.append(
            {
                "ut": ut,
                "max_rails_rate": max_rails_rate,
                "max_physics_rate": max_physics_rate,
            }
        )
        self.conn.space_center.ut = ut

    def read_telemetry(self) -> TelemetrySample:
        self.met = max(self.met + 1.0, self.conn.space_center.ut - 100.0)
        sample = super().read_telemetry()
        return TelemetrySample(
            **{
                **sample.to_dict(),
                "mission_elapsed_s": self.met,
                "altitude_m": 80000.0,
                "surface_altitude_m": 80000.0,
                "situation": "flying",
            }
        )


def _session(tmp_path, controller=None, **kwargs) -> FlightSession:
    controller = controller or FakeController()
    kwargs.setdefault("task_controller_factory", FakeController)
    return FlightSession(
        controller=controller,
        scenario=load_scenario("scenarios/kerbin_orbit_80km.toml"),
        artifacts=RunArtifacts.create(tmp_path, "live"),
        **kwargs,
    )


def test_observe_returns_telemetry_vehicle_and_target(tmp_path) -> None:
    session = _session(tmp_path)

    result = session.observe()

    assert result["ok"] is True
    assert result["telemetry"]["body"] == "Kerbin"
    assert result["vehicle"]["current_stage_resources"]["LiquidFuel"] == 42.0
    assert result["target_orbit"]["periapsis_min_m"] == 70000


def test_structured_controls_log_actions(tmp_path) -> None:
    controller = FakeController()
    session = _session(tmp_path, controller=controller)

    throttle = session.set_throttle(0.7)
    stage = session.stage()
    session.set_attitude("pitch_heading", pitch=80, heading=90)
    prograde = session.set_attitude("prograde")
    normal = session.set_attitude("normal")

    assert throttle["ok"] is True
    assert controller.vessel.control.throttle == 0.7
    assert stage["activated_parts"] == 1
    assert controller.vessel.auto_pilot.pitch == 80
    assert prograde["reference_frame"] == "orbital"
    assert normal["mode"] == "normal"
    assert controller.vessel.auto_pilot.target_direction == (0.0, 1.0, 0.0)
    assert [action["type"] for action in session.actions] == [
        "set_throttle",
        "stage",
        "set_attitude",
        "set_attitude",
        "set_attitude",
    ]


def test_krpc_controller_reverts_to_unpaused_launchpad() -> None:
    scenario = load_scenario("scenarios/kerbin_orbit_80km.toml")
    launch_vessel = SimpleNamespace(name="Kerbal X")
    space_center = SimpleNamespace(
        active_vessel=launch_vessel,
        paused=True,
        revert_calls=0,
    )

    def revert_to_launch() -> None:
        space_center.revert_calls += 1
        space_center.paused = True
        space_center.active_vessel = launch_vessel

    space_center.revert_to_launch = revert_to_launch
    controller = KRPCController(SimpleNamespace(space_center=space_center), scenario)

    controller.prepare_for_launchpad_run(wait_s=0.0)

    assert space_center.revert_calls == 1
    assert space_center.paused is False
    assert controller.vessel is launch_vessel


def test_execute_python_is_escape_hatch_and_rejects_unsafe_import(tmp_path) -> None:
    session = _session(tmp_path)

    ok = session.execute_python(
        "vessel.control.throttle = 0.5\nresult = {'throttle': vessel.control.throttle}"
    )
    bad = session.execute_python("import os")

    assert ok["ok"] is True
    assert ok["result"] == {"throttle": 0.5}
    assert bad["ok"] is False
    assert bad["error_type"] == "FlightToolError"


def test_execute_python_exposes_flat_observe_and_tool_aliases(tmp_path) -> None:
    session = _session(tmp_path)

    result = session.execute_python(
        "telem = observe()\n"
        "ksp_throttle(0.25)\n"
        "ksp_attitude('pitch_heading', pitch=75, heading=90)\n"
        "result = {\n"
        "    'altitude': telem['altitude_m'],\n"
        "    'vehicle': telem['vehicle']['name'],\n"
        "    'throttle': vessel.control.throttle,\n"
        "}\n"
    )

    assert result["ok"] is True
    assert result["result"]["altitude"] > 0
    assert result["result"]["vehicle"] == "Kerbal X"
    assert result["result"]["throttle"] == 0.25


def test_multiple_background_tasks_run_and_stop_by_id(tmp_path) -> None:
    session = _session(tmp_path, poll_interval_s=0.01)

    first = session.start_task("while not should_stop():\n    sleep(0.02)", timeout_s=1.0)
    second = session.start_task("while not should_stop():\n    sleep(0.02)", timeout_s=1.0)
    status = session.check_task()
    ambiguous = session.stop_task()
    stopped = session.stop_task(task_id=first["task_id"])

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["task_id"] != second["task_id"]
    assert {task["task_id"] for task in status["tasks"]} == {
        first["task_id"],
        second["task_id"],
    }
    assert ambiguous["ok"] is False
    assert "multiple tasks" in ambiguous["error"]
    assert stopped["ok"] is True
    session.stop_task(task_id=second["task_id"])


def test_foreground_tools_work_while_background_task_runs_on_separate_controller(
    tmp_path,
) -> None:
    task_controllers: list[FakeController] = []

    def make_task_controller() -> FakeController:
        controller = FakeController()
        task_controllers.append(controller)
        return controller

    session = _session(
        tmp_path,
        poll_interval_s=0.01,
        task_controller_factory=make_task_controller,
    )

    started = session.start_task("while not should_stop():\n    sleep(0.02)", timeout_s=1.0)
    observed = session.observe()
    throttled = session.set_throttle(0.5)
    executed = session.execute_python("print('hi')")
    stopped = session.stop_task()

    assert started["ok"] is True
    assert observed["ok"] is True
    assert throttled["ok"] is True
    assert executed["ok"] is True
    assert task_controllers
    assert stopped["ok"] is True


def test_background_task_reports_result_and_stdout(tmp_path) -> None:
    session = _session(tmp_path, poll_interval_s=0.01)

    started = session.start_task(
        "print('done')\n"
        "result = {'met': getTelemetry()['mission_elapsed_s']}"
    )
    assert started["ok"] is True

    deadline = time.monotonic() + 1.0
    status = session.check_task()
    while status["task"]["running"] and time.monotonic() < deadline:
        time.sleep(0.02)
        status = session.check_task()

    assert status["task"]["status"] == "done"
    assert status["task"]["result"]["met"] > 0
    assert "done" in status["task"]["stdout"]


def test_wait_in_atmosphere_does_not_time_warp(tmp_path) -> None:
    controller = FakeController()
    controller.body.atmosphere_depth = 70000.0
    session = _session(tmp_path, controller=controller, max_atmospheric_wait_s=2.0)

    result = session.wait(2.0)

    assert result["ok"] is True


def test_vehicle_selection_is_stateful(tmp_path) -> None:
    controller = FakeController()
    other = SimpleNamespace(**controller.vessel.__dict__)
    other.name = "Mun Probe"
    controller.conn.space_center.vessels = [controller.vessel, other]
    session = _session(tmp_path, controller=controller)

    listed = session.list_vehicles()
    selected = session.set_vehicle(index=1)
    observed = session.observe()

    assert listed["vehicles"][0]["name"] == "Kerbal X"
    assert selected["selected"]["name"] == "Mun Probe"
    assert observed["vehicle"]["name"] == "Mun Probe"
    assert controller.conn.space_center.active_vessel is other


def test_wait_stops_when_vessel_is_destroyed(tmp_path) -> None:
    session = _session(tmp_path, controller=CrashedController(), poll_interval_s=0.01)

    result = session.wait(10.0)

    assert result["ok"] is False
    assert result["error_type"] == "FlightTerminated"
    events = [
        json.loads(line)
        for line in (session.artifacts.run_dir / "events.jsonl").read_text().splitlines()
    ]
    assert any(event["type"] == "run_terminated" for event in events)


def test_wait_stops_when_vessel_is_landed_and_burning_fuel(tmp_path) -> None:
    session = _session(tmp_path, controller=PadFuelDrainController(), poll_interval_s=0.01)
    session.observe()

    result = session.wait(1.0)

    assert result["ok"] is False
    assert result["error_type"] == "FlightTerminated"
    assert result["error"] == "vessel_landed_burning_fuel"


def test_wait_uses_time_warp_outside_atmosphere_and_finishes_with_polling(tmp_path) -> None:
    controller = VacuumWarpController()
    session = _session(tmp_path, controller=controller, poll_interval_s=0.01)
    session.observe()

    result = session.wait(30.0)

    assert result["ok"] is True
    assert result["telemetry"]["mission_elapsed_s"] >= 31.0
    assert controller.conn.space_center.warp_calls == [
        {
            "ut": 127.0,
            "max_rails_rate": 1000,
            "max_physics_rate": 4,
        }
    ]


def test_wait_treats_lost_krpc_vessel_instance_as_terminated(tmp_path) -> None:
    session = _session(tmp_path, controller=LostVesselController(), poll_interval_s=0.01)

    result = session.wait(1.0)

    assert result["ok"] is False
    assert result["error_type"] == "FlightTerminated"
    assert result["error"] == "vessel_lost"
    assert session.terminated is True
    assert session.termination_reason == "vessel_lost"
    events = [
        json.loads(line)
        for line in (session.artifacts.run_dir / "events.jsonl").read_text().splitlines()
    ]
    terminated = [event for event in events if event["type"] == "run_terminated"]
    assert len(terminated) == 1
    assert terminated[0]["reason"] == "vessel_lost"
    assert terminated[0]["error_type"] == "RuntimeError"


def test_observe_returns_error_after_lost_vessel_instance(tmp_path) -> None:
    session = _session(tmp_path, controller=LostVesselController())

    result = session.observe()

    assert result["ok"] is False
    assert result["error_type"] == "FlightTerminated"
    assert result["error"] == "vessel_lost"

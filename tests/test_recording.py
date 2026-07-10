from __future__ import annotations

import time

from bench.artifacts import RunArtifacts
from bench.recording import TelemetryRecorder
from bench.telemetry import TelemetrySample
from bench.termination import unrecoverable_no_propulsion_reason


class FakeController:
    def __init__(self) -> None:
        self.met = 0.0
        self.closed = False

    def read_telemetry(self) -> TelemetrySample:
        self.met += 1.0
        return TelemetrySample(
            mission_elapsed_s=self.met,
            altitude_m=self.met,
            surface_altitude_m=self.met,
            apoapsis_m=100.0,
            periapsis_m=-100.0,
            surface_speed_m_s=1.0,
            orbital_speed_m_s=1.0,
            vertical_speed_m_s=1.0,
            pitch_deg=90.0,
            heading_deg=90.0,
            roll_deg=0.0,
            stage=1,
            liquid_fuel=1.0,
            oxidizer=1.0,
            solid_fuel=0.0,
            dynamic_pressure_pa=0.0,
            situation="flying",
            body="Kerbin",
            controllable=True,
            intact=True,
        )

    def close(self) -> None:
        self.closed = True

    def read_vehicle_state(self) -> dict[str, object]:
        return {
            "engines": [],
            "decouplers": [],
            "next_stage": None,
        }


def test_recorder_samples_independently_at_fixed_interval(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "run")
    controller = FakeController()
    recorder = TelemetryRecorder(
        artifacts=artifacts,
        controller_factory=lambda: controller,  # type: ignore[arg-type]
        interval_s=0.01,
    )

    recorder.start()
    time.sleep(0.035)
    recorder.stop()

    lines = (artifacts.run_dir / "telemetry.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 3
    assert controller.closed is True


class DeadStickController(FakeController):
    def read_telemetry(self) -> TelemetrySample:
        sample = super().read_telemetry()
        return TelemetrySample(
            **{
                **sample.to_dict(),
                "mission_elapsed_s": 20.0 + self.met,
                "liquid_fuel": 0.0,
                "oxidizer": 0.0,
                "solid_fuel": 0.0,
                "remaining_delta_v_m_s": 0.0,
                "situation": "sub_orbital",
            }
        )

    def read_vehicle_state(self) -> dict[str, object]:
        return {
            "available_thrust": 60000.0,
            "engines": [{"has_fuel": False, "max_thrust": 60000.0}],
            "decouplers": [{"stage": 1}],
            "next_stage": {
                "activate_engines": [],
                "resources": {"LiquidFuel": 0.0, "Oxidizer": 0.0, "SolidFuel": 0.0},
            },
        }


def test_recorder_terminates_confirmed_dead_stick_without_agent_calls(tmp_path) -> None:
    artifacts = RunArtifacts.create(tmp_path, "run")
    controller = DeadStickController()
    recorder = TelemetryRecorder(
        artifacts=artifacts,
        controller_factory=lambda: controller,  # type: ignore[arg-type]
        interval_s=0.01,
        terminal_reason=lambda sample, vehicle: unrecoverable_no_propulsion_reason(
            sample,
            vehicle,
            stable_periapsis_min_m=70000.0,
        ),
    )

    recorder.start()
    time.sleep(0.035)
    recorder.stop()

    events = (artifacts.run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert '"type": "run_terminated"' in events
    assert '"reason": "mission_unrecoverable_no_propulsion"' in events

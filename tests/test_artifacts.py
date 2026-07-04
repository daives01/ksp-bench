from __future__ import annotations

import json
from pathlib import Path

from kspbench.artifacts import RunArtifacts, telemetry_waypoints
from kspbench.config import load_scenario
from kspbench.scoring import score_trace
from kspbench.telemetry import TelemetrySample


def test_writes_score_and_summary(tmp_path: Path) -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))
    artifacts = RunArtifacts.create(tmp_path, "run-1")
    sample = TelemetrySample(
        mission_elapsed_s=10.0,
        altitude_m=1000.0,
        surface_altitude_m=900.0,
        apoapsis_m=10000.0,
        periapsis_m=-500000.0,
        surface_speed_m_s=100.0,
        orbital_speed_m_s=200.0,
        vertical_speed_m_s=50.0,
        pitch_deg=80.0,
        heading_deg=90.0,
        roll_deg=0.0,
        stage=0,
        liquid_fuel=100.0,
        oxidizer=100.0,
        solid_fuel=0.0,
        dynamic_pressure_pa=1000.0,
        situation="flying",
        body="Kerbin",
        controllable=True,
        intact=True,
    )

    result = score_trace(
        run_id="run-1",
        scenario=scenario,
        telemetry=[sample],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )
    artifacts.write_telemetry([sample])
    artifacts.write_telemetry_waypoints([sample])
    artifacts.write_score(result)
    artifacts.write_summary(result)

    score = json.loads((tmp_path / "run-1" / "score.json").read_text(encoding="utf-8"))
    assert score["failure_reason"] == "periapsis_below_target"
    assert (tmp_path / "run-1" / "telemetry.csv").exists()
    waypoints = json.loads(
        (tmp_path / "run-1" / "telemetry_waypoints.json").read_text(encoding="utf-8")
    )
    assert waypoints["interval_s"] == 10.0
    assert len(waypoints["samples"]) == 1
    assert (tmp_path / "run-1" / "summary.txt").exists()


def test_telemetry_waypoints_downsamples_by_mission_elapsed() -> None:
    samples = [
        TelemetrySample(
            mission_elapsed_s=float(met),
            altitude_m=float(met),
            surface_altitude_m=float(met),
            apoapsis_m=10000.0,
            periapsis_m=-500000.0,
            surface_speed_m_s=100.0,
            orbital_speed_m_s=200.0,
            vertical_speed_m_s=50.0,
            pitch_deg=80.0,
            heading_deg=90.0,
            roll_deg=0.0,
            stage=0,
            liquid_fuel=100.0,
            oxidizer=100.0,
            solid_fuel=0.0,
            dynamic_pressure_pa=1000.0,
            situation="flying",
            body="Kerbin",
            controllable=True,
            intact=True,
        )
        for met in [0, 1, 10, 12, 20, 29]
    ]

    waypoints = telemetry_waypoints(samples, interval_s=10.0)

    assert [sample.mission_elapsed_s for sample in waypoints] == [0.0, 10.0, 20.0, 29.0]

from __future__ import annotations

from pathlib import Path

from kspbench.config import load_scenario
from kspbench.scoring import score_trace
from kspbench.telemetry import TelemetrySample


def _sample(**overrides):
    data = {
        "mission_elapsed_s": 300.0,
        "altitude_m": 80000.0,
        "surface_altitude_m": 79900.0,
        "apoapsis_m": 80000.0,
        "periapsis_m": 71000.0,
        "surface_speed_m_s": 2100.0,
        "orbital_speed_m_s": 2250.0,
        "vertical_speed_m_s": 0.0,
        "pitch_deg": 0.0,
        "heading_deg": 90.0,
        "roll_deg": 0.0,
        "stage": 2,
        "liquid_fuel": 10.0,
        "oxidizer": 10.0,
        "solid_fuel": 0.0,
        "dynamic_pressure_pa": 0.0,
        "situation": "orbiting",
        "body": "Kerbin",
        "controllable": True,
        "intact": True,
    }
    data.update(overrides)
    return TelemetrySample(**data)


def test_scores_successful_orbit() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(altitude_m=1000.0), _sample()],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.success is True
    assert result.failure_reason is None
    assert result.score > 90


def test_reports_periapsis_failure() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(periapsis_m=-50000.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.success is False
    assert result.failure_reason == "periapsis_below_target"

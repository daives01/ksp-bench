from __future__ import annotations

from pathlib import Path

from bench.config import load_scenario
from bench.scoring import score_trace
from bench.telemetry import TelemetrySample


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


def test_scores_target_orbit() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(altitude_m=1000.0), _sample()],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.score > 90
    assert result.final_orbit["apoapsis_m"] == 80000.0
    assert result.final_orbit["target_altitude_m"] == 80000.0
    assert result.fuel_remaining["liquid_fuel"] == 10.0
    assert result.time["mission_elapsed_s"] == 300.0


def test_unstable_orbit_scores_lower() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    target = score_trace(
        run_id="target",
        scenario=scenario,
        telemetry=[_sample()],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )
    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(periapsis_m=-50000.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.score < target.score
    assert result.diagnostics["stable_orbit"] is False


def test_stable_orbit_misses_target_but_keeps_partial_credit() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(apoapsis_m=120000.0, periapsis_m=90000.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.diagnostics["stable_orbit"] is True
    assert result.final_orbit["orbit_error_m"] == 25000.0
    assert result.score > 70


def test_invalid_actions_are_diagnostics_not_score_penalties() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    clean = score_trace(
        run_id="clean",
        scenario=scenario,
        telemetry=[_sample()],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
        invalid_actions=0,
        action_count=1,
    )
    noisy = score_trace(
        run_id="noisy",
        scenario=scenario,
        telemetry=[_sample()],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
        invalid_actions=12,
        action_count=13,
    )

    assert noisy.score == clean.score
    assert noisy.diagnostics["invalid_actions"] == 12

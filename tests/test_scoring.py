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
        telemetry=[
            _sample(altitude_m=1000.0),
            _sample(periapsis_m=80000.0, remaining_delta_v_m_s=710.0),
        ],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
        wall_clock_elapsed_s=123.4567,
    )

    assert result.score == 100.0
    assert result.final_orbit["apoapsis_m"] == 80000.0
    assert result.final_orbit["target_altitude_m"] == 80000.0
    assert result.fuel_remaining["liquid_fuel"] == 10.0
    assert result.time["mission_elapsed_s"] == 300.0
    assert result.time["wall_clock_elapsed_s"] == 123.457
    assert result.time["agent_timeout_s"] == 600.0
    assert result.remaining_delta_v_m_s == 710.0


def test_efficiency_bonus_rewards_reserve_above_manual_baseline() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    baseline = score_trace(
        run_id="baseline",
        scenario=scenario,
        telemetry=[_sample(periapsis_m=80000.0, remaining_delta_v_m_s=710.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )
    halfway = score_trace(
        run_id="halfway",
        scenario=scenario,
        telemetry=[_sample(periapsis_m=80000.0, remaining_delta_v_m_s=855.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )
    maximum = score_trace(
        run_id="maximum",
        scenario=scenario,
        telemetry=[_sample(periapsis_m=80000.0, remaining_delta_v_m_s=1200.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert baseline.score == 100.0
    assert halfway.score == 110.0
    assert maximum.score == 120.0


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


def test_orbit_credit_requires_the_intended_body_and_live_vessel() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))
    invalid_finals = [
        _sample(body="Mun"),
        _sample(situation="flying"),
        _sample(intact=False),
        _sample(controllable=False),
    ]

    for final in invalid_finals:
        result = score_trace(
            run_id="test",
            scenario=scenario,
            telemetry=[final],
            agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
            harness_version="test",
        )
        assert result.diagnostics["stable_orbit"] is False
        assert result.score == 20.0


def test_invalid_run_is_visible_in_score_diagnostics() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample()],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
        valid_run=False,
        invalid_reason="agent_or_infrastructure_failure",
    )

    assert result.diagnostics["valid_run"] is False
    assert result.diagnostics["invalid_reason"] == "agent_or_infrastructure_failure"


def test_stable_orbit_misses_target_but_keeps_partial_credit() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(apoapsis_m=120000.0, periapsis_m=90000.0, remaining_delta_v_m_s=710.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.diagnostics["stable_orbit"] is True
    assert result.final_orbit["orbit_error_m"] == 25000.0
    assert 50 < result.score < 80


def test_missing_legacy_delta_v_does_not_receive_reserve_credit() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    result = score_trace(
        run_id="test",
        scenario=scenario,
        telemetry=[_sample(periapsis_m=80000.0)],
        agent={"name": "opencode", "model": "test-model", "adapter": "opencode"},
        harness_version="test",
    )

    assert result.score == 80.0
    assert result.remaining_delta_v_m_s is None


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

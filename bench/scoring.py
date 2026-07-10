from __future__ import annotations

from dataclasses import asdict, dataclass

from bench.config import Scenario
from bench.telemetry import TelemetrySample


@dataclass(frozen=True)
class ScoreResult:
    run_id: str
    instance_id: str
    benchmark_version: str
    harness_version: str
    agent: dict[str, str | None]
    score: float
    final_orbit: dict[str, float | str]
    fuel_remaining: dict[str, float]
    remaining_delta_v_m_s: float | None
    time: dict[str, float | None]
    diagnostics: dict[str, float | int | bool | str | None]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def score_trace(
    *,
    run_id: str,
    scenario: Scenario,
    telemetry: list[TelemetrySample],
    agent: dict[str, str | None],
    harness_version: str,
    invalid_actions: int = 0,
    action_count: int = 0,
    wall_clock_elapsed_s: float | None = None,
    valid_run: bool = True,
    invalid_reason: str | None = None,
    run_diagnostics: dict[str, float | int | bool | str | None] | None = None,
) -> ScoreResult:
    if not telemetry:
        return _empty_result(
            run_id,
            scenario,
            agent,
            harness_version,
            invalid_actions,
            action_count,
            wall_clock_elapsed_s,
            valid_run,
            invalid_reason,
            run_diagnostics,
        )

    final = telemetry[-1]
    max_altitude = max(sample.altitude_m for sample in telemetry)
    max_apoapsis = max(sample.apoapsis_m for sample in telemetry)
    max_periapsis = max(sample.periapsis_m for sample in telemetry)
    elapsed = final.mission_elapsed_s

    milestones = {
        "cleared_tower": max_altitude >= scenario.scoring.cleared_tower_m,
        "reached_10km": max_altitude >= scenario.scoring.reached_10km_m,
        "reached_space": max_altitude >= scenario.scoring.reached_space_m,
        "stable_orbit": _is_qualifying_orbit(scenario, final),
    }
    orbit_error_m = _orbit_error_m(scenario, final)
    score = 0.0
    score += scenario.scoring.cleared_tower_points if milestones["cleared_tower"] else 0.0
    score += scenario.scoring.reached_10km_points if milestones["reached_10km"] else 0.0
    score += scenario.scoring.reached_space_points if milestones["reached_space"] else 0.0
    if milestones["stable_orbit"]:
        score += scenario.scoring.stable_orbit_points
        score += _orbit_precision_points(scenario, orbit_error_m)
        score += _reserve_delta_v_points(scenario, final)
    score = max(0.0, min(_maximum_score(scenario), round(score, 2)))

    final_orbit: dict[str, float | str] = {
        "body": final.body,
        "situation": final.situation,
        "apoapsis_m": round(final.apoapsis_m, 3),
        "periapsis_m": round(final.periapsis_m, 3),
        "target_altitude_m": round(scenario.target_orbit.altitude_m, 3),
        "orbit_error_m": round(orbit_error_m, 3),
        "eccentricity": round(final.eccentricity, 6),
        "inclination_deg": round(final.inclination_deg, 3),
        "orbital_speed_m_s": round(final.orbital_speed_m_s, 3),
        "time_to_apoapsis_s": round(final.time_to_apoapsis_s, 3),
        "time_to_periapsis_s": round(final.time_to_periapsis_s, 3),
    }
    fuel_remaining = {
        "liquid_fuel": round(final.liquid_fuel, 3),
        "oxidizer": round(final.oxidizer, 3),
        "solid_fuel": round(final.solid_fuel, 3),
    }
    time_metrics = {
        # KSP mission elapsed time can advance faster during rails warp. The
        # wall-clock duration is the comparable benchmark-time measurement.
        "wall_clock_elapsed_s": _rounded_or_none(wall_clock_elapsed_s),
        "mission_elapsed_s": round(elapsed, 3),
        "agent_timeout_s": _rounded_or_none(scenario.timeout_s),
    }
    diagnostics: dict[str, float | int | bool | str | None] = {
        "max_altitude_m": round(max_altitude, 3),
        "max_apoapsis_m": round(max_apoapsis, 3),
        "max_periapsis_m": round(max_periapsis, 3),
        **milestones,
        "invalid_actions": invalid_actions,
        "action_count": action_count,
        "intact": final.intact,
        "controllable": final.controllable,
        "valid_run": valid_run,
        **(run_diagnostics or {}),
    }
    if invalid_reason:
        diagnostics["invalid_reason"] = invalid_reason

    return ScoreResult(
        run_id=run_id,
        instance_id=scenario.instance_id,
        benchmark_version=scenario.benchmark_version,
        harness_version=harness_version,
        agent=agent,
        score=score,
        final_orbit=final_orbit,
        fuel_remaining=fuel_remaining,
        remaining_delta_v_m_s=_rounded_or_none(final.remaining_delta_v_m_s),
        time=time_metrics,
        diagnostics=diagnostics,
    )


def _empty_result(
    run_id: str,
    scenario: Scenario,
    agent: dict[str, str | None],
    harness_version: str,
    invalid_actions: int,
    action_count: int,
    wall_clock_elapsed_s: float | None,
    valid_run: bool,
    invalid_reason: str | None,
    run_diagnostics: dict[str, float | int | bool | str | None] | None,
) -> ScoreResult:
    return ScoreResult(
        run_id=run_id,
        instance_id=scenario.instance_id,
        benchmark_version=scenario.benchmark_version,
        harness_version=harness_version,
        agent=agent,
        score=0.0,
        final_orbit={
            "body": scenario.body,
            "situation": "no_telemetry",
            "apoapsis_m": 0.0,
            "periapsis_m": 0.0,
            "target_altitude_m": round(scenario.target_orbit.altitude_m, 3),
            "orbit_error_m": 0.0,
            "eccentricity": 0.0,
            "inclination_deg": 0.0,
            "orbital_speed_m_s": 0.0,
            "time_to_apoapsis_s": 0.0,
            "time_to_periapsis_s": 0.0,
        },
        fuel_remaining={
            "liquid_fuel": 0.0,
            "oxidizer": 0.0,
            "solid_fuel": 0.0,
        },
        remaining_delta_v_m_s=None,
        time={
            "wall_clock_elapsed_s": _rounded_or_none(wall_clock_elapsed_s),
            "mission_elapsed_s": 0.0,
            "agent_timeout_s": _rounded_or_none(scenario.timeout_s),
        },
        diagnostics={
            "max_altitude_m": 0.0,
            "max_apoapsis_m": 0.0,
            "max_periapsis_m": 0.0,
            "cleared_tower": False,
            "reached_10km": False,
            "reached_space": False,
            "stable_orbit": False,
            "invalid_actions": invalid_actions,
            "action_count": action_count,
            "intact": False,
            "controllable": False,
            "valid_run": valid_run,
            **(run_diagnostics or {}),
            **({"invalid_reason": invalid_reason} if invalid_reason else {}),
        },
    )


def _orbit_precision_points(scenario: Scenario, orbit_error_m: float) -> float:
    """Award precision only after orbit is safely established.

    The first 300 m of average apsis error is treated as manual-grade.  From
    there the credit declines linearly to zero at 20 km, keeping near-misses
    distinguishable without letting a loose orbit rival a precise one.
    """
    tolerance = scenario.scoring.orbit_precision_tolerance_m
    zero_credit = scenario.scoring.orbit_precision_zero_credit_error_m
    if orbit_error_m <= tolerance:
        return scenario.scoring.orbit_precision_points
    fraction = 1.0 - ((orbit_error_m - tolerance) / (zero_credit - tolerance))
    return scenario.scoring.orbit_precision_points * max(0.0, fraction)


def _is_qualifying_orbit(scenario: Scenario, final: TelemetrySample) -> bool:
    return (
        final.body == scenario.body
        and final.situation.lower() == "orbiting"
        and final.intact
        and final.controllable
        and final.apoapsis_m > 0
        and final.periapsis_m >= scenario.target_orbit.stable_periapsis_min_m
    )


def _orbit_error_m(scenario: Scenario, final: TelemetrySample) -> float:
    target = scenario.target_orbit.altitude_m
    return (abs(final.apoapsis_m - target) + abs(final.periapsis_m - target)) / 2.0


def _reserve_delta_v_points(scenario: Scenario, final: TelemetrySample) -> float:
    """Reward reserve delta-v, including an efficiency tier beyond manual baseline."""
    remaining = final.remaining_delta_v_m_s
    if remaining is None:
        return 0.0
    remaining = max(0.0, remaining)
    baseline = scenario.scoring.manual_baseline_delta_v_m_s
    baseline_points = scenario.scoring.reserve_delta_v_points * min(1.0, remaining / baseline)
    if remaining <= baseline:
        return baseline_points

    bonus_fraction = (remaining - baseline) / (
        scenario.scoring.efficiency_bonus_delta_v_m_s - baseline
    )
    return baseline_points + scenario.scoring.efficiency_bonus_points * min(1.0, bonus_fraction)


def _maximum_score(scenario: Scenario) -> float:
    scoring = scenario.scoring
    return (
        scoring.cleared_tower_points
        + scoring.reached_10km_points
        + scoring.reached_space_points
        + scoring.stable_orbit_points
        + scoring.orbit_precision_points
        + scoring.reserve_delta_v_points
        + scoring.efficiency_bonus_points
    )


def _rounded_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 3)

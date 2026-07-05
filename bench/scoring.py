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
    time: dict[str, float]
    diagnostics: dict[str, float | int | bool | str]

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
) -> ScoreResult:
    if not telemetry:
        return _empty_result(
            run_id,
            scenario,
            agent,
            harness_version,
            invalid_actions,
            action_count,
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
        "stable_orbit": _is_stable_orbit(scenario, final),
    }
    orbit_error_m = _orbit_error_m(scenario, final)
    score = 0.0
    score += 10.0 if milestones["cleared_tower"] else 0.0
    score += 15.0 if milestones["reached_10km"] else 0.0
    score += 20.0 if milestones["reached_space"] else 0.0
    score += 20.0 if milestones["stable_orbit"] else 0.0
    score += _orbit_quality_points(scenario, final)
    score += _fuel_bonus(scenario, final)
    score = max(0.0, min(100.0, round(score, 2)))

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
        "mission_elapsed_s": round(elapsed, 3),
        "timeout_s": round(scenario.timeout_s, 3),
    }
    diagnostics: dict[str, float | int | bool | str] = {
        "max_altitude_m": round(max_altitude, 3),
        "max_apoapsis_m": round(max_apoapsis, 3),
        "max_periapsis_m": round(max_periapsis, 3),
        **milestones,
        "invalid_actions": invalid_actions,
        "action_count": action_count,
        "intact": final.intact,
        "controllable": final.controllable,
    }

    return ScoreResult(
        run_id=run_id,
        instance_id=scenario.instance_id,
        benchmark_version=scenario.benchmark_version,
        harness_version=harness_version,
        agent=agent,
        score=score,
        final_orbit=final_orbit,
        fuel_remaining=fuel_remaining,
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
        time={
            "mission_elapsed_s": 0.0,
            "timeout_s": round(scenario.timeout_s, 3),
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
        },
    )


def _orbit_quality_points(scenario: Scenario, final: TelemetrySample) -> float:
    target = scenario.target_orbit.altitude_m
    apo_fraction = _altitude_quality_fraction(final.apoapsis_m, target)
    peri_fraction = _altitude_quality_fraction(final.periapsis_m, target)
    return scenario.scoring.target_orbit_points * ((apo_fraction + peri_fraction) / 2.0)


def _altitude_quality_fraction(altitude_m: float, target_m: float) -> float:
    if altitude_m < 0:
        return 0.0
    return max(0.0, 1.0 - (abs(altitude_m - target_m) / target_m))


def _is_stable_orbit(scenario: Scenario, final: TelemetrySample) -> bool:
    return final.periapsis_m >= scenario.target_orbit.stable_periapsis_min_m


def _orbit_error_m(scenario: Scenario, final: TelemetrySample) -> float:
    target = scenario.target_orbit.altitude_m
    return (abs(final.apoapsis_m - target) + abs(final.periapsis_m - target)) / 2.0


def _fuel_bonus(scenario: Scenario, final: TelemetrySample) -> float:
    remaining = max(0.0, final.liquid_fuel + final.oxidizer + final.solid_fuel)
    return min(scenario.scoring.fuel_bonus_points, remaining / 100.0)


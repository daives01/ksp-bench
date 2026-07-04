from __future__ import annotations

from dataclasses import asdict, dataclass

from kspbench.config import Scenario
from kspbench.telemetry import TelemetrySample


@dataclass(frozen=True)
class ScoreResult:
    run_id: str
    instance_id: str
    benchmark_version: str
    harness_version: str
    agent: dict[str, str | None]
    success: bool
    score: float
    milestones: dict[str, bool]
    diagnostics: dict[str, float | int | bool | str]
    failure_reason: str | None

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
        "periapsis_above_70km": final.periapsis_m >= scenario.target_orbit.periapsis_min_m,
    }
    apoapsis_in_band = (
        scenario.target_orbit.apoapsis_min_m
        <= final.apoapsis_m
        <= scenario.target_orbit.apoapsis_max_m
    )
    success = (
        apoapsis_in_band
        and final.periapsis_m >= scenario.target_orbit.periapsis_min_m
        and final.intact
        and final.controllable
        and elapsed <= scenario.timeout_s
    )

    score = 0.0
    score += 10.0 if milestones["cleared_tower"] else 0.0
    score += 15.0 if milestones["reached_10km"] else 0.0
    score += 20.0 if milestones["reached_space"] else 0.0
    score += 20.0 if milestones["periapsis_above_70km"] else 0.0
    score += _orbit_quality_points(scenario, final)
    score += _fuel_bonus(scenario, final)
    score = max(0.0, min(100.0, round(score, 2)))

    diagnostics: dict[str, float | int | bool | str] = {
        "max_altitude_m": round(max_altitude, 3),
        "max_apoapsis_m": round(max_apoapsis, 3),
        "max_periapsis_m": round(max_periapsis, 3),
        "final_apoapsis_m": round(final.apoapsis_m, 3),
        "final_periapsis_m": round(final.periapsis_m, 3),
        "final_time_to_apoapsis_s": round(final.time_to_apoapsis_s, 3),
        "final_time_to_periapsis_s": round(final.time_to_periapsis_s, 3),
        "final_eccentricity": round(final.eccentricity, 6),
        "final_inclination_deg": round(final.inclination_deg, 3),
        "mission_elapsed_s": round(elapsed, 3),
        "invalid_actions": invalid_actions,
        "action_count": action_count,
        "intact": final.intact,
        "controllable": final.controllable,
        "situation": final.situation,
        "body": final.body,
        "liquid_fuel": round(final.liquid_fuel, 3),
        "oxidizer": round(final.oxidizer, 3),
        "solid_fuel": round(final.solid_fuel, 3),
    }

    return ScoreResult(
        run_id=run_id,
        instance_id=scenario.instance_id,
        benchmark_version=scenario.benchmark_version,
        harness_version=harness_version,
        agent=agent,
        success=success,
        score=score,
        milestones=milestones,
        diagnostics=diagnostics,
        failure_reason=None
        if success
        else _failure_reason(scenario, final, elapsed, invalid_actions),
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
        success=False,
        score=0.0,
        milestones={
            "cleared_tower": False,
            "reached_10km": False,
            "reached_space": False,
            "periapsis_above_70km": False,
        },
        diagnostics={
            "max_altitude_m": 0.0,
            "final_apoapsis_m": 0.0,
            "final_periapsis_m": 0.0,
            "mission_elapsed_s": 0.0,
            "invalid_actions": invalid_actions,
            "action_count": action_count,
        },
        failure_reason="no_telemetry",
    )


def _orbit_quality_points(scenario: Scenario, final: TelemetrySample) -> float:
    target_mid = (scenario.target_orbit.apoapsis_min_m + scenario.target_orbit.apoapsis_max_m) / 2.0
    half_band = (scenario.target_orbit.apoapsis_max_m - scenario.target_orbit.apoapsis_min_m) / 2.0
    apo_error = abs(final.apoapsis_m - target_mid)
    apo_fraction = max(0.0, 1.0 - (apo_error / max(half_band * 4.0, 1.0)))

    peri_floor = scenario.target_orbit.periapsis_min_m
    peri_fraction = (
        1.0 if final.periapsis_m >= peri_floor else max(0.0, final.periapsis_m / peri_floor)
    )
    return scenario.scoring.target_orbit_points * ((apo_fraction + peri_fraction) / 2.0)


def _fuel_bonus(scenario: Scenario, final: TelemetrySample) -> float:
    remaining = max(0.0, final.liquid_fuel + final.oxidizer + final.solid_fuel)
    return min(scenario.scoring.fuel_bonus_points, remaining / 100.0)


def _failure_reason(
    scenario: Scenario, final: TelemetrySample, elapsed: float, invalid_actions: int
) -> str:
    if not final.intact:
        return "vessel_not_intact"
    if not final.controllable:
        return "vessel_not_controllable"
    if elapsed > scenario.timeout_s:
        return "timeout"
    if final.periapsis_m < scenario.target_orbit.periapsis_min_m:
        return "periapsis_below_target"
    if final.apoapsis_m < scenario.target_orbit.apoapsis_min_m:
        return "apoapsis_below_target"
    if final.apoapsis_m > scenario.target_orbit.apoapsis_max_m:
        return "apoapsis_above_target"
    return "missed_orbit"

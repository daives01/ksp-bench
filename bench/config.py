from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TargetOrbit:
    altitude_m: float
    stable_periapsis_min_m: float


@dataclass(frozen=True)
class ScoringConfig:
    cleared_tower_m: float
    reached_10km_m: float
    reached_space_m: float
    cleared_tower_points: float
    reached_10km_points: float
    reached_space_points: float
    stable_orbit_points: float
    orbit_precision_points: float
    orbit_precision_tolerance_m: float
    orbit_precision_zero_credit_error_m: float
    reserve_delta_v_points: float
    manual_baseline_delta_v_m_s: float
    efficiency_bonus_points: float
    efficiency_bonus_delta_v_m_s: float


@dataclass(frozen=True)
class Scenario:
    instance_id: str
    benchmark_version: str
    body: str
    vessel_name: str | None
    timeout_s: float
    target_orbit: TargetOrbit
    scoring: ScoringConfig
    source_path: Path | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any], source_path: Path | None = None) -> Scenario:
        required = [
            "instance_id",
            "benchmark_version",
            "body",
            "timeout_s",
            "target_orbit",
            "scoring",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"scenario missing required keys: {joined}")

        target = _expect_mapping(data["target_orbit"], "target_orbit")
        scoring = _expect_mapping(data["scoring"], "scoring")

        return cls(
            instance_id=_expect_str(data["instance_id"], "instance_id"),
            benchmark_version=_expect_str(data["benchmark_version"], "benchmark_version"),
            body=_expect_str(data["body"], "body"),
            vessel_name=_expect_optional_str(data.get("vessel_name"), "vessel_name"),
            timeout_s=_expect_positive_number(data["timeout_s"], "timeout_s"),
            target_orbit=TargetOrbit(
                altitude_m=_expect_number(target["altitude_m"], "target_orbit.altitude_m"),
                stable_periapsis_min_m=_expect_number(
                    target["stable_periapsis_min_m"], "target_orbit.stable_periapsis_min_m"
                ),
            ),
            scoring=ScoringConfig(
                cleared_tower_m=_expect_number(
                    scoring["cleared_tower_m"], "scoring.cleared_tower_m"
                ),
                reached_10km_m=_expect_number(scoring["reached_10km_m"], "scoring.reached_10km_m"),
                reached_space_m=_expect_number(
                    scoring["reached_space_m"], "scoring.reached_space_m"
                ),
                cleared_tower_points=_expect_number(
                    scoring["cleared_tower_points"], "scoring.cleared_tower_points"
                ),
                reached_10km_points=_expect_number(
                    scoring["reached_10km_points"], "scoring.reached_10km_points"
                ),
                reached_space_points=_expect_number(
                    scoring["reached_space_points"], "scoring.reached_space_points"
                ),
                stable_orbit_points=_expect_number(
                    scoring["stable_orbit_points"], "scoring.stable_orbit_points"
                ),
                orbit_precision_points=_expect_number(
                    scoring["orbit_precision_points"], "scoring.orbit_precision_points"
                ),
                orbit_precision_tolerance_m=_expect_positive_number(
                    scoring["orbit_precision_tolerance_m"], "scoring.orbit_precision_tolerance_m"
                ),
                orbit_precision_zero_credit_error_m=_expect_positive_number(
                    scoring["orbit_precision_zero_credit_error_m"],
                    "scoring.orbit_precision_zero_credit_error_m",
                ),
                reserve_delta_v_points=_expect_number(
                    scoring["reserve_delta_v_points"], "scoring.reserve_delta_v_points"
                ),
                manual_baseline_delta_v_m_s=_expect_positive_number(
                    scoring["manual_baseline_delta_v_m_s"], "scoring.manual_baseline_delta_v_m_s"
                ),
                efficiency_bonus_points=_expect_number(
                    scoring["efficiency_bonus_points"], "scoring.efficiency_bonus_points"
                ),
                efficiency_bonus_delta_v_m_s=_expect_positive_number(
                    scoring["efficiency_bonus_delta_v_m_s"],
                    "scoring.efficiency_bonus_delta_v_m_s",
                ),
            ),
            source_path=source_path,
        )

    def validate(self) -> None:
        if self.target_orbit.altitude_m <= 0:
            raise ValueError("target_orbit.altitude_m must be positive")
        if self.target_orbit.stable_periapsis_min_m <= 0:
            raise ValueError("target_orbit.stable_periapsis_min_m must be positive")
        if (
            self.scoring.orbit_precision_zero_credit_error_m
            <= self.scoring.orbit_precision_tolerance_m
        ):
            raise ValueError(
                "scoring.orbit_precision_zero_credit_error_m must exceed the tolerance"
            )
        if (
            self.scoring.efficiency_bonus_delta_v_m_s
            <= self.scoring.manual_baseline_delta_v_m_s
        ):
            raise ValueError(
                "scoring.efficiency_bonus_delta_v_m_s must exceed the manual baseline"
            )


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    with scenario_path.open("rb") as handle:
        data = tomllib.load(handle)
    scenario = Scenario.from_mapping(data, source_path=scenario_path)
    scenario.validate()
    return scenario


def _expect_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a mapping")
    return value


def _expect_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{field} must be a non-empty string")
    return value


def _expect_optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _expect_str(value, field)


def _expect_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be a number")
    return float(value)


def _expect_positive_number(value: Any, field: str) -> float:
    number = _expect_number(value, field)
    if number <= 0:
        raise ValueError(f"{field} must be positive")
    return number

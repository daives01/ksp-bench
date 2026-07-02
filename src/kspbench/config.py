from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kspbench.simple_yaml import load_yaml


@dataclass(frozen=True)
class TargetOrbit:
    apoapsis_min_m: float
    apoapsis_max_m: float
    periapsis_min_m: float


@dataclass(frozen=True)
class ScoringConfig:
    cleared_tower_m: float
    reached_10km_m: float
    reached_space_m: float
    target_orbit_points: float
    fuel_bonus_points: float
    invalid_action_penalty: float


@dataclass(frozen=True)
class ArtifactConfig:
    telemetry_interval_s: float
    root_dir: str


@dataclass(frozen=True)
class KRPCConfig:
    host: str
    rpc_port: int
    stream_port: int


@dataclass(frozen=True)
class Scenario:
    instance_id: str
    benchmark_version: str
    body: str
    launch_site: str
    vessel_name: str | None
    timeout_s: float
    target_orbit: TargetOrbit
    allowed_controls: tuple[str, ...]
    scoring: ScoringConfig
    artifacts: ArtifactConfig
    krpc: KRPCConfig
    source_path: Path | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any], source_path: Path | None = None) -> Scenario:
        required = [
            "instance_id",
            "benchmark_version",
            "body",
            "launch_site",
            "timeout_s",
            "target_orbit",
            "allowed_controls",
            "scoring",
            "artifacts",
            "krpc",
        ]
        missing = [key for key in required if key not in data]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"scenario missing required keys: {joined}")

        target = _expect_mapping(data["target_orbit"], "target_orbit")
        scoring = _expect_mapping(data["scoring"], "scoring")
        artifacts = _expect_mapping(data["artifacts"], "artifacts")
        krpc = _expect_mapping(data["krpc"], "krpc")

        return cls(
            instance_id=_expect_str(data["instance_id"], "instance_id"),
            benchmark_version=_expect_str(data["benchmark_version"], "benchmark_version"),
            body=_expect_str(data["body"], "body"),
            launch_site=_expect_str(data["launch_site"], "launch_site"),
            vessel_name=_expect_optional_str(data.get("vessel_name"), "vessel_name"),
            timeout_s=_expect_positive_number(data["timeout_s"], "timeout_s"),
            target_orbit=TargetOrbit(
                apoapsis_min_m=_expect_number(
                    target["apoapsis_min_m"], "target_orbit.apoapsis_min_m"
                ),
                apoapsis_max_m=_expect_number(
                    target["apoapsis_max_m"], "target_orbit.apoapsis_max_m"
                ),
                periapsis_min_m=_expect_number(
                    target["periapsis_min_m"], "target_orbit.periapsis_min_m"
                ),
            ),
            allowed_controls=tuple(_expect_str_list(data["allowed_controls"], "allowed_controls")),
            scoring=ScoringConfig(
                cleared_tower_m=_expect_number(
                    scoring["cleared_tower_m"], "scoring.cleared_tower_m"
                ),
                reached_10km_m=_expect_number(scoring["reached_10km_m"], "scoring.reached_10km_m"),
                reached_space_m=_expect_number(
                    scoring["reached_space_m"], "scoring.reached_space_m"
                ),
                target_orbit_points=_expect_number(
                    scoring["target_orbit_points"], "scoring.target_orbit_points"
                ),
                fuel_bonus_points=_expect_number(
                    scoring["fuel_bonus_points"], "scoring.fuel_bonus_points"
                ),
                invalid_action_penalty=_expect_number(
                    scoring["invalid_action_penalty"], "scoring.invalid_action_penalty"
                ),
            ),
            artifacts=ArtifactConfig(
                telemetry_interval_s=_expect_positive_number(
                    artifacts["telemetry_interval_s"], "artifacts.telemetry_interval_s"
                ),
                root_dir=_expect_str(artifacts["root_dir"], "artifacts.root_dir"),
            ),
            krpc=KRPCConfig(
                host=_expect_str(krpc["host"], "krpc.host"),
                rpc_port=int(_expect_number(krpc["rpc_port"], "krpc.rpc_port")),
                stream_port=int(_expect_number(krpc["stream_port"], "krpc.stream_port")),
            ),
            source_path=source_path,
        )

    def validate(self) -> None:
        if self.target_orbit.apoapsis_max_m <= self.target_orbit.apoapsis_min_m:
            raise ValueError("target_orbit.apoapsis_max_m must exceed apoapsis_min_m")
        if self.target_orbit.periapsis_min_m <= 0:
            raise ValueError("target_orbit.periapsis_min_m must be positive")
        if not self.allowed_controls:
            raise ValueError("allowed_controls must not be empty")


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    data = load_yaml(scenario_path)
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


def _expect_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field} must be a list of strings")
    return value

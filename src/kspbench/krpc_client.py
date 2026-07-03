from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

from kspbench.config import KRPCConfig, Scenario
from kspbench.telemetry import TelemetrySample


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def check_krpc_reachable(config: KRPCConfig, timeout_s: float = 1.0) -> DoctorCheck:
    try:
        with socket.create_connection((config.host, config.rpc_port), timeout=timeout_s):
            return DoctorCheck("krpc_rpc_port", True, f"{config.host}:{config.rpc_port} reachable")
    except OSError as exc:
        return DoctorCheck(
            "krpc_rpc_port",
            False,
            f"{config.host}:{config.rpc_port} unreachable: {exc}",
        )


def check_krpc_package() -> DoctorCheck:
    try:
        import krpc  # type: ignore  # noqa: F401
    except ImportError:
        return DoctorCheck(
            "krpc_python_package",
            False,
            "not installed; run with the optional 'ksp' extra when using live KSP",
        )
    return DoctorCheck("krpc_python_package", True, "installed")


class KRPCController:
    def __init__(self, conn: Any, scenario: Scenario) -> None:
        self.conn = conn
        self.scenario = scenario
        self.vessel = conn.space_center.active_vessel
        if scenario.vessel_name and self.vessel.name != scenario.vessel_name:
            raise ValueError(
                f"active vessel is {self.vessel.name!r}, expected {scenario.vessel_name!r}"
            )

    @classmethod
    def connect(cls, scenario: Scenario) -> KRPCController:
        try:
            import krpc  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "krpc Python package is not installed; install the project with the 'ksp' extra"
            ) from exc

        conn = krpc.connect(
            name="KSP-bench",
            address=scenario.krpc.host,
            rpc_port=scenario.krpc.rpc_port,
            stream_port=scenario.krpc.stream_port,
        )
        return cls(conn, scenario)

    def read_telemetry(self) -> TelemetrySample:
        vessel = self.vessel
        orbit = vessel.orbit
        body = orbit.body
        flight = vessel.flight(body.reference_frame)
        surface_flight = vessel.flight(vessel.surface_reference_frame)
        resources = vessel.resources

        return TelemetrySample(
            mission_elapsed_s=float(vessel.met),
            altitude_m=float(flight.mean_altitude),
            surface_altitude_m=float(flight.surface_altitude),
            apoapsis_m=float(orbit.apoapsis_altitude),
            periapsis_m=float(orbit.periapsis_altitude),
            surface_speed_m_s=float(surface_flight.speed),
            orbital_speed_m_s=float(orbit.speed),
            vertical_speed_m_s=float(surface_flight.vertical_speed),
            pitch_deg=float(surface_flight.pitch),
            heading_deg=float(surface_flight.heading),
            roll_deg=float(surface_flight.roll),
            stage=int(vessel.control.current_stage),
            liquid_fuel=_resource_amount(resources, "LiquidFuel"),
            oxidizer=_resource_amount(resources, "Oxidizer"),
            solid_fuel=_resource_amount(resources, "SolidFuel"),
            dynamic_pressure_pa=float(getattr(surface_flight, "dynamic_pressure", 0.0)),
            situation=_enum_name(vessel.situation),
            body=str(body.name),
            controllable=_is_controllable(vessel),
            intact=True,
        )

    def read_vehicle_state(self) -> dict[str, Any]:
        vessel = self.vessel
        control = vessel.control
        current_stage = _safe_int(lambda: control.current_stage, default=0)
        resources = vessel.resources
        resource_names = ("LiquidFuel", "Oxidizer", "SolidFuel", "ElectricCharge", "MonoPropellant")

        return {
            "name": _safe_value(lambda: vessel.name, default="unknown"),
            "current_stage": current_stage,
            "next_stage_available": current_stage > 0,
            "throttle": _safe_float(lambda: control.throttle),
            "sas": _safe_bool(lambda: control.sas),
            "rcs": _safe_bool(lambda: control.rcs),
            "controllable": _is_controllable(vessel),
            "mass": _safe_float(lambda: vessel.mass),
            "dry_mass": _safe_float(lambda: vessel.dry_mass),
            "available_thrust": _safe_float(lambda: vessel.available_thrust),
            "max_thrust": _safe_float(lambda: vessel.max_thrust),
            "resources": {
                resource_name: _resource_amount(resources, resource_name)
                for resource_name in resource_names
            },
            "stages": _stage_resources(vessel, current_stage, resource_names),
            "active_engines": _active_engines(vessel),
        }


def _resource_amount(resources: Any, name: str) -> float:
    try:
        return float(resources.amount(name))
    except Exception:
        return 0.0


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", value))


def _is_controllable(vessel: Any) -> bool:
    try:
        return bool(vessel.control.controllable)
    except Exception:
        try:
            return bool(vessel.parts.controlling)
        except Exception:
            return True


def _stage_resources(
    vessel: Any, current_stage: int, resource_names: tuple[str, ...]
) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for stage in range(max(current_stage, 0) + 1):
        try:
            resources = vessel.resources_in_decouple_stage(stage, cumulative=False)
        except Exception:
            continue
        stages.append(
            {
                "stage": stage,
                "resources": {
                    resource_name: _resource_amount(resources, resource_name)
                    for resource_name in resource_names
                },
            }
        )
    return stages


def _active_engines(vessel: Any) -> list[dict[str, Any]]:
    engines: list[dict[str, Any]] = []
    try:
        engine_parts = vessel.parts.engines
    except Exception:
        return engines

    for index, engine in enumerate(engine_parts):
        if not _safe_bool(lambda engine=engine: engine.active):
            continue
        engines.append(
            {
                "index": index,
                "part_name": _safe_value(lambda engine=engine: engine.part.name, default="unknown"),
                "has_fuel": _safe_bool(lambda engine=engine: engine.has_fuel),
                "thrust": _safe_float(lambda engine=engine: engine.thrust),
                "max_thrust": _safe_float(lambda engine=engine: engine.max_thrust),
                "specific_impulse": _safe_float(
                    lambda engine=engine: engine.specific_impulse, default=0.0
                ),
            }
        )
    return engines


def _safe_value(getter: Any, *, default: Any) -> Any:
    try:
        return getter()
    except Exception:
        return default


def _safe_float(getter: Any, default: float = 0.0) -> float:
    return float(_safe_value(getter, default=default))


def _safe_int(getter: Any, default: int = 0) -> int:
    return int(_safe_value(getter, default=default))


def _safe_bool(getter: Any, default: bool = False) -> bool:
    return bool(_safe_value(getter, default=default))

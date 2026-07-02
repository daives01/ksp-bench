from __future__ import annotations

import socket
import time
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

    def apply_action(self, action: dict[str, Any]) -> None:
        action_type = action["type"]
        control = self.vessel.control
        if action_type == "set_throttle":
            control.throttle = float(action["value"])
        elif action_type == "set_sas":
            control.sas = bool(action["enabled"])
        elif action_type == "set_rcs":
            control.rcs = bool(action["enabled"])
        elif action_type == "stage":
            control.activate_next_stage()
        elif action_type == "set_attitude":
            autopilot = self.vessel.auto_pilot
            autopilot.target_pitch_and_heading(float(action["pitch"]), float(action["heading"]))
            autopilot.target_roll = float(action.get("roll", 0.0))
            autopilot.engage()
        elif action_type == "wait":
            time.sleep(float(action["seconds"]))
        else:
            raise ValueError(f"unsupported live action: {action_type}")

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

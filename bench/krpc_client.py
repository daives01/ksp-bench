from __future__ import annotations

import json
import math
import socket
import time
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Any

from bench.config import Scenario
from bench.telemetry import TelemetrySample

_PROPELLANT_DENSITY_KG_PER_UNIT = {
    "LiquidFuel": 5.0,
    "Oxidizer": 5.0,
    "SolidFuel": 7.5,
}


def _krpc_client_name(model: str | None = None) -> str:
    model_name = model or environ.get("KSPBENCH_MODEL")
    if not model_name:
        return "KSP Bench"
    return model_name.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class KRPCConfig:
    host: str = "127.0.0.1"
    rpc_port: int = 50000
    stream_port: int = 50001

    @classmethod
    def from_env(cls) -> KRPCConfig:
        opencode_env = _opencode_ksp_environment()
        return cls(
            host=environ.get("KSP_RPC_HOST") or opencode_env.get("KSP_RPC_HOST") or cls.host,
            rpc_port=_config_int("KSP_RPC_PORT", cls.rpc_port, opencode_env),
            stream_port=_config_int("KSP_STREAM_PORT", cls.stream_port, opencode_env),
        )


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
    def __init__(self, conn: Any, scenario: Scenario, *, strict_vessel: bool = True) -> None:
        self.conn = conn
        self.scenario = scenario
        self.vessel = conn.space_center.active_vessel
        if scenario.vessel_name and self.vessel.name != scenario.vessel_name:
            named_vessel = _find_vessel_by_name(conn.space_center, scenario.vessel_name)
            if named_vessel is not None:
                self.vessel = named_vessel
                conn.space_center.active_vessel = named_vessel
        if strict_vessel and scenario.vessel_name and self.vessel.name != scenario.vessel_name:
            raise ValueError(
                f"active vessel is {self.vessel.name!r}, expected {scenario.vessel_name!r}"
            )

    @classmethod
    def connect(
        cls,
        scenario: Scenario,
        config: KRPCConfig | None = None,
        *,
        strict_vessel: bool = True,
        model: str | None = None,
    ) -> KRPCController:
        try:
            import krpc  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "krpc Python package is not installed; install the project with the 'ksp' extra"
            ) from exc

        krpc_config = config or KRPCConfig.from_env()
        conn = krpc.connect(
            name=_krpc_client_name(model),
            address=krpc_config.host,
            rpc_port=krpc_config.rpc_port,
            stream_port=krpc_config.stream_port,
        )
        return cls(conn, scenario, strict_vessel=strict_vessel)

    def read_telemetry(self) -> TelemetrySample:
        vessel = self.vessel
        orbit = vessel.orbit
        body = orbit.body
        # Use Kerbin's rotating frame for motion relative to the surface.
        # vessel.surface_reference_frame follows the vessel itself, making
        # speed and vertical_speed queried in that frame always read zero.
        flight = vessel.flight(body.reference_frame)
        surface_flight = vessel.flight(vessel.surface_reference_frame)
        resources = vessel.resources

        return TelemetrySample(
            mission_elapsed_s=float(vessel.met),
            altitude_m=float(flight.mean_altitude),
            surface_altitude_m=float(flight.surface_altitude),
            apoapsis_m=float(orbit.apoapsis_altitude),
            periapsis_m=float(orbit.periapsis_altitude),
            surface_speed_m_s=float(flight.speed),
            orbital_speed_m_s=float(orbit.speed),
            vertical_speed_m_s=float(flight.vertical_speed),
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
            intact=_is_intact(vessel),
            time_to_apoapsis_s=_safe_float(lambda: orbit.time_to_apoapsis),
            time_to_periapsis_s=_safe_float(lambda: orbit.time_to_periapsis),
            eccentricity=_safe_float(lambda: orbit.eccentricity),
            inclination_deg=_safe_float(lambda: orbit.inclination),
            remaining_delta_v_m_s=_estimate_remaining_delta_v(vessel),
            latitude_deg=_safe_float(lambda: flight.latitude),
            longitude_deg=_safe_float(lambda: flight.longitude),
        )

    def read_vehicle_state(self) -> dict[str, Any]:
        vessel = self.vessel
        control = vessel.control
        current_stage = _safe_int(lambda: control.current_stage, default=0)
        orbit = vessel.orbit
        body = orbit.body
        surface_flight = vessel.flight(vessel.surface_reference_frame)
        resources = vessel.resources
        resource_names = ("LiquidFuel", "Oxidizer", "SolidFuel", "ElectricCharge", "MonoPropellant")

        stages = _stage_resources(vessel, current_stage, resource_names)
        engines = _engines(vessel)
        decouplers = _decouplers(vessel)

        return {
            "name": _safe_value(lambda: vessel.name, default="unknown"),
            "body": _safe_value(lambda: body.name, default="unknown"),
            "situation": _enum_name(_safe_value(lambda: vessel.situation, default="unknown")),
            "altitude_m": _safe_float(lambda: vessel.flight(body.reference_frame).mean_altitude),
            "surface_altitude_m": _safe_float(lambda: surface_flight.surface_altitude),
            "apoapsis_m": _safe_float(lambda: orbit.apoapsis_altitude),
            "periapsis_m": _safe_float(lambda: orbit.periapsis_altitude),
            "time_to_apoapsis_s": _safe_float(lambda: orbit.time_to_apoapsis),
            "time_to_periapsis_s": _safe_float(lambda: orbit.time_to_periapsis),
            "eccentricity": _safe_float(lambda: orbit.eccentricity),
            "inclination_deg": _safe_float(lambda: orbit.inclination),
            "orbital_speed_m_s": _safe_float(lambda: orbit.speed),
            "vertical_speed_m_s": _safe_float(
                lambda: vessel.flight(body.reference_frame).vertical_speed
            ),
            "dynamic_pressure_pa": _safe_float(
                lambda: getattr(surface_flight, "dynamic_pressure", 0.0)
            ),
            "atmosphere_depth_m": _safe_float(lambda: body.atmosphere_depth),
            "in_atmosphere": _safe_float(lambda: vessel.flight(body.reference_frame).mean_altitude)
            < _safe_float(lambda: body.atmosphere_depth),
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
            "current_stage_resources": _current_stage_resources(stages, current_stage),
            "next_stage": _next_stage_summary(
                current_stage=current_stage,
                stages=stages,
                engines=engines,
                decouplers=decouplers,
            ),
            "stages": stages,
            "active_engines": _active_engines(vessel),
            "engines": engines,
            "decouplers": decouplers,
        }

    def list_vessels(self) -> dict[str, Any]:
        vessels = list(_safe_value(lambda: self.conn.space_center.vessels, default=[]))
        current_index: int | None = None
        summaries: list[dict[str, Any]] = []
        for index, vessel in enumerate(vessels):
            is_current = vessel == self.vessel
            if is_current:
                current_index = index
            summaries.append(_vessel_summary(vessel, index=index, current=is_current))
        return {
            "current_index": current_index,
            "current": _vessel_summary(self.vessel, index=current_index, current=True),
            "vehicles": summaries,
        }

    def select_vessel(
        self,
        *,
        name: str | None = None,
        index: int | None = None,
        make_active: bool = True,
    ) -> dict[str, Any]:
        if (name is None) == (index is None):
            raise ValueError("pass exactly one of name or index")
        vessels = list(_safe_value(lambda: self.conn.space_center.vessels, default=[]))
        if index is not None:
            selected_index = int(index)
            if selected_index < 0 or selected_index >= len(vessels):
                raise IndexError(f"vehicle index {selected_index} is out of range")
            vessel = vessels[selected_index]
        else:
            matches = [
                (candidate_index, candidate)
                for candidate_index, candidate in enumerate(vessels)
                if _safe_value(lambda candidate=candidate: candidate.name, default=None) == name
            ]
            if not matches:
                raise ValueError(f"no vehicle named {name!r}")
            if len(matches) > 1:
                raise ValueError(f"multiple vehicles named {name!r}; select by index")
            selected_index, vessel = matches[0]
        self.vessel = vessel
        if make_active:
            self.conn.space_center.active_vessel = vessel
        return {
            "selected": _vessel_summary(vessel, index=selected_index, current=True),
            "made_active": make_active,
        }

    def prepare_for_launchpad_run(self, *, wait_s: float = 2.0) -> None:
        """Return KSP to an unpaused launchpad state for the next benchmark run."""
        space_center = self.conn.space_center
        _set_unpaused(space_center)

        revert = getattr(space_center, "revert_to_launch", None)
        if not callable(revert):
            raise RuntimeError("kRPC SpaceCenter.revert_to_launch is not available")

        revert()
        _set_unpaused(space_center)
        _set_no_time_warp(space_center)

        deadline = time.monotonic() + max(wait_s, 0.0)
        while time.monotonic() < deadline:
            try:
                self.vessel = space_center.active_vessel
                if not self.scenario.vessel_name or self.vessel.name == self.scenario.vessel_name:
                    self.vessel.control.throttle = 0.0
                    self.validate_launchpad_state()
                    return
            except Exception:
                pass
            time.sleep(0.1)

        self.vessel = space_center.active_vessel
        if self.scenario.vessel_name and self.vessel.name != self.scenario.vessel_name:
            raise ValueError(
                f"active vessel is {self.vessel.name!r}, expected {self.scenario.vessel_name!r}"
            )
        self.vessel.control.throttle = 0.0
        self.validate_launchpad_state()

    def validate_launchpad_state(self) -> TelemetrySample:
        """Fail clearly unless the benchmark vessel is ready for a fresh launch."""
        sample = self.read_telemetry()
        problems: list[str] = []
        if sample.body != self.scenario.body:
            problems.append(f"body is {sample.body!r}, expected {self.scenario.body!r}")
        if sample.situation.lower() != "pre_launch":
            problems.append(f"situation is {sample.situation!r}, expected 'pre_launch'")
        if sample.mission_elapsed_s > 5.0:
            problems.append(f"mission elapsed time is {sample.mission_elapsed_s:.1f}s")
        if not sample.intact:
            problems.append("vessel is not intact")
        if not sample.controllable:
            problems.append("vessel is not controllable")
        throttle = _safe_float(lambda: self.vessel.control.throttle)
        if throttle > 0.001:
            problems.append(f"throttle is {throttle:.3f}, expected 0")
        if problems:
            raise RuntimeError("launchpad preflight failed: " + "; ".join(problems))
        return sample

    def close(self) -> None:
        close = getattr(self.conn, "close", None)
        if callable(close):
            close()


def _resource_amount(resources: Any, name: str) -> float:
    try:
        return float(resources.amount(name))
    except Exception:
        return 0.0


def _estimate_remaining_delta_v(vessel: Any) -> float | None:
    """Estimate final-stage vacuum delta-v from live propellant and engine data."""
    mass = _safe_float(lambda: vessel.mass, default=-1.0)
    if mass <= 0:
        return None

    resources = vessel.resources
    propellant_mass = sum(
        _resource_amount(resources, name) * density
        for name, density in _PROPELLANT_DENSITY_KG_PER_UNIT.items()
    )
    if propellant_mass <= 0:
        return 0.0

    engines = list(_safe_value(lambda: vessel.parts.engines, default=[]))
    fueled = [engine for engine in engines if _safe_bool(lambda engine=engine: engine.has_fuel)]
    # A full staged-vessel estimate requires reproducing KSP's staging
    # simulation. Reserve scoring only needs the final fueled stage; return no
    # estimate while multiple fueled engines/stages remain.
    if len(fueled) != 1:
        return None
    active = [engine for engine in fueled if _safe_bool(lambda engine=engine: engine.active)]
    candidates = active or fueled
    vacuum_isp = max(
        (
            _safe_float(lambda engine=engine: engine.vacuum_specific_impulse, default=0.0)
            for engine in candidates
        ),
        default=0.0,
    )
    burnout_mass = mass - propellant_mass
    if vacuum_isp <= 0 or burnout_mass <= 0 or burnout_mass >= mass:
        return None
    return 9.80665 * vacuum_isp * math.log(mass / burnout_mass)


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", value))


def _find_vessel_by_name(space_center: Any, name: str) -> Any | None:
    for vessel in _safe_value(lambda: space_center.vessels, default=[]):
        if _safe_value(lambda vessel=vessel: vessel.name, default=None) == name:
            return vessel
    return None


def _is_controllable(vessel: Any) -> bool:
    try:
        return bool(vessel.control.controllable)
    except Exception:
        try:
            return bool(vessel.parts.controlling)
        except Exception:
            return True


def _is_intact(vessel: Any) -> bool:
    situation = _enum_name(_safe_value(lambda: vessel.situation, default="unknown")).lower()
    return situation not in {"crashed", "destroyed", "dead"}


def _set_unpaused(space_center: Any) -> None:
    if hasattr(space_center, "paused"):
        space_center.paused = False
    elif hasattr(space_center, "game_paused"):
        space_center.game_paused = False


def _set_no_time_warp(space_center: Any) -> None:
    for name in ("rails_warp_factor", "physics_warp_factor"):
        if hasattr(space_center, name):
            setattr(space_center, name, 0)


def _config_int(name: str, default: int, config: dict[str, str]) -> int:
    value = environ.get(name) or config.get(name)
    return default if value is None else int(value)


def _opencode_ksp_environment() -> dict[str, str]:
    path = Path("opencode.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    environment = (
        data.get("mcp", {})
        .get("ksp", {})
        .get("environment", {})
    )
    if not isinstance(environment, dict):
        return {}
    return {str(key): str(value) for key, value in environment.items()}


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


def _current_stage_resources(
    stages: list[dict[str, Any]],
    current_stage: int,
) -> dict[str, float]:
    for stage in stages:
        if stage["stage"] == current_stage:
            resources = stage.get("resources", {})
            if isinstance(resources, dict):
                return {str(name): float(amount) for name, amount in resources.items()}
    return {}


def _next_stage_summary(
    *,
    current_stage: int,
    stages: list[dict[str, Any]],
    engines: list[dict[str, Any]],
    decouplers: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if current_stage <= 0:
        return None
    stage_number = current_stage - 1
    stage_engines = [engine for engine in engines if engine.get("stage") == stage_number]
    stage_decouplers = [
        decoupler for decoupler in decouplers if decoupler.get("stage") == stage_number
    ]
    return {
        "stage": stage_number,
        "resources": _current_stage_resources(stages, stage_number),
        "activate_engines": stage_engines,
        "decouple_parts": stage_decouplers,
        "engine_count": len(stage_engines),
        "decoupler_count": len(stage_decouplers),
    }


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


def _engines(vessel: Any) -> list[dict[str, Any]]:
    engines: list[dict[str, Any]] = []
    try:
        engine_parts = vessel.parts.engines
    except Exception:
        return engines

    for index, engine in enumerate(engine_parts):
        engines.append(
            {
                "index": index,
                "part_name": _safe_value(lambda engine=engine: engine.part.name, default="unknown"),
                "stage": _safe_int(lambda engine=engine: engine.part.stage, default=-1),
                "decouple_stage": _safe_int(
                    lambda engine=engine: engine.part.decouple_stage,
                    default=-1,
                ),
                "active": _safe_bool(lambda engine=engine: engine.active),
                "has_fuel": _safe_bool(lambda engine=engine: engine.has_fuel),
                "thrust": _safe_float(lambda engine=engine: engine.thrust),
                "max_thrust": _safe_float(lambda engine=engine: engine.max_thrust),
            }
        )
    return engines


def _decouplers(vessel: Any) -> list[dict[str, Any]]:
    decouplers: list[dict[str, Any]] = []
    try:
        decoupler_parts = vessel.parts.with_module("ModuleDecouple")
        decoupler_parts += vessel.parts.with_module("ModuleAnchoredDecoupler")
    except Exception:
        return decouplers

    seen: set[int] = set()
    for index, part in enumerate(decoupler_parts):
        marker = id(part)
        if marker in seen:
            continue
        seen.add(marker)
        decouplers.append(
            {
                "index": index,
                "part_name": _safe_value(lambda part=part: part.name, default="unknown"),
                "stage": _safe_int(lambda part=part: part.stage, default=-1),
                "decouple_stage": _safe_int(lambda part=part: part.decouple_stage, default=-1),
            }
        )
    return decouplers


def _vessel_summary(
    vessel: Any,
    *,
    index: int | None,
    current: bool,
) -> dict[str, Any]:
    orbit = _safe_value(lambda: vessel.orbit, default=None)
    body = _safe_value(lambda: orbit.body if orbit is not None else None, default=None)
    return {
        "index": index,
        "name": _safe_value(lambda: vessel.name, default="unknown"),
        "type": _enum_name(_safe_value(lambda: vessel.type, default="unknown")),
        "situation": _enum_name(_safe_value(lambda: vessel.situation, default="unknown")),
        "body": _safe_value(lambda: body.name, default="unknown"),
        "mission_elapsed_s": _safe_float(lambda: vessel.met),
        "current": current,
    }


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

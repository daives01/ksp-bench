from __future__ import annotations

from typing import Any

from bench.telemetry import TelemetrySample


def unrecoverable_no_propulsion_reason(
    sample: TelemetrySample,
    vehicle: dict[str, Any],
    *,
    stable_periapsis_min_m: float,
) -> str | None:
    """Return a terminal reason when a non-orbiting vessel cannot produce thrust."""
    if sample.mission_elapsed_s < 5.0 or sample.situation.lower() == "pre_launch":
        return None
    if sample.periapsis_m >= stable_periapsis_min_m:
        return None
    if _sample_propellant(sample) > 0.1:
        return None
    if sample.remaining_delta_v_m_s is not None and sample.remaining_delta_v_m_s > 0.1:
        return None
    if any(_engine_can_burn(engine) for engine in vehicle.get("engines") or []):
        return None

    next_stage = vehicle.get("next_stage") or {}
    if any(_engine_can_burn(engine) for engine in next_stage.get("activate_engines") or []):
        return None
    next_resources = next_stage.get("resources") or {}
    if any(
        float(next_resources.get(resource, 0.0) or 0.0) > 0.1
        for resource in ("LiquidFuel", "Oxidizer", "SolidFuel")
    ):
        return None
    return "mission_unrecoverable_no_propulsion"


def _engine_can_burn(engine: dict[str, Any]) -> bool:
    return bool(engine.get("has_fuel")) and float(engine.get("max_thrust", 0.0) or 0.0) > 0.1


def _sample_propellant(sample: TelemetrySample) -> float:
    return sample.liquid_fuel + sample.oxidizer + sample.solid_fuel

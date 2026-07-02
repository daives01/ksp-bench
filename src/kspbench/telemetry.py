from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class TelemetrySample:
    mission_elapsed_s: float
    altitude_m: float
    surface_altitude_m: float
    apoapsis_m: float
    periapsis_m: float
    surface_speed_m_s: float
    orbital_speed_m_s: float
    vertical_speed_m_s: float
    pitch_deg: float
    heading_deg: float
    roll_deg: float
    stage: int
    liquid_fuel: float
    oxidizer: float
    solid_fuel: float
    dynamic_pressure_pa: float
    situation: str
    body: str
    controllable: bool
    intact: bool

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> TelemetrySample:
        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in data:
                raise ValueError(f"telemetry missing field: {field.name}")
            values[field.name] = data[field.name]
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TELEMETRY_COLUMNS = [field.name for field in fields(TelemetrySample)]

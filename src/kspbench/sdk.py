from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kspbench.config import Scenario
from kspbench.telemetry import TelemetrySample


@dataclass
class MissionContext:
    scenario: Scenario
    telemetry: list[TelemetrySample] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    invalid_actions: int = 0
    action_executor: Callable[[dict[str, Any]], None] | None = None
    telemetry_provider: Callable[[], TelemetrySample] | None = None

    def latest_telemetry(self) -> TelemetrySample | None:
        return self.telemetry[-1] if self.telemetry else None

    def record_telemetry(self, sample: TelemetrySample) -> None:
        self.telemetry.append(sample)

    def set_throttle(self, value: float) -> None:
        self._record_action("set_throttle", value=max(0.0, min(1.0, value)))

    def set_attitude(self, *, pitch: float, heading: float, roll: float = 0.0) -> None:
        self._record_action("set_attitude", pitch=pitch, heading=heading, roll=roll)

    def set_sas(self, enabled: bool) -> None:
        self._record_action("set_sas", enabled=enabled)

    def set_rcs(self, enabled: bool) -> None:
        self._record_action("set_rcs", enabled=enabled)

    def stage(self) -> None:
        self._record_action("stage")

    def wait(self, seconds: float) -> None:
        if seconds <= 0:
            self.invalid_actions += 1
            self._record_action("invalid_wait", seconds=seconds)
            return
        self._record_action("wait", seconds=seconds)

    def _record_action(self, action_type: str, **payload: Any) -> None:
        allowed = action_type in self.scenario.allowed_controls or action_type.startswith(
            "invalid_"
        )
        if not allowed:
            self.invalid_actions += 1
        event = {
            "index": len(self.actions),
            "mission_elapsed_s": self.latest_telemetry().mission_elapsed_s
            if self.latest_telemetry()
            else 0.0,
            "type": action_type,
            "allowed": allowed,
            **payload,
        }
        if allowed and self.action_executor is not None:
            self.action_executor(event)
            if self.telemetry_provider is not None:
                self.record_telemetry(self.telemetry_provider())
        self.actions.append(event)

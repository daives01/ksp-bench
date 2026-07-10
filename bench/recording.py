from __future__ import annotations

import threading
import time
from collections.abc import Callable

from bench.artifacts import RunArtifacts
from bench.krpc_client import KRPCController
from bench.telemetry import TelemetrySample


class TelemetryRecorder:
    """Sample KSP independently of agent tool calls at a fixed wall-clock cadence."""

    def __init__(
        self,
        *,
        artifacts: RunArtifacts,
        controller_factory: Callable[[], KRPCController],
        interval_s: float = 5.0,
        terminal_reason: Callable[[TelemetrySample, dict[str, object]], str | None] | None = None,
        terminal_confirmations: int = 2,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        if terminal_confirmations <= 0:
            raise ValueError("terminal_confirmations must be positive")
        self.artifacts = artifacts
        self.controller_factory = controller_factory
        self.interval_s = interval_s
        self.terminal_reason = terminal_reason
        self.terminal_confirmations = terminal_confirmations
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("telemetry recorder already started")
        self._thread = threading.Thread(target=self._run, name="ksp-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_s + 1.0))

    def _run(self) -> None:
        controller: KRPCController | None = None
        next_sample = time.monotonic()
        reported_error = False
        pending_reason: str | None = None
        reason_count = 0
        try:
            while not self._stop.is_set():
                try:
                    if controller is None:
                        controller = self.controller_factory()
                    sample = controller.read_telemetry()
                    self.artifacts.append_telemetry_sample(sample)
                    reason = None
                    if self.terminal_reason is not None:
                        reason = self.terminal_reason(sample, controller.read_vehicle_state())
                    if reason is None:
                        pending_reason = None
                        reason_count = 0
                    else:
                        reason_count = reason_count + 1 if reason == pending_reason else 1
                        pending_reason = reason
                        if reason_count >= self.terminal_confirmations:
                            self.artifacts.append_event(
                                {
                                    "type": "run_terminated",
                                    "reason": reason,
                                    "mission_elapsed_s": sample.mission_elapsed_s,
                                }
                            )
                            break
                    reported_error = False
                except Exception as exc:
                    if not reported_error:
                        self.artifacts.append_event(
                            {
                                "type": "telemetry_recorder_error",
                                "error_type": type(exc).__name__,
                                "detail": str(exc),
                            }
                        )
                        reported_error = True
                    if controller is not None:
                        controller.close()
                        controller = None
                next_sample += self.interval_s
                delay = max(0.0, next_sample - time.monotonic())
                if self._stop.wait(delay):
                    break
        finally:
            if controller is not None:
                controller.close()

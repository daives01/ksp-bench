from __future__ import annotations

import ast
import contextlib
import io
import math
import signal
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from kspbench.artifacts import RunArtifacts
from kspbench.config import Scenario
from kspbench.krpc_client import KRPCController
from kspbench.telemetry import TelemetrySample


class KRPCExecutionError(RuntimeError):
    """Raised when an executeKRPC snippet is rejected or fails."""


class KRPCExecutionTimeout(KRPCExecutionError):
    """Raised when an executeKRPC snippet exceeds its wall-clock budget."""


class LiveKRPCTools:
    """Agent-facing tools for closed-loop kRPC control."""

    def __init__(
        self,
        *,
        controller: KRPCController,
        scenario: Scenario,
        artifacts: RunArtifacts,
        execution_timeout_s: float = 30.0,
        max_sleep_s: float = 240.0,
        poll_interval_s: float = 0.5,
        warp_threshold_s: float = 10.0,
        time_warp: bool = True,
        live_events: bool = False,
    ) -> None:
        self.controller = controller
        self.scenario = scenario
        self.artifacts = artifacts
        self.execution_timeout_s = execution_timeout_s
        self.max_sleep_s = max_sleep_s
        self.poll_interval_s = poll_interval_s
        self.warp_threshold_s = warp_threshold_s
        self.time_warp = time_warp
        self.live_events = live_events
        self.telemetry: list[TelemetrySample] = []
        self.actions: list[dict[str, Any]] = []
        self.invalid_actions = 0
        self._scope: dict[str, Any] = {}

    def getTelemetry(self) -> dict[str, Any]:
        return self.get_telemetry()

    def get_telemetry(self) -> dict[str, Any]:
        sample = self.controller.read_telemetry()
        self.record_telemetry(sample)
        payload = sample.to_dict()
        self._emit_event(
            {
                "type": "tool_call",
                "tool": "getTelemetry",
                "mission_elapsed_s": sample.mission_elapsed_s,
            }
        )
        return payload

    def getVehicleState(self) -> dict[str, Any]:
        return self.get_vehicle_state()

    def get_vehicle_state(self) -> dict[str, Any]:
        state = self.controller.read_vehicle_state()
        self._emit_event(
            {
                "type": "tool_call",
                "tool": "getVehicleState",
                "mission_elapsed_s": self._latest_mission_elapsed_s(),
            }
        )
        return state

    def executeKRPC(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        return self.execute_krpc(code, timeout_s=timeout_s)

    def execute_krpc(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        budget_s = self._execution_budget(timeout_s)
        action: dict[str, Any] = {
            "index": len(self.actions),
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
            "type": "execute_krpc",
            "allowed": True,
            "timeout_s": budget_s,
            "code": code,
        }
        started = time.monotonic()
        stdout = io.StringIO()
        try:
            self._validate_code(code)
            scope = self._execution_scope()
            with contextlib.redirect_stdout(stdout):
                self._exec_with_timeout(code, scope, budget_s)
            result = {
                "ok": True,
                "duration_s": round(time.monotonic() - started, 3),
                "stdout": _truncate(stdout.getvalue()),
                "result": _jsonable(scope.get("result")),
            }
            action.update(result)
            return result
        except Exception as exc:
            self.invalid_actions += 1
            result = {
                "ok": False,
                "duration_s": round(time.monotonic() - started, 3),
                "stdout": _truncate(stdout.getvalue()),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            action.update(result)
            return result
        finally:
            self.actions.append(action)
            self.artifacts.append_action(action)
            self._emit_event(
                {
                    "type": "tool_call",
                    "tool": "executeKRPC",
                    "ok": action.get("ok", False),
                    "mission_elapsed_s": self._latest_mission_elapsed_s(),
                }
            )
            try:
                self.record_telemetry(self.controller.read_telemetry())
            except Exception as exc:
                self._emit_event(
                    {
                        "type": "telemetry_read_failed",
                        "tool": "executeKRPC",
                        "error": str(exc),
                    }
                )

    def record_telemetry(self, sample: TelemetrySample) -> None:
        self.telemetry.append(sample)

    def wait(self, seconds: float, *, poll_interval_s: float | None = None) -> dict[str, Any]:
        started = time.monotonic()
        action: dict[str, Any] = {
            "index": len(self.actions),
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
            "type": "wait",
            "allowed": True,
            "seconds": float(seconds),
            "time_warp_requested": self.time_warp and seconds >= self.warp_threshold_s,
        }
        try:
            if seconds < 0:
                raise ValueError("wait seconds must be non-negative")
            if seconds > self.max_sleep_s:
                raise ValueError(f"wait seconds exceeds max_sleep_s={self.max_sleep_s}")
            warped = False
            if self.time_warp and seconds >= self.warp_threshold_s:
                warped = self._time_warp(seconds)
            if not warped:
                self._polling_sleep(seconds, poll_interval_s=poll_interval_s)
            try:
                self.record_telemetry(self.controller.read_telemetry())
            except Exception as exc:
                self._emit_event(
                    {"type": "telemetry_read_failed", "tool": "wait", "error": str(exc)}
                )
            action.update(
                {
                    "ok": True,
                    "duration_s": round(time.monotonic() - started, 3),
                    "time_warp_used": warped,
                }
            )
            return {
                "ok": True,
                "duration_s": action["duration_s"],
                "time_warp_used": warped,
                "telemetry": self.telemetry[-1].to_dict() if self.telemetry else None,
            }
        except Exception as exc:
            self.invalid_actions += 1
            action.update(
                {
                    "ok": False,
                    "duration_s": round(time.monotonic() - started, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            return {
                "ok": False,
                "duration_s": action["duration_s"],
                "error_type": action["error_type"],
                "error": action["error"],
            }
        finally:
            self.actions.append(action)
            self.artifacts.append_action(action)
            self._emit_event(
                {
                    "type": "tool_call",
                    "tool": "wait",
                    "ok": action.get("ok", False),
                    "seconds": float(seconds),
                    "time_warp_used": action.get("time_warp_used", False),
                    "mission_elapsed_s": self._latest_mission_elapsed_s(),
                }
            )

    def _execution_scope(self) -> dict[str, Any]:
        if not self._scope:
            self._scope = {
                "__builtins__": _safe_builtins(),
                "math": math,
                "sleep": self.sleep,
                "wait": self.sleep,
                "wait_until": self.wait_until,
                "getTelemetry": self.getTelemetry,
                "getVehicleState": self.getVehicleState,
            }
        self._scope.update(
            {
                "conn": self.controller.conn,
                "space_center": self.controller.conn.space_center,
                "vessel": self.controller.vessel,
            }
        )
        return self._scope

    def sleep(self, seconds: float, *, poll_interval_s: float | None = None) -> None:
        if seconds < 0:
            raise ValueError("sleep seconds must be non-negative")
        if seconds > self.max_sleep_s:
            raise ValueError(f"sleep seconds exceeds max_sleep_s={self.max_sleep_s}")
        if self.time_warp and seconds >= self.warp_threshold_s and self._time_warp(seconds):
            self.record_telemetry(self.controller.read_telemetry())
            return
        self._polling_sleep(seconds, poll_interval_s=poll_interval_s)

    def _polling_sleep(self, seconds: float, *, poll_interval_s: float | None = None) -> None:
        deadline = time.monotonic() + seconds
        interval = poll_interval_s or self.poll_interval_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(interval, remaining))
            self.record_telemetry(self.controller.read_telemetry())

    def _time_warp(self, seconds: float) -> bool:
        try:
            space_center = self.controller.conn.space_center
            start_ut = float(space_center.ut)
            space_center.warp_to(start_ut + seconds, max_rails_rate=100000, max_physics_rate=4)
            return True
        except Exception as exc:
            self._emit_event(
                {
                    "type": "time_warp_failed",
                    "seconds": float(seconds),
                    "error": str(exc),
                }
            )
            return False

    def wait_until(
        self,
        condition: Callable[[], bool],
        *,
        timeout_s: float,
        poll_interval_s: float | None = None,
    ) -> bool:
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        if timeout_s > self.max_sleep_s:
            raise ValueError(f"timeout_s exceeds max_sleep_s={self.max_sleep_s}")
        deadline = time.monotonic() + timeout_s
        interval = poll_interval_s or self.poll_interval_s
        while True:
            if condition():
                self.record_telemetry(self.controller.read_telemetry())
                return True
            if time.monotonic() >= deadline:
                self.record_telemetry(self.controller.read_telemetry())
                return False
            time.sleep(interval)
            self.record_telemetry(self.controller.read_telemetry())

    def _execution_budget(self, requested_timeout_s: float | None) -> float:
        budget = (
            requested_timeout_s if requested_timeout_s is not None else self.execution_timeout_s
        )
        if budget <= 0:
            raise ValueError("timeout_s must be positive")
        return min(float(budget), self.max_sleep_s)

    def _validate_code(self, code: str) -> None:
        if not code.strip():
            raise KRPCExecutionError("executeKRPC code must not be empty")
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise KRPCExecutionError(str(exc)) from exc

        banned_calls = {"breakpoint", "compile", "eval", "exec", "input", "open", "__import__"}
        banned_krpc_methods = {
            "load",
            "quickload",
            "quicksave",
            "revert_to_launch",
            "revert_to_editor",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                raise KRPCExecutionError("imports are not allowed inside executeKRPC")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise KRPCExecutionError("dunder names are not allowed inside executeKRPC")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise KRPCExecutionError("dunder attributes are not allowed inside executeKRPC")
            if isinstance(node, ast.Attribute) and node.attr in banned_krpc_methods:
                raise KRPCExecutionError(f"{node.attr} is reserved for the benchmark harness")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in banned_calls
            ):
                raise KRPCExecutionError(f"{node.func.id} is not allowed inside executeKRPC")

    def _exec_with_timeout(self, code: str, scope: dict[str, Any], timeout_s: float) -> None:
        if threading.current_thread() is not threading.main_thread():
            exec(compile(code, "<executeKRPC>", "exec"), scope, scope)
            return

        previous_handler = signal.getsignal(signal.SIGALRM)

        def handle_timeout(_signum: int, _frame: Any) -> None:
            raise KRPCExecutionTimeout(f"executeKRPC exceeded {timeout_s:.3f}s")

        signal.signal(signal.SIGALRM, handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            exec(compile(code, "<executeKRPC>", "exec"), scope, scope)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def _latest_mission_elapsed_s(self) -> float:
        return self.telemetry[-1].mission_elapsed_s if self.telemetry else 0.0

    def _emit_event(self, event: dict[str, Any]) -> None:
        self.artifacts.append_event(event)
        if not self.live_events:
            return
        if event.get("type") == "tool_call":
            tool = event.get("tool", "tool")
            status = ""
            if "ok" in event:
                status = " ok" if event["ok"] else " failed"
            met = event.get("mission_elapsed_s")
            met_text = f" met={float(met):.1f}s" if isinstance(met, int | float) else ""
            extra = ""
            if tool == "wait":
                extra = f" seconds={event.get('seconds')} warp={event.get('time_warp_used')}"
            print(f"[kspbench] {tool}{status}{met_text}{extra}", file=sys.stderr, flush=True)
        elif event.get("type") == "time_warp_failed":
            print(
                f"[kspbench] time warp failed; falling back to sleep: {event.get('error')}",
                file=sys.stderr,
                flush=True,
            )


def _safe_builtins() -> dict[str, Any]:
    return {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "print": print,
        "range": range,
        "round": round,
        "set": set,
        "str": str,
        "sum": sum,
        "tuple": tuple,
    }


def _truncate(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 15] + "...<truncated>"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return repr(value)

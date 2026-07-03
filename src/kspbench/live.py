from __future__ import annotations

import ast
import contextlib
import io
import math
import signal
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
    ) -> None:
        self.controller = controller
        self.scenario = scenario
        self.artifacts = artifacts
        self.execution_timeout_s = execution_timeout_s
        self.max_sleep_s = max_sleep_s
        self.poll_interval_s = poll_interval_s
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
        self.artifacts.append_event(
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
        self.artifacts.append_event(
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
            self.artifacts.append_event(
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
                self.artifacts.append_event(
                    {
                        "type": "telemetry_read_failed",
                        "tool": "executeKRPC",
                        "error": str(exc),
                    }
                )

    def record_telemetry(self, sample: TelemetrySample) -> None:
        self.telemetry.append(sample)

    def _execution_scope(self) -> dict[str, Any]:
        if not self._scope:
            self._scope = {
                "__builtins__": _safe_builtins(),
                "math": math,
                "sleep": self.sleep,
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
        deadline = time.monotonic() + seconds
        interval = poll_interval_s or self.poll_interval_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(interval, remaining))
            self.record_telemetry(self.controller.read_telemetry())

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
            requested_timeout_s
            if requested_timeout_s is not None
            else self.execution_timeout_s
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
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                raise KRPCExecutionError("imports are not allowed inside executeKRPC")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise KRPCExecutionError("dunder names are not allowed inside executeKRPC")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise KRPCExecutionError("dunder attributes are not allowed inside executeKRPC")
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

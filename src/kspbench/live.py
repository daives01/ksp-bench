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
from dataclasses import dataclass, field
from typing import Any

from kspbench.artifacts import RunArtifacts
from kspbench.config import Scenario
from kspbench.krpc_client import KRPCController
from kspbench.telemetry import TelemetrySample


class KRPCExecutionError(RuntimeError):
    """Raised when an executeKRPC snippet is rejected or fails."""


class KRPCExecutionTimeout(KRPCExecutionError):
    """Raised when an executeKRPC snippet exceeds its wall-clock budget."""


class KSPRunTerminated(RuntimeError):
    """Raised when the active vessel can no longer continue the benchmark."""


class AtmosphericWaitDisallowed(KRPCExecutionError):
    """Raised when an agent tries to wait too long while flying in atmosphere."""


@dataclass
class AsyncScript:
    script_id: str
    code: str
    timeout_s: float
    started_monotonic: float
    status: str = "running"
    stdout: str = ""
    result: Any = None
    error_type: str | None = None
    error: str | None = None
    finished_monotonic: float | None = None
    stop_requested: bool = False
    thread: threading.Thread | None = field(default=None, repr=False)


class AsyncScriptStopped(KRPCExecutionError):
    """Raised when an async script observes a cooperative stop request."""


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
        max_atmospheric_sleep_s: float = 2.0,
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
        self.max_atmospheric_sleep_s = max_atmospheric_sleep_s
        self.poll_interval_s = poll_interval_s
        self.warp_threshold_s = warp_threshold_s
        self.time_warp = time_warp
        self.live_events = live_events
        self.telemetry: list[TelemetrySample] = []
        self.actions: list[dict[str, Any]] = []
        self.invalid_actions = 0
        self.terminated = False
        self.termination_reason: str | None = None
        self._scope: dict[str, Any] = {}
        self._async_scripts: dict[str, AsyncScript] = {}
        self._async_lock = threading.Lock()
        self._krpc_lock = threading.RLock()
        self._next_async_script_id = 1

    def getTelemetry(self) -> dict[str, Any]:
        return self.get_telemetry()

    def get_telemetry(self) -> dict[str, Any]:
        with self._krpc_lock:
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
        with self._krpc_lock:
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

    def executeKRPCAsync(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        return self.execute_krpc_async(code, timeout_s=timeout_s)

    def checkAsync(self, script_id: str | None = None) -> dict[str, Any]:
        return self.check_async(script_id)

    def killAsync(self, script_id: str) -> dict[str, Any]:
        return self.kill_async(script_id)

    @property
    def krpc_lock(self) -> Any:
        return self._krpc_lock

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
        if self.terminated:
            action.update(
                {
                    "allowed": False,
                    "ok": False,
                    "duration_s": 0.0,
                    "error_type": "KSPRunTerminated",
                    "error": self.termination_reason or "run already terminated",
                }
            )
            self.invalid_actions += 1
            self.actions.append(action)
            self.artifacts.append_action(action)
            self._emit_event(
                {
                    "type": "tool_call",
                    "tool": "executeKRPC",
                    "ok": False,
                    "mission_elapsed_s": self._latest_mission_elapsed_s(),
                }
            )
            return {
                "ok": False,
                "duration_s": 0.0,
                "error_type": action["error_type"],
                "error": action["error"],
            }
        started = time.monotonic()
        stdout = io.StringIO()
        try:
            self._validate_code(code)
            scope = self._execution_scope()
            with self._krpc_lock, contextlib.redirect_stdout(stdout):
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
            if isinstance(exc, KRPCExecutionTimeout):
                self._emit_event(
                    {
                        "type": "execute_krpc_timeout",
                        "reason": "execute_krpc_timeout",
                        "detail": str(exc),
                        "mission_elapsed_s": self._latest_mission_elapsed_s(),
                    }
                )
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
            if action.get("error_type") != "KRPCExecutionTimeout":
                try:
                    with self._krpc_lock:
                        self.record_telemetry(self.controller.read_telemetry())
                except Exception as exc:
                    self._emit_event(
                        {
                            "type": "telemetry_read_failed",
                            "tool": "executeKRPC",
                            "error": str(exc),
                        }
                    )

    def execute_krpc_async(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        budget_s = self._execution_budget(timeout_s)
        try:
            self._validate_code(code)
        except Exception as exc:
            self.invalid_actions += 1
            return {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        with self._async_lock:
            script_id = f"script-{self._next_async_script_id}"
            self._next_async_script_id += 1
            script = AsyncScript(
                script_id=script_id,
                code=code,
                timeout_s=budget_s,
                started_monotonic=time.monotonic(),
            )
            self._async_scripts[script_id] = script

        action: dict[str, Any] = {
            "index": len(self.actions),
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
            "type": "execute_krpc_async",
            "allowed": True,
            "script_id": script_id,
            "timeout_s": budget_s,
            "code": code,
            "ok": True,
        }
        self.actions.append(action)
        self.artifacts.append_action(action)
        thread = threading.Thread(
            target=self._run_async_script,
            args=(script,),
            name=f"kspbench-{script_id}",
            daemon=True,
        )
        script.thread = thread
        thread.start()
        self._emit_event(
            {
                "type": "tool_call",
                "tool": "executeKRPCAsync",
                "ok": True,
                "script_id": script_id,
                "mission_elapsed_s": self._latest_mission_elapsed_s(),
            }
        )
        return {
            "ok": True,
            "script_id": script_id,
            "status": script.status,
            "timeout_s": budget_s,
        }

    def check_async(self, script_id: str | None = None) -> dict[str, Any]:
        with self._async_lock:
            scripts = list(self._async_scripts.values())
            if script_id is not None:
                script = self._async_scripts.get(script_id)
                if script is None:
                    return {"ok": False, "error": f"unknown script_id: {script_id}"}
                payload = {"script": self._async_status(script)}
            else:
                payload = {"scripts": [self._async_status(script) for script in scripts]}
        self._emit_event(
            {
                "type": "tool_call",
                "tool": "checkAsync",
                "mission_elapsed_s": self._latest_mission_elapsed_s(),
            }
        )
        return {"ok": True, **payload}

    def kill_async(self, script_id: str) -> dict[str, Any]:
        with self._async_lock:
            script = self._async_scripts.get(script_id)
            if script is None:
                return {"ok": False, "error": f"unknown script_id: {script_id}"}
            if script.status == "running":
                script.stop_requested = True
                status = "stop_requested"
            else:
                status = script.status
            payload = self._async_status(script)
        self._emit_event(
            {
                "type": "tool_call",
                "tool": "killAsync",
                "script_id": script_id,
                "mission_elapsed_s": self._latest_mission_elapsed_s(),
            }
        )
        return {"ok": True, "status": status, "script": payload}

    def _run_async_script(self, script: AsyncScript) -> None:
        stdout_chunks: list[str] = []

        def async_print(*values: Any, sep: str = " ", end: str = "\n") -> None:
            stdout_chunks.append(sep.join(str(value) for value in values) + end)

        def raise_if_stopped() -> None:
            if script.stop_requested:
                raise AsyncScriptStopped(f"{script.script_id} stopped")

        def async_sleep(seconds: float, *, poll_interval_s: float | None = None) -> None:
            interval = poll_interval_s or self.poll_interval_s
            deadline = time.monotonic() + seconds
            while True:
                raise_if_stopped()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self.sleep(min(interval, remaining), poll_interval_s=interval)

        def async_wait_until(
            condition: Callable[[], bool],
            *,
            timeout_s: float,
            poll_interval_s: float | None = None,
        ) -> bool:
            interval = poll_interval_s or self.poll_interval_s
            deadline = time.monotonic() + timeout_s
            while True:
                raise_if_stopped()
                if condition():
                    return True
                if time.monotonic() >= deadline:
                    return False
                async_sleep(min(interval, deadline - time.monotonic()), poll_interval_s=interval)

        scope = self._execution_scope(
            extra={
                "sleep": async_sleep,
                "wait": async_sleep,
                "wait_until": async_wait_until,
                "should_stop": lambda: script.stop_requested,
            }
        )
        scope["__builtins__"] = {**_safe_builtins(), "print": async_print}
        try:
            with self._krpc_lock:
                self._exec_with_trace_timeout(script.code, scope, script.timeout_s, script=script)
            with self._async_lock:
                script.status = "done"
                script.result = _jsonable(scope.get("result"))
        except Exception as exc:
            with self._async_lock:
                script.status = "stopped" if isinstance(exc, AsyncScriptStopped) else "failed"
                script.error_type = type(exc).__name__
                script.error = str(exc)
            if not isinstance(exc, AsyncScriptStopped):
                self.invalid_actions += 1
        finally:
            with self._async_lock:
                script.stdout = _truncate("".join(stdout_chunks))
                script.finished_monotonic = time.monotonic()
                self.artifacts.append_event(
                    {
                        "type": "async_script_finished",
                        "script_id": script.script_id,
                        "status": script.status,
                        "error_type": script.error_type,
                        "error": script.error,
                    }
                )

    def _async_status(self, script: AsyncScript) -> dict[str, Any]:
        now = time.monotonic()
        finished = script.finished_monotonic
        elapsed_s = (finished if finished is not None else now) - script.started_monotonic
        return {
            "script_id": script.script_id,
            "status": script.status,
            "running": script.status == "running",
            "stop_requested": script.stop_requested,
            "elapsed_s": round(elapsed_s, 3),
            "timeout_s": script.timeout_s,
            "stdout": script.stdout,
            "result": _jsonable(script.result),
            "error_type": script.error_type,
            "error": script.error,
        }

    def record_telemetry(self, sample: TelemetrySample) -> None:
        self.telemetry.append(sample)
        reason = self._terminal_reason(sample)
        if reason and not self.terminated:
            self.terminated = True
            self.termination_reason = reason
            self._emit_event(
                {
                    "type": "run_terminated",
                    "reason": reason,
                    "mission_elapsed_s": sample.mission_elapsed_s,
                }
            )

    def _raise_if_terminated(self) -> None:
        if self.terminated:
            raise KSPRunTerminated(self.termination_reason or "run terminated")

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
            self._raise_if_terminated()
            if seconds < 0:
                raise ValueError("wait seconds must be non-negative")
            if seconds > self.max_sleep_s:
                raise ValueError(f"wait seconds exceeds max_sleep_s={self.max_sleep_s}")
            self._raise_if_atmospheric_wait(seconds, "wait")
            warped = False
            if self.time_warp and seconds >= self.warp_threshold_s:
                warped = self._time_warp(seconds)
            if not warped:
                self._polling_sleep(seconds, poll_interval_s=poll_interval_s)
            try:
                with self._krpc_lock:
                    self.record_telemetry(self.controller.read_telemetry())
                self._raise_if_terminated()
            except KSPRunTerminated:
                raise
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

    def _execution_scope(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = {} if extra is not None else self._scope
        if not scope:
            scope = {
                "__builtins__": _safe_builtins(),
                "math": math,
                "sleep": self.sleep,
                "wait": self.sleep,
                "wait_until": self.wait_until,
                "getTelemetry": self.getTelemetry,
                "getVehicleState": self.getVehicleState,
            }
            if extra is None:
                self._scope = scope
        scope.update(
            {
                "conn": self.controller.conn,
                "space_center": self.controller.conn.space_center,
                "vessel": self.controller.vessel,
            }
        )
        if extra:
            scope.update(extra)
        return scope

    def sleep(self, seconds: float, *, poll_interval_s: float | None = None) -> None:
        self._raise_if_terminated()
        if seconds < 0:
            raise ValueError("sleep seconds must be non-negative")
        if seconds > self.max_sleep_s:
            raise ValueError(f"sleep seconds exceeds max_sleep_s={self.max_sleep_s}")
        self._raise_if_atmospheric_wait(seconds, "sleep")
        if self.time_warp and seconds >= self.warp_threshold_s and self._time_warp(seconds):
            with self._krpc_lock:
                self.record_telemetry(self.controller.read_telemetry())
            self._raise_if_terminated()
            return
        self._polling_sleep(seconds, poll_interval_s=poll_interval_s)

    def _raise_if_atmospheric_wait(self, seconds: float, helper: str) -> None:
        if seconds <= self.max_atmospheric_sleep_s or not self._in_atmosphere():
            return
        raise AtmosphericWaitDisallowed(
            f"{helper}({seconds:g}) is disabled in atmosphere; use short control-loop "
            f"sleeps <= {self.max_atmospheric_sleep_s:g}s and re-check telemetry"
        )

    def _polling_sleep(self, seconds: float, *, poll_interval_s: float | None = None) -> None:
        deadline = time.monotonic() + seconds
        interval = poll_interval_s or self.poll_interval_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(interval, remaining))
            with self._krpc_lock:
                self.record_telemetry(self.controller.read_telemetry())
            self._raise_if_terminated()

    def _time_warp(self, seconds: float) -> bool:
        try:
            if self._in_atmosphere():
                self._emit_event(
                    {
                        "type": "time_warp_skipped",
                        "seconds": float(seconds),
                        "reason": "in_atmosphere",
                    }
                )
                return False
            with self._krpc_lock:
                space_center = self.controller.conn.space_center
                start_ut = float(space_center.ut)
                space_center.warp_to(
                    start_ut + seconds,
                    max_rails_rate=100000,
                    max_physics_rate=4,
                )
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

    def _in_atmosphere(self) -> bool:
        if self.telemetry:
            sample = self.telemetry[-1]
        else:
            with self._krpc_lock:
                sample = self.controller.read_telemetry()
                self.record_telemetry(sample)
        try:
            with self._krpc_lock:
                atmosphere_depth = float(self.controller.vessel.orbit.body.atmosphere_depth)
        except Exception:
            atmosphere_depth = 0.0
        return atmosphere_depth > 0.0 and sample.altitude_m < atmosphere_depth

    def _terminal_reason(self, sample: TelemetrySample) -> str | None:
        if not sample.intact:
            return "vessel_not_intact"
        if not sample.controllable:
            return "vessel_not_controllable"
        terminal_situations = {"crashed", "destroyed", "dead"}
        situation = sample.situation.lower()
        if situation in terminal_situations:
            return f"vessel_{situation}"
        return None

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
        self._raise_if_atmospheric_wait(timeout_s, "wait_until")
        deadline = time.monotonic() + timeout_s
        interval = poll_interval_s or self.poll_interval_s
        while True:
            if condition():
                with self._krpc_lock:
                    self.record_telemetry(self.controller.read_telemetry())
                self._raise_if_terminated()
                return True
            if time.monotonic() >= deadline:
                with self._krpc_lock:
                    self.record_telemetry(self.controller.read_telemetry())
                self._raise_if_terminated()
                return False
            time.sleep(interval)
            with self._krpc_lock:
                self.record_telemetry(self.controller.read_telemetry())
            self._raise_if_terminated()

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
            if isinstance(node, ast.Import | ast.ImportFrom) and not _is_allowed_import(node):
                raise KRPCExecutionError(
                    "imports are not allowed inside executeKRPC, except import math"
                )
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
            self._exec_with_trace_timeout(code, scope, timeout_s)
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

    def _exec_with_trace_timeout(
        self,
        code: str,
        scope: dict[str, Any],
        timeout_s: float,
        *,
        script: AsyncScript | None = None,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        previous_trace = sys.gettrace()

        def trace_timeout(frame: Any, event: str, arg: Any) -> Any:
            if script is not None and script.stop_requested:
                raise AsyncScriptStopped(f"{script.script_id} stopped")
            if time.monotonic() > deadline:
                raise KRPCExecutionTimeout(f"executeKRPC exceeded {timeout_s:.3f}s")
            return trace_timeout

        sys.settrace(trace_timeout)
        try:
            exec(compile(code, "<executeKRPC>", "exec"), scope, scope)
        finally:
            sys.settrace(previous_trace)

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
        elif event.get("type") == "time_warp_skipped":
            print(
                f"[kspbench] time warp skipped: {event.get('reason')}",
                file=sys.stderr,
                flush=True,
            )
        elif event.get("type") == "run_terminated":
            print(
                f"[kspbench] run terminated: {event.get('reason')}",
                file=sys.stderr,
                flush=True,
            )


def _safe_builtins() -> dict[str, Any]:
    return {
        "__import__": _safe_import,
        "abs": abs,
        "all": all,
        "any": any,
        "BaseException": BaseException,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "Exception": Exception,
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


def _is_allowed_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return all(alias.name == "math" and alias.asname in (None, "math") for alias in node.names)
    return node.module == "math" and node.level == 0


def _safe_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if name == "math" and level == 0:
        return math
    raise ImportError("only import math is allowed inside executeKRPC")


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

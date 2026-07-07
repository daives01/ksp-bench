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

from bench.artifacts import RunArtifacts
from bench.config import Scenario
from bench.krpc_client import KRPCController
from bench.telemetry import TelemetrySample


class FlightToolError(RuntimeError):
    """Raised when an agent tool call is rejected or fails."""


class PythonExecutionTimeout(FlightToolError):
    """Raised when an agent Python snippet exceeds its wall-clock budget."""


class FlightTerminated(FlightToolError):
    """Raised when the active vessel can no longer continue the benchmark."""


class TaskStopped(FlightToolError):
    """Raised when a background task observes a cooperative stop request."""


def _enable_sas_if_needed(vessel: Any) -> bool:
    control = vessel.control
    if not control.sas:
        control.sas = True
        return True
    return False


@dataclass
class ControlTask:
    task_id: str
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


class FlightSession:
    """Small agent-facing control surface for a live KSP benchmark run."""

    def __init__(
        self,
        *,
        controller: KRPCController,
        scenario: Scenario,
        artifacts: RunArtifacts,
        python_timeout_s: float = 15.0,
        task_timeout_s: float = 180.0,
        max_wait_s: float = 240.0,
        max_atmospheric_wait_s: float = 2.0,
        max_sync_python_s: float = 8.0,
        poll_interval_s: float = 0.5,
        live_events: bool = False,
        execution_timeout_s: float | None = None,
        max_sleep_s: float | None = None,
        max_atmospheric_sleep_s: float | None = None,
        task_controller_factory: Callable[[], KRPCController] | None = None,
        controller_reconnect_factory: Callable[[KRPCController], KRPCController] | None = None,
        **_unused: Any,
    ) -> None:
        self.controller = controller
        self.scenario = scenario
        self.artifacts = artifacts
        self.python_timeout_s = execution_timeout_s or python_timeout_s
        self.task_timeout_s = task_timeout_s
        self.max_wait_s = max_sleep_s or max_wait_s
        self.max_atmospheric_wait_s = max_atmospheric_sleep_s or max_atmospheric_wait_s
        self.max_sync_python_s = max_sync_python_s
        self.poll_interval_s = poll_interval_s
        self.live_events = live_events
        self.telemetry: list[TelemetrySample] = []
        self.actions: list[dict[str, Any]] = []
        self.invalid_actions = 0
        self.terminated = False
        self.termination_reason: str | None = None
        self._krpc_lock = threading.RLock()
        self._task_lock = threading.Lock()
        self._tasks: dict[str, ControlTask] = {}
        self._task_controller_factory = task_controller_factory or (
            lambda: KRPCController.connect(scenario)
        )
        self._controller_reconnect_factory = controller_reconnect_factory
        self._next_task_id = 1
        self._orbit_diverged = False
        self._initial_propellant: float | None = None

    @property
    def krpc_lock(self) -> Any:
        return self._krpc_lock

    def observe(self) -> dict[str, Any]:
        started = time.monotonic()
        action: dict[str, Any] = {
            "type": "observe",
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
        }
        try:
            with self._krpc_lock:
                sample = self._read_telemetry_or_terminate(self.controller)
                self._raise_if_terminated()
                vehicle = self.controller.read_vehicle_state()
            payload = {
                "telemetry": sample.to_dict(),
                "vehicle": vehicle,
                "target_orbit": {
                    "altitude_m": self.scenario.target_orbit.altitude_m,
                    "stable_periapsis_min_m": self.scenario.target_orbit.stable_periapsis_min_m,
                },
                "terminated": self.terminated,
                "termination_reason": self.termination_reason,
            }
            result = {"ok": True, **payload}
            action.update(result)
            action["mission_elapsed_s"] = sample.mission_elapsed_s
            return result
        except Exception as exc:
            if self._terminate_for_controller_error(exc):
                exc = FlightTerminated(self.termination_reason or "run terminated")
            result = self._failure(exc, started=started)
            action.update(result)
            return result
        finally:
            self._append_action(action)

    def set_throttle(self, value: float) -> dict[str, Any]:
        value = max(0.0, min(1.0, float(value)))

        def apply() -> dict[str, Any]:
            self.controller.vessel.control.throttle = value
            return {"throttle": value}

        return self._command("set_throttle", apply, throttle=value)

    def stage(self) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            parts = self.controller.vessel.control.activate_next_stage()
            return {"activated_parts": len(parts) if parts is not None else None}

        return self._command("stage", apply)

    def set_attitude(
        self,
        mode: str,
        *,
        pitch: float | None = None,
        heading: float | None = None,
        reference_frame: str = "orbital",
    ) -> dict[str, Any]:
        mode = mode.replace("-", "_")
        if mode == "pitch_heading":
            if pitch is None or heading is None:
                raise ValueError("pitch and heading are required for pitch_heading mode")
            pitch = float(pitch)
            heading = float(heading)

            def apply() -> dict[str, Any]:
                vessel = self.controller.vessel
                _enable_sas_if_needed(vessel)
                autopilot = vessel.auto_pilot
                autopilot.engage()
                autopilot.target_pitch_and_heading(pitch, heading)
                return {"mode": mode, "pitch": pitch, "heading": heading}

            return self._command("set_attitude", apply, mode=mode, pitch=pitch, heading=heading)

        def apply() -> dict[str, Any]:
            vessel = self.controller.vessel
            _enable_sas_if_needed(vessel)
            frame = _reference_frame(vessel, reference_frame)
            flight = vessel.flight(frame)
            direction = _flight_direction(flight, mode)
            autopilot = vessel.auto_pilot
            autopilot.reference_frame = frame
            autopilot.target_direction = direction
            autopilot.engage()
            return {
                "mode": mode,
                "reference_frame": reference_frame,
                "target_direction": direction,
            }

        return self._command("set_attitude", apply, mode=mode, reference_frame=reference_frame)

    def wait(self, seconds: float) -> dict[str, Any]:
        started = time.monotonic()
        action: dict[str, Any] = {
            "type": "wait",
            "seconds": float(seconds),
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
        }
        try:
            self._raise_if_terminated()
            self._sleep(float(seconds), controller=self.controller)
            telemetry = self.telemetry[-1].to_dict() if self.telemetry else None
            result = {
                "ok": True,
                "duration_s": round(time.monotonic() - started, 3),
                "telemetry": telemetry,
            }
            action.update(result)
            return result
        except Exception as exc:
            if self._terminate_for_controller_error(exc):
                exc = FlightTerminated(self.termination_reason or "run terminated")
            result = self._failure(exc, started=started)
            action.update(result)
            return result
        finally:
            self._append_action(action)

    def execute_python(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        started = time.monotonic()
        budget_s = self._timeout(timeout_s, default=self.python_timeout_s)
        budget_s = min(budget_s, self.max_sync_python_s)
        action: dict[str, Any] = {
            "type": "execute_python",
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
            "timeout_s": budget_s,
            "code": code,
        }
        stdout = io.StringIO()
        try:
            self._raise_if_terminated()
            self._validate_code(code)
            scope = self._execution_scope(controller=self.controller)
            if not self._krpc_lock.acquire(timeout=budget_s):
                raise self._sync_python_timeout(budget_s)
            try:
                with contextlib.redirect_stdout(stdout):
                    self._exec_with_timeout(code, scope, budget_s)
                    self._read_telemetry_or_terminate(self.controller)
                    self._raise_if_terminated()
            finally:
                self._krpc_lock.release()
            result = {
                "ok": True,
                "duration_s": round(time.monotonic() - started, 3),
                "stdout": _truncate(stdout.getvalue()),
                "result": _jsonable(scope.get("result")),
            }
            action.update(result)
            return result
        except Exception as exc:
            if self._terminate_for_controller_error(exc):
                exc = FlightTerminated(self.termination_reason or "run terminated")
            result = self._failure(exc, started=started, stdout=stdout.getvalue())
            action.update(result)
            return result
        finally:
            self._append_action(action)

    def start_task(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        budget_s = self._timeout(timeout_s, default=self.task_timeout_s)
        started = time.monotonic()
        action: dict[str, Any] = {
            "type": "start_task",
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
            "timeout_s": budget_s,
            "code": code,
        }
        try:
            self._raise_if_terminated()
            self._validate_code(code)
            with self._task_lock:
                task_id = f"task-{self._next_task_id}"
                self._next_task_id += 1
                task = ControlTask(
                    task_id=task_id,
                    code=code,
                    timeout_s=budget_s,
                    started_monotonic=time.monotonic(),
                )
                self._tasks[task_id] = task
            thread = threading.Thread(
                target=self._run_task,
                args=(task,),
                name=f"bench-control-{task.task_id}",
                daemon=True,
            )
            task.thread = thread
            thread.start()
            result = {"ok": True, "task_id": task.task_id, "status": task.status}
            action.update(result)
            return result
        except Exception as exc:
            if self._terminate_for_controller_error(exc):
                exc = FlightTerminated(self.termination_reason or "run terminated")
            result = self._failure(exc, started=started)
            action.update(result)
            return result
        finally:
            self._append_action(action)

    def check_task(self, task_id: str | None = None) -> dict[str, Any]:
        payload = self.task_snapshot(task_id=task_id)
        self._record_action("check_task", ok=True)
        return {"ok": True, **payload}

    def task_snapshot(self, task_id: str | None = None) -> dict[str, Any]:
        with self._task_lock:
            if task_id is not None:
                task = self._tasks.get(task_id)
                status = self._task_status(task)
                statuses = [status] if status else []
            else:
                statuses = [self._task_status(task) for task in self._tasks.values()]
                status = _current_task_status(statuses)
        latest_telemetry = self.telemetry[-1].to_dict() if self.telemetry else None
        return {
            "task": status,
            "tasks": statuses,
            "latest_telemetry": latest_telemetry,
        }

    def stop_task(self, task_id: str | None = None) -> dict[str, Any]:
        with self._task_lock:
            task: ControlTask | None
            if task_id is not None:
                task = self._tasks.get(task_id)
                if task is None:
                    self._record_action("stop_task", ok=False, task_id=task_id)
                    return {"ok": False, "error": f"unknown task_id: {task_id}", "task": None}
            else:
                running = [task for task in self._tasks.values() if task.status == "running"]
                if len(running) > 1:
                    ids = ", ".join(task.task_id for task in running)
                    self._record_action("stop_task", ok=False)
                    return {
                        "ok": False,
                        "error": f"multiple tasks are running; pass task_id ({ids})",
                        "task": None,
                    }
                task = running[0] if running else _latest_task(self._tasks)
            if task is not None and task.status == "running":
                task.stop_requested = True
            status = self._task_status(task)
        self._record_action("stop_task", ok=True)
        return {"ok": True, "task": status}

    def list_vehicles(self) -> dict[str, Any]:
        return self._command("list_vehicles", self.controller.list_vessels)

    def set_vehicle(
        self,
        *,
        name: str | None = None,
        index: int | None = None,
        make_active: bool = True,
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            return self.controller.select_vessel(name=name, index=index, make_active=make_active)

        return self._command(
            "set_vehicle",
            apply,
            name=name,
            index=index,
            make_active=make_active,
        )

    def reset_launchpad(self, *, wait_s: float = 2.0) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            self.controller.prepare_for_launchpad_run(wait_s=wait_s)
            return {"wait_s": wait_s, "vehicle_name": self.controller.vessel.name}

        return self._command("reset_launchpad", apply, wait_s=wait_s)

    def getTelemetry(self) -> dict[str, Any]:
        return self.observe()["telemetry"]

    def getVehicleState(self) -> dict[str, Any]:
        return self.observe()["vehicle"]

    def getOrbitState(self) -> dict[str, Any]:
        telemetry = self.getTelemetry()
        return {
            key: telemetry[key]
            for key in (
                "mission_elapsed_s",
                "altitude_m",
                "apoapsis_m",
                "periapsis_m",
                "time_to_apoapsis_s",
                "time_to_periapsis_s",
                "eccentricity",
                "inclination_deg",
                "orbital_speed_m_s",
                "liquid_fuel",
                "oxidizer",
                "stage",
                "situation",
                "controllable",
                "intact",
            )
        }

    def executeKRPC(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        return self.execute_python(code, timeout_s=timeout_s)

    def executeKRPCAsync(self, code: str, *, timeout_s: float | None = None) -> dict[str, Any]:
        result = self.start_task(code, timeout_s=timeout_s)
        if result.get("ok"):
            result["script_id"] = result["task_id"]
        return result

    def checkAsync(self, script_id: str | None = None) -> dict[str, Any]:
        result = self.check_task(task_id=script_id)
        task = result.pop("task")
        if script_id is not None and task is None:
            return {"ok": False, "error": f"unknown script_id: {script_id}"}
        return {
            "ok": True,
            "script": task,
            "scripts": result["tasks"],
            "latest_telemetry": result["latest_telemetry"],
        }

    def killAsync(self, script_id: str) -> dict[str, Any]:
        result = self.stop_task(task_id=script_id)
        if not result.get("ok"):
            return {"ok": False, "error": f"unknown script_id: {script_id}"}
        return {"ok": True, "status": "stop_requested", "script": result["task"]}

    def record_telemetry(self, sample: TelemetrySample) -> None:
        self.telemetry.append(sample)
        self.artifacts.append_telemetry_sample(sample)
        propellant = _sample_propellant(sample)
        if self._initial_propellant is None:
            self._initial_propellant = propellant
        if self._orbit_has_diverged(sample):
            self._emit_event(
                {
                    "type": "orbit_target_diverged",
                    "mission_elapsed_s": sample.mission_elapsed_s,
                    "apoapsis_m": sample.apoapsis_m,
                    "periapsis_m": sample.periapsis_m,
                    "target_altitude_m": self.scenario.target_orbit.altitude_m,
                    "stable_periapsis_min_m": self.scenario.target_orbit.stable_periapsis_min_m,
                }
            )
        reason = self._terminal_reason(sample)
        if reason:
            self._terminate(reason, mission_elapsed_s=sample.mission_elapsed_s)

    def _command(
        self,
        action_name: str,
        apply: Callable[[], dict[str, Any]],
        **params: Any,
    ) -> dict[str, Any]:
        started = time.monotonic()
        action: dict[str, Any] = {
            "type": action_name,
            "mission_elapsed_s": self._latest_mission_elapsed_s(),
            **params,
        }
        try:
            self._raise_if_terminated()
            with self._krpc_lock:
                payload = apply()
                sample = self._read_telemetry_or_terminate(self.controller)
                self._raise_if_terminated()
            result = {"ok": True, **payload, "telemetry": sample.to_dict()}
            action.update(result)
            return result
        except Exception as exc:
            if self._terminate_for_controller_error(exc):
                exc = FlightTerminated(self.termination_reason or "run terminated")
            result = self._failure(exc, started=started)
            action.update(result)
            return result
        finally:
            self._append_action(action)

    def _run_task(self, task: ControlTask) -> None:
        stdout_chunks: list[str] = []
        task_controller: KRPCController | None = None

        def task_print(*values: Any, sep: str = " ", end: str = "\n") -> None:
            stdout_chunks.append(sep.join(str(value) for value in values) + end)
            with self._task_lock:
                task.stdout = _truncate_tail("".join(stdout_chunks))

        def should_stop() -> bool:
            return task.stop_requested

        def task_sleep(seconds: float) -> None:
            if task_controller is None:
                raise FlightToolError("background task controller is not initialized")
            self._sleep(float(seconds), controller=task_controller, should_stop=should_stop)

        try:
            task_controller = self._task_controller_factory()
            scope = self._execution_scope(
                controller=task_controller,
                extra={
                    "sleep": task_sleep,
                    "wait": task_sleep,
                    "should_stop": should_stop,
                    "__builtins__": {**_safe_builtins(), "print": task_print},
                },
            )
            self._exec_with_trace_timeout(task.code, scope, task.timeout_s, task=task)
            self._read_telemetry_or_terminate(task_controller)
            with self._task_lock:
                task.status = "done"
                task.result = _jsonable(scope.get("result"))
        except Exception as exc:
            if self._terminate_for_controller_error(exc):
                exc = FlightTerminated(self.termination_reason or "run terminated")
            with self._task_lock:
                task.status = "stopped" if isinstance(exc, TaskStopped) else "failed"
                task.error_type = type(exc).__name__
                task.error = str(exc)
            if not isinstance(exc, TaskStopped):
                self.invalid_actions += 1
        finally:
            if task_controller is not None:
                task_controller.close()
            with self._task_lock:
                task.stdout = _truncate_tail("".join(stdout_chunks))
                task.finished_monotonic = time.monotonic()
                self.artifacts.append_event(
                    {
                        "type": "control_task_finished",
                        "task_id": task.task_id,
                        "status": task.status,
                        "error_type": task.error_type,
                        "error": task.error,
                    }
                )

    def _sleep(
        self,
        seconds: float,
        *,
        controller: KRPCController,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        if seconds < 0:
            raise ValueError("wait seconds must be non-negative")
        if seconds > self.max_wait_s:
            raise ValueError(f"wait seconds exceeds max_wait_s={self.max_wait_s}")
        start_met = self._latest_mission_elapsed_s()
        target_met = start_met + seconds
        deadline = time.monotonic() + seconds
        self._maybe_time_warp_to(target_met, controller=controller)
        last_met = start_met
        while True:
            if should_stop and should_stop():
                raise TaskStopped("control task stopped")
            current_met = self._latest_mission_elapsed_s()
            remaining_met = target_met - current_met
            if remaining_met <= 0:
                return
            if current_met <= last_met and time.monotonic() >= deadline:
                return
            last_met = current_met
            remaining_wall = max(0.0, deadline - time.monotonic())
            time.sleep(min(self.poll_interval_s, remaining_met, remaining_wall))
            self._read_telemetry_or_terminate(controller)
            self._raise_if_terminated()

    def _in_atmosphere(self, controller: KRPCController) -> bool:
        sample = self.telemetry[-1] if self.telemetry else self._read_telemetry_or_terminate(
            controller
        )
        try:
            atmosphere_depth = float(controller.vessel.orbit.body.atmosphere_depth)
        except Exception:
            atmosphere_depth = 0.0
        return atmosphere_depth > 0.0 and sample.altitude_m < atmosphere_depth

    def _terminal_reason(self, sample: TelemetrySample) -> str | None:
        if not sample.intact:
            return "vessel_not_intact"
        if not sample.controllable:
            return "vessel_not_controllable"
        if sample.situation.lower() in {"crashed", "destroyed", "dead"}:
            return f"vessel_{sample.situation.lower()}"
        if self._landed_after_wasting_propellant(sample):
            return "vessel_landed_burning_fuel"
        return None

    def _landed_after_wasting_propellant(self, sample: TelemetrySample) -> bool:
        if sample.situation.lower() != "landed" or sample.mission_elapsed_s < 10.0:
            return False
        if sample.surface_altitude_m > 100.0 or sample.surface_speed_m_s > 1.0:
            return False
        initial_propellant = self._initial_propellant
        if initial_propellant is None:
            return False
        propellant_spent = initial_propellant - _sample_propellant(sample)
        if propellant_spent < 100.0:
            return False
        try:
            throttle = float(self.controller.vessel.control.throttle)
        except Exception:
            throttle = 0.0
        return throttle > 0.1

    def _unrecoverable_reason(
        self,
        sample: TelemetrySample,
        controller: KRPCController,
    ) -> str | None:
        if sample.mission_elapsed_s < 5.0:
            return None
        if sample.situation.lower() == "pre_launch":
            return None
        if sample.periapsis_m >= self.scenario.target_orbit.stable_periapsis_min_m:
            return None
        if _sample_propellant(sample) > 0.1:
            return None
        try:
            vehicle = controller.read_vehicle_state()
        except Exception:
            return None
        if float(vehicle.get("available_thrust", 0.0) or 0.0) > 0.1:
            return None
        engines = vehicle.get("engines") or []
        decouplers = vehicle.get("decouplers") or []
        next_stage = vehicle.get("next_stage")
        if engines or decouplers:
            return None
        if next_stage and (
            next_stage.get("engine_count")
            or next_stage.get("decoupler_count")
            or any(
                float(value or 0.0) > 0.1
                for value in (next_stage.get("resources") or {}).values()
            )
        ):
            return None
        return "mission_unrecoverable_no_propulsion"

    def _maybe_time_warp_to(self, target_met: float, *, controller: KRPCController) -> None:
        if self._in_atmosphere(controller) or not self.telemetry:
            return
        current_met = self._latest_mission_elapsed_s()
        remaining_met = target_met - current_met
        if remaining_met < max(10.0, self.poll_interval_s * 4.0):
            return
        space_center = controller.conn.space_center
        warp_to = getattr(space_center, "warp_to", None)
        if not callable(warp_to):
            return
        try:
            current_ut = float(space_center.ut)
        except Exception:
            return
        undershoot_s = min(5.0, max(2.0, remaining_met * 0.1))
        warp_duration_s = max(0.0, remaining_met - undershoot_s)
        if warp_duration_s <= 0.0:
            return
        warp_to(
            current_ut + warp_duration_s,
            max_rails_rate=1000,
            max_physics_rate=4,
        )
        self._read_telemetry_or_terminate(controller)

    def _read_telemetry_or_terminate(self, controller: KRPCController) -> TelemetrySample:
        try:
            sample = controller.read_telemetry()
        except Exception as exc:
            if self._can_recover_controller_error(exc):
                try:
                    controller = self._recover_controller(controller, exc)
                    sample = controller.read_telemetry()
                except Exception as retry_exc:
                    if self._terminate_for_controller_error(retry_exc):
                        self._raise_if_terminated()
                    raise retry_exc from exc
            else:
                if self._terminate_for_controller_error(exc):
                    self._raise_if_terminated()
                raise
        self.record_telemetry(sample)
        reason = self._unrecoverable_reason(sample, controller)
        if reason:
            self._terminate(reason, mission_elapsed_s=sample.mission_elapsed_s)
        return sample

    def _can_recover_controller_error(self, exc: Exception) -> bool:
        return self._controller_reconnect_factory is not None and "Instance not found" in str(exc)

    def _recover_controller(
        self,
        controller: KRPCController,
        exc: Exception,
    ) -> KRPCController:
        if self._controller_reconnect_factory is None:
            raise exc
        recovered = self._controller_reconnect_factory(controller)
        if controller is self.controller:
            self.controller = recovered
        self._emit_event(
            {
                "type": "krpc_controller_recovered",
                "mission_elapsed_s": self._latest_mission_elapsed_s(),
                "error_type": type(exc).__name__,
                "detail": _truncate(str(exc)),
            }
        )
        return recovered

    def _terminate_for_controller_error(self, exc: Exception) -> bool:
        message = str(exc)
        if "Instance not found" not in message:
            return False
        self._terminate(
            "vessel_lost",
            detail=message,
            error_type=type(exc).__name__,
        )
        return True

    def _terminate(
        self,
        reason: str,
        *,
        mission_elapsed_s: float | None = None,
        detail: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if self.terminated:
            return
        self.terminated = True
        self.termination_reason = reason
        event: dict[str, Any] = {
            "type": "run_terminated",
            "reason": reason,
            "mission_elapsed_s": (
                self._latest_mission_elapsed_s()
                if mission_elapsed_s is None
                else mission_elapsed_s
            ),
        }
        if error_type is not None:
            event["error_type"] = error_type
        if detail is not None:
            event["detail"] = _truncate(detail)
        self._emit_event(event)

    def _orbit_has_diverged(self, sample: TelemetrySample) -> bool:
        if self._orbit_diverged:
            return False
        diverged = (
            sample.apoapsis_m > self.scenario.target_orbit.altitude_m * 5
            and sample.periapsis_m < self.scenario.target_orbit.stable_periapsis_min_m
        )
        self._orbit_diverged = diverged
        return diverged

    def _raise_if_terminated(self) -> None:
        if self.terminated:
            raise FlightTerminated(self.termination_reason or "run terminated")

    def _raise_if_task_running(self, tool_name: str) -> None:
        with self._task_lock:
            running = [task for task in self._tasks.values() if task.status == "running"]
            running_elsewhere = [
                task for task in running if task.thread is not threading.current_thread()
            ]
            if not running_elsewhere:
                return
            task_ids = ", ".join(task.task_id for task in running_elsewhere)
        raise FlightToolError(
            f"tasks are running ({task_ids}); use ksp_check_task or ksp_stop_task before "
            f"calling {tool_name}"
        )

    def _execution_scope(
        self,
        *,
        controller: KRPCController,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def observe() -> dict[str, Any]:
            return self._python_observe(controller)

        def scoped_orbit_state() -> dict[str, Any]:
            telemetry = observe()["telemetry"]
            return {
                key: telemetry[key]
                for key in (
                    "mission_elapsed_s",
                    "altitude_m",
                    "apoapsis_m",
                    "periapsis_m",
                    "time_to_apoapsis_s",
                    "time_to_periapsis_s",
                    "eccentricity",
                    "inclination_deg",
                    "orbital_speed_m_s",
                    "liquid_fuel",
                    "oxidizer",
                    "stage",
                    "situation",
                    "controllable",
                    "intact",
                )
            }

        def scoped_throttle(value: float) -> dict[str, Any]:
            controller.vessel.control.throttle = max(0.0, min(1.0, float(value)))
            return {
                "ok": True,
                "telemetry": self._read_telemetry_or_terminate(controller).to_dict(),
            }

        def scoped_stage() -> dict[str, Any]:
            parts = controller.vessel.control.activate_next_stage()
            return {
                "ok": True,
                "activated_parts": len(parts) if parts is not None else None,
                "telemetry": self._read_telemetry_or_terminate(controller).to_dict(),
            }

        def scoped_attitude(
            mode: str,
            *,
            pitch: float | None = None,
            heading: float | None = None,
            reference_frame: str = "orbital",
        ) -> dict[str, Any]:
            mode = mode.replace("-", "_")
            if mode == "pitch_heading":
                if pitch is None or heading is None:
                    raise ValueError("pitch and heading are required for pitch_heading mode")
                vessel = controller.vessel
                _enable_sas_if_needed(vessel)
                autopilot = vessel.auto_pilot
                autopilot.engage()
                autopilot.target_pitch_and_heading(float(pitch), float(heading))
                return {
                    "ok": True,
                    "mode": mode,
                    "pitch": float(pitch),
                    "heading": float(heading),
                    "telemetry": self._read_telemetry_or_terminate(controller).to_dict(),
                }

            vessel = controller.vessel
            _enable_sas_if_needed(vessel)
            frame = _reference_frame(vessel, reference_frame)
            flight = vessel.flight(frame)
            direction = _flight_direction(flight, mode)
            autopilot = vessel.auto_pilot
            autopilot.reference_frame = frame
            autopilot.target_direction = direction
            autopilot.engage()
            return {
                "ok": True,
                "mode": mode,
                "reference_frame": reference_frame,
                "target_direction": direction,
                "telemetry": self._read_telemetry_or_terminate(controller).to_dict(),
            }

        scope = {
            "__builtins__": _safe_builtins(),
            "math": math,
            "time": time,
            "conn": controller.conn,
            "space_center": controller.conn.space_center,
            "vessel": controller.vessel,
            "observe": observe,
            "getTelemetry": lambda: observe()["telemetry"],
            "getVehicleState": lambda: observe()["vehicle"],
            "getOrbitState": scoped_orbit_state,
            "ksp_observe": observe,
            "ksp_throttle": scoped_throttle,
            "ksp_stage": scoped_stage,
            "ksp_attitude": scoped_attitude,
            "ksp_wait": lambda seconds: self._sleep(float(seconds), controller=controller),
            "sleep": lambda seconds: self._sleep(float(seconds), controller=controller),
            "wait": lambda seconds: self._sleep(float(seconds), controller=controller),
        }
        if extra:
            scope.update(extra)
        return scope

    def _python_observe(self, controller: KRPCController) -> dict[str, Any]:
        sample = self._read_telemetry_or_terminate(controller)
        self._raise_if_terminated()
        vehicle = controller.read_vehicle_state()
        telemetry = sample.to_dict()
        return {
            **telemetry,
            "telemetry": telemetry,
            "vehicle": vehicle,
            "target_orbit": {
                "altitude_m": self.scenario.target_orbit.altitude_m,
                "stable_periapsis_min_m": self.scenario.target_orbit.stable_periapsis_min_m,
            },
            "terminated": self.terminated,
            "termination_reason": self.termination_reason,
        }

    def _validate_code(self, code: str) -> None:
        if not code.strip():
            raise FlightToolError("python code must not be empty")
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise FlightToolError(str(exc)) from exc
        banned_calls = {"breakpoint", "compile", "eval", "exec", "input", "open", "__import__"}
        banned_krpc_methods = {
            "launch_vessel",
            "launch_vessel_from_sph",
            "launch_vessel_from_vab",
            "load",
            "quickload",
            "quicksave",
            "recover_vessel",
            "revert_to_launch",
            "revert_to_editor",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import | ast.ImportFrom) and not _is_allowed_import(node):
                raise FlightToolError("imports are not allowed, except import math and import time")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise FlightToolError("dunder names are not allowed")
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise FlightToolError("dunder attributes are not allowed")
            if isinstance(node, ast.Attribute) and node.attr in banned_krpc_methods:
                raise FlightToolError(f"{node.attr} is not available during flight")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in banned_calls
            ):
                raise FlightToolError(f"{node.func.id} is not allowed")

    def _exec_with_timeout(self, code: str, scope: dict[str, Any], timeout_s: float) -> None:
        if threading.current_thread() is not threading.main_thread():
            self._exec_with_trace_timeout(
                code,
                scope,
                timeout_s,
                task=ControlTask("sync", code, timeout_s, time.monotonic()),
            )
            return

        previous_handler = signal.getsignal(signal.SIGALRM)

        def handle_timeout(_signum: int, _frame: Any) -> None:
            raise self._sync_python_timeout(timeout_s)

        signal.signal(signal.SIGALRM, handle_timeout)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            exec(compile(code, "<ksp-python>", "exec"), scope, scope)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def _exec_with_trace_timeout(
        self,
        code: str,
        scope: dict[str, Any],
        timeout_s: float,
        *,
        task: ControlTask,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        previous_trace = sys.gettrace()

        def trace_timeout(_frame: Any, _event: str, _arg: Any) -> Any:
            if task.stop_requested:
                raise TaskStopped("control task stopped")
            if time.monotonic() > deadline:
                raise PythonExecutionTimeout(f"python execution exceeded {timeout_s:.3f}s")
            return trace_timeout

        sys.settrace(trace_timeout)
        try:
            exec(compile(code, "<ksp-task>", "exec"), scope, scope)
        finally:
            sys.settrace(previous_trace)

    def _timeout(self, requested: float | None, *, default: float) -> float:
        value = default if requested is None else float(requested)
        if value <= 0:
            raise ValueError("timeout_s must be positive")
        return min(value, self.max_wait_s)

    def _sync_python_timeout(self, timeout_s: float) -> PythonExecutionTimeout:
        return PythonExecutionTimeout(
            f"ksp_execute_python exceeded its {timeout_s:.3f}s synchronous response budget. "
            "This tool is only for short snippets that return quickly. For ascent, "
            "circularization, waits, or control loops, use ksp_start_task instead, then "
            "poll ksp_check_task for telemetry/status and use ksp_stop_task if you need to "
            "change strategy."
        )

    def _failure(
        self,
        exc: Exception,
        *,
        started: float,
        stdout: str = "",
    ) -> dict[str, Any]:
        self.invalid_actions += 1
        return {
            "ok": False,
            "duration_s": round(time.monotonic() - started, 3),
            "stdout": _truncate(stdout),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }

    def _append_action(self, action: dict[str, Any]) -> None:
        action.setdefault("index", len(self.actions))
        action.setdefault("allowed", action.get("ok") is not False)
        self.actions.append(action)
        self.artifacts.append_action(action)
        self._emit_event(
            {
                "type": "tool_call",
                "tool": action.get("type"),
                "ok": action.get("ok", True),
                "mission_elapsed_s": self._latest_mission_elapsed_s(),
            }
        )

    def _record_action(self, action_type: str, **payload: Any) -> None:
        self._append_action({"type": action_type, **payload})

    def _task_status(self, task: ControlTask | None) -> dict[str, Any] | None:
        if task is None:
            return None
        now = time.monotonic()
        finished = task.finished_monotonic
        elapsed_s = (finished if finished is not None else now) - task.started_monotonic
        return {
            "task_id": task.task_id,
            "status": task.status,
            "running": task.status == "running",
            "stop_requested": task.stop_requested,
            "elapsed_s": round(elapsed_s, 3),
            "timeout_s": task.timeout_s,
            "stdout": task.stdout,
            "result": _jsonable(task.result),
            "error_type": task.error_type,
            "error": task.error,
        }

    def _latest_mission_elapsed_s(self) -> float:
        return self.telemetry[-1].mission_elapsed_s if self.telemetry else 0.0

    def _emit_event(self, event: dict[str, Any]) -> None:
        self.artifacts.append_event(event)
        if self.live_events and event.get("type") == "run_terminated":
            print(
                f"[bench] run terminated: {event.get('reason')}",
                file=sys.stderr,
                flush=True,
            )


LiveKRPCTools = FlightSession


def _reference_frame(vessel: Any, name: str) -> Any:
    body = vessel.orbit.body
    if name == "surface":
        return body.reference_frame
    if name == "orbital":
        return body.non_rotating_reference_frame
    if name == "vessel_surface":
        return vessel.surface_reference_frame
    raise ValueError("reference_frame must be one of: surface, orbital, vessel_surface")


def _flight_direction(flight: Any, mode: str) -> Any:
    directions = {
        "prograde": "prograde",
        "retrograde": "retrograde",
        "normal": "normal",
        "anti_normal": "anti_normal",
        "radial": "radial",
        "anti_radial": "anti_radial",
    }
    attr = directions.get(mode)
    if attr is None:
        raise ValueError(
            "mode must be one of: pitch_heading, prograde, retrograde, normal, "
            "anti_normal, radial, anti_radial"
        )
    return getattr(flight, attr)


def _current_task_status(statuses: list[dict[str, Any]]) -> dict[str, Any] | None:
    running = [status for status in statuses if status.get("running")]
    if running:
        return running[-1]
    return statuses[-1] if statuses else None


def _latest_task(tasks: dict[str, ControlTask]) -> ControlTask | None:
    return next(reversed(tasks.values())) if tasks else None


def _sample_propellant(sample: TelemetrySample) -> float:
    return sample.liquid_fuel + sample.oxidizer + sample.solid_fuel


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
        return all(
            alias.name in {"math", "time"} and alias.asname in (None, alias.name)
            for alias in node.names
        )
    return node.module in {"math", "time"} and node.level == 0


def _safe_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if name == "math" and level == 0:
        return math
    if name == "time" and level == 0:
        return time
    raise ImportError("only import math and time are allowed")


def _truncate(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 15] + "...<truncated>"


def _truncate_tail(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return "<truncated>..." + value[-(limit - 15) :]


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return repr(value)

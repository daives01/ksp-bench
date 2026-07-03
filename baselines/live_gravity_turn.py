"""Closed-loop Kerbal X baseline using the live kRPC tool interface."""

from __future__ import annotations


def run(tools) -> None:
    tools.getTelemetry()
    tools.getVehicleState()

    tools.executeKRPC(
        """
def hold_pitch(pitch, heading=90.0):
    vessel.auto_pilot.target_pitch_and_heading(float(pitch), float(heading))
    vessel.auto_pilot.target_roll = 0.0
    vessel.auto_pilot.engage()

def stage_dead_engines():
    for engine in vessel.parts.engines:
        if engine.active and not engine.has_fuel:
            vessel.control.activate_next_stage()
            return True
    return False

vessel.control.sas = True
vessel.control.throttle = 1.0
hold_pitch(90.0)
vessel.control.activate_next_stage()
""",
        timeout_s=5.0,
    )

    tools.executeKRPC(
        """
sleep(8.0)
hold_pitch(80.0)
""",
        timeout_s=12.0,
    )

    tools.executeKRPC(
        """
wait_until(
    lambda: (stage_dead_engines() and False) or vessel.orbit.apoapsis_altitude >= 20000.0,
    timeout_s=60.0,
)
hold_pitch(65.0)
""",
        timeout_s=70.0,
    )

    tools.getTelemetry()
    tools.getVehicleState()

    tools.executeKRPC(
        """
wait_until(
    lambda: (stage_dead_engines() and False) or vessel.orbit.apoapsis_altitude >= 50000.0,
    timeout_s=80.0,
)
hold_pitch(35.0)
""",
        timeout_s=90.0,
    )

    tools.executeKRPC(
        """
wait_until(
    lambda: (stage_dead_engines() and False) or vessel.orbit.apoapsis_altitude >= 80000.0,
    timeout_s=80.0,
)
vessel.control.throttle = 0.0
hold_pitch(0.0)
""",
        timeout_s=90.0,
    )

    tools.getTelemetry()
    tools.getVehicleState()

    tools.executeKRPC(
        """
wait_until(lambda: vessel.orbit.time_to_apoapsis <= 35.0, timeout_s=180.0)
stage_dead_engines()
vessel.control.throttle = 1.0
hold_pitch(0.0)
wait_until(
    lambda: vessel.orbit.periapsis_altitude >= 70000.0
    or vessel.orbit.apoapsis_altitude >= 120000.0,
    timeout_s=90.0,
)
vessel.control.throttle = 0.0
result = {
    "apoapsis_m": vessel.orbit.apoapsis_altitude,
    "periapsis_m": vessel.orbit.periapsis_altitude,
}
""",
        timeout_s=200.0,
    )

    tools.getTelemetry()
    tools.getVehicleState()

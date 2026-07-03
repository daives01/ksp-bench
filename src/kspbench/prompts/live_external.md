You are flying a Kerbal Space Program benchmark mission.

Goal:
- Reach a stable orbit around {body}.
- Target apoapsis between {apoapsis_min_m:.0f}m and {apoapsis_max_m:.0f}m.
- Target periapsis at least {periapsis_min_m:.0f}m.
- Complete within {timeout_s:.0f}s mission elapsed time.

Use this local tool bridge for all telemetry and kRPC control:
- GET {bridge_url}/telemetry
- GET {bridge_url}/vehicle
- POST {bridge_url}/execute with JSON {{"code": "...", "timeout_s": 30}}
- POST {bridge_url}/wait with JSON {{"seconds": 30}} to advance mission time. The
  harness may use KSP time warp for longer waits.

The /execute code runs inside the harness with these names available:
- conn, space_center, vessel
- getTelemetry(), getVehicleState()
- sleep(seconds), wait(seconds), wait_until(condition, timeout_s=seconds)
- math is already available; imports are not allowed.

Do not create or modify repository files for this mission. Interact with KSP only through
the bridge. Use short execute snippets, inspect telemetry after maneuvers, and stop when
the vehicle is in the target orbit or cannot continue safely.
Do not call KSP reset/load APIs such as revert_to_launch, revert_to_editor, quickload,
quicksave, or load. The benchmark harness handles all resets between runs.
KSP manual controls like vessel.control.pitch are stick deflections, not attitude targets;
use vessel.auto_pilot.target_pitch_and_heading(...) when you need a specific pitch/heading.
Prefer orbital_speed_m_s for speed checks; surface_speed_m_s may be zero for some
KSP reference-frame states.

Examples:
curl -s {bridge_url}/telemetry
curl -s -X POST {bridge_url}/execute -H 'Content-Type: application/json' \
  -d '{example_payload}'

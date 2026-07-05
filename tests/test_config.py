from __future__ import annotations

from pathlib import Path

from bench.config import load_scenario


def test_loads_example_scenario() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    assert scenario.instance_id == "kerbin_orbit_80km_fixed_rocket_v0"
    assert scenario.vessel_name == "Kerbal 1"
    assert scenario.target_orbit.altitude_m == 80000
    assert scenario.target_orbit.stable_periapsis_min_m == 70000
    assert scenario.timeout_s == 600

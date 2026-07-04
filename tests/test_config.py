from __future__ import annotations

from pathlib import Path

from bench.config import load_scenario


def test_loads_example_scenario() -> None:
    scenario = load_scenario(Path("scenarios/kerbin_orbit_80km.toml"))

    assert scenario.instance_id == "kerbin_orbit_80km_fixed_rocket_v0"
    assert scenario.target_orbit.apoapsis_min_m == 75000
    assert scenario.timeout_s == 600

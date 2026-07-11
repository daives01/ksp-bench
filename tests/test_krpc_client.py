from __future__ import annotations

import math
from types import SimpleNamespace

from bench.krpc_client import _estimate_remaining_delta_v, _krpc_client_name


def test_krpc_client_name_uses_model_without_provider(monkeypatch) -> None:
    monkeypatch.delenv("KSPBENCH_MODEL", raising=False)

    assert _krpc_client_name("openai/gpt-5.4") == "gpt-5.4"


def test_krpc_client_name_reads_model_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("KSPBENCH_MODEL", "opencode/deepseek-v4-flash-free")

    assert _krpc_client_name() == "deepseek-v4-flash-free"


def test_krpc_client_name_falls_back_outside_model_run(monkeypatch) -> None:
    monkeypatch.delenv("KSPBENCH_MODEL", raising=False)

    assert _krpc_client_name() == "KSP Bench"


class FakeResources:
    def __init__(self, amounts: dict[str, float]) -> None:
        self.amounts = amounts

    def amount(self, name: str) -> float:
        return self.amounts.get(name, 0.0)


def test_estimates_final_stage_delta_v_from_burnable_propellant() -> None:
    engine = SimpleNamespace(active=True, has_fuel=True, vacuum_specific_impulse=320.0)
    vessel = SimpleNamespace(
        mass=4_000.0,
        resources=FakeResources({"LiquidFuel": 100.0, "Oxidizer": 100.0}),
        parts=SimpleNamespace(engines=[engine]),
    )

    expected = 9.80665 * 320.0 * math.log(4_000.0 / 3_000.0)
    assert _estimate_remaining_delta_v(vessel) == expected


def test_delta_v_does_not_treat_monopropellant_as_engine_propellant() -> None:
    engine = SimpleNamespace(active=True, has_fuel=True, vacuum_specific_impulse=320.0)
    vessel = SimpleNamespace(
        mass=4_000.0,
        resources=FakeResources({"MonoPropellant": 500.0}),
        parts=SimpleNamespace(engines=[engine]),
    )

    assert _estimate_remaining_delta_v(vessel) == 0.0


def test_delta_v_is_unknown_while_multiple_fueled_stages_remain() -> None:
    engines = [
        SimpleNamespace(active=False, has_fuel=True, vacuum_specific_impulse=320.0),
        SimpleNamespace(active=False, has_fuel=True, vacuum_specific_impulse=345.0),
    ]
    vessel = SimpleNamespace(
        mass=10_000.0,
        resources=FakeResources({"LiquidFuel": 500.0, "Oxidizer": 500.0}),
        parts=SimpleNamespace(engines=engines),
    )

    assert _estimate_remaining_delta_v(vessel) is None

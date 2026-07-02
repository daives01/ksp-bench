"""Simple scripted gravity-turn baseline for harness validation."""

from __future__ import annotations


def run(context) -> None:
    context.set_sas(True)
    context.set_throttle(1.0)
    context.stage()
    context.wait(10.0)
    context.set_attitude(pitch=80.0, heading=90.0, roll=0.0)
    context.wait(45.0)
    context.set_attitude(pitch=55.0, heading=90.0, roll=0.0)
    context.wait(80.0)
    context.set_attitude(pitch=20.0, heading=90.0, roll=0.0)
    context.wait(90.0)
    context.set_attitude(pitch=0.0, heading=90.0, roll=0.0)
    context.stage()

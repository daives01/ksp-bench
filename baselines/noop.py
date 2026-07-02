"""Negative-control baseline that takes no flight actions."""

from __future__ import annotations


def run(context) -> None:
    context.wait(1.0)

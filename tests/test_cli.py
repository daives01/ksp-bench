from __future__ import annotations

import pytest

from kspbench.cli import build_parser


def test_only_opencode_execution_command_is_registered() -> None:
    parser = build_parser()

    assert parser.parse_args(["run", "scenario.toml"]).scenario == "scenario.toml"
    with pytest.raises(SystemExit):
        parser.parse_args(["live", "scenario.toml"])
    with pytest.raises(SystemExit):
        parser.parse_args(["live-external", "scenario.toml"])

from __future__ import annotations

import json
from pathlib import Path

from bench.backfill_costs import backfill_costs


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_backfill_updates_source_index_and_public_detail(tmp_path: Path) -> None:
    usage = {
        "model": "deepseek-v4-flash",
        "input_tokens": 1_000_000,
        "cached_input_tokens": 2_000_000,
        "cache_write_tokens": 0,
        "output_tokens": 100_000,
        "reasoning_tokens": 20_000,
        "cost_usd": None,
    }
    run_path = tmp_path / "runs/model/low/run-1/agent_process.json"
    index_path = tmp_path / "public/index.json"
    detail_path = tmp_path / "public/runs/run-1.json"
    _write(run_path, {"usage": dict(usage)})
    _write(index_path, {"runs": [{"runId": "run-1", "usage": dict(usage)}]})
    _write(detail_path, {"usage": dict(usage)})

    assert backfill_costs(
        runs_dir=tmp_path / "runs", public_data_dir=tmp_path / "public"
    ) == (1, 2)

    for path, selector in (
        (run_path, lambda value: value["usage"]),
        (index_path, lambda value: value["runs"][0]["usage"]),
        (detail_path, lambda value: value["usage"]),
    ):
        updated = selector(json.loads(path.read_text(encoding="utf-8")))
        assert updated["cost_usd"] == 0.1476
        assert updated["cost_kind"] == "api_equivalent"


def test_backfill_leaves_unknown_models_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "runs/model/run/agent_process.json"
    _write(path, {"usage": {"model": "unknown", "cost_usd": None}})

    assert backfill_costs(
        runs_dir=tmp_path / "runs", public_data_dir=tmp_path / "public"
    ) == (0, 0)
    assert json.loads(path.read_text(encoding="utf-8"))["usage"]["cost_usd"] is None

"""Recalculate API-equivalent costs in stored and published run artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bench.usage import _api_equivalent_pricing


def backfill_costs(*, runs_dir: Path, public_data_dir: Path) -> tuple[int, int]:
    run_updates = sum(
        _update_agent_process(path) for path in runs_dir.glob("**/agent_process.json")
    )
    public_updates = 0

    index_path = public_data_dir / "index.json"
    if index_path.is_file():
        document = _read_json(index_path)
        changed = sum(
            _update_usage(run.get("usage"))
            for run in document.get("runs", [])
            if isinstance(run, dict)
        )
        if changed:
            _write_json(index_path, document)
            public_updates += changed

    for path in (public_data_dir / "runs").glob("*.json"):
        document = _read_json(path)
        if _update_usage(document.get("usage")):
            _write_json(path, document)
            public_updates += 1

    return run_updates, public_updates


def _update_agent_process(path: Path) -> int:
    document = _read_json(path)
    if not _update_usage(document.get("usage")):
        return 0
    _write_json(path, document)
    return 1


def _update_usage(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    model = value.get("model")
    if not isinstance(model, str):
        return 0
    pricing = _api_equivalent_pricing(
        model=model,
        input_tokens=int(value.get("input_tokens") or 0),
        cached_input_tokens=int(value.get("cached_input_tokens") or 0),
        cache_write_tokens=int(value.get("cache_write_tokens") or 0),
        output_tokens=int(value.get("output_tokens") or 0)
        + int(value.get("reasoning_tokens") or 0),
    )
    if pricing is None:
        return 0
    updated = {
        "cost_usd": pricing[0],
        "cost_kind": "api_equivalent",
        "pricing_model": model,
        "pricing_source": pricing[1],
    }
    if all(value.get(key) == item for key, item in updated.items()):
        return 0
    value.update(updated)
    return 1


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument(
        "--public-data-dir", type=Path, default=Path("web/public/data")
    )
    args = parser.parse_args(argv)
    run_updates, public_updates = backfill_costs(
        runs_dir=args.runs_dir, public_data_dir=args.public_data_dir
    )
    print(f"Updated {run_updates} run artifacts and {public_updates} public records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

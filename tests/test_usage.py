from __future__ import annotations

import json
import sqlite3

from bench.usage import collect_opencode_session_usage


def test_collect_opencode_session_usage_records_tokens_and_api_equivalent_cost(tmp_path) -> None:
    database = tmp_path / "opencode.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE session (
              id TEXT, title TEXT, model TEXT, tokens_input INTEGER, tokens_output INTEGER,
              tokens_reasoning INTEGER, tokens_cache_read INTEGER, tokens_cache_write INTEGER,
              time_updated INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ses_bench",
                "kspbench:run-1",
                json.dumps({"providerID": "openai", "id": "gpt-5.4"}),
                1_000_000,
                100_000,
                20_000,
                2_000_000,
                50_000,
                1,
            ),
        )

    usage = collect_opencode_session_usage("kspbench:run-1", data_dir=tmp_path)

    assert usage == {
        "source": "opencode_session",
        "session_id": "ses_bench",
        "provider": "openai",
        "model": "gpt-5.4",
        "input_tokens": 1_000_000,
        "cached_input_tokens": 2_000_000,
        "cache_write_tokens": 50_000,
        "output_tokens": 100_000,
        "reasoning_tokens": 20_000,
        "total_tokens": 3_170_000,
        "cost_usd": 4.925,
        "cost_kind": "api_equivalent",
        "pricing_model": "gpt-5.4",
        "pricing_source": "OpenAI standard API",
    }


def test_collect_opencode_session_usage_keeps_tokens_for_unknown_pricing(tmp_path) -> None:
    database = tmp_path / "opencode.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE session (
              id TEXT, title TEXT, model TEXT, tokens_input INTEGER, tokens_output INTEGER,
              tokens_reasoning INTEGER, tokens_cache_read INTEGER, tokens_cache_write INTEGER,
              time_updated INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ses_unknown",
                "kspbench:run-2",
                json.dumps({"providerID": "opencode", "id": "free"}),
                5,
                4,
                3,
                2,
                1,
                1,
            ),
        )

    usage = collect_opencode_session_usage("kspbench:run-2", data_dir=tmp_path)

    assert usage is not None
    assert usage["total_tokens"] == 15
    assert usage["cost_usd"] is None
    assert usage["cost_kind"] is None


def test_collect_opencode_session_usage_prices_supported_free_opencode_model(tmp_path) -> None:
    database = tmp_path / "opencode.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE session (
              id TEXT, title TEXT, model TEXT, tokens_input INTEGER, tokens_output INTEGER,
              tokens_reasoning INTEGER, tokens_cache_read INTEGER, tokens_cache_write INTEGER,
              time_updated INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ses_deepseek",
                "kspbench:run-3",
                json.dumps({"providerID": "opencode", "id": "deepseek-v4-flash-free"}),
                1_000_000,
                100_000,
                20_000,
                2_000_000,
                0,
                1,
            ),
        )

    usage = collect_opencode_session_usage("kspbench:run-3", data_dir=tmp_path)

    assert usage is not None
    assert usage["cost_usd"] == 0.1476
    assert usage["pricing_source"] == "OpenRouter list price: deepseek/deepseek-v4-flash"

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any  # noqa: I001

# Comparable API prices per 1M text tokens: input, cached input, cache write,
# output, and the reference pricing label. OpenCode records a zero cost for
# subscription and free-model usage, so these are intentionally never treated
# as invoices. Reasoning tokens are billed at the output rate. Keep this table
# current when a provider changes its public API pricing.
API_EQUIVALENT_RATES: dict[str, tuple[float, float, float, float, str]] = {
    "gpt-5.6": (5.00, 0.50, 6.25, 30.00, "OpenAI standard API"),
    "gpt-5.6-sol": (5.00, 0.50, 6.25, 30.00, "OpenAI standard API"),
    "gpt-5.6-terra": (2.50, 0.25, 3.125, 15.00, "OpenAI standard API"),
    "gpt-5.6-luna": (1.00, 0.10, 1.25, 6.00, "OpenAI standard API"),
    "gpt-5.5": (5.00, 0.50, 5.00, 30.00, "OpenAI standard API"),
    "gpt-5.4": (2.50, 0.25, 2.50, 15.00, "OpenAI standard API"),
    "gpt-5.4-mini": (0.75, 0.075, 0.75, 4.50, "OpenAI standard API"),
    "gpt-5.4-nano": (0.20, 0.02, 0.20, 1.25, "OpenAI standard API"),
    "gpt-5": (1.25, 0.125, 1.25, 10.00, "OpenAI standard API"),
    # These free OpenCode aliases are mapped to the equivalent paid OpenRouter
    # model, not priced as $0. They make like-for-like model comparisons useful.
    "deepseek-v4-flash": (
        0.09,
        0.018,
        0.09,
        0.18,
        "OpenRouter list price: deepseek/deepseek-v4-flash",
    ),
    "deepseek-v4-flash-free": (
        0.09,
        0.018,
        0.09,
        0.18,
        "OpenRouter list price: deepseek/deepseek-v4-flash",
    ),
    "deepseek-v4-pro": (
        0.435,
        0.087,
        0.435,
        0.87,
        "OpenRouter list price: deepseek/deepseek-v4-pro",
    ),
    "glm-5.2": (0.42, 0.084, 0.42, 1.32, "OpenRouter list price: z-ai/glm-5.2"),
    "kimi-k2.6": (
        0.68,
        0.34,
        0.68,
        3.41,
        "OpenRouter list price: moonshotai/kimi-k2.6",
    ),
    "kimi-k2.7-code": (
        0.74,
        0.15,
        0.74,
        3.50,
        "OpenRouter price: moonshotai/kimi-k2.7-code",
    ),
    "mimo-v2.5": (
        0.105,
        0.028,
        0.105,
        0.28,
        "OpenRouter list price: xiaomi/mimo-v2.5",
    ),
    "minimax-m2.7": (
        0.25,
        0.05,
        0.25,
        1.00,
        "OpenRouter list price: minimax/minimax-m2.7",
    ),
    "minimax-m3": (
        0.30,
        0.06,
        0.30,
        1.20,
        "OpenRouter price: minimax/minimax-m3",
    ),
    "mimo-v2.5-free": (
        0.105,
        0.028,
        0.105,
        0.28,
        "OpenRouter list price: xiaomi/mimo-v2.5",
    ),
    "nemotron-3-ultra-free": (
        0.50,
        0.10,
        0.50,
        2.20,
        "OpenRouter list price: nvidia/nemotron-3-ultra-550b-a55b",
    ),
    "qwen3.6-plus": (
        0.325,
        0.065,
        0.40625,
        1.95,
        "OpenRouter price: qwen/qwen3.6-plus",
    ),
    "qwen3.7-plus": (
        0.32,
        0.064,
        0.40,
        1.28,
        "OpenRouter price: qwen/qwen3.7-plus",
    ),
    "qwen3.7-max": (
        1.25,
        0.25,
        1.5625,
        3.75,
        "OpenRouter price: qwen/qwen3.7-max",
    ),
}


def collect_opencode_session_usage(
    session_title: str,
    *,
    data_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Read a completed OpenCode session's exact local token counters.

    OpenCode intentionally records a zero cost for subscription-backed runs.
    This returns a separate API-equivalent estimate when the model has a known
    standard API rate; it never treats that estimate as the user's invoice.
    """

    root = _opencode_data_dir(data_dir)
    database = root / "opencode.db"
    if not database.is_file():
        return None

    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute(
                """
                SELECT id, model, tokens_input, tokens_output, tokens_reasoning,
                       tokens_cache_read, tokens_cache_write
                FROM session
                WHERE title = ?
                ORDER BY time_updated DESC
                LIMIT 1
                """,
                (session_title,),
            ).fetchone()
    except sqlite3.Error:
        return None

    if row is None:
        return None

    (
        session_id,
        raw_model,
        input_tokens,
        output_tokens,
        reasoning_tokens,
        cache_read,
        cache_write,
    ) = row
    provider, model = _parse_model(raw_model)
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    reasoning_tokens = int(reasoning_tokens or 0)
    cached_input_tokens = int(cache_read or 0)
    cache_write_tokens = int(cache_write or 0)

    total_tokens = (
        input_tokens
        + output_tokens
        + reasoning_tokens
        + cached_input_tokens
        + cache_write_tokens
    )
    pricing = _api_equivalent_pricing(
        model=model,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens + reasoning_tokens,
    )

    return {
        "source": "opencode_session",
        "session_id": session_id,
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_tokens": cache_write_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "cost_usd": pricing[0] if pricing is not None else None,
        "cost_kind": "api_equivalent" if pricing is not None else None,
        "pricing_model": model if pricing is not None else None,
        "pricing_source": pricing[1] if pricing is not None else None,
    }


def _opencode_data_dir(data_dir: str | Path | None) -> Path:
    if data_dir is not None:
        return Path(data_dir).expanduser()
    configured = os.environ.get("OPENCODE_DATA_DIR")
    if configured:
        # OpenCode accepts multiple roots, but a benchmark invocation has one
        # fresh session and the first configured root is the normal location.
        return Path(configured.split(",", 1)[0]).expanduser()
    return Path.home() / ".local" / "share" / "opencode"


def _parse_model(raw_model: Any) -> tuple[str | None, str | None]:
    if not isinstance(raw_model, str):
        return None, None
    try:
        value = json.loads(raw_model)
    except json.JSONDecodeError:
        return None, raw_model
    if not isinstance(value, dict):
        return None, None
    provider = value.get("providerID")
    model = value.get("id")
    return (
        provider if isinstance(provider, str) else None,
        model if isinstance(model, str) else None,
    )


def _api_equivalent_pricing(
    *,
    model: str | None,
    input_tokens: int,
    cached_input_tokens: int,
    cache_write_tokens: int,
    output_tokens: int,
) -> tuple[float, str] | None:
    if model is None:
        return None
    rate = API_EQUIVALENT_RATES.get(model)
    if rate is None:
        return None
    (
        input_rate,
        cached_input_rate,
        cache_write_rate,
        output_rate,
        pricing_source,
    ) = rate
    return (
        input_tokens * input_rate
        + cached_input_tokens * cached_input_rate
        + cache_write_tokens * cache_write_rate
        + output_tokens * output_rate
    ) / 1_000_000, pricing_source

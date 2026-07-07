# KSP-bench Setup

## Requirements

- Kerbal Space Program 1 with the kRPC mod installed and running.
- Python 3.12 via `uv`.
- Bun for the local MCP server.
- OpenCode installed and authenticated.
- A clean benchmark save with the fixed vessel on the launchpad.

## Install

```bash
uv sync
```

Install kRPC in KSP through CKAN or your usual mod workflow. Keep the benchmark
install minimal: kRPC plus its dependencies, no flight-assist or physics-changing mods.

## Configure kRPC

The kRPC host and ports live in the OpenCode MCP config, not in scenario files:

```json
{
  "mcp": {
    "ksp": {
      "environment": {
        "KSP_RPC_HOST": "100.126.59.95",
        "KSP_RPC_PORT": "50000",
        "KSP_STREAM_PORT": "50001"
      }
    }
  }
}
```

Edit [opencode.json](/Users/ives/Documents/ksp-bench/opencode.json) if your KSP
server uses a different host or port. Each Python kRPC subprocess reads those same env vars.

## Prepare References

Populate the read-only kRPC source tree used by the OpenCode agent:

```bash
uv run kspbench prepare-agent --krpc-repo /private/tmp/kspbench-krpc
```

If `--krpc-repo` is omitted, the command uses the installed Python `krpc` package
and any checkout found via `KSPBENCH_KRPC_REPO`, `/private/tmp/kspbench-krpc`, or
`/tmp/kspbench-krpc`.

## Run

Check local setup:

```bash
uv run kspbench doctor
```

Run a scored benchmark:

```bash
uv run kspbench run scenarios/kerbin_orbit_80km.toml --model openai/gpt-5.4
```

Use the OpenCode agent interactively:

```bash
uv run kspbench agent scenarios/kerbin_orbit_80km.toml --model openai/gpt-5.4
```

Or start OpenCode yourself from the repo root and select the `ksp` agent:

```bash
opencode . --agent ksp
```

That direct path starts `mcp/server.ts` through Bun using [opencode.json](/Users/ives/Documents/ksp-bench/opencode.json).
If `KSPBENCH_RUN_DIR` is not set, the MCP server creates a run directory under
`runs/`.

The MCP server runs each foreground KSP tool in a fresh Python process with its
own kRPC connection. `KSPBENCH_MCP_TOOL_TIMEOUT` controls the default hard
timeout for those one-shot calls; duration-based tools such as `wait` add
`KSPBENCH_MCP_TOOL_TIMEOUT_PADDING`. Each `start_task` call runs in its own
supervised Python process; `KSPBENCH_TASK_TIMEOUT_PADDING`,
`KSPBENCH_TASK_STOP_GRACE`, and `KSPBENCH_TASK_STATUS_INTERVAL` tune task
supervision.

## Artifacts

Runs write:

- `action_log.jsonl`
- `telemetry.jsonl`
- `telemetry.csv`
- `telemetry_waypoints.json`
- `agent_process.json`
- `score.json`
- `summary.txt`

## Troubleshooting

- If connection fails, confirm KSP is running, kRPC is started in game, and
  `KSP_RPC_HOST` / `KSP_RPC_PORT` / `KSP_STREAM_PORT` match your server.
- If OpenCode cannot see KSP tools, run `bun run mcp/server.ts` and send an MCP
  `tools/list` request, or run `opencode agent list` from the repo root.
- If the direct agent uses the wrong Python, set `KSPBENCH_PYTHON` to the desired
  interpreter, for example `.venv/bin/python`.

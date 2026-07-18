# KSP-bench

KSP-bench is a small benchmark harness for testing whether agents can fly a fixed Kerbal Space Program 1 mission through kRPC. The v0 task is a fixed-rocket launch from Kerbin into low orbit: fly the Kerbal 1 to an 80 km orbit, keep periapsis above 70 km for a stable orbit, and keep the vessel intact and controllable.

The repo is intentionally split into a few durable parts:

- `mcp/`: a reusable Bun/TypeScript MCP server that exposes the KSP flight tools.
- `.opencode/agents/ksp.md`: the reusable OpenCode KSP agent definition.
- `bench/`: scenario loading, scoring, telemetry, Python kRPC subprocesses, artifacts,
  and the benchmark runner.
- `scenarios/`: benchmark scenario definitions.
- `env/ckan/`: reproducible KSP mod environment metadata.
- `tests/`: fast unit tests that do not require KSP.

Generated run artifacts are written under `runs/` and should not be committed.

## Setup

Prerequisites:

- Python 3.12 managed with `uv`.
- Bun.
- Kerbal Space Program 1.
- CKAN with the kRPC mod installed.
- A dedicated KSP save with the benchmark vessel on the launchpad.

Install the Python environment:

```bash
uv sync
```

Check the local harness and kRPC connectivity:

```bash
uv run kspbench doctor
```

More detailed KSP and CKAN setup notes are in `setup.md`.

Configure the kRPC endpoint in [opencode.json](/Users/ives/Documents/ksp-bench/opencode.json):

```json
"environment": {
  "KSP_RPC_HOST": "100.126.59.95",
  "KSP_RPC_PORT": "50000",
  "KSP_STREAM_PORT": "50001"
}
```

Prepare the OpenCode agent's read-only kRPC reference tree:

```bash
uv run kspbench prepare-agent --krpc-repo /private/tmp/kspbench-krpc
```

If `--krpc-repo` is omitted, the command uses the installed Python `krpc` package and any
checkout found at `KSPBENCH_KRPC_REPO`, `/private/tmp/kspbench-krpc`, or `/tmp/kspbench-krpc`.

## Running

Run the fast test suite:

```bash
uv run pytest
uv run ruff check
```

Run OpenCode against KSP through the reusable `ksp` OpenCode agent and local MCP server:

```bash
uv run kspbench run scenarios/kerbin_orbit_80km.toml \
  --model openai/gpt-5.4
```

Each `run` records the OpenCode session's input, cached-input, output, and reasoning
token counts in `agent_process.json`. For supported model IDs it also records a
`cost_usd` API-equivalent estimate using standard API rates, independent of the wrapper or
provider used to run the model. Supported free model aliases use a comparable paid OpenRouter
list price instead. This is a comparison metric, not the amount billed to a ChatGPT or OpenCode
subscription.

Reapply the current pricing catalog to existing run artifacts and published data with:

```bash
uv run python -m bench.backfill_costs
```

Each score records both `wall_clock_elapsed_s` (the elapsed benchmark-process time used for
time comparisons) and `mission_elapsed_s` (KSP MET used for flight replay). KSP MET can be
accelerated by time warp, so it is not used to rank run duration.

Benchmark agents have no wall-clock deadline by default. Runs stop when the agent exits or the
flight harness detects an unrecoverable vessel state. Use `--agent-timeout` only when an explicit
process deadline is desired. Foreground calls and waits retain short safety caps. Background tasks
default to `--task-timeout`, while an explicit `start_task` timeout is honored so a single task can
cover a full ascent, coast, and circularization.

Raw telemetry is recorded independently of agent tool calls every five wall-clock seconds by
default (`--telemetry-interval`). The compact public flight trace keeps regular mission-time
waypoints plus event-aligned samples for throttle, staging, attitude, task, and tool-error markers.

Queue multiple OpenCode models, reverting KSP to the unpaused launchpad state before
and after each attempt:

```bash
uv run kspbench batch scenarios/kerbin_orbit_80km.toml \
  --model openai/gpt-5.4 \
  --model opencode/deepseek-v4-flash-free
```

The live harness exposes a deliberately small tool surface to the agent:

- Structured flight tools for observing the benchmark vessel, throttle, staging, attitude hold, and wait.
- A direct Python escape hatch for kRPC calls that the structured tools do not cover.
- Multiple background Python control tasks for longer closed-loop burns or guards, each with a task id.

To use the agent interactively instead of as a benchmark run:

```bash
uv run kspbench agent scenarios/kerbin_orbit_80km.toml --model openai/gpt-5.4
```

To use the OpenCode agent directly, start OpenCode from the repo root:

```bash
opencode . --agent ksp
```

OpenCode starts the local MCP server with Bun via `opencode.json`:
`bun run mcp/server.ts`.

This keeps the benchmark centered on the simple question: can the model fly the vessel to orbit,
while the harness records enough telemetry, actions, and artifacts to compare runs.

## Benchmark versions

The active benchmark version lives in the scenario file and is included in every score and
public dataset. The website only compares runs whose version matches the dataset's active version.

- Patch releases (`0.1.x`) are for changes that cannot materially affect performance or scoring,
  such as copy, metadata, logging, website changes, and harmless harness corrections.
- Minor releases (`0.x.0`) are required whenever scenario conditions, the vessel, agent
  instructions, available tools, time limits, scoring, game/mod configuration, or harness behavior
  could affect results. Start a fresh leaderboard and rerun the model field for that release.
- Use `1.0.0` when the methodology is ready to be declared mature; it is not required for ordinary
  stable benchmark operation.

The deciding question is: would runs from before and after the change be fair on the same
leaderboard? If not, bump the minor version. Keep prior public datasets under
`web/public/data/archive/` rather than mixing them into the active leaderboard.

Score or summarize existing run artifacts:

```bash
uv run kspbench score runs/<run_id>
uv run kspbench summarize runs
```

## Git Hygiene

Commit source, tests, scenarios, the CKAN environment file, `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, and this README.

Do not commit local environments, caches, logs, screenshots, recordings, KSP save/craft exports, `.env` files, or generated `runs/` artifacts. If a run result becomes important for analysis, copy only the curated summary into a separate tracked report.

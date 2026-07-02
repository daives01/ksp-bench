# KSP-bench Plan

KSP-bench is an embodied-agent benchmark for evaluating whether language models can control a Kerbal Space Program mission through a structured API. The first version should isolate flight competence before adding vehicle design.

## Scope

The benchmark will start with KSP 1, CKAN-managed mods, and kRPC as the control bridge. Agents will interact with a fixed rocket through a constrained Python SDK and receive telemetry from the running game.

Version 0 intentionally avoids VAB/SPH vehicle construction. kRPC is strongest for inspecting and controlling existing vessels in flight, while craft creation through the editor is not a first-class kRPC capability. Vehicle design will be added later as a separate track.

## Technical Choices

Use a small Python project with modern, reproducible tooling:

- `uv` for Python version management, dependency locking, environment sync, and command execution.
- `pyproject.toml` as the single source of Python package metadata and tool configuration.
- `uv.lock` committed to the repo.
- `.python-version` committed to pin the local interpreter line.
- Ruff for linting and formatting.
- pytest for fast unit tests.
- YAML or TOML scenario files with explicit schema validation.
- JSONL for event/action logs and CSV or Parquet for telemetry.

The benchmark should avoid requiring KSP for every test. Unit tests should cover scoring, config parsing, artifact writing, and agent API validation with fake telemetry. KSP-backed runs should be treated as integration tests.

## Evaluation Harness Lessons

Established LLM benchmark projects suggest several patterns KSP-bench should adopt early.

OpenAI Evals separates eval definitions, model/completion functions, and result recording. It supports custom eval logic, model-graded evals, prompt-chain or tool-using systems through a completion-function protocol, and optional external result logging. KSP-bench should mirror the separation: scenarios define tasks, agents/adapters define how a model acts, and recorders persist the trace.

EleutherAI's LM Evaluation Harness emphasizes config-based task creation, reproducible public prompts, custom metrics, answer extraction/post-processing, multiple generations per document, cached/resumable evaluation, sample logging, and optional visualization/export. KSP-bench should use config-defined scenarios, log every action and telemetry sample, support multiple attempts per scenario, and keep enough raw data for post-hoc analysis.

HELM uses a run/summarize/server workflow and reports multiple metrics rather than a single accuracy number. KSP-bench should provide separate commands for running missions, summarizing result suites, and eventually viewing runs in a local dashboard. The benchmark should report success, mission quality, efficiency, robustness, and cost separately.

SWE-bench uses reproducible execution environments, named run IDs, prediction files, worker parallelism, build/run logs, and final evaluation result directories. KSP-bench cannot containerize KSP as cleanly as SWE-bench containerizes code tasks, but it should still use named run IDs, explicit environment manifests, isolated run directories, and deterministic reset procedures.

Recent agent-harness benchmark work highlights that model results depend heavily on the harness itself: tool API, context policy, retries, budgets, tracing, and recovery behavior. KSP-bench should report results at the model-plus-harness configuration level, not as a bare model score.

Practical implications for v0:

- Treat each mission as an `instance` with a stable ID, scenario config, fixed craft/save, and scoring config.
- Treat each evaluated system as a `run_config` containing model, prompt, adapter, tool API version, retry policy, timeout, and budget.
- Save raw traces first; compute summaries from traces so scoring changes can be audited.
- Support `run`, `score`, and `summarize` as separate CLI operations.
- Support `--run-id`, `--limit`, `--resume`, and `--max-workers` eventually, even if v0 starts single-worker.
- Record model API usage and estimated cost where available.
- Include both aggregate metrics and per-instance outcomes.
- Keep a small validation suite for fast harness checks before expensive KSP runs.

## v0 Goal

Evaluate whether an agent can fly a fixed stock rocket from the Kerbal Space Center launchpad into a stable low Kerbin orbit.

Initial success target:

- Apoapsis between 75 km and 85 km.
- Periapsis above 70 km.
- Vessel remains intact and controllable.
- Mission completes within a fixed timeout.

## Agent Interface

The agent should control flight through a limited API rather than raw keyboard and mouse input.

Likely exposed controls:

- Read telemetry.
- Set throttle.
- Set pitch, heading, and roll targets.
- Toggle SAS/RCS where available.
- Activate next stage.
- Wait for simulation time.
- Create, inspect, and execute maneuver nodes only if included in the scenario track.

Likely telemetry:

- Mission elapsed time.
- Altitude and surface altitude.
- Apoapsis and periapsis.
- Surface and orbital speed.
- Vertical speed.
- Pitch, heading, and roll.
- Current stage.
- Remaining liquid fuel, oxidizer, and solid fuel.
- Dynamic pressure if available.
- Vessel situation and body.

## Tracks

Planned benchmark tracks:

- `fixed-flight`: fixed craft, evaluate flight control only.
- `parameterized-design`: agent chooses from constrained craft template parameters.
- `craft-dsl`: agent emits a validated structured craft specification.
- `repair`: agent receives failure logs and can revise attempts.

v0 should implement only `fixed-flight`.

## Scoring

Use milestone and dense scoring so partial progress is measurable.

Example v0 score components:

- Launch and clear tower.
- Reach 10 km altitude.
- Reach space above 70 km.
- Establish periapsis above 70 km.
- Final apoapsis and periapsis close to target band.
- Preserve vessel control.
- Preserve useful remaining fuel.
- Avoid invalid tool calls, excessive staging, or timeout.

The score output should be machine-readable and include a short failure reason.

For v0, report at least three layers of metrics:

- `success`: strict binary mission success for leaderboard-style comparison.
- `score`: dense 0-100 mission score based on milestones and final orbit quality.
- `diagnostics`: non-ranking metrics such as fuel remaining, elapsed mission time, action count, invalid action count, crash state, and closest achieved apoapsis/periapsis.

The leaderboard metric should be conservative and stable. Diagnostic metrics can evolve faster while the benchmark is being tuned.

Recommended v0 result schema:

```json
{
  "run_id": "2026-07-01T120000Z_gpt-example_gravity-turn",
  "instance_id": "kerbin_orbit_80km_fixed_rocket_v0",
  "benchmark_version": "0.0.1",
  "harness_version": "0.0.1",
  "agent": {
    "name": "gravity_turn",
    "model": null,
    "adapter": "local_python"
  },
  "success": false,
  "score": 62.5,
  "milestones": {
    "cleared_tower": true,
    "reached_10km": true,
    "reached_space": true,
    "periapsis_above_70km": false
  },
  "diagnostics": {
    "max_altitude_m": 91000,
    "final_apoapsis_m": 82000,
    "final_periapsis_m": -120000,
    "mission_elapsed_s": 430,
    "invalid_actions": 0
  },
  "failure_reason": "periapsis_below_target"
}
```

Aggregate reports should include:

- Pass rate.
- Mean and median dense score.
- Milestone completion rates.
- Distribution of failure reasons.
- Mean runtime, action count, token usage, and estimated cost.
- Per-model and per-harness comparisons.
- Confidence intervals or bootstrap intervals once enough runs exist.

## Reproducibility

Each run should capture enough data to debug and compare agents:

- Scenario config.
- Prompt or agent input.
- Agent code or action log.
- Telemetry log.
- Event log.
- Final score JSON.
- Optional screenshots or video.

Run artifacts should be append-only and analysis-friendly:

```text
runs/<suite_id>/<run_id>/
  manifest.json
  scenario.yaml
  run_config.yaml
  prompt.txt
  agent_output/
  action_log.jsonl
  telemetry.csv
  events.jsonl
  score.json
  summary.txt
```

Suite-level summaries should be separate from run artifacts:

```text
results/<suite_id>/
  aggregate.json
  instances.csv
  failures.csv
  metrics.parquet
```

The environment should pin:

- KSP version.
- CKAN mod list.
- kRPC version.
- Python dependency versions.
- Scenario save file.
- Fixed rocket craft file.
- Benchmark timeout and scoring rules.

Each run should also record:

- Git commit if available.
- `uv.lock` hash.
- Python version.
- OS and architecture.
- kRPC connection details.
- Active vessel name and loaded scenario.

## Harness Architecture

The harness should keep five roles separate:

- `scenario`: static task definition, scoring parameters, fixed craft/save references, timeout, and allowed controls.
- `agent_adapter`: turns a model, local script, or future external agent into calls against the KSP-bench SDK.
- `controller`: executes validated control actions against kRPC.
- `recorder`: writes prompts, actions, telemetry, events, model usage, and environment metadata.
- `scorer`: reads final state and trace artifacts, then emits score files.

This separation makes it possible to compare model behavior without changing scoring, change scoring without rerunning KSP where traces are sufficient, and add future agent types without rewriting the mission runner.

v0 should start with local Python baseline agents and a simple adapter. LLM-generated code should come later, after trace logging and scoring are stable.

## Future Vehicle Creation

After v0, vehicle design can be introduced in stages:

1. Parameterized templates, such as booster count, tank count, upper-stage engine, fins, and payload mass.
2. A constrained craft-spec DSL converted by the harness into `.craft` files.
3. Optional custom KSP mod support if direct editor construction becomes necessary.

The benchmark should keep design and flight as separate capabilities so failures are interpretable.

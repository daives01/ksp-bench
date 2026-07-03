# KSP-bench v0 Tasks

This file tracks the immediate implementation work for the first fixed-rocket flight benchmark.

## Phase 1: Repository Skeleton

- [x] Create project layout.
- [x] Use `uv` as the Python project manager.
- [x] Add `pyproject.toml`.
- [x] Pin Python with `.python-version`.
- [x] Commit `uv.lock` after dependencies are selected.
- [x] Add basic CLI entry point.
- [x] Add Ruff lint/format configuration.
- [x] Add pytest test layout.
- [x] Add `.gitignore` for Python, logs, KSP saves, recordings, and local config.
- [x] Add example scenario config for Kerbin orbit.
- [x] Add `env/ckan/` for the reproducible CKAN modlist.

## Phase 2: KSP Environment

- [ ] Install KSP 1 locally.
- [ ] Install CKAN.
- [ ] Create a stock-as-possible CKAN mod profile.
- [ ] Install kRPC and required dependencies through CKAN.
- [ ] Export or record the CKAN mod identifiers and versions.
- [ ] Confirm the kRPC server starts inside KSP.
- [ ] Create or select a fixed stock rocket for v0.
- [ ] Save a clean launchpad scenario for repeatable runs.

## Phase 3: Harness Prototype

- [x] Connect to kRPC from Python.
- [x] Read active vessel telemetry.
- [x] Implement action wrappers for throttle, attitude, SAS, staging, and wait.
- [x] Keep the action API deliberately lower level than a full autopilot.
- [x] Implement telemetry logging to JSONL or CSV.
- [ ] Implement run timeout handling.
- [x] Implement clean run artifact directory creation.
- [x] Record benchmark, Python, kRPC, CKAN, and scenario versions in each run.

## Phase 4: Scenario and Scoring

- [x] Define `kerbin_orbit_80km` scenario config.
- [x] Implement orbit success checks.
- [x] Implement milestone scoring.
- [x] Emit `score.json`.
- [x] Emit a human-readable run summary.
- [x] Add failure reasons for crash, timeout, no connection, invalid vessel, and missed orbit.

## Phase 5: Baselines

- [x] Add a minimal scripted launch baseline.
- [x] Add a gravity-turn baseline.
- [x] Add a no-op or random-control negative baseline.
- [ ] Run baselines against the fixed rocket.
- [ ] Use baseline results to tune timeout and scoring bands.

## Phase 6: Agent Interface

- [x] Define the constrained SDK exposed to agents.
- [x] Start with Python agents loaded from trusted local files.
- [x] Add a live closed-loop Python agent interface with telemetry, vehicle-state, and bounded kRPC execution tools.
- [ ] Add generated-code execution only after the local harness is stable.
- [ ] Decide later whether agents submit Python code, JSON action plans, or both.
- [ ] Add sandbox boundaries for generated code.
- [ ] Create a reference prompt for the fixed-flight task.
- [ ] Save all agent inputs and outputs in run artifacts.

## Phase 8: Project Quality

- [x] Add `uv run ruff check`.
- [x] Add `uv run ruff format --check`.
- [x] Add `uv run pytest`.
- [x] Add a `kspbench doctor` command for local environment checks.
- [x] Add a small fake-kRPC test double so scoring and logging can be tested without launching KSP.
- [x] Keep KSP integration tests separate from fast unit tests.

## Phase 7: Documentation and Validation

- [ ] Expand setup instructions after the first successful local run.
- [ ] Document expected KSP settings.
- [ ] Document how to start KSP and kRPC before running the harness.
- [ ] Document how to run baselines.
- [ ] Document known sources of nondeterminism.
- [ ] Add troubleshooting notes for CKAN, kRPC connection failures, and mod mismatch.

## Initial Definition of Done

v0 is usable when:

- A fresh KSP + CKAN + kRPC setup can load the fixed rocket.
- The Python harness can connect to kRPC and read telemetry.
- A baseline script can launch, stage, and attempt orbit.
- The run produces telemetry logs and `score.json`.
- The setup docs are accurate enough to reproduce the run on another machine.
- `uv sync`, lint, format check, and unit tests pass without requiring KSP.

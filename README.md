# KSP-bench

KSP-bench is a small benchmark harness for testing whether agents can fly a fixed Kerbal Space Program 1 mission through kRPC. The v0 task is a fixed-rocket launch from Kerbin into low orbit: reach an apoapsis between 75 km and 85 km, raise periapsis above 70 km, and keep the vessel intact and controllable.

The repo is intentionally split into a few durable parts:

- `src/kspbench/`: harness code, scoring, telemetry, live kRPC tools, and the OpenCode agent adapter.
- `scenarios/`: benchmark scenario definitions.
- `env/ckan/`: reproducible KSP mod environment metadata.
- `tests/`: fast unit tests that do not require KSP.

Generated run artifacts are written under `runs/` and should not be committed.

## Setup

Prerequisites:

- Python 3.12 managed with `uv`.
- Kerbal Space Program 1.
- CKAN with the kRPC mod installed.
- A dedicated KSP save with the benchmark vessel on the launchpad.

Install the Python environment:

```bash
uv sync
```

Check the local harness and optional kRPC connectivity:

```bash
uv run kspbench doctor
```

More detailed KSP and CKAN setup notes are in `setup.md`.

## Running

Run the fast test suite:

```bash
uv run pytest
uv run ruff check
```

Run OpenCode against KSP through locked-down custom tools:

```bash
uv run kspbench run scenarios/kerbin_orbit_80km.toml \
  --model openai/gpt-5.4
```

Score or summarize existing run artifacts:

```bash
uv run kspbench score runs/<run_id>
uv run kspbench summarize runs
```

## Git Hygiene

Commit source, tests, scenarios, the CKAN environment file, `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`, and this README.

Do not commit local environments, caches, logs, screenshots, recordings, KSP save/craft exports, `.env` files, or generated `runs/` artifacts. If a run result becomes important for analysis, copy only the curated summary into a separate tracked report.

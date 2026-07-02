# Technical Notes

These are the current implementation preferences for KSP-bench v0.

## Python Tooling

Use `uv` rather than a manual `venv` plus `pip` workflow. `uv` gives us one tool for Python installation, dependency locking, environment synchronization, and command execution.

Repo conventions:

- Commit `pyproject.toml`.
- Commit `uv.lock`.
- Commit `.python-version`.
- Run local commands through `uv run`.
- Use `uv sync` to recreate the project environment.
- Do not ask contributors to activate `.venv` manually.

Useful commands:

```bash
uv python install 3.12
uv python pin 3.12
uv sync
uv run kspbench doctor
uv run pytest
uv run ruff check
uv run ruff format --check
```

## Project Shape

Recommended initial layout:

```text
ksp-bench/
  pyproject.toml
  uv.lock
  .python-version
  src/kspbench/
    __init__.py
    cli.py
    config.py
    krpc_client.py
    telemetry.py
    scoring.py
    artifacts.py
  baselines/
    gravity_turn.py
    noop.py
  scenarios/
    kerbin_orbit_80km.yaml
  env/ckan/
    ksp-bench-v0.ckan
  tests/
```

## CLI

Start with a small CLI:

```bash
uv run kspbench doctor
uv run kspbench run scenarios/kerbin_orbit_80km.yaml --agent baselines/gravity_turn
uv run kspbench score runs/<run_id>
```

`doctor` should check Python dependencies, expected files, and kRPC reachability.

## Config

Use scenario config files for benchmark parameters:

- Body.
- Target orbit.
- Timeout.
- Required vessel name or craft ID.
- Allowed control API.
- Scoring weights.
- Artifact settings.

Validate configs at startup with a typed schema. Pydantic is a reasonable choice if we want stronger validation; dataclasses plus explicit checks are enough for v0.

## Logging and Artifacts

Use append-only logs:

- `action_log.jsonl` for agent actions and harness events.
- `telemetry.csv` for regular sampled telemetry.
- `score.json` for final machine-readable scoring.
- `summary.txt` for human inspection.

Every artifact directory should include version metadata so runs can be compared later.

## Testing Strategy

Keep most tests independent of KSP:

- Config parsing.
- Scoring.
- Artifact creation.
- Telemetry normalization.
- Agent API validation.

Use a fake kRPC client for unit tests. Treat real KSP runs as integration tests because they are slow, stateful, and require a graphical game process.

## CKAN and KSP Environment

Use CKAN to keep the KSP install reproducible. v0 should install only kRPC and its CKAN-selected dependencies on top of stock KSP.

Once the working mod set is confirmed, commit a CKAN modlist or metapackage under `env/ckan/`. That file should be part of the benchmark version, just like `uv.lock`.

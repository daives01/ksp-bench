# KSP-bench Setup

This document describes the intended setup for KSP-bench v0. The goal is a stock-as-possible Kerbal Space Program 1 install with only the mods needed for programmatic control through kRPC.

## Requirements

- Kerbal Space Program 1.
- CKAN mod manager.
- `uv` Python project manager.
- A local clone of this repository.

KSP-bench v0 targets KSP 1 because it has mature modding support and stable automation tooling.

## Install KSP

Install Kerbal Space Program 1 through Steam, GOG, or the direct Squad/Private Division installer.

Recommended:

- Use a dedicated KSP install for benchmarking.
- Disable unrelated mods.
- Avoid using a personal career or sandbox save for benchmark runs.
- Keep a backup of the clean benchmark save.

## Install CKAN

Install CKAN from the official CKAN project:

https://github.com/KSP-CKAN/CKAN

After installing CKAN:

1. Launch CKAN.
2. Point it at the dedicated KSP install.
3. Refresh the mod list.
4. Confirm CKAN recognizes the installed KSP version.

CKAN can be used through the GUI, console UI, or command line. For reproducible benchmark work, prefer keeping a committed CKAN modlist or metapackage in the repo once the exact kRPC dependency set is confirmed.

## Install Required Mods

Use CKAN to install:

- `kRPC`

CKAN should automatically select required dependencies. Keep the install otherwise stock unless KSP-bench later adds a specific required mod.

Avoid adding:

- MechJeb.
- Ferram Aerospace Research.
- Kerbal Engineer Redux.
- Part packs.
- Life-support mods.
- Visual or physics overhaul mods.

Those can be useful later for baselines or alternate tracks, but v0 should keep the environment minimal.

After installing mods, export or record the installed CKAN identifiers and versions. The repo should eventually include something like:

```text
env/ckan/ksp-bench-v0.ckan
```

That file becomes part of the benchmark definition, alongside the fixed craft, save, Python lockfile, and scoring config.

## Enable kRPC In Game

1. Start KSP.
2. Open the kRPC server window from the in-game toolbar.
3. Start the server.
4. Use the default local connection settings unless the harness config says otherwise.

The Python harness will connect to the running game over kRPC. KSP must be open with the benchmark vessel loaded before v0 runs.

## Create the v0 Save

Initial manual setup:

1. Start a new sandbox save named `KSP-bench-v0`.
2. Build or import the fixed v0 rocket.
3. Put the rocket on the launchpad.
4. Save the game in a known clean pre-launch state.

The first benchmark scenario will assume:

- Body: Kerbin.
- Launch site: KSC launchpad.
- Goal orbit: 75 km to 85 km apoapsis, periapsis above 70 km.
- Vessel: fixed stock rocket.
- Crew survival: required if crewed.

The exact craft file and save file should be added once the initial rocket is selected.

## Python Environment With uv

Use `uv` for Python version management, dependency locking, command execution, and reproducible local environments. Do not use a manually managed `venv` workflow.

Install `uv` from the official Astral docs:

https://docs.astral.sh/uv/

Expected setup:

```bash
cd ~/Documents/ksp-bench
uv python install 3.12
uv python pin 3.12
uv sync
```

Once implemented, the harness should expose commands similar to:

```bash
uv run kspbench doctor
uv run kspbench run scenarios/kerbin_orbit_80km.yaml --agent baselines/gravity_turn
```

`doctor` should verify that Python dependencies are installed and that kRPC is reachable.

The repo should commit:

- `pyproject.toml`
- `uv.lock`
- `.python-version`

The repo should not commit `.venv/`.

## Running v0

Expected run flow:

1. Start KSP.
2. Load the clean `KSP-bench-v0` save.
3. Place the fixed rocket on the launchpad.
4. Start the kRPC server.
5. Run the benchmark harness from this repo.
6. Inspect the generated run artifact directory.

Expected artifacts:

```text
runs/<run_id>/
  scenario.yaml
  action_log.jsonl
  telemetry.csv
  score.json
  summary.txt
```

## Running External CLI Agents

KSP-bench can also run live missions through terminal coding agents. The harness
starts a localhost tool bridge, then launches the selected CLI with instructions
for calling:

- `GET /telemetry`
- `GET /vehicle`
- `POST /execute`

The bridge is the only supported way for the external agent to read telemetry or
send kRPC snippets. The harness still records actions, telemetry, score, and an
`agent_process.json` file with the command, stdout, stderr, return code, and
timeout status.

Codex CLI:

```bash
uv run kspbench live-external scenarios/kerbin_orbit_80km.yaml \
  --adapter codex \
  --model gpt-5.4
```

Codex is invoked with `codex exec`, `--sandbox workspace-write`, and an ephemeral
session. This follows the current Codex noninteractive interface and leaves room
to add the Codex SDK later for richer event handling.

opencode CLI:

```bash
uv run kspbench live-external scenarios/kerbin_orbit_80km.yaml \
  --adapter opencode \
  --model openai/gpt-5.4
```

opencode is invoked with `opencode run --dir <repo>`. Pass additional CLI flags
with repeated `--agent-arg`, for example:

```bash
uv run kspbench live-external scenarios/kerbin_orbit_80km.yaml \
  --adapter opencode \
  --agent-arg=--format \
  --agent-arg json
```

Both CLIs must already be installed and authenticated before the run starts.

## Troubleshooting

If the harness cannot connect:

- Confirm KSP is running.
- Confirm the kRPC server is started in game.
- Confirm the host and port match the harness config.
- Confirm the Python kRPC package version is compatible with the installed kRPC mod.

If runs differ between attempts:

- Reload the same clean pre-launch save before each run.
- Confirm the vessel and staging are unchanged.
- Confirm no extra physics or part mods are installed.
- Keep the benchmark timeout and physics settings fixed.

If staging behaves unexpectedly:

- Inspect the rocket in the VAB.
- Confirm engines, boosters, decouplers, and parachutes are assigned to the intended stages.
- Save the corrected craft and update the benchmark fixture.

## Notes for Later Versions

Vehicle creation is intentionally out of scope for v0. Later versions can add:

- Parameterized craft templates.
- A constrained craft-spec DSL.
- Generated `.craft` files.
- Separate design-only and design-plus-flight tracks.

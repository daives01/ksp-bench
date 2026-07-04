# kRPC reference for the KSP OpenCode agent

This directory is prepared by `kspbench prepare-agent` and refreshed by `kspbench run`.
It exists so the OpenCode `ksp` agent can search literal kRPC source instead of relying on
hand-written API summaries.

Useful searches:

```bash
rg -n "target_pitch_and_heading|class AutoPilot|class Vessel" .
rg -n "resources_in_decouple_stage|current_stage|activate_next_stage" .
rg -n "reference_frame|prograde|apoapsis_altitude|periapsis_altitude" .
```

Expected generated folders:

- `installed_python_client/`: the installed `krpc` Python package, including generated service
  modules when the optional `krpc` dependency is installed.
- `upstream_python_client/`: `client/python/krpc` copied from the upstream kRPC repository.
- `upstream_spacecenter_service/`: `service/SpaceCenter/src/Services` copied from upstream kRPC.
- `upstream_docs/`: selected upstream API templates and tutorials.

The benchmark tools exposed to the agent come from the local MCP server in `mcp/server.ts`.

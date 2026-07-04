# kRPC reference for the KSP flight agent

This directory contains kRPC source and Python client reference material for flight control.
Search it before guessing unfamiliar kRPC names or object paths.

Useful searches:

```
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

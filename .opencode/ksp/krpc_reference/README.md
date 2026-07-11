# kRPC reference for the KSP flight agent

This directory contains kRPC source and Python client reference material for flight control.
Search it before guessing unfamiliar kRPC names or object paths.

Start with `FLIGHT_API.md` for a compact Python API index. Use the `ksp_krpc_api` tool for
targeted class/member lookup. The copied client source remains the authoritative fallback.

for example there are:

- `installed_python_client/`: the installed `krpc` Python package, including generated service
  modules when the optional `krpc` dependency is installed.
- `upstream_python_client/`: `client/python/krpc` copied from the upstream kRPC repository.
- `upstream_spacecenter_service/`: `service/SpaceCenter/src/Services` copied from upstream kRPC.
- `upstream_docs/`: selected upstream API templates and tutorials.

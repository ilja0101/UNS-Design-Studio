# AGENTS.md

This file provides guidance to agents when working with code in this repository.

- No test/lint harness exists yet; use `python -m py_compile app.py factory.py bridge.py`, `docker compose config`, and `docker compose -f portainer-stack.yml config` as current validation.
- Run locally with `python app.py`; the Flask process starts only the dashboard and manages `factory.py` / `bridge.py` as subprocesses through API calls/UI controls.
- Runtime JSON files are authoritative state, not fixtures: `uns_config.json`, `sim_state.json`, `bridge_config.json`, `server_config.json`, `payload_schemas.json`, `asset_library.json`.
- Docker runtime persists JSON by symlinking `/app/*.json` to `/data/*.json` in `entrypoint.sh`; do not move these config filenames without updating the entrypoint.
- Plant identity is `BusinessUnit|SiteName` with bare site names; OPC-UA site nodes are `Factory` + site name. Keep this split consistent across `app.py`, `factory.py`, and `bridge.py`.
- `opcPath` in tag config is relative to the nearest area ancestor, while `opcNodeName` only overrides the leaf OPC-UA variable name.
- Saving `/api/uns` rewrites `uns_config.json`, restarts `factory.py` if running, invalidates metric cache, syncs `sim_state.json`, then restarts the bridge after a delay.
- `factory.py` still applies canonical tag inheritance for empty workCenter/area/workUnit nodes; `bridge.py` intentionally publishes only explicitly configured tags.
- Bridge stats are parsed from stdout lines prefixed exactly `[BRIDGE_STATS]`; changing this breaks dashboard bridge status.
- Style is existing single-file script style: grouped multi-imports, broad `except Exception` for demo resilience, JSON `indent=2`, UTF-8 when user-facing/config data may contain non-ASCII.


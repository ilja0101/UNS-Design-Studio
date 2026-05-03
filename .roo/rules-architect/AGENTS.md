# Project Architecture Rules (Non-Obvious Only)

- `app.py` is both web server and supervisor: it owns Flask routes, background OPC polling, and subprocess lifecycle for `factory.py` and `bridge.py`.
- Shared state is file-based JSON rather than IPC/database; `factory.py` rereads `sim_state.json` each tick so UI recipe/running changes apply live.
- The UNS tree drives three different projections: OPC-UA address space, dashboard metric paths, and MQTT/NATS topics; schema changes must preserve all projections.
- Docker persistence depends on fixed root-level JSON filenames seeded/symlinked into `/data`; a modular refactor must retain this compatibility or migrate volumes.
- V2 direction is incremental hardening first: deployment foundation, atomic JSON persistence, modularization, tests, then frontend asset extraction.


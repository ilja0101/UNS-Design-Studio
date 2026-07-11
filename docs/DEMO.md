# Hub-spoke "aggregate a UNS live" demo

The `/app` dashboard is a radial hub-spoke of your Unified Namespace: the UNS at
the core, business units / sites / IT systems as spokes, expanding per ISA-95 as
you click. Nodes can be **added to the live UNS** on the spot — the moment you
add one, its simulated data starts publishing to the broker. This is the
edge-driven onboarding story: start with an empty bus and aggregate it live.

## Run it locally

```bash
# 1. Build the SPA (once, or use `npm run dev` for hot-reload against :5000)
cd ui && npm install && npm run build && cd ..

# 2. Run the app
python app.py            # or: First_start.BAT on Windows
```

Open <http://localhost:5000> → redirects to `/app`. For hot-reload UI dev:
`cd ui && npm run dev` (Vite on :5173, proxies `/api` to :5000).

## The stage script

1. **Start the OPC-UA server** (header → *Start Server*), and configure + start
   the **broker bridge** (Settings → Broker, or the legacy dashboard). Point an
   MQTT/NATS viewer at the broker (`mosquitto_sub -t '#' -v`, or MQTT Explorer).
2. On `/app`, click **Clear live UNS** in the toolbar. The bus goes silent —
   nothing publishes.
3. Click a **facility** node → the panel opens → **Add to live UNS (incl. N)**.
   Within one bridge poll its topics appear in your viewer, and the spoke's edge
   turns green and pulses. Click deeper to expand areas / work units.
4. Drop in a **new asset**: select an empty node → *Add asset from library* →
   pick e.g. a pump. The model is saved (`POST /api/uns`, factory + bridge
   hot-restart) and the new asset's tags begin publishing.
5. **All live** puts the whole UNS back on the bus.

## How it works (architecture)

- **Membership** lives in `sim_state.json` → `live_nodes` as inclusion
  *prefixes* over `"|"`-joined node paths (`sim_state_service.set_live`, carve
  logic in `uns_tree.carve_out`). The bridge filters each poll
  (`bridge.py poll()`); **no restart** for add/remove — only model edits (adding
  assets) hot-restart the factory.
- **Graph** comes from `GET /api/graph` (`graph_service.build_graph`), polled at
  2 s by the React app. Single-BU topologies collapse so the core *is* the BU.
- **Orthogonal axes:** membership (on the bus) vs. plant `running` (values
  moving, driven by the shift scheduler) vs. `simulator_running`. Shift hours
  only toggle `running`; they never change membership.

Everything is derived from `uns_config.json` — clear it and model a new UNS in
the **UNS Designer**, and the hub-spoke follows.

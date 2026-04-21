# UNS Design Studio — Full Documentation

> This document covers architecture, API reference, simulation profiles, configuration and requirements.
> For a quick overview and getting started guide see the **[README](README.md)**.

---

## Contents

- [Core Architecture](#core-architecture)
- [Feature Areas](#feature-areas)
- [Simulation Profiles](#simulation-profiles)
- [Asset Library](#asset-library)
- [Configuration Reference](#configuration-reference)
- [API Reference](#api-reference)
- [Data Flows](#data-flows)
- [Requirements](#requirements)
- [File Structure](#file-structure)
- [Release Notes](#release-notes)

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        app.py (Flask)                       │
│   Web dashboard · REST API · OPC-UA poll loop               │
│   sim_state.json ← authoritative running/recipe state       │
└──────────┬───────────────────────┬──────────────────────────┘
           │ subprocess             │ subprocess
           ▼                       ▼
┌──────────────────┐    ┌─────────────────────────┐
│   factory.py     │    │       bridge.py          │
│  OPC-UA Server   │◄───│  OPC-UA → MQTT/NATS      │
│  Simulation loop │    │  Topic publisher         │
└──────────────────┘    └─────────────────────────┘
           ▲
    reads sim_state.json
    (running/stopped per plant)
```

**Key design principle:** `sim_state.json` is the authoritative source of truth for plant running state and active recipe. `factory.py` and `bridge.py` read it on every tick. `app.py` writes to it on every control action. OPC-UA is a data transport, not a control mechanism.

---

## Feature Areas

### 1. UNS / Topic Tree Designer (`/uns`)

Visual tree editor for designing the enterprise namespace hierarchy.

**Capabilities:**
- Create and edit the full ISA-95 hierarchy: Enterprise → Business Unit → Site → Area → Work Center → Work Unit
- Add tags to any node with configurable properties: name, data type (Float/Int/Bool/String/DateTime), unit, access (R/RW), qualifier, payload schema, description
- Assign a **simulation profile** to each tag (see Simulation Profiles below)
- Configure **recipe parameters** per tag (optional, used by factory.py to vary process behaviour)
- Drag-and-drop nodes to reorder or restructure
- **Import/Export** the full UNS as a JSON file — templates can be shared and reused
- **Asset Library** — drop pre-configured asset templates (e.g. Pump, Conveyor, Freezer) onto any node. Assets are defined in `asset_library.json`
- Saving the UNS automatically restarts `factory.py` and `bridge.py` to apply the new structure live

**Requirements:**
- Site names are stored as-is; the OPC-UA server applies a `Factory` prefix to site node names internally
- Every node in the tree gets a stable UUID `id` for cross-reference
- Tag `opcNodeName` overrides the OPC node name when different from the display name
- Tags with `opcPath` are mapped to a specific OPC path relative to their area node
- The enterprise root name (tree → name) is used as the OPC-UA root object name

---

### 2. Dashboard (`/`)

Real-time monitoring and control dashboard for all simulated plants.

**Capabilities:**
- Shows one card per site (plant), grouped by Business Unit
- Each card displays:
  - Running status LED (green = running, grey = stopped, yellow = fault/maintenance)
  - Active recipe name
  - Live metrics: OEE (%), Power (kW), Good Output (accumulator), Inbound Tonnage (accumulator)
  - OEE progress bar with colour-coded health (green ≥80%, yellow ≥60%, red <60%)
- **Start All / Stop All** buttons — writes all plants' running state to `sim_state.json` instantly
- **Per-plant Control modal:**
  - Toggle individual plant running state
  - Select active recipe from the configured recipe list
- **Anomaly Injection modal:**
  - Shows all tags defined in the UNS for the selected plant
  - Searchable by tag name, filterable by work center
  - Set override values on any tag for a configurable duration (seconds), then auto-reset
- Dashboard auto-reloads when UNS structure changes (detected via structure hash)
- Live metric values are resolved dynamically from `uns_config.json` profiles — no hardcoded OPC paths

**Dashboard metric resolution:**
The dashboard shows four KPIs per plant (OEE, Power, Good Output, Inbound). These are resolved by scanning the UNS tree for the first tag with each matching simulation profile (`oee`, `power_kw`, `accumulator_good`, `inbound_tons`). If a profile is absent from the UNS, the metric shows `--`.

---

### 3. Simulation Engine (`factory.py`)

Stateful OPC-UA server with a realistic process simulation for all tags defined in the UNS.

**State machine:**

```
                    ┌──────────────────────────────────┐
                    ▼                                  │
  ┌─────────┐   fault    ┌───────┐   repaired   ┌──────────┐
  │ Running │───────────►│ Fault │─────────────►│ Recovery │
  └─────────┘            └───────┘              └──────────┘
       ▲                                              │
       └──────────────────── ready ───────────────────┘

  ┌─────────┐   start command
  │ Stopped │────────────────────────────────────────► Recovery
  └─────────┘
```

**When a fault fires:**
- Availability collapses; OEE follows (always `A × P × Q / 10000`)
- Flow rate and speed drop to zero
- Motor current spikes; vibration rises
- Power drops to ~12% (standby only)
- All accumulators pause

**Capabilities:**
- Builds the OPC-UA address space dynamically from `uns_config.json` on startup
- Every tag's value is driven by its assigned simulation profile (see below)
- Spontaneous fault events based on vibration level and remaining useful life
- Auto-recovery with configurable tick duration
- Recipe switching: when `sim_state.json` changes the active recipe, `PlantState` updates base parameters on the next tick
- Per-BU default parameters (base power, infeed rate, product price, OEE targets) configurable in `PlantState._GROUP_PARAMS`
- Reads `sim_state.json` on every tick — plant start/stop takes effect within ~1 second
- **Anomaly TCP server** (port 9999): accepts JSON override commands from `app.py` to force any tag to a specific value for testing

**Canonical tag inheritance:** If a work center or area node has no tags defined, it inherits tag definitions from the first node of the same name in the tree — used to avoid duplicating tag definitions across identical work centers.

---

### 4. Broker Bridge (`bridge.py`)

Publishes OPC-UA tag values to MQTT or NATS on a configurable interval.

**Capabilities:**
- Supports MQTT (via paho-mqtt) and NATS protocols
- Topic structure: `<prefix>/<BU>/<site>/<area>/<workCenter>/<workUnit>/<tagName>`
- MQTT topic sanitisation: spaces and reserved characters (`#`, `+`) replaced with underscores
- Publishes only **explicitly defined tags** from `uns_config.json` — canonically inherited tags are not published
- Gating: reads `sim_state.json` before each publish cycle; skips stopped plants
- Reconnect with exponential backoff (5s–60s) on broker disconnect
- Publishes bridge statistics as structured log lines read by `app.py`

---

### 5. Payload Schema Designer (`/payload-schemas`)

Named schema templates that define the JSON structure of published messages.

**Capabilities:**
- Create, edit, and delete named schemas (e.g. "standard", "alarm", "quality")
- Each schema maps source fields (value, timestamp, quality, unit, tag path, site name, data type) to output JSON keys
- Live JSON preview shows exactly what each message will look like
- Schemas are assignable per tag in the UNS designer (`payloadSchema` property)
- Stored in `payload_schemas.json`
- Built-in presets: Standard, Simple Value, Sparkplug B-like, ISA-95 Extended, OSIsoft PI-like, InfluxDB-like

---

### 6. Live UNS Viewer (`/live`)

Real-time view of all MQTT/NATS messages flowing from the bridge.

**Capabilities:**
- Connects to any external broker and subscribes to all topics under the configured prefix
- Displays live topic/value pairs in a filterable topic tree
- Connects independently of the bridge configuration — useful for pointing at a remote broker
- Useful for validating that published topics match the designed UNS structure

---

### 7. Server & Bridge Management (Dashboard sidebar)

**Factory Server:**
- Start / Stop the OPC-UA factory server process
- View live log output from `factory.py`
- OPC-UA connection status indicator

**Broker Bridge:**
- Start / Stop the bridge process
- Configure broker: protocol, host, port, username/password, topic prefix, publish interval
- Live bridge statistics: connection status, OPC-UA status, messages/sec, total published, errors

**Network Settings:**
- Configure OPC-UA bind address and port
- Configure OPC-UA client host (for remote factory servers)
- Configure anomaly TCP server port

---

## Simulation Profiles

| Group | Profiles |
|-------|---------|
| OT / Process | `oee`, `availability`, `performance`, `quality`, `temperature_process`, `temperature_ambient`, `pressure`, `flow_rate`, `level`, `motor_current`, `vibration`, `valve_position`, `speed_rpm`, `boolean_running`, `boolean_fault`, `boolean_alarm` |
| Accumulators | `accumulator_good`, `accumulator_bad`, `accumulator_energy`, `accumulator_generic`, `counter_faults` |
| Maintenance / CMMS | `mtbf`, `mttr`, `pm_compliance`, `remaining_useful_life`, `corrective_wo_count`, `maintenance_cost` |
| Quality / Lab | `quality_metric_pct`, `quality_metric_cont`, `quality_hold`, `batch_id`, `lot_id` |
| Logistics | `silo_level`, `inbound_tons`, `outbound_tons`, `truck_id`, `days_of_supply`, `order_quantity`, `order_status` |
| ERP / Finance | `erp_order_id`, `production_cost_eur`, `waste_cost_eur`, `revenue_eur`, `margin_pct` |
| Energy / Utilities | `power_kw`, `steam_flow`, `compressed_air`, `co2_kg` |
| Recipe | `recipe` — publishes the active recipe string |
| Other | `default` — generic Gaussian walk with configurable min/max/std |

All profiles are plant-state-aware. Values change coherently when a plant faults, recovers or stops.

---

## Asset Library

16 predefined asset bundles insertable from the UNS designer in one click. Each bundle includes pre-wired simulation profiles, data types and units.

| Asset | Tags | Category |
|---|---|---|
| Centrifugal Pump | 11 | Rotating Equipment |
| Control Valve | 6 | Instrumentation |
| Silo / Buffer Tank | 7 | Storage |
| Boiler / Steam Generator | 9 | Utilities |
| Packing / Filling Machine | 13 | Packaging |
| IQF Freezer Tunnel | 8 | Process Equipment |
| Conveyor / Belt Transport | 8 | Material Handling |
| Batch Reactor / Vessel | 10 | Process Equipment |
| Weighbridge / Truck Scale | 5 | Logistics |
| Quality Lab Station | 7 | Quality |
| CMMS / Maintenance Feed | 7 | Maintenance |
| ERP Production Order Feed | 7 | ERP / Finance |
| Energy / Utility Meter | 5 | Energy |
| Fryer / Pre-Fryer | 9 | Process Equipment |
| Drum Dryer | 9 | Process Equipment |
| Crystallizer / Evaporator | 8 | Process Equipment |

To add a custom asset: add an entry to `asset_library.json` — it appears in the picker immediately on next page load.

---

## Configuration Reference

All persistent configuration lives in JSON files — no hardcoded data in source code.

| File | Purpose |
|------|---------|
| `uns_config.json` | Full UNS tree definition (enterprise → BU → site → area → workCenter → workUnit → tags) |
| `sim_state.json` | Plant running state, active recipe, and available recipes per site |
| `server_config.json` | OPC-UA bind IP/port, TCP anomaly port, client host |
| `bridge_config.json` | Broker protocol (MQTT/NATS), host, port, credentials, topic prefix, publish interval |
| `payload_schemas.json` | Named payload schema templates for tag classification |
| `asset_library.json` | Reusable asset templates for the UNS designer asset library |

### `server_config.json`

```json
{
  "opc_bind_ip":     "0.0.0.0",
  "opc_port":        4840,
  "opc_client_host": "127.0.0.1",
  "tcp_port":        9999,
  "host_ip":         "127.0.0.1"
}
```

> Set `opc_bind_ip` to `"0.0.0.0"` to accept connections from the network. Set `opc_client_host` / `host_ip` to your machine's LAN IP so other OPC-UA clients on the network can connect.

### `bridge_config.json`

```json
{
  "protocol":     "mqtt",
  "broker_host":  "127.0.0.1",
  "broker_port":  1883,
  "topic_prefix": "",
  "interval":     2
}
```

> Set `protocol` to `"nats"` and `broker_port` to `4222` for NATS native mode.

### Persistent Docker volume

On first boot, `entrypoint.sh` seeds all JSON config files into the `uns-data` Docker volume. Subsequent container rebuilds do **not** overwrite your customised namespace or schemas.

---

## API Reference

All endpoints are served by `app.py` on port 5000.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | Server status, plant states, bridge stats, enterprise name |
| `GET` | `/api/uns` | Current UNS namespace configuration |
| `POST` | `/api/uns` | Save UNS config (triggers factory + bridge restart) |
| `GET` | `/api/asset-library` | Full asset template library |
| `GET` | `/api/simulation-profiles` | Grouped simulation profile catalogue |
| `GET` | `/api/payload-schemas` | Payload schema definitions |
| `POST` | `/api/payload-schemas` | Save payload schemas |
| `POST` | `/api/server/start` | Start OPC-UA factory server |
| `POST` | `/api/server/stop` | Stop OPC-UA factory server |
| `POST` | `/api/bridge/start` | Start MQTT/NATS bridge |
| `POST` | `/api/bridge/stop` | Stop bridge |
| `GET` | `/api/bridge/config` | Get bridge configuration |
| `POST` | `/api/bridge/config` | Save bridge configuration |
| `POST` | `/api/plant/start` | Start a specific plant |
| `POST` | `/api/plant/stop` | Stop a specific plant |
| `POST` | `/api/plant/control` | Recipe switching and plant state changes |
| `GET` | `/api/recipes/<group>/<plant>` | Get recipe list and active recipe for a plant |
| `POST` | `/api/recipes/<group>/<plant>` | Save recipe list for a plant |
| `GET` | `/api/opc/test` | Diagnose OPC-UA connectivity |
| `POST` | `/api/anomaly/inject` | TCP anomaly injection — force a tag value |

---

## Data Flows

### Plant Start/Stop

```
User clicks "Start All"
    │
    ▼
app.py writes sim_state.json:
  {"plants": {"BU|site": {"running": true, ...}, ...}}
    │
    ├──► factory.py reads sim_state on next tick (~1s)
    │        → PlantState.tick(externally_running=True)
    │        → OPC-UA values start updating
    │
    └──► bridge.py reads sim_state before each publish
             → gates: if not running, skip publish
             → starts publishing when running=true
```

### UNS Save

```
User saves UNS in designer
    │
    ▼
app.py writes uns_config.json
    │
    ├──► _ensure_sim_state_synced():
    │        - New plants added with running=false
    │        - Deleted plants removed
    │        - Recipe lists refreshed from UNS tags
    │
    ├──► factory.py restarted (rebuilds OPC address space)
    │
    └──► bridge.py restarted after 4s (picks up new topic mappings)
```

---

## Requirements

### Functional Requirements

| # | Requirement |
|---|-------------|
| F1 | The UNS tree structure must be fully configurable via the web UI and persisted to `uns_config.json` |
| F2 | No tag names, topic paths, enterprise names, or OPC node paths may be hardcoded in `factory.py`, `app.py`, or `bridge.py` |
| F3 | Plant running state must be controlled via `sim_state.json`; OPC-UA writes are best-effort only |
| F4 | Plants must default to **stopped** after any server restart or UNS save |
| F5 | The bridge must not publish data for stopped plants |
| F6 | The bridge must only publish tags explicitly defined in the UNS — not canonically inherited tags |
| F7 | Saving the UNS must restart the factory server and bridge automatically |
| F8 | The dashboard must display live metrics resolved dynamically from simulation profiles in `uns_config.json` |
| F9 | Recipe switching must be supported per plant; recipe options come from tags with `profile='recipe'` in the UNS |
| F10 | Anomaly injection must work for any tag in the UNS regardless of its path or position in the hierarchy |
| F11 | UNS templates must be importable and exportable as JSON |
| F12 | Asset library templates must be configurable and stored in `asset_library.json` |
| F13 | All broker connection settings must be configurable from the UI and persisted to `bridge_config.json` |

### Non-Functional Requirements

| # | Requirement |
|---|-------------|
| N1 | The application must run on any machine with Python 3.10+ without additional services |
| N2 | The OPC-UA server must be discoverable on the local network (configurable bind IP) |
| N3 | Dashboard polling interval: ≤3 seconds for metric updates |
| N4 | Plant start/stop must take effect within 2 seconds of user action |
| N5 | The bridge must reconnect automatically after broker disconnect with exponential backoff |
| N6 | The system must handle any enterprise template without code changes |

---

## File Structure

```
UNS-Design-Studio/
├── app.py                   # Flask web app, REST API, OPC-UA poll loop
├── factory.py               # OPC-UA server + simulation engine
├── bridge.py                # OPC-UA → MQTT/NATS bridge
│
├── uns_config.json          # UNS tree definition (primary config)
├── sim_state.json           # Plant running state + recipe (runtime state)
├── server_config.json       # OPC-UA and TCP port settings
├── bridge_config.json       # Broker connection settings
├── payload_schemas.json     # Payload schema templates
├── asset_library.json       # Asset library for UNS designer
│
├── templates/
│   ├── index.html           # Dashboard
│   ├── uns_editor.html      # UNS / Topic Tree Designer
│   ├── payload_schemas.html # Payload Schema Designer
│   └── uns_live.html        # Live UNS Viewer
│
├── example_UNS_jsons_to_import/   # Example enterprise templates
├── docs/                          # Screenshots
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh            # First-boot config seeding + symlinks
├── start_dashboard.bat      # Windows local launch script
├── start_dashboard.sh       # Linux/Mac local launch script
└── requirements.txt
```

---

## Release Notes

### v3.1 — Live UNS Viewer & Reference Templates *(current)*
- **Live UNS Viewer** at `/live` — real-time namespace monitoring via external MQTT broker + WebSocket
- **Example enterprise templates** — importable JSON files in `example_UNS_jsons_to_import/`
- **FEATURES.md** — this document: full architecture, requirements, API reference and profile reference
- **UNS designer improvements** — updated layout and tag management

### v3.0 — Stateful Profile Engine
- Complete rewrite of the simulation engine — coherent per-plant state machine replacing independent random walks
- 44 simulation profiles — all plant-state-aware, spanning OT, CMMS, quality, logistics, ERP, energy and recipes
- Recipe system — per-plant recipe lists in `sim_state.json`; switching recipes adjusts simulation parameters live
- `recipe` simulation profile — any tag assigned this profile publishes the active recipe name as a string
- 16-asset library — predefined bundles insertable from the UNS designer in one click
- Dynamic enterprise name — dashboard reads UNS tree root name live
- OEE always `A × P × Q / 10000` — never independently randomised
- Accumulators gate on plant state — pause during fault and stop

### v2.0 — Dynamic Address Space
- `uns_config.json`-driven OPC-UA address space — no hardcoded tag names
- Visual UNS Topic Designer with full ISA-95 node type support
- Payload Schema Designer with presets
- NATS native mode in the bridge
- Anomaly injection via TCP socket

### v1.0 — Initial Release
- OPC-UA server with static address space
- MQTT bridge with configurable polling interval
- Flask dashboard with factory status overview
- Basic Gaussian walk simulation
- Docker support

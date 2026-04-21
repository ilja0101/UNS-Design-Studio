# UNS Design Studio — Features & Requirements

## Overview

UNS Design Studio is a self-contained enterprise simulation platform for designing, validating, and demonstrating Unified Namespace (UNS) architectures. It runs a live OPC-UA server with realistic simulated process data, exposes that data to any MQTT or NATS broker via a configurable bridge, and provides a web-based dashboard for monitoring and control.

It is intended for:
- Learning and demonstrating UNS/ISA-95 topic hierarchy design
- Testing broker and data pipeline configurations without real plant equipment
- Rapid prototyping of enterprise data models

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

## Configuration Files

All persistent configuration lives in JSON files — no hardcoded data in source code.

| File | Purpose |
|------|---------|
| `uns_config.json` | Full UNS tree definition (enterprise → BU → site → area → workCenter → workUnit → tags) |
| `sim_state.json` | Plant running state, active recipe, and available recipes per site |
| `server_config.json` | OPC-UA bind IP/port, TCP anomaly port, client host |
| `bridge_config.json` | Broker protocol (MQTT/NATS), host, port, credentials, topic prefix, publish interval |
| `payload_schemas.json` | Named payload schema templates for tag classification |
| `asset_library.json` | Reusable asset templates for the UNS designer drag-and-drop library |

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
- **Asset Library** — drag pre-configured asset templates (e.g. "Press", "Conveyor", "Pump") onto any node. Assets are defined in `asset_library.json`
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

**Capabilities:**
- Builds the OPC-UA address space dynamically from `uns_config.json` on startup
- Every tag's value is driven by its assigned **simulation profile** (see below)
- Each site has an independent `PlantState` state machine with four states: Running, Fault, Recovery, Stopped
  - Spontaneous fault events based on vibration level and remaining useful life
  - Auto-recovery with configurable tick duration
  - Stopped state zeroes flow/speed variables and reduces power to standby level
- Recipe switching: when `sim_state.json` changes the active recipe for a plant, `PlantState` updates its base parameters (power, infeed rate, OEE targets, etc.) on the next tick
- Per-BU default parameters (base power, infeed rate, product price, OEE targets) configurable in `PlantState._GROUP_PARAMS`
- Reads `sim_state.json` on every tick — plant start/stop takes effect within ~1 second
- **Anomaly TCP server** (port 9999): accepts JSON override commands from `app.py` to force any tag to a specific value for testing

**Simulation Profiles:**

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

**Canonical tag inheritance:** If a work center or area node has no tags defined, it inherits tag definitions from the first node of the same name in the tree (used to avoid duplicating tag definitions across identical work centers).

---

### 4. Broker Bridge (`bridge.py`)

Publishes OPC-UA tag values to MQTT or NATS on a configurable interval.

**Capabilities:**
- Supports MQTT (via paho-mqtt) and NATS protocols
- Topic structure: `<prefix>/<BU>/<site>/<area>/<workCenter>/<workUnit>/<tagName>`
- MQTT topic sanitisation: spaces and MQTT reserved characters (`#`, `+`) replaced with underscores
- Publishes only **explicitly defined tags** from `uns_config.json` — no canonical inherited tags are published
- Gating: reads `sim_state.json` before each publish cycle; skips publishing for stopped plants
- Reconnect with exponential backoff (5s–60s) on broker disconnect
- Skips publish when disconnected to avoid message queue buildup
- Publishes bridge statistics (connected, OPC ok, rate, published count) as structured log lines read by `app.py`

---

### 5. Payload Schema Designer (`/payload-schemas`)

Named schema templates that classify tags by their payload structure.

**Capabilities:**
- Create, edit, and delete named schemas (e.g. "standard", "alarm", "quality")
- Each schema defines expected field names and data types
- Schemas are assignable to tags in the UNS designer (`payloadSchema` property)
- Schemas are stored in `payload_schemas.json`

---

### 6. Live UNS Viewer (`/live`)

Real-time view of all MQTT/NATS messages flowing from the bridge.

**Capabilities:**
- Connects to the configured broker and subscribes to all topics under the configured prefix
- Displays live topic/value pairs in a filterable tree view
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

## Data Flow: Plant Start/Stop

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

## Data Flow: UNS Save

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
EnterpriseSimulator/
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
└── requirements.txt
```

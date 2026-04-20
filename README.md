# 🏭 Royal Farmers Collective — Enterprise UNS Simulator

A fully self-contained **Unified Namespace simulator** for industrial IoT demos, training and development. Simulates a fictional Dutch agri-food concern across five divisions and thirteen factories, publishing realistic OT and IT data over OPC-UA, MQTT and NATS.

Built as a learning and demo tool for **ISA-95 hierarchy**, **UNS architecture**, **OEE analytics**, **CMMS/ERP integration**, and **digital twin** concepts — without needing real factory hardware.

---

## ✨ Features

- **Stateful simulation engine** — each factory runs a state machine (Running → Fault → Recovery → Stopped). OEE, energy, quality, logistics and finance data all derive from the same coherent plant state. No more random noise.
- **44 simulation profiles** covering the full IT/OT stack: OEE pillars, process variables, accumulators, CMMS, quality lab, logistics, ERP/finance, energy and utilities
- **Asset library** — 16 predefined asset templates (Pump, Valve, Silo, Boiler, Packing Machine, IQF Tunnel, Conveyor, Batch Reactor, Weighbridge, Quality Lab, CMMS Feed, ERP Order Feed, Energy Meter, Fryer, Drum Dryer, Crystallizer) that can be inserted into any UNS node with one click
- **Visual UNS Topic Designer** — browser-based drag-and-drop ISA-95 hierarchy editor with asset picker, grouped simulation profile dropdown, and topic path preview
- **OPC-UA server** — full address space built dynamically from `uns_config.json`
- **Protocol bridge** — publishes to MQTT or NATS with configurable payload schemas (Standard, Simple, Sparkplug B-like, ISA-95 Extended, PI-like, InfluxDB-like)
- **Web dashboard** — start/stop individual factories, inject anomalies, monitor bridge stats, design payload schemas
- **Docker-first** — single `docker compose up` gets everything running

---

## 🏢 The Fictional Enterprise

**Royal Farmers Collective** — a parody of Royal Cosun, an agricultural processing holding with five divisions:

| Division | Product | Factories |
|---|---|---|
| 🥔 **KnappertjesBV** | Chips & Snacks | Terneuzen, Bergen op Zoom |
| 🌾 **Vlokkenheim** | Potato Flakes | Emmeloord, Veendam |
| 🍟 **FritoMaxx** | Frozen Frites | Heerenveen, Harlingen, Meppel, Hardenberg, Hoogeveen, Coevorden |
| 🌿 **Wortelkracht** | Chicory & Inulin | Roosendaal |
| 🍬 **DeBietenBende** | Sugar Beet & Sugar | Zevenbergen, Stadskanaal |

---

## 🖥️ Screenshots

> **Dashboard** — factory status overview with OEE, power draw and running state per plant

```

<img width="1920" height="931" alt="image" src="https://github.com/user-attachments/assets/080df3ed-ad06-422a-bde3-c68c91504c62" />



> **UNS Topic Designer** — build your ISA-95 namespace visually

```
🌐 RoyalFarmersCollective
 └─ 🏭 KnappertjesBV
     └─ 🏗️  Terneuzen2
         └─ 📐 ProductionLine
             ├─ ⚙️  OEE              [4 tags]
             ├─ ⚙️  Energy           [2 tags]
             ├─ ⚙️  Maintenance      [5 tags]
             └─ ⚙️  Quality          [4 tags]
```

> **Asset Picker** — insert pre-configured asset bundles into any node

```
🧩 Insert Asset
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ 💧 Pump      │ │ 📦 Packing   │ │ ♨️  Boiler    │
│ Rotating Eq. │ │ Packaging    │ │ Utilities    │
│ 11 tags      │ │ 13 tags      │ │ 9 tags       │
└──────────────┘ └──────────────┘ └──────────────┘
```
<img width="716" height="661" alt="image" src="https://github.com/user-attachments/assets/6afa89de-c1ca-49d1-ac0c-be878a354ea5" />

Tags with simulation profiles are automatically added!

<img width="1917" height="938" alt="image" src="https://github.com/user-attachments/assets/9f27d331-8288-4e24-9a2c-22d908f43bbd" />


---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- Ports `5000`, `4840`, `9999` available on your host

### 1 — Clone the repo

```bash
git clone https://github.com/your-org/enterprise-simulator.git
cd enterprise-simulator
```

### 2 — Build the image

```bash
docker build -t uns-simulator:latest .
```

### 3 — Start the simulator

```bash
docker compose up -d
```

### 4 — Open the dashboard

```
http://localhost:5000
```

That's it. The simulator starts automatically, all 13 factories boot in Running state, and the OPC-UA server is live on port 4840.

---

## 🔌 Connecting a MQTT or NATS Broker

The bridge is **not started automatically** — configure it first via the dashboard.

### MQTT

1. Open the dashboard → **Bridge** tab
2. Set `Protocol: mqtt`, `Broker Host`, `Broker Port` (default 1883)
3. Click **Start Bridge**

The bridge polls OPC-UA every 2 seconds (configurable) and publishes to topics structured as:

```
RoyalFarmersCollective/KnappertjesBV/Terneuzen2/ProductionLine/OEE/OEEPercent
```

### NATS

Set `Protocol: nats` and point to your NATS server. Subjects use `.` separators:

```
RoyalFarmersCollective.KnappertjesBV.Terneuzen2.ProductionLine.OEE.OEEPercent
```

### Connecting from TimescaleDB / Telegraf

Use the Telegraf MQTT consumer input plugin pointed at `RoyalFarmersCollective/#` and write to TimescaleDB. The topic hierarchy maps cleanly to ISA-95 `L1`–`L6` columns.

---

## 🎨 UNS Topic Designer

Navigate to `http://localhost:5000/uns` to open the visual namespace editor.

### Building a namespace from scratch

1. Click **+ Node** to add a child under the root
2. Set the node **Type** (Enterprise → Business Unit → Site → Area → Work Center → Work Unit → Device)
3. Switch to the **Tags** tab to add data points

### Using the Asset Library

1. Select any node in the tree
2. Click **🧩 Insert Asset** in the Tags tab
3. Filter by category, select an asset, preview its tags, click **Insert Tags**

All tags come pre-configured with appropriate simulation profiles. A Centrifugal Pump gives you motor current, vibration, flow rate, pressure, speed, RUL and run hours — all coherent and plant-state-aware.

### Simulation profiles

Click the simulation cell on any tag row to open the profile editor. Profiles are grouped by domain:

| Group | Example profiles |
|---|---|
| OT / Process | `oee`, `availability`, `motor_current`, `vibration`, `flow_rate`, `level` |
| Accumulators | `accumulator_good`, `accumulator_energy`, `counter_faults` |
| Maintenance / CMMS | `mtbf`, `mttr`, `pm_compliance`, `remaining_useful_life` |
| Quality / Lab | `quality_metric_cont`, `quality_hold`, `batch_id` |
| Logistics | `silo_level`, `truck_id`, `days_of_supply`, `order_status` |
| ERP / Finance | `erp_order_id`, `revenue_eur`, `margin_pct` |
| Energy / Utilities | `power_kw`, `steam_flow`, `co2_kg` |

---

## 🧠 Simulation Engine

Each factory runs an independent `PlantState` state machine:

```
Running ──(random fault)──► Fault ──(repair done)──► Recovery ──► Running
   ▲                                                                  │
   └──────────────────────────(startup)───────────────────────────────┘

Stopped ──(start command)──► Recovery ──► Running
```

**All tags derive from the plant state** — no independent random values. When a fault fires:
- Availability drops sharply
- Flow rate and speed go to zero
- Motor current spikes
- Vibration rises
- Power draw drops to ~12% (standby only)
- Accumulators pause

When recovery completes, all values climb back toward their targets. OEE is always computed as `Availability × Performance × Quality / 10000` — never independently randomised.

Per-division base parameters (power draw, infeed rate, product price, unit cost) ensure a FritoMaxx factory behaves differently from a DeBietenBende sugar plant.

---

## 📁 Project Structure

```
EnterpriseSimulator/
├── factory.py          # OPC-UA server + stateful simulation engine
├── bridge.py           # OPC-UA → MQTT / NATS bridge
├── app.py              # Flask dashboard + REST API
├── recipe.py           # Product recipes per division
├── client.py           # CLI client for testing
│
├── uns_config.json     # ISA-95 namespace definition (editable via UI)
├── sim_state.json      # Runtime plant running/stopped state
├── asset_library.json  # Predefined asset templates
├── payload_schemas.json# MQTT/NATS payload schema definitions
├── bridge_config.json  # Bridge connection settings
├── server_config.json  # OPC-UA server bind/endpoint config
│
├── templates/
│   ├── index.html          # Dashboard
│   ├── uns_editor.html     # UNS Topic Designer
│   └── payload_schemas.html# Payload Schema Designer
│
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh       # Volume seeding + symlinks on first boot
└── requirements.txt
```

---

## ⚙️ Configuration

### `server_config.json`

```json
{
  "opc_bind_ip":    "0.0.0.0",
  "opc_port":       4840,
  "opc_client_host":"127.0.0.1",
  "tcp_port":       9999,
  "host_ip":        "127.0.0.1"
}
```

Set `host_ip` to your Docker host's LAN IP if you want OPC-UA clients on other machines to connect.

### `bridge_config.json`

```json
{
  "protocol":    "mqtt",
  "broker_host": "127.0.0.1",
  "broker_port": 1883,
  "topic_prefix": "",
  "interval":    2
}
```

Change `protocol` to `"nats"` and `broker_port` to `4222` for NATS mode.

### Persistent volume

All JSON config files are seeded into the `uns-data` Docker volume on first boot by `entrypoint.sh`. Subsequent container rebuilds preserve your custom namespace without overwriting it.

---

## 🔧 Running Without Docker

If you prefer to run locally (e.g. for development):

```bash
pip install -r requirements.txt

# Terminal 1 — OPC-UA simulator
python factory.py

# Terminal 2 — Dashboard + bridge manager
python app.py

# Terminal 3 (optional) — Bridge directly
python bridge.py
```

Dashboard available at `http://localhost:5000`.

---

## 📦 API Reference

The dashboard exposes a REST API used by the frontend, also useful for scripting:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/uns` | Get current UNS configuration |
| `POST` | `/api/uns` | Save UNS configuration (restarts factory) |
| `GET` | `/api/asset-library` | Get asset template library |
| `GET` | `/api/simulation-profiles` | Get grouped simulation profile catalogue |
| `GET` | `/api/payload-schemas` | Get payload schema definitions |
| `POST` | `/api/payload-schemas` | Save payload schemas |
| `POST` | `/api/server/start` | Start OPC-UA factory server |
| `POST` | `/api/server/stop` | Stop OPC-UA factory server |
| `POST` | `/api/bridge/start` | Start MQTT/NATS bridge |
| `POST` | `/api/bridge/stop` | Stop bridge |
| `GET` | `/api/bridge/config` | Get bridge configuration |
| `POST` | `/api/bridge/config` | Save bridge configuration |
| `POST` | `/api/plant/start` | Start a specific plant |
| `POST` | `/api/plant/stop` | Stop a specific plant |
| `GET` | `/api/opc/test` | Test OPC-UA connectivity |

---

## 🗂️ Release Notes

### v3.0 — Stateful Profile Engine
*Current release*

- **Complete rewrite of `factory.py` simulation engine** — replaced independent random walks with a coherent per-plant state machine (Running / Fault / Recovery / Stopped)
- **44 simulation profiles** covering OT, CMMS, quality, logistics, ERP and energy — all plant-state-aware
- **Asset library** (`asset_library.json`) — 16 predefined asset templates with profiles pre-wired
- **UNS designer** — added 🧩 Insert Asset picker with category filtering and tag preview
- **Profile dropdown** in tag editor now dynamically loaded from `/api/simulation-profiles` — grouped by domain, with contextual hints per profile
- **New API endpoints**: `/api/asset-library`, `/api/simulation-profiles`
- **Backward compatible** — existing `uns_config.json` profiles (`oee`, `percent`, `temperature`, `accumulator`, `boolean`, `truck_id`) continue to work via legacy aliases
- **OEE is now always `A × P × Q / 10000`** — never independently randomised
- **String tags now publish meaningful values**: truck IDs, batch IDs, lot IDs, order statuses, ERP order numbers
- **Accumulators only advance when the plant is running** — paused during fault and stopped states
- **Silo levels drain during production and auto-refill** on truck arrival events
- **Finance accumulators** (revenue, production cost, waste cost, margin) accumulate coherently based on good/bad output rates

### v2.0 — Dynamic Address Space
- Introduced `uns_config.json`-driven dynamic OPC-UA address space — no hardcoded tag names
- Added visual UNS Topic Designer with ISA-95 node types
- Added Payload Schema Designer with multiple schema presets (Standard, Sparkplug B-like, ISA-95 Extended, PI-like, InfluxDB-like)
- Added canonical tag inheritance so all plants in a division share the same tag set
- Per-plant start/stop control via `sim_state.json`
- NATS native mode added to bridge (alongside MQTT)
- Anomaly injection via TCP socket

### v1.0 — Initial Release
- OPC-UA server with hardcoded RoyalFarmersCollective address space
- MQTT bridge with configurable polling interval
- Flask dashboard with factory status overview
- Basic Gaussian walk simulation for all tags
- Docker support

---

## 🤝 Contributing

This is an internal demo and training tool. To contribute:

1. Fork the repo (or clone if you have direct access)
2. Create a feature branch: `git checkout -b feature/my-improvement`
3. Commit your changes: `git commit -m 'Add XYZ'`
4. Push and open a pull request

When adding new simulation profiles, add the profile to both `_profile_value()` in `factory.py` and the `SIMULATION_PROFILES` dict — the latter is what populates the UNS designer dropdown.

When adding new asset templates, add them to `asset_library.json` following the existing structure.

---

## 📄 License

Internal use only. Not for public distribution.

---

*Royal Farmers Collective is a fictional entity created for educational and demonstration purposes. Any resemblance to actual companies, living or dead, is purely coincidental — and probably intentional.*

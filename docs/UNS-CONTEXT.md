# UNS Design Studio — Context & Industrial IoT Landscape

This document explains where this project sits in the broader industrial IoT
architecture conversation: what the simulator does, who uses it, and how the
"Unified Namespace" school of thought relates to alternative approaches.

---

## 1. What this project is

A **UNS (Unified Namespace) sandbox** — a self-contained simulator that lets
practitioners design, demo, and prototype industrial data architectures without
needing real PLCs, factories, or vendor-specific platforms.

It bundles:

- **UNS designer** — visual ISA-95 tree editor (Enterprise → BU → Site → Area →
  WorkCenter → WorkUnit → Tags).
- **OPC-UA server** — dynamic address space built from the designed tree.
- **Stateful simulation engine** — per-plant state machine (Running / Fault /
  Recovery / Stopped) with profile-driven tag values, recipe overrides, and
  realistic correlations (vibration ↔ fault risk, OEE = avail × perf × qual,
  rate-based accumulators).
- **MQTT / NATS bridge** — publishes OPC-UA values to topic trees with
  configurable separators, prefixes, and payload schemas.
- **Asset library** — reusable equipment templates with pre-defined tag sets.
- **Anomaly injection** — TCP override channel for testing alarm rules and
  anomaly detectors against known-bad data.
- **Web dashboard** — Flask-based control plane for plants, recipes, and the
  factory subprocess lifecycle.

---

## 2. Use cases

| Audience | Typical use |
|---|---|
| **SI / consultants** | UNS proofs-of-concept and customer demos without a physical line in the room. |
| **Vendors** | Integration testing for UNS-aware tools (Ignition, Grafana, HighByte, MQTT Explorer, historians). |
| **Educators** | Teach ISA-95 modeling, OPC-UA browsing, MQTT topic design, and payload schema concepts on synthetic data that behaves like a plant. |
| **Architects** | Iterate on naming conventions, separators, payload schemas, and asset library structures cheaply before locking decisions. |
| **Data / ML teams** | Build dashboards, anomaly models, and condition-based-maintenance triggers against the simulator and swap to a real OPC server later. |
| **MES / scheduling demos** | Show recipe / changeover behavior without rewiring a real production line. |

It is **not** a production tool. Its value is in being throw-away realistic
during the design and validation phases of an OT modernization project.

---

## 3. The UNS school of thought

The simulator's worldview tracks Walker Reynolds / 4.0 Solutions, who
popularized **Unified Namespace** as a design pattern:

- **Single source of truth** — one namespace, every system publishes to / reads
  from it.
- **MQTT-centric, event-driven** — report-by-exception, not polling.
- **Edge-first** — context produced where data is born, not in the cloud.
- **ISA-95 hierarchy** — flattened into MQTT topic paths.
- **Decoupled producers / consumers** — broker is the integration boundary.

This framing landed broadly with OT audiences who had been buried in
vendor-specific stacks, and it now drives a large fraction of the modern
"industrial DataOps" conversation.

---

## 4. Alternative / adjacent schools

UNS is one architecture among several. Production stacks usually blend a few.

### 4.1 ISA-95 / B2MML (the formal spec)
Original standard the UNS borrows its hierarchy from. XML / database-centric,
MES-oriented, top-down governance. UNS is its scrappier MQTT cousin.

### 4.2 Sparkplug B (Cirrus Link / Eclipse Tahu)
MQTT spec for industrial: stateful sessions (birth / death messages), strict
topic structure, defined payload format. Many UNS implementations use Sparkplug
under the hood, but a "Sparkplug-only" camp argues the ISA-95 framing is
unnecessary — the spec is enough. Inductive Automation pushes this hardest.

### 4.3 OPC UA purists
"Address space + Companion Specs (PA-DIM, VDMA, AutoID) is the model. MQTT is
unnecessary middleware." The OPC Foundation's line. UA-over-MQTT (UA PubSub) is
their answer to UNS-style pub/sub.

### 4.4 Industrial DataOps (HighByte, Litmus, Cogent)
Focus is **pipelines, transformations, governance, lineage**. UNS is one of
many possible sinks. Treats data as an engineered artifact rather than a
pub/sub fabric.

### 4.5 Event streaming (Confluent / Kafka, Solace event mesh)
"UNS but log-based" — replayable, partitioned, schema registry, designed for
analytics-heavy and high-throughput workloads. NATS sits on the lighter,
edge-friendly end of this same family.

### 4.6 Historian-first (Aveva PI, InfluxDB, TDengine, TimescaleDB)
The historian itself is the source of truth; a UNS layer is optional veneer.
This was the OT default before MQTT-style pub/sub gained traction.

### 4.7 Asset Administration Shell (AAS) / Manufacturing-X / Catena-X
European Industrie 4.0 / Plattform i40 effort. Digital-twin shells, semantic
models, supply-chain federation. Government-backed in Germany / EU; strong in
automotive supply chains.

### 4.8 ISA-88 batch control
Recipe and batch-state focus. OPC UA has a batch companion spec. Heavily used
in pharma and food & beverage where the recipe is the primary modeling concern.

### 4.9 MTConnect
Discrete manufacturing (CNC, machine tools). XML over HTTP, not pub/sub. Niche
but dominant in its segment.

---

## 5. How they coexist in practice

A typical modern OT stack pulls from several of the above:

```
┌─────────────────────────────────────────────────────────┐
│  Consumers: dashboards, MES, ML, supply-chain partners  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  UNS layer (MQTT + ISA-95 topics)  ← Walker / 4.0 frame │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
┌──────────▼──────────┐    ┌──────────▼───────────────┐
│  Event log (Kafka)  │    │  Historian (PI / Influx) │
│  for analytics      │    │  for storage & queries   │
└──────────┬──────────┘    └──────────┬───────────────┘
           │                          │
┌──────────▼──────────────────────────▼───────────────┐
│  Edge: OPC UA servers, Sparkplug B, MTConnect, …    │
└──────────────────────┬──────────────────────────────┘
                       │
                  ┌────▼────┐
                  │  PLCs   │
                  └─────────┘
```

The UNS layer is the **integration bus**; the other layers handle storage,
analytics, federation, and connectivity. Walker Reynolds' contribution was
popularizing the *single-namespace + edge-driven + report-by-exception* mantra
to a broad OT audience — not inventing every component beneath it.

---

## 6. Where this simulator fits the map

UNS Design Studio is opinionated toward the **MQTT + ISA-95 + payload-schema**
school. It is most directly useful for:

- Designing what the topic tree and payload schemas *should* look like.
- Validating downstream consumers against realistic synthetic data.
- Teaching the conceptual model.

It does **not** ship Sparkplug B, Kafka, AAS, or historian integration out of
the box. Those would be additions on top of (or replacements for) the bridge
layer.

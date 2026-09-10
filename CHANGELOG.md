# Changelog

All notable changes to UNS Design Studio are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [2.4.0] — 2026-09-11

### Added

- **The chat shows, not tells** — the same visual vocabulary as IAI-V2 and the
  AMIX Ask AI panels, so one prompt convention serves the family
  (`ui/src/pages/agent/{markdown,ChartBlock,MermaidBlock,SvgBlock,CodeBlock}.tsx`).
  - Markdown **tables** (GFM, with alignment), blockquotes and rules.
  - ```` ```chart ```` renders a bar/line/area/scatter chart from a JSON spec
    with hover values — hand-rolled SVG geometry ported from IAI-V2, no chart
    library.
  - ```` ```mermaid ```` renders a diagram; Mermaid is a lazy chunk (loaded the
    first time a diagram appears, ~170 kB gzipped, strict security level).
  - ```` ```svg ```` renders an inline drawing after allow-list sanitisation:
    scripts, event handlers, `<image>`, `foreignObject` and external `href`s are
    stripped, and an SVG without a `viewBox` is refused.
  - Other fences get syntax highlighting (json/yaml/xml/python/bash) with copy,
    and download for the longer ones. Tool results over 400 characters can be
    downloaded as JSON from the card.
  - **`artifact_create(name, content)`** — the agent hands the user a file,
    shown as a downloadable card. An artifact is an attachment the agent
    authored: same storage, same `attachment_read`, so an MCP client can read
    what the built-in agent produced.
  - **Effort chip** (auto · low · med · high) next to the paperclip: reasoning
    effort for the next turn only, remembered on the message and shown on the
    turn. The system prompt teaches the agent when to use each of the above.

## [2.3.0] — 2026-09-11

### Added

- **Attachments in the agent chat.** A topic policy kept in Excel, a Kepware
  CSV export, a JSON model or a P&ID can be attached to a message — paperclip,
  drag-and-drop or paste — instead of being retyped (`uds_agent/attachments.py`,
  `POST /api/agent/attachments`, `attachments: [ids]` on `/api/agent/chat`).
  - Workbooks and CSVs reach the model as `a | b | c` rows per sheet, trimmed of
    empty rows and columns; text files as themselves; images as an `image_url`
    content part (downscaled in the browser first). Anything else is named and
    declared unreadable rather than pretended.
  - **Bounded by design**: 12 000 characters per file and 30 000 per message go
    inline; a bigger sheet is cut with a line saying how to page it, and two new
    read-only tools — `attachment_list`, `attachment_read` — page rows or lines
    by offset. They go through the backend like every other tool, so the
    standalone MCP process reads a file it does not have on disk.
  - The conversation stores metadata only; the model's copy is rebuilt from the
    file on each turn, so a chat never holds a spreadsheet twice and an image
    never lands in the JSON. Files live under `agent/attachments/`.
  - The system prompt tells the agent an attached policy *is* the policy — rows
    into `policy_set`'s fields, everything else into `notes` verbatim — and a
    tag list is a build order.
  - `openpyxl` joins `requirements.txt`; the standalone MCP image needs nothing
    new.

## [2.2.0] — 2026-09-10

### Added

- **A modelling agent, an agent chat, and an MCP server.** UDS can now be driven
  by a language model: hand it your organisation's **topic policy** and ask for
  a simulation, and it reads the rulebook, builds the ISA-95 tree, instantiates
  real equipment from the asset library, grades its own work, fixes what it
  broke, and shows you the topics the bridge will publish. See
  [docs/AGENT_AND_MCP.md](docs/AGENT_AND_MCP.md).
  - **One tool registry, three consumers** (`uds_agent/tools.py`, 29 tools). The
    built-in chat agent, the in-process `/mcp` endpoint and the standalone
    `python -m uds_mcp` entrypoints all execute the same functions, so an
    external agent is never less capable than the built-in one. Tools reach the
    app through `uds_agent/backend.py`: `DirectBackend` re-enters the app's own
    HTTP handlers in-process (so an agent's UNS save restarts the OPC server and
    the bridge exactly as the Designer's does), `HttpBackend` drives a remote UDS
    over its REST API.
  - **Topic policy as a first-class object** (`uds_agent/policy.py`,
    `topic_policy.json`). Separator, prefix, allowed ISA-95 levels, per-level
    naming patterns, tag case and qualifiers, forbidden parts, topic length —
    plus a free-text `notes` field for the parts a regex cannot express, which
    is injected verbatim into the agent's system prompt. `policy_check` walks
    the model with `uns_tree.build_bridge_entries`, the bridge's own walk, so
    what it validates is literally what would be published.
  - **Every write is snapshotted**, and `uns_revert` puts any of the last 30
    model states back — including undoing a revert. Surfaced as an **Undo** tab
    on the Agent page and at `/api/agent/snapshots`.
  - **Agent page** (`/app/agent`) — streaming chat over SSE, a collapsible card
    per tool call showing arguments and results, conversation history, and a
    side panel with the policy editor, a live compliance report, the topics the
    model would publish, and the undo history.
  - **MCP server** at `POST /mcp`, streamable HTTP, bearer-gated with a token
    minted on first use (`UDS_MCP_TOKEN` to pin it, `UDS_MCP_ENABLED=0` to
    switch it off). `GET /mcp/info` is unauthenticated and reports the protocol
    revision and tool list without leaking anything. Also `python -m uds_mcp
    stdio` for Claude Desktop / Claude Code, and `python -m uds_mcp http` +
    `Dockerfile.mcp` for a separate trust boundary in the shape of
    UNS-Knowledge-Graph's `kg-mcp`.
  - **Settings → Agent** — endpoint, model and API key for any OpenAI-compatible
    provider (Azure AI Foundry, OpenAI, OpenRouter, Ollama, vLLM), a tool-step
    budget, a read-only switch, extra system-prompt instructions, and the MCP
    endpoint/token with a rotate button. The API key is never returned to the
    browser; `UDS_LLM_*` environment variables override the stored values.
  - `uds_agent/llm.py` ports the wire-format lessons from
    UNS-Industrial-AI-V2's adapter: `max_completion_tokens` → `max_tokens`
    fallback, optional params dropped on rejection, a non-streaming fallback,
    tool-call fragments merged by index, and malformed tool arguments answered
    as an error rather than raised.

- **Raw OPC-UA server data models — design the source, not just the UNS.**
  The Designer now edits two kinds of tree: the UNS model that the factory
  simulates and the bridge publishes, and a *raw OPC-UA server* — a PLC sim
  that is served over OPC-UA and published to no broker. Point a gateway or
  protocol converter at it and let someone model the UNS themselves, instead of
  handing them a finished namespace.
  - `app.py` — `POST /api/plc/blank` creates an empty source (no export file
    needed), `GET|PUT /api/plc/<id>/config` reads and writes its tree (saving
    hot-restarts just that sim — the factory and bridge are untouched), and
    `GET /api/plc/<id>/truth[?format=csv]` returns the **answer key**.
  - UI — a source picker in the Designer toolbar (remembered across reloads),
    a raw node palette (channel → device → group instead of ISA-95 levels), the
    live OPC-UA endpoint, an answer-key download, and **Edit in Designer** /
    **New empty source** on the PLC Simulators page.
- **Rawness levels for asset bundles.** An asset can now be inserted the way it
  really comes off a PLC: *Modelled* (the library as-is), *Flat* (readable,
  instance-prefixed), *PLC symbolic* (vendor symbol names — Kepware, Siemens
  German shorthand, Rockwell, ISA loop tags — no units, no descriptions) and
  *Raw addresses* (`DB101.DBW0`, `40001`, `N7:12`, with analogs as integer
  counts). Plus spare/dead padding tags. Every rawified tag keeps a hidden
  `_truth` block — what it really is — so a mapping run by a person or an AI
  agent can be scored against ground truth (`ui/src/pages/designer/rawify.ts`).
- **Assets bring their own structure.** Inserting a bundle can create its own
  node (named after the loop tag or the asset) and optionally split the tags
  into the folders a device actually has — Status, Analog, Counters, Setpoints,
  Ident — instead of dropping loose tags into whatever node was selected.
- `factory.py` — `simulation.rawScale` presents an engineering value as PLC
  counts (60 m³/h → 13824), leaving the scaling for the mapper to recover.

### Changed

- `app.py` — the auth hook now also accepts a per-boot loopback token so the
  agent's in-process tool calls satisfy HTTP Basic without handling the
  operator's password. The token is regenerated every boot and never persisted.
- `requirements.txt` — added `openai` and `httpx`. `openai` is imported only
  when a chat turn actually runs, so a UDS with no LLM configured never
  touches it.

- **Renamed for clarity**: *UNS Designer* → **Data Model Designer** (it models
  both a UNS and a raw OPC-UA server, and says which one it is editing), and
  *UNS Hub* → **UNS Simulation Publisher**.
- `factory.py` now serves the integer width a tag declares (`Int16` reads as
  Int16, not Int64) and clamps to it, so a narrow tag saturates like a real PLC
  word instead of failing the write.

### Fixed

- The Designer's datatype dropdown only knew `Float/Int/Bool/String/DateTime`,
  so a tag from a PLC catalog import (`Boolean`, `Int16`, `UInt16`) displayed as
  "Float" and could be silently retyped by opening the dropdown.

## [Unreleased] — 2026-07-18

### Added

- **PLC Simulators — simulate raw PLC/Kepware datasources as standalone
  OPC-UA servers.** For testing PLC → UNS (NATS) → SCADA integration paths and
  AI-driven tag mapping (UNS-Protocol-Converter), the studio can now run N
  extra OPC-UA servers, each serving an imported PLC tag catalog with live
  simulated values.
  - `tools/import_plc_catalog.py` — converts a browsed catalog export from
    UNS-Protocol-Converter (`catalog_<source>.json` / `/api/catalog` /
    `catalog.csv`) **or** a native Kepware export (JSON project or per-device
    tag CSV) into a Design Studio config. Formats are auto-detected; multiple
    files merge into one tree. Sim profiles are chosen from tag name + datatype
    (Kepware scaling limits feed sim min/max), writable tags become held
    RW command tags, and repeated structures are stamped `udtType` — ground
    truth for mapping evaluation.
  - `factory.py` — `UDS_CONFIG`, `UDS_OPC_PORT`, `UDS_TCP_PORT` env overrides
    so one binary can serve any config on any port (N PLCs = N processes).
  - `app.py` — PLC instance manager: registry (`plc_instances.json` +
    `plc_configs/`), `GET /api/plc/instances`, `POST /api/plc/import`,
    `POST /api/plc/<id>/start|stop`, `PATCH`/`DELETE /api/plc/<id>`,
    per-instance autostart, dashboard-shutdown cleanup.
  - UI — new **PLC Simulators** page (`/plc`): instance cards with endpoint
    (copy-to-clipboard), tag/UDT counts, Start/Stop/Delete, autostart toggle,
    and an import modal (browse one or more export files, optional name/port).
  - `docker-compose.plc-lab.yml` — lab stack: UNS-mode studio + standalone
    PLC sim containers + NATS.
  - Tests: `tests/test_import_plc_catalog.py` (24 tests — format parsing,
    tree equivalence across formats, UDT detection, id uniqueness, scaling,
    OPC-UA NodeId datatypes, system-node filtering, writable-PV vs setpoint).
  - Hardened against real exports: native Kepware CSV structure is read from
    the **Address** column (real Tag Names are flat leaves); browsed catalogs
    report datatypes as **OPC-UA NodeIds** (`i=1` Boolean … `i=10` Float, with
    custom/structured `ns=…;s=…` types → inert String); the OPC-UA `Objects`
    root and Kepware server/diagnostic branches (`Server`, `Aliases`,
    `_Statistics`/`_System`, …) are dropped; multi-source catalogs group by
    `source_id`. Writability no longer freezes a tag — only setpoint/command-
    named tags `hold`; writable process values keep simulating (like a real
    PLC PV). Verified against ~130k-tag real Kepware/converter exports.

## [Unreleased] — 2026-07-17

### Fixed

- **Regression — Import / Export / Clear missing from the UNS Designer.**
  When the UI was rebuilt on the React/family stack (commit `ac754da`,
  2026-07-11), the UNS Designer toolbar was reduced to a **Save** button. The
  **Import**, **Export**, and **Clear** actions that existed in the legacy
  editor (`static/js/uns_editor.js`: `doExportJSON` / `showImport` / `doImport`
  / `confirmClearAll`) were never ported to the React `Designer`, so from the
  primary UI a user could no longer export, import, or clear a UNS.
  - **Restored** (`bd29d37`) in `ui/src/pages/designer/Designer.tsx`:
    - **Export** — downloads the current config as `<root>_uns_config.json`.
    - **Import** — picks a `.json` (accepts `{tree,…}` or a bare tree node),
      re-keys every node/tag id (`reId`) so a null/duplicate id cannot break
      node selection, and loads it as a draft to Save.
    - **Clear** — resets to an empty enterprise root (Save to persist).
  - *Introduced in:* `ac754da` · *Fixed in:* `bd29d37`.

- **UNS Designer crash on generated nodes.** Nodes/tags produced by the
  control-loop generator had `id: null`; the designer keys selection and React
  rendering on `node.id` / `tag.id`, so selecting a generated `cmd` / `setpoint`
  / `vfd` node failed to load. The generator now assigns a unique stable id to
  every node and tag. (`51fa83b`)

### Added

- **Closed-loop setpoints & command tags** for Industrial-AI optimization —
  per-equipment control loops (`ctrl_*` profiles): an optimizer publishes a
  setpoint request, the bridge writes it back to OPC-UA (pub/sub or NATS
  request-reply), the controller ramps the committed setpoint and the process
  values track it (VFD affinity laws for power/current/frequency/flow).
- **Realistic PLC-HMI handshake** — operator mode + accept-optimizer permissive,
  EU limits, optimizer heartbeat + watchdog, and a command-status writeback. The
  optimizer's setpoint is honoured only in Remote + enabled + watchdog-OK; else
  the loop reverts to the operator setpoint (fail-safe on comms loss).
- **Optical sorters & rejects** — a sensitivity loop trading reject rate / yield
  loss against foreign-material escape, with reject accumulation and ejector rate.
- **Motor (M01) devices under VFDs** — each VFD (a `device`) drives a `motor-01`
  (`device`) child with the shaft-speed PV, three-phase L1/L2/L3 voltages &
  currents, winding/bearing temperatures, power factor, insulation resistance
  and run-hours. The drive keeps its drive-side telemetry.
- **`folder` node type** and **`device`** used correctly — `cmd` / `setpoint`
  are tag folders; `vfd` / `motor-01` are devices (control module + motor).
- **Bridge command write-back** (NATS/MQTT) + **NATS request-reply** ack.
- **Asset-library control modules** — VFD, VFD-driven pump, decanter, screw
  loader, level-controlled silo, flow/temperature control loops, optical sorter,
  electric motor.
- **`default` profile `base`** — analog tags can jitter around a configured
  nominal (e.g. 400 V line, 68 °C winding) instead of the tag default.
- Docs: `docs/SETPOINT_OPTIMIZATION.md`, `docs/REALISTIC_CONTROL_ARCHITECTURE.md`;
  tool `tools/enhance_uns_control_loops.py`.

### Notes

- Backward compatible: configs without `ctrl_*` tags (Vault-Tec and all bundled
  templates) build, tick, and bridge unchanged. The public repo default UNS
  (`uns_config.json`) remains **Vault-Tec Industries**.

## [V2.0]

See [FEATURES.md → Release Notes](FEATURES.md#release-notes) for the V2.0 history
(Live UNS Viewer, stateful profile engine, dynamic address space, repository
cleanup and release preparation).

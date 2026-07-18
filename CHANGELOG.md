# Changelog

All notable changes to UNS Design Studio are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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

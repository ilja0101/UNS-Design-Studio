# Changelog

All notable changes to UNS Design Studio are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

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

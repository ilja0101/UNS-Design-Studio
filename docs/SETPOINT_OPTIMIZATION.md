# Setpoint Optimization — closed-loop control tags for the Industrial-AI suite

This guide describes the **request → controller → setpoint → PV** control topology
added to UNS Design Studio, and how an optimizer agent reads monitoring tags and
publishes optimal setpoints over MQTT/NATS.

> For *why* the design looks like this — how a real PLC-HMI setpoint works, and what
> pub/sub + request-reply change — see
> [REALISTIC_CONTROL_ARCHITECTURE.md](REALISTIC_CONTROL_ARCHITECTURE.md). That note
> covers the mode / permissive / watchdog **command faceplate** summarised below.

## The control pattern

Each controlled unit (VFD-driven pump, decanter, screw loader, fan, silo, control
valve …) exposes three kinds of tag, organised as UNS subtopics under the
equipment leaf:

```
…/wash-pump-01/                         (workUnit — the pump)
    running, fault                      (equipment status)
    cmd/                     (folder)   ← writable command subtopic
        speed-sp-request     RW   the optimizer publishes the optimal value here
    setpoint/                (folder)   ← controller-owned
        speed-sp             R    the committed setpoint the controller actually applies
    vfd/                     (device)   ← the drive
        output-frequency     R    Hz
        output-current       R    A     drive output current
        power                R    kW    (VFD affinity law ∝ speed³)
        dc-bus-voltage       R    V
        drive-temperature    R    °C
        drive-ready/-fault   R
        flow                 R    m³/h  (∝ speed)
        motor-01/            (device)   ← the driven motor M01
            run-state        R    on/off
            shaft-speed      R    RPM   the loop PV (tracks the setpoint)
            voltage-l1/l2/l3 R    V     3-phase
            current-l1/l2/l3 R    A     3-phase (∝ load²)
            winding-temperature, bearing-temperature, power-factor,
            insulation-resistance, run-hours
```

`cmd`/`setpoint` are **tag folders**; `vfd` and `motor-01` are **devices** (the
drive and the motor it drives). Nodes must have unique ids and one of the
supported types (`…/workUnit/device/folder`) or the UNS Designer can't render
them.

Flow of control every simulation tick:

1. The **optimizer** publishes a value to `…/cmd/<var>-sp-request` (a writable
   `qualifier: command` tag).
2. The bridge writes it into the OPC-UA command node (write-back, see below).
3. The **controller** (the simulation engine) reads the request, clamps it to
   `[min, max]`, and ramps the **committed setpoint** `…/setpoint/<var>-sp`
   toward it at a bounded rate (no instantaneous jumps).
4. The **process value** `…/vfd/motor-01/shaft-speed` (or `…/level`, `…/flow`, …)
   tracks the committed setpoint with first-order lag, and the electrical/flow PVs are
   derived from it via VFD affinity laws.
5. The bridge publishes every tag (request, setpoint and all PVs) back out as
   telemetry, so the optimizer can observe the effect of its move.

The controller ramps the setpoint and zeroes the PVs when the equipment's plant
is stopped or in a fault state — so an optimizer only ever moves a *running* unit.

## Subjects / topics

Telemetry subject = the UNS **name path** + tag name (NATS uses `.`, MQTT `/`):

```
RoyalFarmersCollective.FritoMaxx.Heerenveen.production.intake-and-washing.destoner.wash-pump-01.vfd.speed
RoyalFarmersCollective.FritoMaxx.Heerenveen.production.intake-and-washing.destoner.wash-pump-01.setpoint.speed-sp
RoyalFarmersCollective.FritoMaxx.Heerenveen.production.intake-and-washing.destoner.wash-pump-01.cmd.speed-sp-request
```

**Reading (monitoring):** subscribe to the telemetry subjects above (payload is
the standard schema, e.g. `{"value": 1450.0, "ts": …, "unit": "RPM", …}`).

**Writing (commands):** publish to the **command prefix** + the *same subject as
the command tag*. The default command prefix is `cmd` (configurable in
`bridge_config.json` → `command_prefix`):

```
NATS  subject: cmd.RoyalFarmersCollective.FritoMaxx.Heerenveen.production.intake-and-washing.destoner.wash-pump-01.cmd.speed-sp-request
MQTT  topic:   cmd/RoyalFarmersCollective/FritoMaxx/Heerenveen/production/intake-and-washing/destoner/wash-pump-01/cmd/speed-sp-request
payload:       {"value": 1450}      (a bare number or {"value": X} both work)
```

The bridge subscribes to `cmd.>` (NATS) / `cmd/#` (MQTT), maps the subject back
to the OPC command node, coerces the value to the tag's data type, and writes it.
A distinct prefix is used so the bridge never receives its own telemetry
publishes (no feedback loop). Only `qualifier: command` + `access: RW` tags are
writable; anything else is rejected and counted in the bridge error stats.

**Request-reply (NATS).** Publish the same command with `nc.request()` instead of
`nc.publish()` and the bridge returns an immediate ack on the reply inbox:

```json
{"status": "accepted", "written": 1450.0, "readback": 1450.0, "tag": "…speed-sp-request"}
{"status": "rejected", "error": "unknown command tag: …"}
```

`accepted` means the write was delivered, type-valid, and persisted (read back from
OPC). It is a **transport ack**, not the control decision — whether the controller
actually *uses* the value depends on mode / permissive / limits / watchdog, which the
optimizer reads from the loop's `ctrl_status` (`command-status`) telemetry tag. Use
request-reply when you want to act on a timeout; use `ctrl_status` to confirm control
acceptance. (Details: [REALISTIC_CONTROL_ARCHITECTURE.md](REALISTIC_CONTROL_ARCHITECTURE.md).)

## Enabling it

Bridge (`bridge_config.json`):

```json
{
  "protocol": "nats",
  "command_write": true,
  "command_prefix": "cmd"
}
```

`command_write` defaults to `true`; set `false` to disable write-back. The bridge
logs `Command write-back: N command tags mapped` on connect and increments a
`commands` counter in its `[BRIDGE_STATS]` output for every applied setpoint.

## Modelling your own control loops

Two ways:

- **Asset library** — drop a *Control Modules* asset (VFD, VFD-driven pump,
  decanter, screw loader, silo, flow/temperature control loop) onto an equipment
  node in the UNS Designer. Its control tags auto-group into one loop per node.
- **By hand / by tag** — give the tags in a loop these `simulation` blocks. Tags
  with an explicit `"loop": "<id>"` group across sub-nodes (`cmd`, `setpoint`,
  `vfd`); without one they group by their parent node.

| Role | `access` | `qualifier` | `simulation.profile` |
|------|----------|-------------|----------------------|
| optimizer request | `RW` | `command` | `ctrl_request` |
| committed setpoint | `R` | `setpoint` | `ctrl_setpoint` |
| measured PV | `R` | `data` | `ctrl_pv` |
| motor current | `R` | `data` | `ctrl_current` |
| active power | `R` | `data` | `ctrl_power` |
| output frequency | `R` | `data` | `ctrl_frequency` |
| derived flow | `R` | `data` | `ctrl_flow` |
| valve output (analog loops) | `R` | `data` | `ctrl_valve` |
| manual held setpoint | `RW` | `command` | `hold` |

### Command faceplate (realistic PLC-HMI handshake — all optional)

Wire these to make a loop behave like a real remote-setpoint loop: the optimizer's
request is honoured **only** in Remote mode, with the operator permissive on, and while
the heartbeat is fresh — otherwise the loop reverts to the operator's setpoint. See
[REALISTIC_CONTROL_ARCHITECTURE.md](REALISTIC_CONTROL_ARCHITECTURE.md).

| Role | `access` | owner | `simulation.profile` |
|------|----------|-------|----------------------|
| loop mode (0=Local, 1=Remote) | `RW` | operator (HMI) | `ctrl_mode` |
| accept-optimizer permissive | `RW` | operator (HMI) | `ctrl_enable` |
| operator setpoint (fallback) | `RW` | operator (HMI) | `ctrl_sp_operator` |
| EU low / high limit | `RW` | operator (HMI) | `ctrl_sp_lo` / `ctrl_sp_hi` |
| optimizer heartbeat (increment each cycle) | `RW` | optimizer | `ctrl_heartbeat` |
| watchdog OK | `R` | controller | `ctrl_watchdog` |
| command status (Accepted/Clamped/…) | `R` | controller | `ctrl_status` |
| active setpoint source (Optimizer/Operator) | `R` | controller | `ctrl_source` |

`ctrl_request` params gain `hb_timeout` (ticks the heartbeat may stall before "stale").
Give operator-owned tags a sensible `simulation.default` (e.g. `ctrl_mode` → 1,
`ctrl_enable` → true) so the loop is usable out of the box.

### Optical sorter (sensitivity → reject) roles

| Role | `simulation.profile` | meaning |
|------|----------------------|---------|
| sensitivity setpoint request | `ctrl_request` (`kind:"sensitivity"`) | optimizer target |
| reject rate (%) | `ctrl_reject_rate` | rises with sensitivity |
| foreign-material escape (%) | `ctrl_escape` | falls with sensitivity |
| yield (%) | `ctrl_yield` | 100 − reject rate |
| reject mass (t, acc.) | `ctrl_reject_acc` | accumulates when running |
| ejector firings (/s) | `ctrl_ejector` | indicative air-jet rate |

`ctrl_request` params for a sorter: `kind:"sensitivity"`, `infeed_defect` (% defective in
the feed), `rated_throughput` (t/h). Drop the **Optical Sorter** asset for a ready-made
sorter with the full faceplate + reject metrics.

The `ctrl_request` tag carries the loop parameters:

```json
{"profile": "ctrl_request", "loop": "heerenveen-washpump01", "kind": "vfd_speed",
 "min": 600, "max": 1480, "rated": 1480, "ramp": 30,
 "rated_power": 90, "rated_current": 160, "no_load_current": 0.18,
 "rated_flow": 220, "default": 1100}
```

- `min`/`max` — request clamp range · `rated` — PV value mapped to 100 % load /
  50 Hz · `ramp` — max setpoint change per tick · `lag` — PV tracking speed
  (0–1) · `rated_power`/`rated_current`/`rated_flow` — derived-PV scaling ·
  `default` — value the loop holds until the optimizer writes.

## Re-generating the enhanced RFC model

The control-enhanced Royal Farmers Collective model
(`example_UNS_jsons_to_import/Royal_Farmers_Collective_Control_Enhanced.json`)
was produced from a plain RFC export with:

```bash
python tools/enhance_uns_control_loops.py  <rfc_export.json>  <enhanced_out.json>
```

It upgrades every rotating unit (pumps, VFDs, fans) into a full closed loop,
converts drifting valve setpoints into analog position loops, and adds new
energy-intensive equipment (screw loader, decanter, level-controlled silo) to
each production site.

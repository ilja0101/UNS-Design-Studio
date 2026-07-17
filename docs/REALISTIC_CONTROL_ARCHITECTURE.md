# Realistic setpoint control: PLC-HMI vs. pub/sub, and where a setpoint optimizer fits

This note explains how setpoints work in a real PLC-HMI plant, what changes when you
put a **setpoint optimizer agent** on top over **pub/sub (MQTT)** and **request-reply
(NATS)**, and how UNS Design Studio now models that faithfully. It is the design
rationale behind the `ctrl_*` handshake tags and the optical-sorter example.

## 1. How a setpoint works in a classic PLC-HMI solution

A setpoint is a **memory address** in the PLC (a DB register on Siemens, a tag/atom on
Rockwell, a holding register over Modbus). The control loop is a **PID block running in
the PLC scan**; it reads the setpoint register and drives the output. The HMI is a
*client* that **writes that register** (operator types 72 °C → HMI writes the SP atom)
and **reads back** the working SP and PV to display on a faceplate.

Three things make this safe and are easy to forget once you leave the PLC world:

- **Mode.** A loop is in `Manual`, `Auto`, or a **remote/cascade/"computer" (SPC)**
  mode. An *external* setpoint is only used when the loop is in the remote mode; the
  operator can always take it back to a local setpoint. Switching modes is
  **bumpless** — the new mode is pre-loaded from the current state so the process
  doesn't jump ([ISA: bumpless transfer](https://blog.isa.org/what-is-the-definition-of-pid-bumpless-transfer)).
- **Limits & validation.** The PLC clamps the SP to an engineering range and rate-limits
  changes. It **never trusts** an incoming value — the PLC is the last line of defence.
- **Synchronous, acknowledged writes.** An HMI/OPC-UA write to a register returns a
  status immediately (good/bad). The writer *knows* the write landed.

Advanced Process Control (APC) / optimizers have existed in this world for decades, but
they don't command the valve directly — they compute a **target** and write it to a
**remote-setpoint register** that the operator has enabled, or present it as an advisory
the operator accepts ([PiControl: APC in DCS/PLC](https://www.picontrolsolutions.com/blog/adaptive-advanced-control-in-dcs-or-plc/)).

## 2. What changes with pub/sub and request-reply

Moving the optimizer onto a broker changes the **transport**, not the control semantics —
and the transport is now **asynchronous and lossy**, so the semantics you got for free
in the PLC have to be made explicit.

| Concern | PLC-HMI (memory address) | MQTT pub/sub | NATS request-reply |
|---|---|---|---|
| Write delivery | synchronous, acknowledged | fire-and-forget (QoS 0/1), no app-level ack | **request → reply**: immediate ack ([Synadia](https://www.synadia.com/blog/nats-edge-event-architecture-9-the-edge-talks-back), [NATS docs](https://docs.nats.io/nats-concepts/core-nats/reqreply)) |
| Did it get accepted? | read the register back | **observe the confirmed SP on a telemetry topic** (eventual) | reply carries the outcome + read-back value |
| Comms lost | wire fault → alarmed | silent — messages just stop arriving | request **times out** → optimizer knows |
| Who is authoritative | the PLC | still the PLC/edge — the broker is a pipe | the PLC/edge |

Two consequences drive the design:

1. **You need an explicit heartbeat/watchdog.** Because pub/sub delivery is silent, the
   controller must not keep obeying a setpoint from an optimizer that has crashed or been
   partitioned. The standard pattern is a **heartbeat counter the optimizer increments
   every cycle**; if it stops advancing within a timeout the controller **reverts to a
   safe local setpoint** ([SCADA-PLC heartbeat for setpoints](https://industrialmonitordirect.com/blogs/knowledgebase/scada-plc-heartbeat-detecting-setpoint-updates-without-value-change), [watchdog fail-safe](https://www.plowtech.net/plc-watchdog-timers/)).
2. **You need writeback confirmation.** The optimizer must not assume its value was used.
   It reads back the **committed setpoint** and a **command-status** ("Accepted / Clamped /
   Rejected / Stale"). This is exactly the Sparkplug B command-writeback idea — command a
   metric with `DCMD`, then confirm from the reported value ([Sparkplug B](https://pulsemq.com/insights/what-is-sparkplug-b.html)).

## 3. The realistic reference architecture (ISA-95 levels)

```
  L4/L3  Setpoint Optimizer Agent  ── computes optimal targets, keeps a heartbeat
            │  publish request  +  (optional) NATS request→reply
            ▼
  L2.5  Edge / UNS command service (the bridge)
            │  validates prefix, coerces type, writes OPC-UA, replies with outcome
            ▼
  L2    HMI / SCADA  ── operator owns Mode + "Accept optimizer" + local SP + EU limits
            │
  L1/L0  PLC control loop  ── PID in scan; honours remote SP only when
                              Mode=Remote AND Enabled AND watchdog-OK;
                              clamps to limits; else runs the operator SP
```

Key point: the **optimizer never writes the final element**. It writes a *request*; the
**controller decides** whether to honour it based on mode, operator permissive, EU limits
and heartbeat freshness — and always keeps the operator setpoint as the safe fallback.
The HMI stays in charge: the operator flips a single "Accept optimizer" toggle and can
revoke it at any time, exactly like enabling a cascade/remote setpoint.

## 4. How UNS Design Studio models this

Each control loop now exposes a **command faceplate** — the pub/sub equivalent of the
HMI/PLC registers. Tags are grouped as UNS subtopics under the equipment:

```
…/optical-sorter-01/
    sensitivity-actual              ctrl_pv        measured PV (tracks committed SP)
    reject-rate, foreign-material-escape, yield, reject-mass, ejector-firings
    setpoint/  sensitivity-sp       ctrl_setpoint  committed working SP (bumpless, ramped)
    cmd/
        sensitivity-sp-request      ctrl_request     ← optimizer target
        loop-mode                   ctrl_mode        ← operator: 0=Local, 1=Remote
        accept-optimizer            ctrl_enable      ← operator permissive
        operator-sensitivity-sp     ctrl_sp_operator ← operator fallback SP
        sensitivity-lo/hi-limit     ctrl_sp_lo/hi    ← operator EU limits
        optimizer-heartbeat         ctrl_heartbeat   ← optimizer increments every cycle
    watchdog-ok       ctrl_watchdog   controller: heartbeat fresh?
    command-status    ctrl_status     Accepted / Clamped / Local(HMI) / OptimizerDisabled / StaleWatchdog
    setpoint-source   ctrl_source     Optimizer / Operator
```

The controller (the sim engine) each tick: reads the request + faceplate inputs, checks
`Mode==Remote AND Enabled AND watchdog-OK`, clamps to the operator limits, ramps the
committed SP bumplessly toward the chosen target, and publishes `command-status` /
`setpoint-source` so the optimizer (and the HMI) can see what actually happened. If the
heartbeat goes stale it reverts to the operator SP — verified end-to-end.

### The optimizer's real loop

1. **Enable** (once, operator action on the HMI): set `loop-mode=1`, `accept-optimizer=true`.
2. **Every cycle**: publish the new target to `…/cmd/…-sp-request` **and** bump
   `…/cmd/optimizer-heartbeat`.
3. **Confirm**: read `command-status` (Accepted/Clamped/…) and the committed setpoint —
   over pub/sub this is the telemetry topic; over NATS the `request()` reply carries an
   immediate transport ack + read-back value.
4. **On its own failure**: stop; the watchdog reverts the loop to the operator SP.

### Two-tier confirmation (why both transports)

- **NATS request-reply** gives the optimizer an *immediate transport ack* — "your write was
  delivered, syntactically valid, and here's the value I read back" — the closest thing to
  the old synchronous PLC write. Use it when you want to act on a timeout.
- **The `command-status` telemetry tag** gives the *control decision* — Accepted / Clamped /
  Rejected(mode/permissive) / Stale — because that decision belongs to the controller and
  can change tick-to-tick (e.g. the operator revokes the permissive). Even with a positive
  request-reply ack, the optimizer must watch `command-status`.

## 5. Worked example — the optical sorter

An optical sorter (TOMRA/Key-style: NIR/laser inspection + high-speed air-jet ejectors)
is a clean optimization target ([TOMRA 3A](https://www.tomra.com/food/machines/tomra-3a),
[Key Optyx](https://www.fruitandveggie.com/key-technology-optical-sorting-system-2778/)).
Its **detection sensitivity** trades two costs:

- **higher sensitivity → higher reject rate** (more good product ejected = **yield loss**),
  but **lower foreign-material escape** (safer product);
- **lower sensitivity → less yield loss**, but more foreign material passes.

The optimizer's job: hold escape below a food-safety limit while **minimising reject
rate** (maximising yield), reacting to the live `infeed-defect-rate`. In the model,
sensitivity 30 % → 90 % moves reject ≈ 6 % → 18 % and escape ≈ 3.3 % → 0.4 % — a real
economic trade-off the agent can optimise, through the full faceplate above (so the
operator stays in control and comms loss is safe).

## References

- ISA — bumpless transfer: https://blog.isa.org/what-is-the-definition-of-pid-bumpless-transfer
- PiControl — APC in DCS/PLC: https://www.picontrolsolutions.com/blog/adaptive-advanced-control-in-dcs-or-plc/
- Industrial Monitor Direct — SCADA-PLC heartbeat for setpoints: https://industrialmonitordirect.com/blogs/knowledgebase/scada-plc-heartbeat-detecting-setpoint-updates-without-value-change
- Plow Technologies — PLC watchdog timers / fail-safe: https://www.plowtech.net/plc-watchdog-timers/
- Sparkplug B (DCMD command / writeback): https://pulsemq.com/insights/what-is-sparkplug-b.html
- Synadia — the edge talks back (request-reply for control): https://www.synadia.com/blog/nats-edge-event-architecture-9-the-edge-talks-back
- NATS docs — request-reply: https://docs.nats.io/nats-concepts/core-nats/reqreply
- TOMRA 3A optical sorter: https://www.tomra.com/food/machines/tomra-3a
- Key Technology Optyx: https://www.fruitandveggie.com/key-technology-optical-sorting-system-2778/

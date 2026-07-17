#!/usr/bin/env python3
"""Enhance the Royal Farmers Collective UNS with per-equipment closed control
loops (request -> controller -> setpoint -> PV) so an Industrial-AI optimizer can
read monitoring tags and publish setpoint requests.

Topology added per controlled unit (child nodes, so they become UNS subtopics):
    <equipment>/
        cmd/       <var>-sp-request   (RW, qualifier=command, profile=ctrl_request)
        setpoint/  <var>-sp           (R,  qualifier=setpoint, profile=ctrl_setpoint)
        vfd/       speed, motor-current, power, output-frequency, flow (ctrl_* PVs)

Valve units are converted in place to analog position loops (auto-grouped).
"""
import json, sys, copy, re

USAGE = "Usage: python tools/enhance_uns_control_loops.py <input_uns.json> <output_uns.json>"
if len(sys.argv) != 3:
    sys.exit(USAGE)

SRC = sys.argv[1]
OUT = sys.argv[2]

cfg = json.load(open(SRC, encoding="utf-8"))

def pascal(name):
    return "".join(p[:1].upper() + p[1:] for p in str(name).replace("_", "-").split("-"))

def walk(n):
    yield n
    for c in n.get("children", []):
        yield from walk(c)

def first_opcpath(node):
    """Return an opcPath from any tag on this node (or its descendants)."""
    for nn in walk(node):
        for t in nn.get("tags", []):
            if "opcPath" in t:
                return t["opcPath"]
    return None

def site_of(path_names):
    # path_names is the |-name path; site is index 2 (Enterprise|BU|Site|...)
    return path_names[2] if len(path_names) > 2 else "site"

# ── parameter presets by equipment kind ───────────────────────────────────────
def speed_params(name):
    n = name.lower()
    if "fan" in n or "blower" in n:
        return dict(kind="vfd_speed", min=300, max=1500, rated=1500, ramp=25,
                    rated_power=75, rated_current=130, no_load_current=0.20,
                    rated_flow=45000, flow_unit="m³/h", default=1100, pv_unit="RPM")
    if "feedwater" in n or "boiler" in n:
        return dict(kind="vfd_speed", min=800, max=2950, rated=2950, ramp=45,
                    rated_power=55, rated_current=95, no_load_current=0.18,
                    rated_flow=60, flow_unit="m³/h", default=2200, pv_unit="RPM")
    if "oil" in n:
        return dict(kind="vfd_speed", min=500, max=1480, rated=1480, ramp=25,
                    rated_power=45, rated_current=80, no_load_current=0.18,
                    rated_flow=140, flow_unit="m³/h", default=1050, pv_unit="RPM")
    # default centrifugal process pump
    return dict(kind="vfd_speed", min=600, max=1480, rated=1480, ramp=30,
                rated_power=90, rated_current=160, no_load_current=0.18,
                rated_flow=220, flow_unit="m³/h", default=1100, pv_unit="RPM")

def make_child(name, ntype="workUnit", desc="", tags=None):
    return {"id": None, "name": name, "type": ntype, "description": desc,
            "children": [], "tags": tags or []}

def ctag(name, dtype, unit, access, qualifier, profile, opcpath, desc, extra=None):
    sim = {"profile": profile}
    if extra:
        sim.update(extra)
    return {"name": name, "dataType": dtype, "unit": unit, "access": access,
            "qualifier": qualifier, "opcPath": opcpath, "payloadSchema": "standard",
            "simulation": sim, "description": desc}

def _nominal(base, lo, hi, std, default=None):
    """Simulation block for a nominal analog value that jitters around `base`."""
    return {"base": base, "min": lo, "max": hi, "std": std, "default": default if default is not None else base}

def build_motor(vfd_base, loop_id, p, name="motor-01"):
    """Electric motor (M01) as a device under the VFD. The loop's process value
    (shaft speed) lives here; the drive keeps its drive-side telemetry. Three-phase
    voltages/currents + winding/bearing thermals are realistic per-motor tags."""
    mb = vfd_base + "/Motor01"
    pv_unit = p.get("pv_unit", "RPM")
    return make_child(name, "device",
                      desc="Electric motor M01 driven by the VFD — 3-phase electricals + thermals.",
                      tags=[
        ctag("run-state", "Bool", "", "R", "data", "boolean_running", mb + "/RunState", "M01 running (on/off)."),
        ctag("fault", "Bool", "", "R", "data", "boolean_fault", mb + "/Fault", "M01 fault / trip."),
        ctag("shaft-speed", "Float", pv_unit, "R", "data", "ctrl_pv", mb + "/ShaftSpeed",
             "SI — motor shaft speed (tracks the committed setpoint).", {"loop": loop_id}),
        ctag("voltage-l1", "Float", "V", "R", "data", "default", mb + "/VoltageL1", "EI — phase L1 voltage.", _nominal(400, 390, 410, 1.5)),
        ctag("voltage-l2", "Float", "V", "R", "data", "default", mb + "/VoltageL2", "EI — phase L2 voltage.", _nominal(400, 390, 410, 1.5)),
        ctag("voltage-l3", "Float", "V", "R", "data", "default", mb + "/VoltageL3", "EI — phase L3 voltage.", _nominal(400, 390, 410, 1.5)),
        ctag("current-l1", "Float", "A", "R", "data", "ctrl_current", mb + "/CurrentL1", "II — phase L1 current (∝ load²).", {"loop": loop_id}),
        ctag("current-l2", "Float", "A", "R", "data", "ctrl_current", mb + "/CurrentL2", "II — phase L2 current (∝ load²).", {"loop": loop_id}),
        ctag("current-l3", "Float", "A", "R", "data", "ctrl_current", mb + "/CurrentL3", "II — phase L3 current (∝ load²).", {"loop": loop_id}),
        ctag("winding-temperature", "Float", "°C", "R", "data", "default", mb + "/WindingTemperature", "TI — stator winding temperature.", _nominal(68, 35, 145, 1.5)),
        ctag("bearing-temperature", "Float", "°C", "R", "data", "default", mb + "/BearingTemperature", "TI — bearing temperature.", _nominal(52, 25, 110, 1.0)),
        ctag("power-factor", "Float", "", "R", "data", "default", mb + "/PowerFactor", "JI — power factor.", _nominal(0.86, 0.72, 0.97, 0.01)),
        ctag("insulation-resistance", "Float", "MΩ", "R", "data", "default", mb + "/InsulationResistance", "EI — winding insulation resistance.", _nominal(480, 50, 800, 8)),
        ctag("run-hours", "Float", "h", "R", "data", "accumulator_generic", mb + "/RunHours", "Cumulative run hours."),
    ])

def vfd_drive_tags(vfd_base, loop_id, p, flow_name=None, flow_unit=None):
    """Drive-side telemetry for a VFD device (the motor's PV lives on the motor)."""
    tags = [
        ctag("output-frequency", "Float", "Hz", "R", "data", "ctrl_frequency", vfd_base + "/OutputFrequency", "SI — drive output frequency.", {"loop": loop_id}),
        ctag("output-current", "Float", "A", "R", "data", "ctrl_current", vfd_base + "/OutputCurrent", "II — drive output current.", {"loop": loop_id}),
        ctag("power", "Float", "kW", "R", "data", "ctrl_power", vfd_base + "/Power", "JI — active power (VFD affinity law ∝ speed³).", {"loop": loop_id}),
        ctag("dc-bus-voltage", "Float", "V", "R", "data", "default", vfd_base + "/DcBusVoltage", "EI — DC-bus voltage.", _nominal(650, 560, 720, 3)),
        ctag("drive-temperature", "Float", "°C", "R", "data", "default", vfd_base + "/DriveTemperature", "TI — drive heatsink temperature.", _nominal(46, 25, 90, 1.5)),
        ctag("drive-ready", "Bool", "", "R", "data", "boolean_running", vfd_base + "/DriveReady", "Drive ready / run confirm."),
        ctag("drive-fault", "Bool", "", "R", "data", "boolean_fault", vfd_base + "/DriveFault", "Drive trip / fault."),
    ]
    if flow_name and p.get("rated_flow"):
        tags.append(ctag(flow_name, "Float", flow_unit or p.get("flow_unit", "m³/h"), "R", "data", "ctrl_flow",
                         vfd_base + "/" + pascal(flow_name), "FI/WI — delivered flow (tracks speed).", {"loop": loop_id}))
    return tags

stats = {"speed_loops": 0, "valve_loops": 0, "new_equipment": 0}

def upgrade_speed_unit(unit, loop_id, base_opc):
    """Add cmd/setpoint/vfd children forming a closed speed loop. base_opc is the
    equipment's opcPath prefix (…/WashPump01). Existing speed/motor-current tags
    on the unit are removed (re-created as loop PVs under vfd/)."""
    p = speed_params(unit.get("name", ""))
    # drop monitoring tags we will re-provide as loop PVs
    unit["tags"] = [t for t in unit.get("tags", [])
                    if t.get("name") not in ("speed", "motor-current", "power", "output-frequency")]
    cmd = make_child("cmd", desc="Command subtopic — optimizer setpoint requests (writable).")
    sp  = make_child("setpoint", desc="Committed setpoints published by the controller.")
    vfd = make_child("vfd", "device", desc="VFD drive — output frequency/current, power, DC-bus, drive thermals.")
    cmd["tags"] = [ctag("speed-sp-request", "Float", p["pv_unit"], "RW", "command",
                        "ctrl_request", base_opc + "/Cmd/SpeedSpRequest",
                        "SIC — motor speed request (optimizer publishes optimal RPM here).",
                        {"loop": loop_id, "kind": p["kind"], "min": p["min"], "max": p["max"],
                         "rated": p["rated"], "ramp": p["ramp"], "rated_power": p["rated_power"],
                         "rated_current": p["rated_current"], "no_load_current": p["no_load_current"],
                         "rated_flow": p["rated_flow"], "default": p["default"]})]
    sp["tags"]  = [ctag("speed-sp", "Float", p["pv_unit"], "R", "setpoint",
                        "ctrl_setpoint", base_opc + "/Setpoint/SpeedSp",
                        "SIC — committed speed setpoint (controller output).", {"loop": loop_id})]
    vfd["tags"] = vfd_drive_tags(base_opc + "/Vfd", loop_id, p, flow_name="flow")
    vfd["children"] = [build_motor(base_opc + "/Vfd", loop_id, p)]
    unit.setdefault("children", []).extend([cmd, sp, vfd])
    stats["speed_loops"] += 1

def upgrade_vfd_unit(unit, loop_id, base_opc):
    """A *-vfd-* unit already carries current/power/frequency; retag them to the
    loop and add cmd/setpoint + a measured speed PV."""
    p = speed_params(unit.get("name", ""))
    retag = {"motor-current": ("ctrl_current", "A"),
             "power": ("ctrl_power", "kW"),
             "output-frequency": ("ctrl_frequency", "Hz")}
    for t in unit.get("tags", []):
        if t.get("name") in retag:
            prof, _u = retag[t["name"]]
            t.setdefault("simulation", {})["profile"] = prof
            t["simulation"]["loop"] = loop_id
    cmd = make_child("cmd", desc="Command subtopic — optimizer setpoint requests (writable).")
    sp  = make_child("setpoint", desc="Committed setpoints published by the controller.")
    cmd["tags"] = [ctag("speed-sp-request", "Float", "RPM", "RW", "command",
                        "ctrl_request", base_opc + "/Cmd/SpeedSpRequest",
                        "SIC — drive speed request (optimizer publishes optimal RPM here).",
                        {"loop": loop_id, "kind": p["kind"], "min": p["min"], "max": p["max"],
                         "rated": p["rated"], "ramp": p["ramp"], "rated_power": p["rated_power"],
                         "rated_current": p["rated_current"], "no_load_current": p["no_load_current"],
                         "rated_flow": p["rated_flow"], "default": p["default"]})]
    sp["tags"]  = [ctag("speed-sp", "Float", "RPM", "R", "setpoint",
                        "ctrl_setpoint", base_opc + "/Setpoint/SpeedSp",
                        "SIC — committed speed setpoint (controller output).", {"loop": loop_id})]
    # The unit is the drive; the motor (with the shaft-speed PV) hangs beneath it.
    motor = build_motor(base_opc, loop_id, p)
    unit.setdefault("children", []).extend([cmd, sp, motor])
    stats["speed_loops"] += 1

def upgrade_valve_unit(unit):
    """Convert a position/setpoint valve into an analog position loop in place.
    The existing RW 'setpoint' becomes the optimizer request; 'position' tracks."""
    tags = {t.get("name"): t for t in unit.get("tags", [])}
    ok = False
    if "setpoint" in tags and "position" in tags:
        spt = tags["setpoint"]
        spt["access"] = "RW"
        spt["qualifier"] = "command"
        spt["simulation"] = {"profile": "ctrl_request", "kind": "flow",
                             "min": 0, "max": 100, "rated": 100, "ramp": 8,
                             "lag": 0.25, "default": 60}
        spt["description"] = "ZC — valve position request (optimizer writes % open)."
        pos = tags["position"]
        pos.setdefault("simulation", {})
        pos["simulation"] = {"profile": "ctrl_pv"}
        pos["description"] = "ZI — measured valve position (tracks request)."
        ok = True
    if ok:
        stats["valve_loops"] += 1

def add_new_equipment(wc, path_names):
    """Add a screw loader, decanter and level-controlled silo under a production
    workCenter, wired as closed loops. opcPath is derived from the workCenter."""
    op = first_opcpath(wc)
    if not op:
        return
    wc_prefix = "/".join(op.split("/")[:4])   # BU/Site/Area/WorkCenter
    site = site_of(path_names)
    added = []

    # ── Screw loader / feeder (VFD speed → mass flow) ──
    lid = f"{site}-screwloader01".lower()
    base = wc_prefix + "/ScrewLoader01"
    sl = make_child("screw-loader-01", desc="Screw loader / feeder on a VFD — sets line mass throughput.")
    sl["tags"] = [
        ctag("running", "Bool", "", "R", "data", "boolean_running", base + "/Running", "Screw running."),
        ctag("fault", "Bool", "", "R", "data", "boolean_fault", base + "/Fault", "Jam / overload trip."),
    ]
    slc = make_child("cmd", desc="Command subtopic — optimizer setpoint requests (writable).")
    sls = make_child("setpoint", desc="Committed setpoints published by the controller.")
    slv = make_child("vfd", "device", desc="VFD drive — output frequency/current, power, mass flow.")
    slp = {"pv_unit": "RPM", "rated_current": 45, "rated_flow": 18, "flow_unit": "t/h"}
    slc["tags"] = [ctag("speed-sp-request", "Float", "RPM", "RW", "command", "ctrl_request",
                        base + "/Cmd/SpeedSpRequest", "SIC — screw speed request (optimizer writes RPM).",
                        {"loop": lid, "kind": "vfd_speed", "min": 10, "max": 120, "rated": 120,
                         "ramp": 4, "rated_power": 22, "rated_current": 45, "no_load_current": 0.25,
                         "rated_flow": 18, "default": 80})]
    sls["tags"] = [ctag("speed-sp", "Float", "RPM", "R", "setpoint", "ctrl_setpoint",
                        base + "/Setpoint/SpeedSp", "SIC — committed screw speed.", {"loop": lid})]
    slv["tags"] = vfd_drive_tags(base + "/Vfd", lid, slp, flow_name="mass-flow", flow_unit="t/h")
    slv["children"] = [build_motor(base + "/Vfd", lid, slp)]
    sl["children"] = [slc, sls, slv]
    added.append(sl)

    # ── Decanter centrifuge (bowl-speed VFD, energy intensive) ──
    lid = f"{site}-decanter01".lower()
    base = wc_prefix + "/Decanter01"
    dc = make_child("decanter-01", desc="Solid-bowl decanter centrifuge on a main-drive VFD — energy intensive.")
    dc["tags"] = [
        ctag("running", "Bool", "", "R", "data", "boolean_running", base + "/Running", "Decanter running."),
        ctag("fault", "Bool", "", "R", "data", "boolean_fault", base + "/Fault", "Drive / vibration trip."),
        ctag("scroll-torque", "Float", "%", "R", "data", "valve_position", base + "/ScrollTorque", "Differential scroll torque."),
        ctag("feed-flow", "Float", "m³/h", "R", "data", "flow_rate", base + "/FeedFlow", "FI — feed flow."),
        ctag("cake-dryness", "Float", "%", "R", "quality", "quality_metric_cont", base + "/CakeDryness", "AI — cake dry-solids."),
        ctag("vibration", "Float", "mm/s", "R", "data", "vibration", base + "/Vibration", "VI — bowl vibration."),
    ]
    dcc = make_child("cmd", desc="Command subtopic — optimizer setpoint requests (writable).")
    dcs = make_child("setpoint", desc="Committed setpoints published by the controller.")
    dcv = make_child("vfd", "device", desc="Main-drive VFD — output frequency/current, power.")
    dcp = {"pv_unit": "RPM", "rated_current": 230, "rated_flow": 0}
    dcc["tags"] = [ctag("bowl-speed-sp-request", "Float", "RPM", "RW", "command", "ctrl_request",
                        base + "/Cmd/BowlSpeedSpRequest", "SIC — bowl speed request (optimizer writes RPM).",
                        {"loop": lid, "kind": "vfd_speed", "min": 1500, "max": 3600, "rated": 3600,
                         "ramp": 25, "rated_power": 132, "rated_current": 230, "no_load_current": 0.22,
                         "rated_flow": 0, "default": 3000})]
    dcs["tags"] = [ctag("bowl-speed-sp", "Float", "RPM", "R", "setpoint", "ctrl_setpoint",
                        base + "/Setpoint/BowlSpeedSp", "SIC — committed bowl speed.", {"loop": lid})]
    dcv["tags"] = vfd_drive_tags(base + "/Vfd", lid, dcp)
    dcv["children"] = [build_motor(base + "/Vfd", lid, dcp)]  # motor shaft-speed = bowl speed (direct drive)
    dc["children"] = [dcc, dcs, dcv]
    added.append(dc)

    # ── Level-controlled intake silo (LIC) ──
    lid = f"{site}-intakesilo01".lower()
    base = wc_prefix + "/IntakeSilo01"
    si = make_child("intake-silo-01", desc="Buffer silo with a level control loop on the outfeed.")
    si["tags"] = [
        ctag("weight-tons", "Float", "t", "R", "data", "silo_level", base + "/WeightTons", "WI — silo load cells."),
        ctag("high-level-switch", "Bool", "", "R", "data", "boolean_alarm", base + "/HighLevelSwitch", "LSH — high level switch."),
        ctag("low-level-switch", "Bool", "", "R", "data", "boolean_fault", base + "/LowLevelSwitch", "LSL — low level switch."),
        ctag("level", "Float", "%", "R", "data", "ctrl_pv", base + "/Level", "LI/LT — measured level (tracks setpoint).", {"loop": lid}),
        ctag("outfeed-valve-output", "Float", "%", "R", "data", "ctrl_valve", base + "/OutfeedValveOutput", "LV — controller output to outfeed.", {"loop": lid}),
    ]
    sic = make_child("cmd", desc="Command subtopic — optimizer setpoint requests (writable).")
    sis = make_child("setpoint", desc="Committed setpoints published by the controller.")
    sic["tags"] = [ctag("level-sp-request", "Float", "%", "RW", "command", "ctrl_request",
                        base + "/Cmd/LevelSpRequest", "LIC — target level request (optimizer writes % level).",
                        {"loop": lid, "kind": "level", "min": 20, "max": 95, "rated": 100,
                         "ramp": 0.6, "lag": 0.05, "default": 70})]
    sis["tags"] = [ctag("level-sp", "Float", "%", "R", "setpoint", "ctrl_setpoint",
                        base + "/Setpoint/LevelSp", "LIC — committed level setpoint.", {"loop": lid})]
    si["children"] = [sic, sis]
    added.append(si)

    # ── Optical sorter with the realistic PLC-HMI faceplate + reject metrics ──
    # Flat under the sorter node so the sensitivity loop + faceplate + reject
    # outputs auto-group into one control loop by parent.
    lid = f"{site}-opticalsorter01".lower()
    base = wc_prefix + "/OpticalSorter01"
    so = make_child("optical-sorter-01",
                    desc="NIR/laser optical sorter with air-jet ejectors. Optimizer tunes detection sensitivity (reject rate vs. foreign-material escape) through the full command faceplate.")
    so["tags"] = [
        ctag("running", "Bool", "", "R", "data", "boolean_running", base + "/Running", "Sorter running."),
        ctag("fault", "Bool", "", "R", "data", "boolean_fault", base + "/Fault", "Sorter fault."),
        ctag("throughput", "Float", "t/h", "R", "data", "flow_rate", base + "/Throughput", "WI — infeed throughput."),
        ctag("infeed-defect-rate", "Float", "%", "R", "quality", "quality_metric_cont", base + "/InfeedDefectRate", "AI — infeed defect / foreign-material load."),
        ctag("ejector-air-pressure", "Float", "bar", "R", "data", "pressure", base + "/EjectorAirPressure", "PI — ejector air-manifold pressure."),
        # sensitivity control loop
        ctag("sensitivity-sp-request", "Float", "%", "RW", "command", "ctrl_request",
             base + "/Cmd/SensitivitySpRequest", "AIC — detection sensitivity request (optimizer writes optimal %).",
             {"loop": lid, "kind": "sensitivity", "min": 20, "max": 95, "rated": 100, "ramp": 4, "lag": 0.2,
              "infeed_defect": 8, "rated_throughput": 12, "hb_timeout": 5, "default": 60}),
        ctag("sensitivity-sp", "Float", "%", "R", "setpoint", "ctrl_setpoint", base + "/Setpoint/SensitivitySp", "AIC — committed sensitivity setpoint.", {"loop": lid}),
        ctag("sensitivity-actual", "Float", "%", "R", "data", "ctrl_pv", base + "/SensitivityActual", "AI — measured sensitivity (tracks setpoint).", {"loop": lid}),
        # PLC-HMI command faceplate
        ctag("loop-mode", "Int", "", "RW", "command", "ctrl_mode", base + "/Cmd/LoopMode", "Operator mode: 0=Local (HMI), 1=Remote (optimizer).", {"loop": lid, "default": 1}),
        ctag("accept-optimizer", "Bool", "", "RW", "command", "ctrl_enable", base + "/Cmd/AcceptOptimizer", "Operator permissive — accept optimizer setpoints.", {"loop": lid, "default": True}),
        ctag("operator-sensitivity-sp", "Float", "%", "RW", "command", "ctrl_sp_operator", base + "/Cmd/OperatorSensitivitySp", "Operator/local sensitivity setpoint (safe fallback).", {"loop": lid, "default": 55}),
        ctag("sensitivity-lo-limit", "Float", "%", "RW", "command", "ctrl_sp_lo", base + "/Cmd/SensitivityLoLimit", "Operator EU low limit.", {"loop": lid, "default": 25}),
        ctag("sensitivity-hi-limit", "Float", "%", "RW", "command", "ctrl_sp_hi", base + "/Cmd/SensitivityHiLimit", "Operator EU high limit.", {"loop": lid, "default": 90}),
        ctag("optimizer-heartbeat", "Int", "", "RW", "command", "ctrl_heartbeat", base + "/Cmd/OptimizerHeartbeat", "Optimizer heartbeat — increment each cycle to keep the watchdog alive.", {"loop": lid, "default": 0}),
        # faceplate writeback outputs
        ctag("watchdog-ok", "Bool", "", "R", "data", "ctrl_watchdog", base + "/WatchdogOk", "Heartbeat fresh — optimizer setpoint trusted.", {"loop": lid}),
        ctag("command-status", "String", "", "R", "data", "ctrl_status", base + "/CommandStatus", "Writeback: Accepted/Clamped/Local(HMI)/OptimizerDisabled/StaleWatchdog.", {"loop": lid}),
        ctag("setpoint-source", "String", "", "R", "data", "ctrl_source", base + "/SetpointSource", "Active setpoint source: Optimizer/Operator.", {"loop": lid}),
        # reject metrics
        ctag("reject-rate", "Float", "%", "R", "quality", "ctrl_reject_rate", base + "/RejectRate", "Fraction of stream ejected (rises with sensitivity).", {"loop": lid}),
        ctag("foreign-material-escape", "Float", "%", "R", "quality", "ctrl_escape", base + "/ForeignMaterialEscape", "Foreign material passing to accept (falls with sensitivity).", {"loop": lid}),
        ctag("yield", "Float", "%", "R", "quality", "ctrl_yield", base + "/Yield", "Accept yield = 100 − reject rate.", {"loop": lid}),
        ctag("reject-mass", "Float", "t", "R", "data", "ctrl_reject_acc", base + "/RejectMass", "Accumulated ejected/reject mass.", {"loop": lid}),
        ctag("ejector-firings", "Float", "1/s", "R", "data", "ctrl_ejector", base + "/EjectorFirings", "Air-jet ejector firing rate.", {"loop": lid}),
    ]
    added.append(so)

    wc.setdefault("children", []).extend(added)
    stats["new_equipment"] += len(added)
    stats["optical_sorters"] = stats.get("optical_sorters", 0) + 1

# ── main walk ──────────────────────────────────────────────────────────────────
def visit(node, path_names):
    names = path_names + [node.get("name", "")]
    ntype = node.get("type", "")
    nm = node.get("name", "")

    # Snapshot children BEFORE upgrading — so we never re-visit the cmd/setpoint/
    # vfd sub-nodes we are about to add (which would otherwise be mis-detected as
    # their own VFD units).
    orig_children = list(node.get("children", []))

    if ntype == "workUnit":
        tagnames = {t.get("name") for t in node.get("tags", [])}
        op = first_opcpath(node)
        base = op.rsplit("/", 1)[0] if op else None
        site = site_of(names)
        slug = f"{site}-{pascal(nm)}".lower()
        is_vfd = ("output-frequency" in tagnames and "power" in tagnames) or nm.endswith("-vfd") or "-vfd-" in nm
        is_speed = "speed" in tagnames
        is_valve = "position" in tagnames and "setpoint" in tagnames
        if base and is_vfd:
            upgrade_vfd_unit(node, slug, base)
        elif base and is_speed:
            upgrade_speed_unit(node, slug, base)
        elif is_valve:
            upgrade_valve_unit(node)

    for c in orig_children:
        visit(c, names)

# process cells to receive new equipment: first production workCenter per site
def first_production_wc(site):
    for area in site.get("children", []):
        if area.get("type") == "area" and area.get("name") == "production":
            for wc in area.get("children", []):
                if wc.get("type") == "workCenter":
                    return wc
    return None

# 1) upgrade existing units
visit(cfg["tree"], [])

# 2) add new equipment per production site
for node in walk(cfg["tree"]):
    if node.get("type") == "site":
        # site path names for slug: Enterprise|BU|Site
        pass
# need site path; re-walk with paths
def add_equipment_walk(node, path_names):
    names = path_names + [node.get("name", "")]
    if node.get("type") == "site" and node.get("name") != "Veghel-HQ":
        wc = first_production_wc(node)
        if wc is not None:
            add_new_equipment(wc, names)
    for c in node.get("children", []):
        add_equipment_walk(c, names)
add_equipment_walk(cfg["tree"], [])

# ── Post-pass 1: node semantics ────────────────────────────────────────────────
# The UNS Designer requires a real id on every node and tag (used as React keys /
# selection lookup) and renders each node by its type. Set the correct types for
# the generated sub-nodes: a VFD is a *control module* (device with tags), while
# cmd/setpoint are *tag folders* (organisational groupings, not devices).
def fix_node_types(node):
    for c in node.get("children", []):
        nm = c.get("name")
        if nm == "vfd":
            c["type"] = "device"
        elif nm in ("cmd", "setpoint"):
            c["type"] = "folder"
        fix_node_types(c)
fix_node_types(cfg["tree"])

# ── Post-pass 2: fill missing ids (nodes + tags), guaranteeing uniqueness ───────
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "x"

_seen = set()
def _unique(base):
    cand, i = base, 1
    while cand in _seen:
        i += 1
        cand = f"{base}-{i}"
    _seen.add(cand)
    return cand

def ensure_ids(node, path):
    if node.get("id"):
        _seen.add(node["id"])
    for t in node.get("tags", []):
        if t.get("id"):
            _seen.add(t["id"])
for _n in walk(cfg["tree"]):        # first register all existing ids
    ensure_ids(_n, "")

def assign_ids(node, path):
    npath = f"{path}-{node.get('name','')}" if path else node.get("name", "")
    if not node.get("id"):
        node["id"] = _unique("nd-" + _slug(npath))
    for t in node.get("tags", []):
        if not t.get("id"):
            src = t.get("opcPath") or f"{npath}-{t.get('name','')}"
            t["id"] = _unique("tg-" + _slug(src))
    for c in node.get("children", []):
        assign_ids(c, npath)
assign_ids(cfg["tree"], "")

cfg["description"] = (cfg.get("description", "") +
    " | Control-enhanced: per-equipment closed loops (request→controller→setpoint→PV) "
    "with cmd/setpoint tag folders + VFD control modules for Industrial-AI setpoint optimization.")

json.dump(cfg, open(OUT, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
n_nodes = sum(1 for _ in walk(cfg["tree"]))
print("stats:", stats, "| nodes:", n_nodes)

"""Closed-loop control: ControlLoop dynamics, loop grouping, command entries,
and the bridge command-payload helpers."""
import factory
import uns_tree
import bridge


# ── ControlLoop dynamics ───────────────────────────────────────────────────────

def _pump_loop():
    loop = factory.ControlLoop("t")
    loop.configure({"min": 600, "max": 1480, "rated": 1480, "ramp": 30,
                    "rated_power": 90, "rated_current": 160, "rated_flow": 220,
                    "default": 1100})
    return loop


def test_setpoint_ramps_toward_request_at_bounded_rate():
    loop = _pump_loop()
    loop.tick(None, True)            # seed at default
    assert abs(loop.sp - 1100) < 1e-6
    loop.tick(1480, True)            # request max
    # committed setpoint moves by at most `ramp` per tick, not instantly
    assert 1100 < loop.sp <= 1100 + 30 + 1e-6


def test_request_is_clamped_to_limits():
    loop = _pump_loop()
    for _ in range(200):
        loop.tick(9999, True)        # way above max
    assert loop.sp <= 1480 + 1e-6
    assert loop.pv <= 1480 * 1.08


def test_pv_and_derived_track_setpoint_and_scale():
    loop = _pump_loop()
    for _ in range(120):
        loop.tick(1480, True)
    # PV converges near rated, derived electricals near their rated values
    assert loop.pv > 1400
    assert loop.output("ctrl_power") > 80          # ~rated 90 kW
    assert loop.output("ctrl_current") > 130       # ~rated 160 A
    assert 45 <= loop.output("ctrl_frequency") <= 55
    assert loop.output("ctrl_flow") > 190          # ~rated 220 m³/h


def test_power_follows_cube_law_below_rated():
    loop = _pump_loop()
    for _ in range(200):
        loop.tick(740, True)         # 50% of rated speed
    # affinity law: power at half speed is a small fraction of rated
    assert loop.output("ctrl_power") < 90 * 0.25


def test_pv_coasts_down_when_not_running():
    loop = _pump_loop()
    for _ in range(60):
        loop.tick(1480, True)
    assert loop.pv > 1000
    for _ in range(30):
        loop.tick(None, False)       # plant stopped/faulted
    assert loop.pv < 50
    assert loop.output("ctrl_power") < 5


# ── Loop grouping (explicit id vs auto-by-parent) ──────────────────────────────

def _sim(profile, **extra):
    d = {"profile": profile}
    d.update(extra)
    return d


def test_build_control_loops_auto_groups_flat_tags_by_parent():
    # Two pumps, flat control tags, no explicit loop id -> two independent loops.
    variables = {}
    for pump in ("PumpA", "PumpB"):
        variables[(pump, "SpeedSetpointRequest")] = (
            object(), _sim("ctrl_request", min=600, max=1480, rated=1480,
                           rated_power=90, rated_current=160, default=1100), "BU|Site", 0.0, None)
        variables[(pump, "Speed")] = (object(), _sim("ctrl_pv"), "BU|Site", 0.0, None)
        variables[(pump, "Power")] = (object(), _sim("ctrl_power"), "BU|Site", 0.0, None)
    loops = factory._build_control_loops(variables)
    assert set(loops) == {"@PumpA", "@PumpB"}
    for loop in loops.values():
        assert loop.request_var is not None
        assert loop.rated_power == 90


def test_explicit_loop_id_groups_tags_across_subnodes():
    variables = {
        ("Pump", "cmd", "SpeedSpRequest"): (object(), _sim("ctrl_request", loop="L1", min=0, max=1500), "BU|Site", 0.0, None),
        ("Pump", "setpoint", "SpeedSp"):   (object(), _sim("ctrl_setpoint", loop="L1"), "BU|Site", 0.0, None),
        ("Pump", "vfd", "Speed"):          (object(), _sim("ctrl_pv", loop="L1"), "BU|Site", 0.0, None),
    }
    loops = factory._build_control_loops(variables)
    assert set(loops) == {"L1"}


# ── Command entry builder (bridge write-back mapping) ──────────────────────────

def test_build_command_entries_selects_only_rw_command_tags():
    pump = {"name": "pump", "type": "workUnit", "tags": [
        {"name": "speed", "dataType": "Float", "access": "R", "qualifier": "data"},
        {"name": "sp-request", "dataType": "Float", "access": "RW", "qualifier": "command"},
        {"name": "recipe", "dataType": "String", "access": "RW", "qualifier": "data"},
    ]}
    area = {"name": "area", "type": "area", "children": [pump]}
    site = {"name": "Site", "type": "site", "children": [area]}
    bu = {"name": "BU", "type": "businessUnit", "children": [site]}
    tree = {"name": "Ent", "type": "enterprise", "children": [bu]}

    entries = uns_tree.build_command_entries(tree, ".")
    topics = [e[0] for e in entries]
    assert topics == ["Ent.BU.Site.area.pump.sp-request"]      # only the RW+command tag
    assert entries[0][1][-1] == "sp-request"                    # opc path leaf


# ── Bridge command payload helpers ─────────────────────────────────────────────

def test_parse_command_payload_forms():
    assert bridge._parse_command_payload(b'{"value": 1450}') == 1450
    assert bridge._parse_command_payload(b'1450') == 1450.0
    assert bridge._parse_command_payload('{"sp": 42.5}') == 42.5
    assert bridge._parse_command_payload(b'{"other": 1}') is None


def test_coerce_command_types():
    v, vt = bridge._coerce_command("Float", 12.5)
    assert v == 12.5
    v, vt = bridge._coerce_command("Int32", 12.7)
    assert v == 13
    v, vt = bridge._coerce_command("Bool", "true")
    assert v is True
    v, vt = bridge._coerce_command("Float", "not-a-number")
    assert v is None and vt is None


# ── PLC-HMI handshake (mode / enable / watchdog / limits / status) ─────────────

def _hs_loop():
    loop = factory.ControlLoop("h")
    loop.configure({"min": 600, "max": 1800, "rated": 1800, "ramp": 200, "default": 1000})
    loop.mode_var = object(); loop.enable_var = object(); loop.op_sp_var = object()
    loop.lo_var = object(); loop.hi_var = object(); loop.hb_var = object()
    return loop


def _drive(loop, ticks, hb_start=0, freeze_hb=False, **hs):
    hb = hb_start
    for _ in range(ticks):
        if not freeze_hb:
            hb += 1
        loop.tick(hs.get("request", 1600), True, {**hs, "hb": hb})
    return loop


def test_no_handshake_wired_honours_optimizer():
    loop = factory.ControlLoop("n")
    loop.configure({"min": 600, "max": 1800, "rated": 1800, "ramp": 200, "default": 1000})
    for _ in range(20):
        loop.tick(1600, True)
    assert loop.source == "Optimizer"
    assert abs(loop.sp - 1600) < 5


def test_local_mode_uses_operator_setpoint():
    loop = _drive(_hs_loop(), 20, mode=0, enable=True, op_sp=900, lo=600, hi=1800, request=1600)
    assert loop.source == "Operator"
    assert loop.status == factory.ControlLoop.ST_LOCAL
    assert abs(loop.sp - 900) < 5


def test_disabled_permissive_falls_back():
    loop = _drive(_hs_loop(), 20, mode=1, enable=False, op_sp=900, lo=600, hi=1800, request=1600)
    assert loop.source == "Operator"
    assert loop.status == factory.ControlLoop.ST_DISABLED


def test_stale_heartbeat_trips_watchdog_and_reverts():
    loop = _drive(_hs_loop(), 20, freeze_hb=True, mode=1, enable=True,
                  op_sp=900, lo=600, hi=1800, request=1600)
    assert loop.watchdog_ok is False
    assert loop.status == factory.ControlLoop.ST_STALE
    assert loop.source == "Operator"
    assert abs(loop.sp - 900) < 5


def test_fresh_heartbeat_accepts_optimizer():
    loop = _drive(_hs_loop(), 20, mode=1, enable=True, op_sp=900, lo=600, hi=1800, request=1600)
    assert loop.watchdog_ok is True
    assert loop.source == "Optimizer"
    assert loop.status == factory.ControlLoop.ST_ACCEPTED
    assert abs(loop.sp - 1600) < 5


def test_request_clamped_to_operator_limits():
    loop = _drive(_hs_loop(), 20, mode=1, enable=True, op_sp=900, lo=600, hi=1500, request=1750)
    assert loop.status == factory.ControlLoop.ST_CLAMPED
    assert abs(loop.sp - 1500) < 5


def test_watchdog_recovers_when_heartbeat_resumes():
    loop = _hs_loop()
    for _ in range(15):                               # heartbeat frozen
        loop.tick(1600, True, {"mode": 1, "enable": True, "op_sp": 900,
                               "lo": 600, "hi": 1800, "hb": 5})
    assert loop.status == factory.ControlLoop.ST_STALE
    hb = 5
    for _ in range(25):                               # heartbeat resumes
        hb += 1
        loop.tick(1600, True, {"mode": 1, "enable": True, "op_sp": 900,
                               "lo": 600, "hi": 1800, "hb": hb})
    assert loop.source == "Optimizer"
    assert abs(loop.sp - 1600) < 5


# ── Optical sorter sensitivity → reject / escape trade-off ─────────────────────

def _sorter():
    loop = factory.ControlLoop("s")
    loop.configure({"kind": "sensitivity", "min": 20, "max": 95, "rated": 100,
                    "ramp": 100, "default": 50, "infeed_defect": 8, "rated_throughput": 12})
    return loop


def test_higher_sensitivity_increases_reject_and_reduces_escape():
    lo = _sorter()
    for _ in range(60):
        lo.tick(30, True)
    lo_reject, lo_escape = lo.output("ctrl_reject_rate"), lo.output("ctrl_escape")
    hi = _sorter()
    for _ in range(60):
        hi.tick(90, True)
    hi_reject, hi_escape = hi.output("ctrl_reject_rate"), hi.output("ctrl_escape")
    assert hi_reject > lo_reject          # more sensitivity → more product ejected
    assert hi_escape < lo_escape          # more sensitivity → less foreign material passes
    assert abs(hi.output("ctrl_yield") - (100 - hi_reject)) < 0.1


def test_sorter_reject_accumulates_only_when_running():
    lo = _sorter()
    for _ in range(30):
        lo.tick(70, True)
    acc_running = lo.output("ctrl_reject_acc")
    assert acc_running > 0
    before = lo.acc_reject
    for _ in range(30):
        lo.tick(70, False)                # stopped: no product, no rejects
    assert lo.acc_reject == before


def test_faceplate_outputs_have_correct_python_types():
    loop = _hs_loop()
    loop.tick(1600, True, {"mode": 1, "enable": True, "op_sp": 900, "lo": 600, "hi": 1800, "hb": 1})
    assert isinstance(loop.output("ctrl_watchdog"), bool)
    assert isinstance(loop.output("ctrl_status"), str)
    assert isinstance(loop.output("ctrl_source"), str)


# ── default profile centres on an optional nominal "base" ──────────────────────

def test_default_profile_centres_on_base():
    ps = factory.PlantState("p", "")
    ps.state = factory.PlantState.RUNNING
    sim = {"base": 400, "min": 390, "max": 410, "std": 1.0}   # e.g. a 400 V line
    vals = [factory._profile_value("default", ps, sim, 0.0) for _ in range(300)]
    avg = sum(vals) / len(vals)
    assert 397 < avg < 403               # centred near 400, not the 0 default
    assert all(390 <= v <= 410 for v in vals)


def test_default_profile_without_base_is_unchanged():
    ps = factory.PlantState("p", "")
    ps.state = factory.PlantState.RUNNING
    sim = {"min": 0, "max": 100, "std": 1.0}                  # no base
    vals = [factory._profile_value("default", ps, sim, 50.0) for _ in range(300)]
    assert 47 < sum(vals) / len(vals) < 53                    # centres on current_value (50)

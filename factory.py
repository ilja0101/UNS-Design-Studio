#!/usr/bin/env python3
# UNS Design Studio — OPC-UA server + stateful simulation engine
#
# Author : Ilja Bartels  |  https://github.com/Ilja0101
# License: MIT  |  https://github.com/Ilja0101/UNS-Design-Studio
#
# Design principles:
#   - NO hardcoded tag names. Simulation is purely profile-driven.
#   - Every profile is plant-state-aware (running/fault/recovery/stopped).
#   - Recipe switching is supported via sim_state.json — no tag name matching needed.
#   - PlantState adjusts base parameters when the active recipe changes.

import asyncio
import os as _os
import signal
import logging
import random
import json
import datetime
from asyncua import Server, ua
from json_persistence import load_json, load_json_or_raise, load_json_async
from uns_tree import resolve_enterprise_root

logging.getLogger('asyncua').setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARN)

BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
DATA_DIR = _os.environ.get('UNS_DATA_DIR') or ('/data' if _os.name != 'nt' and _os.path.isdir('/data') else BASE_DIR)

def _json_log(msg: str):
    print(msg, flush=True)

# ================================================================
# CONFIG
# ================================================================
def _load_server_cfg():
    cfg_path = _os.path.join(DATA_DIR, 'server_config.json')
    return load_json(cfg_path, {}, logger=_json_log, label='server_config.json')

_scfg            = _load_server_cfg()
_OPC_BIND_IP     = _scfg.get('opc_bind_ip',    '0.0.0.0')
_OPC_PORT        = int(_scfg.get('opc_port',   4840))
_TCP_PORT        = int(_scfg.get('tcp_port',   9999))
_HOST_IP         = (_scfg.get('host_ip') or '').strip()
_OPC_CLIENT_HOST = (_scfg.get('opc_client_host') or '').strip()

def _resolve_advertise_host() -> str:
    if _HOST_IP:              return _HOST_IP
    if _OPC_CLIENT_HOST:      return _OPC_CLIENT_HOST
    if _OPC_BIND_IP and _OPC_BIND_IP != '0.0.0.0': return _OPC_BIND_IP
    return '127.0.0.1'

def _endpoint(host: str) -> str:
    return f"opc.tcp://{host}:{_OPC_PORT}/freeopcua/server/"

BIND_ENDPOINT       = _endpoint(_OPC_BIND_IP or '0.0.0.0')
ADVERTISED_ENDPOINT = _endpoint(_resolve_advertise_host())
NAMESPACE_URI_DEFAULT = "http://VirtualUNS.com/uns"
TCP_SERVER_IP   = "0.0.0.0"
TCP_SERVER_PORT = _TCP_PORT

_anomaly_lock    = None  # asyncio.Lock — initialized in main()
anomaly_overrides: dict = {}

def _get_namespace_uri() -> str:
    try:
        path = _os.path.join(DATA_DIR, 'uns_config.json')
        cfg = load_json(path, {}, logger=_json_log, label='uns_config.json')
        if isinstance(cfg, dict):
            return cfg.get('namespaceUri') or NAMESPACE_URI_DEFAULT
    except Exception:
        pass
    return NAMESPACE_URI_DEFAULT

NAMESPACE_URI = _get_namespace_uri()

# ================================================================
# DYNAMIC ENTERPRISE NAME (FIXED — supports any root name from UNS Designer)
# ================================================================
def _get_enterprise_name() -> str:
    """Return the root enterprise name from uns_config.json (supports any name set in UNS Designer)."""
    try:
        path = _os.path.join(DATA_DIR, 'uns_config.json')
        cfg = load_json(path, {}, logger=_json_log, label='uns_config.json')
        name, _ = resolve_enterprise_root(cfg.get('tree', {}) if isinstance(cfg, dict) else {})
        return name
    except Exception:
        return 'GlobalFoodCo'

# ================================================================
# SIM STATE  (read on every tick — picks up recipe changes live)
# ================================================================
SIM_STATE_FILE = _os.path.join(DATA_DIR, 'sim_state.json')

async def _read_sim_state() -> dict:
    data = await load_json_async(SIM_STATE_FILE, {}, logger=_json_log, label='sim_state.json')
    result = {}
    plants = data.get('plants', {}) if isinstance(data, dict) else {}
    for k, v in plants.items():
        if isinstance(v, dict):
            result[k] = v          # new format: {running, recipe, recipes, ...}
        else:
            result[k] = {'running': bool(v)}  # legacy format: bool
    result['simulator_running'] = data.get('simulator_running', True) if isinstance(data, dict) else True
    return result

# ================================================================
# PLANT STATE MACHINE
# ================================================================
class PlantState:
    RUNNING  = "Running"
    FAULT    = "Fault"
    RECOVERY = "Recovery"
    STOPPED  = "Stopped"

    # Default base parameters per division — overridden per recipe when available
    _GROUP_PARAMS = {
        "CrispCraft":  {"base_power": 720,  "infeed_rate": 24,  "product_price": 2.80, "unit_cost": 1.60,
                        "oee_target": 91.0, "avail_target": 95.0, "perf_target": 97.0, "qual_target": 98.5},
        "FlakeMill":   {"base_power": 600,  "infeed_rate": 33,  "product_price": 1.20, "unit_cost": 0.65,
                        "oee_target": 93.0, "avail_target": 97.0, "perf_target": 97.0, "qual_target": 99.0},
        "FrostLine":   {"base_power": 820,  "infeed_rate": 28,  "product_price": 0.95, "unit_cost": 0.52,
                        "oee_target": 88.0, "avail_target": 94.0, "perf_target": 95.0, "qual_target": 98.0},
        "RootCore":    {"base_power": 690,  "infeed_rate": 37,  "product_price": 3.50, "unit_cost": 1.90,
                        "oee_target": 85.0, "avail_target": 92.0, "perf_target": 94.0, "qual_target": 98.0},
        "SugarWorks":  {"base_power": 1185, "infeed_rate": 95,  "product_price": 0.55, "unit_cost": 0.35,
                        "oee_target": 84.0, "avail_target": 91.0, "perf_target": 94.0, "qual_target": 98.5},
    }
    _DEFAULT_PARAMS = {
        "base_power": 500, "infeed_rate": 20, "product_price": 1.00, "unit_cost": 0.60,
        "oee_target": 85.0, "avail_target": 92.0, "perf_target": 94.0, "qual_target": 97.0
    }

    _ORDER_STATES = ["Created", "Released", "In Progress", "Completed", "Closed"]
    _TRUCK_IDS    = [f"TRK-{n:05d}" for n in range(10000, 10200)]

    def __init__(self, plant_key: str, group: str):
        self.plant_key = plant_key
        self.group     = group
        p = self._GROUP_PARAMS.get(group, self._DEFAULT_PARAMS)

        # State machine
        self.state             = self.RUNNING
        self._fault_ticks      = 0
        self._recovery_ticks   = 0
        self._fault_cooldown   = random.randint(40, 200)

        # OEE pillars
        self.availability      = random.uniform(88, 97)
        self.performance       = random.uniform(85, 98)
        self.quality           = random.uniform(92, 99)

        # Process variables
        self.temperature_process = random.uniform(70, 90)
        self.temperature_ambient = random.uniform(18, 24)
        self.pressure            = random.uniform(3.5, 6.5)
        self.flow_rate           = p["infeed_rate"] * random.uniform(0.85, 1.05)
        self.level               = random.uniform(50, 90)
        self.motor_current       = random.uniform(60, 80)
        self.vibration           = random.uniform(0.5, 2.5)
        self.valve_position      = random.uniform(55, 75)
        self.speed_rpm           = random.uniform(900, 1500)

        # Accumulators
        self.acc_good      = random.uniform(50, 500)
        self.acc_bad       = random.uniform(2, 30)
        self.acc_energy    = random.uniform(500, 8000)
        self.acc_generic   = random.uniform(0, 200)
        self.acc_inbound   = random.uniform(100, 800)
        self.acc_outbound  = random.uniform(80, 600)
        self.acc_maint_cost = random.uniform(500, 5000)
        self.acc_prod_cost = random.uniform(2000, 20000)
        self.acc_waste_cost = random.uniform(100, 1000)
        self.acc_revenue   = random.uniform(5000, 50000)
        self.acc_co2       = random.uniform(200, 3000)

        # Maintenance / Reliability
        self.mtbf           = random.uniform(24, 120)
        self.mttr           = random.uniform(20, 180)
        self.pm_compliance  = random.uniform(78, 96)
        self.rul            = random.uniform(100, 2000)
        self.corrective_wo  = random.randint(0, 5)
        self.fault_count    = random.randint(0, 10)
        self.last_failure   = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=random.uniform(2, 96))
        self.next_pm        = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=random.randint(3, 45))

        # Quality
        self.quality_metric_cont = random.uniform(88, 96)
        self.quality_hold        = False
        self._quality_hold_ticks = 0

        # Logistics
        self.days_of_supply  = random.uniform(3, 14)
        self.truck_id        = random.choice(self._TRUCK_IDS)
        self.lot_id          = f"LOT-{random.randint(5000, 9999)}"
        self.batch_id        = f"BATCH-{random.randint(1000, 9999)}"
        self.order_qty       = random.randint(5000, 25000)
        self.order_status_idx = random.randint(0, 3)

        # ERP / Finance
        self.erp_order_id    = f"ORD-{random.randint(100000, 999999)}"
        self.margin_pct      = random.uniform(22, 38)

        # Energy
        self.power_kw        = p["base_power"] * random.uniform(0.88, 1.05)
        self.steam_flow      = p["base_power"] * random.uniform(0.08, 0.12)
        self.compressed_air  = random.uniform(15, 40)

        # Recipe
        self.active_recipe   = ""           # set each tick from sim_state
        self._last_recipe    = ""           # detect changes

        # Internal working params (updated when recipe changes)
        self._base_power     = p["base_power"]
        self._infeed_rate    = p["infeed_rate"]
        self._product_price  = p["product_price"]
        self._unit_cost      = p["unit_cost"]
        self._avail_target   = p["avail_target"]
        self._perf_target    = p["perf_target"]
        self._qual_target    = p["qual_target"]

        # Internal counters
        self._batch_tick     = 0
        self._order_tick     = 0
        self._pm_tick        = 0

    # ── Helpers ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _clamp(v, lo, hi): return max(lo, min(hi, v))
    def _gauss(self, val, std, lo, hi): return self._clamp(val + random.gauss(0, std), lo, hi)
    def _drift(self, val, target, speed, std, lo, hi):
        return self._clamp(val + (target - val) * speed + random.gauss(0, std), lo, hi)

    # ── Properties ───────────────────────────────────────────────────────────────
    @property
    def oee(self): return round(self.availability * self.performance * self.quality / 10000.0, 2)
    @property
    def is_running(self): return self.state == self.RUNNING
    @property
    def is_fault(self):   return self.state == self.FAULT
    @property
    def is_alarm(self):   return self.state in (self.FAULT, self.RECOVERY)
    @property
    def order_status(self): return self._ORDER_STATES[self.order_status_idx % len(self._ORDER_STATES)]

    # ── Recipe change handler ─────────────────────────────────────────────────────
    def _apply_recipe(self, recipe: str, recipe_params: dict):
        self.active_recipe = recipe
        if not recipe_params:
            return
        p = self._GROUP_PARAMS.get(self.group, self._DEFAULT_PARAMS)
        self._base_power    = recipe_params.get("base_power",    p["base_power"])
        self._infeed_rate   = recipe_params.get("infeed_rate",   p["infeed_rate"])
        self._product_price = recipe_params.get("product_price", p["product_price"])
        self._unit_cost     = recipe_params.get("unit_cost",     p["unit_cost"])
        self._avail_target  = recipe_params.get("avail_target",  p["avail_target"])
        self._perf_target   = recipe_params.get("perf_target",   p["perf_target"])
        self._qual_target   = recipe_params.get("qual_target",   p["qual_target"])

    # ── Main tick ─────────────────────────────────────────────────────────────────
    def tick(self, externally_running: bool, plant_sim_state: dict):
        # ── Recipe update ─────────────────────────────────────────────────────────
        new_recipe = plant_sim_state.get("recipe", "")
        if new_recipe != self._last_recipe:
            recipes_list = plant_sim_state.get("recipes", [])
            recipe_params = {}
            for r in recipes_list:
                if isinstance(r, dict) and r.get("name") == new_recipe:
                    recipe_params = r.get("params", {})
                    break
            self._apply_recipe(new_recipe, recipe_params)
            self._last_recipe = new_recipe

        # ── External stop ─────────────────────────────────────────────────────────
        if not externally_running:
            self.state       = self.STOPPED
            self.power_kw    = self._base_power * 0.06
            self.flow_rate   = 0.0
            self.speed_rpm   = 0.0
            self.availability = self._clamp(self.availability - random.uniform(0, 0.3), 0, 100)
            return

        # ── State machine transitions ─────────────────────────────────────────────
        if self.state == self.STOPPED:
            self.state            = self.RECOVERY
            self._recovery_ticks  = random.randint(4, 10)

        if self.state == self.FAULT:
            self._fault_ticks -= 1
            if self._fault_ticks <= 0:
                self.state            = self.RECOVERY
                self._recovery_ticks  = random.randint(5, 15)
                self.fault_count     += 1
                self.corrective_wo   += 1
                self.last_failure     = datetime.datetime.now(datetime.timezone.utc)
                self.mtbf             = self._clamp(self.mtbf * random.uniform(0.7, 0.95), 4, 200)
                self.mttr             = self._clamp(self.mttr * random.uniform(1.05, 1.3), 5, 480)
                self.acc_maint_cost  += random.uniform(200, 2000)
                self.vibration        = self._clamp(self.vibration + random.uniform(1, 3), 0, 15)

        elif self.state == self.RECOVERY:
            self._recovery_ticks -= 1
            if self._recovery_ticks <= 0:
                self.state            = self.RUNNING
                self._fault_cooldown  = random.randint(60, 400)
                self.corrective_wo    = max(0, self.corrective_wo - 1)
                if random.random() < 0.15:
                    self.rul           = random.uniform(800, 2500)
                    self.next_pm       = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=random.randint(14, 60))
                    self.pm_compliance = self._clamp(self.pm_compliance + random.uniform(2, 8), 50, 100)

        elif self.state == self.RUNNING:
            if self._fault_cooldown > 0:
                self._fault_cooldown -= 1
            else:
                fault_prob = 0.003 + max(0, (self.vibration - 3.0) * 0.001) + max(0, (500 - self.rul) * 0.000002)
                if random.random() < fault_prob:
                    self.state        = self.FAULT
                    self._fault_ticks = random.randint(5, 30)

        # ── Variable evolution by state ───────────────────────────────────────────
        if self.state == self.RUNNING:
            self.availability        = self._drift(self.availability, self._avail_target, 0.015, 0.4, 60, 99.5)
            self.performance         = self._drift(self.performance,  self._perf_target,  0.015, 0.5, 55, 100)
            self.quality             = self._drift(self.quality,      self._qual_target,  0.01,  0.3, 70, 100)
            self.temperature_process = self._drift(self.temperature_process, 80.0, 0.02, 0.8, 40, 200)
            self.temperature_ambient = self._gauss(self.temperature_ambient, 0.05, 15, 35)
            self.pressure            = self._drift(self.pressure, 5.0, 0.02, 0.1, 0, 25)
            self.flow_rate           = self._drift(self.flow_rate, self._infeed_rate, 0.02, 0.5, 0, self._infeed_rate * 1.3)
            self.motor_current       = self._drift(self.motor_current, 70.0, 0.02, 1.0, 0, 200)
            self.vibration           = self._drift(self.vibration, 1.5, 0.01, 0.05, 0, 15)
            self.valve_position      = self._drift(self.valve_position, 65.0, 0.02, 1.0, 0, 100)
            self.speed_rpm           = self._drift(self.speed_rpm, 1200.0, 0.02, 10, 0, 3600)
            self.power_kw            = self._drift(self.power_kw, self._base_power, 0.02,
                                                   self._base_power * 0.015, self._base_power * 0.6, self._base_power * 1.2)
            self.steam_flow          = self._drift(self.steam_flow, self._base_power * 0.1, 0.02, 0.5, 0, self._base_power * 0.25)
            self.compressed_air      = self._drift(self.compressed_air, 25.0, 0.02, 0.5, 0, 80)

            consumption  = self._infeed_rate / 3600.0 * 1.2
            self.level   = self._clamp(self.level - consumption * random.uniform(0.8, 1.2), 0, 100)
            if self.level < 20 and random.random() < 0.04:
                self.level        += random.uniform(25, 45)
                self.level         = min(self.level, 100)
                self.truck_id      = random.choice(self._TRUCK_IDS)
                self.lot_id        = f"LOT-{random.randint(5000, 9999)}"
                self.acc_inbound  += random.uniform(20, 50)
            self.days_of_supply = self._clamp(self.level / 7.5, 0.1, 30)

            rate        = self._infeed_rate / 3600.0 * 1.2
            good_rate   = rate * (self.quality / 100.0)
            bad_rate    = rate * (1 - self.quality / 100.0)
            self.acc_good      += good_rate  * random.uniform(0.9, 1.1)
            self.acc_bad       += bad_rate   * random.uniform(0.8, 1.2)
            self.acc_energy    += self.power_kw / 3600.0 * 1.2
            self.acc_generic   += random.uniform(0.01, 0.1)
            self.acc_outbound  += good_rate  * random.uniform(0.9, 1.05)
            self.acc_co2       += self.power_kw * 0.000233

        elif self.state == self.FAULT:
            self.availability  = self._clamp(self.availability - random.uniform(0.5, 2.5), 0, 100)
            self.performance   = self._clamp(self.performance  - random.uniform(0.2, 1.0), 0, 100)
            self.flow_rate     = 0.0
            self.speed_rpm     = 0.0
            self.motor_current = self._clamp(self.motor_current + random.uniform(0, 5), 0, 200)
            self.vibration     = self._clamp(self.vibration + random.uniform(0.2, 1.0), 0, 15)
            self.power_kw      = self._base_power * 0.12
            self.steam_flow    = 0.0
            self.compressed_air = self._base_power * 0.005

        elif self.state == self.RECOVERY:
            self.availability  = self._clamp(self.availability + random.uniform(0.5, 2.5), 0, 100)
            self.performance   = self._clamp(self.performance  + random.uniform(0.2, 1.0), 0, 100)
            self.flow_rate     = self._infeed_rate * random.uniform(0.1, 0.5)
            self.speed_rpm     = 1200 * random.uniform(0.1, 0.5)
            self.motor_current = self._clamp(self.motor_current - random.uniform(0, 2), 0, 200)
            self.vibration     = self._clamp(self.vibration - random.uniform(0.1, 0.4), 0, 15)
            self.power_kw      = self._base_power * random.uniform(0.3, 0.6)
            self.steam_flow    = self._base_power * 0.04
            self.compressed_air = 10.0

        # PM tick
        self._pm_tick += 1
        if self._pm_tick > 3600:
            self._pm_tick      = 0
            self.pm_compliance = self._clamp(self.pm_compliance - random.uniform(0, 0.3), 50, 100)


# ================================================================
# PLANT STATE REGISTRY
# ================================================================
_plant_states: dict = {}

def _get_plant_state(plant_key: str, group: str) -> PlantState:
    if plant_key not in _plant_states:
        _plant_states[plant_key] = PlantState(plant_key, group)
    return _plant_states[plant_key]


# ================================================================
# CONTROL LOOPS  (per-equipment setpoint → PV closed loop)
# ================================================================
# Topology (matches the request → controller → setpoint pattern):
#   • An optimizer writes a *request* to a  …/cmd/<var>-request  tag (RW, held —
#     the sim never overwrites it, so an externally written value persists).
#   • This engine is the *controller*: each tick it ramps the *committed
#     setpoint* (…/setpoint/<var>) toward the request at a bounded rate.
#   • The measured *process value* (…/vfd/speed, …/pv, …) tracks the committed
#     setpoint with first-order lag + small noise, and drops to zero when the
#     equipment's plant is stopped or in fault.
#   • Electrical PVs (power, current, frequency) and flow are *derived* from the
#     PV using VFD affinity laws, so one speed setpoint drives a whole unit.
#
# A loop is declared purely through tag `simulation` blocks — no tag-name
# matching. Every tag in a loop carries {"profile": "ctrl_*", "loop": "<id>"};
# the authoritative parameters (min/max/rated/ramp/rated_power/…) live on the
# ctrl_request tag's simulation block.
class ControlLoop:
    # cmd-status strings surfaced on the …/status writeback tag
    ST_ACCEPTED = "Accepted"
    ST_CLAMPED  = "Clamped"
    ST_LOCAL    = "Local(HMI)"
    ST_DISABLED = "OptimizerDisabled"
    ST_STALE    = "StaleWatchdog"

    def __init__(self, loop_id: str):
        self.loop_id       = loop_id
        self.plant_key     = None
        self.request_var   = None        # OPC variable written by the optimizer
        # ── Realistic PLC-HMI faceplate: optional handshake input variables ──
        self.mode_var      = None        # operator mode  (0=Local/HMI, 1=Remote/optimizer)
        self.enable_var    = None        # operator "Accept optimizer" permissive (Bool)
        self.op_sp_var     = None        # operator local setpoint (the safe fallback)
        self.lo_var        = None        # operator EU low limit
        self.hi_var        = None        # operator EU high limit
        self.hb_var        = None        # optimizer heartbeat counter (freshness)
        # Parameters (overridable from the ctrl_request tag's simulation block)
        self.kind             = "vfd_speed"
        self.sp_min           = 0.0
        self.sp_max           = 1500.0
        self.rated            = 1500.0
        self.ramp             = 30.0     # max change of committed SP per tick
        self.lag              = 0.25     # PV first-order tracking factor
        self.rated_power      = 0.0      # kW at rated PV (0 → no power PV)
        self.rated_current    = 0.0      # A at rated PV
        self.no_load_current  = 0.15     # fraction of rated current at zero load
        self.rated_flow       = 0.0      # flow units at rated PV
        self.default          = 1200.0
        self.hb_timeout       = 5        # ticks the heartbeat may stall before "stale"
        # Optical-sorter (kind="sensitivity") params
        self.infeed_defect    = 8.0      # % defective / foreign material in the infeed
        self.rated_throughput = 12.0     # t/h processed at nominal
        # State
        self._seeded = False
        self.request = None
        self.sp      = None
        self.pv      = 0.0
        self.acc_reject = 0.0            # accumulated reject mass (t) for sorters
        # Handshake state / writeback outputs
        self._last_hb    = None
        self._hb_idle    = 0
        self.watchdog_ok = True
        self.status      = self.ST_ACCEPTED
        self.source      = "Operator"

    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    def configure(self, sim: dict):
        g = sim.get
        self.kind            = g("kind", self.kind)
        self.sp_min          = float(g("min", self.sp_min))
        self.sp_max          = float(g("max", self.sp_max))
        self.rated           = float(g("rated", self.sp_max))
        self.ramp            = float(g("ramp", max(1.0, (self.sp_max - self.sp_min) / 40.0)))
        self.lag             = float(g("lag", self.lag))
        self.rated_power     = float(g("rated_power", self.rated_power))
        self.rated_current   = float(g("rated_current", self.rated_current))
        self.no_load_current = float(g("no_load_current", self.no_load_current))
        self.rated_flow      = float(g("rated_flow", self.rated_flow))
        self.default         = float(g("default", self.rated * 0.8))
        self.hb_timeout      = int(g("hb_timeout", self.hb_timeout))
        self.infeed_defect   = float(g("infeed_defect", self.infeed_defect))
        self.rated_throughput = float(g("rated_throughput", self.rated_throughput))

    def _seed(self):
        if not self._seeded:
            if self.request is None:
                self.request = self.default
            if self.sp is None:
                self.sp = self.default
            self.pv = self.default
            self._seeded = True

    def handshake_vars(self) -> dict:
        """Wired faceplate input variables, read live each tick (or {} if the
        loop has no handshake — then the optimizer request is honoured directly)."""
        return {k: v for k, v in (
            ("mode", self.mode_var), ("enable", self.enable_var),
            ("op_sp", self.op_sp_var), ("lo", self.lo_var),
            ("hi", self.hi_var), ("hb", self.hb_var)) if v is not None}

    def _resolve_target(self, hs: dict):
        """Apply the PLC-HMI handshake: decide which setpoint actually drives the
        loop (optimizer request vs operator SP) and set status/source. Returns the
        target value before ramp/clamp-to-hard-range."""
        has_hs = bool(self.mode_var or self.enable_var or self.hb_var)

        # Operator EU limits (tighten, never widen, the absolute range)
        lo = hs.get("lo"); hi = hs.get("hi")
        eff_lo = self._clamp(float(lo), self.sp_min, self.sp_max) if lo is not None else self.sp_min
        eff_hi = self._clamp(float(hi), self.sp_min, self.sp_max) if hi is not None else self.sp_max
        if eff_lo > eff_hi:
            eff_lo, eff_hi = eff_hi, eff_lo

        # Watchdog: the heartbeat must advance within hb_timeout ticks
        if self.hb_var is not None:
            hb = hs.get("hb")
            if hb is not None and hb != self._last_hb:
                self._last_hb = hb
                self._hb_idle = 0
            else:
                self._hb_idle += 1
            self.watchdog_ok = self._hb_idle <= self.hb_timeout
        else:
            self.watchdog_ok = True

        mode   = hs.get("mode")
        enable = hs.get("enable")
        op_sp  = hs.get("op_sp")

        # Permissive chain: Remote mode AND operator-enabled AND fresh heartbeat
        remote = True
        status = self.ST_ACCEPTED
        if has_hs:
            if mode is not None and int(mode) < 1:
                remote, status = False, self.ST_LOCAL
            elif enable is not None and not bool(enable):
                remote, status = False, self.ST_DISABLED
            elif not self.watchdog_ok:
                remote, status = False, self.ST_STALE

        if remote and self.request is not None:
            target, self.source = self.request, "Optimizer"
        elif has_hs and op_sp is not None:
            target, self.source = float(op_sp), "Operator"     # safe fallback SP
        else:
            target = self.request if self.request is not None else self.sp
            self.source = "Optimizer" if not has_hs else "Operator"

        clamped = self._clamp(target, eff_lo, eff_hi)
        if remote and self.request is not None and abs(clamped - target) > 1e-6:
            status = self.ST_CLAMPED
        self.status = status
        return clamped

    def tick(self, request_value, running: bool, hs: dict = None):
        """Advance the loop one tick. request_value is the live value read from the
        OPC request variable; hs holds live faceplate inputs (mode/enable/…)."""
        self._seed()
        hs = hs or {}
        if request_value is not None:
            try:
                self.request = self._clamp(float(request_value), self.sp_min, self.sp_max)
            except (TypeError, ValueError):
                pass

        target = self._resolve_target(hs)

        # Controller: ramp the committed setpoint toward the resolved target
        # (bumpless — the ramp absorbs any source/mode switch).
        step   = self._clamp(target - self.sp, -self.ramp, self.ramp)
        self.sp = self._clamp(self.sp + step, self.sp_min, self.sp_max)

        # Process value tracks the committed setpoint.
        if not running:
            self.pv = max(0.0, self.pv * 0.7)          # coast down when stopped/faulted
        else:
            noise   = random.gauss(0, max(self.sp_max * 0.0015, 0.01))
            self.pv = self._clamp(self.pv + (self.sp - self.pv) * self.lag + noise,
                                  0.0, self.sp_max * 1.08)
            if self.kind == "sensitivity":
                self.acc_reject += self.rated_throughput / 3600.0 * 1.2 * (self._reject_rate() / 100.0)

    @property
    def frac(self):
        return self._clamp(self.pv / self.rated, 0.0, 1.2) if self.rated else 0.0

    # ── Optical-sorter derivations (sensitivity → reject / escape trade-off) ──
    def _detection(self):
        return self.frac ** 0.45                        # concave: more sensitivity → more caught
    def _false_reject(self):
        return 0.4 + 12.0 * self.frac ** 2              # % good product wrongly ejected
    def _reject_rate(self):
        return self.infeed_defect * self._detection() + self._false_reject()
    def _escape(self):
        return self.infeed_defect * (1.0 - self._detection())   # % foreign material passing

    def output(self, role: str):
        """Value for a given ctrl_* role tag."""
        f = self.frac
        if role == "ctrl_request":
            return round(self.request if self.request is not None else self.default, 2)
        if role == "ctrl_setpoint":
            return round(self.sp, 2)
        if role == "ctrl_pv":
            return round(self.pv, 2)
        if role == "ctrl_power":       # VFD affinity: P ∝ speed³
            return round(self.rated_power * (0.03 + 0.97 * f ** 3), 2)
        if role == "ctrl_current":     # torque ∝ speed² for centrifugal load
            return round(self.rated_current * (self.no_load_current +
                         (1 - self.no_load_current) * f ** 2), 2)
        if role == "ctrl_frequency":   # rated PV assumed to map to 50 Hz
            return round(50.0 * f, 2)
        if role == "ctrl_flow":
            return round(self.rated_flow * f, 2)
        if role == "ctrl_valve":
            return round(self._clamp(f * 100.0, 0.0, 100.0), 2)
        # ── Realistic faceplate writeback outputs ──
        if role == "ctrl_watchdog":
            return bool(self.watchdog_ok)
        if role == "ctrl_status":
            return str(self.status)
        if role == "ctrl_source":
            return str(self.source)
        # ── Optical-sorter reject metrics ──
        if role == "ctrl_reject_rate":
            return round(self._reject_rate(), 2)
        if role == "ctrl_escape":
            return round(self._escape(), 3)
        if role == "ctrl_yield":
            return round(100.0 - self._reject_rate(), 2)
        if role == "ctrl_reject_acc":
            return round(self.acc_reject, 3)
        if role == "ctrl_ejector":     # air-jet firings per second (indicative)
            return round(self._reject_rate() * self.rated_throughput * 2.5, 1)
        return round(self.pv, 2)


def _loop_id_for(opc_path, sim: dict) -> str:
    """Resolve a tag's control-loop id. An explicit simulation.loop groups tags
    across sub-objects (…/cmd, …/setpoint, …/vfd). Without one, tags are grouped
    by their parent node — so a drop-in asset whose control tags are flat under
    one equipment node forms its own loop with no cross-instance collisions."""
    lid = sim.get("loop")
    if lid:
        return str(lid)
    return "@" + "/".join(opc_path[:-1])


def _build_control_loops(variables: dict) -> dict:
    """Scan the built OPC variable table and assemble the ControlLoop registry.

    variables: {opc_path: (var, sim, plant_key, default, vt)}
    """
    # faceplate input roles → ControlLoop attribute that holds the OPC var ref
    _INPUT_ROLE_ATTR = {
        "ctrl_mode": "mode_var", "ctrl_enable": "enable_var",
        "ctrl_sp_operator": "op_sp_var", "ctrl_sp_lo": "lo_var",
        "ctrl_sp_hi": "hi_var", "ctrl_heartbeat": "hb_var",
    }
    loops = {}
    for _opc_path, (var, sim, plant_key, _default, _vt) in variables.items():
        profile = sim.get("profile", "")
        if not isinstance(profile, str) or not profile.startswith("ctrl"):
            continue
        loop_id = _loop_id_for(_opc_path, sim)
        loop = loops.get(loop_id)
        if loop is None:
            loop = ControlLoop(loop_id)
            loops[loop_id] = loop
        if plant_key:
            loop.plant_key = plant_key
        if profile == "ctrl_request":
            loop.request_var = var
            loop.configure(sim)
        elif profile in _INPUT_ROLE_ATTR:
            setattr(loop, _INPUT_ROLE_ATTR[profile], var)
    if loops:
        n_hs = sum(1 for l in loops.values() if l.handshake_vars())
        print(f"[factory] Control loops ready — {len(loops)} closed loops "
              f"({n_hs} with PLC-HMI handshake)")
    return loops


# ================================================================
# PROFILE → VALUE  (pure profile dispatch, no tag names)
# ================================================================
def _profile_value(profile: str, ps: PlantState, sim: dict, current_value):
    p = profile.lower().strip()

    if p == "oee":                    return round(ps.oee, 2)
    if p == "availability":           return round(ps.availability, 2)
    if p == "performance":            return round(ps.performance, 2)
    if p == "quality":                return round(ps.quality, 2)
    if p == "temperature_process":    return round(ps.temperature_process, 2)
    if p == "temperature_ambient":    return round(ps.temperature_ambient, 2)
    if p == "pressure":               return round(ps.pressure, 3)
    if p == "flow_rate":              return round(ps.flow_rate, 3)
    if p == "level":                  return round(ps.level, 2)
    if p == "motor_current":          return round(ps.motor_current, 2)
    if p == "vibration":              return round(ps.vibration, 3)
    if p == "valve_position":         return round(ps.valve_position, 2)
    if p == "speed_rpm":              return round(ps.speed_rpm, 1)
    if p == "boolean_running":        return ps.is_running
    if p == "boolean_fault":          return ps.is_fault
    if p == "boolean_alarm":          return ps.is_alarm
    if p == "accumulator_good":       return round(ps.acc_good, 3)
    if p == "accumulator_bad":        return round(ps.acc_bad, 3)
    if p == "accumulator_energy":     return round(ps.acc_energy, 2)
    if p in ("accumulator_generic", "accumulator"):          return round(ps.acc_generic, 3)
    if p == "counter_faults":         return ps.fault_count
    if p == "mtbf":                   return round(ps.mtbf, 2)
    if p == "mttr":                   return round(ps.mttr, 2)
    if p == "pm_compliance":          return round(ps.pm_compliance, 2)
    if p == "remaining_useful_life":  return round(ps.rul, 1)
    if p == "corrective_wo_count":    return ps.corrective_wo
    if p == "maintenance_cost":       return round(ps.acc_maint_cost, 2)
    if p == "quality_metric_pct":     return round(ps.quality, 2)
    if p == "quality_metric_cont":    return round(ps.quality_metric_cont, 3)
    if p == "quality_hold":           return ps.quality_hold
    if p == "batch_id":               return ps.batch_id
    if p == "lot_id":                 return ps.lot_id
    if p == "silo_level":             return round(ps.level, 2)
    if p == "inbound_tons":           return round(ps.acc_inbound, 3)
    if p == "outbound_tons":          return round(ps.acc_outbound, 3)
    if p == "truck_id":               return ps.truck_id
    if p == "days_of_supply":         return round(ps.days_of_supply, 2)
    if p == "order_quantity":         return ps.order_qty
    if p == "order_status":           return ps.order_status
    if p == "erp_order_id":           return ps.erp_order_id
    if p == "production_cost_eur":    return round(ps.acc_prod_cost, 2)
    if p == "waste_cost_eur":         return round(ps.acc_waste_cost, 2)
    if p == "revenue_eur":            return round(ps.acc_revenue, 2)
    if p == "margin_pct":             return round(ps.margin_pct, 2)
    if p == "power_kw":               return round(ps.power_kw, 2)
    if p == "steam_flow":             return round(ps.steam_flow, 2)
    if p == "compressed_air":         return round(ps.compressed_air, 2)
    if p == "co2_kg":                 return round(ps.acc_co2, 3)

    if p == "recipe":
        return ps.active_recipe if ps.active_recipe else ""

    # Setpoint / command holds and closed-loop control profiles are resolved
    # against the per-equipment ControlLoop registry in run_simulation(). If one
    # is ever dispatched here without a loop, hold the current value rather than
    # walking it — a setpoint must never drift on its own.
    if p == "hold":               return current_value
    if p.startswith("ctrl"):      return current_value

    # Legacy aliases
    if p == "percent":                return round(ps.quality, 2)
    if p == "temperature":            return round(ps.temperature_process, 2)
    if p == "boolean":                return ps.is_running
    if p == "string_cycle":           return ps.truck_id

    # Fallback: plant-state-aware Gaussian walk
    if isinstance(current_value, bool):              return ps.is_running
    if isinstance(current_value, str):               return current_value
    if isinstance(current_value, datetime.datetime): return current_value

    std     = sim.get("std", 2.0)
    lo, hi  = sim.get("min", 0.0), sim.get("max", 100.0)
    # Jitter around a configured nominal ("base") when given — e.g. a 400 V line
    # voltage or a 65 °C winding temperature. Without "base" this stays centred on
    # the tag's default (unchanged behaviour for existing configs).
    center  = sim.get("base", current_value)
    if ps.state == PlantState.FAULT:    std *= 0.2
    elif ps.state == PlantState.RECOVERY: std *= 0.5
    return float(max(lo, min(hi, center + random.gauss(0, std))))


# ================================================================
# SIMULATION PROFILE CATALOGUE
# ================================================================
SIMULATION_PROFILES = {
    "oee":                   {"label": "OEE (%)",                       "group": "OT / Process"},
    "availability":          {"label": "Availability (%)",              "group": "OT / Process"},
    "performance":           {"label": "Performance (%)",               "group": "OT / Process"},
    "quality":               {"label": "Quality (%)",                   "group": "OT / Process"},
    "temperature_process":   {"label": "Process Temperature",           "group": "OT / Process"},
    "temperature_ambient":   {"label": "Ambient Temperature",           "group": "OT / Process"},
    "pressure":              {"label": "Pressure",                      "group": "OT / Process"},
    "flow_rate":             {"label": "Flow Rate (zero when stopped)", "group": "OT / Process"},
    "level":                 {"label": "Tank / Silo Level (%)",         "group": "OT / Process"},
    "motor_current":         {"label": "Motor Current (A)",             "group": "OT / Process"},
    "vibration":             {"label": "Vibration (mm/s)",              "group": "OT / Process"},
    "valve_position":        {"label": "Valve Position (%)",            "group": "OT / Process"},
    "speed_rpm":             {"label": "Speed (RPM)",                   "group": "OT / Process"},
    "boolean_running":       {"label": "Boolean: Running",              "group": "OT / Process"},
    "boolean_fault":         {"label": "Boolean: Fault",                "group": "OT / Process"},
    "boolean_alarm":         {"label": "Boolean: Alarm",                "group": "OT / Process"},
    "accumulator_good":      {"label": "Accumulator: Good Output",      "group": "Accumulators"},
    "accumulator_bad":       {"label": "Accumulator: Rejected Output",  "group": "Accumulators"},
    "accumulator_energy":    {"label": "Accumulator: Energy (kWh)",     "group": "Accumulators"},
    "accumulator_generic":   {"label": "Accumulator: Generic Counter",  "group": "Accumulators"},
    "counter_faults":        {"label": "Counter: Fault Events",         "group": "Accumulators"},
    "mtbf":                  {"label": "MTBF (hours)",                  "group": "Maintenance / CMMS"},
    "mttr":                  {"label": "MTTR (minutes)",                "group": "Maintenance / CMMS"},
    "pm_compliance":         {"label": "PM Compliance (%)",             "group": "Maintenance / CMMS"},
    "remaining_useful_life": {"label": "Remaining Useful Life (h)",     "group": "Maintenance / CMMS"},
    "corrective_wo_count":   {"label": "Corrective Work Orders (open)", "group": "Maintenance / CMMS"},
    "maintenance_cost":      {"label": "Maintenance Cost (EUR, acc.)",  "group": "Maintenance / CMMS"},
    "quality_metric_pct":    {"label": "Quality Metric (%)",            "group": "Quality / Lab"},
    "quality_metric_cont":   {"label": "Quality Metric (continuous)",   "group": "Quality / Lab"},
    "quality_hold":          {"label": "Quality Hold (boolean)",        "group": "Quality / Lab"},
    "batch_id":              {"label": "Batch ID (string)",             "group": "Quality / Lab"},
    "lot_id":                {"label": "Lot / Inbound ID (string)",     "group": "Quality / Lab"},
    "silo_level":            {"label": "Silo / Tank Level (%)",         "group": "Logistics"},
    "inbound_tons":          {"label": "Inbound Tonnage (acc.)",        "group": "Logistics"},
    "outbound_tons":         {"label": "Outbound Tonnage (acc.)",       "group": "Logistics"},
    "truck_id":              {"label": "Last Truck / Delivery ID",      "group": "Logistics"},
    "days_of_supply":        {"label": "Days of Supply",                "group": "Logistics"},
    "order_quantity":        {"label": "Order Quantity",                "group": "Logistics"},
    "order_status":          {"label": "Order Status (string)",         "group": "Logistics"},
    "erp_order_id":          {"label": "ERP Order ID (string)",         "group": "ERP / Finance"},
    "production_cost_eur":   {"label": "Production Cost (EUR, acc.)",   "group": "ERP / Finance"},
    "waste_cost_eur":        {"label": "Waste Cost (EUR, acc.)",        "group": "ERP / Finance"},
    "revenue_eur":           {"label": "Revenue (EUR, acc.)",           "group": "ERP / Finance"},
    "margin_pct":            {"label": "Margin (%)",                    "group": "ERP / Finance"},
    "power_kw":              {"label": "Active Power (kW)",             "group": "Energy / Utilities"},
    "steam_flow":            {"label": "Steam Flow (kg/h)",             "group": "Energy / Utilities"},
    "compressed_air":        {"label": "Compressed Air (m³/h)",        "group": "Energy / Utilities"},
    "co2_kg":                {"label": "CO₂ Emissions (kg, acc.)",      "group": "Energy / Utilities"},
    "recipe":                {"label": "Active Recipe (string)",        "group": "Recipe"},
    # ── Control / Setpoints (closed-loop; see ControlLoop) ──
    "ctrl_request":          {"label": "SP Request (RW, optimizer)",    "group": "Control / Setpoints"},
    "ctrl_setpoint":         {"label": "Committed Setpoint (actual)",   "group": "Control / Setpoints"},
    "ctrl_pv":               {"label": "Process Value (tracks SP)",     "group": "Control / Setpoints"},
    "ctrl_power":            {"label": "Derived Power (kW, VFD law)",   "group": "Control / Setpoints"},
    "ctrl_current":          {"label": "Derived Motor Current (A)",     "group": "Control / Setpoints"},
    "ctrl_frequency":        {"label": "Derived Output Frequency (Hz)", "group": "Control / Setpoints"},
    "ctrl_flow":             {"label": "Derived Flow (tracks SP)",      "group": "Control / Setpoints"},
    "ctrl_valve":            {"label": "Derived Valve Output (%)",      "group": "Control / Setpoints"},
    # ── PLC-HMI handshake / faceplate (operator + optimizer command interface) ──
    "ctrl_mode":             {"label": "Loop Mode (0=Local,1=Remote)",  "group": "Control / Handshake"},
    "ctrl_enable":           {"label": "Accept-Optimizer Permissive",   "group": "Control / Handshake"},
    "ctrl_sp_operator":      {"label": "Operator Setpoint (fallback)",  "group": "Control / Handshake"},
    "ctrl_sp_lo":            {"label": "Operator SP Low Limit",         "group": "Control / Handshake"},
    "ctrl_sp_hi":            {"label": "Operator SP High Limit",        "group": "Control / Handshake"},
    "ctrl_heartbeat":        {"label": "Optimizer Heartbeat (RW)",      "group": "Control / Handshake"},
    "ctrl_watchdog":         {"label": "Watchdog OK (bool)",            "group": "Control / Handshake"},
    "ctrl_status":           {"label": "Command Status (writeback)",    "group": "Control / Handshake"},
    "ctrl_source":           {"label": "Active SP Source",              "group": "Control / Handshake"},
    # ── Optical sorter reject metrics ──
    "ctrl_reject_rate":      {"label": "Reject Rate (%)",               "group": "Control / Sorter"},
    "ctrl_escape":           {"label": "Foreign-Material Escape (%)",   "group": "Control / Sorter"},
    "ctrl_yield":            {"label": "Yield / Accept Rate (%)",       "group": "Control / Sorter"},
    "ctrl_reject_acc":       {"label": "Reject Mass (t, acc.)",         "group": "Control / Sorter"},
    "ctrl_ejector":          {"label": "Ejector Firings (/s)",          "group": "Control / Sorter"},
    "hold":                  {"label": "Hold last written value (SP)",  "group": "Control / Setpoints"},
    "default":               {"label": "Generic Walk (fallback)",       "group": "Other"},
}


# ================================================================
# UNS CONFIG LOADER
# ================================================================
def _load_uns_config():
    path = _os.path.join(DATA_DIR, 'uns_config.json')
    return load_json_or_raise(path, logger=_json_log, label='uns_config.json')


# ================================================================
# DYNAMIC OPC-UA ADDRESS SPACE BUILDER
# ================================================================
async def _create_dynamic_address_space(server, idx, enterprise_obj):
    cfg  = _load_uns_config()
    tree = cfg['tree']
    variables       = {}
    anomaly_key_map = {}

    _, enterprise_node = resolve_enterprise_root(tree)

    canonical = {}
    def _collect_canonical(node):
        name = node.get('name', '')
        tags = node.get('tags', [])
        if tags and name and name not in canonical:
            canonical[name] = tags
        for child in node.get('children', []):
            _collect_canonical(child)
    _collect_canonical(enterprise_node)

    async def _walk(node, uns_parts, opc_parts, area_opc_parts, plant_key):
        ntype    = node.get('type', '')
        name     = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name
        new_opc  = opc_parts + [opc_name]
        new_area = new_opc if ntype == 'area' else area_opc_parts

        # FIXED: plant_key uses logical site name (no "Factory" prefix) to match sim_state.json
        new_plant_key = plant_key
        if ntype == 'site':
            bu_name       = opc_parts[-1] if opc_parts else ''
            site_logical  = name
            new_plant_key = f"{bu_name}|{site_logical}"

        tags = node.get('tags', [])
        if not tags and name in canonical and ntype in ('workCenter', 'area', 'workUnit'):
            tags = canonical[name]

        for tag in tags:
            t_name     = tag['name']
            t_opc_name = tag.get('opcNodeName', t_name)
            data_type  = tag.get('dataType', 'Float')

            if 'opcPath' in tag:
                rel        = tag['opcPath'].split('/')
                target_opc = new_area + rel
            else:
                target_opc = new_opc + [t_opc_name]

            current = enterprise_obj
            for part in target_opc[:-1]:
                try:
                    current = await current.get_child([f"{idx}:{part}"])
                except Exception:
                    current = await current.add_object(idx, part)

            dt = (data_type or 'Float').strip()
            if dt in ('Float', 'Double', 'Real'):
                default, vt = 0.0,   ua.VariantType.Double
            elif dt in ('Int', 'Int16', 'Int32', 'Int64', 'Integer', 'UInt16', 'UInt32', 'UInt64'):
                default, vt = 0,     ua.VariantType.Int64
            elif dt in ('Bool', 'Boolean'):
                default, vt = False, ua.VariantType.Boolean
            elif dt in ('String', 'Str'):
                default, vt = "",    ua.VariantType.String
            elif dt in ('DateTime', 'Timestamp'):
                default = datetime.datetime.now(datetime.timezone.utc)
                vt      = ua.VariantType.DateTime
            else:
                default, vt = 0.0,   ua.VariantType.Double

            sim = tag.get('simulation')
            if not sim or not isinstance(sim, dict):
                sim = {"profile": "default"}
            elif "profile" not in sim:
                sim["profile"] = "default"

            # Seed the initial value. Control/hold tags (setpoints, requests)
            # start at their configured default so an optimizer connecting later
            # reads a sensible value — and, being held, it persists thereafter.
            init_val = default
            if "default" in sim:
                raw_def = sim["default"]
                try:
                    if vt in (ua.VariantType.Float, ua.VariantType.Double):
                        init_val = float(raw_def)
                    elif vt in (ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.Int64,
                                ua.VariantType.UInt16, ua.VariantType.UInt32, ua.VariantType.UInt64):
                        init_val = int(round(float(raw_def)))
                    elif vt == ua.VariantType.Boolean:
                        init_val = raw_def in (True, 1, "1", "true", "True", "on", "yes")
                    elif vt == ua.VariantType.String:
                        init_val = str(raw_def)
                except (TypeError, ValueError):
                    init_val = default

            var = await current.add_variable(idx, target_opc[-1], ua.Variant(init_val, vt))
            if str(tag.get('access', 'R')).upper() == 'RW':
                await var.set_writable()

            variables[tuple(target_opc)] = (var, sim, new_plant_key, default, vt)
            anomaly_key_map["".join(target_opc)] = var

        for child in node.get('children', []):
            await _walk(child, uns_parts + [name], new_opc, new_area, new_plant_key)

    for child in enterprise_node.get('children', []):
        await _walk(child, [], [], [], None)

    print(f"[factory] Dynamic address space ready — {len(variables)} tags")
    return variables, anomaly_key_map


# ================================================================
# MAIN SIMULATION LOOP
# ================================================================
async def run_simulation(variables, anomaly_key_map, stop_event: asyncio.Event, control_loops: dict = None):
    control_loops = control_loops or {}

    def _group_from_key(pk: str) -> str:
        return pk.split("|")[0] if pk and "|" in pk else ""

    plant_keys = set(pk for _, (_, _, pk, _, _) in variables.items() if pk)

    while not stop_event.is_set():
        sim_state = await _read_sim_state()
        simulator_running = bool(sim_state.get('simulator_running', True))

        # Tick every plant state machine
        for pk in plant_keys:
            plant_data = sim_state.get(pk, {})
            if isinstance(plant_data, bool):
                plant_data = {'running': plant_data}
            running = simulator_running and plant_data.get('running', False)
            ps = _get_plant_state(pk, _group_from_key(pk))
            ps.tick(running, plant_data)

        # ── Control-loop pre-pass ──────────────────────────────────────────────
        # Runs after plant states so a loop can honour its plant's run/fault
        # state, and before the OPC writes so setpoints/PVs are up to date. Reads
        # the live request value the optimizer last published into each OPC
        # request variable, then advances the controller and process value.
        for loop in control_loops.values():
            pk = loop.plant_key
            loop_running = bool(simulator_running)
            if loop_running and pk:
                pd = sim_state.get(pk, {})
                if isinstance(pd, bool):
                    pd = {'running': pd}
                ps = _get_plant_state(pk, _group_from_key(pk))
                loop_running = bool(pd.get('running', False)) and \
                    ps.state in (PlantState.RUNNING, PlantState.RECOVERY)
            elif not pk:
                loop_running = bool(simulator_running)
            req = None
            if loop.request_var is not None:
                try:
                    req = await loop.request_var.read_value()
                except Exception:
                    req = None
            # Read the live faceplate inputs (mode/enable/operator-SP/limits/
            # heartbeat) the operator (HMI) and optimizer own, so the handshake
            # decides which setpoint actually drives the loop this tick.
            hs = {}
            for _k, _v in loop.handshake_vars().items():
                try:
                    hs[_k] = await _v.read_value()
                except Exception:
                    hs[_k] = None
            loop.tick(req, loop_running, hs)

        # Snapshot anomaly overrides once per tick to avoid holding the lock during OPC writes
        async with _anomaly_lock:
            overrides_snapshot = dict(anomaly_overrides)

        # Write OPC-UA variables
        for idx, (opc_path, (var, sim, plant_key, default, vt)) in enumerate(list(variables.items())):
            try:
                anomaly_key = "".join(opc_path)
                override = overrides_snapshot.get(anomaly_key)
                if override is not None:
                    await var.write_value(override)
                    continue

                profile = sim.get("profile", "default")

                # Setpoint / command holds and faceplate inputs: never overwrite.
                # These are owned by the external writer (optimizer request,
                # heartbeat) or the operator (mode/enable/operator-SP/limits) and
                # persist in the OPC node between ticks.
                if profile in ("ctrl_request", "hold", "ctrl_mode", "ctrl_enable",
                               "ctrl_sp_operator", "ctrl_sp_lo", "ctrl_sp_hi",
                               "ctrl_heartbeat"):
                    continue

                # Closed-loop control tags read from the ControlLoop registry.
                if isinstance(profile, str) and profile.startswith("ctrl"):
                    loop = control_loops.get(_loop_id_for(opc_path, sim))
                    val  = loop.output(profile) if loop is not None else default
                else:
                    ps  = _get_plant_state(plant_key, _group_from_key(plant_key)) if plant_key \
                          else PlantState("__global__", "")
                    val = _profile_value(profile, ps, sim, default)

                if vt == ua.VariantType.Boolean:
                    await var.write_value(bool(val))
                elif vt in (ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.Int64,
                            ua.VariantType.UInt16, ua.VariantType.UInt32, ua.VariantType.UInt64):
                    await var.write_value(int(round(float(val))) if not isinstance(val, (str, bool)) else 0)
                elif vt in (ua.VariantType.Float, ua.VariantType.Double):
                    await var.write_value(float(val) if not isinstance(val, (str, bool)) else 0.0)
                elif vt == ua.VariantType.String:
                    await var.write_value(str(val))
                elif vt == ua.VariantType.DateTime:
                    if isinstance(val, datetime.datetime):
                        await var.write_value(val)
                else:
                    await var.write_value(val)

            except Exception:
                pass
            if idx and idx % 250 == 0:
                await asyncio.sleep(0)

        await asyncio.sleep(1.2)


# ================================================================
# TCP ANOMALY SERVER
# ================================================================
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        data = await reader.read(1024)
        if data:
            payload   = json.loads(data.decode('utf-8'))
            overrides = payload.get('anomaly_overrides')
            if overrides is not None:
                async with _anomaly_lock:
                    anomaly_overrides.update(overrides)
    except Exception:
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ================================================================
# MAIN
# ================================================================
async def main():
    global _anomaly_lock
    _anomaly_lock = asyncio.Lock()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # Windows' Proactor loop has no add_signal_handler; fall back to
        # signal.signal so the server also runs on a Windows dev box (in the
        # Linux container the loop-based handler is used).
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            try:
                signal.signal(sig, lambda *_: stop_event.set())
            except (ValueError, OSError):
                pass

    server = Server()
    await server.init()
    # Bind on opc_bind_ip (0.0.0.0 by default); advertised endpoint is logged for client reference
    server.set_endpoint(BIND_ENDPOINT)
    server.set_server_name("UNS Design Studio | github.com/Ilja0101")

    idx           = await server.register_namespace(NAMESPACE_URI)
    objects       = server.nodes.objects

    enterprise_name = _get_enterprise_name()
    enterprise_obj  = await objects.add_object(idx, enterprise_name)

    variables, anomaly_key_map = await _create_dynamic_address_space(server, idx, enterprise_obj)
    control_loops = _build_control_loops(variables)

    tcp_server = await asyncio.start_server(handle_client, TCP_SERVER_IP, TCP_SERVER_PORT)
    print(f"[factory] Anomaly TCP server listening on {TCP_SERVER_IP}:{TCP_SERVER_PORT}")

    await server.start()
    print(f"[factory] OPC UA Server listening on {BIND_ENDPOINT} (advertising {ADVERTISED_ENDPOINT}, root: {enterprise_name})")
    await asyncio.sleep(1.5)

    sim_task = asyncio.create_task(run_simulation(variables, anomaly_key_map, stop_event, control_loops))

    print("=" * 70)
    print("    UNS Design Studio  |  github.com/Ilja0101")
    print(f"    Listen    : {BIND_ENDPOINT}")
    print(f"    Endpoint  : {ADVERTISED_ENDPOINT}")
    print(f"    Root      : {enterprise_name}")
    print("=" * 70)

    try:
        await stop_event.wait()
    finally:
        sim_task.cancel()
        try:
            await sim_task
        except asyncio.CancelledError:
            pass
        tcp_server.close()
        await tcp_server.wait_closed()
        await server.stop()
        print("[factory] Server stopped.")

if __name__ == "__main__":
    asyncio.run(main())

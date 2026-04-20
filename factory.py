# factory.py
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
#
# ── Simulation profile catalogue ────────────────────────────────────────────────
#
#   OT / Process
#     oee                   Overall Equipment Effectiveness (%)
#     availability          Machine availability (%)
#     performance           Run rate vs rated speed (%)
#     quality               Good product ratio (%)
#     temperature_process   Process temperature, tracks setpoint
#     temperature_ambient   Ambient / room temperature
#     pressure              Process pressure
#     flow_rate             Flow rate, zero when stopped
#     level                 Tank/silo level (%), drains when running
#     motor_current         Motor current, spikes on fault
#     vibration             Bearing vibration, rises before fault
#     valve_position        Control valve position (%)
#     speed_rpm             Rotational speed, zero when stopped
#     boolean_running       TRUE only when Running
#     boolean_fault         TRUE only when Fault
#     boolean_alarm         TRUE during Fault + Recovery
#
#   Accumulators
#     accumulator_good      Good product tonnage
#     accumulator_bad       Rejected product tonnage
#     accumulator_energy    Cumulative kWh
#     accumulator_generic   Generic counter
#     counter_faults        Fault event counter
#
#   Maintenance / CMMS
#     mtbf                  Mean time between failures (hours)
#     mttr                  Mean time to repair (minutes)
#     pm_compliance         PM schedule compliance (%)
#     remaining_useful_life Estimated RUL (hours)
#     corrective_wo_count   Open corrective work orders
#     maintenance_cost      Cumulative maintenance cost (EUR)
#
#   Quality / Lab
#     quality_metric_pct    First-pass yield / in-spec rate (%)
#     quality_metric_cont   Continuous quality measure
#     quality_hold          Boolean — TRUE when out of spec
#     batch_id              String — cycles on each new batch
#     lot_id                String — cycles on each delivery
#
#   Logistics / Supply Chain
#     silo_level            Silo/tank level (%), drains + refills
#     inbound_tons          Cumulative received tonnage
#     outbound_tons         Cumulative dispatched tonnage
#     truck_id              String — changes on each delivery
#     days_of_supply        Derived from silo level
#     order_quantity        Integer — varies per order cycle
#     order_status          String — cycles through order lifecycle
#
#   ERP / Finance
#     erp_order_id          String — cycles on each production order
#     production_cost_eur   Accumulator
#     waste_cost_eur        Accumulator
#     revenue_eur           Accumulator
#     margin_pct            Derived margin (%)
#
#   Energy / Utilities
#     power_kw              Active power (kW)
#     steam_flow            Steam consumption (kg/h)
#     compressed_air        Compressed air (m³/h)
#     co2_kg                Cumulative CO₂
#
#   Recipe
#     recipe                Active recipe string — driven by sim_state.json
#
#   Fallback
#     default               Generic Gaussian walk

import asyncio
import os as _os
import signal
import threading
import logging
import random
import json
import socket
import time
import datetime
from opcua import Server, ua

logging.getLogger('opcua').setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARN)

# ================================================================
# CONFIG
# ================================================================
def _load_server_cfg():
    cfg_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'server_config.json')
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {}

_scfg            = _load_server_cfg()
_OPC_BIND_IP     = _scfg.get('opc_bind_ip',    '0.0.0.0')
_OPC_PORT        = int(_scfg.get('opc_port',   4840))
_TCP_PORT        = int(_scfg.get('tcp_port',   9999))
_HOST_IP         = (_scfg.get('host_ip') or '').strip()
_OPC_CLIENT_HOST = (_scfg.get('opc_client_host') or '').strip()

def _resolve_endpoint_host() -> str:
    if _HOST_IP:              return _HOST_IP
    if _OPC_CLIENT_HOST:      return _OPC_CLIENT_HOST
    if _OPC_BIND_IP and _OPC_BIND_IP != '0.0.0.0': return _OPC_BIND_IP
    return '127.0.0.1'

SERVER_ENDPOINT = f"opc.tcp://{_resolve_endpoint_host()}:{_OPC_PORT}/freeopcua/server/"
NAMESPACE_URI   = "http://VirtualUNS.com/uns"
TCP_SERVER_IP   = "0.0.0.0"
TCP_SERVER_PORT = _TCP_PORT

stop_flag         = False
anomaly_overrides = {}

# ================================================================
# SIM STATE  (read on every tick — picks up recipe changes live)
# ================================================================
SIM_STATE_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'sim_state.json')

def _read_sim_state() -> dict:
    try:
        with open(SIM_STATE_FILE) as f:
            data   = json.load(f)
            result = {}
            plants = data.get('plants', {})
            for k, v in plants.items():
                if isinstance(v, dict):
                    result[k] = v          # new format: {running, recipe, recipes, ...}
                else:
                    result[k] = {'running': bool(v)}  # legacy format: bool
            result['simulator_running'] = data.get('simulator_running', True)
            return result
    except Exception:
        return {}

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
        """
        Adjust simulation parameters when the active recipe changes.
        recipe_params comes from sim_state.json recipes list entry (optional).
        Falls back gracefully to group defaults if no params are provided.
        """
        self.active_recipe = recipe
        if not recipe_params:
            return
        p = self._GROUP_PARAMS.get(self.group, self._DEFAULT_PARAMS)
        # Apply overrides — recipe can tune any base parameter
        self._base_power    = recipe_params.get("base_power",    p["base_power"])
        self._infeed_rate   = recipe_params.get("infeed_rate",   p["infeed_rate"])
        self._product_price = recipe_params.get("product_price", p["product_price"])
        self._unit_cost     = recipe_params.get("unit_cost",     p["unit_cost"])
        self._avail_target  = recipe_params.get("avail_target",  p["avail_target"])
        self._perf_target   = recipe_params.get("perf_target",   p["perf_target"])
        self._qual_target   = recipe_params.get("qual_target",   p["qual_target"])

    # ── Main tick ─────────────────────────────────────────────────────────────────
    def tick(self, externally_running: bool, plant_sim_state: dict):
        """
        Advance simulation one tick (~1.2s).
        plant_sim_state: the dict from sim_state.json for this plant key,
                         e.g. {"running": true, "recipe": "Naturel", "recipes": [...]}
        """
        # ── Recipe update ─────────────────────────────────────────────────────────
        new_recipe = plant_sim_state.get("recipe", "")
        if new_recipe != self._last_recipe:
            # Find params for this recipe in the recipes list
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

            # Silo drain + truck arrival
            consumption  = self._infeed_rate / 3600.0 * 1.2
            self.level   = self._clamp(self.level - consumption * random.uniform(0.8, 1.2), 0, 100)
            if self.level < 20 and random.random() < 0.04:
                self.level        += random.uniform(25, 45)
                self.level         = min(self.level, 100)
                self.truck_id      = random.choice(self._TRUCK_IDS)
                self.lot_id        = f"LOT-{random.randint(5000, 9999)}"
                self.acc_inbound  += random.uniform(20, 50)
            self.days_of_supply = self._clamp(self.level / 7.5, 0.1, 30)

            # Accumulators
            rate        = self._infeed_rate / 3600.0 * 1.2
            good_rate   = rate * (self.quality / 100.0)
            bad_rate    = rate * (1 - self.quality / 100.0)
            self.acc_good      += good_rate  * random.uniform(0.9, 1.1)
            self.acc_bad       += bad_rate   * random.uniform(0.8, 1.2)
            self.acc_energy    += self.power_kw / 3600.0 * 1.2
            self.acc_generic   += random.uniform(0.01, 0.1)
            self.acc_outbound  += good_rate  * random.uniform(0.9, 1.05)
            self.acc_co2       += self.power_kw * 0.000233 / 3600 * 1.2
            self.acc_revenue   += good_rate  * self._product_price * random.uniform(0.98, 1.02)
            self.acc_prod_cost += (good_rate + bad_rate) * self._unit_cost * random.uniform(0.98, 1.02)
            self.acc_waste_cost += bad_rate  * self._unit_cost * 1.3
            self.margin_pct    = self._drift(self.margin_pct, 30.0, 0.005, 0.1, 5, 55)

            # Quality
            self.quality_metric_cont = self._drift(self.quality_metric_cont, 92.0, 0.01, 0.3, 50, 100)
            if self._quality_hold_ticks > 0:
                self._quality_hold_ticks -= 1
                self.quality_hold = True
            else:
                self.quality_hold = abs(self.quality_metric_cont - 92.0) > 5.0
                if self.quality_hold:
                    self._quality_hold_ticks = random.randint(10, 40)

            # Maintenance
            self.pm_compliance = self._clamp(self.pm_compliance + random.gauss(0, 0.05), 50, 100)
            self.rul           = self._clamp(self.rul - random.uniform(0.0003, 0.0008), 0, 9999)
            self.mtbf          = self._drift(self.mtbf, 72.0, 0.002, 0.1, 4, 300)
            self.mttr          = self._drift(self.mttr, 60.0, 0.002, 0.2, 5, 480)

            # Batch / order cycling
            self._batch_tick += 1
            if self._batch_tick > random.randint(2400, 7200):
                self._batch_tick  = 0
                self.batch_id     = f"BATCH-{random.randint(1000, 9999)}"
                self.erp_order_id = f"ORD-{random.randint(100000, 999999)}"
                self.order_qty    = random.randint(5000, 25000)

            self._order_tick += 1
            if self._order_tick > random.randint(600, 2400):
                self._order_tick       = 0
                self.order_status_idx  = (self.order_status_idx + 1) % len(self._ORDER_STATES)

        elif self.state == self.FAULT:
            self.availability  = self._clamp(self.availability - random.uniform(1.5, 5.0), 0, 100)
            self.performance   = self._clamp(self.performance  - random.uniform(0.5, 2.0), 0, 100)
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
    if p in ("accumulator_generic",
             "accumulator"):          return round(ps.acc_generic, 3)
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

    # ── Recipe profile ─────────────────────────────────────────────────────────
    if p == "recipe":
        return ps.active_recipe if ps.active_recipe else ""

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
    if ps.state == PlantState.FAULT:    std *= 0.2
    elif ps.state == PlantState.RECOVERY: std *= 0.5
    return float(max(lo, min(hi, current_value + random.gauss(0, std))))


# ================================================================
# SIMULATION PROFILE CATALOGUE  (read by app.py for UNS designer)
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
    "default":               {"label": "Generic Walk (fallback)",       "group": "Other"},
}


# ================================================================
# UNS CONFIG LOADER
# ================================================================
def _load_uns_config():
    path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'uns_config.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


# ================================================================
# DYNAMIC OPC-UA ADDRESS SPACE BUILDER
# ================================================================
def _create_dynamic_address_space(server, idx, enterprise_obj):
    cfg  = _load_uns_config()
    tree = cfg['tree']
    variables       = {}
    anomaly_key_map = {}

    canonical = {}
    def _collect_canonical(node):
        name = node.get('name', '')
        tags = node.get('tags', [])
        if tags and name and name not in canonical:
            canonical[name] = tags
        for child in node.get('children', []):
            _collect_canonical(child)
    _collect_canonical(tree)

    def _walk(node, uns_parts, opc_parts, area_opc_parts, plant_key):
        ntype    = node.get('type', '')
        name     = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name
        new_opc  = opc_parts + [opc_name]
        new_area = new_opc if ntype == 'area' else area_opc_parts

        new_plant_key = plant_key
        if ntype == 'site':
            bu_name       = opc_parts[-1] if opc_parts else ''
            new_plant_key = f"{bu_name}|{opc_name}"

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
                    current = current.get_child([f"{idx}:{part}"])
                except Exception:
                    current = current.add_object(idx, part)

            if data_type == 'Float':
                default, vt = 0.0,   ua.VariantType.Double
            elif data_type == 'Int':
                default, vt = 0,     ua.VariantType.Int64
            elif data_type == 'Bool':
                default, vt = False, ua.VariantType.Boolean
            elif data_type == 'String':
                default, vt = "",    ua.VariantType.String
            elif data_type == 'DateTime':
                default = datetime.datetime.now(datetime.timezone.utc)
                vt      = ua.VariantType.DateTime
            else:
                default, vt = 0.0,   ua.VariantType.Double

            var = current.add_variable(idx, target_opc[-1], default, vt)
            var.set_writable(str(tag.get('access', 'R')).upper() == 'RW')

            sim = tag.get('simulation')
            if not sim or not isinstance(sim, dict):
                sim = {"profile": "default"}
            elif "profile" not in sim:
                sim["profile"] = "default"

            variables[tuple(target_opc)] = (var, sim, new_plant_key)
            anomaly_key_map["".join(target_opc)] = var

        for child in node.get('children', []):
            _walk(child, uns_parts + [name], new_opc, new_area, new_plant_key)

    for child in tree.get('children', []):
        _walk(child, [], [], [], None)

    print(f"[factory] Dynamic address space ready — {len(variables)} tags")
    return variables, anomaly_key_map


# ================================================================
# MAIN SIMULATION LOOP
# ================================================================
async def run_simulation(variables, anomaly_key_map):
    def _group_from_key(pk: str) -> str:
        return pk.split("|")[0] if pk and "|" in pk else ""

    plant_keys = set(pk for _, (_, _, pk) in variables.items() if pk)

    while not stop_flag:
        sim_state = _read_sim_state()

        if not sim_state.get('simulator_running', True):
            await asyncio.sleep(1)
            continue

        # Tick every plant state machine
        for pk in plant_keys:
            plant_data = sim_state.get(pk, {})
            if isinstance(plant_data, bool):
                plant_data = {'running': plant_data}
            running = plant_data.get('running', False)
            ps = _get_plant_state(pk, _group_from_key(pk))
            ps.tick(running, plant_data)

        # Write OPC-UA variables
        for opc_path, (var, sim, plant_key) in list(variables.items()):
            try:
                anomaly_key = "".join(opc_path)
                if anomaly_key in anomaly_overrides and anomaly_overrides[anomaly_key] is not None:
                    var.set_value(anomaly_overrides[anomaly_key])
                    continue

                profile = sim.get("profile", "default")
                ps      = _get_plant_state(plant_key, _group_from_key(plant_key)) if plant_key \
                          else PlantState("__global__", "")
                val     = _profile_value(profile, ps, sim, var.get_value())

                current = var.get_value()
                if isinstance(current, bool):
                    var.set_value(bool(val))
                elif isinstance(current, int):
                    var.set_value(int(round(float(val))) if not isinstance(val, (str, bool)) else 0)
                elif isinstance(current, float):
                    var.set_value(float(val) if not isinstance(val, (str, bool)) else 0.0)
                elif isinstance(current, str):
                    var.set_value(str(val))
                elif isinstance(current, datetime.datetime):
                    if isinstance(val, datetime.datetime):
                        var.set_value(val)
                else:
                    var.set_value(val)

            except Exception:
                pass

        await asyncio.sleep(1.2)


# ================================================================
# TCP ANOMALY SERVER
# ================================================================
def handle_client(sock):
    global anomaly_overrides
    try:
        data = sock.recv(1024).decode('utf-8')
        if data:
            payload   = json.loads(data)
            overrides = payload.get('anomaly_overrides')
            if overrides is not None:
                anomaly_overrides.update(overrides)
    except Exception:
        pass
    finally:
        sock.close()

def start_tcp_server():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((TCP_SERVER_IP, TCP_SERVER_PORT))
        s.listen(5)
        print(f"[factory] Anomaly TCP server listening on {TCP_SERVER_IP}:{TCP_SERVER_PORT}")
        while not stop_flag:
            client, _ = s.accept()
            threading.Thread(target=handle_client, args=(client,), daemon=True).start()
    except Exception as e:
        print(f"[factory] TCP server error: {e}")


# ================================================================
# SHUTDOWN
# ================================================================
def signal_handler(_sig, _frame):
    global stop_flag
    stop_flag = True
    print("[factory] Shutdown signal received...")

signal.signal(signal.SIGINT,  signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ================================================================
# MAIN
# ================================================================
async def main():
    global stop_flag
    server = Server()
    server.set_endpoint(SERVER_ENDPOINT)
    server.set_server_name("UNS Design Studio | github.com/Ilja0101")

    idx            = server.register_namespace(NAMESPACE_URI)
    objects        = server.get_objects_node()
    enterprise_obj = objects.add_object(idx, "GlobalFoodCo")

    variables, anomaly_key_map = _create_dynamic_address_space(server, idx, enterprise_obj)

    server.start()
    print(f"[factory] OPC UA Server started on {SERVER_ENDPOINT}")
    await asyncio.sleep(1.5)

    asyncio.create_task(run_simulation(variables, anomaly_key_map))

    print("=" * 70)
    print("    UNS Design Studio  |  github.com/Ilja0101")
    print(f"    Endpoint  : {SERVER_ENDPOINT}")
    print(f"    Profiles  : {len(SIMULATION_PROFILES)} available")
    print("=" * 70)

    try:
        while not stop_flag:
            await asyncio.sleep(1)
    finally:
        server.stop()
        print("[factory] Server stopped.")

if __name__ == "__main__":
    threading.Thread(target=start_tcp_server, daemon=True).start()
    asyncio.run(main())

#!/usr/bin/env python3
"""
UNS Design Studio — Web Dashboard & REST API

Author : Ilja Bartels  |  https://github.com/Ilja0101
License: MIT  |  https://github.com/Ilja0101/UNS-Design-Studio
"""

import asyncio
import hmac
import os, sys, time, json, signal, atexit, hashlib
from datetime import datetime
from quart import Quart, render_template, jsonify, request, Response
from json_persistence import load_json, save_json_atomic
from sim_state_service import get_site_recipes, merge_sim_state_update, sync_sim_state_with_uns
from uns_tree import enterprise_structure, resolve_enterprise_root
import shift

# ── Adjust path so recipe.py is importable ────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('UNS_DATA_DIR') or ('/data' if os.path.isdir('/data') else BASE_DIR)

# ── Quart app ──────────────────────────────────────────────────────────────────
app = Quart(__name__)

# ── Auth (HTTP Basic, single shared demo credential) ────────────────────────
# No login UI here, and no per-user store — this mirrors the rest of the UNS
# family's approach for apps without a built-in login page: gate everything
# behind one shared admin credential (UDS_ADMIN_USERNAME/UDS_ADMIN_PASSWORD).
# Unset (the default) leaves the app open, same as before.
_AUTH_USER = os.environ.get('UDS_ADMIN_USERNAME', '')
_AUTH_PASS = os.environ.get('UDS_ADMIN_PASSWORD', '')

@app.before_request
async def _require_basic_auth():
    if not (_AUTH_USER and _AUTH_PASS):
        return None
    if request.path == '/healthz':
        return None
    auth = request.authorization
    if (
        auth is not None
        and auth.type == 'basic'
        and hmac.compare_digest(auth.username or '', _AUTH_USER)
        and hmac.compare_digest(auth.password or '', _AUTH_PASS)
    ):
        return None
    return Response(
        'Unauthenticated', 401,
        {'WWW-Authenticate': 'Basic realm="UNS Design Studio", charset="UTF-8"'},
    )

# ── Config file paths ─────────────────────────────────────────────────────────
UNS_CONFIG_FILE      = os.path.join(DATA_DIR, 'uns_config.json')
SCHEMAS_CONFIG_FILE  = os.path.join(DATA_DIR, 'payload_schemas.json')
SERVER_CONFIG_FILE   = os.path.join(DATA_DIR, 'server_config.json')
SIM_STATE_FILE       = os.path.join(DATA_DIR, 'sim_state.json')
VIZ_CONFIG_FILE      = os.path.join(DATA_DIR, 'visualization.json')

def _json_log(msg: str):
    print(msg, flush=True)

def _load_server_cfg() -> dict:
    return load_json(SERVER_CONFIG_FILE, {}, logger=_json_log, label='server_config.json')

def _save_server_cfg(data: dict):
    if not save_json_atomic(SERVER_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='server_config.json'):
        raise OSError(f"Could not write {SERVER_CONFIG_FILE}")

_scfg = _load_server_cfg()

# ── Shift-hours config (persisted; seeded from UDS_SHIFT_* env on first boot) ──
SHIFT_CONFIG_FILE = os.path.join(DATA_DIR, 'shift_config.json')

def _load_shift_cfg() -> dict:
    raw = load_json(SHIFT_CONFIG_FILE, None, logger=_json_log, label='shift_config.json')
    if not isinstance(raw, dict):
        seeded = shift.seed_from_env()
        _save_shift_cfg(seeded)          # first boot: persist the env-seeded config
        return seeded
    return shift.normalize(raw)

def _save_shift_cfg(data: dict):
    if not save_json_atomic(SHIFT_CONFIG_FILE, shift.normalize(data), ensure_ascii=False,
                            logger=_json_log, label='shift_config.json'):
        raise OSError(f"Could not write {SHIFT_CONFIG_FILE}")

# ── Enterprise structure (read live from uns_config.json) ──────────────────────
_ENTERPRISE_FALLBACK = {
    "CrispCraft": ["FactoryAntwerp",   "FactoryGhent"],
    "FlakeMill":   ["FactoryLeiden",   "FactoryGroningen"],
    "FrostLine":     ["FactoryDortmund",  "FactoryBremen",  "FactoryHanover",
                      "FactoryLeipzig",  "FactoryCologne",  "FactoryDresden"],
    "RootCore":  ["FactoryLille"],
    "SugarWorks": ["FactoryBruges", "FactoryLiege"],
}

def _get_enterprise_structure() -> dict:
    """Return {businessUnitName: [siteName, …]} from uns_config.json.

    NOTE: Site names are used as-is (no 'Factory' prefix). This ensures
    plant_key = f"{group}|{plant}" matches sim_state.json keys correctly,
    and respects the actual naming in imported templates.
    """
    cfg = load_json(UNS_CONFIG_FILE, None, logger=_json_log, label='uns_config.json')
    return enterprise_structure(cfg, _ENTERPRISE_FALLBACK)

def _get_namespace_uri() -> str:
    try:
        cfg = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
        return cfg.get('namespaceUri', NAMESPACE_URI) if isinstance(cfg, dict) else NAMESPACE_URI
    except Exception:
        return NAMESPACE_URI

# ── DYNAMIC ENTERPRISE NAME (FIXED) ───────────────────────────────────────────
def _get_enterprise_name() -> str:
    """Return the root enterprise name from uns_config.json."""
    try:
        cfg = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
        name, _ = resolve_enterprise_root(cfg.get('tree', {}) if isinstance(cfg, dict) else {})
        return name
    except Exception:
        return 'GlobalFoodCo'

def _get_site_recipes(site_node: dict) -> list:
    return get_site_recipes(site_node)

def _ensure_sim_state_synced():
    """Ensure sim_state.json has all plants from current uns_config.json."""
    cfg = load_json(UNS_CONFIG_FILE, None, logger=_json_log, label='uns_config.json')
    if not isinstance(cfg, dict):
        return
    sim_state = load_json(SIM_STATE_FILE, {'plants': {}, 'simulator_running': False}, logger=_json_log, label='sim_state.json')
    if not isinstance(sim_state, dict):
        sim_state = {'plants': {}, 'simulator_running': False}
    sim_state = sync_sim_state_with_uns(cfg, sim_state)
    if not save_json_atomic(SIM_STATE_FILE, sim_state, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        print("Warning: Could not write sim_state.json")

def _get_division_meta() -> dict:
    """Return {buName: {color, icon, label}} from uns_config.json BU nodes."""
    _DEFAULT = {'color': '#58a6ff', 'icon': '🏭', 'label': ''}
    result = {}

    def _business_units(node: dict):
        if not isinstance(node, dict):
            return
        if node.get('type') == 'businessUnit':
            yield node
            return
        for child in node.get('children', []):
            yield from _business_units(child)

    try:
        cfg = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
        for bu in _business_units(cfg.get('tree', {})):
            name = bu.get('name', '')
            result[name] = {
                'color': bu.get('color', _DEFAULT['color']),
                'icon':  bu.get('icon',  _DEFAULT['icon']),
                'label': bu.get('description', bu.get('label', '')),
            }
    except Exception:
        pass
    return result


NAMESPACE_URI = "http://VirtualUNS.com/uns"

# ── Shared state ───────────────────────────────────────────────────────────────
_state = {
    'opc_host':    _scfg.get('opc_client_host', '127.0.0.1'),
    'opc_port':    int(_scfg.get('opc_port', 4840)),
    'tcp_port':    int(_scfg.get('tcp_port', 9999)),
    'server_proc': None,
    'server_logs': [],
    'opc_connected': False,
    'plant_data':  {},
    'viz_values':  {},
    # Bridge
    'bridge_proc':  None,
    'bridge_stats': {
        'connected': False, 'opc_ok': False,
        'published': 0, 'errors': 0, 'rate': 0.0,
        'protocol': '—', 'ts': 0.0,
    },
    # Shift scheduler: last computed status (served by /api/shift) + cached config.
    'shift_cfg':    {},
    'shift_status': {},
}

# asyncio.Lock instances — protect regions that span await points
_locks = {
    'proc':        asyncio.Lock(),  # server proc start/stop sequence
    'bridge':      asyncio.Lock(),  # bridge proc start/stop sequence
    'sim_control': asyncio.Lock(),  # plant start/stop with reset delay
    'data':        asyncio.Lock(),  # plant_data / viz_values (written by poll, read by routes)
    'shift':       asyncio.Lock(),  # shift config read/write vs the scheduler loop
}

# factory.py reads sim_state.json once per 1.2s simulation tick.  Keep this
# just above that interval so the forced stopped snapshot is observed without
# adding an unnecessary full 2s wait to every plant start request.
SIM_STATE_START_RESET_SECONDS = 1.35
SERVER_START_TIMEOUT_SECONDS = float(os.getenv('UNS_SERVER_START_TIMEOUT', '90'))
SERVER_STOP_PORT_RELEASE_SECONDS = float(os.getenv('UNS_SERVER_STOP_TIMEOUT', '8'))

# ── Helper functions ───────────────────────────────────────────────────────────
def _endpoint():
    return f"opc.tcp://{_state['opc_host']}:{_state['opc_port']}/freeopcua/server/"

def _container_local_host(host: str) -> str:
    host = (host or '').strip()
    if host in ('', '0.0.0.0', '::'):
        return '127.0.0.1'
    cfg = _load_server_cfg()
    advertised = (cfg.get('host_ip') or '').strip()
    bind_ip = (cfg.get('opc_bind_ip') or '').strip()
    if advertised and host == advertised and bind_ip in ('', '0.0.0.0', '::'):
        return '127.0.0.1'
    return host

def _normalize_connect_host(host: str) -> str:
    host = (host or '').strip()
    return '127.0.0.1' if host in ('', '0.0.0.0', '::') else host

async def _opc_tcp_port_open(timeout: float = 0.25) -> bool:
    """Return True when the configured OPC-UA TCP endpoint accepts connections."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(_state['opc_host'], int(_state['opc_port'])),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False

async def _wait_for_opc_port(open_expected: bool, timeout_seconds: float, proc=None) -> bool:
    """Wait for the configured OPC-UA TCP port to become open/closed."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if proc is not None and proc.returncode is not None:
            return False
        if await _opc_tcp_port_open() is open_expected:
            return True
        await asyncio.sleep(0.2)
    return await _opc_tcp_port_open() is open_expected

async def _factory_accepts_connections() -> bool:
    return await _opc_tcp_port_open()

async def _ensure_factory_ready(reason: str = '') -> tuple[bool, str]:
    if _server_alive():
        if await _factory_accepts_connections():
            return True, 'OPC UA server is ready'
        if await _wait_for_opc_port(True, min(15.0, SERVER_START_TIMEOUT_SECONDS), proc=_state['server_proc']):
            return True, 'OPC UA server is ready'
        return False, 'OPC UA server process is running, but the OPC UA port is not ready yet'

    if await _factory_accepts_connections():
        _log(f"[server] OPC UA port is open without a dashboard-managed factory process ({reason})")
        return True, 'OPC UA server is ready'

    _log(f"[server] Factory process is not running; attempting restart ({reason})")
    ok, msg = await start_factory_server()
    if not ok:
        return False, msg
    if await _factory_accepts_connections():
        return True, msg
    return False, 'Factory process started, but the OPC UA port is not ready yet'

def _default_recipe(group: str, plant: str = '') -> str:
    try:
        sim = load_json(SIM_STATE_FILE, {}, logger=_json_log, label='sim_state.json')
        plant_key = f"{group}|{plant}" if plant else None
        if plant_key:
            val = sim.get('plants', {}).get(plant_key, {})
            if isinstance(val, dict):
                recipes = val.get('recipes', [])
                if recipes:
                    r = recipes[0]
                    return r['name'] if isinstance(r, dict) else str(r)
        return ''
    except Exception:
        return ''

async def _send_anomaly(overrides: dict):
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(_state['opc_host'], _state['tcp_port']),
            timeout=3,
        )
        writer.write(json.dumps({'anomaly_overrides': overrides}).encode())
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception as e:
        _log(f"[anomaly TCP error] {e}")
        return False

def _log(msg: str):
    _state['server_logs'].append(msg)
    if len(_state['server_logs']) > 600:
        _state['server_logs'].pop(0)

def _num(value, digits=1, default=0.0):
    try:
        return round(float(value), digits)
    except Exception:
        return default

# ── Dashboard metric path discovery ──────────────────────────────────────────
_DASH_PROFILES = {
    'oee':              'oee',
    'power_kw':         'power',
    'accumulator_good': 'good_tons',
    'inbound_tons':     'trucks_recv',
}
_metric_path_cache: dict = {}
_metric_path_cache_ts: float = 0.0

def _find_dashboard_metric_paths(group: str, plant: str) -> dict:
    global _metric_path_cache, _metric_path_cache_ts
    cache_key = f"{group}|{plant}"
    now = time.time()
    if now - _metric_path_cache_ts > 30:
        _metric_path_cache = {}
        _metric_path_cache_ts = now
    if cache_key in _metric_path_cache:
        return _metric_path_cache[cache_key]

    result = {}
    found  = set()
    cfg = load_json(UNS_CONFIG_FILE, None, logger=_json_log, label='uns_config.json')
    if not isinstance(cfg, dict):
        _metric_path_cache[cache_key] = result
        return result

    def _walk(node, opc_parts, area_opc_parts):
        if len(found) == len(_DASH_PROFILES):
            return
        ntype    = node.get('type', '')
        name     = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name
        new_opc  = opc_parts + [opc_name]
        new_area = new_opc if ntype == 'area' else area_opc_parts
        for tag in node.get('tags', []):
            sim     = tag.get('simulation', {})
            profile = (sim.get('profile', '') if isinstance(sim, dict) else '').lower()
            if profile in _DASH_PROFILES and profile not in found:
                t_opc = tag.get('opcNodeName', tag.get('name', ''))
                if 'opcPath' in tag:
                    path = new_area + tag['opcPath'].split('/')
                else:
                    path = new_opc + [t_opc]
                result[_DASH_PROFILES[profile]] = path
                found.add(profile)
        for child in node.get('children', []):
            _walk(child, new_opc, new_area)

    for bu in cfg.get('tree', {}).get('children', []):
        if bu.get('name') == group:
            for site in bu.get('children', []):
                if site.get('name') == plant:
                    _walk(site, [group], [])
            break

    _metric_path_cache[cache_key] = result
    return result


async def _collect_plant_data(ent, idx):
    """Collect plant data.
    • Running/recipe state — authoritative from sim_state.json
    • Metrics (OEE, power, etc.) — dynamically resolved via uns_config.json profiles,
      navigated from OPC.  Fails gracefully to 0.0 for any missing node.
    """
    sim_state = load_json(SIM_STATE_FILE, {'plants': {}}, logger=_json_log, label='sim_state.json')
    if not isinstance(sim_state, dict):
        sim_state = {'plants': {}}

    async def _read_path(path):
        if not path:
            return 0.0
        try:
            node = ent
            for part in path:
                node = await node.get_child([f"{idx}:{part}"])
            val = await node.read_value()
            return float(val) if val is not None else 0.0
        except Exception:
            return 0.0

    plants = {}
    for group, plant_names in _get_enterprise_structure().items():
        try:
            group_node = await ent.get_child([f"{idx}:{group}"])
        except Exception:
            continue

        for plant in plant_names:
            plant_key = f"{group}|{plant}"
            plant_val = sim_state.get('plants', {}).get(plant_key, False)

            if isinstance(plant_val, dict):
                process_state = bool(plant_val.get('running', False))
                recipe        = plant_val.get('recipe', '--NA--') or '--NA--'
            else:
                process_state = bool(plant_val)
                recipe        = '--NA--'

            site_exists = False
            for site_name in (f"Factory{plant}", plant):
                try:
                    await group_node.get_child([f"{idx}:{site_name}"])
                    site_exists = True
                    break
                except Exception:
                    pass

            if not site_exists:
                plants[plant_key] = {
                    'group': group, 'plant': plant,
                    'process_state': process_state, 'recipe': recipe,
                    'maint_status': 'Running' if process_state else 'Stopped',
                    'opc_ready': False,
                    'oee': 0.0, 'power': 0.0, 'good_tons': 0.0, 'trucks_recv': 0.0,
                }
                continue

            metric_paths = _find_dashboard_metric_paths(group, plant)
            plants[plant_key] = {
                'group':         group,
                'plant':         plant,
                'process_state': process_state,
                'recipe':        recipe,
                'maint_status':  'Running' if process_state else 'Stopped',
                'opc_ready':     True,
                'oee':        _num(await _read_path(metric_paths.get('oee',        []))),
                'power':      _num(await _read_path(metric_paths.get('power',      []))),
                'good_tons':  _num(await _read_path(metric_paths.get('good_tons',  []))),
                'trucks_recv':_num(await _read_path(metric_paths.get('trucks_recv', []))),
            }
    return plants

def _plant_data_from_sim_state(force_stopped: bool = False) -> dict:
    sim_state = load_json(SIM_STATE_FILE, {'plants': {}}, logger=_json_log, label='sim_state.json')
    if not isinstance(sim_state, dict):
        sim_state = {'plants': {}}

    plants = {}
    for group, plant_names in _get_enterprise_structure().items():
        for plant in plant_names:
            plant_key = f"{group}|{plant}"
            plant_val = sim_state.get('plants', {}).get(plant_key, False)
            if isinstance(plant_val, dict):
                process_state = bool(plant_val.get('running', False))
                recipe = plant_val.get('recipe', '--NA--') or '--NA--'
            else:
                process_state = bool(plant_val)
                recipe = '--NA--'
            if force_stopped:
                process_state = False
            plants[plant_key] = {
                'group': group, 'plant': plant,
                'process_state': process_state, 'recipe': recipe,
                'maint_status': 'Running' if process_state else 'Stopped',
                'opc_ready': False,
                'oee': 0.0, 'power': 0.0, 'good_tons': 0.0, 'trucks_recv': 0.0,
            }
    return plants

def _sim_state_plants(running: bool) -> dict:
    sim_state = load_json(SIM_STATE_FILE, {}, logger=_json_log, label='sim_state.json')
    current = sim_state.get('plants', {}) if isinstance(sim_state, dict) else {}
    result = {}
    for pk, existing in current.items():
        if isinstance(existing, dict):
            merged = dict(existing)
            merged['running'] = running
            result[pk] = merged
        else:
            result[pk] = {'running': running}
    return result

def _read_sim_state_raw() -> dict:
    data = load_json(SIM_STATE_FILE, {'plants': {}, 'simulator_running': True}, logger=_json_log, label='sim_state.json')
    return data if isinstance(data, dict) else {'plants': {}, 'simulator_running': True}

def _plant_running(plant_key: str, sim_state: dict) -> bool:
    v = sim_state.get('plants', {}).get(plant_key, False)
    if isinstance(v, dict):
        return bool(v.get('running', False))
    return bool(v)

def _plant_recipe(plant_key: str, sim_state: dict) -> str:
    v = sim_state.get('plants', {}).get(plant_key, {})
    if isinstance(v, dict):
        return v.get('recipe', '')
    return ''

def _plant_recipes(plant_key: str, sim_state: dict) -> list:
    v = sim_state.get('plants', {}).get(plant_key, {})
    if isinstance(v, dict):
        return v.get('recipes', [])
    return []

def _write_sim_state(data: dict):
    current = load_json(SIM_STATE_FILE, {'plants': {}, 'simulator_running': True}, logger=_json_log, label='sim_state.json')
    current = merge_sim_state_update(current, data)
    if not save_json_atomic(SIM_STATE_FILE, current, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        raise OSError(f"Could not write {SIM_STATE_FILE}")

def _all_sim_state_plants_stopped(sim_state: dict) -> bool:
    plants = sim_state.get('plants', {}) if isinstance(sim_state, dict) else {}
    for value in plants.values():
        if isinstance(value, dict):
            if bool(value.get('running', False)):
                return False
        elif bool(value):
            return False
    return not bool(sim_state.get('simulator_running', False)) if isinstance(sim_state, dict) else True

def _mark_all_plants_stopped(reason: str = '') -> bool:
    state = _read_sim_state_raw()
    already_stopped = _all_sim_state_plants_stopped(state)
    state['plants'] = _sim_state_plants(False)
    state['simulator_running'] = False
    if not save_json_atomic(SIM_STATE_FILE, state, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        raise OSError(f"Could not write {SIM_STATE_FILE}")
    for plant in _state['plant_data'].values():
        if isinstance(plant, dict):
            plant['process_state'] = False
            plant['maint_status'] = 'Stopped'
    if reason:
        _log(f"[sim-state] Marked all plants stopped: {reason}")
    return not already_stopped

def _write_all_plants_running(reason: str = ''):
    state = _read_sim_state_raw()
    state['plants'] = _sim_state_plants(True)
    state['simulator_running'] = True
    if not save_json_atomic(SIM_STATE_FILE, state, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        raise OSError(f"Could not write {SIM_STATE_FILE}")
    if reason:
        _log(f"[sim-state] Marked all plants running: {reason}")

def _write_single_plant_running(plant_key: str, running: bool, reason: str = ''):
    _write_sim_state({plant_key: {'running': bool(running)}})
    sim_state = load_json(SIM_STATE_FILE, {}, logger=_json_log, label='sim_state.json')
    current_plants = sim_state.get('plants', {}) if isinstance(sim_state, dict) else {}
    if bool(running):
        _write_sim_state({'simulator_running': True})
    else:
        any_running = any(
            (v.get('running', False) if isinstance(v, dict) else bool(v))
            for k, v in current_plants.items() if k != plant_key
        )
        _write_sim_state({'simulator_running': any_running})
    if reason:
        _log(f"[sim-state] Marked plant {plant_key} {'running' if running else 'stopped'}: {reason}")

async def _reset_then_start_all_plants(delay_seconds: float = SIM_STATE_START_RESET_SECONDS):
    async with _locks['sim_control']:
        _ensure_sim_state_synced()
        _mark_all_plants_stopped('start-all reset before start')
        _log(f"[sim-state] Waiting {delay_seconds:.1f}s before start-all so factory.py can observe stopped state")
        await asyncio.sleep(delay_seconds)
        if not await _factory_accepts_connections():
            _mark_all_plants_stopped('factory process stopped during start-all reset')
            return False, 'OPC UA server stopped before plants could be started'
        _write_all_plants_running('start-all after reset')
        return True, f'All plants started after {delay_seconds:.1f}s reset'

async def _reset_then_start_plant(plant_key: str, delay_seconds: float = SIM_STATE_START_RESET_SECONDS):
    async with _locks['sim_control']:
        _ensure_sim_state_synced()
        _write_single_plant_running(plant_key, False, 'single-plant reset before start')
        _log(f"[sim-state] Waiting {delay_seconds:.1f}s before starting {plant_key} so factory.py can observe stopped state")
        await asyncio.sleep(delay_seconds)
        if not await _factory_accepts_connections():
            _write_single_plant_running(plant_key, False, 'factory process stopped during single-plant reset')
            return False, 'OPC UA server stopped before plant could be started'
        _write_single_plant_running(plant_key, True, 'single-plant after reset')
        return True, f'Plant started after {delay_seconds:.1f}s reset'

def _reconcile_sim_state_with_process(reason: str = ''):
    try:
        if not _server_alive():
            _mark_all_plants_stopped(reason or 'factory process is not running')
    except Exception as e:
        _log(f"[sim-state] Reconcile failed: {e}")

def _server_alive() -> bool:
    p = _state['server_proc']
    return p is not None and p.returncode is None

# ── Server process management ──────────────────────────────────────────────────
async def _capture_output(proc):
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            _log(line.decode('utf-8', errors='replace').rstrip())
    except Exception:
        pass

async def start_factory_server():
    async with _locks['proc']:
        if _state['server_proc'] and _state['server_proc'].returncode is None:
            return False, "Server is already running"
        _state['server_proc'] = None
        _ensure_sim_state_synced()
        _mark_all_plants_stopped('starting fresh factory process')
        if await _opc_tcp_port_open():
            msg = f"OPC UA port {_state['opc_port']} is already in use; stop the existing process before starting the dashboard-managed server"
            _log(f"[server] {msg}")
            return False, msg
        factory_py = os.path.join(BASE_DIR, 'factory.py')
        if not os.path.exists(factory_py):
            return False, f"factory.py not found at {factory_py}"
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, factory_py,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=BASE_DIR,
            )
            _state['server_proc'] = proc
            asyncio.create_task(_capture_output(proc))

            if not await _wait_for_opc_port(True, SERVER_START_TIMEOUT_SECONDS, proc=proc):
                try:
                    if proc.returncode is None:
                        proc.terminate()
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=3)
                        except asyncio.TimeoutError:
                            proc.kill()
                            await proc.wait()
                except Exception:
                    pass
                recent_logs = ' | '.join(_state['server_logs'][-5:])
                exit_part = f"exited with code {proc.returncode}" if proc.returncode is not None else "did not open the OPC UA port"
                msg = f"Server process {exit_part}. Recent logs: {recent_logs}"
                _log(f"[server] {msg}")
                _state['server_proc'] = None
                _mark_all_plants_stopped('factory process failed to start')
                return False, msg

            return True, "Server process started and OPC UA port is accepting connections"
        except Exception as e:
            _state['server_proc'] = None
            try:
                _mark_all_plants_stopped('factory process start raised exception')
            except Exception:
                pass
            return False, str(e)

async def stop_factory_server():
    async with _locks['proc']:
        try:
            _mark_all_plants_stopped('factory process stopping')
        except Exception as e:
            _log(f"[sim-state] Stop pre-reconcile failed: {e}")
        proc = _state['server_proc']
        if proc is None or proc.returncode is not None:
            _state['server_proc'] = None
            try:
                _mark_all_plants_stopped('factory process was already stopped')
            except Exception as e:
                _log(f"[sim-state] Stop reconcile failed: {e}")
            return True, "Server was not running"
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=6)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception:
            pass
        _state['server_proc'] = None
        if not await _wait_for_opc_port(False, SERVER_STOP_PORT_RELEASE_SECONDS):
            _log(f"[server] OPC UA port {_state['opc_port']} still accepts connections after factory process stop")
        try:
            _mark_all_plants_stopped('factory process stopped')
        except Exception as e:
            _log(f"[sim-state] Stop reconcile failed: {e}")
        return True, "Server stopped"

async def _dashboard_shutdown():
    try:
        await stop_bridge()
    except Exception:
        pass
    try:
        await stop_factory_server()
    except Exception:
        try:
            _mark_all_plants_stopped('dashboard shutdown')
        except Exception:
            pass

def _install_shutdown_handlers():
    def _sync_shutdown():
        for key in ('bridge_proc', 'server_proc'):
            p = _state.get(key)
            if p is not None and p.returncode is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        try:
            _mark_all_plants_stopped('dashboard shutdown')
        except Exception:
            pass

    atexit.register(_sync_shutdown)

    # Quart/hypercorn handle SIGINT and SIGTERM on their own (graceful shutdown).
    # We only need to ensure our sync cleanup runs via atexit above.

# ── OPC UA node-cache polling ──────────────────────────────────────────────────
async def _poll_loop():
    """Robust async polling for dynamic factory.py structure using asyncua."""
    from asyncua import Client
    last_endpoint = None
    last_enterprise = None

    while True:
        current_endpoint = _endpoint()
        current_enterprise = _get_enterprise_name()

        if current_endpoint != last_endpoint or current_enterprise != last_enterprise:
            last_endpoint = current_endpoint
            last_enterprise = current_enterprise
            _log(f"[poll] Endpoint or enterprise changed → {current_endpoint} | Root: {current_enterprise}")

        try:
            async with Client(current_endpoint) as client:
                ns_idx = None
                ent    = None
                current_namespace = _get_namespace_uri()
                for attempt in range(12):
                    try:
                        ns_idx = await client.get_namespace_index(current_namespace)
                    except Exception as e:
                        if "BadNoMatch" in str(e):
                            await asyncio.sleep(0.5)
                            continue
                        raise

                    try:
                        root = client.nodes.root
                        ent = await root.get_child(["0:Objects", f"{ns_idx}:{current_enterprise}"])
                        break
                    except Exception:
                        await asyncio.sleep(0.5)
                        continue

                if ent is None:
                    _state['opc_connected'] = False
                    _state['viz_values'] = {}
                    _log(f"[poll] OPC UA available but root node '{current_enterprise}' not ready yet")
                    await asyncio.sleep(1)
                    continue

                _state['opc_connected'] = True
                _log(f"[poll] Successfully connected to OPC UA server — Enterprise: {current_enterprise}")

                async with _locks['data']:
                    _state['plant_data'] = await _collect_plant_data(ent, ns_idx)

                while _endpoint() == current_endpoint and _state['opc_connected']:
                    try:
                        async with _locks['data']:
                            _state['plant_data'] = await _collect_plant_data(ent, ns_idx)
                            _state['viz_values'] = await _collect_viz_values(ent, ns_idx)
                    except Exception as e:
                        _log(f"[poll] Data collection error (triggering reconnect): {e}")
                        _state['opc_connected'] = False
                        _state['viz_values'] = {}
                        break
                    await asyncio.sleep(3)

        except Exception as e:
            _state['opc_connected'] = False
            _state['viz_values'] = {}
            err_str = str(e)
            if "10061" in err_str or "ConnectionRefused" in err_str or "Connection refused" in err_str:
                _log("[poll] OPC UA unavailable: Connection refused - Is the factory server running?")
            elif "BadNoMatch" in err_str:
                _log(f"[poll] OPC UA unavailable: BadNoMatch (root node '{current_enterprise}' not found)")
            else:
                _log(f"[poll] OPC UA unavailable: {type(e).__name__} - {err_str}")
            await asyncio.sleep(4)

# ── OPC UA write helper (one-shot client per command) ─────────────────────────
async def _opc_write(fn):
    """Connect, call fn(client, idx, enterprise), disconnect. Returns (ok, msg)."""
    from asyncua import Client
    try:
        enterprise_name = _get_enterprise_name()
        async with Client(_endpoint()) as client:
            idx  = await client.get_namespace_index(_get_namespace_uri())
            root = client.nodes.root
            ent  = await root.get_child(["0:Objects", f"{idx}:{enterprise_name}"])
            result = await fn(client, idx, ent)
        return True, result or "OK"
    except Exception as e:
        return False, str(e)

# ── Plant tag introspection (for dynamic anomaly UI) ─────────────────────────
def _get_plant_tags(group: str, plant: str) -> list:
    cfg = load_json(UNS_CONFIG_FILE, None, logger=_json_log, label='uns_config.json')
    if not isinstance(cfg, dict):
        return []
    tree     = cfg.get('tree', {})
    site_name = plant[len('Factory'):] if plant.startswith('Factory') else plant
    results = []
    def _walk(node, opc_parts, area_opc_parts, wc_label):
        ntype    = node.get('type', '')
        name     = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name
        new_opc  = opc_parts + [opc_name]
        new_area = new_opc if ntype == 'area' else area_opc_parts
        new_wc   = name    if ntype == 'workCenter' else wc_label
        for tag in node.get('tags', []):
            t_name     = tag['name']
            t_opc_name = tag.get('opcNodeName', t_name)
            if 'opcPath' in tag:
                rel     = tag['opcPath'].split('/')
                target_opc = list(new_area) + rel
            else:
                target_opc = new_opc + [t_opc_name]
            results.append({
                'name':        t_name,
                'anomalyKey':  ''.join(target_opc),
                'dataType':    tag.get('dataType', 'Float'),
                'unit':        tag.get('unit', ''),
                'workCenter':  new_wc,
                'access':      tag.get('access', 'R'),
            })
        for child in node.get('children', []):
            _walk(child, new_opc, new_area, new_wc)
    for bu in tree.get('children', []):
        if bu.get('name') == group:
            for site in bu.get('children', []):
                if site.get('name') == site_name:
                    _walk(site, [group], [], '')
            break
    return results

# ── Periodic sync loop ────────────────────────────────────────────────────────
async def _periodic_sync_loop(interval: int = 10):
    while True:
        try:
            _ensure_sim_state_synced()
        except Exception:
            pass
        await asyncio.sleep(interval)

# ── Shift-hours scheduler ─────────────────────────────────────────────────────
SHIFT_POLL_SECONDS = 30

def _plants_running_count() -> tuple[int, int]:
    """(running, total) across all plants, read from sim_state."""
    state = _read_sim_state_raw()
    plants = state.get('plants', {}) if isinstance(state, dict) else {}
    running = sum(
        1 for v in plants.values()
        if (v.get('running', False) if isinstance(v, dict) else bool(v))
    )
    return running, len(plants)

async def _shift_loop(interval: int = SHIFT_POLL_SECONDS):
    """Clock the plants in/out on the persisted schedule. Off-shift parks the
    plants; the factory server and bridge are left untouched. Idempotent: only
    acts on a real transition, and reasserts if the state drifts."""
    _shift_desired = None
    while True:
        try:
            async with _locks['shift']:
                cfg = dict(_state['shift_cfg']) or _load_shift_cfg()
                _state['shift_cfg'] = cfg
            tz, _ = shift.resolve_tz(cfg.get('tz', 'UTC'))
            now = datetime.now(tz)
            running, total = _plants_running_count()

            if cfg.get('enabled'):
                start_min = shift.parse_hhmm(cfg['start'])
                end_min = shift.parse_hhmm(cfg['end'])
                days = shift.parse_days(cfg['days'])
                want_open = shift.shift_open(now, start_min, end_min, days)
                if want_open and running == 0 and _server_alive():
                    _log('[shift] 🔔 Shift bell — clocking the plants in.')
                    await _reset_then_start_all_plants()
                    running, total = _plants_running_count()
                elif not want_open and running > 0:
                    verb = 'day off' if now.weekday() not in days else 'end of shift'
                    _log(f'[shift] 🌙 {verb} — clocking the plants out.')
                    _mark_all_plants_stopped('shift schedule: off-hours')
                    running, total = _plants_running_count()
                _shift_desired = want_open

            _state['shift_status'] = shift.compute_status(cfg, now, running, total)
        except Exception as e:
            _log(f'[shift] loop error: {e}')
        await asyncio.sleep(interval)

# ── Quart startup hook ────────────────────────────────────────────────────────
@app.before_serving
async def startup():
    _ensure_sim_state_synced()
    _mark_all_plants_stopped('dashboard startup')
    _install_shutdown_handlers()
    _state['shift_cfg'] = _load_shift_cfg()
    asyncio.create_task(_periodic_sync_loop(interval=10))
    asyncio.create_task(_poll_loop())
    asyncio.create_task(_shift_loop())
    print()
    print("==============================================================")
    print("UNS Design Studio")
    print("Dashboard: http://localhost:5000")
    print("==============================================================")
    print()

# ── Quart routes ───────────────────────────────────────────────────────────────
@app.route('/')
async def index():
    return await render_template(
        'index.html',
        structure=_get_enterprise_structure(),
        division_meta=_get_division_meta(),
    )

@app.route('/api/status')
async def api_status():
    _reconcile_sim_state_with_process('status poll found no factory process')
    server_running = _server_alive()
    server_ready = server_running and await _opc_tcp_port_open()
    if not server_ready:
        _state['opc_connected'] = False
        plants = _plant_data_from_sim_state(force_stopped=True)
        _state['plant_data'] = plants
    else:
        async with _locks['data']:
            plants = dict(_state['plant_data'])
        if not plants:
            plants = _plant_data_from_sim_state(force_stopped=False)
    bstats = dict(_state['bridge_stats'])
    cfg = _load_bridge_cfg()
    cfg.pop('password', None)
    struct = _get_enterprise_structure()
    struct_hash = hashlib.md5(json.dumps(struct, sort_keys=True).encode()).hexdigest()[:8]
    enterprise_name = _get_enterprise_name()
    return jsonify(dict(
        server_running=server_running,
        server_ready=server_ready,
        opc_connected=server_ready and _state['opc_connected'],
        opc_host=_state['opc_host'],
        opc_port=_state['opc_port'],
        plants=plants,
        bridge_running=_bridge_alive(),
        bridge_stats=bstats,
        bridge_cfg=cfg,
        structure_hash=struct_hash,
        enterprise_name=enterprise_name,
        ts=time.time(),
    ))

@app.route('/api/logs')
async def api_logs():
    logs = list(_state['server_logs'][-150:])
    return jsonify({'logs': logs})

@app.route('/api/shift', methods=['GET'])
async def api_shift_get():
    """Current shift status (state, schedule, next change, plants running)."""
    status = _state.get('shift_status')
    if not status:
        cfg = _state.get('shift_cfg') or _load_shift_cfg()
        tz, _ = shift.resolve_tz(cfg.get('tz', 'UTC'))
        running, total = _plants_running_count()
        status = shift.compute_status(cfg, datetime.now(tz), running, total)
    return jsonify(status)

@app.route('/api/shift', methods=['POST'])
async def api_shift_save():
    """Update and persist the shift schedule, then apply it on the next tick."""
    data = await request.get_json() or {}
    cfg = shift.normalize(data)
    async with _locks['shift']:
        _save_shift_cfg(cfg)
        _state['shift_cfg'] = cfg
    tz, _ = shift.resolve_tz(cfg.get('tz', 'UTC'))
    running, total = _plants_running_count()
    status = shift.compute_status(cfg, datetime.now(tz), running, total)
    _state['shift_status'] = status
    return jsonify({'ok': True, 'status': status})

@app.route('/api/server/start', methods=['POST'])
async def api_server_start():
    ok, msg = await start_factory_server()
    return jsonify({'ok': ok, 'msg': msg}), 200 if ok else 409

@app.route('/api/server/stop', methods=['POST'])
async def api_server_stop():
    ok, msg = await stop_factory_server()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/config', methods=['POST'])
async def api_config():
    data = await request.get_json() or {}
    if 'host' in data:
        _state['opc_host'] = data['host'].strip()
    if 'port' in data:
        _state['opc_port'] = int(data['port'])
    return jsonify({'ok': True, 'host': _state['opc_host'], 'port': _state['opc_port']})

@app.route('/api/server-config', methods=['GET'])
async def api_server_config_get():
    cfg = _load_server_cfg()
    cfg.setdefault('opc_bind_ip',    '0.0.0.0')
    cfg.setdefault('opc_port',       4840)
    cfg.setdefault('opc_client_host','127.0.0.1')
    cfg.setdefault('tcp_port',       9999)
    cfg.setdefault('host_ip',        '127.0.0.1')
    return jsonify(cfg)

@app.route('/api/server-config', methods=['POST'])
async def api_server_config_save():
    data = await request.get_json() or {}
    cfg  = _load_server_cfg()
    for key in ('opc_bind_ip', 'opc_client_host', 'host_ip'):
        if key in data:
            cfg[key] = data[key].strip()
    for key in ('opc_port', 'tcp_port'):
        if key in data:
            cfg[key] = int(data[key])
    _save_server_cfg(cfg)
    _state['opc_host'] = cfg.get('opc_client_host', _state['opc_host'])
    _state['opc_port'] = int(cfg.get('opc_port',    _state['opc_port']))
    _state['tcp_port'] = int(cfg.get('tcp_port',    _state['tcp_port']))
    return jsonify({'ok': True})

@app.route('/api/plants/start-all', methods=['POST'])
async def api_start_all():
    ready, ready_msg = await _ensure_factory_ready('start-all requested')
    if not ready:
        _mark_all_plants_stopped('start-all requested but factory was not ready')
        return jsonify({'ok': False, 'msg': ready_msg}), 409
    ok, msg = await _reset_then_start_all_plants()
    return jsonify({'ok': ok, 'msg': msg}), 200 if ok else 409

@app.route('/api/plants/stop-all', methods=['POST'])
async def api_stop_all():
    _ensure_sim_state_synced()
    _mark_all_plants_stopped('stop-all requested')
    return jsonify({'ok': True, 'msg': 'Plants stopped'})

@app.route('/api/plant/control', methods=['POST'])
async def api_plant_control():
    data   = await request.get_json() or {}
    group  = data['group']
    plant  = data['plant']
    action = data['action']
    value  = data['value']
    if action == 'set_state':
        plant_key = f"{group}|{plant}"
        if bool(value):
            ready, ready_msg = await _ensure_factory_ready(f'plant start requested for {plant_key}')
            if not ready:
                _mark_all_plants_stopped('plant start requested but factory was not ready')
                return jsonify({'ok': False, 'msg': ready_msg}), 409
            ok, msg = await _reset_then_start_plant(plant_key)
            if not ok:
                return jsonify({'ok': False, 'msg': msg}), 409
        else:
            async with _locks['sim_control']:
                _write_single_plant_running(plant_key, False, 'single-plant stop requested')
    elif action == 'set_recipe':
        plant_key = f"{group}|{plant}"
        _write_sim_state({plant_key: {'recipe': str(value)}})

    return jsonify({'ok': True, 'msg': f'{action} applied'})

@app.route('/api/recipes/<group>/<plant>')
async def api_recipes(group, plant):
    plant_key = f"{group}|{plant}"

    recipes = []
    try:
        cfg = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
        for bu in cfg.get('tree', {}).get('children', []):
            if bu.get('name') == group:
                for site in bu.get('children', []):
                    if site.get('name') == plant and site.get('type') == 'site':
                        recipes = [
                            r['name'] if isinstance(r, dict) else str(r)
                            for r in site.get('recipes', [])
                        ]
                        break
                break
    except Exception:
        pass

    active = ''
    try:
        sim_state = load_json(SIM_STATE_FILE, {}, logger=_json_log, label='sim_state.json')
        plant_val = sim_state.get('plants', {}).get(plant_key, {}) if isinstance(sim_state, dict) else {}
        active = plant_val.get('recipe', '') if isinstance(plant_val, dict) else ''
    except Exception:
        pass

    return jsonify({'recipes': recipes, 'active': active})

@app.route('/api/equipment/<group>')
async def api_equipment(group):
    result = {}
    try:
        cfg = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
        for bu in cfg.get('tree', {}).get('children', []):
            if bu.get('name') == group:
                for site in bu.get('children', []):
                    if site.get('type') == 'site':
                        def _collect(node):
                            for tag in node.get('tags', []):
                                if str(tag.get('access', 'R')).upper() == 'RW':
                                    result[tag.get('name', '')] = tag.get('name', '').lower().replace(' ', '_').replace('-', '_')
                            for child in node.get('children', []):
                                _collect(child)
                        _collect(site)
                        break
                break
    except Exception:
        pass
    return jsonify({'equipment': result})

@app.route('/api/plant/tags/<group>/<plant>')
async def api_plant_tags(group, plant):
    tags = _get_plant_tags(group, plant)
    return jsonify({'tags': tags})

@app.route('/api/anomaly/inject', methods=['POST'])
async def api_anomaly():
    data      = await request.get_json() or {}
    overrides = data.get('overrides', {})
    duration  = float(data.get('duration', 30))
    if not overrides:
        return jsonify({'ok': False, 'msg': 'No overrides specified'})

    async def _run():
        await _send_anomaly(overrides)
        if duration > 0:
            await asyncio.sleep(duration)
            await _send_anomaly({k: None for k in overrides})

    asyncio.create_task(_run())
    return jsonify({'ok': True, 'tags': len(overrides), 'duration': duration})

# ── Broker Bridge management ───────────────────────────────────────────────────
BRIDGE_CONFIG_FILE = os.path.join(DATA_DIR, 'bridge_config.json')
BRIDGE_PY          = os.path.join(BASE_DIR, 'bridge.py')

def _load_bridge_cfg() -> dict:
    return load_json(BRIDGE_CONFIG_FILE, {}, logger=_json_log, label='bridge_config.json')

def _save_bridge_cfg(data: dict):
    if not save_json_atomic(BRIDGE_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='bridge_config.json'):
        raise OSError(f"Could not write {BRIDGE_CONFIG_FILE}")

def _bridge_alive() -> bool:
    p = _state['bridge_proc']
    return p is not None and p.returncode is None

async def _capture_bridge_output(proc):
    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            line = line.decode('utf-8', errors='replace').rstrip()
            if line.startswith('[BRIDGE_STATS] '):
                try:
                    stats = json.loads(line[15:])
                    _state['bridge_stats'].update(stats)
                except Exception:
                    pass
            else:
                _log(f"[bridge] {line}")
    except Exception:
        pass

async def start_bridge():
    async with _locks['bridge']:
        if _state['bridge_proc'] and _state['bridge_proc'].returncode is None:
            return False, "Bridge is already running"
        if not os.path.exists(BRIDGE_PY):
            return False, f"bridge.py not found at {BRIDGE_PY}"
        ready, ready_msg = await _ensure_factory_ready('bridge start requested')
        if not ready:
            _state['bridge_stats'].update({'connected': False, 'opc_ok': False, 'rate': 0.0})
            return False, f"OPC UA server is not ready: {ready_msg}"
        try:
            cfg = _load_bridge_cfg()
            cfg['opc_host'] = _container_local_host(_state['opc_host'])
            cfg['opc_port'] = _state['opc_port']
            cfg['broker_host'] = _normalize_connect_host(cfg.get('broker_host', 'localhost'))
            _save_bridge_cfg(cfg)
        except Exception as e:
            return False, f"Could not update bridge config: {e}"
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, BRIDGE_PY,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=BASE_DIR,
            )
            _state['bridge_proc'] = proc
            asyncio.create_task(_capture_bridge_output(proc))
            return True, "Bridge process started"
        except Exception as e:
            return False, str(e)

async def stop_bridge():
    async with _locks['bridge']:
        proc = _state['bridge_proc']
        if proc is None or proc.returncode is not None:
            _state['bridge_proc'] = None
            return True, "Bridge was not running"
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=6)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception:
            pass
        _state['bridge_proc'] = None
        _state['bridge_stats'].update({'connected': False, 'opc_ok': False, 'rate': 0.0})
        return True, "Bridge stopped"

@app.route('/api/bridge/start', methods=['POST'])
async def api_bridge_start():
    ok, msg = await start_bridge()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/bridge/stop', methods=['POST'])
async def api_bridge_stop():
    ok, msg = await stop_bridge()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/bridge/config', methods=['GET'])
async def api_bridge_cfg_get():
    cfg = _load_bridge_cfg()
    cfg.pop('password', None)
    return jsonify(cfg)

@app.route('/api/bridge/config', methods=['POST'])
async def api_bridge_cfg_save():
    data = await request.get_json() or {}
    cfg  = _load_bridge_cfg()
    for key in ('protocol', 'broker_host', 'broker_port', 'topic_prefix',
                'interval', 'username', 'password'):
        if key in data:
            cfg[key] = data[key]
    if 'broker_host' in cfg:
        cfg['broker_host'] = _normalize_connect_host(cfg.get('broker_host', 'localhost'))
    _save_bridge_cfg(cfg)
    if _bridge_alive():
        await stop_bridge()
        ok, msg = await start_bridge()
        return jsonify({'ok': ok, 'restarted': True, 'msg': msg})
    return jsonify({'ok': True, 'restarted': False})

# ── Asset Library ──────────────────────────────────────────────────────────────
ASSET_LIBRARY_FILE = os.path.join(DATA_DIR, 'asset_library.json')

def _load_asset_library() -> dict:
    data = load_json(ASSET_LIBRARY_FILE, {"assets": []}, logger=_json_log, label='asset_library.json')
    return data if isinstance(data, dict) else {"assets": []}

@app.route('/api/asset-library', methods=['GET'])
async def api_asset_library():
    return jsonify(_load_asset_library())

# ── Simulation Profile Catalogue ───────────────────────────────────────────────
@app.route('/api/simulation-profiles', methods=['GET'])
async def api_simulation_profiles():
    profiles = {
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
    group_order = [
        "OT / Process", "Accumulators", "Maintenance / CMMS",
        "Quality / Lab", "Logistics", "ERP / Finance",
        "Energy / Utilities", "Recipe", "Other"
    ]
    grouped = {}
    for pid, meta in profiles.items():
        g = meta.get("group", "Other")
        grouped.setdefault(g, []).append({"id": pid, "label": meta.get("label", pid)})
    result = []
    for g in group_order:
        if g in grouped:
            result.append({"group": g, "profiles": sorted(grouped[g], key=lambda x: x["label"])})
    for g in grouped:
        if g not in group_order:
            result.append({"group": g, "profiles": sorted(grouped[g], key=lambda x: x["label"])})
    return jsonify(result)

# ── UNS Live View ──────────────────────────────────────────────────────────────
@app.route('/live')
async def uns_live():
    return await render_template('uns_live.html')

@app.websocket('/mqtt-ws')
async def mqtt_ws_proxy():
    """Proxy MQTT-over-WebSocket to the local Mosquitto broker.
    Lets the browser connect to the dashboard host instead of a separate port.
    """
    import websockets
    from quart import websocket as ws
    subprotocols = ws.headers.get('Sec-Websocket-Protocol', '').split(',')
    subprotocols = [s.strip() for s in subprotocols if s.strip()]
    broker_url = f"ws://localhost:{_state.get('mqtt_ws_port', 8083)}/mqtt"
    try:
        async with websockets.connect(
            broker_url,
            subprotocols=subprotocols or ['mqtt'],
            max_size=2**20,
        ) as broker_ws:
            async def client_to_broker():
                while True:
                    data = await ws.receive()
                    await broker_ws.send(data)

            async def broker_to_client():
                async for msg in broker_ws:
                    if isinstance(msg, bytes):
                        await ws.send(msg)
                    else:
                        await ws.send(msg)

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_broker()),
                 asyncio.create_task(broker_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except Exception:
        pass

@app.route('/manual')
async def user_manual():
    return await render_template('manual.html')

@app.route('/settings')
async def settings_page():
    return await render_template('settings.html')

# ── UNS Topic Designer ─────────────────────────────────────────────────────────
@app.route('/uns')
async def uns_editor():
    return await render_template('uns_editor.html')

@app.route('/api/uns', methods=['GET'])
async def api_uns_get():
    data = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
    return jsonify(data if isinstance(data, dict) else {})

@app.route('/api/uns', methods=['POST'])
async def api_uns_save():
    data = await request.get_json() or {}
    data['lastModified'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    if not save_json_atomic(UNS_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='uns_config.json'):
        return jsonify({'ok': False, 'error': 'Could not write UNS config'}), 500
    restarted = []
    factory_was_running = _server_alive()
    if factory_was_running:
        _state['opc_connected'] = False
        await asyncio.sleep(1)
        await stop_factory_server()
        await asyncio.sleep(1)
        ok, _ = await start_factory_server()
        if not ok:
            await asyncio.sleep(3)
            ok, _ = await start_factory_server()
        if ok:
            restarted.append('factory')
            global _metric_path_cache, _metric_path_cache_ts
            _metric_path_cache = {}
            _metric_path_cache_ts = 0.0
            _ensure_sim_state_synced()

            async def _delayed_bridge_restart():
                await asyncio.sleep(4)
                if _bridge_alive():
                    await stop_bridge()
                    await start_bridge()

            asyncio.create_task(_delayed_bridge_restart())
    return jsonify({'ok': True, 'restarted': restarted})

# ── Payload Schema Designer ───────────────────────────────────────────────────
@app.route('/payload-schemas')
async def payload_schemas_page():
    return await render_template('payload_schemas.html')

@app.route('/api/payload-schemas', methods=['GET'])
async def api_schemas_get():
    data = load_json(SCHEMAS_CONFIG_FILE, {'schemas': []}, logger=_json_log, label='payload_schemas.json')
    return jsonify(data if isinstance(data, dict) else {'schemas': []})

@app.route('/api/payload-schemas', methods=['POST'])
async def api_schemas_save():
    data = await request.get_json() or {}
    if not save_json_atomic(SCHEMAS_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='payload_schemas.json'):
        return jsonify({'ok': False, 'error': 'Could not write payload schemas'}), 500
    return jsonify({'ok': True})

# ── Visualization (SCADA mimic) ───────────────────────────────────────────────
import viz_service

def _suggest_kind(name): return viz_service.suggest_kind(name)
def _load_viz_cfg(): return viz_service.load_viz_cfg(VIZ_CONFIG_FILE)
def _save_viz_cfg(data): viz_service.save_viz_cfg(VIZ_CONFIG_FILE, data)
def _walk_viz_entities(): return viz_service.walk_entities(UNS_CONFIG_FILE)
def _viz_resolve_tag_path(entity_id, tag_name):
    return viz_service.resolve_tag_path(UNS_CONFIG_FILE, entity_id, tag_name)

async def _collect_viz_values(ent, idx):
    """Bridge viz_service.collect_values_async to a live OPC client (poll loop only)."""
    async def read(path):
        try:
            n = ent
            for part in path:
                n = await n.get_child([f"{idx}:{part}"])
            return await n.read_value()
        except Exception:
            return None
    return await viz_service.collect_values_async(
        _load_viz_cfg().get('gauges', []),
        _viz_resolve_tag_path,
        read,
    )

@app.route('/viz')
async def viz_page():
    return await render_template('visualization.html')

@app.route('/api/viz/config', methods=['GET'])
async def api_viz_get():
    return jsonify(_load_viz_cfg())

@app.route('/api/viz/config', methods=['POST'])
async def api_viz_save():
    data = await request.get_json() or {}
    data.setdefault('version', 1)
    data['lastModified'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    _save_viz_cfg(data)
    return jsonify({'ok': True})

@app.route('/api/viz/entities', methods=['GET'])
async def api_viz_entities():
    mapped   = _load_viz_cfg().get('entities', {})
    entities = _walk_viz_entities()
    for e in entities:
        cur = mapped.get(e['id'], {})
        e['suggestion'] = _suggest_kind(e['name'])
        e['kind']       = cur.get('kind') or e['suggestion']
        e['mapped']     = bool(cur.get('kind'))
    return jsonify({'kinds': viz_service.EQUIPMENT_KINDS, 'entities': entities})

@app.route('/api/viz/values', methods=['GET'])
async def api_viz_values():
    values = dict(_state.get('viz_values') or {})
    return jsonify({
        'values':    values,
        'opc_ready': bool(_state.get('opc_connected')),
        'ts':        time.time(),
    })

@app.route('/api/viz/tags/<path:entity_id>', methods=['GET'])
async def api_viz_tags(entity_id):
    return jsonify({'tags': viz_service.entity_tags(UNS_CONFIG_FILE, entity_id)})

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

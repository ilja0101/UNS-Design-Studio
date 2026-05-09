#!/usr/bin/env python3
"""
UNS Design Studio — Web Dashboard & REST API

Author : Ilja Bartels  |  https://github.com/Ilja0101
License: MIT  |  https://github.com/Ilja0101/UNS-Design-Studio
"""

import os, sys, time, json, socket, threading, subprocess, hashlib, atexit, signal
from flask import Flask, render_template, jsonify, request
from json_persistence import load_json, save_json_atomic
from sim_state_service import get_site_recipes, merge_sim_state_update, sync_sim_state_with_uns
from uns_tree import enterprise_structure, resolve_enterprise_root

# ── Adjust path so recipe.py is importable ────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── Config file paths ─────────────────────────────────────────────────────────
UNS_CONFIG_FILE      = os.path.join(BASE_DIR, 'uns_config.json')
SCHEMAS_CONFIG_FILE  = os.path.join(BASE_DIR, 'payload_schemas.json')
SERVER_CONFIG_FILE   = os.path.join(BASE_DIR, 'server_config.json')
SIM_STATE_FILE       = os.path.join(BASE_DIR, 'sim_state.json')
VIZ_CONFIG_FILE      = os.path.join(BASE_DIR, 'visualization.json')

def _json_log(msg: str):
    print(msg, flush=True)

def _load_server_cfg() -> dict:
    return load_json(SERVER_CONFIG_FILE, {}, logger=_json_log, label='server_config.json')

def _save_server_cfg(data: dict):
    if not save_json_atomic(SERVER_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='server_config.json'):
        raise OSError(f"Could not write {SERVER_CONFIG_FILE}")

_scfg = _load_server_cfg()

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
    """Return the root enterprise name from uns_config.json.
    Supports both legacy (tree IS enterprise) and wrapper (tree.children[0] is enterprise) layouts."""
    try:
        cfg = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
        name, _ = resolve_enterprise_root(cfg.get('tree', {}) if isinstance(cfg, dict) else {})
        return name
    except Exception:
        return 'GlobalFoodCo'

def _get_site_recipes(site_node: dict) -> list:
    """Return the recipe definitions stored directly on a site node.
    Recipes are defined in uns_config.json as site.recipes = [{name, params}, ...]
    and edited via the Recipes tab in the UNS designer."""
    return get_site_recipes(site_node)

def _ensure_sim_state_synced():
    """Ensure sim_state.json has all plants from current uns_config.json.
    FIXED: Now ALWAYS refreshes the 'recipes' list for every plant when the UNS Designer saves changes.
    This solves the "recipes added in designer are not persisted / not selectable" issue."""
    cfg = load_json(UNS_CONFIG_FILE, None, logger=_json_log, label='uns_config.json')
    if not isinstance(cfg, dict):
        return  # Can't sync without config
    
    sim_state = load_json(SIM_STATE_FILE, {'plants': {}, 'simulator_running': False}, logger=_json_log, label='sim_state.json')
    if not isinstance(sim_state, dict):
        sim_state = {'plants': {}, 'simulator_running': False}
    sim_state = sync_sim_state_with_uns(cfg, sim_state)
    
    # Save updated sim_state
    if not save_json_atomic(SIM_STATE_FILE, sim_state, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        print("Warning: Could not write sim_state.json")

def _get_division_meta() -> dict:
    """Return {buName: {color, icon, label}} from uns_config.json BU nodes.
    Falls back to generic defaults for any group not found."""
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
}
_locks = {
    'logs':   threading.Lock(),
    'data':   threading.Lock(),
    'proc':   threading.Lock(),
    'bridge': threading.Lock(),
    'sim_control': threading.Lock(),
}

# factory.py reads sim_state.json once per 1.2s simulation tick.  Keep this
# just above that interval so the forced stopped snapshot is observed without
# adding an unnecessary full 2s wait to every plant start request.
SIM_STATE_START_RESET_SECONDS = 1.35
SERVER_START_TIMEOUT_SECONDS = 12.0
SERVER_STOP_PORT_RELEASE_SECONDS = 8.0

def _start_periodic_sync(interval: int = 10):
    """Start a background thread that periodically calls _ensure_sim_state_synced()."""
    def _worker():
        while True:
            try:
                _ensure_sim_state_synced()
            except Exception:
                pass
            time.sleep(interval)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

# ── Helper functions ───────────────────────────────────────────────────────────
def _endpoint():
    return f"opc.tcp://{_state['opc_host']}:{_state['opc_port']}/freeopcua/server/"

def _container_local_host(host: str) -> str:
    """Return a loopback-safe host for child processes inside this container.

    The dashboard may advertise the Docker host/LAN IP so external OPC-UA
    clients can discover a usable endpoint, but subprocesses running in the same
    container should connect to the local listener directly. This avoids bridge
    failures when `host_ip` is set to an address that is reachable externally but
    not hairpin-routable from inside the container.
    """
    host = (host or '').strip()
    if host in ('', '0.0.0.0', '::'):
        return '127.0.0.1'
    cfg = _load_server_cfg()
    advertised = (cfg.get('host_ip') or '').strip()
    bind_ip = (cfg.get('opc_bind_ip') or '').strip()
    if advertised and host == advertised and bind_ip in ('', '0.0.0.0', '::'):
        return '127.0.0.1'
    return host

def _opc_tcp_port_open(timeout: float = 0.25) -> bool:
    """Return True when the configured OPC-UA TCP endpoint accepts connections."""
    try:
        with socket.create_connection((_state['opc_host'], int(_state['opc_port'])), timeout=timeout):
            return True
    except OSError:
        return False

def _wait_for_opc_port(open_expected: bool, timeout_seconds: float, proc=None) -> bool:
    """Wait for the configured OPC-UA TCP port to become open/closed.

    When waiting for startup with a child process, stop early if the child exits.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        if _opc_tcp_port_open() is open_expected:
            return True
        time.sleep(0.2)
    return _opc_tcp_port_open() is open_expected

def _default_recipe(group: str, plant: str = '') -> str:
    """Return the first recipe name for a plant from sim_state.json, or empty string."""
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

def _send_anomaly(overrides: dict):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3)
            s.connect((_state['opc_host'], _state['tcp_port']))
            s.send(json.dumps({'anomaly_overrides': overrides}).encode())
        return True
    except Exception as e:
        _log(f"[anomaly TCP error] {e}")
        return False

def _log(msg: str):
    with _locks['logs']:
        _state['server_logs'].append(msg)
        if len(_state['server_logs']) > 600:
            _state['server_logs'].pop(0)

def _read_opc(node, path, default=None):
    try:
        current = node
        for step in path:
            current = current.get_child([step])
        value = current.get_value()
        return default if value is None else value
    except Exception:
        return default

def _num(value, digits=1, default=0.0):
    try:
        return round(float(value), digits)
    except Exception:
        return default

# ── Dashboard metric path discovery ──────────────────────────────────────────
# Maps simulation profile → dashboard field name
_DASH_PROFILES = {
    'oee':              'oee',
    'power_kw':         'power',
    'accumulator_good': 'good_tons',
    'inbound_tons':     'trucks_recv',
}
_metric_path_cache: dict = {}
_metric_path_cache_ts: float = 0.0

def _find_dashboard_metric_paths(group: str, plant: str) -> dict:
    """Return {field: [opc_path_from_enterprise_root]} for each dashboard metric.
    Scans uns_config.json once per cache TTL (30s).  Uses same OPC naming as
    factory.py — site nodes get a 'Factory' prefix."""
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


def _collect_plant_data(ent, idx):
    """Collect plant data.
    • Running/recipe state — authoritative from sim_state.json
    • Metrics (OEE, power, etc.) — dynamically resolved via uns_config.json profiles,
      navigated from OPC.  Fails gracefully to 0.0 for any missing node.
    """
    sim_state = load_json(SIM_STATE_FILE, {'plants': {}}, logger=_json_log, label='sim_state.json')
    if not isinstance(sim_state, dict):
        sim_state = {'plants': {}}

    def _read_path(path):
        """Read an OPC value given a path list starting from enterprise root."""
        if not path:
            return 0.0
        try:
            node = ent
            for part in path:
                node = node.get_child([f"{idx}:{part}"])
            val = node.get_value()
            return float(val) if val is not None else 0.0
        except Exception:
            return 0.0

    plants = {}
    for group, plant_names in _get_enterprise_structure().items():
        try:
            group_node = ent.get_child([f"{idx}:{group}"])
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

            # Verify site node exists (try Factory{plant} first — factory.py convention,
            # then fall back to bare plant name for any future convention changes)
            site_exists = False
            for site_name in (f"Factory{plant}", plant):
                try:
                    group_node.get_child([f"{idx}:{site_name}"])
                    site_exists = True
                    break
                except Exception:
                    pass

            if not site_exists:
                # Site not in OPC tree yet (server still starting) — opc_ready=False
                # tells the dashboard to show '--' instead of misleading zeros
                plants[plant_key] = {
                    'group': group, 'plant': plant,
                    'process_state': process_state, 'recipe': recipe,
                    'maint_status': 'Running' if process_state else 'Stopped',
                    'opc_ready': False,
                    'oee': 0.0, 'power': 0.0, 'good_tons': 0.0, 'trucks_recv': 0.0,
                }
                continue

            # Discover metric OPC paths from uns_config and read live values
            metric_paths = _find_dashboard_metric_paths(group, plant)
            plants[plant_key] = {
                'group':         group,
                'plant':         plant,
                'process_state': process_state,
                'recipe':        recipe,
                'maint_status':  'Running' if process_state else 'Stopped',
                'opc_ready':     True,
                'oee':        _num(_read_path(metric_paths.get('oee',        []))),
                'power':      _num(_read_path(metric_paths.get('power',      []))),
                'good_tons':  _num(_read_path(metric_paths.get('good_tons',  []))),
                'trucks_recv':_num(_read_path(metric_paths.get('trucks_recv', []))),
            }
    return plants

def _plant_data_from_sim_state(force_stopped: bool = False) -> dict:
    """Build dashboard plant payload from sim_state.json without OPC values.

    Used when the managed factory process is stopped or the OPC-UA port is not
    ready so the dashboard never renders stale live data from the last poll.
    """
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
    """Return {plant_key: {running: bool}} for every plant, preserving existing recipe data."""
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
    """Return raw sim_state.json content."""
    data = load_json(SIM_STATE_FILE, {'plants': {}, 'simulator_running': True}, logger=_json_log, label='sim_state.json')
    return data if isinstance(data, dict) else {'plants': {}, 'simulator_running': True}

def _plant_running(plant_key: str, sim_state: dict) -> bool:
    """Extract running bool from either old (bool) or new (dict) plant state format."""
    v = sim_state.get('plants', {}).get(plant_key, False)
    if isinstance(v, dict):
        return bool(v.get('running', False))
    return bool(v)

def _plant_recipe(plant_key: str, sim_state: dict) -> str:
    """Extract active recipe string from plant state."""
    v = sim_state.get('plants', {}).get(plant_key, {})
    if isinstance(v, dict):
        return v.get('recipe', '')
    return ''

def _plant_recipes(plant_key: str, sim_state: dict) -> list:
    """Extract recipe list for a plant."""
    v = sim_state.get('plants', {}).get(plant_key, {})
    if isinstance(v, dict):
        return v.get('recipes', [])
    return []

def _write_sim_state(data: dict):
    """Merge data into sim_state.json. Handles both old bool and new dict plant formats."""
    current = load_json(SIM_STATE_FILE, {'plants': {}, 'simulator_running': True}, logger=_json_log, label='sim_state.json')
    current = merge_sim_state_update(current, data)

    if not save_json_atomic(SIM_STATE_FILE, current, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        raise OSError(f"Could not write {SIM_STATE_FILE}")

def _all_sim_state_plants_stopped(sim_state: dict) -> bool:
    """Return True when no persisted plant state claims to be running."""
    plants = sim_state.get('plants', {}) if isinstance(sim_state, dict) else {}
    for value in plants.values():
        if isinstance(value, dict):
            if bool(value.get('running', False)):
                return False
        elif bool(value):
            return False
    return not bool(sim_state.get('simulator_running', False)) if isinstance(sim_state, dict) else True

def _mark_all_plants_stopped(reason: str = '') -> bool:
    """Persist all plant running flags as stopped, preserving recipes and plant metadata."""
    state = _read_sim_state_raw()
    already_stopped = _all_sim_state_plants_stopped(state)

    state['plants'] = _sim_state_plants(False)
    state['simulator_running'] = False
    if not save_json_atomic(SIM_STATE_FILE, state, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        raise OSError(f"Could not write {SIM_STATE_FILE}")
    with _locks['data']:
        for plant in _state['plant_data'].values():
            if isinstance(plant, dict):
                plant['process_state'] = False
                plant['maint_status'] = 'Stopped'
    if reason:
        _log(f"[sim-state] Marked all plants stopped: {reason}")
    return not already_stopped

def _write_all_plants_running(reason: str = ''):
    """Persist all plant running flags as running, preserving recipes and plant metadata."""
    state = _read_sim_state_raw()
    state['plants'] = _sim_state_plants(True)
    state['simulator_running'] = True
    if not save_json_atomic(SIM_STATE_FILE, state, ensure_ascii=False, logger=_json_log, label='sim_state.json'):
        raise OSError(f"Could not write {SIM_STATE_FILE}")
    if reason:
        _log(f"[sim-state] Marked all plants running: {reason}")

def _write_single_plant_running(plant_key: str, running: bool, reason: str = ''):
    """Persist one plant running flag and keep the global simulator flag consistent."""
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

def _reset_then_start_all_plants(delay_seconds: float = SIM_STATE_START_RESET_SECONDS):
    """Force a durable stopped snapshot before starting all plants."""
    with _locks['sim_control']:
        _ensure_sim_state_synced()
        _mark_all_plants_stopped('start-all reset before start')
        _log(f"[sim-state] Waiting {delay_seconds:.1f}s before start-all so factory.py can observe stopped state")
        time.sleep(delay_seconds)
        if not _server_alive():
            _mark_all_plants_stopped('factory process stopped during start-all reset')
            return False, 'OPC UA server stopped before plants could be started'
        _write_all_plants_running('start-all after reset')
        return True, f'All plants started after {delay_seconds:.1f}s reset'

def _reset_then_start_plant(plant_key: str, delay_seconds: float = SIM_STATE_START_RESET_SECONDS):
    """Force a durable stopped snapshot before starting one plant."""
    with _locks['sim_control']:
        _ensure_sim_state_synced()
        _write_single_plant_running(plant_key, False, 'single-plant reset before start')
        _log(f"[sim-state] Waiting {delay_seconds:.1f}s before starting {plant_key} so factory.py can observe stopped state")
        time.sleep(delay_seconds)
        if not _server_alive():
            _write_single_plant_running(plant_key, False, 'factory process stopped during single-plant reset')
            return False, 'OPC UA server stopped before plant could be started'
        _write_single_plant_running(plant_key, True, 'single-plant after reset')
        return True, f'Plant started after {delay_seconds:.1f}s reset'

def _reconcile_sim_state_with_process(reason: str = ''):
    """Clear stale persisted running flags whenever the managed factory process is not alive."""
    try:
        if not _server_alive():
            _mark_all_plants_stopped(reason or 'factory process is not running')
    except Exception as e:
        _log(f"[sim-state] Reconcile failed: {e}")

def _server_alive() -> bool:
    with _locks['proc']:
        p = _state['server_proc']
        return p is not None and p.poll() is None

# ── Server process management ──────────────────────────────────────────────────
def _capture_output(proc):
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            _log(line.rstrip())
    except Exception:
        pass

def start_factory_server():
    with _locks['proc']:
        if _state['server_proc'] and _state['server_proc'].poll() is None:
            return False, "Server is already running"
        _state['server_proc'] = None
        _ensure_sim_state_synced()
        _mark_all_plants_stopped('starting fresh factory process')
        if _opc_tcp_port_open():
            msg = f"OPC UA port {_state['opc_port']} is already in use; stop the existing process before starting the dashboard-managed server"
            _log(f"[server] {msg}")
            return False, msg
        factory_py = os.path.join(BASE_DIR, 'factory.py')
        if not os.path.exists(factory_py):
            return False, f"factory.py not found at {factory_py}"
        try:
            proc = subprocess.Popen(
                [sys.executable, factory_py],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=BASE_DIR,
            )
            _state['server_proc'] = proc
            threading.Thread(target=_capture_output, args=(proc,), daemon=True).start()

            if not _wait_for_opc_port(True, SERVER_START_TIMEOUT_SECONDS, proc=proc):
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                except Exception:
                    pass
                try:
                    remaining = proc.stdout.read() or ''
                except Exception:
                    remaining = ''
                exit_part = f"exited with code {proc.returncode}" if proc.poll() is not None else "did not open the OPC UA port"
                msg = f"Server process {exit_part}. Output: {remaining.strip()[:1000]}"
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

def stop_factory_server():
    with _locks['proc']:
        try:
            _mark_all_plants_stopped('factory process stopping')
        except Exception as e:
            _log(f"[sim-state] Stop pre-reconcile failed: {e}")
        proc = _state['server_proc']
        if proc is None or proc.poll() is not None:
            _state['server_proc'] = None
            try:
                _mark_all_plants_stopped('factory process was already stopped')
            except Exception as e:
                _log(f"[sim-state] Stop reconcile failed: {e}")
            return True, "Server was not running"
        try:
            proc.terminate()
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()  # Ensure OS reclaims the process (and its sockets) before returning
        _state['server_proc'] = None
        if not _wait_for_opc_port(False, SERVER_STOP_PORT_RELEASE_SECONDS):
            _log(f"[server] OPC UA port {_state['opc_port']} still accepts connections after factory process stop")
        try:
            _mark_all_plants_stopped('factory process stopped')
        except Exception as e:
            _log(f"[sim-state] Stop reconcile failed: {e}")
        return True, "Server stopped"

def _dashboard_shutdown():
    try:
        stop_bridge()
    except Exception:
        pass
    try:
        stop_factory_server()
    except Exception:
        try:
            _mark_all_plants_stopped('dashboard shutdown')
        except Exception:
            pass

def _install_shutdown_handlers():
    def _handle_signal(sig, _frame):
        _dashboard_shutdown()
        try:
            signal.signal(sig, signal.SIG_DFL)
        except Exception:
            pass
        raise SystemExit(0)

    atexit.register(_dashboard_shutdown)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            pass

# ── OPC UA node-cache polling ──────────────────────────────────────────────────
def _poll_loop():
    """Robust polling for dynamic factory.py structure.
    FIXED: Fully dynamic enterprise name from uns_config.json.
    This solves the root namespace change breaking the simulator/dashboard."""
    from opcua import Client
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
            client = Client(current_endpoint)
            client.connect()

            ns_idx = None
            ent = None
            current_namespace = _get_namespace_uri()
            for attempt in range(12):
                try:
                    ns_idx = client.get_namespace_index(current_namespace)
                except Exception as e:
                    if "BadNoMatch" in str(e):
                        time.sleep(0.5)
                        continue
                    raise

                try:
                    root = client.get_root_node()
                    ent = root.get_child(["0:Objects", f"{ns_idx}:{current_enterprise}"])
                    break
                except Exception:
                    time.sleep(0.5)
                    continue

            if ent is None:
                _state['opc_connected'] = False
                with _locks['data']:
                    _state['viz_values'] = {}
                _log(f"[poll] OPC UA available but root node '{current_enterprise}' not ready yet")
                try:
                    client.disconnect()
                except Exception:
                    pass
                time.sleep(1)
                continue

            _state['opc_connected'] = True
            _log(f"[poll] Successfully connected to OPC UA server — Enterprise: {current_enterprise}")

            with _locks['data']:
                _state['plant_data'] = _collect_plant_data(ent, ns_idx)

            while _endpoint() == current_endpoint and _state['opc_connected']:
                try:
                    with _locks['data']:
                        _state['plant_data'] = _collect_plant_data(ent, ns_idx)
                        _state['viz_values'] = _collect_viz_values(ent, ns_idx)
                except Exception as e:
                    _log(f"[poll] Data collection error (triggering reconnect): {e}")
                    _state['opc_connected'] = False
                    with _locks['data']:
                        _state['viz_values'] = {}
                    break
                time.sleep(3)

            try:
                client.disconnect()
            except Exception:
                pass

        except Exception as e:
            _state['opc_connected'] = False
            with _locks['data']:
                _state['viz_values'] = {}
            err_str = str(e)
            if "10061" in err_str or "ConnectionRefused" in err_str or "Connection refused" in err_str:
                _log("[poll] OPC UA unavailable: Connection refused - Is the factory server running?")
            elif "BadNoMatch" in err_str:
                _log(f"[poll] OPC UA unavailable: BadNoMatch (root node '{current_enterprise}' not found)")
            else:
                _log(f"[poll] OPC UA unavailable: {type(e).__name__} - {err_str}")
            time.sleep(4)

threading.Thread(target=_poll_loop, daemon=True, name="opc-poll").start()

# ── OPC UA write helper (one-shot client per command) ─────────────────────────
def _opc_write(fn):
    """Connect, call fn(client, idx, enterprise), disconnect. Returns (ok, msg).
    Enterprise name is read dynamically from uns_config.json tree root."""
    from opcua import Client
    try:
        enterprise_name = _get_enterprise_name()
        client = Client(_endpoint())
        client.connect()
        idx  = client.get_namespace_index(_get_namespace_uri())
        root = client.get_root_node()
        ent  = root.get_child(["0:Objects", f"{idx}:{enterprise_name}"])
        result = fn(client, idx, ent)
        client.disconnect()
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

# ── Flask routes ───────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template(
        'index.html',
        structure=_get_enterprise_structure(),
        division_meta=_get_division_meta(),
    )

@app.route('/api/status')
def api_status():
    _reconcile_sim_state_with_process('status poll found no factory process')
    server_running = _server_alive()
    server_ready = server_running and _opc_tcp_port_open()
    if not server_ready:
        _state['opc_connected'] = False
        plants = _plant_data_from_sim_state(force_stopped=True)
        with _locks['data']:
            _state['plant_data'] = plants
    else:
        with _locks['data']:
            plants = dict(_state['plant_data'])
        if not plants:
            plants = _plant_data_from_sim_state(force_stopped=False)
    with _locks['data']:
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
def api_logs():
    with _locks['logs']:
        logs = list(_state['server_logs'][-150:])
    return jsonify({'logs': logs})

@app.route('/api/server/start', methods=['POST'])
def api_server_start():
    ok, msg = start_factory_server()
    return jsonify({'ok': ok, 'msg': msg}), 200 if ok else 409

@app.route('/api/server/stop', methods=['POST'])
def api_server_stop():
    ok, msg = stop_factory_server()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.json or {}
    if 'host' in data:
        _state['opc_host'] = data['host'].strip()
    if 'port' in data:
        _state['opc_port'] = int(data['port'])
    return jsonify({'ok': True, 'host': _state['opc_host'], 'port': _state['opc_port']})

@app.route('/api/server-config', methods=['GET'])
def api_server_config_get():
    cfg = _load_server_cfg()
    cfg.setdefault('opc_bind_ip',    '0.0.0.0')
    cfg.setdefault('opc_port',       4840)
    cfg.setdefault('opc_client_host','127.0.0.1')
    cfg.setdefault('tcp_port',       9999)
    cfg.setdefault('host_ip',        '127.0.0.1')
    return jsonify(cfg)

@app.route('/api/server-config', methods=['POST'])
def api_server_config_save():
    data = request.json or {}
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
def api_start_all():
    # sim_state.json is the authoritative control source — no OPC writes needed
    if not _server_alive():
        _mark_all_plants_stopped('start-all requested without factory process')
        return jsonify({'ok': False, 'msg': 'Start the OPC UA server before starting plants'}), 409
    if not _opc_tcp_port_open():
        _mark_all_plants_stopped('start-all requested before OPC UA port was ready')
        return jsonify({'ok': False, 'msg': 'OPC UA server process is running, but the OPC UA port is not ready yet'}), 409
    ok, msg = _reset_then_start_all_plants()
    return jsonify({'ok': ok, 'msg': msg}), 200 if ok else 409

@app.route('/api/plants/stop-all', methods=['POST'])
def api_stop_all():
    _ensure_sim_state_synced()
    _mark_all_plants_stopped('stop-all requested')
    return jsonify({'ok': True, 'msg': 'Plants stopped'})

@app.route('/api/plant/control', methods=['POST'])
def api_plant_control():
    data   = request.json or {}
    group  = data['group']
    plant  = data['plant']
    action = data['action']
    value  = data['value']
    if action == 'set_state':
        plant_key = f"{group}|{plant}"
        if bool(value) and not _server_alive():
            _mark_all_plants_stopped('plant start requested without factory process')
            return jsonify({'ok': False, 'msg': 'Start the OPC UA server before starting plants'}), 409
        if bool(value) and not _opc_tcp_port_open():
            _mark_all_plants_stopped('plant start requested before OPC UA port was ready')
            return jsonify({'ok': False, 'msg': 'OPC UA server process is running, but the OPC UA port is not ready yet'}), 409
        if bool(value):
            ok, msg = _reset_then_start_plant(plant_key)
            if not ok:
                return jsonify({'ok': False, 'msg': msg}), 409
        else:
            with _locks['sim_control']:
                _write_single_plant_running(plant_key, False, 'single-plant stop requested')
    elif action == 'set_recipe':
        plant_key = f"{group}|{plant}"
        _write_sim_state({plant_key: {'recipe': str(value)}})

    return jsonify({'ok': True, 'msg': f'{action} applied'})

@app.route('/api/recipes/<group>/<plant>')
def api_recipes(group, plant):
    """Return available recipes (from uns_config.json site node) and active recipe (from sim_state.json)."""
    plant_key = f"{group}|{plant}"

    # Recipe definitions come from uns_config.json site.recipes
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

    # Active selection comes from sim_state.json
    active = ''
    try:
        sim_state = load_json(SIM_STATE_FILE, {}, logger=_json_log, label='sim_state.json')
        plant_val = sim_state.get('plants', {}).get(plant_key, {}) if isinstance(sim_state, dict) else {}
        active = plant_val.get('recipe', '') if isinstance(plant_val, dict) else ''
    except Exception:
        pass

    return jsonify({'recipes': recipes, 'active': active})

@app.route('/api/equipment/<group>')
def api_equipment(group):
    # Equipment options are now dynamically built from plant tags in uns_config.json
    # Return tags that are writable (access=RW) for the given group as equipment options
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
                        break  # first site is representative
                break
    except Exception:
        pass
    return jsonify({'equipment': result})

@app.route('/api/plant/tags/<group>/<plant>')
def api_plant_tags(group, plant):
    tags = _get_plant_tags(group, plant)
    return jsonify({'tags': tags})

@app.route('/api/anomaly/inject', methods=['POST'])
def api_anomaly():
    data      = request.json or {}
    overrides = data.get('overrides', {})
    duration  = float(data.get('duration', 30))
    if not overrides:
        return jsonify({'ok': False, 'msg': 'No overrides specified'})
    def _run():
        _send_anomaly(overrides)
        if duration > 0:
            time.sleep(duration)
            _send_anomaly({k: None for k in overrides})
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'tags': len(overrides), 'duration': duration})

# ── Broker Bridge management ───────────────────────────────────────────────────
BRIDGE_CONFIG_FILE = os.path.join(BASE_DIR, 'bridge_config.json')
BRIDGE_PY          = os.path.join(BASE_DIR, 'bridge.py')

def _load_bridge_cfg() -> dict:
    return load_json(BRIDGE_CONFIG_FILE, {}, logger=_json_log, label='bridge_config.json')

def _save_bridge_cfg(data: dict):
    if not save_json_atomic(BRIDGE_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='bridge_config.json'):
        raise OSError(f"Could not write {BRIDGE_CONFIG_FILE}")

def _bridge_alive() -> bool:
    with _locks['bridge']:
        p = _state['bridge_proc']
        return p is not None and p.poll() is None

def _capture_bridge_output(proc):
    try:
        for line in iter(proc.stdout.readline, ''):
            if not line:
                break
            line = line.rstrip()
            if line.startswith('[BRIDGE_STATS] '):
                try:
                    stats = json.loads(line[15:])
                    with _locks['data']:
                        _state['bridge_stats'].update(stats)
                except Exception:
                    pass
            else:
                _log(f"[bridge] {line}")
    except Exception:
        pass

def start_bridge():
    with _locks['bridge']:
        if _state['bridge_proc'] and _state['bridge_proc'].poll() is None:
            return False, "Bridge is already running"
        if not os.path.exists(BRIDGE_PY):
            return False, f"bridge.py not found at {BRIDGE_PY}"
        try:
            cfg = _load_bridge_cfg()
            cfg['opc_host'] = _container_local_host(_state['opc_host'])
            cfg['opc_port'] = _state['opc_port']
            _save_bridge_cfg(cfg)
        except Exception as e:
            return False, f"Could not update bridge config: {e}"
        try:
            proc = subprocess.Popen(
                [sys.executable, BRIDGE_PY],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=BASE_DIR,
            )
            _state['bridge_proc'] = proc
            threading.Thread(target=_capture_bridge_output, args=(proc,), daemon=True).start()
            return True, "Bridge process started"
        except Exception as e:
            return False, str(e)

def stop_bridge():
    with _locks['bridge']:
        proc = _state['bridge_proc']
        if proc is None or proc.poll() is not None:
            _state['bridge_proc'] = None
            return True, "Bridge was not running"
        try:
            proc.terminate()
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        _state['bridge_proc'] = None
        with _locks['data']:
            _state['bridge_stats'].update({
                'connected': False, 'opc_ok': False, 'rate': 0.0
            })
        return True, "Bridge stopped"

@app.route('/api/bridge/start', methods=['POST'])
def api_bridge_start():
    ok, msg = start_bridge()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/bridge/stop', methods=['POST'])
def api_bridge_stop():
    ok, msg = stop_bridge()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/bridge/config', methods=['GET'])
def api_bridge_cfg_get():
    cfg = _load_bridge_cfg()
    cfg.pop('password', None)
    return jsonify(cfg)

@app.route('/api/bridge/config', methods=['POST'])
def api_bridge_cfg_save():
    data = request.json or {}
    cfg  = _load_bridge_cfg()
    for key in ('protocol', 'broker_host', 'broker_port', 'topic_prefix',
                'interval', 'username', 'password'):
        if key in data:
            cfg[key] = data[key]
    _save_bridge_cfg(cfg)
    if _bridge_alive():
        stop_bridge()
        ok, msg = start_bridge()
        return jsonify({'ok': ok, 'restarted': True, 'msg': msg})
    return jsonify({'ok': True, 'restarted': False})

# ── Asset Library ──────────────────────────────────────────────────────────────
ASSET_LIBRARY_FILE = os.path.join(BASE_DIR, 'asset_library.json')

def _load_asset_library() -> dict:
    data = load_json(ASSET_LIBRARY_FILE, {"assets": []}, logger=_json_log, label='asset_library.json')
    return data if isinstance(data, dict) else {"assets": []}

@app.route('/api/asset-library', methods=['GET'])
def api_asset_library():
    return jsonify(_load_asset_library())

# ── Simulation Profile Catalogue ───────────────────────────────────────────────
@app.route('/api/simulation-profiles', methods=['GET'])
def api_simulation_profiles():
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
def uns_live():
    return render_template('uns_live.html')

@app.route('/manual')
def user_manual():
    return render_template('manual.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

# ── UNS Topic Designer ─────────────────────────────────────────────────────────
@app.route('/uns')
def uns_editor():
    return render_template('uns_editor.html')

@app.route('/api/uns', methods=['GET'])
def api_uns_get():
    data = load_json(UNS_CONFIG_FILE, {}, logger=_json_log, label='uns_config.json')
    return jsonify(data if isinstance(data, dict) else {})

@app.route('/api/uns', methods=['POST'])
def api_uns_save():
    data = request.json or {}
    data['lastModified'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    if not save_json_atomic(UNS_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='uns_config.json'):
        return jsonify({'ok': False, 'error': 'Could not write UNS config'}), 500
    restarted = []
    factory_was_running = _server_alive()
    if factory_was_running:
        _state['opc_connected'] = False
        time.sleep(1)
        stop_factory_server()
        time.sleep(1)  # Let OS release port 4840 before binding again
        ok, _ = start_factory_server()
        if not ok:
            # First attempt failed (port still in TIME_WAIT) — retry once after a longer wait
            time.sleep(3)
            ok, _ = start_factory_server()
        if ok:
            restarted.append('factory')
            # Invalidate metric path cache so new UNS structure is picked up
            global _metric_path_cache, _metric_path_cache_ts
            _metric_path_cache = {}
            _metric_path_cache_ts = 0.0
            # Sync sim_state.json with new UNS structure (preserves running states,
            # adds new plants as stopped, removes deleted plants)
            _ensure_sim_state_synced()
            def _delayed_bridge_restart():
                time.sleep(4)
                if _bridge_alive():
                    stop_bridge()
                    start_bridge()
            threading.Thread(target=_delayed_bridge_restart, daemon=True).start()
    return jsonify({'ok': True, 'restarted': restarted})

# ── Payload Schema Designer ───────────────────────────────────────────────────
@app.route('/payload-schemas')
def payload_schemas_page():
    return render_template('payload_schemas.html')

@app.route('/api/payload-schemas', methods=['GET'])
def api_schemas_get():
    data = load_json(SCHEMAS_CONFIG_FILE, {'schemas': []}, logger=_json_log, label='payload_schemas.json')
    return jsonify(data if isinstance(data, dict) else {'schemas': []})

@app.route('/api/payload-schemas', methods=['POST'])
def api_schemas_save():
    data = request.json or {}
    if not save_json_atomic(SCHEMAS_CONFIG_FILE, data, ensure_ascii=False, logger=_json_log, label='payload_schemas.json'):
        return jsonify({'ok': False, 'error': 'Could not write payload schemas'}), 500
    return jsonify({'ok': True})

# ── Visualization (SCADA mimic) ───────────────────────────────────────────────
# Pure logic lives in viz_service.py; this module only holds the Flask routes
# and the OPC traversal callable used by the poll loop.

import viz_service

def _suggest_kind(name): return viz_service.suggest_kind(name)
def _load_viz_cfg(): return viz_service.load_viz_cfg(VIZ_CONFIG_FILE)
def _save_viz_cfg(data): viz_service.save_viz_cfg(VIZ_CONFIG_FILE, data)
def _walk_viz_entities(): return viz_service.walk_entities(UNS_CONFIG_FILE)
def _viz_resolve_tag_path(entity_id, tag_name):
    return viz_service.resolve_tag_path(UNS_CONFIG_FILE, entity_id, tag_name)

def _collect_viz_values(ent, idx):
    """Bridge viz_service.collect_values to a live OPC client (poll loop only)."""
    def read(path):
        try:
            n = ent
            for part in path:
                n = n.get_child([f"{idx}:{part}"])
            return n.get_value()
        except Exception:
            return None
    return viz_service.collect_values(
        _load_viz_cfg().get('gauges', []),
        _viz_resolve_tag_path,
        read,
    )

@app.route('/viz')
def viz_page():
    return render_template('visualization.html')

@app.route('/api/viz/config', methods=['GET'])
def api_viz_get():
    return jsonify(_load_viz_cfg())

@app.route('/api/viz/config', methods=['POST'])
def api_viz_save():
    data = request.json or {}
    data.setdefault('version', 1)
    data['lastModified'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    _save_viz_cfg(data)
    return jsonify({'ok': True})

@app.route('/api/viz/entities', methods=['GET'])
def api_viz_entities():
    mapped   = _load_viz_cfg().get('entities', {})
    entities = _walk_viz_entities()
    for e in entities:
        cur = mapped.get(e['id'], {})
        e['suggestion'] = _suggest_kind(e['name'])
        e['kind']       = cur.get('kind') or e['suggestion']
        e['mapped']     = bool(cur.get('kind'))
    return jsonify({'kinds': viz_service.EQUIPMENT_KINDS, 'entities': entities})

@app.route('/api/viz/values', methods=['GET'])
def api_viz_values():
    with _locks['data']:
        values = dict(_state.get('viz_values') or {})
    return jsonify({
        'values':    values,
        'opc_ready': bool(_state.get('opc_connected')),
        'ts':        time.time(),
    })

@app.route('/api/viz/tags/<path:entity_id>', methods=['GET'])
def api_viz_tags(entity_id):
    return jsonify({'tags': viz_service.entity_tags(UNS_CONFIG_FILE, entity_id)})

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Ensure sim_state.json is synced with current uns_config.json
    _ensure_sim_state_synced()
    _mark_all_plants_stopped('dashboard startup')
    _install_shutdown_handlers()
    # Start periodic background sync to pick up changes made in the UNS Designer
    _start_periodic_sync(interval=10)
    print()
    print("==============================================================")
    print("UNS Design Studio")
    print("Dashboard: http://localhost:5000")
    print("==============================================================")
    print()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

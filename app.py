#!/usr/bin/env python3
"""
UNS Design Studio — Web Dashboard & REST API

Author : Ilja Bartels  |  https://github.com/Ilja0101
License: MIT  |  https://github.com/Ilja0101/UNS-Design-Studio
"""

import os, sys, time, json, socket, threading, subprocess, hashlib
from flask import Flask, render_template, jsonify, request

# ── Adjust path so recipe.py is importable ────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── Config file paths ─────────────────────────────────────────────────────────
UNS_CONFIG_FILE      = os.path.join(BASE_DIR, 'uns_config.json')
SCHEMAS_CONFIG_FILE  = os.path.join(BASE_DIR, 'payload_schemas.json')
SERVER_CONFIG_FILE   = os.path.join(BASE_DIR, 'server_config.json')
SIM_STATE_FILE       = os.path.join(BASE_DIR, 'sim_state.json')

def _load_server_cfg() -> dict:
    try:
        with open(SERVER_CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_server_cfg(data: dict):
    with open(SERVER_CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

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
    try:
        with open(UNS_CONFIG_FILE) as f:
            cfg = json.load(f)
        struct = {}
        for bu in cfg.get('tree', {}).get('children', []):
            if bu.get('type') == 'businessUnit':
                plants = [
                    s['name']  # Use actual site name, no prefix
                    for s in bu.get('children', [])
                    if s.get('type') == 'site'
                ]
                if plants:
                    struct[bu['name']] = plants
        return struct if struct else _ENTERPRISE_FALLBACK
    except Exception:
        return _ENTERPRISE_FALLBACK

def _get_namespace_uri() -> str:
    try:
        with open(UNS_CONFIG_FILE) as f:
            return json.load(f).get('namespaceUri', NAMESPACE_URI)
    except Exception:
        return NAMESPACE_URI

# ── DYNAMIC ENTERPRISE NAME (FIXED) ───────────────────────────────────────────
def _get_enterprise_name() -> str:
    """Return the root enterprise name from uns_config.json.
    This is the critical fix that makes any custom namespace root (AcmeEnterprise, MyCompany, etc.)
    work with the dashboard, polling loop, and OPC-UA client."""
    try:
        with open(UNS_CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('tree', {}).get('name', 'GlobalFoodCo')
    except Exception:
        return 'GlobalFoodCo'

def _get_site_recipes(site_node: dict) -> list:
    """Return the recipe definitions stored directly on a site node.
    Recipes are defined in uns_config.json as site.recipes = [{name, params}, ...]
    and edited via the Recipes tab in the UNS designer."""
    raw = site_node.get('recipes', [])
    return [
        r if isinstance(r, dict) else {'name': str(r), 'params': {}}
        for r in raw
    ]

def _ensure_sim_state_synced():
    """Ensure sim_state.json has all plants from current uns_config.json.
    FIXED: Now ALWAYS refreshes the 'recipes' list for every plant when the UNS Designer saves changes.
    This solves the "recipes added in designer are not persisted / not selectable" issue."""
    try:
        with open(UNS_CONFIG_FILE) as f:
            cfg = json.load(f)
    except Exception:
        return  # Can't sync without config
    
    try:
        with open(SIM_STATE_FILE) as f:
            sim_state = json.load(f)
    except Exception:
        sim_state = {'plants': {}, 'simulator_running': False}
    
    if 'plants' not in sim_state:
        sim_state['plants'] = {}
    
    # Walk the current enterprise structure and ensure all plants exist + refresh recipes
    for bu in cfg.get('tree', {}).get('children', []):
        if bu.get('type') != 'businessUnit':
            continue
        
        bu_name = bu.get('name')
        
        for site in bu.get('children', []):
            if site.get('type') != 'site':
                continue
            
            site_name = site.get('name')
            plant_key = f"{bu_name}|{site_name}"
            
            # Recipes come from site.recipes in uns_config.json (set via UNS designer Recipes tab)
            recipes = _get_site_recipes(site)
            
            if plant_key not in sim_state['plants']:
                sim_state['plants'][plant_key] = {
                    'running': False,
                    'recipe': recipes[0]['name'] if recipes else '--NA--',
                    'recipes': recipes,
                }
            else:
                # Plant exists — make sure it has the latest recipes list
                plant_state = sim_state['plants'][plant_key]
                if 'recipes' not in plant_state or plant_state['recipes'] != recipes:
                    plant_state['recipes'] = recipes
                if 'recipe' not in plant_state or not any(r.get('name') == plant_state.get('recipe') for r in recipes):
                    plant_state['recipe'] = recipes[0]['name'] if recipes else '--NA--'
    
    # Remove plants that no longer exist in enterprise structure
    current_enterprise_keys = set()
    for bu in cfg.get('tree', {}).get('children', []):
        if bu.get('type') == 'businessUnit':
            for site in bu.get('children', []):
                if site.get('type') == 'site':
                    current_enterprise_keys.add(f"{bu['name']}|{site['name']}")
    
    plants_to_remove = [k for k in sim_state['plants'].keys() if k not in current_enterprise_keys]
    for k in plants_to_remove:
        del sim_state['plants'][k]
    
    # Save updated sim_state
    try:
        with open(SIM_STATE_FILE, 'w') as f:
            json.dump(sim_state, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not write sim_state.json: {e}")

def _get_division_meta() -> dict:
    """Return {buName: {color, icon, label}} from uns_config.json BU nodes.
    Falls back to generic defaults for any group not found."""
    _DEFAULT = {'color': '#58a6ff', 'icon': '🏭', 'label': ''}
    result = {}
    try:
        with open(UNS_CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
        for bu in cfg.get('tree', {}).get('children', []):
            if bu.get('type') == 'businessUnit':
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
}

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

def _default_recipe(group: str, plant: str = '') -> str:
    """Return the first recipe name for a plant from sim_state.json, or empty string."""
    try:
        with open(SIM_STATE_FILE) as f:
            sim = json.load(f)
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
    try:
        with open(UNS_CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception:
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
    try:
        with open(SIM_STATE_FILE) as f:
            sim_state = json.load(f)
    except Exception:
        sim_state = {'plants': {}}

    def _read_path(path):
        """Read an OPC value given a path list starting from enterprise root."""
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
                # Site not in OPC tree yet (server still starting) — use sim_state only
                plants[plant_key] = {
                    'group': group, 'plant': plant,
                    'process_state': process_state, 'recipe': recipe,
                    'maint_status': 'Running' if process_state else 'Stopped',
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
                'oee':        _num(_read_path(metric_paths.get('oee',        []))),
                'power':      _num(_read_path(metric_paths.get('power',      []))),
                'good_tons':  _num(_read_path(metric_paths.get('good_tons',  []))),
                'trucks_recv':_num(_read_path(metric_paths.get('trucks_recv', []))),
            }
    return plants

def _sim_state_plants(running: bool) -> dict:
    """Return {plant_key: {running: bool}} for every plant, preserving existing recipe data."""
    try:
        with open(SIM_STATE_FILE) as f:
            current = json.load(f).get('plants', {})
    except Exception:
        current = {}

    result = {}
    for group, plants in _get_enterprise_structure().items():
        for plant in plants:
            pk = f"{group}|{plant}"
            existing = current.get(pk, {})
            if isinstance(existing, dict):
                merged = dict(existing)
                merged['running'] = running
                result[pk] = merged
            else:
                result[pk] = {'running': running}
    return result

def _read_sim_state_raw() -> dict:
    """Return raw sim_state.json content."""
    try:
        with open(SIM_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {'plants': {}, 'simulator_running': True}

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
    try:
        with open(SIM_STATE_FILE) as f:
            current = json.load(f)
    except Exception:
        current = {'plants': {}, 'simulator_running': True}

    if 'plants' not in current:
        current['plants'] = {}

    if 'plants' in data:
        for k, v in data['plants'].items():
            if k in current['plants'] and isinstance(current['plants'][k], dict) and isinstance(v, dict):
                current['plants'][k].update(v)
            else:
                current['plants'][k] = v
    else:
        for k, v in data.items():
            if k == 'simulator_running':
                current['simulator_running'] = v
            elif '|' in k:
                if k in current['plants'] and isinstance(current['plants'][k], dict):
                    if isinstance(v, bool):
                        current['plants'][k]['running'] = v
                    elif isinstance(v, dict):
                        current['plants'][k].update(v)
                else:
                    current['plants'][k] = {'running': bool(v)} if isinstance(v, bool) else v
            else:
                current[k] = v

    with open(SIM_STATE_FILE, 'w') as f:
        json.dump(current, f, indent=2)

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

            time.sleep(0.8)
            if proc.poll() is not None:
                try:
                    remaining = proc.stdout.read() or ''
                except Exception:
                    remaining = ''
                msg = f"Server process exited with code {proc.returncode}. Output: {remaining.strip()[:1000]}"
                _log(f"[server] {msg}")
                _state['server_proc'] = None
                return False, msg

            return True, "Server process started"
        except Exception as e:
            return False, str(e)

def stop_factory_server():
    with _locks['proc']:
        proc = _state['server_proc']
        if proc is None or proc.poll() is not None:
            _state['server_proc'] = None
            return True, "Server was not running"
        try:
            proc.terminate()
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        _state['server_proc'] = None
        return True, "Server stopped"

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
            for attempt in range(12):
                try:
                    ns_idx = client.get_namespace_index(NAMESPACE_URI)
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
                except Exception as e:
                    _log(f"[poll] Data collection error (triggering reconnect): {e}")
                    _state['opc_connected'] = False
                    break
                time.sleep(3)

            try:
                client.disconnect()
            except Exception:
                pass

        except Exception as e:
            _state['opc_connected'] = False
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
        idx  = client.get_namespace_index(NAMESPACE_URI)
        root = client.get_root_node()
        ent  = root.get_child(["0:Objects", f"{idx}:{enterprise_name}"])
        result = fn(client, idx, ent)
        client.disconnect()
        return True, result or "OK"
    except Exception as e:
        return False, str(e)

# ── Plant tag introspection (for dynamic anomaly UI) ─────────────────────────
def _get_plant_tags(group: str, plant: str) -> list:
    try:
        with open(UNS_CONFIG_FILE) as f:
            cfg = json.load(f)
    except Exception:
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
    with _locks['data']:
        plants = dict(_state['plant_data'])
    with _locks['data']:
        bstats = dict(_state['bridge_stats'])
    cfg = _load_bridge_cfg()
    cfg.pop('password', None)
    struct = _get_enterprise_structure()
    struct_hash = hashlib.md5(json.dumps(struct, sort_keys=True).encode()).hexdigest()[:8]
    enterprise_name = _get_enterprise_name()
    return jsonify(dict(
        server_running=_server_alive(),
        opc_connected=_state['opc_connected'],
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
    return jsonify({'ok': ok, 'msg': msg})

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
    _write_sim_state(_sim_state_plants(True))
    _write_sim_state({'simulator_running': True})
    return jsonify({'ok': True, 'msg': 'All plants started'})

@app.route('/api/plants/stop-all', methods=['POST'])
def api_stop_all():
    _write_sim_state(_sim_state_plants(False))
    _write_sim_state({'simulator_running': False})
    return jsonify({'ok': True, 'msg': 'All plants stopped'})

@app.route('/api/plant/control', methods=['POST'])
def api_plant_control():
    data   = request.json or {}
    group  = data['group']
    plant  = data['plant']
    action = data['action']
    value  = data['value']
    if action == 'set_state':
        plant_key = f"{group}|{plant}"
        _write_sim_state({plant_key: {'running': bool(value)}})
        try:
            with open(SIM_STATE_FILE) as f:
                current_plants = json.load(f).get('plants', {})
        except Exception:
            current_plants = {}
        if bool(value):
            _write_sim_state({'simulator_running': True})
        else:
            any_running = any(
                (v.get('running', False) if isinstance(v, dict) else bool(v))
                for k, v in current_plants.items() if k != plant_key
            )
            _write_sim_state({'simulator_running': any_running})
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
        with open(UNS_CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
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
        with open(SIM_STATE_FILE) as f:
            plant_val = json.load(f).get('plants', {}).get(plant_key, {})
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
        with open(UNS_CONFIG_FILE, encoding='utf-8') as f:
            cfg = json.load(f)
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
    if os.path.exists(BRIDGE_CONFIG_FILE):
        with open(BRIDGE_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def _save_bridge_cfg(data: dict):
    with open(BRIDGE_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

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
            cfg['opc_host'] = _state['opc_host']
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
    try:
        with open(ASSET_LIBRARY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"assets": []}

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

# ── UNS Topic Designer ─────────────────────────────────────────────────────────
@app.route('/uns')
def uns_editor():
    return render_template('uns_editor.html')

@app.route('/api/uns', methods=['GET'])
def api_uns_get():
    if os.path.exists(UNS_CONFIG_FILE):
        with open(UNS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route('/api/uns', methods=['POST'])
def api_uns_save():
    data = request.json or {}
    data['lastModified'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(UNS_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    restarted = []
    factory_was_running = _server_alive()
    if factory_was_running:
        _state['opc_connected'] = False
        time.sleep(1)
        stop_factory_server()
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
    if os.path.exists(SCHEMAS_CONFIG_FILE):
        with open(SCHEMAS_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    return jsonify({'schemas': []})

@app.route('/api/payload-schemas', methods=['POST'])
def api_schemas_save():
    data = request.json or {}
    with open(SCHEMAS_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return jsonify({'ok': True})

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Ensure sim_state.json is synced with current uns_config.json
    _ensure_sim_state_synced()
    # Start periodic background sync to pick up changes made in the UNS Designer
    _start_periodic_sync(interval=10)
    print()
    print("==============================================================")
    print("UNS Design Studio")
    print("Dashboard: http://localhost:5000")
    print("==============================================================")
    print()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
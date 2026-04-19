#!/usr/bin/env python3
"""
Royal Farmers Collective – Enterprise UNS Simulator
Web-based Control Dashboard  (Flask backend)
"""

import os, sys, time, json, socket, threading, subprocess, hashlib
from flask import Flask, render_template, jsonify, request

# ── Adjust path so recipe.py is importable ────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from recipe import Recipe, recipe_data

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
    "KnappertjesBV": ["FactoryTerneuzen",   "FactoryBergenOpZoom"],
    "Vlokkenheim":   ["FactoryEmmeloord",   "FactoryVeendam"],
    "FritoMaxx":     ["FactoryHeerenveen",  "FactoryHarlingen",  "FactoryMeppel",
                      "FactoryHardenberg",  "FactoryHoogeveen",  "FactoryCoevorden"],
    "Wortelkracht":  ["FactoryRoosendaal"],
    "DeBietenBende": ["FactoryZevenbergen", "FactoryStadskanaal"],
}

def _get_enterprise_structure() -> dict:
    """Return {businessUnitName: [FactorySiteName, …]} from uns_config.json."""
    try:
        with open(UNS_CONFIG_FILE) as f:
            cfg = json.load(f)
        struct = {}
        for bu in cfg.get('tree', {}).get('children', []):
            if bu.get('type') == 'businessUnit':
                plants = [
                    'Factory' + s['name']
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

DIVISION_META = {
    "KnappertjesBV":  {"label": "Chips & Snacks",    "icon": "🥔", "color": "#f4900c"},
    "Vlokkenheim":    {"label": "Potato Flakes",      "icon": "🌾", "color": "#c8a96e"},
    "FritoMaxx":      {"label": "Frozen Frites",      "icon": "🍟", "color": "#f5c518"},
    "Wortelkracht":   {"label": "Chicory & Inulin",   "icon": "🌿", "color": "#4caf50"},
    "DeBietenBende":  {"label": "Sugar Beet",         "icon": "🍬", "color": "#a371f7"},
}

# var_key values (lowercase) → these get .capitalize() applied when building anomaly keys
EQUIPMENT_OPTIONS = {
    "KnappertjesBV":  {"Cutter Speed": "cutter_speed", "Blancher Temp": "blancher_temperature",
                       "Fryer Temp": "fryer_temperature", "Cooler Temp": "freezer_temperature"},
    "Vlokkenheim":    {"Drum Speed": "drum_speed", "Drum Temp": "drum_temperature"},
    "FritoMaxx":      {"Cutter Speed": "cutter_speed", "Blancher Temp": "blancher_temperature",
                       "Pre-Fryer Temp": "fryer_temperature", "IQF Tunnel Temp": "freezer_temperature"},
    "Wortelkracht":   {"Extraction Temp": "extraction_temperature"},
    "DeBietenBende":  {"Diffusion Temp": "diffusion_temperature",
                       "Evaporator Temp": "evaporator_temperature",
                       "Crystallizer Temp": "crystallizer_temperature"},
}

NAMESPACE_URI = "http://royalfarmerscollective.com/uns"

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

# ── Helper functions ───────────────────────────────────────────────────────────

def _endpoint():
    return f"opc.tcp://{_state['opc_host']}:{_state['opc_port']}/freeopcua/server/"

def _default_recipe(group: str) -> str:
    for r in Recipe:
        if recipe_data.get(r, {}).get('group') == group:
            return r.value
    return '--NA--'

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

def _collect_plant_data(ent, idx):
    # Use sim_state.json as the authoritative running/stopped source.
    # This works for ALL plants regardless of whether they have a ProcessState
    # OPC node (some plants have custom ProcessControl tags without ProcessState).
    try:
        with open(SIM_STATE_FILE) as f:
            sim_state = json.load(f).get('plants', {})
    except Exception:
        sim_state = {}

    plants = {}
    for group, plant_names in _get_enterprise_structure().items():
        try:
            group_node = ent.get_child([f"{idx}:{group}"])
        except Exception:
            continue

        for plant in plant_names:
            try:
                site = group_node.get_child([f"{idx}:{plant}"])
                line = site.get_child([f"{idx}:ProductionLine"])
            except Exception:
                continue

            plant_key     = f"{group}|{plant}"
            process_state = sim_state.get(plant_key, False)
            recipe        = str(_read_opc(line, [f"{idx}:ProcessControl", f"{idx}:Recipe"], '--NA--'))
            maint_status  = str(_read_opc(line, [f"{idx}:Maintenance", f"{idx}:FabriekStatus"], ''))
            if not maint_status:
                maint_status = 'Running' if process_state else 'Stopped'

            plants[plant_key] = {
                'group': group,
                'plant': plant,
                'process_state': process_state,
                'recipe': recipe,
                'maint_status': maint_status,
                'oee':        _num(_read_opc(line, [f"{idx}:OEE", f"{idx}:OEEPercent"], 0.0)),
                'power':      _num(_read_opc(line, [f"{idx}:Energy", f"{idx}:HuidigVermogenkW"], 0.0)),
                'good_tons':  _num(_read_opc(line, [f"{idx}:Production", f"{idx}:GoodCountTons"], 0.0)),
                'trucks_recv':_num(_read_opc(line, [f"{idx}:Logistics", f"{idx}:InkomendWeegbrug", f"{idx}:CumulatiefOntvangenTons"], 0.0)),
            }
    return plants

def _sim_state_plants(running: bool) -> dict:
    """Return {plant_key: running} for every plant in the current UNS structure."""
    return {
        f"{group}|{plant}": running
        for group, plants in _get_enterprise_structure().items()
        for plant in plants
    }

def _write_sim_state(data: dict):
    """Merge data into sim_state.json. Plant states go under 'plants', global state at top level."""
    try:
        with open(SIM_STATE_FILE) as f:
            current = json.load(f)
    except Exception:
        current = {'plants': {}}
    
    # Handle plant states
    if 'plants' in data:
        current['plants'].update(data['plants'])
    else:
        # Check if this is plant data (contains plant keys like "Group|Plant")
        plant_data = {k: v for k, v in data.items() if '|' in k}
        global_data = {k: v for k, v in data.items() if '|' not in k}
        
        if plant_data:
            current['plants'].update(plant_data)
        if global_data:
            current.update(global_data)
    
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

            # Give the process a short moment to fail fast if something is wrong
            time.sleep(0.8)
            if proc.poll() is not None:
                # Process exited quickly — attempt to capture any available output
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
    """Robust polling for dynamic factory.py structure

    Improves resilience: wait for the server namespace to appear after connect
    before declaring the connection usable. This avoids race conditions when
    factory.py starts and the dynamic address space isn't yet ready.
    """
    from opcua import Client
    last_endpoint = None

    while True:
        current_endpoint = _endpoint()
        if current_endpoint != last_endpoint:
            last_endpoint = current_endpoint
            _log(f"[poll] Endpoint changed → {current_endpoint}")

        try:
            client = Client(current_endpoint)
            client.connect()

                    # Wait briefly for the server to finish registering namespaces / nodes.
            ns_idx = None
            ent = None
            for attempt in range(12):
                try:
                    ns_idx = client.get_namespace_index(NAMESPACE_URI)
                except Exception as e:
                    # Namespace may not be registered yet; retry
                    if "BadNoMatch" in str(e):
                        time.sleep(0.5)
                        continue
                    raise

                # If we got a namespace index, also verify the expected root object exists
                try:
                    root = client.get_root_node()
                    ent = root.get_child(["0:Objects", f"{ns_idx}:RoyalFarmersCollective"])
                    break
                except Exception:
                    # Node not ready yet — wait and retry
                    time.sleep(0.5)
                    continue

            if ent is None:
                # Namespace or expected node not ready yet — treat as transient and retry
                _state['opc_connected'] = False
                _log("[poll] OPC UA available but namespace/objects not ready yet; retrying")
                try:
                    client.disconnect()
                except Exception:
                    pass
                time.sleep(1)
                continue

            # Namespace and RoyalFarmersCollective object found → consider connection healthy
            _state['opc_connected'] = True
            _log("[poll] Successfully connected to OPC UA server")

            with _locks['data']:
                _state['plant_data'] = _collect_plant_data(ent, ns_idx)

            while _endpoint() == current_endpoint and _state['opc_connected']:
                try:
                    with _locks['data']:
                        _state['plant_data'] = _collect_plant_data(ent, ns_idx)
                except Exception as e:
                    # Node structure may have changed (e.g., factory restart with UNS edits)
                    # Force reconnect by breaking out of polling loop
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
                _log("[poll] OPC UA unavailable: BadNoMatch - Node structure mismatch (normal with dynamic server)")
            else:
                _log(f"[poll] OPC UA unavailable: {type(e).__name__} - {err_str}")
            time.sleep(4)
threading.Thread(target=_poll_loop, daemon=True, name="opc-poll").start()

# ── OPC UA write helper (one-shot client per command) ─────────────────────────

# Diagnostic: test OPC UA connection and return namespace / root children
@app.route('/api/opc/test')
def api_opc_test():
    from opcua import Client
    try:
        client = Client(_endpoint())
        if hasattr(client, 'set_timeout'):
            client.set_timeout(3)
        client.connect()
        try:
            ns_array = client.get_namespace_array()
        except Exception:
            ns_array = None
        try:
            idx = client.get_namespace_index(NAMESPACE_URI)
        except Exception as e:
            idx = None
            idx_err = repr(e)
        else:
            idx_err = None
        try:
            root = client.get_root_node()
            children = [str(n) for n in root.get_children()[:20]]
        except Exception:
            children = []
        client.disconnect()
        return jsonify({'ok': True, 'endpoint': _endpoint(), 'namespace_array': ns_array, 'namespace_index': idx, 'namespace_error': idx_err, 'root_children_sample': children})
    except Exception as e:
        return jsonify({'ok': False, 'endpoint': _endpoint(), 'error': repr(e)})


def _start_all_plants(idx, ent):
    """Set ProcessState=True and default recipe for every known plant. Called after restarts."""
    for group, plants in _get_enterprise_structure().items():
        recipe = _default_recipe(group)
        try:
            site = ent.get_child([f"{idx}:{group}"])
        except Exception:
            continue
        for plant in plants:
            try:
                pc = (site.get_child([f"{idx}:{plant}"])
                          .get_child([f"{idx}:ProductionLine"])
                          .get_child([f"{idx}:ProcessControl"]))
                pc.get_child([f"{idx}:ProcessState"]).set_value(True)
                pc.get_child([f"{idx}:Recipe"]).set_value(recipe)
            except Exception:
                pass

def _opc_write(fn):
    """Connect, call fn(client, idx, enterprise), disconnect. Returns (ok, msg)."""
    from opcua import Client
    try:
        client = Client(_endpoint())
        client.connect()
        idx  = client.get_namespace_index(NAMESPACE_URI)
        root = client.get_root_node()
        ent  = root.get_child(["0:Objects", f"{idx}:RoyalFarmersCollective"])
        result = fn(client, idx, ent)
        client.disconnect()
        return True, result or "OK"
    except Exception as e:
        return False, str(e)

# ── Plant tag introspection (for dynamic anomaly UI) ─────────────────────────

def _get_plant_tags(group: str, plant: str) -> list:
    """
    Return [{name, anomalyKey, dataType, unit, workCenter}] for every tag
    defined under <group>/<plant> in uns_config.json.

    anomalyKey matches exactly what factory.py stores in anomaly_key_map:
        "".join(target_opc_parts)
    where target_opc_parts follows the same rules as _create_dynamic_address_space.
    """
    try:
        with open(UNS_CONFIG_FILE) as f:
            cfg = json.load(f)
    except Exception:
        return []

    tree     = cfg.get('tree', {})
    # plant is "FactoryTerneuzen2" → site name is "Terneuzen2"
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
                rel        = tag['opcPath'].split('/')
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

    # Walk only the target business-unit → target site subtree, using the same
    # starting opc_parts as factory.py (bu name first, then site adds Factory prefix).
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
        division_meta=DIVISION_META,
    )

# ─ Status ─────────────────────────────────────────────────────────────────────
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
        ts=time.time(),
    ))

# ─ Server logs ────────────────────────────────────────────────────────────────
@app.route('/api/logs')
def api_logs():
    with _locks['logs']:
        logs = list(_state['server_logs'][-150:])
    return jsonify({'logs': logs})

# ─ Server process ─────────────────────────────────────────────────────────────
@app.route('/api/server/start', methods=['POST'])
def api_server_start():
    ok, msg = start_factory_server()
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/server/stop', methods=['POST'])
def api_server_stop():
    ok, msg = stop_factory_server()
    return jsonify({'ok': ok, 'msg': msg})

# ─ Connection config (legacy — kept for backwards compatibility) ──────────────
@app.route('/api/config', methods=['POST'])
def api_config():
    data = request.json or {}
    if 'host' in data:
        _state['opc_host'] = data['host'].strip()
    if 'port' in data:
        _state['opc_port'] = int(data['port'])
    return jsonify({'ok': True, 'host': _state['opc_host'], 'port': _state['opc_port']})

# ─ Server / network config ────────────────────────────────────────────────────
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
    # Apply OPC-UA client settings live so the poll loop reconnects
    _state['opc_host'] = cfg.get('opc_client_host', _state['opc_host'])
    _state['opc_port'] = int(cfg.get('opc_port',    _state['opc_port']))
    _state['tcp_port'] = int(cfg.get('tcp_port',    _state['tcp_port']))
    return jsonify({'ok': True})

# ─ Bulk plant control ──────────────────────────────────────────────────────────
@app.route('/api/plants/start-all', methods=['POST'])
def api_start_all():
    _write_sim_state(_sim_state_plants(True))
    _write_sim_state({'simulator_running': True})  # Global simulator state
    def fn(_, idx, ent):
        _start_all_plants(idx, ent)
        return "Started all plants"
    ok, msg = _opc_write(fn)
    return jsonify({'ok': ok, 'msg': msg})

@app.route('/api/plants/stop-all', methods=['POST'])
def api_stop_all():
    _write_sim_state(_sim_state_plants(False))
    _write_sim_state({'simulator_running': False})  # Global simulator state
    def fn(_, idx, ent):
        results = []
        for group, plants in _get_enterprise_structure().items():
            try:
                site = ent.get_child([f"{idx}:{group}"])
            except Exception:
                continue
            for plant in plants:
                try:
                    pc = (site.get_child([f"{idx}:{plant}"])
                              .get_child([f"{idx}:ProductionLine"])
                              .get_child([f"{idx}:ProcessControl"]))
                    pc.get_child([f"{idx}:ProcessState"]).set_value(False)
                    pc.get_child([f"{idx}:Recipe"]).set_value('--NA--')
                    results.append(f"✓ {plant}")
                except Exception as e:
                    results.append(f"✗ {plant}: {e}")
        return "; ".join(results)
    ok, msg = _opc_write(fn)
    return jsonify({'ok': ok, 'msg': msg})

# ─ Individual plant control ───────────────────────────────────────────────────
@app.route('/api/plant/control', methods=['POST'])
def api_plant_control():
    data   = request.json or {}
    group  = data['group']
    plant  = data['plant']
    action = data['action']
    value  = data['value']

    if action == 'set_state':
        plant_key = f"{group}|{plant}"
        _write_sim_state({plant_key: bool(value)})
        
        # Update global simulator state
        try:
            with open(SIM_STATE_FILE) as f:
                current = json.load(f).get('plants', {})
        except Exception:
            current = {}
        
        # If starting a plant, set simulator to running
        if bool(value):
            _write_sim_state({'simulator_running': True})
        else:
            # If stopping a plant, check if any plants are still running
            any_running = any(state for key, state in current.items() if key != plant_key and state)
            _write_sim_state({'simulator_running': any_running})

    def fn(_, idx, ent):
        pc = (ent.get_child([f"{idx}:{group}"])
                 .get_child([f"{idx}:{plant}"])
                 .get_child([f"{idx}:ProductionLine"])
                 .get_child([f"{idx}:ProcessControl"]))
        if action == 'set_state':
            pc.get_child([f"{idx}:ProcessState"]).set_value(bool(value))
        elif action == 'set_recipe':
            pc.get_child([f"{idx}:Recipe"]).set_value(str(value))

    ok, msg = _opc_write(fn)
    return jsonify({'ok': ok, 'msg': msg})

# ─ Recipes & equipment metadata ───────────────────────────────────────────────
@app.route('/api/recipes/<group>')
def api_recipes(group):
    recipes = [r.value for r in Recipe if recipe_data.get(r, {}).get('group') == group]
    return jsonify({'recipes': recipes + ['--NA--']})

@app.route('/api/equipment/<group>')
def api_equipment(group):
    return jsonify({'equipment': EQUIPMENT_OPTIONS.get(group, {})})

@app.route('/api/plant/tags/<group>/<plant>')
def api_plant_tags(group, plant):
    """Return all UNS tags for a plant with their anomaly keys (for dynamic anomaly UI)."""
    tags = _get_plant_tags(group, plant)
    return jsonify({'tags': tags})

# ─ Anomaly injection ──────────────────────────────────────────────────────────
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
        # Inject current OPC host/port into bridge config before starting
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


# Bridge routes
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
    cfg.pop('password', None)   # never send password back to browser
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
    # If bridge is running, restart it so new config takes effect
    if _bridge_alive():
        stop_bridge()
        ok, msg = start_bridge()
        return jsonify({'ok': ok, 'restarted': True, 'msg': msg})
    return jsonify({'ok': True, 'restarted': False})


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
    # Restart factory server so it re-reads the updated structure
    if factory_was_running:
        # Signal polling loop to disconnect before we stop the server
        _state['opc_connected'] = False
        time.sleep(1)  # Give polling loop time to disconnect
        stop_factory_server()
        ok, _ = start_factory_server()
        if ok:
            restarted.append('factory')
            # After factory restarts all ProcessState nodes default to False.
            # Restore running state by starting all plants after a short startup delay.
            def _delayed_start_all():
                time.sleep(6)   # wait for OPC-UA server to finish booting (increased from 4)
                # Try to write OPC state (retry once if it fails)
                for attempt in range(2):
                    try:
                        _opc_write(lambda _, idx, ent: _start_all_plants(idx, ent))
                        break  # Success, exit retry loop
                    except Exception:
                        if attempt == 0:
                            time.sleep(2)  # Wait a bit more before retry
                        pass
                # Always update sim_state.json regardless of OPC write success,
                # so the dashboard reflects the intended state
                _write_sim_state(_sim_state_plants(True))
                # Now restart the bridge after the factory is fully ready
                time.sleep(1)  # Brief pause before bridge restart
                if _bridge_alive():
                    stop_bridge()
                    ok, _ = start_bridge()
                    if ok:
                        restarted.append('bridge')
            threading.Thread(target=_delayed_start_all, daemon=True).start()
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
    print()
    print("==============================================================")
    print("Royal Farmers Collective - Enterprise UNS Simulator")
    print("Dashboard: http://localhost:5000")
    print("==============================================================")
    print()
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

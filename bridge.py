#!/usr/bin/env python3
"""
UNS Bridge  –  OPC-UA → NATS (native)  /  OPC-UA → MQTT
Managed as a subprocess by app.py.
Emits  [BRIDGE_STATS] <json>  lines to stdout for app.py to parse.
Config: bridge_config.json in the same directory.

Install deps:
  MQTT mode:  pip install paho-mqtt
  NATS mode:  pip install nats-py
"""

import json, os, sys, time, signal, threading, logging

logging.getLogger('opcua').setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARNING)

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE      = os.path.join(BASE_DIR, 'bridge_config.json')
UNS_CONFIG_FILE  = os.path.join(BASE_DIR, 'uns_config.json')
SCHEMAS_FILE     = os.path.join(BASE_DIR, 'payload_schemas.json')

stop_flag = False
_stats    = {
    "connected": False, "opc_ok": False,
    "published": 0, "errors": 0, "rate": 0.0,
    "protocol": "-", "ts": 0.0,
}


def _sig(_s, _f):
    global stop_flag
    stop_flag = True

signal.signal(signal.SIGINT,  _sig)
signal.signal(signal.SIGTERM, _sig)


def _load_cfg():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"[bridge] Cannot read {CONFIG_FILE}: {e}", flush=True)
        sys.exit(1)


def _load_uns():
    try:
        with open(UNS_CONFIG_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"[bridge] Cannot read {UNS_CONFIG_FILE}: {e}", flush=True)
        sys.exit(1)


def _build_entries(tree, sep, prefix):
    """
    Walk the UNS config tree and return a list of (uns_topic_str, [opc_path_parts], unit_str).

    OPC-UA path rules (matching factory.py conventions):
      - enterprise / businessUnit / area / workCenter nodes : OPC name == node name
      - site nodes            : OPC name == "Factory" + node name
      - tag with "opcNodeName": use that as the OPC leaf name instead of tag name
      - tag with "opcPath"    : path is relative to the *area* ancestor node
                                (e.g. "Logistics/InkomendWeegbrug/LaatsteTruckID")

    Sites that have empty workCenters inherit the canonical tag definitions from the
    first site in the tree that defines tags for that workCenter name, so all plants
    are polled even if only one site has fully specified tags.
    """
    # Walk tree and emit one entry per explicitly-defined tag.
    # No canonical inheritance — the bridge only publishes what is explicitly
    # configured in the UNS designer for each plant.
    entries = []

    def _sanitize(s: str) -> str:
        """Replace characters invalid in MQTT topics / NATS subjects with underscores."""
        import re
        return re.sub(r'[\s#+]', '_', s)

    def _walk(node, uns_parts, opc_parts, area_opc_parts):
        ntype = node.get('type', '')
        name  = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name

        new_uns = uns_parts + [name]
        new_opc = opc_parts + [opc_name]
        new_area_opc = new_opc if ntype == 'area' else area_opc_parts

        tags = node.get('tags', [])

        for tag in tags:
            t_uns       = tag['name']
            t_unit      = tag.get('unit', '')
            t_schema    = tag.get('payloadSchema', 'standard') or 'standard'
            t_data_type = tag.get('dataType', 'Float')

            if 'opcPath' in tag:
                rel_parts   = tag['opcPath'].split('/')
                t_opc_parts = new_area_opc + rel_parts
            else:
                t_opc_name  = tag.get('opcNodeName', t_uns)
                t_opc_parts = new_opc + [t_opc_name]

            # Sanitize every segment: spaces / # / + are invalid in MQTT topics
            safe_uns_parts = [_sanitize(p) for p in new_uns]
            safe_t_uns     = _sanitize(t_uns)
            topic = sep.join(safe_uns_parts + [safe_t_uns])
            if prefix:
                topic = prefix + sep + topic
            entries.append((topic, t_opc_parts, t_unit, t_schema, t_data_type, t_uns))

        for child in node.get('children', []):
            _walk(child, new_uns, new_opc, new_area_opc)

    _walk(tree, [], [], [])
    return entries


def _emit():
    _stats["ts"] = time.time()
    print(f"[BRIDGE_STATS] {json.dumps(_stats)}", flush=True)


def _ser(v):
    """Serialize OPC-UA value to a JSON-safe Python type."""
    if isinstance(v, bool):     return v
    if hasattr(v, 'isoformat'): return v.isoformat()
    try:                         return float(v)
    except Exception:            return str(v)


def _load_schemas() -> dict:
    """Return {schema_id: schema_dict} from payload_schemas.json."""
    try:
        with open(SCHEMAS_FILE) as f:
            data = json.load(f)
        return {s['id']: s for s in data.get('schemas', [])}
    except Exception:
        return {}


def _format_payload(value, ts, unit, schema_id, topic, sep, schemas, data_type, tag_name):
    """Build a JSON payload string according to the named schema."""
    import datetime as _dt
    schema = schemas.get(schema_id) or schemas.get('standard')
    if not schema:
        return json.dumps({"value": value, "ts": ts, "unit": unit, "quality": "good"})

    parts = topic.split(sep)
    sources = {
        'value':          value,
        'ts_epoch':       ts,
        'ts_ms':          int(ts * 1000),
        'ts_iso':         _dt.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
        'quality':        'good',
        'is_good':        True,
        'quality_code':   192,
        'unit':           unit,
        'dataType':       data_type or 'Float',
        'tagName':        tag_name or (parts[-1] if parts else ''),
        'topicPath':      topic,
        'siteName':       parts[2] if len(parts) > 2 else '',
        'workCenterName': parts[4] if len(parts) > 4 else '',
    }

    payload = {}
    for field in schema.get('fields', []):
        key = field.get('key', '')
        if not key:
            continue

        source = field.get('source', '')

        if source == 'static':
            raw = field.get('staticVal', '')

            if raw == 'true':
                payload[key] = True
            elif raw == 'false':
                payload[key] = False
            else:
                try:
                    if raw != '':
                        payload[key] = float(raw) if '.' in raw else int(raw)
                    else:
                        payload[key] = ''
                except Exception:
                    payload[key] = raw

        elif 'static' in field:
            payload[key] = field['static']

        else:
            payload[key] = sources.get(source)

    return json.dumps(payload)


# ── OPC-UA node cache & poll ───────────────────────────────────────────────────

class OpcPoller:
    """
    Connects to the OPC-UA server once, builds a node cache from uns_config.json,
    and returns a list of (topic, json_payload_str) on each poll() call.
    Works with both MQTT (sync) and NATS (called via run_in_executor) modes.
    """

    def __init__(self, endpoint: str, sep: str, prefix: str):
        self.endpoint = endpoint
        self.sep      = sep
        self.prefix   = prefix
        self._opc     = None
        self._cache   = {}   # topic → (node_ref, unit_str)
        # Build entries from uns_config.json once at startup
        uns = _load_uns()
        self._namespace_uri = uns.get('namespaceUri', 'http://royalfarmerscollective.com/uns')
        self._entries = _build_entries(uns['tree'], sep, prefix)

    def connect(self):
        from opcua import Client
        self._opc = Client(self.endpoint)
        self._opc.connect()
        idx  = self._opc.get_namespace_index(self._namespace_uri)
        root = self._opc.get_root_node()

        if not self._cache:
            print("[bridge] Building node cache from uns_config.json...", flush=True)
            ok = miss = 0
            for topic, opc_parts, unit, schema_id, data_type, tag_name in self._entries:
                try:
                    node = root
                    path = ['0:Objects'] + [f'{idx}:{p}' for p in opc_parts]
                    for step in path:
                        node = node.get_child([step])
                    # opc_parts: [EnterpriseName, BusinessUnit, FactorySite, ...]
                    # plant_key matches sim_state.json: "BusinessUnit|FactorySite"
                    # Only set plant_key for tags that belong to specific sites
                    plant_key = None
                    if len(opc_parts) >= 3 and opc_parts[2].startswith('Factory'):
                        plant_key = f"{opc_parts[1]}|{opc_parts[2]}"
                    self._cache[topic] = (node, unit, schema_id, data_type, tag_name, plant_key)
                    ok += 1
                except Exception:
                    miss += 1
            print(f"[bridge] Cache ready: {ok} nodes ({miss} not found in OPC-UA)", flush=True)

        _stats["opc_ok"] = True

    def poll(self):
        """Returns list of (topic, payload_str). Raises on OPC-UA error."""
        ts       = time.time()
        schemas  = _load_schemas()
        sim_state = self._read_sim_state()

        # Check global simulator state - no publishing if simulator is off
        if not sim_state.get('simulator_running', False):
            return []

        out = []
        for topic, (node, unit, schema_id, data_type, tag_name, plant_key) in self._cache.items():
            try:
                v       = _ser(node.get_value())
                payload = _format_payload(v, ts, unit, schema_id, topic, self.sep,
                                          schemas, data_type, tag_name)
                out.append((topic, payload))
            except Exception:
                _stats["errors"] += 1
        return out

    @staticmethod
    def _read_sim_state() -> dict:
        sim_file = os.path.join(BASE_DIR, 'sim_state.json')
        try:
            with open(sim_file) as f:
                data = json.load(f)
                # Return both plants and global state
                result = data.get('plants', {}).copy()
                if 'simulator_running' in data:
                    result['simulator_running'] = data['simulator_running']
                return result
        except Exception:
            return {}

    def disconnect(self):
        _stats["opc_ok"] = False
        try:
            if self._opc:
                self._opc.disconnect()
        except Exception:
            pass
        self._opc = None


# ── MQTT mode (synchronous) ────────────────────────────────────────────────────

def run_mqtt(cfg):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("[bridge] ERROR: paho-mqtt not installed. Run:  pip install paho-mqtt", flush=True)
        sys.exit(1)

    _stats["protocol"] = "mqtt"
    host     = cfg.get("broker_host", "localhost")
    port     = int(cfg.get("broker_port", 1883))
    interval = float(cfg.get("interval", 2.0))
    print(f"[bridge] MQTT mode -> {host}:{port}", flush=True)

    # Use MQTTv311 — universally supported; upgrade to v5 only if broker advertises it
    try:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="uns-sim-bridge",
            protocol=mqtt.MQTTv311,
        )
    except AttributeError:
        # paho < 2.0 doesn't have CallbackAPIVersion
        client = mqtt.Client(client_id="uns-sim-bridge", protocol=mqtt.MQTTv311)

    # Back off reconnect attempts so rapid disconnect/reconnect cycles don't
    # overwhelm the broker (NATS MQTT adapter disconnects on burst publishes).
    try:
        client.reconnect_delay_set(min_delay=5, max_delay=60)
    except Exception:
        pass

    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password", ""))

    connected_ev = threading.Event()

    def on_connect(c, ud, flags, reason_code, props=None):
        rc = reason_code if isinstance(reason_code, int) else reason_code.value
        if rc == 0:
            _stats["connected"] = True
            connected_ev.set()
            print(f"[bridge] MQTT connected to {host}:{port}", flush=True)
            _emit()
        else:
            print(f"[bridge] MQTT connect failed rc={rc}", flush=True)

    def on_disconnect(c, ud, disconnect_flags=None, reason_code=None, props=None):
        _stats["connected"] = False
        rc = reason_code if reason_code is not None else disconnect_flags
        print(f"[bridge] MQTT disconnected (rc={rc})", flush=True)
        _emit()

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()

        if not connected_ev.wait(timeout=10):
            print(f"[bridge] MQTT connection timeout to {host}:{port}", flush=True)
            return

        opc_ep  = f"opc.tcp://{cfg['opc_host']}:{cfg['opc_port']}/freeopcua/server/"
        poller  = OpcPoller(opc_ep, "/", cfg.get("topic_prefix", "").strip())

        def pub(topic, payload):
            # Skip publish while disconnected — avoids buffering a large burst
            # that would overwhelm the broker immediately on reconnect.
            if _stats["connected"]:
                client.publish(topic, payload, qos=0, retain=False)

        _poll_loop(poller, pub, interval)

    except Exception as e:
        print(f"[bridge] MQTT fatal: {e}", flush=True)
    finally:
        client.loop_stop()
        try:   client.disconnect()
        except Exception: pass


# ── NATS mode (async) ──────────────────────────────────────────────────────────

def run_nats(cfg):
    try:
        import nats as nats_lib
    except ImportError:
        print("[bridge] ERROR: nats-py not installed. Run:  pip install nats-py", flush=True)
        sys.exit(1)

    import asyncio

    _stats["protocol"] = "nats"
    host     = cfg.get("broker_host", "localhost")
    port     = int(cfg.get("broker_port", 4222))
    interval = float(cfg.get("interval", 2.0))

    url = f"nats://{host}:{port}"
    if cfg.get("username"):
        url = f"nats://{cfg['username']}:{cfg.get('password','')}@{host}:{port}"

    print(f"[bridge] NATS mode -> {url}", flush=True)

    async def _run():
        global stop_flag
        try:
            nc = await nats_lib.connect(url)
        except Exception as e:
            print(f"[bridge] NATS connect error: {e}", flush=True)
            return

        _stats["connected"] = True
        print("[bridge] NATS connected", flush=True)
        _emit()

        opc_ep = f"opc.tcp://{cfg['opc_host']}:{cfg['opc_port']}/freeopcua/server/"
        poller = OpcPoller(opc_ep, ".", cfg.get("topic_prefix", "").strip())
        loop   = asyncio.get_running_loop()

        try:
            while not stop_flag:
                # OPC-UA is synchronous — run in thread pool so we don't block the event loop
                if not _stats["opc_ok"]:
                    try:
                        await loop.run_in_executor(None, poller.connect)
                    except Exception as e:
                        _stats["errors"] += 1
                        print(f"[bridge] OPC connect error: {e}", flush=True)
                        _emit()
                        await asyncio.sleep(5)
                        continue

                try:
                    t0    = time.time()
                    items = await loop.run_in_executor(None, poller.poll)
                    count = len(items)
                    for subject, payload in items:
                        await nc.publish(subject, payload.encode())
                    _stats["published"] += count
                    elapsed = time.time() - t0
                    _stats["rate"] = round(count / max(elapsed, 0.01), 1)
                    _emit()
                    await asyncio.sleep(max(0.0, interval - elapsed))

                except Exception as e:
                    _stats["opc_ok"] = False
                    await loop.run_in_executor(None, poller.disconnect)
                    print(f"[bridge] Poll error: {e}", flush=True)
                    _emit()

        finally:
            await loop.run_in_executor(None, poller.disconnect)
            try:
                _stats["connected"] = False
                await nc.drain()
            except Exception:
                pass

    asyncio.run(_run())


# ── Core polling loop (used only by MQTT sync mode) ───────────────────────────

def _poll_loop(poller: OpcPoller, publish_fn, interval: float):
    """Synchronous poll loop — shared by MQTT mode."""
    global stop_flag
    while not stop_flag:
        if not _stats["opc_ok"]:
            try:
                poller.connect()
            except Exception as e:
                _stats["errors"] += 1
                print(f"[bridge] OPC connect error: {e}", flush=True)
                _emit()
                time.sleep(5)
                continue

        try:
            t0    = time.time()
            items = poller.poll()
            count = len(items)
            for topic, payload in items:
                publish_fn(topic, payload)
            _stats["published"] += count
            elapsed = time.time() - t0
            _stats["rate"] = round(count / max(elapsed, 0.01), 1)
            _emit()
            time.sleep(max(0.0, interval - elapsed))

        except Exception as e:
            _stats["opc_ok"] = False
            poller.disconnect()
            print(f"[bridge] Poll error: {e}", flush=True)
            _emit()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg      = _load_cfg()
    protocol = cfg.get("protocol", "mqtt").lower()
    print(f"[bridge] UNS Bridge starting - protocol={protocol}", flush=True)
    _emit()

    if protocol == "nats":
        run_nats(cfg)
    else:
        run_mqtt(cfg)

    print("[bridge] Stopped", flush=True)
    _stats["connected"] = False
    _stats["opc_ok"]    = False
    _emit()

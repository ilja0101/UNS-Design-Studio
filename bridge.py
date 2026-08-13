#!/usr/bin/env python3
"""
UNS Bridge  –  OPC-UA → NATS (native)  /  OPC-UA → MQTT
Managed as a subprocess by app.py.
Emits  [BRIDGE_STATS] <json>  lines to stdout for app.py to parse.
Config: bridge_config.json in the same directory.

Install deps:
  MQTT mode:  pip install aiomqtt
  NATS mode:  pip install nats-py
"""

import asyncio
import json
import os
import sys
import time
import signal
import logging
from json_persistence import load_json, load_json_or_raise, load_json_async
from uns_tree import build_bridge_entries, build_command_entries, path_covered as _path_covered


def _live_config(sim_state: dict) -> dict:
    """Read the live-UNS membership block from sim_state (default: all live)."""
    raw = sim_state.get('live_nodes') if isinstance(sim_state, dict) else None
    if not isinstance(raw, dict) or raw.get('mode') != 'explicit':
        return {'mode': 'all'}
    return {'mode': 'explicit', 'paths': [p for p in raw.get('paths', []) if isinstance(p, str) and p]}

logging.getLogger('asyncua').setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARNING)

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
DATA_DIR         = os.environ.get("UNS_DATA_DIR") or ("/data" if os.name != 'nt' and os.path.isdir("/data") else BASE_DIR)
CONFIG_FILE      = os.path.join(DATA_DIR, 'bridge_config.json')
UNS_CONFIG_FILE  = os.path.join(DATA_DIR, 'uns_config.json')
SCHEMAS_FILE     = os.path.join(DATA_DIR, 'payload_schemas.json')
OPC_CACHE_MODE = os.getenv("UNS_BRIDGE_CACHE_MODE", "walk").strip().lower()
OPC_BROWSE_BATCH_SIZE = int(os.getenv("UNS_BRIDGE_OPC_BROWSE_BATCH", "100"))
OPC_READ_BATCH_SIZE = int(os.getenv("UNS_BRIDGE_OPC_READ_BATCH", "100"))
OPC_READ_CONCURRENCY = int(os.getenv("UNS_BRIDGE_OPC_READ_CONCURRENCY", "32"))
PUBLISH_BATCH_SIZE = int(os.getenv("UNS_BRIDGE_PUBLISH_BATCH", "250"))
# nats-py defaults to a 2 MiB outbound buffer. A 20k-tag poll is well past that,
# so while the client is mid-reconnect a publish raises OutboundBufferLimitError
# and the whole poll fails. Buffer a full poll instead.
NATS_PENDING_SIZE = int(os.getenv("UNS_BRIDGE_NATS_PENDING_MB", "64")) * 1024 * 1024
NATS_FLUSH_TIMEOUT = float(os.getenv("UNS_BRIDGE_NATS_FLUSH_TIMEOUT", "20"))

def _json_log(msg: str):
    print(msg, flush=True)

_stats = {
    "connected": False, "opc_ok": False,
    "published": 0, "errors": 0, "rate": 0.0,
    "protocol": "-", "ts": 0.0,
    "per_plant": {},   # plant_key -> published count (feeds the hub-spoke edge pulse)
    "commands": 0,     # write-back commands applied to OPC (optimizer setpoints)
}


# ── Command write-back helpers ────────────────────────────────────────────────

def _normalize_cmd_prefix(raw: str, sep: str) -> str:
    """Normalize a configured command prefix to the active subject separator."""
    p = (raw or "cmd").strip().replace("/", sep).replace(".", sep)
    while p.startswith(sep):
        p = p[len(sep):]
    while p.endswith(sep):
        p = p[:-len(sep)]
    return p or "cmd"


def _parse_command_payload(payload):
    """Extract a scalar from a command message. Accepts JSON {"value": X} (the
    standard telemetry schema), a bare JSON scalar, or a raw string/number."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    payload = payload.strip() if isinstance(payload, str) else payload
    try:
        obj = json.loads(payload)
        if isinstance(obj, dict):
            for k in ("value", "v", "setpoint", "sp"):
                if k in obj:
                    return obj[k]
            return None
        return obj
    except Exception:
        try:
            return float(payload)
        except Exception:
            return payload


def _coerce_command(data_type: str, raw):
    """Coerce a parsed value to (python_value, ua.VariantType) for the tag type."""
    from asyncua import ua as _ua
    dt = (data_type or "Float").strip()
    try:
        if dt in ("Bool", "Boolean"):
            if isinstance(raw, str):
                v = raw.strip().lower() in ("1", "true", "on", "yes")
            else:
                v = bool(raw)
            return v, _ua.VariantType.Boolean
        if dt in ("Int", "Int16", "Int32", "Int64", "Integer",
                  "UInt16", "UInt32", "UInt64"):
            return int(round(float(raw))), _ua.VariantType.Int64
        if dt in ("String", "Str"):
            return str(raw), _ua.VariantType.String
        return float(raw), _ua.VariantType.Double
    except (TypeError, ValueError):
        return None, None


def _load_cfg():
    try:
        return load_json_or_raise(CONFIG_FILE, logger=_json_log, label='bridge_config.json')
    except Exception as e:
        print(f"[bridge] Cannot read {CONFIG_FILE}: {e}", flush=True)
        sys.exit(1)


def _load_uns():
    try:
        return load_json_or_raise(UNS_CONFIG_FILE, logger=_json_log, label='uns_config.json')
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
    return build_bridge_entries(tree, sep, prefix)


def _emit():
    _stats["ts"] = time.time()
    print(f"[BRIDGE_STATS] {json.dumps(_stats)}", flush=True)


async def _sleep_or_stop(stop_event: asyncio.Event, delay: float):
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, delay))
    except asyncio.TimeoutError:
        pass


def _ser(v):
    """Serialize OPC-UA value to a JSON-safe Python type."""
    if isinstance(v, bool):     return v
    if hasattr(v, 'isoformat'): return v.isoformat()
    try:                         return float(v)
    except Exception:            return str(v)


def _load_schemas() -> dict:
    """Return {schema_id: schema_dict} from payload_schemas.json."""
    try:
        data = load_json(SCHEMAS_FILE, {}, logger=_json_log, label='payload_schemas.json')
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


# ── Async OPC-UA node cache & poll ────────────────────────────────────────────

class AsyncOpcPoller:
    """
    Connects to the OPC-UA server once using asyncua, builds a node cache from
    uns_config.json, and returns a list of (topic, json_payload_str) on each
    poll() call.
    """

    def __init__(self, endpoint: str, sep: str, prefix: str):
        self.endpoint = endpoint
        self.sep      = sep
        self.prefix   = prefix
        self._opc     = None
        self._batch_read_supported = True
        self._cache   = {}   # topic → (node_ref, unit_str, ...)
        self._cmd_nodes = {} # bare_topic → (node_ref, data_type)  for write-back
        uns = _load_uns()
        self._namespace_uri = uns.get('namespaceUri', 'http://royalfarmerscollective.com/uns')
        self._entries = _build_entries(uns['tree'], sep, prefix)
        self._cmd_entries = build_command_entries(uns['tree'], sep)

    async def connect(self):
        from asyncua import Client
        self._opc = Client(self.endpoint)
        await self._opc.connect()
        idx  = await self._opc.get_namespace_index(self._namespace_uri)
        root = self._opc.nodes.root

        if not self._cache:
            import time as _time
            t0 = _time.monotonic()
            print("[bridge] Building node cache from uns_config.json...", flush=True)

            if OPC_CACHE_MODE == "translate":
                ok, miss = await self._build_cache_with_translate(idx)
            else:
                ok, miss = await self._build_cache_with_walk(root, idx)
            elapsed = _time.monotonic() - t0
            print(f"[bridge] Cache ready: {ok} nodes ({miss} not found) in {elapsed:.1f}s", flush=True)

        if self._cmd_entries and not self._cmd_nodes:
            await self._build_command_cache(root, idx)

        _stats["opc_ok"] = True

    async def _build_command_cache(self, root, idx: int):
        """Resolve command (RW, qualifier=command) tags to OPC nodes so inbound
        setpoint requests can be written back into the address space."""
        node_cache = {(): root}
        ok = miss = 0
        for bare_topic, opc_parts, data_type in self._cmd_entries:
            try:
                path_parts = ['0:Objects'] + [f'{idx}:{p}' for p in opc_parts]
                node = root
                prefix = ()
                for step in path_parts:
                    prefix = prefix + (step,)
                    cached = node_cache.get(prefix)
                    if cached is None:
                        cached = await node.get_child([step])
                        node_cache[prefix] = cached
                    node = cached
                self._cmd_nodes[bare_topic] = (node, data_type)
                ok += 1
            except Exception:
                miss += 1
        print(f"[bridge] Command write-back: {ok} command tags mapped ({miss} not found)", flush=True)

    async def write_command(self, bare_topic: str, raw_value) -> tuple:
        """Write a setpoint request value to its OPC command node.

        Returns (ok, info) where info is a dict on success (with the value read
        back from OPC, confirming it persisted) or an error string on failure."""
        entry = self._cmd_nodes.get(bare_topic)
        if entry is None:
            return False, f"unknown command tag: {bare_topic}"
        node, data_type = entry
        val, vt = _coerce_command(data_type, raw_value)
        if vt is None:
            return False, f"unparseable value for {bare_topic}: {raw_value!r}"
        from asyncua import ua as _ua
        try:
            await node.write_value(_ua.DataValue(_ua.Variant(val, vt)))
            readback = None
            try:
                readback = _ser(await node.read_value())
            except Exception:
                pass
            return True, {"written": _ser(val), "readback": readback, "tag": bare_topic}
        except Exception as e:
            return False, str(e)

    async def _build_cache_with_walk(self, root, idx: int) -> tuple:
        node_cache = {(): root}
        ok = miss = 0
        for topic, opc_parts, unit, schema_id, data_type, tag_name, node_path in self._entries:
            try:
                path_parts = ['0:Objects'] + [f'{idx}:{p}' for p in opc_parts]
                node = root
                prefix = ()
                for step in path_parts:
                    prefix = prefix + (step,)
                    cached = node_cache.get(prefix)
                    if cached is None:
                        cached = await node.get_child([step])
                        node_cache[prefix] = cached
                    node = cached
                plant_key = None
                if len(opc_parts) >= 3 and opc_parts[2].startswith('Factory'):
                    plant_key = f"{opc_parts[1]}|{opc_parts[2]}"
                self._cache[topic] = (node, unit, schema_id, data_type, tag_name, plant_key, node_path)
                ok += 1
            except Exception:
                miss += 1
        return ok, miss

    async def _build_cache_with_translate(self, idx: int) -> tuple:
        from asyncua import ua as _ua

        def _make_bp(opc_parts):
            bp = _ua.BrowsePath()
            bp.StartingNode = _ua.TwoByteNodeId(_ua.ObjectIds.RootFolder)
            rp = _ua.RelativePath()
            elems = []
            for ns, name in [(0, 'Objects')] + [(idx, p) for p in opc_parts]:
                e = _ua.RelativePathElement()
                e.ReferenceTypeId = _ua.TwoByteNodeId(_ua.ObjectIds.HierarchicalReferences)
                e.IsInverse = False
                e.IncludeSubtypes = True
                e.TargetName = _ua.QualifiedName(Name=str(name), NamespaceIndex=int(ns))
                elems.append(e)
            rp.Elements = elems
            bp.RelativePath = rp
            return bp

        all_bps = [_make_bp(e[1]) for e in self._entries]
        all_res = await self._translate_browsepaths_adaptive(all_bps)

        ok = miss = 0
        for entry, res in zip(self._entries, all_res):
            topic, opc_parts, unit, schema_id, data_type, tag_name, node_path = entry
            if res.StatusCode.is_good() and res.Targets:
                node = self._opc.get_node(res.Targets[0].TargetId)
                plant_key = None
                if len(opc_parts) >= 3 and opc_parts[2].startswith('Factory'):
                    plant_key = f"{opc_parts[1]}|{opc_parts[2]}"
                self._cache[topic] = (node, unit, schema_id, data_type, tag_name, plant_key, node_path)
                ok += 1
            else:
                miss += 1
        return ok, miss

    async def _translate_browsepaths_adaptive(self, browse_paths: list) -> list:
        results = []
        for i in range(0, len(browse_paths), OPC_BROWSE_BATCH_SIZE):
            chunk = browse_paths[i:i + OPC_BROWSE_BATCH_SIZE]
            results.extend(await self._translate_browsepath_chunk(chunk))
        return results

    async def _translate_browsepath_chunk(self, browse_paths: list) -> list:
        try:
            return await self._opc.uaclient.translate_browsepaths_to_nodeids(browse_paths)
        except Exception as e:
            if len(browse_paths) <= 1:
                raise
            mid = len(browse_paths) // 2
            print(
                f"[bridge] BrowsePath batch of {len(browse_paths)} failed; retrying as {mid}+{len(browse_paths) - mid}: {e}",
                flush=True,
            )
            left = await self._translate_browsepath_chunk(browse_paths[:mid])
            right = await self._translate_browsepath_chunk(browse_paths[mid:])
            return left + right

    async def poll(self, stop_event: asyncio.Event = None) -> list:
        ts      = time.time()
        schemas = _load_schemas()
        sim_state = await self._read_sim_state()

        if not sim_state.get('simulator_running', False):
            return []

        # Live-UNS membership: only publish nodes that are part of the live UNS.
        # Absent / mode "all" => publish everything (default). Built once per poll.
        live = _live_config(sim_state)
        live_all = live.get('mode') != 'explicit'
        live_paths = live.get('paths', [])

        cache_items = list(self._cache.items())
        values = await self._read_cached_values(cache_items, stop_event)

        out = []
        for (topic, (node, unit, schema_id, data_type, tag_name, plant_key, node_path)), value in zip(cache_items, values):
            if stop_event and stop_event.is_set():
                break
            if not (live_all or _path_covered(node_path, live_paths)):
                continue
            try:
                if isinstance(value, Exception):
                    raise value
                v       = _ser(value)
                payload = _format_payload(v, ts, unit, schema_id, topic, self.sep,
                                          schemas, data_type, tag_name)
                out.append((topic, payload))
                if plant_key:
                    pp = _stats["per_plant"]
                    pp[plant_key] = pp.get(plant_key, 0) + 1
            except Exception:
                _stats["errors"] += 1
        return out

    async def _read_cached_values(self, cache_items: list, stop_event: asyncio.Event = None) -> list:
        if not cache_items:
            return []
        if self._batch_read_supported:
            try:
                return await self._read_values_batched(cache_items, stop_event)
            except Exception as e:
                self._batch_read_supported = False
                print(f"[bridge] OPC batch read unavailable, using bounded reads: {e}", flush=True)
        return await self._read_values_bounded(cache_items, stop_event)

    async def _read_values_batched(self, cache_items: list, stop_event: asyncio.Event = None) -> list:
        from asyncua import ua as _ua

        values = []
        for i in range(0, len(cache_items), OPC_READ_BATCH_SIZE):
            if stop_event and stop_event.is_set():
                break
            chunk = cache_items[i:i + OPC_READ_BATCH_SIZE]
            params = _ua.ReadParameters()
            params.TimestampsToReturn = _ua.TimestampsToReturn.Neither
            params.NodesToRead = []
            for _topic, (node, *_rest) in chunk:
                read_id = _ua.ReadValueId()
                read_id.NodeId = node.nodeid
                read_id.AttributeId = _ua.AttributeIds.Value
                params.NodesToRead.append(read_id)

            data_values = await self._opc.uaclient.read(params)
            for data_value in data_values:
                try:
                    status = getattr(data_value, "StatusCode", None)
                    if status is not None and hasattr(status, "is_good") and not status.is_good():
                        raise RuntimeError(str(status))
                    variant = getattr(data_value, "Value", data_value)
                    values.append(getattr(variant, "Value", variant))
                except Exception as e:
                    values.append(e)
        return values

    async def _read_values_bounded(self, cache_items: list, stop_event: asyncio.Event = None) -> list:
        sem = asyncio.Semaphore(max(1, OPC_READ_CONCURRENCY))

        async def _read_one(item):
            if stop_event and stop_event.is_set():
                return RuntimeError("bridge stopping")
            async with sem:
                try:
                    return await item[1][0].read_value()
                except Exception as e:
                    return e

        values = []
        for i in range(0, len(cache_items), OPC_READ_BATCH_SIZE):
            if stop_event and stop_event.is_set():
                break
            chunk = cache_items[i:i + OPC_READ_BATCH_SIZE]
            values.extend(await asyncio.gather(*(_read_one(item) for item in chunk)))
        return values

    @staticmethod
    async def _read_sim_state() -> dict:
        sim_file = os.path.join(DATA_DIR, 'sim_state.json')
        data = await load_json_async(sim_file, {}, logger=_json_log, label='sim_state.json')
        result = data.get('plants', {}).copy() if isinstance(data, dict) else {}
        if isinstance(data, dict) and 'simulator_running' in data:
            result['simulator_running'] = data['simulator_running']
        # Carry the live-UNS membership block through — without it the poll()
        # filter can never see explicit membership and would publish everything.
        if isinstance(data, dict) and 'live_nodes' in data:
            result['live_nodes'] = data['live_nodes']
        return result

    async def disconnect(self):
        _stats["opc_ok"] = False
        try:
            if self._opc:
                await self._opc.disconnect()
        except Exception:
            pass
        self._opc = None


class PublishError(Exception):
    """A broker publish failed.

    Distinct from an OPC failure so the caller can reconnect the broker without
    throwing away a working OPC session — rebuilding that cache means browsing
    every node again, which at 20k tags is minutes of silence.
    """

    def __init__(self, cause: BaseException):
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.cause = cause


async def _publish_batched(items: list, publish_one, stop_event: asyncio.Event,
                           concurrent: bool = False) -> int:
    """Publish one poll's worth of messages, a chunk at a time.

    `concurrent` must match how the client behaves, because the two protocols
    are limited by opposite things. Measured here, 20,723 messages per round:

        MQTT (aiomqtt)   serial 2,331 msg/s   chunked 4,096 msg/s
        NATS (nats-py)   serial 311,955 msg/s chunked 60,943 msg/s

    aiomqtt awaits the socket for every message, so overlapping a chunk keeps
    it busy. nats-py only appends to an outbound buffer — publishing is nearly
    free, and wrapping each call in a Task costs far more than it saves. So
    MQTT passes concurrent=True and NATS does not.

    PUBLISH_BATCH_SIZE bounds how many payloads are in flight (250 measured
    best; 5,000 is slower than serial). stop_event is honoured between chunks.
    """
    published = 0
    for i in range(0, len(items), PUBLISH_BATCH_SIZE):
        if stop_event.is_set():
            break
        chunk = items[i:i + PUBLISH_BATCH_SIZE]

        if not concurrent:
            for topic, payload in chunk:
                if stop_event.is_set():
                    break
                try:
                    await publish_one(topic, payload)
                except Exception as e:
                    _stats["errors"] += 1
                    raise PublishError(e)
                published += 1
            continue

        results = await asyncio.gather(
            *(publish_one(topic, payload) for topic, payload in chunk),
            return_exceptions=True,
        )
        first_error = None
        for res in results:
            if isinstance(res, BaseException):
                _stats["errors"] += 1
                if first_error is None:
                    first_error = res
            else:
                published += 1
        if first_error is not None:
            raise PublishError(first_error)
    return published


# ── MQTT mode (async via aiomqtt) ─────────────────────────────────────────────

async def run_mqtt(cfg, stop_event: asyncio.Event):
    try:
        import aiomqtt
    except ImportError:
        print("[bridge] ERROR: aiomqtt not installed. Run:  pip install aiomqtt", flush=True)
        sys.exit(1)

    _stats["protocol"] = "mqtt"
    host     = (cfg.get("broker_host", "localhost") or "localhost").strip()
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    port     = int(cfg.get("broker_port", 1883))
    interval = float(cfg.get("interval", 2.0))
    print(f"[bridge] MQTT mode -> {host}:{port}", flush=True)

    opc_ep = f"opc.tcp://{cfg['opc_host']}:{cfg['opc_port']}/freeopcua/server/"
    poller = AsyncOpcPoller(opc_ep, "/", cfg.get("topic_prefix", "").strip())

    kwargs = {}
    if cfg.get("username"):
        kwargs["username"] = cfg["username"]
        kwargs["password"] = cfg.get("password", "")

    while not stop_event.is_set():
        try:
            async with aiomqtt.Client(host, port=port, **kwargs) as client:
                _stats["connected"] = True
                print(f"[bridge] MQTT connected to {host}:{port}", flush=True)
                _emit()

                # ── Command write-back: subscribe to setpoint requests ──
                cmd_task = None
                cmd_enabled = bool(cfg.get("command_write", True)) and bool(poller._cmd_entries)
                if cmd_enabled:
                    cmd_base = _normalize_cmd_prefix(cfg.get("command_prefix", "cmd"), "/")
                    await client.subscribe(f"{cmd_base}/#")

                    async def _mqtt_cmd_loop():
                        try:
                            async for message in client.messages:
                                subj = str(message.topic)
                                pfx  = cmd_base + "/"
                                if not subj.startswith(pfx):
                                    continue
                                raw = _parse_command_payload(message.payload)
                                ok, info = await poller.write_command(subj[len(pfx):], raw)
                                if ok:
                                    _stats["commands"] += 1
                                else:
                                    _stats["errors"] += 1
                                    print(f"[bridge] command rejected: {info}", flush=True)
                        except Exception as e:
                            print(f"[bridge] MQTT command loop ended: {e}", flush=True)

                    cmd_task = asyncio.create_task(_mqtt_cmd_loop())
                    print(f"[bridge] Command write-back subscribed on {cmd_base}/#", flush=True)

                while not stop_event.is_set():
                    if not _stats["opc_ok"]:
                        try:
                            await poller.connect()
                        except Exception as e:
                            await poller.disconnect()
                            _stats["errors"] += 1
                            print(f"[bridge] OPC connect error: {e}", flush=True)
                            _emit()
                            await _sleep_or_stop(stop_event, 5)
                            continue

                    try:
                        t0    = time.time()
                        items = await poller.poll(stop_event)

                        async def _publish_one(topic, payload):
                            await client.publish(topic, payload)

                        count = await _publish_batched(items, _publish_one, stop_event,
                                                       concurrent=True)
                        _stats["published"] += count
                        elapsed = time.time() - t0
                        _stats["rate"] = round(count / max(elapsed, 0.01), 1)
                        _emit()
                        await _sleep_or_stop(stop_event, max(0.0, interval - elapsed))

                    except PublishError as e:
                        # Broker-side only. Drop out to rebuild the MQTT client
                        # but keep the OPC session and its cache.
                        print(f"[bridge] Publish error: {e}; reconnecting broker", flush=True)
                        _emit()
                        break

                    except Exception as e:
                        _stats["opc_ok"] = False
                        await poller.disconnect()
                        print(f"[bridge] Poll error: {e}", flush=True)
                        _emit()
                        break

                if cmd_task is not None:
                    cmd_task.cancel()

        except Exception as e:
            _stats["connected"] = False
            print(f"[bridge] MQTT connection error: {e}, retrying in 5s", flush=True)
            _emit()
            await _sleep_or_stop(stop_event, 5)

    _stats["connected"] = False
    await poller.disconnect()


# ── NATS mode (async) ──────────────────────────────────────────────────────────

async def run_nats(cfg, stop_event: asyncio.Event):
    try:
        import nats as nats_lib
    except ImportError:
        print("[bridge] ERROR: nats-py not installed. Run:  pip install nats-py", flush=True)
        sys.exit(1)

    _stats["protocol"] = "nats"
    host     = (cfg.get("broker_host", "localhost") or "localhost").strip()
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    port     = int(cfg.get("broker_port", 4222))
    interval = float(cfg.get("interval", 2.0))

    url = f"nats://{host}:{port}"
    if cfg.get("username"):
        url = f"nats://{cfg['username']}:{cfg.get('password','')}@{host}:{port}"

    # A NATS server in operator mode authenticates with a credentials file and
    # refuses username/password outright. Every AMIX broker runs operator mode,
    # so without this the bridge can reach a plain nats-server and nothing on a
    # governed mesh. nats-py reads the file itself, so the path is the one
    # inside this container.
    opts = {
        "max_reconnect_attempts": -1,   # never stop trying to reconnect
        "reconnect_time_wait": 2,
        "connect_timeout": 5,
        "pending_size": NATS_PENDING_SIZE,
    }
    creds = str(cfg.get("creds") or "").strip()
    if creds:
        opts["user_credentials"] = creds

    print(f"[bridge] NATS mode -> {url}" + (f" (creds {creds})" if creds else ""), flush=True)

    # Retry the initial connect until the broker is reachable, and enable
    # infinite reconnect so the bridge survives the broker starting later or
    # restarting, such as when the whole fleet starts together and NATS is
    # still booting. Without this the bridge would give up on the first failure
    # and stay off until somebody restarted it.
    nc = None
    while not stop_event.is_set():
        try:
            nc = await nats_lib.connect(url, **opts)
            break
        except Exception as e:
            print(f"[bridge] NATS connect error: {e}; retrying in 3s", flush=True)
            await _sleep_or_stop(stop_event, 3)
    if nc is None:
        return

    _stats["connected"] = True
    print("[bridge] NATS connected", flush=True)
    _emit()

    opc_ep = f"opc.tcp://{cfg['opc_host']}:{cfg['opc_port']}/freeopcua/server/"
    poller = AsyncOpcPoller(opc_ep, ".", cfg.get("topic_prefix", "").strip())

    # ── Command write-back: subscribe to optimizer setpoint requests ──
    # The optimizer publishes to  <command_prefix>.<uns.name.path>.<tag>  and the
    # bridge writes the value into the matching OPC command node. Uses a distinct
    # subject prefix from telemetry so the bridge never receives its own
    # publishes (no feedback loop).
    if bool(cfg.get("command_write", True)) and poller._cmd_entries:
        cmd_base = _normalize_cmd_prefix(cfg.get("command_prefix", "cmd"), ".")

        async def _on_command(msg):
            # Works for both fire-and-forget publishes and request-reply: if the
            # optimizer used nc.request(), NATS sets msg.reply and we return an
            # immediate transport-level ack (accepted/rejected + value read back).
            # The *control* decision (mode/limits/watchdog) is separate — the
            # optimizer observes it on the loop's …/status telemetry tag.
            reply = getattr(msg, "reply", "") or ""
            try:
                subj = msg.subject
                pfx  = cmd_base + "."
                if not subj.startswith(pfx):
                    if reply:
                        await nc.publish(reply, json.dumps(
                            {"status": "rejected", "error": "subject outside command prefix"}).encode())
                    return
                raw = _parse_command_payload(msg.data)
                ok, info = await poller.write_command(subj[len(pfx):], raw)
                if ok:
                    _stats["commands"] += 1
                    if reply:
                        await nc.publish(reply, json.dumps({"status": "accepted", **info}).encode())
                else:
                    _stats["errors"] += 1
                    print(f"[bridge] command rejected: {info}", flush=True)
                    if reply:
                        await nc.publish(reply, json.dumps({"status": "rejected", "error": info}).encode())
            except Exception as e:
                print(f"[bridge] command handler error: {e}", flush=True)
                if reply:
                    try:
                        await nc.publish(reply, json.dumps({"status": "error", "error": str(e)}).encode())
                    except Exception:
                        pass

        try:
            await nc.subscribe(f"{cmd_base}.>", cb=_on_command)
            print(f"[bridge] Command write-back subscribed on {cmd_base}.>", flush=True)
        except Exception as e:
            print(f"[bridge] Command subscribe failed: {e}", flush=True)

    try:
        while not stop_event.is_set():
            if not _stats["opc_ok"]:
                try:
                    await poller.connect()
                except Exception as e:
                    await poller.disconnect()
                    _stats["errors"] += 1
                    print(f"[bridge] OPC connect error: {e}", flush=True)
                    _emit()
                    await _sleep_or_stop(stop_event, 5)
                    continue

            try:
                t0    = time.time()
                items = await poller.poll(stop_event)

                async def _publish_one(subject, payload):
                    await nc.publish(subject, payload.encode())

                count = await _publish_batched(items, _publish_one, stop_event)
                if count:
                    # nc.publish only appends to the outbound buffer. Flushing
                    # here is what makes "rate" mean messages actually on the
                    # wire, and surfaces broker backpressure as latency instead
                    # of as a silently growing buffer.
                    try:
                        await nc.flush(timeout=NATS_FLUSH_TIMEOUT)
                    except Exception as e:
                        raise PublishError(e)
                _stats["published"] += count
                elapsed = time.time() - t0
                _stats["rate"] = round(count / max(elapsed, 0.01), 1)
                _emit()
                await _sleep_or_stop(stop_event, max(0.0, interval - elapsed))

            except PublishError as e:
                # Broker-side only; nats-py reconnects on its own. Skip this
                # poll rather than tearing down OPC and re-browsing every node.
                print(f"[bridge] Publish error: {e}; skipping poll", flush=True)
                _emit()
                await _sleep_or_stop(stop_event, 1)
                continue

            except Exception as e:
                _stats["opc_ok"] = False
                await poller.disconnect()
                print(f"[bridge] Poll error: {e}", flush=True)
                _emit()

    finally:
        await poller.disconnect()
        try:
            _stats["connected"] = False
            await nc.drain()
        except Exception:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────

async def _main():
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            signal.signal(sig, lambda _s, _f: stop_event.set())

    cfg      = _load_cfg()
    protocol = cfg.get("protocol", "mqtt").lower()
    print(f"[bridge] UNS Bridge starting - protocol={protocol}", flush=True)
    _emit()

    if protocol == "nats":
        await run_nats(cfg, stop_event)
    else:
        await run_mqtt(cfg, stop_event)

    print("[bridge] Stopped", flush=True)
    _stats["connected"] = False
    _stats["opc_ok"]    = False
    _emit()


if __name__ == "__main__":
    # On Windows the default Proactor event loop does not implement
    # loop.add_reader/add_writer, which aiomqtt (paho) relies on — so MQTT mode
    # fails to connect with a NotImplementedError / timeout. The Selector loop
    # supports them and is safe here: the bridge only does socket I/O, it never
    # spawns subprocesses (the reason Proactor is the platform default).
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except AttributeError:
            pass
    asyncio.run(_main())

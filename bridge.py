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
from uns_tree import build_bridge_entries

logging.getLogger('asyncua').setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARNING)

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
DATA_DIR         = os.environ.get("UNS_DATA_DIR") or ("/data" if os.path.isdir("/data") else BASE_DIR)
CONFIG_FILE      = os.path.join(DATA_DIR, 'bridge_config.json')
UNS_CONFIG_FILE  = os.path.join(DATA_DIR, 'uns_config.json')
SCHEMAS_FILE     = os.path.join(DATA_DIR, 'payload_schemas.json')
OPC_BROWSE_BATCH_SIZE = int(os.getenv("UNS_BRIDGE_OPC_BROWSE_BATCH", "100"))
OPC_READ_BATCH_SIZE = int(os.getenv("UNS_BRIDGE_OPC_READ_BATCH", "500"))
OPC_READ_CONCURRENCY = int(os.getenv("UNS_BRIDGE_OPC_READ_CONCURRENCY", "64"))
PUBLISH_BATCH_SIZE = int(os.getenv("UNS_BRIDGE_PUBLISH_BATCH", "250"))

def _json_log(msg: str):
    print(msg, flush=True)

_stats = {
    "connected": False, "opc_ok": False,
    "published": 0, "errors": 0, "rate": 0.0,
    "protocol": "-", "ts": 0.0,
}


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
        uns = _load_uns()
        self._namespace_uri = uns.get('namespaceUri', 'http://royalfarmerscollective.com/uns')
        self._entries = _build_entries(uns['tree'], sep, prefix)

    async def connect(self):
        from asyncua import Client
        self._opc = Client(self.endpoint)
        await self._opc.connect()
        idx  = await self._opc.get_namespace_index(self._namespace_uri)
        root = self._opc.nodes.root

        if not self._cache:
            import time as _time
            from asyncua import ua as _ua
            t0 = _time.monotonic()
            print("[bridge] Building node cache from uns_config.json...", flush=True)

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

            # Translate BrowsePaths in adaptive chunks; large UNS models can
            # overwhelm asyncua's server if thousands are requested at once.
            all_bps   = [_make_bp(e[1]) for e in self._entries]
            all_res   = await self._translate_browsepaths_adaptive(all_bps)

            ok = miss = 0
            for entry, res in zip(self._entries, all_res):
                topic, opc_parts, unit, schema_id, data_type, tag_name = entry
                if res.StatusCode.is_good() and res.Targets:
                    node = self._opc.get_node(res.Targets[0].TargetId)
                    plant_key = None
                    if len(opc_parts) >= 3 and opc_parts[2].startswith('Factory'):
                        plant_key = f"{opc_parts[1]}|{opc_parts[2]}"
                    self._cache[topic] = (node, unit, schema_id, data_type, tag_name, plant_key)
                    ok += 1
                else:
                    miss += 1
            elapsed = _time.monotonic() - t0
            print(f"[bridge] Cache ready: {ok} nodes ({miss} not found) in {elapsed:.1f}s", flush=True)

        _stats["opc_ok"] = True

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

        cache_items = list(self._cache.items())
        values = await self._read_cached_values(cache_items, stop_event)

        out = []
        for (topic, (node, unit, schema_id, data_type, tag_name, plant_key)), value in zip(cache_items, values):
            if stop_event and stop_event.is_set():
                break
            try:
                if isinstance(value, Exception):
                    raise value
                v       = _ser(value)
                payload = _format_payload(v, ts, unit, schema_id, topic, self.sep,
                                          schemas, data_type, tag_name)
                out.append((topic, payload))
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
        return result

    async def disconnect(self):
        _stats["opc_ok"] = False
        try:
            if self._opc:
                await self._opc.disconnect()
        except Exception:
            pass
        self._opc = None


async def _publish_batched(items: list, publish_one, stop_event: asyncio.Event) -> int:
    published = 0
    for i in range(0, len(items), PUBLISH_BATCH_SIZE):
        if stop_event.is_set():
            break
        chunk = items[i:i + PUBLISH_BATCH_SIZE]
        for topic, payload in chunk:
            if stop_event.is_set():
                break
            await publish_one(topic, payload)
            published += 1
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

                        count = await _publish_batched(items, _publish_one, stop_event)
                        _stats["published"] += count
                        elapsed = time.time() - t0
                        _stats["rate"] = round(count / max(elapsed, 0.01), 1)
                        _emit()
                        await _sleep_or_stop(stop_event, max(0.0, interval - elapsed))

                    except Exception as e:
                        _stats["opc_ok"] = False
                        await poller.disconnect()
                        print(f"[bridge] Poll error: {e}", flush=True)
                        _emit()
                        break

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

    print(f"[bridge] NATS mode -> {url}", flush=True)

    try:
        nc = await nats_lib.connect(url)
    except Exception as e:
        print(f"[bridge] NATS connect error: {e}", flush=True)
        return

    _stats["connected"] = True
    print("[bridge] NATS connected", flush=True)
    _emit()

    opc_ep = f"opc.tcp://{cfg['opc_host']}:{cfg['opc_port']}/freeopcua/server/"
    poller = AsyncOpcPoller(opc_ep, ".", cfg.get("topic_prefix", "").strip())

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
                _stats["published"] += count
                elapsed = time.time() - t0
                _stats["rate"] = round(count / max(elapsed, 0.01), 1)
                _emit()
                await _sleep_or_stop(stop_event, max(0.0, interval - elapsed))

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
    asyncio.run(_main())

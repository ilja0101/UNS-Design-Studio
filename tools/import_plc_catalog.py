#!/usr/bin/env python3
"""Import a browsed PLC/Kepware tag catalog into a UNS Design Studio config.

Turns a "raw" PLC datasource export into a simulatable OPC-UA address space,
so the protocol-converter / SCADA side can browse a realistic Kepware-shaped
server (channel -> device -> tag groups / UDT instances -> tags).

Accepted input formats (auto-detected per file):
  1. UNS-Protocol-Converter catalog export
       - catalog_<sourceID>.json cache / GET /api/catalog:
         {"nodes":[{source_id,node_id,browse_path:[..],display_name,data_type,
                    description,writable}]}  (optionally wrapped in {loaded,count,nodes})
       - catalog.csv (columns: source_id,node_id,browse_path,display_name,
                      data_type,description,writable,...)
  2. Native Kepware export
       - JSON project export: {"project":{"channels":[{devices:[{tags,tag_groups}]}]}}
       - per-channel/device tag CSV ("Tag Name","Address","Data Type",
         "Client Access","Scan Rate","Scaled Low/High","Description",...)

Usage:
  python tools/import_plc_catalog.py <export> [<export> ...] [-o plc_configs/plc.json]
         [--name PLC-Sim] [--source-id X] [--channel Y] [--prefix Chan1.Dev1]

Also importable as a module: import_files(paths, name=...) -> config dict.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------- datatypes
# Target values are the dataType strings factory.py's variant mapping accepts.
# Kepware JSON project export TAG_DATA_TYPE integer codes.
_KEPWARE_DT_ENUM = {
    -1: "Float", 0: "String", 1: "Boolean", 2: "Int16", 3: "Int16",
    4: "Int16", 5: "UInt16", 6: "Int32", 7: "UInt32", 8: "Float",
    9: "Double", 10: "UInt16", 11: "UInt32", 12: "DateTime",
    13: "Int64", 14: "UInt64",
}
# OPC-UA built-in DataType numeric NodeIds (ns=0) — how a browsed catalog reports
# types (e.g. "i=1" Boolean, "i=10" Float). Structured/extension types (higher
# ids: NodeId, ExtensionObject, custom structs) have no scalar sim value → String.
_OPCUA_BUILTIN_DT = {
    1: "Boolean", 2: "Int16", 3: "Int16", 4: "Int16", 5: "UInt16", 6: "Int32",
    7: "UInt32", 8: "Int64", 9: "UInt64", 10: "Float", 11: "Double",
    12: "String", 13: "DateTime", 14: "String", 15: "String", 16: "String",
    17: "String", 18: "String", 19: "String", 20: "String", 21: "String",
}
_DT_NAME_MAP = {
    # Kepware names
    "word": "UInt16", "dword": "UInt32", "qword": "UInt64", "short": "Int16",
    "long": "Int32", "llong": "Int64", "bcd": "UInt16", "lbcd": "UInt32",
    "char": "Int16", "byte": "UInt16", "date": "DateTime",
    # OPC-UA / converter names
    "float": "Float", "double": "Double", "real": "Float", "boolean": "Boolean",
    "bool": "Boolean", "string": "String", "datetime": "DateTime",
    "int16": "Int16", "int32": "Int32", "int64": "Int64", "sbyte": "Int16",
    "uint16": "UInt16", "uint32": "UInt32", "uint64": "UInt64",
    "int": "Int32", "integer": "Int32", "number": "Double",
    "localizedtext": "String", "bytestring": "String", "guid": "String",
}

_unknown_dt: Counter = Counter()
_OPCUA_NODEID_RE = re.compile(r"^(?:ns=\d+;)?i=(\d+)$")

def _map_dt(raw) -> str:
    if raw is None or raw == "":
        return "Float"
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return _KEPWARE_DT_ENUM.get(int(raw), "Float")
    key = str(raw).strip()
    # OPC-UA NodeId form ("i=10", "ns=0;i=10") from a browsed catalog
    m = _OPCUA_NODEID_RE.match(key)
    if m:
        code = int(m.group(1))
        if code in _OPCUA_BUILTIN_DT:
            return _OPCUA_BUILTIN_DT[code]
        _unknown_dt[key] += 1
        return "String"
    # Custom/structured type reference ("ns=2;s=SortingEngineState") — not a
    # scalar; represent inertly as String rather than a numeric walk.
    if "s=" in key or key.startswith("ns="):
        _unknown_dt[key] += 1
        return "String"
    low = key.lower()
    # "Word Array" / "Byte Array" etc. → element type (arrays sim as scalars)
    if low.endswith(" array"):
        low = low[: -len(" array")].strip()
    if low in _DT_NAME_MAP:
        return _DT_NAME_MAP[low]
    _unknown_dt[key] += 1
    return "Float"

_NUMERIC_DT = {"Float", "Double", "Int16", "Int32", "Int64", "UInt16", "UInt32", "UInt64"}

# ---------------------------------------------------------------- records
def _record(segments, data_type, writable=False, description="", scan_rate=None,
            eng_lo=None, eng_hi=None, address=None, node_id=None):
    return {
        "segments": [s for s in segments if s], "data_type": data_type,
        "writable": bool(writable), "description": description or "",
        "scan_rate": scan_rate, "eng_lo": eng_lo, "eng_hi": eng_hi,
        "address": address, "node_id": node_id,
    }

def _to_float(v):
    try:
        f = float(str(v).strip())
        return f
    except (TypeError, ValueError):
        return None

# OPC-UA / Kepware server-side branches that are not PLC process data — dropped
# by default so a simulated PLC exposes only real tags. `_`-prefixed segments are
# Kepware diagnostic groups (_Statistics, _System, _CommunicationSerialization…).
_SKIP_TOP = {"Server", "Aliases", "OPCUAServer", "_DataLogger", "_CommunicationSerialization"}

def _clean_catalog_path(path, channel=None):
    """Normalize a browsed catalog path into channel-rooted segments, or None to skip.

    Strips the OPC-UA "Objects" root, drops server/diagnostic branches, and
    (when `channel` is given) keeps only that top-level channel."""
    segs = [s for s in (path if isinstance(path, list) else str(path).split(".")) if s]
    if segs and segs[0] == "Objects":
        segs = segs[1:]
    if not segs:
        return None
    if segs[0] in _SKIP_TOP or any(s.startswith("_") for s in segs):
        return None
    if channel and segs[0] != channel:
        return None
    return segs

# ---------------------------------------------------------------- parsers
def _parse_converter_catalog_json(data, source_id=None, channel=None):
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if nodes is None:
        raise ValueError("converter catalog JSON has no 'nodes' array")
    sources = {n.get("source_id") or "" for n in nodes}
    multi = len({s for s in sources if s}) > 1
    out = []
    for n in nodes:
        sid = n.get("source_id") or ""
        if source_id and sid and sid != source_id:
            continue
        segs = _clean_catalog_path(n.get("browse_path") or [], channel=channel)
        if not segs:
            continue
        if multi and sid and not source_id:
            segs = [sid] + segs
        out.append(_record(segs, _map_dt(n.get("data_type")),
                           writable=bool(n.get("writable")),
                           description=n.get("description", ""),
                           node_id=n.get("node_id")))
    return out

def _parse_converter_catalog_csv(text, source_id=None, channel=None):
    rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    sources = {(r.get("source_id") or "").strip() for r in rows}
    multi = len({s for s in sources if s}) > 1
    for r in rows:
        sid = (r.get("source_id") or "").strip()
        if source_id and sid and sid != source_id:
            continue
        segs = _clean_catalog_path((r.get("browse_path") or "").strip(), channel=channel)
        if not segs:
            continue
        if multi and sid and not source_id:
            segs = [sid] + segs
        out.append(_record(segs, _map_dt(r.get("data_type")),
                           writable=str(r.get("writable", "")).strip().lower() in ("true", "1", "yes"),
                           description=(r.get("description") or "").strip(),
                           node_id=(r.get("node_id") or "").strip() or None))
    return out

def _parse_kepware_project_json(data, channel=None):
    proj = data.get("project", data)
    channels = proj.get("channels") or []
    out = []

    def name_of(obj):
        return str(obj.get("common.ALLTYPES_NAME", "")).strip()

    def tag_records(tags, prefix):
        for t in tags or []:
            nm = name_of(t)
            if not nm:
                continue
            lo = _to_float(t.get("servermain.TAG_SCALING_SCALED_LOW"))
            hi = _to_float(t.get("servermain.TAG_SCALING_SCALED_HIGH"))
            out.append(_record(prefix + [nm], _map_dt(t.get("servermain.TAG_DATA_TYPE")),
                               writable=int(t.get("servermain.TAG_READ_WRITE_ACCESS", 0) or 0) == 1,
                               description=str(t.get("common.ALLTYPES_DESCRIPTION", "") or ""),
                               scan_rate=_to_float(t.get("servermain.TAG_SCAN_RATE_MILLISECONDS")),
                               eng_lo=lo, eng_hi=hi,
                               address=t.get("servermain.TAG_ADDRESS")))

    def walk_groups(groups, prefix):
        for g in groups or []:
            gp = prefix + [name_of(g)]
            tag_records(g.get("tags"), gp)
            walk_groups(g.get("tag_groups"), gp)

    for ch in channels:
        ch_name = name_of(ch)
        if channel and ch_name != channel:
            continue
        for dev in ch.get("devices") or []:
            prefix = [ch_name, name_of(dev)]
            tag_records(dev.get("tags"), prefix)
            walk_groups(dev.get("tag_groups"), prefix)
    return out

def _parse_kepware_csv(text, prefix=None, channel=None):
    """Kepware tag CSV → records.

    Real Kepware CSVs carry only a leaf 'Tag Name'; the structure lives in the
    'Address' column (e.g. Channel.Tags.Table.Tag or Channel.Blocks.Block.Member).
    We build the browse path from Address (channel-rooted, so no filename prefix
    is needed), falling back to Tag Name / an explicit prefix when Address is
    absent."""
    rows = list(csv.DictReader(io.StringIO(text)))
    pre = [p for p in (prefix or "").split(".") if p]
    out = []
    for r in rows:
        r = {(k or "").strip().lstrip("﻿"): v for k, v in r.items()}
        name = (r.get("Tag Name") or r.get("TagName") or "").strip().strip('"')
        address = (r.get("Address") or "").strip().strip('"')
        if not name and not address:
            continue
        if address and "." in address:
            segs = pre + address.split(".")
        elif pre:
            segs = pre + (name.split(".") if name else [address])
        else:
            segs = (name or address).split(".")
        if channel and segs and segs[0] != channel:
            continue
        access = (r.get("Client Access") or "").strip().upper()
        lo = _to_float(r.get("Scaled Low"))
        hi = _to_float(r.get("Scaled High"))
        if lo is None and hi is None:
            lo, hi = _to_float(r.get("Raw Low")), _to_float(r.get("Raw High"))
        out.append(_record(segs, _map_dt(r.get("Data Type")),
                           writable="R/W" in access or access == "RW",
                           description=(r.get("Description") or "").strip(),
                           scan_rate=_to_float(r.get("Scan Rate")),
                           eng_lo=lo, eng_hi=hi,
                           address=address or None))
    return out

def parse_export(text: str, filename: str = "", source_id=None, channel=None, prefix=None):
    """Auto-detect one export file's format and return normalized records."""
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict) and ("project" in data or "channels" in data):
            return _parse_kepware_project_json(data, channel=channel)
        if isinstance(data, dict) and "nodes" in data:
            return _parse_converter_catalog_json(data, source_id=source_id, channel=channel)
        if isinstance(data, list) and data and isinstance(data[0], dict) and "browse_path" in data[0]:
            return _parse_converter_catalog_json({"nodes": data}, source_id=source_id, channel=channel)
        raise ValueError(f"{filename or 'input'}: unrecognized JSON export "
                         "(expected converter catalog 'nodes' or Kepware 'project/channels')")
    # CSV — decide by header
    header = stripped.splitlines()[0] if stripped else ""
    if "browse_path" in header:
        return _parse_converter_catalog_csv(text, source_id=source_id, channel=channel)
    if "Tag Name" in header or "TagName" in header:
        # Structure comes from the Address column; only fall back to a filename
        # prefix if Address turns out to be flat.
        return _parse_kepware_csv(text, prefix=prefix, channel=channel)
    raise ValueError(f"{filename or 'input'}: unrecognized CSV export "
                     "(expected converter catalog.csv or Kepware tag CSV)")

# ---------------------------------------------------------------- sim profiles
# keyword -> (base, min, max, std, unit)
_ANALOG_HINTS = [
    (("rpm", "speed"),                 (1450.0, 0.0, 3000.0, 8.0,  "rpm")),
    (("current", "amp"),               (12.5,   0.0, 80.0,   0.4,  "A")),
    (("power", "_kw", "kw_", "watt"),  (7.5,    0.0, 90.0,   0.3,  "kW")),
    (("volt",),                        (400.0,  0.0, 500.0,  2.0,  "V")),
    (("freq", "hz"),                   (49.5,   0.0, 60.0,   0.2,  "Hz")),
    (("temp",),                        (55.0,   -10.0, 150.0, 0.5, "°C")),
    (("press", "bar", "psi"),          (4.2,    0.0, 12.0,   0.1,  "bar")),
    (("flow", "gpm", "m3h"),           (32.0,   0.0, 120.0,  1.0,  "m3/h")),
    (("level",),                       (62.0,   0.0, 100.0,  0.8,  "%")),
    (("weight", "mass", "load"),       (250.0,  0.0, 1000.0, 3.0,  "kg")),
    (("torque",),                      (35.0,   0.0, 150.0,  0.8,  "Nm")),
    (("vib",),                         (2.2,    0.0, 25.0,   0.15, "mm/s")),
    (("humid",),                       (48.0,   0.0, 100.0,  0.6,  "%")),
    (("position", "valve", "pct", "percent", "%"), (50.0, 0.0, 100.0, 0.7, "%")),
    (("ph",),                          (7.1,    0.0, 14.0,   0.05, "pH")),
]
_BOOL_RUN_WORDS   = ("run", "on", "enable", "start", "active", "avail", "ready", "auto")
_BOOL_FAULT_WORDS = ("fault", "fail", "trip", "error", "noodstop")
_BOOL_ALARM_WORDS = ("alarm", "alm", "warn")
_COUNTER_WORDS    = ("total", "count", "counter", "accum", "cumul", "hours", "runtime")
# Genuine setpoints/commands hold their written value; everything else keeps
# simulating even when writable (a real PLC PV is writable but still changes).
_SETPOINT_WORDS   = ("setpoint", "_sp", "sp_", "spwaarde", "sollwert", "instel",
                     "command", "_cmd", "cmd_", "_ref", "ref_", "wens", "target")

def _is_setpoint(name):
    n = name.lower()
    return any(w in n for w in _SETPOINT_WORDS) or n.endswith("sp") or n.endswith("cmd")

def _sim_for(rec):
    """Choose a simulation profile + unit for one normalized record.

    Writability alone does NOT freeze a tag — most PLC memory is R/W yet the
    PV still moves. Only tags whose name reads as a setpoint/command get the
    `hold` profile (accept + persist a write); the rest simulate and remain
    writable, matching a live PLC."""
    name = rec["segments"][-1].lower()
    dt = rec["data_type"]
    lo, hi = rec.get("eng_lo"), rec.get("eng_hi")

    if _is_setpoint(name):
        default = False if dt == "Boolean" else ("" if dt == "String" else 0)
        return {"profile": "hold", "default": default}, ""

    if dt == "Boolean":
        if any(w in name for w in _BOOL_FAULT_WORDS):
            return {"profile": "boolean_fault"}, ""
        if any(w in name for w in _BOOL_ALARM_WORDS):
            return {"profile": "boolean_alarm"}, ""
        return {"profile": "boolean_running"}, ""

    if dt == "String":
        return {"profile": "hold", "default": ""}, ""
    if dt == "DateTime":
        return {"profile": "default"}, ""

    if any(w in name for w in _COUNTER_WORDS):
        return {"profile": "accumulator_generic"}, ""

    for words, (base, mn, mx, std, unit) in _ANALOG_HINTS:
        if any(w in name for w in words):
            sim = {"profile": "default", "base": base, "min": mn, "max": mx,
                   "std": std, "default": base}
            if lo is not None and hi is not None and hi > lo:
                span = hi - lo
                sim.update({"min": lo, "max": hi, "base": lo + span * 0.55,
                            "std": max(span * 0.005, 0.01),
                            "default": round(lo + span * 0.55, 2)})
            return sim, unit

    # No keyword hit: generic bounded walk (scaling limits if the export had them)
    if lo is not None and hi is not None and hi > lo:
        span = hi - lo
        return {"profile": "default", "min": lo, "max": hi,
                "base": lo + span * 0.5, "std": max(span * 0.01, 0.01),
                "default": round(lo + span * 0.5, 2)}, ""
    return {"profile": "default", "min": 0.0, "max": 100.0, "base": 40.0,
            "std": 1.5, "default": 40.0}, ""

# ---------------------------------------------------------------- tree build
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "x"

def build_tree(records, name="PLC-Sim"):
    """Rebuild the browse hierarchy from normalized records -> Design Studio config."""
    root = {"id": f"ent-{_slug(name)}", "name": name, "type": "enterprise",
            "description": "Simulated raw PLC datasource (imported catalog)",
            "children": [], "tags": []}
    index = {(): root}
    dropped = 0

    for rec in records:
        segs = rec["segments"]
        if len(segs) < 2:
            dropped += 1
            continue
        # interior segments -> nodes; channel=folder, device level=device, rest folder
        for d in range(1, len(segs)):
            key = tuple(segs[:d])
            if key in index:
                continue
            parent = index[tuple(segs[:d - 1])]
            ntype = "folder" if d == 1 else ("device" if d == 2 else "folder")
            node = {"id": None, "name": segs[d - 1], "type": ntype,
                    "description": "", "children": [], "tags": []}
            parent["children"].append(node)
            index[key] = node
        leaf_parent = index[tuple(segs[:-1])]
        sim, unit = _sim_for(rec)
        # Setpoint/command tags that are writable expose a bridge command topic;
        # other tags are plain data (writable or not — a PV can be R/W).
        is_cmd = rec["writable"] and sim.get("profile") == "hold"
        tag = {
            "id": None, "name": segs[-1], "dataType": rec["data_type"],
            "unit": unit, "description": rec["description"],
            "access": "RW" if rec["writable"] else "read",
            "qualifier": "command" if is_cmd else "data",
            "simulation": sim,
        }
        if rec.get("address"):
            tag["plcAddress"] = rec["address"]
        if rec.get("scan_rate"):
            tag["scanRateMs"] = rec["scan_rate"]
        leaf_parent["tags"].append(tag)

    _detect_udts(root)
    _assign_ids(root)
    cfg = {
        "version": "1.0",
        "lastModified": datetime.datetime.now(datetime.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "namespaceUri": f"http://plc-sim/{_slug(name)}",
        "description": f"{name} — simulated PLC/Kepware datasource "
                       "(generated by tools/import_plc_catalog.py)",
        "tree": root,
    }
    return cfg, dropped

def _detect_udts(root):
    """Stamp udtType on nodes whose child-structure repeats — mapping ground truth."""
    groups = {}
    def sig(node):
        return (tuple(sorted(t["name"] for t in node.get("tags", []))),
                tuple(sorted(c["name"] for c in node.get("children", []))))
    def walk(node):
        for c in node.get("children", []):
            s = sig(c)
            if len(s[0]) + len(s[1]) >= 2:
                groups.setdefault(s, []).append(c)
            walk(c)
    walk(root)
    for s, nodes in groups.items():
        if len(nodes) < 2:
            continue
        stems = Counter(re.sub(r"[\d_\-\s]+$", "", n["name"]) or n["name"] for n in nodes)
        stem = stems.most_common(1)[0][0]
        for n in nodes:
            n["udtType"] = f"UDT_{stem}"

def _assign_ids(root):
    seen = set()
    def unique(base):
        if base not in seen:
            seen.add(base)
            return base
        i = 2
        while f"{base}-{i}" in seen:
            i += 1
        seen.add(f"{base}-{i}")
        return f"{base}-{i}"
    def walk(node, path):
        npath = f"{path}-{node['name']}" if path else node["name"]
        if not node.get("id"):
            node["id"] = unique("nd-" + _slug(npath))
        for t in node.get("tags", []):
            if not t.get("id"):
                t["id"] = unique("tg-" + _slug(f"{npath}-{t['name']}"))
        for c in node.get("children", []):
            walk(c, npath)
    walk(root, "")

# ---------------------------------------------------------------- entry points
def import_payloads(payloads, name="PLC-Sim", source_id=None, channel=None, prefix=None):
    """payloads: iterable of (filename, text). Returns (config_dict, summary_dict)."""
    _unknown_dt.clear()
    records = []
    for fname, text in payloads:
        records.extend(parse_export(text, filename=fname, source_id=source_id,
                                    channel=channel, prefix=prefix))
    if not records:
        raise ValueError("no tags found in the provided export(s)")
    cfg, dropped = build_tree(records, name=name)

    counts = {"nodes": 0, "tags": 0, "devices": 0, "folders": 0, "udt_nodes": 0}
    def walk(n):
        counts["nodes"] += 1
        counts["tags"] += len(n.get("tags", []))
        if n.get("type") == "device":
            counts["devices"] += 1
        elif n.get("type") == "folder":
            counts["folders"] += 1
        if n.get("udtType"):
            counts["udt_nodes"] += 1
        for c in n.get("children", []):
            walk(c)
    walk(cfg["tree"])
    summary = {**counts, "records": len(records), "dropped_rows": dropped,
               "unknown_datatypes": dict(_unknown_dt)}
    return cfg, summary

def import_files(paths, name="PLC-Sim", **kw):
    payloads = []
    for p in paths:
        with open(p, "r", encoding="utf-8-sig") as fh:
            payloads.append((os.path.basename(p), fh.read()))
    return import_payloads(payloads, name=name, **kw)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", help="export file(s): converter catalog JSON/CSV or Kepware JSON/CSV")
    ap.add_argument("-o", "--output", help="output config path (default plc_configs/<name>.json)")
    ap.add_argument("--name", default="PLC-Sim", help="root/enterprise name for the simulated server")
    ap.add_argument("--source-id", help="only import this converter source_id")
    ap.add_argument("--channel", help="only import this Kepware channel (JSON project export)")
    ap.add_argument("--prefix", help="dot path prepended to Kepware CSV tags (e.g. Channel1.PLC_A)")
    args = ap.parse_args(argv)

    cfg, summary = import_files(args.inputs, name=args.name, source_id=args.source_id,
                                channel=args.channel, prefix=args.prefix)
    out = args.output or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "plc_configs", f"{_slug(args.name)}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)

    print(f"[import-plc] wrote {out}")
    print(f"[import-plc] records={summary['records']} nodes={summary['nodes']} "
          f"tags={summary['tags']} devices={summary['devices']} folders={summary['folders']} "
          f"udt-instances={summary['udt_nodes']} dropped={summary['dropped_rows']}")
    if summary["unknown_datatypes"]:
        print(f"[import-plc] NOTE unrecognized datatypes (custom/structured → String, "
              f"unknown names → Float): {summary['unknown_datatypes']}")
    print(f"[import-plc] run it:  UDS_CONFIG={out} UDS_OPC_PORT=4841 UDS_TCP_PORT=9998 python factory.py")
    return 0

if __name__ == "__main__":
    sys.exit(main())

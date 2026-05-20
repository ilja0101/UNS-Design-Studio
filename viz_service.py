"""Visualization helpers — pure logic, no Flask, no opcua dep.

Equipment-kind heuristics, UNS→OPC path resolution, viz config I/O, and a
gauge-value collector that takes the OPC traversal as a callable so this
module stays import-clean and testable.
"""

import json
import re
from json_persistence import load_json_async, save_json_atomic_async


EQUIPMENT_KINDS = [
    'tank', 'pump', 'vessel', 'motor', 'valve', 'mixer',
    'reactor', 'conveyor', 'silo', 'heat_exchanger', 'compressor',
    'boiler', 'chiller', 'dryer', 'filter', 'centrifuge', 'column',
    'clarifier', 'screen', 'mill', 'fan', 'flowmeter', 'evaporator',
    'generic',
]

KIND_HEURISTICS = [
    (r'\b(boiler|steam[\s_-]?gen)\b',                 'boiler'),
    (r'\b(chiller|cooler|refrig|freezer)\b',          'chiller'),
    (r'\b(dryer|drier|tumbler)\b',                    'dryer'),
    (r'\b(filter|strainer)\b',                        'filter'),
    (r'\b(centrifuge|separator|decanter)\b',          'centrifuge'),
    (r'\b(column|tower|distill|absorber|stripper)\b', 'column'),
    (r'\b(clarifier|settler|sediment|thickener)\b',   'clarifier'),
    (r'\b(screen|sieve|sifter)\b',                    'screen'),
    (r'\b(mill|grinder|crusher|shredder)\b',          'mill'),
    (r'\b(fan|blower|exhaust)\b',                     'fan'),
    (r'\b(flow[\s_-]?meter|flowmeter|\bfm\b)\b',      'flowmeter'),
    (r'\b(evaporator|concentrator|blancher)\b',       'evaporator'),
    (r'\b(tank|reservoir)\b',                         'tank'),
    (r'\b(silo|hopper|bin)\b',                        'silo'),
    (r'\b(pump)\b',                                   'pump'),
    (r'\b(motor|drive)\b',                            'motor'),
    (r'\b(valve)\b',                                  'valve'),
    (r'\b(mixer|blender|agitator)\b',                 'mixer'),
    (r'\b(reactor|fermenter)\b',                      'reactor'),
    (r'\b(conveyor|belt)\b',                          'conveyor'),
    (r'\b(vessel|kettle)\b',                          'vessel'),
    (r'\b(heat[\s_-]?exchanger|hx)\b',                'heat_exchanger'),
    (r'\b(compressor)\b',                             'compressor'),
]

DEFAULT_VIZ_CFG = {
    'version': 1, 'entities': {}, 'links': [], 'gauges': [], 'animations': []
}

_MAPPABLE = {'site', 'area', 'workCenter', 'workUnit'}


def suggest_kind(name: str) -> str:
    """Return an equipment kind for a free-text name, else 'generic'."""
    n = (name or '').lower().replace('_', ' ')
    for pat, kind in KIND_HEURISTICS:
        if re.search(pat, n):
            return kind
    return 'generic'


def load_viz_cfg(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return dict(DEFAULT_VIZ_CFG, entities={}, links=[], gauges=[], animations=[])


def save_viz_cfg(path: str, data: dict):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _read_uns(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def walk_entities(uns_config_path: str) -> list:
    """Surfaces site / area / workCenter / workUnit nodes from the UNS tree.
    Skips enterprise + BU + tags. Returns list of dicts ready for the editor."""
    cfg = _read_uns(uns_config_path)
    out = []

    def walk(node, parts):
        ntype = node.get('type', '')
        name = node.get('name', '')
        new_parts = parts + [name]
        if ntype in _MAPPABLE:
            out.append({
                'id':         '|'.join(new_parts),
                'name':       name,
                'type':       ntype,
                'parentPath': '|'.join(parts),
                'tags':       [t.get('name') for t in node.get('tags', [])],
            })
        for child in node.get('children', []):
            walk(child, new_parts)

    walk(cfg.get('tree', {}), [])
    return out


def _find_node(tree: dict, parts: list):
    """Walk a UNS tree by name path. Returns (node, opc_parts, area_opc) or None."""
    if not parts or tree.get('name') != parts[0]:
        return None
    node = tree
    opc_parts = []
    area_opc = []
    for name in parts[1:]:
        child = next((c for c in node.get('children', []) if c.get('name') == name), None)
        if not child:
            return None
        ntype = child.get('type', '')
        opc_parts.append(('Factory' + name) if ntype == 'site' else name)
        if ntype == 'area':
            area_opc = list(opc_parts)
        node = child
    return node, opc_parts, area_opc


def resolve_tag_path(uns_config_path: str, entity_id: str, tag_name: str) -> list:
    """UNS entity id + tag name → OPC path list (from enterprise root).
    Mirrors factory.py naming: 'Factory' prefix on site nodes, opcPath is
    area-relative, opcNodeName overrides leaf."""
    found = _find_node(_read_uns(uns_config_path).get('tree', {}), (entity_id or '').split('|'))
    if not found:
        return []
    node, opc_parts, area_opc = found
    for tag in node.get('tags', []):
        if tag.get('name') != tag_name:
            continue
        if 'opcPath' in tag:
            return area_opc + tag['opcPath'].split('/')
        return opc_parts + [tag.get('opcNodeName', tag_name)]
    return []


def entity_tags(uns_config_path: str, entity_id: str) -> list:
    """Tags on a UNS entity, shaped for the gauge config dropdown."""
    found = _find_node(_read_uns(uns_config_path).get('tree', {}), entity_id.split('|'))
    if not found:
        return []
    node, _, _ = found
    out = []
    for t in node.get('tags', []):
        sim = t.get('simulation', {}) if isinstance(t.get('simulation'), dict) else {}
        out.append({
            'name':     t.get('name', ''),
            'dataType': t.get('dataType', 'Float'),
            'unit':     t.get('unit', ''),
            'profile':  sim.get('profile', ''),
        })
    return out


async def load_viz_cfg_async(path: str) -> dict:
    data = await load_json_async(path, None)
    if data is None:
        return dict(DEFAULT_VIZ_CFG, entities={}, links=[], gauges=[], animations=[])
    return data


async def save_viz_cfg_async(path: str, data: dict):
    await save_json_atomic_async(path, data)


async def collect_values_async(gauges: list, resolve_path, read_value) -> dict:
    """Async version of collect_values — read_value must be an async callable."""
    out = {}
    for g in gauges:
        gid = g.get('id') or f"{g.get('entity', '')}#{g.get('tag', '')}"
        path = resolve_path(g.get('entity', ''), g.get('tag', ''))
        if not path:
            out[gid] = None
            continue
        v = await read_value(path)
        if isinstance(v, bool):
            out[gid] = v
        elif isinstance(v, (int, float)):
            out[gid] = v
        elif hasattr(v, 'isoformat'):
            out[gid] = v.isoformat()
        else:
            out[gid] = str(v) if v is not None else None
    return out


def collect_values(gauges: list, resolve_path, read_value) -> dict:
    """Read OPC values for every gauge.
      gauges       : list of {id?, entity, tag}
      resolve_path : (entity, tag) -> list[str] | []
      read_value   : (path: list[str]) -> primitive | None
    Returns {gauge_id: value}. None when path or read fails.
    """
    out = {}
    for g in gauges:
        gid = g.get('id') or f"{g.get('entity', '')}#{g.get('tag', '')}"
        path = resolve_path(g.get('entity', ''), g.get('tag', ''))
        if not path:
            out[gid] = None
            continue
        v = read_value(path)
        if isinstance(v, bool):
            out[gid] = v
        elif isinstance(v, (int, float)):
            out[gid] = v
        elif hasattr(v, 'isoformat'):
            out[gid] = v.isoformat()
        else:
            out[gid] = str(v) if v is not None else None
    return out

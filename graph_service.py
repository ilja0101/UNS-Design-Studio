#!/usr/bin/env python3
"""Build the hub-spoke graph payload (/api/graph) from the live UNS config.

Everything is derived from uns_config.json at request time — no assumptions
about names, depth or shape, so it works for any user-built (or empty) UNS.
Node ids are enterprise-rooted "|"-joined name paths, matching
uns_tree.build_bridge_entries so live-membership prefixes line up exactly.
"""

from uns_tree import resolve_enterprise_root, path_covered
from sim_state_service import get_live_config


def _plant_key_for(bu_name: str, site_name: str) -> str:
    return f"{bu_name}|{site_name}"


def build_graph(tree: dict, sim_state: dict, bridge_stats: dict | None = None) -> dict:
    """Return the GraphResponse dict for the current UNS + live/running state."""
    bridge_stats = bridge_stats or {}
    live = get_live_config(sim_state)
    live_all = live['mode'] != 'explicit'
    live_paths = live['paths']
    plants = sim_state.get('plants', {}) if isinstance(sim_state, dict) else {}
    per_plant = bridge_stats.get('per_plant', {}) if isinstance(bridge_stats, dict) else {}
    simulator_running = bool(sim_state.get('simulator_running', True)) if isinstance(sim_state, dict) else True

    ent_name, ent_node = resolve_enterprise_root(tree)
    nodes = []
    bu_count = 0

    def _running(plant_key: str) -> bool:
        v = plants.get(plant_key)
        if isinstance(v, dict):
            return bool(v.get('running', False))
        return bool(v) if v is not None else False

    def _walk(node, parts, bu_name, plant_key):
        nonlocal bu_count
        ntype = node.get('type', '')
        name = node.get('name', '')
        new_parts = parts + [name]
        node_id = '|'.join(new_parts)

        # thread the plant_key: set at site level (BU|Site), inherited below.
        # 'system' nodes (phase 2) are their own always-on "plant".
        nbu = name if ntype == 'businessUnit' else bu_name
        npk = plant_key
        if ntype == 'site':
            npk = _plant_key_for(bu_name or '', name)
        elif ntype == 'system':
            npk = _plant_key_for(bu_name or ent_name, name)
        if ntype == 'businessUnit':
            bu_count += 1

        own_tags = node.get('tags', []) or []
        is_live = live_all or path_covered(node_id, live_paths)
        running = _running(npk) if npk else False
        nodes.append({
            'id': node_id,
            'type': ntype,
            'name': name,
            'parentId': '|'.join(parts) if parts else None,
            'depth': len(parts),
            'live': bool(is_live),
            'running': running,
            'hasTags': len(own_tags) > 0,
            'tagCount': len(own_tags),
            'plantKey': npk,
            'publishRate': per_plant.get(npk, 0) if npk else 0,
            'description': node.get('description', ''),
        })
        for child in node.get('children', []):
            _walk(child, new_parts, nbu, npk)

    if isinstance(ent_node, dict) and ent_node.get('name'):
        _walk(ent_node, [], '', None)

    return {
        'enterprise': {'id': ent_name, 'name': ent_name},
        'singleBusinessUnit': bu_count == 1,
        'nodes': nodes,
        'liveMode': live['mode'],
        'simulatorRunning': simulator_running,
        'bridge': {
            'connected': bool(bridge_stats.get('connected', False)),
            'protocol': bridge_stats.get('protocol', '-'),
            'msgsPerSec': bridge_stats.get('rate', 0.0),
            'perPlant': per_plant,
        },
    }

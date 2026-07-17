#!/usr/bin/env python3
"""Shared UNS tree traversal helpers."""

import re


def enterprise_structure(cfg: dict, fallback: dict) -> dict:
    """Return {businessUnitName: [bareSiteName, ...]} from a UNS config."""
    if not isinstance(cfg, dict):
        return fallback
    struct = {}

    def _business_units(node: dict):
        if not isinstance(node, dict):
            return
        if node.get('type') == 'businessUnit':
            yield node
            return
        for child in node.get('children', []):
            yield from _business_units(child)

    for bu in _business_units(cfg.get('tree', {})):
        if bu.get('type') == 'businessUnit':
            plants = [
                site['name']
                for site in bu.get('children', [])
                if site.get('type') == 'site'
            ]
            if plants:
                struct[bu['name']] = plants
    return struct


def sanitize_topic_part(value: str) -> str:
    """Replace characters invalid in MQTT topics / NATS subjects with underscores."""
    return re.sub(r'[\s#+]', '_', value)


def resolve_enterprise_root(tree: dict, default_name: str = 'GlobalFoodCo') -> tuple:
    """Resolve the enterprise root node from a UNS tree.

    Two layouts supported:
      • Tree IS the enterprise (has 'name')   → (tree['name'], tree)
      • Tree is a wrapper with one child     → (child['name'], child)
    Falls back to (default_name, tree) when neither is present.
    """
    if not isinstance(tree, dict):
        return (default_name, {})
    name = tree.get('name', '')
    if name:
        return (name, tree)
    for child in tree.get('children', []):
        if isinstance(child, dict) and child.get('name'):
            return (child['name'], child)
    return (default_name, tree)


def build_bridge_entries(tree: dict, sep: str, prefix: str) -> list:
    """Walk the UNS config tree and return bridge entries for explicitly configured tags.

    Walking starts at the enterprise node — wrapper trees are unwrapped so
    opc_parts and topic always start with the enterprise name (matching the
    OPC root created by factory.py).
    """
    entries = []
    _, enterprise_node = resolve_enterprise_root(tree)

    def _walk(node, uns_parts, opc_parts, area_opc_parts):
        ntype = node.get('type', '')
        name = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name

        new_uns = uns_parts + [name]
        new_opc = opc_parts + [opc_name]
        new_area_opc = new_opc if ntype == 'area' else area_opc_parts

        for tag in node.get('tags', []):
            tag_uns = tag['name']
            tag_unit = tag.get('unit', '')
            tag_schema = tag.get('payloadSchema', 'standard') or 'standard'
            tag_data_type = tag.get('dataType', 'Float')

            if 'opcPath' in tag:
                tag_opc_parts = new_area_opc + tag['opcPath'].split('/')
            else:
                tag_opc_name = tag.get('opcNodeName', tag_uns)
                tag_opc_parts = new_opc + [tag_opc_name]

            safe_uns_parts = [sanitize_topic_part(part) for part in new_uns]
            safe_tag_uns = sanitize_topic_part(tag_uns)
            topic = sep.join(safe_uns_parts + [safe_tag_uns])
            if prefix:
                topic = prefix + sep + topic
            # node_path is the "|"-joined UNS name path of the node this tag lives
            # on (unsanitized, matching viz_service / plant_key conventions). Used
            # for per-node live-UNS membership filtering in the bridge.
            node_path = '|'.join(new_uns)
            entries.append((topic, tag_opc_parts, tag_unit, tag_schema, tag_data_type, tag_uns, node_path))

        for child in node.get('children', []):
            _walk(child, new_uns, new_opc, new_area_opc)

    _walk(enterprise_node, [], [], [])
    return entries


def build_command_entries(tree: dict, sep: str) -> list:
    """Walk the UNS config and return write-back entries for command tags.

    A command tag is a writable tag (access == "RW") whose qualifier is
    "command" — i.e. a …/cmd/*-request the optimizer publishes to. Returns
    (bare_topic, opc_parts, data_type) with no topic prefix; the bridge maps an
    incoming command subject (command_prefix + sep + bare_topic) back to the OPC
    node addressed by opc_parts. OPC path rules match build_bridge_entries().
    """
    entries = []
    _, enterprise_node = resolve_enterprise_root(tree)

    def _walk(node, uns_parts, opc_parts, area_opc_parts):
        ntype = node.get('type', '')
        name = node.get('name', '')
        opc_name = ('Factory' + name) if ntype == 'site' else name
        new_uns = uns_parts + [name]
        new_opc = opc_parts + [opc_name]
        new_area_opc = new_opc if ntype == 'area' else area_opc_parts

        for tag in node.get('tags', []):
            access    = str(tag.get('access', 'R')).upper()
            qualifier = str(tag.get('qualifier', 'data')).lower()
            if access != 'RW' or qualifier != 'command':
                continue
            tag_uns = tag['name']
            if 'opcPath' in tag:
                tag_opc_parts = new_area_opc + tag['opcPath'].split('/')
            else:
                tag_opc_parts = new_opc + [tag.get('opcNodeName', tag_uns)]
            safe_uns_parts = [sanitize_topic_part(p) for p in new_uns]
            bare_topic = sep.join(safe_uns_parts + [sanitize_topic_part(tag_uns)])
            entries.append((bare_topic, tag_opc_parts, tag.get('dataType', 'Float')))

        for child in node.get('children', []):
            _walk(child, new_uns, new_opc, new_area_opc)

    _walk(enterprise_node, [], [], [])
    return entries


# ── Live-UNS membership (per-node publish gating) ──────────────────────────────
# Membership is expressed as a set of inclusion *prefixes* over "|"-joined node
# paths. A node publishes iff its path equals, or is a descendant of, one of the
# prefixes. This makes "add a branch (with everything under it)" a single entry,
# and auto-includes assets added later under a live branch. Everything is derived
# from the live tree — no assumptions about names, depth or shape.

def path_covered(node_path: str, prefixes) -> bool:
    """True if node_path is equal to, or a descendant of, any prefix."""
    for p in prefixes:
        if node_path == p or node_path.startswith(p + '|'):
            return True
    return False


def _find_by_path(root: dict, parts: list):
    """Return the node at the given "|"-split name path (rooted at *root*), or None."""
    if not parts or root.get('name') != parts[0]:
        return None
    node = root
    for name in parts[1:]:
        child = next((c for c in node.get('children', []) if c.get('name') == name), None)
        if child is None:
            return None
        node = child
    return node


def carve_out(tree: dict, ancestor_path: str, remove_path: str) -> list:
    """Return the inclusion prefixes that keep everything under *ancestor_path*
    live EXCEPT the *remove_path* subtree.

    Walks from the ancestor toward the node to remove; at each step every sibling
    that does not continue toward remove_path is kept as its own prefix. Removing
    the ancestor itself (ancestor_path == remove_path) yields []. Robust to any
    tree shape; a stale path simply stops the walk early.
    """
    _, enterprise_node = resolve_enterprise_root(tree)
    a_parts = ancestor_path.split('|')
    r_parts = remove_path.split('|')
    if r_parts[:len(a_parts)] != a_parts:
        # remove_path is not under ancestor_path — nothing to carve, keep ancestor.
        return [ancestor_path]
    node = _find_by_path(enterprise_node, a_parts)
    if node is None:
        return [ancestor_path]
    kept = []
    cur_parts = list(a_parts)
    rel = r_parts[len(a_parts):]           # segments from ancestor down to remove
    for seg in rel:
        for child in node.get('children', []):
            cname = child.get('name', '')
            if cname != seg:
                kept.append('|'.join(cur_parts + [cname]))
        nxt = next((c for c in node.get('children', []) if c.get('name') == seg), None)
        if nxt is None:
            break                          # stale path — stop; remove already excluded
        node = nxt
        cur_parts = cur_parts + [seg]
    return kept

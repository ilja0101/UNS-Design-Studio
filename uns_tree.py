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
            entries.append((topic, tag_opc_parts, tag_unit, tag_schema, tag_data_type, tag_uns))

        for child in node.get('children', []):
            _walk(child, new_uns, new_opc, new_area_opc)

    _walk(enterprise_node, [], [], [])
    return entries

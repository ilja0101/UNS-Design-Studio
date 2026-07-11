#!/usr/bin/env python3
"""Simulation state merge/sync helpers used by the Flask dashboard."""

from uns_tree import resolve_enterprise_root, path_covered, carve_out


# ── Live-UNS membership ────────────────────────────────────────────────────────
# Stored in sim_state under "live_nodes": {"mode": "all"} (or key absent) means
# the whole UNS publishes; {"mode": "explicit", "paths": [...]} publishes only the
# node subtrees covered by the inclusion prefixes. See uns_tree.path_covered.

def get_live_config(sim_state: dict) -> dict:
    """Return a normalized {mode, paths} live-membership config (default all-live)."""
    raw = sim_state.get('live_nodes') if isinstance(sim_state, dict) else None
    if not isinstance(raw, dict) or raw.get('mode') != 'explicit':
        return {'mode': 'all', 'paths': []}
    paths = [p for p in raw.get('paths', []) if isinstance(p, str) and p]
    return {'mode': 'explicit', 'paths': _dedupe_prefixes(paths)}


def reset_live(sim_state: dict, mode: str) -> dict:
    """'all' → whole UNS live; 'none' → nothing live (the demo Clear button)."""
    if not isinstance(sim_state, dict):
        sim_state = {}
    sim_state['live_nodes'] = {'mode': 'all'} if mode == 'all' else {'mode': 'explicit', 'paths': []}
    return get_live_config(sim_state)


def set_live(sim_state: dict, tree: dict, path: str, live: bool,
             include_descendants: bool = True) -> dict:
    """Add or remove a node subtree from the live UNS. Returns the new config.

    Adding a node makes it and its descendants publish (and any assets added
    under it later). Removing from within a broader live branch carves the branch
    so siblings stay live. Works on any tree shape; nothing is hardcoded.
    """
    cfg = get_live_config(sim_state)
    paths = list(cfg['paths'])

    if live:
        if cfg['mode'] == 'all':
            pass  # already fully live
        elif not path_covered(path, paths):
            # drop now-redundant descendant prefixes, then add this branch
            paths = [p for p in paths if not path_covered(p, [path])]
            paths.append(path)
            sim_state['live_nodes'] = {'mode': 'explicit', 'paths': _dedupe_prefixes(paths)}
    else:
        enterprise_name, _ = resolve_enterprise_root(tree)
        if cfg['mode'] == 'all':
            # carve the removed subtree out of the whole enterprise
            paths = carve_out(tree, enterprise_name, path)
        else:
            new_paths = []
            for p in paths:
                if p == path or p.startswith(path + '|'):
                    continue                       # drop the removed subtree / descendants
                if path.startswith(p + '|'):
                    new_paths.extend(carve_out(tree, p, path))  # split the covering branch
                else:
                    new_paths.append(p)
            paths = new_paths
        sim_state['live_nodes'] = {'mode': 'explicit', 'paths': _dedupe_prefixes(paths)}

    return get_live_config(sim_state)


def _dedupe_prefixes(paths) -> list:
    """Drop duplicates and any prefix already covered by a shorter one."""
    uniq = sorted(set(paths), key=lambda p: (p.count('|'), p))
    out = []
    for p in uniq:
        if not path_covered(p, [q for q in out]):
            out.append(p)
    return out


def get_site_recipes(site_node: dict) -> list:
    """Return normalized recipe definitions stored directly on a site node."""
    raw = site_node.get('recipes', [])
    return [
        r if isinstance(r, dict) else {'name': str(r), 'params': {}}
        for r in raw
    ]


def sync_sim_state_with_uns(cfg: dict, sim_state: dict) -> dict:
    """Return sim_state synchronized with the current UNS tree."""
    if not isinstance(sim_state, dict):
        sim_state = {'plants': {}, 'simulator_running': False}
    if 'plants' not in sim_state:
        sim_state['plants'] = {}

    current_enterprise_keys = set()

    def _business_units(node: dict):
        if not isinstance(node, dict):
            return
        if node.get('type') == 'businessUnit':
            yield node
            return
        for child in node.get('children', []):
            yield from _business_units(child)

    for bu in _business_units(cfg.get('tree', {})):

        bu_name = bu.get('name')

        for site in bu.get('children', []):
            if site.get('type') != 'site':
                continue

            site_name = site.get('name')
            plant_key = f"{bu_name}|{site_name}"
            current_enterprise_keys.add(plant_key)
            recipes = get_site_recipes(site)

            if plant_key not in sim_state['plants']:
                sim_state['plants'][plant_key] = {
                    'running': False,
                    'recipe': recipes[0]['name'] if recipes else '--NA--',
                    'recipes': recipes,
                }
            else:
                plant_state = sim_state['plants'][plant_key]
                if isinstance(plant_state, dict):
                    if 'running' not in plant_state:
                        plant_state['running'] = False
                    if 'recipes' not in plant_state or plant_state['recipes'] != recipes:
                        plant_state['recipes'] = recipes
                    if 'recipe' not in plant_state or not any(r.get('name') == plant_state.get('recipe') for r in recipes):
                        plant_state['recipe'] = recipes[0]['name'] if recipes else '--NA--'
                else:
                    sim_state['plants'][plant_key] = {
                        'running': bool(plant_state),
                        'recipe': recipes[0]['name'] if recipes else '--NA--',
                        'recipes': recipes,
                    }

    for key in [k for k in sim_state['plants'].keys() if k not in current_enterprise_keys]:
        del sim_state['plants'][key]

    return sim_state


def merge_sim_state_update(current: dict, data: dict) -> dict:
    """Merge API update data into sim_state, preserving legacy bool compatibility."""
    if not isinstance(current, dict):
        current = {'plants': {}, 'simulator_running': True}
    if 'plants' not in current:
        current['plants'] = {}

    if 'plants' in data:
        for key, value in data['plants'].items():
            if key in current['plants'] and isinstance(current['plants'][key], dict) and isinstance(value, dict):
                current['plants'][key].update(value)
            else:
                current['plants'][key] = value
    else:
        for key, value in data.items():
            if key == 'simulator_running':
                current['simulator_running'] = value
            elif '|' in key:
                if key in current['plants'] and isinstance(current['plants'][key], dict):
                    if isinstance(value, bool):
                        current['plants'][key]['running'] = value
                    elif isinstance(value, dict):
                        current['plants'][key].update(value)
                else:
                    current['plants'][key] = {'running': bool(value)} if isinstance(value, bool) else value
            else:
                current[key] = value

    return current

#!/usr/bin/env python3
"""Simulation state merge/sync helpers used by the Flask dashboard."""


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

    for bu in cfg.get('tree', {}).get('children', []):
        if bu.get('type') != 'businessUnit':
            continue

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

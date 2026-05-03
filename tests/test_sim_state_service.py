from sim_state_service import merge_sim_state_update, sync_sim_state_with_uns


def test_merge_sim_state_update_preserves_recipe_when_starting_plant():
    current = {
        'plants': {
            'BU|Site': {'running': False, 'recipe': 'Recipe A', 'recipes': [{'name': 'Recipe A'}]}
        },
        'simulator_running': False,
    }

    merged = merge_sim_state_update(current, {'BU|Site': {'running': True}})

    assert merged['plants']['BU|Site']['running'] is True
    assert merged['plants']['BU|Site']['recipe'] == 'Recipe A'
    assert merged['plants']['BU|Site']['recipes'] == [{'name': 'Recipe A'}]


def test_merge_sim_state_update_supports_legacy_bool_values():
    merged = merge_sim_state_update({'plants': {}}, {'BU|Site': True})

    assert merged['plants']['BU|Site'] == {'running': True}


def test_sync_sim_state_with_uns_adds_updates_and_removes_plants():
    cfg = {
        'tree': {
            'children': [
                {
                    'type': 'businessUnit',
                    'name': 'BU',
                    'children': [
                        {'type': 'site', 'name': 'Site', 'recipes': [{'name': 'Recipe B'}]},
                    ],
                }
            ]
        }
    }
    sim_state = {
        'plants': {
            'BU|Site': {'running': True, 'recipe': 'Missing', 'recipes': []},
            'BU|OldSite': {'running': True},
        },
        'simulator_running': True,
    }

    synced = sync_sim_state_with_uns(cfg, sim_state)

    assert set(synced['plants']) == {'BU|Site'}
    assert synced['plants']['BU|Site']['running'] is True
    assert synced['plants']['BU|Site']['recipe'] == 'Recipe B'
    assert synced['plants']['BU|Site']['recipes'] == [{'name': 'Recipe B'}]

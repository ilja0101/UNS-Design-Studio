"""Live-UNS membership: prefix matcher, add/remove, carve-out, reset.

The tree here is a small synthetic UNS — nothing is hardcoded to any real model,
mirroring that the app treats uns_config.json as arbitrary user data.
"""
from uns_tree import path_covered, carve_out
from sim_state_service import get_live_config, set_live, reset_live

# enterprise E → BU B → sites S1 (areas A1[WC1], A2), S2
TREE = {
    'name': 'E', 'type': 'enterprise', 'children': [
        {'name': 'B', 'type': 'businessUnit', 'children': [
            {'name': 'S1', 'type': 'site', 'children': [
                {'name': 'A1', 'type': 'area', 'children': [
                    {'name': 'WC1', 'type': 'workCenter', 'children': []},
                ]},
                {'name': 'A2', 'type': 'area', 'children': []},
            ]},
            {'name': 'S2', 'type': 'site', 'children': []},
        ]},
    ],
}


def test_path_covered_prefix_semantics():
    assert path_covered('B|S1|A1', ['B|S1'])
    assert path_covered('B|S1', ['B|S1'])
    assert not path_covered('B|S2', ['B|S1'])
    assert not path_covered('B|S10', ['B|S1'])   # not fooled by shared prefix chars


def test_default_is_all_live():
    assert get_live_config({})['mode'] == 'all'
    assert get_live_config({'plants': {}})['mode'] == 'all'


def test_reset_none_then_add_branch():
    st = {}
    reset_live(st, 'none')
    assert get_live_config(st) == {'mode': 'explicit', 'paths': []}
    set_live(st, TREE, 'B|S1', True)
    assert get_live_config(st)['paths'] == ['B|S1']
    # adding a descendant is a no-op (already covered)
    set_live(st, TREE, 'B|S1|A1', True)
    assert get_live_config(st)['paths'] == ['B|S1']
    # adding the whole BU absorbs the redundant child prefix
    set_live(st, TREE, 'B', True)
    assert get_live_config(st)['paths'] == ['B']


def test_remove_exact_prefix():
    st = {'live_nodes': {'mode': 'explicit', 'paths': ['B|S1', 'B|S2']}}
    set_live(st, TREE, 'B|S1', False)
    assert get_live_config(st)['paths'] == ['B|S2']


def test_remove_carves_out_of_broader_branch():
    # paths are enterprise-rooted, matching build_bridge_entries node_path
    st = {'live_nodes': {'mode': 'explicit', 'paths': ['E|B']}}
    # remove one area of S1 — B, S2, and S1's other area must stay live
    set_live(st, TREE, 'E|B|S1|A1', False)
    paths = set(get_live_config(st)['paths'])
    assert paths == {'E|B|S2', 'E|B|S1|A2'}
    assert path_covered('E|B|S2', paths)
    assert path_covered('E|B|S1|A2', paths)
    assert not path_covered('E|B|S1|A1', paths)
    assert not path_covered('E|B|S1|A1|WC1', paths)


def test_remove_from_all_mode_converts_to_explicit_carve():
    st = {}                       # all-live
    set_live(st, TREE, 'E|B|S1', False)
    paths = set(get_live_config(st)['paths'])
    assert paths == {'E|B|S2'}    # only S1 removed; S2 stays
    assert not path_covered('E|B|S1|A1', paths)


def test_carve_out_removing_ancestor_itself_is_empty():
    assert carve_out(TREE, 'E|B', 'E|B') == []


def test_carve_out_stale_path_stops_gracefully():
    # removing a node that doesn't exist under the ancestor keeps siblings sane
    out = carve_out(TREE, 'E|B', 'E|B|S1|Ghost')
    assert 'E|B|S2' in out          # S2 preserved; walk stops at the missing child

"""Tests for _viz_resolve_tag_path — UNS path → OPC path translation."""


def test_resolve_simple_tag(app_module):
    # default tag (no opcPath, no opcNodeName)
    parts = app_module._viz_resolve_tag_path(
        'Acme|NA|plant-01|mixing|tank-01|pump-01', 'flow_rate')
    # 'Factory' prefix on site nodes
    assert parts == ['NA', 'Factoryplant-01', 'mixing', 'tank-01', 'pump-01', 'flow_rate']


def test_resolve_bool_tag(app_module):
    parts = app_module._viz_resolve_tag_path(
        'Acme|NA|plant-01|mixing|tank-01|pump-01', 'running')
    assert parts[-1] == 'running'


def test_resolve_with_opc_path_uses_area_root(app_module):
    # 'pressure' has opcPath='mixing/pump-01/p' → area-relative override
    parts = app_module._viz_resolve_tag_path(
        'Acme|NA|plant-01|mixing|tank-01|pump-01', 'pressure')
    # area_opc = ['NA', 'Factoryplant-01', 'mixing'] then split opcPath
    assert parts == ['NA', 'Factoryplant-01', 'mixing', 'mixing', 'pump-01', 'p']


def test_resolve_unknown_entity(app_module):
    assert app_module._viz_resolve_tag_path('Acme|nope', 'flow_rate') == []


def test_resolve_unknown_tag(app_module):
    assert app_module._viz_resolve_tag_path(
        'Acme|NA|plant-01|mixing|tank-01|pump-01', 'does_not_exist') == []


def test_resolve_wrong_root(app_module):
    assert app_module._viz_resolve_tag_path('Other|NA|plant-01', 'x') == []


def test_resolve_empty_inputs(app_module):
    assert app_module._viz_resolve_tag_path('', 'x') == []
    assert app_module._viz_resolve_tag_path(None, 'x') == []


def test_resolve_with_opc_node_name_override(app_module, write_uns):
    write_uns({
        'name': 'Acme', 'type': 'enterprise',
        'children': [{
            'name': 'plant-x', 'type': 'site',
            'children': [{
                'name': 'a1', 'type': 'area',
                'children': [{
                    'name': 'wu', 'type': 'workUnit',
                    'tags': [{'name': 'temp', 'dataType': 'Float',
                              'opcNodeName': 'TempReading'}],
                }],
            }],
        }],
    })
    parts = app_module._viz_resolve_tag_path('Acme|plant-x|a1|wu', 'temp')
    # site gets Factory prefix; opcNodeName replaces tag name as leaf
    assert parts == ['Factoryplant-x', 'a1', 'wu', 'TempReading']

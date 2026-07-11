from uns_tree import build_bridge_entries, enterprise_structure, sanitize_topic_part


def test_enterprise_structure_uses_bare_site_names():
    cfg = {
        'tree': {
            'children': [
                {
                    'type': 'businessUnit',
                    'name': 'BU',
                    'children': [{'type': 'site', 'name': 'Amsterdam'}],
                }
            ]
        }
    }

    assert enterprise_structure(cfg, {}) == {'BU': ['Amsterdam']}


def test_sanitize_topic_part_replaces_mqtt_wildcards_and_spaces():
    assert sanitize_topic_part('Line 1 + Temp#') == 'Line_1___Temp_'


def test_build_bridge_entries_uses_factory_site_opc_name_and_opc_path_relative_to_area():
    tree = {
        'type': 'enterprise',
        'name': 'Enterprise',
        'children': [
            {
                'type': 'businessUnit',
                'name': 'BU',
                'children': [
                    {
                        'type': 'site',
                        'name': 'Site',
                        'children': [
                            {
                                'type': 'area',
                                'name': 'Area',
                                'tags': [
                                    {'name': 'Local Temp', 'opcNodeName': 'Temperature', 'unit': 'C'},
                                    {'name': 'Remote Flow', 'opcPath': 'Line 1/Flow', 'payloadSchema': 'sparkplug'},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    entries = build_bridge_entries(tree, '/', 'prefix')

    assert entries[0] == (
        'prefix/Enterprise/BU/Site/Area/Local_Temp',
        ['Enterprise', 'BU', 'FactorySite', 'Area', 'Temperature'],
        'C',
        'standard',
        'Float',
        'Local Temp',
        'Enterprise|BU|Site|Area',
    )
    assert entries[1][0] == 'prefix/Enterprise/BU/Site/Area/Remote_Flow'
    assert entries[1][1] == ['Enterprise', 'BU', 'FactorySite', 'Area', 'Line 1', 'Flow']
    assert entries[1][3] == 'sparkplug'

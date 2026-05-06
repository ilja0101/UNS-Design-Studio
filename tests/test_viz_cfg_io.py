"""Tests for _load_viz_cfg / _save_viz_cfg I/O helpers."""
import json
import os


def test_load_missing_returns_default(app_module):
    # tmp viz path doesn't exist on first call
    cfg = app_module._load_viz_cfg()
    assert cfg == {'version': 1, 'entities': {}, 'links': [], 'gauges': [], 'animations': []}


def test_save_roundtrip(app_module):
    payload = {
        'version': 1,
        'entities': {'Acme|NA|plant-01': {'kind': 'tank'}},
        'links': [{'from': 'a', 'to': 'b', 'kind': 'pipe'}],
        'gauges': [{'id': 'g1', 'entity': 'e', 'tag': 't', 'widget': 'numeric',
                    'min': 0, 'max': 100, 'unit': 'C'}],
        'animations': [],
    }
    app_module._save_viz_cfg(payload)
    assert os.path.exists(app_module.VIZ_CONFIG_FILE)
    with open(app_module.VIZ_CONFIG_FILE, encoding='utf-8') as f:
        on_disk = json.load(f)
    assert on_disk == payload


def test_load_malformed_returns_default(app_module):
    with open(app_module.VIZ_CONFIG_FILE, 'w', encoding='utf-8') as f:
        f.write('{ this is broken json')
    cfg = app_module._load_viz_cfg()
    assert cfg.get('gauges') == []
    assert cfg.get('version') == 1


def test_save_pretty_printed(app_module):
    app_module._save_viz_cfg({'version': 1, 'gauges': [{'id': 'x'}]})
    text = open(app_module.VIZ_CONFIG_FILE, encoding='utf-8').read()
    # indent=2 produces newlines
    assert '\n' in text

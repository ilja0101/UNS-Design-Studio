"""Tests for _walk_viz_entities — surfaces only mappable nodes."""


def test_walks_default_tree(app_module):
    out = app_module._walk_viz_entities()
    ids = [e['id'] for e in out]
    # enterprise + BU are skipped, site/area/workCenter/workUnit kept
    assert 'Acme|NA|plant-01' in ids
    assert 'Acme|NA|plant-01|mixing' in ids
    assert 'Acme|NA|plant-01|mixing|tank-01' in ids
    assert 'Acme|NA|plant-01|mixing|tank-01|pump-01' in ids
    # enterprise root and BU not surfaced
    assert 'Acme' not in ids
    assert 'Acme|NA' not in ids


def test_includes_tag_names(app_module):
    out = app_module._walk_viz_entities()
    pump = next(e for e in out if e['name'] == 'pump-01')
    assert pump['tags'] == ['flow_rate', 'running', 'pressure']
    assert pump['type'] == 'workUnit'
    assert pump['parentPath'] == 'Acme|NA|plant-01|mixing|tank-01'


def test_missing_uns_file_returns_empty(app_module, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, 'UNS_CONFIG_FILE', str(tmp_path / 'nope.json'))
    assert app_module._walk_viz_entities() == []


def test_malformed_uns_file_returns_empty(app_module, tmp_path, monkeypatch):
    bad = tmp_path / 'bad.json'
    bad.write_text('{ this is not json', encoding='utf-8')
    monkeypatch.setattr(app_module, 'UNS_CONFIG_FILE', str(bad))
    assert app_module._walk_viz_entities() == []


def test_empty_tree(app_module, write_uns):
    write_uns({'name': 'Empty', 'type': 'enterprise', 'children': []})
    assert app_module._walk_viz_entities() == []

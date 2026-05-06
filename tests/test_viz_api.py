"""Tests for /api/viz/* HTTP endpoints via Flask test client."""


def test_get_config_when_missing_returns_default(flask_client):
    r = flask_client.get('/api/viz/config')
    assert r.status_code == 200
    body = r.get_json()
    assert body['version'] == 1
    assert body['entities'] == {}
    assert body['gauges'] == []


def test_post_config_persists_and_stamps_lastmodified(flask_client, app_module):
    payload = {'entities': {'x': {'kind': 'tank'}}, 'gauges': []}
    r = flask_client.post('/api/viz/config', json=payload)
    assert r.status_code == 200
    assert r.get_json()['ok'] is True

    r2 = flask_client.get('/api/viz/config')
    saved = r2.get_json()
    assert saved['entities']['x']['kind'] == 'tank'
    assert 'lastModified' in saved
    assert saved['version'] == 1   # default injected


def test_post_config_empty_body(flask_client):
    r = flask_client.post('/api/viz/config', json={})
    assert r.status_code == 200
    assert r.get_json()['ok'] is True


def test_get_entities_lists_mappable(flask_client):
    r = flask_client.get('/api/viz/entities')
    assert r.status_code == 200
    body = r.get_json()
    assert 'kinds' in body and 'entities' in body
    ids = [e['id'] for e in body['entities']]
    assert 'Acme|NA|plant-01' in ids
    assert 'Acme|NA|plant-01|mixing|tank-01|pump-01' in ids


def test_get_entities_includes_suggestion(flask_client):
    body = flask_client.get('/api/viz/entities').get_json()
    pump = next(e for e in body['entities'] if e['name'] == 'pump-01')
    assert pump['suggestion'] == 'pump'
    # not yet mapped
    assert pump['mapped'] is False
    assert pump['kind'] == 'pump'   # falls back to suggestion


def test_get_entities_reflects_saved_mapping(flask_client, write_viz):
    write_viz({
        'version': 1,
        'entities': {'Acme|NA|plant-01|mixing|tank-01|pump-01': {'kind': 'motor'}},
        'gauges': [], 'links': [], 'animations': [],
    })
    body = flask_client.get('/api/viz/entities').get_json()
    pump = next(e for e in body['entities'] if e['name'] == 'pump-01')
    assert pump['mapped'] is True
    assert pump['kind'] == 'motor'


def test_get_tags_for_entity(flask_client):
    r = flask_client.get('/api/viz/tags/Acme%7CNA%7Cplant-01%7Cmixing%7Ctank-01%7Cpump-01')
    assert r.status_code == 200
    body = r.get_json()
    names = [t['name'] for t in body['tags']]
    assert names == ['flow_rate', 'running', 'pressure']


def test_values_endpoint_when_no_opc(flask_client, app_module):
    # poll thread never connected — opc_connected starts False
    app_module._state['viz_values'] = {}
    app_module._state['opc_connected'] = False
    body = flask_client.get('/api/viz/values').get_json()
    assert body['values'] == {}
    assert body['opc_ready'] is False
    assert 'ts' in body


def test_values_endpoint_with_cached_values(flask_client, app_module):
    app_module._state['viz_values'] = {'g1': 42.0, 'g2': True}
    app_module._state['opc_connected'] = True
    body = flask_client.get('/api/viz/values').get_json()
    assert body['values']['g1'] == 42.0
    assert body['values']['g2'] is True
    assert body['opc_ready'] is True

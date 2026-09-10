"""Trends: a watch-list ring buffer fed by the poll loop, read as a chart-ready series."""
import time

import pytest

import trend_service
from trend_service import TrendStore, key_for
from uds_agent import tools as tools_mod

from tests.test_agent_tools import FakeBackend


def test_keys_are_root_optional_and_slash_normalised():
    assert key_for('acme/ams-01/mixing', 'flow') == 'acme/ams-01/mixing:flow'
    assert key_for('acme\\ams-01\\mixing/', ' flow ') == 'acme/ams-01/mixing:flow'


def test_watch_record_read_round_trip():
    s = TrendStore(maxlen=10)
    s.add('ams-01/mixing/m1', 'flow_rate', ['Factoryams-01', 'mixing', 'm1', 'flow_rate'], unit='m3/h')
    t0 = time.time() - 30
    for i in range(12):                      # more than maxlen: the oldest fall off
        s.record('ams-01/mixing/m1:flow_rate', 10 + i, t0 + i * 3)
    out = s.read('ams-01/mixing/m1', 'flow_rate', seconds=300)
    assert out['samples'] == 10 and out['returned'] == 10
    assert out['stats'] == {'min': 12.0, 'max': 21.0, 'mean': 16.5, 'last': 21.0}
    assert out['unit'] == 'm3/h'
    chart = out['chart']
    assert chart['type'] == 'line' and chart['x'] == {'kind': 'time'}
    assert chart['series'][0]['data'][-1][1] == 21.0
    assert chart['series'][0]['data'][0][0].endswith('Z')


def test_a_window_and_a_point_budget_thin_the_series():
    s = TrendStore()
    s.add('a', 't', ['a', 't'])
    now = time.time()
    for i in range(300):
        s.record('a:t', float(i), now - 300 + i)
    out = s.read('a', 't', seconds=100, points=10)
    assert 99 <= out['samples'] <= 101
    assert out['returned'] == 10
    assert out['from'] is not None


def test_non_numeric_values_are_reported_not_charted():
    s = TrendStore()
    s.add('a', 'state', ['a', 'state'])
    s.record('a:state', 'RUNNING')
    out = s.read('a', 'state')
    assert 'stats' not in out and out['note'].startswith('values are not numeric')
    assert out['last_values'][0]['value'] == 'RUNNING'
    assert out['chart']['series'][0]['data'] == []


def test_the_watch_list_is_bounded_and_unwatch_drops_history():
    s = TrendStore(max_watch=2)
    s.add('a', 'x', ['a', 'x'])
    s.add('a', 'y', ['a', 'y'])
    with pytest.raises(ValueError, match='watch list holds 2'):
        s.add('a', 'z', ['a', 'z'])
    s.add('a', 'x', ['a', 'x'], unit='%')        # re-adding is an update, not a slot
    assert s.watched()[0]['unit'] == '%'
    assert s.remove('a', 'y') and not s.remove('a', 'y')
    with pytest.raises(KeyError):
        s.read('a', 'y')


def test_a_watched_tag_with_no_samples_reads_empty_not_broken():
    s = TrendStore()
    s.add('a', 'x', ['a', 'x'])
    out = s.read('a', 'x')
    assert out['samples'] == 0 and out['from'] is None and 'stats' not in out


# ── the routes, against the real app with a seeded tree ─────────────────────

@pytest.fixture
def client(app_module, tmp_path, monkeypatch):
    import json
    tree = {'name': 'acme', 'type': 'enterprise', 'children': [
        {'name': 'ams-01', 'type': 'site', 'children': [
            {'name': 'mixing', 'type': 'area', 'children': [
                {'name': 'm1', 'type': 'workUnit', 'tags': [
                    {'name': 'flow_rate', 'unit': 'm3/h', 'dataType': 'Double'}]}]}]}]}
    cfg = tmp_path / 'uns_config.json'
    cfg.write_text(json.dumps({'tree': tree}), encoding='utf-8')
    monkeypatch.setattr(app_module, 'UNS_CONFIG_FILE', str(cfg))
    monkeypatch.setitem(app_module._state, 'trends', trend_service.TrendStore())
    app_module.app.testing = True
    return app_module.app.test_client()


async def test_watch_resolves_the_opc_path_like_the_gauges_do(client, app_module):
    r = await client.post('/api/trends/watch', json={'tags': [
        {'path': 'acme/ams-01/mixing/m1', 'tag': 'flow_rate'},
        {'path': 'ams-01/mixing/nope', 'tag': 'x'}]})
    data = await r.get_json()
    assert r.status_code == 200
    assert data['watched'][0]['path'] == 'ams-01/mixing/m1' and data['watched'][0]['unit'] == 'm3/h'
    assert "no node 'nope'" in data['errors'][0]
    # the poll loop reads exactly this browse path (site nodes carry the Factory prefix)
    assert app_module._state['trends'].targets() == [
        ('ams-01/mixing/m1:flow_rate', ['Factoryams-01', 'mixing', 'm1', 'flow_rate'])]


async def test_read_needs_a_watch_first_then_serves_the_series(client, app_module):
    r = await client.get('/api/trends/read?path=ams-01/mixing/m1&tag=flow_rate')
    assert r.status_code == 404
    await client.post('/api/trends/watch', json={'tags': [{'path': 'ams-01/mixing/m1', 'tag': 'flow_rate'}]})
    app_module._state['trends'].record('ams-01/mixing/m1:flow_rate', 4.2)
    data = await (await client.get('/api/trends/read?path=acme/ams-01/mixing/m1&tag=flow_rate&seconds=60')).get_json()
    assert data['samples'] == 1 and data['stats']['last'] == 4.2
    assert data['chart']['series'][0]['name'] == 'flow_rate'
    listing = await (await client.get('/api/trends')).get_json()
    assert listing['watched'][0]['samples'] == 1


# ── the tools ────────────────────────────────────────────────────────────────

async def test_trend_tools_go_through_the_backend():
    seen = []

    class Backend(FakeBackend):
        async def call(self, method, path, body=None, params=None):
            seen.append((method, path, body, params))
            return {'ok': True, 'watched': [], 'errors': []}

    await tools_mod.call(Backend(), 'trend_watch', {'tags': [{'path': 'a', 'tag': 't'}]})
    await tools_mod.call(Backend(), 'trend_watch', {'action': 'remove', 'tags': [{'path': 'a', 'tag': 't'}]})
    await tools_mod.call(Backend(), 'trend_watch', {'action': 'list'})
    await tools_mod.call(Backend(), 'trend_read', {'path': 'a', 'tag': 't', 'seconds': 60})
    assert [s[:2] for s in seen] == [('POST', '/api/trends/watch'), ('DELETE', '/api/trends/watch'),
                                     ('GET', '/api/trends'), ('GET', '/api/trends/read')]
    assert seen[3][3] == {'path': 'a', 'tag': 't', 'seconds': 60.0, 'points': 120}
    with pytest.raises(tools_mod.ToolError):
        await tools_mod.call(Backend(), 'trend_watch', {})
    # read-only: available on a read-scoped MCP connection
    names = {t.name for t in tools_mod.registry(include_writes=False)}
    assert {'trend_watch', 'trend_read'} <= names

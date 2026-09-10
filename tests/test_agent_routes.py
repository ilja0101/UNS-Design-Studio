"""The /api/agent surface: settings hygiene, policy, snapshots, and the SSE stream."""
import json

import pytest

from uds_agent import loop as agent_loop
from uds_agent import policy as policy_mod
from uds_agent import settings as agent_settings
from uds_agent import store
from uds_agent import tools as tools_mod


@pytest.fixture
def client(app_module, tmp_path, monkeypatch):
    monkeypatch.setattr(agent_settings, 'settings_file', lambda: str(tmp_path / 'agent.json'))
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'topic_policy.json'))
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: _mk(tmp_path / 'snaps'))
    monkeypatch.setattr(store, 'conversations_dir', lambda: _mk(tmp_path / 'convos'))
    app_module.app.testing = True
    return app_module.app.test_client()


def _mk(p):
    p.mkdir(exist_ok=True)
    return str(p)


async def body(response):
    return await response.get_json()


# ── settings ────────────────────────────────────────────────────────────────

async def test_the_api_key_is_never_returned_to_the_browser(client):
    await client.post('/api/agent/settings', json={'endpoint': 'http://x/v1',
                                                   'apiKey': 'super-secret', 'model': 'm'})
    data = await body(await client.get('/api/agent/settings'))
    assert 'apiKey' not in data
    assert data['apiKeySet'] is True
    assert data['configured'] is True
    assert 'super-secret' not in json.dumps(data)


async def test_saving_without_a_key_keeps_the_stored_one(client):
    """The UI cannot send the key back, so absence must mean 'unchanged'."""
    await client.post('/api/agent/settings', json={'endpoint': 'http://x/v1',
                                                   'apiKey': 'k', 'model': 'm'})
    await client.post('/api/agent/settings', json={'model': 'other', 'apiKey': ''})
    data = await body(await client.get('/api/agent/settings'))
    assert data['apiKeySet'] is True
    assert data['model'] == 'other'


async def test_unknown_settings_keys_are_ignored(client):
    await client.post('/api/agent/settings', json={'sudo': True, 'model': 'm'})
    assert 'sudo' not in await body(await client.get('/api/agent/settings'))


async def test_an_mcp_token_is_minted_and_stays_stable(client):
    first = (await body(await client.get('/api/agent/settings')))['mcpToken']
    second = (await body(await client.get('/api/agent/settings')))['mcpToken']
    assert first and first == second


async def test_an_empty_token_on_save_rotates_it(client):
    before = (await body(await client.get('/api/agent/settings')))['mcpToken']
    after = (await body(await client.post('/api/agent/settings',
                                          json={'mcpToken': ''})))['mcpToken']
    assert after and after != before


async def test_the_tool_catalogue_is_exposed_for_the_ui(client):
    tools = (await body(await client.get('/api/agent/tools')))['tools']
    names = {t['name'] for t in tools}
    assert 'uns_overview' in names and 'uns_add_node' in names
    assert next(t for t in tools if t['name'] == 'uns_add_node')['writes'] is True
    assert next(t for t in tools if t['name'] == 'uns_overview')['writes'] is False


# ── policy ──────────────────────────────────────────────────────────────────

async def test_policy_round_trips_and_the_check_follows_it(client):
    await client.post('/api/agent/policy', json={
        'name': 'Acme v3', 'separator': '.', 'prefix': 'plant', 'caseRule': 'kebab',
        'levels': [{'type': 'enterprise', 'required': True}],
        'tag': {'caseRule': 'snake'},
    })
    saved = await body(await client.get('/api/agent/policy'))
    assert saved['name'] == 'Acme v3' and saved['separator'] == '.'

    report = await body(await client.get('/api/agent/policy/check?limit=5'))
    assert report['policy'] == 'Acme v3'
    assert report['separator'] == '.'
    assert len(report['violations']) <= 5


async def test_topics_preview_reflects_the_policy_and_filters(client):
    await client.post('/api/agent/policy', json={'separator': '/', 'prefix': 'uns'})
    everything = await body(await client.get('/api/agent/topics'))
    assert everything['total'] == 3
    assert everything['topics'][0]['topic'].startswith('uns/Acme/NA/plant-01/')

    filtered = await body(await client.get('/api/agent/topics?contains=running'))
    assert filtered['total'] == 1


# ── conversations ───────────────────────────────────────────────────────────

async def test_conversations_can_be_created_listed_read_and_deleted(client):
    created = await body(await client.post('/api/agent/conversations',
                                           json={'title': 'Model a dairy'}))
    cid = created['id']

    listed = (await body(await client.get('/api/agent/conversations')))['conversations']
    assert [c['id'] for c in listed] == [cid]
    assert listed[0]['title'] == 'Model a dairy'

    assert (await body(await client.get(f'/api/agent/conversations/{cid}')))['id'] == cid
    assert (await client.delete(f'/api/agent/conversations/{cid}')).status_code == 200
    assert (await client.get(f'/api/agent/conversations/{cid}')).status_code == 404


async def test_a_conversation_id_cannot_escape_its_directory(client):
    """The id lands in a filename, so path traversal must not resolve."""
    assert (await client.get('/api/agent/conversations/..%2F..%2Fapp')).status_code in (404, 308)


# ── snapshots ───────────────────────────────────────────────────────────────

async def test_snapshots_are_listed_and_can_be_restored(client, app_module):
    from uds_agent.backend import DirectBackend
    backend = DirectBackend(app_module.app)
    await tools_mod.call(backend, 'uns_add_node',
                         {'parent_path': 'Acme/NA', 'name': 'plant-02', 'type': 'site'})

    snapshots = (await body(await client.get('/api/agent/snapshots')))['snapshots']
    assert len(snapshots) == 1

    result = await body(await client.post(f"/api/agent/snapshots/{snapshots[0]['id']}/revert"))
    assert result['revertedTo'] == snapshots[0]['id']
    with open(app_module.UNS_CONFIG_FILE, encoding='utf-8') as f:
        assert [c['name'] for c in json.load(f)['tree']['children'][0]['children']] == ['plant-01']


async def test_reverting_an_unknown_snapshot_is_a_400(client):
    r = await client.post('/api/agent/snapshots/nope/revert')
    assert r.status_code == 400
    assert 'no snapshot' in (await body(r))['error']


# ── chat ────────────────────────────────────────────────────────────────────

async def test_an_empty_message_is_rejected(client):
    r = await client.post('/api/agent/chat', json={'message': '   '})
    assert r.status_code == 400


async def test_the_chat_stream_is_sse_and_frames_every_event(client, monkeypatch):
    async def fake_turn(backend, convo, text, **kw):
        yield {'type': 'tool_call', 'id': 'c1', 'name': 'uns_overview', 'args': {}}
        yield {'type': 'tool_result', 'id': 'c1', 'name': 'uns_overview', 'ok': True,
               'summary': '4 nodes', 'result': {'counts': {'nodes': 4}}}
        yield {'type': 'delta', 'text': 'Four nodes — ünïcode fine.'}
        yield {'type': 'done', 'stop': 'end_turn'}

    monkeypatch.setattr(agent_loop, 'run_turn', fake_turn)
    r = await client.post('/api/agent/chat', json={'message': 'how big?'})
    assert r.status_code == 200
    assert r.headers['Content-Type'].startswith('text/event-stream')
    assert r.headers['X-Accel-Buffering'] == 'no'

    raw = (await r.get_data()).decode('utf-8')
    events = [json.loads(f[len('data: '):]) for f in raw.split('\n\n') if f.startswith('data: ')]
    assert [e['type'] for e in events] == ['start', 'tool_call', 'tool_result', 'delta', 'done']
    assert events[0]['conversation']
    assert events[3]['text'].endswith('ünïcode fine.')


async def test_the_first_frame_names_the_conversation_it_created(client, monkeypatch):
    """The client adopts that id, so a follow-up lands in the same thread."""
    async def fake_turn(backend, convo, text, **kw):
        yield {'type': 'done', 'stop': 'end_turn'}

    monkeypatch.setattr(agent_loop, 'run_turn', fake_turn)
    r = await client.post('/api/agent/chat', json={'message': 'hi'})
    first = json.loads((await r.get_data()).decode('utf-8').split('\n\n')[0][len('data: '):])
    cid = first['conversation']
    assert (await client.get(f'/api/agent/conversations/{cid}')).status_code == 200


async def test_a_crash_mid_stream_reaches_the_client_as_an_error_event(client, monkeypatch):
    async def exploding(backend, convo, text, **kw):
        yield {'type': 'delta', 'text': 'starting'}
        raise RuntimeError('kaboom')

    monkeypatch.setattr(agent_loop, 'run_turn', exploding)
    r = await client.post('/api/agent/chat', json={'message': 'go'})
    raw = (await r.get_data()).decode('utf-8')
    events = [json.loads(f[len('data: '):]) for f in raw.split('\n\n') if f.startswith('data: ')]
    assert events[-1]['type'] == 'error'
    assert 'kaboom' in events[-1]['message']


# ── attachments ─────────────────────────────────────────────────────────────

@pytest.fixture
def attachments_dir(tmp_path, monkeypatch):
    from uds_agent import attachments as att
    monkeypatch.setattr(att, 'attachments_dir', lambda: _mk(tmp_path / 'att'))
    return tmp_path / 'att'


async def test_an_upload_comes_back_as_metadata_and_a_chat_may_reference_it(
        client, attachments_dir, monkeypatch):
    from io import BytesIO
    from quart.datastructures import FileStorage
    r = await client.post('/api/agent/attachments', files={
        'files': FileStorage(BytesIO(b'name,unit\nflow,m3/h\n'), filename='tags.csv',
                             content_type='text/csv')})
    assert r.status_code == 200
    meta = (await body(r))['attachments'][0]
    assert meta['kind'] == 'table' and meta['name'] == 'tags.csv'
    assert 'flow' not in json.dumps(meta)   # metadata, never content

    page = await body(await client.get(f'/api/agent/attachments/{meta["id"]}/read?offset=1'))
    assert page['rows'] == [['flow', 'm3/h']]

    got = {}

    async def fake_turn(backend, convo, text, attachments=None, **kw):
        got['attachments'] = attachments
        yield {'type': 'done', 'stop': 'end_turn'}

    monkeypatch.setattr(agent_loop, 'run_turn', fake_turn)
    r = await client.post('/api/agent/chat', json={'message': '', 'attachments': [meta['id']]})
    assert r.status_code == 200
    await r.get_data()
    assert got['attachments'] == [meta]


async def test_a_chat_naming_an_unknown_attachment_is_refused(client, attachments_dir):
    r = await client.post('/api/agent/chat', json={'message': 'x', 'attachments': ['att-nope']})
    assert r.status_code == 400
    assert 'att-nope' in (await body(r))['error']


async def test_an_upload_with_no_files_is_a_400(client, attachments_dir):
    r = await client.post('/api/agent/attachments', form={'x': 'y'})
    assert r.status_code == 400

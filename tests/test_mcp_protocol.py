"""MCP: the JSON-RPC contract, the bearer gate, and the in-process wiring.

The dispatcher tests use a fake backend; the HTTP tests drive the real Quart
app, which is what proves DirectBackend can re-enter the app's own routes
through the auth hook.
"""
import json

import pytest

from uds_agent import settings as agent_settings
from uds_mcp.protocol import PROTOCOL_VERSION, McpDispatcher

from tests.test_agent_tools import FakeBackend


@pytest.fixture
def dispatcher(tmp_path, monkeypatch):
    from uds_agent import policy as policy_mod
    from uds_agent import tools as tools_mod
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: str(tmp_path))
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'topic_policy.json'))
    return McpDispatcher(FakeBackend())


async def rpc(dispatcher, method, params=None, rid=1):
    return await dispatcher.handle(
        {'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})


async def call_tool(dispatcher, name, args=None):
    reply = await rpc(dispatcher, 'tools/call', {'name': name, 'arguments': args or {}})
    return reply['result']


# ── handshake ───────────────────────────────────────────────────────────────

async def test_initialize_advertises_tools_and_instructions(dispatcher):
    result = (await rpc(dispatcher, 'initialize', {'protocolVersion': PROTOCOL_VERSION}))['result']
    assert result['protocolVersion'] == PROTOCOL_VERSION
    assert result['capabilities']['tools'] == {'listChanged': False}
    assert result['serverInfo']['name'] == 'uns-design-studio'
    assert 'uns_overview' in result['instructions']


async def test_initialize_honours_an_older_protocol_revision(dispatcher):
    result = (await rpc(dispatcher, 'initialize', {'protocolVersion': '2024-11-05'}))['result']
    assert result['protocolVersion'] == '2024-11-05'


async def test_an_unknown_protocol_revision_falls_back_to_ours(dispatcher):
    result = (await rpc(dispatcher, 'initialize', {'protocolVersion': '1999-01-01'}))['result']
    assert result['protocolVersion'] == PROTOCOL_VERSION


async def test_a_notification_gets_no_reply(dispatcher):
    assert await dispatcher.handle(
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None


async def test_ping(dispatcher):
    assert (await rpc(dispatcher, 'ping'))['result'] == {}


async def test_optional_capabilities_answer_empty_rather_than_erroring(dispatcher):
    """Clients probe these even though we don't advertise them."""
    assert (await rpc(dispatcher, 'resources/list'))['result'] == {'resources': []}
    assert (await rpc(dispatcher, 'prompts/list'))['result'] == {'prompts': []}


# ── errors ──────────────────────────────────────────────────────────────────

async def test_an_unknown_method_is_a_jsonrpc_error(dispatcher):
    reply = await rpc(dispatcher, 'bogus/method')
    assert reply['error']['code'] == -32601


async def test_a_non_object_request_is_rejected(dispatcher):
    assert (await dispatcher.handle('not a request'))['error']['code'] == -32600


async def test_tools_call_without_a_name_is_invalid_params(dispatcher):
    assert (await rpc(dispatcher, 'tools/call', {}))['error']['code'] == -32602


async def test_non_object_arguments_are_invalid_params(dispatcher):
    reply = await rpc(dispatcher, 'tools/call', {'name': 'uns_overview', 'arguments': [1, 2]})
    assert reply['error']['code'] == -32602


async def test_a_tool_failure_is_a_successful_rpc_with_iserror(dispatcher):
    """The model must be able to read and retry, not see a transport fault."""
    result = await call_tool(dispatcher, 'uns_browse', {'path': 'nowhere'})
    assert result['isError'] is True
    assert 'nowhere' in result['content'][0]['text']
    assert 'jsonrpc' not in result


async def test_a_batch_returns_only_the_answerable_members(dispatcher):
    replies = await dispatcher.handle([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'},
    ])
    assert [r['id'] for r in replies] == [1, 2]


# ── tools ───────────────────────────────────────────────────────────────────

async def test_tools_list_shape_matches_the_mcp_schema(dispatcher):
    tools = (await rpc(dispatcher, 'tools/list'))['result']['tools']
    assert tools
    for t in tools:
        assert set(t) >= {'name', 'description', 'inputSchema'}
        assert t['inputSchema']['type'] == 'object'
    read_only = {t['name'] for t in tools if t['annotations']['readOnlyHint']}
    assert 'uns_browse' in read_only
    assert 'uns_add_node' not in read_only


async def test_a_result_carries_both_rendered_text_and_structured_content(dispatcher):
    result = await call_tool(dispatcher, 'uns_overview')
    assert result['isError'] is False
    assert result['structuredContent']['counts']['nodes'] == 4
    assert json.loads(result['content'][0]['text'])['counts']['nodes'] == 4


async def test_a_read_only_dispatcher_hides_and_refuses_writes(tmp_path, monkeypatch):
    from uds_agent import tools as tools_mod
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: str(tmp_path))
    d = McpDispatcher(FakeBackend(), allow_writes=False)

    listed = {t['name'] for t in (await rpc(d, 'tools/list'))['result']['tools']}
    assert 'uns_add_node' not in listed

    result = await call_tool(d, 'uns_add_node',
                             {'parent_path': 'acme', 'name': 'x', 'type': 'site'})
    assert result['isError'] is True
    assert 'read-only' in result['content'][0]['text']


async def test_a_tool_that_raises_unexpectedly_becomes_an_rpc_error_not_a_crash(dispatcher):
    class Exploding(FakeBackend):
        async def call(self, *a, **k):
            raise RuntimeError('boom')

    dispatcher.backend = Exploding()
    reply = await rpc(dispatcher, 'tools/call',
                      {'name': 'uns_overview', 'arguments': {}})
    assert reply['error']['code'] == -32603


# ── the in-process HTTP transport, against the real app ─────────────────────

@pytest.fixture
def mcp_client(app_module, tmp_path, monkeypatch):
    """The real app, with agent state redirected into a tmp dir."""
    monkeypatch.setattr(agent_settings, 'settings_file', lambda: str(tmp_path / 'agent.json'))
    from uds_agent import policy as policy_mod
    from uds_agent import tools as tools_mod
    from uds_mcp import http as mcp_http
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'topic_policy.json'))
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: str(tmp_path))
    monkeypatch.setattr(mcp_http, '_dispatcher', None)
    app_module.app.testing = True
    return app_module.app.test_client(), agent_settings.load()['mcpToken']


async def post_mcp(client, token, body):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    return await client.post('/mcp', json=body, headers=headers)


async def test_mcp_requires_a_bearer_token(mcp_client):
    client, _ = mcp_client
    r = await client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert r.status_code == 401
    assert 'Bearer' in r.headers.get('WWW-Authenticate', '')


async def test_mcp_rejects_a_wrong_token(mcp_client):
    client, _ = mcp_client
    r = await post_mcp(client, 'not-the-token', {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})
    assert r.status_code == 401


async def test_mcp_get_is_not_allowed(mcp_client):
    client, token = mcp_client
    r = await client.get('/mcp', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 405
    assert r.headers['Allow'] == 'POST'


async def test_a_notification_over_http_is_accepted_with_no_body(mcp_client):
    client, token = mcp_client
    r = await post_mcp(client, token, {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    assert r.status_code == 202
    assert await r.get_data() == b''


async def test_malformed_json_is_a_parse_error(mcp_client):
    client, token = mcp_client
    r = await client.post('/mcp', data='{not json',
                          headers={'Authorization': f'Bearer {token}',
                                   'Content-Type': 'application/json'})
    assert r.status_code == 400
    assert (await r.get_json())['error']['code'] == -32700


async def test_a_tool_call_over_http_reaches_the_real_uns_routes(mcp_client):
    """DirectBackend re-enters the app's own handlers — this is that path."""
    client, token = mcp_client
    r = await post_mcp(client, token, {
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'uns_overview', 'arguments': {}}})
    assert r.status_code == 200
    result = (await r.get_json())['result']
    assert result['isError'] is False
    assert result['structuredContent']['root']['name'] == 'Acme'


async def test_a_write_over_http_lands_in_the_real_config(mcp_client, app_module):
    client, token = mcp_client
    r = await post_mcp(client, token, {
        'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
        'params': {'name': 'uns_add_node',
                   'arguments': {'parent_path': 'Acme/NA', 'name': 'plant-02',
                                 'type': 'site'}}})
    assert (await r.get_json())['result']['isError'] is False
    with open(app_module.UNS_CONFIG_FILE, encoding='utf-8') as f:
        saved = json.load(f)
    sites = [c['name'] for c in saved['tree']['children'][0]['children']]
    assert sites == ['plant-01', 'plant-02']


async def test_mcp_info_is_open_and_leaks_no_token(mcp_client):
    client, token = mcp_client
    r = await client.get('/mcp/info')
    assert r.status_code == 200
    body = await r.get_json()
    assert body['enabled'] is True
    assert body['protocolVersion'] == PROTOCOL_VERSION
    assert token not in json.dumps(body)


async def test_mcp_can_be_switched_off(mcp_client):
    client, token = mcp_client
    agent_settings.save({'mcpEnabled': False})
    assert (await post_mcp(client, token,
                           {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})).status_code == 404
    assert (await client.get('/mcp/info')).status_code == 404


async def test_the_internal_loopback_token_satisfies_basic_auth(app_module, monkeypatch):
    """A tool call must still work when the dashboard is behind HTTP Basic."""
    from uds_agent.backend import DirectBackend
    monkeypatch.setattr(app_module, '_AUTH_USER', 'admin')
    monkeypatch.setattr(app_module, '_AUTH_PASS', 'secret')
    app_module.app.testing = True

    plain = await app_module.app.test_client().get('/api/uns')
    assert plain.status_code == 401

    result = await DirectBackend(app_module.app).call('GET', '/api/uns')
    assert result['tree']['name'] == 'Acme'

"""The mesh door: the contract as measured on the lab, pinned.

Every shape here is one that came back over the wire on 2026-09-10 -- the
refusal is the gateway's own sentence, byte for byte -- so a drift on either
side shows up here before it shows up as "the agent says nothing".
"""
import json

import pytest

from uds_agent import llm, loop, mesh, settings


# ── subject ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('app_id,token', [
    ('uns-design-studio', 'uns-design-studio'),
    ('UNS Design Studio', 'uns-design-studio'),   # pkg/modelgw.SubjectToken: lower, non-[a-z0-9-_] -> '-'
    ('connect~b4a6119a', 'connect-b4a6119a'),
    ('', 'uns-design-studio'),
])
def test_subject_token_matches_modelgw(app_id, token):
    assert mesh.subject_token(app_id) == token


def test_chat_subject_is_the_gateway_family():
    assert mesh.chat_subject('uns-design-studio') == 'iiot.svc.llmgw.chat.uns-design-studio'
    # Solace form, what the MQTT publish uses and what the driver subscribes.
    assert mesh.chat_subject('uns-design-studio').replace('.', '/') == \
        'iiot/svc/llmgw/chat/uns-design-studio'


# ── envelope ────────────────────────────────────────────────────────────────

def test_envelope_carries_the_openai_body_verbatim():
    body = llm.build_request(model='', system='s', messages=[{'role': 'user', 'content': 'hi'}],
                             tools=[llm.ToolDescriptor('uns_overview', 'd', {'type': 'object'})],
                             temperature=None, reasoning_effort=None, max_tokens=64)
    raw = json.loads(mesh.envelope(body, person='ilja', purpose='probe'))
    assert raw['person'] == 'ilja' and raw['purpose'] == 'probe'
    # The gateway forwards `body` to the provider as-is, so tools must be inside it.
    assert raw['body']['tools'][0]['function']['name'] == 'uns_overview'
    assert raw['body']['tool_choice'] == 'auto'


# ── unwrap: the two things the lab actually sent back ───────────────────────

REFUSAL = {'status': 403, 'body': {'error': {
    'message': 'Nobody has decided whether uns-design-studio may reach gpt-5.6-luna, and this '
               'gateway refuses an undecided pair on a provider whose data leaves the site. '
               'Allow it in the Model Gateway, under Applications.',
    'type': 'permission_denied'}}}


def test_a_refusal_becomes_a_gateway_error_carrying_its_own_sentence():
    with pytest.raises(llm.InferenceError) as exc:
        mesh.unwrap(json.dumps(REFUSAL))
    assert exc.value.kind == 'gateway'
    assert exc.value.status == 403
    assert exc.value.retryable is False
    assert 'Allow it in the Model Gateway, under Applications' in str(exc.value)


def test_an_answer_with_tool_calls_normalises_like_the_http_door():
    ok = {'status': 200, 'provider': 'gpt-5.6-luna', 'residency': 'off_site', 'body': {
        'choices': [{'finish_reason': 'tool_calls', 'message': {
            'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function',
                                           'function': {'name': 'uns_overview', 'arguments': '{}'}}]}}],
        'usage': {'prompt_tokens': 40, 'completion_tokens': 9}}}
    status, body = mesh.unwrap(json.dumps(ok))
    turn = llm.normalize_dict(body)
    assert status == 200
    assert turn.stop_reason == 'tool_use'
    assert [(c.name, c.input) for c in turn.tool_calls] == [('uns_overview', {})]
    assert turn.usage == llm.Usage(prompt_tokens=40, completion_tokens=9)


def test_a_5xx_is_retryable_and_a_non_json_reply_is_not_a_crash():
    with pytest.raises(llm.InferenceError) as exc:
        mesh.unwrap(json.dumps({'status': 502, 'body': {'error': 'provider down'}}))
    assert exc.value.retryable is True
    with pytest.raises(llm.InferenceError):
        mesh.unwrap(b'not json')


# ── settings: the door is chosen, and seeded from the bridge ────────────────

@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'settings_file', lambda: str(tmp_path / 'agent.json'))
    from uds_agent import paths
    monkeypatch.setattr(paths, 'data_dir', lambda: str(tmp_path))
    return tmp_path


def test_mesh_is_seeded_from_the_bridge_config(data_dir):
    (data_dir / 'bridge_config.json').write_text(json.dumps({
        'protocol': 'mqtt', 'broker_host': 'l3-edge-solace', 'broker_port': 1883,
        'username': 'uns', 'password': 'pw'}), encoding='utf-8')
    c = settings.load()
    assert (c['meshProtocol'], c['meshHost'], c['meshPort']) == ('mqtt', 'l3-edge-solace', 1883)
    assert (c['meshUsername'], c['meshPassword']) == ('uns', 'pw')
    # The password never reaches the browser; a flag does.
    view = settings.public_view(c)
    assert 'meshPassword' not in view and view['meshPasswordSet'] is True


def test_a_mesh_host_set_on_purpose_is_not_overwritten_by_the_bridge(data_dir):
    (data_dir / 'bridge_config.json').write_text(json.dumps({
        'protocol': 'nats', 'broker_host': 'l3-edge-nats', 'broker_port': 4222}), encoding='utf-8')
    settings.save({'meshHost': 'somewhere-else', 'meshProtocol': 'nats', 'meshPort': 4222})
    assert settings.load()['meshHost'] == 'somewhere-else'


def test_configured_means_the_chosen_door_not_both(data_dir):
    assert settings.is_configured({'route': 'mesh', 'meshHost': 'l3-edge-solace'})
    assert not settings.is_configured({'route': 'mesh', 'meshHost': ''})
    assert settings.is_configured({'route': 'direct', 'endpoint': 'e', 'apiKey': 'k', 'model': 'm'})
    assert not settings.is_configured({'route': 'direct', 'endpoint': 'e', 'apiKey': '', 'model': 'm'})


def test_make_adapter_picks_the_door():
    a = loop.make_adapter({'route': 'mesh', 'meshProtocol': 'mqtt', 'meshHost': 'h', 'meshPort': 1883,
                           'meshAppId': 'uns-design-studio'})
    assert isinstance(a, mesh.MeshAdapter) and a.protocol == 'mqtt'
    assert a._subject == 'iiot.svc.llmgw.chat.uns-design-studio'
    b = loop.make_adapter({'route': 'direct', 'endpoint': 'http://x/v1', 'apiKey': 'k', 'model': 'm'})
    assert isinstance(b, llm.LlmAdapter)


def test_a_gateway_refusal_is_explained_with_its_own_words():
    msg = loop._explain(llm.InferenceError('gateway', REFUSAL['body']['error']['message'], 403))
    assert msg.startswith('The Model Gateway refused')
    assert 'under Applications' in msg

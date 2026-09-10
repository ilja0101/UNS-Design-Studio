"""The chat turn: tool loop, event stream, persistence, and failure modes.

The LLM is a scripted stand-in — these tests are about what the loop does with
what a model says, not about any provider's wire format (that is
uds_agent/llm.py's own concern).
"""
import json

import pytest

from uds_agent import loop as agent_loop
from uds_agent import policy as policy_mod
from uds_agent import settings as agent_settings
from uds_agent import store
from uds_agent import tools as tools_mod
from uds_agent.llm import InferenceError, InferenceTurn, TextDelta, ToolCall, Usage

from tests.test_agent_tools import FakeBackend


class ScriptedAdapter:
    """Replays a list of turns; records the messages it was handed each time."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def __call__(self, *a, **k):
        return self

    async def stream_turn(self, *, system, messages, tools=None, **kw):
        self.seen.append({'system': system, 'messages': messages,
                          'tools': [t.name for t in tools or []]})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        for chunk in step.get('text_chunks', []):
            yield TextDelta(chunk)
        yield InferenceTurn(
            text=''.join(step.get('text_chunks', [])),
            tool_calls=step.get('tool_calls', []),
            stop_reason='tool_use' if step.get('tool_calls') else 'end_turn',
            usage=Usage(prompt_tokens=10, completion_tokens=5),
        )


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """A configured agent whose state lives in a tmp dir."""
    monkeypatch.setattr(agent_settings, 'settings_file', lambda: str(tmp_path / 'agent.json'))
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'topic_policy.json'))
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: str(tmp_path / 'snaps'))
    monkeypatch.setattr(store, 'conversations_dir', lambda: _mkdir(tmp_path / 'convos'))
    agent_settings.save({'endpoint': 'http://mock/v1', 'apiKey': 'k', 'model': 'm'})
    return FakeBackend()


def _mkdir(p):
    p.mkdir(exist_ok=True)
    return str(p)


def script(monkeypatch, steps):
    adapter = ScriptedAdapter(steps)
    monkeypatch.setattr(agent_loop, 'LlmAdapter', adapter)
    return adapter


async def collect(backend, convo, text):
    return [e async for e in agent_loop.run_turn(backend, convo, text)]


def kinds(events):
    return [e['type'] for e in events]


# ── the happy path ──────────────────────────────────────────────────────────

async def test_a_turn_with_no_tools_streams_text_then_done(agent, monkeypatch):
    script(monkeypatch, [{'text_chunks': ['Hello ', 'there']}])
    events = await collect(agent, store.create(), 'hi')
    assert kinds(events) == ['delta', 'delta', 'done']
    assert ''.join(e['text'] for e in events if e['type'] == 'delta') == 'Hello there'
    assert events[-1]['stop'] == 'end_turn'


async def test_a_tool_call_is_run_and_reported_before_the_answer(agent, monkeypatch):
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_overview', input={})]},
        {'text_chunks': ['4 nodes.']},
    ])
    events = await collect(agent, store.create(), 'how big is it?')
    assert kinds(events) == ['tool_call', 'tool_result', 'delta', 'done']
    assert events[0]['name'] == 'uns_overview'
    assert events[1]['ok'] is True
    assert events[1]['result']['counts']['nodes'] == 4


async def test_several_tools_in_one_assistant_turn_all_run(agent, monkeypatch):
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_overview', input={}),
                        ToolCall(id='c2', name='policy_get', input={})]},
        {'text_chunks': ['done']},
    ])
    events = await collect(agent, store.create(), 'go')
    assert kinds(events) == ['tool_call', 'tool_result', 'tool_call', 'tool_result',
                             'delta', 'done']


async def test_usage_and_steps_accumulate_across_the_turn(agent, monkeypatch):
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_overview', input={})]},
        {'text_chunks': ['ok']},
    ])
    done = (await collect(agent, store.create(), 'go'))[-1]
    assert done['usage'] == {'prompt': 20, 'completion': 10, 'steps': 2}


# ── recovery ────────────────────────────────────────────────────────────────

async def test_a_failing_tool_is_reported_and_the_turn_continues(agent, monkeypatch):
    """The model gets the error text back and is expected to correct itself."""
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_browse', input={'path': 'nowhere'})]},
        {'tool_calls': [ToolCall(id='c2', name='uns_browse', input={'path': 'acme'})]},
        {'text_chunks': ['found it']},
    ])
    events = await collect(agent, store.create(), 'browse')
    results = [e for e in events if e['type'] == 'tool_result']
    assert [r['ok'] for r in results] == [False, True]
    assert 'nl-veghel' in results[0]['summary']
    assert events[-1]['stop'] == 'end_turn'


async def test_unparseable_tool_arguments_come_back_as_a_tool_error(agent, monkeypatch):
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_browse',
                                 input_error='arguments are not valid JSON')]},
        {'text_chunks': ['sorry']},
    ])
    events = await collect(agent, store.create(), 'go')
    bad = next(e for e in events if e['type'] == 'tool_result')
    assert bad['ok'] is False
    assert 'not valid JSON' in bad['summary']


async def test_the_step_budget_stops_a_runaway_turn(agent, monkeypatch):
    agent_settings.save({'maxSteps': 3})
    script(monkeypatch, [{'tool_calls': [ToolCall(id=f'c{i}', name='uns_overview', input={})]}
                         for i in range(3)])
    done = (await collect(agent, store.create(), 'loop forever'))[-1]
    assert done['stop'] == 'max_steps'
    assert done['usage']['steps'] == 3
    assert 'Ask me to continue' in done['message']


async def test_an_endpoint_failure_becomes_a_readable_error_event(agent, monkeypatch):
    script(monkeypatch, [InferenceError('connection', 'cannot reach the LLM endpoint',
                                        retryable=True)])
    events = await collect(agent, store.create(), 'hi')
    assert kinds(events) == ['error']
    assert events[0]['retryable'] is True
    assert 'Settings' in events[0]['message']


async def test_an_unconfigured_agent_says_so_instead_of_calling_out(agent, monkeypatch, tmp_path):
    monkeypatch.setattr(agent_settings, 'settings_file', lambda: str(tmp_path / 'empty.json'))
    events = await collect(agent, store.create(), 'hi')
    assert kinds(events) == ['error']
    assert 'MCP' in events[0]['message']


async def test_a_bad_key_is_explained_rather_than_echoed(agent, monkeypatch):
    script(monkeypatch, [InferenceError('api_status', 'Unauthorized', 401)])
    events = await collect(agent, store.create(), 'hi')
    assert 'API key' in events[0]['message']


# ── writes and permissions ──────────────────────────────────────────────────

async def test_write_tools_are_withheld_when_writes_are_disabled(agent, monkeypatch):
    agent_settings.save({'allowWrites': False})
    adapter = script(monkeypatch, [{'text_chunks': ['ok']}])
    await collect(agent, store.create(), 'hi')
    offered = adapter.seen[0]['tools']
    assert 'uns_browse' in offered
    assert 'uns_add_node' not in offered


async def test_an_edit_takes_a_snapshot(agent, monkeypatch):
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_add_node',
                                 input={'parent_path': 'acme', 'name': 'de-koln',
                                        'type': 'site'})]},
        {'text_chunks': ['added']},
    ])
    await collect(agent, store.create(), 'add a site')
    assert len(tools_mod.list_snapshots()) == 1
    assert agent.saves == 1


# ── prompt assembly ─────────────────────────────────────────────────────────

async def test_the_live_policy_is_injected_into_the_system_prompt(agent, monkeypatch):
    policy_mod.save_policy({'name': 'Acme v3', 'separator': '.', 'prefix': 'plant',
                            'notes': 'No vendor names in topics.'})
    adapter = script(monkeypatch, [{'text_chunks': ['ok']}])
    await collect(agent, store.create(), 'hi')
    system = adapter.seen[0]['system']
    assert 'Acme v3' in system
    assert 'No vendor names in topics.' in system
    assert 'separator "."' in system


async def test_operator_instructions_are_appended(agent, monkeypatch):
    agent_settings.save({'systemPromptExtra': 'Never start the simulation.'})
    adapter = script(monkeypatch, [{'text_chunks': ['ok']}])
    await collect(agent, store.create(), 'hi')
    assert 'Never start the simulation.' in adapter.seen[0]['system']


# ── persistence ─────────────────────────────────────────────────────────────

async def test_the_whole_turn_is_persisted_in_replayable_shape(agent, monkeypatch):
    script(monkeypatch, [
        {'tool_calls': [ToolCall(id='c1', name='uns_overview', input={})]},
        {'text_chunks': ['4 nodes.']},
    ])
    convo = store.create()
    await collect(agent, convo, 'how big?')

    saved = store.load(convo['id'])
    assert [m['role'] for m in saved['messages']] == ['user', 'assistant', 'tool', 'assistant']
    assert saved['messages'][1]['tool_calls'][0]['function']['name'] == 'uns_overview'
    assert saved['messages'][2]['tool_call_id'] == 'c1'
    assert saved['messages'][2]['summary']
    # And it replays back into the model without the UI-only fields.
    replay = store.for_model(saved)
    assert all('summary' not in m and 'ok' not in m for m in replay)
    json.dumps(replay)


async def test_the_title_comes_from_the_first_message(agent, monkeypatch):
    script(monkeypatch, [{'text_chunks': ['ok']}])
    convo = store.create()
    await collect(agent, convo, 'Model a dairy site in Veghel')
    assert store.load(convo['id'])['title'] == 'Model a dairy site in Veghel'


async def test_history_is_carried_into_the_next_turn(agent, monkeypatch):
    adapter = script(monkeypatch, [{'text_chunks': ['one']}, {'text_chunks': ['two']}])
    convo = store.create()
    await collect(agent, convo, 'first')
    await collect(agent, convo, 'second')
    roles = [m['role'] for m in adapter.seen[1]['messages']]
    assert roles == ['user', 'assistant', 'user']


async def test_a_long_tool_result_is_truncated_before_the_model_sees_it(agent, monkeypatch):
    rendered = agent_loop._render({'blob': 'x' * 40000})
    assert len(rendered) < 21000
    assert rendered.endswith('narrow the query and call again)')

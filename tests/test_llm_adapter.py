"""The OpenAI-compatible wire layer.

These paths only fire against particular deployments — a Foundry model that
rejects `max_completion_tokens`, one that refuses `stream`, a truncated tool
call — which is exactly why they need tests rather than a live endpoint.
"""
import json
from types import SimpleNamespace

import pytest

from uds_agent import llm


def frag(index, *, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index, id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def chunk(*, content=None, tool_calls=None, finish=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choices = [] if usage and content is None and tool_calls is None and finish is None else [
        SimpleNamespace(index=0, delta=delta, finish_reason=finish)
    ]
    return SimpleNamespace(choices=choices, usage=usage)


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c
        return gen()


async def consume(adapter, chunks):
    return [item async for item in adapter._consume(FakeStream(chunks))]


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(llm, 'DEFAULT_MAX_TOKENS', 100)
    a = object.__new__(llm.LlmAdapter)   # no network client needed for _consume
    a.model = 'm'
    a._max_tokens = 100
    return a


# ── streaming ───────────────────────────────────────────────────────────────

async def test_text_streams_as_deltas_then_one_turn(adapter):
    items = await consume(adapter, [
        chunk(content='Hel'), chunk(content='lo'), chunk(finish='stop'),
    ])
    assert [i.text for i in items[:-1]] == ['Hel', 'lo']
    assert isinstance(items[-1], llm.InferenceTurn)
    assert items[-1].text == 'Hello'
    assert items[-1].stop_reason == 'end_turn'


async def test_tool_call_fragments_merge_by_index(adapter):
    """id and name arrive first; arguments arrive in pieces across chunks."""
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='call_1', name='uns_browse', arguments='')]),
        chunk(tool_calls=[frag(0, arguments='{"path":')]),
        chunk(tool_calls=[frag(0, arguments='"acme"}')]),
        chunk(finish='tool_calls'),
    ])
    turn = items[-1]
    assert turn.stop_reason == 'tool_use'
    assert len(turn.tool_calls) == 1
    call = turn.tool_calls[0]
    assert (call.id, call.name, call.input) == ('call_1', 'uns_browse', {'path': 'acme'})


async def test_parallel_tool_calls_stay_separate_and_ordered(adapter):
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='a', name='uns_overview', arguments='{}'),
                          frag(1, id='b', name='policy_get', arguments='{}')]),
        chunk(finish='tool_calls'),
    ])
    assert [c.name for c in items[-1].tool_calls] == ['uns_overview', 'policy_get']


async def test_a_name_split_across_fragments_is_concatenated(adapter):
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='a', name='uns_', arguments='')]),
        chunk(tool_calls=[frag(0, name='browse', arguments='{}')]),
        chunk(finish='tool_calls'),
    ])
    assert items[-1].tool_calls[0].name == 'uns_browse'


async def test_malformed_arguments_become_an_input_error_not_an_exception(adapter):
    """A truncated tool call must reach the loop as something it can answer."""
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='a', name='uns_browse', arguments='{"path": "acm')]),
        chunk(finish='tool_calls'),
    ])
    call = items[-1].tool_calls[0]
    assert call.input_error and 'not valid JSON' in call.input_error
    assert call.input == {}


async def test_non_object_arguments_are_an_input_error(adapter):
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='a', name='uns_browse', arguments='[1,2]')]),
        chunk(finish='tool_calls'),
    ])
    assert items[-1].tool_calls[0].input_error == 'arguments JSON must be an object'


async def test_a_fragment_with_no_name_is_dropped(adapter):
    """Some deployments emit an empty trailing slot; it is not a call."""
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='a', name='uns_overview', arguments='{}'),
                          frag(1, id='b', arguments='')]),
        chunk(finish='tool_calls'),
    ])
    assert len(items[-1].tool_calls) == 1


async def test_usage_arrives_on_its_own_choiceless_chunk(adapter):
    items = await consume(adapter, [
        chunk(content='hi'), chunk(finish='stop'),
        chunk(usage=SimpleNamespace(prompt_tokens=42, completion_tokens=7)),
    ])
    assert items[-1].usage == llm.Usage(prompt_tokens=42, completion_tokens=7)


# ── finish-reason normalisation ─────────────────────────────────────────────

@pytest.mark.parametrize('finish,expected', [
    ('stop', 'end_turn'),
    ('tool_calls', 'tool_use'),
    ('length', 'max_tokens'),
    ('function_call', 'tool_use'),
])
async def test_finish_reasons_map_to_our_vocabulary(adapter, finish, expected):
    items = await consume(adapter, [chunk(content='x'), chunk(finish=finish)])
    assert items[-1].stop_reason == expected


async def test_a_content_filter_is_a_refusal_with_an_explanation(adapter):
    """Never a crash — the user gets told to rephrase."""
    items = await consume(adapter, [chunk(finish='content_filter')])
    assert items[-1].stop_reason == 'refusal'
    assert 'content filter' in items[-1].text


async def test_a_missing_finish_reason_is_inferred_from_the_tool_calls(adapter):
    items = await consume(adapter, [
        chunk(tool_calls=[frag(0, id='a', name='uns_overview', arguments='{}')]),
    ])
    assert items[-1].stop_reason == 'tool_use'


# ── per-deployment parameter quirks ─────────────────────────────────────────

def err(message, status=400):
    return SimpleNamespace(status_code=status, message=message)


def test_a_deployment_that_forbids_max_completion_tokens_gets_the_legacy_param():
    params = {'max_completion_tokens': 8000, 'model': 'm'}
    changed = llm._param_fallback(params, err('max_completion_tokens: extra_forbidden', 422))
    assert changed
    assert 'max_completion_tokens' not in params
    assert params['max_tokens'] == 8000


def test_rejected_optional_params_are_dropped_one_at_a_time():
    params = {'temperature': 0.2, 'reasoning_effort': 'high'}
    assert llm._param_fallback(params, err('reasoning_effort is not supported'))
    assert 'reasoning_effort' not in params and 'temperature' in params
    assert llm._param_fallback(params, err('temperature is not supported'))
    assert 'temperature' not in params


def test_an_unrelated_error_triggers_no_fallback():
    params = {'max_completion_tokens': 100}
    assert llm._param_fallback(params, err('model not found', 404)) is None
    assert llm._param_fallback(params, err('rate limited', 429)) is None
    assert params == {'max_completion_tokens': 100}


# ── the non-streaming fallback path ─────────────────────────────────────────

def test_a_non_streaming_response_normalises_to_the_same_turn():
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason='tool_calls',
            message=SimpleNamespace(content='thinking', tool_calls=[
                SimpleNamespace(id='call_1', function=SimpleNamespace(
                    name='uns_browse', arguments=json.dumps({'path': 'acme'}))),
            ]),
        )],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )
    turn = llm._normalize(response)
    assert turn.text == 'thinking'
    assert turn.stop_reason == 'tool_use'
    assert turn.tool_calls[0].input == {'path': 'acme'}
    assert turn.usage.prompt_tokens == 5


def test_a_response_without_usage_still_normalises():
    response = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason='stop',
                                 message=SimpleNamespace(content='hi', tool_calls=None))],
        usage=None,
    )
    assert llm._normalize(response).usage == llm.Usage()

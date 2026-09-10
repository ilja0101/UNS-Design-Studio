"""The agentic turn: model → tool calls → tool results → model, until it stops.

Emits events as it goes so the chat page can stream. The event contract is
small on purpose — the UI renders four things:

``delta``        a chunk of assistant text
``tool_call``    the agent is about to run a tool (name + arguments)
``tool_result``  what came back (ok/error, a one-line summary, the payload)
``done``         the turn ended, with the stop reason and token usage
``error``        the turn could not continue (bad config, endpoint down)

Everything is appended to the conversation as it happens, so a browser that
disconnects mid-turn loses the stream but not the work: reloading the page
shows the completed turn, tool calls included.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from uds_agent import policy as policy_mod
from uds_agent import prompts, settings, store
from uds_agent import tools as tools_mod
from uds_agent.backend import Backend
from uds_agent.llm import (
    InferenceError,
    InferenceTurn,
    LlmAdapter,
    TextDelta,
    ToolDescriptor,
)

log = logging.getLogger(__name__)


def is_configured() -> bool:
    cfg = settings.load()
    return bool(cfg.get('endpoint') and cfg.get('apiKey') and cfg.get('model'))


def _descriptors(allow_writes: bool) -> list[ToolDescriptor]:
    return [
        ToolDescriptor(name=t.name, description=t.description, input_schema=t.schema)
        for t in tools_mod.registry(include_writes=allow_writes)
    ]


async def run_turn(backend: Backend, convo: dict, user_text: str) -> AsyncIterator[dict]:
    """Drive one user turn to completion, yielding UI events."""
    cfg = settings.load()
    if not (cfg.get('endpoint') and cfg.get('apiKey') and cfg.get('model')):
        yield {'type': 'error', 'message':
               'No LLM endpoint configured. Set one under Settings → Agent, or point an '
               'external agent at this UDS over MCP instead.'}
        return

    if user_text:
        store.append(convo, {'role': 'user', 'content': user_text})
        if not convo.get('messages') or len(convo['messages']) == 1:
            convo['title'] = store.title_from(user_text)
        store.save(convo)

    adapter = LlmAdapter(cfg['endpoint'], cfg['apiKey'], cfg['model'],
                         max_tokens=int(cfg.get('maxTokens') or 8000))
    allow_writes = bool(cfg.get('allowWrites', True))
    descriptors = _descriptors(allow_writes)
    system = prompts.system_prompt(policy_mod.load_policy(), cfg.get('systemPromptExtra', ''))
    max_steps = max(1, int(cfg.get('maxSteps') or 24))
    temperature = cfg.get('temperature')
    reasoning = cfg.get('reasoningEffort') or ''

    totals = {'prompt': 0, 'completion': 0, 'steps': 0}

    for step in range(max_steps):
        totals['steps'] = step + 1
        turn: InferenceTurn | None = None
        try:
            async for item in adapter.stream_turn(
                system=system, messages=store.for_model(convo), tools=descriptors,
                temperature=temperature, reasoning_effort=reasoning,
            ):
                if isinstance(item, TextDelta):
                    yield {'type': 'delta', 'text': item.text}
                else:
                    turn = item
        except InferenceError as exc:
            store.save(convo)
            yield {'type': 'error', 'message': _explain(exc), 'retryable': exc.retryable}
            return

        if turn is None:
            yield {'type': 'error', 'message': 'the model returned nothing'}
            return

        totals['prompt'] += turn.usage.prompt_tokens
        totals['completion'] += turn.usage.completion_tokens

        assistant: dict[str, Any] = {'role': 'assistant', 'content': turn.text or ''}
        if turn.tool_calls:
            assistant['tool_calls'] = [
                {'id': c.id, 'type': 'function',
                 'function': {'name': c.name, 'arguments': json.dumps(c.input)}}
                for c in turn.tool_calls
            ]
        store.append(convo, assistant)

        if not turn.tool_calls:
            store.save(convo)
            yield {'type': 'done', 'stop': turn.stop_reason, 'usage': totals,
                   'title': convo.get('title')}
            return

        for tc in turn.tool_calls:
            yield {'type': 'tool_call', 'id': tc.id, 'name': tc.name, 'args': tc.input}
            ok, payload = await _run_tool(backend, tc, allow_writes)
            summary = _summarize(tc.name, ok, payload)
            store.append(convo, {
                'role': 'tool', 'tool_call_id': tc.id, 'name': tc.name,
                'content': _render(payload), 'ok': ok, 'summary': summary,
            })
            yield {'type': 'tool_result', 'id': tc.id, 'name': tc.name, 'ok': ok,
                   'summary': summary, 'result': payload if isinstance(payload, dict) else None}
        store.save(convo)

    store.save(convo)
    yield {'type': 'done', 'stop': 'max_steps', 'usage': totals, 'title': convo.get('title'),
           'message': f'Stopped after {max_steps} tool steps. Ask me to continue if there is '
                      f'more to do.'}


async def _run_tool(backend: Backend, call, allow_writes: bool) -> tuple[bool, Any]:
    if call.input_error:
        return False, f'could not read your arguments: {call.input_error}'
    try:
        return True, await tools_mod.call(backend, call.name, call.input,
                                          allow_writes=allow_writes)
    except tools_mod.ToolError as exc:
        return False, str(exc)
    except Exception as exc:  # a bug in a tool must not kill the conversation
        log.exception('agent: tool %s raised', call.name)
        return False, f'{call.name} failed unexpectedly: {exc}'


def _summarize(name: str, ok: bool, payload: Any) -> str:
    """One line for the tool card — what a person glancing at the chat needs."""
    if not ok:
        return str(payload)[:200]
    if not isinstance(payload, dict):
        return f'{name} ok'
    if 'violations' in payload:
        counts = payload.get('counts') or {}
        if payload.get('ok'):
            return f"policy clean — {counts.get('topics', 0)} topics checked"
        return (f"{counts.get('violations', 0)} violation(s) across "
                f"{counts.get('nodes', 0)} nodes")
    if 'snapshot' in payload:
        bits = [f"{payload.get('nodes', '?')} nodes", f"{payload.get('tags', '?')} tags"]
        if payload.get('restarted'):
            bits.append('restarted ' + ', '.join(payload['restarted']))
        return ', '.join(bits)
    if 'total' in payload and 'topics' in payload:
        return f"{payload['total']} topic(s)"
    if 'count' in payload:
        return f"{payload['count']} result(s)"
    if 'counts' in payload:
        c = payload['counts']
        return f"{c.get('nodes', 0)} nodes, {c.get('tags', 0)} tags"
    if 'nodes' in payload and isinstance(payload['nodes'], list):
        return f"{len(payload['nodes'])} node(s)"
    return f'{name} ok'


def _render(payload: Any) -> str:
    """What the model sees as the tool result. Capped — a huge blob helps nobody."""
    if isinstance(payload, str):
        return payload[:20000]
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    if len(text) > 20000:
        return text[:20000] + '\n…(truncated — narrow the query and call again)'
    return text


def _explain(exc: InferenceError) -> str:
    if exc.kind == 'connection':
        return f'{exc}. Check the endpoint under Settings → Agent.'
    if exc.kind == 'rate_limit':
        return 'The LLM endpoint rate-limited this request. Try again in a moment.'
    if exc.status == 401:
        return 'The LLM endpoint rejected the API key. Update it under Settings → Agent.'
    if exc.status == 404:
        return (f'The endpoint has no deployment named "{settings.load().get("model")}". '
                'Check the model name under Settings → Agent.')
    return str(exc)

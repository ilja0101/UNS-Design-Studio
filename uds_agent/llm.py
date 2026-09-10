"""Streaming adapter over any OpenAI-compatible endpoint.

A port of the wire-format lessons already paid for in UNS-Industrial-AI-V2's
``server/llm/adapter.py``, kept deliberately close to it so the two apps fail
the same way against the same deployment:

* ``max_completion_tokens`` first; deployments that 422 it as ``extra_forbidden``
  get one retry with legacy ``max_tokens``.
* ``temperature`` and ``reasoning_effort`` are only sent when set, and are
  dropped on a retry if the deployment rejects them.
* A deployment that refuses ``stream`` falls back to one non-streaming call,
  emitted as a single delta — the consumer contract does not change.
* Streamed tool-call fragments merge by ``index``: id and name land on the
  first fragment, arguments concatenate across all of them.
* Malformed tool-call JSON becomes ``ToolCall.input_error`` and is answered as
  an error tool result, rather than raising.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 8000
_CONTENT_FILTER_MESSAGE = (
    "The model provider's content filter stopped this response. Please rephrase and try again."
)


@dataclass
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict = field(default_factory=dict)
    input_error: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class TextDelta:
    text: str


@dataclass
class InferenceTurn:
    text: str = ''
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = 'end_turn'
    usage: Usage = field(default_factory=Usage)


class InferenceError(RuntimeError):
    def __init__(self, kind: str, message: str, status: int | None = None,
                 retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retryable = retryable


class LlmAdapter:
    def __init__(self, endpoint: str, api_key: str, model: str,
                 max_tokens: int = DEFAULT_MAX_TOKENS):
        import openai
        self.endpoint = endpoint
        self.model = model
        self._max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        self._client = openai.AsyncOpenAI(base_url=endpoint or None, api_key=api_key or 'unset',
                                          max_retries=2)

    async def stream_turn(
        self, *, system: str, messages: list[dict[str, Any]],
        tools: list[ToolDescriptor] | None = None,
        temperature: float | None = None, reasoning_effort: str | None = None,
    ) -> AsyncIterator[TextDelta | InferenceTurn]:
        """Yield TextDelta items as tokens arrive, then exactly one InferenceTurn."""
        import openai

        params = build_request(model=self.model, system=system, messages=messages, tools=tools,
                               temperature=temperature, reasoning_effort=reasoning_effort,
                               max_tokens=self._max_tokens)

        attempts = 0
        streaming = True
        while True:
            attempts += 1
            try:
                if streaming:
                    stream = await self._client.chat.completions.create(
                        **params, stream=True, stream_options={'include_usage': True})
                    async for item in self._consume(stream):
                        yield item
                else:
                    response = await self._client.chat.completions.create(**params)
                    turn = _normalize(response)
                    if turn.text:
                        yield TextDelta(turn.text)
                    yield turn
                return
            except openai.RateLimitError as exc:
                raise InferenceError('rate_limit', 'rate limited by the LLM endpoint', 429,
                                     retryable=True) from exc
            except openai.APIStatusError as exc:
                mutated = _param_fallback(params, exc)
                if mutated and attempts < 5:
                    log.info('llm: param fallback (%s), retrying', mutated)
                    continue
                if streaming and 'stream' in str(getattr(exc, 'message', exc) or ''):
                    log.info('llm: deployment rejects streaming — falling back')
                    streaming = False
                    continue
                status = getattr(exc, 'status_code', None)
                raise InferenceError('api_status', str(getattr(exc, 'message', exc)), status,
                                     retryable=(status or 0) >= 500) from exc
            except openai.APIConnectionError as exc:
                raise InferenceError('connection',
                                     f'cannot reach the LLM endpoint at {self.endpoint}',
                                     retryable=True) from exc

    async def _consume(self, stream: Any) -> AsyncIterator[TextDelta | InferenceTurn]:
        text_parts: list[str] = []
        frags: dict[int, dict[str, str]] = {}
        finish: str | None = None
        usage = Usage()

        async for chunk in stream:
            if getattr(chunk, 'usage', None):
                usage = Usage(prompt_tokens=chunk.usage.prompt_tokens or 0,
                              completion_tokens=chunk.usage.completion_tokens or 0)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta is not None and delta.content:
                text_parts.append(delta.content)
                yield TextDelta(delta.content)
            for frag in (delta.tool_calls or []) if delta is not None else []:
                slot = frags.setdefault(frag.index, {'id': '', 'name': '', 'arguments': ''})
                if frag.id:
                    slot['id'] = frag.id
                if frag.function is not None:
                    if frag.function.name:
                        slot['name'] += frag.function.name
                    if frag.function.arguments:
                        slot['arguments'] += frag.function.arguments
            if choice.finish_reason:
                finish = choice.finish_reason

        yield _finalize(''.join(text_parts), frags, finish, usage)


def _param_fallback(params: dict[str, Any], exc: Any) -> str | None:
    """Mutate params for one known per-deployment quirk; return what changed."""
    return param_fallback(params, getattr(exc, 'status_code', None),
                          str(getattr(exc, 'message', exc) or ''))


def param_fallback(params: dict[str, Any], status: int | None, msg: str) -> str | None:
    """The same quirks, from a status and a message -- what the mesh door has.

    The gateway forwards the provider's own refusal sentence, so the needles
    below match it on either door. Each call mutates ONE thing and says which;
    the caller retries and comes back if the next refusal names another.
    """
    if status not in (400, 422):
        return None
    # A newer model refusing the legacy name. Seen on the lab from gpt-5.6-luna
    # through the gateway, word for word: "'max_tokens' is not supported with
    # this model. Use 'max_completion_tokens' instead." That sentence names BOTH
    # parameters, so it is checked first and the forward rule below is fenced
    # off from it -- otherwise the two flip each other until the attempt cap.
    if 'max_tokens' in params and "'max_tokens'" in msg and 'max_completion_tokens' in msg:
        params['max_completion_tokens'] = params.pop('max_tokens')
        return 'max_tokens→max_completion_tokens'
    if 'max_completion_tokens' in params and 'max_completion_tokens' in msg and (
        'extra_forbidden' in msg or 'not permitted' in msg or 'unsupported' in msg.lower()
    ) and "'max_tokens' is not supported" not in msg:
        params['max_tokens'] = params.pop('max_completion_tokens')
        return 'max_completion_tokens→max_tokens'
    if 'reasoning_effort' in params and 'reasoning_effort' in msg:
        params.pop('reasoning_effort')
        return 'dropped reasoning_effort'
    if 'temperature' in params and 'temperature' in msg:
        params.pop('temperature')
        return 'dropped temperature'
    return None


def _parse_call(id_: str, name: str, arguments: str) -> ToolCall:
    try:
        parsed = json.loads(arguments or '{}')
    except json.JSONDecodeError as exc:
        return ToolCall(id=id_, name=name, input_error=f'arguments are not valid JSON ({exc.msg})')
    if not isinstance(parsed, dict):
        return ToolCall(id=id_, name=name, input_error='arguments JSON must be an object')
    return ToolCall(id=id_, name=name, input=parsed)


_STOP = {'stop': 'end_turn', 'tool_calls': 'tool_use', 'length': 'max_tokens',
         'function_call': 'tool_use'}


def _finalize(text: str, frags: dict[int, dict[str, str]], finish: str | None,
              usage: Usage) -> InferenceTurn:
    calls = [
        _parse_call(f['id'] or f'call_{i}', f['name'], f['arguments'])
        for i, f in sorted(frags.items())
        if f.get('name')
    ]
    if finish == 'content_filter':
        return InferenceTurn(text=text or _CONTENT_FILTER_MESSAGE, stop_reason='refusal',
                             usage=usage)
    stop = _STOP.get(finish or '', 'tool_use' if calls else 'end_turn')
    return InferenceTurn(text=text, tool_calls=calls, stop_reason=stop, usage=usage)


def _normalize(response: Any) -> InferenceTurn:
    choice = response.choices[0]
    message = choice.message
    frags = {
        i: {'id': tc.id or f'call_{i}', 'name': tc.function.name or '',
            'arguments': tc.function.arguments or ''}
        for i, tc in enumerate(message.tool_calls or [])
    }
    usage = Usage(
        prompt_tokens=getattr(response.usage, 'prompt_tokens', 0) or 0,
        completion_tokens=getattr(response.usage, 'completion_tokens', 0) or 0,
    ) if getattr(response, 'usage', None) else Usage()
    return _finalize(message.content or '', frags, choice.finish_reason, usage)


def build_request(*, model: str, system: str, messages: list[dict[str, Any]],
                  tools: list[ToolDescriptor] | None, temperature: float | None,
                  reasoning_effort: str | None, max_tokens: int) -> dict[str, Any]:
    """The OpenAI chat-completion body, built once for every door.

    The HTTP adapter posts this; the mesh adapter wraps it in the gateway's
    envelope and publishes it. Same bytes either way, so a tool that works on
    one door works on the other -- the gateway forwards the body verbatim.
    """
    params: dict[str, Any] = {
        'model': model,
        'max_completion_tokens': max_tokens,
        'messages': [{'role': 'system', 'content': system}, *messages],
    }
    if tools:
        params['tools'] = [
            {'type': 'function',
             'function': {'name': t.name, 'description': t.description,
                          'parameters': t.input_schema}}
            for t in tools
        ]
        params['tool_choice'] = 'auto'
    if temperature is not None:
        params['temperature'] = temperature
    if reasoning_effort:
        params['reasoning_effort'] = reasoning_effort
    return params


def normalize_dict(response: dict[str, Any]) -> InferenceTurn:
    """``_normalize`` for a response that arrived as JSON rather than an SDK object."""
    choices = response.get('choices') or []
    choice = choices[0] if choices else {}
    message = choice.get('message') or {}
    frags = {
        i: {'id': tc.get('id') or f'call_{i}',
            'name': (tc.get('function') or {}).get('name') or '',
            'arguments': (tc.get('function') or {}).get('arguments') or ''}
        for i, tc in enumerate(message.get('tool_calls') or [])
    }
    u = response.get('usage') or {}
    usage = Usage(prompt_tokens=int(u.get('prompt_tokens') or 0),
                  completion_tokens=int(u.get('completion_tokens') or 0))
    return _finalize(message.get('content') or '', frags, choice.get('finish_reason'), usage)

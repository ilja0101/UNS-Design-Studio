"""The mesh door: ask the Model Gateway over the app's own backbone.

Every appshell application on the IIoT-Hub platform reaches a model this way
by default, and it exists for the situation UDS is in: the only application in
the OT tier, with no HTTP route to the gateway at L4 and no business holding a
provider key of its own. On the bus there is no address to route to. The plant
dials the tier above it, the request rides up, the answer rides back down the
same connection, and nothing inbound is ever opened.

The contract, as measured on the lab on 2026-09-10 rather than read:

* Publish on ``iiot.svc.llmgw.chat.<app-id>`` (``/``-form on Solace/MQTT).
* Envelope ``{"person", "purpose", "body"}`` where ``body`` is the OpenAI
  chat-completion request, forwarded to the provider verbatim -- so ``tools``
  and ``tool_calls`` survive, which is what lets this agent model rather than
  merely chat. ``stream`` must be false: the gateway refuses a stream because
  it reads the token count off the end of the answer for the ledger.
* The reply address is NOT MQTT's response-topic or SMF reply-to. The Solace
  backbone driver carries it as the user property ``bb-reply`` in DOT form and
  moves it into ``Msg.Reply`` on delivery; the responder publishes there. On
  NATS it is the native inbox.
* Reply ``{"status", "body", "provider", "residency"}``; ``body`` is the
  OpenAI response, or ``{"error": {...}}`` with the status telling you which.
* The gateway registers the application on first contact and REFUSES an
  undecided app/model pair on a provider whose data leaves the site, with a
  message saying where to allow it. That refusal is the governance working.

One long-lived reply subscription per connection, with a per-request token
under it. A fresh subscription per request loses the race with the answer
across a DMR link -- the gateway answered in 6 ms on the lab while the
subscription was still propagating, and direct messaging drops a reply with
nobody listening without a word. Measured, not theorised.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from uds_agent.llm import (
    InferenceError,
    InferenceTurn,
    TextDelta,
    ToolDescriptor,
    build_request,
    normalize_dict,
)

log = logging.getLogger(__name__)

SUBJECT_ROOT = 'iiot.svc.llmgw'
DEFAULT_TIMEOUT = 120.0


def subject_token(app_id: str) -> str:
    """pkg/modelgw.SubjectToken: lower-case, [a-z0-9-_], anything else -> '-'."""
    out = []
    for ch in (app_id or '').strip():
        if ch.isascii() and (ch.isalnum() or ch in '-_'):
            out.append(ch.lower())
        else:
            out.append('-')
    return ''.join(out) or 'uns-design-studio'


def chat_subject(app_id: str) -> str:
    return f'{SUBJECT_ROOT}.chat.{subject_token(app_id)}'


def envelope(body: dict, *, person: str, purpose: str) -> bytes:
    return json.dumps({'person': person, 'purpose': purpose, 'body': body},
                      ensure_ascii=False).encode('utf-8')


def unwrap(raw: bytes | str) -> tuple[int, Any]:
    """Return (status, body) from a gateway reply, raising InferenceError on refusal."""
    try:
        reply = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise InferenceError('mesh', f'the gateway reply was not JSON: {exc}') from exc
    status = int(reply.get('status') or 0)
    body = reply.get('body')
    if status != 200:
        message = ''
        if isinstance(body, dict):
            err = body.get('error')
            if isinstance(err, dict):
                message = str(err.get('message') or '')
            elif err:
                message = str(err)
        raise InferenceError('gateway', message or f'the gateway answered {status}', status,
                             retryable=status >= 500)
    if not isinstance(body, dict):
        raise InferenceError('mesh', 'the gateway reply carried no body')
    return status, body


class MeshAdapter:
    """Same ``stream_turn`` surface as ``LlmAdapter``; the wire is the backbone.

    ``protocol`` is ``mqtt`` (a Solace backbone, reached over its MQTT
    listener) or ``nats``. Both speak the same envelope; only the reply
    address differs, and that is the whole reason this class exists.
    """

    def __init__(self, *, protocol: str, host: str, port: int, app_id: str,
                 username: str = '', password: str = '', creds: str = '',
                 person: str = '', purpose: str = '', model: str = '',
                 timeout: float = DEFAULT_TIMEOUT, max_tokens: int = 8000):
        self.protocol = (protocol or 'mqtt').lower()
        self.host, self.port = host, int(port)
        self.username, self.password, self.creds = username, password, creds
        self.app_id = subject_token(app_id)
        self.person = person or 'operator'
        self.purpose = purpose or 'modelling the UNS in UNS Design Studio'
        self.model = model
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        self._max_tokens = max_tokens
        self._subject = chat_subject(self.app_id)
        self._conn_token = secrets.token_hex(6)
        self._client: Any = None
        self._pending: dict[str, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ── public ──────────────────────────────────────────────────────────────

    async def stream_turn(
        self, *, system: str, messages: list[dict[str, Any]],
        tools: list[ToolDescriptor] | None = None,
        temperature: float | None = None, reasoning_effort: str | None = None,
    ) -> AsyncIterator[TextDelta | InferenceTurn]:
        body = build_request(model=self.model, system=system, messages=messages, tools=tools,
                             temperature=temperature, reasoning_effort=reasoning_effort,
                             max_tokens=self._max_tokens)
        body.pop('max_completion_tokens', None)
        body['max_tokens'] = self._max_tokens
        body['stream'] = False   # the gateway refuses a stream, by design
        raw = await self._request(envelope(body, person=self.person, purpose=self.purpose))
        _, response = unwrap(raw)
        turn = normalize_dict(response)
        if turn.text:
            yield TextDelta(turn.text)
        yield turn

    async def aclose(self) -> None:
        if self._reader:
            self._reader.cancel()
            self._reader = None
        client, self._client = self._client, None
        if client is not None:
            try:
                if self.protocol == 'nats':
                    await client.drain()
                else:
                    await client.__aexit__(None, None, None)
            except Exception:  # closing is best-effort
                pass

    # ── transport ───────────────────────────────────────────────────────────

    async def _request(self, payload: bytes) -> bytes:
        if self.protocol == 'nats':
            return await self._request_nats(payload)
        return await self._request_mqtt(payload)

    async def _request_nats(self, payload: bytes) -> bytes:
        """NATS has a native inbox; this is one call."""
        import nats
        async with self._lock:
            if self._client is None:
                opts: dict[str, Any] = {'name': f'{self.app_id}-agent', 'connect_timeout': 5,
                                        'max_reconnect_attempts': -1}
                if self.creds:
                    opts['user_credentials'] = self.creds
                url = f'nats://{self.host}:{self.port}'
                if self.username:
                    url = f'nats://{self.username}:{self.password}@{self.host}:{self.port}'
                try:
                    self._client = await nats.connect(url, **opts)
                except Exception as exc:
                    raise InferenceError('connection', f'cannot reach the backbone at {url}: {exc}',
                                         retryable=True) from exc
        try:
            msg = await self._client.request(self._subject, payload, timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise InferenceError('timeout',
                                 f'no answer from the Model Gateway on {self._subject} within '
                                 f'{self.timeout:.0f}s — is llmgw serving this backbone?',
                                 retryable=True) from exc
        except Exception as exc:
            raise InferenceError('mesh', f'request on {self._subject} failed: {exc}',
                                 retryable=True) from exc
        return msg.data

    async def _request_mqtt(self, payload: bytes) -> bytes:
        """Solace over its MQTT listener: reply address as the bb-reply property."""
        await self._ensure_mqtt()
        token = secrets.token_hex(6)
        reply_subject = f'_REPLY.{self.app_id}.{self._conn_token}.{token}'   # dot form: what the driver reads
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[token] = fut
        try:
            from paho.mqtt.packettypes import PacketTypes
            from paho.mqtt.properties import Properties
            props = Properties(PacketTypes.PUBLISH)
            props.UserProperty = [('bb-reply', reply_subject)]
            await self._client.publish(self._subject.replace('.', '/'), payload, qos=0,
                                       properties=props)
            return await asyncio.wait_for(fut, timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise InferenceError('timeout',
                                 f'no answer from the Model Gateway on {self._subject} within '
                                 f'{self.timeout:.0f}s — is llmgw serving this backbone, and '
                                 f'does the reply subscription reach it?', retryable=True) from exc
        except InferenceError:
            raise
        except Exception as exc:
            raise InferenceError('mesh', f'request on {self._subject} failed: {exc}',
                                 retryable=True) from exc
        finally:
            self._pending.pop(token, None)

    async def _ensure_mqtt(self) -> None:
        async with self._lock:
            if self._client is not None:
                return
            import aiomqtt
            client = aiomqtt.Client(
                self.host, self.port, protocol=aiomqtt.ProtocolVersion.V5,
                username=self.username or None, password=self.password or None,
                identifier=f'{self.app_id}-agent-{self._conn_token}', timeout=10,
            )
            try:
                await client.__aenter__()
            except Exception as exc:
                raise InferenceError('connection',
                                     f'cannot reach the backbone at {self.host}:{self.port}: {exc}',
                                     retryable=True) from exc
            # One subscription for the life of the connection, tokens under it.
            reply_filter = f'_REPLY/{self.app_id}/{self._conn_token}/+'
            await client.subscribe(reply_filter)
            self._client = client
            self._reader = asyncio.create_task(self._read_replies(client))
            # Let the subscription cross the DMR link before the first request
            # can be answered into it. Measured: the gateway answers in ~6 ms,
            # propagation is single-digit ms on a quiet mesh and more under load.
            await asyncio.sleep(1.0)
            log.info('mesh: %s connected to %s:%s, replies on %s', self.protocol, self.host,
                     self.port, reply_filter)

    async def _read_replies(self, client: Any) -> None:
        try:
            async for m in client.messages:
                token = str(m.topic).rsplit('/', 1)[-1]
                fut = self._pending.get(token)
                if fut is not None and not fut.done():
                    fut.set_result(bytes(m.payload))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning('mesh: reply reader stopped: %s', exc)
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(InferenceError('mesh', f'backbone connection lost: {exc}',
                                                     retryable=True))
            self._client = None

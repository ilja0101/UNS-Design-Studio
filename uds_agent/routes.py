"""HTTP surface for the agent — settings, conversations, and the chat stream.

Registered on the dashboard as a Quart blueprint, so it sits behind the same
auth as the rest of the app. The chat endpoint streams Server-Sent Events: one
``data:`` line per event from :func:`uds_agent.loop.run_turn`, which is enough
for the SPA to render text as it arrives and pop a card per tool call, without
a websocket to keep alive.
"""

from __future__ import annotations

import json
import logging

from quart import Blueprint, Response, jsonify, request

from uds_agent import loop as agent_loop
from uds_agent import policy as policy_mod
from uds_agent import settings as agent_settings
from uds_agent import store
from uds_agent import tools as tools_mod
from uds_agent.backend import DirectBackend

log = logging.getLogger(__name__)

bp = Blueprint('uds_agent', __name__, url_prefix='/api/agent')

_backend = DirectBackend()


# ── settings ────────────────────────────────────────────────────────────────

@bp.route('/settings', methods=['GET'])
async def get_settings():
    return jsonify(agent_settings.public_view())


@bp.route('/settings', methods=['POST'])
async def save_settings():
    patch = await request.get_json() or {}
    return jsonify(agent_settings.public_view(agent_settings.save(patch)))


@bp.route('/tools', methods=['GET'])
async def list_tools():
    """What the agent can do — rendered in the UI so the capability is visible."""
    return jsonify({'tools': [
        {'name': t.name, 'description': t.description, 'writes': t.writes,
         'schema': t.schema}
        for t in tools_mod.registry()
    ]})


# ── topic policy ────────────────────────────────────────────────────────────

@bp.route('/policy', methods=['GET'])
async def get_policy():
    return jsonify(policy_mod.load_policy())


@bp.route('/policy', methods=['POST'])
async def save_policy():
    body = await request.get_json() or {}
    if not policy_mod.save_policy(body):
        return jsonify({'ok': False, 'error': 'could not write topic_policy.json'}), 500
    return jsonify({'ok': True, 'policy': policy_mod.load_policy()})


@bp.route('/policy/check', methods=['GET'])
async def check_policy():
    try:
        uns = await _backend.call('GET', '/api/uns')
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500
    limit = max(1, min(200, int(request.args.get('limit', 50))))
    return jsonify(policy_mod.check_policy(uns or {}, limit=limit))


@bp.route('/topics', methods=['GET'])
async def preview_topics():
    uns = await _backend.call('GET', '/api/uns')
    return jsonify(policy_mod.preview_topics(
        uns or {},
        limit=max(1, min(500, int(request.args.get('limit', 100)))),
        contains=request.args.get('contains', ''),
    ))


# ── model snapshots (the undo history) ──────────────────────────────────────

@bp.route('/snapshots', methods=['GET'])
async def snapshots():
    return jsonify({'snapshots': tools_mod.list_snapshots()})


@bp.route('/snapshots/<sid>/revert', methods=['POST'])
async def revert(sid: str):
    try:
        return jsonify(await tools_mod.call(_backend, 'uns_revert', {'snapshot': sid}))
    except tools_mod.ToolError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400


# ── conversations ───────────────────────────────────────────────────────────

@bp.route('/conversations', methods=['GET'])
async def conversations():
    return jsonify({'conversations': store.listing()})


@bp.route('/conversations', methods=['POST'])
async def create_conversation():
    body = await request.get_json() or {}
    return jsonify(store.create(body.get('title') or 'New chat'))


@bp.route('/conversations/<cid>', methods=['GET'])
async def get_conversation(cid: str):
    convo = store.load(cid)
    if convo is None:
        return jsonify({'error': 'no such conversation'}), 404
    return jsonify(convo)


@bp.route('/conversations/<cid>', methods=['DELETE'])
async def delete_conversation(cid: str):
    return jsonify({'ok': store.delete(cid)})


# ── chat ────────────────────────────────────────────────────────────────────

@bp.route('/chat', methods=['POST'])
async def chat():
    body = await request.get_json() or {}
    text = str(body.get('message') or '').strip()
    cid = body.get('conversation')
    convo = store.load(cid) if cid else None
    if convo is None:
        convo = store.create(store.title_from(text))
    if not text:
        return jsonify({'error': 'message must not be empty'}), 400

    async def stream():
        # The conversation id goes out first so the client can adopt a
        # freshly-created conversation before any content arrives.
        yield _sse({'type': 'start', 'conversation': convo['id'], 'title': convo.get('title')})
        try:
            async for event in agent_loop.run_turn(_backend, convo, text):
                yield _sse(event)
        except Exception as exc:  # pragma: no cover — belt and braces
            log.exception('agent: chat stream failed')
            yield _sse({'type': 'error', 'message': str(exc)})

    return Response(stream(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache, no-transform',
        'X-Accel-Buffering': 'no',   # nginx must not buffer an SSE stream
        'Connection': 'keep-alive',
    })


def _sse(event: dict) -> str:
    return 'data: ' + json.dumps(event, ensure_ascii=False, default=str) + '\n\n'

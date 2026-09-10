"""Streamable-HTTP MCP transport, as a Quart blueprint.

Mounted at ``/mcp`` on the dashboard itself, so an external agent drives the
same running UDS the browser is looking at. The gate is a bearer token
(``UDS_MCP_TOKEN``, else the one minted into ``agent_config.json``), matching
the family's convention — see ``UNS-Knowledge-Graph/cmd/kg-mcp``, whose nginx
front door does constant-time bearer matching in exactly this shape.

The spec allows a POST to be answered either with a single JSON body or with an
SSE stream. UDS answers with JSON: every tool here completes in one shot, so a
stream would add framing for no benefit. GET (the server-initiated stream) is
refused with 405, which clients treat as "this server does not push".
"""

from __future__ import annotations

import hmac
import json
import logging

from quart import Blueprint, Response, jsonify, request

from uds_agent import settings as agent_settings
from uds_agent.backend import DirectBackend
from uds_mcp.protocol import PARSE_ERROR, PROTOCOL_VERSION, McpDispatcher

log = logging.getLogger(__name__)

bp = Blueprint('uds_mcp', __name__)

# One dispatcher per process: it is stateless apart from the backend handle.
_dispatcher: McpDispatcher | None = None


def _get_dispatcher() -> McpDispatcher:
    global _dispatcher
    cfg = agent_settings.load()
    allow_writes = bool(cfg.get('mcpAllowWrites', True))
    if _dispatcher is None or _dispatcher.allow_writes != allow_writes:
        _dispatcher = McpDispatcher(DirectBackend(), allow_writes=allow_writes)
    return _dispatcher


def _authorized() -> bool:
    cfg = agent_settings.load()
    token = str(cfg.get('mcpToken') or '')
    if not token:
        return False
    header = request.headers.get('Authorization', '')
    scheme, _, value = header.partition(' ')
    if scheme.lower() != 'bearer':
        return False
    return hmac.compare_digest(value.strip(), token)


def _enabled() -> bool:
    return bool(agent_settings.load().get('mcpEnabled', True))


@bp.route('/mcp', methods=['POST'])
@bp.route('/mcp/', methods=['POST'])
async def mcp_post() -> Response:
    if not _enabled():
        return jsonify({'error': 'MCP is disabled on this UDS'}), 404
    if not _authorized():
        resp = jsonify({'error': 'missing or invalid bearer token'})
        resp.status_code = 401
        resp.headers['WWW-Authenticate'] = 'Bearer realm="uns-design-studio"'
        return resp

    raw = await request.get_data()
    try:
        message = json.loads(raw or b'{}')
    except ValueError as exc:
        return jsonify({'jsonrpc': '2.0', 'id': None,
                        'error': {'code': PARSE_ERROR, 'message': f'invalid JSON: {exc}'}}), 400

    reply = await _get_dispatcher().handle(message)
    if reply is None:
        # A notification carries no response body; 202 is what the spec asks for.
        return Response('', status=202)
    resp = jsonify(reply)
    resp.headers['MCP-Protocol-Version'] = PROTOCOL_VERSION
    return resp


@bp.route('/mcp', methods=['GET'])
@bp.route('/mcp/', methods=['GET'])
async def mcp_get() -> Response:
    """No server-initiated stream — nothing here pushes to the client."""
    resp = Response('', status=405)
    resp.headers['Allow'] = 'POST'
    return resp


@bp.route('/mcp/info', methods=['GET'])
async def mcp_info():
    """Unauthenticated discovery: is MCP on, and what does it expose?

    Deliberately free of anything sensitive — no token, no model contents —
    so a health check or a human wiring up a client can see the endpoint is
    alive and which tools it would offer.
    """
    cfg = agent_settings.load()
    if not cfg.get('mcpEnabled', True):
        return jsonify({'enabled': False}), 404
    dispatcher = _get_dispatcher()
    return jsonify({
        'enabled': True,
        'protocolVersion': PROTOCOL_VERSION,
        'server': {'name': dispatcher.server_name, 'version': dispatcher.server_version},
        'allowWrites': dispatcher.allow_writes,
        'transport': 'streamable-http',
        'endpoint': '/mcp',
        'auth': 'bearer',
        'tools': [
            {'name': t['name'], 'readOnly': t['annotations']['readOnlyHint']}
            for t in dispatcher.tool_descriptors()
        ],
    })

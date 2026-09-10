"""Transport-agnostic MCP dispatch: JSON-RPC in, JSON-RPC out.

Hand-rolled rather than pulled from an SDK, for the same reason kg-mcp keeps
its server small: the surface an agent actually needs is initialize, tools/list
and tools/call, and UDS already has a JSON-RPC-shaped async stack. Every
transport in this package is a thin shell around :meth:`McpDispatcher.handle`.

Errors follow the MCP convention that a *tool* failure is a successful RPC
carrying ``isError: true`` — the model reads the message and retries — while a
*protocol* failure is a JSON-RPC error object.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from uds_agent import tools as tools_mod
from uds_agent.backend import Backend

log = logging.getLogger(__name__)

# The streamable-HTTP revision this server implements. A client asking for an
# older revision is answered at its own version when we can honour it.
PROTOCOL_VERSION = '2025-06-18'
SUPPORTED_VERSIONS = {'2024-11-05', '2025-03-26', '2025-06-18'}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SERVER_INSTRUCTIONS = (
    'UNS Design Studio simulates an industrial Unified Namespace: an ISA-95 tree of sites, '
    'areas, work centres and equipment, each carrying tags that are served over OPC-UA and '
    'published to MQTT/NATS.\n\n'
    'Start with uns_overview, then uns_browse or uns_search to find your way around. To model '
    'something new, read the rulebook with policy_get, build with uns_add_asset (whole realistic '
    'equipment in one call) or uns_replace_subtree (a site at a time), then run policy_check and '
    'fix what it reports. topics_preview shows the topics the model will actually publish. '
    'sim_control starts the OPC-UA server, the bridge and the plants.\n\n'
    'Every write is snapshotted: uns_snapshots lists them and uns_revert undoes.'
)


class McpDispatcher:
    """Owns the tool registry and answers MCP requests against one backend."""

    def __init__(self, backend: Backend, *, allow_writes: bool = True,
                 server_name: str = 'uns-design-studio', server_version: str = '2.5.0'):
        self.backend = backend
        self.allow_writes = allow_writes
        self.server_name = server_name
        self.server_version = server_version

    # ── public API ──────────────────────────────────────────────────────────

    async def handle(self, message: Any) -> Any:
        """Dispatch one JSON-RPC message (or batch). Returns None for notifications."""
        if isinstance(message, list):
            replies = [r for r in [await self.handle(m) for m in message] if r is not None]
            return replies or None
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, 'request must be a JSON-RPC object')

        method = message.get('method')
        req_id = message.get('id')
        is_notification = 'id' not in message

        try:
            result = await self._route(method, message.get('params') or {})
        except _RpcError as exc:
            return None if is_notification else _error(req_id, exc.code, str(exc))
        except Exception as exc:  # never let a bug take the connection down
            log.exception('mcp: %s failed', method)
            return None if is_notification else _error(req_id, INTERNAL_ERROR, str(exc))

        if is_notification:
            return None
        return {'jsonrpc': '2.0', 'id': req_id, 'result': result}

    def tool_descriptors(self) -> list[dict]:
        return [
            {'name': t.name, 'description': t.description, 'inputSchema': t.schema,
             'annotations': {'readOnlyHint': not t.writes, 'destructiveHint': t.writes}}
            for t in tools_mod.registry(include_writes=self.allow_writes)
        ]

    # ── routing ─────────────────────────────────────────────────────────────

    async def _route(self, method: str | None, params: dict) -> Any:
        if method == 'initialize':
            return self._initialize(params)
        if method == 'ping':
            return {}
        if method in ('notifications/initialized', 'notifications/cancelled'):
            return {}
        if method == 'tools/list':
            return {'tools': self.tool_descriptors()}
        if method == 'tools/call':
            return await self._call_tool(params)
        # Declared in capabilities as absent, but well-behaved clients still
        # probe for them; an empty list beats a method-not-found round trip.
        if method == 'resources/list':
            return {'resources': []}
        if method == 'resources/templates/list':
            return {'resourceTemplates': []}
        if method == 'prompts/list':
            return {'prompts': []}
        raise _RpcError(METHOD_NOT_FOUND, f'unknown method: {method}')

    def _initialize(self, params: dict) -> dict:
        asked = params.get('protocolVersion')
        version = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return {
            'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': self.server_name, 'version': self.server_version},
            'instructions': SERVER_INSTRUCTIONS,
        }

    async def _call_tool(self, params: dict) -> dict:
        name = params.get('name')
        if not name:
            raise _RpcError(INVALID_PARAMS, 'tools/call needs a name')
        args = params.get('arguments')
        if args is not None and not isinstance(args, dict):
            raise _RpcError(INVALID_PARAMS, 'arguments must be an object')
        try:
            result = await tools_mod.call(self.backend, name, args or {},
                                          allow_writes=self.allow_writes)
        except tools_mod.ToolError as exc:
            # A tool-level failure is a successful RPC with isError — the model
            # is expected to read it and correct itself, not to see a transport
            # fault it cannot reason about.
            return {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        return {
            'content': [{'type': 'text', 'text': _render(result)}],
            'structuredContent': result if isinstance(result, dict) else {'result': result},
            'isError': False,
        }


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _error(req_id: Any, code: int, message: str) -> dict:
    return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message}}


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)

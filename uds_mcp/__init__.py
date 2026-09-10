"""UDS as an MCP server — the same tools the built-in agent uses, for outside agents.

Three ways in, one dispatcher (:mod:`uds_mcp.protocol`):

* ``/mcp`` on the dashboard itself (:mod:`uds_mcp.http`) — streamable HTTP,
  bearer-gated, tools run in-process so a write lands immediately.
* ``python -m uds_mcp stdio`` — for a desktop agent (Claude Desktop, Claude
  Code) on the same machine; no token, the OS process boundary is the gate.
* ``python -m uds_mcp http`` — its own process/container in front of a remote
  UDS, matching the family's kg-mcp deployment shape.

The last two reach UDS over its REST API, so they can sit anywhere; the first
skips the hop entirely.
"""

from uds_mcp.protocol import McpDispatcher, PROTOCOL_VERSION

__all__ = ['McpDispatcher', 'PROTOCOL_VERSION']

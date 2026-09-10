"""UDS agent — the built-in modelling assistant and its shared tool surface.

Three consumers share one tool registry (``uds_agent.tools``):

* the built-in chat agent (``uds_agent.loop``), driven from the /agent page,
* the in-process MCP server mounted at ``/mcp`` (``uds_mcp.http``),
* the standalone MCP entrypoints — stdio and its own HTTP process
  (``python -m uds_mcp``), which talk to a UDS over its REST API.

Nothing here is imported at app boot unless the agent blueprint is registered,
so a UDS without an LLM key configured behaves exactly as it did before.
"""

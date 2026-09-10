"""stdio MCP transport — newline-delimited JSON-RPC on stdin/stdout.

What Claude Desktop, Claude Code and most local agent runners speak. There is
no token: the caller already owns the process. Anything this server prints for
humans goes to stderr, because stdout *is* the protocol channel.

stdin is read on a worker thread rather than through
``loop.connect_read_pipe``. The asyncio pipe route only works for pipes on
Unix — on Windows' Proactor loop it raises or, worse, silently never delivers a
line, which is exactly where a desktop agent would be running this. A blocking
``readline`` in a thread behaves identically on every platform.
"""

from __future__ import annotations

import asyncio
import json
import sys

from uds_mcp.protocol import PARSE_ERROR, McpDispatcher


async def serve(dispatcher: McpDispatcher, *, stdin=None, stdout=None) -> None:
    loop = asyncio.get_running_loop()
    src = stdin or sys.stdin
    dst = stdout or sys.stdout

    # MCP stdio is UTF-8 by spec, but Python on Windows gives you the console
    # code page (cp1252), which cannot encode so much as an arrow in a tool
    # description — the first tools/list would die mid-write. Force it.
    for stream in (src, dst):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            try:
                reconfigure(encoding='utf-8', errors='replace')
            except (ValueError, OSError):
                pass  # already-wrapped or non-reconfigurable stream: leave it

    while True:
        line = await loop.run_in_executor(None, src.readline)
        if not line:
            return  # stdin closed — the client went away
        text = line.strip() if isinstance(line, str) else line.decode('utf-8', 'replace').strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError as exc:
            _write(dst, {'jsonrpc': '2.0', 'id': None,
                         'error': {'code': PARSE_ERROR, 'message': f'invalid JSON: {exc}'}})
            continue
        reply = await dispatcher.handle(message)
        if reply is not None:
            _write(dst, reply)


def _write(dst, payload) -> None:
    dst.write(json.dumps(payload, ensure_ascii=False, default=str) + '\n')
    dst.flush()

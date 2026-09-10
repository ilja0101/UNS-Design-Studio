"""Standalone MCP entrypoints — ``python -m uds_mcp stdio|http``.

Both talk to a UDS over its REST API (``--uds``), so this process can live on a
laptop next to Claude Desktop or in its own container next to a deployed UDS.
That is the trust-boundary split kg-mcp uses: no session cookie, a bearer token
of its own, and nothing of the dashboard imported into the process.

    # Claude Desktop / Claude Code, against a local UDS
    python -m uds_mcp stdio --uds http://localhost:8050

    # Its own container in front of a deployed UDS
    UDS_MCP_TOKEN=... python -m uds_mcp http --uds http://uds:8050 --listen 0.0.0.0:8060
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from uds_agent.backend import HttpBackend
from uds_mcp.protocol import PROTOCOL_VERSION, McpDispatcher


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog='python -m uds_mcp', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('transport', choices=['stdio', 'http'], nargs='?', default='stdio')
    ap.add_argument('--uds', default=os.environ.get('UDS_URL', 'http://localhost:8050'),
                    help='base URL of the UNS Design Studio to drive')
    ap.add_argument('--uds-token', default=os.environ.get('UDS_API_TOKEN', ''),
                    help='bearer token for the UDS, if it is behind one')
    ap.add_argument('--uds-user', default=os.environ.get('UDS_ADMIN_USERNAME', ''),
                    help='HTTP-Basic user, when the UDS has UDS_ADMIN_USERNAME set')
    ap.add_argument('--uds-password', default=os.environ.get('UDS_ADMIN_PASSWORD', ''))
    ap.add_argument('--listen', default=os.environ.get('UDS_MCP_LISTEN', '127.0.0.1:8060'),
                    help='http transport only: host:port to serve /mcp on')
    ap.add_argument('--read-only', action='store_true',
                    help='hide every write tool from this connection')
    return ap.parse_args(argv)


def _backend(args: argparse.Namespace) -> HttpBackend:
    basic = (args.uds_user, args.uds_password) if args.uds_user and args.uds_password else None
    return HttpBackend(args.uds, token=args.uds_token, basic=basic)


async def _run_stdio(args: argparse.Namespace) -> int:
    from uds_mcp.stdio import serve
    backend = _backend(args)
    print(f'uds-mcp: stdio transport, driving {args.uds} '
          f'({"read-only" if args.read_only else "read-write"})', file=sys.stderr, flush=True)
    try:
        await serve(McpDispatcher(backend, allow_writes=not args.read_only))
    finally:
        await backend.aclose()
    return 0


async def _run_http(args: argparse.Namespace) -> int:
    token = os.environ.get('UDS_MCP_TOKEN', '')
    if not token:
        print('uds-mcp: UDS_MCP_TOKEN is required for the http transport — it is the bearer '
              'token callers must send.', file=sys.stderr)
        return 2

    import hmac
    from quart import Quart, Response, jsonify, request

    backend = _backend(args)
    dispatcher = McpDispatcher(backend, allow_writes=not args.read_only)
    app = Quart('uds-mcp')

    @app.route('/healthz')
    async def healthz():
        return 'ok'

    @app.route('/', methods=['GET'])
    async def root():
        return jsonify({'status': 'ok', 'service': 'uds-mcp', 'uds': args.uds,
                        'protocolVersion': PROTOCOL_VERSION})

    @app.route('/mcp', methods=['POST'])
    @app.route('/mcp/', methods=['POST'])
    async def mcp():
        header = request.headers.get('Authorization', '')
        scheme, _, value = header.partition(' ')
        if scheme.lower() != 'bearer' or not hmac.compare_digest(value.strip(), token):
            resp = jsonify({'error': 'missing or invalid bearer token'})
            resp.status_code = 401
            resp.headers['WWW-Authenticate'] = 'Bearer realm="uds-mcp"'
            return resp
        reply = await dispatcher.handle(await request.get_json(force=True, silent=True) or {})
        if reply is None:
            return Response('', status=202)
        resp = jsonify(reply)
        resp.headers['MCP-Protocol-Version'] = PROTOCOL_VERSION
        return resp

    host, _, port = args.listen.rpartition(':')
    print(f'uds-mcp: http transport on {args.listen} (/mcp bearer-gated), driving {args.uds}',
          file=sys.stderr, flush=True)
    try:
        await app.run_task(host=host or '127.0.0.1', port=int(port or 8060))
    finally:
        await backend.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv if argv is not None else sys.argv[1:])
    runner = _run_stdio if args.transport == 'stdio' else _run_http
    try:
        return asyncio.run(runner(args))
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())

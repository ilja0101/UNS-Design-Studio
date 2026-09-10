"""How a tool reaches a UDS — in-process, or over the wire.

Every tool in :mod:`uds_agent.tools` is written once, against the app's own
REST API, and a ``Backend`` decides how that call is delivered:

* :class:`DirectBackend` dispatches through Quart's test client inside the
  running dashboard process. Same routes, same handlers, same side effects —
  a UNS save still restarts the OPC server and the bridge, because it *is* the
  ``POST /api/uns`` handler. Nothing is reimplemented, so nothing can drift.
* :class:`HttpBackend` speaks to a remote UDS over HTTP, which is what the
  standalone ``python -m uds_mcp`` entrypoints use (stdio for a desktop agent,
  or its own container next to a UDS).

The in-process path still has to satisfy the app's optional HTTP-Basic gate.
Rather than stashing the operator's password, DirectBackend presents a
per-process random header (:data:`INTERNAL_TOKEN`) that ``app.py`` accepts —
it never leaves the process, and it is only reachable after the caller has
already passed the MCP bearer gate or the SPA's own session.
"""

from __future__ import annotations

import secrets
from typing import Any, Protocol

# Regenerated every boot; there is no persisted value to leak or reuse.
INTERNAL_HEADER = 'X-UDS-Internal'
INTERNAL_TOKEN = secrets.token_urlsafe(32)


class BackendError(RuntimeError):
    """A UDS API call that came back non-2xx, carrying the status for the tool."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Backend(Protocol):
    async def call(self, method: str, path: str, body: Any = None,
                   params: dict | None = None) -> Any: ...


class DirectBackend:
    """In-process dispatch against the live Quart app."""

    def __init__(self, app=None):
        self._app = app

    def _resolve(self):
        if self._app is None:
            import app as app_module  # deferred: importing app at module scope would cycle
            self._app = app_module.app
        return self._app

    async def call(self, method: str, path: str, body: Any = None,
                   params: dict | None = None) -> Any:
        client = self._resolve().test_client()
        headers = {INTERNAL_HEADER: INTERNAL_TOKEN}
        kwargs: dict[str, Any] = {'headers': headers}
        if params:
            kwargs['query_string'] = params
        if body is not None:
            kwargs['json'] = body
        response = await client.open(path, method=method.upper(), **kwargs)
        payload = await _decode(response)
        if response.status_code >= 400:
            raise BackendError(response.status_code, _error_text(payload, response.status_code))
        return payload


class HttpBackend:
    """Remote dispatch over HTTP, for the standalone MCP entrypoints."""

    def __init__(self, base_url: str, *, token: str = '', basic: tuple[str, str] | None = None,
                 timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self._token = token
        self._basic = basic
        self._timeout = timeout
        self._client = None

    async def _http(self):
        if self._client is None:
            import httpx
            auth = httpx.BasicAuth(*self._basic) if self._basic else None
            headers = {'Authorization': f'Bearer {self._token}'} if self._token else {}
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self._timeout, headers=headers, auth=auth,
            )
        return self._client

    async def call(self, method: str, path: str, body: Any = None,
                   params: dict | None = None) -> Any:
        client = await self._http()
        response = await client.request(method.upper(), path, json=body, params=params)
        try:
            payload = response.json()
        except Exception:
            payload = {'text': response.text}
        if response.status_code >= 400:
            raise BackendError(response.status_code, _error_text(payload, response.status_code))
        return payload

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def _decode(response) -> Any:
    try:
        return await response.get_json()
    except Exception:
        try:
            return {'text': (await response.get_data()).decode('utf-8', 'replace')}
        except Exception:
            return None


def _error_text(payload: Any, status: int) -> str:
    if isinstance(payload, dict):
        for key in ('error', 'msg', 'message', 'text'):
            if payload.get(key):
                return str(payload[key])
    return f'UDS API returned HTTP {status}'

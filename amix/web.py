"""Quart glue for governed mode: the AMIX SSO route, a signed session cookie, the
same-origin base-path injection, and the governed auth gate / settings guards
(amix-standards/APP-GOVERNANCE.md §2 + §4, SSO.md).

Everything here is installed ONLY when governed — ``install_http_glue`` is called
from app.py behind ``governance.governed()``. Standalone serves the SPA verbatim,
has no ``/auth/amix`` route, no session cookie, and no base injection, so behaviour
is byte-for-byte unchanged.

## Design Studio specifics vs. the FastAPI template

- **No cookie session existed** — the app is HTTP-Basic only. Governed mode adds
  its *own* session as a small stdlib-HMAC-signed cookie (``uds_session``), scoped
  to the portal proxy prefix via ``Path`` so multiple governed apps under one
  origin don't collide. No new dependency (mirrors ssoverify's stdlib stance).
- **The SPA is mounted at ``/app`` with assets under ``/spa/``** (not at ``/``), so
  the injected ``<base href>`` points at ``{prefix}spa/`` (where the relative Vite
  assets live) while ``window.__AMIX_BASE__`` carries the app prefix ``{prefix}``
  for the router basename (``{prefix}app``) and API calls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Callable, Optional

from quart import Quart, Response, redirect, request

from amix.governance import Governance, amix_role_to_role
from amix.ssoverify import VerifyError, verify

log = logging.getLogger(__name__)

SESSION_COOKIE = "uds_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12h — long enough for a working session

_BASE_TAG_RE = re.compile(rb"<base\b[^>]*>", re.IGNORECASE)


# ── session cookie (stdlib HMAC-signed, like ssoverify — no new dependency) ──


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(seg: str) -> bytes:
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def sign_session(secret: bytes, username: str, role: str, now: float, ttl: int = SESSION_TTL_SECONDS) -> str:
    """Mint a compact signed session token: b64url(payload).b64url(hmac)."""
    payload = {"sub": username, "role": role, "exp": int(now) + ttl}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session(secret: bytes, token: str, now: float) -> Optional[tuple[str, str]]:
    """Return (username, role) for a valid unexpired session cookie, else None."""
    if not token or token.count(".") != 1:
        return None
    body, sig = token.split(".")
    want = _b64url(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if now >= int(payload.get("exp", 0)):
        return None
    return str(payload.get("sub", "")), str(payload.get("role", "viewer"))


# ── base-path injection (§4) ──────────────────────────────────────────────


def inject_amix_base(html: bytes, base: str) -> bytes:
    """Rewrite the SPA ``index.html`` for same-origin serving under a portal prefix.

    ``base`` is the ``X-Amix-Base`` header (e.g. ``/connect/design-studio/``). The
    SPA shell is served at ``/app`` and its Vite assets (built with ``base:"./"``)
    live under ``/spa/``; the source index carries ``<base href="/spa/">`` so the
    relative assets resolve at any ``/app`` depth standalone. Here we repoint that
    base at ``{prefix}spa/`` so the proxy-fronted app resolves the same assets, and
    inject a ``window.__AMIX_BASE__ = "{prefix}"`` global the SPA reads for its
    router basename and API calls. The header is a same-origin path from the
    trusted proxy; it is JSON-encoded for the script literal and percent-escaped
    for the attribute so a malformed header can't break out of either context.
    """
    if not base.endswith("/"):
        base += "/"
    base_href = base + "spa/"
    attr = base_href.replace('"', "%22")
    js_lit = json.dumps(base)
    inject = f'<base href="{attr}"><script>window.__AMIX_BASE__={js_lit}</script>'.encode()

    if _BASE_TAG_RE.search(html):
        return _BASE_TAG_RE.sub(inject, html, count=1)
    return html.replace(b"<head>", b"<head>" + inject, 1)


# ── settings governance helpers (§3) ──────────────────────────────────────


def governance_block(gov: Governance) -> dict:
    """The ``governance`` object surfaced in the status/settings endpoint."""
    return {
        "mode": gov.strategy if gov.governed() else "standalone",
        "managed_fields": gov.managed_fields(),
    }


# Bridge keys the platform owns in governed mode (the concrete app-side spelling
# of Governance.managed_fields: nats.url → broker_host/broker_port, subject_prefix
# → topic_prefix).
MANAGED_BRIDGE_KEYS = ("broker_host", "broker_port", "topic_prefix")


def reject_managed_bridge_change(gov: Governance, incoming: dict, current: dict) -> Optional[str]:
    """Return an error string if ``incoming`` would change a platform-managed
    bridge field to a *different* value in governed mode, else None. A save that
    merely re-sends the current managed value (or omits it) is allowed."""
    if not gov.governed():
        return None
    for k in MANAGED_BRIDGE_KEYS:
        if k in incoming and incoming[k] != current.get(k):
            return f"{k} is managed by AMIX and cannot be changed from the app in governed mode"
    return None


# ── HTTP wiring (governed-only) ────────────────────────────────────────────


def install_http_glue(
    app: Quart,
    gov: Governance,
    *,
    basic_configured: Callable[[], bool],
    basic_ok: Callable[[], bool],
) -> Callable[[], Optional[tuple[str, str]]]:
    """Register the governed SSO route, the base-injection hook and the API auth
    gate. Returns ``current_user()`` — a callable giving (username, role) for the
    current request's AMIX session, or None. Call ONLY when ``gov.governed()``.

    ``basic_configured`` reports whether the app's own HTTP-Basic credential is
    set; ``basic_ok`` reports whether the current request satisfies it — both are
    passed in so this module stays decoupled from app.py internals.
    """
    secret = gov.sso_secret.encode("utf-8")

    def current_user() -> Optional[tuple[str, str]]:
        return verify_session(secret, request.cookies.get(SESSION_COOKIE, ""), time.time())

    # 1. SSO handoff: verify the portal's short-lived HS256 token, start our own
    #    session, scope the cookie to the proxy prefix, redirect to strip the token.
    @app.route("/auth/amix")
    async def amix_login():  # noqa: ANN202
        token = request.args.get("token", "")
        try:
            claims = verify(secret, token, time.time())
        except VerifyError as exc:
            return Response(f"amix sso: {exc}", status=401)

        role = amix_role_to_role(claims.roles)
        base = request.headers.get("X-Amix-Base") or "/"
        cookie = sign_session(secret, claims.sub, role, time.time())
        resp = redirect(base, code=302)
        resp.set_cookie(
            SESSION_COOKIE,
            cookie,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="Lax",
            path=base,
        )
        log.info("amix sso: started session for %r (role %s, cookie path %s)", claims.sub, role, base)
        return resp

    # 2. Same-origin base injection: the SPA shell (served at /app*) gets the
    #    <base>/__AMIX_BASE__ rewrite when the portal proxy sets X-Amix-Base.
    @app.after_request
    async def _amix_inject_base(resp: Response):  # noqa: ANN202
        base = request.headers.get("X-Amix-Base")
        if not base:
            return resp
        p = request.path
        if not (p == "/app" or p.startswith("/app/")):
            return resp
        ctype = (resp.content_type or "").lower()
        if "text/html" not in ctype:
            return resp
        body = await resp.get_data()
        resp.set_data(inject_amix_base(body, base))
        return resp

    # 3. Governed auth gate: /api/* requires an AMIX session (or the app's own
    #    Basic credential when one is configured). The SPA shell + assets stay
    #    open so the login bounce and its assets load before the cookie exists.
    @app.before_request
    async def _amix_api_gate():  # noqa: ANN202
        p = request.path
        if not p.startswith("/api/"):
            return None
        if current_user() is not None:
            return None
        # Basic hook (registered earlier) has already vetted Basic when it is
        # configured; if it is, allow — otherwise an AMIX session is required.
        if basic_configured() and basic_ok():
            return None
        if basic_configured():
            return None  # basic hook would have 401'd already; be permissive here
        return Response("Unauthenticated (AMIX SSO required)", 401)

    return current_user

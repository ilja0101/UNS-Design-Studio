"""Governed HTTP behaviour of the AMIX Quart glue (amix/web.py).

These build a throwaway governed Quart app and mount the glue on it — mirroring
how the FastAPI template tests use create_app — so the SSO route, base-path
injection, the session cookie / API auth gate, and the managed-field guard are all
testable offline (no live broker). The end-to-end $PLAT announce + KV convergence
are proven separately against a real NATS container (see the run evidence).

Standalone inertness is proven by the fact that install_http_glue is never called
when not governed (app.py gates it on _GOV.governed()), plus governance_block()
and the pure loader tests in test_amix_sso.py.
"""

from __future__ import annotations

import time

import pytest
from quart import Quart, Response, jsonify, request

from amix import web as amix_web
from amix.governance import Governance
from tests.test_amix_sso import mint

SECRET = "shared-amix-secret"

_SPA_INDEX = (
    b'<!doctype html><html><head><meta charset="utf-8">'
    b'<base href="/spa/"><title>UNS Design Studio</title>'
    b'<script type="module" src="./assets/index-abc.js"></script>'
    b"</head><body><div id=root></div></body></html>"
)


def _governed_gov(secret: str = SECRET) -> Governance:
    return Governance(
        strategy="amix",
        app_id="design-studio",
        app_url="https://amix-ot/connect/design-studio/",
        nats_url="nats://127.0.0.1:59999",  # unreachable — not connected in these tests
        sso_secret=secret,
    )


def _make_app(gov: Governance) -> Quart:
    app = Quart(__name__)
    amix_web.install_http_glue(
        app, gov, basic_configured=lambda: False, basic_ok=lambda: False
    )

    @app.route("/app")
    async def shell():  # noqa: ANN202
        return Response(_SPA_INDEX, content_type="text/html; charset=utf-8")

    @app.route("/api/ping")
    async def ping():  # noqa: ANN202
        return jsonify({"pong": True})

    @app.route("/api/bridge/config", methods=["POST"])
    async def bridge_save():  # noqa: ANN202
        data = await request.get_json() or {}
        current = {"broker_host": "amix-broker", "broker_port": 4222, "topic_prefix": "plant"}
        err = amix_web.reject_managed_bridge_change(gov, data, current)
        if err:
            return jsonify({"ok": False, "error": err}), 409
        return jsonify({"ok": True})

    return app


# ── governance block ────────────────────────────────────────────────────────


def test_governance_block_standalone():
    blk = amix_web.governance_block(Governance())
    assert blk == {"mode": "standalone", "managed_fields": []}


def test_governance_block_governed():
    blk = amix_web.governance_block(_governed_gov())
    assert blk["mode"] == "amix"
    assert "nats.url" in blk["managed_fields"]


# ── base-path injection (§4) ────────────────────────────────────────────────


def test_inject_pure_function():
    out = amix_web.inject_amix_base(_SPA_INDEX, "/connect/design-studio/").decode()
    assert 'window.__AMIX_BASE__="/connect/design-studio/"' in out
    # SPA assets live under /spa/, so the base is repointed there.
    assert '<base href="/connect/design-studio/spa/">' in out
    # exactly one <base> tag (the source /spa/ one is replaced, not duplicated)
    assert out.count("<base") == 1


async def test_index_injected_with_header():
    app = _make_app(_governed_gov())
    client = app.test_client()
    r = await client.get("/app", headers={"X-Amix-Base": "/connect/design-studio/"})
    body = await r.get_data()
    text = body.decode()
    assert 'window.__AMIX_BASE__="/connect/design-studio/"' in text
    assert '<base href="/connect/design-studio/spa/">' in text


async def test_index_verbatim_without_header():
    app = _make_app(_governed_gov())
    client = app.test_client()
    r = await client.get("/app")
    text = (await r.get_data()).decode()
    assert "__AMIX_BASE__" not in text
    assert '<base href="/spa/">' in text  # untouched source base


# ── SSO handoff (§2) ────────────────────────────────────────────────────────


async def test_sso_bad_token_401():
    app = _make_app(_governed_gov())
    client = app.test_client()
    r = await client.get("/auth/amix?token=bad")
    assert r.status_code == 401


async def test_sso_handoff_sets_scoped_cookie():
    app = _make_app(_governed_gov())
    client = app.test_client()
    tok = mint(SECRET.encode(), sub="carol", roles=["ot"])
    r = await client.get(
        "/auth/amix",
        query_string={"token": tok},
        headers={"X-Amix-Base": "/connect/design-studio/"},
    )
    assert r.status_code == 302
    assert r.headers["Location"] == "/connect/design-studio/"
    set_cookie = r.headers.get("Set-Cookie", "")
    assert "uds_session=" in set_cookie
    assert "Path=/connect/design-studio/" in set_cookie


async def test_sso_session_authorizes_protected_api():
    app = _make_app(_governed_gov())
    client = app.test_client()
    # No cookie yet → /api/* is refused.
    assert (await client.get("/api/ping")).status_code == 401
    # Hand off with default base ("/") so the cookie is jar-wide for this test.
    tok = mint(SECRET.encode(), sub="dave", roles=["ot"])  # ot → admin
    r = await client.get("/auth/amix", query_string={"token": tok})
    assert r.status_code == 302
    # The cookie is now in the client jar → the protected route passes.
    ok = await client.get("/api/ping")
    assert ok.status_code == 200
    assert (await ok.get_json()) == {"pong": True}


# ── managed-field guard (§3) ────────────────────────────────────────────────


async def _login(client) -> None:
    """SSO handoff (default base → jar-wide cookie) so /api/* is reachable."""
    tok = mint(SECRET.encode(), sub="op", roles=["ot"])
    r = await client.get("/auth/amix", query_string={"token": tok})
    assert r.status_code == 302


async def test_managed_field_change_refused():
    app = _make_app(_governed_gov())
    client = app.test_client()
    await _login(client)
    r = await client.post("/api/bridge/config", json={"broker_host": "evil.example"})
    assert r.status_code == 409
    body = await r.get_json()
    assert "broker_host" in body["error"]


async def test_unmanaged_field_change_allowed():
    app = _make_app(_governed_gov())
    client = app.test_client()
    await _login(client)
    # interval is not platform-owned → still editable in governed mode.
    r = await client.post("/api/bridge/config", json={"interval": 5})
    assert r.status_code == 200
    assert (await r.get_json())["ok"] is True


async def test_managed_field_same_value_allowed():
    app = _make_app(_governed_gov())
    client = app.test_client()
    await _login(client)
    # Re-sending the current managed value (no change) is fine.
    r = await client.post("/api/bridge/config", json={"broker_port": 4222})
    assert r.status_code == 200


# ── session cookie signing round-trip ───────────────────────────────────────


def test_session_sign_verify_roundtrip():
    secret = SECRET.encode()
    tok = amix_web.sign_session(secret, "erin", "admin", time.time())
    assert amix_web.verify_session(secret, tok, time.time()) == ("erin", "admin")
    # wrong secret / expiry / tamper all reject.
    assert amix_web.verify_session(b"nope", tok, time.time()) is None
    assert amix_web.verify_session(secret, tok, time.time() + amix_web.SESSION_TTL_SECONDS + 1) is None
    assert amix_web.verify_session(secret, "garbage", time.time()) is None

"""Unit tests for the stdlib-only AMIX SSO verify + the governance loader.

The mint helper here reproduces the portal's wire contract (amix-standards/SSO.md)
exactly, so these tests double as a conformance check that ssoverify.verify
interoperates with a portal-minted HS256 token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from amix.governance import (
    Governance,
    GovernanceError,
    amix_role_to_role,
    load_governance,
)
from amix.ssoverify import VerifyError, verify


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint(secret: bytes, *, sub="alice", roles=("ot",), aud="design-studio", exp_in=120) -> str:
    """Mint an HS256 token per the exact wire contract the portal uses."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": sub,
        "roles": list(roles),
        "aud": aud,
        "iss": "amix-portal",
        "iat": now,
        "exp": now + exp_in,
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(secret, f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


SECRET = b"shared-amix-secret"


def test_verify_accepts_valid_token():
    tok = mint(SECRET, sub="bob", roles=["all"])
    claims = verify(SECRET, tok, time.time())
    assert claims.sub == "bob"
    assert claims.roles == ["all"]
    assert claims.aud == "design-studio"
    assert claims.iss == "amix-portal"


def test_verify_rejects_bad_signature():
    tok = mint(SECRET)
    with pytest.raises(VerifyError):
        verify(b"wrong-secret", tok, time.time())


def test_verify_rejects_expired():
    tok = mint(SECRET, exp_in=-1)
    with pytest.raises(VerifyError, match="expired"):
        verify(SECRET, tok, time.time())


def test_verify_rejects_tampered_payload():
    tok = mint(SECRET)
    h, p, s = tok.split(".")
    forged = json.dumps({"sub": "attacker", "roles": ["ot"], "exp": int(time.time()) + 999}).encode()
    tampered = f"{h}.{_b64url(forged)}.{s}"
    with pytest.raises(VerifyError):
        verify(SECRET, tampered, time.time())


def test_verify_rejects_wrong_alg():
    # alg=none downgrade attempt must be refused even if the signature is empty.
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": "x", "exp": int(time.time()) + 60}).encode())
    with pytest.raises(VerifyError, match="alg"):
        verify(SECRET, f"{header}.{payload}.", time.time())


def test_verify_rejects_malformed():
    with pytest.raises(VerifyError, match="malformed"):
        verify(SECRET, "not-a-jwt", time.time())


def test_role_mapping():
    assert amix_role_to_role(["ot"]) == "admin"
    assert amix_role_to_role(["all"]) == "admin"
    assert amix_role_to_role(["enterprise"]) == "viewer"
    assert amix_role_to_role(["something-unknown"]) == "viewer"
    assert amix_role_to_role(["enterprise", "ot"]) == "admin"  # highest wins
    assert amix_role_to_role([]) == "viewer"


def test_governance_standalone_by_default():
    g = load_governance({})
    assert g == Governance()
    assert not g.governed()
    assert g.managed_fields() == []


def test_governance_amix_requires_identity():
    with pytest.raises(GovernanceError, match="AMIX_APP_ID"):
        load_governance({"CONTROL_STRATEGY": "amix"})


def test_governance_amix_full():
    g = load_governance(
        {
            "CONTROL_STRATEGY": "amix",
            "AMIX_APP_ID": "design-studio",
            "AMIX_NATS_URL": "nats://leaf:4222",
            "AMIX_SSO_SECRET": "s",
            "AMIX_APP_URL": "https://amix-ot/connect/design-studio/",
        }
    )
    assert g.governed()
    assert g.app_id == "design-studio"
    assert g.nats_url == "nats://leaf:4222"
    assert "nats.url" in g.managed_fields()
    assert "subject_prefix" in g.managed_fields()


def test_governance_prefix_wins_over_bare():
    g = load_governance(
        {
            "UDS_CONTROL_STRATEGY": "amix",
            "UDS_AMIX_APP_ID": "prefixed",
            "AMIX_APP_ID": "bare",
            "AMIX_NATS_URL": "nats://leaf:4222",
            "AMIX_SSO_SECRET": "s",
        }
    )
    assert g.app_id == "prefixed"  # UDS_ prefix resolves first

"""Verify-only side of the AMIX SSO handoff (amix-standards/SSO.md).

The portal mints a short-lived HS256 JWT; a governed app copies this in, verifies
the token with the shared secret, and starts its OWN session. Apps never mint —
only verify — so there is no signing code here (the RS256 hardening path in
SSO.md §4 makes that asymmetry enforced by key type rather than convention).

This is the Python port of `amix-standards/snippets/ssoverify.go`. It uses the
**standard library only** (`hmac`, `hashlib`, `base64`, `json`, `time`) — no
PyJWT — so it drops into any Python app without a new dependency and its
verification is byte-compatible with amix-portal/internal/sso.Signer.Mint:

  signature = base64url_unpadded( HMAC-SHA256( header_b64 + "." + payload_b64,
                                               key = AMIX_SSO_SECRET (raw UTF-8) ) )

with header ``{"alg":"HS256","typ":"JWT"}`` and base64url unpadded throughout.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field


class VerifyError(Exception):
    """Raised when a token is malformed, mis-signed, or expired."""


@dataclass(frozen=True)
class Claims:
    """The AMIX SSO token payload (the subset an app needs to trust)."""

    sub: str  # the AMIX user
    roles: list[str] = field(default_factory=list)  # portal role(s): ot|enterprise|all
    aud: str = ""  # target app id
    iss: str = ""  # always "amix-portal"
    iat: int = 0
    exp: int = 0


def _b64url_decode(seg: str) -> bytes:
    """Decode an unpadded base64url segment (JWT uses no padding)."""
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def verify(secret: bytes, token: str, now: float) -> Claims:
    """Check the HS256 signature then the expiry, returning the trusted claims.

    ``now`` (unix seconds, float) is passed in so it is unit-testable. This
    mirrors the portal's ``sso.Signer.Verify`` exactly, so a token minted there
    validates here. Raises :class:`VerifyError` on any failure.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise VerifyError("malformed token")
    header_b64, payload_b64, sig_b64 = parts

    # alg must be HS256 — never trust a token that asks for "none" or another alg.
    try:
        header = json.loads(_b64url_decode(header_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise VerifyError("bad header encoding") from exc
    if header.get("alg") != "HS256":
        raise VerifyError("unexpected alg (want HS256)")

    signing_input = (header_b64 + "." + payload_b64).encode("ascii")
    mac = hmac.new(secret, signing_input, hashlib.sha256).digest()
    want = base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")
    if not hmac.compare_digest(sig_b64, want):
        raise VerifyError("bad signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise VerifyError("bad payload") from exc

    exp = int(payload.get("exp", 0))
    if now >= exp:
        raise VerifyError("token expired")

    roles = payload.get("roles") or []
    if not isinstance(roles, list):
        roles = []
    return Claims(
        sub=str(payload.get("sub", "")),
        roles=[str(r) for r in roles],
        aud=str(payload.get("aud", "")),
        iss=str(payload.get("iss", "")),
        iat=int(payload.get("iat", 0)),
        exp=exp,
    )

"""AMIX governance shim — the copy-in overlay that makes a standalone app governable.

Python port of the Go `amix-standards` contract (APP-GOVERNANCE.md / SSO.md),
copied from the UNS-Industrial-AI shim and adapted for this **Quart** app.
Everything here is dormant unless the app is in governed mode
(`Governance.governed()` is true, i.e. `CONTROL_STRATEGY=amix`). With no control
strategy set the app behaves byte-for-byte as it does standalone: no $PLAT
traffic, no `/auth/amix` route, no KV watch, no base-path injection, no session
cookie.

Pieces:
- ``ssoverify`` — stdlib-only HS256 JWT verify (no PyJWT), byte-compatible with
  the Go portal's `internal/sso.Signer.Mint`. (copied verbatim)
- ``governance`` — the env-only ``Governance`` control-strategy record (UDS_ prefix).
- ``announce`` — $PLAT announce + health beat over the governance NATS link.
- ``kvconfig`` — the ``amix_app_config`` JetStream KV watcher (live config).
- ``runtime`` — the ``AmixRuntime`` that owns the governance NATS connection and
  binds announce + KV-watch + the apply/converge callback together. Runs on the
  app's own asyncio loop (Quart is async ASGI — see runtime.py).
- ``web`` — the Quart glue: the ``/auth/amix`` SSO route, the signed session
  cookie, the same-origin ``index.html`` base-path injection, and the governed
  auth gate / settings guards.
"""

from __future__ import annotations

from amix.governance import Governance, GovernanceError, amix_role_to_role, load_governance
from amix.ssoverify import Claims, VerifyError, verify

__all__ = [
    "Governance",
    "GovernanceError",
    "amix_role_to_role",
    "load_governance",
    "Claims",
    "VerifyError",
    "verify",
]

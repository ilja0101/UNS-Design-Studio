"""The AMIX control-strategy record — env-only, standalone by default.

Python port of `UNS-Trendminer/internal/config/governance.go` (copied from the
UNS-Industrial-AI shim). It is populated from the environment ONLY (never a
config file) so a committed ``bridge_config.json`` / seeded setting can never flip
the app into governed mode. Its zero value is standalone: :meth:`Governance.governed`
is false and every governed code path stays dormant, so a governance-capable build
keeps driving a standalone deployment byte-for-byte unchanged.

Env layering mirrors Design Studio's own ``UDS_`` convention (see app.py's
``UDS_ADMIN_USERNAME`` / ``UDS_AUTOSTART`` etc.): each governance var is read as
``UDS_<NAME>`` first, then the bare ``<NAME>`` (the platform's un-prefixed
variables), so the same value resolves whichever convention the deployment uses.
"""

from __future__ import annotations

from dataclasses import dataclass

STRATEGY_STANDALONE = "standalone"
STRATEGY_AMIX = "amix"

# App env prefix (Design Studio uses UDS_). A governance var resolves
# UDS_<NAME> first, then the bare <NAME>.
PREFIX = "UDS_"


def _clean(value: str) -> str:
    """Strip a UTF-8 BOM + surrounding whitespace (deploy artifacts written as
    UTF-8-with-BOM glue a U+FEFF onto env values)."""
    return value.lstrip("﻿").strip()


class GovernanceError(Exception):
    """Raised when CONTROL_STRATEGY=amix but a required platform var is missing."""


@dataclass(frozen=True)
class Governance:
    """AMIX governance settings, sourced from the environment only.

    ``managed_fields`` are the settings keys AMIX owns in governed mode: the UI
    renders them read-only ("Managed by AMIX") and the settings save refuses to
    change them — they come from the platform (env bootstrap + the
    ``amix_app_config`` KV document). Empty in standalone mode.
    """

    strategy: str = STRATEGY_STANDALONE
    app_id: str = ""
    app_url: str = ""
    nats_url: str = ""
    nats_creds: str = ""
    sso_secret: str = ""

    def governed(self) -> bool:
        return self.strategy == STRATEGY_AMIX

    def managed_fields(self) -> list[str]:
        if not self.governed():
            return []
        # Design Studio's bridge publishes the simulated UNS to a broker. In
        # governed mode the platform owns *where* that goes: the UNS broker
        # (bridge broker_host/broker_port) and the browsable subject/topic scope
        # (bridge topic_prefix). Everything else — the UNS model, schemas, PLC
        # catalogs, viz — stays fully editable in the app.
        return ["nats.url", "subject_prefix"]


def load_governance(env: dict[str, str]) -> Governance:
    """Build a :class:`Governance` from ``env`` (usually ``os.environ``).

    Unset / ``standalone`` ⇒ the zero value (all governed paths dormant). In
    ``amix`` mode the required platform identity/secret must be present, else a
    :class:`GovernanceError` is raised so a half-configured governed deployment
    fails fast instead of booting silently ungoverned.
    """

    def get(name: str) -> str:
        return _clean(env.get(PREFIX + name, "") or env.get(name, ""))

    strat = get("CONTROL_STRATEGY").lower()
    if strat in ("", STRATEGY_STANDALONE):
        return Governance()
    if strat != STRATEGY_AMIX:
        raise GovernanceError(
            f"CONTROL_STRATEGY {strat!r} invalid (want {STRATEGY_STANDALONE!r} or {STRATEGY_AMIX!r})"
        )

    g = Governance(
        strategy=STRATEGY_AMIX,
        app_id=get("AMIX_APP_ID"),
        app_url=get("AMIX_APP_URL"),
        nats_url=get("AMIX_NATS_URL"),
        nats_creds=get("AMIX_NATS_CREDS"),
        sso_secret=get("AMIX_SSO_SECRET"),
    )
    if not g.app_id:
        raise GovernanceError("CONTROL_STRATEGY=amix requires AMIX_APP_ID (the $PLAT app id / KV key)")
    if not g.nats_url:
        raise GovernanceError("CONTROL_STRATEGY=amix requires AMIX_NATS_URL (the $PLAT control leaf)")
    if not g.sso_secret:
        raise GovernanceError("CONTROL_STRATEGY=amix requires AMIX_SSO_SECRET (shared SSO secret)")
    return g


# Role mapping (amix-standards/APP-GOVERNANCE.md §2). Highest wins: ot/all operate
# the plant → admin; enterprise is read-only → viewer; anything unrecognised falls
# to viewer (least privilege).
_ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}


def amix_role_to_role(roles: list[str]) -> str:
    best = "viewer"
    for r in roles:
        if r in ("ot", "all"):
            if _ROLE_RANK["admin"] > _ROLE_RANK[best]:
                best = "admin"
        # "enterprise" and unknown → viewer (no change)
    return best

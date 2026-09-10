"""Agent settings — LLM connection, behaviour, and the MCP bearer token.

Stored in ``agent_config.json`` next to the rest of UDS's runtime state, with
environment variables taking precedence so a container can be configured
without a writable settings file. The API key is never returned to the browser:
:func:`public_view` replaces it with a boolean, and a save that omits the key
leaves the stored one alone.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from json_persistence import load_json, save_json_atomic
from uds_agent.paths import settings_file


def _stored() -> dict[str, Any]:
    """The settings file as a dict, or empty -- silently when there is none.

    A fresh UDS has no agent_config.json until the MCP token is minted on the
    first read, so load_json's read-failure line printed twice on every first
    boot. Absent is the normal state, not a fault.
    """
    if not os.path.exists(settings_file()):
        return {}
    raw = load_json(settings_file(), None, label='agent_config.json')
    return dict(raw) if isinstance(raw, dict) else {}

DEFAULTS: dict[str, Any] = {
    # Which door to a model. 'direct' posts to an OpenAI-compatible endpoint
    # with a key this app holds. 'mesh' asks the Model Gateway over the app's
    # own backbone -- the way every appshell application on the platform does
    # by default, and the only way from the OT tier, where nothing has a route
    # to the gateway and nothing should hold a provider key.
    'route': 'direct',
    'meshProtocol': '',     # 'mqtt' (a Solace backbone) or 'nats'; seeded from the bridge
    'meshHost': '',
    'meshPort': 0,
    'meshUsername': '',
    'meshPassword': '',
    'meshCreds': '',
    'meshAppId': 'uns-design-studio',
    'meshModel': '',        # empty lets the gateway pick this app's default
    'meshPerson': '',
    'meshPurpose': '',
    'meshTimeout': 120,
    # Any OpenAI-compatible endpoint: Azure AI Foundry, OpenAI, OpenRouter,
    # Ollama (http://localhost:11434/v1), vLLM, LM Studio.
    'endpoint': '',
    'apiKey': '',
    'model': '',
    'maxTokens': 8000,
    'temperature': None,
    'reasoningEffort': '',
    # How many tool round-trips one chat turn may take before the loop stops
    # and asks the user. Modelling a site legitimately needs a lot of them.
    'maxSteps': 24,
    'allowWrites': True,
    'systemPromptExtra': '',
    # MCP server (the /mcp endpoint external agents connect to).
    'mcpEnabled': True,
    'mcpToken': '',
    'mcpAllowWrites': True,
}

_ENV = {
    'endpoint': 'UDS_LLM_ENDPOINT',
    'apiKey': 'UDS_LLM_API_KEY',
    'model': 'UDS_LLM_MODEL',
    'mcpToken': 'UDS_MCP_TOKEN',
}


def load() -> dict[str, Any]:
    raw = _stored()
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if k in DEFAULTS})
    for key, env in _ENV.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if os.environ.get('UDS_MCP_ENABLED'):
        cfg['mcpEnabled'] = os.environ['UDS_MCP_ENABLED'].strip().lower() not in ('0', 'false', 'no')
    if not cfg['mcpToken']:
        cfg['mcpToken'] = _ensure_token(cfg)
    _seed_mesh_from_bridge(cfg)
    return cfg


def _seed_mesh_from_bridge(cfg: dict[str, Any]) -> None:
    """Default the mesh door to the bridge's own broker.

    "Like the other apps" means over its own backbone, and this app already
    knows its backbone: it is what the bridge publishes to. Only fills what is
    empty, so a mesh host somebody set on purpose is never overwritten.
    """
    if cfg.get('meshHost'):
        return
    from uds_agent.paths import data_dir
    path = os.path.join(data_dir(), 'bridge_config.json')
    if not os.path.exists(path):
        return
    bridge = load_json(path, None, label='bridge_config.json')
    if not isinstance(bridge, dict):
        return
    proto = str(bridge.get('protocol') or '').lower()
    if proto not in ('mqtt', 'nats'):
        return
    cfg['meshProtocol'] = cfg.get('meshProtocol') or proto
    cfg['meshHost'] = str(bridge.get('broker_host') or '')
    cfg['meshPort'] = int(bridge.get('broker_port') or (4222 if proto == 'nats' else 1883))
    cfg['meshUsername'] = cfg.get('meshUsername') or str(bridge.get('username') or '')
    cfg['meshPassword'] = cfg.get('meshPassword') or str(bridge.get('password') or '')
    cfg['meshCreds'] = cfg.get('meshCreds') or str(bridge.get('creds') or '')


def _ensure_token(cfg: dict[str, Any]) -> str:
    """Mint the MCP bearer token on first use and persist it.

    A generated-per-boot token would break every saved MCP client config on
    restart, so it is written once and reused. Rotation is an explicit action
    from the Settings page (``mcpToken: ""`` on save).
    """
    token = secrets.token_urlsafe(32)
    stored = _stored()
    stored['mcpToken'] = token
    save_json_atomic(settings_file(), stored, ensure_ascii=False, label='agent_config.json')
    return token


def save(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a patch into the stored settings; empty apiKey keeps the old one."""
    stored = _stored()
    for key, value in (patch or {}).items():
        if key not in DEFAULTS:
            continue
        if key in ('apiKey', 'meshPassword') and not str(value or '').strip():
            continue  # the UI never sends a secret back; absence means "unchanged"
        if key == 'mcpToken' and not str(value or '').strip():
            stored['mcpToken'] = secrets.token_urlsafe(32)  # explicit rotation
            continue
        stored[key] = value
    save_json_atomic(settings_file(), stored, ensure_ascii=False, label='agent_config.json')
    return load()


def is_configured(c: dict[str, Any]) -> bool:
    """Whether the chosen door has what it needs -- not whether both do."""
    if (c.get('route') or 'direct') == 'mesh':
        return bool(c.get('meshHost'))
    return bool(c.get('endpoint') and c.get('apiKey') and c.get('model'))


def public_view(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the browser is allowed to see — no API key, ever."""
    c = cfg or load()
    out = {k: v for k, v in c.items() if k not in ('apiKey', 'meshPassword')}
    out['apiKeySet'] = bool(c.get('apiKey'))
    out['meshPasswordSet'] = bool(c.get('meshPassword'))
    out['configured'] = is_configured(c)
    out['envManaged'] = {k: bool(os.environ.get(v)) for k, v in _ENV.items()}
    return out

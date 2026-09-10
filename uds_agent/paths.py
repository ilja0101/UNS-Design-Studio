"""Where the agent keeps its state — one place, so tests can redirect it.

Mirrors app.py's DATA_DIR rule (UNS_DATA_DIR, else /data when it exists on a
non-Windows host, else the repo dir) rather than importing app.py, because the
standalone MCP entrypoints must not drag the whole dashboard into memory.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)


def data_dir() -> str:
    return os.environ.get('UNS_DATA_DIR') or (
        '/data' if os.name != 'nt' and os.path.isdir('/data') else REPO_DIR
    )


def agent_dir() -> str:
    """Writable home for conversations and model snapshots."""
    d = os.path.join(data_dir(), 'agent')
    os.makedirs(d, exist_ok=True)
    return d


def settings_file() -> str:
    return os.path.join(data_dir(), 'agent_config.json')


def policy_file() -> str:
    return os.path.join(data_dir(), 'topic_policy.json')


def conversations_dir() -> str:
    d = os.path.join(agent_dir(), 'conversations')
    os.makedirs(d, exist_ok=True)
    return d


def snapshots_dir() -> str:
    d = os.path.join(agent_dir(), 'snapshots')
    os.makedirs(d, exist_ok=True)
    return d

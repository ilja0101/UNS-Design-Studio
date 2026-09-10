"""Conversation persistence — one JSON file per conversation.

No database: UDS keeps every other piece of runtime state as JSON under
DATA_DIR, and a chat history is the same kind of thing. Files are small (a
conversation is trimmed to :data:`MAX_MESSAGES`) and the whole directory is
easy to wipe, back up or ship inside a demo image.

A stored message keeps the raw OpenAI-shaped ``role``/``content``/``tool_calls``
fields, so a conversation can be replayed straight back into the model, plus a
``ts`` and — for tool results — a rendered ``summary`` the UI shows on its
tool-call card without re-deriving it.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from json_persistence import load_json, save_json_atomic
from uds_agent.paths import conversations_dir

MAX_MESSAGES = 400


def _path(cid: str) -> str:
    safe = ''.join(ch for ch in str(cid) if ch.isalnum() or ch in '-_')
    if not safe:
        raise ValueError('invalid conversation id')
    return os.path.join(conversations_dir(), safe + '.json')


def new_id() -> str:
    return time.strftime('%Y%m%d', time.gmtime()) + '-' + uuid.uuid4().hex[:8]


def create(title: str = 'New chat') -> dict:
    convo = {'id': new_id(), 'title': title, 'createdAt': _now(), 'updatedAt': _now(),
             'messages': []}
    save(convo)
    return convo


def load(cid: str) -> dict | None:
    data = load_json(_path(cid), None, label='conversation')
    return data if isinstance(data, dict) else None


def save(convo: dict) -> bool:
    convo['updatedAt'] = _now()
    if len(convo.get('messages') or []) > MAX_MESSAGES:
        convo['messages'] = convo['messages'][-MAX_MESSAGES:]
    return save_json_atomic(_path(convo['id']), convo, ensure_ascii=False, label='conversation')


def delete(cid: str) -> bool:
    try:
        os.unlink(_path(cid))
        return True
    except OSError:
        return False


def listing() -> list[dict]:
    """Every conversation, newest first, without the message bodies."""
    out = []
    try:
        files = os.listdir(conversations_dir())
    except OSError:
        return out
    for f in files:
        if not f.endswith('.json'):
            continue
        convo = load_json(os.path.join(conversations_dir(), f), None, label='conversation')
        if isinstance(convo, dict) and convo.get('id'):
            out.append({
                'id': convo['id'],
                'title': convo.get('title') or 'Untitled',
                'createdAt': convo.get('createdAt', ''),
                'updatedAt': convo.get('updatedAt', ''),
                'messages': len(convo.get('messages') or []),
            })
    return sorted(out, key=lambda c: c['updatedAt'], reverse=True)


def append(convo: dict, message: dict[str, Any]) -> dict:
    message.setdefault('ts', _now())
    convo.setdefault('messages', []).append(message)
    return message


def title_from(text: str) -> str:
    """First line of the opening message, clipped — good enough as a label."""
    line = (text or '').strip().splitlines()[0] if (text or '').strip() else 'New chat'
    return (line[:57] + '…') if len(line) > 58 else line


def for_model(convo: dict) -> list[dict]:
    """Strip UI-only fields so the history can be replayed into the model."""
    keep = ('role', 'content', 'tool_calls', 'tool_call_id', 'name')
    out = []
    for m in convo.get('messages') or []:
        msg = {k: v for k, v in m.items() if k in keep and v is not None}
        if msg.get('role'):
            out.append(msg)
    return out


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

"""The tool surface — one registry, three consumers.

The built-in chat agent, the in-process ``/mcp`` endpoint and the standalone
``python -m uds_mcp`` entrypoints all execute *these* functions. There is no
second definition of "what an agent may do to a UDS" anywhere in the tree, so
an MCP client and the chat agent are always exactly as capable as each other.

Two design rules keep this usable by a language model:

**Never hand back the whole model.** A production UNS here runs to hundreds of
nodes and thousands of tags; dumping ``uns_config.json`` would burn a context
window per turn and teach the agent nothing. Reads are paged and summarised
(``uns_overview`` / ``uns_browse`` / ``uns_search``), and the agent drills in.

**Every write is snapshotted.** Mutating tools call :func:`_save_uns`, which
files the pre-change config under ``agent/snapshots/`` before saving. That is
what makes "apply directly" safe: ``uns_revert`` puts any of the last
:data:`SNAPSHOT_KEEP` states back, and the chat UI surfaces it as an undo.
"""

from __future__ import annotations

import copy
import json
import os
import time
import uuid
from typing import Any, Callable

from json_persistence import load_json, save_json_atomic
from uds_agent import policy as policy_mod
from uds_agent.backend import Backend, BackendError
from uds_agent.paths import snapshots_dir

SNAPSHOT_KEEP = 30

# Node types the designer understands, in ISA-95 depth order.
NODE_TYPES = [
    'enterprise', 'businessUnit', 'site', 'area', 'workCenter', 'workUnit', 'device', 'folder',
]

_REGISTRY: dict[str, 'Tool'] = {}


class ToolError(RuntimeError):
    """A failure the agent should read and retry from, not a server fault."""


class Tool:
    def __init__(self, name: str, description: str, schema: dict, handler: Callable,
                 *, writes: bool = False):
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.writes = writes

    async def run(self, backend: Backend, args: dict) -> Any:
        return await self.handler(backend, args or {})


def tool(name: str, description: str, schema: dict, *, writes: bool = False):
    def wrap(fn):
        _REGISTRY[name] = Tool(name, description, schema, fn, writes=writes)
        return fn
    return wrap


def registry(*, include_writes: bool = True) -> list[Tool]:
    """Every tool, or only the read-only ones when a caller is read-scoped."""
    return [t for t in _REGISTRY.values() if include_writes or not t.writes]


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


async def call(backend: Backend, name: str, args: dict, *, allow_writes: bool = True) -> Any:
    t = _REGISTRY.get(name)
    if t is None:
        raise ToolError(f'unknown tool: {name}')
    if t.writes and not allow_writes:
        raise ToolError(f'{name} writes to the model, and this connection is read-only')
    try:
        return await t.run(backend, args)
    except BackendError as exc:
        raise ToolError(f'UDS rejected the call: {exc}') from exc


# ── schema helpers ──────────────────────────────────────────────────────────

def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        'type': 'object',
        'properties': props,
        'required': required or [],
        'additionalProperties': False,
    }


_STR = {'type': 'string'}
_INT = {'type': 'integer'}
_BOOL = {'type': 'boolean'}


def _path_prop(desc: str) -> dict:
    return {'type': 'string', 'description': desc}


# ── UNS tree addressing ─────────────────────────────────────────────────────
# A path is the "/"-joined chain of node *names* from the tree root, e.g.
# "Vault-Tec_Industries/Vault-Tec/nuka-boston-facility-01". The root's own name
# is optional, so both "" and "Vault-Tec_Industries" address the root — an
# agent that has only seen a topic (which carries the enterprise) and one that
# has only seen `uns_browse` output both address nodes the same way.

def _split(path: str) -> list[str]:
    return [p for p in str(path or '').replace('\\', '/').split('/') if p.strip()]


def _resolve(tree: dict, path: str) -> tuple[dict, dict | None]:
    """Return (node, parent) for a path, raising ToolError with context."""
    parts = _split(path)
    if parts and tree.get('name') == parts[0]:
        parts = parts[1:]
    node, parent = tree, None
    for i, part in enumerate(parts):
        children = node.get('children') or []
        nxt = next((c for c in children if c.get('name') == part), None)
        if nxt is None:
            here = '/'.join(parts[:i]) or tree.get('name', '(root)')
            options = ', '.join(c.get('name', '?') for c in children[:15]) or '(no children)'
            raise ToolError(f"no node '{part}' under '{here}'. children there: {options}")
        parent, node = node, nxt
    return node, parent


def _node_path(tree: dict, target: dict) -> str:
    """The canonical path of a node, found by identity walk."""
    found: list[str] = []

    def walk(n: dict, acc: list[str]) -> bool:
        here = acc + [n.get('name', '')]
        if n is target:
            found.extend(here)
            return True
        return any(walk(c, here) for c in n.get('children') or [])

    walk(tree, [])
    return '/'.join(found)


def _summarize(node: dict, path: str, *, include_tags: bool) -> dict:
    out: dict[str, Any] = {
        'path': path,
        'name': node.get('name', ''),
        'type': node.get('type', ''),
        'children': len(node.get('children') or []),
        'tags': len(node.get('tags') or []),
    }
    if node.get('description'):
        out['description'] = node['description']
    if node.get('recipes'):
        out['recipes'] = [r.get('name') for r in node['recipes'] if isinstance(r, dict)]
    if include_tags and node.get('tags'):
        out['tagList'] = [
            {
                'name': t.get('name'),
                'dataType': t.get('dataType'),
                'unit': t.get('unit', ''),
                'access': t.get('access', 'read'),
                'qualifier': t.get('qualifier', ''),
                'profile': (t.get('simulation') or {}).get('profile', ''),
                'description': t.get('description', ''),
            }
            for t in node['tags']
        ]
    return out


# ── model load / save with snapshots ────────────────────────────────────────

async def _load_uns(backend: Backend) -> dict:
    cfg = await backend.call('GET', '/api/uns')
    if not isinstance(cfg, dict) or not cfg.get('tree'):
        raise ToolError('the UNS model is empty — build a tree first, or import one')
    return cfg


def _write_snapshot(cfg: dict, label: str) -> str:
    """File the pre-change model so ``uns_revert`` has something to go back to."""
    sid = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:6]
    path = os.path.join(snapshots_dir(), sid + '.json')
    save_json_atomic(
        path,
        {'id': sid, 'label': label, 'takenAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
         'config': cfg},
        ensure_ascii=False, label='agent snapshot',
    )
    _prune_snapshots()
    return sid


def _prune_snapshots() -> None:
    try:
        files = sorted(f for f in os.listdir(snapshots_dir()) if f.endswith('.json'))
    except OSError:
        return
    for stale in files[:-SNAPSHOT_KEEP]:
        try:
            os.unlink(os.path.join(snapshots_dir(), stale))
        except OSError:
            pass


def list_snapshots() -> list[dict]:
    out = []
    for f in sorted((f for f in os.listdir(snapshots_dir()) if f.endswith('.json')), reverse=True):
        meta = load_json(os.path.join(snapshots_dir(), f), None, label='agent snapshot')
        if isinstance(meta, dict):
            cfg = meta.get('config') or {}
            out.append({
                'id': meta.get('id') or f[:-5],
                'label': meta.get('label', ''),
                'takenAt': meta.get('takenAt', ''),
                'nodes': _count_nodes(cfg.get('tree') or {}),
            })
    return out


def _count_nodes(node: dict) -> int:
    if not node:
        return 0
    return 1 + sum(_count_nodes(c) for c in node.get('children') or [])


def _count_tags(node: dict) -> int:
    if not node:
        return 0
    return len(node.get('tags') or []) + sum(_count_tags(c) for c in node.get('children') or [])


async def _save_uns(backend: Backend, before: dict, after: dict, label: str) -> dict:
    """Snapshot, then hand the new model to the app's own POST /api/uns.

    Going through the route (not the file) is deliberate: that handler is what
    restarts the OPC server and re-launches the bridge so a running simulation
    picks the change up. Writing the file directly would leave the OPC address
    space serving the previous model until someone restarted it by hand.
    """
    sid = _write_snapshot(before, label)
    result = await backend.call('POST', '/api/uns', after)
    return {
        'ok': bool((result or {}).get('ok', True)),
        'snapshot': sid,
        'restarted': (result or {}).get('restarted') or [],
        'nodes': _count_nodes(after.get('tree') or {}),
        'tags': _count_tags(after.get('tree') or {}),
    }


# ── inspection tools ────────────────────────────────────────────────────────

@tool('uns_overview',
      'High-level shape of the current UNS model: namespace, enterprise, node and tag counts '
      'per ISA-95 level, and the top two levels of the tree. Start here.',
      _obj({}))
async def _uns_overview(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    tree = cfg['tree']
    per_level: dict[str, int] = {}

    def walk(n: dict) -> None:
        per_level[n.get('type', '?')] = per_level.get(n.get('type', '?'), 0) + 1
        for c in n.get('children') or []:
            walk(c)

    walk(tree)
    top = [
        _summarize(c, _node_path(tree, c), include_tags=False)
        for c in (tree.get('children') or [])
    ]
    return {
        'namespaceUri': cfg.get('namespaceUri', ''),
        'description': cfg.get('description', ''),
        'lastModified': cfg.get('lastModified', ''),
        'root': {'name': tree.get('name'), 'type': tree.get('type')},
        'counts': {'nodes': _count_nodes(tree), 'tags': _count_tags(tree), 'byLevel': per_level},
        'children': top,
    }


@tool('uns_browse',
      'List what sits under a path in the UNS tree. Returns one level by default; raise depth '
      'to 2-3 to see further. Use include_tags to also list each node\'s tags.',
      _obj({
          'path': _path_prop('"/"-joined node names from the root, e.g. "acme/site-01/mixing". Empty for the root.'),
          'depth': {'type': 'integer', 'minimum': 1, 'maximum': 4, 'description': 'Levels to expand (default 1).'},
          'include_tags': {'type': 'boolean', 'description': 'Include each node\'s tag list (default false).'},
      }))
async def _uns_browse(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    tree = cfg['tree']
    node, _ = _resolve(tree, args.get('path', ''))
    depth = max(1, min(4, int(args.get('depth') or 1)))
    include_tags = bool(args.get('include_tags'))
    base = _node_path(tree, node)

    def expand(n: dict, prefix: str, left: int) -> list[dict]:
        rows = []
        for c in n.get('children') or []:
            p = f'{prefix}/{c.get("name", "")}' if prefix else c.get('name', '')
            row = _summarize(c, p, include_tags=include_tags)
            if left > 1 and (c.get('children') or []):
                row['nodes'] = expand(c, p, left - 1)
            rows.append(row)
        return rows

    return {
        'node': _summarize(node, base, include_tags=include_tags),
        'nodes': expand(node, base, depth),
    }


@tool('uns_search',
      'Find nodes or tags by substring, anywhere in the model. Returns paths you can pass '
      'straight to uns_browse, uns_set_tags or uns_update_node.',
      _obj({
          'query': {'type': 'string', 'description': 'Case-insensitive substring, matched on name and description.'},
          'kind': {'type': 'string', 'enum': ['node', 'tag', 'any'], 'description': 'What to match (default any).'},
          'type': {'type': 'string', 'description': 'Restrict node hits to this node type, e.g. "site".'},
          'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200},
      }, ['query']))
async def _uns_search(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    tree = cfg['tree']
    q = str(args.get('query', '')).strip().lower()
    if not q:
        raise ToolError('query must not be empty')
    kind = args.get('kind') or 'any'
    want_type = (args.get('type') or '').strip()
    limit = max(1, min(200, int(args.get('limit') or 40)))
    hits: list[dict] = []

    def matches(*fields: str) -> bool:
        return any(q in (f or '').lower() for f in fields)

    def walk(n: dict, prefix: str) -> None:
        if len(hits) >= limit:
            return
        p = f'{prefix}/{n.get("name", "")}' if prefix else n.get('name', '')
        if kind in ('node', 'any') and matches(n.get('name'), n.get('description')):
            if not want_type or n.get('type') == want_type:
                hits.append({'kind': 'node', 'path': p, 'type': n.get('type', ''),
                             'description': n.get('description', '')})
        if kind in ('tag', 'any'):
            for t in n.get('tags') or []:
                if len(hits) >= limit:
                    return
                if matches(t.get('name'), t.get('description')):
                    hits.append({'kind': 'tag', 'path': p, 'tag': t.get('name', ''),
                                 'dataType': t.get('dataType', ''), 'unit': t.get('unit', '')})
        for c in n.get('children') or []:
            walk(c, p)

    walk(tree, '')
    return {'query': q, 'count': len(hits), 'truncated': len(hits) >= limit, 'hits': hits}


@tool('uns_get_node',
      'The full detail of one node — properties, every tag, recipes — without its subtree.',
      _obj({'path': _path_prop('Path to the node.')}, ['path']))
async def _uns_get_node(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    tree = cfg['tree']
    node, parent = _resolve(tree, args.get('path', ''))
    out = {k: v for k, v in node.items() if k != 'children'}
    out['path'] = _node_path(tree, node)
    out['childNames'] = [c.get('name') for c in node.get('children') or []]
    out['parent'] = parent.get('name') if parent else None
    return out


# ── editing tools ───────────────────────────────────────────────────────────

def _new_id(prefix: str, name: str) -> str:
    slug = ''.join(ch if ch.isalnum() else '-' for ch in str(name).lower()).strip('-')
    return f'{prefix}-{slug or "node"}-{uuid.uuid4().hex[:4]}'


_TAG_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string'},
        'dataType': {'type': 'string', 'description': 'Float, Int, Bool/Boolean or String.'},
        'unit': {'type': 'string'},
        'description': {'type': 'string'},
        'access': {'type': 'string', 'enum': ['read', 'RW'], 'description': 'RW makes it writable (a setpoint or command).'},
        'qualifier': {'type': 'string', 'description': 'data | command | state — the topic policy may constrain this.'},
        'payloadSchema': {'type': 'string'},
        'simulation': {
            'type': 'object',
            'description': 'How the value moves. profile comes from simulation_profiles; min/max/base/std tune it.',
            'properties': {
                'profile': {'type': 'string'},
                'min': {'type': 'number'},
                'max': {'type': 'number'},
                'base': {'type': 'number'},
                'std': {'type': 'number'},
            },
            'additionalProperties': True,
        },
    },
    'required': ['name', 'dataType'],
    'additionalProperties': True,
}


@tool('uns_add_node',
      'Add a child node (site, area, workCenter, workUnit, device, folder) under a parent path.',
      _obj({
          'parent_path': _path_prop('Where to hang it. Empty for the root.'),
          'name': {'type': 'string', 'description': 'Node name — this becomes a topic level, so follow the policy.'},
          'type': {'type': 'string', 'enum': NODE_TYPES},
          'description': {'type': 'string'},
          'tags': {'type': 'array', 'items': _TAG_SCHEMA, 'description': 'Optional tags to create with it.'},
      }, ['parent_path', 'name', 'type']), writes=True)
async def _uns_add_node(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    parent, _ = _resolve(after['tree'], args.get('parent_path', ''))
    name = str(args.get('name', '')).strip()
    if not name:
        raise ToolError('name must not be empty')
    if any(c.get('name') == name for c in parent.get('children') or []):
        raise ToolError(f"'{name}' already exists under that parent")
    ntype = args.get('type')
    if ntype not in NODE_TYPES:
        raise ToolError(f'type must be one of: {", ".join(NODE_TYPES)}')
    node = {
        'id': _new_id(ntype[:3], name),
        'name': name,
        'type': ntype,
        'description': str(args.get('description') or ''),
        'children': [],
    }
    if args.get('tags'):
        node['tags'] = [_normalize_tag(t) for t in args['tags']]
    parent.setdefault('children', []).append(node)
    res = await _save_uns(backend, cfg, after, f'add {ntype} {name}')
    res['path'] = _node_path(after['tree'], node)
    return res


@tool('uns_update_node',
      'Rename a node or change its type/description. Renaming changes every topic beneath it.',
      _obj({
          'path': _path_prop('Path to the node.'),
          'name': {'type': 'string'},
          'type': {'type': 'string', 'enum': NODE_TYPES},
          'description': {'type': 'string'},
      }, ['path']), writes=True)
async def _uns_update_node(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, parent = _resolve(after['tree'], args.get('path', ''))
    changed = []
    if args.get('name') and args['name'] != node.get('name'):
        siblings = (parent or {}).get('children') or []
        if any(c is not node and c.get('name') == args['name'] for c in siblings):
            raise ToolError(f"'{args['name']}' already exists alongside that node")
        node['name'] = str(args['name']).strip()
        changed.append('name')
    if args.get('type'):
        if args['type'] not in NODE_TYPES:
            raise ToolError(f'type must be one of: {", ".join(NODE_TYPES)}')
        node['type'] = args['type']
        changed.append('type')
    if 'description' in args:
        node['description'] = str(args.get('description') or '')
        changed.append('description')
    if not changed:
        raise ToolError('nothing to change — pass name, type or description')
    res = await _save_uns(backend, cfg, after, f'update {node.get("name")}')
    res.update({'path': _node_path(after['tree'], node), 'changed': changed})
    return res


@tool('uns_delete_node',
      'Delete a node and everything under it. Reversible with uns_revert.',
      _obj({'path': _path_prop('Path to the node. The root cannot be deleted.')}, ['path']),
      writes=True)
async def _uns_delete_node(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, parent = _resolve(after['tree'], args.get('path', ''))
    if parent is None:
        raise ToolError('the root node cannot be deleted — edit its children instead')
    removed = {'nodes': _count_nodes(node), 'tags': _count_tags(node), 'name': node.get('name')}
    parent['children'] = [c for c in parent['children'] if c is not node]
    res = await _save_uns(backend, cfg, after, f'delete {removed["name"]}')
    res['removed'] = removed
    return res


@tool('uns_move_node',
      'Re-parent a node, carrying its whole subtree to a new place in the hierarchy.',
      _obj({
          'path': _path_prop('Node to move.'),
          'new_parent_path': _path_prop('Where it should end up.'),
      }, ['path', 'new_parent_path']), writes=True)
async def _uns_move_node(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, parent = _resolve(after['tree'], args.get('path', ''))
    if parent is None:
        raise ToolError('the root node cannot be moved')
    target, _ = _resolve(after['tree'], args.get('new_parent_path', ''))

    def contains(hay: dict, needle: dict) -> bool:
        return hay is needle or any(contains(c, needle) for c in hay.get('children') or [])

    if contains(node, target):
        raise ToolError('cannot move a node inside its own subtree')
    if any(c.get('name') == node.get('name') for c in target.get('children') or []):
        raise ToolError(f"'{node.get('name')}' already exists under the target parent")
    parent['children'] = [c for c in parent['children'] if c is not node]
    target.setdefault('children', []).append(node)
    res = await _save_uns(backend, cfg, after, f'move {node.get("name")}')
    res['path'] = _node_path(after['tree'], node)
    return res


def _normalize_tag(raw: dict) -> dict:
    name = str((raw or {}).get('name', '')).strip()
    if not name:
        raise ToolError('every tag needs a name')
    tag: dict[str, Any] = {
        'id': raw.get('id') or _new_id('tag', name),
        'name': name,
        'dataType': raw.get('dataType') or 'Float',
        'unit': str(raw.get('unit') or ''),
        'description': str(raw.get('description') or ''),
        'access': raw.get('access') or 'read',
    }
    if raw.get('qualifier'):
        tag['qualifier'] = raw['qualifier']
    else:
        # A policy that constrains qualifiers rejects an unset one, and the
        # asset-library templates don't carry them. Infer the obvious value —
        # writable means command, everything else is data — so instantiating a
        # template doesn't import a violation per tag. An explicit qualifier
        # from the caller always wins.
        allowed = (policy_mod.load_policy().get('tag') or {}).get('qualifiers') or []
        if allowed:
            guess = 'command' if str(tag['access']).lower() == 'rw' else 'data'
            tag['qualifier'] = guess if guess in allowed else allowed[0]
    if raw.get('payloadSchema'):
        tag['payloadSchema'] = raw['payloadSchema']
    sim = raw.get('simulation')
    tag['simulation'] = sim if isinstance(sim, dict) else {'profile': 'default'}
    return tag


@tool('uns_set_tags',
      'Add or replace the tags on one node. Each tag becomes one published topic.',
      _obj({
          'path': _path_prop('Node that carries the tags.'),
          'tags': {'type': 'array', 'items': _TAG_SCHEMA},
          'mode': {'type': 'string', 'enum': ['append', 'replace'],
                   'description': 'append keeps existing tags (default); replace swaps the whole list.'},
      }, ['path', 'tags']), writes=True)
async def _uns_set_tags(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, _ = _resolve(after['tree'], args.get('path', ''))
    incoming = [_normalize_tag(t) for t in (args.get('tags') or [])]
    if not incoming:
        raise ToolError('pass at least one tag (use uns_delete_tags to remove)')
    if (args.get('mode') or 'append') == 'replace':
        node['tags'] = incoming
    else:
        existing = node.get('tags') or []
        by_name = {t.get('name'): i for i, t in enumerate(existing)}
        for t in incoming:
            if t['name'] in by_name:
                existing[by_name[t['name']]] = t
            else:
                existing.append(t)
        node['tags'] = existing
    res = await _save_uns(backend, cfg, after, f'tags on {node.get("name")}')
    res.update({'path': _node_path(after['tree'], node), 'tagCount': len(node['tags'])})
    return res


@tool('uns_delete_tags',
      'Remove named tags from a node.',
      _obj({
          'path': _path_prop('Node that carries the tags.'),
          'names': {'type': 'array', 'items': _STR},
      }, ['path', 'names']), writes=True)
async def _uns_delete_tags(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, _ = _resolve(after['tree'], args.get('path', ''))
    names = {str(n) for n in (args.get('names') or [])}
    before_count = len(node.get('tags') or [])
    node['tags'] = [t for t in node.get('tags') or [] if t.get('name') not in names]
    removed = before_count - len(node['tags'])
    if not removed:
        raise ToolError(f'none of those tags exist on {node.get("name")}')
    res = await _save_uns(backend, cfg, after, f'delete tags on {node.get("name")}')
    res.update({'removed': removed, 'tagCount': len(node['tags'])})
    return res


@tool('uns_add_asset',
      'Instantiate an asset-library template (pump, boiler, packing machine, control loop, …) '
      'under a parent — creates the node and its full realistic tag set in one call. '
      'Use asset_library to see what is available. This is the fastest way to build a plant.',
      _obj({
          'parent_path': _path_prop('Where the equipment goes — normally an area or workCenter.'),
          'asset': {'type': 'string', 'description': 'Asset template id, e.g. "centrifugal_pump".'},
          'name': {'type': 'string', 'description': 'Instance name. Defaults to the template id.'},
          'type': {'type': 'string', 'enum': NODE_TYPES, 'description': 'Node type to create (default workUnit).'},
          'count': {'type': 'integer', 'minimum': 1, 'maximum': 20,
                    'description': 'Create N instances, suffixed -01, -02, … (default 1).'},
          'conform_names': {'type': 'boolean',
                            'description': 'Rewrite the template\'s tag names into the topic '
                                           'policy\'s case rule (default true).'},
      }, ['parent_path', 'asset']), writes=True)
async def _uns_add_asset(backend: Backend, args: dict) -> dict:
    library = await backend.call('GET', '/api/asset-library')
    assets = (library or {}).get('assets') or []
    aid = str(args.get('asset', ''))
    template = next((a for a in assets if a.get('id') == aid), None)
    if template is None:
        ids = ', '.join(a.get('id', '') for a in assets[:30])
        raise ToolError(f"no asset template '{aid}'. available: {ids}")

    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    parent, _ = _resolve(after['tree'], args.get('parent_path', ''))
    count = max(1, min(20, int(args.get('count') or 1)))
    ntype = args.get('type') or 'workUnit'
    base = str(args.get('name') or aid).strip()

    # The shipped templates use PascalCase tag names ("MotorCurrentA"), which
    # most topic policies reject. Conforming on the way in is far better than
    # importing violations and asking the agent to rename them afterwards.
    conform = args.get('conform_names')
    conform = True if conform is None else bool(conform)
    pol = policy_mod.load_policy()
    rule = (pol.get('tag') or {}).get('caseRule') or pol.get('caseRule') or ''

    def tag_name(raw: str) -> str:
        if not conform or not rule or rule == 'any':
            return raw
        return policy_mod.suggest_name(raw, rule) or raw

    created = []
    for i in range(count):
        name = base if count == 1 else f'{base}-{i + 1:02d}'
        if any(c.get('name') == name for c in parent.get('children') or []):
            raise ToolError(f"'{name}' already exists under that parent")
        tags = []
        for t in template.get('tags') or []:
            t = dict(t)
            t['name'] = tag_name(str(t.get('name', '')))
            tags.append(_normalize_tag(t))
        node = {
            'id': _new_id(ntype[:3], name),
            'name': name,
            'type': ntype,
            'description': template.get('description', ''),
            'children': [],
            'tags': tags,
        }
        parent.setdefault('children', []).append(node)
        created.append(node)
    res = await _save_uns(backend, cfg, after, f'add {count}x {aid}')
    res['created'] = [
        {'path': _node_path(after['tree'], n), 'tags': len(n.get('tags') or [])} for n in created
    ]
    res['conformedNamesTo'] = rule if conform and rule else None
    return res


@tool('uns_replace_subtree',
      'Replace everything under a path with a tree you supply — the bulk path for generating a '
      'whole site or area at once. Pass the node itself (name/type/description/tags/children). '
      'Prefer this over dozens of uns_add_node calls when modelling something new.',
      _obj({
          'path': _path_prop('Node to replace. Empty replaces the whole model root.'),
          'node': {
              'type': 'object',
              'description': 'The replacement node: {name, type, description?, tags?, children?} nested freely.',
              'additionalProperties': True,
          },
      }, ['path', 'node']), writes=True)
async def _uns_replace_subtree(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, parent = _resolve(after['tree'], args.get('path', ''))
    replacement = _rebuild(args.get('node') or {})
    if parent is None:
        after['tree'] = replacement
    else:
        parent['children'] = [replacement if c is node else c for c in parent['children']]
    res = await _save_uns(backend, cfg, after, f'replace subtree {replacement.get("name")}')
    res['path'] = _node_path(after['tree'], replacement)
    return res


def _rebuild(raw: dict) -> dict:
    """Normalise an agent-authored subtree: ids filled in, tags validated."""
    name = str((raw or {}).get('name', '')).strip()
    if not name:
        raise ToolError('every node in the subtree needs a name')
    ntype = raw.get('type') or 'folder'
    if ntype not in NODE_TYPES:
        raise ToolError(f"node '{name}' has type '{ntype}'; must be one of {', '.join(NODE_TYPES)}")
    node: dict[str, Any] = {
        'id': raw.get('id') or _new_id(ntype[:3], name),
        'name': name,
        'type': ntype,
        'description': str(raw.get('description') or ''),
        'children': [_rebuild(c) for c in raw.get('children') or []],
    }
    if raw.get('tags'):
        node['tags'] = [_normalize_tag(t) for t in raw['tags']]
    if raw.get('recipes'):
        node['recipes'] = raw['recipes']
    return node


# ── undo ────────────────────────────────────────────────────────────────────

@tool('uns_snapshots',
      'List the automatic snapshots taken before each agent edit — the undo history.',
      _obj({}))
async def _uns_snapshots(backend: Backend, args: dict) -> dict:
    return {'snapshots': list_snapshots()}


@tool('uns_revert',
      'Put the model back to a snapshot, undoing every edit made since it was taken. '
      'The current model is snapshotted first, so a revert is itself reversible.',
      _obj({'snapshot': {'type': 'string', 'description': 'Snapshot id from uns_snapshots.'}},
           ['snapshot']), writes=True)
async def _uns_revert(backend: Backend, args: dict) -> dict:
    sid = str(args.get('snapshot', '')).strip()
    path = os.path.join(snapshots_dir(), sid + '.json')
    meta = load_json(path, None, label='agent snapshot')
    if not isinstance(meta, dict) or not isinstance(meta.get('config'), dict):
        raise ToolError(f'no snapshot {sid} — call uns_snapshots for the list')
    current = await _load_uns(backend)
    res = await _save_uns(backend, current, meta['config'], f'revert to {sid}')
    res['revertedTo'] = sid
    return res


# ── topic policy ────────────────────────────────────────────────────────────

@tool('policy_get',
      'The active topic policy: separator, prefix, allowed ISA-95 levels, naming rules, and the '
      'free-text notes from the organisation\'s policy document.',
      _obj({}))
async def _policy_get(backend: Backend, args: dict) -> dict:
    return policy_mod.load_policy()


@tool('policy_set',
      'Write the topic policy. Send the whole document — separator, prefix, caseRule, levels, '
      'tag rules, forbiddenParts, notes. Use this when the user pastes a policy in chat.',
      _obj({
          'policy': {
              'type': 'object',
              'description': 'Full policy document. Keys: name, description, separator, prefix, '
                             'caseRule (kebab|snake|lower|upper|pascal|any), maxTopicLength, '
                             'levels[{type,required,caseRule?,pattern?,allowed?}], '
                             'tag{caseRule?,pattern?,qualifiers?}, forbiddenParts[], notes.',
              'additionalProperties': True,
          },
      }, ['policy']), writes=True)
async def _policy_set(backend: Backend, args: dict) -> dict:
    pol = args.get('policy')
    if not isinstance(pol, dict):
        raise ToolError('policy must be an object')
    if not policy_mod.save_policy(pol):
        raise ToolError('could not write topic_policy.json')
    return {'ok': True, 'policy': policy_mod.load_policy()}


@tool('policy_check',
      'Validate the current UNS model against the topic policy. Returns violations with the '
      'path and the fix. Run this after modelling and iterate until it comes back ok.',
      _obj({'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200,
                      'description': 'Max violations to return (default 50).'}}))
async def _policy_check(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    return policy_mod.check_policy(cfg, limit=max(1, min(200, int(args.get('limit') or 50))))


@tool('policy_conform_names',
      'Bulk-rename nodes and/or tags under a path into the policy\'s case rule — the fast fix '
      'for a model that policy_check says is misnamed. Always dry-run it first and show the '
      'user the renames, because renaming rewrites every topic underneath.',
      _obj({
          'path': _path_prop('Where to start. Empty for the whole model.'),
          'scope': {'type': 'string', 'enum': ['tags', 'nodes', 'both'],
                    'description': 'What to rename (default tags — renaming nodes moves topics).'},
          'dry_run': {'type': 'boolean',
                      'description': 'true (the default) reports the renames without applying them.'},
          'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500,
                    'description': 'Max renames to list back (default 40). All are applied.'},
      }), writes=True)
async def _policy_conform_names(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    after = copy.deepcopy(cfg)
    node, _ = _resolve(after['tree'], args.get('path', ''))
    scope = args.get('scope') or 'tags'
    dry = args.get('dry_run')
    dry = True if dry is None else bool(dry)
    limit = max(1, min(500, int(args.get('limit') or 40)))

    pol = policy_mod.load_policy()
    node_rule = pol.get('caseRule') or 'any'
    tag_rule = (pol.get('tag') or {}).get('caseRule') or node_rule
    renames: list[dict] = []

    def rename(n: dict, prefix: str) -> None:
        here = f'{prefix}/{n.get("name", "")}' if prefix else n.get('name', '')
        if scope in ('nodes', 'both') and node_rule not in ('', 'any'):
            new = policy_mod.suggest_name(n.get('name', ''), node_rule)
            if new and new != n.get('name'):
                renames.append({'kind': 'node', 'path': here, 'from': n['name'], 'to': new})
                n['name'] = new
                here = f'{prefix}/{new}' if prefix else new
        if scope in ('tags', 'both') and tag_rule not in ('', 'any'):
            for t in n.get('tags') or []:
                new = policy_mod.suggest_name(t.get('name', ''), tag_rule)
                if new and new != t.get('name'):
                    renames.append({'kind': 'tag', 'path': here, 'from': t['name'], 'to': new})
                    t['name'] = new
        for c in n.get('children') or []:
            rename(c, here)

    rename(node, '')
    if not renames:
        return {'ok': True, 'renamed': 0, 'message': 'every name already matches the policy'}
    if dry:
        return {'ok': True, 'dryRun': True, 'wouldRename': len(renames),
                'renames': renames[:limit],
                'message': 'nothing was changed — call again with dry_run false to apply'}
    res = await _save_uns(backend, cfg, after, f'conform {len(renames)} names to policy')
    res.update({'renamed': len(renames), 'renames': renames[:limit]})
    return res


@tool('policy_suggest_name',
      'Rewrite a free-text name into the policy\'s case rule, so renames stay consistent.',
      _obj({
          'name': {'type': 'string'},
          'rule': {'type': 'string', 'enum': list(policy_mod.CASE_RULES),
                   'description': 'Defaults to the policy\'s own caseRule.'},
      }, ['name']))
async def _policy_suggest_name(backend: Backend, args: dict) -> dict:
    pol = policy_mod.load_policy()
    rule = args.get('rule') or pol.get('caseRule') or 'kebab'
    return {'name': args.get('name'), 'rule': rule,
            'suggestion': policy_mod.suggest_name(args.get('name', ''), rule)}


@tool('topics_preview',
      'The exact topics this model would publish, built by the bridge\'s own walk. Use it to '
      'show the user what the namespace looks like before starting the simulation.',
      _obj({
          'contains': {'type': 'string', 'description': 'Only topics containing this substring.'},
          'limit': {'type': 'integer', 'minimum': 1, 'maximum': 200},
      }))
async def _topics_preview(backend: Backend, args: dict) -> dict:
    cfg = await _load_uns(backend)
    return policy_mod.preview_topics(
        cfg, limit=max(1, min(200, int(args.get('limit') or 40))),
        contains=str(args.get('contains') or ''),
    )


# ── catalogue ───────────────────────────────────────────────────────────────

@tool('asset_library',
      'The equipment templates available to uns_add_asset, with their tag counts.',
      _obj({'search': {'type': 'string', 'description': 'Filter by id, label or category.'}}))
async def _asset_library(backend: Backend, args: dict) -> dict:
    data = await backend.call('GET', '/api/asset-library')
    q = str(args.get('search') or '').strip().lower()
    rows = [
        {'id': a.get('id'), 'label': a.get('label'), 'category': a.get('category'),
         'description': a.get('description', ''), 'tags': len(a.get('tags') or []),
         'tagNames': [t.get('name') for t in (a.get('tags') or [])[:12]]}
        for a in (data or {}).get('assets') or []
    ]
    if q:
        rows = [r for r in rows
                if q in f"{r['id']} {r['label']} {r['category']} {r['description']}".lower()]
    return {'count': len(rows), 'assets': rows}


@tool('simulation_profiles',
      'The value-generation profiles a tag\'s simulation.profile can name (ramps, noise, '
      'boolean states, control loops), grouped by family.',
      _obj({}))
async def _simulation_profiles(backend: Backend, args: dict) -> Any:
    return await backend.call('GET', '/api/simulation-profiles')


@tool('payload_schemas',
      'Read or replace the payload schemas the bridge formats messages with.',
      _obj({
          'schemas': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': True},
                      'description': 'Omit to read. Pass the full list to replace.'},
      }), writes=True)
async def _payload_schemas(backend: Backend, args: dict) -> Any:
    if args.get('schemas') is None:
        return await backend.call('GET', '/api/payload-schemas')
    await backend.call('POST', '/api/payload-schemas', {'schemas': args['schemas']})
    return {'ok': True, 'count': len(args['schemas'])}


# ── runtime ─────────────────────────────────────────────────────────────────

@tool('sim_status',
      'Live state of the simulator: OPC-UA server, bridge, per-plant running flags, recipes, '
      'shift, and current metric values.',
      _obj({}))
async def _sim_status(backend: Backend, args: dict) -> Any:
    return await backend.call('GET', '/api/status')


@tool('sim_control',
      'Start or stop the moving parts: the OPC-UA server, the MQTT/NATS bridge, or every plant.',
      _obj({
          'action': {'type': 'string',
                     'enum': ['server_start', 'server_stop', 'bridge_start', 'bridge_stop',
                              'plants_start', 'plants_stop'],
                     'description': 'server_* is the OPC-UA address space; bridge_* is the broker publisher.'},
      }, ['action']), writes=True)
async def _sim_control(backend: Backend, args: dict) -> Any:
    routes = {
        'server_start': '/api/server/start', 'server_stop': '/api/server/stop',
        'bridge_start': '/api/bridge/start', 'bridge_stop': '/api/bridge/stop',
        'plants_start': '/api/plants/start-all', 'plants_stop': '/api/plants/stop-all',
    }
    path = routes.get(args.get('action'))
    if not path:
        raise ToolError(f'action must be one of: {", ".join(routes)}')
    return await backend.call('POST', path, {})


@tool('plant_control',
      'Start or stop one plant, or switch the recipe it is running.',
      _obj({
          'group': {'type': 'string', 'description': 'Business group / business unit name.'},
          'plant': {'type': 'string', 'description': 'Site name.'},
          'running': {'type': 'boolean'},
          'recipe': {'type': 'string'},
      }, ['group', 'plant']), writes=True)
async def _plant_control(backend: Backend, args: dict) -> Any:
    body = {k: v for k, v in args.items() if v is not None}
    return await backend.call('POST', '/api/plant/control', body)


@tool('anomaly_inject',
      'Inject a fault or process deviation so downstream consumers see something interesting.',
      _obj({
          'group': {'type': 'string'},
          'plant': {'type': 'string'},
          'type': {'type': 'string', 'description': 'Anomaly kind, e.g. "fault", "drift", "spike".'},
          'target': {'type': 'string', 'description': 'Equipment or tag to affect.'},
          'duration': {'type': 'number', 'description': 'Seconds to hold the anomaly.'},
      }), writes=True)
async def _anomaly_inject(backend: Backend, args: dict) -> Any:
    return await backend.call('POST', '/api/anomaly/inject',
                              {k: v for k, v in args.items() if v is not None})


@tool('bridge_config',
      'Read or update the broker the bridge publishes to — protocol, host, port, topic prefix, '
      'separator, publish interval. Keep the prefix and separator in step with the topic policy.',
      _obj({
          'config': {'type': 'object', 'additionalProperties': True,
                     'description': 'Omit to read. Keys mirror the Settings page: protocol, host, '
                                    'port, username, password, prefix, separator, interval.'},
      }), writes=True)
async def _bridge_config(backend: Backend, args: dict) -> Any:
    if args.get('config') is None:
        return await backend.call('GET', '/api/bridge/config')
    return await backend.call('POST', '/api/bridge/config', args['config'])


@tool('plc_simulators',
      'The standalone raw OPC-UA PLC simulators running next to the UNS server: list them, or '
      'start/stop one. These are the "raw" datasources for testing PLC → UNS mapping.',
      _obj({
          'action': {'type': 'string', 'enum': ['list', 'start', 'stop'],
                     'description': 'Defaults to list.'},
          'id': {'type': 'string', 'description': 'Instance id, required for start/stop.'},
      }), writes=True)
async def _plc_simulators(backend: Backend, args: dict) -> Any:
    action = args.get('action') or 'list'
    if action == 'list':
        return await backend.call('GET', '/api/plc/instances')
    iid = str(args.get('id') or '').strip()
    if not iid:
        raise ToolError('id is required to start or stop an instance')
    return await backend.call('POST', f'/api/plc/{iid}/{action}', {})

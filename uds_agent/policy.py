"""Topic policy — the rulebook the agent models against, and its checker.

A UNS topic policy is the document an organisation writes to say what its
broker namespace is allowed to look like: which ISA-95 levels appear, in what
order, how each level is spelled, what a tag may be called. UDS already knows
how to turn a UNS tree into topics (``uns_tree.build_bridge_entries`` — the
exact same walk the bridge publishes with), so a policy check is that walk plus
a set of assertions over the parts.

The split matters: ``levels``/``tag``/``forbiddenParts`` are machine-checkable
and drive :func:`check_policy`, which the agent calls in a loop until it comes
back clean. ``notes`` is the prose the regexes can't capture; it is injected
verbatim into the agent's system prompt instead. Both come from the same file
so "give the agent a topic policy" is a single action.
"""

from __future__ import annotations

import os
import re
from typing import Any

from json_persistence import load_json, save_json_atomic
from uds_agent.paths import policy_file
from uns_tree import build_bridge_entries, sanitize_topic_part

# Case rules a policy can name instead of writing the regex out. "any" opts
# the level out of case checking entirely (still subject to `pattern`).
CASE_RULES: dict[str, str] = {
    'kebab': r'^[a-z0-9]+(-[a-z0-9]+)*$',
    'snake': r'^[a-z0-9]+(_[a-z0-9]+)*$',
    'lower': r'^[a-z0-9][a-z0-9._-]*$',
    'upper': r'^[A-Z0-9][A-Z0-9._-]*$',
    'pascal': r'^[A-Z][A-Za-z0-9]*$',
    'any': r'.*',
}

# The ISA-95 / S88 ladder UDS models, shallowest first. A policy's `levels` is
# a subset of these in this order; anything else is a folder-ish passthrough.
LEVEL_ORDER = [
    'enterprise', 'businessUnit', 'site', 'area', 'workCenter', 'workUnit', 'device',
]

DEFAULT_POLICY: dict[str, Any] = {
    'name': 'Default UNS topic policy',
    'description': 'ISA-95 levels, lower-kebab names, one tag per leaf topic.',
    'separator': '/',
    'prefix': 'uns',
    'caseRule': 'kebab',
    'maxTopicLength': 240,
    'levels': [
        {'type': 'enterprise', 'required': True},
        {'type': 'businessUnit', 'required': False},
        {'type': 'site', 'required': True},
        {'type': 'area', 'required': True},
        {'type': 'workCenter', 'required': False},
        {'type': 'workUnit', 'required': False},
        {'type': 'device', 'required': False},
    ],
    'tag': {'caseRule': 'kebab', 'pattern': '', 'qualifiers': []},
    'forbiddenParts': [],
    'notes': '',
}


def load_policy() -> dict[str, Any]:
    """The active policy, with every key the checker needs present.

    No policy file is the normal state for a fresh UDS, not a fault, so the
    absent-file case falls through to the default silently — load_json's
    logger would otherwise print a read failure on every single check.
    """
    if not os.path.exists(policy_file()):
        return dict(DEFAULT_POLICY)
    raw = load_json(policy_file(), None, label='topic_policy.json')
    if not isinstance(raw, dict):
        return dict(DEFAULT_POLICY)
    merged = dict(DEFAULT_POLICY)
    merged.update({k: v for k, v in raw.items() if v is not None})
    if not isinstance(merged.get('tag'), dict):
        merged['tag'] = dict(DEFAULT_POLICY['tag'])
    if not isinstance(merged.get('levels'), list) or not merged['levels']:
        merged['levels'] = list(DEFAULT_POLICY['levels'])
    return merged


def save_policy(policy: dict[str, Any]) -> bool:
    merged = dict(DEFAULT_POLICY)
    merged.update({k: v for k, v in (policy or {}).items() if v is not None})
    return save_json_atomic(policy_file(), merged, ensure_ascii=False, label='topic_policy.json')


def _compiled(rule: str | None, pattern: str | None) -> re.Pattern | None:
    """Resolve a level's case rule + explicit pattern into one regex.

    An explicit `pattern` wins outright; a named case rule is the fallback. An
    unparseable pattern is treated as "no check" rather than exploding the whole
    report — a policy typo should show up as a lenient check, not a 500.
    """
    src = (pattern or '').strip() or CASE_RULES.get((rule or 'any').strip().lower())
    if not src or src == r'.*':
        return None
    try:
        return re.compile(src)
    except re.error:
        return None


def _violation(code: str, path: str, message: str, fix: str = '') -> dict[str, str]:
    return {'code': code, 'path': path, 'message': message, 'fix': fix}


def check_policy(uns: dict, policy: dict | None = None, *, limit: int = 200) -> dict[str, Any]:
    """Validate a UNS config against a topic policy.

    Returns a report the agent can act on directly: a pass/fail flag, counts,
    the violations (capped, because a 2700-tag model can produce thousands and
    the agent only needs enough to start fixing), and a few sample topics so it
    can see the shape it actually produced.
    """
    pol = policy or load_policy()
    sep = pol.get('separator') or '/'
    prefix = pol.get('prefix') or ''
    tree = (uns or {}).get('tree') or {}

    violations: list[dict[str, str]] = []
    total = 0

    def add(v: dict[str, str]) -> None:
        # Count everything, keep only `limit`. A 2700-tag model can produce
        # thousands of findings; the agent needs the true scale to decide
        # whether to fix them one by one or rebuild, but not the whole list.
        nonlocal total
        total += 1
        if len(violations) < limit:
            violations.append(v)

    levels = [lv for lv in pol.get('levels', []) if isinstance(lv, dict)]
    by_type = {lv.get('type'): lv for lv in levels}
    declared = [lv.get('type') for lv in levels if lv.get('type') in LEVEL_ORDER]
    forbidden = {str(p).strip().lower() for p in (pol.get('forbiddenParts') or []) if str(p).strip()}
    default_case = pol.get('caseRule') or 'any'

    tag_cfg = pol.get('tag') or {}
    tag_re = _compiled(tag_cfg.get('caseRule') or default_case, tag_cfg.get('pattern'))
    qualifiers = {str(q).strip() for q in (tag_cfg.get('qualifiers') or []) if str(q).strip()}

    seen_types: set[str] = set()
    counts = {'nodes': 0, 'tags': 0}

    def walk(node: dict, ancestry: list[str], path_parts: list[str]) -> None:
        counts['nodes'] += 1
        ntype = node.get('type') or ''
        name = node.get('name') or ''
        here = path_parts + [name]
        pretty = '/'.join(here)

        if ntype in LEVEL_ORDER:
            seen_types.add(ntype)
            if declared and ntype not in declared:
                add(_violation(
                    'level.undeclared', pretty,
                    "level '%s' is not part of this policy" % ntype,
                    'use one of: ' + ', '.join(declared),
                ))
            # Ordering: a declared level must sit deeper than every declared
            # level above it. Catches an area hung straight off an enterprise
            # when the policy says a site belongs in between.
            prior = [a for a in ancestry if a in declared]
            if declared and ntype in declared and prior:
                if declared.index(ntype) <= declared.index(prior[-1]):
                    add(_violation(
                        'level.order', pretty,
                        "'%s' nested under '%s' breaks the policy level order" % (ntype, prior[-1]),
                        'policy order is ' + ' > '.join(declared),
                    ))

        lv = by_type.get(ntype) or {}
        name_re = _compiled(lv.get('caseRule') or default_case, lv.get('pattern'))
        if name and name_re and not name_re.match(name):
            add(_violation(
                'name.pattern', pretty,
                "name '%s' does not match the policy for '%s'" % (name, ntype or 'node'),
                'expected ' + name_re.pattern,
            ))
        if name and sep in name:
            add(_violation(
                'name.separator', pretty,
                "name '%s' contains the topic separator '%s'" % (name, sep),
                'rename so the level boundary stays unambiguous',
            ))
        if name.strip().lower() in forbidden:
            add(_violation(
                'name.forbidden', pretty,
                "name '%s' is on the policy's forbidden list" % name, '',
            ))
        allowed = lv.get('allowed') or []
        if allowed and name and name not in allowed:
            add(_violation(
                'name.allowed', pretty,
                "name '%s' is not in the allowed set for '%s'" % (name, ntype),
                'allowed: ' + ', '.join(map(str, allowed[:12])),
            ))

        for tag in node.get('tags') or []:
            counts['tags'] += 1
            tname = tag.get('name') or ''
            tpath = '%s:%s' % (pretty, tname)
            if tag_re and tname and not tag_re.match(tname):
                add(_violation(
                    'tag.pattern', tpath,
                    "tag '%s' does not match the policy tag pattern" % tname,
                    'expected ' + tag_re.pattern,
                ))
            if qualifiers:
                q = tag.get('qualifier') or ''
                if q not in qualifiers:
                    add(_violation(
                        'tag.qualifier', tpath,
                        "tag qualifier '%s' is not allowed" % (q or '(unset)'),
                        'allowed: ' + ', '.join(sorted(qualifiers)),
                    ))

        for child in node.get('children') or []:
            walk(child, ancestry + ([ntype] if ntype else []), here)

    if tree:
        walk(tree, [], [])

    for lv in levels:
        if lv.get('required') and lv.get('type') not in seen_types:
            add(_violation(
                'level.missing', '(model)',
                "policy requires a '%s' level but the model has none" % lv.get('type'), '',
            ))

    # Topic-level checks run off the real bridge walk, so what we validate is
    # literally what would be published — sanitisation included.
    topics: list[str] = []
    if tree:
        try:
            topics = [e[0] for e in build_bridge_entries(tree, sep, prefix)]
        except Exception as exc:  # a malformed tree is a finding, not a crash
            add(_violation('model.unwalkable', '(model)', 'could not build topics: %s' % exc, ''))

    max_len = int(pol.get('maxTopicLength') or 0)
    seen_topics: dict[str, int] = {}
    for t in topics:
        seen_topics[t] = seen_topics.get(t, 0) + 1
        if max_len and len(t) > max_len:
            add(_violation(
                'topic.length', t,
                'topic is %d chars, policy caps at %d' % (len(t), max_len), '',
            ))
    for t, n in seen_topics.items():
        if n > 1:
            add(_violation(
                'topic.duplicate', t,
                '%d tags collapse onto this topic' % n,
                'rename the tags or the nodes so each topic is unique',
            ))

    return {
        'ok': total == 0,
        'policy': pol.get('name') or 'policy',
        'separator': sep,
        'prefix': prefix,
        'counts': {
            'nodes': counts['nodes'],
            'tags': counts['tags'],
            'topics': len(topics),
            'violations': total,
        },
        'reported': len(violations),
        'truncated': total > len(violations),
        'violations': violations,
        'sampleTopics': topics[:10],
    }


def preview_topics(uns: dict, policy: dict | None = None, *, limit: int = 50,
                   contains: str = '') -> dict[str, Any]:
    """The topics this model would publish — the bridge's own walk, unmodified."""
    pol = policy or load_policy()
    sep = pol.get('separator') or '/'
    prefix = pol.get('prefix') or ''
    tree = (uns or {}).get('tree') or {}
    if not tree:
        return {'total': 0, 'topics': [], 'separator': sep, 'prefix': prefix}
    entries = build_bridge_entries(tree, sep, prefix)
    rows = [
        {'topic': e[0], 'unit': e[2], 'dataType': e[4], 'tag': e[5]}
        for e in entries
        if not contains or contains.lower() in e[0].lower()
    ]
    return {'total': len(rows), 'topics': rows[:limit], 'separator': sep, 'prefix': prefix}


def suggest_name(raw: str, rule: str) -> str:
    """Rewrite a free-text name into the policy's case rule.

    Backs the agent's ``policy_suggest_name`` tool, so it renames consistently
    instead of re-deriving the convention tag by tag.
    """
    s = sanitize_topic_part(str(raw or '').strip())
    words = [w for w in re.split(r'[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])', s) if w]
    rule = (rule or 'kebab').lower()
    if rule == 'kebab':
        return '-'.join(w.lower() for w in words)
    if rule == 'snake':
        return '_'.join(w.lower() for w in words)
    if rule == 'lower':
        return ''.join(w.lower() for w in words)
    if rule == 'upper':
        return '_'.join(w.upper() for w in words)
    if rule == 'pascal':
        return ''.join(w.capitalize() for w in words)
    return s

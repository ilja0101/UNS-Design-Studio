"""Topic policy: what the checker catches, and what it must not."""
import pytest

from uds_agent import policy as policy_mod


def _uns(tree):
    return {'tree': tree}


def _node(name, ntype, children=None, tags=None):
    n = {'name': name, 'type': ntype, 'children': children or []}
    if tags:
        n['tags'] = tags
    return n


CLEAN = _uns(_node('acme', 'enterprise', [
    _node('nl-veghel', 'site', [
        _node('mixing', 'area', [
            _node('feed-pump-01', 'workUnit', tags=[
                {'name': 'flow-rate', 'dataType': 'Float', 'unit': 'L/min'},
                {'name': 'running', 'dataType': 'Bool'},
            ]),
        ]),
    ]),
]))

KEBAB = {
    'name': 'test', 'separator': '/', 'prefix': 'uns', 'caseRule': 'kebab',
    'maxTopicLength': 240,
    'levels': [
        {'type': 'enterprise', 'required': True},
        {'type': 'site', 'required': True},
        {'type': 'area', 'required': True},
        {'type': 'workUnit', 'required': False},
    ],
    'tag': {'caseRule': 'kebab', 'pattern': '', 'qualifiers': []},
    'forbiddenParts': [],
    'notes': '',
}


def codes(report):
    return {v['code'] for v in report['violations']}


def test_a_conforming_model_passes():
    report = policy_mod.check_policy(CLEAN, KEBAB)
    assert report['ok'], report['violations']
    assert report['counts']['topics'] == 2
    assert report['sampleTopics'][0] == 'uns/acme/nl-veghel/mixing/feed-pump-01/flow-rate'


def test_case_rule_is_enforced_on_nodes_and_tags():
    bad = _uns(_node('Acme_Corp', 'enterprise', [
        _node('nl-veghel', 'site', [
            _node('mixing', 'area', [
                _node('feed-pump-01', 'workUnit', tags=[{'name': 'FlowRate', 'dataType': 'Float'}]),
            ]),
        ]),
    ]))
    report = policy_mod.check_policy(bad, KEBAB)
    assert not report['ok']
    assert codes(report) == {'name.pattern', 'tag.pattern'}


def test_missing_required_level_is_reported():
    """A site is required; a model that jumps enterprise → area must say so."""
    bad = _uns(_node('acme', 'enterprise', [_node('mixing', 'area', [])]))
    assert 'level.missing' in codes(policy_mod.check_policy(bad, KEBAB))


def test_level_order_violation_is_reported():
    """An enterprise nested under a site inverts the ladder."""
    bad = _uns(_node('acme', 'enterprise', [
        _node('nl-veghel', 'site', [
            _node('acme-two', 'enterprise', []),
            _node('mixing', 'area', []),
        ]),
    ]))
    assert 'level.order' in codes(policy_mod.check_policy(bad, KEBAB))


def test_separator_inside_a_name_is_reported():
    bad = _uns(_node('acme', 'enterprise', [
        _node('nl/veghel', 'site', [_node('mixing', 'area', [])]),
    ]))
    assert 'name.separator' in codes(policy_mod.check_policy(bad, KEBAB))


def test_duplicate_topics_are_reported():
    """Two tags of the same name on one node collapse onto one topic."""
    bad = _uns(_node('acme', 'enterprise', [
        _node('nl-veghel', 'site', [
            _node('mixing', 'area', [
                _node('pump-01', 'workUnit', tags=[
                    {'name': 'flow', 'dataType': 'Float'},
                    {'name': 'flow', 'dataType': 'Float'},
                ]),
            ]),
        ]),
    ]))
    assert 'topic.duplicate' in codes(policy_mod.check_policy(bad, KEBAB))


def test_allowed_list_and_forbidden_parts():
    pol = dict(KEBAB, forbiddenParts=['mixing'], levels=[
        {'type': 'enterprise', 'required': True, 'allowed': ['globex']},
        {'type': 'site', 'required': True},
        {'type': 'area', 'required': True},
    ])
    found = codes(policy_mod.check_policy(CLEAN, pol))
    assert 'name.allowed' in found
    assert 'name.forbidden' in found


def test_tag_qualifiers_are_enforced_when_declared():
    pol = dict(KEBAB, tag={'caseRule': 'kebab', 'qualifiers': ['data', 'command']})
    assert 'tag.qualifier' in codes(policy_mod.check_policy(CLEAN, pol))


def test_violations_are_counted_in_full_but_reported_up_to_the_limit():
    """The agent needs the true scale even when it only gets a sample."""
    tags = [{'name': f'Bad{i}', 'dataType': 'Float'} for i in range(30)]
    bad = _uns(_node('acme', 'enterprise', [
        _node('nl-veghel', 'site', [
            _node('mixing', 'area', [_node('pump-01', 'workUnit', tags=tags)]),
        ]),
    ]))
    report = policy_mod.check_policy(bad, KEBAB, limit=5)
    assert report['counts']['violations'] == 30
    assert report['reported'] == 5
    assert report['truncated'] is True


def test_a_broken_regex_in_a_policy_is_lenient_not_fatal():
    """A typo in a policy pattern must not 500 the whole check."""
    pol = dict(KEBAB, levels=[{'type': 'enterprise', 'required': True, 'pattern': '([unclosed'}])
    report = policy_mod.check_policy(CLEAN, pol)
    assert 'name.pattern' not in codes(report)


def test_nats_separator_changes_the_topics():
    pol = dict(KEBAB, separator='.', prefix='uns')
    report = policy_mod.check_policy(CLEAN, pol)
    assert report['sampleTopics'][0] == 'uns.acme.nl-veghel.mixing.feed-pump-01.flow-rate'


def test_max_topic_length_is_enforced():
    pol = dict(KEBAB, maxTopicLength=20)
    assert 'topic.length' in codes(policy_mod.check_policy(CLEAN, pol))


@pytest.mark.parametrize('raw,rule,expected', [
    ('MotorCurrentA', 'snake', 'motor_current_a'),
    ('Nuka Cola Bottling_01', 'kebab', 'nuka-cola-bottling-01'),
    ('flow rate', 'pascal', 'FlowRate'),
    ('Vault-Tec_Industries', 'kebab', 'vault-tec-industries'),
    ('already-fine', 'kebab', 'already-fine'),
])
def test_suggest_name(raw, rule, expected):
    assert policy_mod.suggest_name(raw, rule) == expected


def test_preview_topics_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_mod, 'load_policy', lambda: KEBAB)
    all_topics = policy_mod.preview_topics(CLEAN)
    assert all_topics['total'] == 2
    filtered = policy_mod.preview_topics(CLEAN, contains='running')
    assert filtered['total'] == 1
    assert filtered['topics'][0]['tag'] == 'running'


def test_load_policy_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'nope.json'))
    assert policy_mod.load_policy()['name'] == policy_mod.DEFAULT_POLICY['name']


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    path = tmp_path / 'topic_policy.json'
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(path))
    assert policy_mod.save_policy({'name': 'Acme v3', 'separator': '.'})
    loaded = policy_mod.load_policy()
    assert loaded['name'] == 'Acme v3'
    assert loaded['separator'] == '.'
    # Keys the caller omitted still come back, so the checker never KeyErrors.
    assert loaded['levels'] and 'tag' in loaded

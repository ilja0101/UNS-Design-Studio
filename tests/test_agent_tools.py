"""The tool layer: addressing, edits, snapshots, and the errors an agent must recover from.

Runs against a fake backend rather than the real app, so a test is about tool
semantics and not about OPC-UA restarts. The MCP-level tests
(test_mcp_protocol.py) cover the wiring to the real routes.
"""
import copy
import json

import pytest

from uds_agent import policy as policy_mod
from uds_agent import tools as tools_mod


BASE = {
    'namespaceUri': 'urn:acme:uns:v1',
    'tree': {
        'name': 'acme', 'type': 'enterprise', 'description': 'Acme',
        'children': [
            {'name': 'nl-veghel', 'type': 'site', 'children': [
                {'name': 'mixing', 'type': 'area', 'children': [
                    {'name': 'pump-01', 'type': 'workUnit', 'children': [], 'tags': [
                        {'id': 't1', 'name': 'flow-rate', 'dataType': 'Float', 'unit': 'L/min',
                         'description': 'Flow', 'access': 'read',
                         'simulation': {'profile': 'flow_rate'}},
                    ]},
                ]},
            ]},
        ],
    },
}

LIBRARY = {'assets': [
    {'id': 'centrifugal_pump', 'label': 'Centrifugal Pump', 'category': 'Rotating',
     'description': 'A pump', 'tags': [
         {'name': 'Running', 'dataType': 'Bool', 'simulation': {'profile': 'boolean_running'}},
         {'name': 'MotorCurrentA', 'dataType': 'Float', 'unit': 'A',
          'simulation': {'profile': 'motor_current'}},
     ]},
]}


class FakeBackend:
    """Stands in for a UDS: holds the config, records what was written."""

    def __init__(self, uns=None):
        self.uns = copy.deepcopy(uns if uns is not None else BASE)
        self.saves = 0
        self.calls = []

    async def call(self, method, path, body=None, params=None):
        self.calls.append((method, path))
        if path == '/api/uns' and method == 'GET':
            return copy.deepcopy(self.uns)
        if path == '/api/uns' and method == 'POST':
            self.uns = copy.deepcopy(body)
            self.saves += 1
            return {'ok': True, 'restarted': []}
        if path == '/api/asset-library':
            return copy.deepcopy(LIBRARY)
        if path == '/api/status':
            return {'server_running': False}
        return {'ok': True}


@pytest.fixture
def backend(tmp_path, monkeypatch):
    """A fake UDS whose snapshots and policy live in a tmp dir."""
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: str(tmp_path))
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'topic_policy.json'))
    return FakeBackend()


async def run(backend, tool, **args):
    # `tool`, not `name` — several tools take a literal `name` argument, and a
    # helper parameter of the same name would swallow it.
    return await tools_mod.call(backend, tool, args)


# ── addressing ──────────────────────────────────────────────────────────────

async def test_paths_work_with_and_without_the_root_name(backend):
    """A path from a topic carries the enterprise; one from uns_browse may not."""
    with_root = await run(backend, 'uns_get_node', path='acme/nl-veghel/mixing')
    without = await run(backend, 'uns_get_node', path='nl-veghel/mixing')
    assert with_root['name'] == without['name'] == 'mixing'


async def test_empty_path_addresses_the_root(backend):
    assert (await run(backend, 'uns_get_node', path=''))['name'] == 'acme'


async def test_a_bad_path_names_the_available_children(backend):
    """The error has to be enough for the model to correct itself."""
    with pytest.raises(tools_mod.ToolError) as exc:
        await run(backend, 'uns_browse', path='acme/nowhere')
    assert 'nl-veghel' in str(exc.value)


# ── reads ───────────────────────────────────────────────────────────────────

async def test_overview_counts_by_level(backend):
    out = await run(backend, 'uns_overview')
    assert out['counts']['nodes'] == 4
    assert out['counts']['tags'] == 1
    assert out['counts']['byLevel']['site'] == 1


async def test_browse_depth_and_tags(backend):
    shallow = await run(backend, 'uns_browse', path='acme')
    assert [n['name'] for n in shallow['nodes']] == ['nl-veghel']
    assert 'nodes' not in shallow['nodes'][0]

    deep = await run(backend, 'uns_browse', path='acme', depth=3, include_tags=True)
    pump = deep['nodes'][0]['nodes'][0]['nodes'][0]
    assert pump['name'] == 'pump-01'
    assert pump['tagList'][0]['name'] == 'flow-rate'


async def test_search_finds_nodes_and_tags(backend):
    assert (await run(backend, 'uns_search', query='flow'))['hits'][0]['kind'] == 'tag'
    nodes = await run(backend, 'uns_search', query='veghel', kind='node')
    assert nodes['hits'][0]['path'] == 'acme/nl-veghel'


async def test_search_rejects_an_empty_query(backend):
    with pytest.raises(tools_mod.ToolError):
        await run(backend, 'uns_search', query='  ')


# ── writes ──────────────────────────────────────────────────────────────────

async def test_add_node_saves_and_snapshots(backend):
    out = await run(backend, 'uns_add_node', parent_path='acme/nl-veghel',
                    name='utilities', type='area', description='Boilers')
    assert backend.saves == 1
    assert out['path'] == 'acme/nl-veghel/utilities'
    assert out['snapshot']
    assert len(tools_mod.list_snapshots()) == 1


async def test_add_node_rejects_a_duplicate_name(backend):
    with pytest.raises(tools_mod.ToolError, match='already exists'):
        await run(backend, 'uns_add_node', parent_path='acme', name='nl-veghel', type='site')
    assert backend.saves == 0


async def test_add_node_rejects_an_unknown_type(backend):
    with pytest.raises(tools_mod.ToolError, match='type must be one of'):
        await run(backend, 'uns_add_node', parent_path='acme', name='x', type='gizmo')


async def test_update_node_renames(backend):
    await run(backend, 'uns_update_node', path='acme/nl-veghel', name='nl-breda')
    assert backend.uns['tree']['children'][0]['name'] == 'nl-breda'


async def test_update_node_needs_something_to_change(backend):
    with pytest.raises(tools_mod.ToolError, match='nothing to change'):
        await run(backend, 'uns_update_node', path='acme')


async def test_delete_node_reports_what_went(backend):
    out = await run(backend, 'uns_delete_node', path='acme/nl-veghel/mixing')
    assert out['removed'] == {'nodes': 2, 'tags': 1, 'name': 'mixing'}


async def test_the_root_cannot_be_deleted(backend):
    with pytest.raises(tools_mod.ToolError, match='root node cannot be deleted'):
        await run(backend, 'uns_delete_node', path='acme')


async def test_move_node_reparents(backend):
    await run(backend, 'uns_add_node', parent_path='acme/nl-veghel', name='utilities', type='area')
    await run(backend, 'uns_move_node', path='acme/nl-veghel/mixing/pump-01',
              new_parent_path='acme/nl-veghel/utilities')
    utilities = backend.uns['tree']['children'][0]['children'][1]
    assert [c['name'] for c in utilities['children']] == ['pump-01']


async def test_a_node_cannot_be_moved_into_itself(backend):
    with pytest.raises(tools_mod.ToolError, match='own subtree'):
        await run(backend, 'uns_move_node', path='acme/nl-veghel',
                  new_parent_path='acme/nl-veghel/mixing')


async def test_set_tags_appends_by_default_and_replaces_on_request(backend):
    path = 'acme/nl-veghel/mixing/pump-01'
    await run(backend, 'uns_set_tags', path=path,
              tags=[{'name': 'pressure', 'dataType': 'Float', 'unit': 'bar'}])
    tags = backend.uns['tree']['children'][0]['children'][0]['children'][0]['tags']
    assert [t['name'] for t in tags] == ['flow-rate', 'pressure']

    await run(backend, 'uns_set_tags', path=path, mode='replace',
              tags=[{'name': 'only', 'dataType': 'Float'}])
    tags = backend.uns['tree']['children'][0]['children'][0]['children'][0]['tags']
    assert [t['name'] for t in tags] == ['only']


async def test_set_tags_updates_a_tag_of_the_same_name_rather_than_duplicating(backend):
    path = 'acme/nl-veghel/mixing/pump-01'
    await run(backend, 'uns_set_tags', path=path,
              tags=[{'name': 'flow-rate', 'dataType': 'Float', 'unit': 'm3/h'}])
    tags = backend.uns['tree']['children'][0]['children'][0]['children'][0]['tags']
    assert len(tags) == 1 and tags[0]['unit'] == 'm3/h'


async def test_a_tag_without_a_name_is_rejected(backend):
    with pytest.raises(tools_mod.ToolError, match='needs a name'):
        await run(backend, 'uns_set_tags', path='acme/nl-veghel/mixing/pump-01',
                  tags=[{'dataType': 'Float'}])


async def test_delete_tags_reports_when_nothing_matched(backend):
    with pytest.raises(tools_mod.ToolError, match='none of those tags exist'):
        await run(backend, 'uns_delete_tags', path='acme/nl-veghel/mixing/pump-01',
                  names=['nope'])


# ── asset library ───────────────────────────────────────────────────────────

async def test_add_asset_instantiates_the_template(backend):
    out = await run(backend, 'uns_add_asset', parent_path='acme/nl-veghel/mixing',
                    asset='centrifugal_pump', name='feed-pump', count=2)
    assert [c['path'] for c in out['created']] == [
        'acme/nl-veghel/mixing/feed-pump-01', 'acme/nl-veghel/mixing/feed-pump-02',
    ]
    assert out['created'][0]['tags'] == 2


async def test_add_asset_conforms_tag_names_to_the_policy(backend, tmp_path):
    """Templates ship PascalCase names; a kebab policy must not inherit them."""
    policy_mod.save_policy({'caseRule': 'kebab', 'tag': {'caseRule': 'kebab'}})
    await run(backend, 'uns_add_asset', parent_path='acme/nl-veghel/mixing',
              asset='centrifugal_pump', name='feed-pump')
    node = backend.uns['tree']['children'][0]['children'][0]['children'][1]
    assert [t['name'] for t in node['tags']] == ['running', 'motor-current-a']


async def test_add_asset_can_keep_the_template_names(backend):
    policy_mod.save_policy({'caseRule': 'kebab', 'tag': {'caseRule': 'kebab'}})
    await run(backend, 'uns_add_asset', parent_path='acme/nl-veghel/mixing',
              asset='centrifugal_pump', name='feed-pump', conform_names=False)
    node = backend.uns['tree']['children'][0]['children'][0]['children'][1]
    assert [t['name'] for t in node['tags']] == ['Running', 'MotorCurrentA']


async def test_an_unknown_asset_lists_what_is_available(backend):
    with pytest.raises(tools_mod.ToolError, match='centrifugal_pump'):
        await run(backend, 'uns_add_asset', parent_path='acme', asset='flux_capacitor')


async def test_a_policy_with_qualifiers_stamps_them_on_new_tags(backend):
    """Otherwise instantiating a template imports one violation per tag."""
    policy_mod.save_policy({'tag': {'caseRule': 'any', 'qualifiers': ['data', 'command']}})
    await run(backend, 'uns_set_tags', path='acme/nl-veghel/mixing/pump-01',
              tags=[{'name': 'speed-sp', 'dataType': 'Float', 'access': 'RW'},
                    {'name': 'speed-pv', 'dataType': 'Float'}])
    tags = backend.uns['tree']['children'][0]['children'][0]['children'][0]['tags']
    by_name = {t['name']: t.get('qualifier') for t in tags}
    assert by_name['speed-sp'] == 'command'
    assert by_name['speed-pv'] == 'data'


# ── bulk generation ─────────────────────────────────────────────────────────

async def test_replace_subtree_normalises_and_fills_in_ids(backend):
    await run(backend, 'uns_replace_subtree', path='acme/nl-veghel', node={
        'name': 'nl-veghel', 'type': 'site', 'children': [
            {'name': 'packing', 'type': 'area', 'children': [
                {'name': 'wrapper-01', 'type': 'workUnit',
                 'tags': [{'name': 'rate', 'dataType': 'Float'}]},
            ]},
        ],
    })
    site = backend.uns['tree']['children'][0]
    assert [c['name'] for c in site['children']] == ['packing']
    wrapper = site['children'][0]['children'][0]
    assert wrapper['id'] and wrapper['tags'][0]['id']


async def test_replace_subtree_rejects_a_bad_node_type(backend):
    with pytest.raises(tools_mod.ToolError, match='must be one of'):
        await run(backend, 'uns_replace_subtree', path='acme/nl-veghel',
                  node={'name': 'x', 'type': 'gizmo'})


async def test_conform_names_is_a_dry_run_unless_told_otherwise(backend):
    policy_mod.save_policy({'caseRule': 'kebab', 'tag': {'caseRule': 'snake'}})
    dry = await run(backend, 'policy_conform_names', scope='tags')
    assert dry['dryRun'] is True
    assert dry['renames'][0] == {'kind': 'tag', 'path': 'acme/nl-veghel/mixing/pump-01',
                                 'from': 'flow-rate', 'to': 'flow_rate'}
    assert backend.saves == 0

    applied = await run(backend, 'policy_conform_names', scope='tags', dry_run=False)
    assert applied['renamed'] == 1
    assert backend.saves == 1


# ── undo ────────────────────────────────────────────────────────────────────

async def test_revert_restores_a_snapshot_and_snapshots_the_revert(backend):
    await run(backend, 'uns_add_node', parent_path='acme', name='de-koln', type='site')
    assert len(backend.uns['tree']['children']) == 2

    snapshot = tools_mod.list_snapshots()[0]['id']
    out = await run(backend, 'uns_revert', snapshot=snapshot)
    assert out['revertedTo'] == snapshot
    assert len(backend.uns['tree']['children']) == 1
    # The revert is itself undoable.
    assert len(tools_mod.list_snapshots()) == 2


async def test_revert_to_an_unknown_snapshot_is_a_tool_error(backend):
    with pytest.raises(tools_mod.ToolError, match='no snapshot'):
        await run(backend, 'uns_revert', snapshot='nope')


async def test_snapshots_are_pruned_to_the_cap(backend, monkeypatch):
    monkeypatch.setattr(tools_mod, 'SNAPSHOT_KEEP', 3)
    for i in range(5):
        await run(backend, 'uns_add_node', parent_path='acme', name=f'site-{i}', type='site')
    assert len(tools_mod.list_snapshots()) == 3


# ── registry ────────────────────────────────────────────────────────────────

def test_read_only_callers_do_not_even_see_write_tools():
    read_only = {t.name for t in tools_mod.registry(include_writes=False)}
    assert 'uns_browse' in read_only
    assert 'uns_add_node' not in read_only


async def test_a_write_tool_is_refused_on_a_read_only_connection(backend):
    with pytest.raises(tools_mod.ToolError, match='read-only'):
        await tools_mod.call(backend, 'uns_add_node',
                             {'parent_path': 'acme', 'name': 'x', 'type': 'site'},
                             allow_writes=False)


async def test_an_unknown_tool_is_a_tool_error(backend):
    with pytest.raises(tools_mod.ToolError, match='unknown tool'):
        await tools_mod.call(backend, 'does_not_exist', {})


def test_every_tool_advertises_a_usable_json_schema():
    for t in tools_mod.registry():
        assert t.description.strip(), t.name
        assert t.schema['type'] == 'object', t.name
        assert isinstance(t.schema['properties'], dict), t.name
        # Required keys must actually be declared, or a strict client rejects it.
        for key in t.schema.get('required', []):
            assert key in t.schema['properties'], f'{t.name}.{key}'
        # Serialisable, because it goes out over JSON-RPC.
        json.dumps(t.schema)

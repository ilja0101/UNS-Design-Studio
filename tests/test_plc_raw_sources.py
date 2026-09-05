"""Raw OT sources: an empty PLC sim the UNS Designer edits like a UNS tree.

These cover the API the Designer's source picker rides on — create empty, read,
save back (with a hot restart of just that sim), and the hidden answer key that
makes a rawified source scoreable.
"""
import json
import os

import pytest

import app as studio


@pytest.fixture
def plc_env(tmp_path, monkeypatch):
    """Isolate the registry + config dir so tests never touch real instances."""
    cfg_dir = tmp_path / 'plc_configs'
    cfg_dir.mkdir()
    monkeypatch.setattr(studio, 'PLC_CONFIG_DIR', str(cfg_dir))
    monkeypatch.setattr(studio, 'PLC_REGISTRY_FILE', str(tmp_path / 'plc_instances.json'))
    monkeypatch.setattr(studio, '_plc_procs', {})
    monkeypatch.setitem(studio._state, 'opc_port', 4840)
    monkeypatch.setitem(studio._state, 'opc_host', '127.0.0.1')
    return cfg_dir


async def _blank(client, **body):
    body.setdefault('name', 'Line 4 Raw')
    res = await client.post('/api/plc/blank', json=body)
    return res, await res.get_json()


async def test_blank_creates_an_empty_running_ready_source(plc_env):
    client = studio.app.test_client()
    res, data = await _blank(client)

    assert res.status_code == 200 and data['ok']
    inst = data['instance']
    assert inst['id'] == 'line-4-raw'
    assert inst['tags'] == 0 and inst['nodes'] == 1
    assert inst['endpoint'] == f"opc.tcp://127.0.0.1:{inst['port']}/freeopcua/server/"

    cfg = json.loads((plc_env / 'line-4-raw.json').read_text(encoding='utf-8'))
    assert cfg['tree']['type'] == 'enterprise'
    assert cfg['tree']['children'] == []


async def test_blank_takes_a_separate_root_name_and_a_chosen_port(plc_env):
    client = studio.app.test_client()
    _, data = await _blank(client, name='Scrubber', rootName='402A1', port=4855)

    assert data['instance']['port'] == 4855
    assert data['instance']['tcpPort'] == 9855
    cfg = json.loads((plc_env / 'scrubber.json').read_text(encoding='utf-8'))
    assert cfg['tree']['name'] == '402A1'


async def test_blank_refuses_a_port_already_in_use(plc_env):
    client = studio.app.test_client()
    await _blank(client, name='A', port=4851)
    res, data = await _blank(client, name='B', port=4851)
    assert res.status_code == 400 and 'already assigned' in data['msg']

    res, data = await _blank(client, name='C', port=4840)  # the studio's own factory
    assert res.status_code == 400


async def test_blank_keeps_ids_unique_for_repeated_names(plc_env):
    client = studio.app.test_client()
    _, first = await _blank(client, name='Line 4 Raw')
    _, second = await _blank(client, name='Line 4 Raw')
    assert first['instance']['id'] == 'line-4-raw'
    assert second['instance']['id'] == 'line-4-raw-2'
    assert second['instance']['port'] != first['instance']['port']


async def test_config_round_trips_and_recounts_the_tree(plc_env):
    client = studio.app.test_client()
    await _blank(client, name='Line 4 Raw')

    got = await (await client.get('/api/plc/line-4-raw/config')).get_json()
    assert got['ok'] and got['config']['tree']['children'] == []

    cfg = got['config']
    cfg['tree']['children'] = [{
        'id': 'n1', 'name': '402A1', 'type': 'folder', 'children': [
            {'id': 'n2', 'name': 'P101', 'type': 'device', 'children': [], 'tags': [
                {'id': 't1', 'name': 'DB101.DBW0', 'dataType': 'Int16',
                 'simulation': {'profile': 'flow_rate',
                                'rawScale': {'engLo': 0, 'engHi': 120, 'rawLo': 0, 'rawHi': 27648}}},
                {'id': 't2', 'name': 'DB101.DBX200.0', 'dataType': 'Boolean',
                 'simulation': {'profile': 'boolean_running'}},
            ]},
        ], 'tags': []},
    ]
    saved = await (await client.put('/api/plc/line-4-raw/config', json={'config': cfg})).get_json()
    assert saved['ok'] and saved['tags'] == 2 and saved['nodes'] == 3
    assert saved['restarted'] is False          # nothing was running
    assert saved['instance']['tags'] == 2       # the instance card follows

    on_disk = json.loads((plc_env / 'line-4-raw.json').read_text(encoding='utf-8'))
    assert on_disk['tree']['children'][0]['children'][0]['tags'][0]['name'] == 'DB101.DBW0'
    assert on_disk['lastModified']


async def test_config_save_restarts_a_running_sim(plc_env, monkeypatch):
    client = studio.app.test_client()
    await _blank(client, name='Line 4 Raw')

    calls = []
    monkeypatch.setattr(studio, '_plc_alive', lambda iid: True)

    async def _stop(iid):
        calls.append(('stop', iid))
        return True, 'stopped'

    async def _start(iid):
        calls.append(('start', iid))
        return True, 'started'

    monkeypatch.setattr(studio, 'stop_plc_instance', _stop)
    monkeypatch.setattr(studio, 'start_plc_instance', _start)

    cfg = (await (await client.get('/api/plc/line-4-raw/config')).get_json())['config']
    saved = await (await client.put('/api/plc/line-4-raw/config', json={'config': cfg})).get_json()

    assert saved['restarted'] is True
    assert calls == [('stop', 'line-4-raw'), ('start', 'line-4-raw')]


async def test_config_rejects_a_body_without_a_tree(plc_env):
    client = studio.app.test_client()
    await _blank(client, name='Line 4 Raw')
    res = await client.put('/api/plc/line-4-raw/config', json={'config': {'version': '1.0'}})
    assert res.status_code == 400


async def test_unknown_instance_is_404_everywhere(plc_env):
    client = studio.app.test_client()
    assert (await client.get('/api/plc/nope/config')).status_code == 404
    assert (await client.put('/api/plc/nope/config', json={'tree': {}})).status_code == 404
    assert (await client.get('/api/plc/nope/truth')).status_code == 404


async def test_truth_reports_the_answer_key_on_opc_paths(plc_env):
    client = studio.app.test_client()
    await _blank(client, name='Line 4 Raw')
    cfg = (await (await client.get('/api/plc/line-4-raw/config')).get_json())['config']
    cfg['tree']['children'] = [{
        'id': 'n1', 'name': '402A1', 'type': 'folder', 'tags': [], 'children': [
            {'id': 'n2', 'name': 'P101', 'type': 'device', 'children': [], 'tags': [
                {'id': 't1', 'name': 'DB101.DBW0', 'dataType': 'Int16',
                 'simulation': {'profile': 'flow_rate'},
                 '_truth': {'asset': 'centrifugal_pump', 'assetLabel': 'Centrifugal Pump',
                            'instance': 'P101', 'tag': 'FlowM3H', 'unit': 'm3/h',
                            'description': 'Process flow', 'profile': 'flow_rate',
                            'role': 'flow', 'engLo': 0, 'engHi': 120,
                            'rawLo': 0, 'rawHi': 27648}},
                {'id': 't2', 'name': 'DB101.DBW2', 'dataType': 'Int16',
                 'simulation': {'profile': 'hold'},
                 '_truth': {'asset': '', 'assetLabel': '', 'instance': 'P101', 'tag': 'spare1',
                            'unit': '', 'description': '', 'profile': 'hold',
                            'role': 'analog', 'decoy': True}},
                {'id': 't3', 'name': 'PlainTag', 'dataType': 'Float', 'simulation': None},
            ]},
        ]},
    ]
    await client.put('/api/plc/line-4-raw/config', json={'config': cfg})

    data = await (await client.get('/api/plc/line-4-raw/truth')).get_json()
    assert data['count'] == 2                       # the un-truthed tag is not in the key
    first = data['rows'][0]
    assert first['opcPath'] == 'Line 4 Raw/402A1/P101/DB101.DBW0'   # as a client browses it
    assert first['canonicalTag'] == 'FlowM3H'
    assert first['asset'] == 'Centrifugal Pump'
    assert first['rawHi'] == 27648
    assert data['rows'][1]['decoy'] is True

    res = await client.get('/api/plc/line-4-raw/truth?format=csv')
    body = (await res.get_data()).decode('utf-8')
    assert res.headers['Content-Type'].startswith('text/csv')
    assert 'attachment; filename="line-4-raw_truth.csv"' in res.headers['Content-Disposition']
    assert body.splitlines()[0].startswith('opcPath,tag,dataType,asset')
    assert 'Line 4 Raw/402A1/P101/DB101.DBW0' in body


async def test_import_still_creates_instances_after_the_helper_refactor(plc_env):
    """The id/port helpers are shared with /api/plc/import — keep it working."""
    client = studio.app.test_client()
    csv_text = ('Tag Name,Address,Data Type,Client Access,Scan Rate\n'
                'FIC_101_PV,PLC01.Tags.FIC_101_PV,Float,Read Only,100\n')
    res = await client.post('/api/plc/import', json={
        'name': 'Imported PLC',
        'files': [{'filename': 'PLC01.csv', 'content': csv_text}],
    })
    data = await res.get_json()
    assert res.status_code == 200 and data['ok'], data
    assert data['instance']['id'] == 'imported-plc'
    assert os.path.exists(os.path.join(str(plc_env), 'imported-plc.json'))

import app as dashboard


async def test_status_reports_disconnected_and_stopped_when_server_not_ready(monkeypatch):
    monkeypatch.setattr(dashboard, '_reconcile_sim_state_with_process', lambda reason='': None)
    monkeypatch.setattr(dashboard, '_server_alive', lambda: False)
    monkeypatch.setattr(dashboard, '_opc_tcp_port_open', lambda timeout=0.25: True)
    monkeypatch.setattr(dashboard, '_load_bridge_cfg', lambda: {})
    monkeypatch.setattr(dashboard, '_bridge_alive', lambda: False)
    monkeypatch.setattr(dashboard, '_get_enterprise_structure', lambda: {'BU': ['Site']})
    monkeypatch.setattr(dashboard, '_get_enterprise_name', lambda: 'Enterprise')
    monkeypatch.setattr(dashboard, 'load_json', lambda *args, **kwargs: {
        'plants': {
            'BU|Site': {'running': True, 'recipe': 'Recipe A'}
        },
        'simulator_running': True,
    })

    dashboard._state['opc_connected'] = True
    dashboard._state['plant_data'] = {
        'BU|Site': {
            'group': 'BU', 'plant': 'Site', 'process_state': True,
            'maint_status': 'Running', 'opc_ready': True, 'recipe': 'Recipe A',
            'oee': 95, 'power': 10, 'good_tons': 20, 'trucks_recv': 3,
        }
    }

    client = dashboard.app.test_client()
    data = await (await client.get('/api/status')).get_json()

    assert data['server_running'] is False
    assert data['server_ready'] is False
    assert data['opc_connected'] is False
    assert data['plants']['BU|Site']['process_state'] is False
    assert data['plants']['BU|Site']['maint_status'] == 'Stopped'
    assert data['plants']['BU|Site']['opc_ready'] is False


async def test_stop_all_is_idempotent_and_returns_plants_stopped(monkeypatch):
    monkeypatch.setattr(dashboard, '_ensure_sim_state_synced', lambda: None)
    monkeypatch.setattr(dashboard, '_mark_all_plants_stopped', lambda reason='': False)

    client = dashboard.app.test_client()
    response = await client.post('/api/plants/stop-all')
    data = await response.get_json()

    assert response.status_code == 200
    assert data == {'ok': True, 'msg': 'Plants stopped'}

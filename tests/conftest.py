"""Pytest fixtures for UNS Design Studio tests.

Importing `app` triggers a daemon OPC-poll thread; that's harmless because the
thread sleeps on connection failure. Each test gets isolated UNS + viz config
files so we never touch the real ones.
"""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Import app.py with config paths redirected to a tmp dir."""
    uns_path = tmp_path / 'uns_config.json'
    viz_path = tmp_path / 'visualization.json'
    uns_path.write_text(json.dumps(_DEFAULT_UNS), encoding='utf-8')

    import app as app_mod
    monkeypatch.setattr(app_mod, 'UNS_CONFIG_FILE', str(uns_path))
    monkeypatch.setattr(app_mod, 'VIZ_CONFIG_FILE', str(viz_path))
    return app_mod


@pytest.fixture
def flask_client(app_module):
    app_module.app.testing = True
    return app_module.app.test_client()


@pytest.fixture
def write_uns(app_module):
    """Helper that overwrites the temp uns_config.json with given tree."""
    def _write(tree):
        with open(app_module.UNS_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'tree': tree}, f)
    return _write


@pytest.fixture
def write_viz(app_module):
    def _write(cfg):
        with open(app_module.VIZ_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
    return _write


_DEFAULT_UNS = {
    'tree': {
        'name': 'Acme', 'type': 'enterprise',
        'children': [
            {
                'name': 'NA', 'type': 'businessUnit',
                'children': [
                    {
                        'name': 'plant-01', 'type': 'site',
                        'children': [
                            {
                                'name': 'mixing', 'type': 'area',
                                'children': [
                                    {
                                        'name': 'tank-01', 'type': 'workCenter',
                                        'children': [
                                            {
                                                'name': 'pump-01', 'type': 'workUnit',
                                                'tags': [
                                                    {'name': 'flow_rate', 'dataType': 'Float',
                                                     'unit': 'L/min'},
                                                    {'name': 'running', 'dataType': 'Bool'},
                                                    {'name': 'pressure', 'dataType': 'Float',
                                                     'unit': 'bar', 'opcPath': 'mixing/pump-01/p'},
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
}

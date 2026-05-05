"""Tests for _suggest_kind heuristic."""
import pytest


@pytest.mark.parametrize('name,expected', [
    ('water-tank-01',     'tank'),
    ('Reservoir',         'tank'),
    ('flour silo',        'silo'),
    ('hopper-A',           'silo'),
    ('PUMP-42',           'pump'),
    ('main motor',        'motor'),
    ('drive_unit',        'motor'),
    ('valve V-01',        'valve'),
    ('Mixer ALPHA',       'mixer'),
    ('blender',           'mixer'),
    ('agitator',          'mixer'),
    ('reactor-1',         'reactor'),
    ('fermenter',         'reactor'),
    ('belt conveyor',     'conveyor'),
    ('vessel-X',          'vessel'),
    ('kettle 5',          'vessel'),
    ('heat exchanger',    'heat_exchanger'),
    ('heat-exchanger',    'heat_exchanger'),
    ('hx-3',              'heat_exchanger'),
    ('compressor',        'compressor'),
    ('something-random',  'generic'),
    ('',                  'generic'),
])
def test_suggest_kind(app_module, name, expected):
    assert app_module._suggest_kind(name) == expected


def test_suggest_kind_none(app_module):
    assert app_module._suggest_kind(None) == 'generic'


def test_suggest_kind_is_case_insensitive(app_module):
    assert app_module._suggest_kind('TANK') == 'tank'
    assert app_module._suggest_kind('Tank-99') == 'tank'

import json

from json_persistence import load_json, save_json_atomic


def test_save_json_atomic_writes_readable_json(tmp_path):
    path = tmp_path / 'state.json'
    data = {'name': 'Ångström', 'items': [1, 2, 3]}

    assert save_json_atomic(str(path), data, ensure_ascii=False)

    assert json.loads(path.read_text(encoding='utf-8')) == data
    assert 'Ångström' in path.read_text(encoding='utf-8')


def test_load_json_returns_default_for_missing_file(tmp_path):
    path = tmp_path / 'missing.json'

    assert load_json(str(path), {'fallback': True}) == {'fallback': True}

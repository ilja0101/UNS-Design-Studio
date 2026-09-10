"""Chat attachments: a workbook in, rows the model can read out — within budget.

The motivating case is a topic policy kept in Excel. The model must see the
rows, not a base64 blob; a big file must not cost a context window; and the
standalone MCP process must be able to page a file it does not have on disk.
"""
import io
import json

import openpyxl
import pytest

from uds_agent import attachments as att
from uds_agent import loop as agent_loop
from uds_agent import policy as policy_mod
from uds_agent import settings as agent_settings
from uds_agent import store
from uds_agent import tools as tools_mod

from tests.test_agent_tools import FakeBackend


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(att, 'attachments_dir', lambda: _mk(tmp_path / 'att'))
    monkeypatch.setattr(store, 'conversations_dir', lambda: _mk(tmp_path / 'convos'))
    monkeypatch.setattr(agent_settings, 'settings_file', lambda: str(tmp_path / 'agent.json'))
    monkeypatch.setattr(policy_mod, 'policy_file', lambda: str(tmp_path / 'topic_policy.json'))
    monkeypatch.setattr(tools_mod, 'snapshots_dir', lambda: _mk(tmp_path / 'snaps'))
    att._render_cache.clear()
    return tmp_path


def _mk(p):
    p.mkdir(exist_ok=True)
    return str(p)


def workbook(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


POLICY_ROWS = [
    ['Rule', 'Value', 'Notes'],
    ['separator', '.', 'NATS style'],
    ['prefix', 'uns', None],
    ['levels', 'enterprise > site > area > workUnit', 'workUnit optional'],
    ['node case', 'kebab', None],
    ['tag case', 'snake', None],
    [None, None, None],
    ['forbidden', 'test, tmp, old', 'never in production topics'],
]


# ── storage and extraction ──────────────────────────────────────────────────

def test_a_workbook_is_stored_with_its_sheet_shapes(data):
    meta = att.save('Topic Policy.xlsx', workbook({'Policy': POLICY_ROWS, 'Empty': []}))
    assert meta['kind'] == 'table'
    assert meta['name'] == 'Topic Policy.xlsx'
    # the blank row is dropped, the empty sheet reports zero
    assert meta['sheets'] == [{'name': 'Policy', 'rows': 7, 'cols': 3},
                              {'name': 'Empty', 'rows': 0, 'cols': 0}]
    assert att.load(meta['id'])['size'] == meta['size']
    assert [m['id'] for m in att.listing()] == [meta['id']]


def test_the_model_sees_the_rows_not_a_blob(data):
    meta = att.save('policy.xlsx', workbook({'Policy': POLICY_ROWS}))
    text = att.render(meta)
    assert text.startswith('[Attachment "policy.xlsx" · table')
    assert 'Sheet "Policy" (7 rows × 3 columns):' in text
    assert 'separator | . | NATS style' in text
    assert 'levels | enterprise > site > area > workUnit | workUnit optional' in text
    assert 'base64' not in text


def test_csv_is_sniffed_and_trimmed(data):
    meta = att.save('tags.csv', b'name;unit;profile\r\nflow_rate;m3/h;noise\r\n;;\r\ntemp;degC;ramp\r\n')
    assert meta['sheets'] == [{'name': 'tags', 'rows': 3, 'cols': 3}]
    assert 'flow_rate | m3/h | noise' in att.render(meta)


def test_text_files_are_inlined_verbatim(data):
    meta = att.save('policy.md', '# Policy\n\nNames are kebab-case — always.\n'.encode('utf-8'))
    assert meta['kind'] == 'text'
    assert 'Names are kebab-case — always.' in att.render(meta)


def test_a_binary_we_cannot_read_is_named_but_not_pretended(data):
    meta = att.save('drawing.pdf', b'%PDF-1.7 ...')
    assert meta['kind'] == 'other'
    text = att.render(meta)
    assert 'drawing.pdf' in text and 'cannot read' in text


def test_a_corrupt_workbook_degrades_to_other_with_a_reason(data):
    meta = att.save('broken.xlsx', b'this is not a zip')
    assert meta['kind'] == 'other'
    assert 'openpyxl' in meta['note']


def test_upload_limits(data):
    with pytest.raises(att.AttachmentError):
        att.save('empty.csv', b'')
    with pytest.raises(att.AttachmentError):
        att.save('huge.bin', b'x' * (att.MAX_BYTES + 1))


def test_file_names_are_sanitised(data):
    meta = att.save('../../etc/passwd', b'root:x')
    assert meta['name'] == 'passwd'
    assert att.file_path(meta).startswith(att.attachments_dir())


# ── the budget: tokens are money ────────────────────────────────────────────

def test_a_big_sheet_is_cut_and_the_model_told_how_to_page(data):
    rows = [['id', 'name', 'unit']] + [[i, f'tag_{i:04d}', 'degC'] for i in range(1500)]
    meta = att.save('tags.xlsx', workbook({'Tags': rows}))
    text = att.render(meta)
    assert len(text) <= att.INLINE_BUDGET + 200
    assert 'more rows — attachment_read id="%s" sheet="Tags" offset=' % meta['id'] in text
    # and paging picks up where the inline block stopped
    page = att.read_page(meta, sheet='Tags', offset=1000, limit=5)
    assert page['total'] == 1501
    assert page['rows'][0] == ['999', 'tag_0999', 'degC']


def test_paging_a_text_file_by_line(data):
    meta = att.save('notes.txt', ('line %d\n' * 50 % tuple(range(50))).encode())
    page = att.read_page(meta, offset=48, limit=10)
    assert page['total'] == 50 and page['lines'] == ['line 48', 'line 49']


def test_paging_an_unknown_sheet_names_the_real_ones(data):
    meta = att.save('p.xlsx', workbook({'Policy': POLICY_ROWS}))
    with pytest.raises(att.AttachmentError, match='sheets: Policy'):
        att.read_page(meta, sheet='Nope')


def test_several_attachments_share_the_message_budget(data):
    big = [['n', 'v']] + [[i, 'x' * 60] for i in range(800)]
    ids = [att.public(att.save(f'f{i}.xlsx', workbook({'S': big}))) for i in range(4)]
    content = att.model_content('here you go', ids)
    assert isinstance(content, str)
    assert content.startswith('here you go\n\nAttached files:')
    assert len(content) <= att.MESSAGE_BUDGET + 4 * 800   # every file present, all bounded
    assert content.count('[Attachment "f') == 4


# ── what the model receives ─────────────────────────────────────────────────

def test_an_image_becomes_an_image_url_part_and_stays_out_of_the_json(data):
    png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
    meta = att.save('pid.png', png, 'image/png')
    convo = store.create('t')
    store.append(convo, {'role': 'user', 'content': 'what is this?',
                         'attachments': [att.public(meta)]})
    store.save(convo)
    # the conversation file holds the metadata, never the bytes
    assert 'base64' not in json.dumps(store.load(convo['id']))
    content = store.for_model(convo)[0]['content']
    assert isinstance(content, list)
    assert content[0] == {'type': 'text', 'text': 'what is this?\n\nAttached files:\n\n'
                          + att.render(meta)}
    assert content[1]['type'] == 'image_url'
    assert content[1]['image_url']['url'].startswith('data:image/png;base64,')


def test_a_deleted_attachment_is_reported_not_crashed(data):
    meta = att.save('p.csv', b'a,b\n1,2\n')
    convo = store.create('t')
    store.append(convo, {'role': 'user', 'content': 'x', 'attachments': [att.public(meta)]})
    att.delete(meta['id'])
    content = store.for_model(convo)[0]['content']
    assert '[Attachment "p.csv" is no longer available]' in content


async def test_the_turn_stores_the_metadata_and_titles_from_the_file(data, monkeypatch):
    """No text, just a file: the model still gets the rows and the chat gets a name."""
    from tests.test_agent_loop import script
    agent_settings.save({'endpoint': 'http://mock/v1', 'apiKey': 'k', 'model': 'm'})
    adapter = script(monkeypatch, [{'text_chunks': ['Stored the policy.']}])
    meta = att.public(att.save('Topic Policy.xlsx', workbook({'Policy': POLICY_ROWS})))
    convo = store.create('New chat')
    events = [e async for e in agent_loop.run_turn(FakeBackend(), convo, '', attachments=[meta])]
    assert events[-1]['type'] == 'done'
    assert convo['title'] == 'Topic Policy.xlsx'
    stored = store.load(convo['id'])['messages'][0]
    assert stored['attachments'] == [meta] and stored['content'] == ''
    sent = adapter.seen[0]['messages'][0]['content']
    assert 'separator | . | NATS style' in sent


# ── the tools, through the backend ──────────────────────────────────────────

async def test_attachment_read_pages_through_the_backend(data):
    """The standalone MCP process has no file on disk; it asks the UDS."""
    meta = att.save('p.xlsx', workbook({'Policy': POLICY_ROWS}))
    seen = {}

    class Backend(FakeBackend):
        async def call(self, method, path, body=None, params=None):
            seen.update(method=method, path=path, params=params)
            return att.read_page(att.load(meta['id']), **{k: v for k, v in (params or {}).items()})

    res = await tools_mod.call(Backend(), 'attachment_read',
                               {'id': meta['id'], 'sheet': 'Policy', 'offset': 1, 'limit': 2})
    assert seen['method'] == 'GET'
    assert seen['path'] == f'/api/agent/attachments/{meta["id"]}/read'
    assert seen['params'] == {'sheet': 'Policy', 'offset': 1, 'limit': 2}
    assert res['rows'] == [['separator', '.', 'NATS style'], ['prefix', 'uns', '']]


def test_both_attachment_tools_are_read_only_and_in_the_registry():
    names = {t.name: t for t in tools_mod.registry(include_writes=False)}
    assert 'attachment_list' in names and 'attachment_read' in names
    assert not names['attachment_read'].writes

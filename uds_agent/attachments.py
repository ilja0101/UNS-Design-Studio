"""Files handed to the agent in chat — a topic policy in Excel, a tag list, a P&ID.

The point of an attachment is that the person already has the document; typing
a spreadsheet into a chat box is not a workflow. So a file is uploaded once,
kept under ``agent/attachments/``, and shown to the model in the cheapest
faithful form we can make of it:

* **Tables** (``.xlsx``/``.xlsm``/``.csv``/``.tsv``) become pipe-separated rows,
  one block per sheet, trimmed of empty rows and columns. A policy written as
  a spreadsheet arrives as the spreadsheet, not as a base64 blob the model
  cannot read.
* **Text** (``.txt``/``.md``/``.json``/``.yaml``/``.xml``…) is inlined as-is.
* **Images** ride as an OpenAI ``image_url`` content part, which every door
  forwards verbatim -- the gateway included.
* Anything else is stored and named, and the model is told it cannot read it.

Tokens are money on the lab, so what goes inline is **bounded**: each file gets
:data:`INLINE_BUDGET` characters in the user message and the model is told how
to page the rest with ``attachment_read``. That tool goes through the backend
like every other, so it works from the standalone MCP process too, where the
file itself is not on disk.
"""

from __future__ import annotations

import base64
import csv
import io
import mimetypes
import os
import re
import secrets
import shutil
import time
from typing import Any

from json_persistence import load_json, save_json_atomic
from uds_agent.paths import attachments_dir

MAX_BYTES = 20 * 1024 * 1024
INLINE_BUDGET = 12_000       # characters per attachment in the user message
MESSAGE_BUDGET = 30_000      # across all attachments on one message
MAX_ROWS = 2_000             # rows read per sheet, whichever comes first
MAX_COLS = 64
PAGE_ROWS = 200              # what one attachment_read returns by default

TABLE_EXT = {'.xlsx', '.xlsm', '.csv', '.tsv'}
TEXT_EXT = {'.txt', '.md', '.markdown', '.json', '.yaml', '.yml', '.xml', '.toml', '.ini',
            '.cfg', '.conf', '.log', '.py', '.js', '.ts', '.sql', '.html', '.htm'}
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}

_render_cache: dict[str, tuple[float, str]] = {}


class AttachmentError(ValueError):
    """Bad upload or unreadable file — the caller's problem, phrased for them."""


# ── storage ─────────────────────────────────────────────────────────────────

def new_id() -> str:
    return 'att-' + time.strftime('%Y%m%d', time.gmtime()) + '-' + secrets.token_hex(4)


def safe_name(name: str) -> str:
    base = os.path.basename(str(name or '').replace('\\', '/')).strip() or 'file'
    base = re.sub(r'[^\w.\- ()]+', '_', base)
    return base[:120]


def kind_of(name: str, mime: str = '') -> str:
    ext = os.path.splitext(name.lower())[1]
    if ext in TABLE_EXT:
        return 'table'
    if ext in IMAGE_EXT or (mime or '').startswith('image/'):
        return 'image'
    if ext in TEXT_EXT or (mime or '').startswith('text/'):
        return 'text'
    return 'other'


def _meta_path(aid: str) -> str:
    safe = ''.join(ch for ch in str(aid) if ch.isalnum() or ch in '-_')
    if not safe:
        raise AttachmentError('invalid attachment id')
    return os.path.join(attachments_dir(), safe + '.json')


def _blob_dir(aid: str) -> str:
    return _meta_path(aid)[:-5]


def save(name: str, data: bytes, mime: str = '') -> dict:
    """Store one upload and return its public metadata."""
    if not data:
        raise AttachmentError(f'{name or "file"} is empty')
    if len(data) > MAX_BYTES:
        raise AttachmentError(f'{name} is {len(data) // (1024 * 1024)} MB; the limit is '
                              f'{MAX_BYTES // (1024 * 1024)} MB')
    aid = new_id()
    fname = safe_name(name)
    meta = {
        'id': aid, 'name': fname, 'size': len(data),
        # curl and some browsers send octet-stream for a workbook; the name knows better.
        'mime': (mime if mime and mime != 'application/octet-stream' else '')
                or mimetypes.guess_type(fname)[0] or 'application/octet-stream',
        'kind': kind_of(fname, mime), 'ts': _now(),
    }
    os.makedirs(_blob_dir(aid), exist_ok=True)
    with open(os.path.join(_blob_dir(aid), fname), 'wb') as fh:
        fh.write(data)
    # A table's shape is worth knowing without opening it again.
    if meta['kind'] == 'table':
        try:
            meta['sheets'] = [{'name': s, 'rows': len(rows), 'cols': max((len(r) for r in rows), default=0)}
                              for s, rows in _tables(meta).items()]
        except AttachmentError as exc:
            meta['kind'] = 'other'
            meta['note'] = str(exc)
    save_json_atomic(_meta_path(aid), meta, ensure_ascii=False, label='attachment')
    return meta


def load(aid: str) -> dict | None:
    meta = load_json(_meta_path(aid), None, label='attachment')
    return meta if isinstance(meta, dict) and meta.get('id') else None


def file_path(meta: dict) -> str:
    return os.path.join(_blob_dir(meta['id']), meta['name'])


def read_bytes(meta: dict) -> bytes:
    try:
        with open(file_path(meta), 'rb') as fh:
            return fh.read()
    except OSError as exc:
        raise AttachmentError(f'{meta.get("name")} is no longer on disk: {exc}') from exc


def delete(aid: str) -> bool:
    ok = False
    try:
        os.unlink(_meta_path(aid))
        ok = True
    except OSError:
        pass
    shutil.rmtree(_blob_dir(aid), ignore_errors=True)
    _render_cache.pop(aid, None)
    return ok


def listing() -> list[dict]:
    out = []
    try:
        files = os.listdir(attachments_dir())
    except OSError:
        return out
    for f in files:
        if f.endswith('.json'):
            meta = load_json(os.path.join(attachments_dir(), f), None, label='attachment')
            if isinstance(meta, dict) and meta.get('id'):
                out.append(meta)
    return sorted(out, key=lambda m: m.get('ts', ''), reverse=True)


def public(meta: dict) -> dict:
    """What the browser and the stored message keep: no paths, no content."""
    return {k: meta[k] for k in ('id', 'name', 'size', 'mime', 'kind', 'ts', 'sheets', 'note')
            if k in meta}


# ── extraction ──────────────────────────────────────────────────────────────

def _tables(meta: dict) -> dict[str, list[list[str]]]:
    """Every sheet as rows of strings, empty rows/columns dropped, capped."""
    name = meta['name']
    ext = os.path.splitext(name.lower())[1]
    data = read_bytes(meta)
    if ext in ('.csv', '.tsv'):
        text = _decode(data)
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel_tab if ext == '.tsv' else csv.excel
        rows = [[_cell(c) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
        return {os.path.splitext(name)[0]: _trim(rows)}
    try:
        import openpyxl
    except ImportError as exc:   # pragma: no cover — requirements.txt carries it
        raise AttachmentError('reading Excel needs the openpyxl package') from exc
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AttachmentError(f'{name} is not a workbook openpyxl can read: {exc}') from exc
    out: dict[str, list[list[str]]] = {}
    for ws in wb.worksheets:
        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= MAX_ROWS:
                break
            rows.append([_cell(c) for c in row[:MAX_COLS]])
        out[ws.title] = _trim(rows)
    wb.close()
    return out


def _cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _trim(rows: list[list[str]]) -> list[list[str]]:
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    used = [i for i in range(width) if any(i < len(r) and r[i] for r in rows)]
    return [[r[i] if i < len(r) else '' for i in used] for r in rows]


def _decode(data: bytes) -> str:
    for enc in ('utf-8-sig', 'utf-16'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1')


def read_page(meta: dict, *, sheet: str = '', offset: int = 0, limit: int = PAGE_ROWS) -> dict:
    """One page of an attachment, for ``attachment_read``."""
    kind = meta.get('kind')
    offset = max(0, int(offset or 0))
    limit = max(1, min(1000, int(limit or PAGE_ROWS)))
    if kind == 'table':
        tables = _tables(meta)
        if not tables:
            return {'id': meta['id'], 'name': meta['name'], 'rows': [], 'total': 0}
        if sheet and sheet not in tables:
            raise AttachmentError(f'no sheet "{sheet}" in {meta["name"]}; sheets: '
                                  + ', '.join(tables))
        title = sheet or next(iter(tables))
        rows = tables[title]
        return {'id': meta['id'], 'name': meta['name'], 'sheet': title,
                'sheets': list(tables), 'offset': offset, 'total': len(rows),
                'rows': rows[offset:offset + limit]}
    if kind == 'text':
        lines = _decode(read_bytes(meta)).splitlines()
        return {'id': meta['id'], 'name': meta['name'], 'offset': offset, 'total': len(lines),
                'lines': lines[offset:offset + limit]}
    raise AttachmentError(f'{meta["name"]} is a {kind or "binary"} file; there is no text to page')


# ── what the model sees ─────────────────────────────────────────────────────

def render(meta: dict, budget: int = INLINE_BUDGET) -> str:
    """The inline block for one attachment, within ``budget`` characters."""
    aid = meta['id']
    mtime = os.path.getmtime(file_path(meta)) if os.path.exists(file_path(meta)) else 0.0
    cached = _render_cache.get(aid)
    if cached and cached[0] == mtime and budget == INLINE_BUDGET:
        return cached[1]
    text = _render(meta, budget)
    if budget == INLINE_BUDGET:
        _render_cache[aid] = (mtime, text)
        if len(_render_cache) > 64:
            _render_cache.pop(next(iter(_render_cache)))
    return text


def _render(meta: dict, budget: int) -> str:
    head = f'[Attachment "{meta["name"]}" · {meta.get("kind")} · {_size(meta.get("size", 0))} · id {meta["id"]}]'
    kind = meta.get('kind')
    try:
        if kind == 'table':
            return head + '\n' + _render_tables(meta, budget - len(head))
        if kind == 'text':
            body = _decode(read_bytes(meta))
            if len(body) > budget:
                shown = body[:budget]
                return (f'{head}\n{shown}\n…(showing {len(shown):,} of {len(body):,} characters — '
                        f'attachment_read with offset pages the rest by line)')
            return head + '\n' + body
        if kind == 'image':
            return head + ' (the image itself is attached to this message)'
    except AttachmentError as exc:
        return f'{head} — could not be read: {exc}'
    note = meta.get('note') or 'a format the agent cannot read; ask the user for CSV, Excel or text'
    return f'{head} — {note}'


def _render_tables(meta: dict, budget: int) -> str:
    tables = _tables(meta)
    if not tables:
        return '(no non-empty cells)'
    per_sheet = max(400, budget // max(1, len(tables)))
    parts = []
    for title, rows in tables.items():
        lines = [f'Sheet "{title}" ({len(rows)} rows × {max((len(r) for r in rows), default=0)} columns):']
        used = len(lines[0])
        shown = 0
        for r in rows:
            line = ' | '.join(r)
            if used + len(line) + 1 > per_sheet:
                break
            lines.append(line)
            used += len(line) + 1
            shown += 1
        if shown < len(rows):
            lines.append(f'…({len(rows) - shown} more rows — attachment_read id="{meta["id"]}" '
                         f'sheet="{title}" offset={shown} reads on)')
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


def model_content(text: str, attachments: list[dict]) -> str | list[dict]:
    """The user message as the model receives it: text, inline blocks, image parts.

    Returns a plain string unless an image is among the attachments, in which
    case it is the OpenAI content-part list; both doors forward either.
    """
    metas = [load(a.get('id', '')) or {**a, 'missing': True} for a in attachments or []]
    blocks, images = [], []
    spent = 0
    for m in metas:
        if m.get('missing'):
            blocks.append(f'[Attachment "{m.get("name", "?")}" is no longer available]')
            continue
        if m.get('kind') == 'image':
            try:
                data = read_bytes(m)
                url = f'data:{m.get("mime") or "image/png"};base64,' + base64.b64encode(data).decode('ascii')
                images.append({'type': 'image_url', 'image_url': {'url': url}})
                blocks.append(render(m))
            except AttachmentError as exc:
                blocks.append(f'[Attachment "{m["name"]}" could not be read: {exc}]')
            continue
        block = render(m, max(600, min(INLINE_BUDGET, MESSAGE_BUDGET - spent)))
        spent += len(block)
        blocks.append(block)
    body = (text or '').strip()
    if blocks:
        body = (body + '\n\n' if body else '') + 'Attached files:\n\n' + '\n\n'.join(blocks)
    if not images:
        return body
    return [{'type': 'text', 'text': body}, *images]


def _size(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f'{n} B'
    if n < 1024 * 1024:
        return f'{n / 1024:.0f} kB'
    return f'{n / (1024 * 1024):.1f} MB'


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


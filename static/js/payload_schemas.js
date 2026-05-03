// ── Sample values for preview ──────────────────────────────────────────────
  const SAMPLE = {
    value:          42.5,
    ts_epoch:       1713523200,
    ts_ms:          1713523200000,
    ts_iso:         '2024-04-19T12:00:00.000Z',
    quality:        'good',
    is_good:        true,
    quality_code:   192,
    unit:           'kW',
    dataType:       'Float',
    tagName:        'CurrentPowerkW',
    topicPath:      'GlobalFoodCo.CrispCraft.Antwerp.ProductionLine.Energy.CurrentPowerkW',
    siteName:       'Antwerp',
    workCenterName: 'Energy',
  };

  const SOURCE_OPTIONS = [
    { v: 'value',           l: 'value — raw tag value' },
    { v: 'ts_epoch',        l: 'ts_epoch — Unix timestamp (s)' },
    { v: 'ts_ms',           l: 'ts_ms — Unix timestamp (ms)' },
    { v: 'ts_iso',          l: 'ts_iso — ISO 8601 string' },
    { v: 'quality',         l: 'quality — \'good\'/\'bad\'' },
    { v: 'is_good',         l: 'is_good — true/false' },
    { v: 'quality_code',    l: 'quality_code — 192/0 (OPC-UA)' },
    { v: 'unit',            l: 'unit — engineering unit' },
    { v: 'dataType',        l: 'dataType — tag data type' },
    { v: 'tagName',         l: 'tagName — last topic segment' },
    { v: 'topicPath',       l: 'topicPath — full topic string' },
    { v: 'siteName',        l: 'siteName — site name' },
    { v: 'workCenterName',  l: 'workCenterName — work center name' },
    { v: 'static',          l: 'static — fixed value' },
  ];

  // ── State ──────────────────────────────────────────────────────────────────
  let schemas = [];      // [{id, name, description, fields:[{key,source,staticVal}]}]
  let activeId = null;
  let previewCollapsed = false;

  // ── DOM refs ───────────────────────────────────────────────────────────────
  const schemaListEl    = document.getElementById('schema-list');
  const emptyStateEl    = document.getElementById('empty-state');
  const schemaEditorEl  = document.getElementById('schema-editor');
  const schemaNameEl    = document.getElementById('schema-name');
  const schemaDescEl    = document.getElementById('schema-desc');
  const fieldsTbody     = document.getElementById('fields-tbody');
  const previewJson     = document.getElementById('preview-json');
  const saveInd         = document.getElementById('save-ind');
  const previewHeader   = document.getElementById('preview-toggle-header');
  const previewLabel    = document.getElementById('preview-toggle-label');

  // ── Toast ──────────────────────────────────────────────────────────────────
  function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.getElementById('toast-container').appendChild(el);
    setTimeout(() => {
      el.classList.add('fade-out');
      el.addEventListener('animationend', () => el.remove());
    }, 2800);
  }

  // ── Save indicator ─────────────────────────────────────────────────────────
  function markUnsaved() {
    saveInd.textContent = '● Unsaved';
    saveInd.className = '';
  }
  function markSaved() {
    saveInd.textContent = '● Saved';
    saveInd.className = 'saved';
  }

  // ── Render sidebar list ────────────────────────────────────────────────────
  function renderList() {
    schemaListEl.innerHTML = '';
    schemas.forEach(s => {
      const li = document.createElement('li');
      if (s.id === activeId) li.classList.add('active');

      const nameSpan = document.createElement('span');
      nameSpan.className = 'schema-name';
      nameSpan.textContent = s.name || '(unnamed)';

      const delBtn = document.createElement('button');
      delBtn.className = 'btn-icon';
      delBtn.textContent = '✕';
      delBtn.title = 'Delete schema';
      delBtn.addEventListener('click', e => {
        e.stopPropagation();
        deleteSchema(s.id);
      });

      li.appendChild(nameSpan);
      li.appendChild(delBtn);
      li.addEventListener('click', () => selectSchema(s.id));
      schemaListEl.appendChild(li);
    });
  }

  // ── Select a schema ────────────────────────────────────────────────────────
  function selectSchema(id) {
    activeId = id;
    const s = schemas.find(x => x.id === id);
    if (!s) {
      showEmptyState();
      return;
    }
    emptyStateEl.style.display = 'none';
    schemaEditorEl.style.display = 'flex';
    schemaNameEl.value = s.name || '';
    schemaDescEl.value = s.description || '';
    renderFields(s.fields || []);
    updatePreview();
    renderList();
  }

  function showEmptyState() {
    emptyStateEl.style.display = 'flex';
    schemaEditorEl.style.display = 'none';
    activeId = null;
    renderList();
  }

  // ── Delete schema ──────────────────────────────────────────────────────────
  function deleteSchema(id) {
    schemas = schemas.filter(s => s.id !== id);
    if (activeId === id) showEmptyState();
    renderList();
    markUnsaved();
  }

  // ── New schema ─────────────────────────────────────────────────────────────
  document.getElementById('btn-new').addEventListener('click', () => {
    const newSchema = {
      id:          'schema-' + Date.now(),
      name:        'New Schema',
      description: '',
      fields:      [],
    };
    schemas.push(newSchema);
    renderList();
    selectSchema(newSchema.id);
    markUnsaved();
    schemaNameEl.focus();
    schemaNameEl.select();
  });

  // ── Render fields table ────────────────────────────────────────────────────
  function renderFields(fields) {
    fieldsTbody.innerHTML = '';
    fields.forEach((f, idx) => addFieldRow(f.key, f.source, f.staticVal));
  }

  function addFieldRow(key = '', source = 'value', staticVal = '') {
    const tr = document.createElement('tr');

    // Key cell
    const tdKey = document.createElement('td');
    tdKey.className = 'col-key';
    const keyInput = document.createElement('input');
    keyInput.type = 'text';
    keyInput.placeholder = 'e.g. v';
    keyInput.value = key;
    keyInput.addEventListener('input', onEditorChange);
    tdKey.appendChild(keyInput);

    // Source cell
    const tdSource = document.createElement('td');
    tdSource.className = 'col-source';
    const srcSelect = document.createElement('select');
    SOURCE_OPTIONS.forEach(opt => {
      const o = document.createElement('option');
      o.value = opt.v;
      o.textContent = opt.l;
      if (opt.v === source) o.selected = true;
      srcSelect.appendChild(o);
    });
    srcSelect.addEventListener('change', () => {
      toggleStaticInput(tr, srcSelect.value === 'static');
      onEditorChange();
    });
    tdSource.appendChild(srcSelect);

    // Static val cell
    const tdStatic = document.createElement('td');
    tdStatic.className = 'col-static';
    const staticInput = document.createElement('input');
    staticInput.type = 'text';
    staticInput.className = 'static-val-input' + (source === 'static' ? ' visible' : '');
    staticInput.placeholder = 'fixed value';
    staticInput.value = staticVal || '';
    staticInput.addEventListener('input', onEditorChange);
    tdStatic.appendChild(staticInput);

    // Delete cell
    const tdDel = document.createElement('td');
    tdDel.className = 'col-del';
    const delBtn = document.createElement('button');
    delBtn.className = 'btn-icon';
    delBtn.textContent = '✕';
    delBtn.title = 'Remove field';
    delBtn.addEventListener('click', () => {
      tr.remove();
      onEditorChange();
    });
    tdDel.appendChild(delBtn);

    tr.appendChild(tdKey);
    tr.appendChild(tdSource);
    tr.appendChild(tdStatic);
    tr.appendChild(tdDel);
    fieldsTbody.appendChild(tr);
  }

  function toggleStaticInput(tr, show) {
    const inp = tr.querySelector('.static-val-input');
    if (inp) inp.classList.toggle('visible', show);
  }

  // ── Add field button ───────────────────────────────────────────────────────
  document.getElementById('btn-add-field').addEventListener('click', () => {
    if (!activeId) return;
    addFieldRow('', 'value', '');
    onEditorChange();
  });

  // ── Collect current editor state into active schema ────────────────────────
  function collectActiveSchema() {
    if (!activeId) return;
    const s = schemas.find(x => x.id === activeId);
    if (!s) return;
    s.name        = schemaNameEl.value.trim() || 'Unnamed Schema';
    s.description = schemaDescEl.value.trim();
    s.fields = [];
    fieldsTbody.querySelectorAll('tr').forEach(tr => {
      const key    = tr.querySelector('td.col-key input').value.trim();
      const source = tr.querySelector('td.col-source select').value;
      const sv     = tr.querySelector('td.col-static input').value;
      s.fields.push({ key, source, staticVal: source === 'static' ? sv : '' });
    });
    // Update sidebar name
    renderList();
  }

  // ── On any editor change ───────────────────────────────────────────────────
  function onEditorChange() {
    collectActiveSchema();
    updatePreview();
    markUnsaved();
  }

  schemaNameEl.addEventListener('input', onEditorChange);
  schemaDescEl.addEventListener('input', onEditorChange);

  // ── Live JSON Preview ──────────────────────────────────────────────────────
  function buildPreviewPayload() {
    if (!activeId) return {};
    const s = schemas.find(x => x.id === activeId);
    if (!s || !s.fields || s.fields.length === 0) return {};
    const obj = {};
    s.fields.forEach(f => {
      if (!f.key) return;
      if (f.source === 'static') {
        // Try to parse as number/bool, else keep as string
        const raw = f.staticVal;
        if (raw === 'true')       obj[f.key] = true;
        else if (raw === 'false') obj[f.key] = false;
        else if (raw !== '' && !isNaN(Number(raw))) obj[f.key] = Number(raw);
        else obj[f.key] = raw;
      } else {
        obj[f.key] = SAMPLE[f.source] !== undefined ? SAMPLE[f.source] : null;
      }
    });
    return obj;
  }

  function updatePreview() {
    const payload = buildPreviewPayload();
    previewJson.textContent = JSON.stringify(payload, null, 2);
  }

  // ── Preview collapse toggle ────────────────────────────────────────────────
  previewHeader.addEventListener('click', () => {
    previewCollapsed = !previewCollapsed;
    previewJson.classList.toggle('collapsed', previewCollapsed);
    previewLabel.textContent = previewCollapsed ? '▶ expand' : '▼ collapse';
  });

  // ── Save All ───────────────────────────────────────────────────────────────
  document.getElementById('btn-save-all').addEventListener('click', async () => {
    collectActiveSchema();
    try {
      const res = await fetch('/api/payload-schemas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schemas }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      markSaved();
      toast('Schemas saved successfully.', 'ok');
    } catch (err) {
      console.error('Save failed:', err);
      toast('Save failed: ' + err.message, 'err');
    }
  });

  // ── Initial load ───────────────────────────────────────────────────────────
  async function loadSchemas() {
    try {
      const res = await fetch('/api/payload-schemas');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      schemas = Array.isArray(data.schemas) ? data.schemas : [];
      renderList();
      if (schemas.length > 0) {
        selectSchema(schemas[0].id);
      } else {
        showEmptyState();
      }
      markSaved();
    } catch (err) {
      console.warn('Could not load schemas from API:', err.message);
      // Start with empty list — this is fine for offline/dev use
      schemas = [];
      renderList();
      showEmptyState();
      toast('Could not reach API — starting empty.', 'info');
    }
  }

  loadSchemas();

  function toggleTheme() {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('uns-theme', next);
  }

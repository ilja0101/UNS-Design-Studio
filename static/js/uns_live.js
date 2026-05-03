// ── State ──────────────────────────────────────────────────────────────────────
let client      = null;
let treeData    = {};     // nested: {children:{}, value:null, ts:0, msgCount:0}
let expanded    = new Set();
let selected    = null;
let filterQ     = '';
let msgCount    = 0;
let leafCount   = 0;
let rateCounter = 0;
let rateDisplay = 0;

// ── Stats ──────────────────────────────────────────────────────────────────────
setInterval(() => {
  rateDisplay = rateCounter;
  rateCounter = 0;
  document.getElementById('stat-rate').textContent = rateDisplay;
}, 1000);

function eid(id) { return document.getElementById(id) }

// ── Connection ─────────────────────────────────────────────────────────────────
function connect() {
  const host  = eid('cfg-host').value.trim() || 'localhost';
  const port  = parseInt(eid('cfg-port').value) || 8083;
  const path  = eid('cfg-path').value.trim() || '/mqtt';
  const user  = eid('cfg-user').value.trim();
  const pass  = eid('cfg-pass').value;
  const topic = eid('cfg-topic').value.trim() || '#';

  setStatus('yellow', 'Connecting…');

  const opts = {
    clientId:       'uns-live-' + Math.random().toString(16).substr(2, 8),
    clean:          true,
    reconnectPeriod: 3000,
  };
  if (user) { opts.username = user; opts.password = pass; }

  const url = `ws://${host}:${port}${path}`;
  client = mqtt.connect(url, opts);

  client.on('connect', () => {
    setStatus('green', `Connected — ${host}:${port}`);
    eid('btn-connect').style.display    = 'none';
    eid('btn-disconnect').style.display = '';
    client.subscribe(topic, { qos: 0 });
  });

  client.on('message', (t, msg) => {
    msgCount++;
    rateCounter++;
    eid('stat-msgs').textContent = msgCount;
    eid('stat-last').style.display = '';
    eid('stat-last-txt').textContent = t.split('/').pop();
    handleMessage(t, msg.toString());
  });

  client.on('error', (e) => {
    setStatus('red', 'Error: ' + e.message);
  });

  client.on('close', () => {
    setStatus('red', 'Disconnected');
    eid('btn-connect').style.display    = '';
    eid('btn-disconnect').style.display = 'none';
  });
}

function disconnect() {
  if (client) { client.end(true); client = null; }
  setStatus('', 'Disconnected');
  eid('btn-connect').style.display    = '';
  eid('btn-disconnect').style.display = 'none';
}

function setStatus(color, txt) {
  const dot = eid('dot');
  dot.className = 'dot' + (color ? ' ' + color : '');
  eid('status-txt').textContent = txt;
}

// ── Tree data ──────────────────────────────────────────────────────────────────
function handleMessage(topic, payload) {
  const parts = topic.split('/');
  let node    = treeData;
  let isNew   = false;

  parts.forEach((part, i) => {
    if (!node[part]) {
      node[part] = { children: {}, value: null, ts: 0, count: 0, isLeaf: false };
      isNew = true;
    }
    if (i === parts.length - 1) {
      node[part].isLeaf = true;
      node[part].value  = payload;
      node[part].ts     = Date.now();
      node[part].count  = (node[part].count || 0) + 1;
      node[part].topic  = topic;
    }
    node = node[part].children;
  });

  if (isNew) {
    leafCount = countLeaves(treeData);
    eid('stat-topics').textContent = leafCount;
    eid('tree-count').textContent  = leafCount + ' leaves';
  }

  renderTree();
  flashNode(topic);

  // Refresh detail if this topic is selected
  if (selected === topic) showDetail(topic);
}

function countLeaves(node) {
  return Object.values(node).reduce((sum, n) => {
    return sum + (n.isLeaf ? 1 : 0) + countLeaves(n.children);
  }, 0);
}

function clearTree() {
  treeData  = {};
  msgCount  = 0;
  leafCount = 0;
  selected  = null;
  expanded.clear();
  eid('stat-topics').textContent = 0;
  eid('stat-msgs').textContent   = 0;
  eid('tree-count').textContent  = '0 leaves';
  eid('detail-body').innerHTML   = '<div class="detail-empty">Click any leaf node to inspect its value</div>';
  renderTree();
}

// ── Render ─────────────────────────────────────────────────────────────────────
function renderTree() {
  const root = eid('tree-root');
  root.innerHTML = '';
  Object.entries(treeData).forEach(([key, node]) => {
    const el = buildNode(key, node, 0, key);
    if (el) root.appendChild(el);
  });
}

function buildNode(key, node, depth, path) {
  const hasChildren = Object.keys(node.children).length > 0;
  const isLeaf      = node.isLeaf;
  const isExp       = expanded.has(path);

  // Filter
  if (filterQ && !pathMatchesFilter(path, node)) return null;

  const wrap = document.createElement('div');
  wrap.className = 't-node';

  const row = document.createElement('div');
  row.className = 't-row' + (selected === path ? ' sel' : '');
  row.style.paddingLeft = (depth * 10 + 6) + 'px';
  row.dataset.path = path;

  // Value display
  let valHtml = '';
  let valClass = 'num';
  if (isLeaf && node.value !== null) {
    let displayVal = node.value;
    try {
      const parsed = JSON.parse(node.value);
      if (typeof parsed === 'object' && parsed !== null) {
        // Show the 'value' field if it exists, otherwise first field
        const v = parsed.value ?? parsed.v ?? Object.values(parsed)[0];
        displayVal = v !== undefined ? String(v) : '{…}';
      } else {
        displayVal = String(parsed);
      }
      if (typeof parsed.value === 'string' || typeof parsed === 'string') valClass = 'str';
      else if (typeof parsed.value === 'boolean' || typeof parsed === 'boolean') valClass = 'bool';
    } catch(e) {
      displayVal = node.value.length > 30 ? node.value.slice(0, 30) + '…' : node.value;
      valClass = 'str';
    }
    valHtml = `<span class="t-val ${valClass}">${esc(displayVal)}</span>`;
  }

  // Age
  let ageHtml = '';
  if (isLeaf && node.ts) {
    const age = Math.floor((Date.now() - node.ts) / 1000);
    ageHtml = `<span class="t-age">${age < 60 ? age + 's' : Math.floor(age/60) + 'm'}</span>`;
  }

  const icon = isLeaf ? '◆' : (isExp ? '▾' : '▸');
  row.innerHTML = `
    <span class="t-exp${hasChildren ? '' : ' inv'}" onclick="toggleExp('${esc(path)}',event)">${isExp ? '▼' : '▶'}</span>
    <span class="t-icon" style="color:${isLeaf ? 'var(--accent)' : 'var(--muted)'}">${icon}</span>
    <span class="t-name${isLeaf ? ' leaf' : ''}">${esc(key)}</span>
    ${valHtml}
    ${ageHtml}
  `;

  if (isLeaf) {
    row.onclick = (e) => { if (!e.target.classList.contains('t-exp')) selectNode(path, node); };
  } else {
    row.onclick = (e) => { if (!e.target.classList.contains('t-exp')) toggleExp(path, e); };
  }

  wrap.appendChild(row);

  if (isExp && hasChildren) {
    const ch = document.createElement('div');
    ch.className = 't-children';
    Object.entries(node.children).forEach(([k, n]) => {
      const el = buildNode(k, n, depth + 1, path + '/' + k);
      if (el) ch.appendChild(el);
    });
    wrap.appendChild(ch);
  }

  return wrap;
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function toggleExp(path, e) {
  if (e) e.stopPropagation();
  expanded.has(path) ? expanded.delete(path) : expanded.add(path);
  renderTree();
}

function filterTree(q) {
  filterQ = q.trim().toLowerCase();
  renderTree();
}

function pathMatchesFilter(path, node) {
  if (!filterQ) return true;
  if (path.toLowerCase().includes(filterQ)) return true;
  if (node.isLeaf && node.value && node.value.toLowerCase().includes(filterQ)) return true;
  return Object.entries(node.children).some(([k, n]) => pathMatchesFilter(path + '/' + k, n));
}

// ── Flash animation on update ──────────────────────────────────────────────────
const flashSet = new Set();
function flashNode(topic) {
  if (flashSet.has(topic)) return;
  flashSet.add(topic);
  setTimeout(() => {
    const row = document.querySelector(`[data-path="${CSS.escape(topic)}"]`);
    if (row) {
      row.classList.add('flash');
      setTimeout(() => { row.classList.remove('flash'); flashSet.delete(topic); }, 400);
    } else {
      flashSet.delete(topic);
    }
  }, 50);
}

// ── Selected node detail ───────────────────────────────────────────────────────
function selectNode(path, node) {
  selected = path;
  renderTree();
  showDetail(path);
}

function showDetail(path) {
  // Find node
  const parts = path.split('/');
  let n = treeData;
  for (const p of parts) {
    if (!n[p]) return;
    n = n[p];
    if (n.children !== undefined && parts.indexOf(p) < parts.length - 1) n = n.children;
  }

  // Re-find correctly
  let cursor = treeData;
  let found  = null;
  for (let i = 0; i < parts.length; i++) {
    if (!cursor[parts[i]]) return;
    found  = cursor[parts[i]];
    cursor = found.children;
  }
  if (!found) return;

  const raw = found.value || '';
  let pretty = raw;
  try { pretty = JSON.stringify(JSON.parse(raw), null, 2); } catch(e) {}

  const age = found.ts ? Math.floor((Date.now() - found.ts) / 1000) : '—';

  eid('detail-body').innerHTML = `
    <div class="detail-topic">${esc(path)}</div>
    <pre class="detail-val">${esc(pretty)}</pre>
    <div class="detail-meta">
      <div class="detail-row"><span class="dk">Last update</span><span class="dv">${age}s ago</span></div>
      <div class="detail-row"><span class="dk">Messages received</span><span class="dv">${found.count || 1}</span></div>
      <div class="detail-row"><span class="dk">Topic depth</span><span class="dv">${path.split('/').length}</span></div>
    </div>
  `;
}

// ── Auto-refresh ages in detail ────────────────────────────────────────────────
setInterval(() => {
  if (selected) showDetail(selected);
  // Refresh age badges in tree (lightweight — just text nodes)
  renderTree();
}, 5000);

// ── Auto-expand first level ────────────────────────────────────────────────────
function autoExpand() {
  Object.keys(treeData).forEach(k => expanded.add(k));
  renderTree();
}

// ── Settings persistence ───────────────────────────────────────────────────────
const SETTINGS_KEY = 'uns-live-settings';

function saveSettings() {
  const settings = {
    host:  eid('cfg-host').value,
    port:  eid('cfg-port').value,
    path:  eid('cfg-path').value,
    topic: eid('cfg-topic').value,
    user:  eid('cfg-user').value,
    // password intentionally not persisted for security
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return;
    const s = JSON.parse(raw);
    if (s.host)  eid('cfg-host').value  = s.host;
    if (s.port)  eid('cfg-port').value  = s.port;
    if (s.path)  eid('cfg-path').value  = s.path;
    if (s.topic) eid('cfg-topic').value = s.topic;
    if (s.user)  eid('cfg-user').value  = s.user;
  } catch(e) {}
}

// Save settings whenever any config field changes
['cfg-host','cfg-port','cfg-path','cfg-topic','cfg-user'].forEach(id => {
  const el = eid(id);
  if (el) el.addEventListener('input', saveSettings);
});

// Load saved settings on page load
loadSettings();

// ── Panel resize ───────────────────────────────────────────────────────────────
(function() {
  const handle = document.getElementById('live-resize');
  const panel  = document.querySelector('.config-panel');
  const KEY    = 'uns-live-config-width';
  const saved  = localStorage.getItem(KEY);
  const w = parseInt(saved, 10);
  if (w > 0) panel.style.width = w + 'px';
  let dragging = false, x0 = 0, w0 = 0;
  handle.addEventListener('mousedown', e => {
    dragging = true; x0 = e.clientX; w0 = panel.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    panel.style.width = Math.max(160, Math.min(w0 + e.clientX - x0, window.innerWidth * 0.7)) + 'px';
  });
  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    localStorage.setItem(KEY, panel.offsetWidth);
  });
  handle.addEventListener('dblclick', () => {
    panel.style.width = '360px';
    localStorage.removeItem(KEY);
  });
})();

function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('uns-theme', next);
}

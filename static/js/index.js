// ── State ──────────────────────────────────────────────────────────────────────
let _ctrl = { group: '', plant: '', short: '', stateVal: null };
let _anom = { group: '', plant: '', short: '', category: '', overrides: {} };
let _logOpen = false;
let _serverLogs = [];
let _pollTimer = null;
let _plantsCache = {};
let _structureHash = null;
let _serverRunning = false;

// ── Polling ────────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const r = await fetch('/api/status');
    if (!r.ok) return;
    const d = await r.json();
    // Reload page if enterprise structure changed (UNS designer was used)
    if (d.structure_hash) {
      if (_structureHash && _structureHash !== d.structure_hash) {
        location.reload();
        return;
      }
      _structureHash = d.structure_hash;
    }
    _plantsCache = d.plants || {};
    _serverRunning = !!d.server_running;
    updateHeader(d);
    updateCards(_plantsCache);
    updatePlantBreaker(_plantsCache, _serverRunning);
    updateBridgeUI(d);
    // sync host/port inputs
    if (document.activeElement.id !== 'inpHost') document.getElementById('inpHost').value = d.opc_host;
    if (document.activeElement.id !== 'inpPort') document.getElementById('inpPort').value = d.opc_port;
  } catch (e) { }
}

function updateHeader(d) {
  const srvDot = document.getElementById('dotServer');
  const srvLbl = document.getElementById('lblServer');
  const opcDot = document.getElementById('dotOpc');
  const opcLbl = document.getElementById('lblOpc');
  // Update enterprise name from UNS config
  if (d.enterprise_name) {
    const h1 = document.getElementById('enterprise-name');
    if (h1 && h1.textContent !== d.enterprise_name) h1.textContent = d.enterprise_name;
    _enterpriseName = d.enterprise_name;
  }
  if (d.server_running) {
    srvDot.className = 'status-dot green';
    srvLbl.textContent = 'Server: Running';
  } else {
    srvDot.className = 'status-dot red';
    srvLbl.textContent = 'Server: Stopped';
  }
  if (d.opc_connected) {
    opcDot.className = 'status-dot green';
    opcLbl.textContent = `OPC UA: Connected (${d.opc_host}:${d.opc_port})`;
  } else {
    opcDot.className = 'status-dot red';
    opcLbl.textContent = `OPC UA: Disconnected`;
  }
}

function updateCards(plants) {
  for (const [key, p] of Object.entries(plants)) {
    const g = p.group, pl = p.plant;
    const led = document.getElementById(`led-${g}-${pl}`);
    const card = document.getElementById(`card-${g}-${pl}`);
    const maint = document.getElementById(`maint-${g}-${pl}`);
    const recipe = document.getElementById(`recipe-${g}-${pl}`);
    const oeeEl = document.getElementById(`oee-${g}-${pl}`);
    const pwrEl = document.getElementById(`power-${g}-${pl}`);
    const goodEl = document.getElementById(`good-${g}-${pl}`);
    const trEl = document.getElementById(`trucks-${g}-${pl}`);
    const bar = document.getElementById(`bar-${g}-${pl}`);

    if (!led) continue;
    // Status
    const running = p.process_state && p.maint_status === 'Running';
    const down = p.maint_status === 'Down';
    const stopped = !p.process_state;

    led.className = 'card-led ' + (running ? 'green' : down ? 'yellow' : '');
    card.className = 'factory-card factory-faceplate ' + (running ? 'status-running' : down ? 'status-down' : 'status-stopped');
    maint.textContent = running ? 'Running' : down ? '⚠ Down' : 'idle';

    // Recipe (shorten)
    const rec = p.recipe && p.recipe !== '--NA--' ? p.recipe : '— idle —';
    recipe.textContent = rec;
    recipe.title = rec;

    // OEE — only show live values when OPC data is confirmed ready
    const oee = p.oee;
    const live = running && p.opc_ready !== false;
    oeeEl.textContent = live ? `${oee}%` : '--';
    oeeEl.className = 'metric-value ' + (oee >= 80 ? 'oee-high' : oee >= 60 ? 'oee-mid' : 'oee-low');
    bar.style.width = live ? `${Math.min(oee, 100)}%` : '0%';
    bar.style.background = oee >= 80 ? 'var(--green)' : oee >= 60 ? 'var(--yellow)' : 'var(--red)';

    // Metrics
    pwrEl.textContent = live ? `${p.power} kW` : '--';
    goodEl.textContent = live ? `${p.good_tons}` : '--';
    trEl.textContent = live ? `${p.trucks_recv}` : '--';
  }
}

// Log polling
async function pollLogs() {
  if (!_logOpen) return;
  try {
    const r = await fetch('/api/logs');
    const d = await r.json();
    _serverLogs = d.logs;
    renderLog();
  } catch (e) { }
}

function renderLog() {
  const pre = document.getElementById('logPre');
  if (!_serverLogs.length) { pre.textContent = 'No log output yet…'; return; }
  pre.innerHTML = _serverLogs.map(l => {
    if (l.includes('✓') || l.includes('gestart') || l.includes('Connected'))
      return `<span class="log-info">${escHtml(l)}</span>`;
    if (l.includes('✗') || l.includes('Fout') || l.includes('Error') || l.includes('error'))
      return `<span class="log-err">${escHtml(l)}</span>`;
    return escHtml(l);
  }).join('\n');
  document.getElementById('logLines').textContent = `${_serverLogs.length} lines`;
}

function escHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function startPolling() {
  poll();
  setInterval(poll, 2000);
  setInterval(pollLogs, 3000);
}

// ── Settings modal ─────────────────────────────────────────────────────────────
async function openSettings() {
  try {
    const r = await fetch('/api/server-config');
    const d = await r.json();
    document.getElementById('cfg-bind-ip').value = d.opc_bind_ip || '0.0.0.0';
    document.getElementById('cfg-opc-port').value = d.opc_port || 4840;
    document.getElementById('cfg-client-host').value = d.opc_client_host || '127.0.0.1';
    document.getElementById('cfg-tcp-port').value = d.tcp_port || 9999;
    document.getElementById('cfg-host-ip').value = d.host_ip || '';
  } catch (e) { toast('Could not load settings', 'error'); return; }
  document.getElementById('settings-modal').style.display = 'flex';
}
function closeSettings() {
  document.getElementById('settings-modal').style.display = 'none';
}
async function saveSettings() {
  const body = {
    opc_bind_ip: document.getElementById('cfg-bind-ip').value.trim(),
    opc_port: parseInt(document.getElementById('cfg-opc-port').value) || 4840,
    opc_client_host: document.getElementById('cfg-client-host').value.trim(),
    tcp_port: parseInt(document.getElementById('cfg-tcp-port').value) || 9999,
    host_ip: document.getElementById('cfg-host-ip').value.trim(),
  };
  const r = await fetch('/api/server-config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const d = await r.json();
  if (d.ok) { toast('Settings saved — restart server to apply', 'ok'); closeSettings(); }
  else { toast('Save failed', 'error'); }
}
document.getElementById('settings-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('settings-modal')) closeSettings();
});
if (window.location.hash === '#settings') {
  window.addEventListener('load', () => openSettings());
}

// ── Server management ──────────────────────────────────────────────────────────
async function serverStart() {
  toast('Starting OPC UA server…', 'info');
  const r = await fetch('/api/server/start', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ local: true })
  });
  const d = await r.json();
  if (d.ok) {
    toast('Server starting (connecting to localhost)…', 'success');
    document.getElementById('inpHost').value = '127.0.0.1';
  } else {
    toast(`Server error: ${d.msg}`, 'error');
  }
}

async function serverStop() {
  if (!confirm('Stop the OPC UA server process?')) return;
  const r = await fetch('/api/server/stop', { method: 'POST' });
  const d = await r.json();
  toast(d.ok ? 'Server stopped' : `Error: ${d.msg}`, d.ok ? 'warn' : 'error');
}

// ── Bulk plant control ──────────────────────────────────────────────────────────
async function startAll() {
  if (!_serverRunning) {
    toast('Start the OPC UA server before starting plants.', 'warn', 5000);
    return;
  }
  toast('Starting all plants…', 'info');
  const r = await fetch('/api/plants/start-all', { method: 'POST' });
  const d = await r.json();
  toast(d.ok ? '🚀 All plants started' : `Error: ${d.msg}`, d.ok ? 'success' : 'error');
}

async function stopAll() {
  toast('Stopping all plants…', 'info');
  const r = await fetch('/api/plants/stop-all', { method: 'POST' });
  const d = await r.json();
  toast(d.ok ? 'All plants stopped' : `Error: ${d.msg}`, d.ok ? 'warn' : 'error');
}

async function toggleAllPlants() {
  const breaker = document.getElementById('plantBreaker');
  if (breaker && breaker.classList.contains('is-disabled')) {
    toast('Start the OPC UA server before starting plants.', 'warn', 5000);
    return;
  }
  const running = breaker && breaker.classList.contains('is-on');
  if (running) await stopAll();
  else await startAll();
}

function updatePlantBreaker(plants, serverRunning = _serverRunning) {
  const breaker = document.getElementById('plantBreaker');
  const caption = document.getElementById('plantBreakerCaption');
  if (!breaker || !caption) return;

  const plantList = Object.values(plants || {});
  const runningCount = plantList.filter(p => p.process_state && p.maint_status === 'Running').length;
  const anyRunning = runningCount > 0;
  breaker.classList.toggle('is-on', anyRunning);
  breaker.classList.toggle('is-disabled', !serverRunning && !anyRunning);
  breaker.setAttribute('aria-pressed', anyRunning ? 'true' : 'false');
  breaker.title = !serverRunning && !anyRunning ? 'Start the OPC UA server before starting plants' : anyRunning ? 'Stop all plants' : 'Start all plants';
  caption.textContent = !serverRunning && !anyRunning
    ? 'Start server first'
    : anyRunning
      ? `${runningCount}/${plantList.length} plants running`
      : 'Plants stopped';
}

// ── Connection config ──────────────────────────────────────────────────────────
async function applyConfig() {
  const host = document.getElementById('inpHost').value.trim();
  const port = parseInt(document.getElementById('inpPort').value) || 4840;
  if (!host) { toast('Enter a host address', 'error'); return; }
  await fetch('/api/config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host, port })
  });
  toast(`Config applied: ${host}:${port}`, 'info');
}

// ── Control Modal ─────────────────────────────────────────────────────────────
async function openCtrlModal(group, plant, short) {
  _ctrl = { group, plant, short, stateVal: null };
  document.getElementById('ctrlTitle').textContent = `⚙ Control — ${short}`;

  // Load recipes from sim_state via new per-plant endpoint
  const r = await fetch(`/api/recipes/${group}/${plant}`);
  const d = await r.json();
  const sel = document.getElementById('selRecipe');

  if (d.recipes && d.recipes.length) {
    sel.innerHTML = d.recipes.map(rec =>
      `<option value="${escAttr(rec)}">${escHtml(rec)}</option>`).join('');
    sel.style.display = '';
    document.getElementById('recipeRow').style.display = '';
  } else {
    // No recipes configured for this plant — hide the dropdown
    sel.innerHTML = '<option value="">— no recipes configured —</option>';
    document.getElementById('recipeRow').style.display = 'none';
  }

  const key = `${group}|${plant}`;
  const current = _plantsCache[key] || {};
  setToggle(typeof current.process_state === 'boolean' ? current.process_state : null);
  if (d.active) sel.value = d.active;
  else if (current.recipe && current.recipe !== '--NA--') sel.value = current.recipe;

  openModal('ctrlModal');
}

function setToggle(val) {
  _ctrl.stateVal = val;
  document.getElementById('btnStateOn').className = 'toggle-btn' + (val === true ? ' active-on' : '');
  document.getElementById('btnStateOff').className = 'toggle-btn' + (val === false ? ' active-off' : '');
}

async function applyControl() {
  const { group, plant, stateVal } = _ctrl;
  const recipe = document.getElementById('selRecipe').value;
  const ops = [];
  if (stateVal !== null) ops.push(apiPlantCtrl(group, plant, 'set_state', stateVal));
  ops.push(apiPlantCtrl(group, plant, 'set_recipe', recipe));
  const results = await Promise.all(ops);
  const allOk = results.every(r => r.ok);
  toast(allOk ? `✓ ${_ctrl.short} updated` : `⚠ Partial error`, allOk ? 'success' : 'warn');
  closeModal('ctrlModal');
}

async function apiPlantCtrl(group, plant, action, value) {
  try {
    const r = await fetch('/api/plant/control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group, plant, action, value })
    });
    return await r.json();
  } catch (e) { return { ok: false }; }
}

// ── Anomaly Modal (dynamic, driven by UNS tag list) ───────────────────────────
async function openAnomalyModal(group, plant, short) {
  _anom = { group, plant, short, overrides: {} };
  document.getElementById('anomalyTitle').textContent = `⚡ Anomaly — ${short}`;
  const body = document.getElementById('anomalyBody');
  body.innerHTML = '<p style="color:var(--muted);font-size:12px;padding:8px 0">Loading tags…</p>';
  openModal('anomalyModal');

  try {
    const r = await fetch(`/api/plant/tags/${encodeURIComponent(group)}/${encodeURIComponent(plant)}`);
    const d = await r.json();
    _renderDynamicAnomaly(d.tags || []);
  } catch (e) {
    body.innerHTML = '<p style="color:var(--red);font-size:12px">Failed to load tag list.</p>';
  }
}

function _renderDynamicAnomaly(tags) {
  const body = document.getElementById('anomalyBody');

  // Only numeric types make sense to override with a number
  const numericTags = tags.filter(t => t.dataType === 'Float' || t.dataType === 'Int');

  // Group by workCenter
  const groups = {};
  for (const t of numericTags) {
    const wc = t.workCenter || '—';
    if (!groups[wc]) groups[wc] = [];
    groups[wc].push(t);
  }

  if (numericTags.length === 0) {
    body.innerHTML = `
      <p style="font-size:12px;color:var(--muted)">
        No numeric tags found for <strong>${_anom.short}</strong>.<br>
        Add Float/Int tags to this plant in the UNS Designer to enable anomaly injection.
      </p>`;
    return;
  }

  let tagRows = '';
  for (const [wc, wcTags] of Object.entries(groups)) {
    tagRows += `<div class="anom-wc-group" data-wc="${wc.toLowerCase()}">
      <div style="font-size:10px;font-weight:700;color:var(--muted);padding:4px 8px;
           text-transform:uppercase;letter-spacing:.4px;background:var(--surface2);
           position:sticky;top:0">${escHtml(wc)}</div>`;
    for (const t of wcTags) {
      const unit = t.unit ? ` <span style="color:var(--muted);font-size:10px">${escHtml(t.unit)}</span>` : '';
      tagRows += `<label class="cb-item anom-tag-item"
          data-search="${(t.name + ' ' + wc).toLowerCase()}"
          style="border-radius:0;border-left:none;border-right:none;border-top:none">
        <input type="checkbox" class="anom-tag-cb" value="${escAttr(t.anomalyKey)}">
        ${escHtml(t.name)}${unit}
      </label>`;
    }
    tagRows += `</div>`;
  }

  body.innerHTML = `
    <p style="font-size:12px;color:var(--muted);margin-bottom:12px">
      Plant: <strong>${escHtml(_anom.short)}</strong> &nbsp;·&nbsp;
      Override tag values in real-time (auto-reset after duration)
    </p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
      <div class="form-group" style="margin:0">
        <label>Override Value</label>
        <input type="number" id="anomValue" step="any" placeholder="e.g. 0 or 999" style="width:100%">
      </div>
      <div class="form-group" style="margin:0">
        <label>Duration (s, 0 = permanent)</label>
        <input type="number" id="anomDuration" value="30" min="0" style="width:100%">
      </div>
    </div>
    <div class="form-group" style="margin:0">
      <label>Tags to override
        <span id="anomSelCount" style="color:var(--accent);font-weight:600;margin-left:6px"></span>
      </label>
      <input type="text" id="anomSearch" placeholder="Search tags…"
             style="width:100%;margin-bottom:6px" oninput="_filterAnomalyTags(this.value)">
      <div id="anomTagList"
           style="max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:6px">
        ${tagRows}
      </div>
    </div>`;

  // Live selection counter
  document.getElementById('anomTagList').addEventListener('change', () => {
    const n = document.querySelectorAll('.anom-tag-cb:checked').length;
    document.getElementById('anomSelCount').textContent = n ? `${n} selected` : '';
  });
}

function _filterAnomalyTags(q) {
  const lq = q.trim().toLowerCase();
  document.querySelectorAll('.anom-tag-item').forEach(el => {
    el.style.display = (!lq || el.dataset.search.includes(lq)) ? '' : 'none';
  });
  document.querySelectorAll('.anom-wc-group').forEach(grp => {
    const visible = [...grp.querySelectorAll('.anom-tag-item')].some(el => el.style.display !== 'none');
    grp.style.display = visible ? '' : 'none';
  });
}

async function injectAnomaly() {
  const valueEl = document.getElementById('anomValue');
  if (!valueEl) { toast('Open the anomaly modal first', 'error'); return; }
  const value = parseFloat(valueEl.value);
  if (isNaN(value)) { toast('Enter a numeric override value', 'error'); return; }

  const overrides = {};
  document.querySelectorAll('.anom-tag-cb:checked').forEach(cb => {
    overrides[cb.value] = value;
  });

  if (Object.keys(overrides).length === 0) {
    toast('Select at least one tag', 'error'); return;
  }

  const duration = parseFloat(document.getElementById('anomDuration').value) || 0;
  const r = await fetch('/api/anomaly/inject', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group: _anom.group, plant: _anom.plant, overrides, duration })
  });
  const d = await r.json();
  if (d.ok) {
    toast(`⚡ ${d.tags} tag(s) overridden${duration > 0 ? ' for ' + duration + 's' : ' permanently'}`, 'warn');
    closeModal('anomalyModal');
  } else {
    toast(`Inject failed: ${d.msg}`, 'error');
  }
}

// ── Log panel ──────────────────────────────────────────────────────────────────
function toggleLog() {
  _logOpen = !_logOpen;
  const body = document.getElementById('logBody');
  const caret = document.getElementById('logCaret');
  const actions = document.getElementById('logActions');
  body.classList.toggle('open', _logOpen);
  actions.style.display = _logOpen ? 'flex' : 'none';
  caret.textContent = _logOpen ? '▼' : '▶';
  if (_logOpen) { pollLogs(); scrollLogBottom(); }
}

function scrollLogBottom() {
  const b = document.getElementById('logBody');
  b.scrollTop = b.scrollHeight;
}

function clearLog() { _serverLogs = []; renderLog(); }

// ── Modal helpers ──────────────────────────────────────────────────────────────
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// Close on overlay click
document.querySelectorAll('.modal-overlay').forEach(el => {
  el.addEventListener('click', e => { if (e.target === el) el.classList.remove('open'); });
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.open')
    .forEach(el => el.classList.remove('open'));
});

// ── Toast ──────────────────────────────────────────────────────────────────────
function toast(msg, type = 'info', ms = 3500) {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 300);
  }, ms);
}

// ── Attribute escape ───────────────────────────────────────────────────────────
function escAttr(s) { return s.replace(/"/g, '&quot;'); }

// ── Bridge ─────────────────────────────────────────────────────────────────────
let _bridgeProto = 'mqtt';
let _enterpriseName = 'Enterprise';

function protoNotes() {
  const e = _enterpriseName;
  return {
    mqtt: `<strong>MQTT mode</strong> — connects to NATS (or any MQTT broker) on port 1883.<br>
           Topic format: <code>${e}/Division/Site/Line/WorkCenter/Tag</code><br>
           Requires: <code>pip install paho-mqtt</code>`,
    nats: `<strong>NATS native mode</strong> — connects to NATS server on port 4222 (not MQTT port).<br>
           Subject format: <code>${e}.Division.Site.Line.WorkCenter.Tag</code><br>
           Requires: <code>pip install nats-py</code>`,
  };
}

const DEFAULT_PORTS = { mqtt: 1883, nats: 4222 };

function updateBridgeUI(d) {
  const running = d.bridge_running;
  const bs = d.bridge_stats || {};
  const cfg = d.bridge_cfg || {};

  // Protocol badge
  const badge = document.getElementById('bridgeProtoBadge');
  const proto = (cfg.protocol || '—').toLowerCase();
  badge.textContent = proto === 'mqtt' ? 'MQTT' : proto === 'nats' ? 'NATS' : '—';
  badge.className = 'proto-badge ' + (running ? proto : 'off');

  // Address
  document.getElementById('bridgeAddr').textContent =
    cfg.broker_host ? `${cfg.broker_host}:${cfg.broker_port}` : 'not configured';

  // Stats
  document.getElementById('bridgeOpcStat').innerHTML =
    `OPC: <strong style="color:${bs.opc_ok ? 'var(--green)' : 'var(--red)'}">${bs.opc_ok ? '✓' : '✗'}</strong>`;
  document.getElementById('bridgeBrokerStat').innerHTML =
    `Broker: <strong style="color:${bs.connected ? 'var(--green)' : 'var(--red)'}">${bs.connected ? 'Connected' : 'Disconnected'}</strong>`;
  document.getElementById('bridgeRateStat').innerHTML =
    running ? `Rate: <strong>${bs.rate ?? 0} msg/s</strong>` : `Rate: <strong>—</strong>`;
  document.getElementById('bridgePubStat').innerHTML =
    running ? `Published: <strong>${(bs.published ?? 0).toLocaleString()}</strong>` : `Published: <strong>—</strong>`;

  // Buttons
  document.getElementById('btnBridgeStart').style.display = running ? 'none' : '';
  document.getElementById('btnBridgeStop').style.display = running ? '' : 'none';
}

async function bridgeStart() {
  toast('Starting bridge…', 'info');
  const r = await fetch('/api/bridge/start', { method: 'POST' });
  const d = await r.json();
  toast(d.ok ? '▶ Bridge started' : `Bridge error: ${d.msg}`, d.ok ? 'success' : 'error');
}

async function bridgeStop() {
  if (!confirm('Stop the broker bridge?')) return;
  const r = await fetch('/api/bridge/stop', { method: 'POST' });
  const d = await r.json();
  toast(d.ok ? '■ Bridge stopped' : `Error: ${d.msg}`, d.ok ? 'warn' : 'error');
}

function selectProto(p) {
  _bridgeProto = p;
  document.getElementById('protoBtnMqtt').className = 'proto-btn' + (p === 'mqtt' ? ' on' : '');
  document.getElementById('protoBtnNats').className = 'proto-btn' + (p === 'nats' ? ' on' : '');
  document.getElementById('cfgPortLabel').textContent =
    p === 'nats' ? 'Port (NATS = 4222)' : 'Port (MQTT = 1883)';
  document.getElementById('bridgeCfgNote').innerHTML = protoNotes()[p] || '';
  // Only auto-fill port if user hasn't typed something custom
  const portEl = document.getElementById('cfgPort');
  if (!portEl.dataset.userEdited) {
    portEl.value = DEFAULT_PORTS[p];
  }
}

async function openBridgeCfg() {
  // Load current config from server
  try {
    const r = await fetch('/api/bridge/config');
    const cfg = await r.json();
    _bridgeProto = cfg.protocol || 'mqtt';
    document.getElementById('cfgHost').value = cfg.broker_host || 'localhost';
    document.getElementById('cfgPort').value = cfg.broker_port || DEFAULT_PORTS[_bridgeProto];
    document.getElementById('cfgUser').value = cfg.username || '';
    document.getElementById('cfgPass').value = '';            // never pre-fill password
    document.getElementById('cfgPrefix').value = cfg.topic_prefix || '';
    document.getElementById('cfgInterval').value = cfg.interval || 2.0;
    const portEl = document.getElementById('cfgPort');
    portEl.dataset.userEdited = '';
  } catch (e) { /* use defaults */ }

  selectProto(_bridgeProto);

  // Mark port as user-edited when they type in it
  document.getElementById('cfgPort').addEventListener('input', function () {
    this.dataset.userEdited = '1';
  }, { once: true });

  openModal('bridgeCfgModal');
}

async function saveBridgeCfg() {
  const payload = {
    protocol: _bridgeProto,
    broker_host: document.getElementById('cfgHost').value.trim(),
    broker_port: parseInt(document.getElementById('cfgPort').value) || DEFAULT_PORTS[_bridgeProto],
    username: document.getElementById('cfgUser').value.trim(),
    password: document.getElementById('cfgPass').value,
    topic_prefix: document.getElementById('cfgPrefix').value.trim(),
    interval: parseFloat(document.getElementById('cfgInterval').value) || 2.0,
  };
  const r = await fetch('/api/bridge/config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const d = await r.json();
  if (d.ok) {
    toast(d.restarted ? '⟳ Bridge config saved & restarted' : '✓ Bridge config saved', 'success');
    closeModal('bridgeCfgModal');
  } else {
    toast(`Save failed: ${d.msg}`, 'error');
  }
}

function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('uns-theme', next);
}

// ── Boot ───────────────────────────────────────────────────────────────────────
startPolling();

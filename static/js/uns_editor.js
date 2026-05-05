// ── Config ──────────────────────────────────────────────────────────────────────
const NT = {
  enterprise: { label: 'Enterprise', color: '#58a6ff', icon: '🏢', next: 'businessUnit' },
  businessUnit: { label: 'Business Unit', color: '#a371f7', icon: '🏭', next: 'site' },
  site: { label: 'Site', color: '#3fb950', icon: '🏗️', next: 'area' },
  area: { label: 'Area', color: '#f4900c', icon: '📐', next: 'workCenter' },
  workCenter: { label: 'Work Center', color: '#e3b341', icon: '⚙️', next: 'workUnit' },
  workUnit: { label: 'Work Unit', color: '#f85149', icon: '🔧', next: 'device' },
  device: { label: 'Device', color: '#8b949e', icon: '📟', next: 'device' },
};

let uns = null;
let selId = null;
let expanded = new Set();
let srchQ = '';
let dirty = false;
let activeTab = 'props';
let editingTagIndex = null;
let _assetLibrary = [];
let _profileCatalogue = [];   // [{group, profiles:[{id,label}]}]
let _selectedAssetId = null;

// ── Utilities ───────────────────────────────────────────────────────────────────
function eid(id) { return document.getElementById(id); }
function esc(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function uid() {
  return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16));
}
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type === 'ok' ? 'ok' : type === 'err' ? 'err' : 'info'}`;
  el.textContent = msg; document.body.appendChild(el);
  setTimeout(() => el.remove(), 2400);
}
function setDirty(v = true) {
  dirty = v;
  const el = eid('save-ind');
  el.textContent = v ? '● Unsaved' : '● Saved';
  el.className = v ? 'unsaved' : 'saved';
  eid('btn-save')?.classList.toggle('needs-save', v);
}

// ── Tree traversal ──────────────────────────────────────────────────────────────
function find(id, node = uns?.tree) {
  if (!node) return null;
  if (node.id === id) return node;
  for (const c of node.children || []) { const f = find(id, c); if (f) return f; }
  return null;
}
function findParent(id, node = uns?.tree, par = null) {
  if (!node) return undefined;
  if (node.id === id) return par;
  for (const c of node.children || []) { const f = findParent(id, c, node); if (f !== undefined) return f; }
  return undefined;
}
function topicPath(id) {
  const parts = [];
  let cur = id;
  const map = {};
  function bm(n) { map[n.id] = n; (n.children || []).forEach(bm); }
  bm(uns.tree);
  const pmap = {};
  function bp(n, p = null) { pmap[n.id] = p; (n.children || []).forEach(c => bp(c, n.id)); }
  bp(uns.tree);
  while (cur) { const n = map[cur]; if (n) parts.unshift(n.name); cur = pmap[cur]; }
  return parts.join('/');
}
function allTagPaths(node = uns?.tree, prefix = '') {
  if (!node) return [];
  const out = [];
  const np = prefix ? `${prefix}/${node.name}` : node.name;
  (node.tags || []).forEach(t => out.push(`${np}/${t.name}`));
  (node.children || []).forEach(c => out.push(...allTagPaths(c, np)));
  return out;
}
function cntNodes(n = uns?.tree) { return n ? 1 + (n.children || []).reduce((s, c) => s + cntNodes(c), 0) : 0; }
function cntTags(n = uns?.tree) { return n ? (n.tags || []).length + (n.children || []).reduce((s, c) => s + cntTags(c), 0) : 0; }
function maxDepth(n = uns?.tree, d = 0) {
  if (!n || !(n.children || []).length) return d;
  return Math.max(...n.children.map(c => maxDepth(c, d + 1)));
}

// ── Rendering ───────────────────────────────────────────────────────────────────
function renderTree() {
  if (!uns || !uns.tree) {
    eid('tree').innerHTML = '<div style="padding:20px;text-align:center;color:var(--muted)">No configuration</div>';
    return;
  }
  if (!expanded.has(uns.tree.id)) expanded.add(uns.tree.id);
  eid('tree').innerHTML = '';
  eid('tree').appendChild(buildEl(uns.tree, 0));
  eid('stats').innerHTML = `<span>Nodes: <strong>${cntNodes()}</strong></span><span>Tags: <strong>${cntTags()}</strong></span><span>Depth: <strong>${maxDepth()}</strong></span>`;
}

function subtreeMatch(n, q) {
  if (!q) return true;
  const lq = q.toLowerCase();
  if (n.name.toLowerCase().includes(lq) || (n.description || '').toLowerCase().includes(lq)) return true;
  if ((n.tags || []).some(t => t.name.toLowerCase().includes(lq))) return true;
  return (n.children || []).some(c => subtreeMatch(c, q));
}

function buildEl(node, depth) {
  if (srchQ && !subtreeMatch(node, srchQ)) return null;
  const tc = NT[node.type] || NT.device;
  const hasC = (node.children || []).length > 0;
  const isExp = expanded.has(node.id);
  const isSel = node.id === selId;

  const wrap = document.createElement('div');
  wrap.className = 't-node';

  const row = document.createElement('div');
  row.className = 't-row' + (isSel ? ' sel' : '');
  row.style.paddingLeft = `${depth * 12 + 6}px`;
  row.onclick = () => selNode(node.id);

  const tc2 = NT[tc.next] || NT.device;
  row.innerHTML = `
    <span class="t-exp${hasC ? '' : ' inv'}" onclick="toggleExp('${node.id}',event)">${isExp ? '▼' : '▶'}</span>
    <span class="t-dot" style="background:${tc.color}"></span>
    <span class="t-name">${esc(node.name)}</span>
    ${(node.tags || []).length ? `<span class="t-badge">${node.tags.length}t</span>` : ''}
    <span class="t-acts">
      <span class="ibtn" title="Add ${tc2.label}" onclick="addChild('${node.id}',false,event)">+</span>
      <span class="ibtn" title="Duplicate subtree" onclick="dupNode('${node.id}',event)">⧉</span>
      <span class="ibtn del" title="Delete" onclick="confirmDelId('${node.id}',event)">×</span>
    </span>`;

  wrap.appendChild(row);

  if (isExp && hasC) {
    const ch = document.createElement('div');
    ch.className = 't-children';
    for (const c of node.children) {
      const el = buildEl(c, depth + 1);
      if (el) ch.appendChild(el);
    }
    wrap.appendChild(ch);
  }
  return wrap;
}

// ── Selection ───────────────────────────────────────────────────────────────────
function selNode(id) {
  selId = id;
  renderTree();
  showProps();
}

function showProps() {
  const node = selId ? find(selId) : null;
  if (!node) {
    eid('props-empty').style.display = 'flex';
    eid('props-content').style.display = 'none';
    return;
  }
  eid('props-empty').style.display = 'none';
  eid('props-content').style.display = 'flex';

  const tc = NT[node.type] || NT.device;
  const ntc = NT[tc.next] || NT.device;

  eid('type-badge').innerHTML = `<span class="type-badge" style="background:${tc.color}18;color:${tc.color};border:1px solid ${tc.color}30">${tc.icon} ${tc.label}</span>`;
  eid('act-row').innerHTML = `
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" onclick="addChild('${node.id}',false)">${ntc.icon} Add ${ntc.label}</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px" onclick="addChild('${node.id}',true)">+ Custom Child</button>`;

  eid('p-name').value = node.name;
  eid('p-type').value = node.type;
  eid('p-desc').value = node.description || '';
  eid('p-path').textContent = topicPath(node.id);

  renderTags(node.tags || []);
  renderPaths(node);
  if (activeTab === 'recipes') loadRecipes(node);
  tab(activeTab);
}

// ── Payload schemas ─────────────────────────────────────────────────────────────
let _schemas = [];
async function loadSchemas() {
  try {
    const r = await fetch('/api/payload-schemas');
    const d = await r.json();
    _schemas = d.schemas || [];
  }
  catch (e) { _schemas = []; }
}
function schemaOptions(current) {
  const opts = [{ id: '', name: '— default (standard) —' }, ..._schemas];
  return opts.map(s => `<option value="${esc(s.id)}"${(current || '') === (s.id) ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
}

// ── Profile catalogue ───────────────────────────────────────────────────────────
async function loadProfileCatalogue() {
  try {
    const r = await fetch('/api/simulation-profiles');
    _profileCatalogue = await r.json();
  } catch (e) {
    // Fallback minimal set
    _profileCatalogue = [
      { group: 'OT / Process', profiles: [{ id: 'oee', label: 'OEE (%)' }, { id: 'availability', label: 'Availability (%)' }, { id: 'performance', label: 'Performance (%)' }, { id: 'quality', label: 'Quality (%)' }] },
      { group: 'Energy / Utilities', profiles: [{ id: 'power_kw', label: 'Active Power (kW)' }, { id: 'accumulator_energy', label: 'Accumulator: Energy (kWh)' }] },
      { group: 'Other', profiles: [{ id: 'default', label: 'Generic Walk (fallback)' }] }
    ];
  }
}

function profileLabel(profileId) {
  if (!profileId) return '—';
  for (const g of _profileCatalogue) {
    const p = g.profiles.find(p => p.id === profileId);
    if (p) return p.label;
  }
  return profileId;
}

function profileSelectOptions(current) {
  let html = '<option value="">None (static value)</option>';
  for (const g of _profileCatalogue) {
    html += `<optgroup label="${esc(g.group)}">`;
    for (const p of g.profiles) {
      html += `<option value="${esc(p.id)}"${current === p.id ? ' selected' : ''}>${esc(p.label)}</option>`;
    }
    html += '</optgroup>';
  }
  return html;
}

// ── Asset library ───────────────────────────────────────────────────────────────
async function loadAssetLibrary() {
  try {
    const r = await fetch('/api/asset-library');
    const d = await r.json();
    _assetLibrary = d.assets || [];
  } catch (e) { _assetLibrary = []; }
}

function showAssetPicker() {
  if (!selId) { toast('Select a node first', 'err'); return; }
  _selectedAssetId = null;
  eid('asset-insert-btn').disabled = true;
  eid('asset-preview').className = 'asset-preview';

  // Build category filter buttons
  const cats = [...new Set(_assetLibrary.map(a => a.category))];
  let filterHTML = `<button class="asset-cat-btn on" onclick="filterAssets(null,this)">All</button>`;
  cats.forEach(c => { filterHTML += `<button class="asset-cat-btn" onclick="filterAssets('${esc(c)}',this)">${esc(c)}</button>`; });
  eid('asset-cat-filters').innerHTML = filterHTML;

  renderAssetGrid(null);
  eid('asset-modal').style.display = 'flex';
}

function filterAssets(cat, btn) {
  document.querySelectorAll('.asset-cat-btn').forEach(b => b.classList.remove('on'));
  btn.classList.add('on');
  renderAssetGrid(cat);
}

function renderAssetGrid(cat) {
  const assets = cat ? _assetLibrary.filter(a => a.category === cat) : _assetLibrary;
  if (!assets.length) {
    eid('asset-grid').innerHTML = '<div style="color:var(--muted);font-size:12px;padding:12px">No assets in this category.</div>';
    return;
  }
  eid('asset-grid').innerHTML = assets.map(a => `
        <div class="asset-card${_selectedAssetId === a.id ? ' sel' : ''}" data-asset-id="${esc(a.id)}" onclick="selectAsset('${esc(a.id)}')">
          <div class="asset-card-icon">${a.icon || '📦'}</div>
          <div class="asset-card-label">${esc(a.label)}</div>
          <div class="asset-card-cat">${esc(a.category)}</div>
          <div class="asset-card-tags">${a.tags.length} tag${a.tags.length !== 1 ? 's' : ''}</div>
        </div>`).join('');
}

function selectAsset(id) {
  _selectedAssetId = id;
  const asset = _assetLibrary.find(a => a.id === id);
  if (!asset) return;

  // Highlight selected card using data attribute (safe with innerHTML-generated elements)
  document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('sel'));
  const card = document.querySelector(`.asset-card[data-asset-id="${id}"]`);
  if (card) card.classList.add('sel');

  // Show preview
  const preview = eid('asset-preview');
  preview.innerHTML = `<strong style="color:var(--text)">${asset.icon} ${esc(asset.label)}</strong>
        <span style="color:var(--muted);margin-left:8px;font-size:10px">${esc(asset.description || '')}</span><br><br>` +
    asset.tags.map(t => `<span class="asset-preview-tag">
          <span style="color:var(--accent)">${esc(t.name)}</span>
          <span style="color:var(--muted)">${esc(t.dataType)}</span>
          ${t.unit ? `<span style="color:var(--yellow)">${esc(t.unit)}</span>` : ''}
          <span style="color:var(--green);font-size:9px">${esc(t.simulation?.profile || '—')}</span>
        </span>`).join('');
  preview.className = 'asset-preview on';

  eid('asset-insert-btn').disabled = false;
}

function doInsertAsset() {
  if (!_selectedAssetId || !selId) return;
  const asset = _assetLibrary.find(a => a.id === _selectedAssetId);
  const node = find(selId);
  if (!asset || !node) return;

  if (!node.tags) node.tags = [];
  let added = 0;
  asset.tags.forEach(t => {
    node.tags.push({
      id: uid(),
      name: t.name,
      dataType: t.dataType || 'Float',
      unit: t.unit || '',
      description: t.description || '',
      access: t.access || 'R',
      payloadSchema: t.payloadSchema || '',
      simulation: t.simulation ? { ...t.simulation } : null
    });
    added++;
  });

  setDirty();
  closeModal('asset-modal');
  renderTags(node.tags);
  tab('tags');
  toast(`Added ${added} tags from "${asset.label}"`, 'ok');
}

// ── Tags ────────────────────────────────────────────────────────────────────────
function renderTags(tags) {
  const w = eid('tags-wrap');
  if (!tags.length) {
    w.innerHTML = `<div class="tags-empty">
          No tags defined yet.<br>
          <small>Use <strong>＋ Add Tag</strong> to add individual data points, or <strong>🧩 Insert Asset Bundle</strong> to add a pre-configured set.</small>
        </div>`;
    return;
  }

  let html = `<table class="ttable">
    <thead><tr>
      <th>Name</th>
      <th>Data Type</th>
      <th>Unit</th>
      <th>Access</th>
      <th>Payload Schema</th>
      <th title="Click any cell to edit simulation profile">Simulation Profile ✏️</th>
      <th>Description</th>
      <th></th>
    </tr></thead><tbody>`;

  tags.forEach((t, i) => {
    const sim = t.simulation || {};
    let simContent;
    if (sim.profile) {
      const label = profileLabel(sim.profile);
      const isDefault = sim.profile === 'default';
      simContent = `<span class="sim-cell" onclick="editSimulation(${i})">
            <span style="color:var(--green);font-weight:500">${esc(label)}</span>
            ${isDefault && sim.base !== undefined ? `<small style="color:var(--muted)">(${sim.base}±${sim.std})</small>` : ''}
            <span style="color:var(--muted);font-size:10px">✏️</span>
          </span>`;
    } else {
      simContent = `<span class="sim-cell sim-cell-none" onclick="editSimulation(${i})">
            — set profile ✏️
          </span>`;
    }

    html += `<tr>
      <td><input class="ti" value="${esc(t.name)}" oninput="updTag(${i},'name',this.value)"></td>
      <td><select class="ts" onchange="updTag(${i},'dataType',this.value)">${['Float', 'Int', 'Bool', 'String', 'DateTime'].map(x => `<option value="${x}"${t.dataType === x ? ' selected' : ''}>${x}</option>`).join('')}</select></td>
      <td><input class="ti" style="width:55px" value="${esc(t.unit || '')}" oninput="updTag(${i},'unit',this.value)"></td>
      <td><select class="ts" onchange="updTag(${i},'access',this.value)">${['R', 'RW', 'W'].map(x => `<option value="${x}"${t.access === x ? ' selected' : ''}>${x}</option>`).join('')}</select></td>
      <td><select class="ts" onchange="updTag(${i},'payloadSchema',this.value)">${schemaOptions(t.payloadSchema)}</select></td>
      <td>${simContent}</td>
      <td><input class="ti" value="${esc(t.description || '')}" oninput="updTag(${i},'description',this.value)"></td>
      <td><span class="ibtn del" onclick="delTag(${i})" title="Delete tag">×</span></td>
    </tr>`;
  });

  html += `</tbody></table>`;
  w.innerHTML = html;
}

function updTag(i, field, val) {
  const n = find(selId);
  if (!n || !n.tags[i]) return;
  n.tags[i][field] = val;
  setDirty();
}

function addTag() {
  const n = find(selId);
  if (!n) return;
  if (!n.tags) n.tags = [];
  n.tags.push({
    id: uid(),
    name: 'NewTag',
    dataType: 'Float',
    unit: '',
    description: '',
    access: 'R',
    payloadSchema: '',
    simulation: null
  });
  setDirty();
  renderTags(n.tags);
  tab('tags');
}

function delTag(i) {
  const n = find(selId);
  if (!n) return;
  n.tags.splice(i, 1);
  setDirty();
  renderTags(n.tags);
}

// ── Recipes tab ─────────────────────────────────────────────────────────────
// Recipes are stored in uns_config.json on the site node (site.recipes = [{name, params}]).
// They are edited in-memory (uns object) and persisted with the normal UNS Save button.
// sim_state.json only tracks the *active* recipe selection per plant.
let _recipeNodeKey = null;   // "Group|site" for the selected site node
let _recipeList = [];     // live reference to node.recipes array
let _recipeActive = '';

function _plantKeyFromNode(node) {
  // Build plant_key = "BusinessUnit|siteName" — matches sim_state.json format exactly.
  const map = {};
  function bm(n) { map[n.id] = n; (n.children || []).forEach(bm); }
  bm(uns.tree);
  const pmap = {};
  function bp(n, p = null) { pmap[n.id] = p; (n.children || []).forEach(c => bp(c, n.id)); }
  bp(uns.tree);

  if (node.type !== 'site') return null;
  const parentId = pmap[node.id];
  const parentNode = map[parentId];
  if (!parentNode) return null;
  return `${parentNode.name}|${node.name}`;   // no "Factory" prefix
}

async function loadRecipes(node) {
  const siteOnly = eid('recipes-site-only');
  const editor = eid('recipes-editor');

  if (!node || node.type !== 'site') {
    siteOnly.style.display = 'flex';
    editor.style.display = 'none';
    siteOnly.style.flexDirection = 'column';
    siteOnly.style.alignItems = 'center';
    return;
  }

  siteOnly.style.display = 'none';
  editor.style.display = 'block';

  _recipeNodeKey = _plantKeyFromNode(node);
  if (!_recipeNodeKey) {
    eid('recipes-list').innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">Cannot determine plant key.</div>';
    return;
  }

  // Recipes live in the in-memory UNS node — no API call needed to load them
  if (!node.recipes) node.recipes = [];
  _recipeList = node.recipes;

  // Active recipe comes from sim_state via API
  const [group, plant] = _recipeNodeKey.split('|');
  try {
    const r = await fetch(`/api/recipes/${group}/${plant}`);
    const d = await r.json();
    _recipeActive = d.active || '';
  } catch (e) {
    _recipeActive = '';
  }
  renderRecipes();
}

function renderRecipes() {
  const list = eid('recipes-list');
  if (!_recipeList.length) {
    list.innerHTML = `<div style="text-align:center;color:var(--muted);font-size:12px;padding:16px">
          No recipes defined.<br><small>Click <strong>＋ Add Recipe</strong> to add the first one.</small>
        </div>`;
    return;
  }
  list.innerHTML = _recipeList.map((r, i) => {
    const isActive = r.name === _recipeActive;
    return `<div class="recipe-row">
          <input class="ti" value="${esc(r.name)}" placeholder="Recipe name"
                 oninput="updateRecipeName(${i}, this.value)" style="flex:2">
          ${isActive ? '<span class="recipe-active-badge">● active</span>' : ''}
          <span class="ibtn del" onclick="deleteRecipe(${i})" title="Remove recipe">×</span>
        </div>`;
  }).join('');
}

function addRecipe() {
  // _recipeList is a live reference to node.recipes — modifying it updates the uns object
  _recipeList.push({ name: 'New Recipe', params: {} });
  renderRecipes();
  setDirty();   // mark UNS as unsaved; user saves via the Save button
}

function deleteRecipe(i) {
  _recipeList.splice(i, 1);
  renderRecipes();
  setDirty();
}

function updateRecipeName(i, val) {
  _recipeList[i].name = val;
  setDirty();
}
function editSimulation(i) {
  const node = find(selId);
  if (!node || !node.tags[i]) return;

  const tag = node.tags[i];
  editingTagIndex = i;
  const sim = tag.simulation || {};

  let modalHTML = `
    <div class="overlay" id="sim-modal">
      <div class="modal" style="max-width:500px">
        <h3>Simulation Profile — <span style="color:var(--accent)">${esc(tag.name)}</span></h3>

        <div class="fg">
          <label>Profile <small style="color:var(--muted)">(optional — enables live simulation)</small></label>
          <select id="tag-simulation-profile" onchange="updateSimulationFields()" style="padding:8px">
            ${profileSelectOptions(sim.profile || '')}
          </select>
        </div>

        <div id="custom-sim-fields" style="margin-top:12px;display:none;gap:12px;flex-wrap:wrap">
          <p style="font-size:11px;color:var(--muted);width:100%;margin-bottom:4px">
            Generic walk parameters — used only when profile is <strong>default</strong>
          </p>
          <div style="flex:1;min-width:90px">
            <label style="font-size:11px;color:var(--muted)">Base</label>
            <input id="tag-sim-base" type="number" step="0.01" class="ti" value="${sim.base ?? 50}">
          </div>
          <div style="flex:1;min-width:90px">
            <label style="font-size:11px;color:var(--muted)">Std Dev</label>
            <input id="tag-sim-std" type="number" step="0.01" class="ti" value="${sim.std ?? 8}">
          </div>
          <div style="flex:1;min-width:90px">
            <label style="font-size:11px;color:var(--muted)">Min</label>
            <input id="tag-sim-min" type="number" step="0.01" class="ti" value="${sim.min ?? 0}">
          </div>
          <div style="flex:1;min-width:90px">
            <label style="font-size:11px;color:var(--muted)">Max</label>
            <input id="tag-sim-max" type="number" step="0.01" class="ti" value="${sim.max ?? 100}">
          </div>
        </div>

        <div id="profile-hint" style="margin-top:12px;padding:8px 10px;background:var(--surface3);border-radius:6px;font-size:11px;color:var(--muted);display:none"></div>

        <div class="modal-actions">
          <button class="btn btn-ghost" onclick="closeSimModal()">Cancel</button>
          <button class="btn btn-primary" onclick="saveSimulation()">Save</button>
        </div>
      </div>
    </div>`;

  const oldModal = document.getElementById('sim-modal');
  if (oldModal) oldModal.remove();
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = modalHTML;
  document.body.appendChild(tempDiv.firstElementChild);

  updateSimulationFields();
}

function updateSimulationFields() {
  const profile = document.getElementById('tag-simulation-profile').value;
  const customDiv = document.getElementById('custom-sim-fields');
  const hintDiv = document.getElementById('profile-hint');

  customDiv.style.display = (profile === 'default') ? 'flex' : 'none';

  // Show a short hint for the selected profile
  const hintMap = {
    'oee': 'Correlated with plant state machine. Degrades on fault, recovers automatically.',
    'availability': 'Drops sharply during fault, climbs during recovery.',
    'boolean_running': 'TRUE only when the plant is in Running state.',
    'boolean_fault': 'TRUE only during an active fault.',
    'boolean_alarm': 'TRUE during fault and recovery phases.',
    'accumulator_good': 'Monotonically increasing. Only advances when plant is running.',
    'accumulator_energy': 'Increases proportionally to current power draw.',
    'silo_level': 'Drains during production. Auto-refills when low (truck arrival).',
    'truck_id': 'Cycles to a new truck ID on each silo refill event.',
    'remaining_useful_life': 'Counts down. Resets after a recovery / PM event.',
    'vibration': 'Rises as a fault approaches, drops after recovery.',
    'motor_current': 'Spikes during fault, normalises during recovery.',
    'erp_order_id': 'Cycles to a new order ID on batch change events.',
    'order_status': 'Progresses through Created → Released → In Progress → Completed → Closed.',
    'default': 'Gaussian walk. Configure base value, std deviation and bounds below.',
  };
  if (hintMap[profile]) {
    hintDiv.textContent = '💡 ' + hintMap[profile];
    hintDiv.style.display = 'block';
  } else if (profile) {
    hintDiv.textContent = '💡 Plant-state-aware: paused during fault, slower during recovery.';
    hintDiv.style.display = 'block';
  } else {
    hintDiv.style.display = 'none';
  }
}

function saveSimulation() {
  if (editingTagIndex === null) return;
  const node = find(selId);
  if (!node || !node.tags[editingTagIndex]) return;

  const tag = node.tags[editingTagIndex];
  const profile = document.getElementById('tag-simulation-profile').value;

  if (profile) {
    if (!tag.simulation) tag.simulation = {};
    tag.simulation.profile = profile;

    if (profile === 'default') {
      tag.simulation.base = parseFloat(document.getElementById('tag-sim-base').value) || 50;
      tag.simulation.std = parseFloat(document.getElementById('tag-sim-std').value) || 8;
      tag.simulation.min = parseFloat(document.getElementById('tag-sim-min').value) || 0;
      tag.simulation.max = parseFloat(document.getElementById('tag-sim-max').value) || 100;
    } else {
      delete tag.simulation.base;
      delete tag.simulation.std;
      delete tag.simulation.min;
      delete tag.simulation.max;
    }
  } else {
    delete tag.simulation;
  }

  setDirty();
  closeSimModal();
  renderTags(node.tags);
}

function closeSimModal() {
  const modal = document.getElementById('sim-modal');
  if (modal) modal.remove();
  editingTagIndex = null;
}

// ── Paths tab ───────────────────────────────────────────────────────────────────
function renderPaths(node) {
  const fullPath = topicPath(node.id);
  const parentPath = fullPath.includes('/') ? fullPath.substring(0, fullPath.lastIndexOf('/')) : '';
  const paths = allTagPaths(node, parentPath);
  eid('paths-count').textContent = `${paths.length} path${paths.length !== 1 ? 's' : ''}`;
  if (!paths.length) {
    eid('paths-list').innerHTML = '<div class="tags-empty">No tags in this subtree.</div>';
    return;
  }
  eid('paths-list').innerHTML = paths.map(p => {
    const parts = p.split('/');
    const tag = parts.pop();
    const rest = parts.join('/');
    return `<div class="path-item"><span style="color:var(--muted)">${esc(rest)}/</span><span class="path-tag">${esc(tag)}</span></div>`;
  }).join('');
}

// ── Tab switching ───────────────────────────────────────────────────────────────
function tab(name) {
  activeTab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.tab === name));
  document.querySelectorAll('.tab-body').forEach(t => t.classList.toggle('on', t.id === `tb-${name}`));
  if (name === 'recipes' && selId) loadRecipes(find(selId));
}

// ── Property changes ────────────────────────────────────────────────────────────
function propChanged() {
  const n = find(selId);
  if (!n) return;
  n.name = eid('p-name').value;
  n.type = eid('p-type').value;
  n.description = eid('p-desc').value;
  eid('p-path').textContent = topicPath(selId);
  setDirty();
  renderTree();
}

// ── Tree operations ─────────────────────────────────────────────────────────────
function toggleExp(id, e) {
  if (e) e.stopPropagation();
  expanded.has(id) ? expanded.delete(id) : expanded.add(id);
  renderTree();
}
function expandAll(n = uns?.tree) {
  if (!n) return;
  expanded.add(n.id);
  (n.children || []).forEach(c => expandAll(c));
  renderTree();
}
function collapseAll(n = uns?.tree) {
  if (!n) return;
  if (n.id !== uns.tree.id) expanded.delete(n.id);
  (n.children || []).forEach(c => collapseAll(c));
  renderTree();
}
function filterTree(q) {
  srchQ = q.trim();
  if (srchQ) expandAll();
  renderTree();
}
function addToRoot() {
  if (uns && uns.tree) addChild(uns.tree.id, false);
}

function addChild(parentId, custom = false, e) {
  if (e) e.stopPropagation();
  const par = find(parentId);
  if (!par) return;
  const tc = NT[par.type] || NT.device;
  const ctype = custom ? 'workCenter' : tc.next;
  const ctc = NT[ctype] || NT.device;
  const nn = {
    id: uid(),
    name: `New${ctc.label.replace(/\s/g, '')}`,
    type: ctype,
    description: '',
    tags: [],
    children: []
  };
  if (!par.children) par.children = [];
  par.children.push(nn);
  expanded.add(parentId);
  setDirty();
  renderTree();
  selNode(nn.id);
  setTimeout(() => {
    const el = eid('p-name');
    if (el) { el.focus(); el.select(); }
  }, 60);
}

function deepClone(o) { return JSON.parse(JSON.stringify(o)); }
function reId(n) {
  n.id = uid();
  (n.children || []).forEach(reId);
  (n.tags || []).forEach(t => t.id = uid());
  return n;
}

function dupNode(id, e) {
  if (e) e.stopPropagation();
  const n = find(id);
  const par = findParent(id);
  if (!n || !par) { toast('Cannot duplicate root', 'err'); return; }
  const copy = reId(deepClone(n));
  copy.name += '_copy';
  const idx = par.children.indexOf(n);
  par.children.splice(idx + 1, 0, copy);
  setDirty();
  renderTree();
  selNode(copy.id);
  toast(`Duplicated ${n.name}`, 'ok');
}
function dupSel() { if (selId) dupNode(selId); }

function confirmDelId(id, e) {
  if (e) e.stopPropagation();
  const n = find(id);
  if (!n) return;
  const nc = cntNodes(n) - 1, nt = cntTags(n);
  eid('conf-title').textContent = `Delete "${n.name}"?`;
  eid('conf-msg').textContent = `Removes ${nc} child node${nc !== 1 ? 's' : ''} and ${nt} tag${nt !== 1 ? 's' : ''}. Cannot be undone.`;
  eid('conf-ok').onclick = () => { doDelete(id); closeModal('confirm-modal'); };
  eid('confirm-modal').style.display = 'flex';
}
function confirmDel() { if (selId) confirmDelId(selId); }

function doDelete(id) {
  if (id === uns.tree.id) { toast('Cannot delete root', 'err'); return; }
  const par = findParent(id);
  if (!par) return;
  par.children = par.children.filter(c => c.id !== id);
  if (selId === id) {
    selId = null;
    eid('props-empty').style.display = 'flex';
    eid('props-content').style.display = 'none';
  }
  setDirty();
  renderTree();
  toast('Node deleted', 'info');
}

// ── Persist ─────────────────────────────────────────────────────────────────────
async function saveConfig() {
  try {
    const r = await fetch('/api/uns', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(uns) });
    const d = await r.json();
    if (d.ok) {
      setDirty(false);
      const svc = (d.restarted || []).join(' + ');
      toast(svc ? `Saved — restarted: ${svc}` : 'Saved', 'ok');
    } else toast('Save failed', 'err');
  } catch (err) { toast('Save error: ' + err.message, 'err'); }
}

async function loadConfig() {
  try {
    const r = await fetch('/api/uns');
    const d = await r.json();
    if (d && d.tree) {
      uns = d;
      expanded.clear();
      expanded.add(uns.tree.id);
      renderTree();
      setDirty(false);
    }
  } catch (e) { toast('Failed to load config', 'err'); }
}

// ── Import / Export ─────────────────────────────────────────────────────────────
function showImport() {
  eid('imp-text').value = '';
  eid('import-modal').style.display = 'flex';
}
function loadFile(inp) {
  const f = inp.files[0];
  if (!f) return;
  const fr = new FileReader();
  fr.onload = e => { eid('imp-text').value = e.target.result; };
  fr.readAsText(f);
}
function doImport() {
  try {
    const d = JSON.parse(eid('imp-text').value.trim());
    if (!d.tree) throw new Error('Missing "tree" property');
    const merge = eid('imp-merge').checked;
    if (merge && uns.tree && uns.tree.children) {
      const incoming = d.tree.children || [];
      if (!incoming.length) throw new Error('Nothing to merge — imported tree has no children');

      const incomingEnt = d.tree;
      const droppedMeta = [];
      if (incomingEnt.type === 'enterprise' && incomingEnt.name && incomingEnt.name !== uns.tree.name) {
        droppedMeta.push(`enterprise name "${incomingEnt.name}"`);
      }
      if (d.namespaceUri && d.namespaceUri !== (uns.namespaceUri || '')) {
        droppedMeta.push(`namespaceUri "${d.namespaceUri}"`);
      }
      if (d.description && d.description !== (uns.description || '')) {
        droppedMeta.push('top-level description');
      }

      const existingNames = new Set((uns.tree.children || []).map(c => c.name));
      const collisions = incoming.map(c => c.name).filter(n => existingNames.has(n));

      const warnings = [];
      if (droppedMeta.length) {
        warnings.push(`Imported wrapper will be DISCARDED — only its child nodes are merged.\nDropped: ${droppedMeta.join(', ')}.`);
      }
      if (collisions.length) {
        warnings.push(`Name collision — duplicate top-level nodes will be created: ${collisions.join(', ')}.`);
      }

      if (warnings.length) {
        const msg = warnings.join('\n\n') + '\n\nProceed with merge?';
        if (!confirm(msg)) return;
      }

      uns.tree.children = uns.tree.children.concat(incoming);
      toast(`Merged ${incoming.length} node(s) into existing tree`, 'ok');
    } else {
      uns = d;
      toast('Imported', 'ok');
    }
    expanded.clear();
    expanded.add(uns.tree.id);
    selId = null;
    eid('props-empty').style.display = 'flex';
    eid('props-content').style.display = 'none';
    setDirty();
    renderTree();
    closeModal('import-modal');
  } catch (e) { toast('Invalid JSON: ' + e.message, 'err'); }
}
function confirmClearAll() {
  if (!confirm('Clear the entire UNS tree? All nodes and tags will be removed.\n\nThis cannot be undone unless you have a saved backup.')) return;
  uns = { version: uns.version || '2.0', namespaceUri: uns.namespaceUri || '', description: '', tree: { id: 'root', name: 'Enterprise', type: 'enterprise', children: [] } };
  expanded.clear();
  expanded.add('root');
  selId = null;
  eid('props-empty').style.display = 'flex';
  eid('props-content').style.display = 'none';
  setDirty();
  renderTree();
  toast('UNS tree cleared', 'ok');
}
function doExportJSON() {
  showExportModal('Export UNS Configuration', JSON.stringify(uns, null, 2), 'uns_config.json');
}
function doExportPaths() {
  const paths = allTagPaths();
  if (!paths.length) { toast('No tags defined yet', 'info'); return; }
  showExportModal(`Topic Paths (${paths.length})`, paths.join('\n'), 'uns_topic_paths.txt');
}
function showExportModal(title, text, fname) {
  eid('exp-title').textContent = title;
  eid('exp-text').value = text;
  eid('exp-dl').onclick = () => dlFile(text, fname);
  eid('export-modal').style.display = 'flex';
}
function copyExp() {
  navigator.clipboard.writeText(eid('exp-text').value).then(() => toast('Copied', 'ok'));
}
function copyPaths() {
  const n = selId ? find(selId) : uns.tree;
  const fp = selId ? topicPath(selId) : '';
  const pp = fp.includes('/') ? fp.substring(0, fp.lastIndexOf('/')) : '';
  const paths = allTagPaths(n, pp);
  navigator.clipboard.writeText(paths.join('\n')).then(() => toast(`Copied ${paths.length} paths`, 'ok'));
}
function dlFile(text, fname) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  a.download = fname; a.click();
}

// ── Modals ───────────────────────────────────────────────────────────────────────
function closeModal(id) {
  eid(id).style.display = 'none';
}
document.querySelectorAll('.overlay').forEach(o => o.addEventListener('click', e => {
  if (e.target === o) o.style.display = 'none';
}));
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.overlay').forEach(m => m.style.display = 'none');
  if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); saveConfig(); }
});

// ── Panel resize ────────────────────────────────────────────────────────────
(function () {
  const handle = document.getElementById('tree-resize');
  const panel = document.querySelector('.tree-panel');
  const KEY = 'uns-tree-width';
  const saved = localStorage.getItem(KEY);
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
    panel.style.width = '320px';
    localStorage.removeItem(KEY);
  });
})();

function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('uns-theme', next);
}

// ── Boot ────────────────────────────────────────────────────────────────────────
Promise.all([loadSchemas(), loadProfileCatalogue(), loadAssetLibrary()]).then(loadConfig);

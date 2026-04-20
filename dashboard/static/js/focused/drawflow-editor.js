/**
 * Drawflow visual pipeline builder.
 * Extracted from dashboard-legacy.js — depends on Drawflow lib + core modules.
 */

// === Visual Pipeline Builder ===

let editor = null;
let activeNodeId = null;

function initDrawflow() {
  const container = $('#drawflow');
  if (!container) return;
  // If container changed (HTMX re-rendered), recreate editor
  if (editor && editor.container === container) return;
  editor = null;
  editor = new Drawflow(container);
  editor.reroute = true;
  editor.reroute_fix_curvature = true;
  editor.force_first_input = false;
  editor.start();

  container.addEventListener('dblclick', function(e) {
    const nodeEl = e.target.closest('.drawflow-node');
    if (nodeEl) {
      e.stopPropagation();
      e.preventDefault();
      const nodeId = nodeEl.id.replace('node-', '');
      openNodeConfig(nodeId);
    }
  });

  editor.on('nodeUnselected', function() { closeNodeConfig(); });
  editor.on('nodeCreated', () => markUnsaved());
  editor.on('nodeRemoved', () => markUnsaved());
  editor.on('connectionCreated', () => markUnsaved());
  editor.on('connectionRemoved', () => markUnsaved());
  editor.on('nodeMoved', () => markUnsaved());

  const zoomDisplay = $('#pl-zoom-level');
  editor.on('zoom', () => {
    if (zoomDisplay) zoomDisplay.textContent = Math.round(editor.zoom * 100) + '%';
  });
}

function markUnsaved() {
  $('#pl-save-status').textContent = 'Unsaved*';
  $('#pl-save-status').style.color = 'var(--color-warning)';
}

function markSaved() {
  $('#pl-save-status').textContent = 'Saved';
  $('#pl-save-status').style.color = 'var(--text-muted)';
}

async function loadPipelinesList() {
  if (!AppState.currentProject) return;
  AppState.pipelines = await API.get(`/api/projects/${AppState.currentProject}/pipelines`);
  const list = $('#pl-list');

  if (!AppState.pipelines || !AppState.pipelines.length) {
    list.innerHTML = `<div style="color:var(--text-muted);font-size:11px;padding:12px;">${i18n.t('pipeline.no_pipelines')}</div>`;
    return;
  }

  list.innerHTML = AppState.pipelines.map(pl => `
    <div class="pl-list-item ${pl.id === AppState.currentPipelineId ? 'active' : ''}" onclick="selectPipeline('${escapeHtml(pl.id)}')">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span>${escapeHtml(pl.name)}${pl.readonly ? ' <span style="font-size:9px;color:var(--text-muted)">🌐</span>' : ''}</span>
        ${!pl.readonly ? `<button onclick="event.stopPropagation();deletePipeline('${escapeHtml(pl.id)}')" style="background:none;border:none;color:var(--color-danger);cursor:pointer;">&times;</button>` : ''}
      </div>
    </div>
  `).join('');

  if (!AppState.currentPipelineId && AppState.pipelines.length > 0) {
    selectPipeline(AppState.pipelines[0].id);
  } else if (AppState.currentPipelineId) {
    selectPipeline(AppState.currentPipelineId, true);
  }
}

async function selectPipeline(id, forceRefresh) {
  if (AppState.currentPipelineId === id && !forceRefresh) return;
  AppState.currentPipelineId = id;
  initDrawflow();

  // Check if this is a global pipeline from cached list
  var cached = (AppState.pipelines || []).find(function(p) { return p.id === id; });
  var isGlobal = cached && cached.is_global;
  var isReadonly = cached && cached.readonly;
  var pl;

  if (isGlobal && cached.graph) {
    // Use cached data for global templates (not in project API)
    pl = cached;
  } else {
    pl = await API.get(`/api/projects/${AppState.currentProject}/pipelines/${id}`);
  }

  $('#pl-name-input').value = pl.name;
  $('#pl-name-input').disabled = !!isReadonly;
  editor.clear();
  if (pl.graph && pl.graph.drawflow && pl.graph.drawflow.Home && Object.keys(pl.graph.drawflow.Home.data).length > 0) {
    try { editor.import(pl.graph); } catch(e) { console.error("Failed to import graph", e); }
  }

  // Disable editing for readonly pipelines
  if (typeof editor.editor_mode !== 'undefined') {
    editor.editor_mode = isReadonly ? 'fixed' : 'edit';
  }

  // Hide/show editing controls for readonly pipelines
  var saveBtn = document.getElementById('pl-save-btn');
  if (saveBtn) saveBtn.style.display = isReadonly ? 'none' : '';
  var clearBtn = document.getElementById('pl-clear-btn');
  if (clearBtn) clearBtn.style.display = isReadonly ? 'none' : '';
  var palette = document.querySelector('.pl-node-palette');
  if (palette) palette.style.display = isReadonly ? 'none' : '';

  closeNodeConfig();
  markSaved();
  $$('.pl-list-item').forEach(el => {
    el.classList.toggle('active', el.getAttribute('onclick').includes(id));
  });
}

async function createNewPipeline() {
  const pl = await API.post(`/api/projects/${AppState.currentProject}/pipelines`, {name: 'New Pipeline'});
  await loadPipelinesList();
  selectPipeline(pl.id);
}

async function deletePipeline(id) {
  if (!confirm(i18n.t('common.delete') + '?')) return;
  await API.del(`/api/projects/${AppState.currentProject}/pipelines/${id}`);
  if (AppState.currentPipelineId === id) AppState.currentPipelineId = null;
  loadPipelinesList();
}

async function saveCurrentPipeline() {
  if (!AppState.currentPipelineId || !editor) return;
  var cached = (AppState.pipelines || []).find(function(p) { return p.id === AppState.currentPipelineId; });
  if (cached && cached.readonly) return; // shouldn't happen but safety check

  const name = $('#pl-name-input').value;
  const graph = editor.export();

  try {
    if (cached && cached.is_global) {
      await API.put('/api/pipeline-templates/' + AppState.currentPipelineId, {name, graph});
    } else {
      await API.put(`/api/projects/${AppState.currentProject}/pipelines/${AppState.currentPipelineId}`, {name, graph});
    }
    markSaved();
    _plToast(i18n.t('pipeline.saved_ok') || 'Pipeline saved', 'success');
    loadPipelinesList();
  } catch (e) {
    _plToast(e.message || 'Save failed', 'error');
  }
}

function _plToast(msg, type) {
  var el = document.createElement('div');
  el.textContent = msg;
  el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:9999;padding:10px 20px;border-radius:var(--radius-sm);font-size:12px;font-family:var(--font);color:#fff;opacity:0;transition:opacity .2s;'
    + (type === 'error' ? 'background:var(--color-danger);' : 'background:var(--color-success);');
  document.body.appendChild(el);
  requestAnimationFrame(function() { el.style.opacity = '1'; });
  setTimeout(function() { el.style.opacity = '0'; setTimeout(function() { el.remove(); }, 200); }, 2500);
}

function plDrag(ev) {
  ev.dataTransfer.setData("node", ev.target.getAttribute("data-node"));
}

function plDrop(ev) {
  ev.preventDefault();
  try {
    const nodeType = ev.dataTransfer.getData("node");
    if (!nodeType) return;
    const container = $('#drawflow');
    if (!container || !editor) return;
    const rect = container.getBoundingClientRect();
    let pos_x = (ev.clientX - rect.left - editor.canvas_x) / editor.zoom;
    let pos_y = (ev.clientY - rect.top - editor.canvas_y) / editor.zoom;
    const isReviewer = nodeType.includes('REVIEW') || nodeType === 'PERF';
    const cls = isReviewer ? 'type-reviewer' : 'type-agent';
    const nodeHtml = `<div class="box"><span>${escapeHtml(nodeType)}</span><span class="node-type-badge">${isReviewer ? 'Reviewer' : 'Agent'}</span></div>`;
    editor.addNode(nodeType, 1, 1, pos_x, pos_y, cls, { agent: nodeType, type: isReviewer ? 'reviewer' : 'agent' }, nodeHtml, false);
  } catch (error) {
    console.error("[Drawflow] Drop error:", error);
  }
}

// Node Config
let availableSkills = [];

async function openNodeConfig(id) {
  activeNodeId = id;
  const node = editor.getNodeFromId(id);
  const data = node.data || {};

  var panel = document.getElementById('node-config-panel');
  var overlay = document.getElementById('node-config-overlay');
  if (!panel || !overlay) return;

  // Determine if current pipeline is readonly
  var cached = (AppState.pipelines || []).find(function(p) { return p.id === AppState.currentPipelineId; });
  var isReadonly = cached && cached.readonly;

  if (editor) {
    editor.node_selected = null;
    editor.drag = false;
    document.dispatchEvent(new MouseEvent('mouseup'));
  }

  const isReviewer = data.type === 'reviewer';
  panel.classList.add('active');
  overlay.classList.add('active');
  $('#cfg-node-title').textContent = data.agent + (isReadonly ? '' : ' Configuration');
  $('#cfg-agent-type-badge').textContent = isReviewer ? 'Skills Reviewer' : 'Execution Agent';

  // Hide/show save button based on readonly
  var applyBtn = panel.querySelector('button[onclick="saveNodeConfig()"]');
  if (applyBtn) applyBtn.style.display = isReadonly ? 'none' : '';

  const skillsSec = $('#cfg-skills-section');
  const promptSec = $('#cfg-prompt-section');

  try {
    if (!AppState.projectAgents || typeof AppState.projectAgents !== 'object' || Array.isArray(AppState.projectAgents) || Object.keys(AppState.projectAgents).length === 0) {
      AppState.projectAgents = await API.get(`/api/projects/${AppState.currentProject}/agents`);
    }
  } catch(e) { console.error('Failed to load agents:', e); AppState.projectAgents = {}; }

  try {
    if (!availableSkills.length) {
      availableSkills = (await API.get('/api/skills')).skills || [];
    }
  } catch(e) { console.error('Failed to load skills:', e); }

  if (isReviewer) {
    skillsSec.classList.remove('hidden');
    promptSec.classList.add('hidden');
    let preselected = data.skills;
    if (!preselected) {
      preselected = [];
      const baseAgent = data.agent.replace('_REVIEW', '').toLowerCase();
      const isPerf = data.agent === 'PERF';
      availableSkills.forEach(s => {
        if (s.agent === 'global') preselected.push(s.source);
        if (s.agent === baseAgent) preselected.push(s.source);
        if (isPerf && s.agent === 'perf') preselected.push(s.source);
        if (s.agent === 'backend' && baseAgent === 'dev') preselected.push(s.source);
        if (s.agent === 'frontend' && baseAgent === 'dev') preselected.push(s.source);
      });
    }
    renderNodeSkills(preselected, isReadonly);
  } else {
    skillsSec.classList.add('hidden');
    promptSec.classList.remove('hidden');
    let initialPrompt = data.prompt || "";
    if (!initialPrompt) {
      const map = { "PM": "project-manager", "BA": "business-analyst", "DESIGN": "designer", "DEV": "developer", "QA": "tester", "COMMIT": "orchestrator", "ARCH": "architect" };
      const legacyKey = map[data.agent] || data.agent.toLowerCase();
      if (AppState.projectAgents[legacyKey]) {
        initialPrompt = AppState.projectAgents[legacyKey].content;
      }
    }
    var promptInput = $('#cfg-prompt-input');
    promptInput.value = initialPrompt;
    promptInput.readOnly = !!isReadonly;
    promptInput.style.opacity = isReadonly ? '0.8' : '1';
  }
}

function closeNodeConfig() {
  var p = document.getElementById('node-config-panel');
  var o = document.getElementById('node-config-overlay');
  if (p) p.classList.remove('active');
  if (o) o.classList.remove('active');
  activeNodeId = null;
  if (editor) {
    editor.drag = false;
    editor.node_selected = null;
    editor.ele_selected = null;
    window.dispatchEvent(new MouseEvent('mouseup'));
    $('#drawflow').dispatchEvent(new MouseEvent('mouseup'));
  }
}

async function renderNodeSkills(selectedSkills, readonly) {
  if (!availableSkills.length) {
    const data = await API.get('/api/skills');
    availableSkills = data.skills || [];
  }
  const list = $('#cfg-skills-list');
  var disabledAttr = readonly ? ' disabled' : '';
  var cursorStyle = readonly ? 'cursor:default;opacity:0.8;' : 'cursor:pointer;';
  list.innerHTML = availableSkills.map(s => {
    const isChecked = selectedSkills && selectedSkills.includes(s.source);
    const descHTML = s.description ? `<div style="font-size:10px;color:var(--text-secondary);margin-top:2px;line-height:1.4;">${escapeHtml(s.description)}</div>` : '';
    return `
      <label style="display:flex;align-items:flex-start;gap:10px;font-size:12px;color:var(--text-primary);${cursorStyle}padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg-secondary);margin-bottom:4px;transition:all 0.15s;" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'">
        <input type="checkbox" class="node-skill-cb" value="${escapeHtml(s.source)}" ${isChecked ? 'checked' : ''}${disabledAttr} style="margin-top:4px;transform:scale(1.1);">
        <div style="flex:1;">
          <div style="font-weight:500;font-size:12px;">${escapeHtml(s.name)}</div>
          ${descHTML}
        </div>
      </label>`;
  }).join('');
}

function saveNodeConfig() {
  if (!activeNodeId) return;
  const node = editor.getNodeFromId(activeNodeId);
  const isReviewer = node.data.type === 'reviewer';

  if (isReviewer) {
    const checked = Array.from($$('.node-skill-cb:checked')).map(cb => cb.value);
    node.data.skills = checked;
    editor.updateNodeDataFromId(activeNodeId, node.data);
  } else {
    const prompt = $('#cfg-prompt-input').value;
    node.data.prompt = prompt;
    editor.updateNodeDataFromId(activeNodeId, node.data);
  }
  markUnsaved();
  closeNodeConfig();
}


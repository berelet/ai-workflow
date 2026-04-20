/**
 * Terminal client — SSE + POST (replaces WebSocket for reliability).
 * Output: EventSource → GET /api/terminal/stream/{session_id}
 * Input:  POST /api/terminal/input/{session_id}
 * Start:  POST /api/terminal/start
 * Stop:   POST /api/terminal/stop/{session_id}
 */

// === Running indicators (topbar dots) ===
function renderRunningIndicators() {
  var el = document.getElementById('running-indicators');
  if (!el) return;
  var running = Object.entries(AppState.sessions || {}).filter(function(e) { return e[1].running; });
  if (!running.length) { el.innerHTML = ''; return; }
  el.innerHTML = running.map(function(e) {
    return '<span style="display:inline-flex;align-items:center;gap:4px"><span style="width:6px;height:6px;border-radius:50%;background:var(--color-success);animation:spin 1s linear infinite"></span>' + escapeHtml(e[0]) + '</span>';
  }).join(' ');
}

// === Terminal (multi-session) ===

const PROVIDER_MODELS = {
  claude: [
    { value: 'opus', label: 'Opus 4.6' },
    { value: 'sonnet', label: 'Sonnet 4.6' },
    { value: 'haiku', label: 'Haiku 4.5' },
  ],
  kiro: [
    { value: 'auto', label: 'Auto (default)' },
    { value: 'claude-sonnet-4-6-v1', label: 'Claude Sonnet 4.6' },
    { value: 'claude-3-7-sonnet-v1', label: 'Claude 3.7 Sonnet' },
    { value: 'claude-3-5-sonnet-v2', label: 'Claude 3.5 Sonnet v2' },
  ],
};

// Check for active session on tab load (reconnect after page reload / phone wake)
async function checkActiveSession() {
  var project = AppState.currentProject;
  if (!project) return;

  // 1. Check if queue is running — show its output
  try {
    var qRes = await API.get('/api/queue/active/list?project_slug=' + encodeURIComponent(project));
    var queues = (qRes && qRes.queues) || [];
    // Show most recent queue (running or recently completed)
    if (queues.length) {
      var q = queues[0]; // most recent
      var qDetail = await API.get('/api/queue/' + q.id);
      // Find running item, or last item with a session
      var targetItem = (qDetail.items || []).find(function(i) { return i.status === 'running'; });
      if (!targetItem) {
        targetItem = (qDetail.items || []).filter(function(i) { return i.terminal_session_id; }).pop();
      }
      if (targetItem && targetItem.terminal_session_id) {
        _showQueueSession(project, targetItem, qDetail);
        return;
      }
    }
  } catch(e) { console.error('checkActiveSession queue error:', e); }

  // 2. Fallback: check for manual active session
  try {
    var res = await API.get('/api/terminal/active?project=' + encodeURIComponent(project));
    if (res.session_id) {
      var s = getSession(project);
      s.sessionId = res.session_id;
      s.running = true;
      s.output = '<span class="t-info">↻ Reconnected to active session...</span>\n';
      if ($('#term-output')) $('#term-output').innerHTML = s.output;
      if ($('#btn-start')) $('#btn-start').disabled = true;
      if ($('#btn-stop')) $('#btn-stop').disabled = false;
      if ($('#term-input-row')) $('#term-input-row').style.display = 'block';
      renderRunningIndicators();
      _connectSSE(project, s);

      // Restore task header
      try {
        var proj = await API.get('/api/projects/' + encodeURIComponent(project));
        var inProgress = (proj.backlog || []).find(function(t) { return t.status === 'in-progress'; });
        if (inProgress) {
          s.taskId = inProgress.id;
          s.taskName = inProgress.task || inProgress.title || '';
          _updateTaskHeader(project);
        }
      } catch(e) {}
    }
  } catch(e) {}
}

// Reconnect SSE when phone wakes up / tab becomes visible
document.addEventListener('visibilitychange', function() {
  if (document.visibilityState !== 'visible') return;
  var project = AppState.currentProject;
  if (!project) return;
  var s = AppState.sessions[project];
  if (!s || !s.running || !s.sessionId) return;
  // If EventSource is dead, reconnect
  if (!s.eventSource || s.eventSource.readyState === 2) {
    _connectSSE(project, s);
  }
});

function updateModelOptions() {
  const provider = $('#term-provider').value;
  const sel = $('#term-model');
  const models = PROVIDER_MODELS[provider] || [];
  sel.innerHTML = models.map((m, i) => `<option value="${m.value}"${i === 0 ? ' selected' : ''}>${m.label}</option>`).join('');
}

function getSession(project) {
  if (!AppState.sessions[project]) {
    AppState.sessions[project] = { sessionId: null, eventSource: null, output: '', running: false, claudeSessionId: null, taskId: null, taskName: null };
  }
  return AppState.sessions[project];
}

function _cleanOutput(d) {
  // Strip ANSI escape sequences
  d = d.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
  d = d.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '');
  d = d.replace(/\x1b[\[\]>()][^\x1b]*?[a-zA-Z]/g, '');
  d = d.replace(/\x1b[>=<][a-zA-Z]?/g, '');
  d = d.replace(/[\x00-\x08\x0e-\x1f]/g, '');
  // Strip cost/pricing info, keep time
  d = d.replace(/\$[\d.,]+[,\s]*/g, '');
  return d;
}

function _setConnStatus(project, status) {
  if (AppState.currentProject !== project) return;
  var el = $('#term-status');
  if (!el) return;
  if (status === 'connected') {
    el.innerHTML = '<span style="color:var(--color-success)">● Connected</span>';
  } else if (status === 'ended') {
    el.textContent = i18n.t('terminal.ready');
  } else if (status === 'error') {
    el.innerHTML = '<span style="color:var(--color-danger)">● Connection error</span>';
  }
}

async function startRun(opts) {
  const project = AppState.currentProject;
  const prompt = $('#term-prompt').value.trim();
  if (!prompt) return;
  const isResume = opts && opts.resume;
  const s = getSession(project);

  // Pick up task context from pending (set by run pipeline modal)
  if (AppState._pendingTaskId) {
    s.taskId = AppState._pendingTaskId;
    s.taskName = AppState._pendingTaskName;
    AppState._pendingTaskId = null;
    AppState._pendingTaskName = null;
  }

  _updateTaskHeader(project);

  if (isResume) {
    s.output += `\n<span class="t-info">&#9656; ${escapeHtml(prompt)}\n\n</span>`;
  } else {
    s.output = `<span class="t-info">&#9654; [${escapeHtml(project)}] ${escapeHtml(prompt.length > 120 ? prompt.slice(0,120) + '...' : prompt)}\n\n</span>`;
    s.claudeSessionId = null;
  }
  s.running = true;
  $('#term-output').innerHTML = s.output;
  $('#term-output').scrollTop = $('#term-output').scrollHeight;
  $('#btn-start').disabled = true;
  $('#btn-stop').disabled = false;
  $('#term-status').textContent = i18n.t('terminal.running');
  $('#term-input-row').style.display = 'block';
  renderRunningIndicators();

  // 1. Start session via POST
  try {
    const payload = {
      project: project,
      prompt: prompt,
      provider: $('#term-provider').value,
      model: $('#term-model').value,
    };
    if (isResume && s.claudeSessionId) payload.claude_session_id = s.claudeSessionId;

    const res = await API.post('/api/terminal/start', payload);
    if (!res.session_id) {
      s.output += `\n<span class="t-error">Failed to start session</span>\n`;
      finishSession(project);
      return;
    }
    s.sessionId = res.session_id;
  } catch (e) {
    s.output += `\n<span class="t-error">${i18n.t('terminal.error')}: ${escapeHtml(e.message || 'start failed')}</span>\n`;
    finishSession(project);
    return;
  }

  // 2. Connect SSE stream
  _connectSSE(project, s);
}

function _connectSSE(project, s) {
  if (s.eventSource) { try { s.eventSource.close(); } catch(e) {} }

  const url = '/api/terminal/stream/' + s.sessionId;
  const es = new EventSource(url);
  s.eventSource = es;

  _setConnStatus(project, 'connected');

  es.onmessage = function(e) {
    try {
      var msg = JSON.parse(e.data);
    } catch(err) { return; }

    if (msg.type === 'output') {
      var d = _cleanOutput(msg.data);
      if (!d.trim()) return;
      d = escapeHtml(d);
      d = d.replace(/(Skills (?:Review|applied).*)/g, '<span class="t-skill">$1</span>');
      d = d.replace(/(Skills:.*)/g, '<span class="t-skill">$1</span>');
      s.output += d;
      if (AppState.currentProject === project) {
        var el = $('#term-output');
        el.innerHTML = s.output;
        el.scrollTop = el.scrollHeight;
        speakNew(s.output);
      }
    } else if (msg.type === 'done') {
      if (msg.claude_session_id) s.claudeSessionId = msg.claude_session_id;
      var doneIcon = (msg.exitCode === 0 || msg.exitCode === '0') ? '&#10003;' : '&#10007;';
      var doneClass = (msg.exitCode === 0 || msg.exitCode === '0') ? 't-done' : 't-error';
      s.output += `\n<span class="${doneClass}">${doneIcon} ${i18n.t('terminal.completed', {code: msg.exitCode})}</span>\n`;
      finishSession(project);
      loadProject();
    }
  };

  es.onerror = function() {
    if (!s.running) { es.close(); return; }

    // If EventSource is CLOSED (not CONNECTING), browser won't auto-retry.
    // This happens after phone sleep/wake. Reconnect manually.
    if (es.readyState === 2) {
      _setConnStatus(project, 'error');
      es.close();
      setTimeout(function() {
        if (s.running && s.sessionId) {
          _setConnStatus(project, 'connected');
          _connectSSE(project, s);
        }
      }, 2000);
    }
  };
}

function finishSession(project) {
  const s = getSession(project);
  s.running = false;
  if (s.eventSource) { try { s.eventSource.close(); } catch(e) {} s.eventSource = null; }
  if (AppState.currentProject === project) {
    $('#term-output').innerHTML = s.output;
    $('#btn-start').disabled = false;
    $('#btn-stop').disabled = true;
    _setConnStatus(project, 'ended');
  }
  renderRunningIndicators();
}

async function stopRun() {
  const project = AppState.currentProject;
  const s = AppState.sessions[project];
  if (s && s.sessionId && s.running) {
    try { await API.post('/api/terminal/stop/' + s.sessionId, {}); } catch(e) {}
  }
  if (s) finishSession(project);
}

function _updateTaskHeader(project) {
  var el = document.getElementById('term-task-header');
  if (!el) return;
  var s = AppState.sessions[project];
  if (!s || !s.taskId) { el.innerHTML = ''; return; }
  el.innerHTML =
    '<span class="term-task-label">#' + escapeHtml(String(s.taskId)) + ' ' + escapeHtml(s.taskName || '') + '</span>' +
    '<div style="display:flex;gap:8px;align-items:center">' +
      '<a href="/artifacts/' + encodeURIComponent(project) + '/' + encodeURIComponent(String(s.taskId)) + '" target="_blank" class="artifact-badge" style="font-size:11px;text-decoration:none">art.</a>' +
      '<button id="btn-complete-task" class="btn-complete-task" onclick="completeTask()">' + i18n.t('terminal.complete_task') + '</button>' +
    '</div>';
  // Check if already done
  API.get('/api/projects/' + encodeURIComponent(project) + '/backlog/' + s.taskId).then(function(item) {
    if (item && item.status === 'done') {
      var btn = document.getElementById('btn-complete-task');
      if (btn) { btn.disabled = true; btn.textContent = '✓ Done'; }
    }
  }).catch(function() {});
}

async function completeTask() {
  var project = AppState.currentProject;
  var s = AppState.sessions[project];
  if (!s || !s.taskId) return;
  var btn = document.getElementById('btn-complete-task');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }
  try {
    var res = await API.post('/api/terminal/complete-task', { project: project, task_id: String(s.taskId) });
    if (res.ok) {
      if (btn) btn.textContent = '✓ Done';
      s.output += '\n<span class="t-done">✓ ' + i18n.t('terminal.task_completed') + '</span>\n';
      var out = $('#term-output');
      if (out) { out.innerHTML = s.output; out.scrollTop = out.scrollHeight; }
    } else {
      if (btn) { btn.disabled = false; btn.textContent = i18n.t('terminal.complete_task'); }
    }
  } catch(e) {
    if (btn) { btn.disabled = false; btn.textContent = i18n.t('terminal.complete_task'); }
  }
}

// --- Queue session viewer (read-only, polls for output) ---
var _queuePollTimer = null;
var _queueCurrentStage = '';
var _queueHeaderCtx = null; // saved for refresh

var _STAGE_PATTERNS = /\b(PM_REVIEW|BA_REVIEW|DEV_REVIEW|QA_REVIEW|ARCH_REVIEW|PM|BA|ARCH|DESIGN|DEV|QA|PERF|COMMIT)\b.*(?:завершено|completed|запущено|started|переходжу|launching|running)/i;
var _STAGE_PATTERN2 = /(?:переходжу до|launching|starting|запускаю)\s+\*{0,2}(PM_REVIEW|BA_REVIEW|DEV_REVIEW|QA_REVIEW|ARCH_REVIEW|PM|BA|ARCH|DESIGN|DEV|QA|PERF|COMMIT)\b/i;

function _detectStage(text) {
  // Try "переходжу до X" first (more specific)
  var m2 = text.match(_STAGE_PATTERN2);
  if (m2) return m2[1].toUpperCase();
  // Fallback: last mention of stage name with action verb
  var m = text.match(_STAGE_PATTERNS);
  if (m) return m[1].toUpperCase();
  return '';
}

function _renderQueueHeader(el, project, queueItem, done, total, taskNum, stage) {
  if (!el) return;
  var stageHtml = stage ? '<span style="font-size:10px;padding:2px 6px;border-radius:3px;background:var(--bg-primary);border:1px solid var(--accent);color:var(--accent)">' + escapeHtml(stage) + '</span>' : '';
  el.innerHTML =
    '<span class="term-task-label">⚡ ' + escapeHtml(queueItem.task_id_display + ' ' + queueItem.title) + ' ' + stageHtml + '</span>' +
    '<div style="display:flex;gap:8px;align-items:center">' +
      '<a href="/artifacts/' + encodeURIComponent(project) + '/' + encodeURIComponent(taskNum) + '" target="_blank" class="artifact-badge" style="font-size:11px;text-decoration:none">art.</a>' +
      '<button onclick="_refreshQueueHeader()" style="background:none;border:1px solid var(--border);border-radius:3px;padding:2px 5px;cursor:pointer;color:var(--text-muted);font-size:11px" title="Refresh">↻</button>' +
    '</div>';
}

async function _refreshQueueHeader() {
  if (!_queueHeaderCtx) return;
  var c = _queueHeaderCtx;
  try {
    var qDetail = await API.get('/api/queue/' + c.queueId);
    var item = (qDetail.items || []).find(function(i) { return i.status === 'running'; });
    if (!item) item = c.queueItem;
    var done = (qDetail.items || []).filter(function(i) { return i.status === 'completed'; }).length;
    var total = (qDetail.items || []).length;
    var taskNum = item.task_id_display.replace(/\D+/g, '');
    var taskHeader = document.getElementById('term-task-header');
    _renderQueueHeader(taskHeader, c.project, item, done, total, taskNum, _queueCurrentStage);
    // If task changed, reconnect to new session
    if (item.terminal_session_id && item.terminal_session_id !== c.sessionId) {
      _showQueueSession(c.project, item, qDetail);
    }
  } catch(e) {}
}

function _showQueueSession(project, queueItem, queueDetail) {
  var out = document.getElementById('term-output');
  var status = document.getElementById('term-status');
  if (!out) { console.error('_showQueueSession: #term-output not found'); return; }

  // Show task in header bar (like normal pipeline run)
  var taskHeader = document.getElementById('term-task-header');
  var done = (queueDetail.items || []).filter(function(i) { return i.status === 'completed'; }).length;
  var total = (queueDetail.items || []).length;
  var taskNum = queueItem.task_id_display.replace(/\D+/g, '');
  _renderQueueHeader(taskHeader, project, queueItem, done, total, taskNum, '');
  out.innerHTML = '';
  _queueCurrentStage = '';

  // Save context for refresh button
  var sessionId = queueItem.terminal_session_id;
  _queueHeaderCtx = { project: project, queueItem: queueItem, queueId: queueDetail.id, sessionId: sessionId };

  var btnStart = document.getElementById('btn-start');
  var btnStop = document.getElementById('btn-stop');
  var inputRow = document.getElementById('term-input-row');
  if (btnStart) btnStart.disabled = true;
  if (btnStop) btnStop.disabled = true;
  if (inputRow) inputRow.style.display = 'none';
  if (status) status.innerHTML = '<span style="color:var(--accent)">● Queue running</span>';

  // Start polling output
  var cursor = 0;

  if (_queuePollTimer) clearInterval(_queuePollTimer);
  _queuePollTimer = setInterval(async function() {
    try {
      var r = await API.get('/api/terminal/poll/' + sessionId + '?cursor=' + cursor);
      if (r.chunks && r.chunks.length) {
        var newText = r.chunks.join('');
        out.innerHTML += escapeHtml(newText);
        out.scrollTop = out.scrollHeight;
        cursor += r.chunks.length;
        // Detect current stage from new output
        var detected = _detectStage(newText);
        if (detected && detected !== _queueCurrentStage) {
          _queueCurrentStage = detected;
          _renderQueueHeader(taskHeader, project, queueItem, done, total, taskNum, detected);
        }
      }
      if (r.done) {
        clearInterval(_queuePollTimer);
        _queuePollTimer = null;
        out.innerHTML += '\n<span class="t-done">✓ Task finished (code ' + (r.exitCode || 0) + ')</span>\n';
        var bs = document.getElementById('btn-start');
        if (bs) bs.disabled = false;
        if (status) status.textContent = i18n.t('terminal.ready');
        // Re-check: maybe next queue item started
        setTimeout(function() { checkActiveSession(); }, 3000);
      }
    } catch(e) {}
  }, 2000);
}

function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

async function sendInput(text) {
  const input = $('#term-input');
  const msg = text || input.value.trim();
  if (!msg) return;
  const s = AppState.sessions[AppState.currentProject];

  if (s && s.sessionId && s.running) {
    // Send via POST
    try {
      await API.post('/api/terminal/input/' + s.sessionId, { data: msg });
    } catch(e) { console.error('sendInput:', e); }
    var out = $('#term-output');
    out.innerHTML += `<div style="color:var(--color-success);border-left:2px solid var(--color-success);padding-left:8px;margin:4px 0">&#9656; ${escapeHtml(msg)}</div>`;
    out.scrollTop = out.scrollHeight;
  } else {
    // No active session — start new run with this as prompt
    $('#term-prompt').value = msg;
    var hasSession = s && s.claudeSessionId;
    startRun(hasSession ? { resume: true } : undefined);
  }
  input.value = '';
  input.style.height = 'auto';
}

// --- File upload ---

// Bind change listener when DOM is ready (Safari iOS needs addEventListener, not inline onchange)
document.addEventListener('DOMContentLoaded', function() {
  _bindFileInput();
});
// Also bind after HTMX swap (terminal tab loaded dynamically)
document.addEventListener('htmx:afterSettle', function() {
  _bindFileInput();
});

function _bindFileInput() {
  var inp = document.getElementById('term-file-input');
  if (inp && !inp._bound) {
    inp._bound = true;
    inp.addEventListener('change', function(e) {
      var file = e.target.files && e.target.files[0];
      if (!file) return;
      e.target.value = '';
      _doTermUpload(file);
    });
  }
}

async function _doTermUpload(file) {
  var form = new FormData();
  form.append('file', file);

  var out = $('#term-output');
  if (out) {
    out.innerHTML += '<div style="color:var(--text-secondary);margin:4px 0">⏳ ' + escapeHtml(file.name) + '...</div>';
    out.scrollTop = out.scrollHeight;
  }

  try {
    var res = await fetch('/api/terminal/upload', {
      method: 'POST',
      credentials: 'same-origin',
      body: form,
    });
    var data = await res.json();
    if (data.error) throw new Error(data.error);

    // Show uploaded file in chat
    if (out) {
      out.innerHTML += '<div style="color:var(--accent);border-left:2px solid var(--accent);padding-left:8px;margin:4px 0">📎 ' + escapeHtml(file.name) + ' (' + _fmtSize(data.size) + ')</div>';
      out.scrollTop = out.scrollHeight;
    }

    // Append file path to prompt input so agent sees it
    var prompt = $('#term-prompt');
    var input = $('#term-input');
    var target = (input && input.offsetParent !== null) ? input : prompt;
    if (target) {
      var prefix = target.value.trim() ? target.value.trim() + '\n' : '';
      target.value = prefix + data.path;
      if (typeof autoGrow === 'function') autoGrow(target);
    }

    // If session is running, also send as input immediately
    var s = AppState.sessions[AppState.currentProject];
    if (s && s.sessionId && s.running) {
      var msg = i18n.t('terminal.file_uploaded', { name: file.name }) + ': ' + data.path;
      await API.post('/api/terminal/input/' + s.sessionId, { data: msg });
    }
  } catch (err) {
    if (out) {
      out.innerHTML += '<div style="color:var(--color-danger);margin:4px 0">✗ ' + i18n.t('terminal.upload_error') + ': ' + escapeHtml(err.message) + '</div>';
      out.scrollTop = out.scrollHeight;
    }
  }
}

function _fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

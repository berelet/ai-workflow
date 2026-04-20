/**
 * Task Queue — select todo/in-progress items, create queue, run all.
 * Preserves selection ORDER — tasks run in the order checkboxes were clicked.
 */

// Ordered list of selected task IDs (preserves click order)
var _queueSelectionOrder = [];

function toggleQueueItem(checkbox) {
  var id = checkbox.value;
  if (checkbox.checked) {
    // Add to end of ordered list
    if (_queueSelectionOrder.indexOf(id) === -1) {
      _queueSelectionOrder.push(id);
    }
  } else {
    // Remove from list
    _queueSelectionOrder = _queueSelectionOrder.filter(function(v) { return v !== id; });
  }
  _updateQueueButton();
}

function _updateQueueButton() {
  var btn = document.getElementById('btn-queue-selected');
  var count = document.getElementById('queue-sel-count');
  if (!btn) return;
  if (_queueSelectionOrder.length > 0) {
    btn.style.display = '';
    count.textContent = _queueSelectionOrder.length;
  } else {
    btn.style.display = 'none';
  }
}

// Legacy compat
function updateQueueSelection() { _updateQueueButton(); }

async function queueSelected() {
  if (!_queueSelectionOrder.length) return;

  var msg = i18n.t('queue.confirm_run', { count: _queueSelectionOrder.length });
  if (!confirm(msg)) return;

  var btn = document.getElementById('btn-queue-selected');
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  try {
    // Create queue — task_ids in selection order
    var res = await API.post('/api/queue/create', {
      project_slug: AppState.currentProject,
      task_ids: _queueSelectionOrder.slice(),
    });
    if (!res.queue_id) throw new Error('Failed to create queue');

    // Start it
    await API.post('/api/queue/' + res.queue_id + '/start', {});

    // Trigger topbar indicator refresh
    var indicator = document.getElementById('queue-indicator-root');
    if (indicator && indicator.__x) {
      indicator.__x.$data.fetchStatus();
    }
  } catch (e) {
    alert(i18n.t('queue.failed') + ': ' + (e.message || e));
  } finally {
    // Reset selection
    _queueSelectionOrder = [];
    document.querySelectorAll('.queue-checkbox:checked').forEach(function(cb) { cb.checked = false; });
    if (btn) { btn.disabled = false; btn.style.display = 'none'; }
  }
}

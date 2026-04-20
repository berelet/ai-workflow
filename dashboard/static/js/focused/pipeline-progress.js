/**
 * Pipeline progress dots on board cards.
 * Fetches stage progress per task and renders inline on cards.
 */

async function loadPipelineProgress() {
  var project = (typeof AppState !== 'undefined' && AppState.currentProject) || '';
  if (!project) return;

  try {
    var data = await API.get('/api/pipeline/project-progress/' + encodeURIComponent(project));
    var items = data.items || {};
    if (!Object.keys(items).length) return;

    // Find all backlog cards and match by UUID in onclick
    var cards = document.querySelectorAll('.backlog-card');
    cards.forEach(function(card) {
      var onclick = card.getAttribute('onclick') || '';
      var match = onclick.match(/openEditModal\('([^']+)'\)/);
      if (!match) return;
      var itemId = match[1];
      var progress = items[itemId];
      if (!progress || !progress.stages || !progress.stages.length) return;

      // Remove old progress bar
      var old = card.querySelector('.pipeline-progress');
      if (old) old.remove();

      // Build progress dots
      var bar = document.createElement('div');
      bar.className = 'pipeline-progress';
      bar.style.cssText = 'display:flex;gap:2px;align-items:center;margin:4px 0 2px;flex-wrap:wrap';

      progress.stages.forEach(function(s) {
        var colors = {
          completed: 'var(--color-success)',
          running: 'var(--accent)',
          failed: 'var(--color-danger)',
          returned: 'var(--color-danger)',
          pending: 'var(--border)',
          skipped: 'var(--border)',
        };
        var icons = {
          completed: '●',
          running: '◉',
          failed: '✗',
          returned: '↩',
          pending: '○',
          skipped: '—',
        };
        var color = colors[s.status] || 'var(--border)';
        var icon = icons[s.status] || '○';

        var dot = document.createElement('span');
        dot.style.cssText = 'font-size:9px;color:' + color + ';white-space:nowrap';
        dot.title = s.stage + ': ' + s.status;
        dot.textContent = icon + s.stage;
        bar.appendChild(dot);
      });

      // Insert after card-title
      var title = card.querySelector('.card-title');
      if (title) title.insertAdjacentElement('afterend', bar);
    });
  } catch(e) {}
}

// Load on board tab render
document.addEventListener('htmx:afterSettle', function() {
  setTimeout(loadPipelineProgress, 500);
});
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(loadPipelineProgress, 1000);
});

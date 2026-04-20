/**
 * Audio recording (MediaRecorder) + Whisper transcription (SSE).
 * Extracted from dashboard-legacy.js — depends on API, i18n.
 */

// === Transcriber ===

let recMediaRecorder = null;
let recChunks = [];
let recBlob = null;
let recTimerInterval = null;
let recStartTime = 0;
let recDisplayStream = null;

function updateRecTimer() {
  const el = $('#rec-timer');
  const s = Math.floor((Date.now() - recStartTime) / 1000);
  const m = Math.floor(s / 60);
  el.textContent = `${String(m).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
}

async function toggleRecording() {
  if (recMediaRecorder && recMediaRecorder.state === 'recording') return;
  const useSystem = $('#rec-system').checked;
  try {
    const streams = [];
    if (useSystem) {
      recDisplayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      const audioTrack = recDisplayStream.getAudioTracks()[0];
      if (audioTrack) streams.push(new MediaStream([audioTrack]));
      recDisplayStream.getVideoTracks().forEach(t => t.stop());
    }
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      streams.push(mic);
    } catch(e) { console.warn('No mic:', e); }
    if (!streams.length) return;
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    streams.forEach(s => ctx.createMediaStreamSource(s).connect(dest));
    recChunks = [];
    recMediaRecorder = new MediaRecorder(dest.stream, { mimeType: 'audio/webm;codecs=opus' });
    recMediaRecorder.ondataavailable = e => { if (e.data.size) recChunks.push(e.data); };
    recMediaRecorder.onstop = () => {
      recBlob = new Blob(recChunks, { type: 'audio/webm' });
      const url = URL.createObjectURL(recBlob);
      $('#rec-audio').src = url;
      $('#rec-preview').classList.remove('hidden');
      streams.forEach(s => s.getTracks().forEach(t => t.stop()));
      if (recDisplayStream) { recDisplayStream.getTracks().forEach(t => t.stop()); recDisplayStream = null; }
    };
    recMediaRecorder.start(1000);
    recStartTime = Date.now();
    recTimerInterval = setInterval(updateRecTimer, 1000);
    $('#rec-status').style.color = 'var(--color-danger)';
    $('#btn-rec').disabled = true;
    $('#btn-rec-stop').disabled = false;
    $('#btn-rec-stop').style.borderColor = 'var(--color-danger)';
    $('#btn-rec-stop').style.color = 'var(--color-danger)';
  } catch(e) { console.error('Recording error:', e); }
}

function stopRecording() {
  if (recMediaRecorder && recMediaRecorder.state === 'recording') {
    recMediaRecorder.stop();
    clearInterval(recTimerInterval);
    $('#rec-status').style.color = '';
    $('#btn-rec').disabled = false;
    $('#btn-rec-stop').disabled = true;
    $('#btn-rec-stop').style.borderColor = 'var(--border)';
    $('#btn-rec-stop').style.color = 'var(--text-muted)';
  }
}

function discardRecording() {
  recBlob = null;
  $('#rec-preview').classList.add('hidden');
  $('#rec-timer').textContent = '00:00';
}

async function uploadRecBlob() {
  if (!recBlob) return null;
  const fd = new FormData();
  fd.append('audio', recBlob, 'recording.webm');
  const res = await API.postForm('/api/transcriber/upload', fd);
  return res.filename;
}

async function uploadOnly() {
  const fname = await uploadRecBlob();
  if (fname) { discardRecording(); loadRecordings(); }
}

// Whisper model persistence
function getWhisperModel() { return $('#whisper-model').value; }

function initWhisperModel() {
  const sel = $('#whisper-model');
  const saved = localStorage.getItem('whisper-model');
  if (saved && ['tiny','base','small','medium','large-v3'].includes(saved)) {
    sel.value = saved;
  } else {
    sel.value = 'base';
    localStorage.setItem('whisper-model', 'base');
  }
  sel.addEventListener('change', () => { localStorage.setItem('whisper-model', sel.value); });
}

// Phase & Progress
let _transcribePhase = 'idle';

function setTranscribePhase(phase, detail) {
  _transcribePhase = phase;
  const iconEl = $('#phase-icon');
  const textEl = $('#phase-text');
  const trackEl = $('#progress-track');
  const fillEl = $('#progress-fill');
  const detailsEl = $('#progress-details');

  iconEl.innerHTML = '';
  iconEl.className = 'phase-icon';
  textEl.textContent = '';
  textEl.style.color = '';
  trackEl.style.display = 'none';
  detailsEl.style.display = 'none';
  fillEl.classList.remove('pulsing');
  fillEl.style.width = '0%';

  const busy = phase === 'loading_model' || phase === 'transcribing';
  setTranscribeButtonsDisabled(busy);

  if (phase === 'idle') return;
  if (phase === 'loading_model') {
    iconEl.innerHTML = '<div class="transcribe-spinner"></div>';
    textEl.textContent = i18n.t('common.loading') + ' ' + (detail || '');
    textEl.style.color = 'var(--text-muted)';
    return;
  }
  if (phase === 'transcribing') {
    iconEl.innerHTML = '<div class="transcribe-spinner"></div>';
    textEl.textContent = i18n.t('transcriber.transcribe') + '...';
    textEl.style.color = 'var(--color-success)';
    trackEl.style.display = 'block';
    detailsEl.style.display = 'flex';
    fillEl.classList.add('pulsing');
    return;
  }
  if (phase === 'completed') {
    iconEl.innerHTML = '<span class="phase-check">&#10003;</span>';
    textEl.textContent = i18n.t('terminal.ready');
    textEl.style.color = 'var(--color-success)';
    trackEl.style.display = 'block';
    fillEl.style.width = '100%';
    fillEl.classList.remove('pulsing');
    setTimeout(() => { setTranscribePhase('idle'); }, 5000);
    return;
  }
  if (phase === 'error') {
    iconEl.innerHTML = '<span class="phase-error-icon">!</span>';
    textEl.textContent = detail || i18n.t('common.error');
    textEl.style.color = 'var(--color-danger)';
    return;
  }
}

function updateProgress(percent, segmentsDone, etaSeconds) {
  if (typeof percent !== 'number' || isNaN(percent)) return;
  percent = Math.min(100, Math.max(0, percent));
  const fillEl = $('#progress-fill');
  const percentEl = $('#progress-percent');
  const etaEl = $('#progress-eta');
  const trackEl = $('#progress-track');
  const detailsEl = $('#progress-details');
  trackEl.style.display = 'block';
  detailsEl.style.display = 'flex';
  fillEl.style.width = percent + '%';
  percentEl.textContent = `${percent}% (${segmentsDone} seg.)`;
  if (typeof etaSeconds === 'number' && !isNaN(etaSeconds) && etaSeconds > 0) {
    etaEl.textContent = `~${etaSeconds}s`;
  } else {
    etaEl.textContent = '';
  }
}

function setTranscribeButtonsDisabled(disabled) {
  const modelSel = $('#whisper-model');
  const transcribeBtn = document.querySelector('#rec-preview button[onclick*="uploadAndTranscribe"]');
  const existingBtns = $$('button[onclick^="transcribeExisting"]');
  if (disabled) {
    modelSel.disabled = true;
    if (transcribeBtn) transcribeBtn.classList.add('transcribe-disabled');
    existingBtns.forEach(b => b.classList.add('transcribe-disabled'));
  } else {
    modelSel.disabled = false;
    if (transcribeBtn) transcribeBtn.classList.remove('transcribe-disabled');
    existingBtns.forEach(b => b.classList.remove('transcribe-disabled'));
  }
}

// SSE transcription
async function runTranscribeSSE(filename) {
  const model = getWhisperModel();
  const log = $('#rec-log');
  log.style.display = 'block';
  log.textContent = '';
  setTranscribePhase('loading_model', model);
  try {
    const response = await API.raw(`/api/transcriber/transcribe/${filename}?model=${encodeURIComponent(model)}&stream=true`, { method: 'POST' });
    if (!response.ok) {
      setTranscribePhase('error', `HTTP ${response.status}`);
      log.textContent = `Error: HTTP ${response.status}`;
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let evt;
          try { evt = JSON.parse(line.slice(6)); } catch(e) { continue; }
          if (evt.type === 'phase') {
            if (evt.phase === 'loading_model') {
              setTranscribePhase('loading_model', evt.model);
              log.textContent += `Loading model: ${evt.model}\n`;
            } else if (evt.phase === 'transcribing') {
              setTranscribePhase('transcribing');
              log.textContent += `Transcribing (duration: ${evt.duration || '?'}s)...\n`;
            } else if (evt.phase === 'completed') {
              setTranscribePhase('completed');
              log.textContent += '\nDone!\n';
              loadRecordings();
            } else if (evt.phase === 'error') {
              setTranscribePhase('error', evt.message);
              log.textContent += `\nError: ${evt.message}\n`;
            }
          } else if (evt.type === 'progress') {
            updateProgress(evt.percent, evt.segments_done, evt.eta_seconds);
          }
        }
      }
    } finally {
      try { reader.cancel(); } catch(e) {}
    }
  } catch(e) {
    setTranscribePhase('error', e.message);
    log.textContent += `\nError: ${e.message}\n`;
  }
}

async function uploadAndTranscribe() {
  if (_transcribePhase === 'loading_model' || _transcribePhase === 'transcribing') return;
  const fname = await uploadRecBlob();
  if (!fname) return;
  discardRecording();
  await runTranscribeSSE(fname);
}

async function loadRecordings() {
  const list = $('#recordings-list');
  if (!list) return;
  const recs = await API.get('/api/transcriber/recordings');
  if (!recs.length) {
    list.innerHTML = `<div style="color:var(--text-muted);font-size:11px;padding:20px;text-align:center">${i18n.t('transcriber.no_recordings')}</div>`;
    return;
  }
  list.innerHTML = recs.map(r => {
    const size = (r.size / 1024 / 1024).toFixed(1);
    const badge = r.has_transcript
      ? '<span style="border:1px solid var(--color-success);color:var(--color-success);padding:1px 6px;font-size:10px">text</span>'
      : '<span style="border:1px solid var(--border);color:var(--text-muted);padding:1px 6px;font-size:10px">no text</span>';
    const safeFilename = escapeHtml(r.filename);
    const transcript = r.transcript
      ? `<div style="margin-top:8px;padding:10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px;color:var(--text-secondary);max-height:150px;overflow-y:auto;line-height:1.5;white-space:pre-wrap">${escapeHtml(r.transcript.slice(0, 1000))}${r.transcript.length > 1000 ? '...' : ''}</div>`
      : '';
    const disabledClass = (_transcribePhase === 'loading_model' || _transcribePhase === 'transcribing') ? 'transcribe-disabled' : '';
    return `<div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <div><span style="font-size:12px;color:var(--text-primary)">${safeFilename}</span> <span style="font-size:11px;color:var(--text-muted)">${size} MB</span></div>
        <div style="display:flex;gap:6px;align-items:center">
          ${badge}
          ${!r.has_transcript ? `<button onclick="transcribeExisting('${safeFilename}')" class="${disabledClass}" style="padding:2px 10px;border:1px solid var(--color-success);background:transparent;color:var(--color-success);cursor:pointer;font-family:var(--font);font-size:10px;border-radius:var(--radius-sm)">${i18n.t('transcriber.transcribe')}</button>` : ''}
          <button onclick="deleteRecording('${safeFilename}')" style="padding:2px 8px;border:1px solid var(--color-danger);background:transparent;color:var(--color-danger);cursor:pointer;font-family:var(--font);font-size:10px;border-radius:var(--radius-sm)">&times;</button>
        </div>
      </div>
      ${transcript}
    </div>`;
  }).join('');
}

async function transcribeExisting(filename) {
  if (_transcribePhase === 'loading_model' || _transcribePhase === 'transcribing') return;
  await runTranscribeSSE(filename);
}

async function deleteRecording(filename) {
  if (!confirm(i18n.t('common.delete') + ': ' + filename + '?')) return;
  await API.del(`/api/transcriber/recordings/${filename}`);
  loadRecordings();
}


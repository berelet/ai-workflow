/**
 * Voice input (Web Speech API) + Text-to-Speech.
 * Extracted from dashboard-legacy.js — browser APIs only.
 */

// === Voice input (Web Speech API) ===

let _recognition = null;
let _micActive = false;
let _micTarget = null;

function initRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.lang = i18n.getSpeechLang();
  r.continuous = true;
  r.interimResults = true;
  r.onresult = (e) => {
    if (!_micTarget) return;
    let final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) final += e.results[i][0].transcript;
    }
    if (final) {
      _micTarget.value += (_micTarget.value && !_micTarget.value.endsWith(' ') ? ' ' : '') + final;
      _micTarget.dispatchEvent(new Event('input'));
    }
  };
  r.onend = () => { if (_micActive) r.start(); };
  r.onerror = () => { stopMic(); };
  return r;
}

function toggleMic(targetId) {
  if (_micActive) { stopMic(); return; }
  if (!_recognition) _recognition = initRecognition();
  if (!_recognition) return;
  _micTarget = document.getElementById(targetId || 'term-input');
  _micActive = true;
  _recognition.start();
  $('#btn-mic').style.color = '#ef4444';
  $('#btn-mic').style.borderColor = '#ef4444';
}

function stopMic() {
  _micActive = false;
  if (_recognition) try { _recognition.stop(); } catch(e) {}
  const btn = $('#btn-mic');
  if (btn) { btn.style.color = 'var(--text-secondary)'; btn.style.borderColor = 'var(--border)'; }
  $$('[id^="btn-mic"]').forEach(b => { b.style.color = 'var(--text-secondary)'; b.style.borderColor = 'var(--border)'; });
}

function toggleMicFor(targetId) {
  if (_micActive && _micTarget === document.getElementById(targetId)) { stopMic(); return; }
  stopMic();
  if (!_recognition) _recognition = initRecognition();
  if (!_recognition) return;
  _micTarget = document.getElementById(targetId);
  _micActive = true;
  _recognition.start();
  const btn = $('#btn-mic-desc');
  if (btn) { btn.style.color = '#ef4444'; btn.style.borderColor = '#ef4444'; }
}

// === TTS ===

let _ttsEnabled = false;
let _ttsLastLen = 0;

function toggleTTS() {
  _ttsEnabled = !_ttsEnabled;
  const btn = $('#btn-tts');
  if (_ttsEnabled) {
    btn.style.color = 'var(--accent)';
    btn.style.borderColor = 'var(--accent)';
    btn.innerHTML = '&#128264; ON';
    _ttsLastLen = (AppState.sessions[AppState.currentProject]?.output || '').length;
  } else {
    btn.style.color = 'var(--text-secondary)';
    btn.style.borderColor = 'var(--border)';
    btn.innerHTML = '&#128264;';
    speechSynthesis.cancel();
  }
}

function speakNew(fullOutput) {
  if (!_ttsEnabled) return;
  const newText = fullOutput.slice(_ttsLastLen).replace(/<[^>]+>/g, '').trim();
  _ttsLastLen = fullOutput.length;
  if (!newText || newText.length < 10) return;
  const u = new SpeechSynthesisUtterance(newText);
  u.lang = i18n.getSpeechLang();
  u.rate = 1.1;
  speechSynthesis.speak(u);
}


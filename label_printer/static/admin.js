/* ═══════════════════════════════════════════════════
   Cake A Wish — Admin
   ═══════════════════════════════════════════════════ */

// ── DOM refs ──────────────────────────────────────────
const canvas      = document.getElementById('preview');
const ctx         = canvas.getContext('2d');
const pill        = document.getElementById('pill');
const tplList     = document.getElementById('tpl-list');
const brightness  = document.getElementById('brightness');
const brightnessV = document.getElementById('brightness-val');
const rotateBtn   = document.getElementById('rotate-btn');
const captureBtn  = document.getElementById('capture-btn');
const quickBtn    = document.getElementById('quick-btn');
const loadInput   = document.getElementById('load-input');
const loadBtn     = document.getElementById('load-btn');
const saveBtn     = document.getElementById('save-btn');
const printBtn    = document.getElementById('print-btn');
const gallery     = document.getElementById('gallery');
const printerIp   = document.getElementById('printer-ip');
const statusBar   = document.getElementById('status-bar');
const video       = document.getElementById('video');

// ── Offscreen canvas (feeds server preview) ───────────
const offCanvas = document.createElement('canvas');
const offCtx    = offCanvas.getContext('2d');

// ── State ─────────────────────────────────────────────
const s = {
  // label / printer
  label:    null,
  labelW:   696,
  labelH:   1044,
  printerOk: false,

  // template
  frameId:  null,
  overlay:  null,   // HTMLImageElement for live compositing

  // image transform
  fitMode:  'contain',
  mirror:   true,
  rotation: 0,
  brightness: 0,

  // capture / live
  captured:    false,
  capturedImg: null,  // ImageBitmap

  // server preview anti-flicker
  hasServerPreview: false,
  previewKey:       null,
  previewSeq:       0,

  // camera
  cameraReady: false,
  liveTimer:   null,
};

// ── Helpers ───────────────────────────────────────────
function setStatus(msg, cls) {
  statusBar.textContent = msg;
  statusBar.className   = cls || '';
}

function setPill(label, cls) {
  pill.textContent = label;
  pill.className   = `pill ${cls}`;
}

function updateButtons() {
  const hasCap = s.captured;
  captureBtn.textContent = hasCap ? 'Retake' : 'Capture';
  captureBtn.classList.toggle('retake', hasCap);
  quickBtn.disabled = !s.cameraReady;
  saveBtn.disabled  = !hasCap;
  printBtn.disabled = !hasCap;
}

// ── Canvas sizing ─────────────────────────────────────
function applyLabel(w, h) {
  s.labelW = w;
  s.labelH = h;
  canvas.width     = w;
  canvas.height    = h;
  offCanvas.width  = w;
  offCanvas.height = h;
}

// ── Draw helpers ──────────────────────────────────────
function drawSource(c, src) {
  const cw = c.canvas.width;
  const ch = c.canvas.height;
  const sw = src.videoWidth  || src.naturalWidth  || src.width;
  const sh = src.videoHeight || src.naturalHeight || src.height;

  c.save();
  c.translate(cw / 2, ch / 2);
  if (s.rotation) c.rotate(s.rotation * Math.PI / 180);
  if (s.mirror)   c.scale(-1, 1);

  let dw, dh;
  if (s.fitMode === 'stretch') {
    dw = cw; dh = ch;
  } else if (s.fitMode === 'cover') {
    const scale = Math.max(cw / sw, ch / sh);
    dw = sw * scale; dh = sh * scale;
  } else {
    const scale = Math.min(cw / sw, ch / sh);
    dw = sw * scale; dh = sh * scale;
  }

  c.drawImage(src, -dw / 2, -dh / 2, dw, dh);
  c.restore();

  if (s.brightness !== 0) {
    const bv = s.brightness * 2.55;
    const id = c.getImageData(0, 0, cw, ch);
    const d  = id.data;
    for (let i = 0; i < d.length; i += 4) {
      d[i]   = Math.max(0, Math.min(255, d[i]   + bv));
      d[i+1] = Math.max(0, Math.min(255, d[i+1] + bv));
      d[i+2] = Math.max(0, Math.min(255, d[i+2] + bv));
    }
    c.putImageData(id, 0, 0);
  }
}

function drawOverlay() {
  if (!s.overlay) return;
  ctx.drawImage(s.overlay, 0, 0, s.labelW, s.labelH);
}

// ── Render ────────────────────────────────────────────
function render() {
  if (!s.labelW) return;

  if (!s.captured) {
    if (!s.cameraReady) return;
    drawSource(ctx, video);
    drawOverlay();
    return;
  }

  const key = `${s.frameId}|${s.fitMode}|${s.mirror}|${s.rotation}|${s.brightness}`;
  if (key === s.previewKey) return;

  s.previewKey = key;
  s.hasServerPreview = false;

  // Show local preview immediately while waiting for server
  drawSource(ctx, s.capturedImg);
  drawOverlay();

  // Build offscreen and request server preview
  drawSource(offCtx, s.capturedImg);
  fetchServerPreview(offCanvas.toDataURL('image/png'));
}

async function fetchServerPreview(dataUrl) {
  const seq = ++s.previewSeq;
  try {
    const res = await fetch('/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: dataUrl, label: s.label || '62red', frame_id: s.frameId }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (seq !== s.previewSeq) return; // stale — newer request in flight

    const img = new Image();
    img.onload = () => {
      if (seq !== s.previewSeq) return;
      ctx.drawImage(img, 0, 0, s.labelW, s.labelH);
      s.hasServerPreview = true;
    };
    img.src = data.image_data;
  } catch { /* keep local preview */ }
}

// ── Template overlay (live compositing) ──────────────
async function loadOverlay(frameId) {
  s.overlay = null;
  if (!frameId) return;
  try {
    const img = new Image();
    img.src   = `/frames/${frameId}/overlay.png?w=${s.labelW}&h=${s.labelH}&t=${Date.now()}`;
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });
    s.overlay = img;
  } catch { /* no overlay */ }
}

// ── Camera ────────────────────────────────────────────
async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    video.srcObject = stream;
    await video.play();
    s.cameraReady = true;
    updateButtons();
    s.liveTimer = setInterval(render, 80);
  } catch (e) {
    setStatus('Camera unavailable: ' + e.message, 'err');
  }
}

function stopLive() {
  clearInterval(s.liveTimer);
  s.liveTimer = null;
}

// ── Capture ───────────────────────────────────────────
async function doCapture() {
  if (s.captured) {
    // Retake
    s.captured         = false;
    s.capturedImg      = null;
    s.previewKey       = null;
    s.hasServerPreview = false;
    s.previewSeq++;
    updateButtons();
    s.liveTimer = setInterval(render, 80);
    return;
  }
  stopLive();
  s.capturedImg = await createImageBitmap(video);
  s.captured    = true;
  s.previewKey  = null;
  updateButtons();
  render();
}

// ── Load from file / dataUrl ──────────────────────────
function loadFromBitmap(bmp) {
  stopLive();
  s.capturedImg      = bmp;
  s.captured         = true;
  s.previewKey       = null;
  s.hasServerPreview = false;
  s.previewSeq++;
  updateButtons();
  render();
}

function loadFromFile(file) {
  const reader = new FileReader();
  reader.onload = e => {
    const img = new Image();
    img.onload = async () => loadFromBitmap(await createImageBitmap(img));
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

function loadFromDataUrl(dataUrl) {
  const img = new Image();
  img.onload = async () => loadFromBitmap(await createImageBitmap(img));
  img.src = dataUrl;
}

// ── Save ──────────────────────────────────────────────
function doSave() {
  const a    = document.createElement('a');
  a.download = `cakeawish-${Date.now()}.png`;
  a.href     = canvas.toDataURL('image/png');
  a.click();
}

// ── Print ─────────────────────────────────────────────
async function doPrint() {
  if (!s.capturedImg) return;
  drawSource(offCtx, s.capturedImg);
  const dataUrl = offCanvas.toDataURL('image/png');
  const ip      = printerIp.value.trim();
  const label   = s.label || '62red';

  printBtn.disabled = true;
  printBtn.classList.add('busy');
  setStatus('Sending to printer…');

  try {
    const res  = await fetch('/print', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: dataUrl, printer_ip: ip, label, frame_id: s.frameId }),
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus('Print failed: ' + (data.detail || res.statusText), 'err');
    } else {
      setStatus('Printed!', 'ok');
      loadGallery();
    }
  } catch (e) {
    setStatus('Network error: ' + e.message, 'err');
  } finally {
    printBtn.classList.remove('busy');
    updateButtons();
  }
}

async function doQuickPrint() {
  if (!s.cameraReady) return;
  stopLive();
  s.capturedImg = await createImageBitmap(video);
  s.captured    = true;
  s.previewKey  = null;
  s.hasServerPreview = false;
  s.previewSeq++;
  updateButtons();
  render();
  doPrint();
}

// ── Gallery ───────────────────────────────────────────
async function loadGallery() {
  try {
    const res  = await fetch('/history');
    const data = await res.json();
    gallery.innerHTML = '';
    data.forEach(item => {
      const el = document.createElement('div');
      el.className = 'g-item';
      el.innerHTML = `<img src="${item.thumbnail}" alt="print"><div class="g-hover">✏️</div>`;
      el.addEventListener('click', () => loadFromDataUrl(item.raw));
      gallery.appendChild(el);
    });
  } catch { /* ignore */ }
}

// ── Templates ─────────────────────────────────────────
async function loadTemplates() {
  try {
    const res  = await fetch('/frames');
    const tpls = await res.json();
    const all  = [{ id: null, name: 'None' }, ...tpls];

    all.forEach(t => {
      const btn  = document.createElement('button');
      btn.className   = 'tpl-btn' + (t.id === s.frameId ? ' active' : '');
      btn.dataset.fid = t.id ?? '';

      const icon = document.createElement('div');
      icon.className   = 'tpl-icon';
      icon.textContent = t.id === null ? '⊘' : t.name[0];
      btn.appendChild(icon);

      const name = document.createElement('span');
      name.className   = 'tpl-name';
      name.textContent = t.name;
      btn.appendChild(name);

      btn.addEventListener('click', () => selectTemplate(t.id, btn));
      tplList.appendChild(btn);
    });
  } catch { /* frames unavailable */ }
}

async function selectTemplate(frameId, btn) {
  s.frameId = frameId || null;
  tplList.querySelectorAll('.tpl-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  loadOverlay(s.frameId);

  if (s.captured) {
    s.previewKey = null;
    render();
  }
}

// ── Printer polling ───────────────────────────────────
async function pollPrinter() {
  const ip = printerIp.value.trim();
  if (!ip) return;
  try {
    const res  = await fetch(`/printer/status?printer_ip=${encodeURIComponent(ip)}`);
    const data = await res.json();

    if (!data.connected) { setPill('Offline', 'offline'); return; }
    if (data.errors && data.errors.length) { setPill('Error', 'error'); return; }

    if (data.phase_type === 'Printing') {
      setPill('Printing…', 'printing');
    } else {
      setPill(data.label || 'Online', 'online');
    }

    if (data.label && data.label !== s.label) {
      s.label = data.label;
      updateLabelDims(data.label);
    }
  } catch {
    setPill('Offline', 'offline');
  }
}

async function updateLabelDims(labelId) {
  try {
    const res    = await fetch('/labels');
    const labels = await res.json();
    const found  = labels.find(l => l.id === labelId);
    if (found && (found.width !== s.labelW || found.height !== s.labelH)) {
      applyLabel(found.width, found.height);
      if (s.frameId) loadOverlay(s.frameId);
      s.previewKey = null;
      render();
    }
  } catch { /* keep current dims */ }
}

// ── Segmented controls ────────────────────────────────
document.querySelectorAll('.seg-wrap').forEach(wrap => {
  wrap.addEventListener('click', e => {
    const btn = e.target.closest('.seg');
    if (!btn) return;
    wrap.querySelectorAll('.seg').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const key = wrap.dataset.key;
    const val = btn.dataset.val;
    if (key === 'fitMode') s.fitMode = val;
    if (key === 'mirror')  s.mirror  = val === 'on';
    if (s.captured) { s.previewKey = null; render(); }
  });
});

// ── Event wiring ──────────────────────────────────────
captureBtn.addEventListener('click', doCapture);
quickBtn.addEventListener('click', doQuickPrint);
loadBtn.addEventListener('click', () => loadInput.click());
loadInput.addEventListener('change', e => { if (e.target.files[0]) loadFromFile(e.target.files[0]); });
saveBtn.addEventListener('click', doSave);
printBtn.addEventListener('click', doPrint);

rotateBtn.addEventListener('click', () => {
  s.rotation = (s.rotation + 90) % 360;
  if (s.captured) { s.previewKey = null; render(); }
});

brightness.addEventListener('input', () => {
  s.brightness             = +brightness.value;
  brightnessV.textContent  = s.brightness;
  if (s.captured) { s.previewKey = null; render(); }
});

printerIp.addEventListener('change', () => {
  s.label = null;
  pollPrinter();
});

// ── Init ──────────────────────────────────────────────
(async function init() {
  applyLabel(s.labelW, s.labelH);
  await loadTemplates();
  await loadGallery();
  await startCamera();
  pollPrinter();
  setInterval(pollPrinter, 2000);
  setInterval(loadGallery, 10000);
})();

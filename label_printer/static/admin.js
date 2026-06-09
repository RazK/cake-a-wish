/* ── DOM ─────────────────────────────────────────── */
const canvas    = document.getElementById('preview');
const ctx       = canvas.getContext('2d');
const pill      = document.getElementById('pill');
const tplList   = document.getElementById('tpl-list');
const brtSlider = document.getElementById('brightness');
const brtOut    = document.getElementById('brightness-out');
const rotateBtn = document.getElementById('rotate-btn');
const captureBtn= document.getElementById('capture-btn');
const quickBtn  = document.getElementById('quick-btn');
const loadInput = document.getElementById('load-input');
const loadBtn   = document.getElementById('load-btn');
const saveBtn   = document.getElementById('save-btn');
const printBtn  = document.getElementById('print-btn');
const gallery   = document.getElementById('gallery');
const ipInput   = document.getElementById('printer-ip');
const statusBar = document.getElementById('status-bar');
const video     = document.getElementById('video');

/* ── Offscreen canvas for server calls ──────────── */
const off    = document.createElement('canvas');
const offCtx = off.getContext('2d');

/* ── State ───────────────────────────────────────── */
const s = {
  labelW: 696, labelH: 1044,   // canvas buffer size, updated from printer poll
  frameId: null,                // selected template id (null = none)
  overlay: null,                // HTMLImageElement for live compositing

  fitMode:    'contain',
  mirror:     true,
  rotation:   0,
  brightness: 0,

  captured:    false,
  capturedBmp: null,            // ImageBitmap captured from camera / file

  previewKey: null,             // last key we sent to server; null = needs refresh
  previewSeq: 0,                // incremented on every server fetch; stale responses ignored

  cameraOn: false,
  liveTimer: null,
};

/* ── Helpers ─────────────────────────────────────── */
function status(msg, cls) {
  statusBar.textContent = msg;
  statusBar.className   = cls || '';
}

function setPill(text, cls) {
  pill.textContent = text;
  pill.className   = 'pill' + (cls ? ' ' + cls : '');
}

function syncButtons() {
  captureBtn.textContent = s.captured ? 'Retake' : 'Capture';
  captureBtn.classList.toggle('retake', s.captured);
  quickBtn.disabled = !s.cameraOn;
  saveBtn.disabled  = !s.captured;
  printBtn.disabled = !s.captured;
}

/* ── Canvas setup ────────────────────────────────── */
function setLabel(w, h) {
  if (s.labelW === w && s.labelH === h) return;
  s.labelW = w; s.labelH = h;
  canvas.width  = w; canvas.height  = h;
  off.width     = w; off.height     = h;
  if (s.frameId) loadOverlay(s.frameId);
  s.previewKey = null;
}

/* ── Draw ────────────────────────────────────────── */
function drawSrc(c, src) {
  const cw = c.canvas.width, ch = c.canvas.height;
  const sw = src.videoWidth  || src.naturalWidth  || src.width  || cw;
  const sh = src.videoHeight || src.naturalHeight || src.height || ch;

  c.save();
  c.translate(cw / 2, ch / 2);
  if (s.rotation) c.rotate(s.rotation * Math.PI / 180);
  if (s.mirror)   c.scale(-1, 1);

  let dw, dh;
  if (s.fitMode === 'stretch') {
    dw = cw; dh = ch;
  } else if (s.fitMode === 'cover') {
    const sc = Math.max(cw / sw, ch / sh);
    dw = sw * sc; dh = sh * sc;
  } else {
    const sc = Math.min(cw / sw, ch / sh);
    dw = sw * sc; dh = sh * sc;
  }
  c.drawImage(src, -dw / 2, -dh / 2, dw, dh);
  c.restore();

  if (s.brightness !== 0) {
    const d  = c.getImageData(0, 0, cw, ch);
    const px = d.data;
    const bv = s.brightness * 2.55;
    for (let i = 0; i < px.length; i += 4) {
      px[i]   = Math.max(0, Math.min(255, px[i]   + bv));
      px[i+1] = Math.max(0, Math.min(255, px[i+1] + bv));
      px[i+2] = Math.max(0, Math.min(255, px[i+2] + bv));
    }
    c.putImageData(d, 0, 0);
  }
}

function drawOverlayOnMain() {
  if (s.overlay) ctx.drawImage(s.overlay, 0, 0, s.labelW, s.labelH);
}

/* ── Render loop ─────────────────────────────────── */
function render() {
  if (!s.captured) {
    // Live: draw video + overlay every tick
    if (!s.cameraOn) return;
    drawSrc(ctx, video);
    drawOverlayOnMain();
    return;
  }

  // Captured: only act when something changed
  const key = `${s.frameId}|${s.fitMode}|${s.mirror}|${s.rotation}|${s.brightness}`;
  if (key === s.previewKey) return;
  s.previewKey = key;

  // Local preview first (instant, no flicker wait)
  drawSrc(ctx, s.capturedBmp);
  drawOverlayOnMain();

  // Server preview in background
  drawSrc(offCtx, s.capturedBmp);
  fetchPreview(off.toDataURL('image/png'));
}

async function fetchPreview(dataUrl) {
  const seq = ++s.previewSeq;
  try {
    const r = await fetch('/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: dataUrl, template_id: s.frameId }),
    });
    if (!r.ok) return;
    const { image_data } = await r.json();
    if (seq !== s.previewSeq) return; // stale
    const img = new Image();
    img.onload = () => { if (seq === s.previewSeq) ctx.drawImage(img, 0, 0, s.labelW, s.labelH); };
    img.src = image_data;
  } catch { /* keep local preview */ }
}

/* ── Template overlay (live compositing) ─────────── */
async function loadOverlay(frameId) {
  s.overlay = null;
  if (!frameId) return;
  try {
    const img = new Image();
    img.src = `/templates/${frameId}/overlay.png?w=${s.labelW}&h=${s.labelH}&_=${Date.now()}`;
    await new Promise((ok, fail) => { img.onload = ok; img.onerror = fail; });
    s.overlay = img;
  } catch { /* no overlay for this template */ }
}

/* ── Camera ──────────────────────────────────────── */
async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    video.srcObject = stream;
    await video.play();
    s.cameraOn = true;
    syncButtons();
    s.liveTimer = setInterval(render, 80);
  } catch (e) {
    status('Camera unavailable: ' + e.message, 'err');
  }
}

function stopLive() {
  clearInterval(s.liveTimer);
  s.liveTimer = null;
}

/* ── Capture ─────────────────────────────────────── */
async function capture() {
  if (s.captured) {
    // Retake → go back to live
    s.captured    = false;
    s.capturedBmp = null;
    s.previewKey  = null;
    s.previewSeq++;
    syncButtons();
    s.liveTimer = setInterval(render, 80);
    return;
  }
  stopLive();
  s.capturedBmp = await createImageBitmap(video);
  s.captured    = true;
  s.previewKey  = null;
  syncButtons();
  render();
}

/* ── Load ────────────────────────────────────────── */
function loadBitmap(bmp) {
  stopLive();
  s.capturedBmp = bmp;
  s.captured    = true;
  s.previewKey  = null;
  s.previewSeq++;
  syncButtons();
  render();
}

loadBtn.addEventListener('click', () => loadInput.click());
loadInput.addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    const img = new Image();
    img.onload = async () => loadBitmap(await createImageBitmap(img));
    img.src = ev.target.result;
  };
  reader.readAsDataURL(file);
});

/* ── Re-edit from gallery ─────────────────────────── */
function loadDataUrl(dataUrl) {
  const img = new Image();
  img.onload = async () => loadBitmap(await createImageBitmap(img));
  img.src = dataUrl;
}

/* ── Save ────────────────────────────────────────── */
saveBtn.addEventListener('click', () => {
  const a    = document.createElement('a');
  a.download = `cakeawish-${Date.now()}.png`;
  a.href     = canvas.toDataURL('image/png');
  a.click();
});

/* ── Print ───────────────────────────────────────── */
async function print() {
  if (!s.capturedBmp) return;
  drawSrc(offCtx, s.capturedBmp);
  const dataUrl = off.toDataURL('image/png');

  printBtn.disabled = true;
  printBtn.classList.add('busy');
  status('Sending to printer…');

  try {
    const r    = await fetch('/print', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: dataUrl, template_id: s.frameId }),
    });
    const data = await r.json();
    if (!r.ok) {
      status('Print failed: ' + (data.detail || r.statusText), 'err');
    } else {
      status('Printed!', 'ok');
      // Prepend new thumbnail to gallery immediately from response
      if (data.thumbnail) prependGalleryItem({ thumbnail: data.thumbnail, raw: dataUrl });
      loadGallery(); // refresh full history in background
    }
  } catch (e) {
    status('Network error: ' + e.message, 'err');
  } finally {
    printBtn.classList.remove('busy');
    syncButtons();
  }
}

async function quickPrint() {
  if (!s.cameraOn) return;
  stopLive();
  s.capturedBmp = await createImageBitmap(video);
  s.captured    = true;
  s.previewKey  = null;
  s.previewSeq++;
  syncButtons();
  render();
  print();
}

/* ── Gallery ─────────────────────────────────────── */
function prependGalleryItem(item) {
  const el = makeGalleryEl(item);
  gallery.insertBefore(el, gallery.firstChild);
  // Keep max 8 visible
  while (gallery.children.length > 8) gallery.removeChild(gallery.lastChild);
}

function makeGalleryEl(item) {
  const el = document.createElement('div');
  el.className = 'g-item';
  el.innerHTML = `<img src="${item.thumbnail}" alt="print"><div class="g-hover">✏️</div>`;
  el.addEventListener('click', () => loadDataUrl(item.raw));
  return el;
}

async function loadGallery() {
  try {
    const r    = await fetch('/history');
    const data = await r.json();
    gallery.innerHTML = '';
    data.forEach(item => gallery.appendChild(makeGalleryEl(item)));
  } catch { /* ignore */ }
}

/* ── Templates ───────────────────────────────────── */
async function loadTemplates() {
  try {
    const r    = await fetch('/templates');
    const tpls = await r.json();

    [{ id: null, name: 'None' }, ...tpls].forEach(t => {
      const btn  = document.createElement('button');
      btn.className   = 'tpl-btn' + (t.id === s.frameId ? ' active' : '');
      btn.dataset.fid = t.id ?? '';

      const icon = document.createElement('div');
      icon.className   = 'tpl-icon';
      icon.textContent = t.id === null ? '⊘' : t.name[0];
      btn.appendChild(icon);

      const label = document.createElement('span');
      label.className   = 'tpl-name';
      label.textContent = t.name;
      btn.appendChild(label);

      btn.addEventListener('click', () => selectTemplate(t.id, btn));
      tplList.appendChild(btn);
    });
  } catch { /* /templates unavailable */ }
}

async function selectTemplate(frameId, btn) {
  s.frameId = frameId || null;
  tplList.querySelectorAll('.tpl-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  loadOverlay(s.frameId);               // update live overlay
  if (s.captured) { s.previewKey = null; render(); }  // re-request server preview
}

/* ── Printer polling ─────────────────────────────── */
async function pollPrinter() {
  try {
    const r    = await fetch('/printer');
    const data = await r.json();

    if (!data.connected) {
      setPill('Offline', 'offline');
      return;
    }
    if (data.errors && data.errors.length) {
      setPill(data.errors[0], 'error');
      return;
    }
    if (data.phase === 'Printing') {
      setPill('Printing…', 'printing');
    } else {
      setPill(data.label_id || 'Online', 'online');
    }

    // Update canvas dims if label changed
    if (data.label_id) setLabel(data.label_w, data.label_h);
  } catch {
    setPill('Offline', 'offline');
  }
}

/* ── Segmented controls ──────────────────────────── */
document.querySelectorAll('.segs').forEach(wrap => {
  wrap.addEventListener('click', e => {
    const btn = e.target.closest('.seg');
    if (!btn) return;
    wrap.querySelectorAll('.seg').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const key = wrap.dataset.state;
    const val = btn.dataset.val;
    if (key === 'fitMode') s.fitMode = val;
    if (key === 'mirror')  s.mirror  = val === 'on';
    if (s.captured) { s.previewKey = null; render(); }
  });
});

/* ── Event wiring ────────────────────────────────── */
captureBtn.addEventListener('click', capture);
quickBtn.addEventListener('click', quickPrint);
printBtn.addEventListener('click', print);

rotateBtn.addEventListener('click', () => {
  s.rotation = (s.rotation + 90) % 360;
  if (s.captured) { s.previewKey = null; render(); }
});

brtSlider.addEventListener('input', () => {
  s.brightness    = +brtSlider.value;
  brtOut.value    = s.brightness;
  if (s.captured) { s.previewKey = null; render(); }
});

ipInput.addEventListener('change', async () => {
  await fetch('/printer', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip: ipInput.value.trim() }),
  });
  pollPrinter();
});

/* ── Boot ────────────────────────────────────────── */
(async () => {
  setLabel(s.labelW, s.labelH);
  await Promise.all([loadTemplates(), loadGallery()]);
  await startCamera();
  pollPrinter();
  setInterval(pollPrinter, 2000);
  setInterval(loadGallery, 12000);
})();

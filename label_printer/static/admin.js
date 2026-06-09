// ── LabelRenderer ───────────────────────────────────────────────────────────
class LabelRenderer {
  #canvas; #ctx; #w = 0; #h = 0;

  constructor(canvas) {
    this.#canvas = canvas;
    this.#ctx    = canvas.getContext('2d', { willReadFrequently: true });
  }

  setSize(w, h) {
    this.#w = this.#canvas.width  = w;
    this.#h = this.#canvas.height = h;
  }

  get width()  { return this.#w; }
  get height() { return this.#h; }

  render(source, { fitMode = 'contain', mirror = false, rotate = 0, brightness = 0 } = {}) {
    if (!this.#w) return;
    const [w, h, ctx] = [this.#w, this.#h, this.#ctx];
    const sw = source.videoWidth  ?? source.naturalWidth  ?? source.width;
    const sh = source.videoHeight ?? source.naturalHeight ?? source.height;
    if (!sw || !sh) return;

    ctx.save();
    if (brightness !== 0) ctx.filter = `brightness(${1 + brightness / 100})`;
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, w, h);
    ctx.translate(w / 2, h / 2);
    if (rotate) ctx.rotate(rotate * Math.PI / 180);
    if (mirror) ctx.scale(-1, 1);
    const [fw, fh] = (rotate % 180 !== 0) ? [h, w] : [w, h];
    if (fitMode === 'stretch') {
      ctx.drawImage(source, -fw / 2, -fh / 2, fw, fh);
    } else {
      const scale = fitMode === 'cover' ? Math.max(fw/sw, fh/sh) : Math.min(fw/sw, fh/sh);
      const dw = sw * scale, dh = sh * scale;
      ctx.drawImage(source, -dw / 2, -dh / 2, dw, dh);
    }
    ctx.restore();
  }

  toDataURL() { return this.#canvas.toDataURL('image/png'); }

  async loadImage(dataUrl) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload  = () => { this.#ctx.drawImage(img, 0, 0, this.#w, this.#h); resolve(); };
      img.onerror = resolve;
      img.src = dataUrl;
    });
  }
}

// ── DOM refs ─────────────────────────────────────────────────────────────────
const video            = document.getElementById('video');
const canvas           = document.getElementById('preview');
const previewOverlay   = document.getElementById('previewOverlay');
const canvasWrap       = document.getElementById('canvasWrap');
const captureBtn       = document.getElementById('captureBtn');
const printBtn         = document.getElementById('printBtn');
const quickPrintBtn    = document.getElementById('quickPrintBtn');
const saveBtn          = document.getElementById('saveBtn');
const loadBtn          = document.getElementById('loadBtn');
const loadInput        = document.getElementById('loadInput');
const statusBar        = document.getElementById('statusBar');
const printerStatusEl  = document.getElementById('printerStatus');
const jobStatusEl      = document.getElementById('jobStatus');
const templatePicker   = document.getElementById('templatePicker');
const galleryEl        = document.getElementById('gallery');
const brightnessSlider = document.getElementById('brightnessSlider');
const brightnessVal    = document.getElementById('brightnessVal');

// ── Renderers ────────────────────────────────────────────────────────────────
const renderer    = new LabelRenderer(canvas);
const _offCanvas  = document.createElement('canvas');
const _offRenderer = new LabelRenderer(_offCanvas);

// ── State ────────────────────────────────────────────────────────────────────
const cfg = { fitMode: 'contain', mirror: 'on' };

let activeLabel      = null;
let labelHeight      = 0;   // 0 = continuous
let activeFrame      = null;
let templateOverlayImg = null;  // HTMLImageElement for live compositing

let captured            = false;
let capturedSrc         = null;
let capturedDataUrl     = null;
let _hasServerPreview   = false;  // true once server preview loaded for current capture
let _captureSeq         = 0;
let _previewCompositionKey = null;

let cameraReady      = false;
let liveTimer        = null;
let isPrinting       = false;
let rotation         = 0;
let brightness       = 0;
let previewToken     = 0;

let lastPrinterLabel = null;
let _knownLabels     = {};

// ── Helpers ──────────────────────────────────────────────────────────────────
function setStatus(msg, type = '') {
  statusBar.textContent = msg;
  statusBar.className   = 'status-bar' + (type ? ` ${type}` : '');
}

function setJobStatus(msg, type = '') {
  if (!msg) { jobStatusEl.hidden = true; return; }
  jobStatusEl.textContent = msg;
  jobStatusEl.className   = type;
  jobStatusEl.hidden      = false;
}

function printerIp() {
  return document.getElementById('printerIp').value.trim();
}

function updateButtons() {
  const canPrint = captured && activeLabel && activeLabel !== '__other__';
  printBtn.disabled      = !canPrint;
  saveBtn.disabled       = !captured;
  quickPrintBtn.disabled = captured || !cameraReady || !activeLabel || activeLabel === '__other__';
}

// ── Canvas sizing ────────────────────────────────────────────────────────────
function constrainCanvas() {
  const maxH = canvasWrap.offsetHeight;
  const maxW = canvasWrap.offsetWidth;
  if (maxH > 0) canvas.style.maxHeight = maxH + 'px';
  if (maxW > 0) canvas.style.maxWidth  = maxW + 'px';
}

function applyLabelSize(w, h) {
  labelHeight = h;
  const isCont = h === 0;
  const [cw, ch] = isCont ? [w, Math.round(w * 1.5)] : [w, h];
  renderer.setSize(cw, ch);
  _offRenderer.setSize(cw, ch);
  constrainCanvas();
  updatePreviewOverlay();
  loadTemplateOverlay();
  render();
}

// ── Template overlay (for live compositing) ──────────────────────────────────
async function loadTemplateOverlay() {
  if (!activeFrame || !renderer.width || !renderer.height) return;
  const url = `/frames/${encodeURIComponent(activeFrame)}/overlay.png?w=${renderer.width}&h=${renderer.height}`;
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    templateOverlayImg = img;
  } catch {
    templateOverlayImg = null;
  }
}

function drawOverlayOnCanvas() {
  if (!templateOverlayImg || !templateOverlayImg.complete) return;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(templateOverlayImg, 0, 0, canvas.width, canvas.height);
}

// ── Server preview ────────────────────────────────────────────────────────────
async function fetchServerPreview() {
  if (!capturedDataUrl || !activeLabel || activeLabel === '__other__') return;
  const token = ++previewToken;
  try {
    const res = await fetch('/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: capturedDataUrl, label: activeLabel, frame_id: activeFrame }),
    });
    if (token !== previewToken || !res.ok) return;
    const { image_data } = await res.json();
    if (token !== previewToken) return;
    await renderer.loadImage(image_data);
    _hasServerPreview = true;
  } catch { /* ignore */ }
}

// ── Render loop ───────────────────────────────────────────────────────────────
// Key insight: in captured mode, once a server preview is loaded, never overwrite
// it from source. Only the offscreen canvas gets redrawn (to produce new capturedDataUrl
// for the next server round-trip). This eliminates all flickering from brightness/
// template/setting changes.
function render() {
  const src = captured ? capturedSrc : (cameraReady ? video : null);
  if (!src || !activeLabel) return;

  if (!captured) {
    // Live mode: draw video + overlay every tick
    renderer.render(src, { fitMode: cfg.fitMode, mirror: cfg.mirror === 'on', rotate: rotation, brightness });
    drawOverlayOnCanvas();
  } else {
    // Captured mode: compute composition key; only act when something changed
    const key = `${_captureSeq}|${activeLabel}|${activeFrame}|${cfg.fitMode}|${cfg.mirror}|${rotation}|${brightness}`;
    if (key !== _previewCompositionKey) {
      _previewCompositionKey = key;
      // Draw source to main canvas only before first server preview arrives
      if (!_hasServerPreview) {
        renderer.render(src, { fitMode: cfg.fitMode, mirror: cfg.mirror === 'on', rotate: rotation, brightness });
      }
      // Always update offscreen canvas → new capturedDataUrl → server preview
      _offRenderer.render(src, { fitMode: cfg.fitMode, mirror: cfg.mirror === 'on', rotate: rotation, brightness });
      capturedDataUrl = _offRenderer.toDataURL();
      fetchServerPreview();
    }
  }
}

const startLive = () => { if (!liveTimer && cameraReady) liveTimer = setInterval(render, 100); };
const stopLive  = () => { clearInterval(liveTimer); liveTimer = null; };

// ── Segmented controls ────────────────────────────────────────────────────────
document.querySelectorAll('.seg-group[data-setting]').forEach(group => {
  group.addEventListener('click', e => {
    const btn = e.target.closest('.seg');
    if (!btn) return;
    group.querySelectorAll('.seg').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    cfg[group.dataset.setting] = btn.dataset.value;
    render();
  });
});

document.getElementById('rotateBtn').addEventListener('click', () => {
  rotation = (rotation + 90) % 360;
  render();
});

brightnessSlider.addEventListener('input', () => {
  brightness = Number(brightnessSlider.value);
  brightnessVal.textContent = brightness > 0 ? `+${brightness}` : String(brightness);
  render();
});

// ── Preview overlay (cut-line indicator) ──────────────────────────────────────
const SVG_NS = 'http://www.w3.org/2000/svg';

function updatePreviewOverlay() {
  const w = canvas.offsetWidth;
  const h = canvas.offsetHeight;
  if (!w || !h) return;
  previewOverlay.setAttribute('viewBox', `0 0 ${w} ${h}`);
  previewOverlay.innerHTML = '';
  if (labelHeight !== 0) return;  // only for continuous tape

  const z = 10;
  let d = `M 0 ${h}`;
  for (let x = 0; x < w; x += z)
    d += ` L ${Math.min(x + z/2, w)} ${h - z} L ${Math.min(x + z, w)} ${h}`;
  d += ` L ${w} ${h + z*2} L 0 ${h + z*2} Z`;

  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', 'rgba(124,111,247,0.2)');
  previewOverlay.appendChild(path);

  const ar = document.createElementNS(SVG_NS, 'text');
  ar.setAttribute('x', w / 2);
  ar.setAttribute('y', h - Math.round(Math.min(h * 0.04, 14)));
  ar.setAttribute('dominant-baseline', 'middle');
  ar.setAttribute('text-anchor', 'middle');
  ar.setAttribute('font-size', Math.round(Math.min(w * 0.15, 20)));
  ar.setAttribute('fill', 'rgba(124,111,247,0.4)');
  ar.textContent = '↓';
  previewOverlay.appendChild(ar);
}

new ResizeObserver(() => { constrainCanvas(); updatePreviewOverlay(); }).observe(canvasWrap);

// ── Labels ────────────────────────────────────────────────────────────────────
async function loadLabels() {
  try {
    const list = await fetch('/labels').then(r => r.json());
    _knownLabels = Object.fromEntries(list.map(l => [l.id, l]));
    if (list.length) selectLabel(list[0].id);
  } catch (err) {
    setStatus(`Labels failed: ${err.message}`, 'error');
  }
}

function selectLabel(id) {
  const lbl = _knownLabels[id];
  if (!lbl) return;
  activeLabel = id;
  applyLabelSize(lbl.width, lbl.height);
  updateButtons();
}

// ── Templates ─────────────────────────────────────────────────────────────────
async function loadTemplates() {
  try {
    const frames = await fetch('/frames').then(r => r.json());
    templatePicker.innerHTML = '';
    frames.forEach((f, i) => {
      const btn = document.createElement('button');
      btn.className  = 'tpl-btn' + (i === 0 ? ' active' : '');
      btn.dataset.id = f.id;
      // Placeholder thumb — just the template name initial for now
      btn.innerHTML = `<span class="tpl-thumb" style="background:var(--primary-ghost);display:flex;align-items:center;justify-content:center;font-size:1.2rem;color:var(--primary);">${f.name[0]}</span>
                       <span class="tpl-name">${f.name}</span>`;
      btn.addEventListener('click', () => selectTemplate(f.id));
      templatePicker.appendChild(btn);
    });
    if (frames.length) {
      activeFrame = frames[0].id;
      loadTemplateOverlay();
    }
  } catch (err) {
    setStatus(`Templates failed: ${err.message}`, 'error');
  }
}

function selectTemplate(id) {
  activeFrame = id;
  templatePicker.querySelectorAll('.tpl-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.id === id)
  );
  // Reload overlay for live compositing
  loadTemplateOverlay().then(() => {
    if (!captured) render();
  });
  // In captured mode: reset composition key to force new server preview
  // (don't touch main canvas — keep current server preview showing until new one arrives)
  if (captured) {
    _previewCompositionKey = '__stale__';
    render();
  }
}

// ── Gallery ───────────────────────────────────────────────────────────────────
async function refreshGallery() {
  try {
    const items = await fetch('/history').then(r => r.json());
    galleryEl.innerHTML = '';
    items.forEach(item => {
      const div = document.createElement('div');
      div.className = 'gallery-item';
      div.title = `${item.label}${item.frame_id ? ' · ' + item.frame_id : ''} — click to re-edit`;
      div.innerHTML = `<img src="${item.thumbnail}" alt="print" />
                       <div class="load-overlay">✏️</div>`;
      div.addEventListener('click', () => loadGalleryItem(item));
      galleryEl.appendChild(div);
    });
  } catch { /* gallery is non-critical */ }
}

function loadGalleryItem(item) {
  // Load raw (pre-frame) image back into preview mode for re-editing
  const img = new Image();
  img.onload = () => {
    capturedSrc        = document.createElement('canvas');
    capturedSrc.width  = img.naturalWidth;
    capturedSrc.height = img.naturalHeight;
    capturedSrc.getContext('2d').drawImage(img, 0, 0);
    stopLive();
    captured          = true;
    _hasServerPreview = false;
    rotation          = 0;
    brightnessSlider.value    = 0;
    brightness                = 0;
    brightnessVal.textContent = '0';
    _captureSeq++;
    _previewCompositionKey = null;
    captureBtn.textContent = 'Retake';
    captureBtn.classList.add('retake');
    updateButtons();
    render();
    setStatus('Loaded from gallery — adjust and print', 'ok');
    setTimeout(() => setStatus(''), 2500);
  };
  img.src = item.raw;
}

// ── Camera ────────────────────────────────────────────────────────────────────
async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = stream;
    video.addEventListener('loadedmetadata', () => {
      cameraReady = true;
      startLive();
      updateButtons();
    }, { once: true });
  } catch {
    captureBtn.disabled = true;
    setStatus('Camera unavailable.', 'error');
  }
}

// ── Capture / Retake ──────────────────────────────────────────────────────────
captureBtn.addEventListener('click', () => {
  if (captured) {
    // Retake
    captured              = false;
    capturedSrc           = null;
    capturedDataUrl       = null;
    _hasServerPreview     = false;
    _previewCompositionKey = null;
    rotation              = 0;
    brightnessSlider.value     = 0;
    brightness                 = 0;
    brightnessVal.textContent  = '0';
    ++previewToken;
    captureBtn.textContent = 'Capture';
    captureBtn.classList.remove('retake');
    updateButtons();
    startLive();
    setStatus('');
  } else {
    // Capture
    if (!cameraReady) return;
    stopLive();
    capturedSrc        = document.createElement('canvas');
    capturedSrc.width  = video.videoWidth;
    capturedSrc.height = video.videoHeight;
    capturedSrc.getContext('2d').drawImage(video, 0, 0);
    captured              = true;
    _hasServerPreview     = false;
    _previewCompositionKey = null;
    _captureSeq++;
    captureBtn.textContent = 'Retake';
    captureBtn.classList.add('retake');
    updateButtons();
    render();
  }
});

// ── Quick Print ───────────────────────────────────────────────────────────────
quickPrintBtn.addEventListener('click', async () => {
  if (captured || !cameraReady || isPrinting) return;
  _offRenderer.render(video, { fitMode: cfg.fitMode, mirror: cfg.mirror === 'on', rotate: rotation, brightness });
  const dataUrl = _offRenderer.toDataURL();
  isPrinting = true;
  quickPrintBtn.disabled = true;
  captureBtn.disabled    = true;
  const prev = quickPrintBtn.textContent;
  quickPrintBtn.textContent = '…';
  try {
    const res = await fetch('/print/auto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: dataUrl, frame_id: activeFrame }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Print failed');
    quickPrintBtn.textContent = '✓';
    setTimeout(() => { quickPrintBtn.textContent = prev; }, 2000);
    refreshGallery();
  } catch (err) {
    quickPrintBtn.textContent = prev;
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    isPrinting          = false;
    captureBtn.disabled = false;
    updateButtons();
  }
});

// ── Save ──────────────────────────────────────────────────────────────────────
saveBtn.addEventListener('click', () => {
  if (!captured) return;
  const a = document.createElement('a');
  a.href     = canvas.toDataURL('image/png');
  a.download = 'cake-a-wish.png';
  a.click();
});

// ── Load ──────────────────────────────────────────────────────────────────────
loadBtn.addEventListener('click', () => loadInput.click());
loadInput.addEventListener('change', () => {
  const file = loadInput.files[0];
  if (!file) return;
  loadInput.value = '';
  const reader = new FileReader();
  reader.onload = e => {
    const img = new Image();
    img.onload = () => {
      capturedSrc        = document.createElement('canvas');
      capturedSrc.width  = img.naturalWidth;
      capturedSrc.height = img.naturalHeight;
      capturedSrc.getContext('2d').drawImage(img, 0, 0);
      stopLive();
      captured              = true;
      _hasServerPreview     = false;
      _previewCompositionKey = null;
      _captureSeq++;
      captureBtn.textContent = 'Retake';
      captureBtn.classList.add('retake');
      updateButtons();
      render();
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
});

// ── Print ─────────────────────────────────────────────────────────────────────
printBtn.addEventListener('click', async () => {
  const ip = printerIp();
  if (!ip) { setStatus('Set Printer IP in Settings.', 'error'); return; }
  if (!activeLabel || activeLabel === '__other__') {
    setStatus('No recognized label — cannot print.', 'error'); return;
  }
  isPrinting = true;
  printBtn.disabled   = true;
  captureBtn.disabled = true;
  printBtn.classList.add('printing');
  const prev = printBtn.textContent;
  printBtn.textContent = 'Printing…';
  setStatus('');
  try {
    const res = await fetch('/print', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_data: capturedDataUrl,
        printer_ip: ip,
        label:      activeLabel,
        frame_id:   activeFrame,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || 'Print failed');
    printBtn.textContent = 'Printed ✓';
    setTimeout(() => { printBtn.textContent = prev; }, 3000);
    refreshGallery();
  } catch (err) {
    printBtn.textContent = prev;
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    printBtn.classList.remove('printing');
    isPrinting          = false;
    printBtn.disabled   = false;
    captureBtn.disabled = false;
  }
});

// ── Printer status — passive indicator, no click ──────────────────────────────
async function checkPrinterStatus(showSpinner = false) {
  const ip = printerIp();
  if (!ip) {
    printerStatusEl.className   = 'status-pill offline';
    printerStatusEl.textContent = 'No printer';
    return;
  }
  if (showSpinner) {
    printerStatusEl.className   = 'status-pill checking';
    printerStatusEl.textContent = 'Checking…';
  }
  try {
    const data = await fetch(`/printer/status?printer_ip=${encodeURIComponent(ip)}`).then(r => r.json());

    if (data.connected) {
      if (data.errors?.length) {
        printerStatusEl.className   = 'status-pill error';
        printerStatusEl.textContent = data.errors[0];
      } else if (data.phase_type === 'Printing state') {
        printerStatusEl.className   = 'status-pill printing';
        printerStatusEl.textContent = 'Printing…';
      } else {
        const labelTxt = data.label ? ` · ${data.label}` : '';
        printerStatusEl.className   = 'status-pill online';
        printerStatusEl.textContent = `Ready${labelTxt}`;
      }

      if (data.label && data.label !== lastPrinterLabel) {
        lastPrinterLabel = data.label;
        selectLabel(data.label);
      } else if (!data.label && data.media_type && !data.media_type.includes('No media')) {
        activeLabel = '__other__';
        updateButtons();
        setStatus(`Unrecognized roll (${data.media_width}mm) — cannot print`, 'error');
      }
    } else {
      printerStatusEl.className   = 'status-pill offline';
      printerStatusEl.textContent = 'Offline';
    }
  } catch {
    printerStatusEl.className   = 'status-pill offline';
    printerStatusEl.textContent = 'Offline';
  }
}

document.getElementById('printerIp').addEventListener('change', () => checkPrinterStatus(true));
setInterval(() => { if (!isPrinting) checkPrinterStatus(); }, 1000);

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  await loadLabels();
  await loadTemplates();
  await refreshGallery();
  startCamera();
  checkPrinterStatus(true);
})();

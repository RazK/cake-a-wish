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

  render(source, { fitMode = 'contain', mirror = false, rotate = 0, brightness = 0 } = {}) {
    if (!this.#w) return;
    this.#drawFit(source, fitMode, mirror, rotate, brightness);
  }

  toDataURL() { return this.#canvas.toDataURL('image/png'); }

  async loadImage(dataUrl) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => { this.#ctx.drawImage(img, 0, 0, this.#w, this.#h); resolve(); };
      img.onerror = resolve;
      img.src = dataUrl;
    });
  }

  #drawFit(src, mode, mirror, rotate, brightness) {
    const sw = src.videoWidth  ?? src.naturalWidth  ?? src.width;
    const sh = src.videoHeight ?? src.naturalHeight ?? src.height;
    if (!sw || !sh) return;
    const [w, h, ctx] = [this.#w, this.#h, this.#ctx];
    ctx.save();
    if (brightness !== 0) {
      const pct = brightness > 0
        ? `brightness(${1 + brightness / 100})`
        : `brightness(${1 + brightness / 100})`;
      ctx.filter = pct;
    }
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, w, h);
    ctx.translate(w / 2, h / 2);
    if (rotate) ctx.rotate(rotate * Math.PI / 180);
    if (mirror) ctx.scale(-1, 1);
    const [fw, fh] = (rotate % 180 !== 0) ? [h, w] : [w, h];
    if (mode === 'stretch') {
      ctx.drawImage(src, -fw / 2, -fh / 2, fw, fh);
    } else {
      const scale = mode === 'cover' ? Math.max(fw/sw, fh/sh) : Math.min(fw/sw, fh/sh);
      const dw = sw * scale, dh = sh * scale;
      ctx.drawImage(src, -dw / 2, -dh / 2, dw, dh);
    }
    ctx.restore();
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

// ── State ────────────────────────────────────────────────────────────────────
const renderer    = new LabelRenderer(canvas);
const _offCanvas  = document.createElement('canvas');
const _offRenderer = new LabelRenderer(_offCanvas);

const cfg = { fitMode: 'contain', mirror: 'on' };

let activeLabel      = null;   // label ID matched from printer
let labelWidth       = 0;
let labelHeight      = 0;

let activeFrame      = null;   // template/frame ID

let captured         = false;
let capturedSrc      = null;
let capturedDataUrl  = null;

let cameraReady      = false;
let liveTimer        = null;
let isPrinting       = false;
let rotation         = 0;
let brightness       = 0;

let previewToken           = 0;
let _captureSeq            = 0;
let _previewCompositionKey = null;

let lastPrinterLabel = null;

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
  const maxH = canvasWrap.offsetHeight - 24;
  const maxW = canvasWrap.offsetWidth  - 24;
  if (maxH > 0) canvas.style.maxHeight = maxH + 'px';
  if (maxW > 0) canvas.style.maxWidth  = maxW + 'px';
}

function applyLabelSize(w, h) {
  labelWidth  = w;
  labelHeight = h;
  const isCont = h === 0;
  const [cw, ch] = isCont ? [w, Math.round(w * 1.5)] : [w, h];
  renderer.setSize(cw, ch);
  _offRenderer.setSize(cw, ch);
  constrainCanvas();
  render();
  updatePreviewOverlay();
}

// ── Server preview ───────────────────────────────────────────────────────────
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
  } catch { /* ignore stale/failed preview */ }
}

// ── Render loop ──────────────────────────────────────────────────────────────
function render() {
  const src = captured ? capturedSrc : (cameraReady ? video : null);
  if (!src || !activeLabel) return;
  renderer.render(src, { fitMode: cfg.fitMode, mirror: cfg.mirror === 'on', rotate: rotation, brightness });
  if (captured) {
    const key = `${_captureSeq}|${activeLabel}|${activeFrame}|${cfg.fitMode}|${cfg.mirror}|${rotation}|${brightness}`;
    if (key !== _previewCompositionKey) {
      _offRenderer.render(src, { fitMode: cfg.fitMode, mirror: cfg.mirror === 'on', rotate: rotation, brightness });
      capturedDataUrl       = _offRenderer.toDataURL();
      _previewCompositionKey = key;
      fetchServerPreview();
    }
  }
}

const startLive = () => { if (!liveTimer && cameraReady) liveTimer = setInterval(render, 100); };
const stopLive  = () => { clearInterval(liveTimer); liveTimer = null; };

// ── Segmented controls ───────────────────────────────────────────────────────
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

// ── Preview overlay (cut-line + feed arrow) ──────────────────────────────────
const SVG_NS = 'http://www.w3.org/2000/svg';

function updatePreviewOverlay() {
  const w = canvas.offsetWidth;
  const h = canvas.offsetHeight;
  if (!w || !h) return;
  previewOverlay.setAttribute('viewBox', `0 0 ${w} ${h}`);
  previewOverlay.innerHTML = '';
  if (!activeLabel || labelHeight !== 0) return; // only for continuous

  const z = 10;
  let d = `M 0 ${h}`;
  for (let x = 0; x < w; x += z)
    d += ` L ${Math.min(x + z/2, w)} ${h - z} L ${Math.min(x + z, w)} ${h}`;
  d += ` L ${w} ${h + z*2} L 0 ${h + z*2} Z`;
  const path = document.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', 'rgba(124,111,247,0.25)');
  previewOverlay.appendChild(path);

  const ar = document.createElementNS(SVG_NS, 'text');
  ar.setAttribute('x', w / 2);
  ar.setAttribute('y', h - Math.round(Math.min(h * 0.04, 14)));
  ar.setAttribute('dominant-baseline', 'middle');
  ar.setAttribute('text-anchor', 'middle');
  ar.setAttribute('font-size', Math.round(Math.min(w * 0.15, 20)));
  ar.setAttribute('fill', 'rgba(124,111,247,0.45)');
  ar.textContent = '↓';
  previewOverlay.appendChild(ar);
}

new ResizeObserver(() => { constrainCanvas(); updatePreviewOverlay(); }).observe(canvasWrap);

// ── Labels (auto-detected from printer) ──────────────────────────────────────
async function loadLabels() {
  try {
    const list  = await fetch('/labels').then(r => r.json());
    const known = Object.fromEntries(list.map(l => [l.id, l]));
    // Default to first label so canvas has a size before printer connects
    const first = list[0];
    if (first) selectLabel(first.id, known);
    return known;
  } catch (err) {
    setStatus(`Labels failed: ${err.message}`, 'error');
    return {};
  }
}

let _knownLabels = {};

function selectLabel(id, known = _knownLabels) {
  const lbl = known[id];
  if (!lbl) return;
  activeLabel = id;
  _knownLabels = known;
  applyLabelSize(lbl.width, lbl.height);
  updateButtons();
}

// ── Templates ────────────────────────────────────────────────────────────────
async function loadTemplates() {
  try {
    const frames = await fetch('/frames').then(r => r.json());
    templatePicker.innerHTML = '';
    frames.forEach((f, i) => {
      const btn = document.createElement('button');
      btn.className    = 'tpl-btn' + (i === 0 ? ' active' : '');
      btn.dataset.id   = f.id;
      btn.innerHTML    = `<span class="tpl-thumb" style="display:flex;align-items:center;justify-content:center;font-size:1.4rem">🖼</span>
                          <span class="tpl-name">${f.name}</span>`;
      btn.addEventListener('click', () => selectTemplate(f.id));
      templatePicker.appendChild(btn);
    });
    if (frames.length) selectTemplate(frames[0].id, false);
  } catch (err) {
    setStatus(`Templates failed: ${err.message}`, 'error');
  }
}

function selectTemplate(id, triggerRender = true) {
  activeFrame = id;
  templatePicker.querySelectorAll('.tpl-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.id === id)
  );
  if (triggerRender) {
    _previewCompositionKey = null; // force re-fetch of server preview
    render();
  }
}

// ── Gallery ──────────────────────────────────────────────────────────────────
async function refreshGallery() {
  try {
    const items = await fetch('/history').then(r => r.json());
    galleryEl.innerHTML = '';
    items.forEach(item => {
      const div = document.createElement('div');
      div.className = 'gallery-item';
      div.title = `${item.label}${item.frame_id ? ' · ' + item.frame_id : ''}`;
      div.innerHTML = `<img src="${item.thumbnail}" alt="print" />
                       <div class="reprint-overlay">🖨</div>`;
      div.addEventListener('click', () => reprintItem(item));
      galleryEl.appendChild(div);
    });
  } catch { /* gallery is non-critical */ }
}

async function reprintItem(item) {
  if (isPrinting) return;
  const ip = printerIp();
  if (!ip) { setStatus('Set Printer IP in Settings.', 'error'); return; }
  isPrinting = true;
  try {
    const res = await fetch('/print/auto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: item.thumbnail, frame_id: item.frame_id }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || 'Reprint failed');
    }
    setStatus('Reprinted!', 'ok');
    setTimeout(() => setStatus(''), 2500);
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    isPrinting = false;
  }
}

// ── Camera ───────────────────────────────────────────────────────────────────
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

// ── Capture / Retake ─────────────────────────────────────────────────────────
captureBtn.addEventListener('click', () => {
  if (captured) {
    captured        = false;
    capturedSrc     = null;
    capturedDataUrl = null;
    rotation        = 0;
    brightnessSlider.value = 0;
    brightness = 0;
    brightnessVal.textContent = '0';
    ++previewToken;
    captureBtn.textContent = 'Capture';
    captureBtn.classList.remove('retake');
    updateButtons();
    startLive();
    setStatus('');
  } else {
    if (!cameraReady) return;
    stopLive();
    capturedSrc        = document.createElement('canvas');
    capturedSrc.width  = video.videoWidth;
    capturedSrc.height = video.videoHeight;
    capturedSrc.getContext('2d').drawImage(video, 0, 0);
    captureBtn.textContent = 'Retake';
    captureBtn.classList.add('retake');
    captured = true;
    _captureSeq++;
    updateButtons();
    render();
  }
});

// ── Quick Print ──────────────────────────────────────────────────────────────
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

// ── Save ─────────────────────────────────────────────────────────────────────
saveBtn.addEventListener('click', () => {
  if (!captured) return;
  const a = document.createElement('a');
  a.href     = canvas.toDataURL('image/png');
  a.download = 'cake-a-wish.png';
  a.click();
});

// ── Load ─────────────────────────────────────────────────────────────────────
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
      captured = true;
      rotation = 0;
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

// ── Print ────────────────────────────────────────────────────────────────────
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

// ── Printer status polling ───────────────────────────────────────────────────
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
printerStatusEl.addEventListener('click', () => checkPrinterStatus(true));
setInterval(() => { if (!isPrinting) checkPrinterStatus(); }, 1000);

// ── Init ─────────────────────────────────────────────────────────────────────
(async () => {
  _knownLabels = await loadLabels();
  await loadTemplates();
  await refreshGallery();
  startCamera();
  checkPrinterStatus(true);
})();

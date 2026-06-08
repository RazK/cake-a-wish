// ── LabelRenderer ─────────────────────────────────────────
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

  render(source, { fitMode = 'contain', bwMode = 'dither', mirror = false, rotate = 0 } = {}) {
    if (!this.#w) return;
    this.#drawFit(source, fitMode, mirror, rotate);
    if (bwMode !== 'none') this.#applyBW(bwMode);
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

  #drawFit(src, mode, mirror, rotate) {
    const sw = src.videoWidth  ?? src.naturalWidth  ?? src.width;
    const sh = src.videoHeight ?? src.naturalHeight ?? src.height;
    if (!sw || !sh) return;
    const [w, h, ctx] = [this.#w, this.#h, this.#ctx];
    ctx.save();
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, w, h);
    ctx.translate(w / 2, h / 2);
    if (rotate) ctx.rotate(rotate * Math.PI / 180);
    if (mirror) ctx.scale(-1, 1);
    // At 90°/270° the source axes are transposed relative to the canvas
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

  #applyBW(mode) {
    const id = this.#ctx.getImageData(0, 0, this.#w, this.#h);
    const d  = id.data;
    for (let i = 0; i < d.length; i += 4)
      d[i] = d[i+1] = d[i+2] = d[i]*0.299 + d[i+1]*0.587 + d[i+2]*0.114;
    // 'grayscale' stops here — no further binarisation
    if      (mode === 'threshold') this.#threshold(d);
    else if (mode === 'dither')    this.#floydSteinberg(d);
    else if (mode === 'atkinson')  this.#atkinson(d);
    this.#ctx.putImageData(id, 0, 0);
  }

  #threshold(d) {
    for (let i = 0; i < d.length; i += 4)
      d[i] = d[i+1] = d[i+2] = d[i] < 128 ? 0 : 255;
  }

  #floydSteinberg(d) {
    const [w, h] = [this.#w, this.#h];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y*w+x)*4, old = d[i], nv = old < 128 ? 0 : 255, e = old - nv;
      d[i] = d[i+1] = d[i+2] = nv;
      if (x+1 < w)   this.#e(d, (y*w+x+1)*4,       e * 7/16);
      if (y+1 < h) {
        if (x > 0)   this.#e(d, ((y+1)*w+x-1)*4,   e * 3/16);
                     this.#e(d, ((y+1)*w+x)*4,      e * 5/16);
        if (x+1 < w) this.#e(d, ((y+1)*w+x+1)*4,   e / 16);
      }
    }
  }

  #atkinson(d) {
    const [w, h] = [this.#w, this.#h];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = (y*w+x)*4, old = d[i], nv = old < 128 ? 0 : 255, e = (old-nv) / 8;
      d[i] = d[i+1] = d[i+2] = nv;
      for (const [dy, dx] of [[0,1],[0,2],[1,-1],[1,0],[1,1],[2,0]]) {
        const ny = y+dy, nx = x+dx;
        if (ny < h && nx >= 0 && nx < w) this.#e(d, (ny*w+nx)*4, e);
      }
    }
  }

  #e(d, i, e) { d[i] = d[i+1] = d[i+2] = Math.max(0, Math.min(255, d[i]+e)); }
}

// ── Labels ─────────────────────────────────────────────────
const LABEL_IDS = ['29x90', '62red'];

// ── DOM refs ───────────────────────────────────────────────
const video           = document.getElementById('video');
const canvas          = document.getElementById('preview');
const previewOverlay  = document.getElementById('previewOverlay');
const canvasWrap      = document.getElementById('canvasWrap');
const captureBtn      = document.getElementById('captureBtn');
const printBtn        = document.getElementById('printBtn');
const quickPrintBtn   = document.getElementById('quickPrintBtn');
const saveBtn         = document.getElementById('saveBtn');
const loadBtn         = document.getElementById('loadBtn');
const loadInput       = document.getElementById('loadInput');
const statusEl        = document.getElementById('status');
const printerStatusEl = document.getElementById('printerStatus');

// ── State ──────────────────────────────────────────────────
const renderer  = new LabelRenderer(canvas);
// Offscreen renderer used to capture the color composition sent to the server.
// Separate from the main canvas so we can show a grayscale live preview
// while still sending a color image so the server can do two-color separation.
const _offCanvas   = document.createElement('canvas');
const _offRenderer = new LabelRenderer(_offCanvas);
const cfg       = { fitMode: 'contain', mirror: 'on' };
let labels           = {};
let activeLabel      = null;
let captured         = false;
let capturedSrc      = null;
let cameraReady      = false;
let liveTimer        = null;
let detectedLabel    = null;  // label locked by printer media detection
let lastPrinterLabel = null;  // last data.label seen from status poll
let printingDotsTimer = null;
let capturedDataUrl        = null;  // raw composition (no BW) sent to /preview and /print
let previewToken           = 0;     // incremented on each fetch to discard stale responses
let rotation               = 0;     // current rotation in degrees (0/90/180/270)
let isPrinting             = false;
let _captureSeq            = 0;     // bumped on each new capture to bust preview cache
let _previewCompositionKey = null;  // key of the last composition sent to /preview

const jobStatusEl = document.getElementById('jobStatus');

// ── Helpers ────────────────────────────────────────────────
const setStatus = (msg, type = '') => {
  if (!msg) { jobStatusEl.hidden = true; return; }
  jobStatusEl.textContent = msg;
  jobStatusEl.className   = type;
  jobStatusEl.hidden      = false;
};

const printerCfg = () => ({
  ip:       document.getElementById('printerIp').value.trim(),
  password: document.getElementById('password').value,
});

// ── Server preview ─────────────────────────────────────────
async function fetchServerPreview() {
  if (!capturedDataUrl || !activeLabel || activeLabel === '__other__') return;
  const token = ++previewToken;
  try {
    const res = await fetch('/preview', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ image_data: capturedDataUrl, label: activeLabel }),
    });
    if (token !== previewToken || !res.ok) return;
    const { image_data } = await res.json();
    if (token !== previewToken) return;
    await renderer.loadImage(image_data);
  } catch { /* ignore preview errors */ }
}

// ── Render ─────────────────────────────────────────────────
function render() {
  const src = captured ? capturedSrc : (cameraReady ? video : null);
  if (!src || !activeLabel) return;
  renderer.render(src, { fitMode: cfg.fitMode, bwMode: 'none', mirror: cfg.mirror === 'on', rotate: rotation });
  if (captured) {
    // Only recompose (and re-fetch preview) when something that affects the output changes.
    // Redundant render() calls (e.g. resize events) skip the expensive toDataURL() + round-trip.
    const key = `${_captureSeq}|${activeLabel}|${cfg.fitMode}|${cfg.mirror}|${rotation}`;
    if (key !== _previewCompositionKey) {
      _offRenderer.render(src, { fitMode: cfg.fitMode, bwMode: 'none', mirror: cfg.mirror === 'on', rotate: rotation });
      capturedDataUrl = _offRenderer.toDataURL();
      _previewCompositionKey = key;
      fetchServerPreview();
    }
  }
}

const startLive = () => { if (!liveTimer && cameraReady) liveTimer = setInterval(render, 100); };
const stopLive  = () => { clearInterval(liveTimer); liveTimer = null; };

// ── Segmented controls ─────────────────────────────────────
document.querySelectorAll('.btn-group[data-setting]').forEach(group => {
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

// ── Carousel ───────────────────────────────────────────────
async function loadLabels() {
  try {
    const list = await fetch('/labels').then(r => r.json());
    const filtered = list.filter(l => LABEL_IDS.includes(l.id));
    labels = Object.fromEntries(filtered.map(l => [l.id, l]));
    buildCarousel(filtered);
    selectLabel(filtered[0]?.id);
  } catch (err) {
    setStatus(`Labels failed: ${err.message}`, 'error');
  }
}

const LABEL_DISPLAY = {
  '29x90': { text: '29x90 BLACK', red: false },
  '62red':  { text: 'BLACK & RED',  red: true  },
};

function labelInkHTML(id) {
  const info = LABEL_DISPLAY[id] ?? { text: id, red: id.includes('red') };
  if (!info.red) return info.text;
  return [...info.text].map((ch, i) =>
    i % 2 === 0 ? ch : `<span class="ink-red">${ch}</span>`
  ).join('');
}

const SVG_NS = 'http://www.w3.org/2000/svg';

function makeShapeSVG(w, h, isContinuous, labelId) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'label-shape');
  svg.setAttribute('width', w);
  svg.setAttribute('height', h);
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);

  if (isContinuous) {
    // Zig-zag on RIGHT edge = cut side
    const z = Math.max(4, Math.round(h / 12));
    let d = `M 0 0 L ${w} 0`;
    for (let y = 0; y < h; y += z) {
      d += ` L ${w - z} ${Math.min(y + z / 2, h)} L ${w} ${Math.min(y + z, h)}`;
    }
    d += ` L 0 ${h} Z`;
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('class', 'shape-path');
    path.setAttribute('d', d);
    svg.appendChild(path);
  } else {
    const rect = document.createElementNS(SVG_NS, 'rect');
    rect.setAttribute('class', 'shape-path');
    rect.setAttribute('x', '1'); rect.setAttribute('y', '1');
    rect.setAttribute('width', w - 2); rect.setAttribute('height', h - 2);
    rect.setAttribute('rx', '2');
    svg.appendChild(rect);
  }

  // Arrow on LEFT (print direction), zig-zag on RIGHT (cut side)
  if (isContinuous) {
    const ar = document.createElementNS(SVG_NS, 'text');
    ar.setAttribute('class', 'shape-arrow');
    ar.setAttribute('x', String(w * 0.15));
    ar.setAttribute('y', String(h / 2));
    ar.setAttribute('dominant-baseline', 'middle');
    ar.setAttribute('text-anchor', 'middle');
    ar.textContent = '←';
    svg.appendChild(ar);
  }

  // Label name inside shape; for continuous shift right to leave room for arrow on left
  const info = LABEL_DISPLAY[labelId];
  if (info) {
    const cx = w * 0.5;
    const cy = h / 2;

    if (info.red) {
      const text = document.createElementNS(SVG_NS, 'text');
      text.setAttribute('x', String(cx));
      text.setAttribute('y', String(cy));
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('dominant-baseline', 'middle');
      text.setAttribute('class', 'shape-label');

      const b = document.createElementNS(SVG_NS, 'tspan');
      b.setAttribute('class', 'shape-text-black'); b.textContent = 'BLACK';
      const a = document.createElementNS(SVG_NS, 'tspan');
      a.setAttribute('class', 'shape-text-amp'); a.textContent = ' & ';
      const r = document.createElementNS(SVG_NS, 'tspan');
      r.setAttribute('class', 'shape-text-red'); r.textContent = 'RED';

      text.append(b, a, r);
      svg.appendChild(text);
    } else {
      const text = document.createElementNS(SVG_NS, 'text');
      text.setAttribute('x', String(cx));
      text.setAttribute('y', String(cy));
      text.setAttribute('text-anchor', 'middle');
      text.setAttribute('dominant-baseline', 'middle');
      text.setAttribute('class', 'shape-label shape-text-black');
      text.textContent = info.text;
      svg.appendChild(text);
    }
  }

  return svg;
}

function buildCarousel(list) {
  const el = document.getElementById('carousel');
  el.innerHTML = '';
  const BASE_W = 120;
  const maxDim = Math.max(...list.map(l => Math.max(l.width, l.height || 0)));
  const scale  = BASE_W / maxDim;

  for (const { id, width, height } of list) {
    const isContinuous = height === 0;
    const short  = isContinuous ? width : Math.min(width, height);
    const shapeW = BASE_W;
    const shapeH = Math.max(20, Math.round(short * scale));

    const card = document.createElement('button');
    card.className  = 'label-card';
    card.dataset.id = id;
    card.title      = `${id} — ${width}×${height || '∞'} dots`;

    card.append(makeShapeSVG(shapeW, shapeH, isContinuous, id));
    card.addEventListener('click', () => selectLabel(id));
    el.appendChild(card);
  }
}

function constrainCanvas() {
  const maxH = canvasWrap.offsetHeight;
  const maxW = canvasWrap.offsetWidth;
  if (maxH > 0) canvas.style.maxHeight = maxH + 'px';
  if (maxW > 0) canvas.style.maxWidth  = maxW + 'px';
}

function updateButtons() {
  printBtn.disabled      = !captured || activeLabel === '__other__';
  saveBtn.disabled       = !captured;
  quickPrintBtn.disabled = captured || !cameraReady || !activeLabel || activeLabel === '__other__';
}

function lockCarouselTo(labelId) {
  detectedLabel = labelId;
  document.querySelectorAll('#carousel .label-card').forEach(card => {
    card.classList.toggle('locked-out', card.dataset.id !== labelId);
  });
}

function unlockCarousel() {
  detectedLabel = null;
  document.querySelectorAll('#carousel .label-card').forEach(card =>
    card.classList.remove('locked-out')
  );
}

function makeOtherShapeSVG(desc) {
  const w = 120, h = 34;
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'label-shape');
  svg.setAttribute('width', w);
  svg.setAttribute('height', h);
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  const rect = document.createElementNS(SVG_NS, 'rect');
  rect.setAttribute('class', 'shape-path');
  rect.setAttribute('x', '1'); rect.setAttribute('y', '1');
  rect.setAttribute('width', w - 2); rect.setAttribute('height', h - 2);
  rect.setAttribute('rx', '4');
  svg.appendChild(rect);
  const text = document.createElementNS(SVG_NS, 'text');
  text.setAttribute('x', String(w / 2));
  text.setAttribute('y', String(h / 2));
  text.setAttribute('text-anchor', 'middle');
  text.setAttribute('dominant-baseline', 'middle');
  text.setAttribute('class', 'shape-label shape-text-warn');
  text.textContent = `⚠ ${desc}`;
  svg.appendChild(text);
  return svg;
}

function injectOtherCard(desc) {
  let card = document.querySelector('.label-card[data-id="__other__"]');
  if (card) {
    card.title = `Unrecognized roll: ${desc}`;
    card.querySelector('.shape-label').textContent = `⚠ ${desc}`;
    return;
  }
  card = document.createElement('button');
  card.className  = 'label-card other-roll';
  card.dataset.id = '__other__';
  card.title      = `Unrecognized roll: ${desc}`;
  card.appendChild(makeOtherShapeSVG(desc));
  card.addEventListener('click', () => selectOther());
  document.getElementById('carousel').prepend(card);
}

function removeOtherCard() {
  const card = document.querySelector('.label-card[data-id="__other__"]');
  if (card) card.remove();
  if (activeLabel === '__other__') {
    const first = document.querySelector('#carousel .label-card:not([data-id="__other__"])');
    if (first) selectLabel(first.dataset.id);
  }
}

function selectOther() {
  activeLabel = '__other__';
  document.querySelectorAll('.label-card').forEach(c =>
    c.classList.toggle('active', c.dataset.id === '__other__')
  );
  updateButtons();
  setStatus('Unrecognized roll — cannot print', 'error');
}

function selectLabel(id) {
  if (!labels[id]) return;
  activeLabel = id;
  updateButtons();
  document.querySelectorAll('.label-card').forEach(c =>
    c.classList.toggle('active', c.dataset.id === id)
  );
  const { width: w, height: h } = labels[id];
  const isCont = h === 0;
  // Canvas matches the label's exact dots_printable dimensions so no server-side rotation is needed.
  // Continuous labels get a synthetic feed length of 1.5× the tape width.
  const [cw, ch] = isCont ? [w, Math.round(w * 1.5)] : [w, h];
  renderer.setSize(cw, ch);
  _offRenderer.setSize(cw, ch);
  constrainCanvas();
  render();
  updatePreviewOverlay();
}

// ── Preview overlay ────────────────────────────────────────
function updatePreviewOverlay() {
  const w = canvas.offsetWidth;
  const h = canvas.offsetHeight;
  if (!w || !h) return;
  previewOverlay.setAttribute('viewBox', `0 0 ${w} ${h}`);
  previewOverlay.innerHTML = '';
  if (!activeLabel || !labels[activeLabel]) return;

  const isContinuous = labels[activeLabel].height === 0;
  const z = 10; // fixed tooth size in display px — stays readable at any canvas size

  if (isContinuous) {
    // Zig-zag mask at BOTTOM (cut side) for portrait continuous label
    let d = `M 0 ${h}`;
    for (let x = 0; x < w; x += z) {
      d += ` L ${Math.min(x + z / 2, w)} ${h - z} L ${Math.min(x + z, w)} ${h}`;
    }
    d += ` L ${w} ${h + z * 2} L 0 ${h + z * 2} Z`;
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', '#111');
    previewOverlay.appendChild(path);
  }

  // Feed-direction arrow — subtle watermark near top, pointing down (feed direction)
  const ar = document.createElementNS(SVG_NS, 'text');
  ar.setAttribute('x', w / 2);
  ar.setAttribute('y', h - Math.round(Math.min(h * 0.04, 14)));
  ar.setAttribute('dominant-baseline', 'middle');
  ar.setAttribute('text-anchor', 'middle');
  ar.setAttribute('font-size', Math.round(Math.min(w * 0.15, 20)));
  ar.setAttribute('fill', 'rgba(255,255,255,0.3)');
  ar.textContent = '↓';
  previewOverlay.appendChild(ar);
}

new ResizeObserver(() => { constrainCanvas(); updatePreviewOverlay(); }).observe(canvasWrap);

// ── Camera ─────────────────────────────────────────────────
async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = stream;
    video.addEventListener('loadedmetadata', () => {
      cameraReady = true;
      startLive();
      updateButtons();
      setStatus('');
    }, { once: true });
  } catch {
    captureBtn.disabled = true;
    setStatus('No camera.', 'error');
  }
}

// ── Capture / Retake ───────────────────────────────────────
captureBtn.addEventListener('click', () => {
  if (captured) {
    // Retake
    captured        = false;
    capturedSrc     = null;
    capturedDataUrl = null;
    rotation        = 0;
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
    captureBtn.textContent = 'Retake';
    captureBtn.classList.add('retake');
    captured = true;
    _captureSeq++;
    updateButtons();
    render();
    setStatus('');
  }
});

// ── Quick Print ────────────────────────────────────────────
quickPrintBtn.addEventListener('click', async () => {
  if (captured || !cameraReady) return;
  _offRenderer.render(video, { fitMode: cfg.fitMode, bwMode: 'none', mirror: cfg.mirror === 'on', rotate: rotation });
  const dataUrl = _offRenderer.toDataURL();
  isPrinting = true;
  quickPrintBtn.disabled = true;
  captureBtn.disabled    = true;
  const prev = quickPrintBtn.textContent;
  quickPrintBtn.textContent = '…';
  try {
    const res  = await fetch('/print/auto', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_data: dataUrl }),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { throw new Error(`Server error ${res.status}`); }
    if (!res.ok) throw new Error(data.detail || 'Print failed');
    quickPrintBtn.textContent = '✓';
    setTimeout(() => { quickPrintBtn.textContent = prev; }, 2000);
  } catch (err) {
    quickPrintBtn.textContent = prev;
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    isPrinting          = false;
    captureBtn.disabled = false;
    updateButtons();
  }
});

// ── Save ───────────────────────────────────────────────────
saveBtn.addEventListener('click', () => {
  if (!captured) return;
  const a = document.createElement('a');
  a.href     = canvas.toDataURL('image/png');
  a.download = 'cake-a-wish.png';
  a.click();
});

// ── Load ───────────────────────────────────────────────────
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
      setStatus('');
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
});

// ── Print ──────────────────────────────────────────────────
printBtn.addEventListener('click', async () => {
  const { ip, password } = printerCfg();
  if (!ip) { setStatus('Set Printer IP.', 'error'); return; }
  if (!activeLabel || activeLabel === '__other__') {
    setStatus('Unrecognized roll — cannot print.', 'error'); return;
  }
  isPrinting          = true;
  printBtn.disabled   = true;
  captureBtn.disabled = true;
  printBtn.classList.add('printing');
  let dots = 0;
  printBtn.textContent = 'Printing';
  printingDotsTimer = setInterval(() => {
    dots = (dots % 3) + 1;
    printBtn.textContent = 'Printing' + '·'.repeat(dots);
  }, 350);
  setStatus('');
  try {
    const res = await fetch('/print', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_data: capturedDataUrl,
        printer_ip: ip,
        label:      activeLabel,
        password:   password || null,
      }),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { throw new Error(`Server error ${res.status}`); }
    if (!res.ok) throw new Error(data.detail || 'Print failed');
    printBtn.textContent = 'Printed!';
    setTimeout(() => { printBtn.textContent = 'Print'; }, 3000);
  } catch (err) {
    printBtn.textContent = 'Print';
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    clearInterval(printingDotsTimer);
    printingDotsTimer   = null;
    printBtn.classList.remove('printing');
    isPrinting          = false;
    printBtn.disabled   = false;
    captureBtn.disabled = false;
  }
});

// ── Printer status ─────────────────────────────────────────
async function checkPrinterStatus(showSpinner = false) {
  const { ip, password } = printerCfg();
  if (!ip) {
    printerStatusEl.className   = 'printer-status offline';
    printerStatusEl.textContent = 'No printer';
    return;
  }
  if (showSpinner) printerStatusEl.className = 'printer-status checking';
  try {
    const params = new URLSearchParams({ printer_ip: ip });
    if (password) params.set('password', password);
    const data = await fetch(`/printer/status?${params}`).then(r => r.json());

    if (data.connected) {
      // Status pill
      if (data.errors?.length) {
        printerStatusEl.className   = 'printer-status error';
        printerStatusEl.textContent = data.errors[0];
      } else if (data.phase_type === 'Printing state') {
        printerStatusEl.className   = 'printer-status printing';
        printerStatusEl.textContent = 'Printing';
      } else {
        printerStatusEl.className   = 'printer-status online';
        printerStatusEl.textContent = 'Ready';
      }

      // Media / label handling
      const hasMedia    = data.media_type && !data.media_type.includes('No media');
      const explicitNone = data.media_type?.includes('No media');
      if (hasMedia && data.label) {
        removeOtherCard();
        if (data.label !== lastPrinterLabel) {
          lastPrinterLabel = data.label;
          selectLabel(data.label);
        }
        lockCarouselTo(data.label);
      } else if (hasMedia && !data.label) {
        const rawDesc = data.media_length > 0
          ? `${data.media_width}×${data.media_length}mm`
          : `${data.media_width}mm`;
        injectOtherCard(rawDesc);
        if (lastPrinterLabel !== '__other__') {
          lastPrinterLabel = '__other__';
          selectOther();
        }
        lockCarouselTo('__other__');
      } else if (explicitNone) {
        // Printer confirmed no tape — unlock so user knows something is wrong
        removeOtherCard();
        if (lastPrinterLabel !== null) { lastPrinterLabel = null; unlockCarousel(); }
      }
      // If media_type is null/undefined (printer connected but no ESC i S response),
      // leave the carousel in its current state — do not unlock.
    } else {
      printerStatusEl.className   = 'printer-status offline';
      printerStatusEl.textContent = 'Offline';
      removeOtherCard();
      if (lastPrinterLabel !== null) { lastPrinterLabel = null; unlockCarousel(); }
    }
  } catch {
    printerStatusEl.className   = 'printer-status offline';
    printerStatusEl.textContent = 'Offline';
  }
}

document.getElementById('printerIp').addEventListener('change', () => checkPrinterStatus(true));
printerStatusEl.addEventListener('click', event => {
  event.stopPropagation();
  checkPrinterStatus(true);
});
setInterval(() => { if (!isPrinting) checkPrinterStatus(); }, 1000);

// ── Init ───────────────────────────────────────────────────
loadLabels();
startCamera();
checkPrinterStatus(true);

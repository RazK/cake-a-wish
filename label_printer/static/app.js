const video        = document.getElementById('video');
const snapshot     = document.getElementById('snapshot');
const labelPreview = document.getElementById('labelPreview');
const previewWrap  = document.getElementById('previewWrap');
const labelBadge   = document.getElementById('labelBadge');
const captureBtn   = document.getElementById('capture');
const retakeBtn    = document.getElementById('retake');
const printBtn     = document.getElementById('print');
const statusEl     = document.getElementById('status');

const canvas       = document.createElement('canvas');
const imageUpload  = document.getElementById('imageUpload');
const uploadBtn    = document.getElementById('uploadBtn');
const uploadName   = document.getElementById('uploadName');
const state        = { bwMode: 'dither', fitMode: 'contain', mirror: 'on' };
let captured       = false;
let cameraReady    = false;
let liveTimer      = null;
let previewBusy    = false;
let previewDirty   = false;
let uploadedFile   = null;

// ── segmented controls ───────────────────────────────────
document.querySelectorAll('.btn-group').forEach(group => {
  group.addEventListener('click', e => {
    const btn = e.target.closest('.seg');
    if (!btn) return;
    group.querySelectorAll('.seg').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state[group.dataset.setting] = btn.dataset.value;
    if (group.dataset.setting === 'mirror') {
      video.classList.toggle('mirrored', state.mirror === 'on');
    }
    refreshPreview();
  });
});

// ── status ───────────────────────────────────────────────
function setStatus(msg, type = '') {
  statusEl.textContent = msg;
  statusEl.className = type;
}

// ── printer settings ─────────────────────────────────────
function printerSettings() {
  return {
    ip:       document.getElementById('printerIp').value.trim(),
    label:    document.getElementById('labelId').value.trim(),
    password: document.getElementById('password').value,
    rotate:   document.getElementById('rotate').checked,
  };
}

// ── image source ─────────────────────────────────────────
function webcamDataURL() {
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (!w || !h) return null;
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (state.mirror === 'on') {
    ctx.save(); ctx.translate(w, 0); ctx.scale(-1, 1);
    ctx.drawImage(video, 0, 0);
    ctx.restore();
  } else {
    ctx.drawImage(video, 0, 0);
  }
  return canvas.toDataURL('image/jpeg', 0.8);
}

function currentImageData() {
  if (captured && snapshot.src) return snapshot.src;
  if (cameraReady) return webcamDataURL();
  return null;
}

function setImageSource(dataURL, fileName) {
  if (!dataURL) return;
  captured = true;
  uploadedFile = true;
  snapshot.src = dataURL;
  snapshot.hidden = false;
  video.hidden = true;
  previewWrap.hidden = false;
  captureBtn.hidden = true;
  uploadBtn.hidden = true;
  retakeBtn.hidden = false;
  printBtn.hidden = false;
  uploadName.textContent = fileName ? `Loaded ${fileName}` : '';
  refreshPreview();
  setStatus('Image ready. Adjust settings or print.');
}

// ── preview ──────────────────────────────────────────────
async function refreshPreview() {
  if (previewBusy) { previewDirty = true; return; }
  previewDirty = false;
  previewBusy = true;
  try {
    const { ip, label, password, rotate } = printerSettings();
    if (!ip || !label) return;

    const imageData = currentImageData();
    if (!imageData) return;

    const res = await fetch('/print', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_data: imageData,
        printer_ip: ip, label, password, rotate,
        preview: true,
        bw_mode: state.bwMode,
        fit_mode: state.fitMode,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setStatus(`Preview error: ${err.detail || res.status}`, 'error');
      return;
    }
    const data = await res.json();
    if (data.preview_image) {
      labelPreview.src   = data.preview_image;
      previewWrap.hidden = false;
      setStatus(captured ? 'Captured. Tweak settings or print.' : 'Live preview active. Capture when ready.');
    }
  } catch (err) {
    setStatus(`Preview error: ${err.message}`, 'error');
  } finally {
    previewBusy = false;
    if (previewDirty) refreshPreview();
  }
}

function startLive() {
  if (liveTimer || !cameraReady) return;
  liveTimer = setInterval(refreshPreview, 100);
  refreshPreview();
}

function stopLive() {
  clearInterval(liveTimer);
  liveTimer = null;
}

// ── camera ───────────────────────────────────────────────
async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true });
    video.srcObject = stream;
    video.addEventListener('loadedmetadata', () => {
      cameraReady = true;
      startLive();
      setStatus('Live preview active. Capture when ready.');
    }, { once: true });
  } catch {
    cameraReady = false;
    captureBtn.disabled = true;
    setStatus('Camera unavailable. Upload an image to continue.', 'error');
  }
}

// ── capture ──────────────────────────────────────────────
captureBtn.addEventListener('click', () => {
  if (!cameraReady) return;
  stopLive();
  captured = true;
  uploadedFile = false;

  const dataURL = webcamDataURL();
  if (!dataURL) { setStatus('Unable to capture from camera.', 'error'); return; }

  snapshot.src    = dataURL;
  snapshot.hidden = false;
  video.hidden    = true;

  captureBtn.hidden = true;
  uploadBtn.hidden  = true;
  retakeBtn.hidden  = false;
  printBtn.hidden   = false;

  refreshPreview();
  setStatus('Captured. Tweak settings or print.');
});

// ── retake ───────────────────────────────────────────────
retakeBtn.addEventListener('click', () => {
  captured = false;
  uploadedFile = false;
  snapshot.hidden = true;
  uploadName.textContent = '';

  if (cameraReady) {
    video.hidden      = false;
    captureBtn.hidden = false;
    uploadBtn.hidden  = false;
    retakeBtn.hidden  = true;
    printBtn.hidden   = true;
    startLive();
    setStatus('Live preview active. Capture when ready.');
  } else {
    video.hidden       = true;
    captureBtn.hidden  = true;
    uploadBtn.hidden   = false;
    retakeBtn.hidden   = true;
    printBtn.hidden    = true;
    previewWrap.hidden = true;
    setStatus('Upload an image to continue.', 'info');
  }
});

// ── upload ───────────────────────────────────────────────
uploadBtn.addEventListener('click', () => imageUpload.click());

imageUpload.addEventListener('change', event => {
  const file = event.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => setImageSource(reader.result, file.name);
  reader.readAsDataURL(file);
});

// ── print ────────────────────────────────────────────────
printBtn.addEventListener('click', async () => {
  const { ip, label, password, rotate } = printerSettings();
  if (!ip || !label) { setStatus('Set Printer IP and Label in Settings.', 'error'); return; }
  if (!snapshot.src)  { setStatus('No image selected to print.', 'error'); return; }

  printBtn.disabled = true;
  setStatus('Sending to printer…');
  try {
    const res = await fetch('/print', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_data: snapshot.src,
        printer_ip: ip, label, password, rotate,
        preview: false,
        bw_mode: state.bwMode,
        fit_mode: state.fitMode,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Request failed');
    setStatus('Printed!', 'ok');
  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
  } finally {
    printBtn.disabled = false;
  }
});

// ── label badge ──────────────────────────────────────────
function updateLabelBadge() {
  const val = document.getElementById('labelId').value.trim();
  labelBadge.textContent = val ? `Label ${val}` : '';
}

document.getElementById('labelId').addEventListener('input', updateLabelBadge);
updateLabelBadge();

video.classList.toggle('mirrored', state.mirror === 'on');
startCamera();

"""Blow detection routes — mounted into web.py with one include_router call.

Endpoints:
  POST /blow/event    — browser MediaPipe feeds a detected blow into BlowEngine
  GET  /blow/stream   — SSE: status every 1s + {event:"blow"} on detection
  POST /blow/settings — update enabled/sensitivity/arduino_threshold, persists to JSON
"""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import serial
import serial.tools.list_ports
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from blow_detection.engine import BlowEngine

logger = logging.getLogger("blow_router")

router = APIRouter()

# ── Settings ──────────────────────────────────────────────────────

SETTINGS_PATH = Path("blow_settings.json")
_settings_lock = threading.Lock()


def _load_settings() -> dict:
    defaults = {"enabled": False, "sensitivity": 0.5, "arduino_threshold": None}
    if SETTINGS_PATH.exists():
        try:
            return {**defaults, **json.loads(SETTINGS_PATH.read_text())}
        except Exception:
            pass
    return defaults


def _save_settings(s: dict):
    SETTINGS_PATH.write_text(json.dumps(s, indent=2))


_settings = _load_settings()

# ── Arduino serial reader ─────────────────────────────────────────

_ARDUINO_KEYWORDS = (
    "arduino", "wch", "ch340", "usb serial", "usb-serial", "cp210", "usb2.0-serial"
)
_BLOW_COOLDOWN = 4.0


def _find_arduino_port() -> Optional[str]:
    for p in serial.tools.list_ports.comports():
        text = f"{p.description} {p.manufacturer or ''}".lower()
        if any(kw in text for kw in _ARDUINO_KEYWORDS):
            return p.device
    return None


class ArduinoReader:
    def __init__(self, arduino_queue):
        self._queue = arduino_queue
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._status = {"connected": False, "level": 0, "threshold": 0}

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def _set(self, **kwargs):
        with self._lock:
            self._status.update(kwargs)

    def _run(self):
        while self._running:
            port = _find_arduino_port()
            if not port:
                self._set(connected=False, level=0, threshold=0)
                time.sleep(5)
                continue
            try:
                ser = serial.Serial(port, 115200, timeout=1)
                self._set(connected=True)
                ard_state = "ready"   # "ready" | "blowing"
                while self._running:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    if raw.startswith("LEVEL,"):
                        parts = raw.split(",")
                        level, ard_thresh = int(parts[1]), int(parts[2])
                        self._set(level=level, threshold=ard_thresh)
                        _broadcast({"arduino_level": {"level": level, "threshold": ard_thresh}})
                        with _settings_lock:
                            srv_thresh = _settings.get("arduino_threshold") or ard_thresh
                        above = level >= srv_thresh
                        if ard_state == "ready" and above:
                            ard_state = "blowing"
                            self._queue.put(time.time())
                        elif ard_state == "blowing" and not above:
                            ard_state = "ready"
                    # Arduino's own BLOW signal ignored — server does its own detection
                ser.close()
            except Exception as e:
                logger.warning(f"Serial error: {e}")
            self._set(connected=False, level=0, threshold=0)
            time.sleep(5)


# ── SSE subscriber pool ───────────────────────────────────────────

_sse_clients: set = set()
_sse_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None
_mediapipe_last_seen: float = 0.0


def _broadcast(payload: dict):
    with _sse_lock:
        clients = list(_sse_clients)
    if _loop and clients:
        for q in clients:
            _loop.call_soon_threadsafe(q.put_nowait, payload)


# ── Engine + Arduino (module-level singletons) ────────────────────

_engine = BlowEngine(
    on_blow=lambda source, ts, _: _broadcast(
        {"event": "blow", "source": source, "ts": ts}
    ),
    blow_to_print=_settings["enabled"],
)
_arduino = ArduinoReader(_engine.arduino_queue)


# ── Startup / shutdown (called from web.py lifespan) ─────────────

async def _status_loop():
    while True:
        await asyncio.sleep(1)
        active = (time.time() - _mediapipe_last_seen) < 30
        with _settings_lock:
            enabled           = _settings["enabled"]
            sensitivity       = _settings["sensitivity"]
            arduino_threshold = _settings["arduino_threshold"]
        _broadcast({
            "arduino":           {"connected": _arduino.get_status()["connected"]},
            "mediapipe":         {"active": active},
            "enabled":           enabled,
            "sensitivity":       sensitivity,
            "arduino_threshold": arduino_threshold,
        })


def startup():
    """Call from FastAPI lifespan — starts background threads and grabs the event loop."""
    global _loop
    _loop = asyncio.get_event_loop()
    _engine.start()
    _arduino.start()
    asyncio.create_task(_status_loop())


def shutdown():
    """Call from FastAPI lifespan — stops background threads."""
    _engine.stop()
    _arduino.stop()


# ── Routes ────────────────────────────────────────────────────────

_TASK_FILE = Path(__file__).parent / "blow_detection" / "face_landmarker.task"

_DEBUG_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Blow Debug</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #111; color: #ccc; font: 13px/1.5 'Courier New', monospace;
         display: flex; height: 100vh; overflow: hidden; }

  /* left: camera */
  #left { position: relative; flex: 1; background: #000;
          display: flex; align-items: center; justify-content: center; }
  #cam  { display: block; max-width: 100%; max-height: 100%; }
  #state-badge { position: absolute; bottom: 18px; left: 50%; transform: translateX(-50%);
                 font-size: 1.6rem; font-weight: 900; letter-spacing: .05em;
                 text-shadow: 0 2px 10px #000; pointer-events: none; }
  #init-msg { position: absolute; color: #666; font-size: 0.9rem; }

  /* right: panel */
  #right { width: 270px; flex-shrink: 0; display: flex; flex-direction: column;
           border-left: 1px solid #222; overflow: hidden; }
  .pane  { padding: 12px 14px; border-bottom: 1px solid #1e1e1e; flex-shrink: 0; }
  .pane h3 { font-size: 0.62rem; text-transform: uppercase; letter-spacing: .1em;
             color: #555; margin-bottom: 8px; }
  .row   { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .pill  { font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 99px;
           border: 1.5px solid; white-space: nowrap; }
  .g { color: #3EBD87; border-color: #3EBD87; }
  .r { color: #E05F7B; border-color: #E05F7B; }
  .m { color: #444;    border-color: #333; }

  .bar-wrap { position: relative; flex: 1; height: 7px; background: #222;
              border-radius: 3px; overflow: visible; }
  .bar-fill { height: 100%; border-radius: 3px; transition: width .07s; }
  .bar-thresh { position: absolute; top: -4px; width: 2px; height: 15px;
                background: #fff; border-radius: 1px; }
  .val { font-size: 0.65rem; color: #555; white-space: nowrap; }

  btn-row { display: flex; gap: 6px; flex-wrap: wrap; }
  button { padding: 4px 10px; background: #1e1e1e; border: 1px solid #333; color: #bbb;
           border-radius: 4px; font: inherit; font-size: 0.75rem; cursor: pointer; }
  button:hover { background: #2a2a2a; }

  #log { flex: 1; overflow-y: auto; padding: 8px 12px; }
  .entry { font-size: 0.68rem; color: #555; padding: 2px 0;
           border-bottom: 1px solid #191919; white-space: nowrap; overflow: hidden;
           text-overflow: ellipsis; }
  .entry.blow { color: #E05F7B; font-weight: 700; }
  .entry.info { color: #7C6FF7; }

  /* ── Blow indicators ─────────────────────────────────────────── */
  .ind-row { display:flex; align-items:center; gap:9px; padding:6px 0; }
  .ind-row:not(:last-child) { border-bottom:1px solid #1a1a1a; }
  .ind-label { font-size:.72rem; flex-shrink:0; width:68px; }
  .ind-count { font-size:.62rem; color:#444; min-width:20px; text-align:right; flex-shrink:0; }
  .ind-bar-wrap { flex:1; height:7px; background:#1c1c1c; border-radius:3px; overflow:hidden; }
  .ind-row.combo .ind-bar-wrap { height:11px; }
  .ind-row.combo .ind-label { font-weight:700; font-size:.76rem; }
</style>
</head>
<body>

<div id="left">
  <canvas id="cam"></canvas>
  <div id="state-badge" style="color:#3EBD87">READY</div>
  <div id="init-msg">initialising…</div>
</div>

<div id="right">
  <div class="pane">
    <h3>MediaPipe</h3>
    <div class="row">
      <span id="mp-pill" class="pill m">loading</span>
      <span id="mp-val" class="val">nw=—  thresh=—</span>
    </div>
    <div class="row">
      <div class="bar-wrap">
        <div id="mp-bar" class="bar-fill" style="width:70%;background:#7C6FF7"></div>
        <div id="mp-thresh" class="bar-thresh" style="left:62%"></div>
      </div>
    </div>
    <div class="row" style="margin-top:4px;gap:4px">
      <span style="font-size:.65rem;color:#444">thresh</span>
      <input id="thresh-slider" type="range" min="20" max="80" value="50"
             style="flex:1;accent-color:#7C6FF7">
      <span id="thresh-num" class="val">0.50</span>
    </div>
  </div>

  <div class="pane">
    <h3>Arduino  <span id="sse-dot" style="color:#555">● sse</span></h3>
    <div class="row">
      <span id="ard-pill" class="pill m">unknown</span>
      <span id="ard-val" class="val">—</span>
    </div>
    <div class="row">
      <div class="bar-wrap">
        <div id="ard-bar" class="bar-fill" style="width:0%;background:#F59E0B"></div>
        <div id="ard-thresh-line" class="bar-thresh" style="left:80%"></div>
      </div>
    </div>
    <div class="row" style="margin-top:4px">
      <span id="en-pill" class="pill m">enabled: —</span>
    </div>
  </div>

  <div class="pane">
    <h3>Blow Indicators</h3>
    <div class="ind-row">
      <span class="ind-label" style="color:#7C6FF7">MediaPipe</span>
      <div class="ind-bar-wrap">
        <div id="bar-mp" style="height:100%;width:0%;border-radius:3px;background:#7C6FF7"></div>
      </div>
      <span class="ind-count" id="cnt-mp">0</span>
    </div>
    <div class="ind-row">
      <span class="ind-label" style="color:#F59E0B">Arduino</span>
      <div class="ind-bar-wrap">
        <div id="bar-ard" style="height:100%;width:0%;border-radius:3px;background:#F59E0B"></div>
      </div>
      <span class="ind-count" id="cnt-ard">0</span>
    </div>
    <div class="ind-row combo">
      <span class="ind-label" style="color:#3EBD87">Combined</span>
      <div class="ind-bar-wrap">
        <div id="bar-comb" style="height:100%;width:0%;border-radius:3px;background:#3EBD87"></div>
      </div>
      <span class="ind-count" id="cnt-comb">0</span>
    </div>
    <div class="row" style="margin-top:6px;gap:4px">
      <span style="font-size:.65rem;color:#444">window</span>
      <input id="combo-slider" type="range" min="500" max="5000" step="100" value="2000"
             style="flex:1;accent-color:#3EBD87">
      <span id="combo-num" class="val">2.0s</span>
    </div>
  </div>

  <div class="pane">
    <h3>Blow-to-print  <span style="color:#555;font-size:.6rem;text-transform:none;letter-spacing:0">(auto-print on blow)</span></h3>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button onclick="setSetting({enabled:true})">Enable</button>
      <button onclick="setSetting({enabled:false})">Disable</button>
      <button onclick="simBlow()">Sim blow</button>
    </div>
  </div>

  <div style="padding:6px 14px;font-size:.6rem;color:#333;border-bottom:1px solid #1a1a1a;flex-shrink:0">
    EVENT LOG
  </div>
  <div id="log"></div>
</div>

<script type="module">
import { FaceLandmarker, FilesetResolver }
  from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";

// ── landmarks ────────────────────────────────────────────────────
const MOUTH_L = 61, MOUTH_R = 291, EYE_L = 33, EYE_R = 263;
const MIN_FRAMES = 3;

let threshold = 0.50;
let state = 'ready', consec = 0, flashUntil = 0;

const _indCounts = { mp: 0, ard: 0, comb: 0 };
const _blowTime  = { mp: 0, ard: 0, comb: 0 };
let _COMBO_WIN = 2000;

function triggerInd(id) {
  _blowTime[id] = performance.now();
  _indCounts[id]++;
  document.getElementById('cnt-' + id).textContent = _indCounts[id];
}

(function animateBars() {
  const now = performance.now();
  for (const [id, color] of [['mp','#7C6FF7'],['ard','#F59E0B'],['comb','#3EBD87']]) {
    const pct = Math.max(0, 1 - (now - _blowTime[id]) / _COMBO_WIN) * 100;
    const bar = document.getElementById('bar-' + id);
    bar.style.width = pct + '%';
    bar.style.boxShadow = pct > 0 ? `0 0 8px 3px ${color}90` : 'none';
  }
  requestAnimationFrame(animateBars);
})();

const cam = document.getElementById('cam');
const ctx = cam.getContext('2d');
const badge = document.getElementById('state-badge');
const initMsg = document.getElementById('init-msg');

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

// ── log ──────────────────────────────────────────────────────────
function addLog(msg, cls = '') {
  const d = document.createElement('div');
  d.className = 'entry ' + cls;
  d.textContent = new Date().toLocaleTimeString('en', {hour12:false}) + '  ' + msg;
  const el = document.getElementById('log');
  el.prepend(d);
  while (el.children.length > 100) el.lastChild.remove();
}

// ── controls ─────────────────────────────────────────────────────
function setSetting(body) {
  fetch('/blow/settings', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
    .then(r => r.json()).then(() => addLog('settings ' + JSON.stringify(body), 'info'));
}
function simBlow() {
  fetch('/blow/event', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({source:'mediapipe', ts: Date.now()/1000})})
    .then(() => addLog('simulated blow sent', 'blow'));
}
window.setSetting = setSetting;
window.simBlow = simBlow;

const slider = document.getElementById('thresh-slider');
slider.addEventListener('input', () => {
  threshold = slider.value / 100;
  document.getElementById('thresh-num').textContent = threshold.toFixed(2);
  updateThreshLine();
});
const comboSlider = document.getElementById('combo-slider');
comboSlider.addEventListener('input', () => {
  _COMBO_WIN = parseInt(comboSlider.value);
  document.getElementById('combo-num').textContent = (_COMBO_WIN / 1000).toFixed(1) + 's';
});

function updateThreshLine() {
  document.getElementById('mp-thresh').style.left =
    Math.min(100, (threshold / 0.8) * 100) + '%';
}
updateThreshLine();

// ── SSE ──────────────────────────────────────────────────────────
const es = new EventSource('/blow/stream');
const sseDot = document.getElementById('sse-dot');
es.onopen  = () => { sseDot.style.color = '#3EBD87'; sseDot.textContent = '● sse'; };
es.onerror = () => { sseDot.style.color = '#E05F7B'; sseDot.textContent = '● sse err'; };
es.onmessage = e => {
  let d; try { d = JSON.parse(e.data); } catch { return; }
  if (d.arduino_level) {
    const al = d.arduino_level;
    const pct = Math.min(100, (al.level / al.threshold) * 80);
    document.getElementById('ard-bar').style.width = pct + '%';
    document.getElementById('ard-thresh-line').style.left =
      Math.min(100, (al.threshold / 200) * 100) + '%';
    document.getElementById('ard-val').textContent = 'lvl=' + al.level + ' thr=' + al.threshold;
    return;
  }
  if (d.event === 'blow') {
    addLog('BLOW ← server (' + d.source + ')', 'blow');
    const src = d.source;
    const key = src === 'mediapipe' ? 'mp' : 'ard';
    const otherKey = src === 'mediapipe' ? 'ard' : 'mp';
    const pNow = performance.now();
    triggerInd(key);
    if (pNow - _blowTime[otherKey] < _COMBO_WIN) triggerInd('comb');
    return;
  }

  const ard = d.arduino || {};
  const ap = document.getElementById('ard-pill');
  ap.className = 'pill ' + (ard.connected ? 'g' : 'm');
  ap.textContent = ard.connected ? 'connected' : 'disconnected';
  if (ard.threshold) {
    const pct = Math.min(100, (ard.level / ard.threshold) * 80);
    document.getElementById('ard-bar').style.width = pct + '%';
    document.getElementById('ard-thresh-line').style.left =
      Math.min(100, (ard.threshold / 200) * 100) + '%';
    document.getElementById('ard-val').textContent =
      'lvl=' + ard.level + ' thr=' + ard.threshold;
  }
  const ep = document.getElementById('en-pill');
  ep.className = 'pill ' + (d.enabled ? 'g' : 'm');
  ep.textContent = 'enabled: ' + (d.enabled ? 'yes' : 'no');

};

// ── MediaPipe init ────────────────────────────────────────────────
addLog('loading FaceLandmarker…', 'info');
const vision = await FilesetResolver.forVisionTasks(
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm'
);
const landmarker = await FaceLandmarker.createFromOptions(vision, {
  baseOptions: { modelAssetPath: '/blow/face_landmarker.task', delegate: 'GPU' },
  runningMode: 'VIDEO',
  numFaces: 1,
});
addLog('FaceLandmarker ready', 'info');

const vid = document.createElement('video');
vid.autoplay = true; vid.playsInline = true; vid.muted = true;
const stream = await navigator.mediaDevices.getUserMedia({ video: true });
vid.srcObject = stream;
await new Promise(res => vid.onloadedmetadata = res);
await vid.play();

initMsg.style.display = 'none';
document.getElementById('mp-pill').className = 'pill g';
document.getElementById('mp-pill').textContent = 'active';

// ── render loop ───────────────────────────────────────────────────
function tick(now) {
  requestAnimationFrame(tick);
  if (vid.readyState < 2) return;

  const W = vid.videoWidth, H = vid.videoHeight;
  if (cam.width !== W || cam.height !== H) { cam.width = W; cam.height = H; }

  // draw mirrored frame
  ctx.save();
  ctx.scale(-1, 1); ctx.translate(-W, 0);
  ctx.drawImage(vid, 0, 0);
  ctx.restore();

  const result = landmarker.detectForVideo(vid, now);
  const lms = result.faceLandmarks;
  let nw = 1.0;

  if (lms && lms.length > 0) {
    const lm = lms[0];
    const mw = dist(lm[MOUTH_L], lm[MOUTH_R]);
    const fw = dist(lm[EYE_L],   lm[EYE_R]);
    nw = fw > 0 ? mw / fw : 1.0;

    // state machine
    const pursed = nw <= threshold;
    if (state === 'ready') {
      consec = pursed ? consec + 1 : 0;
      if (consec >= MIN_FRAMES) {
        state = 'blowing'; flashUntil = now + 600; consec = 0;
        addLog('BLOW nw=' + nw.toFixed(3), 'blow');
        fetch('/blow/event', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({source:'mediapipe', ts: now/1000})});
      }
    } else {
      if (!pursed) { state = 'ready'; consec = 0; }
    }

    // draw landmarks — mirrored x = (1 - lm.x) * W
    const dot = state === 'blowing' ? '#E05F7B' : '#7C6FF7';
    [MOUTH_L, MOUTH_R, EYE_L, EYE_R].forEach(i => {
      const p = lm[i];
      ctx.beginPath();
      ctx.arc((1 - p.x) * W, p.y * H, 5, 0, Math.PI * 2);
      ctx.fillStyle = dot; ctx.fill();
    });
    // mouth line
    const ml = lm[MOUTH_L], mr = lm[MOUTH_R];
    ctx.beginPath();
    ctx.moveTo((1 - ml.x) * W, ml.y * H);
    ctx.lineTo((1 - mr.x) * W, mr.y * H);
    ctx.strokeStyle = dot; ctx.lineWidth = 2; ctx.stroke();

    // HUD bar (top-left, like Python version)
    const bx = 14, by = 14, bw = Math.min(W - 28, 260), bh = 22;
    ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(bx, by, bw, bh);
    const fillW = Math.min(nw / 0.8, 1) * bw;
    ctx.fillStyle = state === 'blowing' ? '#E05F7B' : '#3EBD87';
    ctx.fillRect(bx, by, fillW, bh);
    const tx = bx + Math.min((threshold / 0.8) * bw, bw);
    ctx.fillStyle = '#fff'; ctx.fillRect(tx - 1, by - 3, 2, bh + 6);
    ctx.fillStyle = '#fff'; ctx.font = '11px monospace';
    ctx.fillText('nw=' + nw.toFixed(3) + '  thresh=' + threshold.toFixed(2) +
                 '  ' + state.toUpperCase() + '  ' + consec + '/' + MIN_FRAMES,
                 bx + 4, by + 15);

    // sidebar update
    document.getElementById('mp-bar').style.width =
      Math.min(100, (nw / 0.8) * 100) + '%';
    document.getElementById('mp-val').textContent =
      'nw=' + nw.toFixed(3) + '  thresh=' + threshold.toFixed(2);
  }

  // blow flash border
  if (now < flashUntil) {
    ctx.strokeStyle = '#E05F7B'; ctx.lineWidth = 10;
    ctx.strokeRect(5, 5, W - 10, H - 10);
  }

  // badge
  if (now < flashUntil) {
    badge.style.color = '#E05F7B'; badge.textContent = 'BLOW';
  } else {
    badge.style.color = state === 'blowing' ? '#E05F7B' : '#3EBD87';
    badge.textContent = state.toUpperCase();
  }
}

requestAnimationFrame(tick);
</script>
</body>
</html>"""


@router.get("/blow/debug")
async def blow_debug():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_DEBUG_HTML)


@router.get("/blow/face_landmarker.task")
async def face_landmarker_task():
    return FileResponse(_TASK_FILE, media_type="application/octet-stream")


class _BlowEvent(BaseModel):
    source: str
    ts: float


@router.post("/blow/event")
async def blow_event(body: _BlowEvent):
    global _mediapipe_last_seen
    _mediapipe_last_seen = time.time()
    _engine.mediapipe_queue.put(("mediapipe", body.ts))
    return {"ok": True}


@router.get("/blow/stream")
async def blow_stream(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    with _sse_lock:
        _sse_clients.add(q)

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with _sse_lock:
                _sse_clients.discard(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class _BlowSettings(BaseModel):
    enabled: Optional[bool] = None
    sensitivity: Optional[float] = None
    arduino_threshold: Optional[int] = None


@router.post("/blow/settings")
async def blow_settings(body: _BlowSettings):
    with _settings_lock:
        if body.enabled is not None:
            _settings["enabled"] = body.enabled
            _engine.blow_to_print = body.enabled
        if body.sensitivity is not None:
            _settings["sensitivity"] = body.sensitivity
        if body.arduino_threshold is not None:
            _settings["arduino_threshold"] = body.arduino_threshold
        _save_settings(_settings)
    return {"ok": True}

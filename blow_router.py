"""Blow detection routes — mounted into web.py with one include_router call.

Endpoints:
  POST /blow/event    — browser MediaPipe feeds a detected blow into BlowEngine
  GET  /blow/stream   — SSE: status every 1s + {event:"blow"} on detection
  POST /blow/settings — update enabled/sensitivity/countdown_s, persists to JSON
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
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return {"enabled": False, "sensitivity": 0.5, "countdown_s": 3}


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
                last_blow = 0.0
                while self._running:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    if raw.startswith("LEVEL,"):
                        parts = raw.split(",")
                        self._set(level=int(parts[1]), threshold=int(parts[2]))
                    elif raw == "BLOW":
                        now = time.time()
                        if now - last_blow >= _BLOW_COOLDOWN:
                            last_blow = now
                            self._queue.put(now)
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
            enabled = _settings["enabled"]
            countdown_s = _settings["countdown_s"]
        _broadcast({
            "arduino": _arduino.get_status(),
            "mediapipe": {"active": active},
            "enabled": enabled,
            "countdown_s": countdown_s,
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
<title>Blow Detection Debug</title>
<style>
  :root {
    --bg: #F0EEF8; --surface: #fff; --border: #E2DCF5;
    --primary: #7C6FF7; --text: #2D2640; --sub: #8B83A8; --muted: #B8B0D0;
    --green: #3EBD87; --red: #E05F7B; --amber: #F59E0B;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; font-size: 14px; color: var(--text);
         background: var(--bg); padding: 24px; display: flex; flex-direction: column;
         gap: 16px; max-width: 560px; }
  h1 { font-size: 1.1rem; font-weight: 700; color: var(--primary); }
  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
  .label { font-size: 0.62rem; font-weight: 700; letter-spacing: .08em;
           text-transform: uppercase; color: var(--sub); }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .pill { font-size: 0.72rem; font-weight: 600; padding: 3px 10px; border-radius: 99px;
          border: 1.5px solid; white-space: nowrap; }
  .pill.green { color: var(--green); border-color: var(--green); background: #edfaf5; }
  .pill.red   { color: var(--red);   border-color: var(--red);   background: #fdf0f3; }
  .pill.amber { color: var(--amber); border-color: var(--amber); background: #fef9ec; }
  .pill.muted { color: var(--muted); border-color: var(--muted); background: #f7f5fc; }
  .bar-wrap { flex: 1; height: 8px; background: #eee; border-radius: 4px; overflow: hidden; min-width: 80px; }
  .bar-fill { height: 100%; background: var(--primary); border-radius: 4px; transition: width .1s; }
  .bar-fill.blow { background: var(--red); }
  .num { font-size: 0.78rem; color: var(--sub); min-width: 64px; text-align: right; }
  .log { font-size: 0.72rem; font-family: monospace; color: var(--sub);
         max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
  .log-entry { padding: 4px 8px; border-radius: 6px; background: #f5f3fd; }
  .log-entry.blow { background: #fdf0f3; color: var(--red); font-weight: 600; }
  button { padding: 6px 14px; border-radius: 8px; border: 1.5px solid var(--primary);
           background: var(--primary); color: #fff; font-size: 0.8rem; font-weight: 600;
           cursor: pointer; }
  button.outline { background: #fff; color: var(--primary); }
  #sse-status { font-size: 0.72rem; }
</style>
</head>
<body>
<h1>Blow Detection Debug</h1>

<div class="card">
  <div class="label">SSE Stream <span id="sse-status" style="color:var(--muted)">connecting…</span></div>
  <div class="row">
    <div class="label" style="min-width:60px">Arduino</div>
    <span id="ard-pill" class="pill muted">unknown</span>
    <div class="bar-wrap"><div id="ard-bar" class="bar-fill" style="width:0%"></div></div>
    <span id="ard-num" class="num">—</span>
  </div>
  <div class="row">
    <div class="label" style="min-width:60px">MediaPipe</div>
    <span id="mp-pill" class="pill muted">unknown</span>
  </div>
  <div class="row">
    <div class="label" style="min-width:60px">Enabled</div>
    <span id="en-pill" class="pill muted">—</span>
    <span id="cd-val" class="num" style="text-align:left"></span>
  </div>
</div>

<div class="card">
  <div class="label">Controls</div>
  <div class="row">
    <button id="btn-on"  onclick="setSetting({enabled:true})">Enable</button>
    <button id="btn-off" class="outline" onclick="setSetting({enabled:false})">Disable</button>
    <button class="outline" onclick="simulateBlow()">Simulate MediaPipe blow</button>
  </div>
</div>

<div class="card" style="flex:1">
  <div class="label">Event log</div>
  <div class="log" id="log"></div>
</div>

<script>
const $ = id => document.getElementById(id);

function setPill(el, text, cls) {
  el.textContent = text;
  el.className = 'pill ' + cls;
}

function log(msg, cls='') {
  const d = document.createElement('div');
  d.className = 'log-entry ' + cls;
  d.textContent = new Date().toLocaleTimeString() + '  ' + msg;
  const l = $('log');
  l.prepend(d);
  while (l.children.length > 60) l.lastChild.remove();
}

function setSetting(body) {
  fetch('/blow/settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)})
    .then(r => r.json()).then(d => log('settings → ' + JSON.stringify(body)));
}

function simulateBlow() {
  const ts = Date.now() / 1000;
  fetch('/blow/event', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({source:'mediapipe', ts})})
    .then(r => r.json()).then(() => log('sent POST /blow/event (mediapipe)', 'blow'));
}

let es;
function connect() {
  es = new EventSource('/blow/stream');
  es.onopen = () => { $('sse-status').textContent = '● connected'; $('sse-status').style.color = 'var(--green)'; };
  es.onerror = () => { $('sse-status').textContent = '● error — retrying'; $('sse-status').style.color = 'var(--red)'; };
  es.onmessage = e => {
    let d;
    try { d = JSON.parse(e.data); } catch { return; }

    if (d.event === 'blow') {
      log('BLOW from ' + d.source, 'blow');
      $('ard-bar').classList.add('blow');
      setTimeout(() => $('ard-bar').classList.remove('blow'), 600);
      return;
    }

    // status frame
    const ard = d.arduino || {};
    if (ard.connected) {
      setPill($('ard-pill'), 'connected', 'green');
      const pct = ard.threshold ? Math.min(100, Math.round(ard.level / ard.threshold * 80)) : 0;
      $('ard-bar').style.width = pct + '%';
      $('ard-num').textContent = (ard.level || 0) + ' / ' + (ard.threshold || 0);
    } else {
      setPill($('ard-pill'), 'disconnected', 'red');
      $('ard-bar').style.width = '0%';
      $('ard-num').textContent = '—';
    }

    const mp = d.mediapipe || {};
    setPill($('mp-pill'), mp.active ? 'active' : 'inactive', mp.active ? 'green' : 'muted');

    setPill($('en-pill'), d.enabled ? 'on' : 'off', d.enabled ? 'green' : 'amber');
    $('cd-val').textContent = 'countdown ' + (d.countdown_s || 3) + 's';
  };
}

connect();
</script>
</body>
</html>"""


@router.get("/blow/debug", response_class=FileResponse)
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
    countdown_s: Optional[int] = None


@router.post("/blow/settings")
async def blow_settings(body: _BlowSettings):
    with _settings_lock:
        if body.enabled is not None:
            _settings["enabled"] = body.enabled
            _engine.blow_to_print = body.enabled
        if body.sensitivity is not None:
            _settings["sensitivity"] = body.sensitivity
        if body.countdown_s is not None:
            _settings["countdown_s"] = body.countdown_s
        _save_settings(_settings)
    return {"ok": True}

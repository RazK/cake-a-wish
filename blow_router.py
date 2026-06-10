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

"""Blow detection routes — mounted into web.py with one include_router call.

Endpoints:
  POST /blow/event    — browser MediaPipe feeds a detected blow into BlowEngine
  POST /blow/settings — update sensitivity/cooldown/require flags, persists to JSON

Events pushed to /events SSE stream:
  blow            — {source, ts, will_print}
  cooldown        — {remaining}
  arduino_level   — {level, threshold}
  arduino/mediapipe status — via _status_loop
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
from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import events as sse
from blow_detection.engine import BlowEngine

logger = logging.getLogger("blow_router")

router = APIRouter()

# ── Settings ──────────────────────────────────────────────────────

SETTINGS_PATH = Path("data") / "blow_settings.json"
_settings_lock = threading.Lock()


def _load_settings() -> dict:
    defaults = {"sensitivity": 0.5, "arduino_threshold": None, "cooldown": 4.0, "require_camera": True, "require_arduino": True, "sensor_gap": 1.0}
    if SETTINGS_PATH.exists():
        try:
            return {**defaults, **json.loads(SETTINGS_PATH.read_text())}
        except Exception as e:
            logger.warning(f"Failed to load settings, using defaults: {e}")
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
        self._status = {"connected": False, "port": None, "level": 0, "threshold": 0}

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
                self._set(connected=False, port=None, level=0, threshold=0)
                time.sleep(5)
                continue
            try:
                ser = serial.Serial(port, 115200, timeout=1)
                self._set(connected=True, port=port)
                ard_state = "ready"   # "ready" | "blowing"
                while self._running:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                    if not raw:
                        if not _find_arduino_port():
                            break
                        continue
                    if raw.startswith("LEVEL,"):
                        parts = raw.split(",")
                        level, ard_thresh = int(parts[1]), int(parts[2])
                        self._set(level=level, threshold=ard_thresh)
                        sse.broadcast({"arduino_level": {"level": level, "threshold": ard_thresh}})
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
            self._set(connected=False, port=None, level=0, threshold=0)
            time.sleep(5)


# ── SSE ───────────────────────────────────────────────────────────

_mediapipe_last_seen: float = 0.0


def _init_payload() -> dict:
    ard = _arduino.get_status()
    active = (time.time() - _mediapipe_last_seen) < 30
    with _settings_lock:
        return {
            "sensitivity":       _settings["sensitivity"],
            "arduino_threshold": _settings["arduino_threshold"],
            "cooldown":          _settings.get("cooldown", 4.0),
            "require_camera":    _settings.get("require_camera", True),
            "require_arduino":   _settings.get("require_arduino", True),
            "sensor_gap":        _settings.get("sensor_gap", 1.0),
            "arduino":           {"connected": ard["connected"], "port": ard["port"]},
            "mediapipe":         {"active": active},
        }


sse.register_init_hook(_init_payload)


# ── Engine + Arduino (module-level singletons) ────────────────────

_engine = BlowEngine(
    on_blow=lambda source, ts, will_print: sse.broadcast(
        {"event": "blow", "source": source, "ts": ts, "will_print": will_print}
    ),
    on_cooldown=lambda remaining: sse.broadcast(
        {"event": "cooldown", "remaining": remaining}
    ),
    blow_to_print=True,
    cooldown=_settings.get("cooldown", 4.0),
    require_camera=_settings.get("require_camera", True),
    require_arduino=_settings.get("require_arduino", True),
    sensor_gap=_settings.get("sensor_gap", 1.0),
)
_arduino = ArduinoReader(_engine.arduino_queue)


# ── Startup / shutdown (called from web.py lifespan) ─────────────

async def _status_loop():
    while True:
        await asyncio.sleep(1)
        ard = _arduino.get_status()
        active = (time.time() - _mediapipe_last_seen) < 30
        sse.broadcast({
            "arduino":   {"connected": ard["connected"], "port": ard["port"]},
            "mediapipe": {"active": active},
        })


def startup():
    """Call from FastAPI lifespan — starts background threads and grabs the event loop."""
    sse.set_loop(asyncio.get_event_loop())
    _engine.start()
    _arduino.start()
    asyncio.create_task(_status_loop())


def shutdown():
    """Call from FastAPI lifespan — stops background threads."""
    _engine.stop()
    _arduino.stop()


# ── Routes ────────────────────────────────────────────────────────

_TASK_FILE = Path(__file__).parent / "face_landmarker.task"


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


class _BlowSettings(BaseModel):
    sensitivity:       Optional[float] = Field(default=None, ge=0.0, le=1.0)
    arduino_threshold: Optional[int]   = Field(default=None, ge=1, le=1023)
    cooldown:          Optional[float] = Field(default=None, ge=1.0, le=30.0)
    require_camera:    Optional[bool]  = None
    require_arduino:   Optional[bool]  = None
    sensor_gap:        Optional[float] = Field(default=None, ge=0.1, le=10.0)


@router.post("/blow/settings")
async def blow_settings(body: _BlowSettings):
    with _settings_lock:
        if body.sensitivity is not None:
            _settings["sensitivity"] = body.sensitivity
        if body.arduino_threshold is not None:
            _settings["arduino_threshold"] = body.arduino_threshold
        if body.cooldown is not None:
            _settings["cooldown"] = body.cooldown
            _engine.cooldown = body.cooldown
        if body.require_camera is not None:
            _settings["require_camera"] = body.require_camera
            _engine.require_camera = body.require_camera
        if body.require_arduino is not None:
            _settings["require_arduino"] = body.require_arduino
            _engine.require_arduino = body.require_arduino
        if body.sensor_gap is not None:
            _settings["sensor_gap"] = body.sensor_gap
            _engine.sensor_gap = body.sensor_gap
        snapshot = dict(_settings)
    _save_settings(snapshot)
    return {"ok": True}

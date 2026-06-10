"""MediaPipe mouth-proportion blow detector.

Runs in a background thread. Emits events to a queue and keeps a live
`info` dict for polling (status panel).

Detection logic — state machine:
  Signal: normalized_width = mouth_width / face_width
    mouth_width : landmark 61 (left corner) → 291 (right corner)
    face_width  : landmark 33 (left eye outer) → 263 (right eye outer)
  A blow = lips purse → mouth narrows → normalized_width drops BELOW threshold.

  READY   : counting consecutive frames below threshold
              → when count >= min_frames: emit BLOW, go to BLOWING
  BLOWING : already fired — waiting for mouth to relax (value rises above threshold)
              → when above threshold: go to READY

One BLOW per crossing. Three distinct puffs → three events.
"""

import os
import queue
import threading
import time
import logging
from typing import Optional

import cv2
import mediapipe as mp

logger = logging.getLogger("mediapipe_blow")

_MOUTH_L, _MOUTH_R = 61, 291       # mouth corners
_EYE_L,   _EYE_R   = 33, 263       # outer eye corners (stable face-width reference)
_MODEL = os.path.join(os.path.dirname(__file__), "face_landmarker.task")

_FaceLandmarker = mp.tasks.vision.FaceLandmarker
_FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
_RunningMode = mp.tasks.vision.RunningMode

_READY   = "ready"
_BLOWING = "blowing"


def _dist(a, b) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


class MediaPipeBlow:
    """Reads webcam frames, detects blow expression, pushes events to a queue."""

    def __init__(
        self,
        blow_queue: queue.Queue,
        camera_index: int = 0,
        ratio_threshold: float = 0.5,
        min_frames: int = 3,
    ):
        self._queue = blow_queue
        self._camera_index = camera_index
        self._ratio_threshold = ratio_threshold
        self._min_frames = min_frames

        self._thread: Optional[threading.Thread] = None
        self._running = False

        self._info = {
            "status": "stopped",      # stopped | active | no_face | error
            "state": _READY,          # ready | blowing
            "normalized_width": 1.0,  # mouth_width / face_width  (lower = more pursed)
            "threshold": ratio_threshold,
            "consecutive": 0,
        }
        self._lock = threading.Lock()

    @property
    def info(self) -> dict:
        with self._lock:
            return dict(self._info)

    def update_threshold(self, ratio_threshold: float):
        self._ratio_threshold = ratio_threshold
        with self._lock:
            self._info["threshold"] = ratio_threshold

    def start(self, camera_index: Optional[int] = None):
        if self._running:
            return
        if camera_index is not None:
            self._camera_index = camera_index
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            logger.error(f"Cannot open camera {self._camera_index}")
            with self._lock:
                self._info["status"] = "error"
            return

        options = _FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=_MODEL),
            running_mode=_RunningMode.IMAGE,
            num_faces=1,
        )
        landmarker = _FaceLandmarker.create_from_options(options)

        state = _READY
        consecutive = 0

        with self._lock:
            self._info["status"] = "active"

        try:
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.03)
                    continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect(mp_image)

                if not result.face_landmarks:
                    consecutive = 0
                    with self._lock:
                        self._info["status"] = "no_face"
                        self._info["normalized_width"] = 1.0
                        self._info["consecutive"] = 0
                        self._info["state"] = state
                    time.sleep(0.03)
                    continue

                lm = result.face_landmarks[0]
                mouth_w = _dist(lm[_MOUTH_L], lm[_MOUTH_R])
                face_w  = _dist(lm[_EYE_L],   lm[_EYE_R])
                nw = mouth_w / face_w if face_w > 0 else 1.0
                pursed = nw <= self._ratio_threshold

                if state == _READY:
                    consecutive = consecutive + 1 if pursed else 0
                    if consecutive >= self._min_frames:
                        state = _BLOWING
                        consecutive = 0
                        now = time.time()
                        logger.info(f"BLOW detected (nw={nw:.3f})")
                        self._queue.put(("mediapipe", now))
                elif state == _BLOWING:
                    if not pursed:
                        state = _READY
                        consecutive = 0

                with self._lock:
                    self._info["status"] = "active"
                    self._info["normalized_width"] = round(nw, 3)
                    self._info["consecutive"] = consecutive
                    self._info["threshold"] = self._ratio_threshold
                    self._info["state"] = state

        finally:
            cap.release()
            landmarker.close()
            with self._lock:
                self._info["status"] = "stopped"

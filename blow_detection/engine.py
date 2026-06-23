"""Blow detection engine — fuses Arduino + MediaPipe signals.

Either signal alone is sufficient to trigger a blow event.
Fires a callback with source ('arduino' | 'mediapipe') and timestamp.
Tracks whether 'blow_to_print' is enabled; if not, fires 'would_print' instead.
Enforces a cooldown period after each print fires.
"""

import queue
import threading
import time
import logging
from typing import Callable, Optional

logger = logging.getLogger("blow_engine")


class BlowEngine:
    """Fuses Arduino and MediaPipe queues into a single event stream."""

    def __init__(
        self,
        on_blow: Callable[[str, float, bool], None],
        blow_to_print: bool = False,
        cooldown: float = 4.0,
        on_cooldown: Optional[Callable[[float], None]] = None,
    ):
        """
        on_blow(source, timestamp, will_print)
          source     — 'arduino' | 'mediapipe'
          timestamp  — time.time() of detection
          will_print — True if blow_to_print is on and print will fire

        on_cooldown(remaining)
          remaining  — seconds until next print is allowed (0.0 = ready)
          called every ~100ms after a print fires until cooldown expires
        """
        self._on_blow = on_blow
        self._on_cooldown = on_cooldown
        self._blow_to_print = blow_to_print
        self._cooldown = cooldown
        self._last_print_ts: float = 0.0
        self._last_cooldown_broadcast: float = 0.0
        self._lock = threading.Lock()

        self._arduino_queue: queue.Queue = queue.Queue()
        self._mediapipe_queue: queue.Queue = queue.Queue()

        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Last event info for panel polling
        self._last_event: Optional[dict] = None

    @property
    def arduino_queue(self) -> queue.Queue:
        """Feed Arduino blow timestamps (floats) into this queue."""
        return self._arduino_queue

    @property
    def mediapipe_queue(self) -> queue.Queue:
        """Feed MediaPipe blow events (('mediapipe', float) tuples) here."""
        return self._mediapipe_queue

    @property
    def blow_to_print(self) -> bool:
        return self._blow_to_print

    @blow_to_print.setter
    def blow_to_print(self, value: bool):
        with self._lock:
            self._blow_to_print = value

    @property
    def cooldown(self) -> float:
        return self._cooldown

    @cooldown.setter
    def cooldown(self, value: float):
        with self._lock:
            self._cooldown = value

    @property
    def last_event(self) -> Optional[dict]:
        with self._lock:
            return dict(self._last_event) if self._last_event else None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        while self._running:
            self._drain(self._arduino_queue, "arduino")
            self._drain(self._mediapipe_queue, "mediapipe")
            self._tick_cooldown()
            time.sleep(0.02)

    def _tick_cooldown(self):
        if not self._on_cooldown:
            return
        with self._lock:
            last_print = self._last_print_ts
            cooldown = self._cooldown
        if last_print == 0.0:
            return
        now = time.time()
        if now - self._last_cooldown_broadcast < 0.05:
            return
        remaining = max(0.0, cooldown - (now - last_print))
        self._last_cooldown_broadcast = now
        try:
            self._on_cooldown(round(remaining, 2))
        except Exception as e:
            logger.error(f"on_cooldown callback error: {e}")
        if remaining == 0.0:
            with self._lock:
                self._last_print_ts = 0.0

    def _drain(self, q: queue.Queue, default_source: str):
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                return

            # Arduino pushes raw floats; MediaPipe pushes ('mediapipe', ts) tuples
            if isinstance(item, tuple):
                source, ts = item
            else:
                source, ts = default_source, item

            now = time.time()
            with self._lock:
                # Drop signal if still in cooldown after a print
                if self._last_print_ts > 0 and (now - self._last_print_ts) < self._cooldown:
                    continue

                will_print = self._blow_to_print
                self._last_event = {
                    "source": source,
                    "ts": ts,
                    "will_print": will_print,
                }
                if will_print:
                    self._last_print_ts = now
                    self._last_cooldown_broadcast = 0.0  # broadcast immediately

            logger.info(f"Blow event: source={source} will_print={will_print}")
            try:
                self._on_blow(source, ts, will_print)
            except Exception as e:
                logger.error(f"on_blow callback error: {e}")

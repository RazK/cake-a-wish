"""Start the Cake A Wish server and open the browser.

Intended to be launched via pythonw.exe (no terminal window).
On each launch it kills any existing server on port 8000, starts fresh,
and opens the browser. Logs rotate in logs/server.log.
"""
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT     = Path(__file__).parent
TASK_FILE = ROOT / "blow_detection" / "face_landmarker.task"
TASK_URL  = (
    "https://storage.googleapis.com/mediapipe-models"
    "/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)
PORT = 8000


def _setup_logging():
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "server.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)-20s %(levelname)s %(message)s"))
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.WARNING)


def _kill_existing():
    """Kill any process currently listening on our port."""
    try:
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{PORT}" in parts[1] and parts[3] == "LISTENING":
                pid = int(parts[4])
                if pid != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                    time.sleep(0.5)
    except Exception:
        pass


def _ensure_task_file():
    if TASK_FILE.exists():
        return
    logging.getLogger("launcher").warning("Downloading face_landmarker.task (~3.6 MB)...")
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(TASK_URL, TASK_FILE)
    except Exception as e:
        TASK_FILE.unlink(missing_ok=True)
        logging.getLogger("launcher").error("Could not download face_landmarker.task: %s", e)


def _open_browser():
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=0.5)
            break
        except Exception:
            time.sleep(0.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


def main():
    _setup_logging()
    _kill_existing()
    _ensure_task_file()

    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    from main import app
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()

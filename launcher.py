"""Start the Cake A Wish server and open the browser automatically.

Usage:
    python launcher.py

This is the intended entry point for both development and end-user use.
It downloads the face_landmarker.task model on first run if missing,
then starts uvicorn on localhost:8000 and opens the browser.
"""
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

TASK_FILE = Path(__file__).parent / "blow_detection" / "face_landmarker.task"
TASK_URL  = (
    "https://storage.googleapis.com/mediapipe-models"
    "/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)


def _ensure_task_file():
    if TASK_FILE.exists():
        return
    print("Downloading face_landmarker.task (~3.6 MB) — first run only...")
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(TASK_URL, TASK_FILE)
        print("Downloaded successfully.")
    except Exception as e:
        TASK_FILE.unlink(missing_ok=True)  # remove partial file so next launch retries
        print(f"Warning: could not download face_landmarker.task: {e}")
        print(f"Camera blow detection will be unavailable until the file is present at:\n  {TASK_FILE}")


def main():
    _ensure_task_file()

    import uvicorn
    from main import app

    def _open_browser():
        import urllib.request as _req
        for _ in range(20):
            try:
                _req.urlopen("http://localhost:8000/", timeout=0.5)
                break
            except Exception:
                time.sleep(0.5)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()

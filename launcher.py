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

ROOT      = Path(__file__).parent
TASK_FILE = ROOT / "blow_detection" / "face_landmarker.task"
TASK_URL  = (
    "https://storage.googleapis.com/mediapipe-models"
    "/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)
PORT = 8000


def _setup_logging():
    try:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "server.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)-20s %(levelname)s %(message)s"))
        logging.root.addHandler(handler)
    except Exception:
        logging.root.addHandler(logging.NullHandler())
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
    except Exception:
        pass
    import socket as _socket
    for _ in range(30):
        try:
            s = _socket.create_connection(("127.0.0.1", PORT), timeout=0.1)
            s.close()
            time.sleep(0.1)
        except OSError:
            break


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


def _run_server():
    import uvicorn
    from main import app
    # log_config=None prevents uvicorn from calling sys.stdout.isatty()
    # which crashes under pythonw.exe (no stdout)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning", log_config=None)


def _show_window():
    """Small tkinter control window — appears in the taskbar like any app."""
    import ctypes
    import tkinter as tk

    # Must be called before the window is created — tells Windows this is its
    # own distinct app, not a generic Python process, so it gets its own icon.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CakeAWish.Server.1")
    except Exception:
        pass

    root = tk.Tk()
    root.title("Cake A Wish")
    root.resizable(False, False)
    root.configure(bg="#1e1b2e")

    # Set icon: iconbitmap for title bar, WM_SETICON for taskbar button
    ico_path = ROOT / "static" / "favicon.ico"
    try:
        root.iconbitmap(str(ico_path))
        root.update_idletasks()          # ensure HWND exists
        hwnd  = root.winfo_id()
        hicon = ctypes.windll.user32.LoadImageW(
            None, str(ico_path), 1,      # IMAGE_ICON
            0, 0, 0x10 | 0x40,          # LR_LOADFROMFILE | LR_DEFAULTSIZE
        )
        if hicon:
            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 1, hicon)  # WM_SETICON ICON_BIG
            ctypes.windll.user32.SendMessageW(hwnd, 0x80, 0, hicon)  # WM_SETICON ICON_SMALL
    except Exception:
        pass

    # Layout
    pad = dict(padx=16, pady=6)
    tk.Label(root, text="🎂  Cake A Wish", bg="#1e1b2e", fg="#e8d5f5",
             font=("Segoe UI", 13, "bold")).pack(**pad)
    tk.Label(root, text=f"Running at http://localhost:{PORT}",
             bg="#1e1b2e", fg="#9b8ab0", font=("Segoe UI", 9)).pack(padx=16, pady=(0, 8))

    btn_frame = tk.Frame(root, bg="#1e1b2e")
    btn_frame.pack(padx=16, pady=(0, 14))

    def open_browser():
        webbrowser.open(f"http://127.0.0.1:{PORT}")

    def restart_app():
        root.destroy()
        import sys
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def quit_app():
        root.destroy()
        os._exit(0)

    tk.Button(btn_frame, text="Open", command=open_browser,
              bg="#7c5cbf", fg="white", relief="flat",
              font=("Segoe UI", 9), padx=14, pady=4).pack(side="left", padx=(0, 8))
    tk.Button(btn_frame, text="Restart", command=restart_app,
              bg="#9a3070", fg="#fce8f5", relief="flat",
              font=("Segoe UI", 9), padx=14, pady=4).pack(side="left", padx=(0, 8))
    tk.Button(btn_frame, text="Quit", command=quit_app,
              bg="#4a3060", fg="#e8d5f5", relief="flat",
              font=("Segoe UI", 9), padx=14, pady=4).pack(side="left")

    root.mainloop()


def main():
    _setup_logging()
    _kill_existing()
    _ensure_task_file()

    threading.Thread(target=_open_browser, daemon=True).start()
    threading.Thread(target=_run_server,   daemon=True).start()

    _show_window()   # blocks main thread; closing window quits the app


if __name__ == "__main__":
    main()

"""Entry point for the frozen (PyInstaller) build.

When run as a script (dev mode) it behaves identically — just starts uvicorn
and opens a browser tab. PyInstaller uses this as its Analysis target so it
can walk imports from here.
"""
import sys
import os
import threading
import time
import webbrowser


def _set_base_dir():
    """Tell all modules where bundled assets live."""
    import pathlib
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys._MEIPASS)
    else:
        base = pathlib.Path(__file__).parent
    os.environ["CAKE_BASE_DIR"] = str(base)
    # Also fix CWD so relative "data/" writes land next to the exe
    if getattr(sys, "frozen", False):
        os.chdir(pathlib.Path(sys.executable).parent)


def main():
    _set_base_dir()

    import uvicorn
    from main import app  # noqa: import after env var is set

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()

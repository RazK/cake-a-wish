Label Printer — minimal Brother QL utility
=======================================

Quick usage:

Preview (no send):

```bash
PRINTER_PASSWORD=Lnku1DmF .venv/bin/python hello_label.py 192.168.1.139 --preview --rotate --text "Hello"
```

Print:

```bash
.venv/bin/python hello_label.py 192.168.1.139 --text "Hello"
```

Code layout: `label_printer/` package with `printer.py`, `label.py`, `convertor.py`, `cli.py`, and `web.py`.

Web UI:

```bash
pip install -r requirements.txt
uvicorn label_printer.web:app --reload
```

Then open `http://127.0.0.1:8000` and capture/print from your browser.

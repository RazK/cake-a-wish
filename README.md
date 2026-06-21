# Cake A Wish

Birthday cake photo-booth kiosk for **Microsoft Learning Zone**. A tablet sits behind a real cake — guests blow on the candle, and the printer inside the cake prints their photo on a label that slides out like a Polaroid.

![Admin panel](docs/screenshots/admin-captured.png)

---

## How it works

```
Tablet (front-facing camera)
        │ WiFi
  FastAPI server  (this repo)
        │ TCP 9100 / HTTP 80
  Brother QL-820NWBc  ←  inside the cake
        │
  DK-22251 label  →  out of the cake
```

Staff run the app on a laptop on the same WiFi. Guests never touch anything — a blow on the candle triggers the print automatically via Arduino mic + MediaPipe face detection.

---

## Pages

| Route | Who | What |
|-------|-----|-------|
| `/` | Staff | Admin — camera, capture, template, gallery, settings |

---

## Setup — Mac / Linux

**Requirements:** Python 3.11+

```bash
git clone https://github.com/RazK/cake-a-wish.git
cd cake-a-wish

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Download the MediaPipe face landmarker model (~3.6 MB, not in git)
curl -Lo blow_detection/face_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task

python launcher.py
```

Browser opens at `http://localhost:8000` automatically.

---

## Setup — Windows

**Requirements:** [Python 3.11+](https://www.python.org/downloads/) — during install, tick **"Add python.exe to PATH"**.

```bat
git clone https://github.com/RazK/cake-a-wish.git
cd cake-a-wish

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Download the MediaPipe model (run in PowerShell):

```powershell
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task" `
  -OutFile "blow_detection\face_landmarker.task"
```

Then start the app:

```bat
python launcher.py
```

Browser opens at `http://localhost:8000` automatically.

**USB printing on Windows** requires an extra driver step: install [Zadig](https://zadig.akeo.ie/), select the Brother printer, and install the WinUSB driver. WiFi printing works without this.

---

## Distributable build (no Python needed)

You can build a standalone bundle for Mac or Windows that anyone can run without installing Python.

```bash
python build.py          # build for current platform
python build.py --clean  # clean rebuild
```

Output in `dist/`:
- **Mac** → `dist/CakeAWish.app` — double-click to launch
- **Windows** → `dist/CakeAWish\CakeAWish.exe` — double-click to launch

> **Note:** PyInstaller builds are platform-specific — build on Mac to get a `.app`, build on Windows to get a `.exe`. There are no pre-built binaries available for download yet.

To share: zip the output folder and send it.

```bash
# Mac
zip -r CakeAWish-mac.zip dist/CakeAWish.app

# Windows (PowerShell)
Compress-Archive dist\CakeAWish CakeAWish-win.zip
```

---

## Printer

The app auto-discovers the printer on your local network — no IP config needed. The status pill in the header shows the connection state. If both WiFi and USB are connected, you can switch between them with the WiFi / USB tabs in the Printer card.

---

## Admin panel

![Hardware settings](docs/screenshots/admin-left-panel.png) ![Photo settings](docs/screenshots/admin-right-panel.png)

**Left column — Hardware Settings**
- **Printer** — live status (offline/online/printing/error), label auto-detected from printer
- **Camera** — live MediaPipe feed, lip threshold slider for blow sensitivity
- **Arduino** — serial mic level bar, threshold slider
- **Blow to Print** — toggle auto-print on blow; combined indicator shows fused signal

**Center — Canvas**
- Live camera feed with template overlay composited in real time
- Capture freezes the frame and fetches a WYSIWYG dithered preview from the server
- Action bar: `Capture` / `Retake` / `Quick Print ⚡` / `Load 📂` / `Save 💾` / `Print`

**Right column — Photo Settings**
- **Template** — upload full/header/footer PNG overlays, save custom templates
- **Photos** — brightness slider, gallery of last 20 prints (click to re-edit, delete)

---

## Blow detection

Two independent signals fused server-side:

| Source | How |
|--------|-----|
| **Arduino** | Analog mic on A0, sends `LEVEL,{level},{threshold}` at 100ms intervals over serial |
| **MediaPipe** | Browser-side face landmark detection; pursed-lip ratio triggers `POST /blow/event` |

Either signal alone can trigger a print. Thresholds are tunable via the Arduino and Camera sliders in the Hardware Settings panel.

---

## Templates

Three built-in templates (Clean / Bold / Retro). To add a designer-supplied template:

1. Export from Figma at **696 × 1109 px** (62red label resolution)
2. Create `overlay.png` — transparent where the photo shows, opaque for borders/branding
3. Write `config.json` with fractional photo rect and branding text
4. Drop the folder under `label_printer/frames/my-template/`
5. Restart — template appears automatically in the admin UI

See [PRODUCT.md](docs/PRODUCT.md#6-template-system) for the full spec.

---

## Arduino

Sketch is at `arduino/BlowDetector/BlowDetector.ino`. Flash it to any Arduino with an analog mic on A0. The server auto-detects the serial port on startup (looks for "arduino", "ch340", "cp210" in port names).

---

## Project docs

| Doc | Contents |
|-----|----------|
| [PRODUCT.md](docs/PRODUCT.md) | Full product spec — physical setup, feature set, API surface, print pipeline |
| [DESIGN.md](docs/DESIGN.md) | Design tokens, component specs, layout, interaction model |

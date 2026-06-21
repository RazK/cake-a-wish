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

## Quick start

**Requirements:** [Python 3.11+](https://www.python.org/downloads/)

```bash
# Mac / Linux
./setup.sh        # one-time setup — creates venv, installs deps, adds Desktop shortcut
./run.sh          # start the app (or double-click the Desktop shortcut)
```

```bat
:: Windows
setup.bat         :: one-time setup — creates venv, installs deps, adds Desktop shortcut
run.bat           :: start the app (or double-click the Desktop shortcut)
```

Browser opens at `http://localhost:8000` automatically. The `face_landmarker.task` model (~3.6 MB) is downloaded automatically on first run.

The printer is auto-discovered on the local network — no IP config needed. Works on the same WiFi as the printer, or on the printer's WiFi Direct network (no internet required).

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

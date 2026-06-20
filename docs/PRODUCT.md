# Cake A Wish — Product, UX/UI & Dev Brief

Birthday cake photo-booth kiosk for **Microsoft Learning Zone** conference.
A tablet sits behind a real cake. Guests blow on the candle; the printer inside
the cake prints their photo on a label that slides out like a polaroid.

---

## 1. Physical Setup

```
                 ┌──────────────────────────┐
  Tablet         │  /  (kiosk mode)          │  full-screen, no chrome
  (in cake)      │  front-facing camera      │  guests never touch it
                 └──────────────────────────┘
                          │ WiFi
                 ┌────────┴─────────┐
                 │  FastAPI server  │  runs on same tablet or nearby host
                 └────────┬─────────┘
                          │ TCP 9100 / HTTP 80
                 ┌────────┴─────────┐
                 │  Brother QL-820NWBc │  inside the cake
                 │  DK-22251 tape      │  62mm red+black continuous
                 └──────────────────┘

  Staff laptop  →  /admin  (same WiFi)   debug, retake, gallery
```

---

## 2. Two-Page Architecture

| Route    | Audience | Purpose |
|----------|----------|---------|
| `/`      | Guests   | Kiosk — full-screen live view, blow-to-print, zero chrome |
| `/admin` | Staff    | Full UI — capture, retake, template, gallery, settings |

Both pages talk to the same FastAPI server. The server holds printer state.

---

## 3. Feature Set

### Admin page
- **Live camera feed** — mirrored by default, rotatable 90°
- **Capture / Retake** — single button toggles between modes
- **Quick Print ⚡** — one tap: capture + print immediately (no retake)
- **Load 📂** — choose file from disk instead of webcam, enters preview mode
- **Save 💾** — download captured image (enabled after capture)
- **Print** — send captured + framed image to printer (enabled after capture)
- **Template picker** — choose Clean / Bold / Retro frame (always visible, not buried)
- **Image controls** — fit/cover/stretch, mirror on/off, rotate 90°, brightness slider
- **WYSIWYG server preview** — after capture, server runs the actual dither pipeline and returns the result as PNG; replaces canvas so what you see = what prints
- **Gallery** — last 8 prints shown as thumbnails below controls; hover to reprint
- **Printer settings** — IP, password (collapsible, rarely needed)
- **Printer status pill** — always in header, live-updating every ~1s

### Blow detection (admin page)
- **Arduino mic reader** — serial thread reads `LEVEL,{level},{threshold}` frames at 100ms; detects blow state transitions; broadcasts via SSE
- **MediaPipe** — browser-side face landmark detection; pursed-lip ratio triggers `POST /blow/event`
- **BlowEngine** — server fuses both signals; fires `on_blow(source, ts, will_print)` callback
- **Blow-to-print toggle** — enable/disable auto-print on blow event
- **Countdown overlay** — 3–2–1 over the canvas after blow detected; fires quick-print at zero; keyboard shortcuts (Space cancel, Enter skip)
- **Blow debug page** `/blow/debug` — standalone test panel for tuning thresholds

```
Browser MediaPipe JS  →  POST /blow/event  →  ╮
                                               server fuses → SSE → all clients
Arduino serial        →  blow_router.py    →  ╯
```

### Kiosk page (not yet built)
- Full-bleed camera feed with active template frame composited live
- "Blow on the candle to print!" instruction
- Minimal status dot (no IP/settings exposed to guests)
- Printing animation (photo slides down into printer)

---

## 4. Design System

### Colors
```
Background    #F0EEF8 → #E8E4F5   lavender gradient (135deg)
Surface       #FFFFFF / rgba(255,255,255,0.70)  glass card
Border        #E2DCF5
Primary       #7C6FF7   purple
Primary-dim   #6258D3   purple pressed/hover
Text-main     #2D2640   near-black purple-tint
Text-sub      #8B83A8   muted purple-grey
Danger        #E05F7B   pink-red
Success       #3EBD87   green
```

### Typography
```
Font family   Poppins (Google Fonts)
Heading       700  clamp(1.8rem, 5.5vw, 3.2rem)
Label         600  0.75–0.85rem
Button        600–700  0.95–1rem
Body          400  0.85rem
Letter-spacing  buttons +0.02em, pills +0.04em
```

### Shape & Elevation
```
Card radius   16px
Button radius 12px
Pill radius   20px
Icon btn      8px
Shadow        0 4px 24px rgba(124,111,247,0.10)
```

### Buttons
```
Primary (Print)   bg #7C6FF7   color #fff   font-weight 700
Secondary         bg #fff      color #2D2640  border #E2DCF5
Muted (Retake)    bg #F5F3FF   color #8B83A8
Danger            bg #E05F7B   color #fff
Icon (⚡📂💾↻)   bg surface    color text-sub   40px square
Disabled          opacity 0.35
```

### Printer Status Pill (header, always visible)
```
● Ready · 62red         green  #3EBD87   — online, label matched
● Printing…             amber  #F59E0B   — job in progress
● No media              red    #E05F7B   — printer on, no roll
● Offline               red    #E05F7B   — no TCP connection
◌ Checking…             grey   #8B83A8   — first poll pending
⚠ Fix roll              red    #E05F7B   — error code surfaced
```

---

## 5. Wireframes

### /admin

```
┌─────────────────────────────────────────────────────────────────────┐
│  [lavender gradient bg]                                             │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  🎂  Cake A Wish              ● Ready · 62red  [ Settings ⚙ ] │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────┐  ┌───────────────────────────┐ │
│  │                                 │  │  🖼  Template              │ │
│  │                                 │  │  ┌──────┐┌──────┐┌──────┐ │ │
│  │    LIVE FEED / CAPTURED PHOTO   │  │  │ ╔══╗ ││ ████ ││▓▓sepi│ │ │
│  │                                 │  │  │ ║  ║ ││ ████ ││▓▓▓▓▓▓│ │ │
│  │   [polaroid frame composited    │  │  │ ╚══╝ ││ ████ ││▓▓▓▓▓▓│ │ │
│  │    over live canvas at exact    │  │  │Clean ││ Bold ││ Retro│ │ │
│  │    label aspect ratio]          │  │  └──────┘└──────┘└──────┘ │ │
│  │                                 │  │  [active = purple ring]    │ │
│  │   [canvas 306×991 for 62red,    │  └───────────────────────────┘ │
│  │    or exact die-cut dims]       │                                 │
│  │                                 │  ┌───────────────────────────┐ │
│  │   [server preview PNG replaces  │  │  🎨  Image                 │ │
│  │    canvas after capture]        │  │  Fit    [Contain|Cover|Fill]│ │
│  │                                 │  │  Mirror [ Off  |  On  ]    │ │
│  │                                 │  │  Rotate [ ↺ 90° ]         │ │
│  │                                 │  │  Brightness ━●━━━━━ 0     │ │
│  └─────────────────────────────────┘  └───────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  ┌──────────────┐  ┌──┐  ┌──┐  ┌──┐  ┌──────────────────┐   │  │
│  │  │  Capture     │  │⚡│  │📂│  │💾│  │      Print       │   │  │
│  │  │  (or Retake) │  └──┘  └──┘  └──┘  └──────────────────┘   │  │
│  │  └──────────────┘  quick load  save    [purple, always right] │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  🗂  Gallery  (last 8 prints)                  ← scroll →     │  │
│  │  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐    │  │
│  │  │    │ │    │ │    │ │    │ │    │ │    │ │    │ │    │    │  │
│  │  │[🖨]│ │[🖨]│ │[🖨]│ │[🖨]│ │[🖨]│ │[🖨]│ │[🖨]│ │[🖨]│    │  │
│  │  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘    │  │
│  │  newest first · hover shows reprint button overlay            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ─── ⚙ Settings ────────────────────────────────────────── ▾ ───   │
│  Printer IP · Password · detected label shown read-only            │
└─────────────────────────────────────────────────────────────────────┘
```

### / Kiosk (future)

```
┌─────────────────────────────────────────────────────────────────────┐
│  [full-bleed lavender — no header, no chrome]                       │
│                                                                     │
│           ┌─────────────────────────────────────┐                  │
│           │                                     │                  │
│           │      LIVE CAMERA FEED               │                  │
│           │      [template frame live]          │                  │
│           │                                     │                  │
│           └─────────────────────────────────────┘                  │
│                                                                     │
│                  🎂  Cake A Wish                                    │
│                                                                     │
│         💨  Blow on the candle to print your photo!                 │
│                                                              ◌      │
└─────────────────────────────────────────────────────────────────────┘

  Countdown overlay          Printing overlay
  ┌──────────────────┐       ┌──────────────────┐
  │  [frozen frame]  │       │  [captured frame] │
  │                  │       │  [polaroid frame] │
  │        3         │       │         ↓         │
  │  [giant, white,  │       │       [🖨]         │
  │   scale anim]    │       │   Printing…       │
  └──────────────────┘       └──────────────────┘
```

---

## 6. Template System

### How it works
Every print goes through a frame template before dithering. The template composites
the photo with branding/borders, then the result is sent to brother_ql.

### Adding a designer-supplied template (no code changes needed)

1. Designer opens Figma canvas at exact print resolution:
   - 62red continuous: **696 × 1109 px** (dots_printable for 62red at 300 dpi)
   - 29×90 die-cut: **306 × 991 px**
2. Designer exports two files at 1× from Figma:
   - `overlay.png` — PNG with **transparent** area where the photo should show through; opaque everywhere else (borders, branding, decorations)
   - `background.png` *(optional)* — solid background layer placed behind the photo
3. Designer writes `config.json`:
   ```json
   {
     "id": "my-template",
     "name": "My Template",
     "photo_rect": [0.05, 0.04, 0.95, 0.82],
     "branding_text": "Learning Zone · 2026",
     "branding_pos": [0.5, 0.93],
     "branding_size": 0.035
   }
   ```
   All coordinates are **fractions** (0.0–1.0) of the canvas — label-size independent.
4. Drop the folder under `label_printer/frames/my-template/`
5. Restart server → template auto-appears in `/frames` and the admin UI

### Stub templates (programmatic, no assets)
| ID      | Description |
|---------|-------------|
| `clean` | White polaroid, thin border, small purple branding strip |
| `bold`  | Full-bleed photo, thick purple strip, white text |
| `retro` | Sepia-toned photo, thick border, stamp-style text |

### API
```
GET  /templates              → [{id, name}, ...]
GET  /templates/{id}/overlay.png?w=W&h=H  → RGBA PNG for live preview
POST /preview                → {image_data, template_id}  → dithered PNG
POST /print                  → {image_data, template_id, printer_ip, label}
```

---

## 7. Printer Interfaces

### Transport
```
TCP  port 9100   — ESC/P raster instructions (print jobs)
HTTP port 80     — status polling (/home/status.html)
```

### Supported queries (via `BrotherPrinter`)
| What | How |
|------|-----|
| Connection check | TCP connect to :9100 |
| Status (media, errors, phase) | HTTP GET /home/status.html |
| Print job | TCP send ESC/P raster bytes |

### Status fields surfaced
```
connected       bool
status_type     "Printing" | "Waiting" | "Error" | …
phase_type      "Printing" | "Waiting" | …
media_type      "Continuous" | "Die-cut" | "No media" | …
media_width     int (mm)
media_length    int (mm, 0 for continuous)
errors          list[str]   human-readable error strings
label           str | null  matched brother_ql label ID
```

### Label auto-detection logic
```
62mm continuous + QL-820NWB model → "62red"  (two-color, red+black)
other continuous                  → matched by width
die-cut                           → matched by width × length
```

### Server API surface
```
GET  /printer                       cached monitor state (connected, label, errors)
PUT  /printer                       update printer IP, resets monitor
GET  /templates                     registered frame templates [{id, name}]
GET  /templates/{id}/overlay.png    RGBA overlay PNG for live canvas compositing
POST /preview                       dither preview PNG (WYSIWYG)
POST /print                         send job to printer, append to gallery
GET  /photos                        gallery [{thumbnail, raw_data, index}]
POST /photos                        save photo to gallery
DELETE /photos/{index}              delete photo
GET  /saved-templates               saved custom templates
POST /saved-templates               save custom template
POST /overlay/{slot}                upload PNG to slot (full/header/footer)
GET  /blow/stream                   SSE: printer status, Arduino levels, blow events
POST /blow/event                    receive blow from browser MediaPipe
POST /blow/settings                 update enabled/sensitivity/threshold
```

---

## 8. Print Pipeline

```
Webcam frame (RGB canvas)
      │
      ▼
_offRenderer.toDataURL()     ← offscreen canvas, same transform as main
      │
      ▼  POST /preview or /print
_apply_frame(image, frame_id)    ← composites template over photo
      │
      ▼
build_instructions(image, label_id)
      │
      ├─ is_red=True  → brother_ql convert(red=True, dither=False)
      │                  HSV separation: reds → red channel, darks → black
      │
      └─ is_red=False → brother_ql convert(dither=True)
                         Floyd-Steinberg dither to 1-bit black
      │
      ▼
BrotherPrinter(ip).send_instructions(bytes)
      │
      TCP :9100
      │
      ▼
Brother QL-820NWBc  →  DK-22251 label  →  out of the cake 🎂
```

---

## 9. Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| Canvas dims = `dots_printable` exactly | Avoids portrait/landscape mismatch that caused 500 on 29×90 |
| `bwMode: 'none'` on main canvas always | No color-flash on capture; server preview shows dithered result |
| `_captureSeq` + composition key | Prevents redundant server preview round-trips on re-renders |
| `_execute_print` shared helper | `/print` and `/print/auto` share identical logic, no duplication |
| Frame applied in web.py, not convertor.py | Keeps convertor.py a pure image→bytes pipe; web layer owns composition |
| Background monitor polls every 1s (0.3s offline) | Printer errors surface in status pill naturally; no post-print TCP status hack |
| Fractional coords in template config.json | Same config works for any label size; designer doesn't need to know pixel dims |

---

## 10. Future Work

- **Kiosk page** `/` — full-screen guest view, printing animation, no chrome
- **QR code** on print — points to photo download or event page
- **Mascots / stickers** — designer overlays on templates
- **Multiple label support** — die-cut in addition to 62red continuous

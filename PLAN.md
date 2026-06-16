# Implementation Plan — Cake A Wish Web Layer

Single source of truth for phased build-out.
**Do not start a phase until the previous phase is approved.**

---

## Architecture

**Two-canvas layout:**
- Left panel `#cam-preview` — live camera + MediaPipe landmarks; blow detection visualization only
- Center `#canvas` — composited print canvas (camera + template overlay); what gets captured and printed

**Blow event flow:**
```
Browser MediaPipe JS  →  POST /blow/event  →  ╮
                                               server fuses → SSE → all clients
Arduino serial        →  blow_router.py    →  ╯
```

---

## Phase 1 — Skeleton ✅ Done

FastAPI + Jinja2, 3-column holy grail layout, design tokens, header.

---

## Phase 2 — Backend API ✅ Done

All routes live and verified end-to-end:
- `GET /printer` — polls every 1s, label auto-detected, last-known-good preserved on transient failures
- `PUT /printer {ip}` — update IP, resets monitor
- `GET /templates` — [clean, bold, retro]
- `GET /templates/{id}/overlay.png?w=W&h=H` — RGBA PNG
- `POST /preview` — dithered WYSIWYG PNG
- `POST /print` — sends to printer, appends to gallery
- `GET /history` — last 8 prints
- Printer default IP: `10.140.224.9` (29×90mm die-cut confirmed working)

---

## Phase 2.5 — Bluetooth ⚠️ Blocked

`BTBrotherPrinter` built. macOS RFCOMM never establishes. WiFi is the path forward.

---

## Phase 3 — Left Panel + Printer Status ✅ Done

Everything in the left column is live:

**Printer card:**
- Polls `GET /printer` every 2s — pill states: checking (amber) / online (green) / printing (green) / error (red) / offline (grey)
- Detail line: `{label_id} · {label_w}×{label_h} px`
- Canvas resizes to label dimensions on first valid response; `aspect-ratio` set in CSS; only updates when `connected: true` and value actually changed
- Label fallback bug fixed: monitor loop preserves last known good label when status parse returns no `media_width`

**Camera card:**
- `#cam-preview` canvas: live mirrored camera feed + MediaPipe landmarks drawn
- nw ratio bar + blow counter (purple)
- Lip threshold slider → `POST /blow/settings`

**Arduino card:**
- SSE `arduino_level` → level bar + threshold marker
- Blow counter (amber)
- Threshold slider → `POST /blow/settings`

**Blow to Print card:**
- On/Off toggle pill → `POST /blow/settings {enabled}`
- Combined blow counter + drain animation
- SSE heartbeat syncs toggle state + sensitivity + arduino_threshold from server

**CSS / layout:**
- `.card-head` flex row: label left, status dot right on all three cards
- `#canvas`: `max-height: 65%`, `padding: 16px 0` on wrap, `min-height: 0` on wrap
- `canvas-info` label below canvas

---

## Phase 4 — Main Canvas Live Feed ← NEXT

**What to build (JS in `admin.html`):**

Reuse the `vid` element already running for MediaPipe — don't open a second camera stream.

**Center `#canvas` render loop:**
- `requestAnimationFrame` loop draws `vid` mirrored onto `#canvas` each frame
- On first frame, set `canvas.width/height` to label dims from `window.printerState`
- Fetch template overlay once on load: `GET /templates/{id}/overlay.png?w=W&h=H` → ImageBitmap
- Draw overlay on top of each frame

**Template card — replace placeholder:**
- Three buttons: Clean / Bold / Retro, styled with active state
- Click → fetch new overlay, redraw on next frame

**Canvas info:**
- Already updates from printer polling ✅

### ✋ Approval gate
> 1. Live mirrored camera feed appears in center `#canvas`
> 2. Template overlay composites correctly on the feed
> 3. Clicking a template button switches the overlay
> 4. Canvas dimensions match the loaded label

---

## Phase 5 — Capture + Print Flow

**What to build (JS in `admin.html`):**

**State machine:** `live` ↔ `captured`

**Capture:**
- Freeze: stop drawing live feed, keep last frame on `#canvas`
- Fire `POST /preview {image_data, template_id}` → draw dithered result on `#canvas`
- Show Retake button; enable Print

**Retake:** resume live feed loop

**Print:**
- `POST /print {image_data, template_id}` → status bar "Sending…" → "Printed!"
- Reload `GET /history` → render thumbnails in gallery strip

**Action bar — replace placeholder:**
```
[ Capture ]  [ ⚡ Quick Print ]  [ 📂 Load ]  [ 💾 Save ]  [ Print ]
```
- Print + Save disabled until captured
- ⚡ Quick Print: capture + print in one tap (skips dithered preview)
- 📂 Load: file picker → enters captured mode
- 💾 Save: download current canvas as PNG

**Image controls card — replace placeholder:**
- Fit segmented control (Contain / Cover / Stretch) → canvas transform
- Mirror toggle (On/Off) — mirroring is currently hardcoded on; make it a toggle
- Rotate button (↻ 90°)
- Brightness slider (−100…100) — CSS filter, applied before capture

**Gallery:**
- Load from `GET /history` on page load + after each print
- Thumbnails rendered as `<img>` elements; click → load raw into canvas, enter captured mode

### ✋ Approval gate
> 1. Capture freezes feed, shows dithered server preview
> 2. Retake returns to live camera cleanly
> 3. Print sends job, gallery thumbnail appears
> 4. Changing template while captured re-fires preview without flash
> 5. Fit / Mirror / Rotate / Brightness visibly affect the canvas

---

## Phase 6 — Countdown + Auto-Print on Blow

**Depends on:** Phase 5 complete (needs the print flow).

**What to build (JS in `admin.html`):**

SSE `event: blow` is already received. Add:
- Countdown overlay on `#canvas`: 3…2…1 → fires Quick Print (⚡) at zero
- Only triggers if blow-to-print is enabled and not already counting/printing
- `countdown_s` number input → `POST /blow/settings {countdown_s}`
- SSE heartbeat already syncs `countdown_s` from server

### ✋ Approval gate
> 1. Toggle on → purse lips → countdown overlay → auto print
> 2. Toggle on → blow Arduino mic → same flow
> 3. Toggle off → blowing does nothing
> 4. Countdown respects the `countdown_s` setting

---

## Phase 7 — Settings + Polish

- Printer IP input in a Settings section → `PUT /printer` on blur/Enter → pill resets to checking
- Camera unavailable: status bar error, no crash
- BT/WiFi toggle UI (deferred from Phase 2.5)
- Any visual polish: transitions, empty states, error messages

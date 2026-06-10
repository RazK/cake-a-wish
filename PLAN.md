# Implementation Plan — Cake A Wish Web Layer

Single source of truth for phased build-out.
**Do not start a phase until the previous phase is approved.**

---

## Concurrent Implementation & Ownership

Two Claudes are working in parallel. This section defines the split, the
architecture decision, and the exact integration contract so neither blocks
the other.

### Architecture decision — camera ownership

**The problem:** A webcam can only be opened by one process at a time.
Server-side Python MediaPipe + browser `getUserMedia` for live preview would
conflict — one would fail.

**Decision:** Browser owns the camera exclusively.
- MediaPipe runs in the **browser** (`@mediapipe/tasks-vision` JS/WASM)
- Face blend shapes (`cheekPuff`, `mouthPucker`) detect blowing at 30fps in-browser
- Arduino serial stays **server-side** (can't access serial from browser)
- No video frames streamed over WebSocket — only the final blow event crosses the wire

### Ownership split

| Area | Owner |
|------|-------|
| `web.py` — printer API, preview, print, gallery, SSE endpoint | **Web Claude (this file)** |
| `templates/admin.html` — all frontend JS including MediaPipe JS | **Web Claude (this file)** |
| Arduino serial reader (`blow_detector.py` or equivalent) | **Other Claude** |
| `GET /blow/status` + SSE push when Arduino fires `BLOW` | **Other Claude** exposes; Web Claude consumes |

### Integration contract (the only thing that must be agreed)

**Other Claude delivers one SSE endpoint:**
```
GET /blow/stream
```
Streams Server-Sent Events. Each Arduino blow fires:
```
data: {"source": "arduino", "level": 142, "threshold": 95}
```
Also streams periodic status (every 1s):
```
data: {"arduino": {"connected": true, "level": 38, "threshold": 95}, "enabled": true, "countdown_s": 3}
```

**Web Claude consumes it:**
- Browser `EventSource('/blow/stream')` — no polling needed
- MediaPipe JS runs independently in browser on the camera stream
- Blow fires when **either** Arduino SSE event arrives **or** MediaPipe detects blow
- Both update the same Blow to Print UI state

**Settings written by Web Claude:**
```
POST /blow/settings   { enabled?, sensitivity?, countdown_s? }
```
Other Claude implements this endpoint; Web Claude calls it.

### What can run fully in parallel (no dependency)

Web Claude can complete Phases 2–5 without waiting for anything from Other Claude.
Phase 6 (blow integration) is the merge point — needs the SSE endpoint contract
above to be live before wiring up the frontend.

---

## Phase 1 — Runnable Skeleton ✅ Done

**What was built:**
- `web.py` — FastAPI app, `GET /admin`, Jinja2 template rendering
- `templates/admin.html` — 3-column holy grail layout, design tokens, Handjet logo,
  canvas with label info below, centered action bar, placeholder content

---

## Phase 2 — Backend API

**What gets built (all in `web.py`):**
- Background asyncio task: polls printer every 1s (0.3s when offline/checking), caches state
- Label auto-detection: maps printer status → `label_id` + pixel dims; fallback `62red` (696×1044)
- In-memory gallery list (last 8 prints)
- Routes:
  - `GET /printer` → `{ip, connected, label_id, label_w, label_h, status, phase, errors}`
  - `PUT /printer` `{ip}` → update IP, reset monitor
  - `GET /templates` → `[{id, name}]`
  - `GET /templates/{id}/overlay.png?w=W&h=H` → RGBA PNG
  - `POST /preview` `{image_data, template_id?}` → `{image_data}` (dithered WYSIWYG)
  - `POST /print` `{image_data, template_id?}` → `{ok, thumbnail}` + appends to gallery
  - `GET /history` → last 8 `{thumbnail, raw, template_id, label_id}`

**No frontend changes.**

### ✋ Approval gate
> Curl / browser test each endpoint:
> 1. `GET /printer` returns JSON (even if printer is offline — connected: false)
> 2. `GET /templates` returns the 3 templates
> 3. `GET /templates/clean/overlay.png?w=696&h=1044` returns a PNG
> 4. `POST /preview` with a test image returns a dithered PNG data URL
> 5. `GET /history` returns `[]`

---

## Phase 3 — Static UI

**What gets built (all in `templates/admin.html`):**
- Full CSS implementation of DESIGN.md tokens and components:
  - All design tokens as `--css-variables`
  - Typography: Poppins + Handjet, all sizes/weights
  - All components: printer status pill, template buttons, segmented control,
    primary/outline/icon buttons, brightness slider, gallery items
  - 3-column holy grail layout fully styled
- Static HTML with hardcoded placeholder content (no JS)
- **Blow to Print card** (static, no JS) — in the left column:
  - Card label: "BLOW TO PRINT"
  - Toggle row: "Quick print on blow" On/Off segmented control (placeholder state)
  - Status row: two pills — Arduino (connected/disconnected) + MediaPipe (active/inactive)
  - Sensitivity slider + numeric value
  - Countdown display placeholder "3s"

**Goal:** Page looks pixel-correct. All components styled. No behavior.

### ✋ Approval gate
> Open `/admin` and visually confirm:
> 1. Layout matches the 3-column holy grail (printer+blow left / canvas center / image+gallery right)
> 2. All components look right (pill, template buttons, action bar, gallery, settings)
> 3. Color, typography, spacing match the design tokens
> 4. Blow to Print card is visible in the left column, styled correctly, no JS errors

---

## Phase 4 — Camera + Live Feed

**What gets built (JS in `admin.html`):**
- Camera initialization (`getUserMedia`) → live render loop on canvas
- Template overlay fetch from `/templates/{id}/overlay.png` → composited on canvas each frame
- Printer status polling every 2s → pill state updates (checking / online / offline / printing / error)
- Template button clicks → fetch new overlay, update active state
- Canvas dimensions set from `GET /printer` response (`label_w × label_h`)

**Goal:** Open page, see live camera feed with template composited on top. Pill reflects real printer state.

### ✋ Approval gate
> In the browser:
> 1. Camera feed appears in the canvas (mirrored by default)
> 2. Template overlay is composited correctly on the live feed
> 3. Clicking a template button switches the overlay
> 4. Printer status pill updates from the server every 2s
> 5. Canvas dimensions update when printer label changes

---

## Phase 5 — Capture + Print Flow

**What gets built (JS in `admin.html`):**
- Capture button: freezes frame, fires `POST /preview`, swaps canvas to dithered result
- Retake button: returns to live feed (no flash)
- Print button: `POST /print` → status bar "Sending…" → "Printed!" → gallery reloads
- Gallery: loads from `GET /history` on page load and after each print; thumbnails render
- Disabled states: Print + Save disabled until captured; ⚡ disabled until camera ready
- State D: template change while captured → re-fires preview, no flash

**Goal:** Full happy path works end-to-end — capture → dithered preview → print → thumbnail in gallery.

### ✋ Approval gate
> Walk the happy path:
> 1. Capture freezes feed and shows dithered server preview
> 2. Retake returns to live camera cleanly
> 3. Print sends the job (or gets a network error if printer offline — either is fine)
> 4. Gallery thumbnail appears after a successful print
> 5. Changing template while captured updates the preview without a blank flash

---

## Phase 6 — Blow Detection Integration

**Depends on:** Other Claude's `GET /blow/stream` SSE endpoint being live (see contract above).

**What gets built:**

Backend (`web.py`):
- Consumes Other Claude's blow module — imports and wires Arduino serial reader into startup
- Adds `GET /blow/stream` SSE route (or defers to Other Claude's implementation)
- Adds `POST /blow/settings` `{enabled?, sensitivity?, countdown_s?}` → `{ok}`
- Persists settings to JSON file

Frontend (`admin.html` JS):
- Load `@mediapipe/tasks-vision` — initialize FaceLandmarker on the live camera stream
- Detect blow from blend shapes: `cheekPuff > 0.6` AND `mouthPucker > 0.4` for N consecutive frames
- `EventSource('/blow/stream')` — listen for Arduino blow events
- Fuse both signals: either source triggers countdown
- Blow to Print toggle → `POST /blow/settings {enabled}`
- Sensitivity slider → maps to blend shape threshold + `POST /blow/settings {sensitivity}`
- Countdown input → `POST /blow/settings {countdown_s}`
- On blow (when enabled): animate countdown overlay → fire ⚡ Quick Print at zero
- Update Arduino pill + MediaPipe pill from SSE status messages

**Goal:** Blow into mic or toward camera → countdown → auto print.

### ✋ Approval gate
> 1. `GET /blow/stream` delivers SSE events
> 2. Toggle on → blow toward camera → MediaPipe detects → countdown appears
> 3. Toggle on → blow into Arduino mic → Arduino event → countdown appears
> 4. Countdown reaches zero → Quick Print fires
> 5. Toggle off → blowing does nothing
> 6. Arduino pill + MediaPipe pill reflect live state

---

## Phase 7 — Image Controls + Polish

**What gets built (JS in `admin.html`):**
- Fit segmented control (Contain / Cover / Stretch) → updates canvas transform
- Mirror toggle (Off / On)
- Rotate button (↻ 90°)
- Brightness slider (−100…100) → applied before preview/print
- Settings: Printer IP input → `PUT /printer` on blur/Enter → pill resets to checking
- Gallery re-edit: click thumbnail → loads raw image as new capturedBmp, enters captured mode
- ⚡ Quick Print: capture + print in one tap
- 📂 Load from file: file picker → enters captured mode
- 💾 Save: downloads current canvas as PNG
- State E: camera unavailable → status bar error, empty canvas

**Goal:** All controls work. All button interactions correct. Edge cases handled.

### ✋ Approval gate
> 1. Fit / Mirror / Rotate all affect the canvas visibly
> 2. Brightness slider changes image brightness
> 3. Changing printer IP in Settings → pill goes to checking → updates
> 4. Click a gallery thumbnail → loads into canvas for re-editing
> 5. ⚡ Quick Print, 📂 Load, 💾 Save all work
> 6. Deny camera permission → status bar shows error, no crash

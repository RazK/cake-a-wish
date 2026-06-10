# Implementation Plan — Cake A Wish Web Layer

Single source of truth for phased build-out.
**Do not start a phase until the previous phase is approved.**

---

## Phase 1 — Runnable Skeleton

**What gets built:**
- `web.py` — FastAPI app, single route `GET /admin`, Jinja2 template rendering
- `templates/admin.html` — design tokens as CSS variables, Poppins loaded, correct page structure (header / workspace / action-bar / gallery / settings / status-bar divs) with placeholder content, no JS

**Goal:** `uvicorn web:app` runs, `/admin` opens in browser, page structure is visible.

### ✋ Approval gate
> Run the app and confirm:
> 1. `uvicorn web:app` starts without errors
> 2. `/admin` loads in the browser
> 3. Page sections are visible (even if unstyled/empty)

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
- Full CSS implementation of DESIGN.md §1–3:
  - All design tokens as `--css-variables`
  - Typography: Poppins, all sizes/weights
  - All components: printer status pill, template buttons, segmented control, primary/outline/icon buttons, brightness slider, gallery items, settings collapsible
  - Full 616px layout at correct proportions
- Static HTML with hardcoded placeholder content (no JS)
- **Blow to Print card** (static, no JS) — added to the left column below Settings:
  - Card label: "BLOW TO PRINT"
  - Toggle row: "Quick print on blow" On/Off segmented control (placeholder state)
  - Status row: two pills — Arduino (connected/disconnected) + MediaPipe (active/inactive)
  - Threshold row: sensitivity slider + numeric value
  - Countdown row: display placeholder "3s" (the delay between blow detected and shutter)

**Goal:** Page looks pixel-correct against DESIGN.md wireframes with no behavior. Blow to Print card is visible and styled but inert.

### ✋ Approval gate
> Open `/admin` and visually confirm:
> 1. Layout matches the 616px two-column wireframe
> 2. All components look right (pill, template buttons, action bar, gallery, settings)
> 3. Color, typography, spacing match the design tokens
> 4. Blow to Print card is visible below Settings, layout correct, no JS errors in console

---

## Phase 4 — Camera + Live Feed

**What gets built (JS in `admin.html`):**
- Camera initialization (`getUserMedia`) → live render loop on canvas
- Template overlay fetch from `/templates/{id}/overlay.png` → composited on canvas each frame
- Printer status polling every 2s → pill state updates (checking / online / offline / printing / error)
- Template button clicks → fetch new overlay, update active state

**Goal:** Open page, see live camera feed with template composited on top. Pill reflects real printer state.

### ✋ Approval gate
> In the browser:
> 1. Camera feed appears in the canvas (mirrored by default)
> 2. Template overlay is composited correctly on the live feed
> 3. Clicking a template button switches the overlay
> 4. Printer status pill updates from the server every 2s

---

## Phase 5 — Capture + Print Flow

**What gets built (JS in `admin.html`):**
- Capture button: freezes frame, fires `POST /preview`, swaps canvas to dithered result
- Retake button: returns to live feed (no flash)
- Print button: `POST /print` → status bar "Sending…" → "Printed!" → gallery reloads
- Gallery: loads from `GET /history` on page load and after each print; thumbnails render
- Disabled states: Print + Save disabled until captured; ⚡ disabled until camera ready
- State D: template change while captured → re-fires preview, no flash

**Goal:** Full happy path works end-to-end — capture → see dithered preview → print → thumbnail appears in gallery.

### ✋ Approval gate
> Walk the happy path:
> 1. Capture freezes feed and shows dithered server preview
> 2. Retake returns to live camera cleanly
> 3. Print sends the job (or gets a network error if printer offline — either is fine)
> 4. Gallery thumbnail appears after a successful print
> 5. Changing template while captured updates the preview without a blank flash

---

## Phase 6 — Blow Detection Integration

**What gets built:**

Backend (`web.py`):
- Background task: reads Arduino serial (`/dev/cu.usbserial-21310`, 115200 baud) using `blow_detector.py` pattern — parses `BASELINE`, `LEVEL`, `BLOW` lines
- Background task: MediaPipe webcam blow classifier — detects blow facial expression from the same camera feed
- Fusion: blow event fires when Arduino sends `BLOW` **or** MediaPipe detects a blow (either signal sufficient; configurable)
- Persisted settings (JSON): `enabled` bool, `sensitivity` (maps to Arduino threshold multiplier), `countdown_s` int
- Routes:
  - `GET /blow/status` → `{enabled, arduino: {connected, level, threshold}, mediapipe: {active}}`
  - `POST /blow/settings` `{enabled?, sensitivity?, countdown_s?}` → `{ok}`

Frontend (JS in `admin.html`):
- Wire Blow to Print toggle → `POST /blow/settings {enabled}`
- Poll `GET /blow/status` every 1s → update Arduino + MediaPipe status pills, live level meter in threshold row
- Sensitivity slider → `POST /blow/settings {sensitivity}` on change
- Countdown input → `POST /blow/settings {countdown_s}` on change
- Blow trigger: when `enabled` and blow event arrives (via polling or SSE) → start countdown animation → fire ⚡ Quick Print at zero

**Goal:** Blow into the mic → countdown ticks on screen → photo captured and printed automatically.

### ✋ Approval gate
> 1. `GET /blow/status` returns correct Arduino + MediaPipe state
> 2. Toggle on → blow into mic → countdown appears on screen
> 3. Countdown reaches zero → Quick Print fires (capture + print)
> 4. Toggle off → blowing does nothing
> 5. Arduino pill shows connected/disconnected correctly; MediaPipe pill shows active/inactive
> 6. Sensitivity slider changes detection threshold in real time (visible in level meter)

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
> Test each control:
> 1. Fit / Mirror / Rotate all affect the canvas visibly
> 2. Brightness slider changes image brightness
> 3. Changing printer IP in Settings → pill goes to checking → updates
> 4. Click a gallery thumbnail → loads into canvas for re-editing
> 5. ⚡ Quick Print, 📂 Load, 💾 Save all work
> 6. Deny camera permission → status bar shows error, no crash

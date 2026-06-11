# Implementation Plan — Cake A Wish Web Layer

Single source of truth for phased build-out.
**Do not start a phase until the previous phase is approved.**

---

## Concurrent Implementation & Ownership

Two Claudes are working in parallel. This section defines the split, the
architecture decision, and the exact integration contract so neither blocks
the other.

### Architecture decision — MediaPipe moves to browser, Arduino stays server-side

**Camera conflict:** Python OpenCV + browser `getUserMedia` both need the webcam
and will fight. Solution: MediaPipe detection moves to the browser.

**Blow event flow:**
```
Browser MediaPipe JS  →  POST /blow/event  →  ╮
                                               server fuses → SSE broadcast → all clients
Arduino serial        →  blow_detection/   →  ╯
```

- Browser runs `@mediapipe/tasks-vision` (same model file, same landmark logic as Python)
- On detected blow → `POST /blow/event {source: "mediapipe"}` — tiny, once per blow
- Server receives it, fuses with Arduino events via `BlowEngine`, broadcasts via SSE
- All clients (admin, kiosk) subscribe to SSE → start countdown → call `POST /print`
- `enabled` toggle enforced server-side — server simply doesn't forward if disabled
- Single fusion point means kiosk page gets blow events for free, no logic duplication

**`blow_detection/mediapipe_blow.py` is retired** — replaced by ~30 lines of JS.
`BlowEngine`, Arduino serial reader, `face_landmarker.task` model all stay.

### Ownership split

| Area | Owner |
|------|-------|
| `web.py` — printer API, preview, print, gallery | **Web Claude** |
| `templates/admin.html` — all frontend JS incl. MediaPipe JS | **Web Claude** |
| `blow_detection/engine.py` — BlowEngine fusion | **Other Claude** ✅ done |
| `arduino/` — serial reader + BlowDetector sketch | **Other Claude** ✅ done |
| `POST /blow/event` + `GET /blow/stream` + `POST /blow/settings` | **Other Claude** exposes; Web Claude consumes |

### Integration contract

**Other Claude delivers:**

```
POST /blow/event   { source: "mediapipe", ts: float }
→ { ok: true }
Feeds the browser's MediaPipe detection into BlowEngine.

GET /blow/stream
```
SSE stream. Periodic status (every 1s):
```json
{"arduino": {"connected": true, "level": 38, "threshold": 95},
 "mediapipe": {"active": true},
 "enabled": true, "countdown_s": 3}
```
On blow (from either source):
```json
{"event": "blow", "source": "arduino"|"mediapipe", "ts": 1234567890.0}
```
```
POST /blow/settings   { enabled?, sensitivity?, countdown_s? }
→ { ok: true }
```

**Web Claude delivers:**
- MediaPipe JS running in browser on the existing camera stream
- `POST /blow/event` when MediaPipe detects a blow
- `EventSource('/blow/stream')` → countdown animation → `POST /print`

### What can run fully in parallel

Web Claude completes Phases 2–5 with zero dependency on Other Claude.
Phase 6 is the merge point — needs the three blow endpoints live.

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

## Phase 2.5 — Bluetooth Printer Support ⚠️ Blocked

**What was built:**
- `BTBrotherPrinter` class in `label_printer/printer.py`
  - `query_status()`: opens serial port to confirm BT is live; returns `connected: True/False`
  - `send_instructions()`: prepends `INVALIDATE + INITIALIZE`, writes raster bytes over serial
  - No status/label-detect over BT — uses fallback label (`62red`, 696×1044)
- `web.py` changes:
  - `_printer_bt` state variable; `_make_printer()` selects WiFi vs BT automatically
  - Monitor loop updated: BT mode polls every 2s, skips label detection
  - `GET /printer` now includes `bt_device`, `connection_type: "wifi"|"bt"` fields
  - `PUT /printer {ip?, bt_device?}` — set either or both; bt_device non-empty → BT mode
  - `POST /print` uses `_make_printer()` so it works with both modes
- BT device auto-discovered on macOS at `/dev/cu.QL-820NWB5742`

**To activate BT mode:**
```bash
PRINTER_BT_DEV=/dev/cu.QL-820NWB5742 uvicorn web:app ...
# or at runtime:
curl -X PUT http://localhost:8000/printer -H 'Content-Type: application/json' \
  -d '{"bt_device": "/dev/cu.QL-820NWB5742"}'
```

**Status: blocked on macOS.** CUPS BT backend connects briefly then drops ("Connection Failed"). Raw serial via `/dev/cu.*` opens without error but data never reaches the printer (RFCOMM link doesn't actually establish despite BT showing Connected). Root cause: macOS CUPS BT backend + Brother vendor-specific service `0x902000` don't play well together. **Use WiFi for now.**

**Phase 2.5 UI (deferred to Phase 7 polish):**
- BT/WiFi toggle in Printer settings card
- BT device picker (auto-populated with paired `cu.QL-*` devices from `/dev/`)
- Show `connection_type` badge in status pill

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

**Depends on:** Other Claude's `POST /blow/event`, `GET /blow/stream`, `POST /blow/settings` being live.

**What gets built:**

Frontend (`admin.html` JS):
- Load `@mediapipe/tasks-vision`, serve `face_landmarker.task` as static file
- Run FaceLandmarker in the existing `requestAnimationFrame` loop (same stream as canvas)
- Compute `nw = mouth_w / face_w` (landmarks 61, 291, 33, 263) — same logic as Python
- On blow detected (nw ≤ threshold for N frames, 4s cooldown) → `POST /blow/event {source: "mediapipe"}`
- `EventSource('/blow/stream')` — on `event: blow` → animate countdown overlay → fire ⚡ Quick Print at zero
- Blow to Print toggle → `POST /blow/settings {enabled}`
- Sensitivity slider → `POST /blow/settings {sensitivity}` on change
- Countdown input → `POST /blow/settings {countdown_s}` on change
- SSE status messages → update Arduino pill (connected/level) + MediaPipe pill (active/ratio)

**Goal:** Purse lips toward camera OR blow into Arduino mic → countdown → auto print.

### ✋ Approval gate
> 1. MediaPipe JS running — MediaPipe pill shows "active" in Blow to Print card
> 2. Toggle on → purse lips → browser detects → POST /blow/event → SSE fires → countdown → print
> 3. Toggle on → blow into Arduino mic → SSE fires → same countdown flow
> 4. Toggle off → blowing does nothing
> 5. Arduino pill shows connected/level live from SSE
> 6. Sensitivity slider visibly changes detection threshold in real time

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

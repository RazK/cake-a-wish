# Cake A Wish — Design & Implementation Spec

This document is the single source of truth before any code is written.
Everything here must be validated before implementation begins.

---

## 1. Design Tokens

### Colors
```
--bg-from     #F0EEF8   gradient start
--bg-to       #E8E4F5   gradient end  (body: linear-gradient(150deg, from, to) fixed)

--surface     #FFFFFF   card background
--border      #E2DCF5   card/input border

--primary     #7C6FF7   purple — CTA buttons, active states
--primary-dk  #6258D3   purple pressed / busy state
--ghost       #F2F0FE   light purple tint — secondary backgrounds
--accent      #C9C2F8   medium lavender — borders on focus/hover

--text        #2D2640   near-black (purple tint)
--sub         #8B83A8   secondary text, labels
--muted       #B8B0D0   placeholder, disabled text

--green       #3EBD87   online / success
--red         #E05F7B   offline / error / danger
--amber       #F59E0B   printing / warning
```

### Typography
```
Font:         Poppins (Google Fonts, weights 400/600/700)
Base size:    14px

Page title    700   1.1rem   letter-spacing -0.02em
Section label 700   0.63rem  letter-spacing +0.08em  UPPERCASE  color: --sub
Body text     400   0.85rem
Button text   600   0.87–0.95rem
Pill text     600   0.67rem  letter-spacing +0.04em
Control label 600   0.64rem
Slider value  600   0.62rem
```

### Spacing
```
Page padding:   12px top, 16px sides, 20px bottom
Gap between major rows:  10px
Gap inside sidebar:      8px
Card padding:   12px vertical, 14px horizontal
Control row gap:         6px vertical, 6px horizontal
```

### Elevation & Shape
```
Card:         background white, border 1px --border, radius 14px
              shadow: 0 2px 14px rgba(44,38,64, .09)

Canvas:       no card wrapper — sits on gradient
              shadow: 0 6px 32px rgba(44,38,64, .22)
              border-radius: 8px on canvas element itself

Button-primary: shadow 0 2px 10px rgba(124,111,247, .32)
```

---

## 2. Components

### Printer Status Pill
```
Position: right side of header
Behavior: passive indicator — pointer-events: none, no hover, no click
Size:     auto-width, height ~24px, radius 20px
Layout:   dot (6×6px circle) + text, gap 5px

States:
  .checking   bg --ghost        color --sub    border --border   dot blinks (opacity 1→0.15, 1.2s)
  .online     bg #EDFAF4        color --green  border #B7EFDA    dot solid green
  .offline    bg #FEF0F3        color --red    border #FABFCC    dot solid red
  .printing   bg #FFFBEB        color --amber  border #FDE68A    dot blinks fast (0.6s)
  .error      bg #FEF0F3        color --red    border #FABFCC    dot solid red

Text:
  .checking   "Checking…"
  .online     label id, e.g. "62red"
  .offline    "Offline"
  .printing   "Printing…"
  .error      first error string
```

### Card
```
White surface, 1px border (--border), 14px radius, shadow
Padding: 12px top/bottom, 14px left/right
Card label: uppercase, 0.63rem, 700 weight, --sub color, 8px bottom margin
```

### Template Button  (.tpl-btn)
```
Size:      flex: 1 within a row of 3, roughly 82px wide × 80px tall
Layout:    column — icon area (48×48px) then name label
Border:    2px solid --border, radius 10px
BG:        --ghost

Active:    border-color --primary, box-shadow 0 0 0 3px rgba(124,111,247,.14)
Hover:     border-color --accent
Name text: 0.6rem, 600, --sub; when active: --primary

Icon area (48×48px): shows first letter of template name as large emoji/text
                     for None: shows ⊘ symbol
```

### Segmented Control (.segs + .seg)
```
Wrapper:   flex row, bg --bg-to, border 1px --border, radius 8px, padding 2px
Button:    flex:1, font 0.6rem 600, radius 6px, no border
  default: transparent bg, color --sub
  active:  white bg, color --text, shadow 0 1px 3px rgba(44,38,64,.07)
  hover:   color --text
```

### Buttons
```
All buttons: font-family Poppins, font-weight 600, radius 10px
             hover: brightness(1.07), active: scale(0.97), disabled: opacity 0.35

.btn-primary  bg --primary, color white, font-size 0.95rem, weight 700
              padding 0.65rem 1rem, flex:2 in action bar
              shadow: 0 2px 10px rgba(124,111,247,.32)
              .busy state: bg --primary-dk, cursor wait

.btn-outline  bg white, color --text, border 1.5px --border
              padding 0.65rem 0.9rem, font-size 0.87rem, flex:1 in action bar
              .retake variant: bg --ghost, color --primary, border-color --accent

.btn-icon     40×40px square, bg white, border 1.5px --border, radius 10px
              font-size 1rem, flex-shrink:0
              hover: bg --ghost, color --primary, border-color --accent
              (⚡ 📂 💾 — exactly these three)
```

### Ghost Button (rotate)
```
Small inline button: font 0.65rem 600, padding 3px 10px, radius 7px
bg --ghost, color --primary, border 1px --accent
hover: bg #ddd8ff
```

### Brightness Slider
```
Range input, accent-color --primary
Output value: 0.62rem 600, --sub, right-aligned, fixed width 2rem
```

### Gallery Item
```
Size:      68px wide × 102px tall  (approx 2:3 ratio)
Border:    1.5px --border, radius 7px, overflow hidden
bg:        white (shows while image loads)

Hover:     border-color --primary
           Overlay div fades in: rgba(124,111,247,.75), shows ✏️ centered

Click:     loads raw (pre-frame) image back into canvas for re-editing
```

---

## 3. Layout — /admin Page

### Page structure

3-column holy grail layout, full viewport height, no scroll on the outer shell.

```
[lavender gradient background, full viewport]

┌──────────────────┬───────────────────────────┬──────────────────┐
│  LEFT COLUMN     │  CENTER (canvas)           │  RIGHT COLUMN    │
│  260px fixed     │  flex: 1                   │  260px fixed     │
│  collapsible     │                            │  collapsible     │
│                  │  canvas — centered         │                  │
│  • Printer card  │  aspect ratio from         │  • Template card │
│  • Camera card   │  label_w × label_h         │  • Photos card   │
│  • Arduino card  │                            │                  │
│  • Blow to Print │  action bar (below canvas) │                  │
└──────────────────┴───────────────────────────┴──────────────────┘

Header bar (52px, full width, above the 3 columns):
  Left:   ⚙️ Hardware Settings  (section label, collapses left column)
  Center: 🎂 Cake A Wish  (Handjet font, title)
  Right:  🖼️ Photo Settings  (section label, collapses right column)
```

### Dimensions
```
Left/right columns:  260px fixed, full viewport height, overflow-y: auto
                     padding: 12px 10px
                     display: flex, flex-direction: column, gap: 8px

Center column:       flex: 1, full viewport height
                     display: flex, flex-direction: column
                     align-items: center, justify-content: center
                     padding: 16px

Canvas element:
  max-width:  100%
  max-height: 65vh
  aspect ratio set by JS: canvas.width = label_w, canvas.height = label_h
  Fallback: 696 × 1044 (62red) until API responds

  border-radius: 8px
  box-shadow: 0 6px 32px rgba(44,38,64,.22)
  image-rendering: pixelated
  No card wrapper — sits directly on gradient
```

### Left column contents (top to bottom)
```
Card — Printer:
  Status pill (amber/green/red) with state text
  Detail grid: connection type, IP, label ID, dimensions, model, errors

Card — Camera:
  #cam-preview canvas (4:3) — live MediaPipe feed + landmarks
  Level bar + threshold marker
  "Lip threshold" slider (20–80)

Card — Arduino:
  Level bar + threshold marker
  "Threshold" slider (1–200)

Card — Blow to Print:
  On/Off toggle pill  →  POST /blow/settings
  Combined blow indicator bar with drain animation
```

### Center column contents (top to bottom)
```
Canvas (.label-frame wrapper):
  White border box containing #canvas
  Canvas info text below: "{label_id} · {label_w}×{label_h} px"

Action bar (white card, below canvas):
  [Capture / Retake]  [⚡]  [📂]  [💾]  [Print]
    .btn-outline        icon  icon  icon   .btn-primary
    flex:1             40px  40px  40px   flex:2

  Live mode:      [Capture] + [Quick Print]
  Captured mode:  [Retake]  + [Print]
  Countdown mode: [Cancel]  + [Print now]  + progress bar overlay

Capture button shows "Capture" / "Retake" depending on state
Print and 💾 disabled until captured
⚡ disabled until camera is ready
```

### Right column contents (top to bottom)
```
Card — Template (rc-panel):
  Full overlay slot:    load PNG, no alignment
  Header overlay slot:  load PNG, alignment pill (full/left/center/right)
  Footer overlay slot:  load PNG, alignment pill
  [Save template] button
  Saved templates gallery (2-column grid)

Card — Photos (rc-panel):
  Brightness slider (0–200, value 100)
  [Save photo] button (disabled until captured)
  Photos gallery (2-column grid, newest first)

Status bar (below cards, tiny text):
  Font: 0.7rem, color --muted (default)  .ok → --green  .err → --red
```

---

## 4. Page States

### State A — Live Camera (default)
```
Canvas: shows live video feed, mirrored, with template overlay composited on top
Capture btn: "Capture"  (.btn-outline, no .retake)
Print btn: disabled
💾: disabled
⚡: enabled (camera is ready)
Status bar: empty
```

### State B — Captured
```
Canvas: shows server WYSIWYG preview (dithered PNG from /preview)
  → While waiting for server: shows local canvas render (no blank flash)
  → When server responds: swaps in server preview seamlessly
Capture btn: "Retake"  (.btn-outline.retake — ghost purple)
Print btn: enabled
💾: enabled
Status bar: empty
```

### State C — Printing
```
Print btn: disabled + .busy class (darker purple, cursor:wait)
Status bar: "Sending to printer…"  (--muted color)
Everything else: normal
After success: status bar "Printed!" (.ok, green), gallery reloads
After failure: status bar shows error (.err, red)
```

### State D — Template change in captured mode
```
When user clicks a different template while in captured mode:
  → previewKey is cleared
  → local render updates immediately (shows local compositing + overlay)
  → server preview request fires
  → when server responds, canvas swaps to dithered result
  → NO flash / blank frames at any point
```

### State E — Camera unavailable
```
Canvas: blank (lavender bg shows through, canvas is empty)
Status bar: "Camera unavailable: <reason>"  .err
Capture btn: still shows, but clicking does nothing (no source)
Load btn: still works — user can load from file
```

---

## 5. Interactions

### Template selection
```
1. User clicks template button
2. Active class moves to clicked button
3. If in live mode: fetch overlay PNG, composite on next render tick
4. If in captured mode: clear previewKey → triggers new server preview fetch
5. No re-load of page, no flash
```

### Capture
```
1. Click "Capture"
2. Stop live render loop (clearInterval)
3. createImageBitmap(video) → store as s.capturedBmp
4. s.captured = true
5. Draw local preview immediately (drawSrc + overlay)
6. Fire server preview request in background
7. When server responds: swap canvas to dithered result
```

### Retake
```
1. Click "Retake"
2. s.captured = false, s.capturedBmp = null
3. Increment previewSeq (cancels any in-flight server preview)
4. Restart live render loop (setInterval)
```

### IP change
```
1. User edits printer-ip input, presses Enter / tab
2. PUT /printer { "ip": "..." }
3. Server resets monitor, begins polling new IP
4. Pill switches to .checking
5. Next GET /printer response updates pill state
```

### Gallery re-edit
```
1. User clicks a gallery item
2. Load item.raw (medium-res JPEG, pre-frame) as new capturedBmp
3. Enters captured mode (same as if user had captured from camera)
4. Template / controls from sidebar apply on top
5. Server preview fires automatically
```

---

## 6. API Contract (from frontend perspective)

```
PUT  /printer
     body: { ip: string }
     → { ip: string }
     Use: when user changes IP in settings

GET  /printer
     → { ip, connected, label_id, label_w, label_h, status, phase, errors }
     Use: poll every 2s, update pill + canvas dimensions

GET  /templates
     → [{ id: string, name: string }, ...]
     Use: once on load, build template buttons

GET  /templates/:id/overlay.png?w=W&h=H
     → RGBA PNG
     Use: fetch on template select, composite over live canvas

POST /preview
     body: { image_data: string (data URL), template_id?: string }
     → { image_data: string (data URL, dithered PNG) }
     Use: after capture or settings change

POST /print
     body: { image_data: string (data URL), template_id?: string }
     → { ok: true, thumbnail: string (data URL) }
     Use: on Print button click

GET  /history
     → [{ thumbnail, raw, template_id, label_id }, ...]
     Use: on load and after each print
```

### Notes
- `image_data` is always the RAW transformed image (no frame applied client-side)
  The server applies the template. Client only composites the overlay visually.
- Canvas buffer dimensions = label_w × label_h (from GET /printer)
- Fallback label if none detected: "62red" (696×1044)

---

## 7. Resolved Design Decisions

1. **Gallery hover action**: click loads raw back into canvas (re-edit). Delete button visible on hover.
2. **Template "None" option**: custom overlay slots (full/header/footer) serve as the flexible layer; 3 programmatic templates always available.
3. **Canvas when no camera**: empty canvas (lavender bg shows through). Load button still works.
4. **Settings password field**: omitted — printer IP is sufficient for current deployment.
5. **Action bar as a card**: white card with rounded corners, below the canvas in the center column.
6. **Gallery**: 2-column grid inside the Photos card in the right column (not a full-width strip).

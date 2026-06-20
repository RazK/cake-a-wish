import asyncio
import base64
import io
import json
import os
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel

from blow_detection.router import router as blow_router, startup as blow_startup, shutdown as blow_shutdown
from label_printer.convertor import build_instructions, process_for_preview
from label_printer.frames import REGISTRY
from label_printer.printer import BrotherPrinter, BTBrotherPrinter, USBBrotherPrinter, find_usb_printer

# ── Paths ────────────────────────────────────────────────────────────────────
# When frozen by PyInstaller, CAKE_BASE_DIR points to sys._MEIPASS (bundled assets).
# User-writable data lives next to the executable (CWD is set by launcher.py).
_BASE_DIR = Path(os.environ["CAKE_BASE_DIR"]) if "CAKE_BASE_DIR" in os.environ else Path(__file__).parent

# ── State ────────────────────────────────────────────────────────────────────

_OVERLAY_DIR = Path("data") / "overlays"
_OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
_OVERLAY_PATHS = {
    "header": _OVERLAY_DIR / "header.png",
    "footer": _OVERLAY_DIR / "footer.png",
    "full":   _OVERLAY_DIR / "full.png",
}

_FALLBACK_LABEL = "62"
_FALLBACK_W, _FALLBACK_H = 696, 1044
_DEFAULT_IP = os.getenv("PRINTER_IP", "10.140.224.9")
_DEFAULT_BT = os.getenv("PRINTER_BT_DEV", "")  # e.g. /dev/cu.QL-820NWB5742

_printer_ip: str = _DEFAULT_IP
_printer_bt: str = _DEFAULT_BT  # non-empty → BT mode (legacy)
_active_mode: str = "wifi"      # "wifi" | "usb" — ignored when _printer_bt is set
_usb_device_id: Optional[str] = None  # updated each monitor tick
_printer_state: dict = {
    "ip": _DEFAULT_IP,
    "bt_device": _DEFAULT_BT,
    "connection_type": "bt" if _DEFAULT_BT else "wifi",
    "active_mode": "bt" if _DEFAULT_BT else "wifi",
    "connected": False,
    "label_id": _FALLBACK_LABEL,
    "label_w": _FALLBACK_W,
    "label_h": _FALLBACK_H,
    "status": "checking",
    "phase": None,
    "errors": [],
    "printer_connections": {"wifi": {"available": bool(_DEFAULT_IP), "ip": _DEFAULT_IP},
                             "usb":  {"available": False, "device": None}},
}


def _make_printer():
    """Return the active printer instance based on current connection mode."""
    if _printer_bt:
        return BTBrotherPrinter(_printer_bt)
    if _active_mode == "usb" and _usb_device_id:
        return USBBrotherPrinter(_usb_device_id)
    return BrotherPrinter(_printer_ip)
_DATA_DIR = Path("data")
_PHOTOS_FILE = _DATA_DIR / "photos.json"
_TEMPLATES_FILE = _DATA_DIR / "saved_templates.json"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data))


_photos: list[dict] = _load_json(_PHOTOS_FILE, [])
_saved_templates: list[dict] = _load_json(_TEMPLATES_FILE, [])

# ── Label helpers ─────────────────────────────────────────────────────────────

def _label_dims(label_id: str) -> tuple[int, int]:
    from brother_ql.labels import LabelsManager
    lm = LabelsManager()
    lbl = next((el for el in lm.iter_elements() if el.identifier == label_id), None)
    if lbl is None:
        return _FALLBACK_W, _FALLBACK_H
    w, h = lbl.dots_printable
    return w, (h if h > 0 else _FALLBACK_H)


def _detect_label(status: dict, model: str = "QL-820NWB") -> str:
    """Map printer HTTP status fields → brother_ql label identifier."""
    if not status:
        return _FALLBACK_LABEL
    width = status.get("media_width", 0)   # mm
    length = status.get("media_length", 0) # mm (0 = continuous)
    if not width:
        return _FALLBACK_LABEL
    try:
        from brother_ql.labels import LabelsManager
        lm = LabelsManager()
        for lbl in lm.iter_elements():
            ts = getattr(lbl, "tape_size", None)
            if ts is None:
                continue
            tw, tl = ts
            if length == 0 and tl == 0 and tw == width:
                return lbl.identifier
            if length > 0 and tw == width and tl == length:
                return lbl.identifier
    except Exception:
        pass
    return _FALLBACK_LABEL

# ── Image helpers ─────────────────────────────────────────────────────────────

def _decode_image(data_url: str) -> Image.Image:
    _, _, b64 = data_url.partition(",")
    return Image.open(io.BytesIO(base64.b64decode(b64 or data_url))).convert("RGB")


def _encode_image(img: Image.Image, fmt: str = "PNG", **kw) -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    mime = "image/jpeg" if fmt.upper() in ("JPEG", "JPG") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode()}"


def _decode_overlay(data_url: str) -> Image.Image:
    _, _, b64 = data_url.partition(",")
    return Image.open(io.BytesIO(base64.b64decode(b64 or data_url)))


def _thumbnail(img: Image.Image) -> str:
    t = img.copy()
    t.thumbnail((68, 102), Image.LANCZOS)
    return _encode_image(t, "JPEG", quality=70)


def _apply_frame(img: Image.Image, template_id: Optional[str]) -> Image.Image:
    if template_id and template_id in REGISTRY:
        return REGISTRY[template_id].apply(img)
    return img

def _wifi_reachable(ip: str) -> bool:
    try:
        s = socket.create_connection((ip, 9100), timeout=0.4)
        s.close()
        return True
    except Exception:
        return False


_last_discovery: float = 0.0

async def _discover_wifi_printer() -> Optional[str]:
    """Scan all local /24 subnets concurrently for port 9100. Returns first IP found."""
    import subprocess, re

    async def _probe(host: str) -> Optional[str]:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(host, 9100), timeout=0.3)
            w.close()
            await w.wait_closed()
            return host
        except Exception:
            return None

    try:
        # Collect all local IPv4 addresses from all interfaces
        out = subprocess.check_output(["ifconfig"], text=True, stderr=subprocess.DEVNULL)
        local_ips = [m for m in re.findall(r'inet (\d+\.\d+\.\d+\.\d+)', out)
                     if not m.startswith("127.")]
        if not local_ips:  # fallback: gateway-routed interface
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80)); local_ips = [s.getsockname()[0]]; s.close()

        prefixes = list(dict.fromkeys(ip.rsplit(".", 1)[0] for ip in local_ips))
        hosts = [f"{p}.{i}" for p in prefixes for i in range(1, 255)]
        results = await asyncio.gather(*[_probe(h) for h in hosts])
        return next((r for r in results if r), None)
    except Exception:
        return None

# ── Printer monitor ───────────────────────────────────────────────────────────

async def _monitor_loop():
    global _printer_state, _active_mode, _usb_device_id, _printer_ip, _last_discovery
    _last_label              = _FALLBACK_LABEL
    _last_w, _last_h         = _FALLBACK_W, _FALLBACK_H
    _last_media_w_mm         = 0
    _last_media_h_mm         = 0
    _last_model              = "QL-820NWB"
    while True:
        bt    = _printer_bt
        ip    = _printer_ip
        delay = 1.0

        # ── Probe both connections in parallel ────────────────────
        # Probe USB always; probe WiFi separately only when USB is active
        # (when WiFi is active, query_status() below gives us reachability —
        # probing twice would double-connect to port 9100 and confuse the printer)
        async def _usb_probe():
            return await asyncio.to_thread(find_usb_printer) if not bt else None

        async def _side_wifi_probe():
            if ip and not bt and _active_mode == "usb":
                return await asyncio.to_thread(_wifi_reachable, ip)
            return None  # filled from query_status result below

        usb_id, wifi_ok = await asyncio.gather(_usb_probe(), _side_wifi_probe())
        if not bt:
            _usb_device_id = usb_id
        usb_avail = bool(usb_id)

        printer_connections = {
            "wifi": {"available": bool(ip), "ip": ip,        "reachable": wifi_ok},
            "usb":  {"available": usb_avail, "device": usb_id, "reachable": usb_avail},
        }

        active = "bt" if bt else _active_mode
        try:
            printer   = _make_printer()
            result    = await asyncio.to_thread(printer.query_status)
            connected = result["connected"]
            model     = getattr(printer, "model", "QL-820NWB")

            # ── Sync reachable with actual poll result ─────────────
            if not bt:
                if _active_mode == "wifi":
                    # WiFi reachability comes from the poll, not a separate probe
                    printer_connections["wifi"]["reachable"] = connected
                elif _active_mode == "usb":
                    # Catches race: USB present at probe time but gone by query_status
                    printer_connections["usb"]["reachable"] = connected
                    if not connected:
                        printer_connections["usb"]["available"] = False

            # ── Auto-discovery: find WiFi printer IP when offline ──
            if not bt and _active_mode == "wifi" and not connected:
                if time.time() - _last_discovery > 30 or _last_discovery == 0.0:
                    _last_discovery = time.time()
                    found = await _discover_wifi_printer()
                    if found and found != _printer_ip:
                        _printer_ip = found
                        printer  = _make_printer()
                        result   = await asyncio.to_thread(printer.query_status)
                        connected = result["connected"]
                        printer_connections["wifi"]["ip"]        = found
                        printer_connections["wifi"]["reachable"] = connected

            # ── Auto-failover (post-poll, uses real connectivity) ──
            # `connected` may have been updated by discovery above — check it fresh
            if not bt:
                if _active_mode == "wifi" and not connected and usb_avail:
                    _active_mode = "usb"
                    printer   = _make_printer()
                    result    = await asyncio.to_thread(printer.query_status)
                    connected = result["connected"]
                    printer_connections["usb"]["reachable"] = connected
                elif _active_mode == "usb" and not usb_avail and wifi_ok:
                    _active_mode = "wifi"
                    printer   = _make_printer()
                    result    = await asyncio.to_thread(printer.query_status)
                    connected = result["connected"]
                    printer_connections["wifi"]["reachable"] = connected

            active = "bt" if bt else _active_mode

            if bt or _active_mode == "usb":
                label_id   = _last_label
                w, h       = _last_w, _last_h
                media_w_mm = _last_media_w_mm
                media_h_mm = _last_media_h_mm
                errors, phase = [], None
                pill  = "online" if connected else "offline"
                if not connected:
                    delay = 2.0
            else:
                st         = result.get("status") or {}
                errors     = st.get("errors", [])
                phase      = st.get("phase_type")
                raw_mw     = st.get("media_width",  0)
                raw_mh     = st.get("media_length", 0)
                if raw_mw:
                    label_id         = _detect_label(st, model)
                    w, h             = _label_dims(label_id)
                    _last_label      = label_id
                    _last_w, _last_h = w, h
                    _last_media_w_mm = raw_mw
                    _last_media_h_mm = raw_mh
                    _last_model      = model
                else:
                    label_id = _last_label
                    w, h     = _last_w, _last_h
                media_w_mm = _last_media_w_mm
                media_h_mm = _last_media_h_mm
                model      = _last_model
                if not connected:
                    pill, delay = "offline", 0.3
                elif errors:
                    pill = "error"
                elif phase and "print" in phase.lower():
                    pill = "printing"
                else:
                    pill = "online"

            _printer_state = {
                "ip": _printer_ip, "bt_device": bt,
                "connection_type": active,
                "active_mode": active,
                "model": model,
                "connected": connected,
                "label_id": label_id, "label_w": w, "label_h": h,
                "media_w_mm": media_w_mm, "media_h_mm": media_h_mm,
                "status": pill, "phase": phase, "errors": errors,
                "printer_connections": printer_connections,
            }
        except Exception as exc:
            _printer_state = {
                "ip": _printer_ip, "bt_device": bt,
                "connection_type": active,
                "active_mode": active,
                "model": _last_model,
                "connected": False,
                "label_id": _FALLBACK_LABEL, "label_w": _FALLBACK_W, "label_h": _FALLBACK_H,
                "media_w_mm": 0, "media_h_mm": 0,
                "status": "offline", "phase": None, "errors": [str(exc)],
                "printer_connections": printer_connections,
            }
            delay = 0.3
        await asyncio.sleep(delay)

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_monitor_loop())
    blow_startup()
    yield
    blow_shutdown()
    task.cancel()

app = FastAPI(lifespan=lifespan)
app.include_router(blow_router)
_templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

if (_BASE_DIR / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def admin(request: Request):
    return _templates.TemplateResponse(request, "admin.html")

# ── Printer ───────────────────────────────────────────────────────────────────

@app.get("/printer")
async def get_printer():
    return _printer_state


class PrinterUpdate(BaseModel):
    ip: Optional[str] = None
    bt_device: Optional[str] = None

@app.put("/printer")
async def put_printer(req: PrinterUpdate):
    global _printer_ip, _printer_bt, _printer_state
    if req.bt_device is not None:
        _printer_bt = req.bt_device
    if req.ip is not None:
        _printer_ip = req.ip
    conn = "bt" if _printer_bt else "wifi"
    _printer_state = {
        **_printer_state,
        "ip": _printer_ip, "bt_device": _printer_bt,
        "connection_type": conn,
        "connected": False, "status": "checking",
    }
    return {"ip": _printer_ip, "bt_device": _printer_bt, "connection_type": conn}


class ConnectRequest(BaseModel):
    mode: str  # "wifi" | "usb"

@app.post("/printer/connect")
async def connect_printer(req: ConnectRequest):
    global _active_mode, _printer_state, _last_discovery
    if req.mode not in ("wifi", "usb"):
        raise HTTPException(400, "mode must be 'wifi' or 'usb'")
    _active_mode = req.mode
    if req.mode == "wifi":
        _last_discovery = 0.0  # force immediate discovery on next monitor tick
    # Use already-known reachability for the target mode so the UI doesn't flash "Searching"
    pc = _printer_state.get("printer_connections", {})
    already_connected = pc.get(req.mode, {}).get("reachable") is True
    _printer_state = {**_printer_state,
                      "active_mode": req.mode, "connection_type": req.mode,
                      "connected": already_connected,
                      "status": "online" if already_connected else "checking",
                      "phase": None, "errors": []}
    return {"ok": True, "mode": _active_mode}

# ── Templates ─────────────────────────────────────────────────────────────────

@app.get("/templates")
async def get_templates():
    return [{"id": t.id, "name": t.name} for t in REGISTRY.values()]


@app.get("/templates/{template_id}/overlay.png")
async def get_overlay(template_id: str, w: int = 696, h: int = 1044):
    frame = REGISTRY.get(template_id)
    if frame is None:
        raise HTTPException(404, "Template not found")
    overlay = await asyncio.to_thread(frame.get_overlay, w, h)
    buf = io.BytesIO()
    overlay.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")

# ── Preview ───────────────────────────────────────────────────────────────────

class ImageRequest(BaseModel):
    image_data: str
    template_id: Optional[str] = None


class PrintRequest(BaseModel):
    image_data: str
    template_id: Optional[str] = None
    raw_data: Optional[str] = None  # raw camera frame for photos gallery


class PhotoSave(BaseModel):
    raw_data: str


class TemplateSave(BaseModel):
    name: str
    slots: dict  # {full, header, footer} each None or {align, data_url, original_name}


@app.post("/preview")
async def preview(req: ImageRequest):
    img = _decode_image(req.image_data)
    w, h = _printer_state["label_w"], _printer_state["label_h"]
    img = img.resize((w, h), Image.LANCZOS)
    framed = await asyncio.to_thread(_apply_frame, img, req.template_id)
    result = await asyncio.to_thread(process_for_preview, framed, _printer_state["label_id"])
    return {"image_data": _encode_image(result)}

# ── Print ─────────────────────────────────────────────────────────────────────

@app.post("/print")
async def print_label(req: PrintRequest):
    img = _decode_image(req.image_data)
    w, h = _printer_state["label_w"], _printer_state["label_h"]
    img = img.resize((w, h), Image.LANCZOS)
    framed = await asyncio.to_thread(_apply_frame, img, req.template_id)
    label_id = _printer_state["label_id"]
    try:
        instructions = await asyncio.to_thread(build_instructions, framed.rotate(180), label_id)
        printer = _make_printer()
        await asyncio.to_thread(printer.send_instructions, instructions)
    except Exception as exc:
        raise HTTPException(500, str(exc))

    if req.raw_data:
        raw_img = _decode_image(req.raw_data)
        _photos.insert(0, {"thumbnail": _thumbnail(raw_img), "raw_data": req.raw_data})
        del _photos[20:]
        _save_json(_PHOTOS_FILE, _photos)

    return {"ok": True}

# ── Photos ────────────────────────────────────────────────────────────────────

@app.get("/photos")
async def get_photos():
    return [{"thumbnail": p["thumbnail"], "raw_data": p["raw_data"], "index": i}
            for i, p in enumerate(_photos)]


@app.post("/photos")
async def save_photo(req: PhotoSave):
    img = _decode_image(req.raw_data)
    _photos.insert(0, {"thumbnail": _thumbnail(img), "raw_data": req.raw_data})
    del _photos[20:]
    _save_json(_PHOTOS_FILE, _photos)
    return {"ok": True}


@app.delete("/photos/{index}")
async def delete_photo(index: int):
    if index < 0 or index >= len(_photos):
        raise HTTPException(404, "Not found")
    _photos.pop(index)
    _save_json(_PHOTOS_FILE, _photos)
    return {"ok": True}

# ── Saved templates ───────────────────────────────────────────────────────────

@app.get("/saved-templates")
async def get_saved_templates():
    return [{"name": t["name"], "thumbnail": t["thumbnail"], "index": i}
            for i, t in enumerate(_saved_templates)]


@app.get("/saved-templates/{index}")
async def get_saved_template(index: int):
    if index < 0 or index >= len(_saved_templates):
        raise HTTPException(404, "Not found")
    return _saved_templates[index]


def _template_thumbnail(slots: dict) -> Optional[str]:
    TW, TH = 120, 180
    LABEL_W = 696
    base = Image.new("RGBA", (TW, TH), (45, 40, 65, 255))
    scale = TW / LABEL_W  # ~0.172 — preserve natural overlay proportions
    for slot in ("full", "header", "footer"):
        data = slots.get(slot)
        if not data:
            continue
        try:
            ov = _decode_overlay(data["data_url"]).convert("RGBA")
            align = data.get("align", "full")
            if slot == "full":
                ov_r = ov.resize((TW, TH), Image.LANCZOS)
                base.paste(ov_r, (0, 0), ov_r)
            else:
                if align == "full":
                    # stretch to full thumb width
                    ov_w = TW
                    ov_h = max(1, int(ov.height * TW / ov.width))
                    x = 0
                else:
                    # scale by label ratio so partial overlays look partial
                    ov_w = max(1, int(ov.width * scale))
                    ov_h = max(1, int(ov.height * scale))
                    x = {"left": 0, "right": TW - ov_w, "center": (TW - ov_w) // 2}.get(align, 0)
                ov_r = ov.resize((ov_w, ov_h), Image.LANCZOS)
                y = 0 if slot == "header" else TH - ov_h
                base.paste(ov_r, (x, y), ov_r)
        except Exception:
            pass
    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


@app.post("/saved-templates")
async def save_template(req: TemplateSave):
    processed = {}
    for slot, data in req.slots.items():
        if not data:
            processed[slot] = None
            continue
        try:
            img = _decode_overlay(data["data_url"])
            img.thumbnail((350, 525), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            processed[slot] = {**data, "data_url": "data:image/png;base64," + b64}
        except Exception:
            processed[slot] = data
    thumb = await asyncio.to_thread(_template_thumbnail, processed)
    _saved_templates.insert(0, {"name": req.name, "thumbnail": thumb, "slots": processed})
    del _saved_templates[20:]
    _save_json(_TEMPLATES_FILE, _saved_templates)
    return {"ok": True}


@app.delete("/saved-templates/{index}")
async def delete_saved_template(index: int):
    if index < 0 or index >= len(_saved_templates):
        raise HTTPException(404, "Not found")
    _saved_templates.pop(index)
    _save_json(_TEMPLATES_FILE, _saved_templates)
    return {"ok": True}

# ── Custom overlays (header / footer / full) ──────────────────────────────────

@app.post("/overlay/{slot}")
async def upload_overlay(slot: str, file: UploadFile = File(...)):
    if slot not in _OVERLAY_PATHS:
        raise HTTPException(400, "Invalid slot — use header, footer, or full")
    data = await file.read()
    _OVERLAY_PATHS[slot].write_bytes(data)
    return {"ok": True}


@app.get("/overlay/{slot}")
async def get_overlay_file(slot: str):
    if slot not in _OVERLAY_PATHS:
        raise HTTPException(400, "Invalid slot")
    path = _OVERLAY_PATHS[slot]
    if not path.exists():
        raise HTTPException(404, "No overlay for this slot")
    return Response(content=path.read_bytes(), media_type="image/png")


@app.delete("/overlay/{slot}")
async def delete_overlay_file(slot: str):
    if slot not in _OVERLAY_PATHS:
        raise HTTPException(400, "Invalid slot")
    _OVERLAY_PATHS[slot].unlink(missing_ok=True)
    return {"ok": True}

# ── Dev entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

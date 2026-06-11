import asyncio
import base64
import io
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel

import blow_router
from label_printer.convertor import build_instructions, process_for_preview
from label_printer.frames import REGISTRY
from label_printer.printer import BrotherPrinter, BTBrotherPrinter

# ── State ────────────────────────────────────────────────────────────────────

_FALLBACK_LABEL = "62red"
_FALLBACK_W, _FALLBACK_H = 696, 1044
_DEFAULT_IP = os.getenv("PRINTER_IP", "10.140.224.9")
_DEFAULT_BT = os.getenv("PRINTER_BT_DEV", "")  # e.g. /dev/cu.QL-820NWB5742

_printer_ip: str = _DEFAULT_IP
_printer_bt: str = _DEFAULT_BT  # non-empty → BT mode
_printer_state: dict = {
    "ip": _DEFAULT_IP,
    "bt_device": _DEFAULT_BT,
    "connection_type": "bt" if _DEFAULT_BT else "wifi",
    "connected": False,
    "label_id": _FALLBACK_LABEL,
    "label_w": _FALLBACK_W,
    "label_h": _FALLBACK_H,
    "status": "checking",
    "phase": None,
    "errors": [],
}


def _make_printer():
    """Return the active printer instance based on current connection mode."""
    if _printer_bt:
        return BTBrotherPrinter(_printer_bt)
    return BrotherPrinter(_printer_ip)
_history: list[dict] = []

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
    # QL-820NWB + 62mm continuous tape → 62red (two-colour)
    if "820" in model and width == 62 and length == 0:
        return "62red"
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


def _thumbnail(img: Image.Image) -> str:
    t = img.copy()
    t.thumbnail((68, 102), Image.LANCZOS)
    return _encode_image(t, "JPEG", quality=70)


def _apply_frame(img: Image.Image, template_id: Optional[str]) -> Image.Image:
    if template_id and template_id in REGISTRY:
        return REGISTRY[template_id].apply(img)
    return img

# ── Printer monitor ───────────────────────────────────────────────────────────

async def _monitor_loop():
    global _printer_state
    while True:
        bt = _printer_bt
        ip = _printer_ip
        delay = 1.0
        try:
            printer = _make_printer()
            result = await asyncio.to_thread(printer.query_status)
            connected = result["connected"]

            if bt:
                # BT: no status info available — use fallback label
                label_id, w, h = _FALLBACK_LABEL, _FALLBACK_W, _FALLBACK_H
                errors, phase = [], None
                pill = "online" if connected else "offline"
                if not connected:
                    delay = 2.0
            else:
                st = result.get("status") or {}
                label_id = _detect_label(st, printer.model)
                w, h = _label_dims(label_id)
                errors = st.get("errors", [])
                phase = st.get("phase_type")
                if not connected:
                    pill, delay = "offline", 0.3
                elif errors:
                    pill = "error"
                elif phase and "print" in phase.lower():
                    pill = "printing"
                else:
                    pill = "online"

            _printer_state = {
                "ip": ip, "bt_device": bt,
                "connection_type": "bt" if bt else "wifi",
                "connected": connected,
                "label_id": label_id, "label_w": w, "label_h": h,
                "status": pill, "phase": phase, "errors": errors,
            }
        except Exception as exc:
            _printer_state = {
                "ip": ip, "bt_device": bt,
                "connection_type": "bt" if bt else "wifi",
                "connected": False,
                "label_id": _FALLBACK_LABEL, "label_w": _FALLBACK_W, "label_h": _FALLBACK_H,
                "status": "offline", "phase": None, "errors": [str(exc)],
            }
            delay = 0.3
        await asyncio.sleep(delay)

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_monitor_loop())
    blow_router.startup()
    yield
    blow_router.shutdown()
    task.cancel()

app = FastAPI(lifespan=lifespan)
app.include_router(blow_router.router)
_templates = Jinja2Templates(directory="templates")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
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
async def print_label(req: ImageRequest):
    img = _decode_image(req.image_data)
    w, h = _printer_state["label_w"], _printer_state["label_h"]
    img = img.resize((w, h), Image.LANCZOS)
    framed = await asyncio.to_thread(_apply_frame, img, req.template_id)
    label_id = _printer_state["label_id"]
    try:
        instructions = await asyncio.to_thread(build_instructions, framed, label_id)
        printer = _make_printer()
        await asyncio.to_thread(printer.send_instructions, instructions)
    except Exception as exc:
        raise HTTPException(500, str(exc))

    thumb = _thumbnail(img)
    _history.insert(0, {
        "thumbnail": thumb,
        "raw": req.image_data,
        "template_id": req.template_id or "",
        "label_id": label_id,
    })
    del _history[8:]
    return {"ok": True, "thumbnail": thumb}

# ── History ───────────────────────────────────────────────────────────────────

@app.get("/history")
async def get_history():
    return _history

# ── Dev entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web:app", host="0.0.0.0", port=8000, reload=True)

import asyncio
import base64
import io
import json
import logging
import os
import traceback
from contextlib import asynccontextmanager

logger = logging.getLogger("main")
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from pydantic import BaseModel

import events as sse
from blow_detection.router import router as blow_router, startup as blow_startup, shutdown as blow_shutdown
from label_printer.convertor import build_instructions, process_for_preview
from label_printer.frames import REGISTRY
from label_printer.manager import PrinterManager

# ── Printer ───────────────────────────────────────────────────────────────────

_DEFAULT_IP     = os.getenv("PRINTER_IP", "10.140.224.9")
_printer_manager = PrinterManager(wifi_ip=_DEFAULT_IP)

# ── Overlay dirs ──────────────────────────────────────────────────────────────

_OVERLAY_DIR = Path("data") / "overlays"
_OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
_OVERLAY_PATHS = {
    "header": _OVERLAY_DIR / "header.png",
    "footer": _OVERLAY_DIR / "footer.png",
    "full":   _OVERLAY_DIR / "full.png",
}

# ── Persistence helpers ───────────────────────────────────────────────────────

_DATA_DIR      = Path("data")
_PHOTOS_FILE   = _DATA_DIR / "photos.json"
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

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_printer_manager.run())
    blow_startup()
    yield
    blow_shutdown()
    task.cancel()

app = FastAPI(lifespan=lifespan)
app.include_router(sse.router)
app.include_router(blow_router)
_templates = Jinja2Templates(directory="templates")

if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def admin(request: Request):
    return _templates.TemplateResponse(request, "admin.html")

# ── Printer ───────────────────────────────────────────────────────────────────

class PrinterUpdate(BaseModel):
    ip: Optional[str] = None


@app.put("/printer")
async def put_printer(req: PrinterUpdate):
    if req.ip:
        _printer_manager.set_wifi_ip(req.ip)
    return {"ok": True}


class ConnectRequest(BaseModel):
    mode: str  # "wifi" | "usb"


@app.post("/printer/connect")
async def connect_printer(req: ConnectRequest):
    if req.mode not in ("wifi", "usb"):
        raise HTTPException(400, "mode must be 'wifi' or 'usb'")
    _printer_manager.set_active(req.mode)
    return {"ok": True, "mode": req.mode}

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
    img      = _decode_image(req.image_data)
    state    = _printer_manager.get_state()
    w, h     = state["label_w"], state["label_h"]
    img      = img.resize((w, h), Image.LANCZOS)
    framed   = await asyncio.to_thread(_apply_frame, img, req.template_id)
    result   = await asyncio.to_thread(process_for_preview, framed, state["label_id"])
    return {"image_data": _encode_image(result)}

# ── Print ─────────────────────────────────────────────────────────────────────

class PrintRequest(BaseModel):
    image_data: str
    template_id: Optional[str] = None
    raw_data: Optional[str] = None


@app.post("/print")
async def print_label(req: PrintRequest):
    img      = _decode_image(req.image_data)
    state    = _printer_manager.get_state()
    w, h     = state["label_w"], state["label_h"]
    label_id = state["label_id"]
    img      = img.resize((w, h), Image.LANCZOS)
    framed   = await asyncio.to_thread(_apply_frame, img, req.template_id)
    try:
        instructions = await asyncio.to_thread(build_instructions, framed.rotate(180), label_id)
        await asyncio.to_thread(_printer_manager.send_job, instructions)
    except Exception as exc:
        logger.error("Print failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(503, str(exc))

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


class PhotoSave(BaseModel):
    raw_data: str


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


def _template_thumbnail(slots: dict, margin_left: int = 0, margin_right: int = 0) -> Optional[str]:
    TW, TH = 120, 180
    LABEL_W = 696
    base = Image.new("RGBA", (TW, TH), (45, 40, 65, 255))
    scale = TW / LABEL_W
    for slot in ("full", "header", "footer"):
        data = slots.get(slot)
        if not data:
            continue
        try:
            ov    = _decode_overlay(data["data_url"]).convert("RGBA")
            align = data.get("align", "full")
            if slot == "full":
                ov_r = ov.resize((TW, TH), Image.LANCZOS)
                base.paste(ov_r, (0, 0), ov_r)
            else:
                if align == "full":
                    ov_w = TW
                    ov_h = max(1, int(ov.height * TW / ov.width))
                    x    = 0
                else:
                    ov_w = max(1, int(ov.width * scale))
                    ov_h = max(1, int(ov.height * scale))
                    x    = {"left": 0, "right": TW - ov_w, "center": (TW - ov_w) // 2}.get(align, 0)
                ov_r = ov.resize((ov_w, ov_h), Image.LANCZOS)
                y    = 0 if slot == "header" else TH - ov_h
                base.paste(ov_r, (x, y), ov_r)
        except Exception:
            pass
    if margin_left:
        ml_px = max(1, round(margin_left * scale))
        base.paste(Image.new("RGBA", (ml_px, TH), (255, 255, 255, 200)), (0, 0))
    if margin_right:
        mr_px = max(1, round(margin_right * scale))
        base.paste(Image.new("RGBA", (mr_px, TH), (255, 255, 255, 200)), (TW - mr_px, 0))
    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


class TemplateSave(BaseModel):
    name: str
    slots: dict
    margin_left: int  = 0
    margin_right: int = 0


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
    thumb = await asyncio.to_thread(_template_thumbnail, processed, req.margin_left, req.margin_right)
    _saved_templates.insert(0, {
        "name": req.name, "thumbnail": thumb, "slots": processed,
        "margin_left": req.margin_left, "margin_right": req.margin_right,
    })
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

# ── Custom overlays ───────────────────────────────────────────────────────────

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

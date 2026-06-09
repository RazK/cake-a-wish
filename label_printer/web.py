from __future__ import annotations

import asyncio
import base64
import io
import re
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel
from PIL import Image

from .convertor import build_instructions, process_for_preview
from .printer import BrotherPrinter
from .frames import get_frame, REGISTRY as _frame_registry
from brother_ql.devicedependent import label_type_specs
from brother_ql.labels import LabelsManager

ROOT          = Path(__file__).resolve().parent
STATIC_DIR    = ROOT / "static"
TEMPLATES_DIR = ROOT / "templates"
DEFAULT_IP    = "192.168.1.139"

STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

IMAGE_DATA_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$")

# ── Label detection ──────────────────────────────────────────────────────────
_lm = LabelsManager()


def _match_label(media_type: str, media_width: int, media_length: int,
                 model: str = "QL-820NWB") -> Optional[str]:
    if not media_type or "No media" in media_type:
        return None
    is_endless = "Continuous" in media_type
    if is_endless and media_width == 62 and any(s in model for s in ("QL-800", "QL-810W", "QL-820NWB")):
        return "62red"
    for el in _lm.iter_elements():
        w, h = el.tape_size
        if w != media_width:
            continue
        if is_endless and h == 0:
            return el.identifier
        if not is_endless and h == media_length:
            return el.identifier
    return None


def _label_dims(label_id: str) -> tuple[int, int]:
    spec = label_type_specs.get(label_id, {})
    dp = spec.get("dots_printable")
    return (dp[0], dp[1]) if dp else (696, 1044)


# ── Printer monitor ──────────────────────────────────────────────────────────
_mon: dict = {
    "ip":        DEFAULT_IP,
    "connected": False,
    "ps":        None,
    "label_id":  None,
}


async def _monitor_loop() -> None:
    while True:
        ip = _mon["ip"]
        if ip:
            result = await asyncio.to_thread(BrotherPrinter(ip).query_status)
            _mon["connected"] = result["connected"]
            ps = result.get("status")
            _mon["ps"] = ps
            _mon["label_id"] = _match_label(
                ps.get("media_type", "")  if ps else "",
                ps.get("media_width", 0)  if ps else 0,
                ps.get("media_length", 0) if ps else 0,
            ) if ps else None
        await asyncio.sleep(0.3 if not _mon["connected"] else 1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_monitor_loop())
    yield
    task.cancel()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Cake-A-Wish", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

# ── History ───────────────────────────────────────────────────────────────────
_history: deque[dict] = deque(maxlen=8)


# ── Request models ────────────────────────────────────────────────────────────
class SetPrinterReq(BaseModel):
    ip: str


class PreviewReq(BaseModel):
    image_data:  str
    template_id: Optional[str] = None


class PrintReq(BaseModel):
    image_data:  str
    template_id: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────
def _decode_image(image_data: str) -> Image.Image:
    m = IMAGE_DATA_RE.match(image_data)
    if not m:
        raise HTTPException(status_code=400, detail="Invalid image_data")
    return Image.open(io.BytesIO(base64.b64decode(m.group(1)))).convert("RGB")


def _apply_template(image: Image.Image, template_id: Optional[str]) -> Image.Image:
    if not template_id:
        return image
    tpl = get_frame(template_id)
    if tpl is None:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template_id}")
    return tpl.apply(image)


def _thumb(image: Image.Image) -> str:
    img = image.copy()
    img.thumbnail((120, 480), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _medium(image: Image.Image) -> str:
    w, h = image.size
    img  = image.resize((400, int(h * 400 / w)), Image.LANCZOS) if w > 400 else image.copy()
    buf  = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _printer_state() -> dict:
    ps       = _mon.get("ps") or {}
    label_id = _mon.get("label_id")
    w, h     = _label_dims(label_id) if label_id else (696, 1044)
    return {
        "ip":        _mon["ip"],
        "connected": _mon["connected"],
        "label_id":  label_id,
        "label_w":   w,
        "label_h":   h,
        "status":    ps.get("status_type"),
        "phase":     ps.get("phase_type"),
        "errors":    ps.get("errors", []),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.put("/printer")
def set_printer(req: SetPrinterReq) -> JSONResponse:
    _mon["ip"]        = req.ip.strip()
    _mon["connected"] = False
    _mon["ps"]        = None
    _mon["label_id"]  = None
    return JSONResponse(content={"ip": _mon["ip"]})


@app.get("/printer")
def get_printer() -> JSONResponse:
    return JSONResponse(content=_printer_state())


@app.get("/templates")
def get_templates() -> JSONResponse:
    return JSONResponse(content=[
        {"id": t.id, "name": t.name} for t in _frame_registry.values()
    ])


@app.get("/templates/{template_id}/overlay.png")
def template_overlay(template_id: str, w: int = 400, h: int = 600) -> Response:
    tpl = get_frame(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Unknown template: {template_id}")
    overlay = tpl.get_overlay(w, h)
    buf = io.BytesIO()
    overlay.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@app.post("/preview")
async def preview(req: PreviewReq) -> JSONResponse:
    image   = _decode_image(req.image_data)
    framed  = _apply_template(image, req.template_id)
    label   = _mon.get("label_id") or "62red"
    lw, lh  = _label_dims(label)
    if framed.size != (lw, lh):
        framed = framed.resize((lw, lh), Image.LANCZOS)
    result  = await asyncio.to_thread(process_for_preview, framed, label)
    buf     = io.BytesIO()
    result.save(buf, format="PNG")
    return JSONResponse(content={
        "image_data": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    })


@app.post("/print")
def print_label(req: PrintReq) -> JSONResponse:
    if not _mon["ip"]:
        raise HTTPException(status_code=503, detail="No printer configured")
    if not _mon["connected"]:
        raise HTTPException(status_code=503, detail="Printer offline")
    label = _mon.get("label_id")
    if not label:
        raise HTTPException(status_code=503, detail="No label detected")

    image  = _decode_image(req.image_data)
    framed = _apply_template(image, req.template_id)
    lw, lh = _label_dims(label)
    if framed.size != (lw, lh):
        framed = framed.resize((lw, lh), Image.LANCZOS)

    try:
        instructions = build_instructions(framed, label)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Conversion failed: {exc}")

    try:
        result = BrotherPrinter(_mon["ip"]).send_instructions(instructions)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not result.get("instructions_sent"):
        raise HTTPException(status_code=502, detail="Printer did not accept job")

    entry = {
        "thumbnail":   _thumb(framed),
        "raw":         _medium(image),
        "template_id": req.template_id,
        "label_id":    label,
    }
    _history.appendleft(entry)
    return JSONResponse(content={"ok": True, "thumbnail": entry["thumbnail"]})


@app.get("/history")
def history() -> JSONResponse:
    return JSONResponse(content=list(_history))


@app.get("/admin", response_class=HTMLResponse)
def admin() -> HTMLResponse:
    return HTMLResponse(content=jinja.get_template("admin.html").render(default_ip=_mon["ip"]))


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content='<meta http-equiv="refresh" content="0;url=/admin">')

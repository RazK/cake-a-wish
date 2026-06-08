from __future__ import annotations

import asyncio
import base64
import io
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel
from PIL import Image

from .convertor import build_instructions, process_for_preview
from .printer import BrotherPrinter
from .frames import get_frame
from brother_ql.devicedependent import label_type_specs
from brother_ql.labels import LabelsManager

ROOT          = Path(__file__).resolve().parent
STATIC_DIR    = ROOT / "static"
TEMPLATES_DIR = ROOT / "templates"

IMAGE_DATA_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$")

# ── Label matching ──────────────────────────────────────────────────────────
_lm = LabelsManager()

def match_label(
    media_type: str,
    media_width: int,
    media_length: int,
    model: str = "QL-820NWB",
) -> Optional[str]:
    """Return the best-matching label identifier for the loaded media, or None."""
    if not media_type or "No media" in media_type:
        return None
    is_endless = "Continuous" in media_type
    # Two-color capable models: 62mm endless → 62red (black+red tape)
    if is_endless and media_width == 62 and any(m in model for m in ("QL-800", "QL-810W", "QL-820NWB")):
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


# ── Background printer monitor ──────────────────────────────────────────────
_monitor: dict = {"ip": None, "connected": False, "printer_status": None, "label": None}


async def _printer_monitor_loop() -> None:
    """Query printer status via ESC i S every second and cache the result."""
    while True:
        ip = _monitor["ip"]
        if ip:
            result = await asyncio.to_thread(BrotherPrinter(ip).query_status)
            _monitor["connected"] = result["connected"]
            ps = result["status"]
            _monitor["printer_status"] = ps
            _monitor["label"] = match_label(
                ps.get("media_type", "") if ps else "",
                ps.get("media_width", 0) if ps else 0,
                ps.get("media_length", 0) if ps else 0,
            ) if ps else None
        # Poll faster when offline so reconnection is caught within ~1s
        await asyncio.sleep(0.3 if not _monitor["connected"] else 1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_printer_monitor_loop())
    yield
    task.cancel()


app = FastAPI(title="Cake-A-Wish Camera Print", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


class PreviewRequest(BaseModel):
    image_data: str
    label:      str = "29x90"
    frame_id:   Optional[str] = None


class PrintRequest(BaseModel):
    image_data: str
    printer_ip: str
    label:      str = "29x90"
    password:   Optional[str] = None
    frame_id:   Optional[str] = None


def _apply_frame(image: Image.Image, frame_id: Optional[str]) -> Image.Image:
    if not frame_id:
        return image
    frame = get_frame(frame_id)
    if frame is None:
        raise HTTPException(status_code=400, detail=f"Unknown frame: {frame_id}")
    return frame.apply(image)


def decode_image(image_data: str) -> Image.Image:
    match = IMAGE_DATA_RE.match(image_data)
    if not match:
        raise ValueError("Unsupported image data format")
    return Image.open(io.BytesIO(base64.b64decode(match.group(1)))).convert("RGB")


@app.get("/frames")
def get_frames() -> JSONResponse:
    from .frames import REGISTRY
    return JSONResponse(content=[
        {"id": t.id, "name": t.name} for t in REGISTRY.values()
    ])


@app.get("/labels")
def get_labels() -> JSONResponse:
    result = [
        {"id": lid, "width": spec["dots_printable"][0], "height": spec["dots_printable"][1]}
        for lid, spec in label_type_specs.items()
        if spec.get("dots_printable")
    ]
    return JSONResponse(content=sorted(result, key=lambda x: x["id"]))


@app.get("/printer/status")
async def printer_status(printer_ip: str, password: Optional[str] = None) -> JSONResponse:
    if not printer_ip:
        return JSONResponse(content={"connected": False, "errors": []})

    # Register new IP — monitor picks it up on next cycle
    if _monitor["ip"] != printer_ip:
        _monitor["ip"] = printer_ip
        _monitor["connected"] = False
        _monitor["printer_status"] = None
        _monitor["label"] = None

    ps = _monitor.get("printer_status") or {}
    return JSONResponse(content={
        "connected":    _monitor["connected"],
        "status_type":  ps.get("status_type"),
        "phase_type":   ps.get("phase_type"),
        "media_type":   ps.get("media_type"),
        "media_width":  ps.get("media_width"),
        "media_length": ps.get("media_length"),
        "errors":       ps.get("errors", []),
        "label":        _monitor.get("label"),
    })


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    template = jinja_env.get_template("index.html")
    return HTMLResponse(content=template.render(default_printer_ip="192.168.1.139"))


@app.post("/preview")
async def preview_image(req: PreviewRequest) -> JSONResponse:
    """Run the same dithering as /print and return the result as a PNG for WYSIWYG preview."""
    try:
        image = decode_image(req.image_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if req.label not in label_type_specs:
        raise HTTPException(status_code=400, detail=f"Unknown label: {req.label}")
    image = _apply_frame(image, req.frame_id)
    processed = await asyncio.to_thread(process_for_preview, image, req.label)
    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return JSONResponse(content={"image_data": f"data:image/png;base64,{b64}"})


def _execute_print(
    image: Image.Image, label: str, printer_ip: str,
    frame_id: Optional[str] = None,
) -> JSONResponse:
    if label not in label_type_specs:
        raise HTTPException(status_code=400, detail=f"Unknown label: {label}")
    image = _apply_frame(image, frame_id)
    try:
        instructions = build_instructions(image, label)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Image conversion failed: {exc}")
    try:
        result = BrotherPrinter(printer_ip).send_instructions(instructions)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not result.get("instructions_sent", False):
        raise HTTPException(status_code=502, detail="Failed to deliver instructions to printer")
    return JSONResponse(content=result)


@app.post("/print")
def print_image(req: PrintRequest) -> JSONResponse:
    try:
        image = decode_image(req.image_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _execute_print(image, req.label, req.printer_ip, req.frame_id)


class AutoPrintRequest(BaseModel):
    image_data: str
    frame_id:   Optional[str] = None


@app.post("/print/auto")
def print_auto(req: AutoPrintRequest) -> JSONResponse:
    if not _monitor["ip"]:
        raise HTTPException(status_code=503, detail="No printer configured")
    if not _monitor["connected"]:
        raise HTTPException(status_code=503, detail="Printer offline")
    if not _monitor["label"]:
        raise HTTPException(status_code=503, detail="No recognized label loaded")
    try:
        image = decode_image(req.image_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _execute_print(image, _monitor["label"], _monitor["ip"], req.frame_id)

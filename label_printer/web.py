from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Literal, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel
from PIL import Image

from .convertor import build_instructions
from .printer import BrotherPrinter
from brother_ql.devicedependent import label_type_specs

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
TEMPLATES_DIR = ROOT / "templates"

app = FastAPI(title="Cake-A-Wish Camera Print")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

IMAGE_DATA_RE = re.compile(r"^data:image/[^;]+;base64,(.+)$")


class PrintImageRequest(BaseModel):
    image_data: str
    printer_ip: str
    label: str = "29x90"
    password: Optional[str] = None
    rotate: bool = True
    preview: bool = False
    bw_mode: Literal["dither", "atkinson", "threshold"] = "dither"
    fit_mode: Literal["contain", "cover", "stretch"] = "contain"


def decode_image(image_data: str) -> Image.Image:
    match = IMAGE_DATA_RE.match(image_data)
    if not match:
        raise ValueError("Unsupported image data format")
    raw = base64.b64decode(match.group(1))
    return Image.open(io.BytesIO(raw)).convert("RGB")


def label_pixel_dimensions(label_id: str) -> tuple[int, int]:
    specs = label_type_specs.get(label_id)
    if specs:
        dots = specs.get("dots_printable")
        if dots:
            return dots[0], dots[1]
    return 696, 200


def prepare_image_for_label(image: Image.Image, label_id: str, rotate: bool, fit_mode: str) -> Image.Image:
    width, height = label_pixel_dimensions(label_id)
    if rotate:
        width, height = height, width

    if fit_mode == "stretch":
        return image.resize((width, height), Image.LANCZOS)

    if fit_mode == "cover":
        img_ratio = image.width / image.height
        label_ratio = width / height
        if img_ratio > label_ratio:
            new_h = height
            new_w = int(new_h * img_ratio)
        else:
            new_w = width
            new_h = int(new_w / img_ratio)
        resized = image.resize((new_w, new_h), Image.LANCZOS)
        x = (new_w - width) // 2
        y = (new_h - height) // 2
        return resized.crop((x, y, x + width, y + height))

    # contain: letterbox
    canvas = Image.new("RGB", (width, height), "white")
    image.thumbnail((width, height), Image.LANCZOS)
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def to_bw(image: Image.Image, mode: str) -> Image.Image:
    gray = image.convert("L")

    if mode == "dither":
        return gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")

    if mode == "threshold":
        threshold = int(255 * 0.5)
        return gray.point(lambda p: 255 if p > threshold else 0, mode="L")

    # atkinson — distributes 1/8 of error to 6 neighbours, high contrast
    px = np.array(gray, dtype=np.float32)
    h, w = px.shape
    for y in range(h):
        for x in range(w):
            old = px[y, x]
            new = 255.0 if old >= 128 else 0.0
            px[y, x] = new
            err = (old - new) / 8.0
            for dy, dx in [(0,1),(0,2),(1,-1),(1,0),(1,1),(2,0)]:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w:
                    px[ny, nx] += err
    return Image.fromarray(np.clip(px, 0, 255).astype(np.uint8), mode="L")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    template = jinja_env.get_template("index.html")
    html = template.render(
        default_printer_ip="192.168.1.139",
        default_label_id="29x90",
    )
    return HTMLResponse(content=html)


@app.post("/print")
def print_image(request: PrintImageRequest) -> JSONResponse:
    try:
        image = decode_image(request.image_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if request.label not in label_type_specs:
        raise HTTPException(status_code=400, detail=f"Unknown label id: {request.label}")

    prepared = prepare_image_for_label(image, request.label, request.rotate, request.fit_mode)

    if request.preview:
        out = to_bw(prepared, request.bw_mode)
        buffer = io.BytesIO()
        out.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return JSONResponse(content={"preview_image": f"data:image/png;base64,{encoded}"})

    instructions = build_instructions(prepared, request.label)
    printer = BrotherPrinter(request.printer_ip, password=request.password)
    response = printer.send_instructions(instructions)
    return JSONResponse(content=response)

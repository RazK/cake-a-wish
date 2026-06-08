from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def _default_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


class FrameTemplate:
    """
    Base class for photo frame templates.

    Subclass this for programmatic (stub) templates.

    For designer-supplied templates: drop overlay.png + optional background.png
    + config.json in a folder under label_printer/frames/, then instantiate
    AssetFrameTemplate pointing at that folder — no subclass needed.
    """

    id:   str = ""
    name: str = ""

    def apply(self, photo: Image.Image) -> Image.Image:
        """
        Composite the frame onto photo.
        photo is RGB at label canvas dimensions.
        Returns RGB image at the same dimensions.
        """
        raise NotImplementedError


class AssetFrameTemplate(FrameTemplate):
    """
    Loads overlay.png / background.png / config.json from a folder.
    This is the path designer-supplied templates take — no code changes needed.
    """

    def __init__(self, folder: Path) -> None:
        cfg = json.loads((folder / "config.json").read_text())
        self.id   = cfg["id"]
        self.name = cfg["name"]
        self._photo_rect    = cfg["photo_rect"]          # [left, top, right, bottom] as fractions
        self._branding_text = cfg.get("branding_text", "")
        self._branding_pos  = cfg.get("branding_pos",  [0.5, 0.93])
        self._branding_size = cfg.get("branding_size", 0.04)

        bg_path  = folder / "background.png"
        ov_path  = folder / "overlay.png"
        self._background = Image.open(bg_path).convert("RGBA") if bg_path.exists() else None
        self._overlay    = Image.open(ov_path).convert("RGBA") if ov_path.exists() else None

    def apply(self, photo: Image.Image) -> Image.Image:
        w, h = photo.size
        canvas = Image.new("RGBA", (w, h), (255, 255, 255, 255))

        if self._background:
            canvas.paste(self._background.resize((w, h), Image.LANCZOS), (0, 0))

        # Fit photo into photo_rect
        l, t, r, b = [int(v * dim) for v, dim in zip(
            self._photo_rect,
            [w, h, w, h],
        )]
        pw, ph = r - l, b - t
        photo_fit = photo.convert("RGBA").resize((pw, ph), Image.LANCZOS)
        canvas.paste(photo_fit, (l, t))

        if self._overlay:
            canvas.alpha_composite(self._overlay.resize((w, h), Image.LANCZOS))

        if self._branding_text:
            draw = ImageDraw.Draw(canvas)
            font_size = max(10, int(h * self._branding_size))
            font = _default_font(font_size)
            tx = int(w * self._branding_pos[0])
            ty = int(h * self._branding_pos[1])
            draw.text((tx, ty), self._branding_text, fill=(80, 60, 200, 255),
                      font=font, anchor="mm")

        return canvas.convert("RGB")

from PIL import Image, ImageDraw, ImageFilter
from ._base import FrameTemplate, _default_font


class RetroFrame(FrameTemplate):
    """
    Retro high-contrast: sepia-tinted photo, thick white border, stamp-style text.
    Designer replaces this with overlay.png + config.json.
    """
    id   = "retro"
    name = "Retro"

    def apply(self, photo: Image.Image) -> Image.Image:
        w, h   = photo.size
        border = max(10, int(w * 0.05))
        strip  = max(30, int(h * 0.11))
        inner_w = w - border * 2
        inner_h = h - border * 2 - strip

        # Sepia tone
        gray   = photo.convert("L")
        sepia  = Image.merge("RGB", [
            gray.point(lambda x: min(255, int(x * 1.10))),
            gray.point(lambda x: min(255, int(x * 0.85))),
            gray.point(lambda x: min(255, int(x * 0.65))),
        ])

        canvas = Image.new("RGB", (w, h), (255, 252, 240))

        photo_fit = sepia.resize((inner_w, inner_h), Image.LANCZOS)
        canvas.paste(photo_fit, (border, border))

        draw = ImageDraw.Draw(canvas)

        # Heavy outer border
        draw.rectangle([0, 0, w - 1, h - 1], outline=(200, 180, 140), width=border)

        # Bottom strip text
        font_size = max(10, int(strip * 0.35))
        font = _default_font(font_size)
        ty = h - strip // 2
        draw.text((w // 2, ty), "Microsoft Learning Zone  ·  2026",
                  fill=(100, 70, 20), font=font, anchor="mm")

        return canvas

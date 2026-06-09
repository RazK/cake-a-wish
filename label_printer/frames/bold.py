from PIL import Image, ImageDraw
from ._base import FrameTemplate, _default_font


class BoldFrame(FrameTemplate):
    """
    Bold purple branding strip at bottom, full-bleed photo above.
    Designer replaces this with overlay.png + config.json.
    """
    id          = "bold"
    name        = "Bold"
    _STRIP_FRAC = 0.14
    _PURPLE     = (124, 111, 247)

    photo_rect_frac = (0.0, 0.0, 1.0, 1.0 - _STRIP_FRAC)
    strip_color     = _PURPLE

    def apply(self, photo: Image.Image) -> Image.Image:
        w, h   = photo.size
        strip  = max(36, int(h * self._STRIP_FRAC))
        photo_h = h - strip

        canvas = Image.new("RGB", (w, h), self._PURPLE)

        photo_fit = photo.resize((w, photo_h), Image.LANCZOS)
        canvas.paste(photo_fit, (0, 0))

        draw = ImageDraw.Draw(canvas)
        font_size = max(11, int(strip * 0.38))
        font = _default_font(font_size)
        draw.text(
            (w // 2, photo_h + strip // 2),
            "✨ Cake A Wish  ·  Learning Zone",
            fill=(255, 255, 255),
            font=font,
            anchor="mm",
        )

        return canvas

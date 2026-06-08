from PIL import Image, ImageDraw
from ._base import FrameTemplate, _default_font


class CleanFrame(FrameTemplate):
    """
    Minimal polaroid. White background, thin border, small branding strip at bottom.
    Designer replaces this with overlay.png + config.json.
    """
    id   = "clean"
    name = "Clean"

    def apply(self, photo: Image.Image) -> Image.Image:
        w, h = photo.size
        pad   = max(8,  int(w * 0.04))
        strip = max(32, int(h * 0.12))
        border = max(2, int(w * 0.006))

        canvas = Image.new("RGB", (w, h), (255, 255, 255))

        # Photo region
        ph = h - strip - pad
        photo_fit = photo.resize((w - pad * 2, ph - pad), Image.LANCZOS)
        canvas.paste(photo_fit, (pad, pad))

        # Thin border around photo
        draw = ImageDraw.Draw(canvas)
        draw.rectangle(
            [pad, pad, w - pad, pad + ph - pad],
            outline=(220, 220, 220), width=border,
        )

        # Branding strip
        font_size = max(10, int(strip * 0.30))
        font = _default_font(font_size)
        tx, ty = w // 2, h - strip // 2
        draw.text((tx, ty), "Learning Zone", fill=(100, 80, 200),
                  font=font, anchor="mm")

        return canvas

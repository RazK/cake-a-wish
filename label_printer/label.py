from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from brother_ql.devicedependent import label_type_specs


class LabelImage:
    def __init__(self, text: str, label_id: str, subtitle: Optional[str] = None, font_size: int = 90):
        self.text = text
        self.label_id = label_id
        self.subtitle = subtitle
        self.font_size = font_size

    def _label_pixels(self) -> Tuple[int, int]:
        specs = label_type_specs.get(self.label_id)
        if not specs:
            return 696, 200
        dp = specs.get("dots_printable")
        if dp:
            return dp[0], dp[1]
        return 696, 200

    def render(self, rotate: bool = False) -> Image.Image:
        width, height = self._label_pixels()
        if rotate:
            width, height = height, width

        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)

        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]

        def load_font(size: int):
            for path in font_paths:
                try:
                    return ImageFont.truetype(path, size=size)
                except OSError:
                    continue
            return ImageFont.load_default()

        margin = max(4, int(min(width, height) * 0.04))
        max_lines = 1 if rotate else 6

        import textwrap

        chosen_text = self.text
        chosen_font = load_font(self.font_size)
        fitted = False

        for lines in range(1, max_lines + 1):
            wrapped = self.text if rotate else textwrap.fill(self.text, width=max(1, int(len(self.text) / lines) + 1))
            for size in range(self.font_size, 5, -2):
                font = load_font(size)
                bbox = draw.multiline_textbbox((0, 0), wrapped, font=font)
                if bbox[2] - bbox[0] <= width - 2 * margin and bbox[3] - bbox[1] <= height - 2 * margin:
                    chosen_text = wrapped
                    chosen_font = font
                    fitted = True
                    break
            if fitted:
                break

        if not fitted:
            for size in range(self.font_size, 5, -1):
                font = load_font(size)
                bbox = draw.multiline_textbbox((0, 0), chosen_text, font=font)
                if bbox[2] - bbox[0] <= width - 2 * margin and bbox[3] - bbox[1] <= height - 2 * margin:
                    chosen_font = font
                    break

        subtitle_text = f"({self.subtitle})" if self.subtitle else None
        subtitle_font = load_font(max(16, int(self.font_size * 0.35))) if subtitle_text else None

        main_bbox = draw.multiline_textbbox((0, 0), chosen_text, font=chosen_font)
        text_height = main_bbox[3] - main_bbox[1]
        subtitle_height = 0
        line_spacing = max(22, int(self.font_size * 0.22))

        if subtitle_text:
            subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
            subtitle_height = subtitle_bbox[3] - subtitle_bbox[1]
            text_height += line_spacing + subtitle_height

        y = (height - text_height) // 2
        x = (width - (main_bbox[2] - main_bbox[0])) // 2
        draw.multiline_text((x, y), chosen_text, fill="black", font=chosen_font, align="center", spacing=line_spacing)

        if subtitle_text:
            subtitle_y = y + (main_bbox[3] - main_bbox[1]) + line_spacing
            subtitle_x = (width - (subtitle_bbox[2] - subtitle_bbox[0])) // 2
            draw.text((subtitle_x, subtitle_y), subtitle_text, fill="black", font=subtitle_font)

        return image

    def save_preview(self, path: str, rotate: bool = False) -> None:
        img = self.render(rotate=rotate)
        img.save(path)

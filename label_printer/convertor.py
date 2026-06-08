from PIL import Image
import PIL.ImageOps
import PIL.ImageChops
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS  # removed in Pillow 10, brother_ql still uses it
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert


def process_for_preview(image: Image.Image, label_id: str = '') -> Image.Image:
    """Simulate the print pipeline and return an RGB image for WYSIWYG display.

    For two-color (62red) labels: applies the same HSV separation as brother_ql
    and returns an RGB image showing black/red/white regions.
    For black-only labels: Floyd-Steinberg dither, returns L-mode image.
    """
    from brother_ql.labels import LabelsManager, Color
    from brother_ql.image_trafos import filtered_hsv
    lm = LabelsManager()
    lbl = next((el for el in lm.iter_elements() if el.identifier == label_id), None)
    is_red = lbl is not None and lbl.color == Color.BLACK_RED_WHITE

    im = image.convert("RGB")

    if is_red:
        red_filt = filtered_hsv(
            im,
            lambda h: 255 if (h < 40 or h > 210) else 0,
            lambda s: 255 if s > 100 else 0,
            lambda v: 255 if v > 80 else 0,
        )
        red_mask = PIL.ImageOps.invert(red_filt.convert("L")).point(lambda x: 255 if x else 0)

        black_filt = filtered_hsv(
            im,
            lambda h: 255,
            lambda s: 255,
            lambda v: 255 if v < 80 else 0,
        )
        black_mask_all = PIL.ImageOps.invert(black_filt.convert("L")).point(lambda x: 255 if x else 0)
        black_mask = PIL.ImageChops.subtract(black_mask_all, red_mask)

        preview = Image.new("RGB", im.size, (255, 255, 255))
        preview.paste(Image.new("RGB", im.size, (0, 0, 0)),       mask=black_mask)
        preview.paste(Image.new("RGB", im.size, (210, 20, 20)),   mask=red_mask)
        return preview
    else:
        return image.convert("L").convert("1").convert("L")


def build_instructions(image: Image.Image, label_id: str, model: str = "QL-820NWB") -> bytes:
    from brother_ql.labels import LabelsManager, Color
    lm   = LabelsManager()
    lbl  = next((el for el in lm.iter_elements() if el.identifier == label_id), None)
    is_red = lbl is not None and lbl.color == Color.BLACK_RED_WHITE
    qlr  = BrotherQLRaster(model)
    qlr.exception_on_warning = True
    # Pass the original image; brother_ql handles HSV separation (red) or dithering (black-only)
    convert(qlr, [image], label_id, rotate=0, threshold=70.0, dither=not is_red,
            compress=False, red=is_red, dpi_600=False, hq=True, cut=True)
    return qlr.data

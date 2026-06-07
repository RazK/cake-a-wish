from PIL import Image
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert


def build_instructions(image: Image.Image, label_id: str, model: str = "QL-820NWB") -> bytes:
    qlr = BrotherQLRaster(model)
    qlr.exception_on_warning = True
    convert(qlr, [image], label_id, rotate="auto", threshold=70.0, dither=True, compress=False, red=False, dpi_600=False, hq=True, cut=True)
    return qlr.data

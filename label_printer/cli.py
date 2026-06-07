import argparse
import os
from pathlib import Path
from typing import Optional

from .label import LabelImage
from .printer import BrotherPrinter
from .convertor import build_instructions

PREVIEW_DIR = Path("artifacts")
PREVIEW_FILE = "label_preview.png"
INSTRUCTION_FILE = "label_instructions.bin"


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Print labels on Brother QL-series printers.")
    parser.add_argument("ip", help="Printer IP address")
    parser.add_argument("--label", help="Label id (e.g. 62x29, 29x90, 62, 62red)")
    parser.add_argument("--text", required=True, help="Text to print")
    parser.add_argument("--subtitle", help="Optional secondary text printed below the main text")
    parser.add_argument("--preview", action="store_true", help="Save PNG preview and instruction bytes instead of sending")
    parser.add_argument("--rotate", action="store_true", help="Rotate image before conversion")
    parser.add_argument("--password", help="Printer admin password (falls back to PRINTER_PASSWORD env var)")
    args = parser.parse_args(argv)

    password = args.password or os.environ.get("PRINTER_PASSWORD")
    printer = BrotherPrinter(args.ip, password=password)

    label_id = args.label or printer.detect_label()
    if not label_id:
        raise SystemExit("Printer label could not be detected. Provide --label or verify printer connectivity.")

    image = LabelImage(args.text, label_id, subtitle=args.subtitle)
    rendered = image.render(rotate=args.rotate)

    if args.preview:
        PREVIEW_DIR.mkdir(exist_ok=True)
        preview_path = PREVIEW_DIR / PREVIEW_FILE
        image.save_preview(preview_path, rotate=args.rotate)

        instructions = build_instructions(rendered, label_id)
        instr_path = PREVIEW_DIR / INSTRUCTION_FILE
        instr_path.write_bytes(instructions)

        print(f"Preview saved: {preview_path}")
        print(f"Instructions saved: {instr_path}")
        return

    instructions = build_instructions(rendered, label_id)
    print(f"Sending {len(instructions)} bytes to {args.ip}...")
    response = printer.send_instructions(instructions)
    print("Printer response:", response)


if __name__ == "__main__":
    main()

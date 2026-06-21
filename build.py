"""Build the distributable bundle.

    python build.py          # build for current platform
    python build.py --clean  # remove dist/ and build/ first
"""
import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    clean = "--clean" in sys.argv
    if clean:
        for d in ("dist", "build"):
            p = ROOT / d
            if p.exists():
                print(f"removing {p}")
                shutil.rmtree(p)

    print("installing pyinstaller...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "-q"])

    print("building...")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        str(ROOT / "cake_a_wish.spec"),
    ])

    out = ROOT / "dist" / "CakeAWish"
    print(f"\nDone. Output: {out}")
    print("Mac: open dist/CakeAWish.app")
    print("Windows: run dist/CakeAWish/CakeAWish.exe")


if __name__ == "__main__":
    main()

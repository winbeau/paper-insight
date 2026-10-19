"""Render frontend/public/logo.svg into a macOS .icns (logo on a rounded dark tile).

Usage: python packaging/make_icns.py <logo.svg> <out.icns>
Uses PyMuPDF (a backend dependency) plus the system `sips` and `iconutil`.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # pymupdf

CANVAS = 1024
TILE_MARGIN = 100   # macOS icon grid: the tile is ~824px inside a 1024 canvas
LOGO_PADDING = 120  # logo inset within the tile


def render_master(svg_path: Path, png_path: Path) -> None:
    svg = svg_path.read_text(encoding="utf-8")
    match = re.search(r'viewBox="\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)', svg)
    width, height = (match.group(1), match.group(2)) if match else ("1024", "1024")
    # width="100%" makes MuPDF fall back to a letter-size page: pin the real size
    svg = re.sub(r'width="[^"]*"', f'width="{width}"', svg, count=1)
    svg = re.sub(r'height="[^"]*"', f'height="{height}"', svg, count=1)
    logo = fitz.open(stream=svg.encode("utf-8"), filetype="svg")
    logo_pdf = fitz.open("pdf", logo.convert_to_pdf())

    doc = fitz.open()
    page = doc.new_page(width=CANVAS, height=CANVAS)
    tile = fitz.Rect(TILE_MARGIN, TILE_MARGIN, CANVAS - TILE_MARGIN, CANVAS - TILE_MARGIN)
    # The logo is white + yellow: put it on the app's ink color (#0f1419)
    page.draw_rect(tile, color=None, fill=(0x0F / 255, 0x14 / 255, 0x19 / 255), radius=0.22)
    page.show_pdf_page(tile + (LOGO_PADDING, LOGO_PADDING, -LOGO_PADDING, -LOGO_PADDING), logo_pdf, 0)
    page.get_pixmap(alpha=True).save(str(png_path))


def main(svg: str, out: str) -> None:
    out_path = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        master = Path(tmp) / "master.png"
        render_master(Path(svg), master)
        iconset = Path(tmp) / "PaperInsight.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                subprocess.run(
                    ["sips", "-z", str(pixels), str(pixels), str(master), "--out", str(iconset / name)],
                    check=True, capture_output=True,
                )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out_path)], check=True)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:3])

"""Build the brand and illustration assets for the web app and the Flutter app.

    python scripts/brand_assets.py --sources <folder with the Higgsfield PNGs>

The logo is drawn here from one set of coordinates (a house with a pulse line inside, from a
Higgsfield concept), so the SVG and every PNG size match exactly and stay crisp. The
illustrations were generated with Higgsfield (Z Image) and are only resized and compressed
here; the multi-megabyte originals are not committed.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
WEB_IMG = ROOT / "api" / "src" / "jamii_api" / "web" / "static" / "img"
MOBILE = ROOT / "mobile" / "assets"

BLUE = "#2A78D6"
WHITE = "#FFFFFF"
STROKE = 4.5
# All on a 64 x 64 grid.
ROOF = [(12, 30), (32, 13), (52, 30)]
WALLS = [(17, 25.75), (17, 50), (47, 50), (47, 25.75)]
# One clear beat: a single rise and fall, spaced so the strokes never merge at 16 px.
PULSE = [(17, 38), (25, 38), (28.5, 30), (33, 44.5), (36.5, 38), (47, 38)]
GLYPH = (ROOF, WALLS, PULSE)

# Higgsfield output -> (destination, max width, max height)
ILLUSTRATIONS = {
    "login_4.png": [(WEB_IMG / "login-chp.webp", 560, 747), (MOBILE / "illustrations" / "chp_walking.webp", 480, 640)],
    "empty_review_6.png": [(WEB_IMG / "all-caught-up.webp", 440, 330)],
    "empty_mobile_8.png": [(MOBILE / "illustrations" / "report_prompt.webp", 420, 420)],
}


def svg(rounded: bool = True) -> str:
    def points(pts):
        return " ".join(f"{x:g},{y:g}" for x, y in pts)

    rx = 14 if rounded else 0
    lines = "".join(f'<polyline points="{points(p)}"/>' for p in GLYPH)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Jamii Pulse">'
        f'<rect width="64" height="64" rx="{rx}" fill="{BLUE}"/>'
        f'<g fill="none" stroke="{WHITE}" stroke-width="{STROKE}" stroke-linecap="round" '
        f'stroke-linejoin="round">{lines}</g></svg>\n'
    )


def png(size: int, *, background: bool = True, rounded: bool = True, glyph_scale: float = 1.0) -> Image.Image:
    """Draw at 8x and scale down, for smooth edges at every size."""
    ss = size * 8
    unit = ss / 64
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        if rounded:
            d.rounded_rectangle([0, 0, ss - 1, ss - 1], radius=round(14 * unit), fill=BLUE)
        else:
            d.rectangle([0, 0, ss - 1, ss - 1], fill=BLUE)
    width = round(STROKE * unit * glyph_scale)
    centre = ss / 2

    def place(x, y):
        return (centre + (x * unit - centre) * glyph_scale, centre + (y * unit - centre) * glyph_scale)

    for pts in GLYPH:
        xy = [place(x, y) for x, y in pts]
        d.line(xy, fill=WHITE, width=width, joint="curve")
        for x, y in (xy[0], xy[-1]):  # round caps
            r = width / 2
            d.ellipse([x - r, y - r, x + r, y + r], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def build_brand() -> None:
    WEB_IMG.mkdir(parents=True, exist_ok=True)
    (WEB_IMG / "logo.svg").write_text(svg(), encoding="utf-8")
    png(32).save(WEB_IMG / "favicon-32.png", optimize=True)
    png(180, rounded=False).convert("RGB").save(WEB_IMG / "apple-touch-icon.png", optimize=True)
    brand = MOBILE / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    # Square, no transparency: iOS rounds the corners itself.
    png(1024, rounded=False).convert("RGB").save(brand / "app_icon.png", optimize=True)
    # Android adaptive icon foreground: glyph only, inside the 66% safe zone.
    png(1024, background=False, glyph_scale=0.62).save(brand / "app_icon_foreground.png", optimize=True)
    png(256).save(brand / "logo.png", optimize=True)
    # Flutter web build (the app in a browser): favicon and PWA icons.
    web = ROOT / "mobile" / "web"
    png(32).save(web / "favicon.png", optimize=True)
    for size in (192, 512):
        png(size).save(web / "icons" / f"Icon-{size}.png", optimize=True)
        png(size, rounded=False, glyph_scale=0.8).save(web / "icons" / f"Icon-maskable-{size}.png", optimize=True)


def build_illustrations(sources: Path) -> None:
    for name, outputs in ILLUSTRATIONS.items():
        src = Image.open(sources / name).convert("RGB")
        for dest, max_w, max_h in outputs:
            dest.parent.mkdir(parents=True, exist_ok=True)
            img = src.copy()
            img.thumbnail((max_w, max_h), Image.LANCZOS)
            img.save(dest, "WEBP", quality=78, method=6)
            print(f"{dest.relative_to(ROOT)}  {img.size[0]}x{img.size[1]}  {dest.stat().st_size // 1024} KB")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", type=Path, help="folder with the Higgsfield PNGs; omit to rebuild the logo only")
    args = p.parse_args()
    build_brand()
    print("logo: svg, favicon, apple-touch-icon, app icons")
    if args.sources:
        build_illustrations(args.sources)


if __name__ == "__main__":
    main()

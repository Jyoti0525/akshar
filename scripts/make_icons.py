"""Generate the app icons from the AKSHAR mark. AKSHAR.md section 11.

The mark is the letter **A** — *akshar* means "letter" — drawn as three strokes
inside a ring, in the crimson-to-orange gradient of the logo. The web app draws
the same three strokes as inline SVG in `web/src/components/brand.tsx`; this
script is the raster twin of that file, and the coordinates are deliberately the
same 64-unit grid so the two cannot drift apart without somebody noticing.

Run it when the palette or the mark changes:

    python scripts/make_icons.py

Writes `web/public/icons/*.png` and `web/src/app/icon.png` (Next serves that one
as the favicon; without it the tab shows a browser default and every page logs a
404 for `/favicon.ico`).

**Everything is drawn at 4x and downscaled.** Pillow has no anti-aliased stroke
primitive, so a 192 px icon drawn directly has visibly stepped diagonals — and
the mark is two diagonals. Supersampling costs about a second and is the whole
difference between a crisp icon and one that looks like a screenshot.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "web" / "public" / "icons"
APP = ROOT / "web" / "src" / "app"

# From `:root` in `web/src/app/globals.css`. Light mode only: a launcher icon is
# composited against a wallpaper, not against our page, so it carries its own
# ground and never follows the display mode.
PAPER = (253, 250, 247)  # --bg
BRAND_FROM = (168, 22, 58)  # --brand-from, bottom-left of the gradient
BRAND_TO = (240, 113, 61)  # --brand-to, top-right

SUPERSAMPLE = 4

# The mark, on the same 0..64 grid as `AksharMark` in brand.tsx.
RING_RADIUS = 30.5
RING_WIDTH = 1.75
LEG_WIDTH = 7.5
BAR_WIDTH = 6.5
APEX = (32.0, 14.0)
FOOT_LEFT = (14.0, 50.0)
FOOT_RIGHT = (50.0, 50.0)
BAR = ((22.5, 36.0), (41.5, 36.0))


def _gradient(size: int) -> Image.Image:
    """The brand gradient, bottom-left to top-right, as an image to mask.

    Matches `linearGradient x1=0 y1=1 x2=1 y2=0` in `brand.tsx`. Built by hand
    rather than with a library because the only thing needed is a linear ramp
    along one diagonal, and the projection of a pixel onto that diagonal is one
    line of arithmetic.
    """
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    assert pixels is not None
    span = 2.0 * (size - 1)
    for y in range(size):
        for x in range(size):
            # x increasing and y decreasing both move along the gradient, so the
            # parameter is their sum, normalised over its full range.
            t = (x + (size - 1 - y)) / span
            pixels[x, y] = (
                round(BRAND_FROM[0] + (BRAND_TO[0] - BRAND_FROM[0]) * t),
                round(BRAND_FROM[1] + (BRAND_TO[1] - BRAND_FROM[1]) * t),
                round(BRAND_FROM[2] + (BRAND_TO[2] - BRAND_FROM[2]) * t),
            )
    return image


def _round_line(
    canvas: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    width: float,
) -> None:
    """A stroke with round caps, which `ImageDraw.line` does not provide.

    `joint="curve"` rounds the joins of a polyline but leaves the two ends
    square, and a square-ended A has a visibly clipped apex against the ring.
    """
    canvas.line([start, end], fill=255, width=round(width))
    radius = width / 2.0
    for point in (start, end):
        canvas.ellipse(
            [point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius],
            fill=255,
        )


def _mask(size: int, *, inset: float) -> Image.Image:
    """The mark as an alpha mask on a `size` square, drawn on the 64-unit grid.

    `inset` is the fraction of the square left empty around the mark. A maskable
    icon is cropped to whatever shape the launcher likes — a circle on most
    Android versions, a squircle on some — so it has to keep everything inside
    the middle 80%, while the plain icon can use nearly the whole square.
    """
    mask = Image.new("L", (size, size), 0)
    canvas = ImageDraw.Draw(mask)

    box = size * (1.0 - 2.0 * inset)
    scale = box / 64.0
    origin = size * inset

    def at(point: tuple[float, float]) -> tuple[float, float]:
        return (origin + point[0] * scale, origin + point[1] * scale)

    centre = at((32.0, 32.0))
    radius = RING_RADIUS * scale
    canvas.ellipse(
        [centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius],
        outline=110,  # the ring is at 0.4 opacity in the SVG
        width=max(1, round(RING_WIDTH * scale)),
    )

    _round_line(canvas, at(APEX), at(FOOT_LEFT), LEG_WIDTH * scale)
    _round_line(canvas, at(APEX), at(FOOT_RIGHT), LEG_WIDTH * scale)
    _round_line(canvas, at(BAR[0]), at(BAR[1]), BAR_WIDTH * scale)

    return mask


def draw(size: int, *, maskable: bool) -> Image.Image:
    big = size * SUPERSAMPLE
    ground = Image.new("RGB", (big, big), PAPER)
    ground.paste(_gradient(big), (0, 0), _mask(big, inset=0.19 if maskable else 0.09))
    return ground.resize((size, size), Image.Resampling.LANCZOS)


def main() -> int:
    ICONS.mkdir(parents=True, exist_ok=True)

    for name, size, maskable in (
        (ICONS / "icon-192.png", 192, False),
        (ICONS / "icon-512.png", 512, False),
        (ICONS / "maskable-512.png", 512, True),
        (APP / "icon.png", 512, False),
    ):
        draw(size, maskable=maskable).save(name, format="PNG", optimize=True)
        print(f"  wrote {name.relative_to(ROOT)}  {size}x{size}")

    # `.ico` must be RGBA or Pillow refuses it — "The PNG is not in RGBA format"
    # — and the sizes have to be listed or it writes a single 512 px frame that
    # Windows renders as a smear in the taskbar.
    icon = draw(256, maskable=False).convert("RGBA")
    icon.save(APP / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print(f"  wrote {(APP / 'favicon.ico').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

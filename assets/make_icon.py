"""Regenerate the app icon: a liquid-glass envelope on the app's black + spring-green.

    python assets/make_icon.py

Writes assets/freight.ico (multi-size), assets/freight-256.png, and the dashboard
favicons under outreach/web/static/. Pillow only — no ImageMagick / cairosvg needed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATIC = ROOT / "outreach" / "web" / "static"

# App palette (style.css)
NEAR_BLACK = (5, 8, 10, 255)          # #05080a
ACCENT = (61, 220, 132)               # #3ddc84

S = 5                                 # supersample factor
N = 256 * S


def _sx(v: float) -> int:
    return int(round(v * S))


def _mask_rounded(box, radius) -> Image.Image:
    m = Image.new("L", (N, N), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, radius=radius, fill=255)
    return m


def render() -> Image.Image:
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))

    # --- rounded-square background -------------------------------------------
    bg_r = _sx(56)
    panel = _mask_rounded([0, 0, N - 1, N - 1], bg_r)
    base = Image.new("RGBA", (N, N), NEAR_BLACK)

    # ambient green glow, brightest a little above centre
    glow = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    cx, cy = N * 0.5, N * 0.43
    steps = 54
    for i in range(steps):
        rad = _sx(150) * (1 - i / steps)
        a = int(3 + i * 2.4)
        gd.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(*ACCENT, min(a, 135)))
    glow = glow.filter(ImageFilter.GaussianBlur(_sx(26)))
    base = Image.alpha_composite(base, glow)

    # corner vignette so the panel reads black at the edges
    vig = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vig)
    for i in range(40):
        inset = _sx(120) * (i / 40)
        vd.rounded_rectangle(
            [inset, inset, N - inset, N - inset], radius=bg_r, outline=(0, 0, 0, 7), width=_sx(4)
        )
    vig = vig.filter(ImageFilter.GaussianBlur(_sx(24)))
    base = Image.alpha_composite(base, vig)

    # faint top sheen on the panel itself
    top = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    td = ImageDraw.Draw(top)
    for y in range(0, int(N * 0.5)):
        a = int(30 * (1 - y / (N * 0.5)))
        td.line([(0, y), (N, y)], fill=(255, 255, 255, a))
    base = Image.alpha_composite(base, top)

    base.putalpha(panel)
    img = Image.alpha_composite(img, base)

    # --- envelope geometry -------------------------------------------------
    ew, eh = _sx(154), _sx(108)
    ex = (N - ew) // 2
    ey = int(N * 0.5 - eh * 0.5) + _sx(6)
    er = _sx(18)
    env_box = [ex, ey, ex + ew, ey + eh]
    env_mask = _mask_rounded(env_box, er)

    # drop shadow so the glass floats
    sh = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [ex, ey + _sx(12), ex + ew, ey + eh + _sx(12)], radius=er, fill=(0, 0, 0, 170)
    )
    sh = sh.filter(ImageFilter.GaussianBlur(_sx(16)))
    sh.putalpha(ImageChops.subtract(sh.getchannel("A"), env_mask))  # don't darken under the glass
    img = Image.alpha_composite(img, sh)

    glass = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    gdr = ImageDraw.Draw(glass)

    # frosted body
    gdr.rounded_rectangle(env_box, radius=er, fill=(255, 255, 255, 32))

    # soft specular blob, upper-left
    spec = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(spec).ellipse(
        [ex + _sx(14), ey + _sx(8), ex + _sx(78), ey + _sx(44)], fill=(255, 255, 255, 70)
    )
    spec = spec.filter(ImageFilter.GaussianBlur(_sx(12)))
    spec.putalpha(ImageChops.multiply(spec.getchannel("A"), env_mask))
    glass = Image.alpha_composite(glass, spec)

    # top-edge highlight inside the body
    hi = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hi)
    for y in range(ey, ey + int(eh * 0.55)):
        t = (y - ey) / (eh * 0.55)
        hd.line([(ex, y), (ex + ew, y)], fill=(255, 255, 255, int(60 * (1 - t))))
    hi.putalpha(ImageChops.multiply(hi.getchannel("A"), env_mask))
    glass = Image.alpha_composite(glass, hi)

    # diagonal specular sheen
    sheen = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).polygon(
        [
            (ex - _sx(24), ey + eh * 0.12),
            (ex + _sx(34), ey + eh * 0.12),
            (ex + ew * 0.58, ey + eh + _sx(24)),
            (ex + ew * 0.36, ey + eh + _sx(24)),
        ],
        fill=(255, 255, 255, 42),
    )
    sheen = sheen.filter(ImageFilter.GaussianBlur(_sx(7)))
    sheen.putalpha(ImageChops.multiply(sheen.getchannel("A"), env_mask))
    glass = Image.alpha_composite(glass, sheen)

    # borders — dim all round, bright along top + left (light top-left)
    gdr.rounded_rectangle(env_box, radius=er, outline=(255, 255, 255, 90), width=_sx(1.6))
    edge = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    ed = ImageDraw.Draw(edge)
    ed.arc([ex, ey, ex + 2 * er, ey + 2 * er], 180, 270, fill=(255, 255, 255, 200), width=_sx(2))
    ed.line([(ex + er, ey), (ex + ew - er, ey)], fill=(255, 255, 255, 200), width=_sx(2))
    ed.line([(ex, ey + er), (ex, ey + eh - er)], fill=(255, 255, 255, 150), width=_sx(2))
    glass = Image.alpha_composite(glass, edge)

    # envelope flap — the green "V"
    fx = ex + ew / 2
    fy = ey + eh * 0.44
    flap = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    fd = ImageDraw.Draw(flap)
    fd.line([(ex + _sx(5), ey + _sx(4)), (fx, fy)], fill=(*ACCENT, 230), width=_sx(4.4))
    fd.line([(ex + ew - _sx(5), ey + _sx(4)), (fx, fy)], fill=(*ACCENT, 230), width=_sx(4.4))
    fglow = flap.filter(ImageFilter.GaussianBlur(_sx(6)))
    flap = Image.alpha_composite(fglow, flap)
    flap.putalpha(ImageChops.multiply(flap.getchannel("A"), env_mask))
    glass = Image.alpha_composite(glass, flap)

    img = Image.alpha_composite(img, glass)
    return img.resize((256, 256), Image.LANCZOS)


def main() -> None:
    icon = render()

    png = HERE / "freight-256.png"
    icon.save(png)

    ico = HERE / "freight.ico"
    icon.save(ico, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    STATIC.mkdir(parents=True, exist_ok=True)
    icon.resize((32, 32), Image.LANCZOS).save(
        STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
    )
    icon.save(STATIC / "favicon-256.png")
    shutil.copyfile(HERE / "icon.svg", STATIC / "favicon.svg")

    print(f"wrote {ico.name}, {png.name}, static/favicon.ico, static/favicon.svg")


if __name__ == "__main__":
    main()

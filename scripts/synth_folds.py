"""Render synthetic top-down photos of the 8 origami fortune teller states.

    .venv/bin/python scripts/synth_folds.py --out scripts/out/folds [--n 6] [--seed 7] [--hand-rate 0.3]

These are drawings, not photos: flat polygons with a paper texture, soft shadows, light falloff and
a little perspective, on dark felt. They exist to measure the camera check before real footage
arrives, and every number measured on them must be re-tested on real footage.

Writes state<k>_clean.jpg (centered, no jitter, no hand: used as the lesson's reference video) and
state<k>_v<ii>.jpg (random rotation, scale, offset, tilt, lighting, blur, sometimes a hand), plus
manifest.json with the parameters of every image. Same seed, same bytes: all randomness comes from
random.Random, never from Pillow's unseeded noise.

Paper is yellow on the front and blue on the back. Colors follow real paper: after the first
corners-to-center fold, the flaps show the back (blue), and every later state shows blue outside
too, so states 4 to 8 differ by shape, not color (the honest, harder test).

States (paper units; the sheet is 2 x 2, centered at 0):
  1 flat square, yellow up
  2 large triangle (corner to corner; the folded half shows blue)
  3 square with an X crease (faint diagonal lines), yellow up
  4 diamond of four blue triangular flaps meeting at the center, seams visible
  5 flipped: a plain blue diamond, no flaps, faint creases
  6 corners in again: half-size square of four flaps with seams
  7 same as 6 plus a center cross crease
  8 four pointed pockets standing up, shaded as pyramids
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

STATES = 8
SIZE = (1280, 720)
PS = 1000  # paper canvas side in pixels
SPAN = 2.4  # paper units across the paper canvas
YELLOW = (236, 204, 74)
BLUE = (58, 108, 186)
SKIN = [(224, 172, 140), (198, 140, 104), (160, 106, 74), (236, 192, 160), (122, 82, 58)]
Pt = tuple[float, float]

# outline of the object in paper units (where a hand can touch it)
_SQ: list[Pt] = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
_DIAMOND: list[Pt] = [(1, 0), (0, 1), (-1, 0), (0, -1)]
_SMALL: list[Pt] = [(0.5, 0.5), (-0.5, 0.5), (-0.5, -0.5), (0.5, -0.5)]
OUTLINES: dict[int, list[Pt]] = {1: _SQ, 2: [(-1, -1), (1, -1), (-1, 1)], 3: _SQ, 4: _DIAMOND, 5: _DIAMOND,
                                 6: _SMALL, 7: _SMALL, 8: [(-0.62, -0.62), (0.62, -0.62), (0.62, 0.62), (-0.62, 0.62)]}
TITLES = {
    1: "flat square, yellow up",
    2: "large triangle",
    3: "square with X crease",
    4: "diamond of four flaps meeting at center",
    5: "flipped, plain blue diamond",
    6: "half-size square of four flaps",
    7: "four flaps plus center cross crease",
    8: "four pointed pockets",
}



@dataclass
class Params:
    """Everything that varies between renders of one state."""

    rotation: float = 0.0  # degrees
    scale: float = 1.0
    offset: Pt = (0.0, 0.0)  # fraction of canvas height
    tilt: float = 0.06  # perspective: how much wider the near (bottom) edge is
    tilt_x: float = 0.0
    light_angle: float = 135.0  # degrees, direction the light comes from (135 = upper left)
    light_gain: float = 1.0
    falloff: float = 0.22  # how much darker the far corners are
    falloff_center: Pt = (0.42, 0.38)  # fraction of the canvas
    tint: tuple[int, int, int] = (255, 250, 242)
    felt: tuple[int, int, int] = (40, 43, 46)
    blur: float = 0.0
    shadow: float = 0.5
    hand: dict | None = None
    paper_seed: int = 0
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- noise and helpers

def noise(rng: random.Random, size: tuple[int, int], cell: int = 1, blur: float = 0.0) -> Image.Image:
    """Seeded uniform noise in L mode; cell > 1 makes coarse blotches (upscaled bicubic)."""
    w, h = max(1, size[0] // cell), max(1, size[1] // cell)
    img = Image.frombytes("L", (w, h), rng.randbytes(w * h))
    if cell > 1:
        img = img.resize(size, Image.BICUBIC)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return img


def level(img: Image.Image, lo: float, hi: float) -> Image.Image:
    """Map 0..255 to lo..hi (both 0..1 multipliers, scaled to 0..255)."""
    return img.point(lambda v: int(255 * (lo + (hi - lo) * v / 255)))


def shade(color: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * f))) for c in color)  # type: ignore[return-value]


def px(p: Pt) -> Pt:
    """Paper units (y up) to paper canvas pixels."""
    u = PS / SPAN
    return (PS / 2 + p[0] * u, PS / 2 - p[1] * u)


def poly(points: list[Pt]) -> list[Pt]:
    return [px(p) for p in points]


def shrink(points: list[Pt], by: float) -> list[Pt]:
    """Move each vertex toward the centroid by a fraction: leaves a thin seam between flaps."""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return [(x + (cx - x) * by, y + (cy - y) * by) for x, y in points]


def light_dir(angle: float) -> Pt:
    a = math.radians(angle)
    return (math.cos(a), math.sin(a))


def facing(apex: Pt, a: Pt, b: Pt, light: Pt) -> float:
    """How much a sloped face (apex up, edge a-b down) faces the light: -1..1."""
    mx, my = (a[0] + b[0]) / 2 - apex[0], (a[1] + b[1]) / 2 - apex[1]
    n = math.hypot(mx, my) or 1.0
    return (mx * light[0] + my * light[1]) / n


# ---------------------------------------------------------------- paper drawing

class Paper:
    """One RGBA paper layer on the PS x PS canvas, drawn face by face."""

    def __init__(self, rng: random.Random, light: Pt):
        self.rgb = Image.new("RGB", (PS, PS), (0, 0, 0))
        self.alpha = Image.new("L", (PS, PS), 0)
        self.rng = rng
        self.light = light

    def face(self, points: list[Pt], color: tuple[int, int, int], f: float = 1.0) -> None:
        ImageDraw.Draw(self.rgb).polygon(poly(points), fill=shade(color, f))
        ImageDraw.Draw(self.alpha).polygon(poly(points), fill=255)

    def flap(self, points: list[Pt], color: tuple[int, int, int], gap: float = 0.035) -> None:
        """A folded-over layer: casts a small soft shadow on what is under it, then is drawn
        slightly shrunk so a seam shows, with a lit fold edge."""
        pts = shrink(points, gap)
        sh = Image.new("L", (PS, PS), 0)
        dx, dy = -self.light[0] * 5, self.light[1] * 5  # shadow falls away from the light
        ImageDraw.Draw(sh).polygon([(x + dx, y + dy) for x, y in poly(pts)], fill=120)
        sh = sh.filter(ImageFilter.GaussianBlur(4))
        self.rgb = Image.composite(Image.new("RGB", (PS, PS), (0, 0, 0)), self.rgb, sh)
        jitter = self.rng.uniform(0.97, 1.03)
        self.face(pts, color, jitter)
        # thin highlight along the outer fold edge (first two points by convention)
        ImageDraw.Draw(self.rgb).line(poly(pts[:2]), fill=shade(color, 1.12 * jitter), width=3)

    def crease(self, a: Pt, b: Pt, strength: float = 1.0) -> None:
        """A faint valley line: a dark line with a light line next to it, softened."""
        line = Image.new("L", (PS, PS), 0)
        hi = Image.new("L", (PS, PS), 0)
        pa, pb = px(a), px(b)
        ImageDraw.Draw(line).line([pa, pb], fill=int(70 * strength), width=3)
        ImageDraw.Draw(hi).line([(pa[0] + 2, pa[1] + 2), (pb[0] + 2, pb[1] + 2)], fill=int(45 * strength), width=2)
        line = ImageChops.multiply(line.filter(ImageFilter.GaussianBlur(1.0)), self.alpha)
        hi = ImageChops.multiply(hi.filter(ImageFilter.GaussianBlur(1.0)), self.alpha)
        self.rgb = Image.composite(Image.new("RGB", (PS, PS), (0, 0, 0)), self.rgb, line)
        self.rgb = Image.composite(Image.new("RGB", (PS, PS), (255, 255, 255)), self.rgb, hi)

    def seam(self, a: Pt, b: Pt) -> None:
        line = Image.new("L", (PS, PS), 0)
        ImageDraw.Draw(line).line([px(a), px(b)], fill=150, width=2)
        line = ImageChops.multiply(line.filter(ImageFilter.GaussianBlur(0.8)), self.alpha)
        self.rgb = Image.composite(Image.new("RGB", (PS, PS), (0, 0, 0)), self.rgb, line)

    def texture(self, seed: int) -> None:
        """Paper fibers and blotches, multiplied in (about +-4 percent)."""
        rng = random.Random(seed)
        fine = level(noise(rng, (PS, PS), 1, 0.8), 0.93, 1.0)
        coarse = level(noise(rng, (PS, PS), 40, 6), 0.95, 1.0)
        tex = ImageChops.multiply(fine, coarse)
        self.rgb = ImageChops.multiply(self.rgb, Image.merge("RGB", (tex, tex, tex)))
        bright = Image.new("RGB", (PS, PS), (12, 12, 12))
        self.rgb = ImageChops.add(self.rgb, bright)


def draw_state(state: int, paper: Paper) -> float:
    """Draws one state; returns how tall the object stands (shadow length factor)."""
    Y, B = YELLOW, BLUE
    L = paper.light
    sq = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    diamond_pts = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    if state in (1, 3):
        paper.face(sq, Y)
        if state == 3:
            paper.crease((-1, -1), (1, 1), 0.9)
            paper.crease((-1, 1), (1, -1), 0.9)
        return 1.0
    if state == 2:
        paper.face([(-1, -1), (1, -1), (-1, 1)], Y)  # bottom half, only a sliver shows
        # folded half: fold edge (hypotenuse) first so it gets the highlight
        paper.flap([(1, -1), (-1, 1), (-0.985, -0.985)], B, gap=0.012)
        return 1.3
    if state == 4:
        paper.face(diamond_pts, Y)  # center of the sheet, seen only through the seams
        for i in range(4):
            a, b = diamond_pts[i], diamond_pts[(i + 1) % 4]
            paper.flap([a, b, (0, 0)], B)
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            paper.crease((mid[0] * 0.15, mid[1] * 0.15), (mid[0] * 0.9, mid[1] * 0.9), 0.5)
        return 1.4
    if state == 5:
        paper.face(diamond_pts, B)
        paper.crease((0.5, 0.5), (-0.5, -0.5), 0.6)
        paper.crease((-0.5, 0.5), (0.5, -0.5), 0.6)
        for i in range(4):  # the edges are folds: a slightly lit rim
            a, b = diamond_pts[i], diamond_pts[(i + 1) % 4]
            ImageDraw.Draw(paper.rgb).line(poly([a, b]), fill=shade(B, 1.1), width=3)
        return 1.4
    if state in (6, 7):
        h = 0.5
        small = [(h, h), (-h, h), (-h, -h), (h, -h)]
        paper.face(small, B)
        for i in range(4):
            a, b = small[i], small[(i + 1) % 4]
            paper.flap([a, b, (0, 0)], B)
        for c in small:
            paper.seam((c[0] * 0.08, c[1] * 0.08), (c[0] * 0.95, c[1] * 0.95))
        if state == 7:
            paper.crease((-h, 0), (h, 0), 1.3)
            paper.crease((0, -h), (0, h), 1.3)
        return 1.6
    if state == 8:
        s, g = 0.62, 0.035
        # the cross-shaped opening between pockets: the inside, which is yellow and in shadow
        paper.face([(-s, -s), (s, -s), (s, s), (-s, s)], shade(Y, 0.45))
        for qx in (-1, 1):
            for qy in (-1, 1):
                x0, x1 = sorted((qx * g, qx * s))
                y0, y1 = sorted((qy * g, qy * s))
                corners = [(x1, y0), (x1, y1), (x0, y1), (x0, y0)]
                # apex of the pocket sits toward the center: the four points meet in the middle
                apex = (qx * (g + (s - g) * 0.32), qy * (g + (s - g) * 0.32))
                for i in range(4):
                    a, b = corners[i], corners[(i + 1) % len(corners)]
                    paper.face([apex, a, b], B, 0.8 + 0.28 * facing(apex, a, b, L))
                for c in corners:  # ridge lines
                    ImageDraw.Draw(paper.rgb).line(poly([apex, c]), fill=shade(B, 1.18), width=2)
        return 4.0
    raise ValueError(f"state must be 1..{STATES}, got {state}")


# ---------------------------------------------------------------- scene

def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (8 x 8; no numpy in the lock)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def perspective_coeffs(src: list[Pt], dst: list[Pt]) -> list[float]:
    """Coefficients for Image.transform(PERSPECTIVE): maps output pixel (dst) to input pixel (src)."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    return _solve(a, b)


def place(p: Params, size: tuple[int, int]) -> list[Pt]:
    """Where the paper canvas corners land on the output image."""
    w, h = size
    half = h * 0.31 * p.scale * (SPAN / 2)  # the 2-unit sheet spans 0.62 of the height at scale 1
    cx, cy = w / 2 + p.offset[0] * h, h / 2 + p.offset[1] * h
    t = math.radians(p.rotation)
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):  # canvas corners, y down
        x, y = sx * half, sy * half
        x, y = x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)
        # camera tilted toward the far (top) edge: the near edge is wider, depth is foreshortened
        k = 1 + p.tilt * (y / half) + p.tilt_x * (x / half)
        out.append((cx + x * k, cy + y * (1 - p.tilt * 0.3)))
    return out


def felt(rng: random.Random, p: Params, size: tuple[int, int]) -> Image.Image:
    base = Image.new("RGB", size, p.felt)
    fine = level(noise(rng, size, 1, 0.6), 0.86, 1.0)
    coarse = level(noise(rng, size, 24, 8), 0.9, 1.0)
    tex = ImageChops.multiply(fine, coarse)
    return ImageChops.multiply(base, Image.merge("RGB", (tex, tex, tex)))


def falloff(p: Params, size: tuple[int, int]) -> Image.Image:
    """Multiplier image: 1.0 under the light, darker toward the far corners."""
    w, h = size
    g = Image.radial_gradient("L")  # 256 x 256, 0 at the center, 255 at the rim
    big = g.resize((w * 2, h * 2), Image.BICUBIC)
    cx, cy = int(w * p.falloff_center[0]), int(h * p.falloff_center[1])
    crop = big.crop((w - cx, h - cy, 2 * w - cx, 2 * h - cy))
    return crop.point(lambda v: int(255 * max(0.0, 1 - p.falloff * (v / 255) ** 1.4)))


def apply_h(c: list[float], pt: Pt) -> Pt:
    """Apply a perspective transform given as 8 coefficients."""
    x, y = pt
    d = c[6] * x + c[7] * y + 1
    return ((c[0] * x + c[1] * y + c[2]) / d, (c[3] * x + c[4] * y + c[5]) / d)


def hand_layer(p: Params, corners: list[Pt], size: tuple[int, int], rng: random.Random) -> tuple[Image.Image, Image.Image]:
    """A skin-toned blob with fingers reaching over one edge of the paper. corners is the object
    outline on the output image. Returns (rgb, alpha)."""
    hd = p.hand or {}
    i = hd["edge"] % len(corners)
    a, b = corners[i], corners[(i + 1) % len(corners)]
    cx = sum(c[0] for c in corners) / len(corners)
    cy = sum(c[1] for c in corners) / len(corners)
    t = hd["along"]
    ex, ey = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
    ox, oy = ex - cx, ey - cy  # outward from the paper center
    n = math.hypot(ox, oy) or 1.0
    ox, oy = ox / n, oy / n
    side = math.hypot(b[0] - a[0], b[1] - a[1])
    side = max(side, size[1] * 0.3)
    reach = hd["reach"] * side * 0.42  # how far fingertips come in past the paper edge, in px
    alpha = Image.new("L", size, 0)
    d = ImageDraw.Draw(alpha)
    palm_r = size[1] * 0.085  # hands do not shrink with small folds
    px_, py_ = ex + ox * palm_r * 1.25, ey + oy * palm_r * 1.25
    d.ellipse([px_ - palm_r, py_ - palm_r * 0.85, px_ + palm_r, py_ + palm_r * 0.85], fill=255)
    tx, ty = -oy, ox  # along the edge
    fingers = hd["fingers"]
    for f in range(fingers):
        off = (f - (fingers - 1) / 2) * palm_r * 0.36
        bx, by = px_ + tx * off, py_ + ty * off
        fx, fy = ex - ox * reach + tx * off * 0.9, ey - oy * reach + ty * off * 0.9
        d.line([(bx, by), (fx, fy)], fill=255, width=int(palm_r * 0.36))
        r = palm_r * 0.18
        d.ellipse([fx - r, fy - r, fx + r, fy + r], fill=255)
    alpha = alpha.filter(ImageFilter.GaussianBlur(2.2))
    skin = Image.new("RGB", size, tuple(hd["skin"]))
    tex = level(noise(rng, size, 6, 3), 0.9, 1.0)
    skin = ImageChops.multiply(skin, Image.merge("RGB", (tex, tex, tex)))
    # simple roundness: darker toward the outline
    inner = alpha.filter(ImageFilter.GaussianBlur(palm_r * 0.25))
    skin = ImageChops.multiply(skin, Image.merge("RGB", [level(inner, 0.7, 1.05)] * 3))
    return skin, alpha


def compose(state: int, p: Params, size: tuple[int, int] = SIZE, scene_seed: int = 0) -> Image.Image:
    rng = random.Random(scene_seed)
    light = light_dir(p.light_angle)
    paper = Paper(random.Random(p.paper_seed + 1), light)
    height = draw_state(state, paper)
    paper.texture(p.paper_seed)

    corners = place(p, size)
    src = [(0, 0), (PS, 0), (PS, PS), (0, PS)]
    coeffs = perspective_coeffs(src, corners)
    rgb = paper.rgb.transform(size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    alpha = paper.alpha.transform(size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)

    img = felt(rng, p, size)
    # drop shadow, away from the light; taller objects cast longer, softer shadows
    sdx, sdy = -light[0] * 6 * height, light[1] * 6 * height
    sh = ImageChops.offset(alpha, int(sdx), int(sdy)).filter(ImageFilter.GaussianBlur(5 + 3 * height))
    sh = sh.point(lambda v: int(v * p.shadow))
    img = Image.composite(Image.new("RGB", size, (6, 6, 8)), img, sh)
    # contact shadow right at the edge
    contact = alpha.filter(ImageFilter.GaussianBlur(2)).point(lambda v: int(v * 0.35))
    img = Image.composite(Image.new("RGB", size, (0, 0, 0)), img, contact)
    img = Image.composite(rgb, img, alpha)

    if p.hand:
        fwd = perspective_coeffs(corners, src)  # paper canvas pixel -> output pixel
        outline = [apply_h(fwd, px(q)) for q in OUTLINES[state]]
        skin, ha = hand_layer(p, outline, size, rng)
        hs = ImageChops.offset(ha, int(sdx * 1.6), int(sdy * 1.6)).filter(ImageFilter.GaussianBlur(14))
        img = Image.composite(Image.new("RGB", size, (0, 0, 0)), img, hs.point(lambda v: int(v * 0.45)))
        img = Image.composite(skin, img, ha)

    fall = falloff(p, size)
    img = ImageChops.multiply(img, Image.merge("RGB", (fall, fall, fall)))
    img = ImageChops.multiply(img, Image.new("RGB", size, p.tint))
    if p.light_gain != 1.0:
        img = img.point(lambda v: min(255, int(v * p.light_gain)))
    sensor = level(noise(rng, size, 1), 0.96, 1.0)
    img = ImageChops.multiply(img, Image.merge("RGB", (sensor, sensor, sensor)))
    if p.blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(p.blur))
    return img


def clean_params(state: int, seed: int) -> Params:
    """The reference look: centered, square to the camera, a gentle tilt, standard light."""
    return Params(paper_seed=seed * 100 + state)


def jitter_params(state: int, seed: int, i: int, hand_rate: float = 0.3) -> Params:
    """Deterministic random variant i of a state."""
    rng = random.Random(f"fold-{seed}-{state}-{i}")
    hand = None
    if rng.random() < hand_rate:
        hand = {
            "edge": rng.randrange(4),
            "along": rng.uniform(0.25, 0.75),
            "reach": rng.uniform(0.05, 0.22),
            "fingers": rng.choice([2, 3, 4]),
            "skin": list(rng.choice(SKIN)),
        }
    warm = rng.uniform(-1, 1)
    return Params(
        rotation=rng.uniform(-180, 180),
        scale=rng.uniform(0.75, 1.15),
        offset=(rng.uniform(-0.18, 0.18), rng.uniform(-0.08, 0.08)),
        tilt=rng.uniform(0.0, 0.14),
        tilt_x=rng.uniform(-0.05, 0.05),
        light_angle=rng.uniform(60, 210),
        light_gain=rng.uniform(0.85, 1.15),
        falloff=rng.uniform(0.12, 0.38),
        falloff_center=(rng.uniform(0.2, 0.8), rng.uniform(0.15, 0.7)),
        tint=(255, int(248 + 6 * warm), int(240 + 14 * warm)),
        felt=(rng.randint(30, 48), rng.randint(32, 50), rng.randint(34, 54)),
        blur=rng.choice([0.0, 0.0, rng.uniform(0.4, 1.4)]),
        shadow=rng.uniform(0.35, 0.65),
        hand=hand,
        paper_seed=seed * 1000 + state * 37 + i,
    )


def render(state: int, seed: int = 7, variant: int | None = None, size: tuple[int, int] = SIZE,
           hand_rate: float = 0.3) -> tuple[Image.Image, Params]:
    """variant None is the clean reference render; an int is a jittered variant."""
    if not 1 <= state <= STATES:
        raise ValueError(f"state must be 1..{STATES}")
    p = clean_params(state, seed) if variant is None else jitter_params(state, seed, variant, hand_rate)
    scene = seed * 7919 + state * 101 + (-1 if variant is None else variant)
    return compose(state, p, size, scene), p


def to_jpeg(img: Image.Image, quality: int = 88) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def write_set(out: Path, n: int, seed: int, hand_rate: float = 0.3, size: tuple[int, int] = SIZE,
              start: int = 0, clean: bool = True) -> dict:
    """Write clean and jittered renders of all 8 states; returns the manifest."""
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"synthetic": True, "seed": seed, "size": list(size), "hand_rate": hand_rate,
                      "note": "Pillow drawings, not photos. Re-test every result on real footage.",
                      "images": []}
    for state in range(1, STATES + 1):
        variants: list[int | None] = ([None] if clean else []) + list(range(start, start + n))
        for v in variants:
            img, p = render(state, seed, v, size, hand_rate)
            name = f"state{state}_clean.jpg" if v is None else f"state{state}_v{v:02d}.jpg"
            (out / name).write_bytes(to_jpeg(img))
            manifest["images"].append({"file": name, "state": state, "variant": v,
                                       "title": TITLES[state], "params": asdict(p)})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--n", type=int, default=6, help="jittered variants per state")
    ap.add_argument("--start", type=int, default=0, help="first variant index (held-out sets use a different range)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--hand-rate", type=float, default=0.3, help="share of variants with a hand over an edge")
    ap.add_argument("--no-clean", action="store_true", help="skip the clean reference renders")
    args = ap.parse_args(argv)
    m = write_set(args.out, args.n, args.seed, args.hand_rate, start=args.start, clean=not args.no_clean)
    print(f"wrote {len(m['images'])} synthetic images to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

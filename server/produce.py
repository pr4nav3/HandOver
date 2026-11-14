"""Course production: edited tutorial videos made from a lesson's cut steps, automatically and re-renderable.

Reads clips/NN.mp4 (with any voiceover mix), captions/NN.vtt and frames/NN.jpg, never changes them, and writes:

  clips_produced/NN.mp4   one edited clip per step: title card, step label, progress bar, slow push-in toward the
                          action region, a highlight ring at the key moment, optional burned captions, audio at -16 LUFS
  clips_produced/NN.vtt   that clip's captions, shifted to its timeline (soft captions)
  produced/course.mp4     intro card, every produced step with 300 ms crossfades, outro card
  produced/course.vtt     soft captions for the whole course
  produced/chapters.vtt   one chapter per step
  produced/cover.jpg      title over the best frame
  produced/assist.json    action regions and key moments (from rubric.json, Claude, or none), reused by re-renders

The style lives in lesson.json "production" (see STYLE_DEFAULTS and server/docs/production.md); produce() merges a
passed style into it, renders into a temp folder and swaps the result in only when everything succeeded.

All text is drawn with Pillow into PNGs with alpha (this ffmpeg has no drawtext), then composited by ffmpeg.

    python -m server.produce lessons/<id> [--no-zoom] [--no-cards] [--burn-captions] [--theme NAME] [--steps 2,3]

Settings: HANDOVER_PRODUCE_MODEL (default claude-haiku-5-5), HANDOVER_PRODUCE_JOBS (default 3, at most 3),
HANDOVER_PRODUCE_FONT (a .ttf or .ttc path; default the system San Francisco font). HANDOVER_NO_NETWORK=1 makes
no Claude call. ANTHROPIC_API_KEY comes from the environment or <repo>/.env and is never printed.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

from server import config, teach

log = logging.getLogger("handover.produce")

REPO = teach.REPO
Progress = Callable[[str, str], None]


def noop(status: str, message: str) -> None:
    pass


# ---------------------------------------------------------------- settings

_SETTINGS: dict[str, tuple[str, Any, tuple]] = {
    "HANDOVER_PRODUCE_MODEL": ("str", "claude-haiku-5-5", ()),
    "HANDOVER_PRODUCE_JOBS": ("int", 3, (1, 3)),
    "HANDOVER_PRODUCE_FONT": ("str", None, ()),
}


def _setting(name: str):
    """config.get once the name is registered there; until then the defaults above."""
    try:
        return config.get(name)
    except KeyError:
        kind, default, extra = _SETTINGS[name]
        if kind == "int":
            return config.env_int(name, default, *extra)
        return config.env_str(name, default)


def produce_model() -> str:
    return str(_setting("HANDOVER_PRODUCE_MODEL"))


def max_jobs() -> int:
    return max(1, min(3, int(_setting("HANDOVER_PRODUCE_JOBS"))))


def _no_network() -> bool:
    return bool(config.get("HANDOVER_NO_NETWORK"))


# ---------------------------------------------------------------- style

CARD_S = 1.2          # title card length
XFADE_S = 0.3         # card into clip, and step into step in the course
INTRO_S = 2.0
OUTRO_S = 2.5
LABEL_S = 2.5         # step label (lower third) on screen
LABEL_IN_S = 0.2      # it appears this long after the clip starts
MOVE_S = 0.35         # fades and rises of text
RING_S = 1.0
RING_IN_S = 0.3
RING_OUT_S = 0.3
MAX_ZOOM = 1.3
CENTER_ZOOM = 1.08    # gentle push-in when no action region is known
ZOOM_MARGIN = 0.06    # room kept around the action region on every side, as a fraction of the frame
ZOOM_HOLD = 0.85      # the push-in reaches its end at this fraction of the clip and holds
LUFS = -16
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

TITLE_CARDS = ("card", "overlay", "off")
STYLE_DEFAULTS: dict[str, Any] = {
    "theme": "system",
    "title_cards": "card",
    "zoom": True,
    "highlight": True,
    "burn_captions": False,  # players already show captions/NN.vtt; burn for exports and social clips
    "accent": None,          # "#RRGGBB"; None uses the theme's accent
}

# Colors from apps/design/THEMES.md, per look: (paper, raised, ink, ink2 alpha, accent, onAccent).
_LOOKS: dict[str, dict[str, tuple]] = {
    "system": {"light": ("#F0F1F2", "#FBFBFC", "#1A1B1E", 0.70, "#3E5FD9", "#FFFFFF"),
               "dark": ("#131416", "#1D1E21", "#EDEEF0", 0.68, "#8AA8FF", "#0E1630")},
    "night": {"dark": ("#000000", "#0F0F11", "#F2F2F4", 0.66, "#8AA8FF", "#0E1630")},
    "highContrast": {"light": ("#FFFFFF", "#F2F2F4", "#000000", 0.84, "#0030C0", "#FFFFFF"),
                     "dark": ("#000000", "#1A1A1C", "#FFFFFF", 0.86, "#ADC4FF", "#00102E")},
    "ivory": {"light": ("#F4F1EA", "#FCFBF7", "#221E18", 0.70, "#255EA8", "#FFFFFF"),
              "dark": ("#1A1815", "#24211D", "#EFEAE0", 0.68, "#95B7EE", "#0E1A30")},
    "dim": {"dark": ("#1F2227", "#272A30", "#E1E4E8", 0.72, "#93ACF2", "#101830")},
    "grain": {"light": ("#EEEDE9", "#FAFAF8", "#1C1B19", 0.72, "#34519F", "#FFFFFF"),
              "dark": ("#171716", "#21211F", "#EEEDEA", 0.70, "#9DB1F2", "#111A33")},
    "newsprint": {"light": ("#E8E6E1", "#F5F4F0", "#141414", 0.74, "#A3221E", "#FFFFFF")},
    "chalkboard": {"dark": ("#1D2A25", "#24332D", "#EEF2EC", 0.74, "#F0E19A", "#2A2600")},
    "harbor": {"light": ("#ECF0F1", "#F9FBFB", "#15202A", 0.72, "#0F6680", "#FFFFFF"),
               "dark": ("#0F1619", "#172024", "#E6EEF1", 0.70, "#6CC4DB", "#06222B")},
    "sage": {"light": ("#EEF1EC", "#FAFBF8", "#1A211B", 0.72, "#3E6B48", "#FFFFFF"),
             "dark": ("#141814", "#1C221C", "#E7EEE6", 0.70, "#9CCB9F", "#10241A")},
    "clay": {"light": ("#F3EEEA", "#FCFAF8", "#241B17", 0.72, "#A8452A", "#FFFFFF"),
             "dark": ("#1B1513", "#251D1A", "#F2E9E4", 0.70, "#F0A07E", "#2E1208")},
    "nocturne": {"dark": ("#0E1221", "#151A2D", "#E6E9F5", 0.70, "#9AAEFF", "#101640")},
    "mono": {"light": ("#FFFFFF", "#F6F6F6", "#000000", 0.66, "#000000", "#FFFFFF"),
             "dark": ("#000000", "#121212", "#FFFFFF", 0.68, "#FFFFFF", "#000000")},
    "matte": {"light": ("#E7E6E2", "#F1F0EC", "#1E1E1E", 0.74, "#2E2E2E", "#F1F0EC")},
}
_ALIASES = {"dark": "system", "light": "system-light"}
# "<id>" uses the theme's dark look when it has one (video is watched against black), "<id>-light" and
# "<id>-dark" pick a look.
THEME_NAMES: tuple[str, ...] = tuple(sorted(
    list(_LOOKS) + [f"{k}-{look}" for k, looks in _LOOKS.items() if len(looks) == 2 for look in looks]))
CAPTION_FILL = (0, 0, 0, 184)   # captionFill: black at 72% in every theme
CAPTION_INK = (255, 255, 255, 255)


@dataclass(frozen=True)
class Theme:
    name: str
    light: bool
    bg: tuple            # paper: card base and outro, RGB
    panel: tuple         # raised, translucent: the step label, RGBA
    text: tuple          # ink, RGBA
    secondary: tuple     # ink2, RGBA
    accent: tuple        # RGB
    on_accent: tuple     # RGB
    veil: tuple          # paper, translucent, laid over a blurred frame behind card text, RGBA
    track: tuple         # progress bar track, RGBA


def _rgb(hex_color: str) -> tuple:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _theme(theme_id: str, look: str, accent: Optional[str]) -> Theme:
    paper, raised, ink, ink2, acc, on_acc = _LOOKS[theme_id][look]
    p, r, k = _rgb(paper), _rgb(raised), _rgb(ink)
    light = look == "light"
    return Theme(f"{theme_id}-{look}", light, p, (*r, 224), (*k, 255), (*k, int(round(255 * ink2))),
                 _rgb(accent or acc), _rgb(on_acc), (*p, 204 if light else 184), (*k, 56))


def _split(name: str) -> tuple[str, Optional[str]]:
    name = _ALIASES.get(name, name)
    base, _, look = name.partition("-")
    return base, (look or None)


def card_theme(style: dict) -> Theme:
    """Colors for full-frame cards (title card, intro, outro, cover): the chosen look of the theme."""
    base, look = _split(style["theme"])
    looks = _LOOKS[base]
    look = look if look in looks else ("dark" if "dark" in looks else "light")
    return _theme(base, look, style.get("accent"))


def overlay_theme(style: dict) -> Theme:
    """Colors for things drawn over the video (step label, progress bar, ring): the dark look when the theme has
    one, as the apps force dark controls over video; always-light themes keep their light look."""
    base, _ = _split(style["theme"])
    looks = _LOOKS[base]
    return _theme(base, "dark" if "dark" in looks else "light", style.get("accent"))


_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_style(raw: Optional[dict]) -> dict:
    """A clean style dict: known keys only, bad values replaced by defaults. Booleans for title_cards are read as
    card (true) or off (false); "dark" and "light" are read as system and system-light."""
    out = dict(STYLE_DEFAULTS)
    raw = raw if isinstance(raw, dict) else {}
    theme = _ALIASES.get(str(raw.get("theme")), raw.get("theme"))
    if theme in THEME_NAMES:
        out["theme"] = theme
    tc = raw.get("title_cards")
    if isinstance(tc, bool):
        out["title_cards"] = "card" if tc else "off"
    elif tc in TITLE_CARDS:
        out["title_cards"] = tc
    for key in ("zoom", "highlight", "burn_captions"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    if isinstance(raw.get("accent"), str) and _HEX.match(raw["accent"]):
        out["accent"] = raw["accent"].upper()
    return out


# ---------------------------------------------------------------- fonts and text

FONT_CANDIDATES = (
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
WEIGHTS = {"regular": 400, "medium": 510, "semibold": 590, "bold": 700}
_font_cache: dict[tuple, ImageFont.FreeTypeFont] = {}


def font_path() -> Optional[str]:
    override = _setting("HANDOVER_PRODUCE_FONT")
    if override and Path(str(override)).is_file():
        return str(override)
    return next((p for p in FONT_CANDIDATES if Path(p).is_file()), None)


def font(size: float, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """The system UI font at a pixel size. With the variable San Francisco font the weight and optical size axes
    are set, so large titles get the Display letterforms and tighter spacing."""
    size = max(8, int(round(size)))
    key = (size, weight)
    if key in _font_cache:
        return _font_cache[key]
    path = font_path()
    if path is None:
        f = ImageFont.load_default(size)
    else:
        f = ImageFont.truetype(path, size)
        try:
            axes = f.get_variation_axes()
            values = []
            for axis in axes:
                name = axis["name"].decode() if isinstance(axis["name"], bytes) else str(axis["name"])
                if name == "Weight":
                    values.append(WEIGHTS[weight])
                elif name == "Optical Size":
                    values.append(max(axis["minimum"], min(axis["maximum"], size)))
                else:
                    values.append(axis["default"])
            f.set_variation_by_axes(values)
        except (OSError, AttributeError, KeyError):
            pass  # not a variable font
    _font_cache[key] = f
    return f


def text_width(text: str, f: ImageFont.FreeTypeFont) -> float:
    return f.getlength(text)


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: float, max_lines: int = 2) -> list[str]:
    """Greedy word wrap. The last allowed line ends with an ellipsis if the text does not fit."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for i, w in enumerate(words):
        trial = f"{cur} {w}".strip()
        if text_width(trial, f) <= max_w or not cur:
            cur = trial
            continue
        lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            rest = " ".join(words[i:])
            lines[-1] = _ellipsize(lines[-1] + " " + rest, f, max_w)
            return lines
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [_ellipsize(" ".join(lines[max_lines - 1:]), f, max_w)]
    return [_ellipsize(line, f, max_w) for line in lines]


def _ellipsize(text: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    if text_width(text, f) <= max_w:
        return text
    while text and text_width(text + "\u2026", f) > max_w:
        text = text[:-1].rstrip()
    return text + "\u2026"


def fit_title(text: str, weight: str, size: float, max_w: float, max_lines: int = 2,
              min_scale: float = 0.7) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest font from size down to size * min_scale at which text wraps into max_lines without cutting."""
    s = size
    while True:
        f = font(s, weight)
        lines = wrap(text, f, max_w, max_lines)
        if not any(line.endswith("\u2026") for line in lines) or s <= size * min_scale:
            return f, balance(lines, f, max_w)
        s -= max(1.0, size * 0.05)


def balance(lines: list[str], f: ImageFont.FreeTypeFont, max_w: float) -> list[str]:
    """Two wrapped lines re-split where the longer line is shortest, so a title never ends on one stray word."""
    if len(lines) != 2 or lines[-1].endswith("\u2026"):
        return lines
    words = " ".join(lines).split()
    best = lines
    best_w = max(text_width(x, f) for x in lines)
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        w = max(text_width(a, f), text_width(b, f))
        if w <= max_w and w < best_w:
            best, best_w = [a, b], w
    return best


def _line_height(f: ImageFont.FreeTypeFont, factor: float = 1.18) -> int:
    return int(round(f.size * factor))


def draw_lines(draw: ImageDraw.ImageDraw, lines: Sequence[str], f: ImageFont.FreeTypeFont, fill: tuple,
               x: float, y_top: float, align: str = "left", line_h: Optional[int] = None) -> float:
    """Draws lines with their first baseline at y_top + ascent. x is the left edge, or the center when align is
    center. Returns the y below the last line."""
    lh = line_h or _line_height(f)
    ascent = f.getmetrics()[0]
    y = y_top
    for line in lines:
        anchor = "ms" if align == "center" else "ls"
        draw.text((x, y + ascent), line, font=f, fill=fill, anchor=anchor)
        y += lh
    return y


# ---------------------------------------------------------------- overlay images

@dataclass(frozen=True)
class Layout:
    width: int
    height: int

    @property
    def u(self) -> float:
        """One design pixel: layouts are drawn for 1080 px on the short side and scale from there."""
        return min(self.width, self.height) / 1080

    @property
    def margin(self) -> int:
        return int(round(56 * self.u))

    @property
    def portrait(self) -> bool:
        return self.height > self.width


SS = 3  # supersampling for shapes; Pillow's own antialiasing on rounded rectangles is rough


def _rounded(size: tuple[int, int], radius: float, fill: tuple) -> Image.Image:
    w, h = size
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=radius * SS, fill=fill)
    return big.resize((w, h), Image.LANCZOS)


def _panel(size: tuple[int, int], radius: float, theme: Theme) -> Image.Image:
    """A raised panel with a hairline edge (ink at 10 percent in dark looks, 9 percent in light ones)."""
    w, h = size
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    edge = (*theme.text[:3], 23 if theme.light else 26)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=radius * SS, fill=theme.panel,
                                          outline=edge, width=SS)
    return big.resize((w, h), Image.LANCZOS)


def ring_frame(region_w: int, region_h: int, layout: Layout, accent: tuple, scale: float = 1.0,
               alpha: float = 1.0) -> Image.Image:
    """A rounded rectangle outline around a region, drawn at scale about its center on a fixed canvas. The canvas is
    the region plus ring_pad on every side, so every frame of the animation has the same size and position."""
    u = layout.u
    pad = ring_pad(layout)
    stroke = max(2.0, 4 * u)
    w, h = region_w + 2 * pad, region_h + 2 * pad
    big = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    gap = 10 * u  # ring sits this far outside the region
    rw, rh = (region_w + 2 * gap) * scale, (region_h + 2 * gap) * scale
    cx, cy = w / 2, h / 2
    box = [(cx - rw / 2) * SS, (cy - rh / 2) * SS, (cx + rw / 2) * SS, (cy + rh / 2) * SS]
    radius = min(22 * u, rw / 4, rh / 4) * SS
    a = max(0.0, min(1.0, alpha))
    contour = stroke + 2 * u
    d.rounded_rectangle(box, radius=radius, outline=(0, 0, 0, int(90 * a)), width=max(1, int(contour * SS)))
    inset = (contour - stroke) / 2 * SS
    inner = [box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset]
    d.rounded_rectangle(inner, radius=max(0.0, radius - inset), outline=(*accent, int(255 * a)),
                        width=max(1, int(stroke * SS)))
    return big.resize((w, h), Image.LANCZOS)


def ring_pad(layout: Layout) -> int:
    return int(math.ceil(18 * layout.u))


def _ease_out(p: float) -> float:
    return 1 - (1 - max(0.0, min(1.0, p))) ** 3


def ring_frames(region_w: int, region_h: int, layout: Layout, accent: tuple, fps: float) -> list[Image.Image]:
    """RING_S of animation: a gentle scale-in from 92 percent with a fade, a hold, then a fade out."""
    n = max(1, int(round(RING_S * fps)))
    n_in, n_out = max(1, int(round(RING_IN_S * fps))), max(1, int(round(RING_OUT_S * fps)))
    frames = []
    for i in range(n):
        if i < n_in:
            e = _ease_out((i + 1) / n_in)
            scale, alpha = 0.92 + 0.08 * e, e
        elif i >= n - n_out:
            scale, alpha = 1.0, 1 - _ease_out((i - (n - n_out) + 1) / n_out)
        else:
            scale, alpha = 1.0, 1.0
        frames.append(ring_frame(region_w, region_h, layout, accent, scale, alpha))
    return frames


def lower_third(n: int, total: int, title: str, layout: Layout, theme: Theme) -> Image.Image:
    """The step label: "Step N of M" over the title on a translucent rounded panel."""
    u = layout.u
    pad_x, pad_y = int(28 * u), int(20 * u)
    max_w = int((0.8 if layout.portrait else 0.5) * layout.width) - 2 * pad_x
    f_label = font(26 * u, "semibold")
    f_title, lines = fit_title(title, "semibold", 40 * u, max_w, 2, 0.8)
    label = f"Step {n} of {total}"
    gap = int(6 * u)
    lh = _line_height(f_title, 1.16)
    text_w = max([text_width(label, f_label)] + [text_width(x, f_title) for x in lines])
    w = int(math.ceil(text_w)) + 2 * pad_x
    h = pad_y + _line_height(f_label) + gap + lh * len(lines) + pad_y - int(4 * u)
    img = _panel((w, h), 18 * u, theme)
    d = ImageDraw.Draw(img)
    y = draw_lines(d, [label], f_label, (*theme.accent, 255), pad_x, pad_y)
    draw_lines(d, lines, f_title, theme.text, pad_x, y + gap, line_h=lh)
    return img


def caption_image(lines: Sequence[str], layout: Layout) -> Image.Image:
    """A caption: white text on a translucent dark rounded bar, centered lines."""
    u = layout.u
    f = caption_font(layout)
    pad_x, pad_y = int(20 * u), int(10 * u)
    lh = _line_height(f, 1.22)
    w = int(math.ceil(max(text_width(x, f) for x in lines))) + 2 * pad_x
    h = lh * len(lines) + 2 * pad_y
    img = _rounded((w, h), 8 * u, CAPTION_FILL)
    draw_lines(ImageDraw.Draw(img), lines, f, CAPTION_INK, w / 2, pad_y + int(1 * u), "center", lh)
    return img


def caption_font(layout: Layout) -> ImageFont.FreeTypeFont:
    return font(36 * layout.u, "semibold")


def caption_max_width(layout: Layout) -> int:
    return int((0.86 if layout.portrait else 0.62) * layout.width)


def progress_images(layout: Layout, theme: Theme) -> tuple[Image.Image, Image.Image]:
    """(track, fill), both the full frame width and progress_height tall."""
    h = progress_height(layout)
    return (Image.new("RGBA", (layout.width, h), theme.track), Image.new("RGBA", (layout.width, h), (*theme.accent, 255)))


def progress_height(layout: Layout) -> int:
    return max(2, int(round(4 * layout.u)))


def blurred_backdrop(frame: Path, layout: Layout, theme: Theme) -> Image.Image:
    """The frame scaled to fill, heavily blurred and veiled with the theme color, as RGB."""
    img = Image.open(frame).convert("RGB")
    img = _cover(img, layout.width, layout.height)
    small = img.resize((max(1, layout.width // 8), max(1, layout.height // 8)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(6))
    img = small.resize((layout.width, layout.height), Image.BICUBIC).convert("RGBA")
    img.alpha_composite(Image.new("RGBA", img.size, theme.veil))
    return img.convert("RGB")


def title_card(frame: Path, title_size: tuple[int, int], layout: Layout, theme: Theme) -> tuple[Image.Image, int]:
    """The step title card background: theme paper with a small sharp thumbnail of the first frame (12 px corners,
    hairline edge) centered above where the title block goes. Returns the image (RGB) and the title block's top y,
    so the thumbnail and the title sit together as one centered group."""
    u = layout.u
    img = solid_backdrop(layout, theme).convert("RGBA")
    src = Image.open(frame).convert("RGB")
    thumb_w = int(round(layout.width * (0.42 if layout.portrait else 0.2)))
    thumb_h = max(1, int(round(thumb_w * src.height / src.width)))
    gap = int(round(36 * u))
    top = (layout.height - (thumb_h + gap + title_size[1])) // 2
    x = (layout.width - thumb_w) // 2
    pic = src.resize((thumb_w, thumb_h), Image.LANCZOS).convert("RGBA")
    pic.putalpha(_rounded((thumb_w, thumb_h), 12 * u, (255, 255, 255, 255)).getchannel("A"))
    edge = (*theme.text[:3], 23 if theme.light else 26)
    img.alpha_composite(_rounded((thumb_w + 2, thumb_h + 2), 12 * u + 1, edge), (x - 1, top - 1))
    img.alpha_composite(pic, (x, top))
    return img.convert("RGB"), top + thumb_h + gap


def solid_backdrop(layout: Layout, theme: Theme) -> Image.Image:
    return Image.new("RGB", (layout.width, layout.height), theme.bg)


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((max(w, int(round(img.width * scale))), max(h, int(round(img.height * scale)))), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def title_block(kicker: str, title: str, layout: Layout, theme: Theme, *, sub: str = "",
                title_size: float = 80, max_frac: float = 0.74) -> Image.Image:
    """Centered text block for cards: a small secondary line, the title (up to two lines), an optional subline.
    The kicker is not in the accent color: cards sit on a blurred frame of any color."""
    u = layout.u
    max_w = int(layout.width * (0.86 if layout.portrait else max_frac))
    f_k = font(34 * u, "semibold")
    f_t, lines = fit_title(title, "bold", title_size * u, max_w, 2 if not layout.portrait else 3)
    f_s = font(32 * u, "regular")
    lh = _line_height(f_t, 1.08)
    gap1, gap2 = int(14 * u), int(18 * u)
    h = (_line_height(f_k) + gap1 if kicker else 0) + lh * len(lines) + (gap2 + _line_height(f_s) if sub else 0)
    w = int(math.ceil(max([text_width(x, f_t) for x in lines] + [text_width(kicker, f_k), text_width(sub, f_s)])))
    w += int(8 * u)
    img = Image.new("RGBA", (w, h + int(8 * u)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0.0
    if kicker:
        y = draw_lines(d, [kicker], f_k, theme.secondary, w / 2, y, "center") + gap1
    y = draw_lines(d, lines, f_t, theme.text, w / 2, y, "center", lh)
    if sub:
        draw_lines(d, [sub], f_s, theme.secondary, w / 2, y + gap2, "center")
    return img


def check_mark(size: int, accent: tuple, ink: tuple) -> Image.Image:
    """A filled accent circle with a check, drawn supersampled."""
    big = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    s = size * SS
    d.ellipse((0, 0, s - 1, s - 1), fill=(*accent, 255))
    pts = [(0.28 * s, 0.52 * s), (0.44 * s, 0.67 * s), (0.73 * s, 0.36 * s)]
    d.line(pts, fill=ink, width=int(0.085 * s), joint="curve")
    for p in (pts[0], pts[-1]):
        r = 0.0425 * s
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=ink)
    return big.resize((size, size), Image.LANCZOS)


def outro_block(titles: Sequence[str], layout: Layout, theme: Theme) -> Image.Image:
    """"Lesson complete" with a check, then the numbered step list (two columns past six steps)."""
    u = layout.u
    f_h = font(64 * u, "bold")
    f_n = font(28 * u, "semibold")
    f_i = font(28 * u, "regular")
    shown = list(titles[:12])
    more = len(titles) - len(shown)
    cols = 2 if len(shown) > 6 and not layout.portrait else 1
    rows = math.ceil(len(shown) / cols)
    lh = _line_height(f_i, 1.5)
    num_w = int(text_width("12", f_n) + 18 * u)
    col_max = int(layout.width * (0.36 if cols == 2 else (0.8 if layout.portrait else 0.5)))
    col_w = min(col_max, num_w + int(math.ceil(max((text_width(t, f_i) for t in shown), default=0))) + int(4 * u))
    mark = int(64 * u)
    head_h = max(mark, _line_height(f_h))
    gap = int(44 * u)
    col_gap = int(48 * u)
    w = max(cols * col_w + (cols - 1) * col_gap, int(mark + 20 * u + text_width("Lesson complete", f_h)))
    h = head_h + gap + rows * lh + (lh if more else 0)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    head_w = mark + int(20 * u) + text_width("Lesson complete", f_h)
    hx = (w - head_w) / 2
    img.alpha_composite(check_mark(mark, theme.accent, (*theme.on_accent, 255)), (int(hx), int((head_h - mark) / 2)))
    d.text((hx + mark + 20 * u, head_h / 2), "Lesson complete", font=f_h, fill=theme.text, anchor="lm")
    list_w = cols * col_w + (cols - 1) * col_gap
    x0 = (w - list_w) / 2
    for i, title in enumerate(shown):
        c, r = divmod(i, rows)
        x = x0 + c * (col_w + col_gap)
        y = head_h + gap + r * lh
        d.text((x + num_w - 18 * u, y + lh / 2), str(i + 1), font=f_n, fill=(*theme.accent, 255), anchor="rm")
        d.text((x + num_w, y + lh / 2), _ellipsize(title, f_i, col_w - num_w), font=f_i, fill=theme.text,
               anchor="lm")
    if more:
        d.text((w / 2, head_h + gap + rows * lh + lh / 2), f"and {more} more", font=f_i, fill=theme.secondary,
               anchor="mm")
    return img


def cover_image(frame: Path, title: str, sub: str, layout: Layout, theme: Theme) -> Image.Image:
    """The cover: theme paper, the sharp frame as a rounded inset on one side, title and details beside it."""
    u = layout.u
    img = solid_backdrop(layout, theme).convert("RGBA")
    src = Image.open(frame).convert("RGB")
    if layout.portrait:
        inset_w = int(layout.width * 0.84)
        inset_h = int(inset_w * src.height / src.width)
        ix, iy = (layout.width - inset_w) // 2, int(layout.height * 0.12)
        text_x, text_y, max_w = layout.width * 0.08, iy + inset_h + 64 * u, layout.width * 0.84
    else:
        inset_w = int(layout.width * 0.5)
        inset_h = int(inset_w * src.height / src.width)
        ix, iy = int(layout.width - layout.margin * 1.6 - inset_w), (layout.height - inset_h) // 2
        text_x, max_w = layout.margin * 1.6, ix - layout.margin * 2.6
        text_y = None
    pic = src.resize((inset_w, inset_h), Image.LANCZOS).convert("RGBA")
    mask = _rounded((inset_w, inset_h), 24 * u, (255, 255, 255, 255)).getchannel("A")
    pic.putalpha(mask)
    edge = _rounded((inset_w + 2, inset_h + 2), 24 * u + 1, (255, 255, 255, 40))
    img.alpha_composite(edge, (ix - 1, iy - 1))
    img.alpha_composite(pic, (ix, iy))
    f_t, lines = fit_title(title, "bold", 72 * u, max_w, 3)
    f_s = font(30 * u, "regular")
    lh = _line_height(f_t, 1.08)
    block_h = lh * len(lines) + 22 * u + _line_height(f_s)
    if text_y is None:
        text_y = (layout.height - block_h) / 2
    d = ImageDraw.Draw(img)
    y = draw_lines(d, lines, f_t, theme.text, text_x, text_y, line_h=lh) + 22 * u
    draw_lines(d, [sub], f_s, theme.secondary, text_x, y)
    return img.convert("RGB")


# ---------------------------------------------------------------- captions

@dataclass
class Cue:
    start: float
    end: float
    text: str


_VTT_TIME = re.compile(r"(\d+:)?\d+:\d+(\.\d+)?")


def read_vtt(path: Path) -> list[Cue]:
    """Cues from a WebVTT file. Cue settings, ids and notes are ignored; a missing file gives no cues."""
    if not path.is_file():
        return []
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8", errors="replace").replace("\r", ""))
    for block in blocks:
        lines = [x for x in block.strip().split("\n") if x.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = (s.strip().split()[0] for s in line.split("-->", 1))
                try:
                    start, end = teach.parse_time(a), teach.parse_time(b)
                except ValueError:
                    break
                text = " ".join(" ".join(lines[i + 1:]).split())
                text = re.sub(r"<[^>]+>", "", text)
                if text and end > start:
                    cues.append(Cue(start, end, text))
                break
    return cues


def write_vtt(path: Path, cues: Sequence[Cue]) -> None:
    lines = ["WEBVTT", ""]
    for c in cues:
        lines += [f"{teach.fmt_vtt(c.start)} --> {teach.fmt_vtt(c.end)}", c.text.replace("-->", "to"), ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def caption_chunks(cues: Sequence[Cue], layout: Layout) -> list[tuple[float, float, list[str]]]:
    """Every cue as one or more pieces of at most two lines. A long cue is split by words, each piece getting a
    share of the cue's time proportional to its length."""
    f = caption_font(layout)
    max_w = caption_max_width(layout)
    out = []
    for c in cues:
        lines = wrap(c.text, f, max_w, max_lines=99)
        pieces = [lines[i:i + 2] for i in range(0, len(lines), 2)]
        total = sum(len(" ".join(p)) for p in pieces) or 1
        t = c.start
        for p in pieces:
            d = (c.end - c.start) * len(" ".join(p)) / total
            out.append((t, t + d, p))
            t += d
    return out


# ---------------------------------------------------------------- ffmpeg helpers

def ffmpeg() -> str:
    return teach._bin("ffmpeg")


def ffprobe() -> str:
    return teach._bin("ffprobe")


@dataclass
class Probe:
    width: int
    height: int
    fps: float
    duration: float
    audio: bool


def probe(path: Path) -> Probe:
    p = subprocess.run([ffprobe(), "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"could not read {path.name}: {p.stderr.strip()[-200:]}")
    data = json.loads(p.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError(f"{path.name} has no video stream")
    num, _, den = str(video.get("r_frame_rate") or "30/1").partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if not 1 <= fps <= 120:
        fps = 30.0
    return Probe(int(video["width"]), int(video["height"]), round(fps, 3),
                 float((data.get("format") or {}).get("duration") or 0.0),
                 any(s.get("codec_type") == "audio" for s in streams))


def run(cmd: list[str], timeout: float = 1800) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"ffmpeg failed ({p.returncode}):\n{tail}")


def loudness(path: Path) -> Optional[dict]:
    """First loudnorm pass: the measured values, or None when the audio is silent or unreadable."""
    p = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        f"loudnorm=I={LUFS}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr)
    if p.returncode != 0 or not m:
        return None
    try:
        got = json.loads(m.group(0))
        values = {k: float(got[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (ValueError, KeyError):
        return None
    if not all(math.isfinite(v) for v in values.values()) or values["input_i"] < -70:
        return None
    return values


def audio_chain(measured: Optional[dict], delay_s: float) -> str:
    """Audio filters for one step: -16 LUFS (two-pass linear when measured), 48 kHz stereo, delayed for the card."""
    if measured:
        norm = (f"loudnorm=I={LUFS}:TP=-1.5:LRA=11:measured_I={measured['input_i']:.2f}:"
                f"measured_TP={measured['input_tp']:.2f}:measured_LRA={measured['input_lra']:.2f}:"
                f"measured_thresh={measured['input_thresh']:.2f}:offset={measured['target_offset']:.2f}:linear=true,")
    else:
        norm = ""
    delay = f",adelay=delays={int(round(delay_s * 1000))}:all=1" if delay_s > 0 else ""
    return f"aresample=48000,{norm}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo{delay},apad"


def ease_out_expr(p: str) -> str:
    return f"(1-pow(1-{p},3))"


def ease_in_out_expr(p: str) -> str:
    return f"if(lt({p},0.5),4*pow({p},3),1-pow(-2*{p}+2,3)/2)"


def _ramp(start: float, length: float) -> str:
    return f"clip((t-{start:.3f})/{length:.3f},0,1)"


class Graph:
    """Collects ffmpeg inputs and filter chains; chains are joined with ";" into one -filter_complex."""

    def __init__(self) -> None:
        self.inputs: list[list[str]] = []
        self.chains: list[str] = []
        self._n = 0

    def input(self, *args: str) -> int:
        self.inputs.append(list(args))
        return len(self.inputs) - 1

    def still(self, path: Path, fps: float, seconds: float) -> int:
        return self.input("-loop", "1", "-framerate", f"{fps:g}", "-t", f"{seconds:.3f}", "-i", str(path))

    def label(self, prefix: str = "v") -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def add(self, chain: str) -> None:
        self.chains.append(chain)

    def overlay(self, base: str, k: int, start: float, seconds: float, x: str, y: str,
                fade_in: float = MOVE_S, fade_out: float = MOVE_S, pre: str = "") -> str:
        """Lays still input k over base from start for seconds, fading in and out. x and y may use t."""
        src, out = self.label("o"), self.label()
        fades = []
        if fade_in > 0:
            fades.append(f"fade=t=in:st=0:d={fade_in:.3f}:alpha=1")
        if fade_out > 0:
            fades.append(f"fade=t=out:st={max(0.0, seconds - fade_out):.3f}:d={fade_out:.3f}:alpha=1")
        chain = ",".join([f"[{k}:v]format=rgba", *([pre] if pre else []), *fades,
                          f"setpts=PTS-STARTPTS+{start:.3f}/TB"])
        self.add(f"{chain}[{src}]")
        self.add(f"[{base}][{src}]overlay=x='{x}':y='{y}':eval=frame:eof_action=pass[{out}]")
        return out

    def text(self) -> str:
        return ";".join(self.chains)


def zoom_filters(target: Optional[tuple[float, float, float, float]], width: int, height: int, seconds: float,
                 fps: float = 30.0, max_zoom: float = MAX_ZOOM) -> str:
    """A slow push-in with zoompan on a pre-scaled copy (up to 2x, at most 3840 px wide), so each frame's crop
    moves in steps of half a pixel or less and the motion stays smooth. Returns "" when the push-in would be tiny.

    The end zoom is the most that still keeps the action region plus ZOOM_MARGIN on every side in view, capped at
    max_zoom; with no region it is CENTER_ZOOM toward the center. Ease in-out on the clip clock (it), reaching
    the end at ZOOM_HOLD of the clip and holding there."""
    if target is None:
        z, cx, cy = min(CENTER_ZOOM, max_zoom), 0.5, 0.5
    else:
        x0, y0, x1, y1 = target
        z = min(max_zoom, 1 / (x1 - x0 + 2 * ZOOM_MARGIN), 1 / (y1 - y0 + 2 * ZOOM_MARGIN))
        cx = min(max((x0 + x1) / 2, 0.5 / z), 1 - 0.5 / z) if z > 1 else 0.5
        cy = min(max((y0 + y1) / 2, 0.5 / z), 1 - 0.5 / z) if z > 1 else 0.5
    if z < 1.02 or seconds < 1.0:
        return ""
    k = max(1.0, min(2.0, 3840 / max(width, height)))
    sw, sh = int(round(width * k / 2)) * 2, int(round(height * k / 2)) * 2
    e = ease_in_out_expr(f"clip(it/{max(0.5, seconds * ZOOM_HOLD):.3f},0,1)")
    zexpr = f"1+{z - 1:.4f}*({e})"
    xexpr = f"clip((0.5+{cx - 0.5:.4f}*({e}))*iw-iw/zoom/2,0,iw-iw/zoom)"
    yexpr = f"clip((0.5+{cy - 0.5:.4f}*({e}))*ih-ih/zoom/2,0,ih-ih/zoom)"
    return (f"scale={sw}:{sh}:flags=bicubic,zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1"
            f":s={width}x{height}:fps={fps:g}")


def end_zoom(target: Optional[tuple[float, float, float, float]], max_zoom: float = MAX_ZOOM) -> float:
    if target is None:
        return min(CENTER_ZOOM, max_zoom)
    x0, y0, x1, y1 = target
    return min(max_zoom, 1 / (x1 - x0 + 2 * ZOOM_MARGIN), 1 / (y1 - y0 + 2 * ZOOM_MARGIN))


FINAL_VF = teach.CLIP_VF


# ---------------------------------------------------------------- plans

@dataclass
class StepPlan:
    n: int
    total: int
    title: str
    clip: Path
    vtt: Path
    first_frame: Path            # written by prepare
    probe: Probe
    region: Optional[tuple[float, float, float, float]]   # normalized x0, y0, x1, y1
    key_time: Optional[float]    # seconds into the clip
    frac0: float                 # course progress at the start and end of this step
    frac1: float
    style: dict
    zoom: bool = True
    highlight: bool = True

    @property
    def card(self) -> bool:
        return self.style["title_cards"] == "card"

    @property
    def lead(self) -> float:
        """Seconds of the produced clip before the original clip is fully in."""
        return CARD_S - XFADE_S if self.card else 0.0

    @property
    def seconds(self) -> float:
        return self.lead + self.probe.duration


def ring_window(plan: StepPlan) -> Optional[tuple[float, float]]:
    """(start, end) of the highlight in clip time, or None when there is nothing honest to point at."""
    if not plan.highlight or plan.region is None or plan.probe.duration < RING_S + 0.4:
        return None
    x0, y0, x1, y1 = plan.region
    if x1 - x0 > 0.6 or y1 - y0 > 0.5 or (x1 - x0) * (y1 - y0) > 0.25:  # a big box points at nothing in particular
        return None
    key = plan.key_time if plan.key_time is not None else plan.probe.duration * 0.6
    start = min(max(0.3, key - 0.4), plan.probe.duration - RING_S - 0.1)
    return start, start + RING_S


def label_window(plan: StepPlan) -> Optional[tuple[float, float]]:
    if plan.style["title_cards"] == "overlay":
        return None  # the overlay title already names the step
    start = LABEL_IN_S if plan.card else 0.0
    end = min(start + LABEL_S, plan.probe.duration - 0.15)
    return (start, end) if end - start >= 1.0 else None


def region_px(plan: StepPlan) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = plan.region  # type: ignore[misc]
    w, h = plan.probe.width, plan.probe.height
    return int(x0 * w), int(y0 * h), int(math.ceil(x1 * w)), int(math.ceil(y1 * h))


# ---------------------------------------------------------------- one step

def prepare_step(plan: StepPlan, work: Path) -> dict:
    """Renders every overlay PNG the step needs into work and returns their paths and positions."""
    work.mkdir(parents=True, exist_ok=True)
    layout = Layout(plan.probe.width, plan.probe.height)
    theme, over = card_theme(plan.style), overlay_theme(plan.style)
    assets: dict[str, Any] = {}
    run([ffmpeg(), "-y", "-v", "error", "-i", str(plan.clip), "-frames:v", "1", "-q:v", "2", str(plan.first_frame)])
    if plan.style["title_cards"] in ("card", "overlay"):
        block = title_block(f"Step {plan.n}", plan.title, layout, theme if plan.card else over)
        block.save(work / "title.png")
        assets["title"] = (work / "title.png", block.size)
    if plan.card:
        card, title_y = title_card(plan.first_frame, assets["title"][1], layout, theme)
        card.save(work / "card.png")
        assets["card"], assets["title_y"] = work / "card.png", title_y
    if plan.style["title_cards"] == "overlay":
        Image.new("RGBA", (layout.width, layout.height), over.veil).save(work / "veil.png")
        assets["veil"] = work / "veil.png"
    if label_window(plan):
        lt = lower_third(plan.n, plan.total, plan.title, layout, over)
        lt.save(work / "label.png")
        assets["label"] = (work / "label.png", lt.size)
    win = ring_window(plan)
    if win:
        x0, y0, x1, y1 = region_px(plan)
        ring_dir = work / "ring"
        ring_dir.mkdir(exist_ok=True)
        for i, img in enumerate(ring_frames(x1 - x0, y1 - y0, layout, over.accent, plan.probe.fps)):
            img.save(ring_dir / f"{i:03d}.png")
        pad = ring_pad(layout)
        assets["ring"] = (ring_dir / "%03d.png", (x0 - pad, y0 - pad))
    track, fill = progress_images(layout, over)
    track.save(work / "track.png")
    fill.save(work / "fill.png")
    assets["track"], assets["fill"] = work / "track.png", work / "fill.png"
    caps = []
    if plan.style["burn_captions"]:
        for i, (a, b, lines) in enumerate(caption_chunks(read_vtt(plan.vtt), layout)):
            a, b = max(0.0, a), min(plan.probe.duration, b)
            if b - a < 0.2:
                continue
            img = caption_image(lines, layout)
            path = work / f"cap{i:02d}.png"
            img.save(path)
            caps.append((path, img.size, a, b))
    assets["captions"] = caps
    return assets


def step_graph(plan: StepPlan, assets: dict) -> Graph:
    """The ffmpeg inputs and filter graph for one produced step. Output labels: [vout] and [aout]."""
    g = Graph()
    layout = Layout(plan.probe.width, plan.probe.height)
    u, m = layout.u, layout.margin
    W, H, fps, D = plan.probe.width, plan.probe.height, plan.probe.fps, plan.probe.duration
    clip = g.input("-i", str(plan.clip))
    base = g.label()
    g.add(f"[{clip}:v]fps={fps:g},format=yuv420p,setsar=1[{base}]")

    if "ring" in assets:
        pattern, (rx, ry) = assets["ring"]
        start, _ = ring_window(plan)  # type: ignore[misc]
        k = g.input("-framerate", f"{fps:g}", "-start_number", "0", "-i", str(pattern))
        src, out = g.label("o"), g.label()
        g.add(f"[{k}:v]format=rgba,setpts=PTS-STARTPTS+{start:.3f}/TB[{src}]")
        g.add(f"[{base}][{src}]overlay=x={rx}:y={ry}:eof_action=pass[{out}]")
        base = out

    if plan.zoom:
        zf = zoom_filters(plan.region, W, H, D, fps)
        if zf:
            out = g.label()
            g.add(f"[{base}]{zf},format=yuv420p[{out}]")
            base = out

    rise = 12 * u
    if plan.style["title_cards"] == "overlay":
        hold = min(1.5, D - 0.3)
        k = g.still(assets["veil"], fps, hold)
        base = g.overlay(base, k, 0.0, hold, "0", "0", fade_in=0)
        path, (tw, th) = assets["title"]
        k = g.still(path, fps, hold)
        base = g.overlay(base, k, 0.0, hold, f"{(W - tw) // 2}", f"{(H - th) // 2}", fade_in=0)

    label_y = None
    win = label_window(plan)
    if win and "label" in assets:
        path, (lw, lh) = assets["label"]
        a, b = win
        label_y = H - m - lh
        k = g.still(path, fps, b - a)
        y = f"{label_y}+{rise:.1f}*(1-{ease_out_expr(_ramp(a, MOVE_S))})"
        base = g.overlay(base, k, a, b - a, f"{m}", y)

    for path, (cw, ch), a, b in assets.get("captions", []):
        y = H - m - ch
        if label_y is not None and win and a < win[1] and b > win[0] and not layout.portrait:
            y = label_y - int(16 * u) - ch
        k = g.still(path, fps, b - a)
        base = g.overlay(base, k, a, b - a, f"{(W - cw) // 2}", f"{y}", fade_in=0.15, fade_out=0.15)

    if plan.card:
        bg = g.still(assets["card"], fps, CARD_S)
        card = g.label("c")
        g.add(f"[{bg}:v]fps={fps:g},format=yuv420p,setsar=1[{card}]")
        path, (tw, th) = assets["title"]
        k = g.still(path, fps, CARD_S)
        ty = assets.get("title_y", (H - th) // 2)
        y = f"{ty}+{rise:.1f}*(1-{ease_out_expr(_ramp(0.0, MOVE_S))})"
        card = g.overlay(card, k, 0.0, CARD_S, f"{(W - tw) // 2}", y, fade_out=0)
        out = g.label()
        g.add(f"[{card}][{base}]xfade=transition=fade:duration={XFADE_S:.3f}:offset={CARD_S - XFADE_S:.3f}[{out}]")
        base = out

    T = plan.seconds
    ph = progress_height(layout)
    k = g.still(assets["track"], fps, T)
    base = g.overlay(base, k, 0.0, T, "0", f"{H - ph}", fade_in=0, fade_out=0)
    k = g.still(assets["fill"], fps, T)
    x = f"-{W}+{W}*({plan.frac0:.5f}+{plan.frac1 - plan.frac0:.5f}*clip(t/{T:.3f},0,1))"
    base = g.overlay(base, k, 0.0, T, x, f"{H - ph}", fade_in=0, fade_out=0)
    g.add(f"[{base}]{FINAL_VF}[vout]")

    if plan.probe.audio:
        measured = assets.get("loudness")
        g.add(f"[{clip}:a]{audio_chain(measured, plan.lead)}[aout]")
    else:
        g.add("anullsrc=r=48000:cl=stereo[aout]")
    return g


def render_step(plan: StepPlan, out_dir: Path, work: Path) -> Path:
    """clips_produced/NN.mp4 and NN.vtt for one step."""
    assets = prepare_step(plan, work)
    if plan.probe.audio:
        assets["loudness"] = loudness(plan.clip)
    g = step_graph(plan, assets)
    nn = f"{plan.n:02d}"
    out = out_dir / f"{nn}.mp4"
    cmd = [ffmpeg(), "-y", "-v", "error"]
    for args in g.inputs:
        cmd += args
    cmd += ["-filter_complex", g.text(), "-map", "[vout]", "-map", "[aout]", *X264, *teach.SDR_TAGS,
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{plan.seconds:.3f}", "-movflags", "+faststart",
            str(out)]
    run(cmd)
    cues = [Cue(c.start + plan.lead, c.end + plan.lead, c.text) for c in read_vtt(plan.vtt)]
    write_vtt(out_dir / f"{nn}.vtt", cues)
    return out


# ---------------------------------------------------------------- course

def fmt_length(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} sec"
    return f"{int(round(s / 60))} min"


def course_graph(steps: Sequence[tuple[Path, float]], intro_bg: Path, intro_text: tuple[Path, tuple[int, int]],
                 outro_bg: Path, outro_text: tuple[Path, tuple[int, int]], width: int, height: int,
                 fps: float) -> tuple[Graph, float]:
    """Intro card, the produced steps and the outro card joined with XFADE_S crossfades (video and audio).
    Returns the graph (outputs [vout], [aout]) and the course length."""
    g = Graph()
    u = Layout(width, height).u
    segs: list[tuple[str, str, float]] = []

    def card(bg: Path, text: tuple[Path, tuple[int, int]], seconds: float) -> tuple[str, str, float]:
        k = g.still(bg, fps, seconds)
        v = g.label("c")
        g.add(f"[{k}:v]fps={fps:g},format=yuv420p,setsar=1[{v}]")
        path, (tw, th) = text
        t = g.still(path, fps, seconds - 0.1)
        y = f"{(height - th) // 2}+{14 * u:.1f}*(1-{ease_out_expr(_ramp(0.1, 0.4))})"
        v = g.overlay(v, t, 0.1, seconds - 0.1, f"{(width - tw) // 2}", y, fade_in=0.4, fade_out=0)
        a = g.label("a")
        g.add(f"anullsrc=r=48000:cl=stereo,atrim=duration={seconds:.3f}[{a}]")
        return v, a, seconds

    segs.append(card(intro_bg, intro_text, INTRO_S))
    for path, seconds in steps:
        k = g.input("-i", str(path))
        v, a = g.label("s"), g.label("a")
        g.add(f"[{k}:v]fps={fps:g},format=yuv420p,setsar=1,settb=AVTB[{v}]")
        g.add(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[{a}]")
        segs.append((v, a, seconds))
    segs.append(card(outro_bg, outro_text, OUTRO_S))

    v, a, length = segs[0]
    for nv, na, nlen in segs[1:]:
        ov, oa = g.label(), g.label("a")
        g.add(f"[{v}]settb=AVTB[{v}t];[{nv}]settb=AVTB[{nv}t];"
              f"[{v}t][{nv}t]xfade=transition=fade:duration={XFADE_S:.3f}:offset={length - XFADE_S:.3f}[{ov}]")
        g.add(f"[{a}][{na}]acrossfade=d={XFADE_S:.3f}:c1=tri:c2=tri[{oa}]")
        v, a, length = ov, oa, length + nlen - XFADE_S
    g.add(f"[{v}]{FINAL_VF}[vout]")
    g.add(f"[{a}]anull[aout]")
    return g, length


def course_starts(step_seconds: Sequence[float]) -> list[float]:
    """When each step's crossfade begins in course.mp4."""
    starts, t = [], INTRO_S - XFADE_S
    for s in step_seconds:
        starts.append(t)
        t += s - XFADE_S
    return starts


def write_chapters(path: Path, titles: Sequence[str], starts: Sequence[float], length: float) -> None:
    cues = []
    for i, (title, a) in enumerate(zip(titles, starts)):
        a = 0.0 if i == 0 else a + XFADE_S / 2
        b = starts[i + 1] + XFADE_S / 2 if i + 1 < len(starts) else length
        cues.append(Cue(a, b, f"{i + 1}. {title}"))
    write_vtt(path, cues)


def best_frame(lesson_dir: Path, steps: Sequence[dict]) -> Optional[Path]:
    """The finished result (the last step's reference frame) unless it is nearly black; then the brightest one."""
    frames = [lesson_dir / str(s.get("ref_frame") or f"frames/{i + 1:02d}.jpg") for i, s in enumerate(steps)]
    frames = [f for f in frames if f.is_file()]
    if not frames:
        return None

    def brightness(p: Path) -> float:
        return ImageStat.Stat(Image.open(p).convert("L").resize((64, 64))).mean[0]

    if brightness(frames[-1]) >= 24:
        return frames[-1]
    return max(frames, key=brightness)


# ---------------------------------------------------------------- action regions

RUBRIC = "rubric.json"


def _clean_box(raw: Any, width: int = 0, height: int = 0) -> Optional[tuple[float, float, float, float]]:
    """A normalized (x0, y0, x1, y1) from a list or dict; pixel values are divided by the frame size."""
    try:
        if isinstance(raw, dict):
            if all(k in raw for k in ("x0", "y0", "x1", "y1")):
                box = [float(raw[k]) for k in ("x0", "y0", "x1", "y1")]
            elif all(k in raw for k in ("x", "y", "w", "h")):
                x, y, w, h = (float(raw[k]) for k in ("x", "y", "w", "h"))
                box = [x, y, x + w, y + h]
            else:
                return None
        elif isinstance(raw, (list, tuple)) and len(raw) == 4:
            box = [float(v) for v in raw]
        else:
            return None
    except (TypeError, ValueError):
        return None
    if max(box) > 1.5 and width and height:
        box = [box[0] / width, box[1] / height, box[2] / width, box[3] / height]
    x0, y0, x1, y1 = (max(0.0, min(1.0, v)) for v in box)
    if x1 - x0 < 0.03 or y1 - y0 < 0.03:
        return None
    return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))


def rubric_regions(lesson_dir: Path, width: int, height: int) -> Optional[dict[int, tuple]]:
    """Regions from rubric.json, by step number, or None when there is no rubric. Accepts {"steps": [{"n": 1,
    "region": ...}]} or {"1": {"region": ...}}; a region is [x0, y0, x1, y1], {x0..y1} or {x, y, w, h}."""
    path = lesson_dir / RUBRIC
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("produce: rubric.json is unreadable; ignoring it")
        return None
    items: list[tuple[int, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("steps"), list):
        items = [(int(s.get("n", i + 1)), s) for i, s in enumerate(data["steps"]) if isinstance(s, dict)]
    elif isinstance(data, dict):
        items = [(int(k), v) for k, v in data.items() if str(k).isdigit() and isinstance(v, dict)]
    out = {}
    for n, s in items:
        box = _clean_box(s.get("region") or s.get("bbox"), width, height)
        if box:
            out[n] = box
    return out


ASSIST_SYSTEM = """You help edit short how-to video clips. For each step you get three frames from its clip
(start, middle, end) with their times in seconds and the frame size in pixels. Return, for every step:
- the action region as pixel coordinates in that frame size (origin top left): x0, y0, x1, y1. It is the
  smallest box that contains the hands and the object they work on in ALL three frames, with a little room around
  them. Measure each step on its own frames; steps usually differ.
- key_time: the second within the clip where the step's result first becomes clearly visible, between 0 and the
  clip length. Judge it from the frames; do not default to the start.
Base both on what you see. If the hands and object fill most of the frame, return a box close to the full frame."""

ASSIST_SCHEMA = {
    "type": "object",
    "properties": {"steps": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "x0": {"type": "number"}, "y0": {"type": "number"},
                       "x1": {"type": "number"}, "y1": {"type": "number"}, "key_time": {"type": "number"}},
        "required": ["n", "x0", "y0", "x1", "y1", "key_time"],
        "additionalProperties": False}}},
    "required": ["steps"],
    "additionalProperties": False,
}
ASSIST_SIDE = 512
last_cost_usd = 0.0


def _jpeg_b64(path: Path) -> tuple[str, tuple[int, int]]:
    """The frame shrunk so its long side is ASSIST_SIDE, as base64 JPEG, and its size in pixels."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((ASSIST_SIDE, ASSIST_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), img.size


def _grab(clip: Path, t: float, out: Path) -> bool:
    p = subprocess.run([ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(clip), "-frames:v",
                        "1", "-q:v", "3", str(out)], capture_output=True, timeout=60)
    return p.returncode == 0 and out.is_file() and out.stat().st_size > 0


def claude_assist(items: Sequence[tuple[int, str, Path, float]], work: Path, client: Any = None,
                  model: Optional[str] = None) -> dict[int, dict]:
    """One Claude call for the whole lesson. items are (n, title, clip, seconds). Returns {n: {"region": box,
    "key_time": s}}. Raises RuntimeError on any failure, so the caller falls back to center and ref_time."""
    global last_cost_usd
    from server import spend

    model = model or produce_model()
    content: list[dict] = []
    sizes: dict[int, tuple[int, int]] = {}
    for n, title, clip, seconds in items:
        content.append({"type": "text", "text": f"Step {n}: {title}. Clip length {seconds:.1f} s."})
        for label, t in (("start", min(0.2, seconds / 4)), ("middle", seconds / 2),
                         ("end", max(0.0, seconds - 0.15))):
            out = work / f"assist-{n:02d}-{label}.jpg"
            if _grab(clip, t, out):
                data, size = _jpeg_b64(out)
                sizes[n] = size
                content.append({"type": "text", "text": f"{label} frame at {t:.1f} s ({size[0]}x{size[1]} px)"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": data}})
    if not any(c["type"] == "image" for c in content):
        raise RuntimeError("no frames could be read")
    content.append({"type": "text", "text": "Return the action region and key_time for every step."})
    if not spend.allow():
        raise RuntimeError("the Claude budget is used up; no call was made")
    if client is None:
        import anthropic

        key = teach._secret("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("no Claude key")
        client = anthropic.Anthropic(api_key=key, timeout=90.0, max_retries=2)
    try:
        response = client.messages.create(
            model=model, max_tokens=4000, system=ASSIST_SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": ASSIST_SCHEMA}},
        )
    except Exception as e:
        raise RuntimeError(f"Claude call failed: {type(e).__name__}") from None
    usage = getattr(response, "usage", None)
    if usage is not None:
        last_cost_usd = spend.record(model, usage)
    if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude did not finish (stop reason {response.stop_reason})")
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        rows = json.loads(text)["steps"]
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Claude's answer was not valid JSON") from None
    lengths = {n: s for n, _, _, s in items}
    out: dict[int, dict] = {}
    for row in rows:
        try:
            n = int(row["n"])
        except (KeyError, TypeError, ValueError):
            continue
        if n not in lengths:
            continue
        w, h = sizes.get(n, (ASSIST_SIDE, ASSIST_SIDE))
        box = _clean_box([row.get("x0"), row.get("y0"), row.get("x1"), row.get("y1")], w, h)
        try:
            kt = float(row.get("key_time"))
            kt = kt if 0 <= kt <= lengths[n] else None
        except (TypeError, ValueError):
            kt = None
        out[n] = {"region": list(box) if box else None, "key_time": kt}
    return out


def _signature(clip: Path) -> str:
    st = clip.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def find_regions(lesson_dir: Path, steps: Sequence[dict], probes: dict[int, Probe], work: Path,
                 cached: Optional[dict], allow_claude: bool = True, client: Any = None,
                 progress: Progress = noop) -> dict:
    """The assist record: {"source": "rubric"|"claude"|"none", "model"?, "signatures", "steps": {n: {...}}}.
    rubric.json wins; else a cached Claude answer for the same clips; else one Claude call; else nothing."""
    first = probes[min(probes)]
    sigs = {str(n): _signature(lesson_dir / str(s.get("clip") or f"clips/{n:02d}.mp4"))
            for n, s in ((int(s.get("n", i + 1)), s) for i, s in enumerate(steps))}
    rubric = rubric_regions(lesson_dir, first.width, first.height)
    if rubric is not None:
        return {"source": "rubric", "signatures": sigs,
                "steps": {str(n): {"region": list(b), "key_time": None} for n, b in rubric.items()}}
    if cached and cached.get("source") == "claude" and cached.get("signatures") == sigs:
        return cached
    if not allow_claude or _no_network():
        return {"source": "none", "signatures": sigs, "steps": {}}
    items = []
    for i, s in enumerate(steps):
        n = int(s.get("n", i + 1))
        items.append((n, str(s.get("title") or f"Step {n}"),
                      lesson_dir / str(s.get("clip") or f"clips/{n:02d}.mp4"), probes[n].duration))
    progress("assist", f"asking {produce_model()} for action regions ({len(items)} steps, one call)")
    try:
        got = claude_assist(items, work, client=client)
    except Exception as e:
        log.warning("produce: no Claude regions (%s); using the center and ref_time", str(e)[:200])
        progress("assist", f"no Claude regions ({str(e)[:120]}); using the center and ref_time")
        return {"source": "none", "signatures": sigs, "steps": {}}
    return {"source": "claude", "model": produce_model(), "signatures": sigs, "cost_usd": round(last_cost_usd, 6),
            "steps": {str(n): v for n, v in got.items()}}


# ---------------------------------------------------------------- orchestration

PRODUCED_DIRS = ("clips_produced", "produced")


def wait_for_load(progress: Progress = noop, checks: int = 20) -> None:
    """Waits (30 s at a time, at most checks times) while the 5 minute load average is above 1.5 x the cores."""
    limit = (os.cpu_count() or 4) * 3 // 2
    for _ in range(checks):
        try:
            load = os.getloadavg()[1]
        except (OSError, AttributeError):
            return
        if load <= limit:
            return
        progress("waiting", f"load {load:.0f} is above {limit}; waiting before rendering")
        time.sleep(30)


def _load_lesson(lesson_dir: Path) -> dict:
    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    if not isinstance(lesson, dict) or not isinstance(lesson.get("steps"), list) or not lesson["steps"]:
        raise ValueError("lesson.json has no steps")
    return lesson


def _ref_seconds(step: dict) -> Optional[float]:
    """ref_time is on the source video's clock; this is the same moment in the step's clip."""
    try:
        if not step.get("ref_time"):
            return None
        return teach.parse_time(step["ref_time"]) - teach.parse_time(step.get("start") or 0)
    except ValueError:
        return None


def _overrides(production: dict, n: int) -> dict:
    per = production.get("steps") if isinstance(production.get("steps"), dict) else {}
    o = per.get(str(n)) or per.get(n) or {}
    return o if isinstance(o, dict) else {}


def build_plans(lesson_dir: Path, lesson: dict, style: dict, probes: dict[int, Probe], assist: dict,
                work: Path) -> list[StepPlan]:
    steps = lesson["steps"]
    total_s = sum(p.duration for p in probes.values()) or 1.0
    production = lesson.get("production") if isinstance(lesson.get("production"), dict) else {}
    plans, t = [], 0.0
    for i, s in enumerate(steps):
        n = int(s.get("n", i + 1))
        pr = probes[n]
        found = (assist.get("steps") or {}).get(str(n)) or {}
        o = _overrides(production, n)
        region = _clean_box(o.get("region"), pr.width, pr.height) or _clean_box(found.get("region"))
        key = o.get("key_time") if isinstance(o.get("key_time"), (int, float)) else _ref_seconds(s)
        if key is None:
            key = found.get("key_time")
        if key is not None and not 0 <= key <= pr.duration:
            key = None
        plans.append(StepPlan(
            n=n, total=len(steps), title=" ".join(str(s.get("title") or f"Step {n}").split()),
            clip=lesson_dir / str(s.get("clip") or f"clips/{n:02d}.mp4"),
            vtt=lesson_dir / str(s.get("captions") or f"captions/{n:02d}.vtt"),
            first_frame=work / f"{n:02d}" / "first.jpg", probe=pr, region=region, key_time=key,
            frac0=t / total_s, frac1=(t + pr.duration) / total_s, style=style,
            zoom=style["zoom"] and o.get("zoom", True) is not False,
            highlight=style["highlight"] and o.get("highlight", True) is not False))
        t += pr.duration
    return plans


def render_course(lesson: dict, plans: Sequence[StepPlan], clips_dir: Path, out_dir: Path, work: Path,
                  lesson_dir: Path) -> float:
    """course.mp4, course.vtt, chapters.vtt and cover.jpg into out_dir. Returns the course length."""
    first = plans[0].probe
    layout = Layout(first.width, first.height)
    style = plans[0].style
    theme = card_theme(style)
    paths = [clips_dir / f"{p.n:02d}.mp4" for p in plans]
    seconds = [probe(p).duration for p in paths]
    length = INTRO_S + sum(seconds) + OUTRO_S - XFADE_S * (len(paths) + 1)
    title = " ".join(str(lesson.get("title") or lesson.get("id") or "Lesson").split())
    sub = f"{len(plans)} steps \u00b7 {fmt_length(length)}"
    frame = best_frame(lesson_dir, lesson["steps"]) or plans[0].first_frame
    work.mkdir(parents=True, exist_ok=True)
    solid_backdrop(layout, theme).save(work / "intro.png")
    intro = title_block("", title, layout, theme, sub=sub, title_size=84)
    intro.save(work / "intro_text.png")
    solid_backdrop(layout, theme).save(work / "outro.png")
    outro = outro_block([p.title for p in plans], layout, theme)
    outro.save(work / "outro_text.png")
    g, length = course_graph(list(zip(paths, seconds)), work / "intro.png", (work / "intro_text.png", intro.size),
                             work / "outro.png", (work / "outro_text.png", outro.size), first.width, first.height,
                             first.fps)
    cmd = [ffmpeg(), "-y", "-v", "error"]
    for args in g.inputs:
        cmd += args
    cmd += ["-filter_complex", g.text(), "-map", "[vout]", "-map", "[aout]", *X264, *teach.SDR_TAGS,
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{length:.3f}", "-movflags", "+faststart",
            str(out_dir / "course.mp4")]
    run(cmd)
    starts = course_starts(seconds)
    write_chapters(out_dir / "chapters.vtt", [p.title for p in plans], starts, length)
    cues = []
    for p, a in zip(plans, starts):
        for c in read_vtt(clips_dir / f"{p.n:02d}.vtt"):
            cues.append(Cue(a + c.start, a + c.end, c.text))
    write_vtt(out_dir / "course.vtt", cues)
    cover_image(frame, title, sub, layout, theme).save(out_dir / "cover.jpg", quality=90)
    return length


def _swap_in(lesson_dir: Path, tmp: Path) -> None:
    """Old output folders aside, new ones in, old ones deleted: the same safe order as teach's recut."""
    old = Path(tempfile.mkdtemp(prefix=".produce_old-", dir=lesson_dir))
    try:
        for sub in PRODUCED_DIRS:
            if (lesson_dir / sub).exists():
                (lesson_dir / sub).replace(old / sub)
            (tmp / sub).replace(lesson_dir / sub)
    finally:
        shutil.rmtree(old, ignore_errors=True)


def _save_production(lesson_dir: Path, style: dict, output: dict) -> dict:
    """Re-reads lesson.json just before writing so edits made during the render are kept."""
    lesson = _load_lesson(lesson_dir)
    current = lesson.get("production") if isinstance(lesson.get("production"), dict) else {}
    production = {**current, **style, "output": output}
    lesson["production"] = production
    teach._write_json(lesson_dir / "lesson.json", lesson)
    return production


def produce(lesson_dir: Path, style: Optional[dict] = None, *, steps: Optional[Sequence[int]] = None,
            assist: bool = True, client: Any = None, jobs: Optional[int] = None,
            progress: Progress = noop) -> dict:
    """Renders the lesson's produced clips and course. style is merged over lesson.json "production" and saved.
    steps re-renders only those steps (others are kept when their files exist) and always rebuilds the course.
    Everything renders into a temp folder inside the lesson and is swapped in only when all of it succeeded."""
    t0 = time.monotonic()
    lesson_dir = Path(lesson_dir)
    lesson = _load_lesson(lesson_dir)
    saved = lesson.get("production") if isinstance(lesson.get("production"), dict) else {}
    merged = normalize_style({**{k: saved[k] for k in STYLE_DEFAULTS if k in saved}, **(style or {})})
    numbers = [int(s.get("n", i + 1)) for i, s in enumerate(lesson["steps"])]
    probes = {}
    for i, s in enumerate(lesson["steps"]):
        clip = lesson_dir / str(s.get("clip") or f"clips/{numbers[i]:02d}.mp4")
        if not clip.is_file():
            raise FileNotFoundError(f"step {numbers[i]} has no clip ({clip.name})")
        probes[numbers[i]] = probe(clip)

    tmp = Path(tempfile.mkdtemp(prefix=".produce_tmp-", dir=lesson_dir))
    try:
        work = tmp / "work"
        clips_out, out = tmp / "clips_produced", tmp / "produced"
        for d in (work, clips_out, out):
            d.mkdir(parents=True)
        cached = None
        old_assist = lesson_dir / "produced" / "assist.json"
        if old_assist.is_file():
            try:
                cached = json.loads(old_assist.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
        found = find_regions(lesson_dir, lesson["steps"], probes, work, cached, assist, client, progress)
        (out / "assist.json").write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
        plans = build_plans(lesson_dir, lesson, merged, probes, found, work)

        wanted = set(steps or numbers)
        old_clips = lesson_dir / "clips_produced"
        todo = []
        for p in plans:
            nn = f"{p.n:02d}"
            if p.n not in wanted and (old_clips / f"{nn}.mp4").is_file():
                shutil.copy2(old_clips / f"{nn}.mp4", clips_out / f"{nn}.mp4")
                if (old_clips / f"{nn}.vtt").is_file():
                    shutil.copy2(old_clips / f"{nn}.vtt", clips_out / f"{nn}.vtt")
            else:
                todo.append(p)

        wait_for_load(progress)
        workers = max(1, min(jobs or max_jobs(), 3, len(todo) or 1))
        progress("rendering", f"{len(todo)} steps, {workers} at a time")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(render_step, p, clips_out, work / f"{p.n:02d}"): p for p in todo}
            for fut in concurrent.futures.as_completed(futures):
                p = futures[fut]
                fut.result()
                progress("rendering", f"step {p.n} of {p.total} done")
        progress("rendering", "course video")
        length = render_course(lesson, plans, clips_out, out, work / "course", lesson_dir)
        shutil.rmtree(work, ignore_errors=True)
        _swap_in(lesson_dir, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    elapsed = time.monotonic() - t0
    output = {
        "clips": "clips_produced",
        "course": "produced/course.mp4",
        "cover": "produced/cover.jpg",
        "chapters": "produced/chapters.vtt",
        "captions": "produced/course.vtt",
        "seconds": round(length, 2),
        "steps": len(plans),
        "assist": found["source"],
        "sources": found["signatures"],
        "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    _save_production(lesson_dir, merged, output)
    return {"style": merged, "output": output, "rendered": [p.n for p in todo], "render_seconds": round(elapsed, 2),
            "seconds_per_video_minute": round(elapsed / max(length / 60, 1e-6), 2),
            "cost_usd": round(float(found.get("cost_usd", 0.0)) if found["source"] == "claude" and
                              found is not cached else 0.0, 6)}


def status(lesson_dir: Path) -> dict:
    """For the editor and players: whether produced output exists, whether it is stale (a clip changed after the
    render, for example by a recut or voiceover), and the saved style."""
    lesson_dir = Path(lesson_dir)
    lesson = _load_lesson(lesson_dir)
    production = lesson.get("production") if isinstance(lesson.get("production"), dict) else {}
    output = production.get("output") or {}
    present = (lesson_dir / "produced" / "course.mp4").is_file()
    stale = False
    if present:
        for i, s in enumerate(lesson["steps"]):
            n = int(s.get("n", i + 1))
            clip = lesson_dir / str(s.get("clip") or f"clips/{n:02d}.mp4")
            if not clip.is_file() or (output.get("sources") or {}).get(str(n)) != _signature(clip) or \
                    not (lesson_dir / "clips_produced" / f"{n:02d}.mp4").is_file():
                stale = True
                break
    return {"present": present, "stale": stale, "style": normalize_style(production), "output": output}


# ---------------------------------------------------------------- CLI

def _parse_steps(text: str) -> list[int]:
    try:
        out = sorted({int(x) for x in text.split(",") if x.strip()})
    except ValueError:
        raise argparse.ArgumentTypeError("--steps takes step numbers like 2,3") from None
    if not out or min(out) < 1:
        raise argparse.ArgumentTypeError("--steps takes step numbers like 2,3")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.produce", description="Render edited tutorial videos.")
    ap.add_argument("lesson_dir", type=Path)
    ap.add_argument("--no-zoom", action="store_true", help="no push-in")
    ap.add_argument("--no-cards", action="store_true", help="no title cards (title_cards off)")
    ap.add_argument("--title-cards", choices=TITLE_CARDS, help="card, overlay or off")
    ap.add_argument("--no-highlight", action="store_true", help="no highlight ring")
    ap.add_argument("--burn-captions", action="store_true", help="burn captions into the picture")
    ap.add_argument("--soft-captions", action="store_true", help="stop burning captions")
    ap.add_argument("--theme", choices=THEME_NAMES, metavar="NAME", help="a theme id from apps/design/THEMES.md")
    ap.add_argument("--accent", help="accent color as #RRGGBB")
    ap.add_argument("--steps", type=_parse_steps, help="only re-render these steps, for example 2,3")
    ap.add_argument("--no-assist", action="store_true", help="never call Claude for action regions")
    args = ap.parse_args(argv)
    lesson_dir = args.lesson_dir
    if not (lesson_dir / "lesson.json").is_file():
        print(f"no lesson.json in {lesson_dir}", file=sys.stderr)
        return 2
    style: dict[str, Any] = {}
    if args.no_zoom:
        style["zoom"] = False
    if args.no_cards:
        style["title_cards"] = "off"
    if args.title_cards:
        style["title_cards"] = args.title_cards
    if args.no_highlight:
        style["highlight"] = False
    if args.burn_captions:
        style["burn_captions"] = True
    if args.soft_captions:
        style["burn_captions"] = False
    if args.theme:
        style["theme"] = args.theme
    if args.accent:
        if not _HEX.match(args.accent):
            print("--accent takes a color like #0A84FF", file=sys.stderr)
            return 2
        style["accent"] = args.accent
    show: Progress = lambda status, message: print(f"[{status}] {message}", flush=True)  # noqa: E731
    try:
        result = produce(lesson_dir, style, steps=args.steps, assist=not args.no_assist, progress=show)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = result["output"]
    print(f"course {lesson_dir / out['course']} ({out['seconds']:.1f} s, {out['steps']} steps, "
          f"regions from {out['assist']})")
    print(f"rendered in {result['render_seconds']:.1f} s, {result['seconds_per_video_minute']:.1f} s per minute of "
          f"video; Claude cost ${result['cost_usd']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

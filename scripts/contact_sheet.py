"""Contact sheets for deciding where a take's steps start and end.

    .venv/bin/python scripts/contact_sheet.py VIDEO [--every 2] [--cols 6] [--out sheet.jpg]
    .venv/bin/python scripts/contact_sheet.py --lesson lessons/<id> [--out lessons/<id>/review/sheet.jpg]

Grid mode: one frame every --every seconds (optionally only --from to --to), --cols per row, each with its time
burned in as MM:SS.s, the same format lesson.json uses.

Lesson mode: one row per step with four frames taken from the lesson's norm.mp4: the step's first frame, its
middle, the reference frame the camera check compares against (frames/NN.jpg, at ref_time) and its last frame.
When lessons/<id>/review/boundaries.json exists (vision boundaries), each step that ends at a model-chosen cut gets
a strip of the +-2 s frames around it under its row, the chosen frame outlined in red, with the model's reason.
Each row is labelled with the step number, title, start to end, check type and question, so a person can see a
boundary that is early or late, move start and end in lesson.json and recut. Default output:
lessons/<id>/review/sheet.jpg.

Needs only Pillow and ffmpeg (HANDOVER_FFMPEG, PATH, then Homebrew). Writes only the --out file.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (250, 247, 240)
INK = (30, 30, 30)
MUTED = (110, 105, 95)
ACCENT = (190, 60, 40)


# ---------------------------------------------------------------- helpers

def _bin(name: str) -> str:
    override = os.environ.get("HANDOVER_FFMPEG")
    if override and Path(override).is_file():
        p = Path(override)
        cand = p if name == "ffmpeg" else p.with_name(name + p.suffix)
        if cand.is_file():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    brew = Path("/opt/homebrew/bin") / name
    if brew.is_file():
        return str(brew)
    raise SystemExit(f"{name} not found on PATH")


def parse_time(value) -> float:
    if value is None or value == "":
        raise ValueError("empty time")
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    for part in str(value).strip().split(":"):
        total = total * 60 + float(part)
    return total


def fmt(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}"


def duration(video: Path) -> float:
    p = subprocess.run([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(video)], capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise SystemExit(f"could not read the length of {video}") from None


def font(size: int, bold: bool = False):
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Helvetica.ttc"] if bold else
             ["arial.ttf", "DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"])
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1
        return ImageFont.load_default()


def grab(video: Path, t: float, width: int) -> Image.Image | None:
    """The frame at t seconds, scaled to width, or None when ffmpeg returns nothing (past the end)."""
    with tempfile.TemporaryDirectory(prefix="handover-sheet-") as tmp:
        out = Path(tmp) / "f.jpg"
        subprocess.run([_bin("ffmpeg"), "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out)],
                       capture_output=True)
        if not out.is_file() or out.stat().st_size == 0:
            return None
        with Image.open(out) as im:
            return im.convert("RGB")


def stamp(img: Image.Image, text: str, size: int = 18) -> Image.Image:
    """Time label in a dark box at the bottom left of the frame."""
    img = img.copy()
    d = ImageDraw.Draw(img)
    f = font(size, bold=True)
    box = d.textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    x, y = 6, img.height - h - 14
    d.rectangle((x - 4, y - 4, x + w + 6, y + h + 8), fill=(0, 0, 0))
    d.text((x, y - box[1] + 2), text, font=f, fill=(255, 255, 255))
    return img


def placeholder(width: int, height: int, text: str) -> Image.Image:
    img = Image.new("RGB", (width, height), (200, 196, 188))
    ImageDraw.Draw(img).text((10, height // 2), text, font=font(16), fill=INK)
    return img


# ---------------------------------------------------------------- grid mode

def grid_sheet(video: Path, every: float, cols: int, width: int, t_from: float, t_to: float | None) -> Image.Image:
    length = duration(video)
    t_to = length if t_to is None else min(t_to, length)
    if every <= 0 or t_to <= t_from:
        raise SystemExit("nothing to show: check --every, --from and --to")
    with tempfile.TemporaryDirectory(prefix="handover-sheet-") as tmp:
        # one ffmpeg pass: fps=1/every picks the frame nearest each multiple of `every` after --from
        subprocess.run([_bin("ffmpeg"), "-v", "error", "-y", "-ss", f"{t_from:.3f}", "-i", str(video),
                        "-t", f"{t_to - t_from:.3f}", "-vf", f"fps=1/{every:g},scale={width}:-2", "-q:v", "3",
                        str(Path(tmp) / "f%05d.jpg")], capture_output=True)
        files = sorted(Path(tmp).glob("f*.jpg"))
        if not files:
            raise SystemExit(f"ffmpeg returned no frames from {video}")
        tiles = []
        for k, f in enumerate(files):
            with Image.open(f) as im:
                tiles.append(stamp(im.convert("RGB"), fmt(t_from + k * every)))
    tw, th = tiles[0].size
    gap, head = 6, 44
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * gap, head + rows * (th + gap) + gap), BG)
    d = ImageDraw.Draw(sheet)
    d.text((gap, 10), f"{video.name}  {fmt(t_from)} to {fmt(t_to)}  one frame every {every:g} s",
           font=font(20, bold=True), fill=INK)
    for k, tile in enumerate(tiles):
        r, c = divmod(k, cols)
        sheet.paste(tile, (gap + c * (tw + gap), head + r * (th + gap)))
    return sheet


# ---------------------------------------------------------------- lesson mode

def window_frames(video: Path, times: list[float], height: int) -> list[Image.Image]:
    """Frames at evenly spaced times (one ffmpeg call from the first time at the same rate)."""
    if len(times) < 2:
        return []
    step = times[1] - times[0]
    with tempfile.TemporaryDirectory(prefix="handover-sheet-") as tmp:
        subprocess.run([_bin("ffmpeg"), "-v", "error", "-y", "-ss", f"{times[0]:.3f}", "-i", str(video),
                        "-t", f"{times[-1] - times[0] + step / 2:.3f}", "-vf", f"fps={1 / step:.6f},scale=-2:{height}",
                        "-q:v", "4", str(Path(tmp) / "w%04d.jpg")], capture_output=True)
        out = []
        for f in sorted(Path(tmp).glob("w*.jpg"))[:len(times)]:
            with Image.open(f) as im:
                out.append(im.convert("RGB"))
        return out


def cut_strips(lesson_dir: Path, video: Path, width: int) -> dict:
    """From review/boundaries.json (vision boundaries): per step n, a strip of the +-2 s frames around its cut
    with the chosen frame outlined, plus a caption line. {} when there is no log."""
    path = lesson_dir / "review" / "boundaries.json"
    if not path.is_file():
        return {}
    try:
        log = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    model = (log.get("pass2") or {}).get("model") or (log.get("pass1") or {}).get("model") or "?"
    out = {}
    for b in (log.get("pass2") or {}).get("boundaries") or []:
        times = b.get("frames") or []
        frames = window_frames(video, times, 150)
        if not frames:
            continue
        tw = max(40, (width - 4) // len(frames) - 4)
        frames = [im.resize((tw, round(im.height * tw / im.width))) for im in frames]
        th = frames[0].height
        strip = Image.new("RGB", (width, th + 30), BG)
        d = ImageDraw.Draw(strip)
        chosen = min(range(len(times)), key=lambda i: abs(times[i] - b.get("done_s", -1)))
        for i, im in enumerate(frames):
            x = 4 + i * (tw + 4)
            strip.paste(im, (x, 26))
            if i == chosen:
                d.rectangle((x - 3, 23, x + tw + 2, 26 + th + 2), outline=ACCENT, width=4)
                d.text((x, 2), "cut", font=font(16, bold=True), fill=ACCENT)
            elif i % 4 == 0:
                d.text((x, 6), fmt(times[i]), font=font(12), fill=MUTED)
        caption = (f"vision cut {b.get('done_s', 0):.2f} s (pass 1 {b.get('coarse_s', 0):.2f} s, {model}): "
                   f"{b.get('reason', '')}")
        out[int(b["boundary"])] = (strip, caption)
    return out



COLUMNS = ("first", "middle", "reference", "last")


def lesson_sheet(lesson_dir: Path, width: int) -> Image.Image:
    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    video = lesson_dir / str(lesson.get("video") or "norm.mp4")
    if not video.is_file():
        raise SystemExit(f"{video} is missing; the lesson sheet is drawn from the full video")
    steps = lesson.get("steps") or []
    if not steps:
        raise SystemExit("lesson.json has no steps")
    length = duration(video)
    label_w, gap, head = 380, 8, 54
    rows = []
    for i, s in enumerate(steps):
        a, b = parse_time(s.get("start")), parse_time(s.get("end"))
        b = min(b, length)
        ref_t = None
        try:
            ref_t = parse_time(s.get("ref_time")) if s.get("ref_time") else None
        except ValueError:
            ref_t = None
        tiles = []
        for col in COLUMNS:
            if col == "first":
                t, img = a, grab(video, a, width)
            elif col == "middle":
                t, img = (a + b) / 2, grab(video, (a + b) / 2, width)
            elif col == "last":
                t, img = b - 0.05, grab(video, max(a, b - 0.05), width)
            else:
                ref = lesson_dir / str(s.get("ref_frame") or f"frames/{i + 1:02d}.jpg")
                t, img = ref_t, None
                if ref.is_file():
                    with Image.open(ref) as im:
                        im = im.convert("RGB")
                        img = im.resize((width, round(im.height * width / im.width)))
            label = f"{col} {fmt(t)}" if t is not None else f"{col} (after the step end)" if col == "reference" else col
            tiles.append(stamp(img, label, 16) if img is not None else None)
        rows.append((s, a, b, tiles))
    th = max(t.height for _, _, _, ts in rows for t in ts if t is not None)
    W = label_w + len(COLUMNS) * (width + gap) + gap
    strips = cut_strips(lesson_dir, video, W - 2 * gap)
    heights = [th + (strips[s.get("n", r + 1)][0].height + 24 if s.get("n", r + 1) in strips else 0)
               for r, (s, _, _, _) in enumerate(rows)]
    sheet = Image.new("RGB", (W, head + sum(h + gap for h in heights) + gap), BG)
    d = ImageDraw.Draw(sheet)
    d.text((gap, 10), f"{lesson.get('id', lesson_dir.name)}  {lesson.get('title', '')}", font=font(24, bold=True),
           fill=INK)
    d.text((gap + 2, 36), "per step: first frame, middle, reference frame (what the camera compares), last frame",
           font=font(14), fill=MUTED)
    f_big, f_small = font(22, bold=True), font(15)
    for r, (s, a, b, tiles) in enumerate(rows):
        y = head + sum(h + gap for h in heights[:r])
        if r % 2:
            d.rectangle((0, y - gap // 2, W, y + heights[r] + gap // 2), fill=(242, 237, 226))
        n = s.get("n", r + 1)
        d.text((gap, y + 4), f"{n}", font=font(40, bold=True), fill=ACCENT)
        x0 = gap + 56
        lines = textwrap.wrap(str(s.get("title") or ""), 26)[:3]
        yy = y + 8
        for ln in lines:
            d.text((x0, yy), ln, font=f_big, fill=INK)
            yy += 28
        yy += 6
        info = [f"{fmt(a)} to {fmt(b)}  ({b - a:.1f} s)",
                f"{s.get('check_type', 'camera')}" + (f", self-test {'ok' if s['self_test'].get('ok') else 'FAILED'}"
                                                      if isinstance(s.get("self_test"), dict) else "")]
        q = str(s.get("check_question") or "")
        if q and s.get("check_type") != "manual":
            info += textwrap.wrap("Q: " + q, 44)[:5]
        for ln in info:
            d.text((x0, yy), ln, font=f_small, fill=MUTED if not ln.startswith("Q") else INK)
            yy += 20
        for c, tile in enumerate(tiles):
            x = label_w + c * (width + gap)
            sheet.paste(tile if tile is not None else placeholder(width, th, "no frame"), (x, y))
        got = strips.get(s.get("n", r + 1))
        if got:
            strip, caption = got
            d.text((gap, y + th + 4), textwrap.shorten(caption, 150), font=font(15), fill=INK)
            sheet.paste(strip, (gap, y + th + 24))
    return sheet


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="contact_sheet.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("video", nargs="?", type=Path, help="a video (grid mode)")
    ap.add_argument("--lesson", type=Path, help="a lesson folder: one row per step")
    ap.add_argument("--every", type=float, default=2.0, help="grid: seconds between frames (default 2)")
    ap.add_argument("--cols", type=int, default=6, help="grid: frames per row (default 6)")
    ap.add_argument("--from", dest="t_from", default="0", help="grid: first time, MM:SS or seconds")
    ap.add_argument("--to", dest="t_to", default=None, help="grid: last time, MM:SS or seconds")
    ap.add_argument("--width", type=int, default=None, help="width of one frame in pixels (grid 240, lesson 220)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output JPEG (grid: sheet.jpg; lesson: <lesson>/review/sheet.jpg)")
    args = ap.parse_args(argv)
    if bool(args.video) == bool(args.lesson):
        ap.error("give a VIDEO or --lesson LESSON_DIR (one of them)")
    if args.lesson:
        if not (args.lesson / "lesson.json").is_file():
            ap.error(f"no lesson.json in {args.lesson}")
        sheet = lesson_sheet(args.lesson, args.width or 220)
        out = args.out or args.lesson / "review" / "sheet.jpg"
    else:
        if not args.video.is_file():
            ap.error(f"no such video: {args.video}")
        sheet = grid_sheet(args.video, args.every, max(1, args.cols), args.width or 240,
                           parse_time(args.t_from), parse_time(args.t_to) if args.t_to else None)
        out = args.out or Path("sheet.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, "JPEG", quality=85)
    print(f"wrote {out} ({sheet.width}x{sheet.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

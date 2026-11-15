"""Check a lesson folder against CONTRACT.md section 3 before it goes on stage.

    .venv/bin/python scripts/lesson_lint.py lessons/demo-v1 [lessons/other ...] [--strict] [--json]

Each check prints OK, WARN or FAIL. FAIL means the hub or the browser will
misbehave (missing clip, bad timestamps, a codec Chrome cannot play). WARN means
it works but a learner may notice (a color word in a check question, a blurry
reference frame, a gap between steps).

Exit code: 1 when any check fails (or warns, with --strict), 2 on bad usage, else 0.
Needs Pillow and ffprobe (PATH, then Homebrew's folder). Never writes anything.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_RANK = {OK: 0, WARN: 1, FAIL: 2}

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
DURATION_TOLERANCE = 0.15  # seconds between lesson.json times and the probed clip
BLACK_MEAN = 16.0  # mean luminance (0 to 255) below which a frame counts as near-black
BLUR_EDGE_VAR = 20.0  # variance of the edge image below which a frame counts as blurry
SMALL_SIDE = 320  # long side in pixels below which a frame is too small to judge

COLOR_WORDS = {
    "red", "orange", "yellow", "green", "blue", "purple", "violet", "pink", "white", "black",
    "gray", "grey", "brown", "cyan", "magenta", "teal", "beige", "gold", "silver", "navy",
    "color", "colour", "colored", "coloured",
}
YES_NO_STARTS = {
    "is", "are", "does", "do", "has", "have", "can", "will", "was", "were", "did", "could",
    "should", "would",
}
ANSWERS = {"yes", "no", "unsure"}


# ---------------------------------------------------------------- small helpers

def parse_time(value) -> float:
    """Same rule as server/teach.py: seconds, "MM:SS", "MM:SS.s" or "HH:MM:SS"."""
    if isinstance(value, bool):
        raise ValueError(f"bad timestamp: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"bad timestamp: {value!r}")
    parts = value.strip().split(":")
    if len(parts) > 3:
        raise ValueError(f"bad timestamp: {value!r}")
    total = 0.0
    for part in parts:
        try:
            total = total * 60 + float(part)
        except ValueError:
            raise ValueError(f"bad timestamp: {value!r}") from None
    if total < 0:
        raise ValueError(f"bad timestamp: {value!r}")
    return total


def parse_vtt_time(value: str) -> float:
    """WebVTT cue time: "HH:MM:SS.mmm" or "MM:SS.mmm"."""
    if not re.fullmatch(r"(\d{2,}:)?\d{2}:\d{2}\.\d{3}", value):
        raise ValueError(f"bad cue time {value!r}")
    return parse_time(value)


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def fmt_s(seconds: float) -> str:
    return f"{seconds:.2f} s"


def ffprobe_bin() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    brew = Path("/opt/homebrew/bin/ffprobe")
    return str(brew) if brew.is_file() else None


def probe(path: Path) -> dict:
    """ffprobe streams and format as a dict. Raises RuntimeError when ffprobe cannot read the file."""
    exe = ffprobe_bin()
    if not exe:
        raise RuntimeError("ffprobe not found")
    p = subprocess.run(
        [exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        tail = (p.stderr.strip().splitlines() or ["unreadable"])[-1]
        raise RuntimeError(tail[:120])
    try:
        return json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        raise RuntimeError("ffprobe returned no data") from None


def probe_duration(info: dict) -> float | None:
    try:
        return float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        return None


def safe_rel_path(value) -> str | None:
    """Reason a lesson path is unsafe, or None when it is a relative forward-slash path inside the folder."""
    if not isinstance(value, str) or not value:
        return "must be a non-empty string"
    if "\\" in value:
        return "must use forward slashes"
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return "must be relative to the lesson folder"
    if ".." in value.split("/"):
        return "must stay inside the lesson folder"
    return None


# ---------------------------------------------------------------- report

class Report:
    """Ordered checks; adding to the same check keeps the worst level and every non-OK detail."""

    def __init__(self, lesson_id: str, path: Path):
        self.lesson_id = lesson_id
        self.path = path
        self.rows: dict[str, list] = {}

    def add(self, check: str, level: str, detail: str = "") -> None:
        row = self.rows.setdefault(check, [OK, [], []])  # level, problems, ok notes
        if _RANK[level] > _RANK[row[0]]:
            row[0] = level
        (row[2] if level == OK else row[1]).append(detail)

    def ok(self, check: str, detail: str = "") -> None:
        self.add(check, OK, detail)

    def warn(self, check: str, detail: str) -> None:
        self.add(check, WARN, detail)

    def fail(self, check: str, detail: str) -> None:
        self.add(check, FAIL, detail)

    def checks(self) -> list[dict]:
        out = []
        for name, (level, problems, notes) in self.rows.items():
            detail = "; ".join(d for d in problems if d) if problems else ", ".join(d for d in notes if d)
            out.append({"check": name, "result": level, "detail": detail})
        return out

    def counts(self) -> dict:
        c = {OK: 0, WARN: 0, FAIL: 0}
        for level, _, _ in self.rows.values():
            c[level] += 1
        return c

    def result(self) -> str:
        c = self.counts()
        return FAIL if c[FAIL] else WARN if c[WARN] else OK

    def as_dict(self) -> dict:
        return {"id": self.lesson_id, "path": str(self.path), "result": self.result(),
                "counts": self.counts(), "checks": self.checks()}


# ---------------------------------------------------------------- media checks

def check_clip(rep: Report, name: str, path: Path, expected: float | None) -> float | None:
    """Codec, pixel format, audio and duration of one clip. Returns the probed duration."""
    try:
        info = probe(path)
    except RuntimeError as e:
        rep.fail(name, f"ffprobe cannot read it: {e}")
        return None
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video:
        rep.fail(name, "no video stream")
    else:
        v = video[0]
        codec, pix = v.get("codec_name"), v.get("pix_fmt")
        if codec != "h264":
            rep.fail(name, f"video is {codec}, browsers need h264")
        if pix != "yuv420p":
            rep.fail(name, f"pixel format is {pix}, browsers need yuv420p")
        if codec == "h264" and pix == "yuv420p":
            rep.ok(name, "h264 yuv420p")
    if not audio:
        rep.warn(name, "no audio track, the expert's voice will be silent")
    elif audio[0].get("codec_name") != "aac":
        rep.fail(name, f"audio is {audio[0].get('codec_name')}, browsers need aac")
    else:
        rep.ok(name, "aac")
    dur = probe_duration(info)
    if dur is None:
        rep.fail(name, "duration unknown")
    elif expected is not None:
        if abs(dur - expected) > DURATION_TOLERANCE:
            rep.fail(name, f"clip is {fmt_s(dur)}, start to end is {fmt_s(expected)}")
        else:
            rep.ok(name, fmt_s(dur))
    return dur


def check_vtt(rep: Report, name: str, path: Path, clip_len: float | None) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        rep.fail(name, f"unreadable: {type(e).__name__}")
        return
    lines = text.splitlines()
    first = lines[0].strip() if lines else ""
    if first != "WEBVTT" and not first.startswith(("WEBVTT ", "WEBVTT\t")):
        rep.fail(name, "does not start with WEBVTT")
        return
    cues = 0
    for i, line in enumerate(lines, 1):
        if "-->" not in line:
            continue
        cues += 1
        left, right = line.split("-->", 1)
        try:
            a = parse_vtt_time(left.strip())
            b = parse_vtt_time(right.strip().split()[0] if right.strip() else "")
        except ValueError as e:
            rep.fail(name, f"line {i}: {e}")
            continue
        if b <= a:
            rep.fail(name, f"line {i}: cue ends before it starts")
        if clip_len is not None and b > clip_len + DURATION_TOLERANCE:
            rep.fail(name, f"line {i}: cue ends at {fmt_s(b)}, clip is {fmt_s(clip_len)}")
    if cues == 0:
        rep.warn(name, "no cues, the clip will play without captions")
    else:
        rep.ok(name, f"{cues} cue{'s' if cues != 1 else ''}")


def frame_stats(path: Path) -> dict:
    """Decode a frame and measure it. Raises on a file Pillow cannot decode."""
    from PIL import Image, ImageFilter, ImageStat

    with Image.open(path) as im:
        im.load()
        fmt, size = im.format, im.size
        gray = im.convert("L")
    gray.thumbnail((640, 640))
    # FIND_EDGES marks the image border as an edge; crop it so a blurry frame does not look sharp
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edges = edges.crop((2, 2, max(3, edges.width - 2), max(3, edges.height - 2)))
    return {
        "format": fmt,
        "size": size,
        "mean": ImageStat.Stat(gray).mean[0],
        "edge_var": ImageStat.Stat(edges).var[0],
    }


def check_frame(rep: Report, name: str, path: Path) -> None:
    try:
        s = frame_stats(path)
    except Exception as e:  # Pillow raises several types for broken images
        rep.fail(name, f"does not decode: {type(e).__name__}")
        return
    w, h = s["size"]
    if s["format"] != "JPEG":
        rep.warn(name, f"is {s['format']}, expected JPEG")
    if max(w, h) < SMALL_SIDE:
        rep.warn(name, f"only {w}x{h}, too small to judge")
    if s["mean"] < BLACK_MEAN:
        rep.fail(name, f"near-black (mean {s['mean']:.0f} of 255)")
    elif s["edge_var"] < BLUR_EDGE_VAR:
        rep.warn(name, f"looks blurry or flat (edge variance {s['edge_var']:.0f}, want {BLUR_EDGE_VAR:.0f}+)")
    else:
        rep.ok(name, f"{w}x{h}, sharp")


# ---------------------------------------------------------------- lesson checks

def check_question(rep: Report, name: str, step: dict, check_type: str) -> None:
    q = step.get("check_question", None if check_type == "manual" else "Is this step finished?")
    if q is not None and not isinstance(q, str):
        rep.fail(name, "check_question must be a string")
        return
    q = (q or "").strip()
    if check_type == "manual":
        if q:
            rep.warn(name, "manual step has a check_question; it is ignored, contract says \"\"")
        else:
            rep.ok(name, "manual")
        return
    if not q:
        rep.fail(name, "camera step needs a check_question")
        return
    words = re.findall(r"[A-Za-z']+", q.lower())
    if not words or words[0] not in YES_NO_STARTS or not q.endswith("?"):
        rep.warn(name, "question should be yes/no, like \"Is ...?\" or \"Are ...?\"")
    colors = sorted({w for w in words if w in COLOR_WORDS})
    if colors:
        rep.warn(name, f"mentions color ({', '.join(colors)}); ask about shape or count instead")
    rep.ok(name, "camera, yes/no")


def check_extras(rep: Report, name: str, step: dict, n: int, start: float | None, end: float | None) -> None:
    """Title, prerequisites and the NEW optional fields (ref_time, common_mistake, self_test)."""
    title = step.get("title", "")
    if not isinstance(title, str):
        rep.fail(name, "title must be a string")
    elif not title.strip():
        rep.warn(name, "no title")

    pre = step.get("prerequisites", [])
    if not isinstance(pre, list) or not all(is_int(p) for p in pre):
        rep.fail(name, "prerequisites must be a list of ints")
    else:
        bad = [p for p in pre if not 1 <= p < n]
        if bad:
            rep.fail(name, f"prerequisites {bad} must each be 1 to {n - 1}")

    if step.get("ref_time") is not None:
        try:
            t = parse_time(step["ref_time"])
        except ValueError as e:
            rep.fail(name, f"ref_time: {e}")
        else:
            if start is not None and end is not None and not start <= t <= end:
                rep.fail(name, f"ref_time {fmt_s(t)} is outside the step ({fmt_s(start)} to {fmt_s(end)})")

    if "common_mistake" in step and not isinstance(step["common_mistake"], str):
        rep.fail(name, "common_mistake must be a string")

    st = step.get("self_test")
    if st is not None:
        if (not isinstance(st, dict) or st.get("own") not in ANSWERS or st.get("prev") not in ANSWERS
                or not isinstance(st.get("ok"), bool)):
            rep.fail(name, 'self_test must be {"own":"yes|no|unsure","prev":"yes|no|unsure","ok":bool}')
        elif not st["ok"] and step.get("check_type", "camera") != "manual":
            rep.warn(name, "teach-time self-test failed; consider making this step manual")
    rep.ok(name, "fields valid")


def check_string_list(rep: Report, name: str, data: dict, key: str) -> None:
    if key not in data:
        return
    v = data[key]
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        rep.fail(name, f"{key} must be a list of non-empty strings")


def lint(folder: Path) -> Report:
    folder = Path(folder)
    if folder.is_file() and folder.name == "lesson.json":
        folder = folder.parent
    rep = Report(folder.name, folder)

    # lesson.json
    path = folder / "lesson.json"
    if not path.is_file():
        rep.fail("lesson.json", "missing")
        return rep
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        rep.fail("lesson.json", f"does not parse: {e}")
        return rep
    if not isinstance(data, dict):
        rep.fail("lesson.json", "top level must be an object")
        return rep
    rep.ok("lesson.json", "parses")

    # top-level fields and id
    if not ID_RE.match(folder.name):
        rep.fail("lesson id", f"folder name {folder.name!r} breaks the id rule")
    lid = data.get("id", folder.name)
    if not isinstance(lid, str) or not ID_RE.match(lid):
        rep.fail("lesson id", f"id {lid!r} breaks the id rule")
    elif lid != folder.name:
        rep.warn("lesson id", f"id {lid!r} differs from folder {folder.name!r}; the hub uses the folder name")
    else:
        rep.lesson_id = lid
        rep.ok("lesson id", lid)

    top = "top-level fields"
    if "title" in data and not isinstance(data["title"], str):
        rep.fail(top, "title must be a string")
    video = data.get("video", "norm.mp4")
    bad = safe_rel_path(video)
    if bad:
        rep.fail(top, f"video {bad}")
        video = None
    steps = data.get("steps", [])
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        rep.fail(top, "steps must be a list of objects")
        steps = []
    check_string_list(rep, top, data, "safety")
    check_string_list(rep, top, data, "tools")
    rep.ok(top, "valid")

    if not steps:
        rep.warn("steps", "no steps; the lesson is done as soon as it opens")
        return rep

    # numbering
    ns = [s.get("n", i + 1) for i, s in enumerate(steps)]
    if not all(is_int(n) for n in ns):
        rep.fail("step numbers", "every n must be an int")
    elif ns != list(range(1, len(steps) + 1)):
        rep.fail("step numbers", f"n must run 1 to {len(steps)} in order, found {ns}")
    else:
        rep.ok("step numbers", f"1 to {len(steps)}")

    # timing
    spans: list[tuple[float, float] | None] = []
    for i, s in enumerate(steps, 1):
        if "start" not in s or "end" not in s:
            rep.fail("timing", f"step {i} needs start and end")
            spans.append(None)
            continue
        try:
            a, b = parse_time(s["start"]), parse_time(s["end"])
        except ValueError as e:
            rep.fail("timing", f"step {i}: {e}")
            spans.append(None)
            continue
        if a >= b:
            rep.fail("timing", f"step {i}: start {fmt_s(a)} is not before end {fmt_s(b)}")
        spans.append((a, b))
    for i in range(1, len(spans)):
        prev, cur = spans[i - 1], spans[i]
        if prev is None or cur is None:
            continue
        if cur[0] < prev[1] - 0.05:
            rep.fail("timing", f"step {i + 1} starts at {fmt_s(cur[0])}, before step {i} ends at {fmt_s(prev[1])}")
        elif cur[0] > prev[1] + 0.05:
            rep.warn("timing", f"gap of {fmt_s(cur[0] - prev[1])} between steps {i} and {i + 1}")
    rep.ok("timing", "start before end, contiguous")

    # full video
    last_end = max((sp[1] for sp in spans if sp), default=None)
    if video:
        vpath = folder / video
        if not vpath.is_file():
            rep.fail("video", f"{video} missing")
        else:
            try:
                vdur = probe_duration(probe(vpath))
            except RuntimeError as e:
                rep.fail("video", f"ffprobe cannot read {video}: {e}")
                vdur = None
            if vdur is not None and last_end is not None and last_end > vdur + DURATION_TOLERANCE:
                rep.fail("video", f"last step ends at {fmt_s(last_end)}, {video} is {fmt_s(vdur)}")
            elif vdur is not None:
                rep.ok("video", f"{video} {fmt_s(vdur)}")

    # per step
    for i, s in enumerate(steps, 1):
        nn = f"{i:02d}"
        span = spans[i - 1]
        start, end = (span if span else (None, None))
        expected = end - start if span and end > start else None
        label = f"step {i}"

        files = {}
        for key, default in (("clip", f"clips/{nn}.mp4"), ("captions", f"captions/{nn}.vtt"),
                             ("ref_frame", f"frames/{nn}.jpg")):
            rel = s.get(key, default)
            bad = safe_rel_path(rel)
            if bad:
                rep.fail(f"{label} files", f"{key} {bad}")
            elif not (folder / rel).is_file():
                rep.fail(f"{label} files", f"{rel} missing")
            else:
                files[key] = folder / rel
        rep.ok(f"{label} files", "clip, captions, frame present")

        clip_len = check_clip(rep, f"{label} clip", files["clip"], expected) if "clip" in files else None
        if "captions" in files:
            check_vtt(rep, f"{label} captions", files["captions"], clip_len if clip_len is not None else expected)
        if "ref_frame" in files:
            check_frame(rep, f"{label} frame", files["ref_frame"])

        ctype = s.get("check_type", "camera")
        if ctype not in ("camera", "manual"):
            rep.fail(f"{label} check", f"check_type {ctype!r} must be camera or manual")
        else:
            check_question(rep, f"{label} check", s, ctype)
        check_extras(rep, f"{label} fields", s, i, start, end)
    return rep


# ---------------------------------------------------------------- output

def render(rep: Report) -> str:
    rows = rep.checks()
    width = max([len("Check")] + [len(r["check"]) for r in rows])
    try:
        shown = rep.path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        shown = rep.path
    out = [f"{rep.lesson_id}  ({shown})", f"  {'Check'.ljust(width)}  Result  Detail"]
    for r in rows:
        out.append(f"  {r['check'].ljust(width)}  {r['result'].ljust(6)}  {r['detail']}".rstrip())
    c = rep.counts()
    out.append(f"  {rep.result()}: {c[OK]} OK, {c[WARN]} WARN, {c[FAIL]} FAIL")
    return "\n".join(out)


def resolve(arg: str) -> Path:
    """A lesson folder path, or a bare id looked up in <repo>/lessons."""
    p = Path(arg)
    if p.exists() or "/" in arg:
        return p
    return REPO / "lessons" / arg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lesson_lint.py", description="Check lesson folders against CONTRACT.md section 3.")
    ap.add_argument("lessons", nargs="+", help="lesson folders, for example lessons/demo-v1")
    ap.add_argument("--strict", action="store_true", help="exit 1 on WARN too")
    ap.add_argument("--json", action="store_true", help="print JSON instead of tables")
    a = ap.parse_args(argv)

    reports = []
    for arg in a.lessons:
        folder = resolve(arg)
        if not folder.exists():
            print(f"lesson_lint: {arg}: no such folder", file=sys.stderr)
            return 2
        reports.append(lint(folder))

    if a.json:
        print(json.dumps([r.as_dict() for r in reports], indent=2))
    else:
        print("\n\n".join(render(r) for r in reports))

    worst = max(_RANK[r.result()] for r in reports)
    return 1 if worst == _RANK[FAIL] or (a.strict and worst >= _RANK[WARN]) else 0


if __name__ == "__main__":
    sys.exit(main())

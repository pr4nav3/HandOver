"""Teach pipeline: one expert video in, a lesson folder of per-step clips out.

normalize -> extract (one Gemini call) -> cut. See CONTRACT.md for the lesson layout.

CLI (run from the repo root):
  .venv/bin/python -m server.teach VIDEO --id fortune-teller-v1 --title "Fold a fortune teller"
      [--steps-json steps.json] [--concat more.mov ...]
  .venv/bin/python -m server.teach --recut lessons/<id>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

REPO = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

MODEL = os.environ.get("HANDOVER_TEACH_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL_HINT = "gemini-3.1-pro-preview"
UPLOAD_TIMEOUT_S = 300

Progress = Callable[[str, str], None]


def noop(status: str, message: str) -> None:
    pass


# ---------------------------------------------------------------- schema

class Step(BaseModel):
    start: str
    end: str
    title: str
    check_question: str
    prerequisites: list[int]


class Segment(BaseModel):
    start: float
    end: float
    text: str


class Extraction(BaseModel):
    steps: list[Step]
    transcript: list[Segment]


PROMPT = """You are watching one video of an expert doing a hands-on task while narrating it out loud.
Split the video into the ordered steps a beginner would follow to repeat the task.

How to find step boundaries:
- The narration is the primary signal. A new step starts when the expert starts describing a new action
  ("now fold...", "next...", "then take..."). Use the video to confirm the action really changes there
  and to place the boundary at the moment the hands start the new action.
- Steps are in order, contiguous and cover the whole task: each step's end equals the next step's start.
  The first step starts at the beginning of the task and the last step ends when the task is finished.
- Prefer 3 to 12 steps. One step is one physical action with a clear result. Do not merge unrelated actions
  and do not split one action into tiny pieces.

For each step give:
- start and end as "MM:SS" timestamps in the video.
- title: an imperative instruction of 4 to 8 words, for example "Fold all four corners to the center".
- check_question: one yes/no question about the visible state of the object right after the step is done,
  answerable from a single camera photo, for example "Is the paper a smaller square with four triangular
  flaps meeting at the center?". A "yes" must mean the step is done. If the result of the step cannot be
  seen in a photo (for example a crease that is made and then unfolded, a felt tension, a sound, a smell),
  write exactly: manual
- prerequisites: the 1-based numbers of earlier steps that must be done before this one. Usually just the
  previous step. Use [] for the first step.

Also give the transcript of the narration: segments of one short sentence or phrase each, with start and
end in seconds (decimal numbers) from the start of the video, and the spoken text. Transcribe what is said;
do not invent speech. If nothing is said, return an empty transcript.
"""


# ---------------------------------------------------------------- helpers

def _run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:3])} ...\n{tail}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RuntimeError(f"could not read duration of {path}: {out.stderr.strip()}")


def has_audio(path: Path) -> bool:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return bool(out.stdout.strip())


def parse_time(value) -> float:
    """Accepts seconds (number or numeric string), "MM:SS", "MM:SS.s" or "HH:MM:SS"."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    parts = s.split(":")
    try:
        total = 0.0
        for part in parts:
            total = total * 60 + float(part)
        return total
    except ValueError:
        raise ValueError(f"bad timestamp: {value!r}")


def fmt_mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}:{s % 60:02d}"


def fmt_vtt(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def sanitize_id(lesson_id: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", lesson_id.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    if not s:
        raise ValueError("lesson id is empty after sanitizing")
    return s


def lessons_root() -> Path:
    return Path(os.environ.get("HANDOVER_LESSONS") or REPO / "lessons")


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _api_key() -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    env = REPO / ".env"
    if env.exists():
        values = {}
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            values[k] = v.strip().strip('"').strip("'")
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if values.get(name):
                return values[name]
    raise RuntimeError("no Gemini key: set GEMINI_API_KEY (or GOOGLE_API_KEY) or add it to .env at the repo root")


# ---------------------------------------------------------------- 1. normalize

def normalize(src: Path, dst: Path) -> None:
    """1080p tall, 30 fps constant, H.264 + AAC, faststart. Adds silent audio when the input has none."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    audio = has_audio(src)
    cmd = [FFMPEG, "-y", "-i", str(src)]
    if not audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
    cmd += [
        "-map", "0:v:0", "-map", "0:a:0" if audio else "1:a:0",
        "-vf", "scale=-2:1080,format=yuv420p", "-r", "30", "-fps_mode", "cfr",
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(dst),
    ]
    _run(cmd)


def concat(normalized: list[Path], dst: Path) -> None:
    """Joins already normalized files (same codec settings) without re-encoding."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in normalized:
            f.write("file '" + str(Path(p).resolve()).replace("'", "'\\''") + "'\n")
        listfile = f.name
    try:
        _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy",
              "-movflags", "+faststart", str(dst)])
    finally:
        os.unlink(listfile)


# ---------------------------------------------------------------- 2. extract

def _clean_extraction(ex: Extraction, duration: float) -> Extraction:
    """Sort, clamp to the video, drop empty steps and remap prerequisites to the new numbering."""
    indexed = sorted(enumerate(ex.steps, start=1), key=lambda t: parse_time(t[1].start))
    kept: list[tuple[int, Step]] = []
    for old_n, st in indexed:
        a = min(max(0.0, parse_time(st.start)), duration)
        b = min(max(0.0, parse_time(st.end)), duration)
        if b - a < 0.5:
            continue
        kept.append((old_n, st.model_copy(update={"start": fmt_mmss(a), "end": fmt_mmss(b)})))
    renum = {old: new for new, (old, _) in enumerate(kept, start=1)}
    steps = []
    for new_n, (_, st) in enumerate(kept, start=1):
        pre = sorted({renum[p] for p in st.prerequisites if p in renum and renum[p] < new_n})
        steps.append(st.model_copy(update={"prerequisites": pre, "title": st.title.strip()}))
    if not steps:
        raise RuntimeError("extraction produced no usable steps")
    return Extraction(steps=steps, transcript=ex.transcript)


def extract(norm: Path) -> Extraction:
    """One Gemini call on the normalized video. Returns steps and transcript."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_api_key(), http_options=types.HttpOptions(api_version="v1beta"))
    f = client.files.upload(file=str(norm))
    deadline = time.time() + UPLOAD_TIMEOUT_S
    while True:
        state = str(getattr(f.state, "value", f.state) or "")
        if state == "ACTIVE":
            break
        if state == "FAILED":
            raise RuntimeError(f"Gemini could not process the uploaded video: {f.error}")
        if time.time() > deadline:
            raise RuntimeError(f"Gemini file upload not ACTIVE after {UPLOAD_TIMEOUT_S} s (state {state})")
        time.sleep(2)
        f = client.files.get(name=f.name)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=Extraction.model_json_schema(),
    )

    def call(with_fps: bool):
        video = types.Part(
            file_data=types.FileData(file_uri=f.uri, mime_type=f.mime_type),
            video_metadata=types.VideoMetadata(fps=2) if with_fps else None,
        )
        contents = [types.Content(role="user", parts=[video, types.Part(text=PROMPT)])]
        return client.models.generate_content(model=MODEL, contents=contents, config=config)

    try:
        try:
            resp = call(True)
        except Exception as e:
            msg = str(e).lower()
            if "video_metadata" in msg or "fps" in msg:
                resp = call(False)
            else:
                raise
    except Exception as e:
        raise RuntimeError(
            f"Gemini call failed with model {MODEL}: {e}. "
            f"Try HANDOVER_TEACH_MODEL={FALLBACK_MODEL_HINT}"
        ) from e
    finally:
        try:
            client.files.delete(name=f.name)
        except Exception:
            pass

    if not resp.text:
        raise RuntimeError("Gemini returned an empty response")
    return Extraction.model_validate_json(resp.text)


def mock_extraction(duration: float, steps_json: Path | None) -> Extraction:
    """Steps from a JSON file (same shape as Extraction), or three equal placeholder steps."""
    if steps_json:
        return Extraction.model_validate_json(Path(steps_json).read_text())
    third = duration / 3
    steps = [
        Step(start=fmt_mmss(i * third), end=fmt_mmss(duration if i == 2 else (i + 1) * third),
             title=f"Placeholder step {i + 1}", check_question="manual",
             prerequisites=[i] if i else [])
        for i in range(3)
    ]
    return Extraction(steps=steps, transcript=[])


# ---------------------------------------------------------------- 3. cut

def _write_vtt(path: Path, transcript: list[Segment], start: float, length: float) -> None:
    lines = ["WEBVTT", ""]
    for seg in transcript:
        a = max(seg.start, start) - start
        b = min(seg.end, start + length) - start
        a, b = max(0.0, a), min(length, b)
        text = " ".join(seg.text.replace("-->", "->").split())
        if b - a < 0.05 or not text:
            continue
        lines += [f"{fmt_vtt(a)} --> {fmt_vtt(b)}", text, ""]
    path.write_text("\n".join(lines) + "\n")


def _last_frame(clip: Path, out: Path) -> None:
    for offset in ("-0.1", "-0.5", "-1.0"):
        out.unlink(missing_ok=True)
        p = subprocess.run([FFMPEG, "-y", "-sseof", offset, "-i", str(clip), "-frames:v", "1", "-q:v", "2", str(out)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return
    raise RuntimeError(f"could not grab last frame of {clip}")


def cut(lesson_dir: Path, extraction: Extraction, lesson_id: str | None = None, title: str | None = None) -> dict:
    """Cuts clips, captions and reference frames per step and writes lesson.json and extraction.json."""
    lesson_dir = Path(lesson_dir)
    norm = lesson_dir / "norm.mp4"
    duration = probe_duration(norm)
    old = {}
    if (lesson_dir / "lesson.json").exists():
        old = json.loads((lesson_dir / "lesson.json").read_text())
    lesson_id = lesson_id or old.get("id") or lesson_dir.name
    title = title or old.get("title") or lesson_id

    for sub in ("clips", "captions", "frames"):
        shutil.rmtree(lesson_dir / sub, ignore_errors=True)
        (lesson_dir / sub).mkdir(parents=True)

    steps_out = []
    for n, st in enumerate(extraction.steps, start=1):
        a = min(max(0.0, parse_time(st.start)), duration)
        b = min(max(0.0, parse_time(st.end)), duration)
        if b - a < 0.2:
            raise ValueError(f"step {n} has no length after clamping ({st.start} to {st.end}, video {duration:.1f} s)")
        nn = f"{n:02d}"
        clip = lesson_dir / "clips" / f"{nn}.mp4"
        _run([FFMPEG, "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(norm),
              "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-c:a", "aac",
              "-movflags", "+faststart", str(clip)])
        length = probe_duration(clip)
        _write_vtt(lesson_dir / "captions" / f"{nn}.vtt", extraction.transcript, a, length)
        _last_frame(clip, lesson_dir / "frames" / f"{nn}.jpg")
        question = st.check_question.strip()
        manual = question.lower().strip(" .") == "manual" or not question
        steps_out.append({
            "n": n,
            "title": st.title.strip(),
            "start": fmt_mmss(a),
            "end": fmt_mmss(b),
            "clip": f"clips/{nn}.mp4",
            "captions": f"captions/{nn}.vtt",
            "ref_frame": f"frames/{nn}.jpg",
            "check_type": "manual" if manual else "camera",
            "check_question": "" if manual else question,
            "prerequisites": [p for p in st.prerequisites if 1 <= p < n],
        })

    lesson = {"id": lesson_id, "title": title, "video": "norm.mp4", "steps": steps_out}
    _write_json(lesson_dir / "extraction.json", json.loads(extraction.model_dump_json()))
    _write_json(lesson_dir / "lesson.json", lesson)
    return lesson


# ---------------------------------------------------------------- 4. recut

def recut(lesson_dir: Path) -> dict:
    """Rebuilds clips, captions and frames from lesson.json (possibly hand-edited) and the saved transcript."""
    lesson_dir = Path(lesson_dir)
    lesson = json.loads((lesson_dir / "lesson.json").read_text())
    transcript: list[Segment] = []
    ex_path = lesson_dir / "extraction.json"
    if ex_path.exists():
        transcript = Extraction.model_validate_json(ex_path.read_text()).transcript
    steps = [
        Step(start=str(s["start"]), end=str(s["end"]), title=s["title"],
             check_question="manual" if s.get("check_type") == "manual" else (s.get("check_question") or "manual"),
             prerequisites=list(s.get("prerequisites") or []))
        for s in lesson["steps"]
    ]
    return cut(lesson_dir, Extraction(steps=steps, transcript=transcript), lesson.get("id"), lesson.get("title"))


# ---------------------------------------------------------------- 5. full pipeline

def build(srcs: list[Path], lesson_id: str, title: str, progress: Progress = noop,
          steps_json: Path | None = None) -> dict:
    lesson_id = sanitize_id(lesson_id)
    lesson_dir = lessons_root() / lesson_id
    lesson_dir.mkdir(parents=True, exist_ok=True)
    norm = lesson_dir / "norm.mp4"

    progress("normalizing", "Converting video to 1080p 30 fps")
    if len(srcs) == 1:
        normalize(Path(srcs[0]), norm)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            parts = []
            for i, src in enumerate(srcs):
                part = Path(tmp) / f"part{i:02d}.mp4"
                progress("normalizing", f"Converting part {i + 1} of {len(srcs)}")
                normalize(Path(src), part)
                parts.append(part)
            concat(parts, norm)
    duration = probe_duration(norm)

    if steps_json or os.environ.get("HANDOVER_TEACH_MOCK") == "1":
        progress("extracting", "Using provided steps (mock mode)")
        extraction = mock_extraction(duration, steps_json)
    else:
        progress("extracting", f"Finding steps with {MODEL}")
        extraction = extract(norm)
    extraction = _clean_extraction(extraction, duration)

    progress("cutting", f"Cutting {len(extraction.steps)} step clips")
    lesson = cut(lesson_dir, extraction, lesson_id, title)
    progress("done", f"{len(lesson['steps'])} steps ready")
    return lesson


def process_upload(src: Path, lesson_id: str, title: str, progress: Progress = noop,
                   steps_json: Path | None = None) -> dict:
    """normalize -> extract -> cut. Returns lesson.json as a dict. Raises on failure."""
    return build([Path(src)], lesson_id, title, progress, steps_json)


# ---------------------------------------------------------------- 6. CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.teach", description="Turn one expert video into a lesson.")
    ap.add_argument("video", nargs="?", type=Path)
    ap.add_argument("--id", dest="lesson_id")
    ap.add_argument("--title")
    ap.add_argument("--steps-json", type=Path)
    ap.add_argument("--concat", nargs="+", type=Path, default=[], help="more videos appended after VIDEO")
    ap.add_argument("--recut", type=Path, metavar="LESSON_DIR")
    args = ap.parse_args(argv)

    def show(status: str, message: str) -> None:
        print(f"[{status}] {message}", flush=True)

    t0 = time.time()
    if args.recut:
        lesson = recut(args.recut)
        print(f"[done] recut {len(lesson['steps'])} steps in {args.recut} ({time.time() - t0:.1f} s)")
        return 0
    if not args.video or not args.lesson_id:
        ap.error("VIDEO and --id are required (or use --recut LESSON_DIR)")
    lesson = build([args.video, *args.concat], args.lesson_id, args.title or args.lesson_id, show, args.steps_json)
    print(f"[done] {lessons_root() / lesson['id']} ({time.time() - t0:.1f} s)")
    for s in lesson["steps"]:
        print(f"  {s['n']:2d}. {s['start']}-{s['end']}  {s['title']}  [{s['check_type']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

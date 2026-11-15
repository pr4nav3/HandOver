"""Teach pipeline: one expert video in, a lesson folder of per-step clips out.

normalize -> extract (one Gemini call) -> cut. See CONTRACT.md for the lesson layout.

CLI (run from the repo root):
  .venv/bin/python -m server.teach VIDEO --id fortune-teller-v1 --title "Fold a fortune teller"
      [--steps-json steps.json] [--concat more.mov ...] [--dry-run]
  .venv/bin/python -m server.teach --recut lessons/<id> [--dry-run]
  .venv/bin/python -m server.teach --self-test lessons/<id>

--dry-run prints the planned cuts and writes nothing (a new video needs --steps-json or HANDOVER_TEACH_MOCK=1,
because a dry run never calls Gemini).

Exit codes: 0 ok, 1 something failed (ffmpeg, Gemini, files), 2 bad input or usage,
3 self-test ran but at least one camera step failed it (make those steps manual or reword their question).
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, ValidationError, field_validator

from server import config

REPO = Path(__file__).resolve().parent.parent
log = logging.getLogger("handover.teach")
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ and HLG, what iPhones record in HDR
SDR_TAGS = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
SDR_FRAME_TAGS = "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
# Full range input (yuvj420p from cameras or JPEG-built videos) is squeezed to TV range 8-bit 4:2:0: browsers
# and our lesson lint expect plain yuv420p.
TV_RANGE = "in_range=auto:out_range=tv"
CLIP_VF = f"scale={TV_RANGE},format=yuv420p,{SDR_FRAME_TAGS}"
# a keyframe every second and none from scene cuts, so the player can seek a clip smoothly
SEEK_TAGS = ["-force_key_frames", "expr:gte(t,n_forced*1)", "-sc_threshold", "0", "-pix_fmt", "yuv420p"]

MODEL = config.get("HANDOVER_TEACH_MODEL")  # value at import, kept for old callers; code uses _model()


def _model() -> str:
    """Read per call (server/config.py), so a changed HANDOVER_TEACH_MODEL applies without a restart."""
    return str(config.get("HANDOVER_TEACH_MODEL"))
UPLOAD_TIMEOUT_S = 300
REQUEST_TIMEOUT_MS = 600_000     # one extraction call may take minutes on a long video
MAX_OUTPUT_TOKENS = 32768
INLINE_LIMIT = 18 * 1024 * 1024  # proxies under this go inline in the request; bigger ones use the Files API
LONG_VIDEO_S = 300               # above this the model samples 1 frame per second instead of 2

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
    ref_time: str = ""  # model hint: when the finished state is clearly visible with hands clear
    common_mistake: str = ""


class Segment(BaseModel):
    """Stored in seconds. "MM:SS" strings (what the model writes) are accepted and converted."""
    start: float
    end: float
    text: str

    @field_validator("start", "end", mode="before")
    @classmethod
    def _seconds(cls, v):
        return parse_time(v) if isinstance(v, str) else v


class Extraction(BaseModel):
    transcript: list[Segment]
    steps: list[Step]
    safety: list[str] = []
    tools: list[str] = []


class _WireSegment(BaseModel):
    """What the model writes for one transcript segment: times as "MM:SS" strings, like step times."""
    start: str = Field(description='"MM:SS" or "MM:SS.s"')
    end: str = Field(description='"MM:SS" or "MM:SS.s"')
    text: str


class _WireExtraction(BaseModel):
    """The response schema. transcript comes first so the model writes the narration before choosing steps.
    No descriptions on fields whose type is a model: a $ref with siblings can be rejected."""
    transcript: list[_WireSegment]
    steps: list[Step]
    safety: list[str]
    tools: list[str]


def gemini_schema() -> dict:
    """The response schema with every field required, so the model always fills ref_time, safety and so on.
    The defaults on Step and Extraction only exist so older extraction.json files and steps files still load."""
    schema = _WireExtraction.model_json_schema()
    for node in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in node:
            node["required"] = list(node["properties"])
    return schema


def _from_wire(text: str) -> Extraction:
    """Parses the model's JSON. Transcript segments with unreadable times are dropped, not fatal."""
    wire = _WireExtraction.model_validate_json(text)
    transcript = []
    for seg in wire.transcript:
        try:
            transcript.append(Segment(start=parse_time(seg.start), end=parse_time(seg.end), text=seg.text))
        except ValueError:
            continue
    return Extraction(transcript=transcript, steps=wire.steps, safety=wire.safety, tools=wire.tools)


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
  flaps meeting at the center?". A "yes" must mean the step is done. Describe the state by shape, outline,
  number of corners, flaps, folds or seams, and which side is up. It must hold at any rotation, position
  and size: the learner's camera sees the object at its own angle. Never use color: the learner's
  material and light may differ. The question must tell this step's result apart from the previous step's
  result. If the result of the step cannot be seen in a photo (for example a crease that is made and then
  unfolded, a felt tension, a sound, a smell), write exactly: manual
- prerequisites: the 1-based numbers of earlier steps that must be done before this one. Usually just the
  previous step. Use [] for the first step.
- ref_time: one "MM:SS.s" timestamp inside this step, as late as possible, where the finished result of the
  step is fully visible, still, sharp, and not covered by hands or tools. Use "" if there is no such moment.
- common_mistake: the most likely mistake a beginner makes on this step, as a short instruction that fixes
  it, at most 8 words, for example "Flip it over first.". Use "" if the narration and video give no reason
  to expect one. Do not invent hazards or mistakes.

Also give, for the whole task:
- safety: short warnings the expert actually says or clearly shows (for example "Wear gloves."), each at most
  10 words. Use [] if there are none.
- tools: the tools and materials the expert names or uses, each a short noun phrase (for example
  "15 mm wrench"). Use [] if there are none.

First give the transcript of the narration: segments of one short sentence or phrase each, with start and
end as "MM:SS" timestamps in the video (same clock as the steps), and the spoken text. Transcribe what is said;
do not invent speech. If nothing is said, return an empty transcript.
"""


# ---------------------------------------------------------------- helpers

def _bin(name: str) -> str:
    """Path to ffmpeg or ffprobe. Same order as server/replay.py: HANDOVER_FFMPEG (the ffmpeg binary; ffprobe is
    looked for next to it), then PATH (ffmpeg.exe on Windows), then Homebrew's folder on a Mac."""
    override = config.get("HANDOVER_FFMPEG")
    if override:
        override = str(override)
        if not Path(override).is_file():
            raise RuntimeError(f"HANDOVER_FFMPEG points to {override}, which is not a file.")
        if name == "ffmpeg":
            return override
        sibling = Path(override).with_name(name + Path(override).suffix)
        if sibling.is_file():
            return str(sibling)
    found = shutil.which(name)
    if found:
        return found
    brew = Path("/opt/homebrew/bin") / name
    if brew.is_file():
        return str(brew)
    raise RuntimeError(f"{name} not found on PATH. Install ffmpeg and make sure {name} runs from a terminal.")


def _capture(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")


def _run(cmd: list[str]) -> None:
    p = _capture(cmd)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:3])} ...\n{tail}")


def probe_duration(path: Path) -> float:
    out = _capture([_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise RuntimeError(f"could not read duration of {path}: {out.stderr.strip()}")


def audio_stream(path: Path) -> int | None:
    """Index, among the audio streams, of the first one ffmpeg can decode. iPhone .mov files can carry a first
    audio track with no codec (codec_name "none"); mapping it makes ffmpeg refuse the whole file."""
    out = _capture([_bin("ffprobe"), "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name",
                    "-of", "csv=p=0", str(path)])
    for i, line in enumerate(out.stdout.strip().splitlines()):
        codec = line.strip().strip(",").lower()
        if codec and codec not in ("none", "unknown"):
            return i
    return None


def has_audio(path: Path) -> bool:
    return audio_stream(path) is not None


def color_transfer(path: Path) -> str:
    """Transfer function of the first video stream, for example bt709, smpte2084 (PQ) or arib-std-b67 (HLG)."""
    out = _capture([_bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer",
                    "-of", "default=nw=1:nk=1", str(path)])
    return out.stdout.strip().lower()


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
    """ "MM:SS", or "MM:SS.s" (one decimal) when the time is not a whole second, so short steps keep their length."""
    tenths = max(0, int(round(seconds * 10)))
    m, rem = divmod(tenths, 600)
    s, t = divmod(rem, 10)
    return f"{m:02d}:{s:02d}" + (f".{t}" if t else "")


def quantize(seconds: float) -> float:
    """The time fmt_mmss writes, so a clip and its lesson.json timestamps agree."""
    return parse_time(fmt_mmss(seconds))


def fmt_vtt(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def sanitize_id(lesson_id: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", lesson_id.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:64].rstrip("-")  # the read rule allows 64 characters
    if not s:
        raise ValueError("lesson id is empty after sanitizing")
    return s


def lessons_root() -> Path:
    return Path(config.get("HANDOVER_LESSONS") or REPO / "lessons")


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _retry(lambda: tmp.replace(path))  # Windows: the hub may be reading lesson.json at that moment


SWAP_TRIES = 5      # Windows: a folder or file held open by the hub or a shell refuses a rename (WinError 32)
SWAP_WAIT_S = 0.5


def _retry(fn, tries: int = SWAP_TRIES, wait: float = SWAP_WAIT_S):
    """fn(), retried on PermissionError (Windows sharing violations are usually brief). Re-raises the last one."""
    for k in range(tries):
        try:
            return fn()
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(wait)


def _env_file() -> dict[str, str]:
    """KEY=value pairs from <repo>/.env (never printed)."""
    env = REPO / ".env"
    values: dict[str, str] = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            values[k] = v.strip().strip('"').strip("'")
    return values


def _secret(*names: str) -> str | None:
    """The first of names set in the environment, else in <repo>/.env."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    values = _env_file()
    for name in names:
        if values.get(name):
            return values[name]
    return None


def _api_key() -> str:
    key = _secret("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("no Gemini key: set GEMINI_API_KEY (or GOOGLE_API_KEY) or add it to .env at the repo root")
    return key


def _anthropic_key() -> str | None:
    return _secret("ANTHROPIC_API_KEY")


def teach_provider() -> str:
    """Which extractor a new lesson uses: "gemini", "claude" or "mock" (three placeholder steps).
    HANDOVER_TEACH_MOCK wins; then HANDOVER_TEACH_PROVIDER; auto prefers Gemini (it hears the narration and its
    free tier costs nothing), then Claude when ANTHROPIC_API_KEY exists, else placeholders."""
    if config.get("HANDOVER_TEACH_MOCK"):
        return "mock"
    choice = config.get("HANDOVER_TEACH_PROVIDER")
    if choice in ("gemini", "claude"):
        return str(choice)
    if _secret("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return "gemini"
    if _anthropic_key():
        return "claude"
    return "mock"


# ---------------------------------------------------------------- 1. normalize

def normalize(src: Path, dst: Path) -> None:
    """1080p tall, 30 fps constant, H.264 + AAC, faststart, tagged SDR bt709. Adds silent audio when the input
    has none. iPhone HDR (PQ or HLG, bt2020) is converted to the bt709 color matrix so browsers show it SDR."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    audio_idx = audio_stream(src)
    audio = audio_idx is not None
    if color_transfer(src) in HDR_TRANSFERS:
        # Real tone mapping (HLG or PQ to SDR), not just a matrix swap: the matrix-only path blows out white
        # paper and hides creases. Mobius keeps highlight detail and natural color; npl is the nominal peak.
        vf = ("zscale=t=linear:npl=1000,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0,"
              f"zscale=t=bt709:m=bt709:r=tv,format=yuv420p,scale=-2:1080:{TV_RANGE},format=yuv420p")
    else:
        vf = f"scale=-2:1080:{TV_RANGE},format=yuv420p"
    vf += "," + SDR_FRAME_TAGS  # the encoder flags alone lose to the frame tags ffmpeg carries from the input
    cmd = [_bin("ffmpeg"), "-y", "-i", str(src)]
    if not audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
    cmd += [
        "-map", "0:v:0", "-map", f"0:a:{audio_idx}" if audio else "1:a:0",
        "-vf", vf, "-r", "30", "-fps_mode", "cfr",
        "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", *SEEK_TAGS, *SDR_TAGS,
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(dst),
    ]
    _run(cmd)


def concat(normalized: list[Path], dst: Path) -> None:
    """Joins already normalized files (same codec settings) without re-encoding."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in normalized:
            f.write("file '" + Path(p).resolve().as_posix().replace("'", "'\\''") + "'\n")
        listfile = Path(f.name)
    try:
        _run([_bin("ffmpeg"), "-y", "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy",
              "-movflags", "+faststart", str(dst)])
    finally:
        listfile.unlink(missing_ok=True)


# ---------------------------------------------------------------- 2. extract

def _clean_extraction(ex: Extraction, duration: float) -> Extraction:
    """Sort, clamp to the video, drop empty steps and remap prerequisites to the new numbering."""
    indexed = sorted(enumerate(ex.steps, start=1), key=lambda t: parse_time(t[1].start))
    kept: list[tuple[int, Step]] = []
    for old_n, st in indexed:
        a = min(max(0.0, parse_time(st.start)), duration)
        b = min(max(0.0, parse_time(st.end)), duration)
        start, end = fmt_mmss(a), fmt_mmss(b)
        if b - a < 0.5 or start == end:
            continue
        kept.append((old_n, st.model_copy(update={"start": start, "end": end})))
    renum = {old: new for new, (old, _) in enumerate(kept, start=1)}
    steps = []
    for new_n, (_, st) in enumerate(kept, start=1):
        pre = sorted({renum[p] for p in st.prerequisites if p in renum and renum[p] < new_n})
        steps.append(st.model_copy(update={"prerequisites": pre, "title": st.title.strip(),
                                           "ref_time": st.ref_time.strip(),
                                           "common_mistake": " ".join(st.common_mistake.split())}))
    if not steps:
        raise RuntimeError("extraction produced no usable steps")
    return Extraction(steps=steps, transcript=ex.transcript, safety=_clean_list(ex.safety), tools=_clean_list(ex.tools))


def _clean_list(items) -> list[str]:
    """Strings only, whitespace collapsed, empty and repeated entries (ignoring case) dropped, order kept."""
    out, seen = [], set()
    for item in items or []:
        text = " ".join(str(item).split()) if isinstance(item, (str, int, float)) else ""
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def _first_step_manual(ex: Extraction) -> Extraction:
    """New extractions only: the first step is the starting setup, which a camera check cannot judge reliably."""
    if not ex.steps:
        return ex
    first = ex.steps[0].model_copy(update={"check_question": "manual"})
    return ex.model_copy(update={"steps": [first, *ex.steps[1:]]})


def _contiguous(ex: Extraction) -> Extraction:
    """New model extractions only: each step ends where the next one starts (the prompt asks for this, but a
    model may leave gaps or overlaps). Starts are kept because they follow the narration onsets; a step left
    shorter than 0.5 s is dropped and its prerequisites renumbered. The last step keeps its own end."""
    steps = list(ex.steps)
    for _ in range(len(steps) + 1):
        changed = False
        for i in range(len(steps) - 1):
            if steps[i].end != steps[i + 1].start:
                steps[i] = steps[i].model_copy(update={"end": steps[i + 1].start})
                changed = True
        keep = [i for i, st in enumerate(steps) if parse_time(st.end) - parse_time(st.start) >= 0.5]
        if len(keep) < len(steps):
            renum = {old + 1: new + 1 for new, old in enumerate(keep)}
            steps = [steps[i].model_copy(update={"prerequisites": sorted(
                {renum[q] for q in steps[i].prerequisites if q in renum and renum[q] < new + 1})})
                for new, i in enumerate(keep)]
            changed = True
        if not changed:
            break
    if not steps:
        raise RuntimeError("extraction produced no usable steps")
    return ex.model_copy(update={"steps": steps})


_FLIP_WORDS = re.compile(r"\b(flip|flips|flipping|turn (it|the \w+|everything) over|turn over)\b", re.IGNORECASE)
_FLIP_TAIL = re.compile(r"\s*(,\s*)?(and|then)?\s*(flip|turn)\b.*$", re.IGNORECASE)


def _split_flips(ex: Extraction) -> Extraction:
    """New model extractions only: flipping the object over is always its own step. When a step's narration has a
    flip line starting more than 1 s inside the step (the model merged the flip into the action before it), the
    step is split at that line. The flip part keeps the step's end, question, ref_time and common_mistake (they
    describe the state after the flip); the part before has no question of its own, so it becomes manual."""
    groups: list[list[Step]] = []  # the new steps each old step became
    is_flip = [bool(_FLIP_WORDS.match(st.title.strip())) for st in ex.steps]
    for i, st in enumerate(ex.steps):
        a, b = parse_time(st.start), parse_time(st.end)
        line = next((seg for seg in ex.transcript
                     if a + 1.0 <= seg.start <= b - 1.0 and _FLIP_WORDS.search(seg.text)), None)
        # skip when this step is the flip, or the next one already is (it only starts a little late)
        if line is None or is_flip[i] or (i + 1 < len(is_flip) and is_flip[i + 1]):
            groups.append([st])
            continue
        cut_at = fmt_mmss(quantize(line.start))
        before = _FLIP_TAIL.sub("", st.title).strip(" ,") or st.title
        groups.append([st.model_copy(update={"end": cut_at, "title": before, "check_question": "manual",
                                             "ref_time": "", "common_mistake": ""}),
                       st.model_copy(update={"start": cut_at, "title": "Flip it over"})])
    if all(len(g) == 1 for g in groups):
        return ex
    first_new, last_new, n = {}, {}, 0  # old step number -> its first and last new step number
    for old, group in enumerate(groups, start=1):
        first_new[old], last_new[old] = n + 1, n + len(group)
        n += len(group)
    steps: list[Step] = []
    for old, group in enumerate(groups, start=1):
        for k, st in enumerate(group):
            if k:  # the flip part follows the part before it
                pre = [first_new[old]]
            else:  # finishing an old step means finishing all of its parts
                pre = sorted({last_new[q] for q in st.prerequisites if q in last_new and q < old})
            steps.append(st.model_copy(update={"prerequisites": pre}))
    return ex.model_copy(update={"steps": steps})


_CREASE_TITLE = re.compile(r"\bcrease|\bfold\b.*\bunfold|\bunfold\b.*\bfold\b", re.IGNORECASE)


def _crease_steps_manual(ex: Extraction) -> Extraction:
    """New model extractions only: a fold-and-unfold or crease step leaves the object looking almost unchanged,
    so a camera check cannot judge it. The prompt says so; this enforces it from the step title."""
    steps = [st.model_copy(update={"check_question": "manual"}) if _CREASE_TITLE.search(st.title) else st
             for st in ex.steps]
    return ex.model_copy(update={"steps": steps})


MIN_STEP_S = 6.0  # default of HANDOVER_MIN_STEP_S


def min_step_s() -> float:
    """HANDOVER_MIN_STEP_S: steps shorter than this are merged into a neighbour (0 turns merging off)."""
    return float(config.env_float("HANDOVER_MIN_STEP_S", MIN_STEP_S, min=0.0, max=600.0))


def _is_flip(st: Step) -> bool:
    return bool(_FLIP_WORDS.match(st.title.strip()))


def _length(st: Step) -> float:
    return parse_time(st.end) - parse_time(st.start)


def _merge_short_steps(ex: Extraction, min_s: float | None = None) -> Extraction:
    """New model extractions only: a step shorter than HANDOVER_MIN_STEP_S (default 6 s) is merged into the step
    before it (the first step into the one after it). Frames-only extraction made 2 to 5 s steps out of
    crease-and-unfold moves and a 2.6 s final step on a real take. The shortest step goes first, repeated until
    none is left. A flip step is never merged and never absorbs another step (flipping is its own step).

    The merged step keeps the longer step's title and common_mistake and the later step's ref_time (its end is
    the later step's end). It is camera only if the surviving (longer) step was camera; its question is then the
    later step's when that one is camera (it describes the merged end state), else the survivor's."""
    min_s = min_step_s() if min_s is None else min_s
    if min_s <= 0 or len(ex.steps) < 2:
        return ex
    items: list[tuple[list[int], Step]] = [([n], st) for n, st in enumerate(ex.steps, start=1)]
    while len(items) > 1:
        short = [k for k, (_, st) in enumerate(items) if _length(st) < min_s and not _is_flip(st)]
        merged = False
        for k in sorted(short, key=lambda k: (_length(items[k][1]), k)):
            target = next((j for j in ((k - 1, k + 1) if k else (k + 1,))
                           if 0 <= j < len(items) and not _is_flip(items[j][1])), None)
            if target is None:
                continue
            i, j = sorted((k, target))
            (m1, first), (m2, second) = items[i], items[j]
            survivor = first if _length(first) >= _length(second) else second
            other = second if survivor is first else first
            if _is_manual(survivor.check_question):
                question = "manual"
            elif not _is_manual(second.check_question):
                question = second.check_question
            else:
                question = survivor.check_question
            step = survivor.model_copy(update={
                "start": first.start, "end": second.end, "check_question": question,
                "ref_time": second.ref_time, "common_mistake": survivor.common_mistake or other.common_mistake})
            items[i:j + 1] = [(m1 + m2, step)]
            merged = True
            break
        if not merged:
            break
    if len(items) == len(ex.steps):
        return ex
    new_of = {old: new for new, (members, _) in enumerate(items, start=1) for old in members}
    steps = []
    for new, (members, st) in enumerate(items, start=1):
        pre = {new_of[p] for m in members for p in ex.steps[m - 1].prerequisites if p in new_of}
        steps.append(st.model_copy(update={"prerequisites": sorted(p for p in pre if p < new)}))
    return ex.model_copy(update={"steps": steps})


# ---------------------------------------------------------------- color guard (check questions)

# Same list as scripts/lesson_lint.py (test_teach checks they match). A learner's paper or light may differ from the
# expert's, so check questions must never depend on color.
COLOR_WORDS = {
    "red", "orange", "yellow", "green", "blue", "purple", "violet", "pink", "white", "black",
    "gray", "grey", "brown", "cyan", "magenta", "teal", "beige", "gold", "silver", "navy",
    "color", "colour", "colored", "coloured",
}
_COLOR_RE = "|".join(sorted(COLOR_WORDS, key=len, reverse=True))
_COLOR_STRIP = re.compile(rf"\b(?:{_COLOR_RE})(?:-colou?red)?\b\s*", re.IGNORECASE)
REPHRASE_PROMPT = """Rewrite each yes/no check question below so it asks about shape, outline, layers, flaps or which
side faces up, never color or rotation. Keep each one a yes/no question about the same finished state of the step, one
sentence ending in "?". Return every question by its number."""


class _Rephrased(BaseModel):
    n: int
    question: str


class _RephraseAnswer(BaseModel):
    questions: list[_Rephrased]


def color_words(text: str) -> list[str]:
    return sorted({w for w in re.findall(r"[A-Za-z']+", (text or "").lower()) if w in COLOR_WORDS})


def strip_colors(question: str) -> str:
    """Last resort: drops color words ("Is the blue side up?" becomes "Is the side up?"). Clumsy but color free.
    Returns "manual" when too little is left to be a real question (fewer than 4 words)."""
    q = _COLOR_STRIP.sub("", question)
    q = re.sub(r"\s+([?,.!])", r"\1", re.sub(r"\s{2,}", " ", q)).strip(" ,")
    if len(re.findall(r"[A-Za-z']+", q)) < 4:
        return "manual"
    return q[:1].upper() + q[1:]


def _rephrase_schema() -> dict:
    schema = _RephraseAnswer.model_json_schema()
    for node in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in node:
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
    return schema


def _rephrase_request(bad: dict[int, Step]) -> str:
    lines = [f"{n}. (step: {st.title}) {st.check_question}" for n, st in bad.items()]
    return REPHRASE_PROMPT + "\n\n" + "\n".join(lines)


def _rephrase_claude(bad: dict[int, Step]) -> dict[int, str]:
    import anthropic

    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key")
    spend = _spend()
    if not spend.allow():
        raise RuntimeError("the Claude spending limit is reached")
    model = _claude_model()
    response = anthropic.Anthropic(api_key=key).messages.create(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": _rephrase_request(bad)}],
        output_config={"format": {"type": "json_schema", "schema": _rephrase_schema()}},
    )
    spend.record(model, response.usage)
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    return {q.n: q.question for q in _RephraseAnswer.model_validate_json(text).questions}


def _rephrase_gemini(bad: dict[int, Step]) -> dict[int, str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_api_key(), http_options=types.HttpOptions(api_version="v1beta", timeout=60_000))
    resp = client.models.generate_content(
        model=_model(), contents=_rephrase_request(bad),
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_json_schema=_rephrase_schema(), max_output_tokens=1024))
    return {q.n: q.question for q in _RephraseAnswer.model_validate_json(resp.text or "").questions}


def guard_colors(ex: Extraction, provider: str, progress: Progress = noop) -> Extraction:
    """New model extractions only: no camera check_question may name a color. Offending questions go to the same
    provider and model in ONE batched rephrase call; a rephrase that still names a color, a failed call, or
    HANDOVER_NO_NETWORK=1 falls back to stripping the color words. Every fallback is logged."""
    bad = {n: st for n, st in enumerate(ex.steps, start=1)
           if not _is_manual(st.check_question) and color_words(st.check_question)}
    if not bad:
        return ex
    progress("extracting", f"Check questions name a color on steps {', '.join(map(str, bad))}; rephrasing")
    new: dict[int, str] = {}
    if config.get("HANDOVER_NO_NETWORK"):
        progress("extracting", "HANDOVER_NO_NETWORK=1: removing the color words instead of rephrasing")
    else:
        try:
            new = (_rephrase_claude if provider == "claude" else _rephrase_gemini)(bad)
        except Exception as e:
            reason = scrub(f"{type(e).__name__}: {e}".splitlines()[0][:160])
            progress("extracting", f"Rephrase call failed ({reason}); removing the color words instead")
            log.warning("color rephrase failed: %s", reason)
    steps = list(ex.steps)
    for n, st in bad.items():
        q = " ".join(str(new.get(n) or "").split())
        if not q or color_words(q):
            q = strip_colors(st.check_question)
            log.warning("step %d: color words stripped from the check question: %r -> %r", n, st.check_question, q)
            what = "made manual (too little left without color words)" if q == "manual" \
                else "removed color words from the check question"
            progress("extracting", f"Step {n}: {what}")
        steps[n - 1] = st.model_copy(update={"check_question": q})
    return ex.model_copy(update={"steps": steps})


def make_proxy(norm: Path, dst: Path) -> None:
    """A small copy for the model: 480 p, 10 fps, mono 48 kbps audio. Same timeline as norm.mp4."""
    _run([_bin("ffmpeg"), "-y", "-i", str(norm), "-vf", "scale=-2:480", "-r", "10",
          "-c:v", "libx264", "-crf", "32", "-preset", "veryfast", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-movflags", "+faststart", str(dst)])


def extract(norm: Path, progress: Progress = noop) -> Extraction:
    """One Gemini call on a small proxy of the normalized video. Returns steps and transcript.

    The proxy goes inline in the request when it is under 18 MB (no upload, no polling), otherwise through the
    Files API. It is deleted afterwards. Its timestamps match norm.mp4."""
    from google import genai
    from google.genai import types

    norm = Path(norm)
    model = _model()
    proxy = norm.with_name("proxy.mp4")
    client = genai.Client(api_key=_api_key(),
                          http_options=types.HttpOptions(api_version="v1beta", timeout=REQUEST_TIMEOUT_MS))
    uploaded = None
    try:
        make_proxy(norm, proxy)
        fps = 1 if probe_duration(proxy) > LONG_VIDEO_S else 2
        size = proxy.stat().st_size
        if size < INLINE_LIMIT:
            progress("extracting", f"Sending a {size / 1e6:.1f} MB proxy inline to {model}")
            source = {"inline_data": types.Blob(data=proxy.read_bytes(), mime_type="video/mp4")}
        else:
            progress("extracting", f"Uploading a {size / 1e6:.1f} MB proxy to the Gemini Files API")
            uploaded = client.files.upload(file=str(proxy))
            deadline = time.time() + UPLOAD_TIMEOUT_S
            while True:
                state = str(getattr(uploaded.state, "value", uploaded.state) or "")
                if state == "ACTIVE":
                    break
                if state == "FAILED":
                    raise RuntimeError(f"Gemini could not process the uploaded video: {uploaded.error}")
                if time.time() > deadline:
                    raise RuntimeError(f"Gemini file upload not ACTIVE after {UPLOAD_TIMEOUT_S} s (state {state})")
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            source = {"file_data": types.FileData(file_uri=uploaded.uri, mime_type=uploaded.mime_type)}

        gen_config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=gemini_schema(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )

        def call(with_fps: bool):
            video = types.Part(**source, video_metadata=types.VideoMetadata(fps=fps) if with_fps else None)
            contents = [types.Content(role="user", parts=[video, types.Part(text=PROMPT)])]
            return client.models.generate_content(model=model, contents=contents, config=gen_config)

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
                f"Gemini call failed with model {model}: {e}. "
                f"Check the key and the free tier limits, or set HANDOVER_TEACH_MODEL to another free model"
            ) from e
    finally:
        proxy.unlink(missing_ok=True)
        if uploaded is not None:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass

    if not resp.text:
        raise RuntimeError("Gemini returned an empty response")
    try:
        return _from_wire(resp.text)
    except ValidationError as e:
        raise RuntimeError(f"Gemini answer did not match the lesson schema: {e}") from None


def mock_extraction(duration: float, steps_json: Path | None) -> Extraction:
    """Steps from a JSON file (same shape as Extraction), or three equal placeholder steps."""
    if steps_json:
        return Extraction.model_validate_json(Path(steps_json).read_text(encoding="utf-8"))
    third = duration / 3
    steps = [
        Step(start=fmt_mmss(i * third), end=fmt_mmss(duration if i == 2 else (i + 1) * third),
             title=f"Placeholder step {i + 1}", check_question="manual",
             prerequisites=[i] if i else [])
        for i in range(3)
    ]
    return Extraction(steps=steps, transcript=[])


# ---------------------------------------------------------------- 2b. Claude fallback (frames only)

CLAUDE_MAX_FRAMES = 120
CLAUDE_MAX_TOKENS = 8000

# Splitting rules both Claude prompts share. Written after an end-to-end test where Haiku merged the flip into the
# fold before it and Sonnet merged the setup with the first fold.
_CLAUDE_STEP_RULES = """- Flipping or turning the object over is always its own step, never part of a fold or another action.
- A fold-and-unfold or crease-only step, where the object looks almost the same afterwards, is manual: its
  check_question is exactly: manual
- The first step is the setup: the material laid out in its starting state, before the first change.
- Each step's title describes the action performed inside that step's own start to end range, not the next one.
- Each check_question asks about the state at the END of that step, after its action is complete.
- Return only steps you can see or hear. No filler steps such as "check that it is finished" or "admire the
  result".
"""

CLAUDE_PROMPT = """These are frames from one video of an expert doing a hands-on task, about one per second.
The text before each image is its timestamp in the video. There is no audio: judge only what you see.
Split the video into the ordered steps a beginner would follow to repeat the task.

How to find step boundaries:
- A new step starts when the hands start a new action with a new visible result.
- Steps are in order, contiguous and cover the whole task: each step's end equals the next step's start.
  The first step starts at the first frame of the task and the last step ends when the task is finished.
- Prefer 3 to 12 steps. One step is one physical action with a clear result. Do not merge unrelated actions
  and do not split one action into tiny pieces.
- Only use timestamps that appear in the frame labels, or times between them.
""" + _CLAUDE_STEP_RULES + "\n" + PROMPT[PROMPT.index("For each step give:"):PROMPT.index("First give the transcript")].replace(
    "the narration and video give", "the video gives").replace(
    "the expert actually says or clearly shows", "the expert clearly shows").replace(
    "the expert names or uses", "the expert uses")


CLAUDE_NARRATED_PROMPT = """These are frames from one video of an expert doing a hands-on task, about one per second,
and a transcript of the expert's narration made by a speech model. The text before each image is its timestamp
in the video; each transcript line is "[start to end] words", on the same clock.
Split the video into the ordered steps a beginner would follow to repeat the task.

How to find step boundaries:
- The narration is the primary boundary signal; the frames confirm it. A new step starts when the expert starts
  describing a new action ("now fold...", "next...", "then take..."). Use the frames to confirm the action
  really changes there and to place the boundary at the moment the hands start the new action.
- Each separately narrated instruction is its own step. Never merge two narrated actions into one step, even
  when they are short or close together.
- Steps are in order, contiguous and cover the whole task: each step's end equals the next step's start.
  The first step starts at the beginning of the task and the last step ends when the task is finished.
- Prefer 3 to 12 steps. One step is one physical action with a clear result. Do not merge unrelated actions
  and do not split one action into tiny pieces.
- Only use timestamps from the frame labels or the transcript, or times between them.
""" + _CLAUDE_STEP_RULES + "\n" + PROMPT[PROMPT.index("For each step give:"):PROMPT.index("First give the transcript")]


PRIOR_PROMPT = """The task is known. Below is a hand-written plan of its steps for this task. Its times are placeholders
and do NOT match this video. Use it as a strong prior: expect the same actions in the same order, and reuse its
titles, check questions and common mistakes when they match what you see. Your job is to find where each planned
action happens in these frames. Follow the video where the expert clearly differs from the plan (an extra action,
a skipped or repeated one, a different order). The expert's hands may stay in the frame the whole time, so there may
be no pause between steps: place each boundary at the moment the hands start the next action.

Plan:
"""


def prior_text(steps_json: Path) -> str:
    """A steps template (lessons/templates/*.steps.json, the Extraction shape) as the prompt's plan section:
    one line per step with its title, whether it is manual, its check question and common mistake. Times are
    left out on purpose: template times are placeholders."""
    ex = Extraction.model_validate_json(Path(steps_json).read_text(encoding="utf-8"))
    lines = []
    for n, st in enumerate(ex.steps, start=1):
        q = "manual" if _is_manual(st.check_question) else st.check_question.strip()
        line = f"{n}. {st.title.strip()} | check_question: {q}"
        if st.common_mistake.strip():
            line += f" | common_mistake: {st.common_mistake.strip()}"
        lines.append(line)
    if not lines:
        raise ValueError(f"{steps_json} has no steps")
    return PRIOR_PROMPT + "\n".join(lines)


# ---------------------------------------------------------------- 2b. local transcription (faster-whisper)

WHISPER_SIZES = {"tiny.en": "75 MB", "base.en": "145 MB", "small.en": "460 MB", "medium.en": "1.5 GB"}
_whisper_models: dict[str, object] = {}  # one loaded model per name, per process


def _whisper_model_name() -> str:
    return str(config.env_str("HANDOVER_WHISPER_MODEL", "small.en"))


def transcribe_mode(provider: str) -> str:
    """HANDOVER_TRANSCRIBE: local (faster-whisper on this Mac), model (the extraction model's own transcript;
    Claude has none), off (no captions). auto is local for Claude and model for Gemini."""
    mode = config.env_choice("HANDOVER_TRANSCRIBE", "auto", ("auto", "local", "model", "off"))
    if mode == "auto":
        return "local" if provider == "claude" else "model"
    return mode


def _load_whisper(name: str, progress: Progress = noop):
    """The faster-whisper model, loaded once per process on CPU with int8. The first use downloads it from
    Hugging Face into the default cache."""
    if name in _whisper_models:
        return _whisper_models[name]
    from faster_whisper import WhisperModel

    try:
        from faster_whisper.utils import download_model

        download_model(name, local_files_only=True)
    except Exception:  # not in the cache yet
        size = WHISPER_SIZES.get(name)
        progress("extracting", f"Downloading speech model {name} once{f', about {size}' if size else ''}")
    model = WhisperModel(name, device="cpu", compute_type="int8")
    _whisper_models[name] = model
    return model


def _audio_16k(media: Path):
    """The audio track as 16 kHz mono float32 samples, decoded by ffmpeg. Passing samples (not a file) keeps
    faster-whisper away from its own av-based decoder, which fails with the av version in our lock file."""
    import numpy as np

    p = subprocess.run([_bin("ffmpeg"), "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-2:]
        raise RuntimeError(f"could not read the audio of {Path(media).name}: {' '.join(tail)}")
    return np.frombuffer(p.stdout, dtype=np.float32)


def transcribe(media: Path, progress: Progress = noop) -> list[Segment]:
    """Narration of a video or audio file as segments in seconds, with faster-whisper (HANDOVER_WHISPER_MODEL,
    default small.en; base.en is faster, medium.en is better) and its voice activity filter. Raises on failure."""
    t0 = time.time()
    model = _load_whisper(_whisper_model_name(), progress)
    progress("extracting", "Transcribing narration")
    # Word timestamps trim each segment to the speech itself; plain segments absorb the
    # silence between lines, which shifted captions and step boundaries by up to 5 s.
    segments, _info = model.transcribe(_audio_16k(media), vad_filter=True, word_timestamps=True)
    out = []
    for seg in segments:
        if not seg.text.strip():
            continue
        words = getattr(seg, "words", None) or []
        start = float(words[0].start) if words else float(seg.start)
        end = float(words[-1].end) if words else float(seg.end)
        out.append(Segment(start=start, end=max(end, start), text=" ".join(seg.text.split())))
    progress("extracting", f"Transcribed {len(out)} narration segments in {time.time() - t0:.1f} s")
    return out


def _transcribe_safely(media: Path, progress: Progress = noop) -> list[Segment] | None:
    """transcribe(), but a missing package, failed download or bad audio gives None and a progress line."""
    try:
        return transcribe(media, progress)
    except Exception as e:
        reason = f"{type(e).__name__}: {e}".splitlines()[0][:160]
        progress("extracting", f"Speech model unavailable ({scrub(reason)}); continuing without a transcript")
        return None


def _transcript_lines(transcript: list[Segment]) -> str:
    return "\n".join(f"[{fmt_mmss(seg.start)} to {fmt_mmss(seg.end)}] {seg.text}" for seg in transcript)


class _ClaudeExtraction(BaseModel):
    steps: list[Step]
    safety: list[str]
    tools: list[str]


def claude_schema() -> dict:
    """Flat schema for output_config.format: every field required, no extra fields, no defaults."""
    schema = _ClaudeExtraction.model_json_schema()
    for node in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in node:
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
            for prop in node["properties"].values():
                prop.pop("default", None)
    return schema


def _claude_model() -> str:
    return str(config.get("HANDOVER_CLAUDE_TEACH_MODEL"))


def sample_frames(video: Path, out_dir: Path, max_frames: int = CLAUDE_MAX_FRAMES) -> list[tuple[float, Path]]:
    """About one JPEG per second, evenly spread and at most max_frames, as (time in seconds, file)."""
    duration = probe_duration(video)
    count = max(1, min(max_frames, int(duration)))
    rate = count / duration if duration > 0 else 1.0
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([_bin("ffmpeg"), "-y", "-v", "error", "-i", str(video), "-vf", f"fps={rate:.6f}", "-frames:v", str(count),
          "-q:v", "4", str(out_dir / "%04d.jpg")])
    files = sorted(out_dir.glob("*.jpg"))
    return [(k / rate, f) for k, f in enumerate(files)]


def _spend():
    """server/spend.py guards the paid Claude budget. Without it, no paid call is made."""
    try:
        from server import spend
    except ImportError:
        raise RuntimeError("server/spend.py is missing, so the Claude budget cannot be checked; "
                           "no paid call was made") from None
    return spend


def extract_claude(norm: Path, progress: Progress = noop, prior: Path | None = None) -> Extraction:
    """One Claude call on about 1 fps frames of a small proxy. Claude cannot hear, so with HANDOVER_TRANSCRIBE
    local (the default for Claude) the narration is transcribed on this Mac first and sent as timestamped text;
    it also becomes the captions. Without a transcript, Claude sees frames only and the captions are empty.
    prior: a steps template for a known task (see prior_text), sent before the instructions as a strong prior."""
    import base64

    import anthropic

    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key: set ANTHROPIC_API_KEY or add it to .env at the repo root")
    spend = _spend()
    model = _claude_model()
    norm = Path(norm)
    with tempfile.TemporaryDirectory(prefix="handover-frames-") as tmp:
        proxy = Path(tmp) / "proxy.mp4"
        make_proxy(norm, proxy)
        frames = sample_frames(proxy, Path(tmp) / "frames")
        content: list[dict] = []
        for t, f in frames:
            content.append({"type": "text", "text": fmt_mmss(t)})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.standard_b64encode(f.read_bytes()).decode()}})
    transcript: list[Segment] = []
    if transcribe_mode("claude") == "local":
        transcript = _transcribe_safely(norm, progress) or []
    if transcript:
        content.insert(0, {"type": "text", "text": "Narration transcript:\n" + _transcript_lines(transcript)})
        content.append({"type": "text", "text": CLAUDE_NARRATED_PROMPT})
        progress("extracting", f"Sending {len(frames)} frames and {len(transcript)} narration lines to {model}")
    else:
        content.append({"type": "text", "text": CLAUDE_PROMPT})
        progress("extracting", f"Sending {len(frames)} frames to {model} (no audio narration: captions will be empty)")
    if prior:
        content.append({"type": "text", "text": prior_text(prior)})
        progress("extracting", f"Using {Path(prior).name} as the step plan prior")
    if not spend.allow():
        raise RuntimeError("the Claude spending limit is reached; no call was made")
    client = anthropic.Anthropic(api_key=key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": claude_schema()}},
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude call failed with model {model}: {e}") from None
    spend.record(model, response.usage)
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to describe this video")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"Claude's answer was cut off at {CLAUDE_MAX_TOKENS} tokens")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError("Claude returned an empty response")
    try:
        got = _ClaudeExtraction.model_validate_json(text)
    except ValidationError as e:
        raise RuntimeError(f"Claude answer did not match the lesson schema: {e}") from None
    return Extraction(transcript=transcript, steps=got.steps, safety=got.safety, tools=got.tools)


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
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _last_frame(clip: Path, out: Path) -> None:
    for offset in ("-0.1", "-0.5", "-1.0"):
        out.unlink(missing_ok=True)
        p = subprocess.run([_bin("ffmpeg"), "-y", "-sseof", offset, "-i", str(clip), "-frames:v", "1", "-q:v", "2", str(out)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return
    raise RuntimeError(f"could not grab last frame of {clip}")


# ---------------------------------------------------------------- 3a. reference frames

REF_TAIL = 0.15        # look for the reference in the last 15% of the step
REF_MIN_WINDOW = 0.3   # seconds; very short steps still get a few frames to compare
REF_END_GAP = 0.05     # stay this far before the step end so the frame belongs to this step
REF_CANDIDATES = 8
THUMB = 96             # stillness is measured on 96x96 gray thumbnails
DARK = 16.0            # mean gray level below this counts as a black frame (fade, lens covered)
# "Hands-free still": there is no hand detector in this repo, so frame difference is the only signal. Measured at
# 10 fps on a real 2.5 min take: hands off the paper gives 0.1 to 0.4, hands holding or slowly folding 1 to 3,
# folding 4 to 12. A frame at or below REF_STILL counts as hands free.
REF_STILL = 0.8
REF_STILL_FPS = 10.0
REF_EXTEND = 2.5       # seconds past the step end searched when the window has no still frame (the pause
                       # usually comes just after the boundary the model chose)
# Takes where the hands never leave the frame have no hands-free still anywhere. Then the stillest half second
# in the last HANDOVER_REF_TAIL (default 25%) of the step wins, when it is clearly stiller than the usual pick.
REF_WINDOW_S = 0.5     # length of the window whose mean frame-to-frame difference is scored
REF_WINDOW_GAIN = 0.8  # the window must move at most this fraction of the usual pick's own window to replace it
REF_BRIGHT = 0.88      # pixels at or above this fraction of the step's bright end count as uncovered material


def ref_tail() -> float:
    """HANDOVER_REF_TAIL: fraction of the step, counted back from its end, searched for the stillest window."""
    return float(config.get("HANDOVER_REF_TAIL"))


def _floor_tenth(t: float) -> float:
    return int(t * 10 + 1e-6) / 10


def _gray_frames(video: Path, t0: float, t1: float, fps: float) -> list:
    """Gray thumbnails from t0 to t1 at a fixed rate, as (absolute time, PIL image). One ffmpeg call."""
    from PIL import Image

    if t1 - t0 <= 0:
        return []
    p = subprocess.run([_bin("ffmpeg"), "-v", "error", "-ss", f"{t0:.3f}", "-i", str(video), "-t", f"{t1 - t0:.3f}",
                        "-vf", f"fps={fps:.4f},scale={THUMB}:{THUMB},format=gray", "-f", "rawvideo", "-pix_fmt", "gray",
                        "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise RuntimeError(f"could not sample frames of {video}: {' '.join(tail)}")
    size = THUMB * THUMB
    return [(t0 + i / fps, Image.frombytes("L", (THUMB, THUMB), p.stdout[i * size:(i + 1) * size]))
            for i in range(len(p.stdout) // size)]


def _motion(frames: list, i: int) -> float:
    """Mean gray difference between frame i and its neighbors: 0 is perfectly still."""
    from PIL import ImageChops, ImageStat

    diffs = [ImageStat.Stat(ImageChops.difference(frames[i][1], frames[j][1])).mean[0]
             for j in (i - 1, i + 1) if 0 <= j < len(frames)]
    return sum(diffs) / len(diffs) if diffs else 0.0


def _brightness(img) -> float:
    from PIL import ImageStat

    return ImageStat.Stat(img).mean[0]


def pick_ref_time(video: Path, a: float, b: float, hint: float | None = None, *,
                  extend: float = REF_EXTEND, duration: float | None = None) -> float | None:
    """The stillest, not black moment in the last 15% of [a, b], on the 0.1 s grid lesson.json uses.

    About 8 candidates are spread over that window and each is scored by how much it differs from the frames
    next to it. When the model's hint lies in the step and is nearly as still as the best candidate, the hint
    wins, because the model also checked that hands are clear. Returns None when no frame could be sampled.

    When that choice is not hands-free still (see REF_STILL), the window is scanned at 10 fps for a still frame;
    when it has none, up to extend seconds past b (never past the video end, duration) are searched too, and
    the first still pause there is returned: a time >= b, which the caller stores as a null ref_time. When
    nothing is still anywhere (hands in the frame the whole time), the stillest half-second window in the last
    HANDOVER_REF_TAIL of the step (default 25%) replaces that frame when it is clearly stiller (see
    _stillest_window)."""
    t = _pick_in_window(video, a, b, hint)
    if t is None or extend <= 0:
        return t
    try:
        better, found_still = _still_pick(video, a, b, t, extend, duration)
    except RuntimeError:
        better, found_still = None, True
    if better is not None:
        return better
    if found_still:
        return t
    try:
        window = _stillest_window(video, a, b, t)
    except RuntimeError:
        window = None
    return t if window is None else window


def _window_scores(frames: list, k: int) -> list[tuple[float, float, int]]:
    """(center time, mean frame-to-frame difference, center index) for every run of k+1 consecutive frames."""
    from PIL import ImageChops, ImageStat

    diffs = [ImageStat.Stat(ImageChops.difference(frames[i][1], frames[i + 1][1])).mean[0]
             for i in range(len(frames) - 1)]
    return [(frames[s + k // 2][0], sum(diffs[s:s + k]) / k, s + k // 2) for s in range(len(diffs) - k + 1)]


def _percentile_gray(img, q: float) -> int:
    hist, total, acc = img.histogram(), img.width * img.height, 0
    for level, count in enumerate(hist):
        acc += count
        if acc >= q * total:
            return level
    return 255


def _stillest_window(video: Path, a: float, b: float, chosen: float, tail: float | None = None) -> float | None:
    """The center of the stillest REF_WINDOW_S window in the last `tail` of [a, b] (HANDOVER_REF_TAIL), on the
    0.1 s grid, or None to keep `chosen`. Motion is the mean absolute difference between consecutive 96x96 gray
    frames at 10 fps. The window must move at most REF_WINDOW_GAIN of the window around `chosen`, so steady
    motion or a pick that is already the stillest keeps `chosen`; so does a `chosen` outside the searched tail
    (a model hint). Among windows within 20% (or 0.3) of the stillest, the one with the most bright pixels wins:
    a cheap stand-in for "the light material is not covered by hands". Black frames never win."""
    tail = ref_tail() if tail is None else tail
    end = b - REF_END_GAP
    t0 = max(a, b - max((b - a) * tail, REF_MIN_WINDOW))
    if end - t0 < 0.3:
        return None
    frames = _gray_frames(video, t0, end, REF_STILL_FPS)
    k = max(2, round(REF_WINDOW_S * REF_STILL_FPS))
    if len(frames) < k + 1:
        return None
    scores = [w for w in _window_scores(frames, k) if _brightness(frames[w[2]][1]) >= DARK]
    if not scores:
        return None
    around = min(scores, key=lambda w: abs(w[0] - chosen))
    if abs(around[0] - chosen) > 0.5:
        return None
    least = min(w[1] for w in scores)
    if least > around[1] * REF_WINDOW_GAIN:
        return None
    near = [w for w in scores if w[1] <= max(least * 1.2, least + 0.3)]
    level = REF_BRIGHT * max(_percentile_gray(img, 0.99) for _, img in frames)

    def bright(w) -> int:
        return sum(frames[w[2]][1].histogram()[min(255, int(level)):])

    best = max(near, key=lambda w: (bright(w), w[0]))
    return max(quantize(a), min(_floor_tenth(best[0]), _floor_tenth(end - 0.1)))


def _still_pick(video: Path, a: float, b: float, chosen: float, extend: float,
                duration: float | None) -> tuple[float | None, bool]:
    """A hands-free still time when the chosen one is not still: in the window first, then after b. Returns
    (a better time, or None to keep the chosen one; whether a hands-free still frame was found at all,
    counting the chosen one)."""
    end = b - REF_END_GAP
    t0 = max(a, b - max((b - a) * REF_TAIL, REF_MIN_WINDOW))
    limit = probe_duration(video) if duration is None else duration
    t1 = max(end, min(b + extend, limit - 0.05))
    frames = _gray_frames(video, max(a, min(t0, chosen - 0.15)), t1, REF_STILL_FPS)  # the hint may be earlier
    if len(frames) < 2:
        return None, True
    scored = [(t, _motion(frames, i), _brightness(img)) for i, (t, img) in enumerate(frames)]

    def still(c) -> bool:
        return c[1] <= REF_STILL and c[2] >= DARK

    near = min(scored, key=lambda c: abs(c[0] - chosen))
    if abs(near[0] - chosen) <= 0.1 + 1e-6 and still(near):
        return None, True  # the usual pick is already hands free
    inside = [c for c in scored if t0 - 1e-6 <= c[0] < end and still(c)]
    if inside:
        best = min(inside, key=lambda c: (round(c[1], 1), -c[0]))
        return max(quantize(a), min(_floor_tenth(best[0]), _floor_tenth(end - 0.1))), True
    run: list = []  # the first run of still frames after the window: the pause after the step
    for c in scored:
        if c[0] < end:
            continue
        if still(c):
            run.append(c)
        elif run:
            break
    if not run:
        return None, False
    best = min(run, key=lambda c: (round(c[1], 1), c[0]))
    return max(quantize(b), _floor_tenth(best[0])), True


def _pick_in_window(video: Path, a: float, b: float, hint: float | None = None) -> float | None:
    """The original rule: the stillest candidate in the last 15% of [a, b], or the model's hint when it is
    nearly as still."""
    end = b - REF_END_GAP
    t0 = max(a, b - max((b - a) * REF_TAIL, REF_MIN_WINDOW))
    if end - t0 < 0.05:
        return None
    fps = min(30.0, max(10.0, 10.0 / (end - t0)))
    frames = _gray_frames(video, t0, end, fps)
    if not frames:
        return None
    count = min(REF_CANDIDATES, len(frames))
    picks = sorted({round(k * (len(frames) - 1) / max(1, count - 1)) for k in range(count)})
    cands = [(frames[i][0], _motion(frames, i), _brightness(frames[i][1])) for i in picks]

    hinted = None
    if hint is not None and a <= hint < end:
        near = frames if t0 <= hint else _gray_frames(video, max(a, hint - 0.1), min(end, hint + 0.15), 10.0)
        if near:
            i = min(range(len(near)), key=lambda j: abs(near[j][0] - hint))
            hinted = (near[i][0], _motion(near, i), _brightness(near[i][1]))

    lit = [c for c in cands if c[2] >= DARK] or cands
    best = min(lit, key=lambda c: (round(c[1], 1), -c[0]))  # ties go to the later frame: the finished state
    chosen = best
    if hinted and hinted[2] >= DARK and hinted[1] <= max(best[1] * 1.5, best[1] + 1.5):
        chosen = hinted
    t = _floor_tenth(chosen[0])
    if t >= end:
        t = _floor_tenth(end - 0.1)
    return max(t, quantize(a))


def _grab_frame(video: Path, t: float, out: Path) -> None:
    """Full size JPEG of the frame at t seconds. Written next to out first, so a failure leaves out alone."""
    part = out.with_name(out.stem + ".part" + out.suffix)
    part.unlink(missing_ok=True)
    p = subprocess.run([_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                        "-q:v", "2", str(part)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not part.exists() or part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"could not grab the frame at {fmt_mmss(t)} of {video}")
    part.replace(out)


def _ref_frame(norm: Path, clip: Path, out: Path, a: float, b: float, ref_time: str, explicit: bool,
               duration: float | None = None) -> str | None:
    """Writes the reference frame for one step and returns its ref_time, or None for the clip's last frame.

    explicit (recut): a ref_time inside the step is used as is. Otherwise, and when it is empty or outside the
    step (the step was moved), the stillest frame in the last 15% is chosen, preferring the model's hint (see
    pick_ref_time). A still pause found just after the step end is also returned as None: ref_time must lie
    inside the step (CONTRACT.md), and the same pause is found again on every recut."""
    return _ref_frame_info(norm, clip, out, a, b, ref_time, explicit, duration)[0]


def _ref_frame_info(norm: Path, clip: Path, out: Path, a: float, b: float, ref_time: str, explicit: bool,
                    duration: float | None = None) -> tuple[str | None, str]:
    """_ref_frame plus a short note on where the frame came from, for the progress line."""
    _last_frame(clip, out)  # the contract default, kept if nothing better can be grabbed
    t = None
    try:
        given = parse_time(ref_time) if str(ref_time or "").strip() else None
    except ValueError:
        given = None
    if explicit and given is not None and a - 0.05 <= given <= b + 0.05:
        t = max(quantize(a), min(_floor_tenth(given), _floor_tenth(b - 0.1)))
    else:
        try:
            t = pick_ref_time(norm, a, b, given, duration=duration)
        except RuntimeError:
            t = None
    if t is None:
        return None, "last frame"
    try:
        _grab_frame(norm, t, out)
    except RuntimeError:
        return None, "last frame"
    if t >= b:
        return None, f"pause at {fmt_mmss(t)} after the step end"
    return fmt_mmss(t), fmt_mmss(t)


def _spans(extraction: Extraction, duration: float) -> list[tuple[float, float]]:
    """Validated (start, end) seconds per step, on the 0.1 s grid. Raises ValueError naming the step."""
    if not extraction.steps:
        raise ValueError("lesson has no steps")
    spans: list[tuple[float, float]] = []
    for n, st in enumerate(extraction.steps, start=1):
        try:
            a = quantize(min(max(0.0, parse_time(st.start)), duration))
            b = quantize(min(max(0.0, parse_time(st.end)), duration))
        except ValueError as e:
            raise ValueError(f"step {n}: {e}") from None
        if b - a < 0.2:
            raise ValueError(f"step {n} has no length after clamping ({st.start} to {st.end}, video {duration:.1f} s)")
        spans.append((a, b))
    return spans


def cut(lesson_dir: Path, extraction: Extraction, lesson_id: str | None = None, title: str | None = None,
        *, keep: dict | None = None, progress: Progress = noop, exact_refs: bool = False) -> dict:
    """Cuts clips, captions and reference frames per step and writes lesson.json and extraction.json.

    Every timestamp is checked before anything is cut, and the new files are built in .recut_tmp/ and swapped
    in only when every step succeeded, so a bad timestamp or an ffmpeg failure leaves the old lesson intact.

    keep: the current lesson.json (recut). Then only n, start, end, clip, captions, ref_frame, check_question,
    prerequisites and ref_time are written into each step; every other field of the lesson and its steps stays,
    and step ref_time values are used as given (CONTRACT.md section 3, Recut rule)."""
    lesson_dir = Path(lesson_dir)
    norm = lesson_dir / "norm.mp4"
    duration = probe_duration(norm)
    old = keep
    if old is None and (lesson_dir / "lesson.json").exists():
        old = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    old = old or {}
    lesson_id = lesson_id or old.get("id") or lesson_dir.name
    title = title or old.get("title") or lesson_id

    spans = _spans(extraction, duration)

    tmp = lesson_dir / ".recut_tmp"
    _clear_tmp(tmp)  # a stale one from a failed earlier swap must not leak old files into this cut
    for sub in SUBDIRS:
        (tmp / sub).mkdir(parents=True, exist_ok=True)

    try:
        steps_out = _cut_steps(norm, tmp, extraction, spans, keep, progress, duration, exact_refs)
    except BaseException:
        _rmtree(tmp)
        raise
    _swap_in(lesson_dir, tmp, progress)

    if keep is not None:
        lesson = dict(keep)
        lesson.update({"id": lesson_id, "title": title, "steps": steps_out})
        lesson.setdefault("video", "norm.mp4")
    else:
        lesson = {"id": lesson_id, "title": title, "video": "norm.mp4",
                  "safety": list(extraction.safety), "tools": list(extraction.tools), "steps": steps_out}
    _write_json(lesson_dir / "extraction.json", json.loads(extraction.model_dump_json()))
    _write_json(lesson_dir / "lesson.json", lesson)
    return lesson


SUBDIRS = ("clips", "captions", "frames")


def _rmtree(path: Path) -> bool:
    """Deletes a folder, retrying while Windows reports it in use. True when it is gone."""
    for k in range(SWAP_TRIES):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        if k < SWAP_TRIES - 1:
            time.sleep(SWAP_WAIT_S)
    log.warning("could not remove %s (in use?)", path)
    return False


def _clear_tmp(tmp: Path) -> None:
    """Removes a stale .recut_tmp. When a file in it stays locked, empties what it can so the cut starts clean."""
    if not tmp.exists() or _rmtree(tmp):
        return
    for f in sorted(tmp.rglob("*"), reverse=True):
        try:
            f.unlink() if f.is_file() else None
        except OSError:
            pass
    leftover = [f for f in tmp.rglob("*") if f.is_file()]
    if leftover:
        raise RuntimeError(f"{tmp} is left over from an earlier cut and {len(leftover)} file(s) in it are in use; "
                           f"close whatever holds them and try again")


def _copy_over(src: Path, dst: Path) -> None:
    """Fallback when a folder cannot be renamed: copies src's files over dst's, file by file, and removes the
    files of dst that src does not have (for example frames/09.jpg after a recut down to 8 steps)."""
    dst.mkdir(parents=True, exist_ok=True)
    names = set()
    for f in sorted(src.iterdir()):
        if f.is_file():
            names.add(f.name)
            _retry(lambda f=f: shutil.copyfile(f, dst / f.name))
    for f in sorted(dst.iterdir()):
        if f.is_file() and f.name not in names:
            try:
                _retry(f.unlink)
            except OSError as e:
                log.warning("stale %s could not be removed: %s", f, e)


def _swap_in(lesson_dir: Path, tmp: Path, progress: Progress = noop) -> None:
    """Moves the old folders aside, the new ones in, then deletes the old ones. Works on Windows too, where a
    folder cannot be renamed over an existing one: each rename is retried on PermissionError (WinError 32, the
    folder is open in the hub or a shell), and when it still fails the new files are copied over the old ones
    file by file instead. .recut_tmp and .recut_old are removed at the end."""
    old = lesson_dir / ".recut_old"
    if not _rmtree(old):  # a locked leftover: park this swap's old folders next to it instead
        old = lesson_dir / f".recut_old-{int(time.time() * 1000)}"
    old.mkdir(exist_ok=True)
    copied = []
    for sub in SUBDIRS:
        cur, new = lesson_dir / sub, tmp / sub
        if cur.exists():
            try:
                _retry(lambda: cur.replace(old / sub))
            except PermissionError:
                _copy_over(new, cur)
                copied.append(sub)
                continue
        try:
            _retry(lambda: new.replace(cur))
        except PermissionError:
            _copy_over(new, cur)
            copied.append(sub)
    if copied:
        progress("cutting", f"{', '.join(copied)} in use; copied the new files over the old ones")
        log.warning("recut swap: %s could not be renamed (in use); copied file by file", ", ".join(copied))
    _rmtree(old)
    _rmtree(tmp)


def _is_manual(question: str) -> bool:
    q = question.strip()
    return not q or q.lower().strip(" .") == "manual"


def _cut_steps(norm: Path, out_dir: Path, extraction: Extraction, spans: list[tuple[float, float]],
               keep: dict | None = None, progress: Progress = noop, duration: float | None = None,
               exact_refs: bool = False) -> list[dict]:
    old_steps = (keep or {}).get("steps") or []
    steps_out = []
    total = len(spans)
    for n, (st, (a, b)) in enumerate(zip(extraction.steps, spans), start=1):
        nn = f"{n:02d}"
        clip = out_dir / "clips" / f"{nn}.mp4"
        _run([_bin("ffmpeg"), "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(norm),
              "-vf", CLIP_VF, "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", *SEEK_TAGS, *SDR_TAGS,
              "-c:a", "aac",
              "-movflags", "+faststart", str(clip)])
        length = probe_duration(clip)
        _write_vtt(out_dir / "captions" / f"{nn}.vtt", extraction.transcript, a, length)
        ref_time, ref_note = _ref_frame_info(norm, clip, out_dir / "frames" / f"{nn}.jpg", a, b, st.ref_time,
                                             keep is not None or exact_refs, duration)
        manual = _is_manual(st.check_question)
        progress("cutting", f"step {n} of {total}  {fmt_mmss(a)} to {fmt_mmss(b)}  "
                            f"reference {ref_note}  [{'manual' if manual else 'camera'}]")
        rewritten = {
            "n": n,
            "start": fmt_mmss(a),
            "end": fmt_mmss(b),
            "clip": f"clips/{nn}.mp4",
            "captions": f"captions/{nn}.vtt",
            "ref_frame": f"frames/{nn}.jpg",
            "check_question": "" if manual else st.check_question.strip(),
            "prerequisites": [p for p in st.prerequisites if 1 <= p < n],
            "ref_time": ref_time,
        }
        if keep is not None:
            base = old_steps[n - 1] if n - 1 < len(old_steps) and isinstance(old_steps[n - 1], dict) else {}
            step = dict(base)
            step.update(rewritten)
            step.setdefault("title", st.title.strip())
            if manual or "check_type" not in step:
                step["check_type"] = "manual" if manual else "camera"
        else:
            step = {"n": n, "title": st.title.strip(), **rewritten,
                    "check_type": "manual" if manual else "camera",
                    "common_mistake": st.common_mistake.strip()}
            step = {k: step[k] for k in ("n", "title", "start", "end", "clip", "captions", "ref_frame", "ref_time",
                                         "check_type", "check_question", "prerequisites", "common_mistake")}
        steps_out.append(step)
    return steps_out


# ---------------------------------------------------------------- 4. recut

DEFAULT_QUESTION = "Is this step finished?"  # CONTRACT.md section 3: a camera step with no question


def _lesson_extraction(lesson_dir: Path, lesson: dict) -> Extraction:
    """lesson.json steps (possibly hand edited) plus the saved transcript, as an Extraction for cut."""
    transcript: list[Segment] = []
    ex_path = lesson_dir / "extraction.json"
    if ex_path.exists():
        transcript = Extraction.model_validate_json(ex_path.read_text(encoding="utf-8")).transcript
    try:
        steps = [
            Step(start=str(s["start"]), end=str(s["end"]), title=str(s.get("title") or f"Step {i}"),
                 check_question="manual" if s.get("check_type") == "manual"
                 else (str(s.get("check_question") or "").strip() or DEFAULT_QUESTION),
                 prerequisites=list(s.get("prerequisites") or []),
                 ref_time=str(s.get("ref_time") or ""), common_mistake=str(s.get("common_mistake") or ""))
            for i, s in enumerate(lesson["steps"], start=1)
        ]
    except (KeyError, TypeError, AttributeError, ValidationError) as e:  # hand-edited lesson.json with a bad step
        raise ValueError(f"bad step in lesson.json: {type(e).__name__}: {e}") from None
    return Extraction(steps=steps, transcript=transcript,
                      safety=_clean_list(lesson.get("safety")), tools=_clean_list(lesson.get("tools")))


def recut(lesson_dir: Path, progress: Progress = noop, *, auto: bool = True, retitle: bool = False,
          strict: bool = False, repick: bool = False, boundaries: str = "legacy") -> dict:
    """Rebuilds clips, captions and frames from lesson.json (possibly hand-edited) and the saved transcript.

    Follows the Recut rule: every field recut does not own is kept, step 1 is never forced to manual, and a
    step's ref_time is used when it lies inside the step (otherwise a new one is chosen and written).
    auto: then the camera questions are rewritten from the new reference frames (teach provider) and the
    automatic self-test runs (see questions_from_refs and _auto_self_test); retitle and strict as in _after_cut.
    repick: every ref_time is cleared first, so each reference frame is chosen again (after moving steps).
    A voiceover field is dropped: the new clips carry the take's own audio (run server.voice again)."""
    lesson_dir = Path(lesson_dir)
    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    if not isinstance(lesson, dict):
        raise ValueError("bad lesson.json: not an object")
    if repick:
        for st in lesson.get("steps") or []:
            if isinstance(st, dict):
                st["ref_time"] = None
        if boundaries == "vision":  # the human's start and end win; the reference is the done frame at each cut
            ref_times_at_cuts(lesson_dir, lesson)
    if lesson.pop("voiceover", None) is not None:
        progress("cutting", "the voiceover is dropped by the recut; run python -m server.voice again")
    extraction = _lesson_extraction(lesson_dir, lesson)
    out = cut(lesson_dir, extraction, lesson.get("id"), lesson.get("title"), keep=lesson, progress=progress)
    if auto:
        out = _after_cut(lesson_dir, out, teach_provider(), progress, retitle=retitle, strict=strict)
    return out


# ---------------------------------------------------------------- 5. self-test (S-T)

def _selftest_timeout() -> float:
    """HANDOVER_SELFTEST_TIMEOUT through server/config.py: default 10 s, 0.1 to 120."""
    return float(config.get("HANDOVER_SELFTEST_TIMEOUT"))


def _check_is_mock() -> bool:
    return config.get("HANDOVER_CHECK") == "mock"


async def _self_test(lesson_dir: Path, progress: Progress = noop) -> tuple[dict, list[int]]:
    """The self-test itself. Returns the updated lesson and the steps skipped because a check call failed."""
    import asyncio

    from server import check

    lesson_dir = Path(lesson_dir)
    lesson = json.loads(await asyncio.to_thread((lesson_dir / "lesson.json").read_text, encoding="utf-8"))
    steps = lesson.get("steps") or []
    mock = _check_is_mock()

    def read(rel) -> bytes | None:
        p = lesson_dir / str(rel or "")
        return p.read_bytes() if rel and p.is_file() and p.stat().st_size > 0 else None

    def start_frame(s: dict) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "start.jpg"
            try:
                _grab_frame(lesson_dir / (lesson.get("video") or "norm.mp4"), parse_time(s["start"]), out)
            except (RuntimeError, ValueError, KeyError):
                return None
            return out.read_bytes()

    refs = await asyncio.to_thread(
        lambda: [read(s.get("ref_frame") or f"frames/{i + 1:02d}.jpg") for i, s in enumerate(steps)])

    timeout = _selftest_timeout()

    errored: list[int] = []
    for i, s in enumerate(steps):
        if s.get("check_type") == "manual":
            continue
        n = s.get("n", i + 1)
        if not refs[i]:
            progress("self-test", f"step {n}: skipped, reference frame missing")
            continue
        q = (s.get("check_question") or "").strip() or DEFAULT_QUESTION
        before = refs[i - 1] if i > 0 and refs[i - 1] else await asyncio.to_thread(start_frame, s)
        if before is None:
            progress("self-test", f"step {n}: skipped, no earlier frame to compare with")
            continue
        # step_started_at only matters in mock mode: long ago gives yes, just now gives no.
        own = await check.check_frame(refs[i], refs[i], q, step_started_at=time.monotonic() - 1e6,
                                      timeout=timeout)
        prev = await check.check_frame(refs[i], before, q, step_started_at=time.monotonic(),
                                       timeout=timeout)
        failed = getattr(own, "error", None) or getattr(prev, "error", None)
        if failed:
            # a timeout or API error says nothing about the question; never store it as a disagreement
            s.pop("self_test", None)
            errored.append(n)
            progress("self-test", f"step {n}: skipped, check failed ({failed})")
            continue
        result = {"own": own.done, "prev": prev.done, "ok": own.done == "yes" and prev.done == "no"}
        if mock:
            result["mock"] = True
        s["self_test"] = result
        verdict = "ok" if result["ok"] else "FAILED, suggest manual or a clearer question"
        progress("self-test", f"step {n}: own {own.done} {own.confidence:.2f}, "
                              f"prev {prev.done} {prev.confidence:.2f}  {verdict}")

    await asyncio.to_thread(_write_json, lesson_dir / "lesson.json", lesson)
    return lesson, errored


async def self_test_lesson_async(lesson_dir: Path, progress: Progress = noop) -> dict:
    """Asks the live check two questions per camera step and writes the answers into lesson.json:
    own:  this step's reference against its own question, which should be yes;
    prev: the previous step's reference against this question, which should be no (for the first step, or when
          the previous reference is missing, the frame at this step's start is used instead).
    ok is own == yes and prev == no. A step that is not ok is a candidate for manual. Manual steps are skipped.
    A step whose check call failed (timeout, quota, no key) is skipped and its old self_test removed.

    Uses check.check_frame, so HANDOVER_CHECK=mock runs without network; mock answers depend only on the time
    passed in, never on the images, and such results carry "mock": true. Each call may take up to
    HANDOVER_SELFTEST_TIMEOUT seconds (default 10). For the hub: await it on its own loop; file and ffmpeg
    work runs in threads. Returns the updated lesson."""
    lesson, _ = await _self_test(lesson_dir, progress)
    return lesson


def self_test_lesson(lesson_dir: Path, progress: Progress = noop) -> dict:
    """Synchronous wrapper of self_test_lesson_async for the CLI and scripts (not from a running loop)."""
    import asyncio

    return asyncio.run(self_test_lesson_async(lesson_dir, progress))


def _run_async(make_coro):
    """asyncio.run(make_coro()), in a worker thread when this thread already runs a loop."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coro())
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(lambda: asyncio.run(make_coro())).result()


def auto_selftest_on() -> bool:
    """HANDOVER_AUTO_SELFTEST (default on): self-test every cut and recut, failing steps become manual."""
    return bool(config.env_bool("HANDOVER_AUTO_SELFTEST", True))


def _auto_self_test(lesson_dir: Path, lesson: dict, progress: Progress = noop, *, strict: bool = False) -> dict:
    """After a cut or recut: runs the self-test (same calls and progress lines as --self-test) and makes every
    camera step whose own reference does not pass its own question manual (check_type manual, check_question
    "", the self_test result kept). Skipped when HANDOVER_AUTO_SELFTEST is off, offline (HANDOVER_NO_NETWORK),
    in mock check mode (answers ignore the images) or without a key for the check provider. Steps whose check
    call failed are left as they are. strict: a step that fails either half (its question is also yes on the
    previous step's reference, so the camera would pass it before the learner does anything) becomes manual too.
    Never raises: a failure keeps the lesson as cut."""
    if not auto_selftest_on():
        return lesson
    camera = [s.get("n", i + 1) for i, s in enumerate(lesson.get("steps") or []) if s.get("check_type") != "manual"]
    if not camera:
        return lesson
    if config.get("HANDOVER_NO_NETWORK"):
        progress("self-test", "HANDOVER_NO_NETWORK=1: automatic self-test skipped")
        return lesson
    try:
        from server import check

        if check.is_mock():
            progress("self-test", "HANDOVER_CHECK=mock: automatic self-test skipped (mock answers ignore images)")
            return lesson
        if not check._key_for(check.provider()):
            progress("self-test", f"no {check.provider()} key: automatic self-test skipped")
            return lesson
        progress("self-test", f"{len(camera)} camera steps in {lesson_dir}, check: {check.active_model()}")
        t0 = time.time()
        tested, errored = _run_async(lambda: _self_test(Path(lesson_dir), progress))
    except Exception as e:
        reason = scrub(f"{type(e).__name__}: {e}".splitlines()[0][:160])
        progress("self-test", f"automatic self-test failed ({reason}); keeping the questions as they are")
        log.warning("automatic self-test failed: %s", reason)
        return lesson
    made_manual = []
    for i, s in enumerate(tested.get("steps") or []):
        st = s.get("self_test")
        if s.get("check_type") != "manual" and isinstance(st, dict) and (st.get("own") != "yes"
                                                                          or (strict and not st.get("ok"))):
            s["check_type"] = "manual"
            s["check_question"] = ""
            made_manual.append(s.get("n", i + 1))
    failed = [s.get("n", i + 1) for i, s in enumerate(tested.get("steps") or [])
              if isinstance(s.get("self_test"), dict) and not s["self_test"].get("ok")]
    _write_json(Path(lesson_dir) / "lesson.json", tested)
    progress("self-test", f"self-test wrote lesson.json ({time.time() - t0:.1f} s)")
    if errored:
        progress("self-test", f"the check failed on steps {', '.join(map(str, errored))}, so they were not tested")
    if failed:
        progress("self-test", f"Steps that failed: {', '.join(map(str, failed))}")
    if made_manual:
        progress("self-test", f"Steps made manual ({'they failed the self-test' if strict else 'their own reference failed the question'}): "
                              f"{', '.join(map(str, made_manual))}")
    return tested


# ---------------------------------------------------------------- 5b. check questions from the reference frames

REF_QUESTION_PROMPT = """Each numbered step above has two photos of the same object during a hands-on task:
BEFORE, the state when the step starts, and DONE, the state when the step is finished, plus the step's title.
For each step write one yes/no check_question that a camera will ask about a photo of a learner's object.
It must be clearly true of the DONE photo and clearly false of the BEFORE photo.
Describe only the fold or assembly state you can see in DONE: the outline shape, the number of corners, which folds,
creases or seams exist, how many layers or flaps there are and where they meet, which side faces up. Never mention
size, color, position, rotation, lighting, hands, tools, the table or the background: the learner's material,
camera angle and light differ. Ignore hands that cover part of the object. When the title and the photos
disagree, trust the photos. One short sentence ending in "?". Return every step by its number."""
REF_IMAGE_SIDE = 768   # long side of the images sent; enough to see folds, a fraction of the full frame's tokens
REF_QUESTION_TOKENS = 4096


def _small_jpeg(data: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((REF_IMAGE_SIDE, REF_IMAGE_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return buf.getvalue()


def _ref_question_items(lesson_dir: Path, lesson: dict) -> list[dict]:
    """For each camera step with both images: {"n", "title", "before", "done"} (JPEG bytes, shrunk). BEFORE is
    the previous step's reference, or the video's frame at step 1's start for step 1. At most CLAUDE_MAX_FRAMES
    images in all (two per step)."""
    steps = lesson.get("steps") or []

    def read(rel) -> bytes | None:
        p = lesson_dir / str(rel or "")
        return p.read_bytes() if rel and p.is_file() and p.stat().st_size > 0 else None

    def ref(i: int) -> bytes | None:
        return read(steps[i].get("ref_frame") or f"frames/{i + 1:02d}.jpg")

    items = []
    for i, s in enumerate(steps):
        if s.get("check_type") == "manual" or len(items) >= CLAUDE_MAX_FRAMES // 2:
            continue
        done = ref(i)
        if i > 0:
            before = ref(i - 1)
        else:
            before = None
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "first.jpg"
                try:
                    _grab_frame(lesson_dir / (lesson.get("video") or "norm.mp4"), parse_time(s.get("start") or 0), out)
                    before = out.read_bytes()
                except (RuntimeError, ValueError):
                    before = None
        if done and before:
            items.append({"n": int(s.get("n", i + 1)), "title": str(s.get("title") or "").strip(),
                          "before": _small_jpeg(before), "done": _small_jpeg(done)})
    return items


def _ref_questions_claude(items: list[dict]) -> dict[int, str]:
    import base64

    import anthropic

    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key")
    spend = _spend()
    if not spend.allow():
        raise RuntimeError("the Claude spending limit is reached")

    def image(data: bytes) -> dict:
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.standard_b64encode(data).decode()}}

    content: list[dict] = []
    for it in items:
        content += [{"type": "text", "text": f"Step {it['n']}: {it['title']}\nBEFORE:"}, image(it["before"]),
                    {"type": "text", "text": f"Step {it['n']} DONE:"}, image(it["done"])]
    content.append({"type": "text", "text": REF_QUESTION_PROMPT})
    model = _claude_model()
    response = anthropic.Anthropic(api_key=key).messages.create(
        model=model, max_tokens=REF_QUESTION_TOKENS,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": _rephrase_schema()}},
    )
    spend.record(model, response.usage)
    if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude stopped: {response.stop_reason}")
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    return {q.n: q.question for q in _RephraseAnswer.model_validate_json(text).questions}


def _ref_questions_gemini(items: list[dict]) -> dict[int, str]:
    from google import genai
    from google.genai import types

    parts = []
    for it in items:
        parts += [types.Part(text=f"Step {it['n']}: {it['title']}\nBEFORE:"),
                  types.Part.from_bytes(data=it["before"], mime_type="image/jpeg"),
                  types.Part(text=f"Step {it['n']} DONE:"),
                  types.Part.from_bytes(data=it["done"], mime_type="image/jpeg")]
    parts.append(types.Part(text=REF_QUESTION_PROMPT))
    client = genai.Client(api_key=_api_key(), http_options=types.HttpOptions(api_version="v1beta", timeout=120_000))
    resp = client.models.generate_content(
        model=_model(), contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_json_schema=_rephrase_schema(),
                                           max_output_tokens=REF_QUESTION_TOKENS))
    return {q.n: q.question for q in _RephraseAnswer.model_validate_json(resp.text or "").questions}


def _ref_questions_call(provider: str, items: list[dict]) -> dict[int, str]:
    """The one model call: {step n: question}. Raises on any failure."""
    return (_ref_questions_claude if provider == "claude" else _ref_questions_gemini)(items)


def _usable_question(q) -> str | None:
    q = " ".join(str(q or "").split())
    if not q or _is_manual(q) or not q.endswith("?") or len(q) > 240 or color_words(q):
        return None
    return q


def questions_from_refs(lesson_dir: Path, lesson: dict, provider: str, progress: Progress = noop) -> dict:
    """Rewrites each camera step's check_question from its chosen reference frames, in ONE call to the teach
    provider: per step its BEFORE image (the previous reference, or the first frame for step 1), its DONE image
    (its own reference) and its title. Questions written from the proxy video failed 5 of 8 self-tests against
    their own reference on a real take. An answer that is missing, empty, not a question or names a color keeps
    that step's old question; a failed call, an unknown provider or HANDOVER_NO_NETWORK=1 keeps them all.
    Writes lesson.json when anything changed and returns the lesson."""
    lesson_dir = Path(lesson_dir)
    if provider not in ("claude", "gemini"):
        return lesson
    if config.get("HANDOVER_NO_NETWORK"):
        progress("questions", "HANDOVER_NO_NETWORK=1: keeping the extracted check questions")
        return lesson
    try:
        items = _ref_question_items(lesson_dir, lesson)
    except Exception as e:
        log.warning("reference question images failed: %s", e)
        return lesson
    if not items:
        return lesson
    model = _claude_model() if provider == "claude" else _model()
    progress("questions", f"Writing check questions for {len(items)} camera steps from their reference frames "
                          f"with {model}")
    try:
        new = _ref_questions_call(provider, items)
    except Exception as e:
        reason = scrub(f"{type(e).__name__}: {e}".splitlines()[0][:160])
        progress("questions", f"Question call failed ({reason}); keeping the extracted questions")
        log.warning("reference question call failed: %s", reason)
        return lesson
    wanted = {it["n"] for it in items}
    changed = 0
    for i, s in enumerate(lesson.get("steps") or []):
        n = s.get("n", i + 1)
        if n not in wanted:
            continue
        q = _usable_question(new.get(n))
        if q is None:
            progress("questions", f"step {n}: no usable question came back; keeping the old one")
            continue
        if q != s.get("check_question"):
            s["check_question"] = q
            s.pop("self_test", None)  # it tested the old question
            changed += 1
    if changed:
        _write_json(lesson_dir / "lesson.json", lesson)
    progress("questions", f"{changed} of {len(items)} check questions rewritten from the reference frames")
    return lesson


# ---------------------------------------------------------------- 5c. titles and questions from the frames

RETITLE_PROMPT = """Each numbered step above has three photos of the same object during a hands-on task: BEFORE (the
state when the step starts), DURING (the middle of the step) and DONE (the state when the step is finished), and
its current title, which may be wrong. Rewrite every step so its title, check question and tip agree with the photos
and with each other.
- title: an instruction of 3 to 8 words for the action that turns BEFORE into DONE, for example "Fold the square in
  half into a rectangle". Name the action and the shape it leaves. Keep the current title when it already says
  that. Step 1 is the first thing a learner does with fresh material, so its title must make sense as a first
  step: start from "the sheet" (or the material's plain name), never "again", never "strip" or another result
  that needs an earlier fold. Use "again" only for an action already done in an earlier step. Name the object
  in each title as it looks in that step's BEFORE photo.
- Shapes: call an outline a square when its sides look about equal, even in a tall photo; a rectangle only when
  one side is clearly longer. When DONE has the same outline as BEFORE, the title and question must name what
  differs (an added crease, a flap, more layers), or the question is manual.
- check_question: one yes/no question a camera will ask about a photo of the learner's object. Clearly true of
  DONE and clearly false of BEFORE. Name the outline shape and at least one count: corners, creases or seams,
  flaps or layers, and say where they meet or which side faces up. It must describe the same shape the title
  names: a title that says triangle gets a question about a triangle. Never mention color, size, position,
  rotation, lighting, hands, tools, the table or the background. Ignore hands that cover part of the object.
  One short sentence ending in "?". When DONE looks the same as BEFORE (a fold that is unfolded again, a crease
  only, a step whose change a camera cannot see), write exactly: manual
- common_mistake: the most likely beginner mistake on this step, as a short instruction that prevents it, at
  most 8 words, for example "Line up the corners before creasing.". No color words.
Trust the photos over the current title. Return every step by its number."""


RETITLE_TOKENS = 8000  # three fields per step; Haiku once ran past 4096 on 8 steps


class _Retitled(BaseModel):
    n: int
    title: str
    check_question: str
    common_mistake: str


class _RetitleAnswer(BaseModel):
    steps: list[_Retitled]


def _retitle_schema() -> dict:
    schema = _RetitleAnswer.model_json_schema()
    for node in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in node:
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
    return schema


def _retitle_items(lesson_dir: Path, lesson: dict) -> list[dict]:
    """For every step: {"n", "title", "before", "during", "done"} (small JPEG bytes). BEFORE is the previous
    step's reference (the video's frame at step 1's start for step 1), DURING the frame at the middle of the
    step, DONE its own reference. Steps missing an image are left out."""
    steps = lesson.get("steps") or []
    video = lesson_dir / (lesson.get("video") or "norm.mp4")

    def ref(i: int) -> bytes | None:
        p = lesson_dir / str(steps[i].get("ref_frame") or f"frames/{i + 1:02d}.jpg")
        return p.read_bytes() if p.is_file() and p.stat().st_size > 0 else None

    def at(t: float) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "f.jpg"
            try:
                _grab_frame(video, t, out)
                return out.read_bytes()
            except (RuntimeError, ValueError):
                return None

    items = []
    for i, s in enumerate(steps[:CLAUDE_MAX_FRAMES // 3]):
        try:
            a, b = parse_time(s.get("start") or 0), parse_time(s.get("end") or 0)
        except ValueError:
            continue
        before = ref(i - 1) if i > 0 else at(a)
        during, done = at((a + b) / 2), ref(i)
        if before and during and done:
            items.append({"n": int(s.get("n", i + 1)), "title": str(s.get("title") or "").strip(),
                          "before": _small_jpeg(before), "during": _small_jpeg(during), "done": _small_jpeg(done)})
    return items


def _retitle_claude(items: list[dict]) -> dict[int, _Retitled]:
    import base64

    import anthropic

    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key")
    spend = _spend()
    if not spend.allow():
        raise RuntimeError("the Claude spending limit is reached")

    def image(data: bytes) -> dict:
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.standard_b64encode(data).decode()}}

    content: list[dict] = []
    for it in items:
        content += [{"type": "text", "text": f"Step {it['n']}, current title: {it['title']}\nBEFORE:"},
                    image(it["before"]), {"type": "text", "text": f"Step {it['n']} DURING:"}, image(it["during"]),
                    {"type": "text", "text": f"Step {it['n']} DONE:"}, image(it["done"])]
    content.append({"type": "text", "text": RETITLE_PROMPT})
    model = _claude_model()
    response = anthropic.Anthropic(api_key=key).messages.create(
        model=model, max_tokens=RETITLE_TOKENS,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": _retitle_schema()}},
    )
    spend.record(model, response.usage)
    if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude stopped: {response.stop_reason}")
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    return {r.n: r for r in _RetitleAnswer.model_validate_json(text).steps}


def _retitle_gemini(items: list[dict]) -> dict[int, _Retitled]:
    from google import genai
    from google.genai import types

    parts = []
    for it in items:
        parts += [types.Part(text=f"Step {it['n']}, current title: {it['title']}\nBEFORE:"),
                  types.Part.from_bytes(data=it["before"], mime_type="image/jpeg"),
                  types.Part(text=f"Step {it['n']} DURING:"),
                  types.Part.from_bytes(data=it["during"], mime_type="image/jpeg"),
                  types.Part(text=f"Step {it['n']} DONE:"),
                  types.Part.from_bytes(data=it["done"], mime_type="image/jpeg")]
    parts.append(types.Part(text=RETITLE_PROMPT))
    client = genai.Client(api_key=_api_key(), http_options=types.HttpOptions(api_version="v1beta", timeout=120_000))
    resp = client.models.generate_content(
        model=_model(), contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           response_json_schema=_retitle_schema(),
                                           max_output_tokens=REF_QUESTION_TOKENS))
    return {r.n: r for r in _RetitleAnswer.model_validate_json(resp.text or "").steps}


def _usable_title(t) -> str | None:
    t = " ".join(str(t or "").split()).rstrip(".")
    if not t or len(t) > 80 or color_words(t):
        return None
    return t[:1].upper() + t[1:]


def titles_from_refs(lesson_dir: Path, lesson: dict, provider: str, progress: Progress = noop) -> dict:
    """Rewrites every step's title, check question and common mistake from its frames, in ONE call to the teach
    provider (BEFORE, DURING and DONE images per step, see _retitle_items), so the title and the question name the
    same shape. A question of "manual" makes the step manual; a usable question makes it a camera step again
    (the self-test that follows decides). Step 1 stays manual (the first-step rule). An answer that is missing,
    too long or names a color keeps that field. A failed call, an unknown provider or HANDOVER_NO_NETWORK=1 keeps
    everything. Writes lesson.json when anything changed and returns the lesson."""
    lesson_dir = Path(lesson_dir)
    if provider not in ("claude", "gemini"):
        return lesson
    if config.get("HANDOVER_NO_NETWORK"):
        progress("titles", "HANDOVER_NO_NETWORK=1: keeping the titles and questions")
        return lesson
    try:
        items = _retitle_items(lesson_dir, lesson)
    except Exception as e:
        log.warning("retitle images failed: %s", e)
        return lesson
    if not items:
        return lesson
    model = _claude_model() if provider == "claude" else _model()
    progress("titles", f"Writing titles and check questions for {len(items)} steps from their frames with {model}")
    try:
        new = (_retitle_claude if provider == "claude" else _retitle_gemini)(items)
    except Exception as e:
        reason = scrub(f"{type(e).__name__}: {e}".splitlines()[0][:160])
        progress("titles", f"Title call failed ({reason}); keeping the titles and questions")
        log.warning("retitle call failed: %s", reason)
        return lesson
    wanted = {it["n"] for it in items}
    changed = 0
    for i, s in enumerate(lesson.get("steps") or []):
        n = s.get("n", i + 1)
        got = new.get(n)
        if n not in wanted or got is None:
            continue
        before = (s.get("title"), s.get("check_type"), s.get("check_question"), s.get("common_mistake"))
        title = _usable_title(got.title)
        if title:
            s["title"] = title
        mistake = " ".join(str(got.common_mistake or "").split())
        if mistake and len(mistake) <= 100 and not color_words(mistake):
            s["common_mistake"] = mistake if mistake[-1] in ".!?" else mistake + "."
        q = " ".join(str(got.check_question or "").split())
        if i == 0 or _is_manual(q):
            s["check_type"], s["check_question"] = "manual", ""
        elif _usable_question(q):
            s["check_type"], s["check_question"] = "camera", q
        if (s.get("title"), s.get("check_type"), s.get("check_question"), s.get("common_mistake")) != before:
            changed += 1
            if (s.get("check_type"), s.get("check_question")) != before[1:3]:
                s.pop("self_test", None)  # it tested the old question
        progress("titles", f"step {n}: {s.get('title')}  [{s.get('check_type')}]  {s.get('check_question') or ''}")
    if changed:
        _write_json(lesson_dir / "lesson.json", lesson)
    progress("titles", f"{changed} of {len(items)} steps rewritten from their frames")
    return lesson


def _after_cut(lesson_dir: Path, lesson: dict, provider: str, progress: Progress = noop, *,
               retitle: bool = False, strict: bool = False) -> dict:
    """Questions (retitle: titles, questions and tips) from the reference frames, then the automatic self-test
    (strict: every step that fails it becomes manual, not only those whose own reference fails)."""
    if retitle:
        lesson = titles_from_refs(lesson_dir, lesson, provider, progress)
    else:
        lesson = questions_from_refs(lesson_dir, lesson, provider, progress)
    return _auto_self_test(lesson_dir, lesson, progress, strict=strict)


# ---------------------------------------------------------------- 5d. vision boundaries: cut when each step is DONE

# Frames-only takes (no speech, hands never leave the frame) have no narration and no pauses to cut on. Here the
# model itself says when each step's end state is first visible. Pass 1 sees the whole take as contact sheets (one
# frame per HANDOVER_TEACH_SAMPLE_S) and returns, per step, the first time its end state is clearly visible. Pass 2
# looks at every boundary again at 4 fps in a +-2 s window and picks the first frame where the end state is reached:
# that frame is the cut. Stillness never decides a boundary; it only breaks ties for the reference frame.

BOUNDARY_FALLBACK_MODEL = "claude-haiku-5-5"
BOUNDARY_TOKENS = 16000
SHEET_COLS, SHEET_ROWS = 8, 5      # 40 frames per sheet image in pass 1
SHEET_TILE_H = 240                 # pass 1 frame height in pixels
REFINE_HALF_S = 2.0                # pass 2 window: coarse time +- this
REFINE_STEP_S = 0.25
REFINE_COLS = 6
REFINE_TILE_H = 300
REF_WINDOW_BEFORE_CUT = 1.0        # reference frame: the done frame, or a less covered one this far before the cut
REF_SAME_SHAPE = 4.0               # a reference candidate must look this close to the done frame
QUICK_FLIP_MIN_S = 0.8             # a flagged quick flip may be this short; every other step needs HANDOVER_MIN_STEP_S


def teach_sample_s() -> float:
    """HANDOVER_TEACH_SAMPLE_S: seconds between the frames pass 1 sees (default 1.0)."""
    return float(config.get("HANDOVER_TEACH_SAMPLE_S"))


def boundary_model() -> str:
    """HANDOVER_TEACH_BOUNDARY_MODEL: the model that finds when each step is done (default claude-sonnet-5-5)."""
    return str(config.get("HANDOVER_TEACH_BOUNDARY_MODEL"))


def _label_font(size: int):
    from PIL import ImageFont

    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _frames_at_rate(video: Path, t0: float, t1: float, every: float, height: int, out_dir: Path) -> list:
    """(time, PIL RGB image) every `every` seconds from t0 to t1, scaled to `height`. One ffmpeg call."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    if t1 - t0 <= 0:
        return []
    _run([_bin("ffmpeg"), "-y", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(video), "-t", f"{t1 - t0:.3f}",
          "-vf", f"fps={1 / every:.6f},scale=-2:{height}", "-q:v", "4", str(out_dir / "f%05d.jpg")])
    out = []
    for k, f in enumerate(sorted(out_dir.glob("f*.jpg"))):
        with Image.open(f) as im:
            out.append((round(t0 + k * every, 3), im.convert("RGB")))
    return out


def _tile(frames: list, cols: int, outline: int | None = None, font_size: int = 22) -> bytes:
    """Frames in reading order with each time burned in (MM:SS.s, top left, white on black); `outline` (an index)
    gets a thick red border. Returns JPEG bytes."""
    from PIL import Image, ImageDraw

    w, h = frames[0][1].size
    gap = 4
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + gap) + gap, rows * (h + gap) + gap), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = _label_font(font_size)
    for i, (t, img) in enumerate(frames):
        r, c = divmod(i, cols)
        x, y = gap + c * (w + gap), gap + r * (h + gap)
        sheet.paste(img, (x, y))
        m, sec = divmod(max(0.0, t), 60)
        label = f"{int(m):02d}:{sec:05.2f}"
        box = draw.textbbox((0, 0), label, font=font)
        draw.rectangle((x, y, x + box[2] - box[0] + 10, y + box[3] - box[1] + 10), fill=(0, 0, 0))
        draw.text((x + 5, y + 5 - box[1]), label, font=font, fill=(255, 255, 255))
        if outline == i:
            draw.rectangle((x - 2, y - 2, x + w + 1, y + h + 1), outline=(220, 30, 30), width=6)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=82)
    return buf.getvalue()


class _DoneStep(BaseModel):
    title: str
    check_question: str
    common_mistake: str
    done_s: float
    reason: str
    quick_flip: bool


class _DoneWire(BaseModel):
    """What the model writes: the time as printed on the frame ("MM:SS.ss"), never a bare number of seconds,
    because a model reading "01:33.00" once answered 33."""
    title: str
    check_question: str
    common_mistake: str
    done_at: str
    reason: str
    quick_flip: bool


class _DoneAnswer(BaseModel):
    steps: list[_DoneWire]
    safety: list[str]
    tools: list[str]


class _Refined(BaseModel):
    boundary: int
    done_s: float
    reason: str


class _RefinedWire(BaseModel):
    boundary: int
    done_at: str
    reason: str


class _RefineAnswer(BaseModel):
    boundaries: list[_RefinedWire]


def _wire_seconds(value: str) -> float | None:
    try:
        return parse_time(str(value).strip())
    except ValueError:
        return None


def _strict_schema(model: type[BaseModel]) -> dict:
    schema = model.model_json_schema()
    for node in [schema, *schema.get("$defs", {}).values()]:
        if "properties" in node:
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
    return schema


DONE_PROMPT = """The images above are contact sheets of ONE video of an expert doing a hands-on task, with no speech.
Each sheet shows frames in reading order (left to right, then top to bottom), one every {every:g} s; the time of each
frame is printed on it as MM:SS.ss. The whole take is {duration:.1f} s long.

Split the take into the ordered steps a beginner follows and find when each step is DONE.
For each step return:
- done_at: the time printed on the FIRST frame (copy it exactly, "MM:SS.ss") where that step's END STATE is clearly visible: the fold is
  completed and lies in its new shape, even if hands are still on the paper. Not when the hands pause, slow down or
  leave; not when the next action starts. Read the times printed on the frames.
- reason: one short sentence on what is visible at done_at that was not visible before (the new shape, seam or
  flap count).
- title: an instruction of 3 to 8 words for the action of this step. Step 1 is the first thing done with the fresh
  material, so its title makes sense as a first step.
- check_question: one yes/no question about the END STATE that a camera can answer from one photo: name the outline
  shape and a count (corners, creases or seams, flaps or layers). Never color, size, position, hands or background.
  Write exactly manual when the end state looks the same as the start (a crease made and unfolded).
- common_mistake: the likely beginner mistake, as a short instruction that prevents it, at most 8 words.
- quick_flip: true only for a step that just flips or turns the object over (it may be very short), else false.
Rules: steps in order, done_at strictly increasing; the last step is done when the finished object is complete.
Prefer 5 to 12 steps of one physical action each. Also give safety warnings you can see (usually []) and the tools
and materials used.
"""

DONE_PRIOR = """
The task is known. Here is a hand-written plan of its steps. Treat it as a strong prior: expect these actions in
this order and return one entry per plan step, reusing the plan's titles, questions and tips where they match what
you see. Follow the video only where the expert clearly differs (an extra, skipped, repeated or reordered action).
Plan:
"""

REFINE_PROMPT = """Each image above shows the frames around one step boundary of the same video, 0.25 s apart in
reading order, with the time printed on each frame. For each boundary, pick the FIRST frame where that step's end state
(given in the text before the image) is reached: the fold completed and lying in its new shape, even with hands on the
paper. Return its printed time exactly as shown ("MM:SS.ss") as done_at, and one short reason. If the end state is already reached in the
first frame, return that frame's time; if it is not reached in any frame, return the last frame's time."""


def _boundary_call(content: list[dict], schema: dict, label: str, progress: Progress) -> tuple[str, str, dict]:
    """One structured Claude call with HANDOVER_TEACH_BOUNDARY_MODEL, retried once with Haiku when it fails.
    Returns (model, JSON text, usage dict). Raises RuntimeError when both fail or the budget is used up."""
    import anthropic

    key = _anthropic_key()
    if not key:
        raise RuntimeError("no Anthropic key")
    spend = _spend()
    client = anthropic.Anthropic(api_key=key, timeout=300.0, max_retries=1)
    errors = []
    for model in dict.fromkeys([boundary_model(), BOUNDARY_FALLBACK_MODEL]):
        if not spend.allow():
            raise RuntimeError("the Claude spending limit is reached; no call was made")
        t0 = time.time()
        try:
            response = client.messages.create(
                model=model, max_tokens=BOUNDARY_TOKENS,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            )
        except Exception as e:
            errors.append(f"{model}: {type(e).__name__}")
            progress("extracting", f"{label} with {model} failed ({type(e).__name__}); trying the fallback")
            continue
        cost = spend.record(model, response.usage)
        u = response.usage
        usage = {"input_tokens": getattr(u, "input_tokens", 0), "output_tokens": getattr(u, "output_tokens", 0),
                 "usd": round(float(cost or 0), 5), "seconds": round(time.time() - t0, 1)}
        progress("extracting", f"{label}: {model}, {usage['input_tokens']} in / {usage['output_tokens']} out "
                               f"tokens, ${usage['usd']:.4f}, {usage['seconds']} s")
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
        if response.stop_reason in ("refusal", "max_tokens") or not text:
            errors.append(f"{model}: stop {response.stop_reason}")
            continue
        return model, text, usage
    raise RuntimeError(f"{label} failed: {'; '.join(errors)}")


def _image_block(data: bytes) -> dict:
    import base64

    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(data).decode()}}


def _clean_done_times(steps: list[_DoneStep], duration: float, min_s: float) -> tuple[list[_DoneStep], list[str]]:
    """Monotonic done times inside the video; a step shorter than min_s (QUICK_FLIP_MIN_S for a flagged quick flip)
    is merged with its neighbour: into the next step for the first step, else the earlier step is folded into it
    (its end state, title and question win, because they describe where the merged clip ends)."""
    notes: list[str] = []
    out: list[_DoneStep] = []
    for st in steps:
        t = min(max(0.0, float(st.done_s)), duration)
        if out and t <= out[-1].done_s + 0.1:
            notes.append(f"'{st.title}' done at {t:.1f} s is not after the previous step; merged into it")
            out[-1] = st.model_copy(update={"done_s": max(out[-1].done_s, t)})
            continue
        out.append(st.model_copy(update={"done_s": t}))
    changed = True
    while changed and len(out) > 1:
        changed = False
        for i, st in enumerate(out):
            start = out[i - 1].done_s if i else 0.0
            end = duration if i == len(out) - 1 else st.done_s
            need = QUICK_FLIP_MIN_S if st.quick_flip else min_s
            if end - start >= need:
                continue
            if i == 0:
                notes.append(f"step 1 '{st.title}' is {end - start:.1f} s; merged into the next step")
                del out[0]
            else:
                notes.append(f"'{st.title}' is {end - start:.1f} s; the step before it is merged into it")
                del out[i - 1]
            changed = True
            break
    return out, notes


def _ref_near_cut(video: Path, a: float, done: float) -> float:
    """The reference time for a step that ends at its done frame: the done frame itself (just before the cut),
    unless a frame in the REF_WINDOW_BEFORE_CUT seconds before it is about as still, looks nearly the same
    (mean 96x96 gray difference to the done frame at most REF_SAME_SHAPE, so the fold is already in place) and shows
    3 to 20% more bright, uncovered material (a hand moved off the paper; a much larger bright area would be the
    sheet before the fold). On the 0.1 s grid, inside [a, done]."""
    t1 = done
    t0 = max(a, done - REF_WINDOW_BEFORE_CUT)
    default = max(quantize(a), _floor_tenth(done))
    if t1 - t0 < 0.3:
        return default
    try:
        frames = _gray_frames(video, t0, t1 + 0.1, REF_STILL_FPS)
    except RuntimeError:
        return default
    if len(frames) < 3:
        return default
    level = REF_BRIGHT * max(_percentile_gray(img, 0.99) for _, img in frames)
    scored = [(t, _motion(frames, i), sum(img.histogram()[min(255, int(level)):]), _brightness(img))
              for i, (t, img) in enumerate(frames) if t <= t1 + 1e-6]
    if not scored:
        return default
    from PIL import ImageChops, ImageStat

    base = scored[-1]  # the done frame
    done_img = [img for t, img in frames if t <= t1 + 1e-6][-1]

    def same_shape(t: float) -> bool:
        img = next(im for tt, im in frames if tt == t)
        return ImageStat.Stat(ImageChops.difference(img, done_img)).mean[0] <= REF_SAME_SHAPE

    better = [c for c in scored if c[3] >= DARK and c[1] <= max(base[1] * 1.2, base[1] + 0.3)
              and base[2] * 1.03 < c[2] <= base[2] * 1.2 and same_shape(c[0])]
    if not better:
        return default
    best = max(better, key=lambda c: (c[2], c[0]))
    return max(quantize(a), _floor_tenth(best[0]))


def extract_vision(norm: Path, lesson_dir: Path, progress: Progress = noop, prior: Path | None = None) -> Extraction:
    """Steps cut where the model sees each step DONE (frames only, two calls). See the section comment.

    Writes lesson_dir/review/boundaries.json with both passes (times, reasons, model, tokens) and the final cuts.
    Each step's ref_time is its done frame (see _ref_near_cut); cut() must be called with exact_refs=True so it is
    kept. Raises RuntimeError on failure (the caller falls back to extract_claude)."""
    norm, lesson_dir = Path(norm), Path(lesson_dir)
    duration = probe_duration(norm)
    every = teach_sample_s()
    log_out: dict = {"video_s": round(duration, 2), "sample_s": every}
    with tempfile.TemporaryDirectory(prefix="handover-vision-") as tmp:
        frames = _frames_at_rate(norm, 0.0, duration, every, SHEET_TILE_H, Path(tmp) / "all")
        if not frames:
            raise RuntimeError("no frames could be sampled from the take")
        per = SHEET_COLS * SHEET_ROWS
        content: list[dict] = []
        for k in range(0, len(frames), per):
            chunk = frames[k:k + per]
            content.append({"type": "text", "text": f"Sheet {k // per + 1}: {fmt_mmss(chunk[0][0])} to "
                                                    f"{fmt_mmss(chunk[-1][0])}"})
            content.append(_image_block(_tile(chunk, SHEET_COLS)))
        prompt = DONE_PROMPT.format(every=every, duration=duration)
        if prior:
            prompt += DONE_PRIOR + prior_text(prior)[len(PRIOR_PROMPT):]
        content.append({"type": "text", "text": prompt})
        progress("extracting", f"Pass 1: {len(frames)} frames on {(len(frames) + per - 1) // per} sheets, "
                               f"finding when each step is done")
        model1, text, usage1 = _boundary_call(content, _strict_schema(_DoneAnswer), "pass 1", progress)
        try:
            answer = _DoneAnswer.model_validate_json(text)
        except ValidationError as e:
            raise RuntimeError(f"pass 1 answer did not match the schema: {e}") from None
        raw = []
        for w in answer.steps:
            t = _wire_seconds(w.done_at)
            if t is not None:
                raw.append(_DoneStep(title=w.title, check_question=w.check_question, common_mistake=w.common_mistake,
                                     done_s=t, reason=w.reason, quick_flip=w.quick_flip))
        if not raw:
            raise RuntimeError("pass 1 returned no steps with a readable time")
        log_out["pass1"] = {"model": model1, "usage": usage1,
                            "steps": [{"n": i + 1, "title": s.title, "done_s": round(s.done_s, 2),
                                       "reason": s.reason, "quick_flip": s.quick_flip}
                                      for i, s in enumerate(raw)]}
        steps, notes = _clean_done_times(raw, duration, min_step_s())

        # pass 2: every boundary between steps (the last step ends at the last frame)
        refined: list[dict] = []
        content = []
        windows = []
        for k, st in enumerate(steps[:-1], start=1):
            t = st.done_s
            w0, w1 = max(0.0, t - REFINE_HALF_S), min(duration - 0.05, t + REFINE_HALF_S)
            win = _frames_at_rate(norm, w0, w1 + 0.01, REFINE_STEP_S, REFINE_TILE_H, Path(tmp) / f"w{k:02d}")
            if len(win) < 2:
                continue
            windows.append((k, win))
            end_state = st.check_question if not _is_manual(st.check_question) else st.reason
            content.append({"type": "text", "text": f"Boundary {k}: end of step {k} '{st.title}'. End state: "
                                                    f"{end_state} (coarse estimate {t:.2f} s)"})
            content.append(_image_block(_tile(win, REFINE_COLS)))
        model2, usage2 = None, None
        if windows:
            content.append({"type": "text", "text": REFINE_PROMPT})
            progress("extracting", f"Pass 2: refining {len(windows)} boundaries at {REFINE_STEP_S:g} s")
            try:
                model2, text, usage2 = _boundary_call(content, _strict_schema(_RefineAnswer), "pass 2", progress)
                got = {}
                for w in _RefineAnswer.model_validate_json(text).boundaries:
                    t = _wire_seconds(w.done_at)
                    if t is not None:
                        got[w.boundary] = _Refined(boundary=w.boundary, done_s=t, reason=w.reason)
            except (RuntimeError, ValidationError) as e:
                progress("extracting", f"Pass 2 failed ({str(e)[:120]}); keeping the pass 1 times")
                got = {}
            for k, win in windows:
                coarse = steps[k - 1].done_s
                b = got.get(k)
                t = coarse
                reason = "pass 2 gave no answer; pass 1 time kept"
                if b is not None and win[0][0] - 0.01 <= b.done_s <= win[-1][0] + 0.01:
                    t = min(win, key=lambda f: abs(f[0] - b.done_s))[0]  # snap to a frame the model saw
                    reason = b.reason
                elif b is not None:
                    reason = f"pass 2 time {b.done_s:.2f} s is outside the window; pass 1 time kept"
                refined.append({"boundary": k, "coarse_s": round(coarse, 2), "done_s": round(t, 2),
                                "window_s": [win[0][0], win[-1][0]], "reason": reason,
                                "frames": [f[0] for f in win]})
                steps[k - 1] = steps[k - 1].model_copy(update={"done_s": t})
        log_out["pass2"] = {"model": model2, "usage": usage2, "boundaries": refined}
        steps, notes2 = _clean_done_times(steps, duration, min_step_s())
        notes += notes2

    out_steps: list[Step] = []
    cuts = []
    a = 0.0
    for i, st in enumerate(steps):
        last = i == len(steps) - 1
        done = st.done_s
        b = duration if last else quantize(done + 0.1)  # the done frame belongs to this step; the next starts there
        ref = _ref_near_cut(norm, a, min(done, b - 0.1))
        out_steps.append(Step(start=fmt_mmss(a), end=fmt_mmss(b), title=st.title.strip(),
                              check_question=st.check_question.strip() or "manual",
                              prerequisites=[i] if i else [], ref_time=fmt_mmss(ref),
                              common_mistake=st.common_mistake.strip()))
        cuts.append({"n": i + 1, "title": st.title.strip(), "start": fmt_mmss(a), "end": fmt_mmss(b),
                     "done_s": round(done, 2), "ref_time": fmt_mmss(ref), "reason": st.reason,
                     "quick_flip": st.quick_flip})
        a = b
    log_out.update({"notes": notes, "cuts": cuts})
    review = lesson_dir / "review"
    review.mkdir(parents=True, exist_ok=True)
    _write_json(review / "boundaries.json", log_out)
    for c in cuts:
        progress("extracting", f"step {c['n']}: {c['start']} to {c['end']}  {c['title']}  ({c['reason']})")
    for n in notes:
        progress("extracting", n)
    return Extraction(transcript=[], steps=out_steps, safety=_clean_list(answer.safety),
                      tools=_clean_list(answer.tools))


def ref_times_at_cuts(lesson_dir: Path, lesson: dict) -> None:
    """--recut --repick --boundaries vision: each step's ref_time becomes its done frame at the (possibly hand
    edited) cut, with the same occlusion tie-break as a new vision build (see _ref_near_cut). In place."""
    video = Path(lesson_dir) / (lesson.get("video") or "norm.mp4")
    for st in lesson.get("steps") or []:
        try:
            a, b = parse_time(st["start"]), parse_time(st["end"])
        except (KeyError, ValueError, TypeError):
            continue
        if b - a >= 0.3:
            st["ref_time"] = fmt_mmss(_ref_near_cut(video, a, b - 0.1))


# ---------------------------------------------------------------- 6. full pipeline

def _sources_duration(srcs: list[Path]) -> float:
    return sum(probe_duration(Path(s)) for s in srcs)


def _plan_extraction(duration: float, steps_json: Path | None) -> Extraction:
    """What a mock or steps-file build would cut, without touching any file."""
    ex = _clean_extraction(mock_extraction(duration, steps_json), duration)
    return ex if steps_json else _first_step_manual(ex)


def _gemini_transcript_mode(ex: Extraction, norm: Path, progress: Progress) -> Extraction:
    """HANDOVER_TRANSCRIBE for Gemini: model keeps its transcript, local replaces it with faster-whisper's
    (Gemini's stays if whisper fails), off drops it so the captions are empty."""
    mode = transcribe_mode("gemini")
    if mode == "off":
        progress("extracting", "HANDOVER_TRANSCRIBE=off: captions will be empty")
        return ex.model_copy(update={"transcript": []})
    if mode == "local":
        local = _transcribe_safely(norm, progress)
        if local is not None:
            return ex.model_copy(update={"transcript": local})
        progress("extracting", "Keeping Gemini's transcript for the captions")
    return ex


def build(srcs: list[Path], lesson_id: str, title: str, progress: Progress = noop,
          steps_json: Path | None = None, *, prior: Path | None = None, retitle: bool = False,
          strict: bool = False, boundaries: str = "legacy") -> dict:
    """normalize, extract, clean, cut, then questions (or titles, retitle) from the reference frames and the
    automatic self-test. prior: a steps template used as a strong prior by the Claude extraction (known task);
    retitle and strict: see _after_cut. boundaries "vision" (Claude only): cut where the model sees each step done
    (extract_vision); on failure it falls back to the legacy extraction."""
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
    vision = False

    if steps_json:
        progress("extracting", f"Using steps from {Path(steps_json).name}")
        extraction = _clean_extraction(mock_extraction(duration, steps_json), duration)
    else:
        provider = teach_provider()
        if provider == "mock":
            why = "HANDOVER_TEACH_MOCK is set" if config.get("HANDOVER_TEACH_MOCK") else "no Gemini or Anthropic key"
            progress("extracting", f"Using three placeholder steps ({why})")
            extraction = mock_extraction(duration, None)
        elif provider == "claude" and boundaries == "vision":
            try:
                extraction = extract_vision(norm, lesson_dir, progress, prior)
                vision = True
            except Exception as e:
                reason = scrub(f"{type(e).__name__}: {e}".splitlines()[0][:160])
                progress("extracting", f"Vision boundaries failed ({reason}); falling back to the legacy extraction")
                extraction = extract_claude(norm, progress, prior)
        elif provider == "claude":
            progress("extracting", f"Finding steps with {_claude_model()} from frames")
            extraction = extract_claude(norm, progress, prior)
        else:
            if prior:
                progress("extracting", "the step plan prior is used by the Claude extraction only; ignored")
            progress("extracting", f"Finding steps with {_model()}")
            extraction = _gemini_transcript_mode(extract(norm, progress), norm, progress)
        extraction = _clean_extraction(extraction, duration)
        if vision:  # boundaries are the model's done moments: no flip splitting, no merging here
            extraction = _crease_steps_manual(_contiguous(extraction))
        else:
            extraction = _crease_steps_manual(_contiguous(_split_flips(extraction)))
        if provider in ("claude", "gemini") and not vision:
            before = len(extraction.steps)
            extraction = _merge_short_steps(extraction)
            if len(extraction.steps) < before:
                progress("extracting", f"Merged steps shorter than {min_step_s():g} s: "
                                       f"{before} steps became {len(extraction.steps)}")
        extraction = _first_step_manual(extraction)
        if provider in ("claude", "gemini"):
            extraction = guard_colors(extraction, provider, progress)

    progress("cutting", f"Cutting {len(extraction.steps)} step clips")
    lesson = cut(lesson_dir, extraction, lesson_id, title, progress=progress, exact_refs=vision)
    if not steps_json and provider in ("claude", "gemini"):
        # job statuses are a fixed list in the apps (queued ... cutting, done): report this under "cutting"
        lesson = _after_cut(lesson_dir, lesson, provider, lambda st, msg: progress("cutting", f"{st}: {msg}"),
                            retitle=retitle, strict=strict)
    progress("done", f"{len(lesson['steps'])} steps ready")
    return lesson


def scrub(text: str) -> str:
    """Error text safe to show in a job status: the Gemini and Anthropic keys removed (check._redact and the
    same rule for ANTHROPIC_API_KEY) and absolute paths
    replaced by <lessons>, <repo> and <tmp>."""
    try:
        from server import check

        text = check._redact(text)
    except Exception:  # check.py unavailable or no key configured: nothing to redact
        pass
    for key in (_secret("GEMINI_API_KEY", "GOOGLE_API_KEY"), _anthropic_key()):
        if key:
            text = text.replace(key, "***")
    roots = []
    for label, root in (("<lessons>", lessons_root()), ("<repo>", REPO), ("<tmp>", Path(tempfile.gettempdir()))):
        for form in {str(root), str(Path(root).resolve()), Path(root).as_posix(), Path(root).resolve().as_posix()}:
            roots.append((form.rstrip("/\\"), label))
    for form, label in sorted(roots, key=lambda r: -len(r[0])):  # longest first: lessons may sit inside the repo
        if len(form) > 1:
            text = text.replace(form, label)
    return text


def process_upload(src: Path, lesson_id: str, title: str, progress: Progress = noop,
                   steps_json: Path | None = None) -> dict:
    """normalize -> extract -> cut. Returns lesson.json as a dict. Raises on failure, with the message scrubbed
    (see scrub) because the hub shows it to the browser as the job status."""
    try:
        return build([Path(src)], lesson_id, title, progress, steps_json)
    except Exception as e:
        msg = scrub(str(e))
        if type(e) in (RuntimeError, ValueError):
            raise type(e)(msg) from None
        raise RuntimeError(scrub(f"{type(e).__name__}: {e}")) from None


# ---------------------------------------------------------------- 7. CLI

def _print_plan(extraction: Extraction, spans: list[tuple[float, float]], explicit: bool) -> None:
    for n, (st, (a, b)) in enumerate(zip(extraction.steps, spans), start=1):
        kind = "manual" if _is_manual(st.check_question) else "camera"
        ref = st.ref_time.strip()
        ref_note = (f"reference at {ref}" if explicit else f"reference near {ref} if still") if ref \
            else "reference: stillest frame in the last 15%"
        print(f"  {n:2d}. {fmt_mmss(a)} to {fmt_mmss(b)} ({b - a:.1f} s)  {st.title.strip()}  [{kind}]  {ref_note}")


class UsageError(Exception):
    pass


def _lesson_dir_arg(path: Path) -> Path:
    path = Path(path)
    if not (path / "lesson.json").is_file():
        raise UsageError(f"no lesson.json in {path}")
    return path


def step_table(lesson: dict) -> str:
    """n, title, start, end, check type, question and self-test of every step, as an aligned text table."""
    rows = [("#", "Title", "Start", "End", "Check", "Question", "Self-test")]
    for i, s in enumerate(lesson.get("steps") or []):
        st = s.get("self_test")
        test = "-" if not isinstance(st, dict) else \
            f"{'ok' if st.get('ok') else 'FAIL'} (own {st.get('own')}, prev {st.get('prev')})"
        q = str(s.get("check_question") or "")
        rows.append((str(s.get("n", i + 1)), str(s.get("title") or ""), str(s.get("start") or ""),
                     str(s.get("end") or ""), str(s.get("check_type") or "camera"),
                     q if len(q) <= 70 else q[:67] + "...", test))
    w = [max(len(r[c]) for r in rows) for c in range(len(rows[0]))]
    out = []
    for k, r in enumerate(rows):
        out.append("  ".join(c.ljust(w[j]) for j, c in enumerate(r)).rstrip())
        if k == 0:
            out.append("  ".join("-" * x for x in w))
    return "\n".join(out)


def _run_cli(args, show: Progress) -> int:
    t0 = time.time()
    if args.table:
        d = _lesson_dir_arg(args.table)
        print(step_table(json.loads((d / "lesson.json").read_text(encoding="utf-8"))))
        return 0
    if args.self_test:
        d = _lesson_dir_arg(args.self_test)
        if not (d / "norm.mp4").is_file() and not args.dry_run:
            show("self-test", "norm.mp4 missing; the first step may be skipped")
        lesson = json.loads((d / "lesson.json").read_text(encoding="utf-8"))
        camera = [s.get("n", i + 1) for i, s in enumerate(lesson.get("steps") or []) if s.get("check_type") != "manual"]
        from server import check as _check  # the provider the live hub uses, not the Gemini default
        mode = "mock" if _check_is_mock() else _check.active_model()
        show("self-test", f"{len(camera)} camera steps in {d}, check: {mode}")
        if args.dry_run:
            print(f"  would test steps {', '.join(map(str, camera)) or 'none'}")
            return 0
        import asyncio

        lesson, errored = asyncio.run(_self_test(d, show))
        failed = [s.get("n", i + 1) for i, s in enumerate(lesson.get("steps") or [])
                  if isinstance(s.get("self_test"), dict) and not s["self_test"].get("ok")]
        print(f"[done] self-test wrote lesson.json ({time.time() - t0:.1f} s)")
        if errored:
            print(f"error: the check failed on steps {', '.join(map(str, errored))}, so they were not tested. "
                  f"Check the Gemini key and limits, then run the self-test again.", file=sys.stderr)
            return 1
        if failed:
            print(f"Steps that failed: {', '.join(map(str, failed))}. Make them manual or reword the question, "
                  f"then run the self-test again.")
            return 3
        return 0

    if args.recut:
        d = _lesson_dir_arg(args.recut)
        if args.dry_run:
            lesson = json.loads((d / "lesson.json").read_text(encoding="utf-8"))
            extraction = _lesson_extraction(d, lesson)
            spans = _spans(extraction, probe_duration(d / "norm.mp4"))
            print(f"[dry-run] recut of {d} would cut {len(spans)} steps:")
            _print_plan(extraction, spans, explicit=True)
            return 0
        show("cutting", f"Recutting {d}")
        lesson = recut(d, show, retitle=args.retitle, strict=args.strict_self_test, repick=args.repick,
                       boundaries=args.boundaries)
        print(f"[done] recut {len(lesson['steps'])} steps in {d} ({time.time() - t0:.1f} s)")
        return 0

    if not args.video or not args.lesson_id:
        raise UsageError("VIDEO and --id are required (or use --recut LESSON_DIR or --self-test LESSON_DIR)")
    srcs = [args.video, *args.concat]
    for src in srcs:
        if not Path(src).is_file():
            raise UsageError(f"video not found: {src}")
    if args.steps_json and not Path(args.steps_json).is_file():
        raise UsageError(f"steps file not found: {args.steps_json}")
    if args.dry_run:
        if not args.steps_json and not config.get("HANDOVER_TEACH_MOCK"):
            raise UsageError("--dry-run never calls Gemini: pass --steps-json, or set HANDOVER_TEACH_MOCK=1")
        duration = _sources_duration(srcs)
        extraction = _plan_extraction(duration, args.steps_json)
        dest = lessons_root() / sanitize_id(args.lesson_id)
        print(f"[dry-run] {dest}{' (exists, would be overwritten)' if dest.exists() else ''}: "
              f"{len(extraction.steps)} steps from {duration:.1f} s of video")
        _print_plan(extraction, _spans(extraction, duration), explicit=False)
        return 0
    if args.prior and not Path(args.prior).is_file():
        raise UsageError(f"prior steps file not found: {args.prior}")
    lesson = build(srcs, args.lesson_id, args.title or args.lesson_id, show, args.steps_json, prior=args.prior,
                   retitle=args.retitle, strict=args.strict_self_test, boundaries=args.boundaries)
    print(f"[done] {lessons_root() / lesson['id']} ({time.time() - t0:.1f} s)")
    for s in lesson["steps"]:
        print(f"  {s['n']:2d}. {s['start']} to {s['end']}  {s['title']}  [{s['check_type']}]")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.teach", description="Turn one expert video into a lesson.")
    ap.add_argument("video", nargs="?", type=Path)
    ap.add_argument("--id", dest="lesson_id")
    ap.add_argument("--title")
    ap.add_argument("--steps-json", type=Path)
    ap.add_argument("--concat", nargs="+", type=Path, default=[], help="more videos appended after VIDEO")
    ap.add_argument("--recut", type=Path, metavar="LESSON_DIR")
    ap.add_argument("--self-test", type=Path, metavar="LESSON_DIR",
                    help="check each camera question against its own and the previous reference frame")
    ap.add_argument("--dry-run", action="store_true", help="print the planned cuts and write nothing")
    ap.add_argument("--prior", type=Path, metavar="STEPS_JSON",
                    help="known task: a steps template (lessons/templates/*.steps.json) as a strong prior for the "
                         "Claude extraction; its times are ignored")
    ap.add_argument("--retitle", action="store_true",
                    help="after the cut, rewrite titles, check questions and tips from each step's frames")
    ap.add_argument("--strict-self-test", action="store_true",
                    help="every step that fails the automatic self-test becomes manual (default: only those "
                         "whose own reference fails)")
    ap.add_argument("--repick", action="store_true", help="with --recut: choose every reference frame again")
    ap.add_argument("--boundaries", choices=("legacy", "vision"), default="legacy",
                    help="vision: cut where the model sees each step done (frames only, Claude, two calls); with "
                         "--recut --repick: each reference is the done frame at its cut")
    ap.add_argument("--table", type=Path, metavar="LESSON_DIR", help="print the lesson's step table and exit")
    args = ap.parse_args(argv)
    if args.recut and args.self_test:
        ap.error("use either --recut or --self-test, not both")

    def show(status: str, message: str) -> None:
        print(f"[{status}] {message}", flush=True)

    try:
        return _run_cli(args, show)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (RuntimeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

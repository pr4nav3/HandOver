"""Real-time step understanding: where the learner is inside a step, and mistakes as they happen.

The live check (check.py) asks one yes/no question against one reference frame, the end of the step.
This module adds two things on top of it, both Claude only, both guarded by the spend ledger:

1. A teach-time rubric, built once per lesson (build_rubric). For each camera step it samples three
   keyframes from the expert's video (START, MID, DONE: the stillest frame near each point) into
   frames/NN_a.jpg, NN_b.jpg and NN_c.jpg, and one Claude call over all steps returns, per step:
   2 to 4 visible stages, the done cue, 1 to 3 likely mistakes (label, visible sign, a hint of at most
   10 words, severity) and the region where the action happens. Written to lessons/<id>/rubric.json,
   an additive file: lesson.json is never touched.

2. Live understanding (understand_frame): one call per frame with a cached prefix (system rules, the
   step's rubric text, BEFORE, START, MID and DONE) and the LIVE image last. It answers the stage, a
   progress from 0 to 1, done yes|no|unsure with a confidence, a mistake label (or none) with its own
   confidence, and seen and differs. The result is a CheckResult subclass, so the engine can use it
   as a drop-in for check_frame (done, confidence, reason) and read the new fields when it wants them.

MistakeTracker turns understanding results into live mistake messages (kind "live"): the same label
in N results in a row at a minimum confidence, cleared when the stage advances or the label is gone,
with a per-label cooldown. It complements mistake.py's behind and ahead logic; it does not replace it.

    python -m server.understand --rubric lessons/<id> [--model M] [--keep-frames]
    python -m server.understand --live lessons/<id> STEP_N LIVE.jpg [-n 3]

Settings (read through config.get once registered there; until then through the config.env_* helpers
with the same defaults and bounds, see SETTINGS below):
    HANDOVER_UNDERSTAND_MODEL           Claude model for the rubric and live calls (default claude-haiku-5-5)
    HANDOVER_UNDERSTAND_TIMEOUT         seconds before a live call counts as a timeout (default 5, 0.1 to 60)
    HANDOVER_LIVE_MISTAKE_MIN_CONF      minimum mistake confidence that counts (default 0.75, 0 to 1)
    HANDOVER_LIVE_MISTAKE_REPEAT        results in a row with the same label to fire (default 2, 1 to 10)
    HANDOVER_LIVE_MISTAKE_CLEAR         results in a row without the label to clear it (default 2, 1 to 10)
    HANDOVER_LIVE_MISTAKE_COOLDOWN_S    seconds before the same label may fire again (default 8, 0 to 600)
Also honored, from check.py: HANDOVER_CLAUDE_CACHE, HANDOVER_NO_NETWORK, HANDOVER_CHECK=mock.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from server import check, config, spend
from server.check import CheckResult, Done

log = logging.getLogger("handover.understand")

DEFAULT_MODEL = "claude-haiku-5-5"
RUBRIC_FILE = "rubric.json"
RUBRIC_VERSION = 1
KEY_LABELS = ("START", "MID", "DONE")
KEY_SUFFIXES = ("a", "b", "c")
KEY_MAX_SIDE = 672  # keyframes and BEFORE in the live call: same size as check.py's cached references
RUBRIC_IMAGE_SIDE = 512  # keyframes in the one rubric call: up to 3 per camera step, so a little smaller
JPEG_QUALITY = 85
LIVE_MAX_TOKENS = 384  # Haiku 5.x with thinking off: about 90 tokens of JSON; room for long labels
LIVE_THINKING_MAX_TOKENS = 1536  # models that keep adaptive thinking (Sonnet, Opus) need room for it
RUBRIC_MAX_TOKENS = 8000
RUBRIC_TIMEOUT_S = 180.0
WORDS_SEEN = 8
WORDS_HINT = 10
WORDS_LABEL = 5
MAX_STAGES = 4
MAX_MISTAKES = 3
SEVERITIES = ("low", "medium", "high")
SAME_FRAME_DIFF = 2.0  # mean gray difference (0 to 255, 96 px thumbnails) below which two keyframes count as one

Progress = Callable[[str, str], None]


def _noop(status: str, message: str) -> None:
    del status, message


# ---------------------------------------------------------------- settings

# name: (kind, default, min, max). Proposed for server/config.py's REGISTRY; values here must match it.
SETTINGS: dict[str, tuple[str, Any, Optional[float], Optional[float]]] = {
    "HANDOVER_UNDERSTAND_MODEL": ("str", DEFAULT_MODEL, None, None),
    "HANDOVER_UNDERSTAND_TIMEOUT": ("float", 5.0, 0.1, 60),
    "HANDOVER_LIVE_MISTAKE_MIN_CONF": ("float", 0.75, 0, 1),
    "HANDOVER_LIVE_MISTAKE_REPEAT": ("int", 2, 1, 10),
    "HANDOVER_LIVE_MISTAKE_CLEAR": ("int", 2, 1, 10),
    "HANDOVER_LIVE_MISTAKE_COOLDOWN_S": ("float", 8.0, 0, 600),
}


def setting(name: str) -> Any:
    """The registry value once config.py knows the name; until then the same default and bounds from SETTINGS."""
    try:
        config.tunable(name)
    except KeyError:
        kind, default, lo, hi = SETTINGS[name]
        if kind == "str":
            return config.env_str(name, default)
        reader = getattr(config, "env_" + kind)
        return reader(name, default, None if lo is None else type(default)(lo), None if hi is None else type(default)(hi))
    return config.get(name)


def model_name(override: Optional[str] = None) -> str:
    return str(override or setting("HANDOVER_UNDERSTAND_MODEL") or DEFAULT_MODEL)


def _timeout(override: Optional[float] = None) -> float:
    if override is not None and override > 0:
        return float(override)
    return float(setting("HANDOVER_UNDERSTAND_TIMEOUT"))


# ---------------------------------------------------------------- small text helpers

def _words(text: Any, n: int) -> str:
    """At most n words, one line, trailing punctuation dropped. Never None."""
    out = " ".join(str(text or "").replace("\n", " ").split()[:n]).strip()
    return out.rstrip(".,;:")


def _label(text: Any) -> str:
    return _words(text, WORDS_LABEL).lower()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if v != v else v  # NaN


def _clamp01(value: Any) -> float:
    return max(0.0, min(1.0, _num(value)))


# ---------------------------------------------------------------- images

_blocks: "dict[tuple[str, int], dict]" = {}
_BLOCKS_MAX = 128


def _image_block(jpeg: bytes, side: int = KEY_MAX_SIDE) -> dict:
    """Image block for a fixed image (keyframe or BEFORE), memoized by sha1 so the bytes are identical on every
    call and the prompt cache matches. Shared: callers copy it before adding cache_control."""
    key = (hashlib.sha1(jpeg).hexdigest(), side)
    block = _blocks.get(key)
    if block is None:
        block = check._claude_image(check.downscale_jpeg(jpeg, side, JPEG_QUALITY))
        if len(_blocks) >= _BLOCKS_MAX:
            _blocks.pop(next(iter(_blocks)))
        _blocks[key] = block
    return block


def _gray_thumb(jpeg: bytes):
    from PIL import Image

    with Image.open(io.BytesIO(jpeg)) as im:
        return im.convert("L").resize((96, 96))


def frame_diff(a: bytes, b: bytes) -> float:
    """Mean gray difference of two JPEGs on 96 px thumbnails: 0 is identical, 255 is opposite."""
    from PIL import ImageChops, ImageStat

    return ImageStat.Stat(ImageChops.difference(_gray_thumb(a), _gray_thumb(b))).mean[0]


# ---------------------------------------------------------------- rubric: keyframes

def _stillest(video: Path, t0: float, t1: float, target: float) -> Optional[float]:
    """The stillest, not black moment in [t0, t1], ties going to the one nearest target. teach.py's
    stillness measure: mean gray difference to the neighboring frames on 96 px thumbnails."""
    from server import teach

    if t1 - t0 < 0.05:
        return None
    fps = min(30.0, max(5.0, 8.0 / (t1 - t0)))
    frames = teach._gray_frames(video, t0, t1, fps)
    if not frames:
        return None
    scored = [(t, teach._motion(frames, i), teach._brightness(img)) for i, (t, img) in enumerate(frames)]
    lit = [s for s in scored if s[2] >= teach.DARK] or scored
    best = min(lit, key=lambda s: (round(s[1], 1), abs(s[0] - target)))
    return int(best[0] * 10 + 1e-6) / 10


def _windows(a: float, b: float) -> list[tuple[float, float, float]]:
    """(t0, t1, target) for START and MID. 15% of the step (at least 0.3 s, at most a third of it)."""
    length = b - a
    w = min(max(0.15 * length, 0.3), length / 3)
    mid = (a + b) / 2
    return [(a + 0.05, a + w, a), (mid - w / 2, mid + w / 2, mid)]


def _read(path: Path) -> Optional[bytes]:
    return path.read_bytes() if path.is_file() and path.stat().st_size > 0 else None


def sample_keyframes(lesson_dir: Path, lesson: dict, *, resample: bool = True) -> dict[int, dict]:
    """Writes frames/NN_a.jpg, NN_b.jpg and NN_c.jpg for every camera step and returns, per step number,
    {"files": [rel paths], "times": [seconds or None], "sources": [...]}.

    DONE is the step's reference frame (the one the live check already compares with), so both checks agree on
    what finished looks like. START and MID are the stillest frames near the step's start and middle. When START
    looks the same as DONE (a static video, or a step that starts with a cut) the previous step's reference
    stands in as START, since that is what the object looks like before the step. resample=False keeps
    keyframe files that already exist (a teacher's hand-picked frames, or the benchmark's)."""
    from server import teach

    lesson_dir = Path(lesson_dir)
    steps = lesson.get("steps") or []
    video = lesson_dir / (lesson.get("video") or "norm.mp4")
    (lesson_dir / "frames").mkdir(parents=True, exist_ok=True)
    out: dict[int, dict] = {}
    for i, s in enumerate(steps):
        if s.get("check_type", "camera") != "camera":
            continue
        n = int(s.get("n", i + 1))
        rels = [f"frames/{n:02d}_{x}.jpg" for x in KEY_SUFFIXES]
        paths = [lesson_dir / r for r in rels]
        if not resample and all(_read(p) for p in paths):
            out[n] = {"files": rels, "times": [None, None, None], "sources": ["kept"] * 3}
            continue
        ref = _read(lesson_dir / (s.get("ref_frame") or f"frames/{n:02d}.jpg"))
        prev = None
        if i > 0:
            prev = _read(lesson_dir / (steps[i - 1].get("ref_frame") or f"frames/{n - 1:02d}.jpg"))
        times: list[Optional[float]] = [None, None, None]
        sources = ["", "", ""]
        try:
            a, b = teach.parse_time(s["start"]), teach.parse_time(s["end"])
        except (KeyError, ValueError):
            a = b = 0.0
        # DONE: the reference frame; else the stillest frame near the end
        if ref is not None:
            paths[2].write_bytes(ref)
            sources[2] = "ref_frame"
            try:
                times[2] = teach.parse_time(s["ref_time"]) if s.get("ref_time") else None
            except ValueError:
                times[2] = None
        elif video.is_file() and b > a:
            t = teach.pick_ref_time(video, a, b)
            if t is not None:
                teach._grab_frame(video, t, paths[2])
                times[2], sources[2] = t, "video"
        if not _read(paths[2]):
            raise RuntimeError(f"step {n}: no reference frame and no video to take a DONE keyframe from")
        done = paths[2].read_bytes()
        # START and MID from the video
        for k, (t0, t1, target) in enumerate(_windows(a, b) if video.is_file() and b > a else []):
            try:
                t = _stillest(video, t0, t1, target)
                if t is not None:
                    teach._grab_frame(video, t, paths[k])
                    times[k], sources[k] = t, "video"
            except RuntimeError as e:
                log.warning("step %d: could not sample the %s keyframe: %s", n, KEY_LABELS[k], e)
        if prev is not None and (not _read(paths[0]) or frame_diff(paths[0].read_bytes(), done) < SAME_FRAME_DIFF):
            paths[0].write_bytes(prev)
            times[0], sources[0] = None, "prev_ref_frame"
        for k in (0, 1):  # nothing better: the step's own reference
            if not _read(paths[k]):
                paths[k].write_bytes(done)
                times[k], sources[k] = None, "ref_frame"
        out[n] = {"files": rels, "times": times, "sources": sources}
    return out


# ---------------------------------------------------------------- rubric: the call

RUBRIC_SYSTEM = (
    "You write a visual rubric for a camera that watches a learner repeat a hands-on task, one step at a time. "
    "For each step you get its title, the expert's narration (when there is any), the yes or no check question, "
    "and photos from the expert's video: START (as the step begins), MID (halfway) and DONE (finished). "
    "Describe only what a camera can see: shapes, outlines, corners, folds, seams, layers, which side faces up, "
    "and where parts sit relative to each other. "
    "Every cue must hold at any rotation, position and size: the learner's object may be turned to any angle, "
    "moved, or nearer or farther than in the photos. Describe what changed (corners meet in the middle, a flap "
    "lies on top, a part stands up), never orientation in the picture (no diamond against square for one shape, "
    "no left, right, top or bottom of the image) and never size in the picture. "
    "Do not name colors: the learner's material and light differ. "
    "Never rely on sound, hands, motion or the expert's words alone. "
    "stages: 2 to 4 visible sub-stages in order, from the first visible change after START up to DONE; the last "
    "stage is the finished state. START itself is never a stage: stage 0 is the first visible change. Each has a "
    "short label (at most 4 words) and the visible cue that identifies it (at most 15 words). "
    "done_cue: what must be visible to call the step complete (at most 20 words). "
    "mistakes: 1 to 3 likely beginner mistakes in this step that a camera can see, favoring results that end up "
    "looking wrong (misaligned, incomplete, wrong side up, wrong shape). Each has a short lowercase "
    "label (at most 4 words, unique within the step), the visible sign (at most 15 words), a corrective hint "
    "for the learner of at most 10 words, and severity low, medium or high. A mistake must look different from "
    "every correct stage, including half-finished ones, and from START: an unfinished or unstarted step is not "
    "a mistake. "
    "region: the box around where the action happens, as fractions of the image width and height "
    "(x0 < x1, y0 < y1, all 0 to 1). "
    "Return one entry per step, with the step number n as given."
)
RUBRIC_FINAL = "Write the rubric for every step above."


def rubric_schema() -> dict:
    """Flat structured-output schema: no $defs, every field required, no extra fields, no numeric or length
    bounds (Claude structured outputs reject some; the counts and ranges are enforced in clean_rubric)."""
    def obj(props: dict) -> dict:
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

    text = {"type": "string"}
    stage = obj({"label": text, "cue": text})
    mistake = obj({"label": text, "sign": text, "hint": text,
                   "severity": {"type": "string", "enum": list(SEVERITIES)}})
    region = obj({k: {"type": "number"} for k in ("x0", "y0", "x1", "y1")})
    step = obj({"n": {"type": "integer"}, "stages": {"type": "array", "items": stage}, "done_cue": text,
                "mistakes": {"type": "array", "items": mistake}, "region": region})
    return obj({"steps": {"type": "array", "items": step}})


def _narration(lesson_dir: Path, start: float, end: float) -> str:
    """The transcript lines inside [start, end] from extraction.json, or "" when there is none."""
    path = Path(lesson_dir) / "extraction.json"
    try:
        segs = json.loads(path.read_text(encoding="utf-8")).get("transcript") or []
    except (OSError, ValueError, AttributeError):
        return ""
    words = []
    for seg in segs:
        try:
            a, b = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if b > start and a < end:
            words.append(" ".join(str(seg.get("text", "")).split()))
    return " ".join(w for w in words if w)[:600]


def _step_header(s: dict, n: int, narration: str) -> str:
    q = (s.get("check_question") or "").strip() or "Is this step finished?"
    lines = [f"STEP {n}: {(s.get('title') or '').strip()}", f"Question: {q}"]
    lines.append(f"Narration: {narration}" if narration else "Narration: none")
    return "\n".join(lines)


def rubric_content(lesson_dir: Path, lesson: dict, keyframes: dict[int, dict]) -> list[dict]:
    """Per camera step: its header text, then START, MID and DONE. Then the final instruction."""
    from server import teach

    content: list[dict] = []
    for i, s in enumerate(lesson.get("steps") or []):
        n = int(s.get("n", i + 1))
        if n not in keyframes:
            continue
        try:
            narration = _narration(lesson_dir, teach.parse_time(s["start"]), teach.parse_time(s["end"]))
        except (KeyError, ValueError):
            narration = ""
        content.append({"type": "text", "text": _step_header(s, n, narration)})
        for label, rel in zip(KEY_LABELS, keyframes[n]["files"]):
            content.append({"type": "text", "text": f"STEP {n} {label}"})
            content.append(_image_block((Path(lesson_dir) / rel).read_bytes(), RUBRIC_IMAGE_SIDE))
    content.append({"type": "text", "text": RUBRIC_FINAL})
    return content


def _region(raw: Any) -> dict:
    r = raw if isinstance(raw, dict) else {}
    x0, y0, x1, y1 = (_clamp01(r.get(k)) for k in ("x0", "y0", "x1", "y1"))
    if x1 - x0 < 0.02 or y1 - y0 < 0.02:  # empty or flipped box: the whole frame
        return {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    return {"x0": round(x0, 3), "y0": round(y0, 3), "x1": round(x1, 3), "y1": round(y1, 3)}


def clean_step(raw: dict) -> dict:
    """Enforce what the schema cannot: 1 to 4 stages (2 to 4 asked), at most 3 mistakes with unique labels
    that are not "none", hints of at most 10 words, severity from the list, a region inside the frame."""
    done_cue = _words(raw.get("done_cue"), 30)
    stages = []
    for st in raw.get("stages") or []:
        label, cue = _words(st.get("label"), WORDS_LABEL), _words(st.get("cue"), 25)
        if label or cue:
            stages.append({"label": label or cue, "cue": cue or label})
    stages = stages[:MAX_STAGES] or [{"label": "done", "cue": done_cue or "the finished state"}]
    mistakes, seen = [], set()
    for m in raw.get("mistakes") or []:
        label = _label(m.get("label"))
        if not label or label in seen or label in ("none", "null", "nothing"):
            continue
        seen.add(label)
        sev = str(m.get("severity", "")).strip().lower()
        mistakes.append({"label": label, "sign": _words(m.get("sign"), 25), "hint": _words(m.get("hint"), WORDS_HINT),
                         "severity": sev if sev in SEVERITIES else "medium"})
    return {"stages": stages, "done_cue": done_cue, "mistakes": mistakes[:MAX_MISTAKES],
            "region": _region(raw.get("region"))}


def lesson_signature(lesson: dict) -> str:
    """sha1 of what the rubric depends on: each step's n, title, times, type, question and reference frame name.
    A recut or an edited question changes it, so the engine can tell a stale rubric from a current one."""
    keys = ("n", "title", "start", "end", "check_type", "check_question", "ref_frame", "ref_time")
    data = [{k: s.get(k) for k in keys} for s in lesson.get("steps") or []]
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def _write_json(path: Path, data: dict) -> None:
    """Atomic: a temp file in the same folder, then rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _client():
    """The per-loop AsyncAnthropic from check.py (tests replace check._get_claude with a fake)."""
    return check._get_claude()


def _has_key() -> bool:
    return check._has_client("claude") or bool(check._anthropic_key())


def _thinking_off(model: str) -> bool:
    return check._claude_thinking_off(model)


async def build_rubric(lesson_dir: Path, *, model: Optional[str] = None, resample: bool = True,
                       progress: Progress = _noop) -> dict:
    """Samples the keyframes, makes one Claude call for the whole lesson and writes rubric.json. Returns the
    rubric. Raises RuntimeError with a readable message when there is no key, the budget is spent, or the
    answer is unusable (refusal, cut off, not JSON); what a failed call cost is still in the ledger."""
    lesson_dir = Path(lesson_dir)
    lesson = json.loads(await asyncio.to_thread((lesson_dir / "lesson.json").read_text, encoding="utf-8"))
    model = model_name(model)
    progress("rubric", "Sampling keyframes")
    keyframes = await asyncio.to_thread(sample_keyframes, lesson_dir, lesson, resample=resample)
    steps_by_n = {int(s.get("n", i + 1)): s for i, s in enumerate(lesson.get("steps") or [])}
    rubric: dict = {"version": RUBRIC_VERSION, "lesson_id": lesson.get("id") or lesson_dir.name, "model": model,
                    "created": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "source": lesson_signature(lesson), "cost_usd": 0.0, "steps": []}
    if not keyframes:
        await asyncio.to_thread(_write_json, lesson_dir / RUBRIC_FILE, rubric)
        return rubric
    if not _has_key():
        raise RuntimeError("no Claude key: set ANTHROPIC_API_KEY or add it to .env; no call was made")
    if not spend.allow():
        raise RuntimeError("the Claude spending limit is reached; no call was made")
    content = await asyncio.to_thread(rubric_content, lesson_dir, lesson, keyframes)
    req: dict = {"model": model, "max_tokens": RUBRIC_MAX_TOKENS, "system": [{"type": "text", "text": RUBRIC_SYSTEM}],
                 "messages": [{"role": "user", "content": content}],
                 "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": rubric_schema()}},
                 "timeout": RUBRIC_TIMEOUT_S}
    progress("rubric", f"Asking {model} for stages and mistakes of {len(keyframes)} camera steps")
    try:
        resp = await asyncio.wait_for(_client().messages.create(**req), RUBRIC_TIMEOUT_S + 5)
    except Exception as e:
        raise RuntimeError(f"rubric call failed ({check.classify_error(e)}): {check._redact(str(e))[:200]}") from None
    try:
        text, usd = check._claude_text(resp, model)
    except check._CheckFailure as e:
        raise RuntimeError(f"rubric answer unusable: {e}") from None
    try:
        answer = json.loads(text)
    except ValueError:
        raise RuntimeError("rubric answer was not JSON") from None
    rubric["cost_usd"] = round(usd, 6)
    got = {}
    for raw in answer.get("steps") or []:
        try:
            got[int(raw.get("n"))] = raw
        except (TypeError, ValueError):
            continue
    for n, kf in keyframes.items():
        if n not in got:
            log.warning("rubric: the model returned nothing for step %d; that step keeps the plain check", n)
            continue
        s = steps_by_n[n]
        entry = {"n": n, "title": (s.get("title") or "").strip(),
                 "question": (s.get("check_question") or "").strip() or "Is this step finished?",
                 "keyframes": kf["files"], "keyframe_times": kf["times"], "keyframe_sources": kf["sources"]}
        entry.update(clean_step(got[n]))
        rubric["steps"].append(entry)
    await asyncio.to_thread(_write_json, lesson_dir / RUBRIC_FILE, rubric)
    progress("rubric", f"Rubric written for {len(rubric['steps'])} of {len(keyframes)} camera steps, ${usd:.4f}")
    return rubric


# ---------------------------------------------------------------- rubric: reading

def load_rubric(lesson_dir: Path, lesson: Optional[dict] = None) -> Optional[dict]:
    """rubric.json, or None when missing, unreadable, from another version, or stale (lesson given and its
    signature changed since the rubric was built, e.g. after a recut)."""
    path = Path(lesson_dir) / RUBRIC_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != RUBRIC_VERSION or not isinstance(data.get("steps"), list):
        return None
    if lesson is not None and data.get("source") != lesson_signature(lesson):
        return None
    return data


def step_entry(rubric: Optional[dict], n: int) -> Optional[dict]:
    """The rubric entry of step n (1-based, lesson.json's n), or None."""
    for s in (rubric or {}).get("steps") or []:
        if s.get("n") == n:
            return s
    return None


def read_keyframes(lesson_dir: Path, entry: dict) -> list[bytes]:
    """START, MID, DONE bytes for one entry; raises OSError when a file is missing."""
    return [(Path(lesson_dir) / rel).read_bytes() for rel in entry.get("keyframes") or []]


# ---------------------------------------------------------------- live understanding

@dataclass
class Understanding(CheckResult):
    """A CheckResult (done, confidence, latency_ms, reason, error, cost_usd, cache_read_tokens) plus where the
    learner is inside the step. On a failure: done unsure, confidence 0, stage -1, progress 0, no mistake."""

    stage: int = -1
    """Index into the rubric's stages of the latest stage visible in LIVE; -1 not started or unclear."""
    progress: float = 0.0
    mistake: Optional[str] = None
    """Label of a rubric mistake visible in LIVE, or None."""
    mistake_confidence: float = 0.0
    seen: Optional[str] = None
    """Up to 8 words on LIVE, for logs and the bench. Not sent to the UI."""

    def as_dict(self) -> dict:
        out = super().as_dict()
        out.update(stage=self.stage, progress=round(self.progress, 3), mistake=self.mistake,
                   mistake_confidence=round(self.mistake_confidence, 3))
        return out


UNDERSTAND_SYSTEM = (
    "You watch a learner do one step of a hands-on task through a camera and report how far along the step is. "
    "You get the step's rubric (numbered stages with their visible cues, the done cue, and likely mistakes with "
    "their visible signs) and photos from the expert: BEFORE (the end of the previous step, when given), START, "
    "MID and DONE. Then LIVE, the camera now. "
    "Hands, shadows, background, lighting, rotation, scale and camera angle do not matter: the same shape turned "
    "to any angle, moved, or at another size matches a cue (a square turned 45 degrees looks like a diamond "
    "and still counts). "
    'First write "seen": at most 8 words on LIVE (outline, orientation, visible parts). '
    'Then "differs": at most 8 words on what LIVE lacks compared with DONE, or "nothing". '
    'Then "stage": the number of the latest stage whose cue is visible in LIVE, or -1 if LIVE still looks like '
    "START or BEFORE, or is unclear. "
    'Then "progress" from 0 (looks like BEFORE or START) to 1 (looks like DONE). '
    'Then "mistake": the label of a listed mistake only if its visible sign is clearly in LIVE, else "none". '
    "A correct but unfinished stage is not a mistake: when LIVE fits a stage cue, prefer the stage. "
    'Then "mistake_confidence": 0.9 or more when the sign is plainly visible, about 0.5 when you only suspect '
    "it, 0 when none. "
    'Then "done": yes only if the done cue and every feature in the question are visible in LIVE; no if not; '
    'unsure if the object is not visible or blurred. Last "confidence" from 0 to 1.'
)
LIVE_FINAL = "Answer for IMAGE LIVE."
_KEY_SETS = {1: ("DONE",), 2: ("START", "DONE"), 3: KEY_LABELS}
_NONE = ("none", "null", "nothing", "n/a", "")


def rubric_text(entry: dict) -> str:
    """The step's rubric as the model reads it. Deterministic, so it caches."""
    lines = [f"Step: {entry.get('title') or ''}", f"Question: {entry.get('question') or 'Is this step finished?'}",
             "Stages:"]
    lines += [f"{i}. {st.get('label', '')}: {st.get('cue', '')}" for i, st in enumerate(entry.get("stages") or [])]
    lines.append(f"Done cue: {entry.get('done_cue') or ''}")
    mistakes = entry.get("mistakes") or []
    lines.append("Mistakes:" if mistakes else "Mistakes: none listed")
    lines += [f"- {m['label']}: {m.get('sign', '')}" for m in mistakes]
    return "\n".join(lines)


def live_schema(entry: dict) -> dict:
    """Evidence first (seen, differs), then the verdicts. The mistake enum is the step's labels plus none, so
    an answer always maps back to a rubric mistake. No numeric bounds: enforced in parse_understanding."""
    labels = [m["label"] for m in entry.get("mistakes") or []]
    props = {
        "seen": {"type": "string", "description": "At most 8 words on LIVE: outline, orientation, visible parts"},
        "differs": {"type": "string", "description": 'At most 8 words on what LIVE lacks compared with DONE, or "nothing"'},
        "stage": {"type": "integer", "description": "latest visible stage number, or -1"},
        "progress": {"type": "number", "description": "0 to 1"},
        "mistake": {"type": "string", "enum": [*labels, "none"], "description": "a listed mistake label, or none"},
        "mistake_confidence": {"type": "number", "description": "0 to 1"},
        "done": {"type": "string", "enum": ["yes", "no", "unsure"], "description": "yes, no, or unsure"},
        "confidence": {"type": "number", "description": "0 to 1"},
    }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def live_content(entry: dict, keyframes: list[bytes], live_jpeg: bytes, prev_step_ref: Optional[bytes],
                 cache: Optional[bool] = None) -> list[dict]:
    """Rubric text, BEFORE, START, MID, DONE (cache breakpoint on the last of these), then LIVE and the final
    line. Everything before LIVE repeats for every frame of a step, so later calls read it from the cache."""
    if not keyframes:
        raise ValueError("understand_frame needs at least one keyframe (DONE)")
    labels = _KEY_SETS.get(len(keyframes))
    if labels is None:
        raise ValueError("understand_frame takes at most 3 keyframes (START, MID, DONE)")
    content: list[dict] = [{"type": "text", "text": rubric_text(entry)}]
    # When START is the previous step's reference (sample_keyframes does that for static starts), BEFORE would
    # be the same picture twice: label START as both instead of paying for the copy.
    same = prev_step_ref is not None and labels[0] == "START" and prev_step_ref == keyframes[0]
    if prev_step_ref is not None and not same:
        content += [{"type": "text", "text": "IMAGE BEFORE: the end of the previous step"}, _image_block(prev_step_ref)]
    for label, jpeg in zip(labels, keyframes):
        text = "IMAGE START (also BEFORE: the end of the previous step)" if same and label == "START" else f"IMAGE {label}"
        content += [{"type": "text", "text": text}, _image_block(jpeg)]
    if check._cache_on() if cache is None else cache:
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}  # a copy: the memo stays clean
    live = check.downscale_jpeg(live_jpeg, check._max_side(), check.CLAUDE_JPEG_QUALITY)
    content += [{"type": "text", "text": "IMAGE LIVE: the camera now"}, check._claude_image(live),
                {"type": "text", "text": LIVE_FINAL}]
    return content


def live_request(model: str, content: list[dict], schema: dict, secs: float) -> dict:
    """Same shape rules as check.py: JSON schema output at effort low, thinking off where the model allows it,
    no streaming, and no temperature, top_p or top_k (API version 2026-10-21 rejects them)."""
    off = _thinking_off(model)
    req: dict = {
        "model": model,
        "max_tokens": LIVE_MAX_TOKENS if off else LIVE_THINKING_MAX_TOKENS,
        "system": [{"type": "text", "text": UNDERSTAND_SYSTEM}],
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        "timeout": secs,
    }
    if off:
        req["thinking"] = {"type": "disabled"}
    return req


def parse_understanding(text: str, entry: dict) -> dict:
    """Validate the JSON answer with check.py's guards, then the new fields.

    check._parse_answer: lowercase done, confidence clamped, and a yes below HANDOVER_MIN_CONF becomes unsure
    (a confident yes stays yes even when differs names something). Here: stage outside -1..len(stages)-1 becomes -1, progress and mistake_confidence are clamped, the
    mistake label is matched case-insensitively to the rubric (anything else is no mistake), a mistake at stage
    -1 is dropped (the model sometimes names "not started yet" as a mistake), and yes together
    with a named mistake becomes unsure: never advance on a contradiction."""
    done, conf, reason = check._parse_answer(text)
    data = json.loads(text)
    n_stages = len(entry.get("stages") or [])
    stage = int(_num(data.get("stage"), -1)) if isinstance(data.get("stage"), (int, float)) else -1
    if not -1 <= stage < n_stages:
        stage = -1
    labels = {m["label"].lower(): m["label"] for m in entry.get("mistakes") or []}
    raw = str(data.get("mistake") or "").strip().lower()
    mistake = None if raw in _NONE or stage == -1 else labels.get(raw)  # an unstarted step is not a mistake
    m_conf = _clamp01(data.get("mistake_confidence")) if mistake else 0.0
    if done == "yes" and mistake is not None:
        done = "unsure"
    seen = _words(data.get("seen"), WORDS_SEEN) or None
    return {"done": done, "confidence": conf, "reason": reason, "stage": stage,
            "progress": _clamp01(data.get("progress")), "mistake": mistake, "mistake_confidence": m_conf, "seen": seen}


async def _mock_understand(entry: dict, keyframes: list[bytes], step_started_at: Optional[float]) -> Understanding:
    """HANDOVER_CHECK=mock: check.py's mock verdict, mapped onto the last stage (yes) or not started (no)."""
    r = await check._mock_check(keyframes[-1], step_started_at)
    last = max(0, len(entry.get("stages") or []) - 1)
    yes = r.done == "yes"
    return Understanding(r.done, r.confidence, r.latency_ms, stage=last if yes else -1, progress=1.0 if yes else 0.0)


async def understand_frame(step_rubric: dict, keyframes: list[bytes], live_jpeg: bytes,
                           prev_step_ref: Optional[bytes], *, timeout: Optional[float] = None,
                           model: Optional[str] = None, step_started_at: Optional[float] = None) -> Understanding:
    """One Claude call: where is LIVE inside this step? Never raises. Any failure gives done unsure,
    confidence 0 and an error class the Breaker understands (timeout, rate_limited, error, no_key, budget).

    step_rubric is one entry of rubric.json (step_entry). keyframes are START, MID, DONE (read_keyframes; one or
    two also work: DONE, or START and DONE). prev_step_ref is the previous step's reference, shown as BEFORE.
    timeout overrides HANDOVER_UNDERSTAND_TIMEOUT and model HANDOVER_UNDERSTAND_MODEL for this call only.
    step_started_at matters only in mock mode, as in check_frame."""
    if check.is_mock():
        return await _mock_understand(step_rubric, keyframes, step_started_at)
    if not _has_key():
        return Understanding("unsure", 0.0, 0, error="no_key")
    if not spend.allow():
        return Understanding("unsure", 0.0, 0, error="budget")  # no call made
    check._load_sdk("claude")
    name = model_name(model)
    t0 = time.monotonic()
    secs, usd, cached = 0.0, 0.0, 0
    try:
        secs = _timeout(timeout)
        content = await asyncio.to_thread(live_content, step_rubric, keyframes, live_jpeg, prev_step_ref)
        req = live_request(name, content, live_schema(step_rubric), secs)
        resp = await asyncio.wait_for(_client().messages.create(**req), secs + check.TIMEOUT_GRACE)
        text, usd = check._claude_text(resp, name)
        cached = int(getattr(getattr(resp, "usage", None), "cache_read_input_tokens", 0) or 0)
        try:
            got = parse_understanding(text, step_rubric)
        except Exception as e:
            raise check._CheckFailure("error", f"unparseable answer: {type(e).__name__}", usd) from e
    except Exception as e:  # timeout, network, quota, refusal, truncation, bad JSON, bad image
        err = check.classify_error(e)
        check._log_failure("understand", err, e, secs)
        ms = int((time.monotonic() - t0) * 1000)
        return Understanding("unsure", 0.0, ms, error=err, cost_usd=getattr(e, "cost_usd", usd))
    ms = int((time.monotonic() - t0) * 1000)
    return Understanding(got["done"], got["confidence"], ms, got["reason"], None, usd, cached,
                         stage=got["stage"], progress=got["progress"], mistake=got["mistake"],
                         mistake_confidence=got["mistake_confidence"], seen=got["seen"])


# ---------------------------------------------------------------- live mistake policy

class MistakeTracker:
    """When an understanding result becomes a live mistake warning. Pure: the caller passes the time.

    Fires when the same mistake label comes back in `repeat` results in a row, each at confidence >= min_conf.
    The warning stays active until the stage advances past the stage it fired at, or the label is missing from
    `clear_after` results in a row, or the step changes. A label fires at most once per `cooldown_s` (per step).
    Failed results (error set) are skipped: they say nothing about the paper.

        tracker.start_step(step, entry)            on every step change (entry may be None)
        msg = tracker.feed(result, now)            the contract message when it fires, else None
        tracker.active                             the message currently shown, or None once cleared
    """

    def __init__(self, min_conf: Optional[float] = None, repeat: Optional[int] = None,
                 clear_after: Optional[int] = None, cooldown_s: Optional[float] = None, source: str = "claude"):
        self.min_conf = float(min_conf if min_conf is not None else setting("HANDOVER_LIVE_MISTAKE_MIN_CONF"))
        self.repeat = int(repeat if repeat is not None else setting("HANDOVER_LIVE_MISTAKE_REPEAT"))
        self.clear_after = int(clear_after if clear_after is not None else setting("HANDOVER_LIVE_MISTAKE_CLEAR"))
        self.cooldown_s = float(cooldown_s if cooldown_s is not None else setting("HANDOVER_LIVE_MISTAKE_COOLDOWN_S"))
        self.source = source
        self.step: Optional[int] = None
        self.active: Optional[dict] = None
        self._entry: Optional[dict] = None
        self._hints: dict[str, str] = {}
        self._label: Optional[str] = None
        self._count = 0
        self._absent = 0
        self._fired_stage = -1
        self._last_fire: dict[tuple[int, str], float] = {}  # kept across step changes

    def start_step(self, step: int, entry: Optional[dict]) -> None:
        self.step, self._entry = step, entry
        self.active = None
        self._hints = {m["label"]: m.get("hint") or "" for m in (entry or {}).get("mistakes") or []}
        self._label, self._count, self._absent, self._fired_stage = None, 0, 0, -1

    def reset(self) -> None:
        """Drop the streak and the active warning, keep the step and the cooldowns (e.g. on dismiss_mistake)."""
        if self.step is not None:
            self.start_step(self.step, self._entry)

    def feed(self, result: Any, now: float) -> Optional[dict]:
        if self.step is None or getattr(result, "error", None):
            return None
        label = getattr(result, "mistake", None)
        conf = float(getattr(result, "mistake_confidence", 0.0) or 0.0)
        stage = int(getattr(result, "stage", -1))
        if label is not None and (conf < self.min_conf or label not in self._hints):
            label = None
        # streak of the same confident label
        if label is not None and label == self._label:
            self._count += 1
        else:
            self._label, self._count = label, (1 if label is not None else 0)
        # clearing the active warning
        if self.active is not None:
            if stage > self._fired_stage:
                self.active = None
            elif label == self.active["label"]:
                self._absent = 0
            else:
                self._absent += 1
                if self._absent >= self.clear_after:
                    self.active = None
        if label is None or self._count < self.repeat:
            return None
        if self.active is not None and self.active["label"] == label:
            return None
        last = self._last_fire.get((self.step, label))
        if last is not None and now - last < self.cooldown_s:
            return None
        self._last_fire[(self.step, label)] = now
        self._fired_stage, self._absent = stage, 0
        msg = {"type": "mistake", "step": self.step, "kind": "live", "label": label,
               "message": self._hints.get(label) or label, "confidence": round(conf, 3), "source": self.source}
        self.active = msg
        return msg


# ---------------------------------------------------------------- CLI

def _main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.understand")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rubric", type=Path, metavar="LESSON_DIR", help="build rubric.json for a lesson folder")
    g.add_argument("--live", nargs=3, metavar=("LESSON_DIR", "STEP_N", "LIVE_JPG"),
                   help="run understand_frame on one image against the lesson's rubric")
    ap.add_argument("--model", default=None, help="override HANDOVER_UNDERSTAND_MODEL")
    ap.add_argument("--keep-frames", action="store_true", help="--rubric: keep existing NN_a/b/c.jpg keyframes")
    ap.add_argument("-n", type=int, default=1, help="--live: number of calls")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if not spend.allow():
        print(spend.report())
        print("Refusing to run: the Claude budget is exhausted.")
        return 2
    if a.rubric:
        lesson_dir = a.rubric.resolve()
        try:
            rubric = asyncio.run(build_rubric(lesson_dir, model=a.model, resample=not a.keep_frames,
                                              progress=lambda s, m: print(f"[{s}] {m}", flush=True)))
        except RuntimeError as e:
            print(f"error: {e}")
            return 1
        for s in rubric["steps"]:
            stages = " > ".join(st["label"] for st in s["stages"])
            mistakes = "; ".join(f"{m['label']} ({m['severity']}): {m['hint']}" for m in s["mistakes"])
            print(f"step {s['n']}: {stages}\n  done: {s['done_cue']}\n  mistakes: {mistakes}\n  region: {s['region']}")
        print(f"wrote {lesson_dir / RUBRIC_FILE}  cost ${rubric['cost_usd']:.4f}")
        return 0
    lesson_dir, n, live = Path(a.live[0]).resolve(), int(a.live[1]), Path(a.live[2])
    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    rubric = load_rubric(lesson_dir, lesson)
    entry = step_entry(rubric, n)
    if entry is None:
        print(f"no current rubric entry for step {n}: run --rubric {lesson_dir} first")
        return 1
    steps = lesson.get("steps") or []
    idx = next(i for i, s in enumerate(steps) if int(s.get("n", 0)) == n)
    prev = None
    if idx > 0:
        prev = _read(lesson_dir / (steps[idx - 1].get("ref_frame") or f"frames/{n - 1:02d}.jpg"))

    async def run() -> None:
        for i in range(max(1, a.n)):
            u = await understand_frame(entry, read_keyframes(lesson_dir, entry), live.read_bytes(), prev, model=a.model)
            print(f"{i + 1:3d}  {u.done:6s} {u.confidence:.2f}  stage {u.stage}  progress {u.progress:.2f}  "
                  f"mistake {u.mistake} {u.mistake_confidence:.2f}  {u.latency_ms} ms  ${u.cost_usd:.6f}  "
                  f"cache_read {u.cache_read_tokens}  {u.error or ''}  seen: {u.seen}  differs: {u.reason}", flush=True)

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

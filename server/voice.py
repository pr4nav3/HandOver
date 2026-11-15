"""Automatic voiceover: a calm spoken narration for lessons whose expert said little or nothing.

Three parts, each usable on its own:

1. write_script(steps, transcript, frames_by_step): one Claude call per lesson (structured output) writes 1 to 3
   short spoken sentences per step that fit the clip (about 2.5 words per second). Guarded by server/spend.py.
2. speak(text, out_wav): Kokoro, an open-source neural voice (Apache 2.0), run on the CPU through kokoro-onnx
   (macOS and Windows; espeak-ng comes from the espeakng-loader wheel). The model files download once into
   ~/.cache/handover/kokoro. Falls back to macOS `say` (Mac only), and on total failure returns 0 instead of
   raising, so a lesson build never crashes on speech.
3. apply_voiceover(lesson_dir, scripts, mode): mixes the voice into clips/NN.mp4 (the original audio ducked to
   about -18 dB in "duck", dropped in "replace"), writes captions/NN.vtt timed from each synthesized sentence,
   keeps clips/NN.orig.mp4 and captions/NN.orig.vtt so undo() can put everything back, and records a top-level
   "voiceover" field in lesson.json.

needs_voiceover(transcript, steps) says whether the narration is too thin; should_voiceover adds the
HANDOVER_VOICEOVER setting (auto, always, off).

    python -m server.voice lessons/<id> [--mode duck|replace|auto] [--voice af_heart] [--dry-run] [--undo]
                                        [--script voice.json]
    python -m server.voice --cues web/public/voice [--voice af_heart]
    python -m server.voice --audition "TEXT" --voices af_heart,af_bella --out DIR [--speed 0.95]

--mode auto replaces the take's audio when its narration is unusable (needs_voiceover), else ducks it.
--script FILE takes hand-written lines, {"steps": {"1": "line", "2": "line"}} with 1-based step numbers; a step
not in the file gets Claude's script (or its title with HANDOVER_NO_NETWORK=1). A line over the clip's word limit
is kept and the overflow printed. lesson.json's voiceover field records each step's script_source.
--cues FOLDER renders the Learn screen's spoken cues (APP_CUES) as small mono mp3 files with the lesson voice.
--audition renders TEXT once per Kokoro voice to DIR/<voice>.mp3, to pick a voice by ear (no network).

Speech provider: HANDOVER_TTS_PROVIDER=kokoro (default) or elevenlabs. elevenlabs needs ELEVENLABS_API_KEY (environment
or <repo>/.env, never printed) and uses HANDOVER_ELEVEN_VOICE (default Sarah) and HANDOVER_ELEVEN_MODEL (default
eleven_multilingual_v2); a missing key, HANDOVER_NO_NETWORK=1 or a failed call logs one line and uses Kokoro.

Settings: HANDOVER_VOICE_SCRIPT_MODEL (default claude-haiku-5-5), HANDOVER_VOICE (default af_heart),
HANDOVER_VOICE_SPEED (default 0.95), HANDOVER_VOICEOVER (default auto). ANTHROPIC_API_KEY comes from the
environment or <repo>/.env and is never printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
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
import threading
import urllib.request
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from server import config

log = logging.getLogger("handover.voice")

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- settings

# Defaults used until these names are in config.REGISTRY; once registered, config.get wins.
_SETTINGS: dict[str, tuple[str, Any, tuple]] = {
    "HANDOVER_VOICE_SCRIPT_MODEL": ("str", "claude-haiku-5-5", ()),
    "HANDOVER_VOICE": ("str", "af_heart", ()),
    "HANDOVER_VOICE_SPEED": ("float", 1.0, (0.7, 1.3)),
    "HANDOVER_VOICEOVER": ("choice", "auto", ("auto", "always", "off")),
    "HANDOVER_TTS_PROVIDER": ("choice", "kokoro", ("kokoro", "elevenlabs")),
    "HANDOVER_ELEVEN_VOICE": ("str", "EXAVITQu4vr4xnSDxMaL", ()),
    "HANDOVER_ELEVEN_MODEL": ("choice", "eleven_multilingual_v2", ("eleven_multilingual_v2", "eleven_turbo_v2_5")),
}
DEFAULT_SPEED = 0.95  # a touch slower than Kokoro's own pace: calmer, and easier to follow over a clip


def _setting(name: str):
    try:
        return config.get(name)
    except KeyError:
        kind, default, extra = _SETTINGS[name]
        if kind == "float":
            return config.env_float(name, default, *extra)
        if kind == "choice":
            return config.env_choice(name, default, extra)
        return config.env_str(name, default)


def script_model() -> str:
    return str(_setting("HANDOVER_VOICE_SCRIPT_MODEL"))


def default_voice() -> str:
    return str(_setting("HANDOVER_VOICE"))


def default_speed() -> float:
    # Read here, not through config.get, so the default is this module's DEFAULT_SPEED with the registry's bounds.
    return float(config.env_float("HANDOVER_VOICE_SPEED", DEFAULT_SPEED, 0.7, 1.3))


def tts_provider() -> str:
    return str(_setting("HANDOVER_TTS_PROVIDER"))


def eleven_voice() -> str:
    return str(_setting("HANDOVER_ELEVEN_VOICE"))


def eleven_model() -> str:
    return str(_setting("HANDOVER_ELEVEN_MODEL"))


def voiceover_setting() -> str:
    return str(_setting("HANDOVER_VOICEOVER"))


# ---------------------------------------------------------------- small helpers

WORDS_PER_SECOND = 2.5
LEAD_S = 0.4  # silence before the first sentence
TAIL_S = 0.3  # silence kept free at the end of the clip
GAP_S = 0.35  # pause between sentences, so a line breathes
SAMPLE_RATE = 24000  # Kokoro's rate; `say` output is resampled to match
DUCK_DB = -18
VOICE_LUFS = -16  # common loudness target for spoken audio on phones and the web


class VoiceError(RuntimeError):
    """The script could not be written (no key, budget reached, bad answer). Speech never raises this."""


class BudgetExceeded(VoiceError):
    pass


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Steps and segments may be dicts (lesson.json) or objects (teach.py's pydantic models)."""
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def parse_time(value: Any) -> float:
    """Seconds from a number or an "SS", "MM:SS" or "HH:MM:SS" string (fractions allowed)."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    for part in str(value).strip().split(":"):
        total = total * 60 + float(part)
    return total


def fmt_vtt(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


_DASHES = re.compile("\\s*[\u2012\u2013\u2014\u2015\u2212]\\s*|\\s+-{1,3}\\s+")
_IN_THIS_STEP = re.compile(r"^(in this step|in this clip|here|now|okay|ok|so)\s*,?\s+", re.I)


def clean_sentence(text: str) -> str:
    """One spoken sentence: no em or en dashes, no filler opener, single spaces, ends with punctuation."""
    text = _DASHES.sub(", ", str(text)).replace("-->", "to")
    text = " ".join(text.split()).strip(" ,")
    text = _IN_THIS_STEP.sub("", text)
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(str(text).split()))
    return [s for s in (clean_sentence(p) for p in parts) if s]


def _words(text: str) -> int:
    return len(str(text).split())


def word_budget(seconds: float) -> int:
    """Words that fit a clip at a calm pace, leaving the lead-in and tail free."""
    return max(4, int((seconds - LEAD_S - TAIL_S) * WORDS_PER_SECOND))


MAX_STEP_WORDS = 22  # a long clip is not a reason to talk more: the learner is watching hands, not listening


def word_limit(seconds: float) -> int:
    """word_budget, capped at MAX_STEP_WORDS: what the script writer is asked for and held to."""
    return min(word_budget(seconds), MAX_STEP_WORDS)


def step_seconds(step: Any) -> float:
    return max(0.0, parse_time(_get(step, "end")) - parse_time(_get(step, "start")))


# ---------------------------------------------------------------- 4. decision

def needs_voiceover(transcript: Sequence[Any], steps: Sequence[Any]) -> bool:
    """True when the expert's narration is unusable: empty, covering under 40% of the step time, or under
    3 words per step on average."""
    lines = [s for s in (transcript or []) if str(_get(s, "text", "")).strip()]
    if not lines or not steps:
        return True
    words = sum(_words(_get(s, "text", "")) for s in lines)
    if words / len(steps) < 3:
        return True
    spans = sorted((parse_time(_get(s, "start")), parse_time(_get(s, "end"))) for s in lines)
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    step_total = covered = 0.0
    for st in steps:
        a, b = parse_time(_get(st, "start")), parse_time(_get(st, "end"))
        step_total += max(0.0, b - a)
        covered += sum(max(0.0, min(b, y) - max(a, x)) for x, y in merged)
    return step_total <= 0 or covered / step_total < 0.4


def should_voiceover(transcript: Sequence[Any], steps: Sequence[Any]) -> bool:
    """needs_voiceover, overridden by HANDOVER_VOICEOVER: always or off."""
    mode = voiceover_setting()
    if mode == "off":
        return False
    return mode == "always" or needs_voiceover(transcript, steps)


# ---------------------------------------------------------------- 1. script writer

@dataclass
class StepScript:
    n: int
    title: str
    seconds: float  # clip length the narration must fit
    sentences: list[str] = field(default_factory=list)
    source: str = "claude"  # where the lines came from: claude, file (hand-written --script) or title (fallback)
    times: list[Optional[float]] = field(default_factory=list)  # per sentence: start on the clip's clock, or None

    def time_at(self, i: int) -> Optional[float]:
        return self.times[i] if i < len(self.times) else None

    @property
    def narration(self) -> str:
        return " ".join(self.sentences)

    def to_dict(self) -> dict:
        out = {"n": self.n, "title": self.title, "seconds": round(self.seconds, 2), "sentences": self.sentences,
               "source": self.source}
        if any(t is not None for t in self.times):
            out["times"] = self.times
        return out


SYSTEM = """You write the voiceover for short how-to video clips. A calm, friendly person will read each line
aloud while the learner watches the clip and copies the expert's hands.

For each step write 1 or 2 short spoken sentences, usually 8 to 18 words in all, never more than 22:
- Calm, plain and concrete, second person, with the quiet warmth of a calm coach standing next to the learner.
  Contractions are welcome (you're, it's, don't). No exclamation marks, no praise words ("great job", "perfect",
  "awesome").
- First sentence: the physical action you can see in the frames, concretely (which edge or corner goes where,
  what to press or flip), not a vague restatement of the title.
- Optional second sentence: the one thing to watch for (use the common mistake when one is given, phrased as
  what to do), or what the paper should look like when the step is done, stated plainly.
- "Done when" lines are for you, not to be read out. Never ask the learner a question, never say "check that"
  or "make sure you now have", never recite the finished state as a test.
- Stay within the step's word limit; fewer words is better. Never pad a long clip with extra sentences.
- No filler and no openers like "In this step", "Now", "Here we", "Okay", "Next". No step numbers.
- No dashes of any kind, no lists, no emoji, no quotes. Plain sentences that sound natural spoken aloud.
- If the expert's own words are given, keep their meaning and any specific detail, but make them clear.
- When the title and the frames disagree, describe what the frames show.
- Do not invent tools, amounts or facts you cannot see or read."""

SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "sentences": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["n", "sentences"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["steps"],
    "additionalProperties": False,
}

FRAME_SIDE = 512
MAX_FRAMES_PER_STEP = 2
last_cost_usd = 0.0  # cost of the most recent write_script call, for the CLI report


def _read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    path = REPO / ".env"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def _anthropic_key() -> Optional[str]:
    return os.environ.get("ANTHROPIC_API_KEY") or _read_env_file().get("ANTHROPIC_API_KEY") or None


def _jpeg_b64(frame: Any) -> Optional[str]:
    """A path or raw bytes, shrunk so the long side is 512 px, as base64 JPEG. None if unreadable."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(frame) if isinstance(frame, (bytes, bytearray)) else frame)
        img = img.convert("RGB")
        img.thumbnail((FRAME_SIDE, FRAME_SIDE))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii")
    except (OSError, ValueError) as e:
        log.warning("voiceover: skipping a frame that could not be read (%s)", type(e).__name__)
        return None


def _frames_for(frames_by_step: Any, index: int, n: int) -> list:
    if not frames_by_step:
        return []
    if isinstance(frames_by_step, Mapping):
        got = frames_by_step.get(n, frames_by_step.get(str(n), []))
    else:
        got = frames_by_step[index] if index < len(frames_by_step) else []
    if isinstance(got, (str, Path, bytes, bytearray)):
        got = [got]
    return list(got or [])[:MAX_FRAMES_PER_STEP]


def fallback_scripts(steps: Sequence[Any], clip_seconds: Optional[Sequence[float]] = None) -> list[StepScript]:
    """A plain narration from each step's title and common mistake, for when Claude cannot be used."""
    out = []
    for i, st in enumerate(steps):
        seconds = clip_seconds[i] if clip_seconds and i < len(clip_seconds) else step_seconds(st)
        n = int(_get(st, "n", i + 1) or i + 1)
        title = str(_get(st, "title", "") or f"Step {n}")
        sentences = split_sentences(title)
        mistake = str(_get(st, "common_mistake", "") or "").strip()
        if mistake:
            sentences += split_sentences(mistake)
        out.append(StepScript(n, title, seconds, _fit_words(sentences, word_limit(seconds)), "title"))
    return out


TimedLines = list[tuple[Optional[float], str]]  # (start on the clip's clock or None, text)


def _read_script_json(path: Path) -> Mapping:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cannot read the script file {path}: {type(e).__name__}") from None
    steps = data.get("steps") if isinstance(data, Mapping) else None
    if not isinstance(steps, Mapping):
        raise ValueError('the script file needs {"steps": {"1": "line", ...}}')
    return data


def _timed_line(n: int, item: Any) -> Optional[tuple[Optional[float], str]]:
    """One entry of a step's list: {"at": 3.5, "text": "..."}, [3.5, "..."] or a plain string."""
    at: Optional[float] = None
    if isinstance(item, Mapping):
        text, raw = item.get("text"), item.get("at")
    elif isinstance(item, (list, tuple)) and len(item) == 2:
        raw, text = item
    else:
        text, raw = item, None
    if raw is not None:
        try:
            at = float(parse_time(raw))
        except (TypeError, ValueError):
            raise ValueError(f"step {n} in the script file: bad time {raw!r}") from None
        if at < 0:
            raise ValueError(f"step {n} in the script file: time {raw!r} is negative")
    line = " ".join(str(text if text is not None else "").split())
    return (at, line) if line else None


def load_script_file(path: Path) -> dict[int, Union[str, TimedLines]]:
    """Hand-written lines from {"steps": {"1": "line", ...}} (1-based step numbers). A step may instead be a list
    of timed lines, [{"at": 3.5, "text": "..."}, ...] (seconds into the clip, or "m:ss"); a line without "at"
    follows the one before it. Raises ValueError."""
    steps = _read_script_json(path)["steps"]
    out: dict[int, Union[str, TimedLines]] = {}
    for k, v in steps.items():
        try:
            n = int(str(k).strip())
        except ValueError:
            raise ValueError(f"step key {k!r} in the script file is not a number") from None
        if n < 1:
            raise ValueError(f"step {n} in the script file: steps are numbered from 1")
        if isinstance(v, (list, tuple)):
            items = [t for t in (_timed_line(n, it) for it in v) if t]
            if items:
                out[n] = items
            continue
        line = " ".join(str(v if v is not None else "").split())
        if line:
            out[n] = line
    return out


def script_file_speed(path: Path) -> Optional[float]:
    """The speaking speed the script file asks for ("speed": 0.9), within the registry's bounds, or None."""
    raw = _read_script_json(path).get("speed")
    if raw is None:
        return None
    try:
        speed = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"the script file's speed {raw!r} is not a number") from None
    if not 0.7 <= speed <= 1.3:
        raise ValueError(f"the script file's speed {speed} is outside 0.7 to 1.3")
    return speed


def file_scripts(steps: Sequence[Any], lines: Mapping[int, Union[str, TimedLines]],
                 clip_seconds: Optional[Sequence[float]] = None, warn=print) -> list[Optional[StepScript]]:
    """Per step, a StepScript from the hand-written line, or None when the file has no line for it. A line over
    the clip's word limit is kept whole; warn() gets the overflow so it is never trimmed silently. Timed lines
    keep their times (each entry is spoken as one piece, at its moment); a time past the clip is reported."""
    out: list[Optional[StepScript]] = []
    for i, st in enumerate(steps):
        n = int(_get(st, "n", i + 1) or i + 1)
        if n not in lines:
            out.append(None)
            continue
        seconds = clip_seconds[i] if clip_seconds and i < len(clip_seconds) else step_seconds(st)
        value = lines[n]
        times: list[Optional[float]] = []
        if isinstance(value, str):
            sentences = split_sentences(value)
        else:
            sentences = [clean_sentence(text) for _, text in value]
            times = [at for at, _ in value]
            for at in times:
                if at is not None and at > seconds - TAIL_S:
                    warn(f"warning: step {n} has a line at {at:.1f}s but its clip is {seconds:.1f}s long")
        limit, words = word_limit(seconds), " ".join(sentences).split()
        if len(words) > limit and not times:
            warn(f"warning: step {n} line is {len(words)} words, over its limit of {limit} for a {seconds:.1f}s "
                 f"clip; kept whole. Over by: {' '.join(words[limit:])}")
        out.append(StepScript(n, str(_get(st, "title", "") or f"Step {n}"), seconds, sentences, "file", times))
    return out


def _fit_words(sentences: list[str], budget: int) -> list[str]:
    """Drop trailing sentences until the narration fits the word budget; the first sentence always stays."""
    kept: list[str] = []
    for s in sentences[:3]:
        if kept and _words(" ".join(kept + [s])) > budget:
            break
        kept.append(s)
    return kept


def _build_content(steps: Sequence[Any], transcript: Sequence[Any], frames_by_step: Any,
                   seconds: list[float]) -> list[dict]:
    content: list[dict] = []
    lines = [s for s in (transcript or []) if str(_get(s, "text", "")).strip()]
    if lines:
        text = "\n".join(f"[{parse_time(_get(s, 'start')):.1f}s to {parse_time(_get(s, 'end')):.1f}s] "
                         f"{' '.join(str(_get(s, 'text')).split())}" for s in lines)
        content.append({"type": "text", "text": "The expert's own words, from a speech model (may be partial or "
                                                "unclear), on the same clock as the step times:\n" + text})
    for i, st in enumerate(steps):
        n = int(_get(st, "n", i + 1) or i + 1)
        parts = [f"Step {n}: {_get(st, 'title', '')}",
                 f"Time in the video: {parse_time(_get(st, 'start')):.1f}s to {parse_time(_get(st, 'end')):.1f}s",
                 f"Clip length: {seconds[i]:.1f} seconds, so at most {word_limit(seconds[i])} words"]
        question = str(_get(st, "check_question", "") or "").strip()
        if question and question != "manual" and _get(st, "check_type") != "manual":
            parts.append(f"Done when: {question}")
        mistake = str(_get(st, "common_mistake", "") or "").strip()
        if mistake:
            parts.append(f"Common mistake: {mistake}")
        content.append({"type": "text", "text": "\n".join(parts)})
        for frame in _frames_for(frames_by_step, i, n):
            data = _jpeg_b64(frame)
            if data:
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text": f"Write the voiceover for all {len(steps)} steps, one entry per step "
                                            "with its step number n."})
    return content


def _spend():
    from server import spend  # owned by the check builder; imported late so tests can swap the ledger

    return spend


def write_script(steps: Sequence[Any], transcript: Sequence[Any] = (), frames_by_step: Any = None, *,
                 clip_seconds: Optional[Sequence[float]] = None, client: Any = None,
                 model: Optional[str] = None) -> list[StepScript]:
    """One Claude call writes every step's narration. steps are lesson.json dicts or teach.Step objects;
    transcript is segments with start, end (seconds or "MM:SS") and text; frames_by_step is a list (by step
    index) or a dict (by step n) of 1 to 2 image paths or bytes per step. clip_seconds overrides each step's
    end minus start. Raises BudgetExceeded when over the Claude budget and VoiceError on other failures."""
    global last_cost_usd
    steps = list(steps)
    if not steps:
        return []
    seconds = [float(clip_seconds[i]) if clip_seconds and i < len(clip_seconds) else step_seconds(st)
               for i, st in enumerate(steps)]
    model = model or script_model()
    spend = _spend()
    if not spend.allow():
        raise BudgetExceeded("the Claude budget is used up (see python -m server.spend); no voiceover script "
                             "was written")
    if client is None:
        import anthropic

        key = _anthropic_key()
        if not key:
            raise VoiceError("no Claude key: set ANTHROPIC_API_KEY or add it to .env at the repo root")
        client = anthropic.Anthropic(api_key=key, timeout=90.0, max_retries=2)

    content = _build_content(steps, transcript, frames_by_step, seconds)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except Exception as e:  # the SDK's errors all derive from anthropic.APIError; keep the message short
        raise VoiceError(f"Claude call for the voiceover script failed: {type(e).__name__}") from None
    usage = getattr(response, "usage", None)
    if usage is not None:
        last_cost_usd = spend.record(model, usage)
    stop = getattr(response, "stop_reason", None)
    if stop in ("refusal", "max_tokens"):
        raise VoiceError(f"Claude did not finish the voiceover script (stop reason {stop})")
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        got = {int(item["n"]): item.get("sentences") or [] for item in json.loads(text)["steps"]}
    except (ValueError, KeyError, TypeError) as e:
        raise VoiceError(f"Claude's voiceover script was not valid JSON ({type(e).__name__})") from None

    fallback = fallback_scripts(steps, seconds)
    out = []
    for i, st in enumerate(steps):
        n = int(_get(st, "n", i + 1) or i + 1)
        sentences = [c for s in got.get(n, []) for c in split_sentences(str(s))]
        sentences = _fit_words(sentences, word_limit(seconds[i])) if sentences else fallback[i].sentences
        if n not in got:
            log.warning("voiceover: Claude skipped step %d; using its title", n)
        out.append(StepScript(n, str(_get(st, "title", "") or f"Step {n}"), seconds[i], sentences))
    return out


# ---------------------------------------------------------------- 2. speech

KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
KOKORO_MODEL = "kokoro-v1.0.onnx"
KOKORO_VOICES = "voices-v1.0.bin"
KOKORO_FILES = {  # name: (bytes, sha256), from the release's asset list
    KOKORO_MODEL: (325505369, "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"),
    KOKORO_VOICES: (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}
KOKORO_DIR = Path.home() / ".cache" / "handover" / "kokoro"
FALLBACK_VOICE = "af_heart"

_kokoro = None
_kokoro_lock = threading.Lock()
_kokoro_failed: Optional[str] = None


def _download(name: str, dest: Path) -> None:
    size, digest = KOKORO_FILES[name]
    part = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    with urllib.request.urlopen(KOKORO_URL + name, timeout=60) as r, open(part, "wb") as f:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    if part.stat().st_size != size or h.hexdigest() != digest:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{name} download did not match its published size and checksum")
    os.replace(part, dest)


def ensure_kokoro_files(folder: Optional[Path] = None) -> tuple[Path, Path]:
    """The Kokoro model and voices files, downloaded once and checked against the published sizes."""
    folder = Path(folder or KOKORO_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    missing = [n for n, (size, _) in KOKORO_FILES.items()
               if not (folder / n).is_file() or (folder / n).stat().st_size != size]
    if missing:
        mb = sum(KOKORO_FILES[n][0] for n in missing) / 1e6
        print(f"downloading voice model once, about {mb:.0f} MB", flush=True)
        for n in missing:
            _download(n, folder / n)
    return folder / KOKORO_MODEL, folder / KOKORO_VOICES


def _load_kokoro():
    global _kokoro, _kokoro_failed
    with _kokoro_lock:
        if _kokoro is None and _kokoro_failed is None:
            try:
                from kokoro_onnx import Kokoro

                # phonemizer warns "words count mismatch" on most lines; it is harmless for whole sentences
                logging.getLogger("phonemizer").setLevel(logging.ERROR)
                model, voices = ensure_kokoro_files()
                _kokoro = Kokoro(str(model), str(voices))
            except Exception as e:  # missing package, no network, bad file: fall back to `say`
                _kokoro_failed = f"{type(e).__name__}: {e}"[:200]
                log.warning("voiceover: Kokoro unavailable (%s); %s", _kokoro_failed,
                            "using macOS say" if sys.platform == "darwin" else
                            "no other speech engine on this system, so no voice")
        return _kokoro


def _write_wav(path: Path, samples, rate: int = SAMPLE_RATE) -> float:
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return len(pcm) / rate


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _speak_kokoro(text: str, out_wav: Path, voice: str, speed: float) -> tuple[float, str]:
    k = _load_kokoro()
    if k is None:
        raise RuntimeError("Kokoro unavailable")
    if voice not in k.get_voices():
        log.warning("voiceover: Kokoro has no voice %r; using %s", voice, FALLBACK_VOICE)
        voice = FALLBACK_VOICE
    samples, rate = k.create(text, voice=voice, speed=speed, lang="en-us")
    seconds = _write_wav(out_wav, samples, rate)
    if seconds <= 0:
        raise RuntimeError("Kokoro returned no audio")
    return seconds, voice


_SAY_PREFERENCE = ("(Premium)", "(Enhanced)")
_SAY_NAMED = ("Samantha", "Ava", "Allison", "Tom", "Alex")


def best_say_voice() -> Optional[str]:
    """The most natural installed en_US voice for `say`: a Premium or Enhanced download first, then the
    standard Samantha family, else the system default (None)."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    voices = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}(\w\w_\w\w)\s", line)
        if m and m.group(2) == "en_US":
            voices.append(m.group(1).strip())
    for tag in _SAY_PREFERENCE:
        for v in voices:
            if tag in v:
                return v
    for name in _SAY_NAMED:
        if name in voices:
            return name
    return None


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    """ffmpeg or ffprobe, in the same order as teach.py: HANDOVER_FFMPEG, PATH, then Homebrew."""
    override = config.get("HANDOVER_FFMPEG")
    if override and Path(str(override)).is_file():
        p = Path(str(override))
        if name == "ffmpeg":
            return str(p)
        sibling = p.with_name(name + p.suffix)
        if sibling.is_file():
            return str(sibling)
    found = shutil.which(name) or (str(Path("/opt/homebrew/bin") / name)
                                   if (Path("/opt/homebrew/bin") / name).is_file() else None)
    if not found:
        raise RuntimeError(f"{name} not found on PATH")
    return found


def _speak_say(text: str, out_wav: Path, speed: float) -> tuple[float, str]:
    if sys.platform != "darwin" or not shutil.which("say"):
        raise RuntimeError("macOS say is not available on this system")
    voice = best_say_voice()
    with tempfile.TemporaryDirectory(prefix="handover-say-") as tmp:
        src, aiff = Path(tmp) / "text.txt", Path(tmp) / "out.aiff"
        src.write_text(text, encoding="utf-8")
        cmd = ["say", "-o", str(aiff), "-f", str(src)]
        if voice:
            cmd[1:1] = ["-v", voice]
        if abs(speed - 1.0) > 0.01:
            cmd[1:1] = ["-r", str(int(180 * speed))]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(aiff), "-ar", str(SAMPLE_RATE), "-ac", "1",
                        "-c:a", "pcm_s16le", str(out_wav)], check=True, capture_output=True, timeout=120)
    return wav_seconds(out_wav), voice or "default"


ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/"
ELEVEN_FORMAT = "mp3_44100_128"
ELEVEN_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.3}
_eleven_warned = False


def _eleven_key() -> Optional[str]:
    return os.environ.get("ELEVENLABS_API_KEY") or _read_env_file().get("ELEVENLABS_API_KEY") or None


def _eleven_post(url: str, body: dict, key: str) -> bytes:
    """The one HTTP call to ElevenLabs (urllib only). Tests replace this function."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _speak_eleven(text: str, out_wav: Path, speed: float) -> tuple[float, str]:
    """ElevenLabs text to speech, decoded to the same 24 kHz mono WAV as Kokoro. Raises on any failure."""
    if config.get("HANDOVER_NO_NETWORK"):
        raise RuntimeError("HANDOVER_NO_NETWORK=1")
    key = _eleven_key()
    if not key:
        raise RuntimeError("no ELEVENLABS_API_KEY")
    voice_id = eleven_voice()
    body = {"text": text, "model_id": eleven_model(),
            "voice_settings": {**ELEVEN_SETTINGS, "speed": round(min(1.2, max(0.7, speed)), 2)}}
    try:
        data = _eleven_post(f"{ELEVEN_URL}{voice_id}?output_format={ELEVEN_FORMAT}", body, key)
    except Exception as e:  # HTTPError, URLError, timeouts: never echo the request (it carries the key)
        code = getattr(e, "code", None)
        raise RuntimeError(f"ElevenLabs call failed ({type(e).__name__}{f' {code}' if code else ''})") from None
    if not data:
        raise RuntimeError("ElevenLabs returned no audio")
    mp3 = Path(out_wav).with_suffix(".eleven.mp3")
    try:
        mp3.write_bytes(data)
        p = subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(mp3), "-ar", str(SAMPLE_RATE), "-ac", "1",
                            "-c:a", "pcm_s16le", str(out_wav)], capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            raise RuntimeError("ElevenLabs audio could not be decoded")
    finally:
        mp3.unlink(missing_ok=True)
    seconds = wav_seconds(out_wav)
    if seconds <= 0:
        raise RuntimeError("ElevenLabs returned no audio")
    return seconds, voice_id


def synthesize(text: str, out_wav: Path, voice: Optional[str] = None,
               speed: Optional[float] = None) -> tuple[float, str, str]:
    """(seconds, engine, voice) for one text. engine is "elevenlabs", "kokoro", "say", or "" with 0 seconds on
    failure. HANDOVER_TTS_PROVIDER=elevenlabs tries ElevenLabs first; voice is then HANDOVER_ELEVEN_VOICE."""
    global _eleven_warned
    text = " ".join(clean_sentence(s) for s in split_sentences(text))
    out_wav = Path(out_wav)
    if not text:
        return 0.0, "", ""
    voice = voice or default_voice()
    speed = float(speed or default_speed())
    if tts_provider() == "elevenlabs":
        try:
            seconds, used = _speak_eleven(text, out_wav, speed)
            return seconds, "elevenlabs", used
        except Exception as e:
            if not _eleven_warned:
                _eleven_warned = True
                log.warning("voiceover: ElevenLabs not used (%s); using Kokoro", str(e)[:120])
    try:
        seconds, used = _speak_kokoro(text, out_wav, voice, speed)
        return seconds, "kokoro", used
    except Exception as e:
        if _kokoro_failed is None:
            log.warning("voiceover: Kokoro failed (%s); trying macOS say", type(e).__name__)
    try:
        seconds, used = _speak_say(text, out_wav, speed)
        return seconds, "say", used
    except Exception as e:
        log.error("voiceover: no speech engine worked (%s); continuing without a voice", type(e).__name__)
        return 0.0, "", ""


def speak(text: str, out_wav: Path, voice: Optional[str] = None) -> float:
    """Speak text into a 24 kHz mono WAV. Returns its length in seconds, or 0 on total failure (never raises)."""
    try:
        return synthesize(text, out_wav, voice)[0]
    except Exception as e:  # belt and braces: a lesson build must never crash on speech
        log.error("voiceover: speech failed (%s)", type(e).__name__)
        return 0.0


# ---------------------------------------------------------------- 3. mixing

def _probe(path: Path) -> tuple[float, bool]:
    """(duration in seconds, has an audio stream)."""
    out = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout or "{}")
    duration = float(data.get("format", {}).get("duration") or 0.0)
    return duration, any(s.get("codec_type") == "audio" for s in data.get("streams", []))


@dataclass
class Narration:
    wav: Path
    cues: list[tuple[float, float, str]]  # (start, end, sentence) on the clip's clock
    engine: str
    voice: str


def _read_samples(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError("unexpected WAV format")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32767


def _layout(parts: Sequence[tuple[str, Optional[float], Path, float]]) -> tuple[list[float], float]:
    """Start of each part and the end of the last one. An untimed part follows the one before it after GAP_S;
    a timed part starts at its moment, or right after the previous part when that one is still speaking."""
    starts, t = [], LEAD_S
    for _, at, _, seconds in parts:
        if at is not None:
            t = max(t, at)
        starts.append(t)
        t += seconds + GAP_S
    return starts, t - GAP_S


def narrate(sentences: Sequence[str], clip_seconds: float, workdir: Path, voice: Optional[str] = None,
            speed: Optional[float] = None, synth=synthesize,
            times: Optional[Sequence[Optional[float]]] = None) -> Optional[Narration]:
    """Synthesize each sentence and lay them out on the clip's clock: after a short lead-in with small pauses,
    or, for sentences with a time in `times`, at that moment, so a line is heard while the hands do the thing.
    Speeds up a little if the voice would run past the clip, then (untimed narration only) drops trailing
    sentences. None if no sentence could be spoken."""
    import numpy as np

    base = float(speed or default_speed())
    room = clip_seconds - TAIL_S
    items = [(s, times[i] if times and i < len(times) else None) for i, s in enumerate(sentences) if s]
    timed = any(at is not None for _, at in items)

    parts: list[tuple[str, Optional[float], Path, float]] = []
    engine = used = ""
    for rate in (base, base * 1.1, base * 1.2):
        parts, engine, used = [], "", ""
        for i, (s, at) in enumerate(items):
            out = Path(workdir) / f"s{i}-{rate:.2f}.wav"
            seconds, eng, v = synth(s, out, voice, rate)
            if seconds > 0:
                parts.append((s, at, out, seconds))
                engine, used = engine or eng, used or v
        if not parts:
            return None
        if _layout(parts)[1] <= room:
            break
    if not timed:
        while len(parts) > 1 and _layout(parts)[1] > room:
            parts.pop()
    starts, end = _layout(parts)
    if end > room:
        log.warning("voiceover: narration ends at %.1fs but its clip allows %.1fs; the end is cut", end, room)
    want = int(clip_seconds * SAMPLE_RATE)
    audio = np.zeros(max(want, int(math.ceil(end * SAMPLE_RATE)) + 1), dtype=np.float32)
    cues = []
    for (s, _, path, _), t in zip(parts, starts):
        samples = _read_samples(path)
        seconds = len(samples) / SAMPLE_RATE
        k = int(round(t * SAMPLE_RATE))
        audio[k:k + len(samples)] += samples
        cues.append((t, t + seconds, s))
    audio = audio[:want]
    out = Path(workdir) / "voice.wav"
    _write_wav(out, audio)
    cues = [(a, min(b, clip_seconds), s) for a, b, s in cues if a < clip_seconds]
    return Narration(out, cues, engine, used)


def write_vtt(path: Path, cues: Sequence[tuple[float, float, str]], clip_seconds: float) -> None:
    """One cue per sentence; each cue stays up a moment after its sentence, never past the next one."""
    lines = ["WEBVTT", ""]
    for i, (a, b, text) in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < len(cues) else clip_seconds
        end = min(b + 0.3, nxt, clip_seconds)
        lines += [f"{fmt_vtt(a)} --> {fmt_vtt(end)}", text.replace("-->", "to"), ""]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def mix(source: Path, voice_wav: Path, out: Path, mode: str, clip_seconds: float, has_audio: bool) -> None:
    """Video copied as is; voice brought to a steady speech loudness; original audio ducked or dropped."""
    voice_chain = (f"[1:a]aresample=48000,loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11,aresample=48000,"
                   "aformat=sample_fmts=fltp:channel_layouts=stereo")
    if mode == "duck" and has_audio:
        graph = (f"{voice_chain}[v];[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"volume={DUCK_DB}dB[bg];[v][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        graph = f"{voice_chain}[a]"
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-i", str(source), "-i", str(voice_wav),
           "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]", "-map_metadata", "0",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{clip_seconds:.3f}",
           "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if p.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg mix failed: {p.stderr.strip()[-300:]}")


REPLACE_TRIES = 6     # Windows: a clip the hub is streaming refuses a rename (WinError 32) for a moment
REPLACE_WAIT_S = 0.5


def _replace(src: Path, dst: Path) -> None:
    """os.replace, retried while Windows reports the file in use."""
    import time

    for k in range(REPLACE_TRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if k == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_WAIT_S)


def _load_lesson(lesson_dir: Path) -> dict:
    return json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))


def _save_lesson(lesson_dir: Path, lesson: dict) -> None:
    path = lesson_dir / "lesson.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(lesson, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    _replace(tmp, path)


def _paths(lesson_dir: Path, step: dict, n: int) -> tuple[Path, Path, Path, Path]:
    """(clip, original clip backup, captions, original captions backup)."""
    nn = f"{n:02d}"
    clip = lesson_dir / str(step.get("clip") or f"clips/{nn}.mp4")
    vtt = lesson_dir / str(step.get("captions") or f"captions/{nn}.vtt")
    return clip, clip.with_name(clip.stem + ".orig.mp4"), vtt, vtt.with_name(vtt.stem + ".orig.vtt")


def original_clip(lesson_dir: Path, step: dict, n: int) -> Path:
    """The expert's untouched clip: the .orig backup if a voiceover was applied, else the clip itself."""
    clip, orig, _, _ = _paths(Path(lesson_dir), step, n)
    return orig if orig.is_file() else clip


def apply_voiceover(lesson_dir: Path, scripts: Sequence[StepScript], mode: str = "duck",
                    voice: Optional[str] = None, *, speed: Optional[float] = None, synth=synthesize) -> dict:
    """Voice every scripted step into its clip and captions. Always starts from the original clip, so running
    it twice does not stack voices. A step whose speech or mix fails keeps its current clip. Never raises
    for a single step; returns {"voiced": [n...], "skipped": [n...], "voiceover": field or None}."""
    if mode not in ("duck", "replace"):
        raise ValueError("mode must be duck or replace")
    lesson_dir = Path(lesson_dir)
    lesson = _load_lesson(lesson_dir)
    by_n = {int(s.get("n", i + 1)): s for i, s in enumerate(lesson.get("steps", []))}
    voiced, skipped, engines, voices = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="handover-voice-") as tmp:
        for sc in scripts:
            step = by_n.get(sc.n)
            if step is None or not sc.sentences:
                skipped.append(sc.n)
                continue
            clip, orig, vtt, vtt_orig = _paths(lesson_dir, step, sc.n)
            source = orig if orig.is_file() else clip
            try:
                if not source.is_file():
                    raise RuntimeError(f"{source.name} is missing")
                seconds, has_audio = _probe(source)
                work = Path(tmp) / f"{sc.n:02d}"
                work.mkdir()
                nar = narrate(sc.sentences, seconds, work, voice, speed, synth, sc.times)
                if nar is None:
                    raise RuntimeError("no speech")
                out = clip.with_name(clip.stem + ".voice.tmp.mp4")
                mix(source, nar.wav, out, mode, seconds, has_audio)
                if not orig.is_file():
                    shutil.copy2(clip, orig)  # a copy, not a move: if the swap below fails, the clip still plays
                _replace(out, clip)
                if vtt.is_file() and not vtt_orig.is_file():
                    shutil.copy2(vtt, vtt_orig)
                vtt.parent.mkdir(parents=True, exist_ok=True)
                write_vtt(vtt, nar.cues, seconds)
                voiced.append(sc.n)
                engines.append(nar.engine)
                voices.append(nar.voice)
            except Exception as e:
                log.error("voiceover: step %d kept its clip (%s)", sc.n, str(e)[:200] or type(e).__name__)
                clip.with_name(clip.stem + ".voice.tmp.mp4").unlink(missing_ok=True)
                skipped.append(sc.n)
    field_value = None
    if voiced:
        engine = max(set(engines), key=engines.count)
        sources = {sc.n: sc.source for sc in scripts}
        used_voice = voices[engines.index(engine)]
        model = {"kokoro": "kokoro-v1.0", "elevenlabs": eleven_model()}.get(engine, "macos-say")
        field_value = {"engine": engine, "voice": used_voice, "model": model, "tts": f"{engine}:{used_voice}",
                       "script_model": script_model(), "mode": mode, "speed": float(speed or default_speed()),
                       "steps": {str(n): {"script_source": sources.get(n, "claude")} for n in voiced}}
        lesson = _load_lesson(lesson_dir)
        lesson["voiceover"] = field_value
        _save_lesson(lesson_dir, lesson)
    return {"voiced": voiced, "skipped": skipped, "voiceover": field_value}


def undo(lesson_dir: Path) -> int:
    """Put back every original clip and caption file and drop the voiceover field. Returns steps restored."""
    lesson_dir = Path(lesson_dir)
    lesson = _load_lesson(lesson_dir)
    restored = 0
    for i, step in enumerate(lesson.get("steps", [])):
        clip, orig, vtt, vtt_orig = _paths(lesson_dir, step, int(step.get("n", i + 1)))
        if orig.is_file():
            _replace(orig, clip)
            restored += 1
        if vtt_orig.is_file():
            _replace(vtt_orig, vtt)
    if "voiceover" in lesson:
        del lesson["voiceover"]
        _save_lesson(lesson_dir, lesson)
    return restored


# ---------------------------------------------------------------- app cues

APP_CUES = {  # file stem: line. The Learn screen plays /voice/<stem>.mp3 (web/public/voice); see docs/voice.md
    "done-moving-on": "That's it. Next step.",
    "lesson-complete": "That's the whole thing. Nicely done.",
    "checks-off": "I can't see well right now. Tap Next when you're done.",
    "camera-lost": "I lost the camera. Keep going with Next.",
    "ahead": "You're ahead of me. Let's go back one step.",
    "still-step": "Not quite yet. Take another look at the clip.",
}
CUE_BITRATE = "48k"
CUE_PAD_S = 0.08  # a few silent milliseconds at the start so a browser never clips the first consonant


def render_line(text: str, mp3: Path, voice: Optional[str] = None, speed: Optional[float] = None,
                synth=None) -> tuple[float, str, str]:
    """One short line as a small mono mp3: each sentence spoken, GAP_S of silence between them, edges trimmed,
    loudness normalized. Returns (seconds, engine, voice); raises RuntimeError when nothing could be spoken."""
    import numpy as np

    synth = synth or synthesize
    mp3 = Path(mp3)
    with tempfile.TemporaryDirectory(prefix="handover-line-") as tmp:
        chunks, engine, used = [], "", ""
        for i, sentence in enumerate(split_sentences(text)):
            wav = Path(tmp) / f"s{i}.wav"
            seconds, eng, v = synth(sentence, wav, voice, speed)
            if seconds <= 0:
                raise RuntimeError("no speech")
            engine, used = engine or eng, used or v
            if chunks:
                chunks.append(np.zeros(int(GAP_S * SAMPLE_RATE), dtype=np.float32))
            chunks.append(_trim(_read_samples(wav)))
        if not chunks:
            raise RuntimeError("nothing to say")
        whole = Path(tmp) / "line.wav"
        seconds = _write_wav(whole, np.concatenate(chunks))
        graph = (f"adelay={int(CUE_PAD_S * 1000)},apad=pad_dur=0.15,"
                 f"loudnorm=I={VOICE_LUFS}:TP=-1.5:LRA=11,aresample={SAMPLE_RATE}")
        mp3.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(whole), "-af", graph, "-ac", "1",
                            "-c:a", "libmp3lame", "-b:a", CUE_BITRATE, "-map_metadata", "-1", str(mp3)],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0 or not mp3.is_file() or mp3.stat().st_size == 0:
            raise RuntimeError(f"ffmpeg: {p.stderr.strip()[-200:]}")
    return seconds, engine, used


def _trim(samples, threshold: float = 0.003):
    """Drop the near-silence a speech engine leaves at both ends of a sentence."""
    import numpy as np

    loud = np.flatnonzero(np.abs(samples) > threshold)
    return samples[loud[0]:loud[-1] + 1] if len(loud) else samples


def render_cues(folder: Path, voice: Optional[str] = None, cues: Mapping[str, str] = APP_CUES,
                synth=None) -> int:
    """Each cue as FOLDER/<name>.mp3 in the lesson voice (HANDOVER_TTS_PROVIDER, else Kokoro), mono 48 kbps.
    Returns 0 when every file was written, else 1."""
    failed = 0
    for name, line in cues.items():
        mp3 = Path(folder) / f"{name}.mp3"
        try:
            seconds, engine, used = render_line(line, mp3, voice, None, synth)
            print(f"{mp3.name}: {mp3.stat().st_size / 1024:.1f} KB, {seconds:.1f}s, {engine}:{used}: {line}")
        except Exception as e:
            failed += 1
            print(f"{name}.mp3 not written ({str(e)[:200] or type(e).__name__})", file=sys.stderr)
    return 1 if failed else 0


def audition(text: str, voices: Sequence[str], folder: Path, speed: Optional[float] = None, synth=None) -> int:
    """TEXT once per Kokoro voice, as FOLDER/<voice>.mp3, to pick a voice by ear. Kokoro only, no network: a
    voice Kokoro does not have is reported, not silently replaced. Returns 0 when every file was written."""
    if synth is None:
        def synth(t, out, v=None, sp=None):
            seconds, used = _speak_kokoro(t, out, v, float(sp or default_speed()))
            return seconds, "kokoro", used
    failed = 0
    for v in [x.strip() for x in voices if x.strip()]:
        mp3 = Path(folder) / f"{v}.mp3"
        try:
            seconds, _, used = render_line(text, mp3, v, speed or default_speed(), synth)
            if used != v:
                mp3.unlink(missing_ok=True)
                raise RuntimeError(f"Kokoro has no voice {v}")
            print(f"{mp3}: {mp3.stat().st_size / 1024:.1f} KB, {seconds:.1f}s")
        except Exception as e:
            failed += 1
            print(f"{v}: not written ({str(e)[:200] or type(e).__name__})", file=sys.stderr)
    return 1 if failed else 0


# ---------------------------------------------------------------- CLI

def _lesson_transcript(lesson_dir: Path) -> list[dict]:
    path = lesson_dir / "extraction.json"
    if not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("transcript") or [])
    except (OSError, ValueError, AttributeError):
        return []


def _lesson_frames(lesson_dir: Path, steps: list[dict], out: Path) -> tuple[list[list[Path]], list[float]]:
    """Per step: a frame from the middle of the original clip (the action) and the reference frame (the
    finished state), plus each clip's real length."""
    frames, seconds = [], []
    for i, st in enumerate(steps):
        n = int(st.get("n", i + 1))
        clip = original_clip(lesson_dir, st, n)
        got: list[Path] = []
        length = step_seconds(st)
        if clip.is_file():
            try:
                length = _probe(clip)[0] or length
                mid = out / f"{n:02d}-mid.jpg"
                subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{length / 2:.2f}", "-i", str(clip),
                                "-frames:v", "1", "-vf", f"scale={FRAME_SIDE}:-2", "-q:v", "4", str(mid)],
                               capture_output=True, timeout=60)
                if mid.is_file():
                    got.append(mid)
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError):
                pass
        ref = lesson_dir / str(st.get("ref_frame") or "")
        if st.get("ref_frame") and ref.is_file():
            got.append(ref)
        frames.append(got)
        seconds.append(length)
    return frames, seconds


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.voice", description="Automatic voiceover for a lesson.")
    ap.add_argument("lesson", type=Path, nargs="?", help="lesson folder, for example lessons/demo-v1")
    ap.add_argument("--mode", choices=("duck", "replace", "auto"), default="duck",
                    help="duck keeps the original audio quietly underneath; replace drops it; auto replaces when "
                         "the take has no usable narration, else ducks")
    ap.add_argument("--voice", default=None, help=f"Kokoro voice (default HANDOVER_VOICE, now {default_voice()})")
    ap.add_argument("--dry-run", action="store_true", help="write and print the scripts without synthesizing")
    ap.add_argument("--undo", action="store_true", help="restore the original clips and captions")
    ap.add_argument("--script", type=Path, default=None, metavar="FILE",
                    help='hand-written lines, {"steps": {"1": "line", ...}}; steps not in it get the usual script')
    ap.add_argument("--cues", type=Path, default=None, metavar="FOLDER",
                    help="render the Learn screen's spoken cues as mp3 files into FOLDER")
    ap.add_argument("--audition", default=None, metavar="TEXT", help="render TEXT once per --voices voice")
    ap.add_argument("--voices", default="af_heart,af_bella,af_nicole,am_adam,bm_george",
                    help="comma-separated Kokoro voices for --audition")
    ap.add_argument("--out", type=Path, default=None, metavar="DIR", help="folder for the --audition files")
    ap.add_argument("--speed", type=float, default=None, help=f"speaking speed, 0.7 to 1.3 (default "
                                                              f"HANDOVER_VOICE_SPEED, now {default_speed()}; a "
                                                              f"--script file's \"speed\" is used when given)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # a Windows console is cp1252: never crash on a curly quote
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    if args.cues is not None:
        return render_cues(args.cues, args.voice)
    if args.audition is not None:
        if args.out is None:
            ap.error("--audition needs --out DIR")
        return audition(args.audition, args.voices.split(","), args.out, args.speed)
    if args.lesson is None:
        ap.error("a lesson folder is required (or --cues FOLDER)")
    lesson_dir = args.lesson.resolve()
    if not (lesson_dir / "lesson.json").is_file():
        print(f"no lesson.json in {args.lesson}", file=sys.stderr)
        return 2
    if args.undo:
        print(f"restored {undo(lesson_dir)} original clips")
        return 0
    lesson = _load_lesson(lesson_dir)
    steps = list(lesson.get("steps") or [])
    transcript = _lesson_transcript(lesson_dir)
    thin = needs_voiceover(transcript, steps)
    mode = args.mode if args.mode != "auto" else ("replace" if thin else "duck")
    if args.mode == "auto":
        print(f"mode auto: {mode} ({'no usable narration in the take' if thin else 'the take has narration'})")
    elif not thin:
        print("note: the expert's narration looks usable; voicing anyway because you asked")
    lines: dict[int, Union[str, TimedLines]] = {}
    speed = args.speed
    if args.script is not None:
        try:
            lines = load_script_file(args.script)
            speed = speed if speed is not None else script_file_speed(args.script)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        known = {int(st.get("n", i + 1)) for i, st in enumerate(steps)}
        for n in sorted(set(lines) - known):
            print(f"warning: the script file has step {n}, which this lesson does not have; ignored")
    with tempfile.TemporaryDirectory(prefix="handover-voice-frames-") as tmp:
        frames, seconds = _lesson_frames(lesson_dir, steps, Path(tmp))
        from_file = file_scripts(steps, lines, seconds)
        todo = [i for i, sc in enumerate(from_file) if sc is None]
        if args.script is not None:
            print(f"script file {args.script.name}: {len(steps) - len(todo)} of {len(steps)} steps hand-written")
        written: list[StepScript] = []
        if not todo:
            pass
        elif config.get("HANDOVER_NO_NETWORK"):
            print("HANDOVER_NO_NETWORK=1, no Claude call; using the step titles instead")
            written = fallback_scripts([steps[i] for i in todo], [seconds[i] for i in todo])
        else:
            try:
                written = write_script([steps[i] for i in todo], transcript, [frames[i] for i in todo],
                                       clip_seconds=[seconds[i] for i in todo])
                print(f"script by {script_model()}, cost ${last_cost_usd:.5f}")
            except VoiceError as e:
                print(f"{e}; using the step titles instead")
                written = fallback_scripts([steps[i] for i in todo], [seconds[i] for i in todo])
        fill = iter(written)
        scripts = [sc if sc is not None else next(fill) for sc in from_file]
    for sc in scripts:
        print(f"\n{sc.n:02d} {sc.title} ({sc.seconds:.1f}s, {_words(sc.narration)} words, {sc.source})")
        for i, s in enumerate(sc.sentences):
            at = sc.time_at(i)
            print(f"   {'' if at is None else f'{at:5.1f}s  '}{s}")
    if args.dry_run:
        return 0
    print(f"\nspeed {speed if speed is not None else default_speed()}")
    result = apply_voiceover(lesson_dir, scripts, mode, args.voice, speed=speed)
    print(f"voiced steps {result['voiced'] or 'none'}; kept {result['skipped'] or 'none'}")
    if result["voiceover"]:
        print("lesson.json voiceover:", json.dumps(result["voiceover"]))
    return 0 if result["voiced"] else 1


if __name__ == "__main__":
    sys.exit(main())

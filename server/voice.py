"""Automatic voiceover: a calm spoken narration for lessons whose expert said little or nothing.

Three parts, each usable on its own:

1. write_script(steps, transcript, frames_by_step): one Claude call per lesson (structured output) writes 1 to 3
   short spoken sentences per step that fit the clip (about 2.5 words per second). Guarded by server/spend.py.
2. speak(text, out_wav): Kokoro, an open-source neural voice (Apache 2.0), run on this Mac's CPU through
   kokoro-onnx. The model files download once into ~/.cache/handover/kokoro. Falls back to macOS `say`, and on
   total failure returns 0 instead of raising, so a lesson build never crashes on speech.
3. apply_voiceover(lesson_dir, scripts, mode): mixes the voice into clips/NN.mp4 (the original audio ducked to
   about -18 dB in "duck", dropped in "replace"), writes captions/NN.vtt timed from each synthesized sentence,
   keeps clips/NN.orig.mp4 and captions/NN.orig.vtt so undo() can put everything back, and records a top-level
   "voiceover" field in lesson.json.

needs_voiceover(transcript, steps) says whether the narration is too thin; should_voiceover adds the
HANDOVER_VOICEOVER setting (auto, always, off).

    python -m server.voice lessons/<id> [--mode duck|replace] [--voice af_heart] [--dry-run] [--undo]

Settings: HANDOVER_VOICE_SCRIPT_MODEL (default claude-haiku-5-5), HANDOVER_VOICE (default af_heart),
HANDOVER_VOICE_SPEED (default 1.0), HANDOVER_VOICEOVER (default auto). ANTHROPIC_API_KEY comes from the
environment or <repo>/.env and is never printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import logging
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
from typing import Any, Mapping, Optional, Sequence

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
}


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
    return float(_setting("HANDOVER_VOICE_SPEED"))


def voiceover_setting() -> str:
    return str(_setting("HANDOVER_VOICEOVER"))


# ---------------------------------------------------------------- small helpers

WORDS_PER_SECOND = 2.5
LEAD_S = 0.4  # silence before the first sentence
TAIL_S = 0.3  # silence kept free at the end of the clip
GAP_S = 0.25  # pause between sentences
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

    @property
    def narration(self) -> str:
        return " ".join(self.sentences)

    def to_dict(self) -> dict:
        return {"n": self.n, "title": self.title, "seconds": round(self.seconds, 2), "sentences": self.sentences}


SYSTEM = """You write the voiceover for short how-to video clips. A calm, friendly person will read each line
aloud while the learner watches the clip and copies the expert's hands.

For each step write 1 to 3 short spoken sentences:
- Second person, warm and plain, like a patient friend standing next to the learner.
- Name the action the learner can see in the frames, then the one thing to watch for (use the common mistake
  when one is given, phrased as what to do).
- Stay within the step's word limit; fewer words is better than rushing.
- No filler and no openers like "In this step", "Now", "Here we", "Okay". No step numbers.
- No dashes of any kind, no lists, no emoji, no quotes. Plain sentences that sound natural spoken aloud.
- If the expert's own words are given, keep their meaning and any specific detail, but make them clear.
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
        out.append(StepScript(n, title, seconds, _fit_words(sentences, word_budget(seconds))))
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
                 f"Clip length: {seconds[i]:.1f} seconds, so at most {word_budget(seconds[i])} words"]
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
        sentences = _fit_words(sentences, word_budget(seconds[i])) if sentences else fallback[i].sentences
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
                log.warning("voiceover: Kokoro unavailable (%s); using macOS say", _kokoro_failed)
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
    if not shutil.which("say"):
        raise RuntimeError("macOS say is not available")
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


def synthesize(text: str, out_wav: Path, voice: Optional[str] = None,
               speed: Optional[float] = None) -> tuple[float, str, str]:
    """(seconds, engine, voice) for one text. engine is "kokoro", "say", or "" with 0 seconds on failure."""
    text = " ".join(clean_sentence(s) for s in split_sentences(text))
    out_wav = Path(out_wav)
    if not text:
        return 0.0, "", ""
    voice = voice or default_voice()
    speed = float(speed or default_speed())
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


def narrate(sentences: Sequence[str], clip_seconds: float, workdir: Path, voice: Optional[str] = None,
            speed: Optional[float] = None, synth=synthesize) -> Optional[Narration]:
    """Synthesize each sentence, lay them out after a short lead-in with small pauses, and pad to the clip.
    Speeds up a little, then drops trailing sentences, if the voice would run past the clip. None if no
    sentence could be spoken."""
    import numpy as np

    base = float(speed or default_speed())
    room = clip_seconds - LEAD_S - TAIL_S
    sentences = [s for s in sentences if s]
    def length(parts) -> float:
        return sum(p[2] for p in parts) + GAP_S * (len(parts) - 1)

    for rate in (base, base * 1.1, base * 1.2):
        parts: list[tuple[str, Path, float]] = []
        engine = used = ""
        for i, s in enumerate(sentences):
            out = Path(workdir) / f"s{i}-{rate:.2f}.wav"
            seconds, eng, v = synth(s, out, voice, rate)
            if seconds > 0:
                parts.append((s, out, seconds))
                engine, used = engine or eng, used or v
        if not parts:
            return None
        if length(parts) <= room:
            break
    while len(parts) > 1 and length(parts) > room:
        parts.pop()
    total = length(parts)
    if total > room:
        log.warning("voiceover: narration (%.1fs) is longer than its clip allows (%.1fs); the end is cut",
                    total, room)
    chunks, cues, t = [np.zeros(int(LEAD_S * SAMPLE_RATE), dtype=np.float32)], [], LEAD_S
    for i, (s, path, _) in enumerate(parts):
        samples = _read_samples(path)
        seconds = len(samples) / SAMPLE_RATE
        cues.append((t, t + seconds, s))
        chunks.append(samples)
        t += seconds
        if i < len(parts) - 1:
            chunks.append(np.zeros(int(GAP_S * SAMPLE_RATE), dtype=np.float32))
            t += GAP_S
    audio = np.concatenate(chunks)
    want = int(clip_seconds * SAMPLE_RATE)
    audio = np.pad(audio, (0, max(0, want - len(audio))))[:want]
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
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _load_lesson(lesson_dir: Path) -> dict:
    return json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))


def _save_lesson(lesson_dir: Path, lesson: dict) -> None:
    path = lesson_dir / "lesson.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(lesson, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


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
                nar = narrate(sc.sentences, seconds, work, voice, speed, synth)
                if nar is None:
                    raise RuntimeError("no speech")
                out = clip.with_name(clip.stem + ".voice.tmp.mp4")
                mix(source, nar.wav, out, mode, seconds, has_audio)
                if not orig.is_file():
                    os.replace(clip, orig)
                os.replace(out, clip)
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
        field_value = {"engine": engine, "voice": voices[engines.index(engine)],
                       "model": "kokoro-v1.0" if engine == "kokoro" else "macos-say",
                       "script_model": script_model(), "mode": mode}
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
            os.replace(orig, clip)
            restored += 1
        if vtt_orig.is_file():
            os.replace(vtt_orig, vtt)
    if "voiceover" in lesson:
        del lesson["voiceover"]
        _save_lesson(lesson_dir, lesson)
    return restored


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
    ap.add_argument("lesson", type=Path, help="lesson folder, for example lessons/demo-v1")
    ap.add_argument("--mode", choices=("duck", "replace"), default="duck",
                    help="duck keeps the original audio quietly underneath; replace drops it")
    ap.add_argument("--voice", default=None, help=f"Kokoro voice (default HANDOVER_VOICE, now {default_voice()})")
    ap.add_argument("--dry-run", action="store_true", help="write and print the scripts without synthesizing")
    ap.add_argument("--undo", action="store_true", help="restore the original clips and captions")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
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
    if not needs_voiceover(transcript, steps):
        print("note: the expert's narration looks usable; voicing anyway because you asked")
    with tempfile.TemporaryDirectory(prefix="handover-voice-frames-") as tmp:
        frames, seconds = _lesson_frames(lesson_dir, steps, Path(tmp))
        try:
            scripts = write_script(steps, transcript, frames, clip_seconds=seconds)
            print(f"script by {script_model()}, cost ${last_cost_usd:.5f}")
        except VoiceError as e:
            print(f"{e}; using the step titles instead")
            scripts = fallback_scripts(steps, seconds)
    for sc in scripts:
        print(f"\n{sc.n:02d} {sc.title} ({sc.seconds:.1f}s, {_words(sc.narration)} words)\n   {sc.narration}")
    if args.dry_run:
        return 0
    print()
    result = apply_voiceover(lesson_dir, scripts, args.mode, args.voice)
    print(f"voiced steps {result['voiced'] or 'none'}; kept {result['skipped'] or 'none'}")
    if result["voiceover"]:
        print("lesson.json voiceover:", json.dumps(result["voiceover"]))
    return 0 if result["voiced"] else 1


if __name__ == "__main__":
    sys.exit(main())

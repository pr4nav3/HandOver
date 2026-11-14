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

from pydantic import BaseModel, Field, ValidationError, field_validator

from server import config

REPO = Path(__file__).resolve().parent.parent
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ and HLG, what iPhones record in HDR
SDR_TAGS = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
SDR_FRAME_TAGS = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
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
  number of corners, flaps, folds or seams, and which way the object faces. Never use color: the learner's
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


def has_audio(path: Path) -> bool:
    out = _capture([_bin("ffprobe"), "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                    "-of", "csv=p=0", str(path)])
    return bool(out.stdout.strip())


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
    tmp.replace(path)


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
    audio = has_audio(src)
    if color_transfer(src) in HDR_TRANSFERS:
        vf = "scale=-2:1080:in_color_matrix=bt2020:out_color_matrix=bt709,format=yuv420p"
    else:
        vf = "scale=-2:1080,format=yuv420p"
    vf += "," + SDR_FRAME_TAGS  # the encoder flags alone lose to the frame tags ffmpeg carries from the input
    cmd = [_bin("ffmpeg"), "-y", "-i", str(src)]
    if not audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest"]
    cmd += [
        "-map", "0:v:0", "-map", "0:a:0" if audio else "1:a:0",
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

""" + PROMPT[PROMPT.index("For each step give:"):PROMPT.index("First give the transcript")].replace(
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
- Steps are in order, contiguous and cover the whole task: each step's end equals the next step's start.
  The first step starts at the beginning of the task and the last step ends when the task is finished.
- Prefer 3 to 12 steps. One step is one physical action with a clear result. Do not merge unrelated actions
  and do not split one action into tiny pieces.
- Only use timestamps from the frame labels or the transcript, or times between them.

""" + PROMPT[PROMPT.index("For each step give:"):PROMPT.index("First give the transcript")]


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
    segments, _info = model.transcribe(_audio_16k(media), vad_filter=True)
    out = [Segment(start=float(seg.start), end=float(seg.end), text=" ".join(seg.text.split()))
           for seg in segments if seg.text.strip()]
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


def extract_claude(norm: Path, progress: Progress = noop) -> Extraction:
    """One Claude call on about 1 fps frames of a small proxy. Claude cannot hear, so with HANDOVER_TRANSCRIBE
    local (the default for Claude) the narration is transcribed on this Mac first and sent as timestamped text;
    it also becomes the captions. Without a transcript, Claude sees frames only and the captions are empty."""
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
        progress("extracting", f"Sending {len(frames)} frames to {model} (no audio: captions will be empty)")
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


# ---------------------------------------------------------------- 3a. reference frames (M8)

REF_TAIL = 0.15        # look for the reference in the last 15% of the step
REF_MIN_WINDOW = 0.3   # seconds; very short steps still get a few frames to compare
REF_END_GAP = 0.05     # stay this far before the step end so the frame belongs to this step
REF_CANDIDATES = 8
THUMB = 96             # stillness is measured on 96x96 gray thumbnails
DARK = 16.0            # mean gray level below this counts as a black frame (fade, lens covered)


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


def pick_ref_time(video: Path, a: float, b: float, hint: float | None = None) -> float | None:
    """The stillest, not black moment in the last 15% of [a, b], on the 0.1 s grid lesson.json uses.

    About 8 candidates are spread over that window and each is scored by how much it differs from the frames
    next to it. When the model's hint lies in the step and is nearly as still as the best candidate, the hint
    wins, because the model also checked that hands are clear. Returns None when no frame could be sampled."""
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


def _ref_frame(norm: Path, clip: Path, out: Path, a: float, b: float, ref_time: str, explicit: bool) -> str | None:
    """Writes the reference frame for one step and returns its ref_time, or None for the clip's last frame.

    explicit (recut): a ref_time inside the step is used as is. Otherwise, and when it is empty or outside the
    step (the step was moved), the stillest frame in the last 15% is chosen, preferring the model's hint."""
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
            t = pick_ref_time(norm, a, b, given)
        except RuntimeError:
            t = None
    if t is None:
        return None
    try:
        _grab_frame(norm, t, out)
    except RuntimeError:
        return None
    return fmt_mmss(t)


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
        *, keep: dict | None = None, progress: Progress = noop) -> dict:
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
    shutil.rmtree(tmp, ignore_errors=True)
    for sub in SUBDIRS:
        (tmp / sub).mkdir(parents=True)

    try:
        steps_out = _cut_steps(norm, tmp, extraction, spans, keep, progress)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    _swap_in(lesson_dir, tmp)

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


def _swap_in(lesson_dir: Path, tmp: Path) -> None:
    """Moves the old folders aside, the new ones in, then deletes the old ones. Works on Windows too, where a
    folder cannot be renamed over an existing one."""
    old = lesson_dir / ".recut_old"
    shutil.rmtree(old, ignore_errors=True)
    old.mkdir()
    for sub in SUBDIRS:
        if (lesson_dir / sub).exists():
            (lesson_dir / sub).replace(old / sub)
        (tmp / sub).replace(lesson_dir / sub)
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)


def _is_manual(question: str) -> bool:
    q = question.strip()
    return not q or q.lower().strip(" .") == "manual"


def _cut_steps(norm: Path, out_dir: Path, extraction: Extraction, spans: list[tuple[float, float]],
               keep: dict | None = None, progress: Progress = noop) -> list[dict]:
    old_steps = (keep or {}).get("steps") or []
    steps_out = []
    total = len(spans)
    for n, (st, (a, b)) in enumerate(zip(extraction.steps, spans), start=1):
        nn = f"{n:02d}"
        clip = out_dir / "clips" / f"{nn}.mp4"
        _run([_bin("ffmpeg"), "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(norm),
              "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", *SEEK_TAGS, *SDR_TAGS, "-c:a", "aac",
              "-movflags", "+faststart", str(clip)])
        length = probe_duration(clip)
        _write_vtt(out_dir / "captions" / f"{nn}.vtt", extraction.transcript, a, length)
        ref_time = _ref_frame(norm, clip, out_dir / "frames" / f"{nn}.jpg", a, b, st.ref_time, keep is not None)
        manual = _is_manual(st.check_question)
        progress("cutting", f"step {n} of {total}  {fmt_mmss(a)} to {fmt_mmss(b)}  "
                            f"reference {ref_time or 'last frame'}  [{'manual' if manual else 'camera'}]")
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


def recut(lesson_dir: Path, progress: Progress = noop) -> dict:
    """Rebuilds clips, captions and frames from lesson.json (possibly hand-edited) and the saved transcript.

    Follows the Recut rule: every field recut does not own is kept, step 1 is never forced to manual, and a
    step's ref_time is used when it lies inside the step (otherwise a new one is chosen and written)."""
    lesson_dir = Path(lesson_dir)
    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    if not isinstance(lesson, dict):
        raise ValueError("bad lesson.json: not an object")
    extraction = _lesson_extraction(lesson_dir, lesson)
    return cut(lesson_dir, extraction, lesson.get("id"), lesson.get("title"), keep=lesson, progress=progress)


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

    if steps_json:
        progress("extracting", f"Using steps from {Path(steps_json).name}")
        extraction = _clean_extraction(mock_extraction(duration, steps_json), duration)
    else:
        provider = teach_provider()
        if provider == "mock":
            why = "HANDOVER_TEACH_MOCK is set" if config.get("HANDOVER_TEACH_MOCK") else "no Gemini or Anthropic key"
            progress("extracting", f"Using three placeholder steps ({why})")
            extraction = mock_extraction(duration, None)
        elif provider == "claude":
            progress("extracting", f"Finding steps with {_claude_model()} from frames")
            extraction = extract_claude(norm, progress)
        else:
            progress("extracting", f"Finding steps with {_model()}")
            extraction = _gemini_transcript_mode(extract(norm, progress), norm, progress)
        extraction = _first_step_manual(_clean_extraction(extraction, duration))

    progress("cutting", f"Cutting {len(extraction.steps)} step clips")
    lesson = cut(lesson_dir, extraction, lesson_id, title, progress=progress)
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


def _run_cli(args, show: Progress) -> int:
    t0 = time.time()
    if args.self_test:
        d = _lesson_dir_arg(args.self_test)
        if not (d / "norm.mp4").is_file() and not args.dry_run:
            show("self-test", "norm.mp4 missing; the first step may be skipped")
        lesson = json.loads((d / "lesson.json").read_text(encoding="utf-8"))
        camera = [s.get("n", i + 1) for i, s in enumerate(lesson.get("steps") or []) if s.get("check_type") != "manual"]
        mode = "mock" if _check_is_mock() else config.get("HANDOVER_CHECK_MODEL")
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
        lesson = recut(d, show)
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
    lesson = build(srcs, args.lesson_id, args.title or args.lesson_id, show, args.steps_json)
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

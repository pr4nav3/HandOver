"""Real end-to-end teach test: a narrated expert take with known ground truth, through the real pipeline.

    .venv/bin/python scripts/teach_e2e.py [--keep] [--whisper-model small.en] [--take DIR] [--seed 11]
        [--voice Samantha] [--max-load 24] [--quiet]
    .venv/bin/python scripts/teach_e2e.py --rescore DIR

1. Builds a 1080p30 "expert take" in a temp folder: the 8 fortune teller states from scripts/synth_folds.py,
   each held 6 to 9 s (different per step), with slow camera drift and a synthetic hand crossing the paper at
   some state changes, plus macOS `say` narration (one or two sentences per step, starting at a varied point
   inside the step) mixed to an AAC track. Writes take.mp4 and ground_truth.json (true step times, spoken text).
   --take DIR reuses take.mp4 and ground_truth.json from an earlier --keep run, so two runs see the same input.
2. Runs the real CLI, `python -m server.teach take.mp4 --id e2e-narrated ...`, with HANDOVER_LESSONS in the temp
   folder, HANDOVER_TEACH_PROVIDER=claude, HANDOVER_TRANSCRIBE=local and HANDOVER_WHISPER_MODEL. This makes one
   paid Claude call (the spend ledger in server/spend.py guards it) and, the first time, downloads the speech model.
3. Scores the lesson against the ground truth and prints a PASS/FAIL table:
     step count within 1 of the truth, mean boundary error <= 2.0 s, transcript WER <= 15%, no lesson_lint FAIL,
     Claude cost <= $0.05; plus captions in every clip, caption timing (a transcript segment may reach at most
     0.5 s into silence on average), no color words in check questions, step 1 manual, and a common_mistake on
     the flip step.
   Writes scripts/out/teach-e2e-<ts>.md.
   --rescore DIR scores the lesson of an earlier --keep run again without calling anything (no timings, and the
   cost row shows unknown).

The visuals are Pillow drawings and the voice is synthetic: this proves the pipeline end to end, not the
accuracy on real footage. Exit codes: 0 every row passed, 1 a row failed or the pipeline failed, 2 setup problem.
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
OUT = SCRIPTS / "out"
PY = REPO / ".venv" / "bin" / "python"
LESSON_ID = "e2e-narrated"
TITLE = "E2E narrated fortune teller"
W, H, FPS = 1920, 1080, 30
SR = 48000  # narration sample rate
FLIP_STEP = 5  # truth step where the expert flips the paper over

# thresholds
MAX_STEP_DIFF = 1
MAX_MEAN_BOUNDARY_S = 2.0
MAX_WER = 0.15
MAX_COST_USD = 0.05
MAX_CAPTION_DRIFT_S = 0.5  # mean distance from a caption's start or end to the nearest spoken words

# What the expert says per state of synth_folds.py (1 flat square ... 8 four pockets).
NARRATION: list[list[str]] = [
    ["Start with a square sheet of paper flat on the table, colored side up."],
    ["Fold it corner to corner into a big triangle.", "Press the fold down firmly."],
    ["Now open it up and fold the other diagonal.", "Unfold it again so you can see an X crease."],
    ["Next, fold all four corners into the center, so the points meet in the middle."],
    ["Flip the whole thing over.", "The smooth side should face up now."],
    ["Fold the four new corners into the center again, to make a smaller square."],
    ["Fold it in half both ways and open it back up, so you get a cross crease."],
    ["Finally, push your fingers into the four pockets and pinch the points together.",
     "Your fortune teller is done."],
]

_NUMBERS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
            "7": "seven", "8": "eight", "9": "nine", "10": "ten", "11": "eleven", "12": "twelve"}


# ---------------------------------------------------------------- scoring math (tested offline)

def words(text: str) -> list[str]:
    """Lowercase words for WER: hyphens split words, punctuation dropped, small digits spelled out."""
    text = text.lower().replace("-", " ")
    out = []
    for w in re.findall(r"[a-z0-9']+", text):
        w = w.strip("'")
        if w:
            out.append(_NUMBERS.get(w, w))
    return out


def wer(reference: str, hypothesis: str) -> tuple[int, int, float]:
    """Word error rate with difflib's alignment: (errors, reference words, rate). A replace block counts the
    longer side, so substitutions plus the extra insertions or deletions are all counted."""
    ref, hyp = words(reference), words(hypothesis)
    errors = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        if op == "replace":
            errors += max(i2 - i1, j2 - j1)
        elif op == "delete":
            errors += i2 - i1
        elif op == "insert":
            errors += j2 - j1
    if not ref:
        return errors, 0, 0.0 if not hyp else 1.0
    return errors, len(ref), errors / len(ref)


def boundary_errors(truth: list[float], found: list[float]) -> list[float | None]:
    """For each true boundary (a step start after the first), the distance in seconds to the nearest found
    boundary. None when nothing was found. The step count row catches merged or extra steps."""
    if not found:
        return [None for _ in truth]
    return [min(abs(t - f) for f in found) for t in truth]


def summarize(errors: list[float | None]) -> tuple[float | None, float | None]:
    """(mean, max) of the known errors; (None, None) when there are none."""
    known = [e for e in errors if e is not None]
    if not known:
        return None, None
    return sum(known) / len(known), max(known)


def distance_to_speech(t: float, spoken: list[tuple[float, float]]) -> float:
    """0 when t falls inside a spoken interval, else the distance in seconds to the nearest one."""
    if not spoken:
        return 0.0
    return min(0.0 if a <= t <= b else min(abs(t - a), abs(t - b)) for a, b in spoken)


def caption_drift(segments: list[tuple[float, float]], spoken: list[tuple[float, float]]) -> list[float]:
    """Per transcript segment, how far it reaches into silence past the words it holds: the larger of (first
    overlapping spoken line's start minus the segment start) and (segment end minus the last overlapping line's
    end), never below 0. A caption shown 4 s before its words are said scores 4; a segment split mid-sentence
    scores 0. A segment over no speech at all scores its distance to the nearest speech."""
    out = []
    for a, b in segments:
        hit = [(x, y) for x, y in spoken if overlap((a, b), (x, y)) > 0.05]
        if not hit:
            out.append(max(distance_to_speech(a, spoken), distance_to_speech(b, spoken)))
            continue
        out.append(max(0.0, hit[0][0] - a, b - hit[-1][1]))
    return out


def overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def best_overlap(window: tuple[float, float], spans: list[tuple[float, float]]) -> int | None:
    """Index of the span that overlaps window the most, None when none overlaps."""
    scores = [overlap(window, s) for s in spans]
    if not scores or max(scores) <= 0:
        return None
    return scores.index(max(scores))


FLIP_RE = re.compile(r"\b(flip|flipped|flipping|turn\w* (it |the \w+ |everything )?over)\b", re.I)


def flip_index(steps: list[dict], window: tuple[float, float], spans: list[tuple[float, float]]) -> int | None:
    """The found step that holds the flip: the first whose title or question says flip or turn over, else the
    one overlapping the true flip window most (a merged step can hide the flip inside another title)."""
    for i, s in enumerate(steps):
        if FLIP_RE.search(f"{s.get('title', '')} {s.get('check_question', '')}"):
            return i
    return best_overlap(window, spans)


def vtt_cues(text: str) -> list[str]:
    """Cue texts of a WebVTT file."""
    cues, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        if "-->" in line:
            body = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    break
                body.append(nxt.strip())
            if body:
                cues.append(" ".join(body))
    return cues


MARKERS = {
    "normalized": "[extracting] Finding steps",
    "download": "Downloading speech model",
    "transcribe": "[extracting] Transcribing narration",
    "transcribed": "[extracting] Transcribed ",
    "claude": "[extracting] Sending ",
    "cut": "[cutting] Cutting ",
    "done": "[done]",
}


def stage_times(lines: list[tuple[float, str]], total: float) -> dict[str, float | None]:
    """Seconds per stage from the CLI's timestamped progress lines (time since start, text).

    normalize: start to "Finding steps". prep: proxy and frame sampling (and the speech model load when it was
    already downloaded). download: speech model download and load, first run only. transcribe, claude, cut:
    between their progress lines. A stage whose lines are missing is None."""
    at: dict[str, float] = {}
    for t, text in lines:
        for key, marker in MARKERS.items():
            if key not in at and marker in text:
                at[key] = t
    if "cut" in at:
        at.setdefault("done", total)

    def span(a: str | None, b: str) -> float | None:
        if a is None or a not in at or b not in at:
            return None
        return max(0.0, at[b] - at[a])

    start_tx = "download" if "download" in at else "transcribe"
    out = {
        "normalize": at.get("normalized"),
        "prep": span("normalized", start_tx),
        "download": span("download", "transcribe") if "download" in at else None,
        "transcribe": span("transcribe", "transcribed"),
        "claude": span("claude", "cut"),
        "cut": span("cut", "done"),
        "total": total,
    }
    return out


def color_words(question: str, vocabulary: set[str]) -> list[str]:
    return sorted({w for w in re.findall(r"[a-z']+", question.lower()) if w in vocabulary})


# ---------------------------------------------------------------- helpers

def parse_time(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    for part in str(value).strip().split(":"):
        total = total * 60 + float(part)
    return total


def ffmpeg() -> str:
    found = os.environ.get("HANDOVER_FFMPEG") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not Path(found).is_file():
        raise SetupError("ffmpeg not found (PATH, HANDOVER_FFMPEG or /opt/homebrew/bin)")
    return found


def run(cmd: list[str]) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {p.stderr.strip()[-400:]}")


def wait_for_load(limit: int) -> None:
    """The house rule before heavy steps: wait while the 5 minute load average is above limit."""
    while int(os.getloadavg()[1]) > limit:
        print(f"[load] {os.getloadavg()[1]:.1f} is above {limit}, waiting 30 s", flush=True)
        time.sleep(30)


class SetupError(Exception):
    pass


def fmt(v: float | None, unit: str = " s", digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}{unit}"


# ---------------------------------------------------------------- 1. build the take

def _say(text: str, voice: str, rate: int, out_wav: Path, tmp: Path):
    """One spoken sentence as mono float samples at SR."""
    aiff = tmp / (out_wav.stem + ".aiff")
    run(["say", "-v", voice, "-r", str(rate), "-o", str(aiff), text])
    run([ffmpeg(), "-y", "-v", "error", "-i", str(aiff), "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le",
         str(out_wav)])
    import numpy as np

    with wave.open(str(out_wav)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    # trim the voice's own leading and trailing silence so the ground truth times are the spoken times
    loud = np.nonzero(np.abs(data) > 0.01)[0]
    if len(loud):
        data = data[max(0, loud[0] - int(0.02 * SR)):loud[-1] + int(0.05 * SR)]
    return data


def plan_take(rng: random.Random, voice: str, tmp: Path) -> tuple[list[dict], list]:
    """Step windows and narration placement. Each step lasts 6 to 9 s, its first sentence starts 0.4 to 1.4 s in,
    a second sentence follows after a 0.3 to 0.9 s pause, and at least 0.5 s of quiet ends the step."""
    lengths = [6.0 + 3.0 * (i + rng.random()) / len(NARRATION) for i in range(len(NARRATION))]
    rng.shuffle(lengths)
    steps, clips, t = [], [], 0.0
    for k, sentences in enumerate(NARRATION, start=1):
        for rate in (rng.randint(168, 186), 195, 210):
            audio = [_say(s, voice, rate, tmp / f"line{k}_{i}.wav", tmp) for i, s in enumerate(sentences)]
            gaps = [rng.uniform(0.3, 0.9) for _ in audio[1:]]
            speech = sum(len(a) for a in audio) / SR + sum(gaps)
            if speech + 0.9 <= 9.0:
                break
        length = max(lengths[k - 1], speech + 0.9)
        lead = rng.uniform(0.4, min(1.4, length - speech - 0.5))
        spoken, at = [], t + lead
        for i, (s, a) in enumerate(zip(sentences, audio)):
            if i:
                at += gaps[i - 1]
            dur = len(a) / SR
            spoken.append({"start": round(at, 3), "end": round(at + dur, 3), "text": s})
            clips.append((at, a))
            at += dur
        steps.append({"n": k, "start": round(t, 3), "end": round(t + length, 3), "rate": rate,
                      "text": " ".join(sentences), "speech": spoken})
        t += length
    return steps, clips


def mix_narration(clips: list, duration: float, out_wav: Path, seed: int) -> None:
    import numpy as np

    n = int(round(duration * SR))
    buf = np.random.default_rng(seed).normal(0.0, 0.0015, n).astype(np.float32)  # quiet room tone
    for at, audio in clips:
        i = int(round(at * SR))
        seg = audio[: max(0, n - i)]
        buf[i:i + len(seg)] += seg * 0.9
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _affine(img, dx: float, dy: float, rot_deg: float, zoom: float):
    from PIL import Image

    c, s = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    a, b, d, e = c / zoom, s / zoom, -s / zoom, c / zoom
    cx, cy = W / 2, H / 2
    data = (a, b, cx - a * (cx + dx) - b * (cy + dy), d, e, cy - d * (cx + dx) - e * (cy + dy))
    return img.transform((W, H), Image.AFFINE, data, resample=Image.BILINEAR, fillcolor=(30, 32, 34))


def _bell(x: float) -> float:
    """0 outside [-1, 1], 1 at 0, smooth in between."""
    return 0.0 if abs(x) >= 1 else 0.5 * (1 + math.cos(math.pi * x))


def render_video(steps: list[dict], seed: int, wav: Path, out: Path) -> dict:
    """Pipes 1080p frames to ffmpeg with the narration as AAC. Returns what was drawn (for ground_truth.json)."""
    import synth_folds as sf

    rng = random.Random(seed)
    bases = []
    for k in range(1, 9):
        p = sf.clean_params(k, seed)
        p.rotation = rng.uniform(-14, 14)  # the expert puts the paper down a little differently each time
        p.offset = (rng.uniform(-0.05, 0.05), rng.uniform(-0.03, 0.03))
        bases.append(sf.compose(k, p, (W, H), seed * 31 + k))
    corners = [(W / 2 - 0.34 * H, H * 0.16), (W / 2 + 0.34 * H, H * 0.16),
               (W / 2 + 0.34 * H, H * 0.84), (W / 2 - 0.34 * H, H * 0.84)]
    outward = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    transitions = [s["start"] for s in steps[1:]]
    with_hand = sorted(rng.sample(range(len(transitions)), k=5))
    hands = {}
    for i in with_hand:
        hp = sf.Params(hand={"edge": rng.choice([1, 2, 3]), "along": rng.uniform(0.3, 0.7),
                             "reach": rng.uniform(0.45, 0.7), "fingers": rng.choice([3, 4]),
                             "skin": list(rng.choice(sf.SKIN))})
        skin, alpha = sf.hand_layer(hp, corners, (W, H), random.Random(seed + i))
        hands[i] = (skin, alpha, outward[hp.hand["edge"]])
    phase = [rng.uniform(0, 2 * math.pi) for _ in range(4)]
    duration = steps[-1]["end"]
    frames = int(round(duration * FPS))
    fade = 0.4

    cmd = [ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    from PIL import Image

    try:
        for f in range(frames):
            t = f / FPS
            dx = 14 * math.sin(2 * math.pi * t / 6.1 + phase[0]) + 4 * math.sin(2 * math.pi * t / 1.9 + phase[1])
            dy = 6 * math.sin(2 * math.pi * t / 4.7 + phase[2]) + 2 * math.sin(2 * math.pi * t / 1.3 + phase[3])
            rot = 0.7 * math.sin(2 * math.pi * t / 7.3 + phase[1])
            k = sum(1 for b in transitions if t >= b)  # index of the current state (0 based)
            img = _affine(bases[k], dx, dy, rot, 1.06)
            # the paper changes shape over 0.4 s right at each boundary, under the hand when there is one
            for i, b in enumerate(transitions):
                if b - fade / 2 <= t < b + fade / 2:
                    w = (t - (b - fade / 2)) / fade
                    img = Image.blend(_affine(bases[i], dx, dy, rot, 1.06),
                                      _affine(bases[i + 1], dx, dy, rot, 1.06), w)
            for i, (skin, alpha, (ox, oy)) in hands.items():
                x = (t - transitions[i]) / 1.0  # the hand comes in over 1 s, folds, and leaves over 1 s
                g = _bell(x)
                if g > 0:
                    away = (1 - g) * 0.6 * H
                    pos = (int(ox * away), int(oy * away))
                    img.paste(skin, pos, alpha)
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()[-400:]}")
    except BaseException:
        proc.kill()
        raise
    return {"hand_crossings_at": [round(transitions[i], 3) for i in with_hand], "state_fade_s": fade}


def build_take(work: Path, seed: int, voice: str) -> dict:
    tmp = work / "audio"
    tmp.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    steps, clips = plan_take(rng, voice, tmp)
    duration = steps[-1]["end"]
    wav = work / "narration.wav"
    mix_narration(clips, duration, wav, seed)
    drawn = render_video(steps, seed, wav, work / "take.mp4")
    import synth_folds as sf

    for s in steps:
        s["state"] = sf.TITLES[s["n"]]
    truth = {"synthetic": True, "note": "Pillow drawings and macOS say narration, not real footage.",
             "seed": seed, "voice": voice, "size": [W, H], "fps": FPS, "duration": round(duration, 3),
             "flip_step": FLIP_STEP, **drawn, "steps": steps}
    (work / "ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    return truth


# ---------------------------------------------------------------- 2. run the real pipeline

def run_teach(take: Path, lessons: Path, whisper_model: str, quiet: bool) -> tuple[int, list[tuple[float, str]], float]:
    env = dict(os.environ)
    env.pop("HANDOVER_TEACH_MOCK", None)
    env.update({"HANDOVER_LESSONS": str(lessons), "HANDOVER_TEACH_PROVIDER": "claude",
                "HANDOVER_TRANSCRIBE": "local", "HANDOVER_WHISPER_MODEL": whisper_model,
                "PYTHONUNBUFFERED": "1"})
    cmd = [str(PY), "-m", "server.teach", str(take), "--id", LESSON_ID, "--title", TITLE]
    t0 = time.monotonic()
    lines: list[tuple[float, str]] = []
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    for line in proc.stdout:
        t = time.monotonic() - t0
        lines.append((t, line.rstrip()))
        if not quiet:
            print(f"  {t:6.1f}  {line.rstrip()}", flush=True)
    rc = proc.wait()
    return rc, lines, time.monotonic() - t0


def spend_snapshot() -> dict | None:
    try:
        from server import spend

        s = spend.status()
        return {"usd": s.total_usd, "calls": s.total_calls}
    except Exception as e:  # the ledger is unreadable: cost cannot be measured
        print(f"[spend] could not read the ledger: {type(e).__name__}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- 3. score

def lint(lesson_dir: Path) -> dict:
    p = subprocess.run([str(PY), str(SCRIPTS / "lesson_lint.py"), str(lesson_dir), "--json"],
                       capture_output=True, text=True, cwd=REPO)
    try:
        return json.loads(p.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        return {"result": "FAIL", "counts": {}, "checks": [{"check": "lint", "result": "FAIL",
                                                            "detail": (p.stderr or p.stdout).strip()[-300:]}]}


def score(truth: dict, lesson_dir: Path, stages: dict, cost: float | None, calls: int | None) -> dict:
    sys.path.insert(0, str(SCRIPTS))
    import lesson_lint

    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    extraction = json.loads((lesson_dir / "extraction.json").read_text(encoding="utf-8"))
    steps = lesson["steps"]
    tsteps = truth["steps"]
    spans = [(parse_time(s["start"]), parse_time(s["end"])) for s in steps]

    t_bounds = [s["start"] for s in tsteps[1:]]
    f_bounds = [a for a, _ in spans[1:]]
    errs = boundary_errors(t_bounds, f_bounds)
    mean_err, max_err = summarize(errs)

    reference = " ".join(s["text"] for s in tsteps)
    hypothesis = " ".join(seg["text"] for seg in extraction.get("transcript") or [])
    n_err, n_ref, rate = wer(reference, hypothesis)
    spoken = [(x["start"], x["end"]) for t in tsteps for x in t["speech"]]
    segs = [(float(seg["start"]), float(seg["end"])) for seg in extraction.get("transcript") or []]
    drift = caption_drift(segs, spoken)
    drift_mean, drift_max = summarize(drift)

    captions = []
    for s in steps:
        p = lesson_dir / s["captions"]
        captions.append(vtt_cues(p.read_text(encoding="utf-8")) if p.is_file() else [])
    no_caption = [s["n"] for s, c in zip(steps, captions) if not c]

    colored = {s["n"]: color_words(s.get("check_question") or "", lesson_lint.COLOR_WORDS) for s in steps}
    colored = {n: c for n, c in colored.items() if c}

    flip_truth = next(s for s in tsteps if s["n"] == truth.get("flip_step", FLIP_STEP))
    fi = flip_index(steps, (flip_truth["start"], flip_truth["end"]), spans)
    flip = steps[fi] if fi is not None else None

    lint_rep = lint(lesson_dir)
    lint_fail = [c for c in lint_rep.get("checks", []) if c["result"] == "FAIL"]
    lint_warn = [c for c in lint_rep.get("checks", []) if c["result"] == "WARN"]

    rows = [
        ("Step count", f"{len(steps)} found, {len(tsteps)} true", f"within {MAX_STEP_DIFF}",
         abs(len(steps) - len(tsteps)) <= MAX_STEP_DIFF),
        ("Mean boundary error", fmt(mean_err), f"<= {MAX_MEAN_BOUNDARY_S:.1f} s",
         mean_err is not None and mean_err <= MAX_MEAN_BOUNDARY_S),
        ("Transcript WER", f"{rate:.1%} ({n_err} of {n_ref} words)", f"<= {MAX_WER:.0%}", rate <= MAX_WER),
        ("Caption timing", "no transcript" if drift_mean is None else
         f"mean {drift_mean:.2f} s, max {drift_max:.2f} s into silence", f"mean <= {MAX_CAPTION_DRIFT_S:.1f} s",
         drift_mean is not None and drift_mean <= MAX_CAPTION_DRIFT_S),
        ("Lint", f"{lint_rep.get('result')}: {len(lint_fail)} FAIL, {len(lint_warn)} WARN", "no FAIL",
         not lint_fail),
        ("Claude cost", "unknown" if cost is None else f"${cost:.4f} in {calls} calls", f"<= ${MAX_COST_USD:.2f}",
         cost is not None and cost <= MAX_COST_USD),
        ("Captions per clip", "all clips" if not no_caption else f"empty: steps {no_caption}", "every clip",
         not no_caption),
        ("Color words in questions", "none" if not colored else
         "; ".join(f"step {n}: {', '.join(c)}" for n, c in colored.items()), "none", not colored),
        ("Step 1 manual", steps[0].get("check_type", "?"), "manual", steps[0].get("check_type") == "manual"),
        ("Flip step common_mistake", "no step overlaps it" if flip is None else
         f"step {flip['n']}: {'present' if flip.get('common_mistake') else 'missing'}", "present",
         bool(flip and flip.get("common_mistake"))),
    ]
    return {"lesson": lesson, "extraction": extraction, "rows": rows, "errors": errs, "mean": mean_err,
            "max": max_err, "wer": rate, "reference": reference, "hypothesis": hypothesis, "captions": captions,
            "drift": drift, "lint": lint_rep, "stages": stages, "cost": cost, "calls": calls,
            "passed": all(r[3] for r in rows)}


# ---------------------------------------------------------------- 4. report

def table(rows: list[tuple]) -> str:
    out = ["| Check | Value | Threshold | Result |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {'PASS' if ok else 'FAIL'} |" for a, b, c, ok in rows]
    return "\n".join(out)


def report(res: dict, truth: dict, whisper_model: str, claude_model: str, take: Path) -> str:
    st = res["stages"]
    tsteps = truth["steps"]
    lesson_steps = res["lesson"]["steps"]
    lines = [
        f"# Teach end-to-end test, {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"Result: **{'PASS' if res['passed'] else 'FAIL'}**",
        "",
        f"- Input: {truth['duration']:.1f} s synthetic take ({W}x{H} {FPS} fps), {len(tsteps)} steps, voice "
        f"{truth['voice']}, seed {truth['seed']}. Pillow drawings and `say` narration, not real footage.",
        f"- Pipeline: `python -m server.teach` with Claude ({claude_model}) and local Whisper ({whisper_model}).",
        f"- Take: {take}",
        "",
        "## Checks",
        "",
        table(res["rows"]),
        "",
        "## Steps, truth vs found",
        "",
        "| n | True span | Spoken | Found span | Start error | Found title | Check | Question |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i in range(max(len(tsteps), len(lesson_steps))):
        t = tsteps[i] if i < len(tsteps) else None
        f = lesson_steps[i] if i < len(lesson_steps) else None
        err = res["errors"][i - 1] if 1 <= i <= len(res["errors"]) else None
        lines.append(" | ".join([
            f"| {i + 1}",
            f"{t['start']:.1f} to {t['end']:.1f}" if t else "",
            t["text"] if t else "",
            f"{parse_time(f['start']):.1f} to {parse_time(f['end']):.1f}" if f else "",
            fmt(err) if i else "first",
            f["title"] if f else "",
            f["check_type"] if f else "",
            (f.get("check_question") or "") + " |" if f else " |",
        ]))
    lines += [
        "",
        f"Boundary error over the {len(res['errors'])} true boundaries: "
        f"mean {fmt(res['mean'])}, max {fmt(res['max'])}.",
        "",
        "## Stage timings",
        "",
        "| Stage | Seconds |",
        "|---|---|",
        f"| Normalize | {fmt(st['normalize'], '')} |",
        f"| Proxy and frames{'' if st['download'] is not None else ' (and speech model load)'} "
        f"| {fmt(st['prep'], '')} |",
        f"| Speech model download and load | {fmt(st['download'], '') if st['download'] is not None else 'cached'} |",
        f"| Transcribe | {fmt(st['transcribe'], '')} |",
        f"| Claude | {fmt(st['claude'], '')} |",
        f"| Cut | {fmt(st['cut'], '')} |",
        f"| Total | {fmt(st['total'], '')} |",
        "",
        "## Common mistakes",
        "",
    ]
    lines += [f"- Step {s['n']} ({s['title']}): {s['common_mistake']}" for s in lesson_steps if s.get("common_mistake")]
    lines += ["", "## Captions (first three clips)", ""]
    for s, cues in list(zip(lesson_steps, res["captions"]))[:3]:
        lines.append(f"- Clip {s['n']:02d}: " + (" / ".join(cues) if cues else "(empty)"))
    lines += ["", "## Transcript", "", f"- Spoken: {res['reference']}", f"- Heard: {res['hypothesis']}", "",
              "| Segment start | End | Into silence | Text |", "|---|---|---|---|"]
    lines += [f"| {seg['start']:.2f} | {seg['end']:.2f} | {d:.2f} s | {seg['text']} |"
              for seg, d in zip(res["extraction"].get("transcript") or [], res["drift"])]
    lines += ["",
              "## Lint", "", f"{res['lint'].get('result')}, counts {res['lint'].get('counts')}", ""]
    lines += [f"- {c['check']}: {c['result']} {c['detail']}" for c in res["lint"].get("checks", [])
              if c["result"] != "OK"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main

def write_report(res: dict, truth: dict, whisper_model: str, take: Path) -> Path:
    sys.path.insert(0, str(REPO))
    from server import config

    text = report(res, truth, whisper_model, str(config.get("HANDOVER_CLAUDE_TEACH_MODEL")), take)
    OUT.mkdir(exist_ok=True)
    path = OUT / f"teach-e2e-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(text, encoding="utf-8")
    print()
    width = max(len(r[0]) for r in res["rows"])
    for name, value, limit, ok in res["rows"]:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {value}  (threshold {limit})")
    print("  stages: " + ", ".join(f"{k} {fmt(v)}" for k, v in res["stages"].items() if v is not None))
    print(f"\n{'PASS' if res['passed'] else 'FAIL'}. Report: {path}")
    return path


def rescore(work: Path, whisper_model: str) -> int:
    lesson_dir, truth_path = work / "lessons" / LESSON_ID, work / "ground_truth.json"
    if not (lesson_dir / "lesson.json").is_file() or not truth_path.is_file():
        print(f"setup: {work} needs ground_truth.json and lessons/{LESSON_ID}/lesson.json", file=sys.stderr)
        return 2
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    res = score(truth, lesson_dir, stage_times([], 0.0), None, None)
    write_report(res, truth, f"{whisper_model} (rescored, model not verified)", work / "take.mp4")
    return 0 if res["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="teach_e2e.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", action="store_true", help="keep the temp folder with the take and the lesson")
    ap.add_argument("--whisper-model", default=os.environ.get("HANDOVER_WHISPER_MODEL") or "small.en")
    ap.add_argument("--take", type=Path, help="reuse take.mp4 and ground_truth.json from this folder")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--voice", default="Samantha")
    ap.add_argument("--max-load", type=int, default=24, help="wait while the 5 minute load average is above this")
    ap.add_argument("--quiet", action="store_true", help="do not echo the pipeline's progress lines")
    ap.add_argument("--rescore", type=Path, metavar="DIR", help="score the lesson of a kept run again, no calls")
    a = ap.parse_args(argv)
    if a.rescore:
        return rescore(a.rescore, a.whisper_model)

    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(SCRIPTS))
    work = Path(tempfile.mkdtemp(prefix="handover-teach-e2e-"))
    try:
        if not PY.is_file():
            raise SetupError(f"no virtualenv python at {PY}")
        from server import config, teach

        if not teach._anthropic_key():
            raise SetupError("no Anthropic key (ANTHROPIC_API_KEY or .env): the real path needs one")
        if a.take:
            take, truth_path = a.take / "take.mp4", a.take / "ground_truth.json"
            if not take.is_file() or not truth_path.is_file():
                raise SetupError(f"{a.take} needs take.mp4 and ground_truth.json")
            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            print(f"[take] reusing {take} ({truth['duration']:.1f} s)")
        else:
            if not shutil.which("say"):
                raise SetupError("macOS `say` is needed for the narration")
            wait_for_load(a.max_load)
            t0 = time.monotonic()
            print(f"[take] rendering {len(NARRATION)} steps at {W}x{H} {FPS} fps into {work}", flush=True)
            truth = build_take(work, a.seed, a.voice)
            take = work / "take.mp4"
            print(f"[take] {truth['duration']:.1f} s take in {time.monotonic() - t0:.1f} s; boundaries "
                  + ", ".join(f"{s['start']:.1f}" for s in truth["steps"][1:]), flush=True)

        lessons = work / "lessons"
        lessons.mkdir(exist_ok=True)
        before = spend_snapshot()
        wait_for_load(a.max_load)
        print(f"[teach] Claude {config.get('HANDOVER_CLAUDE_TEACH_MODEL')}, Whisper {a.whisper_model}", flush=True)
        rc, lines, total = run_teach(take, lessons, a.whisper_model, a.quiet)
        after = spend_snapshot()
        cost = calls = None
        if before and after:
            cost, calls = after["usd"] - before["usd"], after["calls"] - before["calls"]
        lesson_dir = lessons / LESSON_ID
        if rc != 0 or not (lesson_dir / "lesson.json").is_file():
            print(f"FAIL: server.teach exited {rc}; last lines:", file=sys.stderr)
            for _, line in lines[-8:]:
                print(f"  {line}", file=sys.stderr)
            return 1

        res = score(truth, lesson_dir, stage_times(lines, total), cost, calls)
        if calls is not None and calls != 1:
            print(f"[spend] note: the ledger counted {calls} calls during the run; another process may have "
                  f"spent at the same time, so the cost row is an upper bound", flush=True)
        write_report(res, truth, a.whisper_model, take)
        return 0 if res["passed"] else 1
    except SetupError as e:
        print(f"setup: {e}", file=sys.stderr)
        return 2
    finally:
        if a.keep:
            print(f"[keep] {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

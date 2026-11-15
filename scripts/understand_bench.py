"""Benchmark for real-time step understanding (server/understand.py) on synthetic fold renders.

    .venv/bin/python scripts/understand_bench.py [--n 3] [--max-usd 0.40] [--model claude-haiku-5-5]
        [--compare-model claude-sonnet-5-5 --compare-n 1] [--seed 2001] [--no-check]

What it renders (Pillow drawings from scripts/synth_folds.py, not photos; every number must be re-tested on
real footage):

  in-between states  real partial folds drawn with synth_folds' own Paper primitives: a corner flap lifted
                     part way (its top-down projection), 1, 2 or 3 of 4 corners folded, the sheet squashed
                     mid-flip. Step 8 (pockets) has no geometric model here: its one in-between frame is a 50%
                     alpha blend of states 7 and 8, a crude proxy, labeled "blend" in the results.
  injected mistakes   step 2 corners not lined up; step 4 only 3 corners folded; step 4 corners stopped short
                     of the center; step 5 flipped before the 4th corner was folded; step 6 corners short of
                     the center.

Every test frame is a jittered variant (rotation, scale, light, blur, sometimes a hand) with a seed the
lesson never used. The rubric is built by server.understand.build_rubric on a copy of the synthetic lesson
whose keyframes are START = the previous step's reference, MID = a clean in-between render, DONE = the step's
reference (an idealized expert video: the lesson's own video is static per step).

Measures, per model: progress monotonicity along each step's series, stage accuracy (expected stage is the
truth progress split evenly over the rubric's stages, so it is approximate), mistake detection and false
alarm rates at confidence >= 0.75, MistakeTracker live warnings on whole sequences, done accuracy against the
current check (check.check_frame, same frames), latency p50 and p90, and cost.

--max-usd is a hard stop: before every call it checks spend.allow() and the ledger's total since the run
started plus the priciest call so far. Writes scripts/out/understand-<ts>/ with the renders, the rubric of
each model, results.json and report.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import shutil
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

import synth_folds as sf  # noqa: E402
from PIL import Image  # noqa: E402

LESSON = REPO / "lessons" / "synthetic-fortune-teller-v1"
KEY_SEED = 7  # the lesson's renders
MIN_CONF = 0.8  # engine rule for a yes
MISTAKE_CONF = 0.75
FIRST_CALL_ESTIMATE_USD = 0.003
Pt = tuple[float, float]


# ---------------------------------------------------------------- partial fold geometry

def _flap_tip(corner: Pt, fa: Pt, fb: Pt, theta: float) -> Pt:
    """Top-down position of a corner lifted by theta degrees about the fold line fa-fb (180 = folded flat)."""
    dx, dy = fb[0] - fa[0], fb[1] - fa[1]
    t = ((corner[0] - fa[0]) * dx + (corner[1] - fa[1]) * dy) / (dx * dx + dy * dy)
    foot = (fa[0] + t * dx, fa[1] + t * dy)
    c = math.cos(math.radians(theta))
    return (foot[0] + (corner[0] - foot[0]) * c, foot[1] + (corner[1] - foot[1]) * c)


def _flap(paper: sf.Paper, corner: Pt, fa: Pt, fb: Pt, theta: float, front, back, gap: float = 0.035) -> None:
    """Under 90 degrees the flap still shows its top side (shaded as it tilts), past 90 its underside."""
    tip = _flap_tip(corner, fa, fb, theta)
    if abs(theta - 90) < 4:
        return  # edge-on: invisible from above
    color = sf.shade(front, 0.82 + 0.18 * math.cos(math.radians(theta))) if theta < 90 else back
    paper.flap([fa, fb, tip], color, gap=gap)


_SQ_CORNERS: list[Pt] = [(1, 1), (-1, 1), (-1, -1), (1, -1)]  # counter-clockwise
_DIAMOND: list[Pt] = [(1, 0), (0, 1), (-1, 0), (0, -1)]


def _square_folds(paper: sf.Paper, folds: dict[int, float], level: float = 1.0, base=sf.YELLOW, flap=sf.BLUE,
                  crease: bool = True, mirror: bool = False) -> list[Pt]:
    """The 2 x 2 sheet with corners folded toward the center. folds maps corner index to theta (180 = flat).
    level 1 lands the corner on the center; more than 1 stops it short. Returns the outline."""
    outline: list[Pt] = []
    lines = {}
    for i, (cx, cy) in enumerate(_SQ_CORNERS):
        if i not in folds:
            outline.append((cx, cy))
            continue
        fa, fb = (cx, cy * (level - 1)), (cx * (level - 1), cy)
        lines[i] = (fa, fb)
        outline += [fa, fb] if i % 2 == 0 else [fb, fa]
    if mirror:
        outline = [(-x, y) for x, y in outline]
    paper.face(outline, base)
    if crease:
        paper.crease((-1, -1), (1, 1), 0.9 if not mirror else 0.5)
        paper.crease((-1, 1), (1, -1), 0.9 if not mirror else 0.5)
    for i, theta in folds.items():
        fa, fb = lines[i]
        _flap(paper, _SQ_CORNERS[i], fa, fb, theta, base, flap)
    return outline


def _diamond_folds(paper: sf.Paper, folds: dict[int, float], h: float = 0.5) -> list[Pt]:
    """State 5 (plain blue diamond) with corners folded toward the center about the line at distance h."""
    outline: list[Pt] = []
    lines = {}
    for i, (cx, cy) in enumerate(_DIAMOND):
        if i not in folds:
            outline.append((cx, cy))
            continue
        px, py = -cy, cx
        fa = (cx * h + px * (1 - h), cy * h + py * (1 - h))
        fb = (cx * h - px * (1 - h), cy * h - py * (1 - h))
        lines[i] = (fa, fb)
        outline += [fb, fa]
    paper.face(outline, sf.BLUE)
    paper.crease((0.5, 0.5), (-0.5, -0.5), 0.6)
    paper.crease((-0.5, 0.5), (0.5, -0.5), 0.6)
    for i, theta in folds.items():
        fa, fb = lines[i]
        _flap(paper, _DIAMOND[i], fa, fb, theta, sf.BLUE, sf.BLUE)
    return outline


def _squash(paper: sf.Paper, f: float) -> None:
    """Mid-flip: the sheet turns about the vertical axis, so from above it is f times as wide."""
    w = max(8, int(sf.PS * f))
    for name in ("rgb", "alpha"):
        img = getattr(paper, name)
        small = img.resize((w, sf.PS), Image.BICUBIC)
        canvas = Image.new(img.mode, (sf.PS, sf.PS), 0)
        canvas.paste(small, ((sf.PS - w) // 2, 0))
        setattr(paper, name, canvas)


def _draw_fold2(theta: float):
    def draw(paper: sf.Paper) -> float:
        paper.face([(-1, -1), (1, -1), (-1, 1)], sf.YELLOW)
        _flap(paper, (1, 1), (1, -1), (-1, 1), theta, sf.YELLOW, sf.BLUE, gap=0.012)
        return 1.0 + 1.5 * math.sin(math.radians(theta))
    return draw


def _draw_misaligned2(paper: sf.Paper) -> float:
    """Folded flat but along x + y = 0.25 instead of the diagonal: yellow strips and a corner stick out."""
    paper.face([(-1, -1), (1, -1), (1, -0.75), (-0.75, 1), (-1, 1)], sf.YELLOW)
    _flap(paper, (1, 1), (1, -0.75), (-0.75, 1), 180, sf.YELLOW, sf.BLUE, gap=0.012)
    return 1.3


def _draw_square(folds: dict[int, float], level: float = 1.0):
    def draw(paper: sf.Paper) -> float:
        _square_folds(paper, folds, level)
        return 1.4 + (1.2 if any(t < 175 for t in folds.values()) else 0)
    return draw


def _draw_early_flip(paper: sf.Paper) -> float:
    """Step 4 left with 3 corners folded, then flipped: the plain blue back, one square corner sticking out."""
    from PIL import ImageDraw

    pts: list[Pt] = []
    for i, (cx, cy) in enumerate(_SQ_CORNERS):
        if i == 0:  # the corner left open
            pts.append((cx, cy))
        else:
            fa, fb = (cx, 0.0), (0.0, cy)
            pts += [fa, fb] if i % 2 == 0 else [fb, fa]
    pts = [(-x, y) for x, y in pts]  # the flip mirrors it
    paper.face(pts, sf.BLUE)
    paper.crease((0.5, 0.5), (-0.5, -0.5), 0.6)
    paper.crease((-0.5, 0.5), (0.5, -0.5), 0.6)
    for a, b in zip(pts, pts[1:] + pts[:1]):  # the edges are folds: a slightly lit rim, as in state 5
        ImageDraw.Draw(paper.rgb).line(sf.poly([a, b]), fill=sf.shade(sf.BLUE, 1.1), width=3)
    return 1.4


def _draw_flip(state: int, f: float):
    def draw(paper: sf.Paper) -> float:
        _ORIG_DRAW(state, paper)
        _squash(paper, f)
        return 3.0
    return draw


def _draw_diamond(folds: dict[int, float], h: float = 0.5):
    def draw(paper: sf.Paper) -> float:
        _diamond_folds(paper, folds, h)
        return 1.5 + (1.0 if any(t < 175 for t in folds.values()) else 0)
    return draw


_ORIG_DRAW = sf.draw_state
CUSTOM: dict[str, tuple[int, Callable[[sf.Paper], float], list[Pt]]] = {}


def _register(key: str, code: int, draw: Callable[[sf.Paper], float], outline: list[Pt]) -> None:
    CUSTOM[key] = (code, draw, outline)
    sf.OUTLINES[key] = outline  # type: ignore[index]  # where a hand may reach in


def _draw_any(state, paper):
    if isinstance(state, str):
        return CUSTOM[state][1](paper)
    return _ORIG_DRAW(state, paper)


sf.draw_state = _draw_any  # compose() looks draw_state up at call time

_SQ = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
_DM = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
_register("s2_lift60", 201, _draw_fold2(60), _SQ)
_register("s2_lift100", 202, _draw_fold2(100), _SQ)
_register("s2_lift135", 203, _draw_fold2(135), _SQ)
_register("s2_misaligned", 204, _draw_misaligned2, _SQ)
_register("s4_one", 401, _draw_square({0: 180}), _SQ)
_register("s4_two", 402, _draw_square({0: 180, 2: 180}), _SQ)
_register("s4_three_lift", 403, _draw_square({0: 180, 1: 180, 2: 180, 3: 120}), _SQ)
_register("s4_three", 404, _draw_square({0: 180, 1: 180, 2: 180}), _SQ)
_register("s4_short", 405, _draw_square({0: 180, 1: 180, 2: 180, 3: 180}, level=1.3), _SQ)
_register("s5_flip_a", 501, _draw_flip(4, 0.45), _DM)
_register("s5_flip_b", 502, _draw_flip(5, 0.45), _DM)
_register("s5_flip_mid", 503, _draw_flip(5, 0.3), _DM)
_register("s5_early", 504, _draw_early_flip, _SQ)
_register("s6_one", 601, _draw_diamond({0: 180}), _DM)
_register("s6_two", 602, _draw_diamond({0: 180, 2: 180}), _DM)
_register("s6_three_lift", 603, _draw_diamond({0: 180, 1: 180, 2: 180, 3: 120}), _DM)
_register("s6_short", 604, _draw_diamond({0: 180, 1: 180, 2: 180, 3: 180}, h=0.65), _DM)


def render(key, variant: Optional[int], seed: int, size=sf.SIZE, hand_rate: float = 0.3) -> Image.Image:
    """key: a synth_folds state (int), a CUSTOM key, or ("blend", a, b, w). variant None = clean."""
    if isinstance(key, tuple) and key[0] == "blend":
        _, a, b, w = key
        return Image.blend(render(a, variant, seed, size, hand_rate), render(b, variant, seed, size, hand_rate), w)
    code = key if isinstance(key, int) else CUSTOM[key][0]
    if variant is None:
        p = sf.Params(paper_seed=seed * 100 + code)
    else:
        p = sf.jitter_params(code, seed, variant, hand_rate)
    scene = seed * 7919 + code * 101 + (-1 if variant is None else variant)
    return sf.compose(key, p, size, scene)


# ---------------------------------------------------------------- plan

@dataclass
class Frame:
    step: int
    name: str
    key: object
    progress: Optional[float]  # truth; None for injected mistakes
    kind: str  # series or mistake
    proxy: str = "geometry"  # geometry, blend, or state (a finished synth_folds state)


SERIES: dict[int, list[tuple[str, object, float, str]]] = {
    2: [("start", 1, 0.0, "state"), ("lift60", "s2_lift60", 0.33, "geometry"),
        ("lift135", "s2_lift135", 0.75, "geometry"), ("done", 2, 1.0, "state")],
    4: [("start", 3, 0.0, "state"), ("one", "s4_one", 0.25, "geometry"), ("two", "s4_two", 0.5, "geometry"),
        ("three_lift", "s4_three_lift", 0.85, "geometry"), ("done", 4, 1.0, "state")],
    5: [("start", 4, 0.0, "state"), ("flip_a", "s5_flip_a", 0.35, "geometry"),
        ("flip_b", "s5_flip_b", 0.65, "geometry"), ("done", 5, 1.0, "state")],
    6: [("start", 5, 0.0, "state"), ("one", "s6_one", 0.25, "geometry"), ("two", "s6_two", 0.5, "geometry"),
        ("three_lift", "s6_three_lift", 0.85, "geometry"), ("done", 6, 1.0, "state")],
    8: [("start", 7, 0.0, "state"), ("blend", ("blend", 7, 8, 0.5), 0.5, "blend"), ("done", 8, 1.0, "state")],
}
MID_KEY: dict[int, object] = {2: "s2_lift100", 4: "s4_two", 5: "s5_flip_mid", 6: "s6_two", 8: ("blend", 7, 8, 0.5)}
MISTAKES: dict[int, list[tuple[str, str]]] = {
    2: [("misaligned", "s2_misaligned")],
    4: [("three_corners", "s4_three"), ("short_of_center", "s4_short")],
    5: [("flipped_early", "s5_early")],
    6: [("short_of_center", "s6_short")],
}


def plan() -> list[Frame]:
    frames = []
    for step, series in SERIES.items():
        frames += [Frame(step, name, key, p, "series", proxy) for name, key, p, proxy in series]
        frames += [Frame(step, name, key, None, "mistake") for name, key in MISTAKES.get(step, [])]
    return frames


def write_lesson(out: Path) -> Path:
    """Copy of the synthetic lesson (lesson.json, extraction.json, frames) with bench keyframes NN_a/b/c."""
    dst = out / "lesson"
    (dst / "frames").mkdir(parents=True, exist_ok=True)
    for name in ("lesson.json", "extraction.json"):
        shutil.copy2(LESSON / name, dst / name)
    for f in (LESSON / "frames").glob("[0-9][0-9].jpg"):
        shutil.copy2(f, dst / "frames" / f.name)
    for step in SERIES:
        shutil.copy2(LESSON / "frames" / f"{step - 1:02d}.jpg", dst / "frames" / f"{step:02d}_a.jpg")
        sf_img = render(MID_KEY[step], None, KEY_SEED, (1920, 1080))
        (dst / "frames" / f"{step:02d}_b.jpg").write_bytes(sf.to_jpeg(sf_img))
        shutil.copy2(LESSON / "frames" / f"{step:02d}.jpg", dst / "frames" / f"{step:02d}_c.jpg")
    return dst


def write_frames(out: Path, frames: list[Frame], n: int, seed: int) -> dict[tuple[str, int, int], Path]:
    files = {}
    d = out / "frames"
    d.mkdir(parents=True, exist_ok=True)
    for f in frames:
        for i in range(n):
            p = d / f"s{f.step}_{f.kind}_{f.name}_v{i:02d}.jpg"
            if not p.exists():
                p.write_bytes(sf.to_jpeg(render(f.key, i, seed)))
            files[(f"{f.step}:{f.kind}:{f.name}", f.step, i)] = p
    return files


# ---------------------------------------------------------------- run

@dataclass
class Row:
    model: str
    step: int
    frame: str
    kind: str
    proxy: str
    variant: int
    truth_progress: Optional[float]
    stage: int = -1
    n_stages: int = 0
    progress: float = 0.0
    done: str = "unsure"
    confidence: float = 0.0
    mistake: Optional[str] = None
    mistake_confidence: float = 0.0
    seen: Optional[str] = None
    reason: Optional[str] = None
    latency_ms: int = 0
    cost_usd: float = 0.0
    cache_read: int = 0
    error: Optional[str] = None
    check_done: Optional[str] = None
    check_confidence: float = 0.0
    check_latency_ms: int = 0
    check_cost_usd: float = 0.0
    check_error: Optional[str] = None
    extra: dict = field(default_factory=dict)


async def run_model(model: str, lesson_dir: Path, frames: list[Frame], files: dict, n: int, budget,
                    with_check: bool, rubric: dict, log: Callable[[str], None]) -> tuple[list[Row], Optional[str]]:
    from server import check, understand

    lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    by_n = {s["n"]: s for s in lesson["steps"]}
    rows: list[Row] = []
    for step in SERIES:
        entry = understand.step_entry(rubric, step)
        if entry is None:
            log(f"{model}: no rubric entry for step {step}; skipped")
            continue
        keys = understand.read_keyframes(lesson_dir, entry)
        ref = (lesson_dir / by_n[step]["ref_frame"]).read_bytes()
        prev = (lesson_dir / by_n[step - 1]["ref_frame"]).read_bytes()
        q = by_n[step]["check_question"]
        for i in range(n):
            for f in (x for x in frames if x.step == step):
                why = budget.stop_reason()
                if why:
                    return rows, why
                live = files[(f"{f.step}:{f.kind}:{f.name}", f.step, i)].read_bytes()
                u = await understand.understand_frame(entry, keys, live, prev, model=model)
                budget.note(u.cost_usd)
                r = Row(model, step, f.name, f.kind, f.proxy, i, f.progress, u.stage, len(entry["stages"]),
                        u.progress, u.done, u.confidence, u.mistake, u.mistake_confidence, u.seen, u.reason,
                        u.latency_ms, u.cost_usd, u.cache_read_tokens, u.error)
                if with_check:
                    why = budget.stop_reason()
                    if why:
                        rows.append(r)
                        return rows, why
                    c = await check.check_frame(ref, live, q, prev_ref=prev)
                    budget.note(c.cost_usd)
                    r.check_done, r.check_confidence, r.check_latency_ms = c.done, c.confidence, c.latency_ms
                    r.check_cost_usd, r.check_error = c.cost_usd, c.error
                rows.append(r)
                chk = f"  check {r.check_done} {r.check_confidence:.2f}" if with_check else ""
                log(f"{model} s{step} {f.kind:7s} {f.name:16s} v{i}  {u.done:6s} {u.confidence:.2f}  stage {u.stage}"
                    f"/{len(entry['stages'])}  prog {u.progress:.2f}  mistake {u.mistake} {u.mistake_confidence:.2f}"
                    f"  {u.latency_ms} ms{chk}{'  ' + u.error if u.error else ''}")
    return rows, None


# ---------------------------------------------------------------- metrics

def pct(vals: list[int], q: float) -> Optional[int]:
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def expected_stage(p: float, n_stages: int) -> int:
    """Truth progress split evenly over the stages: 0 is not started (-1), 1 is the last stage."""
    if p <= 0:
        return -1
    return max(0, min(n_stages - 1, math.ceil(p * n_stages) - 1))


def engine_yes(done: Optional[str], conf: float) -> bool:
    return done == "yes" and conf >= MIN_CONF


def metrics(rows: list[Row], tracker_factory: Callable) -> dict:
    ok = [r for r in rows if not r.error]
    series = [r for r in ok if r.kind == "series"]
    mistakes = [r for r in ok if r.kind == "mistake"]
    out: dict = {"calls": len(rows), "errors": len(rows) - len(ok)}
    # progress monotonicity, per (step, variant) series in truth order
    pairs = mono = full = n_series = 0
    abs_err = []
    for (step, v) in sorted({(r.step, r.variant) for r in series}):
        seq = sorted((r for r in series if r.step == step and r.variant == v), key=lambda r: r.truth_progress)
        if len(seq) < 2:
            continue
        n_series += 1
        good = 0
        for a, b in zip(seq, seq[1:]):
            pairs += 1
            if b.progress >= a.progress - 0.05:
                good += 1
        mono += good
        full += good == len(seq) - 1
        abs_err += [abs(r.progress - r.truth_progress) for r in seq]
    out["progress_pairs_monotonic"] = (mono, pairs)
    out["series_fully_monotonic"] = (full, n_series)
    out["progress_mae"] = round(statistics.mean(abs_err), 3) if abs_err else None
    # stages
    exact = near = 0
    for r in series:
        e = expected_stage(r.truth_progress, r.n_stages)
        exact += r.stage == e
        near += abs(r.stage - e) <= 1
    out["stage_exact"] = (exact, len(series))
    out["stage_within_1"] = (near, len(series))
    starts = [r for r in series if r.truth_progress == 0]
    dones = [r for r in series if r.truth_progress == 1]
    out["stage_start_not_started"] = (sum(r.stage == -1 for r in starts), len(starts))
    out["stage_done_last"] = (sum(r.stage == r.n_stages - 1 for r in dones), len(dones))
    # mistakes per frame
    flagged = lambda r: r.mistake is not None and r.mistake_confidence >= MISTAKE_CONF  # noqa: E731
    out["mistake_detected"] = (sum(flagged(r) for r in mistakes), len(mistakes))
    out["mistake_false_alarm"] = (sum(flagged(r) for r in series), len(series))
    out["mistake_threshold_sweep"] = {
        str(th): {"detected": (sum(r.mistake is not None and r.mistake_confidence >= th for r in mistakes),
                               len(mistakes)),
                  "false_alarm": (sum(r.mistake is not None and r.mistake_confidence >= th for r in series),
                                  len(series))}
        for th in (0.5, 0.6, 0.75, 0.9)}
    out["mistake_false_alarm_inbetween"] = (sum(flagged(r) for r in series if 0 < r.truth_progress < 1),
                                            sum(1 for r in series if 0 < r.truth_progress < 1))
    # tracker on sequences
    fires_clean = n_clean = 0
    for (step, v) in sorted({(r.step, r.variant) for r in series}):
        seq = sorted((r for r in series if r.step == step and r.variant == v), key=lambda r: r.truth_progress)
        t = tracker_factory(step)
        n_clean += 1
        fires_clean += any(t.feed(_as_result(r), 2.0 * k) for k, r in enumerate(seq))
    fired = total = 0
    labels: dict[str, list] = {}
    for (step, name) in sorted({(r.step, r.frame) for r in mistakes}):
        seq = sorted((r for r in mistakes if r.step == step and r.frame == name), key=lambda r: r.variant)
        start = next((r for r in series if r.step == step and r.truth_progress == 0 and r.variant == 0), None)
        t = tracker_factory(step)
        total += 1
        msgs = [t.feed(_as_result(r), 2.0 * k) for k, r in enumerate(([start] if start else []) + seq)]
        hit = [m for m in msgs if m]
        fired += bool(hit)
        labels[f"s{step} {name}"] = [r.mistake for r in seq]
    out["tracker_fired_on_injected"] = (fired, total)
    out["tracker_false_fire_on_clean_series"] = (fires_clean, n_clean)
    out["mistake_labels_seen"] = labels
    # done vs check
    def done_stats(get) -> dict:
        d = {"done_yes": (sum(get(r) for r in dones), len(dones))}
        not_done = [r for r in ok if not (r.kind == "series" and r.truth_progress == 1)]
        d["false_pass_all"] = (sum(get(r) for r in not_done), len(not_done))
        d["false_pass_inbetween"] = (sum(get(r) for r in series if 0 < r.truth_progress < 1),
                                     sum(1 for r in series if 0 < r.truth_progress < 1))
        d["false_pass_mistake"] = (sum(get(r) for r in mistakes), len(mistakes))
        return d
    out["understand_done"] = done_stats(lambda r: engine_yes(r.done, r.confidence))
    checked = [r for r in ok if r.check_done is not None and not r.check_error]
    if checked:
        out["check_done"] = done_stats(lambda r: engine_yes(r.check_done, r.check_confidence))
        out["check_latency_p50"] = pct([r.check_latency_ms for r in checked], 0.5)
        out["check_latency_p90"] = pct([r.check_latency_ms for r in checked], 0.9)
        out["check_cost_usd"] = round(sum(r.check_cost_usd for r in rows), 5)
        out["check_errors"] = sum(1 for r in rows if r.check_error)
    lat = [r.latency_ms for r in ok]
    out["latency_p50"], out["latency_p90"] = pct(lat, 0.5), pct(lat, 0.9)
    out["cost_usd"] = round(sum(r.cost_usd for r in rows), 5)
    out["cost_per_call_usd"] = round(out["cost_usd"] / len(rows), 6) if rows else None
    out["cache_read_median"] = statistics.median([r.cache_read for r in ok]) if ok else None
    return out


def _as_result(r: Row):
    from types import SimpleNamespace

    return SimpleNamespace(error=r.error, mistake=r.mistake, mistake_confidence=r.mistake_confidence, stage=r.stage)


def frac(t) -> str:
    a, b = t
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def report(meta: dict, results: dict[str, dict], subsets: dict[str, dict]) -> str:
    lines = [f"# Understanding benchmark, {meta['when']}", "",
             "Synthetic Pillow renders, not photos. Re-test on real footage before trusting any number.", "",
             f"- Variants per frame: {meta['n']} (seed {meta['seed']}), frames per variant: {meta['frames']}",
             f"- Spend cap ${meta['max_usd']:.2f}; ledger delta for the whole run ${meta['spent']:.4f}"
             + (f"; stopped early: {meta['stopped']}" if meta.get("stopped") else ""), ""]

    def table(res: dict[str, dict]) -> list[str]:
        models = list(res)
        rows = [("calls (errors)", lambda m: f"{m['calls']} ({m['errors']})"),
                ("progress pairs monotonic", lambda m: frac(m["progress_pairs_monotonic"])),
                ("series fully monotonic", lambda m: frac(m["series_fully_monotonic"])),
                ("progress mean abs error", lambda m: str(m["progress_mae"])),
                ("stage exact (approximate truth)", lambda m: frac(m["stage_exact"])),
                ("stage within 1", lambda m: frac(m["stage_within_1"])),
                ("start frame: stage -1", lambda m: frac(m["stage_start_not_started"])),
                ("done frame: last stage", lambda m: frac(m["stage_done_last"])),
                ("mistake detected per frame (conf >= 0.75)", lambda m: frac(m["mistake_detected"])),
                ("mistake false alarm, clean frames", lambda m: frac(m["mistake_false_alarm"])),
                ("  of which in-between frames", lambda m: frac(m["mistake_false_alarm_inbetween"])),
                ("tracker fired on injected sequence", lambda m: frac(m["tracker_fired_on_injected"])),
                ("tracker false fire on clean series", lambda m: frac(m["tracker_false_fire_on_clean_series"])),
                ("done: yes on done frames (understand)", lambda m: frac(m["understand_done"]["done_yes"])),
                ("done: false pass, all others (understand)", lambda m: frac(m["understand_done"]["false_pass_all"])),
                ("  in-between (understand)", lambda m: frac(m["understand_done"]["false_pass_inbetween"])),
                ("  injected mistakes (understand)", lambda m: frac(m["understand_done"]["false_pass_mistake"])),
                ("done: yes on done frames (current check)",
                 lambda m: frac(m["check_done"]["done_yes"]) if "check_done" in m else "-"),
                ("done: false pass, all others (current check)",
                 lambda m: frac(m["check_done"]["false_pass_all"]) if "check_done" in m else "-"),
                ("  in-between (current check)",
                 lambda m: frac(m["check_done"]["false_pass_inbetween"]) if "check_done" in m else "-"),
                ("  injected mistakes (current check)",
                 lambda m: frac(m["check_done"]["false_pass_mistake"]) if "check_done" in m else "-"),
                ("latency p50 / p90 ms (understand)", lambda m: f"{m['latency_p50']} / {m['latency_p90']}"),
                ("latency p50 / p90 ms (current check)",
                 lambda m: f"{m.get('check_latency_p50')} / {m.get('check_latency_p90')}" if "check_done" in m else "-"),
                ("cost understand total / per call", lambda m: f"${m['cost_usd']:.4f} / ${m['cost_per_call_usd']:.6f}"),
                ("cost current check total", lambda m: f"${m['check_cost_usd']:.4f}" if "check_done" in m else "-"),
                ("cache read tokens, median", lambda m: str(m["cache_read_median"]))]
        out = ["| Metric | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
        for name, fn in rows:
            out.append(f"| {name} | " + " | ".join(fn(res[k]) for k in models) + " |")
        return out

    lines += ["## All variants", ""] + table(results) + [""]
    if subsets:
        lines += ["## Same variant subset for every model", ""] + table(subsets) + [""]
    lines += ["## Mistake confidence threshold sweep (per frame)", "",
              "| Model | threshold | detected | false alarm on clean frames |", "|---|---|---|---|"]
    for model, res in results.items():
        for th, v in res["mistake_threshold_sweep"].items():
            lines.append(f"| {model} | {th} | {frac(v['detected'])} | {frac(v['false_alarm'])} |")
    lines += [""]
    lines += ["## Rubric cost", ""] + [f"- {m}: ${c:.4f}" for m, c in meta["rubric_cost"].items()] + [""]
    lines += ["## Mistake labels per injected sequence (variant order)", ""]
    for model, res in results.items():
        for k, v in res["mistake_labels_seen"].items():
            lines.append(f"- {model} {k}: {v}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main

async def amain(a) -> int:
    from accuracy import Budget
    from server import spend, understand

    os.environ.pop("HANDOVER_CHECK", None)
    os.environ["HANDOVER_CHECK_PROVIDER"] = "claude"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = a.out or (SCRIPTS / "out" / f"understand-{ts}")
    out.mkdir(parents=True, exist_ok=True)
    frames = plan()
    n_max = max(a.n, a.compare_n if a.compare_model else 0)
    print(f"rendering {len(frames)} frames x {n_max} variants into {out}", flush=True)
    lesson_dir = write_lesson(out)
    files = write_frames(out, frames, n_max, a.seed)
    budget = Budget(a.max_usd, status=spend.status)
    budget.priciest = FIRST_CALL_ESTIMATE_USD
    log_lines: list[str] = []

    def log(s: str) -> None:
        log_lines.append(s)
        print(s, flush=True)

    arms = [(a.model, a.n, not a.no_check)]
    if a.compare_model:
        arms.append((a.compare_model, a.compare_n, False))
    all_rows: dict[str, list[Row]] = {}
    rubric_cost: dict[str, float] = {}
    stopped = None
    for model, n, with_check in arms:
        why = budget.stop_reason()
        if why:
            stopped = why
            break
        mdir = out / f"lesson-{model}"
        if mdir.exists():
            shutil.rmtree(mdir)
        shutil.copytree(lesson_dir, mdir)
        t0 = time.monotonic()
        try:
            rubric = await understand.build_rubric(mdir, model=model, resample=False,
                                                   progress=lambda s, m: log(f"[{s}] {m}"))
        except RuntimeError as e:
            log(f"{model}: rubric failed: {e}")
            continue
        rubric_cost[model] = rubric["cost_usd"]
        budget.note(min(rubric["cost_usd"], 0.0))  # the rubric is a one-off; keep priciest = live calls
        log(f"{model}: rubric in {time.monotonic() - t0:.1f} s, ${rubric['cost_usd']:.4f}")
        rows, why = await run_model(model, mdir, frames, files, n, budget, with_check, rubric, log)
        all_rows[model] = rows
        if why:
            stopped = why
            log(f"stopped: {why}")
            break

    def factory_for(model: str):
        rub = understand.load_rubric(out / f"lesson-{model}")

        def make(step: int):
            t = understand.MistakeTracker(min_conf=MISTAKE_CONF, repeat=2, clear_after=2, cooldown_s=8.0)
            t.start_step(step, understand.step_entry(rub, step))
            return t
        return make

    results = {m: metrics(rows, factory_for(m)) for m, rows in all_rows.items() if rows}
    subsets = {}
    if len(results) > 1:
        k = min(a.compare_n, a.n)
        subsets = {m: metrics([r for r in rows if r.variant < k], factory_for(m)) for m, rows in all_rows.items()
                   if rows}
    meta = {"when": ts, "n": a.n, "seed": a.seed, "frames": len(frames), "max_usd": a.max_usd,
            "spent": budget.spent(), "stopped": stopped, "rubric_cost": rubric_cost,
            "compare_model": a.compare_model, "compare_n": a.compare_n}
    (out / "results.json").write_text(json.dumps(
        {"meta": meta, "metrics": results, "subset_metrics": subsets,
         "rows": {m: [asdict(r) for r in rows] for m, rows in all_rows.items()}}, indent=1), encoding="utf-8")
    md = report(meta, results, subsets)
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "log.txt").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(md)
    print(f"wrote {out}")
    return 0 if results else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=3, help="jittered variants per frame")
    ap.add_argument("--max-usd", type=float, default=0.40, help="hard cap for the whole run (ledger delta)")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--compare-model", default=None, help="second model, understand only (e.g. claude-sonnet-5-5)")
    ap.add_argument("--compare-n", type=int, default=1, help="variants for the second model")
    ap.add_argument("--seed", type=int, default=2001)
    ap.add_argument("--no-check", action="store_true", help="skip the current check baseline")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--render-only", action="store_true", help="write the renders and keyframes, make no call")
    a = ap.parse_args(argv)
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    if a.render_only:
        out = a.out or (SCRIPTS / "out" / "understand-renders")
        write_lesson(out)
        write_frames(out, plan(), a.n, a.seed)
        print(f"wrote renders to {out}")
        return 0
    return asyncio.run(amain(a))


if __name__ == "__main__":
    sys.exit(main())

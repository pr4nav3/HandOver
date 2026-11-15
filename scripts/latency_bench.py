#!/usr/bin/env python3
"""Latency bench: time from a finished step to the camera advance, with and without the confirm speedups.

    .venv/bin/python scripts/latency_bench.py [--trials 8] [--fps 1] [--conf 0.95] [--code DIR]

Runs the hub's learn engine in this process in mock mode (no network, no keys, nothing written outside a temp
folder). The check is a stand-in that waits HANDOVER_MOCK_LATENCY_MS (default 600) and then answers yes for the
finished scene and no for anything else. A fake camera sends one moving frame, then the finished scene at
--fps frames per second (contract: about 1 fps), starting at a random point in the frame interval.

Per trial it records, all on the engine's clock:
    finished   the first frame of the finished scene
    settled    the frame the motion gate first lets through (the scene has been still for
               HANDOVER_GATE_STILL_FRAMES frames)
    verified   state status "verified" goes out (badge and next_clip preload start)
    advance    the advance message goes out (the next clip starts)

Configs: before (HANDOVER_MAX_INFLIGHT=1, HANDOVER_FAST_PATH=0, the old one-check-at-a-time behavior),
pipelined (2 checks at once on different frames), pipelined plus fast path (one yes at HANDOVER_FAST_CONF
or more advances), the same with an answer below the fast-path bar, and the same with HANDOVER_UNDERSTAND=1
(a stand-in understanding call of the same latency beside each check; both must say yes). A last row shows a knob this
change does not touch (HANDOVER_GATE_STILL_FRAMES=1) for comparison only.

--ui measures the live picture instead: frames go to the engine at --fps (use 15, as the new senders) for a few
seconds, and it reports how many reach a stand-in viewer (at most HANDOVER_UI_FPS), and the time from a frame
arriving to it being handed to the viewer, for a 640 px frame (forwarded as is) and a 1280 px frame (downscaled).

Prints a table and writes scripts/out/latency-<time>.md. --code points at another checkout's folder (one
that holds server/) to measure older code the same way; unknown settings are then simply ignored.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import io
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "scripts" / "out"
LESSON = "bench"
DONE_COLOR = (40, 160, 90)


def mock_latency_s() -> float:
    """HANDOVER_MOCK_LATENCY_MS: how long the stand-in check takes (default 600, range 0 to 10000)."""
    raw = os.environ.get("HANDOVER_MOCK_LATENCY_MS", "").strip()
    try:
        ms = float(raw) if raw else 600.0
    except ValueError:
        ms = 600.0
    return (ms if 0 <= ms <= 10000 else 600.0) / 1000


def isolate(tmp: Path) -> None:
    """Mock mode, no network, temp lessons and event mirror; no keys or Databricks settings in this process."""
    for k in list(os.environ):
        if k.startswith(("HANDOVER_", "DATABRICKS_")) and k != "HANDOVER_MOCK_LATENCY_MS":
            del os.environ[k]
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(k, None)
    os.environ.update({"HANDOVER_CHECK": "mock", "HANDOVER_NO_NETWORK": "1", "HANDOVER_LESSONS": str(tmp / "lessons"),
                       "HANDOVER_EVENTS_JSONL": str(tmp / "events.jsonl"), "HANDOVER_MIN_FRAME_GAP": "0",
                       "HANDOVER_LOG_JSON": "0"})


def jpeg(color: tuple[int, int, int], size: tuple[int, int] = (640, 360)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def make_lesson(lessons: Path) -> None:
    d = lessons / LESSON
    (d / "frames").mkdir(parents=True)
    steps = []
    for i, color in enumerate((DONE_COLOR, (160, 40, 40)), start=1):
        (d / "frames" / f"{i:02d}.jpg").write_bytes(jpeg(color, (320, 180)))
        steps.append({"n": i, "title": f"Bench {i}", "start": f"00:0{i - 1}", "end": f"00:0{i}",
                      "ref_frame": f"frames/{i:02d}.jpg", "check_type": "camera",
                      "check_question": f"Is bench step {i} done?"})
    lesson = {"id": LESSON, "title": "Latency bench", "steps": steps}
    (d / "lesson.json").write_text(json.dumps(lesson), "utf-8")
    try:  # a rubric, so the HANDOVER_UNDERSTAND row has something to understand
        from server import understand
    except ImportError:
        return
    entries = [{"n": s["n"], "title": s["title"], "question": s["check_question"], "keyframes": [s["ref_frame"]] * 3,
                "stages": [{"label": "done", "cue": "done"}], "done_cue": "done", "mistakes": [], "region": {}}
               for s in steps]
    (d / "rubric.json").write_text(json.dumps({"version": understand.RUBRIC_VERSION,
                                               "source": understand.lesson_signature(lesson), "steps": entries}))


class Trial:
    def __init__(self) -> None:
        self.finished = self.settled = self.verified = self.advance = None
        self.checks = 0


async def run_trial(main, check, gate_mod, fps: float, conf: float, rng: random.Random) -> Trial:
    """One step from moving hands to the camera advance."""
    t = Trial()
    done_frame = jpeg(DONE_COLOR)
    latency = mock_latency_s()

    async def fake_check(ref, live, question, *, step_started_at=None, prev_ref=None, **_):
        if t.advance is None:  # checks for this step only, not the next step's first check
            t.checks += 1
        await asyncio.sleep(latency)
        if live == done_frame:
            return check.CheckResult("yes", conf, int(latency * 1000))
        return check.CheckResult("no", 0.85, int(latency * 1000), reason="hands still moving")

    check.check_frame = fake_check
    try:
        from server import understand

        async def fake_understand(entry, keys, live, prev, **_):  # same latency and verdict as the check
            await asyncio.sleep(latency)
            yes = live == done_frame
            return understand.Understanding("yes" if yes else "no", conf if yes else 0.85, int(latency * 1000),
                                            stage=0 if yes else -1, progress=1.0 if yes else 0.0)

        understand.understand_frame = fake_understand
    except ImportError:
        pass
    engine = main.Engine()
    main.engine = engine
    engine.cameras = 1  # a camera is connected; frames go straight to on_frame below

    real_observe = engine.gate.observe

    def observe(frame: bytes, now: float) -> bool:
        wanted = real_observe(frame, now)
        if wanted and frame == done_frame and t.settled is None:
            t.settled = time.monotonic()
        return wanted

    engine.gate.observe = observe
    real_broadcast = engine.broadcast

    def broadcast(msg) -> None:
        if isinstance(msg, dict):
            if msg.get("type") == "state" and msg.get("status") == "verified" and t.verified is None:
                t.verified = time.monotonic()
            elif msg.get("type") == "advance" and msg.get("reason") == "camera" and t.advance is None:
                t.advance = time.monotonic()
        real_broadcast(msg)

    engine.broadcast = broadcast
    engine.select(LESSON)
    loop_task = asyncio.create_task(engine.check_loop())
    try:
        await asyncio.sleep(rng.uniform(0, 1 / fps))  # random phase against the camera clock
        engine.on_frame(jpeg((rng.randrange(256), rng.randrange(256), rng.randrange(256))))  # hands in view
        deadline = time.monotonic() + 30
        while t.advance is None and time.monotonic() < deadline:
            await asyncio.sleep(1 / fps)
            if t.finished is None:
                t.finished = time.monotonic()
            engine.on_frame(done_frame)
        await asyncio.sleep(0.05)
    finally:
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)
    return t


CONFIGS = [
    ("before: 1 check at a time, no fast path", {"HANDOVER_MAX_INFLIGHT": "1", "HANDOVER_FAST_PATH": "0"}, None),
    ("pipelined: 2 checks at once", {"HANDOVER_MAX_INFLIGHT": "2", "HANDOVER_FAST_PATH": "0"}, None),
    ("pipelined + fast path", {"HANDOVER_MAX_INFLIGHT": "2", "HANDOVER_FAST_PATH": "1"}, None),
    ("pipelined + fast path, answer conf 0.90 (below the fast bar)",
     {"HANDOVER_MAX_INFLIGHT": "2", "HANDOVER_FAST_PATH": "1"}, 0.90),
    ("pipelined + fast path + HANDOVER_UNDERSTAND=1 (understanding beside the check, same latency)",
     {"HANDOVER_MAX_INFLIGHT": "2", "HANDOVER_FAST_PATH": "1", "HANDOVER_UNDERSTAND": "1"}, None),
    ("for comparison only: + HANDOVER_GATE_STILL_FRAMES=1 (not changed by this work)",
     {"HANDOVER_MAX_INFLIGHT": "2", "HANDOVER_FAST_PATH": "1", "HANDOVER_GATE_STILL_FRAMES": "1"}, None),
]


def p(vals: list[float], q: float) -> float:
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))]


def fmt(vals: list[float]) -> str:
    if not vals:
        return "n/a"
    return f"{statistics.median(vals):.2f} / {p(vals, 0.9):.2f}"


async def ui_trial(main, frame: bytes, fps: float, seconds: float) -> tuple[int, int, list[float]]:
    """Frames sent, frames handed to the viewer, and arrival-to-viewer delays in seconds (newest frame each)."""
    engine = main.Engine()
    main.engine = engine
    arrived: dict[int, float] = {}  # engine frame number -> when it arrived
    delays: list[float] = []

    class Viewer:
        frames = True

        def push(self, msg) -> None:
            if isinstance(msg, bytes) and engine.frame_seq in arrived:
                delays.append(time.monotonic() - arrived[engine.frame_seq])

    engine.ui.add(Viewer())  # type: ignore[arg-type]
    loop_task = asyncio.create_task(engine.ui_frame_loop())
    sent = 0
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        engine.on_frame(frame)
        sent += 1
        arrived[engine.frame_seq] = time.monotonic()
        await asyncio.sleep(1 / fps)
    await asyncio.sleep(0.2)
    loop_task.cancel()
    return sent, len(delays), delays


def ui_bench(a) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="handover-latency-"))
    isolate(tmp)
    sys.path.insert(0, str(a.code.resolve()))
    from server import config, main  # noqa: E402

    seconds = 4.0
    rows = []
    try:
        for label, size in (("640 px, forwarded as is", (640, 360)), ("1280 px, downscaled to 960", (1280, 720))):
            sent, got, delays = asyncio.run(ui_trial(main, jpeg(DONE_COLOR, size), a.fps, seconds))
            rows.append(f"| {label} | {sent / seconds:.1f} | {got / seconds:.1f} | "
                        f"{p(delays, 0.5) * 1000:.1f} / {p(delays, 0.9) * 1000:.1f} |")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    stamp = dt.datetime.now()
    text = "\n".join([f"# UI frame bench, {stamp:%Y-%m-%d %H:%M:%S}", "",
                      f"- In-process engine, frames sent at {a.fps:g} fps for {seconds:g} s, "
                      f"HANDOVER_UI_FPS {config.get('HANDOVER_UI_FPS')}",
                      "- Delay: frame arriving to it being handed to the viewer's sender (newest frame only), "
                      "p50 / p90 in ms", "",
                      "| Frame | Sent fps | To viewer fps | Delay p50 / p90 (ms) |", "|---|---|---|---|", *rows, ""])
    print(text)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"latency-ui-{stamp:%Y%m%d-%H%M%S}.md"
    out.write_text(text, encoding="utf-8")
    print(f"Report: {out}")
    return 0


def main_cli() -> int:
    ap = argparse.ArgumentParser(prog="scripts/latency_bench.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--trials", type=int, default=8, help="trials per config (default 8)")
    ap.add_argument("--fps", type=float, default=1.0, help="camera frames per second (default 1, as the phone)")
    ap.add_argument("--conf", type=float, default=0.95, help="confidence of the stand-in yes (default 0.95)")
    ap.add_argument("--seed", type=int, default=7, help="random seed for the camera phase (default 7)")
    ap.add_argument("--code", type=Path, default=REPO, help="folder that holds server/ (default this repo)")
    ap.add_argument("--only", type=int, nargs="*", help="run only these config rows (1-based)")
    ap.add_argument("--ui", action="store_true", help="measure the live picture to viewers instead (use --fps 15)")
    a = ap.parse_args()
    if a.trials < 1 or a.fps <= 0:
        ap.error("--trials must be 1 or more and --fps above 0")
    if a.ui:
        return ui_bench(a)

    tmp = Path(tempfile.mkdtemp(prefix="handover-latency-"))
    latency = mock_latency_s()
    isolate(tmp)
    sys.path.insert(0, str(a.code.resolve()))
    import logging

    from server import check, gate, main  # noqa: E402

    logging.getLogger("handover").setLevel(logging.WARNING)
    make_lesson(main.LESSONS)
    hold = main.VERIFIED_HOLD
    rows = []
    try:
        for i, (name, env, conf) in enumerate(CONFIGS, start=1):
            if a.only and i not in a.only:
                continue
            for k in ("HANDOVER_MAX_INFLIGHT", "HANDOVER_FAST_PATH", "HANDOVER_GATE_STILL_FRAMES", "HANDOVER_UNDERSTAND"):
                os.environ.pop(k, None)
            os.environ.update(env)
            rng = random.Random(a.seed)
            trials = []
            for _ in range(a.trials):
                trials.append(asyncio.run(run_trial(main, check, gate, a.fps, conf or a.conf, rng)))
            ok = [t for t in trials if None not in (t.finished, t.settled, t.verified, t.advance)]
            rows.append({
                "config": name,
                "answer_conf": conf or a.conf,
                "trials": f"{len(ok)} of {len(trials)}",
                "settle_verified": [t.verified - t.settled for t in ok],
                "settle_advance": [t.advance - t.settled for t in ok],
                "finished_advance": [t.advance - t.finished for t in ok],
                "checks": [t.checks for t in ok],
            })
            r = rows[-1]
            print(f"{i}. {name}: settle to advance p50/p90 {fmt(r['settle_advance'])} s ({r['trials']} trials)",
                  flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    head = ["Config", "Settled to verified (s)", "Settled to advance (s)", "Finished to advance (s)",
            "Checks per step", "Trials"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        checks = f"{statistics.median(r['checks']):.0f}" if r["checks"] else "n/a"
        lines.append(f"| {r['config']} | {fmt(r['settle_verified'])} | {fmt(r['settle_advance'])} | "
                     f"{fmt(r['finished_advance'])} | {checks} | {r['trials']} |")
    stamp = dt.datetime.now()
    md = [f"# Latency bench, {stamp:%Y-%m-%d %H:%M:%S}", "",
          f"- Measured: in-process engine, mock mode, stand-in check of {latency * 1000:.0f} ms "
          f"(HANDOVER_MOCK_LATENCY_MS), camera at {a.fps:g} fps, {a.trials} trials per row, seed {a.seed}",
          f"- Verified hold: {hold:g} s (HANDOVER_VERIFIED_HOLD); debounce n from HANDOVER_DEBOUNCE_N",
          f"- Code measured: {'this repo' if a.code.resolve() == REPO else a.code}",
          "- Cells are p50 / p90 in seconds. Settled = the frame the motion gate first lets through.", "",
          *lines, ""]
    text = "\n".join(md)
    print()
    print(text)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"latency-{stamp:%Y%m%d-%H%M%S}.md"
    out.write_text(text, encoding="utf-8")
    print(f"Report: {out}")
    return 0 if all(r["trials"].split()[0] == r["trials"].split()[-1] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main_cli())

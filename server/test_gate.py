"""Motion gate tests. Run: .venv/bin/python -m server.test_gate (or pytest if installed)."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

from server.gate import MotionGate

REPO = Path(__file__).resolve().parent.parent
VIDEO = REPO / "lessons" / "demo-v1" / "norm.mp4"
W, H = 1280, 720


def frame(rect_x: int | None = None, color: int = 200, extra: bool = False) -> bytes:
    """A 1280x720 JPEG: a textured mat, an optional moving rectangle, an optional second shape."""
    img = Image.new("RGB", (W, H), (40, 70, 50))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 80):
        d.line([(x, 0), (x, H)], fill=(60, 90, 70), width=2)
    d.rectangle([500, 250, 780, 470], fill=(30, 60, 160))  # the paper
    if extra:
        d.polygon([(500, 250), (780, 250), (640, 400)], fill=(230, 230, 230))  # a fold
    if rect_x is not None:
        d.rectangle([rect_x, 300, rect_x + 200, 500], fill=(color, color - 40, color - 80))  # a hand
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def feed(gate: MotionGate, frames: list[bytes], t0: float = 0.0, dt: float = 1.0, engine: bool = True) -> list[bool]:
    """Feed frames at dt spacing; like the engine, mark a check whenever the gate allows one."""
    out = []
    for i, f in enumerate(frames):
        now = t0 + i * dt
        ok = gate.observe(f, now)
        if ok and engine:
            gate.mark_checked(now)
        out.append(ok)
    return out


def test_static_scene_checks_once_then_holds():
    g = MotionGate(enabled=True)
    still = frame()
    out = feed(g, [still] * 6)  # 0..5 s, under the 6 s heartbeat
    assert out == [False, False, True, False, False, False], out
    assert g.stats["frames_seen"] == 6 and g.stats["checks_allowed"] == 1


def test_moving_rectangle_holds():
    g = MotionGate(enabled=True)
    feed(g, [frame()] * 3)  # settle and check the empty scene
    out = feed(g, [frame(rect_x=100 + 120 * i) for i in range(8)], t0=3.0, dt=0.5)
    assert not any(out), out
    assert g.stats["last_motion"] > g.motion_thresh


def test_scene_change_after_settling():
    g = MotionGate(enabled=True)
    assert feed(g, [frame()] * 3) == [False, False, True]
    moving = [frame(rect_x=100 + 150 * i) for i in range(4)]
    after = [frame(extra=True)] * 4
    out = feed(g, moving + after, t0=3.0, dt=0.5)  # stays inside the 6 s heartbeat
    # Hand moves (hold), the fold appears (motion), then two still frames settle: one check.
    assert out == [False] * 4 + [False, False, True, False], out
    assert g.stats["last_change"] is not None and g.stats["last_change"] < g.change_thresh


def test_heartbeat_after_6s():
    g = MotionGate(enabled=True)
    out = feed(g, [frame()] * 15)  # 0..14 s, unchanged
    allowed = [i for i, ok in enumerate(out) if ok]
    assert allowed == [2, 8, 14], allowed


def test_heartbeat_during_continuous_motion():
    g = MotionGate(enabled=True)
    shaky = [frame(rect_x=100 + 100 * (i % 2)) for i in range(61)]  # 0..30 s at 2 fps, never settles
    out = feed(g, shaky, dt=0.5)
    allowed = [i * 0.5 for i, ok in enumerate(out) if ok]
    assert allowed == [6.0, 12.0, 18.0, 24.0, 30.0], allowed
    assert g.stats["last_motion"] > g.motion_thresh  # still moving at the end


def test_disabled_gate():
    g = MotionGate(enabled=False)
    assert feed(g, [frame(rect_x=i * 50) for i in range(5)] + [b"junk"]) == [True] * 6


def test_env_disable():
    os.environ["HANDOVER_GATE"] = "0"
    try:
        assert MotionGate().enabled is False
    finally:
        del os.environ["HANDOVER_GATE"]
    assert MotionGate().enabled is True


def test_env_thresholds():
    names = ["HANDOVER_GATE_MOTION", "HANDOVER_GATE_STILL", "HANDOVER_GATE_STILL_FRAMES",
             "HANDOVER_GATE_CHANGE", "HANDOVER_GATE_HEARTBEAT_S"]
    defaults = (0.02, 0.005, 2, 0.018, 6.0)

    def values(g: MotionGate) -> tuple:
        return (g.motion_thresh, g.still_thresh, g.still_frames, g.change_thresh, g.heartbeat_s)

    assert values(MotionGate()) == defaults
    try:
        for name, v in zip(names, ["0.05", "0.01", "3", "0.025", "4.5"]):
            os.environ[name] = v
        assert values(MotionGate()) == (0.05, 0.01, 3, 0.025, 4.5)
        assert MotionGate(change_thresh=0.04).change_thresh == 0.04  # argument wins over env
        for name, v in zip(names, ["abc", "-1", "2.5", "", "0"]):
            os.environ[name] = v
        assert values(MotionGate()) == defaults  # bad values fall back
    finally:
        for name in names:
            os.environ.pop(name, None)


def test_corrupt_bytes():
    g = MotionGate(enabled=True)
    still = frame()
    for bad in [b"", b"\xff\xd8garbage", still[: len(still) // 3], b"\x89PNG\r\n\x1a\n", bytes(500)]:
        assert g.observe(bad, 0.0) is False
    # Bad frames in between do not break settling on good ones.
    assert feed(g, [still, b"x", still, still], engine=False) == [False, False, False, True]


def test_reset_allows_next_settled_frame():
    g = MotionGate(enabled=True)
    still = frame()
    feed(g, [still] * 4)  # checked at t=2, held at t=3
    assert g.observe(still, 4.0) is False
    g.reset()
    assert g.observe(still, 5.0) is True  # motion history survives reset, scene is settled
    g.mark_checked(5.0)
    assert g.observe(still, 6.0) is False
    assert g.stats["last_change"] is not None


def test_speed():
    g = MotionGate(enabled=True)
    frames = [frame(rect_x=(i % 10) * 100) for i in range(50)]
    t = time.perf_counter()
    for i, f in enumerate(frames):
        g.observe(f, float(i))
    ms = (time.perf_counter() - t) * 1000 / len(frames)
    print(f"  observe(): {ms:.2f} ms per 1280x720 JPEG ({len(frames[0]) // 1024} KB)")
    assert ms < 10, ms  # target is under 5 ms; slack for a busy machine


def test_real_video():
    if not VIDEO.exists() or not shutil.which("ffmpeg"):
        print("  skipped: no norm.mp4 or ffmpeg")
        return
    tmp = Path(tempfile.mkdtemp(prefix="handover-gate-"))
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(VIDEO), "-vf", "fps=2,scale=1280:-2", "-q:v", "4", str(tmp / "%04d.jpg")],
            check=True,
        )
        files = sorted(tmp.glob("*.jpg"))
        g = MotionGate(enabled=True)
        times, cost = [], 0.0
        for i, p in enumerate(files):
            now = i * 0.5
            data = p.read_bytes()
            t = time.perf_counter()
            ok = g.observe(data, now)
            cost += time.perf_counter() - t
            if ok:
                g.mark_checked(now)
                times.append(now)
        print(f"  norm.mp4: {len(files)} frames at 2 fps, {len(times)} checks at {times} s")
        print(f"  observe(): {cost * 1000 / len(files):.2f} ms per frame on real 1280x720 JPEGs")
        assert 3 <= len(times) <= 15, times
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

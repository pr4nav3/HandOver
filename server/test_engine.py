"""Learn engine and hub protocol tests: /ws/camera (hello, active camera, replace, nav, frame limits), state
fields, motion gate, breaker, mistake check, web app serving, DELETE, and the M15 privacy guarantee.

No network and no ffmpeg: lessons are written with Pillow into a temp folder, Gemini is replaced by fakes.

Run: .venv/bin/python -m server.test_engine
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import pathlib
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

TMP = Path(tempfile.mkdtemp(prefix="handover-engine-test-"))
os.environ["HANDOVER_LESSONS"] = str(TMP / "lessons")  # before importing server.main, which reads it once
os.environ["HANDOVER_CHECK"] = "mock"
os.environ["HANDOVER_GATE"] = "0"
os.environ["HANDOVER_MIN_FRAME_GAP"] = "0"  # tests stream faster than the 5 fps cap; test_frame_gap covers it
os.environ.pop("HANDOVER_MOCK_MISTAKE", None)
os.environ["HANDOVER_EVENTS_JSONL"] = str(TMP / "scratch" / "events.jsonl")  # server.databricks local mirror

import anyio  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from server import check, main, mistake  # noqa: E402

LESSON = "engine-test"
COLORS = [(200, 30, 30), (30, 200, 30), (30, 30, 200)]


# ---------------------------------------------------------------- fixtures

def jpeg(color: tuple[int, int, int], size: tuple[int, int] = (1280, 720)) -> bytes:
    """An in-memory JPEG; 1280 wide so the UI downscale really re-encodes."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


FRAME = jpeg((90, 90, 90))


def make_lesson(lesson_id: str = LESSON) -> Path:
    """A three-step camera lesson with reference frames and no clips (the engine never reads clips)."""
    d = main.LESSONS / lesson_id
    shutil.rmtree(d, ignore_errors=True)
    (d / "frames").mkdir(parents=True)
    steps = []
    for i, color in enumerate(COLORS, start=1):
        (d / "frames" / f"{i:02d}.jpg").write_bytes(jpeg(color, (320, 240)))
        steps.append({"n": i, "title": f"Step {i}", "start": f"00:0{i - 1}", "end": f"00:0{i}",
                      "ref_frame": f"frames/{i:02d}.jpg", "check_type": "camera",
                      "check_question": f"Is step {i} done?",
                      "common_mistake": "Flip it over first." if i == 2 else ""})
    (d / "lesson.json").write_text(json.dumps({"id": lesson_id, "title": "Engine test", "steps": steps}), "utf-8")
    return d


@contextlib.contextmanager
def env(**values: str | None) -> Iterator[None]:
    """Set or unset environment variables for one block."""
    old = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def patched(obj: Any, **attrs: Any) -> Iterator[None]:
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def gemini() -> Iterator[None]:
    """Gemini mode with a key present; each test replaces the Gemini calls itself."""
    with env(HANDOVER_CHECK=None), patched(check, has_key=lambda: True):
        yield


@contextlib.contextmanager
def hub() -> Iterator[TestClient]:
    """A fresh engine and a running app (lifespan on, so the check and frame loops run) on one event loop."""
    main.engine = main.Engine()
    with TestClient(main.app) as client:
        yield client


def recv(ws: Any, timeout: float = 3.0) -> dict:
    """The next raw ASGI message from the hub, or TimeoutError."""
    async def get() -> dict:
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()
    return ws.portal.call(get)


def recv_json(ws: Any, pred: Callable[[dict], bool] = lambda m: True, timeout: float = 3.0) -> dict:
    """The first text message matching pred; binary frames and other messages are skipped."""
    deadline = time.monotonic() + timeout
    while True:
        msg = recv(ws, max(0.01, deadline - time.monotonic()))
        if msg.get("text") is not None:
            data = json.loads(msg["text"])
            if pred(data):
                return data


def drain(ws: Any, quiet: float = 0.4) -> list[dict]:
    """Every message until the hub has been quiet for `quiet` seconds."""
    out = []
    with contextlib.suppress(TimeoutError):
        while True:
            out.append(recv(ws, quiet))
    return out


def wait_for(cond: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)


def is_state(m: dict) -> bool:
    return m.get("type") == "state"


def select(ui: Any, lesson_id: str = LESSON) -> dict:
    ui.send_json({"type": "select_lesson", "id": lesson_id})
    return recv_json(ui, lambda m: is_state(m) and m["lesson_id"] == lesson_id)


def hello(**fields: Any) -> dict:
    return {"type": "hello", "device_id": "dev-1", "name": "Test phone", "platform": "ios", "source": "phone", **fields}


# ---------------------------------------------------------------- /ws/camera: hello and identity

def test_hello_sets_identity_and_state() -> None:
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        assert recv_json(ui)["camera"] is None
        with c.websocket_connect("/ws/camera") as cam:
            assert recv_json(cam) == {"type": "camera_status", "active": True}
            st = recv_json(ui, is_state)
            assert st["camera_connected"]
            assert st["camera"] == {"name": "Camera 1", "platform": "other", "source": "phone"}
            for bad in ({"platform": "android"}, {"source": 5}, {"name": ["x"]}, {"device_id": {}}):
                cam.send_json(hello(**bad))  # malformed: ignored, no state for this camera
            cam.send_text("not json")
            assert drain(cam) == [] and not main.engine.cams[0].said_hello
            cam.send_json(hello())
            first = recv_json(cam)
            assert is_state(first) and first["camera"] == {"name": "Test phone", "platform": "ios", "source": "phone"}
            assert recv_json(ui, is_state)["camera"]["name"] == "Test phone"
            cam.send_json(hello(name="Ray-Ban Meta via iPhone", source="glasses"))  # repeat hello updates
            st = recv_json(ui, is_state)
            assert st["camera"] == {"name": "Ray-Ban Meta via iPhone", "platform": "ios", "source": "glasses"}
            assert recv_json(cam, is_state)["camera"]["source"] == "glasses"
        st = recv_json(ui, is_state)
        assert not st["camera_connected"] and st["camera"] is None


def test_hello_grace_avoids_identity_flicker() -> None:
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        recv_json(ui)
        with c.websocket_connect("/ws/camera") as cam:
            cam.send_json(hello(name="Phone", source="glasses"))  # within the grace time
            states = [json.loads(m["text"]) for m in drain(ui, 0.6) if m.get("text")]
            cameras = [st["camera"] for st in states if st["type"] == "state"]
            assert cameras == [{"name": "Phone", "platform": "ios", "source": "glasses"}], cameras


def test_breaker_reason_passes_through() -> None:
    with gemini(), hub():
        main.engine.breaker.force_open("budget", time.monotonic())  # type: ignore[arg-type]
        assert (main.engine.state()["check_offline"], main.engine.state()["check_offline_reason"]) == (True, "budget")


def test_hello_within_grace_has_no_default_name_flicker() -> None:
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        recv_json(ui)
        with c.websocket_connect("/ws/camera") as cam:
            cam.send_json(hello(name="Glasses"))
            states = [json.loads(m["text"]) for m in drain(ui, 0.6) if m.get("text")]
            names = [st["camera"]["name"] for st in states if is_state(st) and st["camera"]]
            assert names == ["Glasses"], names  # never "Camera 1" first


def test_breaker_reason_passes_through_budget() -> None:
    with gemini(), hub():
        main.engine.breaker.force_open("budget", time.monotonic())
        assert main.engine.state()["check_offline_reason"] == "budget"


def test_state_has_new_fields() -> None:
    make_lesson()
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        st = select(ui)
        for key in ("lesson_id", "rev", "step", "total", "status", "last_check", "camera_connected"):
            assert key in st, key  # every EXISTS field kept
        assert st["camera"] is None and st["mistake"] is None
        assert (st["check_offline"], st["check_offline_reason"]) == (False, None)


# ---------------------------------------------------------------- active camera

def test_active_camera_newest_wins_and_idle_switch() -> None:
    with patched(main, ACTIVE_IDLE_SECONDS=0.8), hub() as c, c.websocket_connect("/ws/ui") as ui:
        recv_json(ui)
        with c.websocket_connect("/ws/camera") as a:
            a.send_json(hello(device_id="a", name="A"))
            a.send_bytes(FRAME)
            wait_for(lambda: main.engine.frame_seq == 1)
            with c.websocket_connect("/ws/camera") as b:  # newest connection wins at once
                assert recv_json(b) == {"type": "camera_status", "active": True}
                assert recv_json(a, lambda m: m.get("active") is False) == {"type": "camera_status", "active": False}
                assert recv_json(ui, lambda m: is_state(m) and m["camera"]["name"] == "Camera 2")
                a.send_bytes(FRAME)  # B silent for under 0.8 s (state came after the 0.3 s grace): not judged
                time.sleep(0.1)
                assert main.engine.frame_seq == 1
                time.sleep(0.6)
                a.send_bytes(FRAME)  # B silent past the limit and A is sending: A takes over with this frame
                wait_for(lambda: main.engine.frame_seq == 2)
                assert main.engine.active is not None and main.engine.active.name == "A"
                assert recv_json(b, lambda m: m.get("active") is False) == {"type": "camera_status", "active": False}
                assert recv_json(ui, lambda m: is_state(m) and m["camera"]["name"] == "A")
                b.send_json(hello(device_id="b", name="B"))  # a hello makes B newest again
                assert recv_json(ui, lambda m: is_state(m) and m["camera"]["name"] == "B")
            st = recv_json(ui, is_state)  # B left: A, the remaining camera, is active again
            assert st["camera_connected"] and st["camera"]["name"] == "A"


def test_hello_spam_does_not_hold_active() -> None:
    with patched(main, ACTIVE_IDLE_SECONDS=0.3), hub() as c:
        with c.websocket_connect("/ws/camera") as b, c.websocket_connect("/ws/camera") as a:
            a.send_json(hello(device_id="a", name="A"))
            wait_for(lambda: main.engine.active is not None and main.engine.active.name == "A")
            for _ in range(5):  # A repeats hello but sends no frames
                a.send_json(hello(device_id="a", name="A"))
                time.sleep(0.1)
            b.send_bytes(FRAME)
            wait_for(lambda: main.engine.active is not None and main.engine.active.name == "Camera 1")


def test_replaced_closes_4000() -> None:
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        recv_json(ui)
        with c.websocket_connect("/ws/camera") as old:
            old.send_json(hello(device_id="phone-x"))
            recv_json(old, is_state)
            with c.websocket_connect("/ws/camera") as new:
                new.send_json(hello(device_id="phone-x", name="Phone again"))
                closed = recv(old, 3.0)
                while closed["type"] != "websocket.close":
                    closed = recv(old, 3.0)
                assert (closed["code"], closed["reason"]) == (4000, "replaced")
                wait_for(lambda: len(main.engine.cams) == 1)
                assert main.engine.active is not None and main.engine.active.name == "Phone again"
                assert main.engine.state()["camera_connected"]


# ---------------------------------------------------------------- camera nav and messages

def test_camera_next_back_after_hello_with_from() -> None:
    make_lesson()
    with hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        recv_json(cam)  # camera_status
        cam.send_json({"type": "next", "reason": "button", "from": 0})  # before hello: ignored, no reply
        assert drain(cam) == []
        cam.send_json(hello())
        recv_json(cam, is_state)
        cam.send_json({"type": "next", "reason": "button", "from": 0})
        assert recv_json(cam, lambda m: m["type"] == "error") == {"type": "error", "message": "no lesson selected"}
        select(ui)
        recv_json(cam, lambda m: is_state(m) and m["lesson_id"] == LESSON)
        cam.send_json({"type": "next", "reason": "button", "from": 0})
        assert recv_json(cam, lambda m: m["type"] == "advance") == {"type": "advance", "from": 0, "to": 1,
                                                                    "reason": "button"}
        assert recv_json(cam, is_state)["step"] == 1
        cam.send_json({"type": "next", "reason": "button", "from": 0})  # stale: the hub is on step 1
        cam.send_json({"type": "back", "from": 0})  # stale too
        time.sleep(0.2)
        assert main.engine.step == 1
        cam.send_json({"type": "back", "from": 1})
        wait_for(lambda: main.engine.step == 0)


def test_frame_limits() -> None:
    with hub() as c, c.websocket_connect("/ws/camera") as cam:
        cam.send_bytes(b"\xff\xd8" + b"\0" * (2 * 1024 * 1024))  # over 2 MB
        cam.send_bytes(b"not a jpeg")
        time.sleep(0.2)
        assert main.engine.frame_seq == 0
        cam.send_bytes(FRAME)
        wait_for(lambda: main.engine.frame_seq == 1)


def test_frames_are_binary_only_to_ui() -> None:
    make_lesson()
    with hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        cam.send_json(hello())
        select(ui)
        for _ in range(3):
            cam.send_bytes(FRAME)
            time.sleep(0.1)
        got = drain(ui, 0.6)
        frames = [m["bytes"] for m in got if m.get("bytes")]
        assert frames and frames[-1][:2] == b"\xff\xd8"
        assert max(Image.open(io.BytesIO(frames[-1])).size) <= main.UI_FRAME_MAX_SIDE
        to_camera = drain(cam)
        assert to_camera and all(m.get("bytes") is None for m in to_camera)


# ---------------------------------------------------------------- check loop: gate, breaker, reason

class FakeCheck:
    """Stands in for check.check_frame and records each call."""

    def __init__(self, answer: Callable[[bytes], check.CheckResult]):
        self.answer = answer
        self.calls: list[bytes] = []
        self.prev_refs: list[bytes | None] = []
        self.times: list[float] = []

    async def __call__(self, ref: bytes, live: bytes, question: str, *, step_started_at: float | None = None,
                       prev_ref: bytes | None = None) -> check.CheckResult:
        self.calls.append(ref)
        self.prev_refs.append(prev_ref)
        self.times.append(time.monotonic())
        return self.answer(ref)


def test_check_gets_previous_reference() -> None:
    d = make_lesson()
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 1))
    with patched(check, check_frame=fake), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        cam.send_bytes(FRAME)
        wait_for(lambda: len(fake.calls) == 1)
        assert fake.prev_refs == [None]  # step 0 has no previous step
        ui.send_json({"type": "goto", "step": 1})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 1)
        cam.send_bytes(jpeg((1, 2, 3)))
        wait_for(lambda: len(fake.calls) == 2)
        assert fake.prev_refs[1] == (d / "frames" / "01.jpg").read_bytes()


def test_last_check_reason_passes_through() -> None:
    make_lesson()
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 12, reason="seams still facing up"))
    with patched(check, check_frame=fake), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        cam.send_bytes(FRAME)
        st = recv_json(ui, lambda m: is_state(m) and m["last_check"] is not None)
        assert st["last_check"] == {"done": "no", "confidence": 0.9, "latency_ms": 12,
                                    "reason": "seams still facing up"}


def test_motion_gate_holds_back_repeated_frames() -> None:
    make_lesson()
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 1))
    with env(HANDOVER_GATE="1"), patched(check, check_frame=fake), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        cam.send_bytes(FRAME)
        time.sleep(0.2)
        assert fake.calls == []  # the very first frame is never checked
        for _ in range(6):
            cam.send_bytes(FRAME)
            time.sleep(0.1)
        assert len(fake.calls) == 1, len(fake.calls)  # settled once; identical frames after that wait for the heartbeat


def test_fast_confirm_after_first_yes() -> None:
    """After one yes, the next still frame is checked at once, although the gate sees no change."""
    make_lesson()
    fake = FakeCheck(lambda ref: check.CheckResult("yes", 0.9, 1))
    interval = 0.2
    with env(HANDOVER_GATE="1", HANDOVER_DEBOUNCE_N="3"), patched(check, check_frame=fake), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        sent: list[float] = []
        for _ in range(5):
            cam.send_bytes(FRAME)
            sent.append(time.monotonic())
            time.sleep(interval)
    assert len(fake.times) >= 2, fake.times
    first = fake.times[0]
    next_frame = min(t for t in sent if t > first)
    assert fake.times[1] - next_frame < interval, (fake.times, sent)


def test_first_camera_advance_is_fast_in_mock() -> None:
    """Mock, pass at once: the advance lands within 2 x check latency + 1.5 s of the scene settling."""
    make_lesson()
    mock_latency = 0.6
    with env(HANDOVER_GATE="1", HANDOVER_MOCK_PASS_SECONDS="0"), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        settled_at = None
        for i in range(40):
            cam.send_bytes(FRAME)
            if i == 2:
                settled_at = time.monotonic()  # third identical frame: the gate counts the scene as still
            if main.engine.step == 1:
                break
            time.sleep(0.1)
        wait_for(lambda: main.engine.step == 1, timeout=5)
        took = time.monotonic() - settled_at
    assert took < 2 * mock_latency + 1.5, took


def test_mistake_compare_does_not_delay_advance() -> None:
    make_lesson()
    verdict = {"done": "no"}
    fake = FakeCheck(lambda ref: check.CheckResult(verdict["done"], 0.9, 1))
    compare_started: list[float] = []

    async def slow_compare(live: bytes, pairs: list[tuple[int, bytes]], question: str | None = None
                           ) -> check.MatchResult:
        compare_started.append(time.monotonic())
        await anyio.sleep(3)
        return check.MatchResult(None, 0.0, 3000)

    with gemini(), patched(check, check_frame=fake, compare_refs=slow_compare), \
            patched(main, VERIFIED_HOLD=0.05), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        main.engine.watch = mistake.MistakeWatch(settle_s=0.1, cooldown_s=60)
        select(ui)
        i = 0
        while not compare_started and i < 30:
            cam.send_bytes(jpeg((i * 7 % 255, 60, 60)))
            i += 1
            time.sleep(0.05)
        assert compare_started, "the mistake compare never started"
        verdict["done"] = "yes"
        flipped = time.monotonic()
        while main.engine.step == 0 and time.monotonic() - flipped < 2.5:
            cam.send_bytes(jpeg((i * 7 % 255, 90, 90)))
            i += 1
            time.sleep(0.05)
        assert main.engine.step == 1, "advance waited for the compare"
        assert time.monotonic() - compare_started[0] < 3  # the compare is still sleeping


def test_breaker_turns_checks_off_and_back_on() -> None:
    make_lesson()
    answers = {"error": "rate_limited"}
    fake = FakeCheck(lambda ref: check.CheckResult("unsure", 0.0, 5, error=answers["error"]))
    events: list[dict] = []
    with gemini(), env(HANDOVER_BREAKER_SECONDS="1"), patched(check, check_frame=fake), \
            patched(main, EVENT_SINKS=[events.append]), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        cam.send_bytes(FRAME)
        st = recv_json(ui, lambda m: is_state(m) and m["check_offline"])
        assert st["check_offline_reason"] == "rate_limited"
        for _ in range(3):
            cam.send_bytes(jpeg((10, 10, 10)))
            time.sleep(0.05)
        assert len(fake.calls) == 1  # open: no checks run
        answers["error"] = None
        time.sleep(1.0)
        cam.send_bytes(FRAME)  # trial call succeeds and closes the breaker
        st = recv_json(ui, lambda m: is_state(m) and not m["check_offline"])
        assert st["check_offline_reason"] is None and len(fake.calls) == 2
    breaker = [(e["open"], e["reason"]) for e in events if e["kind"] == "breaker"]
    assert breaker == [(True, "rate_limited"), (False, None)], breaker


def test_crashing_check_counts_as_breaker_error() -> None:
    make_lesson()

    async def crash(*args: Any, **kwargs: Any) -> check.CheckResult:
        raise RuntimeError("boom")

    with gemini(), patched(check, check_frame=crash), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        for i in range(3):
            cam.send_bytes(jpeg((i * 50, 0, 0)))
            time.sleep(0.15)
        st = recv_json(ui, lambda m: is_state(m) and m["check_offline"])
        assert st["check_offline_reason"] == "errors"


def test_bad_env_values_do_not_crash_engine() -> None:
    with env(HANDOVER_DEBOUNCE_N="abc", HANDOVER_BREAKER_SECONDS="soon", HANDOVER_MISTAKE_PARALLEL="maybe"):
        engine = main.Engine()
        assert engine.debouncer.n >= 1 and engine.breaker.open_seconds == 30.0 and main.mistake_parallel()
    with env(HANDOVER_DEBOUNCE_N="0"):
        assert main.Engine().debouncer.n >= 1


def test_breaker_never_offline_in_mock() -> None:
    with hub():
        main.engine.breaker.record(check.CheckResult("unsure", 0.0, 1, error="no_key"), time.monotonic())
        assert main.engine.state()["check_offline"] is False


# ---------------------------------------------------------------- mistake check (M9)

def test_mistake_behind_gemini_once_then_yes_clears() -> None:
    make_lesson()
    verdict = {"done": "no"}
    fake = FakeCheck(lambda ref: check.CheckResult(verdict["done"], 0.9, 1))
    compares: list[list[int]] = []

    async def compare(live: bytes, pairs: list[tuple[int, bytes]], question: str | None = None) -> check.MatchResult:
        compares.append([i for i, _ in pairs])
        return check.MatchResult(0, 0.9, 3)  # live frame matches step 0 while the learner is on step 1

    with gemini(), env(HANDOVER_DEBOUNCE_N="5"), patched(check, check_frame=fake, compare_refs=compare), \
            hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        main.engine.watch = mistake.MistakeWatch(settle_s=0.2, cooldown_s=60)
        select(ui)
        ui.send_json({"type": "goto", "step": 1})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 1)
        for i in range(8):
            cam.send_bytes(jpeg((i * 20, 50, 50)))
            time.sleep(0.08)
        m = recv_json(ui, lambda m: m["type"] == "mistake")
        assert m == {"type": "mistake", "step": 1, "kind": "behind", "looks_like": 0, "message": "Flip it over first.",
                     "confidence": 0.9, "source": "gemini"}
        st = recv_json(ui, lambda s: is_state(s) and s["mistake"] is not None)
        assert st["mistake"]["kind"] == "behind" and "type" not in st["mistake"]
        assert compares == [[0, 1, 2]]  # once, over k-1, k, k+1
        verdict["done"] = "yes"
        cam.send_bytes(FRAME)
        assert recv_json(ui, lambda s: is_state(s) and s["mistake"] is None)["step"] == 1


def test_mistake_ahead_confirmed_skips_two() -> None:
    make_lesson()
    ref_next = (main.LESSONS / LESSON / "frames" / "02.jpg").read_bytes()
    fake = FakeCheck(lambda ref: check.CheckResult("yes" if ref == ref_next else "no", 0.9, 1))

    async def compare(live: bytes, pairs: list[tuple[int, bytes]], question: str | None = None) -> check.MatchResult:
        return check.MatchResult(1, 0.9, 3)

    with gemini(), patched(check, check_frame=fake, compare_refs=compare), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        main.engine.watch = mistake.MistakeWatch(settle_s=0.2, cooldown_s=60)
        select(ui)
        for i in range(8):
            cam.send_bytes(jpeg((i * 20, 50, 50)))
            time.sleep(0.08)
        assert recv_json(ui, lambda m: m["type"] == "mistake")["kind"] == "ahead"
        assert recv_json(ui, lambda m: m["type"] == "advance") == {"type": "advance", "from": 0, "to": 2,
                                                                   "reason": "camera"}


def test_mock_ahead_is_confirmed_and_shown() -> None:
    make_lesson()
    with env(HANDOVER_MOCK_MISTAKE="ahead:0", HANDOVER_MOCK_PASS_SECONDS="100"), \
            patched(mistake, MOCK_AFTER_S=0.3), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        for i in range(4):
            cam.send_bytes(jpeg((i * 30, 40, 40)))
            time.sleep(0.4)
        # The ahead state lasts one tick (the skip replaces it before it is sent), so the message is what shows it.
        shown = recv_json(ui, lambda m: m["type"] == "mistake", timeout=5)
        assert (shown["step"], shown["kind"], shown["source"]) == (0, "ahead", "mock")
        assert shown["message"] == "You're ahead."
        adv = recv_json(ui, lambda m: m["type"] == "advance")
        assert (adv["from"], adv["to"], adv["reason"]) == (0, 2, "camera")
        assert recv_json(ui, is_state)["mistake"] is None


def test_mock_mistake_hook_and_dismiss() -> None:
    make_lesson()
    with env(HANDOVER_MOCK_MISTAKE="behind:1", HANDOVER_MOCK_PASS_SECONDS="100"), \
            patched(mistake, MOCK_AFTER_S=0.3), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        ui.send_json({"type": "goto", "step": 1})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 1)
        for i in range(4):
            cam.send_bytes(jpeg((i * 30, 40, 40)))
            time.sleep(0.4)
        m = recv_json(ui, lambda m: m["type"] == "mistake", timeout=5)
        assert (m["kind"], m["source"], m["message"]) == ("behind", "mock", "Flip it over first.")
        assert recv_json(ui, lambda s: is_state(s) and s["mistake"])["mistake"]["source"] == "mock"
        ui.send_json({"type": "dismiss_mistake"})
        assert recv_json(ui, lambda s: is_state(s) and s["mistake"] is None)["step"] == 1


# ---------------------------------------------------------------- per-client sender

class FakeSocket:
    """Records what a UIClient sends; `stall` makes every send hang."""

    def __init__(self, stall: bool = False):
        self.stall = stall
        self.sent: list[Any] = []
        self.closed: int | None = None

    async def send_text(self, text: str) -> None:
        if self.stall:
            await anyio.sleep(60)
        self.sent.append(json.loads(text))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = code


def run_sender(client: main.UIClient, seconds: float) -> None:
    """Run the client's sender for a while on a fresh loop, then stop it."""
    import asyncio

    async def go() -> None:
        task = asyncio.create_task(client.sender())
        await asyncio.sleep(seconds)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())


def test_sender_keeps_latest_state_and_event_order() -> None:
    ws = FakeSocket()
    client = main.UIClient(ws, "ui-test")  # type: ignore[arg-type]
    client.push({"type": "state", "step": 0})
    client.push({"type": "advance", "from": 0, "to": 1, "reason": "camera"})
    client.push({"type": "state", "step": 1})
    client.push({"type": "mistake", "step": 1})
    for i in range(5):
        client.push(b"\xff\xd8frame%d" % i)  # only the newest unsent frame is kept
    run_sender(client, 0.1)
    kinds = [m["type"] if isinstance(m, dict) else "frame" for m in ws.sent]
    assert kinds == ["advance", "mistake", "state", "frame"], kinds
    assert ws.sent[2]["step"] == 1 and ws.sent[3] == b"\xff\xd8frame4"  # latest state, then the newest frame


def test_sender_full_queue_drops_oldest_text_never_state() -> None:
    ws = FakeSocket()
    client = main.UIClient(ws, "ui-full")  # type: ignore[arg-type]
    client.push({"type": "state", "step": 3})
    for i in range(main.EVENT_QUEUE_MAX + 5):
        client.push({"type": "error", "message": str(i)})
    run_sender(client, 0.2)
    texts = [m["message"] for m in ws.sent if m["type"] == "error"]
    assert len(texts) == main.EVENT_QUEUE_MAX and texts[0] == "5" and texts[-1] == str(main.EVENT_QUEUE_MAX + 4)
    assert ws.sent[-1] == {"type": "state", "step": 3}


def test_sender_closes_1011_when_stalled() -> None:
    ws = FakeSocket(stall=True)
    client = main.UIClient(ws, "ui-stalled")  # type: ignore[arg-type]
    client.push({"type": "state", "step": 0})
    with patched(main, SEND_TIMEOUT=0.1):
        run_sender(client, 0.4)
    assert ws.closed == main.CLOSE_STALLED and ws.sent == []


# ---------------------------------------------------------------- events, logs, request ids

def test_events_reach_list_sink() -> None:
    make_lesson()
    events: list[dict] = []

    def broken(event: dict) -> None:
        raise RuntimeError("sink down")

    with env(HANDOVER_MOCK_PASS_SECONDS="0", HANDOVER_DEBOUNCE_N="1"), patched(main, VERIFIED_HOLD=0.05), \
            patched(main, EVENT_SINKS=[broken, events.append]), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        ui.send_json({"type": "next", "reason": "button", "from": 0})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 1)
        deadline = time.monotonic() + 10
        while not main.engine.done and time.monotonic() < deadline:
            cam.send_bytes(FRAME)
            time.sleep(0.1)
        wait_for(lambda: any(e["kind"] == "run_done" for e in events))
    kinds = [e["kind"] for e in events]
    assert kinds[:3] == ["run_start", "step_enter", "advance"], kinds
    assert {"check", "run_done"} <= set(kinds)
    run_ids = {e["run_id"] for e in events}
    assert len(run_ids) == 1 and None not in run_ids
    for e in events:
        assert {"event_id", "ts", "run_id", "lesson_id", "rev", "kind"} <= e.keys() and e["ts"].endswith("Z")
        assert e["lesson_id"] == LESSON
    first = next(e for e in events if e["kind"] == "step_enter")
    assert first == {**first, "step": 0, "check_type": "camera", "expert_seconds": 1.0}
    adv = next(e for e in events if e["kind"] == "advance")
    assert (adv["from"], adv["to"], adv["reason"]) == (0, 1, "button") and adv["step_seconds"] >= 0
    chk = next(e for e in events if e["kind"] == "check")
    assert chk["model"] == "mock" and chk["error_kind"] is None and chk["gated"] is False
    done = next(e for e in events if e["kind"] == "run_done")
    assert (done["camera_steps"], done["manual_steps"], done["mistakes"]) == (2, 1, 0)
    assert len(json.dumps(events)) < 20_000  # small metadata only, never frames


class FakeDatabricks:
    """Records the server.databricks calls the adapter sink makes."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start_run(self, lesson_id: str, learner: str | None = None) -> str:
        self.calls.append(("start_run", lesson_id))
        return "db-run"

    def end_run(self) -> None:
        self.calls.append(("end_run",))

    def emit(self, kind: str, /, **fields: Any) -> None:
        self.calls.append(("emit", kind, fields))

    def upload_lesson_files(self, lesson_dir: Path, lesson_id: str) -> None:
        self.calls.append(("upload", lesson_id))


def test_databricks_adapter() -> None:
    import sys

    make_lesson()
    fake = FakeDatabricks()
    old = sys.modules.get("server.databricks")
    sys.modules["server.databricks"] = fake  # type: ignore[assignment]
    sink = [main.databricks_sink]
    try:
        with env(HANDOVER_MOCK_PASS_SECONDS="0", HANDOVER_DEBOUNCE_N="1"), patched(main, VERIFIED_HOLD=0.05), \
                patched(main, EVENT_SINKS=sink), hub() as c, c.websocket_connect("/ws/ui") as ui, \
                c.websocket_connect("/ws/camera") as cam:
            assert sink == [main.databricks_sink]  # lifespan does not add it twice
            select(ui)
            deadline = time.monotonic() + 10
            while not main.engine.done and time.monotonic() < deadline:
                cam.send_bytes(FRAME)
                time.sleep(0.1)
            behind = {"type": "mistake", "step": main.engine.step, "kind": "behind", "looks_like": 1, "message": "m",
                      "confidence": 0.9, "source": "gemini"}
            main.engine._raise_mistake(behind)  # ignored: the lesson is done
            main.engine.done = False
            main.engine._raise_mistake(behind)
            main.engine.breaker.force_open("rate_limited", time.monotonic())
            with env(HANDOVER_CHECK=None):
                main.engine.sync_offline()
                main.engine.breaker.record(check.CheckResult("yes", 0.9, 1), time.monotonic())
                main.engine.sync_offline()
            from server import teach
            with patched(teach, recut=lambda d: {"id": LESSON, "steps": []}):
                assert c.post(f"/api/lessons/{LESSON}/recut").status_code == 200
    finally:
        if old is None:
            sys.modules.pop("server.databricks", None)
        else:
            sys.modules["server.databricks"] = old
    names = [x[0] if x[0] != "emit" else x[1] for x in fake.calls]
    assert names[:3] == ["end_run", "start_run", "step_enter"], names
    assert fake.calls[1] == ("start_run", LESSON)
    adv = next(x[2] for x in fake.calls if x[:2] == ("emit", "advance"))
    assert (adv["from_step"], adv["to_step"], adv["reason"]) == (0, 1, "camera") and "step_seconds" in adv
    chk = next(x[2] for x in fake.calls if x[:2] == ("emit", "check"))
    assert {"step", "done", "confidence", "latency_ms", "reason"} <= chk.keys() and "kind" not in chk
    mis = next(x[2] for x in fake.calls if x[:2] == ("emit", "mistake"))
    assert (mis["kind"], mis["looks_like"], mis["confidence"]) == ("behind", 1, 0.9)
    offline = [(x[2]["open"], x[2]["reason"]) for x in fake.calls if x[:2] == ("emit", "check_offline")]
    assert offline == [(True, "rate_limited"), (False, None)], offline
    done = next(x[2] for x in fake.calls if x[:2] == ("emit", "run_done"))
    assert {"total_seconds", "camera_steps", "manual_steps", "mistakes"} <= done.keys()
    assert names[names.index("run_done") + 1] == "end_run"
    assert chk["hub_run_id"] and isinstance(chk["rev"], int) and chk["hub_ts"].endswith("Z")
    assert "run_start" not in names and "run_end" not in names
    assert names[-1] == "upload" and fake.calls[-1] == ("upload", LESSON)


def test_run_stops_on_delete_and_shutdown() -> None:
    events: list[dict] = []
    make_lesson("stop-a")
    make_lesson("stop-b")
    with patched(main, EVENT_SINKS=[events.append]):
        with hub() as c, c.websocket_connect("/ws/ui") as ui:
            select(ui, "stop-a")
            assert c.delete("/api/lessons/stop-a").status_code == 200
            select(ui, "stop-b")
        stops = [e["reason"] for e in events if e["kind"] == "run_stop"]
    assert stops == ["deleted", "shutdown"], stops


def test_request_id_header() -> None:
    with hub() as c:
        r = c.get("/api/lessons")
        assert main.REQUEST_ID_RE.match(r.headers["x-request-id"])
        assert c.get("/api/lessons", headers={"x-request-id": "abc-123"}).headers["x-request-id"] == "abc-123"
        assert c.get("/", headers={"x-request-id": "bad id!"}).headers["x-request-id"] != "bad id!"


def test_json_log_lines() -> None:
    import logging

    record = logging.LogRecord("handover", logging.INFO, __file__, 1, "step %d -> %d", (0, 1), None)
    main.ContextFilter().filter(record)
    out = json.loads(main.JsonFormatter().format(record))
    assert (out["level"], out["logger"], out["msg"], out["ctx"]) == ("INFO", "handover", "step 0 -> 1", "-")


def test_snapshot_has_counters() -> None:
    with hub() as c, c.websocket_connect("/ws/camera") as cam:
        cam.send_bytes(FRAME)
        wait_for(lambda: main.metrics["frames_in"] > 0)
        snap = main.engine.snapshot()
        assert snap["cameras"] == 1 and snap["check_mode"] == "mock" and snap["counters"]["frames_in"] > 0


# ---------------------------------------------------------------- REST: web app and DELETE

def test_root_serves_dist_and_falls_back() -> None:
    dist = TMP / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>HandOver</title>", "utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)", "utf-8")
    (dist / "assets" / "index-abc.css").write_text("body{}", "utf-8")
    (TMP / "secret.txt").write_text("no", "utf-8")
    make_lesson()
    with hub() as c:
        with patched(main, WEB_DIST=dist):
            r = c.get("/")
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and "HandOver" in r.text
            js, css = c.get("/assets/index-abc.js"), c.get("/assets/index-abc.css")
            assert js.headers["content-type"].startswith("text/javascript"), js.headers
            assert css.headers["content-type"].startswith("text/css")
            assert c.get("/assets/missing.js").status_code == 404
            assert c.get("/assets/%2e%2e/%2e%2e/secret.txt").status_code == 404
            assert c.get("/api/lessons").json()[0]["id"] == LESSON  # not shadowed
            assert c.get(f"/lessons/{LESSON}/lesson.json").status_code == 200
            assert c.get("/capture").headers["content-type"].startswith("text/html")
        with patched(main, WEB_DIST=TMP / "no-dist"):
            assert c.get("/").json()["api"] == "/api/lessons"
            assert c.get("/assets/index-abc.js").status_code == 404


def test_delete_lesson_clears_active() -> None:
    d = make_lesson("to-delete")
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        select(ui, "to-delete")
        r = c.delete("/api/lessons/to-delete")
        assert r.status_code == 200 and r.json() == {"deleted": "to-delete"}
        st = recv_json(ui, lambda m: is_state(m) and m["lesson_id"] is None)
        assert st["total"] == 0 and st["step"] == 0 and not d.exists()
        assert c.delete("/api/lessons/to-delete").status_code == 404
        assert c.delete("/api/lessons/bad%20id").status_code == 400
        (main.LESSONS / "half-built").mkdir()  # a teach job still building: not a lesson yet
        assert c.delete("/api/lessons/half-built").status_code == 404 and (main.LESSONS / "half-built").exists()


# ---------------------------------------------------------------- hardening (Phase 4)

class HeldLock:
    """Stands in for lesson_write_lock while another recut or delete holds it."""

    def locked(self) -> bool:
        return True


@contextlib.contextmanager
def no_jobs_run() -> Iterator[list[tuple]]:
    """Uploads are accepted but the teach thread only records its arguments."""
    calls: list[tuple] = []
    with patched(main, _run_job=lambda *args: calls.append(args)):
        yield calls
    for args in calls:
        args[1].unlink(missing_ok=True)


def upload(c: TestClient, name: str = "v.mp4", **data: str) -> Any:
    return c.post("/api/lesson", files={"file": (name, b"\0" * 100, "video/mp4")}, data=data)


def test_upload_reserves_id_before_saving() -> None:
    with hub() as c, no_jobs_run() as calls:
        first, second = upload(c, id="Same Id"), upload(c, id="same-id")
        assert first.status_code == 200 and second.status_code == 409, (first.text, second.text)
        a, b = upload(c, title="Twin"), upload(c, title="Twin")
        assert a.json()["id"] != b.json()["id"]
        assert main.jobs[first.json()["job"]]["status"] == "queued" and len(calls) == 3
    main.jobs.clear()


def test_failed_save_marks_job_error() -> None:
    with hub() as c, no_jobs_run(), patched(main, save_upload=lambda file, dest: False):  # size known only while saving
        assert upload(c, title="Big").status_code == 413
        assert [j for j in main.jobs.values()] == [{"status": "error", "message": "video is larger than 2 GB",
                                                    "id": "big"}]
    main.jobs.clear()


def test_upload_suffix_allowlist_and_blank_title() -> None:
    with hub() as c, no_jobs_run() as calls:
        assert upload(c, "evil.m3u8").status_code == 200  # no title field at all
        assert upload(c, "clip.MOV", title="Mov").status_code == 200
        assert calls[0][1].suffix == ".mp4" and calls[0][3] == "Untitled lesson"
        assert calls[1][1].suffix == ".mov"
    main.jobs.clear()


def test_upload_limits_429_411_413() -> None:
    with hub() as c, no_jobs_run():
        main.jobs.update({f"busy{i}": {"status": "queued", "message": "", "id": f"busy{i}"} for i in range(3)})
        r = upload(c, title="Fourth")
        assert (r.status_code, r.json()["detail"]) == (429, "too many jobs")
        main.jobs.clear()
        chunked = c.post("/api/lesson", content=iter([b"--x\r\n"]),
                         headers={"content-type": "multipart/form-data; boundary=x"})
        assert (chunked.status_code, chunked.json()["detail"]) == (411, "content length required")
        assert chunked.headers["x-request-id"]
        with patched(main, MAX_UPLOAD_BYTES=10):
            big = c.post("/api/lesson", files={"file": ("v.mp4", b"\0" * (1024**2 + 100), "video/mp4")})
            assert big.status_code == 413 and main.jobs == {}  # refused before a job or a file existed
    main.jobs.clear()


def test_one_teach_job_at_a_time() -> None:
    from server import teach

    running, peak = [0], [0]
    lock = __import__("threading").Lock()

    def slow(src: Path, lesson_id: str, title: str, progress: Callable) -> None:
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.3)
        with lock:
            running[0] -= 1
        raise RuntimeError(f"stop at {main.LESSONS}/x")  # also checks the redaction below

    import threading
    with patched(teach, process_upload=slow):
        for i in range(2):
            main.jobs[f"j{i}"] = {"status": "queued", "message": "", "id": f"slot-{i}"}
        threads = [threading.Thread(target=main._run_job, args=(f"j{i}", TMP / f"none{i}.mp4", f"slot-{i}", "t"))
                   for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert peak[0] == 1
    assert main.jobs["j0"]["message"] == "RuntimeError: stop at <lessons>/x"
    main.jobs.clear()


def test_recut_lock_and_body_rules() -> None:
    make_lesson()
    url = f"/api/lessons/{LESSON}/recut"
    with hub() as c:
        with patched(main, lesson_write_lock=HeldLock()):
            assert c.post(url).json()["detail"] == "recut already running"
            r = c.delete(f"/api/lessons/{LESSON}")
            assert (r.status_code, r.json()["detail"]) == (409, "recut already running")
        big = c.post(url, content=b" " * (main.MAX_RECUT_BODY + 1), headers={"content-type": "application/json"})
        assert (big.status_code, big.json()["detail"]) == (413, "body is larger than 1 MB")
        plain = c.post(url, content=b'{"steps": []}', headers={"content-type": "text/plain"})
        assert plain.status_code == 415
        many = c.post(url, json={"steps": [{"start": "00:00", "end": "00:01"}] * 51})
        assert (many.status_code, many.json()["detail"]) == (400, "too many steps")


def test_recut_500_is_redacted() -> None:
    from server import teach

    make_lesson()

    def broken(d: Path) -> dict:
        raise OSError(f"cannot write {d}/clips/01.mp4 under {main.REPO}")

    with hub() as c, patched(teach, recut=broken):
        r = c.post(f"/api/lessons/{LESSON}/recut")
    assert r.status_code == 500 and str(main.LESSONS) not in r.text and "<lessons>" in r.json()["detail"]


def test_no_key_shows_offline_at_startup() -> None:
    with env(HANDOVER_CHECK=None), patched(check, has_key=lambda: False), hub() as c, \
            c.websocket_connect("/ws/ui") as ui:
        st = recv_json(ui, is_state)
        assert (st["check_offline"], st["check_offline_reason"]) == (True, "no_key")


def test_mock_mistake_hook_not_after_yes() -> None:
    make_lesson()
    engine = main.Engine()
    engine.select(LESSON)
    engine.go(1, "button")
    engine.step_started -= 10
    engine.cameras = 1
    with env(HANDOVER_MOCK_MISTAKE="behind:1"):
        engine.last_check = {"done": "yes", "confidence": 0.9, "latency_ms": 1, "reason": None}
        engine._mock_tick()
        assert engine.mistake is None
        engine.last_check, engine.mock_tick_at = None, 0.0  # no check yet on this step counts as not yes
        engine._mock_tick()
        assert engine.mistake is not None and engine.mistake["kind"] == "behind"


def test_mock_mistake_fires_with_gate_on() -> None:
    """Identical frames: the gate holds checks back after the first, yet the planted mistake still fires."""
    make_lesson()
    fired_at = None
    with env(HANDOVER_GATE="1", HANDOVER_MOCK_MISTAKE="behind:1", HANDOVER_MOCK_PASS_SECONDS="100"), \
            patched(mistake, MOCK_AFTER_S=2.0), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        ui.send_json({"type": "goto", "step": 1})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 1)
        start, checks_before = time.monotonic(), main.metrics["checks"]
        while time.monotonic() - start < 5 and main.engine.mistake is None:
            cam.send_bytes(FRAME)
            time.sleep(0.25)
        fired_at = time.monotonic() - start
        m = recv_json(ui, lambda m: m["type"] == "mistake")
        assert (m["step"], m["kind"], m["source"]) == (1, "behind", "mock")
        checks_in_window = main.metrics["checks"] - checks_before
    assert fired_at < 3.6, fired_at  # 2 s delay plus at most one tick and a frame
    assert checks_in_window <= 1, checks_in_window  # the gate held checks back, so a result-driven hook never ran


def test_parse_message_limits() -> None:
    assert main.parse_message('{"type": "next"}') == {"type": "next"}
    assert main.parse_message('{"type": "x", "pad": "' + "a" * 9000 + '"}') is None
    assert main.parse_message("[" * 5000 + "]" * 5000) is None  # too long
    with patched(main, MAX_TEXT_MESSAGE=10**7):
        assert main.parse_message("[" * 200000 + "]" * 200000) is None  # RecursionError is caught


def test_camera_and_viewer_caps_and_frame_gap() -> None:
    with env(HANDOVER_MAX_CAMERAS="1", HANDOVER_MAX_VIEWERS="1"), hub() as c:
        with c.websocket_connect("/ws/camera"), c.websocket_connect("/ws/camera") as extra:
            msg = recv(extra)
            assert (msg["type"], msg["code"]) == ("websocket.close", 1013)
        with c.websocket_connect("/ws/ui"), c.websocket_connect("/ws/ui") as extra:
            msg = recv(extra)
            assert (msg["type"], msg["code"]) == ("websocket.close", 1013)
    with env(HANDOVER_MIN_FRAME_GAP="0.2"), hub() as c, c.websocket_connect("/ws/camera") as cam:
        for _ in range(3):
            cam.send_bytes(FRAME)  # back to back: only the first counts
        time.sleep(0.25)
        cam.send_bytes(FRAME)
        wait_for(lambda: main.engine.frame_seq == 2)
        time.sleep(0.1)
        assert main.engine.frame_seq == 2


def test_check_loop_survives_a_failing_iteration() -> None:
    make_lesson()
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 1))
    with patched(check, check_frame=fake), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        real, failed = main.engine._next_job, []

        def flaky() -> Any:
            if not failed:
                failed.append(1)
                raise RuntimeError("bad lesson data")
            return real()

        main.engine._next_job = flaky  # type: ignore[method-assign]
        cam.send_bytes(FRAME)
        time.sleep(0.2)
        cam.send_bytes(jpeg((5, 5, 5)))
        wait_for(lambda: len(fake.calls) == 1)
        assert failed


def test_ref_frame_default_and_non_string() -> None:
    d = make_lesson("ref-default")
    lesson = json.loads((d / "lesson.json").read_text("utf-8"))
    del lesson["steps"][0]["ref_frame"]
    lesson["steps"][1]["ref_frame"] = 42
    (d / "lesson.json").write_text(json.dumps(lesson), "utf-8")
    engine = main.Engine()
    engine.select("ref-default")
    assert engine.ref_bytes(0) == (d / "frames" / "01.jpg").read_bytes()
    assert engine.ref_bytes(1) is None and engine.ref_bytes(7) is None


def test_lesson_json_not_an_object() -> None:
    d = main.LESSONS / "not-object"
    d.mkdir(parents=True, exist_ok=True)
    (d / "lesson.json").write_text("[1, 2]", "utf-8")
    with hub() as c:
        r = c.get("/api/lessons/not-object")
        assert (r.status_code, r.json()["detail"]) == (500, "lesson.json unreadable: not an object")
        assert "not-object" not in [x["id"] for x in c.get("/api/lessons").json()]
    shutil.rmtree(d)


def test_startup_cleanup_lists_by_default_and_removes_only_when_enabled() -> None:
    uploads = TMP / "uploads-cleanup"
    uploads.mkdir(exist_ok=True)
    old, fresh = uploads / "old.mp4", uploads / "fresh.mp4"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    d = make_lesson("cleanup")
    (d / ".recut_tmp").mkdir()
    (d / ".recut_tmp" / "01.mp4").write_bytes(b"x")
    long_ago = time.time() - 2 * main.STALE_TEMP_SECONDS
    for p in (old, d / ".recut_tmp"):
        os.utime(p, (long_ago, long_ago))
    with patched(main, UPLOADS=uploads), env(HANDOVER_STARTUP_CLEANUP=None):
        listed = main.startup_cleanup()  # default: log-only
    assert set(listed) == {old, d / ".recut_tmp"} and old.exists() and (d / ".recut_tmp" / "01.mp4").exists()
    with patched(main, UPLOADS=uploads), env(HANDOVER_STARTUP_CLEANUP="1"):
        removed = main.startup_cleanup()
    assert set(removed) == {old, d / ".recut_tmp"} and not old.exists() and not (d / ".recut_tmp").exists()
    assert fresh.exists() and (d / "lesson.json").exists() and (d / "frames" / "01.jpg").exists()


def test_rev_only_increases() -> None:
    newer, older = make_lesson("rev-new"), make_lesson("rev-old")
    os.utime(older / "lesson.json", (1_000_000, 1_000_000))
    engine = main.Engine()
    engine.select("rev-new")
    first = engine.rev
    engine.select("rev-new")
    assert engine.rev == first  # same file again: nothing to refetch
    engine.select("rev-old")  # its mtime is far older
    assert engine.rev == first + 1
    assert newer.exists()


# ---------------------------------------------------------------- M15: learn frames never touch disk

class WriteGuard:
    """Fails every file write outside `allowed` and records it, so a write caught by a broad except still counts."""

    WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    def __init__(self, allowed: Path):
        self.allowed = allowed.resolve()
        self.violations: list[str] = []

    def _check(self, path: Any) -> None:
        if isinstance(path, int):
            return  # an already open descriptor
        p = Path(os.fsdecode(path)).resolve()
        if self.allowed not in p.parents:
            self.violations.append(str(p))
            raise PermissionError(f"privacy test: write blocked: {p}")

    @contextlib.contextmanager
    def active(self) -> Iterator[None]:
        real_open, real_os_open = builtins.open, os.open
        real_save = Image.Image.save
        real_wb, real_wt = pathlib.Path.write_bytes, pathlib.Path.write_text
        guard = self

        def g_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if any(ch in mode for ch in "wax+"):
                guard._check(file)
            return real_open(file, mode, *args, **kwargs)

        def g_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if flags & guard.WRITE_FLAGS:
                guard._check(path)
            return real_os_open(path, flags, *args, **kwargs)

        def g_save(im: Image.Image, fp: Any, *args: Any, **kwargs: Any) -> None:
            if isinstance(fp, (str, bytes, os.PathLike)):
                guard._check(fp)
            return real_save(im, fp, *args, **kwargs)

        def g_wb(p: pathlib.Path, data: bytes) -> int:
            guard._check(p)
            return real_wb(p, data)

        def g_wt(p: pathlib.Path, data: str, *args: Any, **kwargs: Any) -> int:
            guard._check(p)
            return real_wt(p, data, *args, **kwargs)

        builtins.open = io.open = g_open
        os.open, Image.Image.save = g_os_open, g_save
        pathlib.Path.write_bytes, pathlib.Path.write_text = g_wb, g_wt
        try:
            yield
        finally:
            builtins.open = io.open = real_open
            os.open, Image.Image.save = real_os_open, real_save
            pathlib.Path.write_bytes, pathlib.Path.write_text = real_wb, real_wt


def files_under(*roots: Path) -> set[Path]:
    skip = {".git", ".venv", "node_modules", "__pycache__"}
    out: set[Path] = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            out.update(Path(dirpath) / f for f in filenames)
    return out


def test_privacy_learn_frames_never_touch_disk() -> None:
    make_lesson()
    scratch = TMP / "scratch"
    scratch.mkdir(exist_ok=True)
    guard = WriteGuard(scratch)
    with guard.active():  # the guard really blocks: a write under the repo fails and is recorded
        try:
            (main.REPO / "privacy-probe.jpg").write_bytes(FRAME)
            raise AssertionError("guard did not block a repo write")
        except PermissionError:
            pass
        with contextlib.suppress(PermissionError):
            Image.new("RGB", (4, 4)).save(main.LESSONS / "probe.jpg")
    assert len(guard.violations) == 2 and not (main.REPO / "privacy-probe.jpg").exists()
    guard.violations.clear()

    before = files_under(main.REPO, main.LESSONS)
    with env(HANDOVER_GATE="1", HANDOVER_MOCK_PASS_SECONDS="0", HANDOVER_DEBOUNCE_N="1"), \
            patched(main, VERIFIED_HOLD=0.1), hub() as c, guard.active(), \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        cam.send_json({"type": "hello", "device_id": "replay-1", "name": "Replay: fold.mp4", "platform": "replay",
                       "source": "file"})
        assert select(ui)["camera"]["source"] == "file"
        deadline = time.monotonic() + 15
        while not main.engine.done and time.monotonic() < deadline:
            cam.send_bytes(FRAME)  # a replay-style stream at 10 fps
            time.sleep(0.1)
        got = drain(ui, 0.3)
    assert main.engine.done, "the mock session did not reach done; frames were not processed"
    assert any(m.get("bytes") for m in got), "no live frames reached the UI"
    mirror = TMP / "scratch" / "events.jsonl"  # server.databricks wrote events (metadata) during the session
    if main.databricks_module() is not None:
        lines = mirror.read_text("utf-8").splitlines()
        assert lines and all(len(line) < 4096 and "\\xff\\xd8" not in line for line in lines)
    assert guard.violations == [], guard.violations
    created = files_under(main.REPO, main.LESSONS) - before
    leaked = [p for p in created if main.LESSONS in p.parents or p.read_bytes()[:2] == b"\xff\xd8"]
    assert leaked == [], leaked


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

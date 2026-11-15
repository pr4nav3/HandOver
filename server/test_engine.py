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
os.environ["HANDOVER_CHECK_INTERVAL_S"] = "0.2"  # the floor: pipelining tests need checks close together; test_check_interval covers 1 s
os.environ.pop("HANDOVER_MOCK_MISTAKE", None)
os.environ["HANDOVER_EVENTS_JSONL"] = str(TMP / "scratch" / "events.jsonl")  # server.databricks local mirror
os.environ["HANDOVER_DATA"] = str(TMP / "data")  # accounts and library state, never the repo's
os.environ.pop("HANDOVER_AUTH", None)

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
    """Gemini mode with a key present; each test replaces the Gemini calls itself. The provider is pinned, so a
    Claude key in the environment or <repo>/.env cannot turn this into a Claude run."""
    with env(HANDOVER_CHECK=None, HANDOVER_CHECK_PROVIDER="gemini"), patched(check, has_key=lambda: True):
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
            assert st["camera"] == {"name": "Camera 1", "platform": "other", "source": "unknown"}
            for bad in ({"platform": 5}, {"source": 5}, {"name": ["x"]}, {"device_id": {}}):
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


def test_hello_platforms_new_apps_and_other() -> None:
    """Android and desktop apps are named; any other platform string is "other" and still unlocks next."""
    for platform, want in (("android", "android"), ("macos", "macos"), ("windows", "windows"), ("linux", "linux"),
                           ("ios", "ios"), ("Android", "android"), ("visionos", "other"), ("  ", None)):
        fields = main.parse_hello({"type": "hello", "platform": platform})
        assert fields is not None and fields.get("platform") == want, (platform, fields)
    assert main.parse_hello({"type": "hello", "platform": None}) is None
    make_lesson()
    with hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        cam.send_json(hello(platform="tizen"))
        assert recv_json(ui, lambda m: is_state(m) and m["camera"] and m["camera"]["name"] == "Test phone"
                         )["camera"]["platform"] == "other"
        cam.send_json({"type": "next", "reason": "button", "from": 0})
        assert recv_json(ui, lambda m: m["type"] == "advance")["reason"] == "button"


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
        assert st["check_interval_s"] == 0.2 and st["ui_fps"] == 15  # this module sets the 0.2 s floor
        assert isinstance(st["ui_fps"], int)


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


def test_jpeg_size_reads_the_header() -> None:
    for size in ((640, 360), (1280, 720), (17, 3000)):
        assert main.jpeg_size(jpeg((10, 20, 30), size)) == size
    buf = io.BytesIO()
    Image.new("RGB", (300, 200)).save(buf, format="JPEG", progressive=True)
    assert main.jpeg_size(buf.getvalue()) == (300, 200)
    for bad in (b"", b"\xff\xd8", b"not a jpeg", FRAME[:40]):
        assert main.jpeg_size(bad) is None


def test_fifteen_fps_in_gives_capped_ui_fps_and_normal_check_rate() -> None:
    """A sender at 15 fps with about 640 px frames: viewers get the camera's own bytes (no re-encode) at no
    more than HANDOVER_UI_FPS, the motion gate decodes at most 4 frames a second, and a still scene still gets
    the normal check rate (one check when it settles, then the heartbeat), never one check per frame."""
    make_lesson()
    small = jpeg((90, 90, 90), (640, 360))
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 1))
    seconds = 2.0
    for fps in (15, 5):
        with env(HANDOVER_GATE="1", HANDOVER_UI_FPS=str(fps), HANDOVER_MIN_FRAME_GAP=None), \
                patched(check, check_frame=fake), hub() as c, c.websocket_connect("/ws/ui") as ui, \
                c.websocket_connect("/ws/camera") as cam:
            select(ui)
            drain(ui, 0.2)
            fake.calls.clear()
            gated0 = main.metrics["frames_gated"]
            start = time.monotonic()
            sent = 0
            while time.monotonic() - start < seconds:
                cam.send_bytes(small)
                sent += 1
                time.sleep(1 / 15)
            frames = [m["bytes"] for m in drain(ui, 0.3) if m.get("bytes")]
            gated = main.metrics["frames_gated"] - gated0
        assert sent >= 25, sent
        assert frames and all(f == small for f in frames)  # forwarded as is
        assert len(frames) <= fps * seconds + 2, (fps, len(frames))
        assert len(frames) >= min(fps, 15) * seconds * 0.5, (fps, len(frames))  # and really near the cap
        assert gated <= seconds / main.GATE_MIN_INTERVAL + 2, gated
        assert len(fake.calls) <= 2, len(fake.calls)  # settled once; the 6 s heartbeat is not due yet


def test_frame_to_ui_adds_little_latency() -> None:
    """Passthrough path: from a frame arriving to it reaching a viewer's sender, well under 20 ms on average."""
    make_lesson()
    small = jpeg((40, 90, 140), (640, 360))
    with env(HANDOVER_UI_FPS="30", HANDOVER_MIN_FRAME_GAP=None), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        drain(ui, 0.2)
        client = next(iter(main.engine.ui))
        stamps: list[float] = []
        orig = client.push

        def push(msg: Any) -> None:
            if isinstance(msg, bytes):
                stamps.append(time.monotonic())
            orig(msg)

        client.push = push  # type: ignore[method-assign]
        orig_on_frame = main.engine.on_frame
        arrived: list[float] = []

        def on_frame(data: bytes) -> None:
            arrived.append(time.monotonic())
            orig_on_frame(data)

        main.engine.on_frame = on_frame  # type: ignore[method-assign]
        for _ in range(10):
            cam.send_bytes(small)
            time.sleep(0.1)  # slower than the cap, so no frame waits for its slot
        drain(ui, 0.2)
    pairs = list(zip(arrived, stamps))
    assert len(pairs) >= 8, (len(arrived), len(stamps))
    delays = sorted(b - a for a, b in pairs)
    assert delays[len(delays) // 2] < 0.02, delays


def test_set_check_interval_clamps_and_broadcasts() -> None:
    """set_check_interval works with no lesson, is clamped to 0.2..10, and every state carries the value;
    bad values are ignored."""
    with env(HANDOVER_CHECK_INTERVAL_S=None, HANDOVER_UI_FPS="20"), hub() as c, c.websocket_connect("/ws/ui") as ui:
        st = recv_json(ui, is_state)
        assert st["check_interval_s"] == 1.0 and st["ui_fps"] == 20  # registry default, env value
        for sent, want in ((0.5, 0.5), (2, 2.0), (0.01, 0.2), (99, 10.0), (0.2, 0.2)):
            ui.send_json({"type": "set_check_interval", "seconds": sent})
            st = recv_json(ui, is_state)
            assert st["check_interval_s"] == want, (sent, st["check_interval_s"])
        for bad in ("1", True, None, [1]):
            ui.send_json({"type": "set_check_interval", "seconds": bad})
        ui.send_text('{"type":"set_check_interval","seconds":NaN}')
        assert not [m for m in drain(ui, 0.3) if m.get("text")]  # ignored: no state, no error
        assert main.engine.check_interval_s() == 0.2
        make_lesson()
        assert select(ui)["check_interval_s"] == 0.2  # kept across select_lesson


def test_check_interval_caps_model_calls_at_camera_rate() -> None:
    """A 12 fps camera with the gate off (every frame wanted): the model is offered at most one frame per
    check_interval_s, and a set_check_interval takes effect at once."""
    make_lesson()
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 1))
    with env(HANDOVER_CHECK_INTERVAL_S=None), patched(check, check_frame=fake), hub() as c,             c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)

        def stream(seconds: float) -> int:
            start, n = time.monotonic(), 0
            while time.monotonic() - start < seconds:
                cam.send_bytes(jpeg((n % 200, 90, 90), (320, 240)))
                n += 1
                time.sleep(1 / 12)
            return n

        fake.calls.clear()
        sent = stream(2.5)
        assert sent >= 20, sent
        assert 2 <= len(fake.calls) <= 3, len(fake.calls)  # 1 s default: about 2.5 checks, never one per frame
        gaps = [b - a for a, b in zip(fake.times, fake.times[1:])]
        assert all(g >= 0.95 for g in gaps), gaps
        ui.send_json({"type": "set_check_interval", "seconds": 0.5})
        recv_json(ui, lambda m: is_state(m) and m["check_interval_s"] == 0.5)
        fake.calls.clear()
        fake.times.clear()
        stream(2.5)
        assert 4 <= len(fake.calls) <= 6, len(fake.calls)
        gaps = [b - a for a, b in zip(fake.times, fake.times[1:])]
        assert all(g >= 0.45 for g in gaps), gaps


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


# ---------------------------------------------------------------- provenance and latency

def test_state_check_mode_names_the_real_provider() -> None:
    with hub():
        assert main.engine.state()["check_mode"] == "mock"
        with gemini():
            assert main.engine.state()["check_mode"] == "gemini"
        with env(HANDOVER_CHECK=None, HANDOVER_CHECK_PROVIDER="claude"):
            assert main.engine.state()["check_mode"] == "claude"
            assert main.engine.snapshot()["check_mode"] == "claude"


def test_check_event_and_mistake_source_name_the_real_provider() -> None:
    make_lesson()
    events: list[dict] = []

    async def compare(live: bytes, pairs: list[tuple[int, bytes]], question: str | None = None) -> check.MatchResult:
        return check.MatchResult(0, 0.9, 3)  # behind: looks like step 0 while on step 1

    with env(HANDOVER_CHECK=None, HANDOVER_CHECK_PROVIDER="claude", HANDOVER_CLAUDE_CHECK_MODEL="claude-test-model"), \
            patched(check, compare_refs=compare), patched(main, EVENT_SINKS=[events.append]):
        engine = main.Engine()
        engine.select(LESSON)
        engine.go(1, "button")
        job = main.CheckJob(1, "Is step 2 done?", engine.ref_bytes(1), FRAME, engine.version)
        engine._record_check(job, check.CheckResult("no", 0.9, 5))
        anyio.run(engine._compare_and_raise, job)
    chk = next(e for e in events if e["kind"] == "check")
    assert chk["model"] == "claude-test-model", chk
    mis = next(e for e in events if e["kind"] == "mistake")
    assert mis["source"] == "claude" and engine.mistake and engine.mistake["source"] == "claude", mis


def test_frame_debouncer_order_and_fast_path() -> None:
    def deb() -> main.FrameDebouncer:
        return main.FrameDebouncer()

    with env(HANDOVER_DEBOUNCE_N="2", HANDOVER_MIN_CONF="0.8", HANDOVER_FAST_PATH="0"):
        d = deb()
        assert not d.feed(2, "yes", 0.9) and d.count == 1
        assert d.feed(1, "yes", 0.9) and d.count == 0  # two frames, finished out of order
        d = deb()
        d.feed(1, "yes", 0.9), d.feed(3, "no", 0.9)
        assert not d.feed(2, "yes", 0.9) and d.count == 0  # the newest frame said no
        d = deb()
        d.feed(2, "no", 0.9), d.feed(3, "yes", 0.9)
        assert not d.feed(1, "yes", 0.9)  # a late yes for an older frame does not jump the no
        d = deb()
        d.feed(5, "yes", 0.9)
        assert not d.feed(4, "no", 0.9) and d.count == 1  # a late no for an older frame does not reset
        assert d.feed(6, "yes", 0.9)
        d = deb()
        d.feed(1, "yes", 0.79)
        assert not d.feed(2, "yes", 0.9)  # low confidence yes is not a yes
        assert not deb().feed(1, "yes", 0.99)  # fast path off
    with env(HANDOVER_DEBOUNCE_N="2", HANDOVER_MIN_CONF="0.8", HANDOVER_FAST_PATH=None, HANDOVER_FAST_CONF=None):
        assert deb().feed(1, "yes", 0.92)
        assert not deb().feed(1, "yes", 0.91)
        assert not deb().feed(1, "yes", 0.99, "seam still open")  # names a difference: needs a second yes
        d = deb()
        d.feed(2, "no", 0.9)
        assert not d.feed(1, "yes", 0.99)  # only the newest frame answered may take the fast path
        with env(HANDOVER_FAST_CONF="0.95"):
            assert not deb().feed(1, "yes", 0.94) and deb().feed(1, "yes", 0.95)
        with env(HANDOVER_FAST_CONF="7"):  # out of range: the default 0.92
            assert deb().feed(1, "yes", 0.92)
        with env(HANDOVER_MIN_CONF="0.97", HANDOVER_FAST_CONF="0.9"):
            assert not deb().feed(1, "yes", 0.95)  # never below the normal yes bar


class SlowCheck:
    """A check that takes `latency` seconds; records start and end times and the most checks at once."""

    def __init__(self, latency: float, done: str = "yes", confidence: float = 0.9):
        self.latency, self.done, self.confidence = latency, done, confidence
        self.starts: list[float] = []
        self.ends: list[float] = []
        self.running = 0
        self.peak = 0

    async def __call__(self, ref: bytes, live: bytes, question: str, *, step_started_at: float | None = None,
                       prev_ref: bytes | None = None) -> check.CheckResult:
        self.starts.append(time.monotonic())
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await anyio.sleep(self.latency)
        finally:
            self.running -= 1
        self.ends.append(time.monotonic())
        return check.CheckResult(self.done, self.confidence, int(self.latency * 1000))


def run_until_verified(cam: Any, timeout: float = 5.0, every: float = 0.15) -> float:
    """Streams identical frames every `every` s until the engine shows verified; returns when that happened."""
    deadline = time.monotonic() + timeout
    next_send = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_send:
            cam.send_bytes(FRAME)
            next_send = now + every
        if main.engine.verified:
            return time.monotonic()
        time.sleep(0.01)
    raise AssertionError("never verified")


def test_pipelined_confirm_halves_the_wait() -> None:
    """Two checks on different settled frames run at once; two yes answers verify after about one check
    latency. HANDOVER_MAX_INFLIGHT=1 is the old one-at-a-time behavior."""
    make_lesson()
    latency = 0.6
    took = {}
    for inflight in ("2", "1"):
        slow = SlowCheck(latency)
        with env(HANDOVER_GATE="1", HANDOVER_FAST_PATH="0", HANDOVER_DEBOUNCE_N="2", HANDOVER_MAX_INFLIGHT=inflight), \
                patched(check, check_frame=slow), patched(main, VERIFIED_HOLD=0.3), hub() as c, \
                c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
            select(ui)
            verified_at = run_until_verified(cam)
            took[inflight] = (verified_at - slow.starts[0], slow.peak)
            assert main.engine.status() == "verified" and main.engine.step == 0
            wait_for(lambda: main.engine.step == 1)
    assert took["2"][1] == 2 and took["1"][1] == 1, took
    assert took["2"][0] < latency + 0.35, took  # second check started on the next frame, not after the first
    assert took["1"][0] >= 2 * latency, took


def test_pipelined_stale_step_results_dropped() -> None:
    make_lesson()
    slow = SlowCheck(0.5)
    with env(HANDOVER_GATE="1", HANDOVER_FAST_PATH="0", HANDOVER_DEBOUNCE_N="2"), patched(check, check_frame=slow), \
            hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        for _ in range(8):  # the gate samples the newest frame every GATE_MIN_INTERVAL; settle, then pipeline
            cam.send_bytes(FRAME)
            time.sleep(0.12)
            if slow.running == 2:
                break
        wait_for(lambda: slow.running == 2, timeout=2)
        ui.send_json({"type": "goto", "step": 2})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 2)
        wait_for(lambda: slow.running == 0, timeout=2)
        time.sleep(0.1)
        assert main.engine.step == 2 and not main.engine.verified and main.engine.last_check is None


def test_fast_path_one_confident_yes_verifies() -> None:
    make_lesson()
    latency = 0.4
    slow = SlowCheck(latency, confidence=0.97)
    with env(HANDOVER_GATE="1", HANDOVER_DEBOUNCE_N="2", HANDOVER_FAST_PATH=None), patched(check, check_frame=slow), \
            patched(main, VERIFIED_HOLD=0.3), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        verified_at = run_until_verified(cam)
        assert len(slow.ends) == 1, slow.ends  # verified on the first answer
        assert verified_at - slow.starts[0] < latency + 0.2
        wait_for(lambda: main.engine.step == 1)
    low = SlowCheck(latency, confidence=0.9)  # below HANDOVER_FAST_CONF: still needs two
    with env(HANDOVER_GATE="1", HANDOVER_DEBOUNCE_N="2", HANDOVER_FAST_PATH=None), patched(check, check_frame=low), \
            hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        run_until_verified(cam)
        assert len(low.ends) == 2, low.ends


def test_next_clip_after_one_yes_and_verified_is_instant() -> None:
    make_lesson()
    answers = iter(["yes", "no", "yes", "yes", "yes"])
    fake = FakeCheck(lambda ref: check.CheckResult(next(answers, "yes"), 0.9, 1))
    with env(HANDOVER_DEBOUNCE_N="3", HANDOVER_FAST_PATH="0", HANDOVER_MAX_INFLIGHT="1"), \
            patched(check, check_frame=fake), patched(main, VERIFIED_HOLD=0.6), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        assert select(ui)["next_clip"] is None
        cam.send_bytes(jpeg((1, 1, 1)))
        st = recv_json(ui, lambda m: is_state(m) and m["last_check"] is not None)
        assert st["last_check"]["done"] == "yes" and st["next_clip"] == "clips/02.mp4", st
        cam.send_bytes(jpeg((2, 2, 2)))
        st = recv_json(ui, lambda m: is_state(m) and (m["last_check"] or {}).get("done") == "no")
        assert st["next_clip"] is None, st
        seen: list = []
        i = 3
        while not main.engine.verified and i < 30:
            cam.send_bytes(jpeg((i, i, i)))
            i += 1
            time.sleep(0.05)
        st = recv_json(ui, lambda m: is_state(m) and m["status"] == "verified")
        t_verified = time.monotonic()
        assert st["next_clip"] == "clips/02.mp4" and st["step"] == 0
        adv = recv_json(ui, lambda m: m["type"] == "advance")
        assert adv["reason"] == "camera" and 0.4 <= time.monotonic() - t_verified <= 1.0
        st = recv_json(ui, is_state)
        assert st["step"] == 1 and st["next_clip"] is None
        ui.send_json({"type": "goto", "step": 2})
        recv_json(ui, lambda m: is_state(m) and m["step"] == 2)
        cam.send_bytes(jpeg((200, 1, 1)))
        st = recv_json(ui, lambda m: is_state(m) and m["last_check"] is not None)
        assert st["last_check"]["done"] == "yes" and st["next_clip"] is None  # last step: nothing to preload
        del seen


def test_latency_env_values_are_bounded() -> None:
    with env(HANDOVER_MAX_INFLIGHT="9", HANDOVER_FAST_CONF="0.2", HANDOVER_FAST_PATH="maybe", HANDOVER_AHEAD_SKIP="x"):
        assert (main.max_inflight(), main.fast_conf(), main.fast_path(), main.ahead_skip()) == (2, 0.92, True, False)
    with env(HANDOVER_MAX_INFLIGHT="4", HANDOVER_FAST_CONF="1", HANDOVER_FAST_PATH="0", HANDOVER_AHEAD_SKIP="1"):
        assert (main.max_inflight(), main.fast_conf(), main.fast_path(), main.ahead_skip()) == (4, 1.0, False, True)


def test_run_start_carries_source_mode_and_learner() -> None:
    """run_start and databricks.start_run get the active camera's source, the check mode and the learner id
    (from an optional select_lesson token), so dashboards can leave out mock and replay runs."""
    import sys
    from server import accounts

    make_lesson()
    calls: list[tuple] = []

    class NewDb(FakeDatabricks):
        def start_run(self, lesson_id: str, learner: str | None = None, source: str | None = None,
                      **extra: Any) -> str:
            calls.append(("start_run", lesson_id, learner, source, extra))
            return "db-run"

    class OldDb(FakeDatabricks):  # today's signature: no source, no extras; the hub must not break it
        def start_run(self, lesson_id: str, learner: str | None = None) -> str:
            calls.append(("old_start_run", lesson_id, learner))
            return "db-run"

    events: list[dict] = []
    old = sys.modules.get("server.databricks")
    try:
        for fake in (NewDb(), OldDb()):
            sys.modules["server.databricks"] = fake  # type: ignore[assignment]
            with patched(main, EVENT_SINKS=[main.databricks_sink, events.append]), \
                    patched(accounts, resolve_token=lambda t: {"id": "u-42", "name": "Ana"} if t == "good" else None), \
                    hub() as c, c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
                cam.send_json(hello(source="file", platform="replay"))
                recv_json(ui, lambda m: is_state(m) and m["camera"] and m["camera"]["source"] == "file")
                ui.send_json({"type": "select_lesson", "id": LESSON, "token": "good"})
                recv_json(ui, lambda m: is_state(m) and m["lesson_id"] == LESSON)
                ui.send_json({"type": "select_lesson", "id": LESSON, "token": "bad"})  # anonymous, still allowed
                ui.send_json({"type": "select_lesson", "id": LESSON})
                wait_for(lambda: len([e for e in events if e["kind"] == "run_start"]) >= 3)
    finally:
        if old is None:
            sys.modules.pop("server.databricks", None)
        else:
            sys.modules["server.databricks"] = old
    starts = [e for e in events if e["kind"] == "run_start"]
    assert (starts[0]["learner"], starts[0]["source"], starts[0]["check_mode"]) == ("u-42", "file", "mock"), starts[0]
    assert starts[1]["learner"] is None and starts[2]["learner"] is None
    assert calls[0] == ("start_run", LESSON, "u-42", "file", {"check_mode": "mock"}), calls[0]
    assert ("old_start_run", LESSON, "u-42") in calls, calls


def test_recut_drops_voiceover_and_auth_guard() -> None:
    from server import teach

    d = make_lesson()
    data = json.loads((d / "lesson.json").read_text("utf-8"))
    data["voiceover"] = {"voice": "narrator", "clips": "voice/"}
    (d / "lesson.json").write_text(json.dumps(data), "utf-8")
    seen: list[dict] = []

    def fake_recut(folder: Path) -> dict:
        seen.append(json.loads((folder / "lesson.json").read_text("utf-8")))
        return seen[-1]

    with patched(teach, recut=fake_recut), hub() as c:
        assert c.post(f"/api/lessons/{LESSON}/recut").status_code == 200
        assert "voiceover" not in seen[-1] and seen[-1]["steps"]
        body = {**data, "voiceover": {"voice": "x"}}
        assert c.post(f"/api/lessons/{LESSON}/recut", json=body).status_code == 200
        assert "voiceover" not in seen[-1]
        with env(HANDOVER_AUTH="required"):
            assert c.post(f"/api/lessons/{LESSON}/recut").status_code == 401
            assert c.delete(f"/api/lessons/{LESSON}").status_code == 401
            assert c.post("/api/lesson", files={"file": ("v.mp4", b"0", "video/mp4")}).status_code == 401
        assert c.post(f"/api/lessons/{LESSON}/recut", headers={"authorization": "Bearer nope"}).status_code == 401


# ---------------------------------------------------------------- real-time understanding (HANDOVER_UNDERSTAND)

def write_rubric(d: Path) -> None:
    """A rubric.json for the test lesson: steps 1 and 2 have entries (keyframes = the reference frames)."""
    from server import understand

    lesson = json.loads((d / "lesson.json").read_text("utf-8"))
    steps = [{"n": n, "title": f"Step {n}", "question": f"Is step {n} done?",
              "keyframes": [f"frames/{n:02d}.jpg"] * 3,
              "stages": [{"label": "half", "cue": "half"}, {"label": "all", "cue": "all"}],
              "done_cue": "done", "mistakes": [{"label": "torn", "sign": "rip", "hint": "Careful, it tore.",
                                                "severity": "high"}], "region": {}} for n in (1, 2)]
    (d / "rubric.json").write_text(json.dumps({"version": understand.RUBRIC_VERSION,
                                               "source": understand.lesson_signature(lesson), "steps": steps}))


class FakeUnderstand:
    def __init__(self, latency: float = 0.0):
        self.latency = latency
        self.answer: dict = {"done": "no", "confidence": 0.9, "stage": 0, "progress": 0.4, "mistake": None,
                             "mistake_confidence": 0.0}
        self.starts: list[float] = []

    async def __call__(self, entry: dict, keys: list[bytes], live: bytes, prev: bytes | None, **kw: Any) -> Any:
        from server import understand

        self.starts.append(time.monotonic())
        if self.latency:
            await anyio.sleep(self.latency)
        a = self.answer
        return understand.Understanding(a["done"], a["confidence"], 1, stage=a["stage"], progress=a["progress"],
                                        mistake=a["mistake"], mistake_confidence=a["mistake_confidence"])


def test_understanding_both_must_say_yes_and_fills_progress() -> None:
    from server import understand

    d = make_lesson()
    write_rubric(d)
    und = FakeUnderstand(latency=0.3)
    slow = SlowCheck(0.3, confidence=0.97)
    with env(HANDOVER_UNDERSTAND="1", HANDOVER_GATE="0", HANDOVER_DEBOUNCE_N="2", HANDOVER_UNDERSTAND_OVERRIDE_N="0"), \
            patched(check, check_frame=slow), patched(understand, understand_frame=und), \
            patched(main, VERIFIED_HOLD=0.1), hub() as c, c.websocket_connect("/ws/ui") as ui, \
            c.websocket_connect("/ws/camera") as cam:
        select(ui)
        assert main.engine.rubric is not None
        for i in range(8):
            cam.send_bytes(jpeg((i * 10, 5, 5)))
            time.sleep(0.12)
        st = recv_json(ui, lambda m: is_state(m) and m.get("progress") is not None)
        assert st["progress"] == 0.4 and st["stage"] == {"index": 0, "count": 2, "label": "half"}, st
        assert main.engine.step == 0 and not main.engine.verified  # check says yes, understanding says no
        assert abs(und.starts[0] - slow.starts[0]) < 0.1  # both calls in flight at once on the same frame
        und.answer = {**und.answer, "done": "yes", "confidence": 0.95, "stage": 1, "progress": 1.0}
        i = 20
        while main.engine.step == 0 and i < 60:
            cam.send_bytes(jpeg((i * 3, 5, 5)))
            i += 1
            time.sleep(0.1)
        assert main.engine.step == 1
        st = recv_json(ui, lambda m: is_state(m) and m["step"] == 1)
        assert st["progress"] is None and st["stage"] is None  # reset on step change


def test_understand_override_after_n_check_yes() -> None:
    """HANDOVER_UNDERSTAND=1: the check says yes at 0.9 on every frame, understanding keeps saying no (the live
    run's rotated square). After HANDOVER_UNDERSTAND_OVERRIDE_N (3) such answers the check's verdict is accepted:
    clients get reason camera (contract), the advance event says understand_override."""
    from server import understand

    d = make_lesson()
    write_rubric(d)
    und = FakeUnderstand()
    fake = FakeCheck(lambda ref: check.CheckResult("yes", 0.9, 1))
    events: list[dict] = []
    with env(HANDOVER_UNDERSTAND="1", HANDOVER_GATE="0", HANDOVER_DEBOUNCE_N="2",
             HANDOVER_UNDERSTAND_OVERRIDE_N=None, HANDOVER_UNDERSTAND_OVERRIDE_CONF=None), \
            patched(check, check_frame=fake), patched(understand, understand_frame=und), \
            patched(main, VERIFIED_HOLD=0.05, EVENT_SINKS=[events.append], OVERRIDE_MIN_SECONDS=0.0), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        select(ui)
        i = 0
        while main.engine.step == 0 and i < 40:
            cam.send_bytes(jpeg((i * 5, 11, 11)))
            i += 1
            time.sleep(0.1)
        adv = recv_json(ui, lambda m: m["type"] == "advance")
        assert (adv["from"], adv["to"], adv["reason"]) == (0, 1, "camera"), adv
    ev = next(e for e in events if e["kind"] == "advance")
    assert (ev["from"], ev["to"], ev["reason"]) == (0, 1, "understand_override"), ev
    checks = [e for e in events if e["kind"] == "check" and e["step"] == 0]
    assert len(checks) >= 3, checks  # never before 3 check yes answers
    assert main.metrics["understand_overrides"] >= 1


def test_understand_override_needs_a_time_span() -> None:
    """Three confident check yes answers in quick succession are not enough while understanding says no: the
    streak must also span OVERRIDE_MIN_SECONDS, so understanding's no is never just one extra check."""
    yes, u_no = check.CheckResult("yes", 0.9, 1), check.CheckResult("no", 0.9, 1)
    make_lesson()
    clock = [100.0]
    with env(HANDOVER_UNDERSTAND_OVERRIDE_N=None, HANDOVER_UNDERSTAND_OVERRIDE_CONF=None), \
            patched(main.time, monotonic=lambda: clock[0]):
        e = main.Engine()
        e.select(LESSON)
        assert [e._override_due(yes, u_no) for _ in range(5)] == [False] * 5  # same instant: never
        clock[0] += main.OVERRIDE_MIN_SECONDS
        assert e._override_due(yes, u_no) is True


def test_understand_override_counting() -> None:
    """_override_due: only confident check yes answers with understanding not yes count; anything else from the
    check resets; both yes leaves the count alone; 0 turns it off; the count resets on a step change."""
    yes, low, no = (check.CheckResult("yes", 0.9, 1), check.CheckResult("yes", 0.79, 1),
                    check.CheckResult("no", 0.9, 1))
    u_no, u_yes, u_unsure = (check.CheckResult("no", 0.9, 1), check.CheckResult("yes", 0.9, 1),
                             check.CheckResult("unsure", 0.0, 1))
    make_lesson()
    with env(HANDOVER_UNDERSTAND_OVERRIDE_N=None, HANDOVER_UNDERSTAND_OVERRIDE_CONF=None), \
            patched(main, OVERRIDE_MIN_SECONDS=0.0):
        e = main.Engine()
        e.select(LESSON)
        got = [e._override_due(r, u) for r, u in
               [(yes, u_no), (yes, u_unsure), (no, u_no), (yes, u_no), (low, u_no), (yes, u_no), (yes, u_yes),
                (yes, u_no)]]
        assert got == [False] * 8 and e.override_streak == 2, (got, e.override_streak)
        assert e._override_due(yes, u_no) is True
        e.go(1, "button")
        assert e.override_streak == 0
        with env(HANDOVER_UNDERSTAND_OVERRIDE_N="0"):
            assert not any(e._override_due(yes, u_no) for _ in range(6))
        with env(HANDOVER_UNDERSTAND_OVERRIDE_CONF="0.95"):
            e.override_streak = 0
            assert not any(e._override_due(yes, u_no) for _ in range(6)) and e.override_streak == 0


def test_understanding_off_or_stale_is_todays_behavior() -> None:
    from server import understand

    d = make_lesson()
    write_rubric(d)
    und = FakeUnderstand()
    fake = FakeCheck(lambda ref: check.CheckResult("yes", 0.9, 1))
    with env(HANDOVER_UNDERSTAND=None, HANDOVER_DEBOUNCE_N="2"), patched(check, check_frame=fake), \
            patched(understand, understand_frame=und), patched(main, VERIFIED_HOLD=0.05), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        assert select(ui)["progress"] is None
        for i in range(4):
            cam.send_bytes(jpeg((i * 30, 9, 9)))
            time.sleep(0.1)
        wait_for(lambda: main.engine.step >= 1)
        assert und.starts == [] and main.engine.rubric is None
    data = json.loads((d / "lesson.json").read_text("utf-8"))
    data["steps"][0]["end"] = "00:00.5"  # a recut makes the rubric stale
    (d / "lesson.json").write_text(json.dumps(data), "utf-8")
    with env(HANDOVER_UNDERSTAND="1"), hub():
        main.engine.select(LESSON)
        assert main.engine.rubric is None and main.engine.understand_entry(0) is None


def test_live_mistakes_are_advisory_and_switchable() -> None:
    from server import understand

    d = make_lesson()
    write_rubric(d)
    und = FakeUnderstand()
    und.answer = {**und.answer, "mistake": "torn", "mistake_confidence": 0.9}
    fake = FakeCheck(lambda ref: check.CheckResult("no", 0.9, 1))
    for live in (False, True):
        with env(HANDOVER_UNDERSTAND="1", HANDOVER_LIVE_MISTAKES="1" if live else None, HANDOVER_GATE="0"), \
                patched(check, check_frame=fake), patched(understand, understand_frame=und), hub() as c, \
                c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
            select(ui)
            for i in range(5):
                cam.send_bytes(jpeg((i * 30, 7, 7)))
                time.sleep(0.1)
            if not live:
                time.sleep(0.2)
                assert main.engine.mistake is None
                continue
            m = recv_json(ui, lambda m: m["type"] == "mistake")
            assert (m["kind"], m["label"], m["message"], m["source"]) == ("live", "torn", "Careful, it tore.", "mock")
            st = recv_json(ui, lambda s: is_state(s) and s["mistake"] is not None)
            assert st["mistake"]["kind"] == "live" and st["step"] == 0
            ui.send_json({"type": "dismiss_mistake"})
            recv_json(ui, lambda s: is_state(s) and s["mistake"] is None)
            assert main.engine.step == 0  # never moves the step


def test_state_run_id_for_the_done_screen() -> None:
    """state.run_id: null with no lesson, the engine's id per select, or the id databricks.start_run returned."""
    import sys

    make_lesson()
    with patched(main, EVENT_SINKS=[], databricks_module=lambda: None), hub() as c, \
            c.websocket_connect("/ws/ui") as ui:  # no Databricks: the engine's own id
        assert recv_json(ui, is_state)["run_id"] is None
        first = select(ui)["run_id"]
        assert isinstance(first, str) and first == main.engine.run.run_id
        ui.send_json({"type": "select_lesson", "id": LESSON})
        second = recv_json(ui, lambda m: is_state(m) and m["run_id"] != first)["run_id"]
        assert isinstance(second, str) and second != first

    class Db(FakeDatabricks):
        def start_run(self, lesson_id: str, learner: str | None = None) -> str:
            return "db-run-7"

    old = sys.modules.get("server.databricks")
    sys.modules["server.databricks"] = Db()  # type: ignore[assignment]
    try:
        with patched(main, EVENT_SINKS=[main.databricks_sink]), hub() as c, c.websocket_connect("/ws/ui") as ui:
            assert select(ui)["run_id"] == "db-run-7"
    finally:
        if old is None:
            sys.modules.pop("server.databricks", None)
        else:
            sys.modules["server.databricks"] = old


def test_ui_frames_0_gets_no_live_frames() -> None:
    make_lesson()
    with hub() as c, c.websocket_connect("/ws/ui") as viewer, c.websocket_connect("/ws/ui?frames=0") as phone, \
            c.websocket_connect("/ws/camera") as cam:
        select(viewer)
        assert recv_json(phone, lambda m: is_state(m) and m["lesson_id"] == LESSON)["step"] == 0
        for i in range(4):
            cam.send_bytes(jpeg((i * 40, 20, 20)))
            time.sleep(0.3)
        assert any(m.get("bytes") for m in drain(viewer, 0.4)), "the normal viewer got no frames"
        got = drain(phone, 0.4)
        assert not any(m.get("bytes") for m in got), "frames=0 viewer got a frame"
        viewer.send_json({"type": "next", "from": 0})
        assert recv_json(phone, lambda m: m["type"] == "advance")["to"] == 1  # text still arrives


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


def test_mistake_ahead_shows_banner_never_skips_by_default() -> None:
    """HANDOVER_AHEAD_SKIP unset: a confirmed ahead only shows "You're ahead." and the step stays put. The compare
    gets no step question (a neutral one is used inside check.compare_refs)."""
    make_lesson()
    ref_next = (main.LESSONS / LESSON / "frames" / "02.jpg").read_bytes()
    fake = FakeCheck(lambda ref: check.CheckResult("yes" if ref == ref_next else "no", 0.95, 1))
    questions: list[Any] = []

    async def compare(live: bytes, pairs: list[tuple[int, bytes]], question: str | None = None) -> check.MatchResult:
        questions.append(question)
        return check.MatchResult(1, 0.9, 3)

    with gemini(), env(HANDOVER_AHEAD_SKIP=None), patched(check, check_frame=fake, compare_refs=compare), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        main.engine.watch = mistake.MistakeWatch(settle_s=0.2, cooldown_s=60)
        select(ui)
        for i in range(8):
            cam.send_bytes(jpeg((i * 20, 50, 50)))
            time.sleep(0.08)
        m = recv_json(ui, lambda m: m["type"] == "mistake")
        assert (m["kind"], m["message"], m["source"]) == ("ahead", "You're ahead.", "gemini"), m
        st = recv_json(ui, lambda s: is_state(s) and s["mistake"] is not None)
        assert st["step"] == 0 and st["mistake"]["kind"] == "ahead"
        got = [json.loads(x["text"]) for x in drain(ui, 0.8) if x.get("text")]
        assert not [x for x in got if x.get("type") == "advance"], got
        assert main.engine.step == 0
        assert questions and all(q is None for q in questions), questions


def test_ahead_confirm_verdicts() -> None:
    """_confirm_ahead: show needs a k+1 yes at 0.8; skip needs HANDOVER_AHEAD_SKIP=1, the k+1 yes at 0.9 and a
    yes for step k itself on the same frame."""
    make_lesson()
    ref_k, ref_next = ((main.LESSONS / LESSON / "frames" / f"{i:02d}.jpg").read_bytes() for i in (1, 2))
    cases = [  # (skip on, k+1 answer, k answer, verdict)
        (False, ("yes", 0.95), ("yes", 0.95), "show"),
        (False, ("yes", 0.79), ("yes", 0.95), None),
        (False, ("no", 0.95), ("yes", 0.95), None),
        (True, ("yes", 0.95), ("yes", 0.85), "skip"),
        (True, ("yes", 0.95), ("no", 0.95), "show"),
        (True, ("yes", 0.95), ("unsure", 0.5), "show"),
        (True, ("yes", 0.89), ("yes", 0.95), "show"),
        (True, ("no", 0.95), ("yes", 0.95), None),
    ]
    for skip, nxt, own, want in cases:
        answers = {ref_next: nxt, ref_k: own}
        fake = FakeCheck(lambda ref: check.CheckResult(answers[ref][0], answers[ref][1], 1))
        with gemini(), env(HANDOVER_AHEAD_SKIP="1" if skip else "0"), patched(check, check_frame=fake):
            engine = main.Engine()
            main_engine, main.engine = main.engine, engine
            try:
                engine.select(LESSON)
                job = main.CheckJob(0, "Is step 1 done?", ref_k, FRAME, engine.version)
                got = anyio.run(engine._confirm_ahead, job)
            finally:
                main.engine = main_engine
        assert got == want, (skip, nxt, own, got)
        assert len(fake.calls) == (2 if skip else 1), (skip, len(fake.calls))


def _ahead_run(compare_conf: float, n_frames: int = 60) -> tuple[list[dict], list[dict], list[int]]:
    """Step 0 with the live frame always matching step 1: the check of step 0 says no, the k+1 confirm says yes
    0.95, the compare names step 1 at compare_conf. Returns (ui messages, events, steps seen)."""
    make_lesson()
    ref_next = (main.LESSONS / LESSON / "frames" / "02.jpg").read_bytes()
    # A missed advance: step 0's own check is an unsure no (0.6). A confident no would mean step 0 was skipped,
    # which ahead_confirm must never paper over (test_ahead_confirm_blocked_when_own_check_says_no).
    fake = FakeCheck(lambda ref: check.CheckResult("yes", 0.95, 1) if ref == ref_next else check.CheckResult("no", 0.6, 1))
    events: list[dict] = []
    compares: list[int] = []

    async def compare(live: bytes, pairs: list[tuple[int, bytes]], question: str | None = None) -> check.MatchResult:
        compares.append(main.engine.step)
        return check.MatchResult(main.engine.step + 1, compare_conf, 3)

    msgs: list[dict] = []
    with gemini(), env(HANDOVER_AHEAD_SKIP=None, HANDOVER_AHEAD_CONFIRM_N=None, HANDOVER_AHEAD_CONFIRM_CONF=None,
                       HANDOVER_DEBOUNCE_N="5"), \
            patched(check, check_frame=fake, compare_refs=compare), \
            patched(main, EVENT_SINKS=[events.append], VERIFIED_HOLD=5.0), hub() as c, \
            c.websocket_connect("/ws/ui") as ui, c.websocket_connect("/ws/camera") as cam:
        main.engine.watch = mistake.MistakeWatch(settle_s=0.1, cooldown_s=0.3)
        select(ui)
        for i in range(n_frames):
            cam.send_bytes(jpeg((i * 4 % 250, 60, 60)))
            time.sleep(0.05)
            if main.engine.step != 0:
                break
        time.sleep(0.2)
        msgs = [json.loads(x["text"]) for x in drain(ui, 0.3) if x.get("text")]
    return msgs, events, compares


def test_ahead_confirm_moves_one_step_after_three_verdicts() -> None:
    """The live run's stranded learner: "ahead, looks like step k+1" at 0.85, confirmed by the k+1 check, three
    times in a row. The step moves to k+1 (never k+2), clients see reason camera, the event says ahead_confirm."""
    msgs, events, compares = _ahead_run(0.85)
    advances = [m for m in msgs if m.get("type") == "advance"]
    assert [(a["from"], a["to"], a["reason"]) for a in advances] == [(0, 1, "camera")], advances
    banners = [m for m in msgs if m.get("type") == "mistake"]
    assert len(banners) == 2 and all(b["kind"] == "ahead" for b in banners), banners  # third verdict advances
    ev = [e for e in events if e["kind"] == "advance"]
    assert [(e["from"], e["to"], e["reason"]) for e in ev] == [(0, 1, "ahead_confirm")], ev
    assert compares.count(0) == 3, compares
    run_done = [e for e in events if e["kind"] == "run_done"]
    assert run_done == []


def test_false_ahead_at_07_never_advances() -> None:
    """The live run's false "ahead, looks like step 6" at 0.7 on step 5: the banner may show (0.7 passes
    HANDOVER_MISTAKE_MIN_CONF and the k+1 check confirmed it), but under HANDOVER_AHEAD_CONFIRM_CONF (0.8) it never
    counts, so the step never moves however often it repeats."""
    msgs, events, compares = _ahead_run(0.7, n_frames=80)
    assert len(compares) >= 4, compares
    banners = [m for m in msgs if m.get("type") == "mistake"]
    assert len(banners) >= 4 and all(b["confidence"] == 0.7 for b in banners), banners
    assert not [m for m in msgs if m.get("type") == "advance"], msgs
    assert not [e for e in events if e["kind"] == "advance"]
    assert main.engine.step == 0


def test_ahead_confirm_streak_resets_and_bounds() -> None:
    """_ahead_confirm_due: only confirmed ahead verdicts at 0.8 or more count; an unconfirmed one, a low one or
    any other answer resets; 0 turns it off; it never moves more than one step."""
    make_lesson()
    with env(HANDOVER_AHEAD_CONFIRM_N=None, HANDOVER_AHEAD_CONFIRM_CONF=None):
        e = main.Engine()
        e.select(LESSON)
        job = main.CheckJob(0, "q", b"", FRAME, e.version)
        seq = [(True, 0.85), (True, 0.85), (False, 0.9), (True, 0.85), (True, 0.85), (True, 0.79), (True, 0.85),
               (True, 0.85)]
        assert [e._ahead_confirm_due(job, c, conf) for c, conf in seq] == [False] * 8 and e.step == 0
        assert e._ahead_confirm_due(job, True, 0.85) is True
        assert (e.step, e.ahead_streak) == (1, 0)
        with env(HANDOVER_AHEAD_CONFIRM_N="0"):
            job = main.CheckJob(1, "q", b"", FRAME, e.version)
            assert not any(e._ahead_confirm_due(job, True, 0.99) for _ in range(6)) and e.step == 1
        stale = main.CheckJob(0, "q", b"", FRAME, e.version)  # a verdict for a step already left
        e.ahead_streak = 5
        assert e._ahead_confirm_due(stale, True, 0.9) is False and e.step == 1


def test_ahead_confirm_blocked_when_own_check_says_no() -> None:
    """A confident "no" from step k's own check means k was skipped, not missed: ahead verdicts never move on."""
    make_lesson()
    with env(HANDOVER_AHEAD_CONFIRM_N=None, HANDOVER_AHEAD_CONFIRM_CONF=None):
        e = main.Engine()
        e.select(LESSON)
        job = main.CheckJob(0, "q", b"", FRAME, e.version)
        e.last_check = {"done": "no", "confidence": 0.9}
        assert not any(e._ahead_confirm_due(job, True, 0.95) for _ in range(6)) and e.step == 0
        e.last_check = {"done": "no", "confidence": 0.6}  # an unsure no does not block recovery
        assert [e._ahead_confirm_due(job, True, 0.95) for _ in range(3)] == [False, False, True] and e.step == 1


def test_mock_ahead_banner_by_default_skip_when_enabled() -> None:
    make_lesson()
    for skip in (False, True):
        with env(HANDOVER_MOCK_MISTAKE="ahead:0", HANDOVER_MOCK_PASS_SECONDS="100",
                 HANDOVER_AHEAD_SKIP="1" if skip else None), \
                patched(mistake, MOCK_AFTER_S=0.3), hub() as c, c.websocket_connect("/ws/ui") as ui, \
                c.websocket_connect("/ws/camera") as cam:
            select(ui)
            for i in range(4):
                cam.send_bytes(jpeg((i * 30, 40, 40)))
                time.sleep(0.4)
            shown = recv_json(ui, lambda m: m["type"] == "mistake", timeout=5)
            assert (shown["step"], shown["kind"], shown["source"]) == (0, "ahead", "mock")
            assert shown["message"] == "You're ahead."
            if skip:
                adv = recv_json(ui, lambda m: m["type"] == "advance")
                assert (adv["from"], adv["to"], adv["reason"]) == (0, 2, "camera")
                assert recv_json(ui, is_state)["mistake"] is None
            else:
                st = recv_json(ui, lambda s: is_state(s) and s["mistake"] is not None)
                assert st["step"] == 0 and st["mistake"]["kind"] == "ahead"
                got = [json.loads(x["text"]) for x in drain(ui, 0.6) if x.get("text")]
                assert not [x for x in got if x.get("type") == "advance"], got


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


def test_databricks_knows_every_engine_event_kind() -> None:
    """Every event kind the engine emits reaches server.databricks under a kind it knows (no unknown_kind):
    run_done and run_stop were missing. breaker goes out as check_offline; run_start and run_end come from
    start_run and end_run. Reads KINDS only; nothing is sent."""
    import re

    from server import databricks

    emitted = set(re.findall(r'self\.emit\("([a-z_]+)"', Path(main.__file__).read_text("utf-8")))
    assert {"advance", "check", "mistake", "step_enter", "breaker", "run_done", "run_stop"} <= emitted, emitted
    sent = {"check_offline" if k == "breaker" else k for k in emitted} | {"run_start", "run_end"}
    assert sent <= databricks.KINDS, sent - databricks.KINDS


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


def test_end_lesson_unloads_and_stops_run() -> None:
    make_lesson("to-end")
    with hub() as c, c.websocket_connect("/ws/ui") as ui:
        select(ui, "to-end")
        ui.send_text(json.dumps({"type": "end_lesson"}))
        st = recv_json(ui, lambda m: is_state(m) and m["lesson_id"] is None)
        assert st["total"] == 0 and st["step"] == 0
        assert main.engine.run is None and main.engine.lesson is None
        ui.send_text(json.dumps({"type": "end_lesson"}))  # nothing loaded: a quiet no-op
        select(ui, "to-end")
        run = main.engine.run_id()
        ui.send_text(json.dumps({"type": "end_lesson", "lesson_id": "other-lesson"}))  # stale: ignored
        ui.send_text(json.dumps({"type": "end_lesson", "lesson_id": "to-end", "run_id": "old-run"}))  # stale run
        time.sleep(0.3)
        assert main.engine.lesson_id == "to-end" and main.engine.run_id() == run
        ui.send_text(json.dumps({"type": "end_lesson", "lesson_id": "to-end", "run_id": run}))
        recv_json(ui, lambda m: is_state(m) and m["lesson_id"] is None)
        assert (main.LESSONS / "to-end").exists()  # ending never touches the lesson files


def test_hub_info_pairing_fields() -> None:
    with hub() as c, patched(main, lan_ip=lambda: "192.168.1.20"):
        info = c.get("/api/hub-info").json()
        port = info["http_port"]
        assert info["hub_url"] == f"http://192.168.1.20:{port}"
        assert info["pair_link"] == f"handover://connect?hub=http%3A%2F%2F192.168.1.20%3A{port}"
        assert info["capture_url"] is None  # tests run without certs: no https camera page to point at
    with hub() as c, patched(main, lan_ip=lambda: "192.168.1.20", has_certs=lambda: True):
        info = c.get("/api/hub-info").json()
        assert info["capture_url"] == f"https://192.168.1.20:{info['https_port']}/capture"
    with hub() as c, patched(main, lan_ip=lambda: None):
        info = c.get("/api/hub-info").json()
        assert info["hub_url"] is None and info["pair_link"] is None


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
    # The gate held checks back (one trigger plus its one pipelined partner), so a result-driven hook never ran.
    assert checks_in_window <= main.max_inflight(), checks_in_window


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
    def starts_jpeg(p: Path) -> bool:
        try:
            with p.open("rb") as f:
                return f.read(2) == b"\xff\xd8"
        except OSError:  # another tool (an Xcode build under the repo) removed its temp file meanwhile
            return False

    leaked = [p for p in created if main.LESSONS in p.parents or starts_jpeg(p)]
    assert leaked == [], leaked


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

"""Black-box contract suite: checks a running hub against CONTRACT.md over real HTTP and WebSocket.

Starts its own hub (mock check, mock teach, a temp copy of lessons/demo-v1) on ports 8060 and 8061, runs every
test, stops the hub and removes the temp files. NEW items that are not built yet are SKIP, found by probing.

Run: .venv/bin/python -m server.test_contract
Prints ok / FAIL / SKIP per test; exit code 1 when any test fails.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from PIL import Image
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

REPO = Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / "bin" / "python"
PORT, HTTPS_PORT = 8060, 8061
MISTAKE_PORT, MISTAKE_HTTPS_PORT = 8062, 8063
LESSON = "demo-v1"
TOTAL = 5  # steps in demo-v1; step index 2 is manual, the others are camera
MANUAL_STEP = 2
PASS_SECONDS = 2
STATUSES = {"watching", "checking", "verified", "manual", "done"}
NOT_BUILT = "NEW, not implemented"


class Skip(Exception):
    pass


# ---------------------------------------------------------------- hub process

class Hub:
    def __init__(self, tmp: Path, lessons: Path, port: int, https_port: int, extra: Optional[dict] = None):
        self.base = f"http://127.0.0.1:{port}"
        self.ws = f"ws://127.0.0.1:{port}"
        self.log = tmp / f"hub-{port}.log"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("HANDOVER_") and k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
        env.update({
            "HANDOVER_PORT": str(port), "HANDOVER_HTTPS_PORT": str(https_port), "HANDOVER_CERTS": "/nonexistent",
            "HANDOVER_CHECK": "mock", "HANDOVER_NO_NETWORK": "1", "HANDOVER_MOCK_PASS_SECONDS": str(PASS_SECONDS), "HANDOVER_TEACH_MOCK": "1",
            "HANDOVER_LESSONS": str(lessons),
            "HANDOVER_GATE": "0",  # identical synthetic frames would never pass the motion gate
            "PYTHONUNBUFFERED": "1",
        })
        env.update(extra or {})
        self.env = env
        self.port = port
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> None:
        if _http(f"http://127.0.0.1:{self.port}", "GET", "/", timeout=1)[0] != 0:
            raise RuntimeError(f"port {self.port} is already in use; stop that process first")
        self._logf = self.log.open("wb")
        self.proc = subprocess.Popen([str(PY), "-m", "server.main"], cwd=REPO, env=self.env,
                                     stdout=self._logf, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                break
            if _http(self.base, "GET", "/api/lessons", timeout=1)[0] == 200:
                return
            time.sleep(0.2)
        raise RuntimeError(f"hub on {self.port} did not start:\n{self.tail()}")

    def tail(self, n: int = 30) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-n:])
        except OSError:
            return ""

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        if getattr(self, "_logf", None):
            self._logf.close()


# ---------------------------------------------------------------- HTTP helpers

def _http(base: str, method: str, path: str, body: Optional[bytes] = None, headers: Optional[dict] = None,
          timeout: float = 30) -> tuple[int, dict, bytes]:
    """(status, lowercased headers, body). Status 0 means no connection."""
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, {}, b""


HUB: Hub  # the main hub, set in main()


async def http(method: str, path: str, body: Optional[bytes] = None, headers: Optional[dict] = None,
               hub: Optional[Hub] = None) -> tuple[int, dict, bytes]:
    return await asyncio.to_thread(_http, (hub or HUB).base, method, path, body, headers)


async def get_json(path: str) -> Any:
    status, _, body = await http("GET", path)
    assert status == 200, f"GET {path} gave {status}"
    return json.loads(body)


def detail(body: bytes) -> Any:
    try:
        return json.loads(body).get("detail")
    except (ValueError, AttributeError):
        return None


def expect_error(resp: tuple[int, dict, bytes], status: int, message: Optional[str]) -> None:
    got, _, body = resp
    assert got == status, f"status {got}, want {status} (body {body[:200]!r})"
    if message is not None:
        assert detail(body) == message, f"detail {detail(body)!r}, want {message!r}"


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, data) in files.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                  f"Content-Type: application/octet-stream\r\n\r\n".encode())
        out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


async def upload(title: str, lesson_id: Optional[str], data: bytes = b"not a video") -> tuple[int, dict, bytes]:
    fields = {"title": title}
    if lesson_id is not None:
        fields["id"] = lesson_id
    body, ctype = multipart(fields, {"file": ("clip.mp4", data)})
    return await http("POST", "/api/lesson", body, {"Content-Type": ctype})


# ---------------------------------------------------------------- WebSocket helpers

CLOSED = object()


class Conn:
    """One WebSocket with a background reader. Text messages are decoded JSON, binary stays bytes."""

    def __init__(self, ws):
        self.ws = ws
        self.q: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.task = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, path: str, hub: Optional[Hub] = None) -> "Conn":
        ws = await connect((hub or HUB).ws + path, max_size=None, open_timeout=5)
        return cls(ws)

    async def _read(self) -> None:
        try:
            async for m in self.ws:
                if isinstance(m, str):
                    try:
                        m = json.loads(m)
                    except ValueError:
                        m = {"_raw": m}
                await self.q.put(m)
        except ConnectionClosed:
            pass
        self.closed = True
        await self.q.put(CLOSED)

    @property
    def close_code(self):
        return self.ws.close_code

    @property
    def close_reason(self):
        return self.ws.close_reason

    async def send(self, msg: Any) -> None:
        if isinstance(msg, (bytes, str)):
            await self.ws.send(msg)
        else:
            await self.ws.send(json.dumps(msg))

    async def get(self, timeout: float) -> Any:
        """Next message, or None on timeout. CLOSED when the socket closed."""
        try:
            m = await asyncio.wait_for(self.q.get(), timeout)
        except asyncio.TimeoutError:
            return None
        if m is CLOSED:
            await self.q.put(CLOSED)  # keep reporting closed
        return m

    async def wait(self, pred: Callable[[Any], bool], timeout: float = 3.0, what: str = "message",
                   seen: Optional[list] = None) -> Any:
        """First message matching pred (binary included only if pred accepts bytes). Others go to `seen`."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            m = await self.get(max(left, 0)) if left > 0 else None
            if m is None:
                raise AssertionError(f"timed out after {timeout:.1f} s waiting for {what}")
            if m is CLOSED:
                raise AssertionError(f"socket closed while waiting for {what} (code {self.close_code})")
            try:
                ok = pred(m)
            except (TypeError, KeyError, AttributeError):
                ok = False
            if ok:
                return m
            if seen is not None:
                seen.append(m)

    async def drain(self, seconds: float) -> list:
        """Everything that arrives within `seconds`."""
        out, end = [], time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            m = await self.get(left)
            if m is None:
                break
            if m is CLOSED:
                break
            out.append(m)
        return out

    async def close(self) -> None:
        with _suppress():
            await self.ws.close()
        with _suppress():
            await asyncio.wait_for(self.task, 2)


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return exc[0] is not None and not issubclass(exc[0], (KeyboardInterrupt, SystemExit))


def is_type(t: str) -> Callable[[Any], bool]:
    return lambda m: isinstance(m, dict) and m.get("type") == t


def texts(msgs: list) -> list:
    return [m for m in msgs if isinstance(m, dict)]


def binaries(msgs: list) -> list:
    return [m for m in msgs if isinstance(m, bytes)]


def state_where(**kw) -> Callable[[Any], bool]:
    def pred(m):
        return is_type("state")(m) and all(m.get(k) == v for k, v in kw.items())
    return pred


async def ui_ready(lesson: str = LESSON, step: int = 0) -> Conn:
    """A /ws/ui connection with `lesson` freshly selected, optionally moved to `step`, and the queue quiet."""
    ui = await Conn.open("/ws/ui")
    await ui.wait(is_type("state"), what="initial state")
    await ui.send({"type": "select_lesson", "id": lesson})
    await ui.wait(state_where(lesson_id=lesson, step=0), what=f"state after selecting {lesson}")
    if step:
        await ui.send({"type": "goto", "step": step})
        await ui.wait(state_where(step=step), what=f"state at step {step}")
    await ui.drain(0.2)
    return ui


async def current_state() -> dict:
    ui = await Conn.open("/ws/ui")
    try:
        return await ui.wait(is_type("state"), what="initial state")
    finally:
        await ui.close()


def jpeg(w: int = 1280, h: int = 720, color=(30, 120, 200), pad: int = 0) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG", quality=80)
    return b.getvalue() + b"\0" * pad


FRAME = jpeg()


async def send_frames(cam: Conn, seconds: float, every: float = 0.4, frame: bytes = FRAME) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        await cam.send(frame)
        await asyncio.sleep(every)


def hello(device_id: str, name: str, platform: str = "ios", source: str = "glasses") -> dict:
    return {"type": "hello", "device_id": device_id, "name": name, "platform": platform, "source": source}


# ---------------------------------------------------------------- feature probes

FEATURES: dict[str, bool] = {}


def need(feature: str) -> None:
    if not FEATURES.get(feature):
        raise Skip(NOT_BUILT)


async def probe() -> None:
    st = await current_state()
    FEATURES["camera"] = "camera" in st  # W8 / W5: hello, identity, active camera, camera messages
    FEATURES["mistake"] = "mistake" in st  # M9
    FEATURES["check_offline"] = "check_offline" in st  # M6
    status, _, _ = await http("DELETE", "/api/lessons/no-such-lesson-probe")
    FEATURES["delete"] = status not in (404, 405)
    if status == 404:  # 404 from a real route has the JSON detail; FastAPI's no-route 404 is "Not Found"
        _, _, body = await http("DELETE", "/api/lessons/no-such-lesson-probe")
        FEATURES["delete"] = detail(body) != "Not Found"
    status, headers, _ = await http("GET", "/")
    FEATURES["dist"] = status == 200 and headers.get("content-type", "").startswith("text/html")


# ---------------------------------------------------------------- tests: no lesson yet (must run first)

TESTS: list[tuple[str, Callable]] = []


def test(fn):
    TESTS.append((fn.__name__.removeprefix("test_"), fn))
    return fn


def check_state_types(st: dict) -> None:
    def is_int(v):
        return isinstance(v, int) and not isinstance(v, bool)
    assert st.get("type") == "state"
    assert st["lesson_id"] is None or isinstance(st["lesson_id"], str), f"lesson_id {st['lesson_id']!r}"
    assert is_int(st["rev"]), f"rev {st['rev']!r}"
    assert is_int(st["step"]) and is_int(st["total"]), f"step/total {st['step']!r}/{st['total']!r}"
    assert st["status"] in STATUSES, f"status {st['status']!r}"
    assert isinstance(st["camera_connected"], bool), f"camera_connected {st['camera_connected']!r}"
    lc = st["last_check"]
    if lc is not None:
        assert lc.get("done") in ("yes", "no", "unsure"), f"last_check.done {lc.get('done')!r}"
        assert isinstance(lc.get("confidence"), (int, float)) and 0 <= lc["confidence"] <= 1, lc
        assert is_int(lc.get("latency_ms")), lc
        if "reason" in lc:
            assert lc["reason"] is None or isinstance(lc["reason"], str), lc
    if "camera" in st and st["camera"] is not None:
        assert set(st["camera"]) >= {"name", "platform", "source"}, st["camera"]
    if "check_offline" in st:
        assert isinstance(st["check_offline"], bool), st["check_offline"]
    if "mistake" in st and st["mistake"] is not None:
        assert isinstance(st["mistake"], dict) and "type" not in st["mistake"], st["mistake"]


@test
async def test_ui_state_no_lesson():
    st = await current_state()
    check_state_types(st)
    assert st["lesson_id"] is None and st["step"] == 0 and st["total"] == 0, st
    assert st["status"] == "watching", st
    assert st["rev"] == 0, f"rev {st['rev']} with no lesson, want 0"


@test
async def test_ui_error_no_lesson_selected():
    ui = await Conn.open("/ws/ui")
    try:
        await ui.wait(is_type("state"))
        for msg in ({"type": "next", "reason": "button"}, {"type": "back"}, {"type": "goto", "step": 1}):
            await ui.send(msg)
            m = await ui.wait(is_type("error"), what=f"error for {msg['type']}")
            assert m.get("message") == "no lesson selected", m
    finally:
        await ui.close()


@test
async def test_camera_error_no_lesson_selected():
    need("camera")
    cam = await Conn.open("/ws/camera")
    try:
        await cam.send(hello("err-cam", "Error cam"))
        await cam.drain(0.3)
        await cam.send({"type": "next", "reason": "button", "from": 0})
        m = await cam.wait(is_type("error"), what="error on the camera socket")
        assert m.get("message") == "no lesson selected", m
    finally:
        await cam.close()


@test
async def test_ui_select_errors():
    ui = await Conn.open("/ws/ui")
    try:
        await ui.wait(is_type("state"))
        for lid, want in (("bad id", "bad lesson id"), ("-x", "bad lesson id"), ("no-such", "lesson not found")):
            await ui.send({"type": "select_lesson", "id": lid})
            m = await ui.wait(is_type("error"), what=f"error for {lid!r}")
            assert m.get("message") == want, f"{lid!r}: {m}"
        await ui.send({"type": "select_lesson", "id": "broken"})
        m = await ui.wait(is_type("error"), what="error for broken lesson.json")
        assert str(m.get("message")).startswith("lesson.json unreadable: "), m
    finally:
        await ui.close()


# ---------------------------------------------------------------- tests: REST (section 4)

@test
async def test_rest_list_sorted_and_filtered():
    data = await get_json("/api/lessons")
    ids = [d["id"] for d in data]
    assert ids == sorted(ids), f"not sorted: {ids}"
    for want in ("alpha", LESSON, "zeta"):
        assert want in ids, f"{want} missing from {ids}"
    for bad in ("broken", "bad.id", "empty-folder"):
        assert bad not in ids, f"{bad} should be skipped: {ids}"
    by = {d["id"]: d for d in data}
    assert by[LESSON] == {"id": LESSON, "title": "Demo lesson", "steps": TOTAL}, by[LESSON]
    assert by["zeta"]["title"] == "zeta" and by["zeta"]["steps"] == 1, by["zeta"]
    assert by["alpha"]["steps"] == 0, by["alpha"]


@test
async def test_rest_get_lesson():
    status, headers, body = await http("GET", f"/api/lessons/{LESSON}")
    assert status == 200, status
    assert "no-cache" in headers.get("cache-control", ""), headers.get("cache-control")
    assert json.loads(body)["steps"][0]["title"] == "Lay the blue sheet flat"
    expect_error(await http("GET", "/api/lessons/-bad"), 400, "bad lesson id")
    expect_error(await http("GET", "/api/lessons/bad.id"), 400, "bad lesson id")
    expect_error(await http("GET", "/api/lessons/" + "a" * 65), 400, "bad lesson id")
    expect_error(await http("GET", "/api/lessons/no-such"), 404, "lesson not found")
    status, _, body = await http("GET", "/api/lessons/broken")
    assert status == 500 and str(detail(body)).startswith("lesson.json unreadable: "), (status, body[:200])


@test
async def test_rest_capture_page():
    status, headers, body = await http("GET", "/capture")
    assert status == 200, status
    assert headers.get("content-type", "").startswith("text/html"), headers.get("content-type")
    assert "no-cache" in headers.get("cache-control", ""), headers.get("cache-control")


@test
async def test_rest_lesson_files_vtt():
    status, headers, body = await http("GET", f"/lessons/{LESSON}/captions/01.vtt")
    assert status == 200, status
    assert headers.get("content-type", "").startswith("text/vtt"), headers.get("content-type")
    assert "no-cache" in headers.get("cache-control", ""), headers.get("cache-control")
    assert body.startswith(b"WEBVTT"), body[:20]


@test
async def test_rest_lesson_files_mp4_range():
    size = (TMP_LESSONS / LESSON / "clips" / "01.mp4").stat().st_size
    status, headers, body = await http("GET", f"/lessons/{LESSON}/clips/01.mp4", headers={"Range": "bytes=0-99"})
    assert status == 206, status
    assert headers.get("content-type", "").startswith("video/mp4"), headers.get("content-type")
    assert headers.get("content-range") == f"bytes 0-99/{size}", headers.get("content-range")
    assert len(body) == 100, len(body)
    assert "no-cache" in headers.get("cache-control", ""), headers.get("cache-control")
    status, headers, body = await http("GET", f"/lessons/{LESSON}/clips/01.mp4")
    assert status == 200 and len(body) == size, (status, len(body))
    assert headers.get("accept-ranges") == "bytes", headers.get("accept-ranges")


@test
async def test_rest_upload_id_rules():
    expect_error(await upload("Dup", LESSON), 409, "lesson id already exists")
    expect_error(await upload("Dup", "DEMO-V1"), 409, "lesson id already exists")
    expect_error(await upload("Bad", "!!!"), 400, "bad lesson id")
    status, _, body = await upload("Clean me", "Hello World_2")
    assert status == 200, (status, body[:200])
    res = json.loads(body)
    assert res["id"] == "hello-world-2", res
    assert isinstance(res["job"], str) and res["job"], res
    # The junk video fails; the job reports error and the half-built folder is gone.
    job = None
    for _ in range(100):
        job = await get_json(f"/api/jobs/{res['job']}")
        if job["status"] in ("done", "error"):
            break
        await asyncio.sleep(0.1)
    assert job["status"] == "error", job
    assert isinstance(job["message"], str) and job["message"] and job["id"] == "hello-world-2", job
    assert not (TMP_LESSONS / "hello-world-2").exists(), "failed job left its lesson folder"
    expect_error(await http("GET", "/api/lessons/hello-world-2"), 404, "lesson not found")


@test
async def test_rest_upload_generated_id():
    status, _, body = await upload("   ", None)
    assert status == 200, (status, body[:200])
    res = json.loads(body)
    assert re.fullmatch(r"untitled-lesson(-\d+)?", res["id"]), res
    status, _, body = await upload("Alpha", None)
    assert status == 200, (status, body[:200])
    assert json.loads(body)["id"] == "alpha-2", body  # alpha exists, so the next free slug


@test
async def test_rest_job_not_found():
    expect_error(await http("GET", "/api/jobs/nope"), 404, "job not found")


@test
async def test_rest_recut_errors():
    before = await get_json("/api/lessons/recut-me")
    bad = json.loads(json.dumps(before))
    bad["steps"][0]["start"] = "nonsense"
    status, _, body = await http("POST", "/api/lessons/recut-me/recut", json.dumps(bad).encode(),
                                 {"Content-Type": "application/json"})
    assert status == 400, (status, body[:300])
    assert isinstance(detail(body), str) and detail(body), body[:300]
    after = await get_json("/api/lessons/recut-me")
    assert after == before, "a failed recut changed lesson.json"
    expect_error(await http("POST", "/api/lessons/no-such/recut"), 404, "lesson not found")
    expect_error(await http("POST", "/api/lessons/-bad/recut"), 400, "bad lesson id")


@test
async def test_rest_root_json_fallback():
    if FEATURES["dist"]:
        raise Skip("web/dist is served, so the JSON fallback cannot show")
    status, headers, body = await http("GET", "/")
    assert status == 200, status
    assert json.loads(body) == {"app": "HandOver", "api": "/api/lessons", "capture": "/capture",
                                "ui": "http://localhost:5173"}, body


@test
async def test_rest_root_dist():
    if not FEATURES["dist"]:
        raise Skip(NOT_BUILT)
    status, headers, body = await http("GET", "/")
    html = body.decode("utf-8", "replace")
    assert status == 200 and "<html" in html.lower(), html[:200]
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert assets, "index.html references no /assets/ files"
    want = {".js": ("text/javascript", "application/javascript"), ".css": ("text/css",)}
    for a in assets:
        st, h, _ = await http("GET", a)
        assert st == 200, f"{a}: {st}"
        ext = Path(a).suffix
        if ext in want:
            assert h.get("content-type", "").startswith(want[ext]), f"{a}: {h.get('content-type')}"
    data = await get_json("/api/lessons")  # the API still wins over the app
    assert isinstance(data, list)


# ---------------------------------------------------------------- tests: engine (section 5)

async def expect_advance(ui: Conn, frm: int, to: int, reason: str, step: Optional[int] = None,
                         status: Optional[str] = None) -> dict:
    """The next text messages are advance then the matching state."""
    m = await ui.wait(lambda x: isinstance(x, dict), what=f"advance {frm}->{to}")
    assert m.get("type") == "advance", f"want advance before state, got {m}"
    assert (m.get("from"), m.get("to"), m.get("reason")) == (frm, to, reason), m
    st = await ui.wait(lambda x: isinstance(x, dict), what="state after advance")
    assert st.get("type") == "state", f"want state right after advance, got {st}"
    want_step = to if step is None else step
    assert st["step"] == want_step and st["total"] == TOTAL, st
    if status:
        assert st["status"] == status, st
    return st


async def expect_quiet(ui: Conn, seconds: float = 0.5, what: str = "command") -> None:
    got = texts(await ui.drain(seconds))
    assert not got, f"{what} should be ignored, got {got}"


@test
async def test_engine_select_and_state():
    ui = await ui_ready()
    try:
        await ui.send({"type": "select_lesson", "id": LESSON})
        st = await ui.wait(is_type("state"))
        check_state_types(st)
        assert (st["lesson_id"], st["step"], st["total"], st["status"]) == (LESSON, 0, TOTAL, "watching"), st
        assert st["rev"] > 0, st
        assert st["last_check"] is None, st
    finally:
        await ui.close()


@test
async def test_engine_next_back_reasons():
    ui = await ui_ready()
    try:
        await ui.send({"type": "next"})
        await expect_advance(ui, 0, 1, "button")
        await ui.send({"type": "next", "reason": "voice"})
        st = await expect_advance(ui, 1, 2, "voice")
        assert st["status"] == "manual", st
        await ui.send({"type": "next", "reason": "shout"})
        await expect_advance(ui, 2, 3, "button")
        await ui.send({"type": "back"})
        await expect_advance(ui, 3, 2, "button")
        await ui.send({"type": "back", "from": 2})
        await expect_advance(ui, 2, 1, "button")
        await ui.send({"type": "back"})
        await expect_advance(ui, 1, 0, "button")
        await ui.send({"type": "back"})
        await expect_quiet(ui, what="back at step 0")
    finally:
        await ui.close()


@test
async def test_engine_next_reason_timer_counts_as_button():
    ui = await ui_ready()
    try:
        await ui.send({"type": "next", "reason": "timer"})
        await expect_advance(ui, 0, 1, "button")
    finally:
        await ui.close()


@test
async def test_engine_goto_rules():
    ui = await ui_ready()
    try:
        await ui.send({"type": "goto", "step": 3})
        await expect_advance(ui, 0, 3, "button")
        for bad in (TOTAL, -1, "2", 1.5, None, 3):
            await ui.send({"type": "goto", "step": bad})
        await expect_quiet(ui, what="goto out of range, wrong type, or current step")
        await ui.send({"type": "goto", "step": 0})
        await expect_advance(ui, 3, 0, "button")
        await ui.send({"type": "goto", "step": 3})
        await expect_advance(ui, 0, 3, "button")
        await ui.send({"type": "select_lesson", "id": LESSON})
        m = await ui.wait(lambda x: isinstance(x, dict))
        assert m.get("type") == "state" and m["step"] == 0, f"select should reset to step 0 with state only: {m}"
    finally:
        await ui.close()


@test
async def test_engine_done_semantics():
    ui = await ui_ready(step=TOTAL - 1)
    try:
        await ui.send({"type": "next", "from": TOTAL - 1})
        st = await expect_advance(ui, TOTAL - 1, TOTAL, "button", step=TOTAL - 1, status="done")
        assert st["total"] == TOTAL
        await ui.send({"type": "next"})
        await expect_quiet(ui, what="next on the done screen")
        await ui.send({"type": "goto", "step": TOTAL})
        await expect_quiet(ui, what="goto total")
        # Done screen: from may be total or total - 1.
        await ui.send({"type": "back", "from": TOTAL})
        st = await expect_advance(ui, TOTAL, TOTAL - 1, "button")
        assert st["status"] != "done", st
        await ui.send({"type": "next", "from": TOTAL - 1})
        await expect_advance(ui, TOTAL - 1, TOTAL, "button", step=TOTAL - 1, status="done")
        await ui.send({"type": "back", "from": TOTAL - 1})
        await expect_advance(ui, TOTAL, TOTAL - 1, "button")
        await ui.send({"type": "goto", "step": 1})
        await expect_advance(ui, TOTAL - 1, 1, "button")
    finally:
        await ui.close()


@test
async def test_engine_stale_from_guard():
    ui = await ui_ready(step=1)
    try:
        await ui.send({"type": "next", "from": 0})
        await ui.send({"type": "back", "from": 3})
        await ui.send({"type": "next", "from": "1"})
        await expect_quiet(ui, what="next/back with a stale from")
        await ui.send({"type": "next", "from": 1})
        await expect_advance(ui, 1, 2, "button")
        await ui.send({"type": "goto", "step": TOTAL - 1})
        await expect_advance(ui, 2, TOTAL - 1, "button")
        await ui.send({"type": "next", "from": TOTAL - 1})
        await expect_advance(ui, TOTAL - 1, TOTAL, "button", step=TOTAL - 1, status="done")
        await ui.send({"type": "next", "from": TOTAL - 2})
        await ui.send({"type": "back", "from": TOTAL - 2})
        await expect_quiet(ui, what="stale from on the done screen")
    finally:
        await ui.close()


# ---------------------------------------------------------------- tests: /ws/ui (section 7)

@test
async def test_ui_invalid_json_and_unknown_types_ignored():
    ui = await ui_ready()
    try:
        for raw in ("not json{", "[1, 2]", '"text"', "42", '{"type": "bogus"}', '{"no": "type"}'):
            await ui.send(raw)
        await expect_quiet(ui, what="invalid JSON or unknown type")
        await ui.send({"type": "next"})
        await expect_advance(ui, 0, 1, "button")
    finally:
        await ui.close()


@test
async def test_ui_viewers_share_messages():
    a = await ui_ready()
    b = await Conn.open("/ws/ui")
    try:
        first = await b.wait(is_type("state"))
        assert first["lesson_id"] == LESSON and first["step"] == 0, first
        await a.send({"type": "next"})
        await expect_advance(a, 0, 1, "button")
        await expect_advance(b, 0, 1, "button")
    finally:
        await a.close()
        await b.close()


@test
async def test_ui_camera_connected_broadcast():
    ui = await ui_ready(step=MANUAL_STEP)
    try:
        cam = await Conn.open("/ws/camera")
        try:
            st = await ui.wait(state_where(camera_connected=True), what="camera_connected true")
            if FEATURES["camera"]:
                assert st["camera"] is not None, st
        finally:
            await cam.close()
        st = await ui.wait(state_where(camera_connected=False), what="camera_connected false")
        if FEATURES["camera"]:
            assert st["camera"] is None, st
    finally:
        await ui.close()


@test
async def test_ui_frames_from_plain_camera():
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await cam.send(FRAME)
        frame = await ui.wait(lambda m: isinstance(m, bytes), what="binary frame on /ws/ui")
        assert frame[:2] == b"\xff\xd8", frame[:4]
        size = Image.open(io.BytesIO(frame)).size
        assert max(size) <= 960, f"forwarded frame is {size}, long side must be at most 960"
        await cam.send(b"not a jpeg")
        assert not binaries(await ui.drain(0.6)), "non-JPEG binary was forwarded"
    finally:
        await cam.close()
        await ui.close()


@test
async def test_ui_frame_rate_limit():
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await ui.drain(0.3)
        start = time.monotonic()
        await send_frames(cam, 1.6, every=0.05)
        got = binaries(await ui.drain(0.4))
        elapsed = time.monotonic() - start
        assert got, "no frames forwarded"
        assert len(got) <= int(elapsed * 4) + 1, f"{len(got)} frames in {elapsed:.1f} s, limit 4 per second"
    finally:
        await cam.close()
        await ui.close()


@test
async def test_ui_frames_only_from_active_camera():
    need("camera")
    ui = await ui_ready(step=MANUAL_STEP)
    b = await Conn.open("/ws/camera")
    a = None
    try:
        await b.send(hello("act-b", "Cam B", "web", "browser"))
        await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("name") == "Cam B",
                      what="state.camera = Cam B")
        a = await Conn.open("/ws/camera")
        await a.send(hello("act-a", "Cam A"))
        await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("name") == "Cam A",
                      what="state.camera = Cam A (newest hello is active)")
        await ui.drain(0.3)
        await b.send(FRAME)
        assert not binaries(await ui.drain(1.0)), "frame from the inactive camera was forwarded"
        await a.send(FRAME)
        await ui.wait(lambda m: isinstance(m, bytes), what="frame from the active camera")
    finally:
        if a:
            await a.close()
        await b.close()
        await ui.close()


# ---------------------------------------------------------------- tests: /ws/camera (section 6)

@test
async def test_camera_default_identity():
    need("camera")
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await cam.send(FRAME)
        st = await ui.wait(lambda m: is_type("state")(m) and m.get("camera"), what="state with camera")
        c = st["camera"]
        assert re.fullmatch(r"Camera \d+", str(c.get("name"))), c
        assert c.get("platform") == "other" and c.get("source") == "phone", c
        # A malformed hello is ignored: identity stays the default and next stays locked.
        await cam.send({"type": "hello", "device_id": 7, "name": 7, "platform": 7, "source": 7})
        await cam.send({"type": "next", "reason": "button", "from": MANUAL_STEP})
        got = texts(await ui.drain(0.6))
        assert not [m for m in got if m.get("type") == "advance"], f"next after malformed hello moved: {got}"
        for m in got:
            if m.get("type") == "state" and m.get("camera"):
                assert m["camera"]["name"] == c["name"], f"malformed hello changed the camera: {m['camera']}"
    finally:
        await cam.close()
        await ui.close()


@test
async def test_camera_hello_updates_state():
    need("camera")
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await cam.send(hello("hello-1", "Ray-Ban Meta via iPhone", "ios", "glasses"))
        st = await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("platform") == "ios",
                           what="state.camera after hello")
        assert {k: st["camera"][k] for k in ("name", "platform", "source")} == \
            {"name": "Ray-Ban Meta via iPhone", "platform": "ios", "source": "glasses"}, st["camera"]
        await cam.send(hello("hello-1", "Replay: clip.mp4", "replay", "file"))
        st = await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("source") == "file",
                           what="state.camera after a repeated hello")
        assert st["camera"]["name"] == "Replay: clip.mp4" and st["camera"]["platform"] == "replay", st["camera"]
    finally:
        await cam.close()
        await ui.close()


@test
async def test_camera_gets_status_and_state_after_hello():
    need("camera")
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await cam.send(hello("status-1", "Status cam"))
        seen: list = []
        m = await cam.wait(is_type("camera_status"), what="camera_status", seen=seen)
        assert m.get("active") is True, m
        st = await cam.wait(is_type("state"), what="state on the camera socket", seen=seen) \
            if not any(is_type("state")(x) for x in seen) else next(x for x in seen if is_type("state")(x))
        assert st["lesson_id"] == LESSON and st["step"] == MANUAL_STEP, st
        await ui.send({"type": "next"})
        await cam.wait(lambda x: is_type("advance")(x) and x.get("to") == MANUAL_STEP + 1,
                       what="advance on the camera socket")
        await cam.wait(state_where(step=MANUAL_STEP + 1), what="state on the camera socket after advance")
        await cam.drain(0.3)
        await ui.send({"type": "back"})
        got = await cam.drain(0.6)
        assert not binaries(got), "camera socket received binary frames"
    finally:
        await cam.close()
        await ui.close()


@test
async def test_camera_next_back_only_after_hello():
    need("camera")
    ui = await ui_ready()
    cam = await Conn.open("/ws/camera")
    try:
        await ui.drain(0.3)
        await cam.send({"type": "next", "reason": "button", "from": 0})
        await cam.send({"type": "back", "from": 0})
        got = texts(await ui.drain(0.6))
        assert not [m for m in got if m.get("type") == "advance"], f"next without hello moved: {got}"
        await cam.send(hello("nb-1", "Next cam"))
        await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("name") == "Next cam")
        await ui.drain(0.2)
        await cam.send({"type": "next", "reason": "button", "from": 0})
        await expect_advance(ui, 0, 1, "button")
        await cam.send({"type": "next", "reason": "button", "from": 0})
        await expect_quiet(ui, what="stale next from the camera")
        await cam.send({"type": "back", "from": 1})
        await expect_advance(ui, 1, 0, "button")
    finally:
        await cam.close()
        await ui.close()


@test
async def test_camera_replaced_4000():
    need("camera")
    first = await Conn.open("/ws/camera")
    second = None
    try:
        await first.send(hello("dup-1", "First"))
        await first.drain(0.3)
        second = await Conn.open("/ws/camera")
        await second.send(hello("dup-1", "Second"))
        await asyncio.wait_for(first.task, 3)
        assert first.close_code == 4000 and first.close_reason == "replaced", \
            f"close {first.close_code} {first.close_reason!r}, want 4000 'replaced'"
        await asyncio.sleep(0.3)
        assert not second.closed, "the newer connection was closed"
    except asyncio.TimeoutError:
        raise AssertionError("older connection with the same device_id was not closed")
    finally:
        await first.close()
        if second:
            await second.close()


@test
async def test_camera_oversized_frame_ignored():
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await ui.drain(0.3)
        await cam.send(jpeg(pad=2_200_000))
        forwarded = binaries(await ui.drain(1.0))
        await cam.send(FRAME)
        try:
            await ui.wait(lambda m: isinstance(m, bytes), timeout=2, what="normal frame after the big one")
        except AssertionError:
            raise AssertionError("a normal frame after a 2.2 MB frame was not forwarded (connection dropped?)")
        assert not cam.closed, f"camera socket closed after a big frame (code {cam.close_code})"
        if forwarded:
            raise Skip(f"{NOT_BUILT} (a 2.2 MB frame was forwarded)")
    finally:
        await cam.close()
        await ui.close()


@test
async def test_camera_active_switch_after_idle():
    need("camera")
    ui = await ui_ready(step=MANUAL_STEP)
    b = await Conn.open("/ws/camera")
    a = None
    try:
        await b.send(hello("idle-b", "Idle B", "web", "browser"))
        await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("name") == "Idle B")
        a = await Conn.open("/ws/camera")
        await a.send(hello("idle-a", "Idle A"))
        a_last = time.monotonic()
        await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("name") == "Idle A")
        sender = asyncio.create_task(send_frames(b, 8.5, every=0.4))
        try:
            await ui.wait(lambda m: is_type("state")(m) and (m.get("camera") or {}).get("name") == "Idle B",
                          timeout=8, what="switch to the camera that is still sending")
            waited = time.monotonic() - a_last
            assert waited >= 4.5, f"switched after {waited:.1f} s of idle, want 5 s"
            await b.wait(lambda m: is_type("camera_status")(m) and m.get("active") is True,
                         what="camera_status active true for the new camera")
            await a.wait(lambda m: is_type("camera_status")(m) and m.get("active") is False,
                         what="camera_status active false for the idle camera")
        finally:
            sender.cancel()
    finally:
        if a:
            await a.close()
        await b.close()
        await ui.close()


# ---------------------------------------------------------------- tests: check, mock mode (section 8)

@test
async def test_check_camera_advance_verified_then_advance():
    ui = await ui_ready()
    cam = await Conn.open("/ws/camera")
    sender = asyncio.create_task(send_frames(cam, 12, every=0.4))
    try:
        seen: list = []
        st = await ui.wait(state_where(status="verified"), timeout=9, what="status verified", seen=seen)
        t_verified = time.monotonic()
        assert st["step"] == 0, st
        assert st["last_check"] and st["last_check"]["done"] == "yes", st
        assert st["last_check"]["confidence"] >= 0.8, st
        assert not [m for m in texts(seen) if m.get("type") == "advance"], "advanced before verified"
        nos = [m for m in texts(seen) if m.get("type") == "state" and (m.get("last_check") or {}).get("done") == "no"]
        for m in nos:
            assert m["last_check"]["confidence"] == 0.85, m["last_check"]
        m = await ui.wait(is_type("advance"), timeout=3, what="camera advance")
        hold = time.monotonic() - t_verified
        assert (m["from"], m["to"], m["reason"]) == (0, 1, "camera"), m
        want = float(os.environ.get("HANDOVER_VERIFIED_HOLD", "0.8"))  # tuning knob, default 0.8 s
        assert want - 0.2 <= hold <= want + 0.8, f"verified held {hold:.2f} s, want about {want:.1f} s"
        st = await ui.wait(lambda x: isinstance(x, dict), what="state after camera advance")
        assert st.get("type") == "state" and st["step"] == 1 and st["last_check"] is None, st
        assert st["status"] in ("watching", "checking"), st
        await ui.send({"type": "next", "from": 0})
        got = texts(await ui.drain(0.4))
        assert not [x for x in got if x.get("type") == "advance" and x.get("reason") == "button"], \
            f"stale next after a camera advance was applied: {got}"
    finally:
        sender.cancel()
        await cam.close()
        await ui.close()


@test
async def test_check_manual_step_waits():
    ui = await ui_ready(step=MANUAL_STEP)
    cam = await Conn.open("/ws/camera")
    try:
        await send_frames(cam, PASS_SECONDS + 1.6, every=0.4)
        got = texts(await ui.drain(0.3))
        assert not [m for m in got if m.get("type") == "advance"], f"manual step advanced by camera: {got}"
        for m in got:
            if m.get("type") == "state":
                assert m["status"] == "manual" and m["step"] == MANUAL_STEP, m
        await ui.send({"type": "next", "from": MANUAL_STEP})
        await expect_advance(ui, MANUAL_STEP, MANUAL_STEP + 1, "button")
    finally:
        await cam.close()
        await ui.close()


@test
async def test_check_offline_fields():
    need("check_offline")
    st = await current_state()
    assert "check_offline_reason" in st, st
    assert st["check_offline"] is False, f"mock mode should never be offline: {st['check_offline']}"
    assert st["check_offline_reason"] is None, st["check_offline_reason"]


# ---------------------------------------------------------------- tests: recut and delete

@test
async def test_engine_rev_increases_after_recut():
    ui = await ui_ready("recut-me", step=1)
    try:
        await ui.send({"type": "select_lesson", "id": "recut-me"})
        st = await ui.wait(state_where(lesson_id="recut-me"))
        rev0 = st["rev"]
        await asyncio.sleep(0.05)
        status, _, body = await http("POST", "/api/lessons/recut-me/recut")
        assert status == 200, (status, body[:300])
        lesson = json.loads(body)
        assert len(lesson["steps"]) == TOTAL, lesson
        st = await ui.wait(lambda m: is_type("state")(m) and m["lesson_id"] == "recut-me" and m["rev"] != rev0,
                           timeout=5, what="state with a new rev after recut")
        assert st["rev"] > rev0, f"rev went from {rev0} to {st['rev']}"
        again = await get_json("/api/lessons/recut-me")
        assert again == lesson, "GET after recut differs from the recut response"
    finally:
        await ui.close()


@test
async def test_rest_delete_lesson():
    if not FEATURES["delete"]:
        raise Skip(NOT_BUILT)
    ui = await ui_ready("delete-me")
    try:
        status, _, body = await http("DELETE", "/api/lessons/delete-me")
        assert status == 200 and json.loads(body) == {"deleted": "delete-me"}, (status, body[:200])
        st = await ui.wait(state_where(lesson_id=None), what="state cleared after deleting the active lesson")
        assert st["total"] == 0 and st["step"] == 0 and st["status"] == "watching", st
        assert not (TMP_LESSONS / "delete-me").exists(), "folder still on disk"
        expect_error(await http("GET", "/api/lessons/delete-me"), 404, "lesson not found")
        status, _, _ = await http("DELETE", "/api/lessons/delete-me")
        assert status == 404, status
        await ui.send({"type": "next"})
        m = await ui.wait(is_type("error"))
        assert m["message"] == "no lesson selected", m
    finally:
        await ui.close()


# ---------------------------------------------------------------- tests: mistake (second hub, mock hook)

@test
async def test_mistake_mock_and_dismiss():
    need("mistake")
    hub = Hub(TMP, TMP_LESSONS, MISTAKE_PORT, MISTAKE_HTTPS_PORT,
              {"HANDOVER_MOCK_PASS_SECONDS": "60", "HANDOVER_MOCK_MISTAKE": "behind:1"})
    await asyncio.to_thread(hub.start)
    ui = cam = sender = None
    try:
        ui = await Conn.open("/ws/ui", hub)
        await ui.wait(is_type("state"))
        await ui.send({"type": "select_lesson", "id": LESSON})
        await ui.wait(state_where(lesson_id=LESSON, step=0))
        await ui.send({"type": "goto", "step": 1})
        st = await ui.wait(state_where(step=1))
        assert st.get("mistake") is None, st
        t0 = time.monotonic()
        cam = await Conn.open("/ws/camera", hub)
        if FEATURES["camera"]:
            await cam.send(hello("mistake-cam", "Mistake cam"))
        sender = asyncio.create_task(send_frames(cam, 12, every=0.4))
        seen: list = []
        m = await ui.wait(is_type("mistake"), timeout=9, what="mistake message", seen=seen)
        assert time.monotonic() - t0 >= 3.5, "mistake fired before 4 s on the step"
        common = json.loads((TMP_LESSONS / LESSON / "lesson.json").read_text())["steps"][1].get("common_mistake")
        want_msg = common or "This still looks like step 1."
        assert (m.get("step"), m.get("kind"), m.get("looks_like"), m.get("source")) == (1, "behind", 0, "mock"), m
        assert m.get("message") == want_msg, f"message {m.get('message')!r}, want {want_msg!r}"
        assert isinstance(m.get("confidence"), (int, float)) and 0 <= m["confidence"] <= 1, m
        expect_mistake = {k: v for k, v in m.items() if k != "type"}
        st = next((x for x in seen + await ui.drain(0.6)
                   if is_type("state")(x) and x.get("mistake")), None)
        assert st is not None, "no state carried the mistake"
        assert st["mistake"] == expect_mistake, f"state.mistake {st['mistake']} != {expect_mistake}"
        assert st["step"] == 1, "a behind mistake moved the step"
        if FEATURES["camera"]:
            await cam.wait(is_type("mistake"), timeout=2, what="mistake on the camera socket after hello")
        await ui.send({"type": "dismiss_mistake"})
        st = await ui.wait(lambda x: is_type("state")(x) and x.get("mistake") is None, what="state after dismiss")
        assert st["step"] == 1, st
        got = texts(await ui.drain(1.5))
        assert not [x for x in got if x.get("type") == "mistake"], f"mistake fired twice on one visit: {got}"
        # A step change clears it too: fire again on a fresh visit, then move.
        await ui.send({"type": "goto", "step": 0})
        await ui.wait(state_where(step=0))
        await ui.send({"type": "goto", "step": 1})
        await ui.wait(state_where(step=1))
        await ui.wait(is_type("mistake"), timeout=8, what="mistake on the second visit")
        await ui.wait(lambda x: is_type("state")(x) and x.get("mistake"), timeout=2)
        await ui.send({"type": "next", "from": 1})
        await ui.wait(is_type("advance"))
        st = await ui.wait(is_type("state"))
        assert st["step"] == 2 and st.get("mistake") is None, f"step change did not clear the mistake: {st}"
    finally:
        if sender:
            sender.cancel()
        if cam:
            await cam.close()
        if ui:
            await ui.close()
        await asyncio.to_thread(hub.stop)


# ---------------------------------------------------------------- fixtures and runner

TMP: Path
TMP_LESSONS: Path


def make_lessons(root: Path) -> None:
    src = REPO / "lessons" / LESSON
    shutil.copytree(src, root / LESSON)
    for copy in ("recut-me", "delete-me"):
        shutil.copytree(src, root / copy)
        p = root / copy / "lesson.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["id"] = copy
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def write(name: str, text: str) -> None:
        (root / name).mkdir()
        (root / name / "lesson.json").write_text(text, encoding="utf-8")

    write("alpha", json.dumps({"id": "alpha", "title": "Alpha", "steps": []}))
    write("zeta", json.dumps({"steps": [{"start": "00:00", "end": "00:01"}]}))
    write("broken", "{not json")
    write("bad.id", json.dumps({"title": "Bad", "steps": []}))
    (root / "empty-folder").mkdir()


async def run_all() -> list[tuple[str, str, str]]:
    await probe()
    results = []
    for name, fn in TESTS:
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(fn(), 30)
            res, why = "ok", ""
        except Skip as e:
            res, why = "SKIP", str(e)
        except AssertionError as e:
            res, why = "FAIL", str(e) or traceback.format_exc(limit=2).strip().splitlines()[-1]
        except asyncio.TimeoutError:
            res, why = "FAIL", "test timed out after 30 s"
        except Exception as e:
            res, why = "FAIL", f"{type(e).__name__}: {e}"
        dt = time.monotonic() - t0
        line = f"{res:<4}  {name}  ({dt:.1f} s)" + (f": {why}" if why else "")
        print(line, flush=True)
        results.append((name, res, why))
        await asyncio.sleep(0.15)  # let the hub settle camera disconnects before the next test
    return results


def main() -> int:
    global HUB, TMP, TMP_LESSONS
    started = time.monotonic()
    TMP = Path(tempfile.mkdtemp(prefix="handover-contract-"))
    TMP_LESSONS = TMP / "lessons"
    TMP_LESSONS.mkdir()
    HUB = Hub(TMP, TMP_LESSONS, PORT, HTTPS_PORT)
    results: list = []
    try:
        make_lessons(TMP_LESSONS)
        HUB.start()
        results = asyncio.run(run_all())
    except Exception as e:
        print(f"FAIL  setup: {type(e).__name__}: {e}", flush=True)
        results.append(("setup", "FAIL", str(e)))
    finally:
        HUB.stop()
        if any(r[1] == "FAIL" for r in results) and os.environ.get("HANDOVER_TEST_LOG"):
            print("\nhub log tail:\n" + HUB.tail(60), flush=True)
        shutil.rmtree(TMP, ignore_errors=True)
    counts = {k: sum(1 for r in results if r[1] == k) for k in ("ok", "FAIL", "SKIP")}
    print(f"\n{counts['ok']} ok, {counts['FAIL']} failed, {counts['SKIP']} skipped "
          f"in {time.monotonic() - started:.1f} s", flush=True)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())

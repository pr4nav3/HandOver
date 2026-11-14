"""HandOver server: lessons REST API, static lesson files, and the learn engine.

Run:  scripts/run_server.sh   (or: .venv/bin/python -m uvicorn server.main:app --host 0.0.0.0 --port 8000)
Shared interface: CONTRACT.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import check

mimetypes.add_type("text/vtt", ".vtt")
mimetypes.add_type("video/mp4", ".mp4")

log = logging.getLogger("handover")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%H:%M:%S"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False
    check.log.addHandler(_h)
    check.log.setLevel(logging.INFO)
    check.log.propagate = False

REPO = Path(__file__).resolve().parent.parent
LESSONS = Path(os.environ.get("HANDOVER_LESSONS") or REPO / "lessons").resolve()
UPLOADS = Path(__file__).resolve().parent / "uploads"
STATIC = Path(__file__).resolve().parent / "static"
LESSONS.mkdir(parents=True, exist_ok=True)

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
UI_FRAME_MAX_SIDE = 960
UI_FRAME_MIN_INTERVAL = 0.25  # at most 4 frames per second to the UI
VERIFIED_HOLD = 1.2  # seconds the "verified" status shows before advancing


# ---------------------------------------------------------------- lessons on disk

def lesson_dir(lesson_id: str) -> Path:
    if not ID_RE.match(lesson_id):
        raise HTTPException(400, "bad lesson id")
    return LESSONS / lesson_id


def read_lesson(lesson_id: str) -> dict:
    path = lesson_dir(lesson_id) / "lesson.json"
    if not path.is_file():
        raise HTTPException(404, "lesson not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"lesson.json unreadable: {e}")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")
    return s or "lesson"


def unique_id(base: str) -> str:
    taken = {j["id"] for j in jobs.values() if j["status"] not in ("done", "error")}
    cand, i = base, 2
    while (LESSONS / cand).exists() or cand in taken:
        cand, i = f"{base}-{i}", i + 1
    return cand


# ---------------------------------------------------------------- websocket clients

class UIClient:
    """One /ws/ui connection. A queue plus one sender task keeps sends ordered."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    def push(self, msg: Any, droppable: bool = False) -> None:
        # Frames are dropped when the client is behind; state messages are kept.
        if droppable and self.queue.qsize() > 2:
            return
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    async def sender(self) -> None:
        while True:
            msg = await self.queue.get()
            if isinstance(msg, bytes):
                await self.ws.send_bytes(msg)
            else:
                await self.ws.send_text(json.dumps(msg))


# ---------------------------------------------------------------- learn engine

class Engine:
    """Single global learn session."""

    def __init__(self) -> None:
        self.lesson_id: Optional[str] = None
        self.lesson: Optional[dict] = None
        self.step = 0
        self.done = False
        self.checking = False
        self.verified = False
        self.last_check: Optional[dict] = None
        self.version = 0  # bumps on every lesson or step change
        self.step_started = time.monotonic()
        self.debouncer = check.Debouncer()
        self.ui: set[UIClient] = set()
        self.cameras = 0
        self.frame: Optional[bytes] = None
        self.frame_seq = 0
        self.checked_seq = 0
        self.frame_event = asyncio.Event()
        self.ui_frame_event = asyncio.Event()
        self.ref_cache: dict[tuple, bytes] = {}
        self.missing_ref_logged: set = set()

    # ---- state

    @property
    def steps(self) -> list:
        return (self.lesson or {}).get("steps") or []

    def current(self) -> Optional[dict]:
        s = self.steps
        return s[self.step] if self.lesson and not self.done and 0 <= self.step < len(s) else None

    def status(self) -> str:
        if self.lesson is not None and (self.done or not self.steps):
            return "done"
        cur = self.current()
        if cur is not None and cur.get("check_type") == "manual":
            return "manual"
        if self.verified:
            return "verified"
        if self.checking:
            return "checking"
        return "watching"

    def state(self) -> dict:
        return {
            "type": "state",
            "lesson_id": self.lesson_id,
            "step": self.step,
            "total": len(self.steps),
            "status": self.status(),
            "last_check": self.last_check,
            "camera_connected": self.cameras > 0,
        }

    def broadcast(self, msg: Any, droppable: bool = False) -> None:
        for c in list(self.ui):
            c.push(msg, droppable)

    def broadcast_state(self) -> None:
        self.broadcast(self.state())

    # ---- step changes

    def _enter_step(self) -> None:
        self.version += 1
        self.debouncer.reset()
        self.checking = False
        self.verified = False
        self.last_check = None
        self.step_started = time.monotonic()
        self.checked_seq = self.frame_seq  # never judge a new step with a frame taken before it began

    def select(self, lesson_id: str) -> None:
        lesson = read_lesson(lesson_id)
        self.lesson_id, self.lesson = lesson_id, lesson
        self.step, self.done = 0, False
        self.ref_cache.clear()
        self._enter_step()
        log.info("selected lesson %s (%d steps)", lesson_id, len(self.steps))
        self.broadcast_state()

    def reload_if_active(self, lesson_id: str) -> None:
        """After a recut, pick up new timestamps and reference frames, keep the step."""
        if self.lesson_id != lesson_id:
            return
        with contextlib.suppress(HTTPException):
            self.lesson = read_lesson(lesson_id)
        self.ref_cache.clear()
        if self.step >= len(self.steps):
            self.step = max(0, len(self.steps) - 1)
        self._enter_step()
        self.broadcast_state()

    def go(self, to: int, reason: str) -> None:
        """Move to step index `to`. `to == total` means finished (status done)."""
        if self.lesson is None:
            return
        total = len(self.steps)
        to = max(0, min(to, total))
        frm = total if self.done else self.step
        if to == frm:
            return
        if to >= total:
            self.done = True
            self.step = max(0, total - 1)
        else:
            self.done = False
            self.step = to
        self._enter_step()
        log.info("step %d -> %d (%s)", frm, to, reason)
        self.broadcast({"type": "advance", "from": frm, "to": to, "reason": reason})
        self.broadcast_state()

    def position(self) -> int:
        return len(self.steps) if self.done else self.step

    # ---- frames

    def on_frame(self, data: bytes) -> None:
        self.frame = data
        self.frame_seq += 1
        self.frame_event.set()
        self.ui_frame_event.set()

    def ref_bytes(self, step: dict) -> Optional[bytes]:
        rel = step.get("ref_frame")
        if not rel or not self.lesson_id:
            return None
        key = (self.lesson_id, rel)
        if key not in self.ref_cache:
            path = (LESSONS / self.lesson_id / rel).resolve()
            if not path.is_file() or LESSONS not in path.parents:
                if key not in self.missing_ref_logged:
                    log.warning("reference frame missing: %s", path)
                    self.missing_ref_logged.add(key)
                return None
            self.ref_cache[key] = path.read_bytes()
        return self.ref_cache[key]

    # ---- background loops

    async def check_loop(self) -> None:
        """One check in flight at a time, always on the newest frame."""
        while True:
            await self.frame_event.wait()
            self.frame_event.clear()
            cur = self.current()
            if cur is None or cur.get("check_type", "camera") != "camera" or self.verified:
                continue
            if self.frame is None or self.frame_seq == self.checked_seq or self.cameras == 0:
                continue
            ref = self.ref_bytes(cur)
            if ref is None:
                continue
            frame, seq, version = self.frame, self.frame_seq, self.version
            self.checked_seq = seq
            question = cur.get("check_question") or "Is this step finished?"
            self.checking = True
            self.broadcast_state()
            try:
                res = await check.check_frame(ref, frame, question, step_started_at=self.step_started)
            except Exception:  # check_frame should never raise; keep the loop alive regardless
                log.exception("check crashed")
                res = check.CheckResult("unsure", 0.0, 0)
            if version != self.version:
                continue  # step changed while the check was running; the stale result is ignored
            self.checking = False
            self.last_check = res.as_dict()
            passed = self.debouncer.feed(res.done, res.confidence)
            if passed:
                self.verified = True
                self.broadcast_state()
                await asyncio.sleep(VERIFIED_HOLD)
                if version == self.version:
                    self.go(self.position() + 1, "camera")
            else:
                self.broadcast_state()
            if self.frame_seq != self.checked_seq:
                self.frame_event.set()  # frames arrived meanwhile; check the newest one next

    async def ui_frame_loop(self) -> None:
        """Forward the newest camera frame to UI clients, downscaled, at most 4 per second."""
        last = 0.0
        while True:
            await self.ui_frame_event.wait()
            self.ui_frame_event.clear()
            wait = UI_FRAME_MIN_INTERVAL - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            frame = self.frame
            if frame is None or not self.ui:
                continue
            last = time.monotonic()
            try:
                small = await asyncio.to_thread(check.downscale_jpeg, frame, UI_FRAME_MAX_SIDE, 75)
            except Exception as e:
                log.warning("bad camera frame skipped: %s", e)
                continue
            self.broadcast(small, droppable=True)


engine = Engine()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(engine.check_loop()), asyncio.create_task(engine.ui_frame_loop())]
    log.info("lessons: %s  check: %s", LESSONS, "mock" if check.is_mock() else "gemini")
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="HandOver", lifespan=lifespan)


# ---------------------------------------------------------------- REST

@app.get("/")
def root() -> dict:
    return {"app": "HandOver", "api": "/api/lessons", "capture": "/capture", "ui": "http://localhost:5173"}


@app.get("/capture")
def capture() -> FileResponse:
    return FileResponse(STATIC / "capture.html", media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/api/lessons")
def list_lessons() -> list:
    out = []
    for d in sorted(LESSONS.iterdir()) if LESSONS.is_dir() else []:
        f = d / "lesson.json"
        if not (d.is_dir() and f.is_file() and ID_RE.match(d.name)):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"id": d.name, "title": data.get("title") or d.name, "steps": len(data.get("steps") or [])})
    return out


@app.get("/api/lessons/{lesson_id}")
def get_lesson(lesson_id: str) -> JSONResponse:
    return JSONResponse(read_lesson(lesson_id), headers={"Cache-Control": "no-cache"})


jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def _set_job(job: str, **kw) -> None:
    with jobs_lock:
        jobs[job].update(kw)


def _run_job(job: str, src: Path, lesson_id: str, title: str) -> None:
    def progress(status: str, message: str = "") -> None:
        _set_job(job, status=status, message=message)

    try:
        from server import teach

        teach.process_upload(src, lesson_id, title, progress)
        _set_job(job, status="done", message="ready")
        log.info("job %s done: lesson %s", job, lesson_id)
    except Exception as e:
        log.exception("job %s failed", job)
        msg = f"{type(e).__name__}: {e}".strip()
        if len(msg) > 400:  # ffmpeg errors are long; keep the start and the useful tail
            msg = msg[:160].split("\n")[0] + " ... " + msg[-220:]
        _set_job(job, status="error", message=msg)


@app.post("/api/lesson")
async def upload_lesson(file: UploadFile = File(...), title: str = Form(...), id: Optional[str] = Form(None)) -> dict:
    title = title.strip() or "Untitled lesson"
    if id:
        if not ID_RE.match(id):
            raise HTTPException(400, "bad lesson id")
        if (LESSONS / id).exists():
            raise HTTPException(409, "lesson id already exists")
        lesson_id = id
    else:
        lesson_id = unique_id(slugify(title))
    job = uuid.uuid4().hex[:12]
    UPLOADS.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
        suffix = ".mp4"
    src = UPLOADS / f"{job}{suffix}"

    def save() -> None:
        with src.open("wb") as f:
            shutil.copyfileobj(file.file, f, 1024 * 1024)

    await asyncio.to_thread(save)
    with jobs_lock:
        jobs[job] = {"status": "queued", "message": "", "id": lesson_id}
    threading.Thread(target=_run_job, args=(job, src, lesson_id, title), daemon=True).start()
    log.info("job %s queued: %s -> lesson %s", job, src.name, lesson_id)
    return {"job": job, "id": lesson_id}


@app.get("/api/jobs/{job}")
def job_status(job: str) -> dict:
    with jobs_lock:
        if job not in jobs:
            raise HTTPException(404, "job not found")
        return dict(jobs[job])


@app.post("/api/lessons/{lesson_id}/recut")
async def recut(lesson_id: str, request: Request) -> Any:
    """Re-cut from lesson.json. An optional JSON body (a full lesson object) is saved first."""
    d = lesson_dir(lesson_id)
    read_lesson(lesson_id)  # 404 if missing
    body = await request.body()
    original = (d / "lesson.json").read_text(encoding="utf-8")
    if body.strip():
        try:
            new = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, "body must be JSON")
        if not isinstance(new, dict) or not isinstance(new.get("steps"), list):
            raise HTTPException(400, "body must be a lesson object with steps")
        new["id"] = lesson_id
        tmp = d / "lesson.json.tmp"
        tmp.write_text(json.dumps(new, indent=2), encoding="utf-8")
        tmp.replace(d / "lesson.json")
    try:
        from server import teach

        result = await asyncio.to_thread(teach.recut, d)
    except ValueError as e:  # bad timestamps in lesson.json: keep the last good file
        (d / "lesson.json").write_text(original, encoding="utf-8")
        raise HTTPException(400, str(e))
    except Exception as e:
        (d / "lesson.json").write_text(original, encoding="utf-8")
        log.exception("recut %s failed", lesson_id)
        raise HTTPException(500, f"recut failed: {type(e).__name__}: {e}")
    engine.reload_if_active(lesson_id)
    return result


class LessonFiles(StaticFiles):
    """Lesson folder with no-cache so a recut shows up at once. Range requests come from Starlette."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/lessons", LessonFiles(directory=LESSONS), name="lessons")


# ---------------------------------------------------------------- WebSockets

@app.websocket("/ws/camera")
async def ws_camera(ws: WebSocket) -> None:
    await ws.accept()
    engine.cameras += 1
    log.info("camera connected (%d)", engine.cameras)
    if engine.cameras == 1:
        engine.broadcast_state()
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data and data[:2] == b"\xff\xd8":
                engine.on_frame(data)
    except WebSocketDisconnect:
        pass
    finally:
        engine.cameras -= 1
        log.info("camera disconnected (%d)", engine.cameras)
        if engine.cameras == 0:
            engine.broadcast_state()


@app.websocket("/ws/ui")
async def ws_ui(ws: WebSocket) -> None:
    await ws.accept()
    client = UIClient(ws)
    engine.ui.add(client)
    client.push(engine.state())
    sender = asyncio.create_task(client.sender())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text"):
                handle_ui_message(client, msg["text"])
            if sender.done():
                break
    except WebSocketDisconnect:
        pass
    finally:
        engine.ui.discard(client)
        sender.cancel()
        with contextlib.suppress(BaseException):
            await sender


def handle_ui_message(client: UIClient, text: str) -> None:
    try:
        msg = json.loads(text)
        kind = msg.get("type")
    except (json.JSONDecodeError, AttributeError):
        return
    if kind == "select_lesson":
        try:
            engine.select(str(msg.get("id", "")))
        except HTTPException as e:
            client.push({"type": "error", "message": e.detail})
    elif engine.lesson is None:
        client.push({"type": "error", "message": "no lesson selected"})
    elif kind == "next":
        reason = msg.get("reason") if msg.get("reason") in ("button", "voice", "timer") else "button"
        engine.go(engine.position() + 1, reason)
    elif kind == "back":
        engine.go(engine.position() - 1, "button")
    elif kind == "goto":
        step = msg.get("step")
        if isinstance(step, int) and 0 <= step < len(engine.steps):
            engine.go(step, "button")


# ---------------------------------------------------------------- entry point

def serve() -> None:
    """Serve http and (when certs exist) https from ONE process, so both share the same learn session."""
    import uvicorn

    http_port = int(os.environ.get("HANDOVER_PORT", "8000"))
    https_port = int(os.environ.get("HANDOVER_HTTPS_PORT", "8443"))
    certs = Path(os.environ.get("HANDOVER_CERTS") or REPO / "certs")
    cert, key = certs / "cert.pem", certs / "key.pem"
    configs = [uvicorn.Config(app, host="0.0.0.0", port=http_port, lifespan="on")]
    if cert.is_file() and key.is_file():
        # The lifespan (engine start) runs on the http server only; the https server shares it.
        configs.append(uvicorn.Config(app, host="0.0.0.0", port=https_port, lifespan="off",
                                      ssl_certfile=str(cert), ssl_keyfile=str(key)))
    else:
        log.info("no certs/ found: http only. Run scripts/certs.sh for the iPhone camera page.")

    class Server(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self):  # signals are handled once below, for both servers
            yield

    servers = [Server(c) for c in configs]

    async def run_all() -> None:
        import signal

        def stop() -> None:
            for s in servers:
                s.force_exit = s.should_exit
                s.should_exit = True

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop)

        async def run_one(s) -> int:
            try:
                await s.serve()
                return 0
            except SystemExit as e:  # uvicorn exits this way on startup failure, after logging why
                return int(e.code or 1)

        tasks = [asyncio.create_task(run_one(s)) for s in servers]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        stop()
        codes = await asyncio.gather(*tasks)
        if any(codes):
            raise SystemExit(max(codes))

    asyncio.run(run_all())


if __name__ == "__main__":
    serve()

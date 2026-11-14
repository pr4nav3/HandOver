"""HandOver server: lessons REST API, static lesson files, and the learn engine.

Run:  scripts/run_server.sh   (or: .venv/bin/python -m server.main; on Windows .venv\\Scripts\\python -m server.main)
Shared interface: CONTRACT.md.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import contextvars
import importlib
import itertools
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import check, config, gate, mistake

for _ext, _type in ((".vtt", "text/vtt"), (".mp4", "video/mp4"), (".js", "text/javascript"),
                    (".mjs", "text/javascript"), (".css", "text/css"), (".svg", "image/svg+xml"),
                    (".woff2", "font/woff2"), (".map", "application/json"), (".wasm", "application/wasm")):
    mimetypes.add_type(_type, _ext)

# ---------------------------------------------------------------- logging

log_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("log_ctx", default="-")
"""Who a log line is about: req-<id> for HTTP, cam-<n> or ui-<n> for sockets, job-<id> for teach jobs."""


class ContextFilter(logging.Filter):
    """Stamps every record with the current log_ctx."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.ctx = log_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line (HANDOVER_LOG_JSON=1), for piping into tools."""

    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
               "level": record.levelname, "logger": record.name, "ctx": getattr(record, "ctx", "-"),
               "msg": record.getMessage()}
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out)


def setup_logging() -> None:
    """The one logging setup: the handover loggers (main, check, gate, mistake) and uvicorn share one handler.
    Human-readable by default, JSON lines when HANDOVER_LOG_JSON=1. Safe to call twice."""
    root = logging.getLogger("handover")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    if config.env_bool("HANDOVER_LOG_JSON", False):
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s [%(ctx)s] %(message)s", "%H:%M:%S"))
    for name in ("handover", "uvicorn"):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


setup_logging()
log = logging.getLogger("handover")
conn_ids = {"cam": itertools.count(1), "ui": itertools.count(1)}  # socket ids for log lines, never reused

metrics: collections.Counter = collections.Counter()
"""Process-wide counters (frames, checks, sends, drops). Read with Engine.snapshot(); routes can expose it later."""

REPO = Path(__file__).resolve().parent.parent
LESSONS = Path(os.environ.get("HANDOVER_LESSONS") or REPO / "lessons").resolve()
UPLOADS = Path(__file__).resolve().parent / "uploads"
STATIC = Path(__file__).resolve().parent / "static"
WEB_DIST = Path(str(config.get("HANDOVER_WEB_DIST") or REPO / "web" / "dist"))
LESSONS.mkdir(parents=True, exist_ok=True)

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
UI_FRAME_MAX_SIDE = 960
UI_FRAME_MIN_INTERVAL = 0.25  # at most 4 frames per second to the UI
VERIFIED_HOLD = config.env_float("HANDOVER_VERIFIED_HOLD", 0.8, 0, 10)  # seconds "verified" shows before advancing
MAX_UPLOAD_BYTES = 2 * 1024**3  # 2 GB
CHECKING_SHOW_AFTER = 1.5  # seconds a check must be in flight before the UI is told "checking"
MAX_FRAME_BYTES = 2 * 1024**2  # camera frames over 2 MB are ignored
ACTIVE_IDLE_SECONDS = 5.0  # an active camera silent this long loses to one that is sending frames
CLOSE_REPLACED = 4000  # close code when a newer connection says hello with the same device_id
HELLO_PLATFORMS = ("ios", "web", "replay")
HELLO_SOURCES = ("glasses", "phone", "browser", "file")
SEND_TIMEOUT = 5.0  # seconds one websocket send may take before the client counts as stalled
EVENT_QUEUE_MAX = 64  # advance, mistake and error messages held per client before new ones are dropped
CLOSE_STALLED = 1011  # close code when a client's sender gave up (a send took over SEND_TIMEOUT)
WARM_UP_TIMEOUT = 5.0  # seconds for the startup call that opens the pooled Gemini connection
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
UPLOAD_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")  # never playlists (HLS, concat) for ffmpeg
MOCK_TICK_SECONDS = 1.0  # the mock mistake hook is looked at no more often than this
MAX_ACTIVE_JOBS = 3  # queued plus running teach jobs before uploads get 429
MAX_RECUT_BODY = 1024**2  # 1 MB
MAX_RECUT_STEPS = 50
MAX_TEXT_MESSAGE = 8192  # longer websocket text is ignored
CLOSE_TRY_LATER = 1013  # close code when the camera or viewer cap is reached
STALE_TEMP_SECONDS = 3600  # startup cleanup only removes temp files untouched this long


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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"lesson.json unreadable: {redact(str(e))}")
    if not isinstance(data, dict):
        raise HTTPException(500, "lesson.json unreadable: not an object")
    return data


def redact(text: str) -> str:
    """The Gemini key and absolute paths out of anything a client or a log line sees."""
    text = check._redact(text)
    for path, label in ((LESSONS, "<lessons>"), (REPO, "<repo>")):
        text = text.replace(str(path), label)
    return text


def lesson_rev(lesson_id: Optional[str]) -> int:
    """lesson.json modification time in ms. Clients refetch the lesson and bust media caches when it changes."""
    if not lesson_id:
        return 0
    try:
        return int((LESSONS / lesson_id / "lesson.json").stat().st_mtime_ns // 1_000_000)
    except OSError:
        return 0


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")
    return s or "lesson"


def unique_id(base: str) -> str:
    """A free lesson id from base. Call with jobs_lock held, so the answer stays free until the job is listed."""
    taken = {j["id"] for j in jobs.values() if j["status"] not in ("done", "error")}
    cand, i = base, 2
    while (LESSONS / cand).exists() or cand in taken:
        cand, i = f"{base}-{i}", i + 1
    return cand


# ---------------------------------------------------------------- websocket clients

class UIClient:
    """One websocket client and its single sender task.

    Text messages (advance, mistake, error) go out in order from a bounded queue; when it is full the oldest
    text is dropped. `state` is a full snapshot and a live frame is only worth its newest copy, so each keeps
    just the latest. Send order: queued text, then the latest state (so an advance always arrives right before
    its state), then the latest frame. A send that takes over SEND_TIMEOUT means the client stalled: the sender
    ends and closes the socket with 1011 (CLOSE_STALLED), and the client reconnects.
    """

    def __init__(self, ws: WebSocket, label: str = "-"):
        self.ws = ws
        self.label = label
        self.queue: collections.deque = collections.deque()
        self.latest_state: Optional[dict] = None
        self.latest_frame: Optional[bytes] = None
        self.wake = asyncio.Event()

    def push(self, msg: Any) -> None:
        """Queue one message: bytes are a live frame, a dict is JSON text."""
        if isinstance(msg, bytes):
            if self.latest_frame is not None:
                metrics["frames_replaced_slow_client"] += 1
            self.latest_frame = msg
        elif isinstance(msg, dict) and msg.get("type") == "state":
            self.latest_state = msg
        else:
            if len(self.queue) >= EVENT_QUEUE_MAX:
                self.queue.popleft()
                metrics["events_dropped_full_queue"] += 1
            self.queue.append(msg)
        self.wake.set()

    def _pending(self) -> bool:
        return bool(self.queue) or self.latest_state is not None or self.latest_frame is not None

    def _next(self) -> Any:
        if self.queue:
            return self.queue.popleft()
        if self.latest_state is not None:
            msg, self.latest_state = self.latest_state, None
            return msg
        msg, self.latest_frame = self.latest_frame, None
        return msg

    async def _send(self, msg: Any) -> None:
        if isinstance(msg, bytes):
            await self.ws.send_bytes(msg)
        else:
            await self.ws.send_text(json.dumps(msg))

    async def sender(self) -> None:
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                while self._pending():
                    await asyncio.wait_for(self._send(self._next()), SEND_TIMEOUT)
                    metrics["ws_messages_sent"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:  # timeout (stalled client) or a dead socket
            metrics["ws_senders_failed"] += 1
            log.warning("%s sender stopped (%s); closing 1011", self.label, type(e).__name__)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.ws.close(code=CLOSE_STALLED), 1.0)


class Camera(UIClient):
    """One /ws/camera connection. Receives text only (camera_status, and after hello state, advance, mistake,
    error); live frames never go back to a camera."""

    def __init__(self, ws: WebSocket, number: int, now: float, label: str = "-"):
        super().__init__(ws, label)
        self.number = number
        self.name = f"Camera {number}"
        self.platform = "other"
        self.source = "phone"
        self.device_id: Optional[str] = None
        self.said_hello = False
        self.connected_at = now
        self.active_since = now  # when it last became active; idle counts from here until its first frame
        self.last_frame = 0.0  # 0 = no frame yet
        self.announce: Optional[asyncio.TimerHandle] = None  # pending first state broadcast, see add_camera

    def push(self, msg: Any) -> None:
        if not isinstance(msg, bytes):
            super().push(msg)

    def identity(self) -> dict:
        return {"name": self.name, "platform": self.platform, "source": self.source}


def parse_hello(msg: dict) -> Optional[dict]:
    """The identity fields of a hello, cleaned, or None when it is malformed. Absent fields keep their value."""
    out: dict = {}
    for key, allowed in (("platform", HELLO_PLATFORMS), ("source", HELLO_SOURCES)):
        if key in msg:
            if msg[key] not in allowed:
                return None
            out[key] = msg[key]
    for key, limit in (("device_id", 128), ("name", 64)):
        if key in msg:
            if not isinstance(msg[key], str):
                return None
            value = msg[key].strip()[:limit]
            if value:
                out[key] = value
    return out


# ---------------------------------------------------------------- learn engine

# ---------------------------------------------------------------- learn events

EVENT_SINKS: list[Callable[[dict], None]] = []
"""Subscribers for learn events (server/databricks.py appends one). Called inline on the event loop, so a sink
must return at once. Events hold no frames and nothing here writes to disk, so M15 holds."""


ENVELOPE = ("event_id", "ts", "run_id", "lesson_id", "rev", "kind")  # fields every learn event carries


def databricks_module() -> Any:
    """server.databricks (Pranav's uploader) when it can be imported, else None; the hub runs either way."""
    try:
        return importlib.import_module("server.databricks")
    except ImportError:
        return None


def databricks_sink(event: dict) -> None:
    """Translates learn events to server.databricks calls. Its functions return at once and never raise.
    Its own run_start and run_end come from start_run and end_run. Every event also carries the hub's
    run_id, rev and ts (as hub_run_id, rev, hub_ts); fields it does not know go to its extra column."""
    db = databricks_module()
    if db is None:
        return
    kind = event["kind"]
    fields = {k: v for k, v in event.items() if k not in ENVELOPE}
    fields.update(hub_run_id=event["run_id"], rev=event["rev"], hub_ts=event["ts"])
    if kind == "run_start":
        db.end_run()
        db.start_run(event["lesson_id"])
    elif kind in ("run_done", "run_stop"):
        db.emit(kind, **fields)  # run_done totals, or why the run stopped early
        db.end_run()
    elif kind == "advance":
        db.emit("advance", from_step=fields.pop("from"), to_step=fields.pop("to"), **fields)
    elif kind == "mistake":
        db.emit("mistake", kind=fields.pop("mistake_kind"), **fields)
    elif kind == "breaker":
        db.emit("check_offline", **fields)  # reason is null when checks come back on; open tells which
    else:  # step_enter, check (with reason)
        db.emit(kind, **fields)


def publish_lesson_files(lesson_id: str) -> None:
    """After a teach job or a recut succeeds: lesson files to the Databricks Volume (a no-op without
    credentials). Lesson files only; live camera frames are never part of this."""
    db = databricks_module()
    if db is not None:
        db.upload_lesson_files(LESSONS / lesson_id, lesson_id)


def parse_seconds(text: Any) -> Optional[float]:
    """lesson.json time ("MM:SS", "MM:SS.s", "HH:MM:SS" or plain seconds) in seconds; None when unreadable."""
    try:
        total = 0.0
        for part in str(text).split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return None


def mistake_parallel() -> bool:
    """HANDOVER_MISTAKE_PARALLEL=0 runs the mistake compare inline (serial), for tight rate limits."""
    return config.env_bool("HANDOVER_MISTAKE_PARALLEL", True)


@dataclass
class RunStats:
    """One pass through a lesson, from select_lesson to done, for the run events."""

    run_id: str
    started: float
    camera_steps: int = 0  # forward step moves by the camera
    manual_steps: int = 0  # forward step moves by button or voice
    mistakes: int = 0
    done_sent: bool = False


@dataclass
class CheckJob:
    """One check about to run: the step, its reference (and the previous step's), and the newest gated frame."""

    index: int
    question: str
    ref: bytes
    frame: bytes
    version: int
    prev_ref: Optional[bytes] = None


class Engine:
    """Single global learn session."""

    def __init__(self) -> None:
        self.lesson_id: Optional[str] = None
        self.lesson: Optional[dict] = None
        self.rev = 0  # only ever increases, see refresh_rev
        self.rev_source: tuple = (None, 0)  # (lesson_id, lesson.json mtime in ms) rev was last computed from
        self.step = 0
        self.done = False
        self.checking = False
        self.verified = False
        self.last_check: Optional[dict] = None
        self.mistake: Optional[dict] = None  # contract 7.2 fields minus "type"
        self.version = 0  # bumps on every lesson or step change
        self.step_started = time.monotonic()
        self.debouncer = check.Debouncer()
        self.gate = gate.MotionGate()
        self.breaker = check.Breaker()
        self.watch = mistake.MistakeWatch()
        self.offline_seen: tuple = (False, None)  # (check_offline, reason) last sent to clients
        self.run: Optional[RunStats] = None
        self.failed_sinks: set[int] = set()
        self.started = time.monotonic()
        self.ui: set[UIClient] = set()
        self.cams: list[Camera] = []
        self.cameras = 0  # len(self.cams); kept as a plain count for the check loop
        self.active: Optional[Camera] = None
        self.frame: Optional[bytes] = None
        self.frame_seq = 0
        self.checked_seq = 0
        self.gated_frame: Optional[bytes] = None  # newest frame the motion gate has seen
        self.gated_seq = 0
        self.frame_wanted = False  # the motion gate's answer for gated_frame
        self.inflight: Optional[asyncio.Task] = None  # the one running check
        self.mistake_task: Optional[asyncio.Task] = None  # the one running mistake compare (or mock confirm)
        self.mock_tick_at = 0.0  # last time the mock mistake hook was looked at
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

    def offline(self) -> tuple[bool, Optional[str]]:
        """(check_offline, check_offline_reason). Mock mode never uses Gemini, so it is never offline."""
        if check.is_mock() or not self.breaker.offline:
            return False, None
        return True, self.breaker.reason

    def state(self) -> dict:
        offline, reason = self.offline()
        return {
            "type": "state",
            "lesson_id": self.lesson_id,
            "step": self.step,
            "total": len(self.steps),
            "status": self.status(),
            "last_check": self.last_check,
            "camera_connected": self.cameras > 0,
            "rev": self.rev,
            "camera": self.active.identity() if self.active else None,
            "check_offline": offline,
            "check_offline_reason": reason,
            "mistake": self.mistake,
        }

    def broadcast(self, msg: Any) -> None:
        """To every UI client; text messages also go to every camera that said hello."""
        for c in list(self.ui):
            c.push(msg)
        if not isinstance(msg, bytes):
            for cam in self.cams:
                if cam.said_hello:
                    cam.push(msg)

    def broadcast_state(self) -> None:
        self.broadcast(self.state())

    def sync_offline(self) -> bool:
        """Records the breaker state; True when it changed since clients last heard it."""
        now = self.offline()
        changed, self.offline_seen = now != self.offline_seen, now
        if changed:
            self.emit("breaker", open=now[0], reason=now[1])
        return changed

    def open_breaker_if_no_key(self) -> None:
        """In gemini mode without a key, show "Checks off" from the start instead of after the first frame."""
        has_key = getattr(check, "has_key", None)  # public key probe requested from check.py
        if check.is_mock() or has_key is None or has_key():
            return
        self.breaker.force_open("no_key", time.monotonic())
        self.sync_offline()

    def emit(self, event: str, /, **fields: Any) -> None:
        """Send one learn event to every EVENT_SINKS subscriber. A failing sink is logged and skipped.
        The event type goes out as "kind", so the mistake event carries its own kind as mistake_kind."""
        if not EVENT_SINKS:
            return
        payload = {"event_id": uuid.uuid4().hex,
                 "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "run_id": self.run.run_id if self.run else None, "lesson_id": self.lesson_id, "rev": self.rev,
                 **fields, "kind": event}
        for sink in list(EVENT_SINKS):
            try:
                sink(payload)
            except Exception as e:
                metrics["event_sink_errors"] += 1
                if id(sink) in self.failed_sinks:  # traceback once per sink, not once per event
                    log.debug("event sink %r failed again: %s", sink, e)
                else:
                    self.failed_sinks.add(id(sink))
                    log.exception("event sink %r failed (further failures logged at debug)", sink)

    def _emit_step_enter(self) -> None:
        cur = self.current()
        if cur is None:
            return
        start, end = parse_seconds(cur.get("start")), parse_seconds(cur.get("end"))
        expert = round(end - start, 3) if start is not None and end is not None else None
        self.emit("step_enter", step=self.step, check_type=cur.get("check_type", "camera"), expert_seconds=expert)

    def snapshot(self) -> dict:
        """Health and counters in one dict, for a future /api/health or /api/metrics route."""
        offline, reason = self.offline()
        return {"uptime_s": round(time.monotonic() - self.started, 1), "lesson_id": self.lesson_id,
                "step": self.step, "total": len(self.steps), "status": self.status(), "cameras": self.cameras,
                "ui_clients": len(self.ui), "check_mode": "mock" if check.is_mock() else "gemini",
                "check_offline": offline, "check_offline_reason": reason, "gate": self.gate.stats,
                "counters": dict(metrics)}

    # ---- step changes

    def _enter_step(self) -> None:
        self.version += 1
        self.debouncer.reset()
        self.gate.reset()
        self.watch.reset()
        self.checking = False
        self.verified = False
        self.last_check = None
        self.mistake = None
        self.step_started = time.monotonic()
        self.checked_seq = self.frame_seq  # never judge a new step with a frame taken before it began

    def select(self, lesson_id: str) -> None:
        lesson = read_lesson(lesson_id)
        self.lesson_id, self.lesson = lesson_id, lesson
        self.refresh_rev()
        self.step, self.done = 0, False
        self.ref_cache.clear()
        self._enter_step()
        self.run = RunStats(uuid.uuid4().hex, time.monotonic())
        log.info("selected lesson %s (%d steps)", lesson_id, len(self.steps))
        self.emit("run_start", total=len(self.steps))
        self._emit_step_enter()
        self.broadcast_state()

    def reload_if_active(self, lesson_id: str) -> None:
        """After a recut, pick up new timestamps and reference frames, keep the step."""
        if self.lesson_id != lesson_id:
            return
        with contextlib.suppress(HTTPException):
            self.lesson = read_lesson(lesson_id)
        self.refresh_rev()
        self.ref_cache.clear()
        if self.step >= len(self.steps):
            self.step = max(0, len(self.steps) - 1)
        self._enter_step()
        self.broadcast_state()

    def refresh_rev(self) -> None:
        """rev = max(previous + 1, lesson.json mtime in ms), so it only ever increases, even when switching to an
        older lesson. Unchanged when the same lesson file is selected again (nothing to refetch)."""
        source = (self.lesson_id, lesson_rev(self.lesson_id))
        if source != self.rev_source:
            self.rev = max(self.rev + 1, source[1])
            self.rev_source = source

    def clear_if_active(self, lesson_id: str) -> None:
        """The lesson is being deleted: unload it so nothing reads its files, and tell the clients."""
        if self.lesson_id != lesson_id:
            return
        self.stop_run("deleted")
        self.lesson_id, self.lesson = None, None
        self.step, self.done = 0, False
        self.ref_cache.clear()
        self._enter_step()
        log.info("cleared deleted lesson %s", lesson_id)
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
        step_seconds = round(time.monotonic() - self.step_started, 3)
        if to >= total:
            self.done = True
            self.step = max(0, total - 1)
        else:
            self.done = False
            self.step = to
        self._enter_step()
        log.info("step %d -> %d (%s)", frm, to, reason)
        metrics[f"advances_{reason}"] += 1
        self.broadcast({"type": "advance", "from": frm, "to": to, "reason": reason})
        self.emit("advance", **{"from": frm, "to": to, "reason": reason, "step_seconds": step_seconds})
        self._record_run(frm, to, reason)
        self.broadcast_state()

    def stop_run(self, why: str) -> None:
        """End an unfinished run without a run_done (lesson deleted, hub shutting down)."""
        if self.run is not None and not self.run.done_sent:
            self.emit("run_stop", reason=why)
        self.run = None

    def _record_run(self, frm: int, to: int, reason: str) -> None:
        """Count forward moves for the run, then emit step_enter, or run_done the first time the run finishes."""
        run = self.run
        if run is not None and to > frm:
            if reason == "camera":
                run.camera_steps += to - frm
            else:
                run.manual_steps += to - frm
        if not self.done:
            self._emit_step_enter()
        elif run is not None and not run.done_sent:
            run.done_sent = True
            self.emit("run_done", total_seconds=round(time.monotonic() - run.started, 3),
                      camera_steps=run.camera_steps, manual_steps=run.manual_steps, mistakes=run.mistakes)

    def position(self) -> int:
        return len(self.steps) if self.done else self.step

    def dismiss_mistake(self) -> None:
        if self.mistake is not None:
            self.mistake = None
            self.broadcast_state()

    # ---- cameras

    def add_camera(self, ws: WebSocket, now: float, label: str = "-") -> Camera:
        """A new connection is the newest camera, so it becomes active."""
        taken = {c.number for c in self.cams}
        cam = Camera(ws, next(n for n in range(1, len(taken) + 2) if n not in taken), now, label)
        self.cams.append(cam)
        self.cameras = len(self.cams)
        self._set_active(cam)
        log.info("camera connected: %s (%d)", cam.name, self.cameras)
        # The UI hears about the camera once its hello arrives, or after the grace time without one, so the
        # banner does not flicker from "Camera 1" to the real name within a moment.
        grace = config.env_float("HANDOVER_HELLO_GRACE_MS", 300, 0, 5000) / 1000
        cam.announce = asyncio.get_running_loop().call_later(grace, self._announce, cam)
        return cam

    def _announce(self, cam: Camera) -> None:
        cam.announce = None
        if cam in self.cams:
            self.broadcast_state()

    @staticmethod
    def _cancel_announce(cam: Camera) -> None:
        if cam.announce is not None:
            cam.announce.cancel()
            cam.announce = None

    def remove_camera(self, cam: Camera) -> None:
        """Safe to call twice (a replaced camera is dropped at hello time and again when its socket ends)."""
        if self._drop(cam):
            log.info("camera disconnected: %s (%d)", cam.name, self.cameras)
            self.broadcast_state()

    def _drop(self, cam: Camera) -> bool:
        if cam not in self.cams:
            return False
        self._cancel_announce(cam)
        self.cams.remove(cam)
        self.cameras = len(self.cams)
        if self.active is cam:
            self.active = None
            heir = max(self.cams, key=lambda c: (c.last_frame, c.connected_at), default=None)
            if heir is not None:
                self._set_active(heir)
        return True

    @staticmethod
    def idle_for(cam: Camera, now: float) -> float:
        """Seconds since the camera's last frame (or since it became active). Text messages do not count, so a
        camera that only repeats hello still hands over to one that sends frames."""
        return now - max(cam.last_frame, cam.active_since)

    def _set_active(self, cam: Camera) -> bool:
        """Make `cam` the active camera; tells the old and new one. False when it already was."""
        if self.active is cam:
            return False
        if self.active is not None:
            self.active.push({"type": "camera_status", "active": False})
        self.active = cam
        cam.active_since = time.monotonic()
        cam.push({"type": "camera_status", "active": True})
        return True

    def on_hello(self, cam: Camera, msg: dict) -> list[Camera]:
        """Apply a hello. Returns older connections with the same device_id, already dropped, to close."""
        fields = parse_hello(msg)
        if fields is None:
            log.info("malformed hello from %s ignored", cam.name)
            return []
        for key, value in fields.items():
            setattr(cam, key, value)
        cam.said_hello = True
        self._cancel_announce(cam)  # this hello's state broadcast below is the announcement
        replaced = [c for c in self.cams if c is not cam and cam.device_id and c.device_id == cam.device_id]
        for old in replaced:
            self._drop(old)
        self._set_active(cam)
        log.info("hello: %s (%s, %s)", cam.name, cam.platform, cam.source)
        self.broadcast_state()
        return replaced

    def camera_frame(self, cam: Camera, data: bytes, now: float) -> None:
        """A binary message from a camera. Only the active camera's JPEGs are judged and forwarded. An active
        camera with no frame for ACTIVE_IDLE_SECONDS loses to one that is sending frames (this one, right now)."""
        if len(data) > MAX_FRAME_BYTES or data[:2] != b"\xff\xd8":
            metrics["frames_ignored"] += 1
            return
        if now - cam.last_frame < config.env_float("HANDOVER_MIN_FRAME_GAP", 0.2, 0, 5):
            metrics["frames_too_fast"] += 1
            return
        cam.last_frame = now
        metrics["frames_in"] += 1
        if self.active is not cam and (self.active is None or self.idle_for(self.active, now) >= ACTIVE_IDLE_SECONDS):
            self._set_active(cam)
            log.info("active camera: %s", cam.name)
            self.broadcast_state()
        if self.active is cam:
            self.on_frame(data)

    # ---- frames

    def on_frame(self, data: bytes) -> None:
        """A frame from the active camera. Held in memory only; frames never touch disk (M15)."""
        self.frame = data
        self.frame_seq += 1
        self.frame_event.set()
        self.ui_frame_event.set()

    def ref_bytes(self, index: int) -> Optional[bytes]:
        """Reference frame of step `index` (its ref_frame, default frames/NN.jpg), cached; None when missing."""
        steps = self.steps
        if not self.lesson_id or not 0 <= index < len(steps):
            return None
        rel = steps[index].get("ref_frame") or f"frames/{index + 1:02d}.jpg"
        if not isinstance(rel, str):
            return None
        key = (self.lesson_id, rel)
        if key not in self.ref_cache:
            path = (LESSONS / self.lesson_id / rel).resolve()
            if not path.is_file() or LESSONS not in path.parents:
                if key not in self.missing_ref_logged:
                    log.warning("reference frame missing: %s", redact(str(path)))
                    self.missing_ref_logged.add(key)
                return None
            self.ref_cache[key] = path.read_bytes()
        return self.ref_cache[key]

    # ---- background loops

    async def check_loop(self) -> None:
        """Gates every new frame (Pillow work in a worker thread) and starts a check when none is in flight,
        always on the newest gated frame. Gating goes on while a check runs, so the gate sees all motion."""
        log_ctx.set("engine")
        try:
            while True:
                await self.frame_event.wait()
                self.frame_event.clear()
                try:
                    await self._gate_newest()
                    self._mock_tick()
                    if self.inflight is None or self.inflight.done():
                        job = self._next_job()
                        if job is not None:
                            self.inflight = asyncio.create_task(self._check_task(job))
                except Exception:  # one bad frame or lesson must not stop checking for the session
                    log.exception("check loop iteration failed")
        finally:
            for task in (self.inflight, self.mistake_task):
                if task is not None:
                    task.cancel()

    async def _gate_newest(self) -> None:
        if self.frame is None or self.frame_seq == self.gated_seq:
            return
        frame, seq = self.frame, self.frame_seq
        wanted = await asyncio.to_thread(self.gate.observe, frame, time.monotonic())
        self.gated_frame, self.gated_seq, self.frame_wanted = frame, seq, wanted

    async def _check_task(self, job: CheckJob) -> None:
        try:
            await self._run_check(job)
        except Exception:  # keep checking later frames; nothing awaits this task, so log here
            log.exception("check task crashed")
        finally:
            self.frame_event.set()  # frames gated meanwhile may be ready for the next check

    def _next_job(self) -> Optional[CheckJob]:
        """The check to run now, or None. Order matters: the breaker's trial call is spent last."""
        cur = self.current()
        if cur is None or cur.get("check_type", "camera") != "camera" or self.verified:
            return None
        frame = self.gated_frame
        # Fast confirm: after a yes, the next still frame is checked at once, even though the gate sees no
        # change since the last check; otherwise the confirming yes would wait for the 6 s heartbeat.
        confirming = self.debouncer.count > 0 and self.gate.settled
        if frame is None or self.gated_seq <= self.checked_seq or self.cameras == 0:
            return None
        if not (self.frame_wanted or confirming):
            return None
        ref = self.ref_bytes(self.step)
        if ref is None:
            return None
        now = time.monotonic()
        allowed = self.breaker.allow(now)
        if self.sync_offline():
            self.broadcast_state()
        if not allowed:
            return None
        self.gate.mark_checked(now)
        self.checked_seq = self.gated_seq
        question = cur.get("check_question") or "Is this step finished?"
        prev_ref = self.ref_bytes(self.step - 1) if self.step > 0 else None
        return CheckJob(self.step, question, ref, frame, self.version, prev_ref)

    async def _run_check(self, job: CheckJob) -> None:
        # Checks run back to back, so status stays "watching" unless one is slow; flipping to "checking"
        # for every frame made the UI flap twice a second.
        prev = self._check_signature()
        show = asyncio.get_running_loop().call_later(CHECKING_SHOW_AFTER, self._show_checking, job.version)
        try:
            res = await check.check_frame(job.ref, job.frame, job.question, step_started_at=self.step_started,
                                          prev_ref=job.prev_ref)
        except Exception:  # check_frame should never raise; keep the loop alive regardless
            log.exception("check crashed")
            res = check.CheckResult("unsure", 0.0, 0, error="error")
        finally:
            show.cancel()
        self.breaker.record(res, time.monotonic())
        offline_changed = self.sync_offline()
        self._record_check(job, res)
        if job.version != self.version:
            if offline_changed:
                self.broadcast_state()
            return  # step changed while the check was running; the stale result is ignored
        shown = self.checking
        self.checking = False
        self.last_check = res.as_dict()
        cleared = res.done == "yes" and self.mistake is not None
        if cleared:
            self.mistake = None
        if self.debouncer.feed(res.done, res.confidence):
            await self._verify_and_advance(job.version)
            return
        if shown or cleared or offline_changed or self._check_signature() != prev:
            self.broadcast_state()  # only when the answer changed, not on every identical result
        await self._after_result(job, res.done)

    def _record_check(self, job: CheckJob, res: check.CheckResult) -> None:
        metrics["checks"] += 1
        if res.error:
            metrics[f"check_errors_{res.error}"] += 1
        log.debug("check step %d: %s %.2f %d ms, gate %s", job.index, res.done, res.confidence, res.latency_ms,
                  self.gate.stats)
        model = "mock" if check.is_mock() else str(config.get("HANDOVER_CHECK_MODEL"))
        self.emit("check", step=job.index, done=res.done, confidence=round(res.confidence, 3),
                  latency_ms=res.latency_ms, reason=res.reason, model=model, gated=self.gate.enabled,
                  error_kind=res.error)

    async def _verify_and_advance(self, version: int) -> None:
        self.verified = True
        self.broadcast_state()
        await asyncio.sleep(VERIFIED_HOLD)
        if version == self.version:
            self.go(self.position() + 1, "camera")

    def _show_checking(self, version: int) -> None:
        if version == self.version and not self.verified:
            self.checking = True
            self.broadcast_state()

    def _check_signature(self) -> tuple:
        lc = self.last_check or {}
        return self.status(), lc.get("done"), lc.get("confidence"), lc.get("reason")

    # ---- mistake check (M9)

    async def _after_result(self, job: CheckJob, done: str) -> None:
        """Feed the mistake policy after a check that did not pass. A due compare runs as its own task (one at a
        time) so it never delays normal checks, or inline when HANDOVER_MISTAKE_PARALLEL=0.
        Mock mode never calls Gemini for this; its HANDOVER_MOCK_MISTAKE hook runs in _mock_tick instead."""
        if check.is_mock():
            return
        if not self.watch.on_result(job.index, done, time.monotonic()):
            return
        if self.mistake_task is not None and not self.mistake_task.done():
            return
        if mistake_parallel():
            self.mistake_task = asyncio.create_task(self._background(self._compare_and_raise(job), "mistake compare"))
        else:
            await self._compare_and_raise(job)

    async def _background(self, work: Awaitable[None], what: str) -> None:
        try:
            await work
        except Exception:  # nothing awaits this task, so log here
            log.exception("%s crashed", what)

    def _mock_tick(self) -> None:
        """HANDOVER_MOCK_MISTAKE hook, mock mode only. Looked at on the frame path at most once a second, so it
        fires even while the motion gate holds checks back. Once per step visit, after the hook's delay, unless
        the last check on this step said yes. An ahead still needs its confirming check."""
        now = time.monotonic()
        if not check.is_mock() or now - self.mock_tick_at < MOCK_TICK_SECONDS:
            return
        self.mock_tick_at = now
        cur = self.current()
        if cur is None or cur.get("check_type", "camera") != "camera" or self.verified or self.cameras == 0:
            return
        if self.last_check is not None and self.last_check.get("done") == "yes":
            return
        found = self.watch.mock(self.step, now - self.step_started, self.steps)
        if found is None:
            return
        if not mistake.needs_confirmation(found):
            self._raise_mistake(found)
            return
        frame, ref = self.gated_frame or self.frame, self.ref_bytes(self.step)
        if frame is None or ref is None or (self.mistake_task is not None and not self.mistake_task.done()):
            return
        job = CheckJob(self.step, cur.get("check_question") or "", ref, frame, self.version)
        self.mistake_task = asyncio.create_task(self._background(self._confirm_and_raise(job, found), "mock confirm"))

    async def _confirm_and_raise(self, job: CheckJob, found: dict) -> None:
        if await self._confirm_ahead(job) and job.version == self.version:
            self._raise_mistake(found)

    async def _compare_and_raise(self, job: CheckJob) -> None:
        match = await self._compare(job)
        if match is None or job.version != self.version:
            return
        found = self.watch.decide(job.index, len(self.steps), match.step, match.confidence, self.steps, "gemini")
        if found is None:
            return
        if mistake.needs_confirmation(found) and not await self._confirm_ahead(job):
            return
        if job.version == self.version:
            self._raise_mistake(found)

    async def _compare(self, job: CheckJob) -> Optional[check.MatchResult]:
        """One multiple-choice call over references k-1, k, k+1 (those that exist). None when it cannot run."""
        refs = []
        for i in (job.index - 1, job.index, job.index + 1):
            ref = self.ref_bytes(i)
            if ref is not None:
                refs.append((i, ref))
        if len(refs) < 2 or not self._breaker_allows():
            return None
        match = await check.compare_refs(job.frame, refs, job.question)
        self._breaker_record(match)
        return None if match.error else match

    async def _confirm_ahead(self, job: CheckJob) -> bool:
        """An ahead match counts only if a normal check of step k+1 says yes with enough confidence."""
        k1 = job.index + 1
        if k1 >= len(self.steps):
            return False
        nxt = self.steps[k1]
        ref = self.ref_bytes(k1)
        if ref is None or not self._breaker_allows():
            return False
        question = nxt.get("check_question") or "Is this step finished?"
        # Mock: the HANDOVER_MOCK_MISTAKE hook stands in for Gemini's match, so its confirming check is told the
        # step finished long ago; with the real step timer it would repeat the "no" that triggered the hook.
        started = 0.0 if check.is_mock() else self.step_started
        res = await check.check_frame(ref, job.frame, question, step_started_at=started, prev_ref=job.ref)
        self._breaker_record(res)
        return res.done == "yes" and res.confidence >= mistake.AHEAD_CONFIRM_CONF

    def _breaker_allows(self) -> bool:
        allowed = self.breaker.allow(time.monotonic())
        if self.sync_offline():
            self.broadcast_state()
        return allowed

    def _breaker_record(self, result: check.CheckResult | check.MatchResult) -> None:
        self.breaker.record(result, time.monotonic())
        if self.sync_offline():
            self.broadcast_state()

    def _raise_mistake(self, found: dict) -> None:
        """Send the mistake once and show it in state.mistake. Behind stays until cleared; ahead (already
        confirmed) skips to k+2 right after."""
        k = found["step"]
        if k != self.step or self.done:
            return
        log.info("mistake on step %d: %s (%s)", k, found["kind"], found["source"])
        metrics["mistakes"] += 1
        if self.run is not None:
            self.run.mistakes += 1
        self.emit("mistake", step=k, mistake_kind=found["kind"], looks_like=found["looks_like"],
                  confidence=found["confidence"], source=found["source"])
        ahead = mistake.needs_confirmation(found)
        if ahead and k + 1 >= len(self.steps):
            return
        self.mistake = {key: value for key, value in found.items() if key != "type"}
        self.broadcast(found)
        self.broadcast_state()  # state.mistake holds it while shown; an ahead then skips to k+2, which clears it
        if ahead:
            self.go(k + 2, "camera")

    async def ui_frame_loop(self) -> None:
        """Forward the newest camera frame to UI clients, downscaled, at most 4 per second."""
        log_ctx.set("engine")
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
                log.debug("bad camera frame skipped: %s", e)
                metrics["frames_undecodable"] += 1
                continue
            self.broadcast(small)


engine = Engine()


async def warm_up() -> None:
    """Open the pooled Gemini connection at startup so the first real check is not slow. Skipped in mock mode,
    without a key, or until check.py offers a public warm_up; never fails startup."""
    warm = getattr(check, "warm_up", None)
    if check.is_mock() or warm is None:
        return
    try:
        await asyncio.wait_for(warm(), WARM_UP_TIMEOUT)
    except Exception as e:
        log.warning("gemini warm-up skipped: %s", check._redact(f"{type(e).__name__}: {e}"))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(engine.check_loop()), asyncio.create_task(engine.ui_frame_loop()),
             asyncio.create_task(warm_up())]
    engine.open_breaker_if_no_key()
    if databricks_module() is not None and databricks_sink not in EVENT_SINKS:
        EVENT_SINKS.append(databricks_sink)
    log.info("lessons: %s  check: %s", LESSONS, "mock" if check.is_mock() else "gemini")
    yield
    engine.stop_run("shutdown")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="HandOver", lifespan=lifespan)


class RequestIdMiddleware:
    """Tags each HTTP request's log lines with req-<id> and returns the id in x-request-id. A well-formed
    incoming x-request-id is kept so a client can correlate. Plain ASGI, so file streaming is untouched."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        given = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = given if REQUEST_ID_RE.match(given) else uuid.uuid4().hex[:12]

        async def send_with_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode("latin-1"))]
            await send(message)

        token = log_ctx.set(f"req-{rid}")
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log_ctx.reset(token)


class UploadLengthMiddleware:
    """POST /api/lesson must declare its size, and is refused before any body is read when it is far too big."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/lesson":
            length = dict(scope.get("headers") or []).get(b"content-length", b"").decode("latin-1")
            refusal = None
            if not length.isdigit():
                refusal = (411, "content length required")
            elif int(length) > MAX_UPLOAD_BYTES + 1024**2:  # 1 MB of slack for the multipart wrapping
                refusal = (413, "video is larger than 2 GB")
            if refusal is not None:
                await JSONResponse({"detail": refusal[1]}, status_code=refusal[0])(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(UploadLengthMiddleware)
app.add_middleware(RequestIdMiddleware)  # added last, so it is outermost and tags refusals too


# ---------------------------------------------------------------- REST

@app.get("/", response_model=None)
def root() -> FileResponse | dict:
    """The built web app when web/dist exists, else a pointer to the API and the Vite dev server."""
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return {"app": "HandOver", "api": "/api/lessons", "capture": "/capture", "ui": "http://localhost:5173"}


@app.get("/assets/{path:path}")
def web_asset(path: str) -> FileResponse:
    """Hashed build files of the web app (Vite names change on every build, so they cache forever)."""
    root = (WEB_DIST / "assets").resolve()
    file = (root / path).resolve()
    if root not in file.parents or not file.is_file():
        raise HTTPException(404, "not found")
    media_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    return FileResponse(file, media_type=media_type, headers={"Cache-Control": "public, max-age=31536000, immutable"})


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
        if not isinstance(data, dict):
            continue
        out.append({"id": d.name, "title": data.get("title") or d.name, "steps": len(data.get("steps") or [])})
    return out


@app.get("/api/lessons/{lesson_id}")
def get_lesson(lesson_id: str) -> JSONResponse:
    return JSONResponse(read_lesson(lesson_id), headers={"Cache-Control": "no-cache"})


jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
job_slots = threading.BoundedSemaphore(1)  # one teach job runs at a time; the rest wait as "queued"
lesson_write_lock = asyncio.Lock()  # recut and delete never overlap; a second one gets 409


def _set_job(job: str, **kw) -> None:
    with jobs_lock:
        jobs[job].update(kw)


def _job_error_message(e: Exception) -> str:
    msg = redact(f"{type(e).__name__}: {e}".strip())
    if len(msg) > 400:  # ffmpeg errors are long; keep the start and the useful tail
        msg = msg[:160].split("\n")[0] + " ... " + msg[-220:]
    return msg


def _run_job(job: str, src: Path, lesson_id: str, title: str) -> None:
    def progress(status: str, message: str = "") -> None:
        _set_job(job, status=status, message=message)

    log_ctx.set(f"job-{job}")  # a plain thread starts with an empty context
    try:
        with job_slots:
            from server import teach

            teach.process_upload(src, lesson_id, title, progress)
        _set_job(job, status="done", message="ready")
        log.info("job %s done: lesson %s", job, lesson_id)
        publish_lesson_files(lesson_id)
    except Exception as e:
        msg = _job_error_message(e)
        log.error("job %s failed: %s", job, msg)
        log.debug("job %s traceback", job, exc_info=True)
        d = LESSONS / lesson_id
        if d.is_dir() and not (d / "lesson.json").exists():  # half-built lesson folder from this job
            shutil.rmtree(d, ignore_errors=True)
        _set_job(job, status="error", message=msg)
    finally:
        src.unlink(missing_ok=True)


def reserve_job(requested_id: Optional[str], title: str) -> tuple[str, str]:
    """Choose the lesson id and list the job in one locked step, so two uploads can never claim the same id.
    Returns (job, lesson_id)."""
    from server import teach

    with jobs_lock:
        active = [j["id"] for j in jobs.values() if j["status"] not in ("done", "error")]
        if len(active) >= MAX_ACTIVE_JOBS:
            raise HTTPException(429, "too many jobs")
        if requested_id and requested_id.strip():
            try:
                lesson_id = teach.sanitize_id(requested_id)  # the same id the teach pipeline will write to
            except ValueError:
                raise HTTPException(400, "bad lesson id")
            if not ID_RE.match(lesson_id):
                raise HTTPException(400, "bad lesson id")
            if lesson_id in active or (LESSONS / lesson_id).exists():
                raise HTTPException(409, "lesson id already exists")
        else:
            lesson_id = unique_id(slugify(title))
        job = uuid.uuid4().hex[:12]
        jobs[job] = {"status": "queued", "message": "", "id": lesson_id}
    return job, lesson_id


def save_upload(file: UploadFile, dest: Path) -> bool:
    """Copies the upload to disk. False when it passes the size limit."""
    written = 0
    with dest.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                return False
            f.write(chunk)
    return True


@app.post("/api/lesson")
async def upload_lesson(file: UploadFile = File(...), title: str = Form(""), id: Optional[str] = Form(None)) -> dict:
    title = title.strip() or "Untitled lesson"
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "video is larger than 2 GB")
    job, lesson_id = reserve_job(id, title)
    suffix = Path(file.filename or "").suffix.lower()
    src = UPLOADS / f"{job}{suffix if suffix in UPLOAD_SUFFIXES else '.mp4'}"
    try:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        ok = await asyncio.to_thread(save_upload, file, src)
    except BaseException:
        src.unlink(missing_ok=True)
        _set_job(job, status="error", message="upload failed")
        raise
    if not ok:
        src.unlink(missing_ok=True)
        _set_job(job, status="error", message="video is larger than 2 GB")
        raise HTTPException(413, "video is larger than 2 GB")
    threading.Thread(target=_run_job, args=(job, src, lesson_id, title), daemon=True).start()
    log.info("job %s queued: %s -> lesson %s", job, src.name, lesson_id)
    return {"job": job, "id": lesson_id}


@app.get("/api/jobs/{job}")
def job_status(job: str) -> dict:
    with jobs_lock:
        if job not in jobs:
            raise HTTPException(404, "job not found")
        return dict(jobs[job])


async def read_recut_body(request: Request) -> Optional[dict]:
    """The optional lesson object sent with a recut, validated; None for an empty body."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_RECUT_BODY:
        raise HTTPException(413, "body is larger than 1 MB")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_RECUT_BODY:
            raise HTTPException(413, "body is larger than 1 MB")
    if not body.strip():
        return None
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "body must be application/json")
    try:
        new = json.loads(body)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        raise HTTPException(400, "body must be JSON")
    if not isinstance(new, dict) or not isinstance(new.get("steps"), list):
        raise HTTPException(400, "body must be a lesson object with steps")
    if len(new["steps"]) > MAX_RECUT_STEPS:
        raise HTTPException(400, "too many steps")
    return new


@app.post("/api/lessons/{lesson_id}/recut")
async def recut(lesson_id: str, request: Request) -> Any:
    """Re-cut from lesson.json. An optional JSON body (a full lesson object) is saved first."""
    d = lesson_dir(lesson_id)
    read_lesson(lesson_id)  # 404 if missing
    new = await read_recut_body(request)
    if lesson_write_lock.locked():
        raise HTTPException(409, "recut already running")
    async with lesson_write_lock:
        original = (d / "lesson.json").read_text(encoding="utf-8")
        if new is not None:
            new["id"] = lesson_id
            tmp = d / "lesson.json.tmp"
            tmp.write_text(json.dumps(new, indent=2), encoding="utf-8")
            tmp.replace(d / "lesson.json")
        try:
            from server import teach

            result = await asyncio.to_thread(teach.recut, d)
        except ValueError as e:  # bad timestamps in lesson.json: keep the last good file
            (d / "lesson.json").write_text(original, encoding="utf-8")
            raise HTTPException(400, redact(str(e)))
        except Exception as e:
            (d / "lesson.json").write_text(original, encoding="utf-8")
            msg = redact(f"{type(e).__name__}: {e}")
            log.error("recut %s failed: %s", lesson_id, msg)
            log.debug("recut %s traceback", lesson_id, exc_info=True)
            raise HTTPException(500, f"recut failed: {msg}")
    engine.reload_if_active(lesson_id)
    publish_lesson_files(lesson_id)
    return result


@app.delete("/api/lessons/{lesson_id}")
async def delete_lesson(lesson_id: str) -> dict:
    """Remove a lesson folder. A folder without lesson.json (a teach job still building) is not a lesson: 404."""
    d = lesson_dir(lesson_id)
    if not (d / "lesson.json").is_file():
        raise HTTPException(404, "lesson not found")
    if lesson_write_lock.locked():
        raise HTTPException(409, "recut already running")
    async with lesson_write_lock:
        engine.clear_if_active(lesson_id)
        try:
            await asyncio.to_thread(shutil.rmtree, d)
        except OSError as e:
            log.error("delete %s failed: %s", lesson_id, redact(str(e)))
            raise HTTPException(500, f"delete failed: {redact(str(e))}")
    log.info("deleted lesson %s", lesson_id)
    return {"deleted": lesson_id}


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
    label = f"cam-{next(conn_ids['cam'])}"
    log_ctx.set(label)
    if len(engine.cams) >= config.env_int("HANDOVER_MAX_CAMERAS", 8, 1, 64):
        log.warning("camera refused: limit reached")
        await ws.close(code=CLOSE_TRY_LATER, reason="too many cameras")
        return
    cam = engine.add_camera(ws, time.monotonic(), label)
    sender = asyncio.create_task(cam.sender())
    try:
        while cam in engine.cams:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                engine.camera_frame(cam, msg["bytes"], time.monotonic())
            elif msg.get("text"):
                await handle_camera_message(cam, msg["text"])
            if sender.done():
                break
    except (WebSocketDisconnect, RuntimeError):  # RuntimeError: receive after the socket was closed as replaced
        pass
    finally:
        engine.remove_camera(cam)
        sender.cancel()
        with contextlib.suppress(BaseException):
            await sender


@app.websocket("/ws/ui")
async def ws_ui(ws: WebSocket) -> None:
    await ws.accept()
    label = f"ui-{next(conn_ids['ui'])}"
    log_ctx.set(label)
    if len(engine.ui) >= config.env_int("HANDOVER_MAX_VIEWERS", 32, 1, 256):
        log.warning("viewer refused: limit reached")
        await ws.close(code=CLOSE_TRY_LATER, reason="too many viewers")
        return
    client = UIClient(ws, label)
    engine.ui.add(client)
    log.info("ui connected (%d)", len(engine.ui))
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
        log.info("ui disconnected (%d)", len(engine.ui))
        sender.cancel()
        with contextlib.suppress(BaseException):
            await sender


def from_matches(frm: Any) -> bool:
    """next/back carry the step the client was showing. A different step means the server moved on (a camera
    advance, another tap) and the command is stale. Absent `from` is the legacy form and always applies.
    On the done screen the state shows step total-1, so both total-1 and total count as current."""
    if frm is None:
        return True
    if not isinstance(frm, int) or isinstance(frm, bool):
        return False
    return frm == engine.position() or (engine.done and frm == engine.step)


def parse_message(text: str) -> Optional[dict]:
    """A JSON object from a client, or None for invalid JSON or anything that is not an object."""
    if len(text) > MAX_TEXT_MESSAGE:
        return None
    try:
        msg = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return None
    return msg if isinstance(msg, dict) else None


def navigate(client: UIClient, msg: dict) -> None:
    """next or back from the web app or a camera, with the stale `from` guard."""
    kind = msg.get("type")
    if engine.lesson is None:
        client.push({"type": "error", "message": "no lesson selected"})
    elif not from_matches(msg.get("from")):
        log.info("ignored stale %s (from %r, now at %d)", kind, msg.get("from"), engine.position())
    elif kind == "next":
        reason = msg.get("reason") if msg.get("reason") in ("button", "voice") else "button"
        engine.go(engine.position() + 1, reason)
    else:
        engine.go(engine.position() - 1, "button")


def handle_ui_message(client: UIClient, text: str) -> None:
    msg = parse_message(text)
    if msg is None:
        return
    kind = msg.get("type")
    if kind == "select_lesson":
        try:
            engine.select(str(msg.get("id", "")))
        except HTTPException as e:
            client.push({"type": "error", "message": e.detail})
    elif engine.lesson is None:
        client.push({"type": "error", "message": "no lesson selected"})
    elif kind in ("next", "back"):
        navigate(client, msg)
    elif kind == "goto":
        step = msg.get("step")
        if isinstance(step, int) and not isinstance(step, bool) and 0 <= step < len(engine.steps):
            engine.go(step, "button")
    elif kind == "dismiss_mistake":
        engine.dismiss_mistake()


async def handle_camera_message(cam: Camera, text: str) -> None:
    """hello, and next/back once the camera has said hello. Everything else is ignored."""
    msg = parse_message(text)
    if msg is None:
        return
    kind = msg.get("type")
    if kind == "hello":
        for old in engine.on_hello(cam, msg):
            log.info("closing %s: replaced by a newer connection", old.name)
            with contextlib.suppress(Exception):
                await old.ws.close(code=CLOSE_REPLACED, reason="replaced")
    elif kind in ("next", "back") and cam.said_hello:
        navigate(cam, msg)


# ---------------------------------------------------------------- entry point

def startup_cleanup(now: Optional[float] = None) -> list[Path]:
    """List what a crash can leave behind: upload copies in server/uploads and .recut_tmp / .recut_old inside
    lesson folders, untouched for STALE_TEMP_SECONDS (so a second hub from the same repo never touches files a
    running hub still uses). Log-only by default: nothing is deleted unless HANDOVER_STARTUP_CLEANUP=1.
    Nothing else in a lesson folder is ever touched. Returns the stale paths found; each is logged."""
    now = time.time() if now is None else now
    delete = config.env_bool("HANDOVER_STARTUP_CLEANUP", False)
    candidates = list(UPLOADS.iterdir()) if UPLOADS.is_dir() else []
    for d in (LESSONS.iterdir() if LESSONS.is_dir() else []):
        if d.is_dir() and not d.is_symlink():
            candidates += [d / name for name in (".recut_tmp", ".recut_old") if (d / name).exists()]
    stale = []
    for path in candidates:
        try:
            if now - path.lstat().st_mtime < STALE_TEMP_SECONDS:
                continue
            if delete:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        except OSError as e:
            log.warning("startup cleanup: could not remove %s: %s", redact(str(path)), e)
            continue
        if delete:
            log.info("startup cleanup: removed %s", redact(str(path)))
        else:
            log.info("startup cleanup: stale, not removed (set HANDOVER_STARTUP_CLEANUP=1 to remove): %s",
                     redact(str(path)))
        stale.append(path)
    return stale


def serve() -> None:
    """Serve http and (when certs exist) https from ONE process, so both share the same learn session."""
    import uvicorn

    http_port = int(config.get("HANDOVER_PORT"))  # type: ignore[arg-type]
    https_port = int(config.get("HANDOVER_HTTPS_PORT"))  # type: ignore[arg-type]
    startup_cleanup()
    certs = Path(os.environ.get("HANDOVER_CERTS") or REPO / "certs")
    cert, key = certs / "cert.pem", certs / "key.pem"
    # Oversize camera frames are dropped by the app (the 2 MB rule) instead of uvicorn closing the camera;
    # pings find dead phones within 20 s; log_config=None keeps the one logging setup above.
    common = dict(host="0.0.0.0", ws_max_size=8 * 1024**2, ws_ping_interval=10, ws_ping_timeout=10,
                  ws_per_message_deflate=False, timeout_graceful_shutdown=3, log_config=None)
    configs = [uvicorn.Config(app, port=http_port, lifespan="on", **common)]
    if cert.is_file() and key.is_file():
        # The lifespan (engine start) runs on the http server only; the https server shares it.
        configs.append(uvicorn.Config(app, port=https_port, lifespan="off", ssl_certfile=str(cert),
                                      ssl_keyfile=str(key), **common))
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
            try:
                loop.add_signal_handler(sig, stop)
            except (NotImplementedError, RuntimeError):  # Windows event loops have no add_signal_handler
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop))

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

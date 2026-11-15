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
import math
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server import accounts, analytics_privacy, check, config, gate, mistake, routes_library, understand

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
GATE_MIN_INTERVAL = 0.125  # 8 tiny gate decodes/s: two still samples recognize a finished motion in ~250 ms
FAST_CONFIRM_INTERVAL = 0.25  # after a likely pass, confirm promptly without raising the normal model-call rate
VERIFIED_HOLD = config.env_float("HANDOVER_VERIFIED_HOLD", 0.8, 0, 10)  # seconds "verified" shows before advancing
MAX_UPLOAD_BYTES = 2 * 1024**3  # 2 GB
CHECKING_SHOW_AFTER = 1.5  # seconds a check must be in flight before the UI is told "checking"
MAX_FRAME_BYTES = 2 * 1024**2  # camera frames over 2 MB are ignored
ACTIVE_IDLE_SECONDS = 5.0  # an active camera silent this long loses to one that is sending frames
CLOSE_REPLACED = 4000  # close code when a newer connection says hello with the same device_id
HELLO_PLATFORMS = ("ios", "android", "web", "macos", "windows", "linux", "replay")  # anything else: "other"
HELLO_SOURCES = ("glasses", "phone", "browser", "file")
SEND_TIMEOUT = 5.0  # seconds one websocket send may take before the client counts as stalled
EVENT_QUEUE_MAX = 64  # advance, mistake and error messages held per client before new ones are dropped
CLOSE_STALLED = 1011  # close code when a client's sender gave up (a send took over SEND_TIMEOUT)
WARM_UP_TIMEOUT = 5.0  # seconds for the startup call that opens the pooled check-provider connection
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
    """API keys and absolute paths out of anything a client or a log line sees."""
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

    def __init__(self, ws: WebSocket, label: str = "-", frames: bool = True):
        self.ws = ws
        self.label = label
        self.frames = frames  # False (/ws/ui?frames=0): a phone that is itself the camera gets no live frames
        self.queue: collections.deque = collections.deque()
        self.latest_state: Optional[dict] = None
        self.latest_frame: Optional[bytes] = None
        self.wake = asyncio.Event()

    def push(self, msg: Any) -> None:
        """Queue one message: bytes are a live frame, a dict is JSON text."""
        if isinstance(msg, bytes) and not self.frames:
            return
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
        self.source = "unknown"  # never guessed: only a hello says what kind of camera this is
        self.device_id: Optional[str] = None
        self.said_hello = False
        self.connected_at = now
        self.hello_at = 0.0
        self.first_frame_at = 0.0
        self.active_since = now  # when it last became active; idle counts from here until its first frame
        self.last_frame = 0.0  # 0 = no frame yet
        self.frame_interval_ema = 0.0  # receive cadence only; frames remain memory-only
        self.announce: Optional[asyncio.TimerHandle] = None  # pending first state broadcast, see add_camera

    def push(self, msg: Any) -> None:
        if not isinstance(msg, bytes):
            super().push(msg)

    def identity(self) -> dict:
        return {"name": self.name, "platform": self.platform, "source": self.source}

    def record_frame(self, now: float) -> None:
        if self.last_frame:
            gap = max(0.001, now - self.last_frame)
            self.frame_interval_ema = gap if not self.frame_interval_ema else self.frame_interval_ema * 0.75 + gap * 0.25
        self.last_frame = now

    def received_fps(self) -> Optional[float]:
        return round(1 / self.frame_interval_ema, 1) if self.frame_interval_ema > 0 else None


def parse_hello(msg: dict) -> Optional[dict]:
    """The identity fields of a hello, cleaned, or None when it is malformed. Absent fields keep their value.
    An unknown platform string becomes "other" (a new app still gets next and back); a non-string platform or
    an unknown source makes the hello malformed."""
    out: dict = {}
    if "platform" in msg:
        platform = msg["platform"]
        if not isinstance(platform, str):
            return None
        platform = platform.strip().lower()
        if platform:
            out["platform"] = platform if platform in HELLO_PLATFORMS else "other"
    if "source" in msg:
        if msg["source"] not in HELLO_SOURCES:
            return None
        out["source"] = msg["source"]
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
must return at once. Events hold no frames and nothing here writes to disk, so the privacy guarantee holds."""


ENVELOPE = ("event_id", "ts", "run_id", "lesson_id", "rev", "kind")  # fields every learn event carries


def databricks_module() -> Any:
    """server.databricks (the Databricks uploader) when it can be imported, else None; the hub runs either way."""
    try:
        return importlib.import_module("server.databricks")
    except ImportError:
        return None


DB_RUN_IDS: dict[str, str] = {}
"""Hub run id -> the run id server.databricks.start_run returned (the id its events, and so the library's
scores, are keyed by)."""


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
        db_run = call_accepting(db.start_run, event["lesson_id"], **fields)
        if isinstance(db_run, str) and db_run and event.get("run_id"):
            DB_RUN_IDS.clear()  # only the newest run matters; keeps this from growing
            DB_RUN_IDS[event["run_id"]] = db_run
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


def call_accepting(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """fn(*args, **kwargs) with only the keyword arguments fn accepts (all of them when it takes **kwargs), so the
    hub can pass new fields to server.databricks before its signature has them."""
    import inspect

    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        params = {}
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    return fn(*args, **kwargs)


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


OVERRIDE_MIN_SECONDS = 8.0
"""understand_override also needs its streak of confident check yes answers to span this long."""


def _tunable(kind: str, name: str, default: Any, lo: Any = None, hi: Any = None) -> Any:
    """A HANDOVER_* value through server/config.py once it is registered there; until then the same default
    and bounds are applied here, so registering it later changes nothing."""
    try:
        return config.get(name)
    except KeyError:
        pass
    if kind == "int":
        return config.env_int(name, default, lo, hi)
    if kind == "float":
        return config.env_float(name, default, lo, hi)
    return config.env_bool(name, default)


def max_inflight() -> int:
    """HANDOVER_MAX_INFLIGHT: checks allowed at once on one step, each on a different settled frame."""
    return _tunable("int", "HANDOVER_MAX_INFLIGHT", 2, 1, 4)


def fast_path() -> bool:
    """HANDOVER_FAST_PATH: one very confident yes that names no difference advances without a second yes."""
    return _tunable("bool", "HANDOVER_FAST_PATH", True)


def fast_conf() -> float:
    """HANDOVER_FAST_CONF: confidence a single yes needs for the fast path."""
    return _tunable("float", "HANDOVER_FAST_CONF", 0.92, 0.5, 1)


def ahead_skip() -> bool:
    """HANDOVER_AHEAD_SKIP: an ahead mistake may skip to step k+2. Off by default: a wrong skip is far worse than
    a missed catch, so ahead only shows its banner."""
    return _tunable("bool", "HANDOVER_AHEAD_SKIP", False)


AHEAD_SKIP_CONF = 0.9  # with HANDOVER_AHEAD_SKIP=1, the k+1 confirm needs this, plus a yes for step k itself


def ahead_confirm_n() -> int:
    """HANDOVER_AHEAD_CONFIRM_N: confirmed ahead verdicts in a row, each pointing at step k+1, that move the step
    to k+1 (reason ahead_confirm). 0 turns the recovery off."""
    return int(config.get("HANDOVER_AHEAD_CONFIRM_N"))  # type: ignore[arg-type]


def ahead_confirm_conf() -> float:
    """HANDOVER_AHEAD_CONFIRM_CONF: compare confidence an ahead verdict needs to count toward ahead_confirm."""
    return float(config.get("HANDOVER_AHEAD_CONFIRM_CONF"))  # type: ignore[arg-type]


def understand_override_n() -> int:
    """HANDOVER_UNDERSTAND_OVERRIDE_N: confident check yes answers in a row, while understanding does not say yes,
    after which the check's verdict is accepted (reason understand_override). 0 turns the fallback off."""
    return int(config.get("HANDOVER_UNDERSTAND_OVERRIDE_N"))  # type: ignore[arg-type]


def understand_override_conf() -> float:
    """HANDOVER_UNDERSTAND_OVERRIDE_CONF: confidence a check yes needs to count toward understand_override."""
    return float(config.get("HANDOVER_UNDERSTAND_OVERRIDE_CONF"))  # type: ignore[arg-type]


# Advances the camera made. Clients get reason "camera" for all of them (CONTRACT 7: camera|button|voice, and the
# chime plays); events, logs and metrics keep the specific reason, so Databricks can tell a recovery from a pass.
CAMERA_REASONS = ("camera", "ahead_confirm", "understand_override")

_mode_cache: tuple = (None, 0.0, "")  # (env key, when, mode)


def understanding_on() -> bool:
    """HANDOVER_UNDERSTAND: run real-time understanding beside the check; advance needs both to say yes."""
    return bool(config.get("HANDOVER_UNDERSTAND"))


def live_mistakes_on() -> bool:
    """HANDOVER_LIVE_MISTAKES: show advisory live mistakes from understanding."""
    return bool(config.get("HANDOVER_LIVE_MISTAKES"))


def combine(res: check.CheckResult, und: check.CheckResult) -> check.CheckResult:
    """The verdict the debounce sees when understanding runs: yes only when both say yes (confidence the lower
    of the two, reason from the check, else from understanding). Otherwise the more cautious answer: no
    before unsure. Latency is the slower call; errors stay the check's."""
    ms = max(res.latency_ms, und.latency_ms)
    if res.done == "yes" and und.done == "yes":
        return check.CheckResult("yes", min(res.confidence, und.confidence), ms, res.reason or und.reason, res.error)
    pick = res if res.done == "no" else und if und.done == "no" else res if res.done != "yes" else und
    return check.CheckResult(pick.done, pick.confidence, ms, res.reason or und.reason, res.error)


def ui_fps() -> float:
    """HANDOVER_UI_FPS: live frames forwarded to each viewer per second, at most."""
    return float(config.get("HANDOVER_UI_FPS"))  # type: ignore[arg-type]


CHECK_INTERVAL_RANGE = (float(config.tunable("HANDOVER_CHECK_INTERVAL_S").min or 0.2),
                        float(config.tunable("HANDOVER_CHECK_INTERVAL_S").max or 10))  # seconds, from the registry


def clamp_check_interval(seconds: float) -> float:
    lo, hi = CHECK_INTERVAL_RANGE
    return min(hi, max(lo, float(seconds)))


def check_offer_interval(configured: float, urgent: bool) -> float:
    """Cadence for the next model offer.

    Normal observation stays at the configured budget. Once a pass is being confirmed—or the bounded second
    pipeline slot is already justified by a settled motion—we use a short lane so the user is not left holding a
    completed step for the remainder of a long check interval. `max_inflight` and the debounce still cap work.
    """
    return min(configured, FAST_CONFIRM_INTERVAL) if urgent else configured


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}  # start-of-frame markers


def jpeg_size(data: bytes) -> Optional[tuple[int, int]]:
    """(width, height) from the JPEG's start-of-frame header, without decoding; None when it cannot be read.
    Walks the marker segments only, so it costs microseconds even on a large frame."""
    if data[:2] != b"\xff\xd8":
        return None
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD8)):  # markers without a length
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # end of image, or entropy-coded data starts before any frame header
            return None
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            return None
        if marker in _SOF:
            if i + 9 > n:
                return None
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return (width, height) if width and height else None
        i += 2 + length
    return None


def check_mode() -> str:
    """Who answers the live check right now: "mock", "claude" or "gemini". The provenance label in state,
    events, mistakes and logs. Cached for 2 s because the provider lookup may read <repo>/.env."""
    global _mode_cache
    key = tuple(os.environ.get(k) for k in ("HANDOVER_CHECK", "HANDOVER_CHECK_PROVIDER", "ANTHROPIC_API_KEY"))
    now = time.monotonic()
    if _mode_cache[0] != key or now - _mode_cache[1] > 2.0:
        _mode_cache = (key, now, "mock" if check.is_mock() else check.provider())
    return _mode_cache[2]


class FrameDebouncer:
    """Debounce over results keyed by frame order, so checks running at once can finish in any order.

    Advances when the newest n results by frame (each from a different frame) are confident yes answers. A late
    answer for an older frame never outweighs a newer one. Fast path: a single yes at fast_conf or more that
    named no difference (reason None) on the newest frame answered so far advances alone. n and min_conf are
    the HANDOVER_DEBOUNCE_N and HANDOVER_MIN_CONF values check.Debouncer reads.
    """

    def __init__(self) -> None:
        base = check.Debouncer()
        self.n, self.min_conf = base.n, base.min_conf
        self.results: dict[int, bool] = {}  # frame seq -> confident yes

    def feed(self, seq: int, done: str, confidence: float, reason: Optional[str] = None) -> bool:
        """Record the answer for frame `seq`. True when the step should advance (and resets)."""
        passed = done == "yes" and confidence >= self.min_conf
        self.results[seq] = passed
        newest = sorted(self.results)[-self.n:]
        fast = (passed and reason is None and seq == newest[-1] and fast_path()
                and confidence >= max(fast_conf(), self.min_conf))
        if fast or (len(newest) == self.n and all(self.results[s] for s in newest)):
            self.reset()
            return True
        return False

    @property
    def count(self) -> int:
        """Confident yes answers in a row, counting back from the newest frame answered."""
        out = 0
        for seq in sorted(self.results, reverse=True):
            if not self.results[seq]:
                break
            out += 1
        return out

    def reset(self) -> None:
        self.results.clear()


@dataclass
class StepStats:
    """Small, frame-free aggregates for one step in one run."""

    entries: int = 0
    checks: int = 0
    yes: int = 0
    no: int = 0
    unsure: int = 0
    errors: int = 0
    latency_total_ms: int = 0
    latency_max_ms: int = 0
    mistakes: int = 0


@dataclass
class RunStats:
    """One pass through a lesson, from select_lesson to done, for the run events."""

    run_id: str
    started: float
    camera_steps: int = 0  # forward step moves by the camera
    manual_steps: int = 0  # forward step moves by button or voice
    mistakes: int = 0
    done_sent: bool = False
    camera_connections: int = 0
    camera_disconnects: int = 0
    camera_sources: set[str] = field(default_factory=set)
    steps: dict[int, StepStats] = field(default_factory=dict)

    def for_step(self, step: int) -> StepStats:
        return self.steps.setdefault(step, StepStats())

    def totals(self) -> dict[str, Any]:
        values = list(self.steps.values())
        checks = sum(s.checks for s in values)
        latency = sum(s.latency_total_ms for s in values)
        return {
            "checks": checks,
            "checks_yes": sum(s.yes for s in values),
            "checks_no": sum(s.no for s in values),
            "checks_unsure": sum(s.unsure for s in values),
            "check_errors": sum(s.errors for s in values),
            "check_latency_avg_ms": round(latency / checks, 1) if checks else None,
            "check_latency_max_ms": max((s.latency_max_ms for s in values), default=0) or None,
            "camera_connections": self.camera_connections,
            "camera_disconnects": self.camera_disconnects,
            "camera_sources": sorted(self.camera_sources),
        }


@dataclass
class CheckJob:
    """One check about to run: the step, its reference (and the previous step's), and the newest gated frame."""

    index: int
    question: str
    ref: bytes
    frame: bytes
    version: int
    prev_ref: Optional[bytes] = None
    seq: int = 0  # frame number, so answers from checks running at once are put back in frame order
    run_id: Optional[str] = None  # binds a late result to the run that offered its frame


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
        self.debouncer = FrameDebouncer()
        self.gate = gate.MotionGate()
        self.breaker = check.Breaker()
        self.watch = mistake.MistakeWatch()
        self.rubric: Optional[dict] = None  # understand.load_rubric for the lesson; None when missing or stale
        self.key_cache: dict[tuple, list[bytes]] = {}  # (lesson_id, n) -> START, MID, DONE keyframes
        self.tracker = understand.MistakeTracker()  # live mistakes (HANDOVER_LIVE_MISTAKES)
        self.progress: Optional[float] = None  # from understanding, 0..1
        self.stage: Optional[dict] = None  # from understanding, {"index", "count", "label"}
        self.offline_seen: tuple = (False, None)  # (check_offline, reason) last sent to clients
        self.last_broadcast: Optional[dict] = None  # the last state broadcast, see broadcast_state
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
        self.inflight: set[asyncio.Task] = set()  # running checks, at most max_inflight(), on different frames
        self.spare_slots = 0  # extra checks a gate-triggered check may still start on the next settled frames
        self.mistake_task: Optional[asyncio.Task] = None  # the one running mistake compare (or mock confirm)
        self.mock_tick_at = 0.0  # last time the mock mistake hook was looked at
        self.ahead_streak = 0  # confirmed ahead verdicts in a row on this step (HANDOVER_AHEAD_CONFIRM_N)
        self.override_streak = 0  # check yes, understanding not yes, in a row (HANDOVER_UNDERSTAND_OVERRIDE_N)
        self.override_since = 0.0  # when that streak started (it must also span OVERRIDE_MIN_SECONDS)
        self.gated_at = -1e9  # when the motion gate last looked at a frame (GATE_MIN_INTERVAL)
        self.check_interval_override: Optional[float] = None  # set_check_interval from /ws/ui; None = env value
        self.offered_at = -1e9  # when a frame was last offered to the check model (check_interval_s)
        self.offer_wake_booked = False
        self.gate_wake_booked = False
        self.auto_advance_held = False
        self.observation_phase_sent: Optional[str] = None
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
        """(check_offline, check_offline_reason). Mock mode never calls a model, so it is never offline."""
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
            "check_mode": check_mode(),
            "next_clip": self.next_clip(),
            "progress": self.progress,
            "stage": self.stage,
            "run_id": self.run_id(),
            "check_interval_s": self.check_interval_s(),
            "ui_fps": int(ui_fps()),
            "held": self.auto_advance_held,
            "observation": self.observation(),
        }

    def observation(self) -> dict:
        """Frame-free feedback explaining what the live checker is doing right now."""
        if self.lesson is None:
            phase = "idle"
        elif self.cameras == 0:
            phase = "waiting_camera"
        elif self.active is None or self.frame is None:
            phase = "waiting_frame"
        elif self.verified:
            phase = "verified"
        elif any(not task.done() for task in self.inflight):
            phase = "checking"
        elif not self.gate.settled:
            phase = "moving"
        elif self.gate_wake_booked:
            phase = "settling"
        else:
            phase = "watching"
        cam = self.active
        age = round(max(0.0, time.monotonic() - cam.last_frame) * 1000) if cam and cam.last_frame else None
        return {"phase": phase, "frame_age_ms": age, "camera_fps": cam.received_fps() if cam else None}

    def broadcast_observation_if_changed(self) -> None:
        phase = self.observation()["phase"]
        if phase == self.observation_phase_sent:
            return
        self.observation_phase_sent = phase
        self.broadcast_state()

    def check_interval_s(self) -> float:
        """Seconds between frames offered to the check model, at least: the runtime value from
        set_check_interval, else HANDOVER_CHECK_INTERVAL_S. The camera may send 15 fps for the live view; the
        model still sees at most one frame per interval (the motion gate and heartbeat apply on top)."""
        if self.check_interval_override is not None:
            return self.check_interval_override
        return float(config.get("HANDOVER_CHECK_INTERVAL_S"))  # type: ignore[arg-type]

    def set_check_interval(self, seconds: float) -> None:
        """set_check_interval from /ws/ui: clamped to CHECK_INTERVAL_RANGE, applied at once, state broadcast."""
        self.check_interval_override = clamp_check_interval(seconds)
        log.info("check interval set to %.2f s", self.check_interval_override)
        self.frame_event.set()  # a shorter interval may allow a check right now
        self.broadcast_state()

    def run_id(self) -> Optional[str]:
        """The run the Done screen scores (GET /api/runs/{run_id}/score): the id databricks.start_run returned,
        else the engine's own id for this select. None with no run."""
        if self.run is None:
            return None
        return DB_RUN_IDS.get(self.run.run_id, self.run.run_id)

    def next_clip(self) -> Optional[str]:
        """The next step's clip (relative path) once this step has one confident yes, so the web can preload it
        before the advance. None otherwise, and on the last step."""
        if self.done or not (self.verified or self.debouncer.count > 0):
            return None
        steps = self.steps
        k = self.step + 1
        if not 0 < k < len(steps):
            return None
        clip = steps[k].get("clip") or f"clips/{k + 1:02d}.mp4"
        return clip if isinstance(clip, str) else None

    def broadcast(self, msg: Any) -> None:
        """To every UI client; text messages also go to every camera that said hello."""
        for c in list(self.ui):
            c.push(msg)
        if not isinstance(msg, bytes):
            for cam in self.cams:
                if cam.said_hello:
                    cam.push(msg)

    def broadcast_state(self) -> None:
        """Always sends: commands such as select_lesson get their state even when nothing changed."""
        self.last_broadcast = self.state()
        self.observation_phase_sent = self.last_broadcast["observation"]["phase"]
        self.broadcast(self.last_broadcast)

    def broadcast_state_if_changed(self) -> None:
        """For check results: sends state only when it differs from the last one broadcast, so two checks
        running at once that give the same answer produce one state, not two."""
        st = self.state()
        if st == self.last_broadcast:
            metrics["states_unchanged_skipped"] += 1
            return
        self.last_broadcast = st
        self.observation_phase_sent = st["observation"]["phase"]
        self.broadcast(st)

    def sync_offline(self) -> bool:
        """Records the breaker state; True when it changed since clients last heard it."""
        now = self.offline()
        changed, self.offline_seen = now != self.offline_seen, now
        if changed:
            self.emit("breaker", open=now[0], reason=now[1])
        return changed

    def open_breaker_if_no_key(self) -> None:
        """In claude or gemini mode without a key, show "Checks off" from the start instead of after the first frame."""
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
        fields, _ = analytics_privacy.scrub_fields(fields)
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
        entry = None
        if self.run is not None:
            stats = self.run.for_step(self.step)
            stats.entries += 1
            entry = stats.entries
            if self.active is not None and self.active.source != "unknown":
                self.run.camera_sources.add(self.active.source)
        self.emit("step_enter", step=self.step, check_type=cur.get("check_type", "camera"), expert_seconds=expert,
                  entry=entry, camera_source=self.active.source if self.active else None,
                  camera_connected=self.cameras > 0)

    def snapshot(self) -> dict:
        """Health and counters in one dict, for a future /api/health or /api/metrics route."""
        offline, reason = self.offline()
        return {"uptime_s": round(time.monotonic() - self.started, 1), "lesson_id": self.lesson_id,
                "step": self.step, "total": len(self.steps), "status": self.status(), "cameras": self.cameras,
                "ui_clients": len(self.ui), "check_mode": check_mode(),
                "check_offline": offline, "check_offline_reason": reason, "gate": self.gate.stats,
                "counters": dict(metrics)}

    # ---- step changes

    def _enter_step(self) -> None:
        self.version += 1
        self.debouncer.reset()
        self.spare_slots = 0
        self.gate.reset()
        self.watch.reset()
        self.ahead_streak = 0
        self.override_streak = 0
        self.override_since = 0.0
        self.checking = False
        self.verified = False
        self.last_check = None
        self.mistake = None
        self.progress = None
        self.stage = None
        self.auto_advance_held = False
        self.observation_phase_sent = None
        self.tracker.start_step(self.step, self.understand_entry(self.step))
        self.step_started = time.monotonic()
        self.checked_seq = self.frame_seq  # never judge a new step with a frame taken before it began

    def load_rubric(self) -> None:
        """The lesson's rubric.json when understanding is on; None when missing or stale (after a recut)."""
        self.key_cache.clear()
        self.rubric = None
        if self.lesson_id and self.lesson is not None and understanding_on():
            self.rubric = understand.load_rubric(LESSONS / self.lesson_id, self.lesson)

    def understand_entry(self, index: int) -> Optional[dict]:
        """Rubric entry of step `index` (0-based) when understanding is on, else None."""
        if self.rubric is None or not understanding_on() or not 0 <= index < len(self.steps):
            return None
        n = self.steps[index].get("n", index + 1)
        return understand.step_entry(self.rubric, n)

    def keyframes(self, entry: dict) -> Optional[list[bytes]]:
        """START, MID, DONE keyframes of a rubric entry, cached like ref_bytes; None when a file is missing."""
        key = (self.lesson_id, entry.get("n"))
        if key not in self.key_cache:
            try:
                frames = understand.read_keyframes(LESSONS / str(self.lesson_id), entry)
            except OSError:
                if key not in self.missing_ref_logged:
                    log.warning("understanding keyframes missing for step %s", entry.get("n"))
                    self.missing_ref_logged.add(key)
                return None
            if not frames:
                return None
            self.key_cache[key] = frames
        return self.key_cache[key]

    def select(self, lesson_id: str, learner: Optional[str] = None) -> None:
        """Load a lesson at step 0 and start a run. learner: the signed-in user's id, or None (anonymous)."""
        previous_lesson = self.lesson_id
        previous_done = self.done
        lesson = read_lesson(lesson_id)  # validate before an invalid selection can interrupt the current run
        if self.run is not None:
            self.stop_run("restarted" if previous_lesson == lesson_id else "switched")
        self.lesson_id, self.lesson = lesson_id, lesson
        self.refresh_rev()
        self.step, self.done = 0, False
        self.ref_cache.clear()
        self.load_rubric()
        self._enter_step()
        self.run = RunStats(uuid.uuid4().hex, time.monotonic())
        if self.active is not None:
            self.run.camera_connections = 1
            if self.active.source != "unknown":
                self.run.camera_sources.add(self.active.source)
        log.info("selected lesson %s (%d steps)", lesson_id, len(self.steps))
        # source and check_mode let dashboards leave out mock and replay runs; learner tags per-user progress
        attempt_kind = ("replay" if previous_lesson == lesson_id and previous_done else
                        "restart" if previous_lesson == lesson_id else "new")
        now = time.monotonic()
        self.emit("run_start", total=len(self.steps), learner=learner, attempt_kind=attempt_kind,
                  source=self.active.source if self.active else None,
                  platform=self.active.platform if self.active else None,
                  camera_connect_age_ms=(round((now - self.active.connected_at) * 1000)
                                         if self.active else None),
                  camera_ready=self.active.first_frame_at > 0 if self.active else False,
                  camera_first_frame_age_ms=(round((now - self.active.first_frame_at) * 1000)
                                             if self.active and self.active.first_frame_at else None),
                  check_mode=check_mode(), check_interval_s=self.check_interval_s())
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
        self.load_rubric()
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
        self.unload("deleted")
        log.info("cleared deleted lesson %s", lesson_id)

    def end_lesson(self) -> None:
        """A learner pressed End: stop the run (run_stop, reason "ended"), unload the lesson so no more checks
        run, and tell every client (state with no lesson). A no-op when nothing is loaded."""
        if self.lesson is None:
            return
        log.info("lesson %s ended by the learner", self.lesson_id)
        self.unload("ended")

    def unload(self, why: str) -> None:
        self.stop_run(why)
        self.lesson_id, self.lesson = None, None
        self.step, self.done = 0, False
        self.ref_cache.clear()
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
        step_seconds = round(time.monotonic() - self.step_started, 3)
        step_stats = self.run.steps.get(frm) if self.run is not None else None
        check_avg = (round(step_stats.latency_total_ms / step_stats.checks, 1)
                     if step_stats is not None and step_stats.checks else None)
        if to >= total:
            self.done = True
            self.step = max(0, total - 1)
        else:
            self.done = False
            self.step = to
        self._enter_step()
        log.info("step %d -> %d (%s)", frm, to, reason)
        metrics[f"advances_{reason}"] += 1
        wire = "camera" if reason in CAMERA_REASONS else reason
        self.broadcast({"type": "advance", "from": frm, "to": to, "reason": wire})
        self.emit("advance", **{"from": frm, "to": to, "reason": reason, "step_seconds": step_seconds,
                  "checks_on_step": step_stats.checks if step_stats else 0,
                  "check_latency_avg_ms": check_avg,
                  "check_errors_on_step": step_stats.errors if step_stats else 0,
                  "mistakes_on_step": step_stats.mistakes if step_stats else 0,
                  "camera_source": self.active.source if self.active else None})
        self._record_run(frm, to, reason)
        self.broadcast_state()

    def stop_run(self, why: str) -> None:
        """End an unfinished run without a run_done (lesson deleted, hub shutting down)."""
        if self.run is not None and not self.run.done_sent:
            self.emit("run_stop", reason=why, elapsed_seconds=round(time.monotonic() - self.run.started, 3),
                      current_step=self.position(), total=len(self.steps),
                      completion_ratio=round(self.position() / max(1, len(self.steps)), 3),
                      **self.run.totals())
        self.run = None

    def _record_run(self, frm: int, to: int, reason: str) -> None:
        """Count forward moves for the run, then emit step_enter, or run_done the first time the run finishes."""
        run = self.run
        if run is not None and to > frm:
            if reason in CAMERA_REASONS:
                run.camera_steps += to - frm
            else:
                run.manual_steps += to - frm
        if not self.done:
            self._emit_step_enter()
        elif run is not None and not run.done_sent:
            run.done_sent = True
            self.emit("run_done", total_seconds=round(time.monotonic() - run.started, 3),
                      camera_steps=run.camera_steps, manual_steps=run.manual_steps, mistakes=run.mistakes,
                      total=len(self.steps), completion_ratio=1.0, **run.totals())

    def position(self) -> int:
        return len(self.steps) if self.done else self.step

    def dismiss_mistake(self) -> None:
        self.tracker.reset()
        if self.mistake is not None:
            self.mistake = None
            self.broadcast_state()

    def set_hold(self, held: bool) -> None:
        """Pause camera auto-advance; manual navigation remains available and clears hold on the new step."""
        if self.lesson is None or held == self.auto_advance_held:
            return
        self.auto_advance_held = held
        self.emit("auto_advance_hold", held=held, step=self.step)
        if not held and self.verified:
            self.go(self.position() + 1, "camera")
        else:
            self.broadcast_state()

    # ---- cameras

    def add_camera(self, ws: WebSocket, now: float, label: str = "-") -> Camera:
        """A new connection is the newest camera, so it becomes active."""
        taken = {c.number for c in self.cams}
        cam = Camera(ws, next(n for n in range(1, len(taken) + 2) if n not in taken), now, label)
        self.cams.append(cam)
        self.cameras = len(self.cams)
        self._set_active(cam)
        if self.run is not None:
            self.run.camera_connections += 1
        self.emit("camera_connect", camera_number=cam.number, camera_count=self.cameras)
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
        if self._drop(cam, "socket_closed"):
            log.info("camera disconnected: %s (%d)", cam.name, self.cameras)
            self.broadcast_state()

    def _drop(self, cam: Camera, reason: str = "removed") -> bool:
        if cam not in self.cams:
            return False
        was_active = self.active is cam
        connected_s = round(max(0.0, time.monotonic() - cam.connected_at), 3)
        self._cancel_announce(cam)
        self.cams.remove(cam)
        self.cameras = len(self.cams)
        if self.active is cam:
            self.active = None
            heir = max(self.cams, key=lambda c: (c.last_frame, c.connected_at), default=None)
            if heir is not None:
                self._set_active(heir)
        if self.run is not None:
            self.run.camera_disconnects += 1
        self.emit("camera_disconnect", camera_number=cam.number, source=cam.source, platform=cam.platform,
                  reason=reason, active=was_active, connected_seconds=connected_s,
                  had_frame=cam.first_frame_at > 0, camera_count=self.cameras)
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
        if cam.said_hello or cam.first_frame_at:
            self.emit("camera_active", camera_number=cam.number, source=cam.source, platform=cam.platform,
                      camera_count=self.cameras)
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
        cam.hello_at = time.monotonic()
        self._cancel_announce(cam)  # this hello's state broadcast below is the announcement
        replaced = [c for c in self.cams if c is not cam and cam.device_id and c.device_id == cam.device_id]
        for old in replaced:
            self._drop(old, "replaced")
        self._set_active(cam)
        if self.run is not None and cam.source != "unknown":
            self.run.camera_sources.add(cam.source)
        self.emit("camera_hello", camera_number=cam.number, source=cam.source, platform=cam.platform,
                  connect_latency_ms=round((cam.hello_at - cam.connected_at) * 1000),
                  replaced=len(replaced), active=self.active is cam, camera_count=self.cameras)
        log.info("hello: %s (%s, %s)", cam.name, cam.platform, cam.source)
        self.broadcast_state()
        return replaced

    def camera_frame(self, cam: Camera, data: bytes, now: float) -> None:
        """A binary message from a camera. Only the active camera's JPEGs are judged and forwarded. An active
        camera with no frame for ACTIVE_IDLE_SECONDS loses to one that is sending frames (this one, right now)."""
        if len(data) > MAX_FRAME_BYTES or data[:2] != b"\xff\xd8":
            metrics["frames_ignored"] += 1
            return
        if now - cam.last_frame < config.env_float("HANDOVER_MIN_FRAME_GAP", 0.04, 0, 5):
            metrics["frames_too_fast"] += 1
            return
        first = cam.first_frame_at == 0
        cam.record_frame(now)
        if first:
            cam.first_frame_at = now
            if self.run is not None and cam.source != "unknown":
                self.run.camera_sources.add(cam.source)
            self.emit("camera_first_frame", camera_number=cam.number, source=cam.source, platform=cam.platform,
                      connect_latency_ms=round((now - cam.connected_at) * 1000),
                      hello_to_frame_ms=round((now - cam.hello_at) * 1000) if cam.hello_at else None,
                      active=self.active is cam)
        metrics["frames_in"] += 1
        if self.active is not cam and (self.active is None or self.idle_for(self.active, now) >= ACTIVE_IDLE_SECONDS):
            self._set_active(cam)
            log.info("active camera: %s", cam.name)
            self.broadcast_state()
        if self.active is cam:
            self.on_frame(data)

    # ---- frames

    def on_frame(self, data: bytes) -> None:
        """A frame from the active camera. Held in memory only; frames never touch disk."""
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
                    self.inflight = {t for t in self.inflight if not t.done()}
                    if len(self.inflight) < max_inflight():
                        job = self._next_job()
                        if job is not None:
                            self.inflight.add(asyncio.create_task(self._check_task(job)))
                            self.broadcast_observation_if_changed()
                except Exception:  # one bad frame or lesson must not stop checking for the session
                    log.exception("check loop iteration failed")
        finally:
            for task in (*self.inflight, self.mistake_task):
                if task is not None:
                    task.cancel()

    async def _gate_newest(self) -> None:
        if self.frame is None or self.frame_seq == self.gated_seq:
            return
        # The gate decodes each frame it sees. Cameras may send 15 fps for a smooth picture, so the gate looks at
        # the newest frame at most every GATE_MIN_INTERVAL; a wake-up is booked so the last frame of a burst is
        # still gated. With the gate off nothing is decoded and every frame goes through.
        now = time.monotonic()
        if self.gate.enabled:
            wait = GATE_MIN_INTERVAL - (now - self.gated_at)
            if wait > 0:
                if not self.gate_wake_booked:
                    self.gate_wake_booked = True
                    asyncio.get_running_loop().call_later(wait, self._gate_wake)
                return
        self.gated_at = now
        metrics["frames_gated"] += 1
        frame, seq = self.frame, self.frame_seq
        wanted = await asyncio.to_thread(self.gate.observe, frame, time.monotonic())
        self.gated_frame, self.gated_seq, self.frame_wanted = frame, seq, wanted
        self.broadcast_observation_if_changed()

    def _gate_wake(self) -> None:
        self.gate_wake_booked = False
        self.frame_event.set()

    def _offer_wake(self) -> None:
        self.offer_wake_booked = False
        self.frame_event.set()

    async def _check_task(self, job: CheckJob) -> None:
        try:
            await self._run_check(job)
        except Exception:  # keep checking later frames; nothing awaits this task, so log here
            log.exception("check task crashed")
        finally:
            self.frame_event.set()  # frames gated meanwhile may be ready for the next check
            self.broadcast_observation_if_changed()

    def _next_job(self) -> Optional[CheckJob]:
        """The check to run now, or None. Order matters: the breaker's trial call is spent last."""
        cur = self.current()
        if cur is None or cur.get("check_type", "camera") != "camera" or self.verified:
            return None
        frame = self.gated_frame
        # Fast confirm: after a yes, the next still frame is checked at once, even though the gate sees no
        # change since the last check; otherwise the confirming yes would wait for the 6 s heartbeat.
        # The understand_override count (check yes, understanding no) confirms the same way.
        confirming = (self.debouncer.count > 0 or self.override_streak > 0) and self.gate.settled
        # Pipelined confirm: while a gate-triggered check runs, the next settled frame starts the confirming
        # check right away instead of after the first answer. At most max_inflight() - 1 extra checks per gate
        # trigger (change or heartbeat); a still scene that keeps answering no gets no more than that.
        running = sum(1 for t in self.inflight if not t.done())
        pipelined = running > 0 and self.spare_slots > 0 and self.gate.settled
        if running >= self.debouncer.n - self.debouncer.count:
            confirming = pipelined = False  # the checks already running can finish the debounce; no extra call
        if frame is None or self.gated_seq <= self.checked_seq or self.cameras == 0:
            return None
        if not (self.frame_wanted or confirming or pipelined):
            return None
        ref = self.ref_bytes(self.step)
        if ref is None:
            return None
        now = time.monotonic()
        # Check cadence: at most one frame per check_interval_s goes to the model, whatever the camera rate. A
        # wake-up is booked so a frame held back here is looked at again when the interval is over.
        urgent = confirming or pipelined
        interval = check_offer_interval(self.check_interval_s(), urgent)
        wait = interval - (now - self.offered_at)
        if wait > 0:
            metrics["checks_held_interval"] += 1
            if not self.offer_wake_booked:
                self.offer_wake_booked = True
                asyncio.get_running_loop().call_later(wait, self._offer_wake)
            return None
        allowed = self.breaker.allow(now)
        if self.sync_offline():
            self.broadcast_state()
        if not allowed:
            return None
        if self.frame_wanted:
            self.spare_slots = max_inflight() - 1
        elif pipelined and not confirming:
            self.spare_slots -= 1
        self.gate.mark_checked(now)
        self.offered_at = now
        self.checked_seq = self.gated_seq
        if urgent and interval < self.check_interval_s():
            metrics["checks_fast_confirm"] += 1
        question = cur.get("check_question") or "Is this step finished?"
        prev_ref = self.ref_bytes(self.step - 1) if self.step > 0 else None
        return CheckJob(self.step, question, ref, frame, self.version, prev_ref, self.gated_seq,
                        self.run.run_id if self.run else None)

    async def _run_check(self, job: CheckJob) -> None:
        # Checks run back to back, so status stays "watching" unless one is slow; flipping to "checking"
        # for every frame made the UI flap twice a second.
        show = asyncio.get_running_loop().call_later(CHECKING_SHOW_AFTER, self._show_checking, job.version)
        entry = self.understand_entry(job.index)
        keys = self.keyframes(entry) if entry is not None else None
        und: Optional[understand.Understanding] = None
        try:
            if keys:  # understanding on and a rubric entry: both calls on the same frame, at once
                res, und = await asyncio.gather(
                    self._safe_check(job),
                    self._safe_understand(entry, keys, job))
            else:
                res = await self._safe_check(job)
        finally:
            show.cancel()
        self.breaker.record(res, time.monotonic())
        if und is not None:
            self.breaker.record(und, time.monotonic())
        offline_changed = self.sync_offline()
        self._record_check(job, res)
        override = False
        if und is not None:
            if job.version == self.version and not self.verified:
                override = self._override_due(res, und)
            res = combine(res, und)
        if job.version != self.version or self.verified:
            if offline_changed:
                self.broadcast_state()
            return  # step changed (or already verified) while the check was running; the result is ignored
        shown = self.checking
        self.checking = False
        self.last_check = res.as_dict()
        cleared = res.done == "yes" and self.mistake is not None
        if cleared:
            self.mistake = None
        if und is not None:
            cleared = self._apply_understanding(und) or cleared
        if self.debouncer.feed(job.seq, res.done, res.confidence, res.reason):
            await self._verify_and_advance(job.version)
            return
        if override:
            log.info("understand_override on step %d: %d check yes answers in a row while understanding said no",
                     job.index, self.override_streak)
            metrics["understand_overrides"] += 1
            await self._verify_and_advance(job.version, "understand_override")
            return
        # Compared with what clients last got, not with the moment this check started: with checks running at
        # once, an older start would make every answer look new.
        if shown or cleared or offline_changed or self._check_signature() != self._signature_of(self.last_broadcast):
            self.broadcast_state_if_changed()  # only when the answer changed, not on every identical result
        await self._after_result(job, res.done)

    async def _safe_check(self, job: CheckJob) -> check.CheckResult:
        try:
            return await check.check_frame(job.ref, job.frame, job.question, step_started_at=self.step_started,
                                           prev_ref=job.prev_ref)
        except Exception:  # check_frame should never raise; keep the loop alive regardless
            log.exception("check crashed")
            return check.CheckResult("unsure", 0.0, 0, error="error")

    async def _safe_understand(self, entry: dict, keys: list[bytes], job: CheckJob) -> "understand.Understanding":
        try:
            return await understand.understand_frame(entry, keys, job.frame, job.prev_ref,
                                                     step_started_at=self.step_started)
        except Exception:  # understand_frame should never raise either
            log.exception("understanding crashed")
            return understand.Understanding("unsure", 0.0, 0, error="error")

    def _override_due(self, res: check.CheckResult, und: check.CheckResult) -> bool:
        """Bounded fallback for HANDOVER_UNDERSTAND=1: count confident check yes answers (at
        HANDOVER_UNDERSTAND_OVERRIDE_CONF) given while understanding did not say yes. Any check answer that is not
        such a yes resets the count; a result where both say yes leaves it alone (the debounce handles that one).
        True once the count reaches HANDOVER_UNDERSTAND_OVERRIDE_N (0 never) AND the streak spans at least
        OVERRIDE_MIN_SECONDS, so a confident understanding "no" costs several seconds of agreement, not one extra
        check."""
        need = understand_override_n()
        if res.done != "yes" or res.confidence < understand_override_conf():
            self.override_streak = 0
            return False
        if und.done == "yes":
            return False
        now = time.monotonic()
        if self.override_streak == 0:
            self.override_since = now
        self.override_streak += 1
        return need > 0 and self.override_streak >= need and now - self.override_since >= OVERRIDE_MIN_SECONDS

    def _apply_understanding(self, und: "understand.Understanding") -> bool:
        """progress, stage and (with HANDOVER_LIVE_MISTAKES) live mistakes from one understanding result.
        True when state.mistake changed. A live mistake is advisory and never moves the step."""
        if und.error is None:
            metrics["understand_results"] += 1
            stages = (self.understand_entry(self.step) or {}).get("stages") or []
            self.progress = round(max(0.0, min(1.0, und.progress)), 3)
            if 0 <= und.stage < len(stages):
                self.stage = {"index": und.stage, "count": len(stages), "label": stages[und.stage].get("label") or ""}
            else:
                self.stage = None
        if not live_mistakes_on():
            return False
        self.tracker.source = check_mode()
        msg = self.tracker.feed(und, time.monotonic())
        if msg is not None:
            self.mistake = {k: v for k, v in msg.items() if k != "type"}
            metrics["live_mistakes"] += 1
            self.emit("mistake", step=msg["step"], mistake_kind="live", label=msg["label"],
                      confidence=msg["confidence"], source=msg["source"])
            self.broadcast(msg)
            return True
        if self.mistake is not None and self.mistake.get("kind") == "live" and self.tracker.active is None:
            self.mistake = None
            return True
        return False

    def _record_check(self, job: CheckJob, res: check.CheckResult) -> None:
        metrics["checks"] += 1
        if res.error:
            metrics[f"check_errors_{res.error}"] += 1
        log.debug("check step %d: %s %.2f %d ms, gate %s", job.index, res.done, res.confidence, res.latency_ms,
                  self.gate.stats)
        model = "mock" if check.is_mock() else check.active_model()
        effective_run_id = job.run_id if job.run_id is not None else (self.run.run_id if self.run else None)
        stale = job.version != self.version or (job.run_id is not None and
                                                (self.run is None or job.run_id != self.run.run_id))
        if not stale and self.run is not None:
            stats = self.run.for_step(job.index)
            stats.checks += 1
            if res.done == "yes": stats.yes += 1
            elif res.done == "no": stats.no += 1
            else: stats.unsure += 1
            stats.errors += res.error is not None
            stats.latency_total_ms += max(0, res.latency_ms)
            stats.latency_max_ms = max(stats.latency_max_ms, res.latency_ms)
        self.emit("check", run_id=effective_run_id, step=job.index, done=res.done,
                  confidence=round(res.confidence, 3),
                  latency_ms=res.latency_ms, reason=res.reason, model=model, gated=self.gate.enabled,
                  error_kind=res.error, stale=stale, camera_source=self.active.source if self.active else None,
                  frame_seq=job.seq)

    async def _verify_and_advance(self, version: int, reason: str = "camera") -> None:
        """verified (with next_clip) goes out at once, so the badge and the preload start now; the step moves
        after VERIFIED_HOLD. reason is one of CAMERA_REASONS."""
        self.verified = True
        self.checking = False
        self.broadcast_state()
        await asyncio.sleep(VERIFIED_HOLD)
        if version == self.version and not self.auto_advance_held:
            self.go(self.position() + 1, reason)

    def _show_checking(self, version: int) -> None:
        if version == self.version and not self.verified:
            self.checking = True
            self.broadcast_state()

    def _check_signature(self) -> tuple:
        lc = self.last_check or {}
        return (self.status(), lc.get("done"), lc.get("confidence"), lc.get("reason"), self.next_clip(),
                self.progress, self.stage)

    @staticmethod
    def _signature_of(st: Optional[dict]) -> tuple:
        """_check_signature of a state message already sent (None: nothing sent yet)."""
        if st is None:
            return (None,)
        lc = st.get("last_check") or {}
        return (st.get("status"), lc.get("done"), lc.get("confidence"), lc.get("reason"), st.get("next_clip"),
                st.get("progress"), st.get("stage"))

    # ---- mistake check

    async def _after_result(self, job: CheckJob, done: str) -> None:
        """Feed the mistake policy after a check that did not pass. A due compare runs as its own task (one at a
        time) so it never delays normal checks, or inline when HANDOVER_MISTAKE_PARALLEL=0.
        Mock mode never calls a model for this; its HANDOVER_MOCK_MISTAKE hook runs in _mock_tick instead."""
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
        verdict = await self._confirm_ahead(job)
        if verdict is not None and job.version == self.version:
            self._raise_mistake(found, skip=verdict == "skip")

    async def _compare_and_raise(self, job: CheckJob) -> None:
        match = await self._compare(job)
        if match is None or job.version != self.version:
            return
        found = self.watch.decide(job.index, len(self.steps), match.step, match.confidence, self.steps, check_mode())
        verdict: Optional[str] = "show"
        if found is not None and mistake.needs_confirmation(found):
            verdict = await self._confirm_ahead(job)
        if job.version != self.version:
            return
        confirmed_ahead = found is not None and mistake.needs_confirmation(found) and verdict is not None
        if verdict != "skip" and self._ahead_confirm_due(job, confirmed_ahead, match.confidence):
            return
        if found is not None and verdict is not None:
            self._raise_mistake(found, skip=verdict == "skip")

    def _ahead_confirm_due(self, job: CheckJob, confirmed_ahead: bool, confidence: float) -> bool:
        """Recovery after a missed advance. A confirmed ahead verdict for step k+1 (compare plus the k+1 check, see
        _confirm_ahead) at HANDOVER_AHEAD_CONFIRM_CONF or more counts; any other compare answer on this step
        (behind, same step, too unsure, unconfirmed) resets the count. When HANDOVER_AHEAD_CONFIRM_N verdicts in a
        row agree, the step moves to k+1, never further, with reason ahead_confirm. True when it moved."""
        need = ahead_confirm_n()
        own = self.last_check if job.index == self.step else None
        own_says_no = own is not None and own.get("done") == "no" and float(own.get("confidence") or 0) >= 0.8
        if not confirmed_ahead or confidence < ahead_confirm_conf() or own_says_no:
            # A confident "no" from this step's own check means step k was skipped, not missed: no recovery.
            self.ahead_streak = 0
            return False
        self.ahead_streak += 1
        if need <= 0 or self.ahead_streak < need or job.index != self.step or self.done or self.verified:
            return False
        log.info("ahead_confirm on step %d: %d ahead verdicts in a row for step %d", job.index,
                 self.ahead_streak, job.index + 1)
        metrics["ahead_confirms"] += 1
        self.go(job.index + 1, "ahead_confirm")
        return True

    async def _compare(self, job: CheckJob) -> Optional[check.MatchResult]:
        """One multiple-choice call over references k-1, k, k+1 (those that exist). None when it cannot run."""
        refs = []
        for i in (job.index - 1, job.index, job.index + 1):
            ref = self.ref_bytes(i)
            if ref is not None:
                refs.append((i, ref))
        if len(refs) < 2 or not self._breaker_allows():
            return None
        match = await check.compare_refs(job.frame, refs, None)  # neutral question: the step's own would bias it
        self._breaker_record(match)
        return None if match.error else match

    async def _confirm_ahead(self, job: CheckJob) -> Optional[str]:
        """What an ahead match may do: None (nothing), "show" (the banner only) or "skip" (banner, then k+2).

        The banner needs a normal check of step k+1 to say yes at AHEAD_CONFIRM_CONF. The skip also needs
        HANDOVER_AHEAD_SKIP=1, that check at AHEAD_SKIP_CONF, and a normal check of step k itself saying yes on
        the same frame, because the compare often calls a skipped step "ahead" (accuracy run: 15 of 23)."""
        k1 = job.index + 1
        if k1 >= len(self.steps):
            return None
        ref = self.ref_bytes(k1)
        if ref is None or not self._breaker_allows():
            return None
        question = self.steps[k1].get("check_question") or "Is this step finished?"
        # Mock: the HANDOVER_MOCK_MISTAKE hook stands in for the model's match, so its confirming check is told
        # the step finished long ago; with the real step timer it would repeat the "no" that triggered the hook.
        started = 0.0 if check.is_mock() else self.step_started
        skip = ahead_skip()
        checks = [check.check_frame(ref, job.frame, question, step_started_at=started, prev_ref=job.ref)]
        if skip:
            own_q = self.steps[job.index].get("check_question") or "Is this step finished?"
            prev = self.ref_bytes(job.index - 1) if job.index > 0 else None
            checks.append(check.check_frame(job.ref, job.frame, own_q, step_started_at=started, prev_ref=prev))
        results = await asyncio.gather(*checks)
        for res in results:
            self._breaker_record(res)
        nxt = results[0]
        if nxt.done != "yes" or nxt.confidence < mistake.AHEAD_CONFIRM_CONF:
            return None
        if skip:
            own = results[1]
            if (nxt.confidence >= AHEAD_SKIP_CONF and own.done == "yes"
                    and own.confidence >= self.debouncer.min_conf):
                return "skip"
        return "show"

    def _breaker_allows(self) -> bool:
        allowed = self.breaker.allow(time.monotonic())
        if self.sync_offline():
            self.broadcast_state()
        return allowed

    def _breaker_record(self, result: check.CheckResult | check.MatchResult) -> None:
        self.breaker.record(result, time.monotonic())
        if self.sync_offline():
            self.broadcast_state()

    def _raise_mistake(self, found: dict, skip: bool = False) -> None:
        """Send the mistake once and show it in state.mistake. Behind, and ahead without skip, stay until
        cleared and never move the step. An ahead with skip (see _confirm_ahead) goes to k+2 right after."""
        k = found["step"]
        if k != self.step or self.done:
            return
        log.info("mistake on step %d: %s (%s)", k, found["kind"], found["source"])
        metrics["mistakes"] += 1
        if self.run is not None:
            self.run.mistakes += 1
            self.run.for_step(k).mistakes += 1
        self.emit("mistake", step=k, mistake_kind=found["kind"], looks_like=found["looks_like"],
                  confidence=found["confidence"], source=found["source"])
        ahead = mistake.needs_confirmation(found)
        if ahead and k + 1 >= len(self.steps):
            return
        self.mistake = {key: value for key, value in found.items() if key != "type"}
        self.broadcast(found)
        self.broadcast_state()  # state.mistake holds it while shown; a skip to k+2 clears it
        if ahead and skip:
            self.go(k + 2, "camera")

    async def ui_frame_loop(self) -> None:
        """Forward the newest camera frame to UI clients, at most HANDOVER_UI_FPS per second. A frame whose long
        side is already UI_FRAME_MAX_SIDE or less (read from its header) goes out as is; a larger one is
        downscaled in a worker thread. Nothing queues: each viewer keeps only the newest frame (UIClient.push)
        and has its own sender, so a slow viewer drops frames without delaying the others."""
        log_ctx.set("engine")
        last = 0.0
        while True:
            await self.ui_frame_event.wait()
            self.ui_frame_event.clear()
            wait = 1.0 / ui_fps() - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
            frame = self.frame  # the newest, taken after the wait
            if frame is None or not self.ui:
                continue
            last = time.monotonic()
            size = jpeg_size(frame)
            if size is not None and max(size) <= UI_FRAME_MAX_SIDE:
                metrics["ui_frames_passthrough"] += 1
                self.broadcast(frame)
                continue
            try:
                small = await asyncio.to_thread(check.downscale_jpeg, frame, UI_FRAME_MAX_SIDE, 75, True)
            except Exception as e:
                log.debug("bad camera frame skipped: %s", e)
                metrics["frames_undecodable"] += 1
                continue
            metrics["ui_frames_downscaled"] += 1
            self.broadcast(small)


engine = Engine()


async def warm_up() -> None:
    """Open the pooled connection to the check provider at startup so the first real check is not slow. Skipped
    in mock mode, without a key, or until check.py offers a public warm_up; never fails startup."""
    warm = getattr(check, "warm_up", None)
    if check.is_mock() or warm is None:
        return
    try:
        await asyncio.wait_for(warm(), WARM_UP_TIMEOUT)
    except Exception as e:
        log.warning("check warm-up skipped: %s", check._redact(f"{type(e).__name__}: {e}"))


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(engine.check_loop()), asyncio.create_task(engine.ui_frame_loop()),
             asyncio.create_task(warm_up())]
    engine.open_breaker_if_no_key()
    if databricks_module() is not None and databricks_sink not in EVENT_SINKS:
        EVENT_SINKS.append(databricks_sink)
    log.info("lessons: %s  check: %s", LESSONS, check_mode() if check.is_mock() else f"{check_mode()} {check.active_model()}")
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


@app.get("/voice/{name}")
def web_voice(name: str) -> FileResponse:
    """Spoken cues of the Learn screen (web/public/voice, copied into web/dist/voice by the build)."""
    root = (WEB_DIST / "voice").resolve()
    file = (root / name).resolve()
    if root not in file.parents or not file.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(file, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


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


def lan_ip() -> Optional[str]:
    """This computer's address on the local network, or None. Connecting a UDP socket sends no packet; it only
    asks the OS which interface would route outward."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


@app.get("/api/hub-info")
def hub_info() -> dict:
    """What a screen needs to pair a phone: the hub's LAN address, its ports, the handover:// pairing link the
    apps scan, and the phone browser camera page (https, since phone browsers only allow the camera there)."""
    from urllib.parse import quote

    ip = lan_ip()
    http_port = int(config.get("HANDOVER_PORT"))  # type: ignore[arg-type]
    https_port = int(config.get("HANDOVER_HTTPS_PORT"))  # type: ignore[arg-type]
    hub = f"http://{ip}:{http_port}" if ip else None
    return {"lan_ip": ip, "http_port": http_port, "https_port": https_port, "hub_url": hub,
            "pair_link": f"handover://connect?hub={quote(hub, safe='')}" if hub else None,
            "capture_url": f"https://{ip}:{https_port}/capture" if ip and has_certs() else None}


def has_certs() -> bool:
    """True when the hub serves https (the phone browser camera page needs it)."""
    certs = Path(os.environ.get("HANDOVER_CERTS") or REPO / "certs")
    return (certs / "cert.pem").is_file() and (certs / "key.pem").is_file()


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


@app.post("/api/lesson", dependencies=[Depends(accounts.mutation_guard)])
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


@app.post("/api/lessons/{lesson_id}/recut", dependencies=[Depends(accounts.mutation_guard)])
async def recut(lesson_id: str, request: Request) -> Any:
    """Re-cut from lesson.json. An optional JSON body (a full lesson object) is saved first."""
    d = lesson_dir(lesson_id)
    read_lesson(lesson_id)  # 404 if missing
    new = await read_recut_body(request)
    if lesson_write_lock.locked():
        raise HTTPException(409, "recut already running")
    async with lesson_write_lock:
        original = (d / "lesson.json").read_text(encoding="utf-8")
        if new is None and "voiceover" in read_lesson(lesson_id):
            new = read_lesson(lesson_id)
        if new is not None:
            new["id"] = lesson_id
            new.pop("voiceover", None)  # the recut clips carry the original audio, not the voiceover
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


@app.delete("/api/lessons/{lesson_id}", dependencies=[Depends(accounts.mutation_guard)])
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


def _job_snapshot(job: str) -> Optional[dict]:
    with jobs_lock:
        return dict(jobs[job]) if job in jobs else None


# Accounts, course library, editor and scoring routes. A setter, not an import of main, because
# `python -m server.main` runs this file as __main__.
app.include_router(routes_library.router)
routes_library.configure(lock=lesson_write_lock, on_lesson_changed=lambda lesson_id: engine.reload_if_active(lesson_id),
                         upload=upload_lesson, job_status=_job_snapshot,
                         publish=lambda d, lesson_id: publish_lesson_files(lesson_id))

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
    client = UIClient(ws, label, frames=ws.query_params.get("frames", "1").strip().lower() not in ("0", "false", "no"))
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


def learner_id(token: Any) -> Optional[str]:
    """The user id behind an optional select_lesson token, or None (anonymous, or a token that does not resolve).
    Anonymous learning is always allowed, so a bad token is not an error here."""
    if not isinstance(token, str) or not token.strip():
        return None
    try:
        user = accounts.resolve_token(token.strip())
    except Exception:  # an unreadable token store must not block learning
        log.warning("learner token lookup failed", exc_info=True)
        return None
    return str(user["id"]) if user and user.get("id") else None


def handle_ui_message(client: UIClient, text: str) -> None:
    msg = parse_message(text)
    if msg is None:
        return
    kind = msg.get("type")
    if kind == "select_lesson":
        try:
            engine.select(str(msg.get("id", "")), learner=learner_id(msg.get("token")))
        except HTTPException as e:
            client.push({"type": "error", "message": e.detail})
    elif kind == "end_lesson":
        # A stale End (a screen still showing an older lesson or run) must not unload what someone else started.
        want_lesson, want_run = msg.get("lesson_id"), msg.get("run_id")
        current_run = engine.run_id()  # the id clients see in state.run_id
        if (want_lesson is not None and want_lesson != engine.lesson_id) or \
                (want_run is not None and current_run is not None and want_run != current_run):
            log.info("ignored stale end_lesson for %s / %s", want_lesson, want_run)
        else:
            engine.end_lesson()
    elif kind == "set_check_interval":  # a setting, so it works with no lesson loaded
        seconds = msg.get("seconds")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds):
            engine.set_check_interval(float(seconds))
    elif engine.lesson is None:
        client.push({"type": "error", "message": "no lesson selected"})
    elif kind in ("next", "back"):
        navigate(client, msg)
    elif kind == "goto":
        step = msg.get("step")
        if isinstance(step, int) and not isinstance(step, bool) and 0 <= step < len(engine.steps):
            engine.go(step, "button")
    elif kind == "hold":
        held = msg.get("hold")
        if isinstance(held, bool):
            engine.set_hold(held)
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


def port_free(port: int) -> bool:
    """True when nothing listens on 0.0.0.0:port. Binds the way uvicorn will (SO_REUSEADDR only off Windows,
    where it would let two listeners share a port), so a taken port is named before any server starts."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


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

    for c in configs:
        if not port_free(c.port):
            hint = f"netstat -ano | findstr :{c.port}" if os.name == "nt" else f"lsof -nP -iTCP:{c.port} -sTCP:LISTEN"
            log.error("port %d is already in use (often a stale hub): find it with  %s  and stop it, "
                      "or set HANDOVER_PORT / HANDOVER_HTTPS_PORT", c.port, hint)
            raise SystemExit(1)
    servers = [Server(c) for c in configs]
    info = hub_info()
    if info["hub_url"]:
        log.info("pair a phone: open HandOver and enter %s (QR: %s)", info["hub_url"], info["pair_link"])

    async def run_all() -> None:
        import signal

        def stop() -> None:
            for s in servers:
                s.force_exit = s.should_exit
                s.should_exit = True

        loop = asyncio.get_running_loop()
        # SIGBREAK: Ctrl+Break in a Windows console, and what scripts/e2e_demo.py sends for a clean stop.
        for sig in (signal.SIGINT, signal.SIGTERM, *([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])):
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

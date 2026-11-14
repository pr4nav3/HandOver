"""Databricks plumbing: learn events and lesson files to Unity Catalog, never in the live loop.

Every call here returns at once and never raises. Events always go to the local mirror
`<repo>/logs/events.jsonl` (one JSON object per line). When DATABRICKS_HOST, DATABRICKS_TOKEN and
DATABRICKS_WAREHOUSE_ID are set (environment or repo-root .env), a daemon thread also sends them to
the SQL warehouse through the Statement Execution API, batched: one statement per table per flush, at
most 200 rows, at most every 5 s, nothing when there is nothing to send (Free Edition has a daily
compute quota). Failures are soft: logged at most once a minute, exponential back-off to 60 s.

Env (values are never printed):
    DATABRICKS_HOST          https://xxx.cloud.databricks.com
    DATABRICKS_TOKEN         personal access token
    DATABRICKS_WAREHOUSE_ID  SQL warehouse id
    DATABRICKS_CATALOG       default workspace
    DATABRICKS_SCHEMA        default handover
    HANDOVER_EVENTS_JSONL    optional override of the local mirror path

API:
    run_id = start_run(lesson_id, learner=None)
    emit("step_enter", step=0)
    emit("check", step=2, done="no", confidence=0.8, latency_ms=900, reason="seams up")
    emit("advance", from_step=2, to_step=3, reason="camera")
    emit("mistake", step=4, kind="behind", looks_like=3, confidence=0.86)
    emit("check_offline", reason="rate_limited")
    end_run()
    upload_lesson_files(lesson_dir, lesson_id)
    status()

CLI (from the repo root):
    python -m server.databricks --init       print the DDL; with credentials, run it
    python -m server.databricks --selftest   three events to a temp JSONL; with credentials, flush one batch
    python -m server.databricks --tail       last 20 local events
    python -m server.databricks --warm       with credentials, SELECT 1 to start the warehouse
"""

from __future__ import annotations

import atexit
import collections
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("handover.databricks")

REPO = Path(__file__).resolve().parent.parent
SQL_FILE = Path(__file__).resolve().parent / "static" / "databricks_init.sql"

BATCH_MAX = 200
FLUSH_EVERY = 5.0  # seconds
QUEUE_MAX = 10_000
BACKOFF_MAX = 60.0
LOG_EVERY = 60.0  # at most one failure log line per minute
MAX_FILE_BYTES = 200 * 1024**2
MAX_RETRIES = 3  # a failed batch is retried this many times, then dropped (the JSONL keeps it)
HTTP_TIMEOUT = 45.0  # wait_timeout is 30 s on the server side
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
KINDS = {"run_start", "run_end", "step_enter", "check", "advance", "mistake", "check_offline"}


# ---------------------------------------------------------------- config (read at import, no side effects)

def _read_env_file() -> dict[str, str]:
    """Same rules as server/check.py: KEY=VALUE lines, # comments, optional export and quotes."""
    out: dict[str, str] = {}
    path = REPO / ".env"
    try:
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            out[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _load_config() -> dict[str, str]:
    env = _read_env_file()

    def get(name: str, default: str = "") -> str:
        return (os.environ.get(name) or env.get(name) or default).strip()

    host = get("DATABRICKS_HOST").rstrip("/")
    if host and not host.startswith(("https://", "http://")):
        host = "https://" + host
    return {
        "host": host,
        "token": get("DATABRICKS_TOKEN"),
        "warehouse": get("DATABRICKS_WAREHOUSE_ID"),
        "catalog": get("DATABRICKS_CATALOG", "workspace"),
        "schema": get("DATABRICKS_SCHEMA", "handover"),
        "jsonl": get("HANDOVER_EVENTS_JSONL"),
    }


_cfg = _load_config()


def _config_error() -> Optional[str]:
    if not (_cfg["host"] and _cfg["token"] and _cfg["warehouse"]):
        return None  # simply disabled
    for k in ("catalog", "schema"):
        if not IDENT_RE.match(_cfg[k]):
            return f"DATABRICKS_{k.upper()} must be letters, digits and underscores"
    return None


def _enabled() -> bool:
    return bool(_cfg["host"] and _cfg["token"] and _cfg["warehouse"]) and _config_error() is None


def _fq(table: str) -> str:
    return f"`{_cfg['catalog']}`.`{_cfg['schema']}`.`{table}`"


def _local_path() -> Path:
    return Path(_cfg["jsonl"]) if _cfg["jsonl"] else REPO / "logs" / "events.jsonl"


# ---------------------------------------------------------------- tables

# Column name -> SQL type. Rows travel as one JSON string parameter per statement and are expanded with
# from_json + inline, so there is one named marker per batch and no string ever lands in SQL text.
TABLES: dict[str, dict[str, Any]] = {
    "events": {
        "cols": {
            "event_id": "STRING", "run_id": "STRING", "lesson_id": "STRING", "step": "INT",
            "ts": "TIMESTAMP", "kind": "STRING", "done": "STRING", "confidence": "DOUBLE",
            "latency_ms": "INT", "reason": "STRING", "from_step": "INT", "to_step": "INT",
            "mistake_kind": "STRING", "looks_like": "INT", "extra": "STRING",
        },
        "key": None,  # append only
    },
    "runs": {
        "cols": {"run_id": "STRING", "lesson_id": "STRING", "learner": "STRING",
                 "started_at": "TIMESTAMP", "ended_at": "TIMESTAMP"},
        "key": ("run_id",),
    },
    "lessons": {
        "cols": {"lesson_id": "STRING", "title": "STRING", "expert": "STRING",
                 "duration_s": "DOUBLE", "created_at": "TIMESTAMP"},
        "key": ("lesson_id",),
    },
    "steps": {
        "cols": {"lesson_id": "STRING", "n": "INT", "title": "STRING", "start_s": "DOUBLE",
                 "end_s": "DOUBLE", "check_type": "STRING", "check_question": "STRING"},
        "key": ("lesson_id", "n"),
    },
}
FLUSH_ORDER = ("lessons", "steps", "runs", "events")


def _statement_for(table: str) -> str:
    spec = TABLES[table]
    cols = spec["cols"]
    # Timestamps travel as ISO strings and are cast, so the JSON schema is all primitive types.
    struct = ", ".join(f"`{c}`: {'STRING' if t == 'TIMESTAMP' else t}" for c, t in cols.items())
    select = ", ".join(f"CAST(`{c}` AS TIMESTAMP) AS `{c}`" if t == "TIMESTAMP" else f"`{c}`"
                       for c, t in cols.items())
    src = f"SELECT {select} FROM (SELECT inline(from_json(:rows, 'ARRAY<STRUCT<{struct}>>')) AS r)"
    names = ", ".join(f"`{c}`" for c in cols)
    if spec["key"] is None:
        return f"INSERT INTO {_fq(table)} ({names}) {src}"
    on = " AND ".join(f"t.`{k}` = s.`{k}`" for k in spec["key"])
    upd = ", ".join(f"t.`{c}` = s.`{c}`" for c in cols if c not in spec["key"])
    if table == "runs":  # the start row has no ended_at; never let a late start row erase it
        upd = upd.replace("t.`ended_at` = s.`ended_at`", "t.`ended_at` = coalesce(s.`ended_at`, t.`ended_at`)")
    vals = ", ".join(f"s.`{c}`" for c in cols)
    return (f"MERGE INTO {_fq(table)} t USING ({src}) s ON {on} "
            f"WHEN MATCHED THEN UPDATE SET {upd} WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({vals})")


# ---------------------------------------------------------------- state

_lock = threading.Lock()  # run state, counters, queue
_cond = threading.Condition(_lock)
_file_lock = threading.Lock()
_queue: collections.deque = collections.deque()  # (table, row) tuples, bounded by QUEUE_MAX
_run: dict[str, Any] = {"run_id": None, "lesson_id": None, "learner": None, "started_at": None, "step": 0}
_stats: dict[str, Any] = {"flushed": 0, "statements": 0, "dropped": 0, "failed_batches": 0,
                          "last_error": None, "last_error_at": None, "last_flush_at": None,
                          "uploaded_files": 0, "local_errors": 0}
_thread: Optional[threading.Thread] = None
_last_log = {"remote": 0.0, "local": 0.0, "overflow": 0.0}
_inflight = 0  # rows taken off the queue and not yet settled, for flush()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _scrub(msg: str) -> str:
    tok = _cfg.get("token") or ""
    if tok:
        msg = msg.replace(tok, "***")
    msg = re.sub(r"dapi[0-9a-fA-F]{20,}", "***", msg)
    msg = re.sub(r"(?i)bearer\s+\S+", "Bearer ***", msg)
    return " ".join(msg.split())[:300]


def _soft_fail(where: str, msg: str) -> None:
    msg = _scrub(msg)
    now = time.time()
    with _lock:
        _stats["last_error"] = f"{where}: {msg}"
        _stats["last_error_at"] = _now_iso()
        quiet = now - _last_log["remote"] < LOG_EVERY
        if not quiet:
            _last_log["remote"] = now
    if not quiet:
        log.warning("databricks %s failed (local JSONL kept): %s", where, msg)


# ---------------------------------------------------------------- public API

def start_run(lesson_id: Optional[str], learner: Optional[str] = None) -> Optional[str]:
    """Begin a learner run (ends any active one first). Returns the run id."""
    try:
        if _run["run_id"] is not None:
            end_run()
        run_id = str(uuid.uuid4())
        started = _now_iso()
        with _lock:
            _run.update(run_id=run_id, lesson_id=lesson_id, learner=learner, started_at=started, step=0)
        _enqueue("runs", {"run_id": run_id, "lesson_id": lesson_id, "learner": learner,
                          "started_at": started, "ended_at": None})
        emit("run_start", step=0, **({"learner": learner} if learner else {}))
        return run_id
    except Exception as e:  # never raise into the server
        _soft_fail("start_run", f"{type(e).__name__}: {e}")
        return None


def end_run() -> None:
    """Finish the active run, if any."""
    try:
        if _run["run_id"] is None:
            return
        emit("run_end")
        with _lock:
            row = {"run_id": _run["run_id"], "lesson_id": _run["lesson_id"], "learner": _run["learner"],
                   "started_at": _run["started_at"], "ended_at": _now_iso()}
            _run.update(run_id=None, learner=None, started_at=None)
        _enqueue("runs", row)
    except Exception as e:
        _soft_fail("end_run", f"{type(e).__name__}: {e}")


def emit(kind: str, /, **fields: Any) -> None:
    """Record one event. `kind` is positional-only, so a mistake can pass its own `kind=`.

    Recognised fields: step (0-based; defaults to the last known step), lesson_id (defaults to the run's),
    done, confidence, latency_ms, reason, from_step / to_step (or "from" / "to"), kind / mistake_kind and
    looks_like for mistakes. Anything else goes to `extra` as JSON.
    """
    try:
        f = dict(fields)
        if "from" in f:
            f.setdefault("from_step", f.pop("from"))
        if "to" in f:
            f.setdefault("to_step", f.pop("to"))
        if "kind" in f:
            f.setdefault("mistake_kind", f.pop("kind"))
        with _lock:
            if "step" in f and f["step"] is not None:
                _run["step"] = f["step"]
            elif kind == "advance" and f.get("from_step") is not None:
                f["step"] = f["from_step"]
            step = f.pop("step", None)
            if step is None:
                step = _run["step"]
            if kind in ("advance", "step_enter") and f.get("to_step") is not None:
                _run["step"] = f["to_step"]
            run_id = _run["run_id"]
            lesson_id = f.pop("lesson_id", None) or _run["lesson_id"]
            if lesson_id is not None and _run["run_id"] is None:
                _run["lesson_id"] = lesson_id
        known = TABLES["events"]["cols"]
        row: dict[str, Any] = {
            "event_id": str(uuid.uuid4()), "run_id": run_id, "lesson_id": lesson_id,
            "step": _as_int(step), "ts": _now_iso(), "kind": str(kind),
            "done": _as_str(f.pop("done", None)),
            "confidence": _as_float(f.pop("confidence", None)),
            "latency_ms": _as_int(f.pop("latency_ms", None)),
            "reason": _as_str(f.pop("reason", None)),
            "from_step": _as_int(f.pop("from_step", None)),
            "to_step": _as_int(f.pop("to_step", None)),
            "mistake_kind": _as_str(f.pop("mistake_kind", None)),
            "looks_like": _as_int(f.pop("looks_like", None)),
        }
        extra = {k: v for k, v in f.items() if k not in known}
        if kind not in KINDS:
            extra["unknown_kind"] = True
        row["extra"] = json.dumps(extra, default=str, separators=(",", ":")) if extra else None
        _write_local(row)
        _enqueue("events", row)
    except Exception as e:
        _soft_fail("emit", f"{type(e).__name__}: {e}")


def upload_lesson_files(lesson_dir: Path, lesson_id: str) -> None:
    """Background: lesson.json, frames/*.jpg, captions/*.vtt, clips/*.mp4 to the Volume, plus the
    lessons and steps rows. Does nothing when Databricks is not configured."""
    try:
        if not _enabled():
            return
        t = threading.Thread(target=_upload_worker, args=(Path(lesson_dir), str(lesson_id)),
                             name="databricks-upload", daemon=True)
        t.start()
    except Exception as e:
        _soft_fail("upload", f"{type(e).__name__}: {e}")


def status() -> dict:
    """Queue depth, counters, last error (no secrets), enabled flag."""
    with _lock:
        return {
            "enabled": _enabled(),
            "config_error": _config_error(),
            "target": f"{_cfg['catalog']}.{_cfg['schema']}",
            "queue": len(_queue),
            "in_flight": _inflight,
            "flushed": _stats["flushed"],
            "statements": _stats["statements"],
            "dropped": _stats["dropped"],
            "failed_batches": _stats["failed_batches"],
            "uploaded_files": _stats["uploaded_files"],
            "last_flush_at": _stats["last_flush_at"],
            "last_error": _stats["last_error"],
            "last_error_at": _stats["last_error_at"],
            "run_id": _run["run_id"],
            "local_jsonl": str(_local_path()),
        }


def flush(timeout: float = 10.0) -> bool:
    """Ask the worker to send what is queued now and wait up to `timeout` s. True if the queue drained.
    For the CLI and shutdown; the server never needs to call it."""
    try:
        if not _enabled():
            return True
        _ensure_thread()
        deadline = time.monotonic() + timeout
        with _cond:
            _flush_now.set()
            _cond.notify_all()
            while (_queue or _inflight) and time.monotonic() < deadline:
                _cond.wait(min(0.2, max(0.0, deadline - time.monotonic())))
            return not _queue and not _inflight
    except Exception:
        return False


# ---------------------------------------------------------------- local mirror

def _write_local(row: dict) -> None:
    try:
        path = _local_path()
        line = json.dumps(row, default=str, separators=(",", ":")) + "\n"
        with _file_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as e:
        now = time.time()
        with _lock:
            _stats["local_errors"] += 1
            quiet = now - _last_log["local"] < LOG_EVERY
            if not quiet:
                _last_log["local"] = now
        if not quiet:
            log.warning("could not append to %s: %s", _local_path(), e)


# ---------------------------------------------------------------- queue and worker

_flush_now = threading.Event()


def _enqueue(table: str, row: dict) -> None:
    if not _enabled():
        return
    _ensure_thread()
    overflow = False
    with _cond:
        if len(_queue) >= QUEUE_MAX:
            _queue.popleft()
            _stats["dropped"] += 1
            now = time.time()
            if now - _last_log["overflow"] >= LOG_EVERY:
                _last_log["overflow"] = now
                overflow = True
        _queue.append((table, row))
        if len(_queue) >= BATCH_MAX:
            _cond.notify_all()
    if overflow:
        log.warning("databricks queue full (%d); dropping oldest rows, local JSONL still has them", QUEUE_MAX)


def _ensure_thread() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        first = _thread is None
        _thread = threading.Thread(target=_worker, name="databricks-flush", daemon=True)
        _thread.start()
    if first:
        atexit.register(flush, 3.0)  # best effort: send what is queued on a clean exit


def _worker() -> None:
    global _inflight
    backoff = 0.0
    while True:
        try:
            with _cond:
                first_seen = time.monotonic() if _queue else None
                # Wait until a full batch, 5 s after the oldest queued row, or an explicit flush.
                while True:
                    if _queue and first_seen is None:
                        first_seen = time.monotonic()
                    if _flush_now.is_set() and _queue:
                        break
                    if len(_queue) >= BATCH_MAX:
                        break
                    if first_seen is not None and time.monotonic() - first_seen >= FLUSH_EVERY:
                        break
                    wait = FLUSH_EVERY if first_seen is None else FLUSH_EVERY - (time.monotonic() - first_seen)
                    _cond.wait(max(0.05, wait))
                batch = [_queue.popleft() for _ in range(min(BATCH_MAX, len(_queue)))]
                _inflight = len(batch)
                if not _queue:
                    _flush_now.clear()
            ok, failed = _send_batch(batch)
            with _cond:
                if failed:
                    _stats["failed_batches"] += 1
                    keep = [(t, r) for t, r in failed if r.setdefault("__tries", 0) < MAX_RETRIES]
                    for t, r in keep:
                        r["__tries"] += 1
                    _stats["dropped"] += len(failed) - len(keep)
                    room = QUEUE_MAX - len(_queue)
                    for item in reversed(keep[:max(0, room)]):
                        _queue.appendleft(item)
                _inflight = 0
                _cond.notify_all()
            if failed:
                backoff = min(BACKOFF_MAX, backoff * 2 if backoff else 2.0)
                _flush_now.clear()
                time.sleep(backoff)
            else:
                backoff = 0.0
        except Exception as e:  # keep the worker alive whatever happens
            with _cond:
                _inflight = 0
                _cond.notify_all()
            _soft_fail("worker", f"{type(e).__name__}: {e}")
            backoff = min(BACKOFF_MAX, backoff * 2 if backoff else 2.0)
            time.sleep(backoff)


def _send_batch(batch: list) -> tuple[int, list]:
    """One statement per table in the batch. Returns (rows sent, items that failed)."""
    by_table: dict[str, list] = collections.defaultdict(list)
    for table, row in batch:
        by_table[table].append(row)
    sent, failed = 0, []
    for table in FLUSH_ORDER:
        rows = by_table.get(table)
        if not rows:
            continue
        key = TABLES[table]["key"]
        if key:  # MERGE needs unique source keys: the latest row per key wins
            dedup: dict[tuple, dict] = {}
            for r in rows:
                dedup[tuple(r.get(k) for k in key)] = r
            rows = list(dedup.values())
        cols = TABLES[table]["cols"]
        payload = json.dumps([{c: r.get(c) for c in cols} for r in rows], default=str, separators=(",", ":"))
        err = _execute(_statement_for(table), [{"name": "rows", "value": payload, "type": "STRING"}])
        if err is None:
            sent += len(rows)
            with _lock:
                _stats["flushed"] += len(rows)
                _stats["statements"] += 1
                _stats["last_flush_at"] = _now_iso()
        else:
            _soft_fail(f"insert {table}", err)
            failed.extend((table, r) for r in rows)
    return sent, failed


# ---------------------------------------------------------------- HTTP

def _request(method: str, path: str, body: Optional[bytes] = None, content_type: str = "application/json",
             timeout: float = HTTP_TIMEOUT, length: Optional[int] = None, stream: Any = None) -> tuple[int, bytes]:
    url = _cfg["host"] + path
    headers = {"Authorization": f"Bearer {_cfg['token']}", "Content-Type": content_type,
               "User-Agent": "handover-hub/1.0"}
    data: Any = body
    if stream is not None:
        data = stream
        headers["Content-Length"] = str(length or 0)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        except Exception:
            return e.code, b""


def _execute(statement: str, parameters: Optional[list] = None, wait: bool = False) -> Optional[str]:
    """Run one SQL statement on the warehouse. None on success, else a short error string.

    wait_timeout 30 s covers a warm warehouse; on_wait_timeout CONTINUE lets a cold one finish the
    statement on its own, which we count as accepted (no polling: the daily quota). Only `wait=True`
    (the --init CLI, where order matters) polls until the statement ends.
    """
    try:
        body: dict[str, Any] = {"warehouse_id": _cfg["warehouse"], "statement": statement,
                                "wait_timeout": "30s", "on_wait_timeout": "CONTINUE",
                                "disposition": "INLINE", "format": "JSON_ARRAY"}
        if parameters:
            body["parameters"] = parameters
        code, raw = _request("POST", "/api/2.0/sql/statements", json.dumps(body).encode("utf-8"))
        if not 200 <= code < 300:
            return f"HTTP {code} {_error_text(raw)}"
        res = json.loads(raw or b"{}")
        state = (res.get("status") or {}).get("state", "")
        if wait:
            sid = res.get("statement_id")
            deadline = time.monotonic() + 600
            while state in ("PENDING", "RUNNING") and sid and time.monotonic() < deadline:
                time.sleep(5)
                code, raw = _request("GET", f"/api/2.0/sql/statements/{urllib.parse.quote(sid)}")
                if not 200 <= code < 300:
                    return f"HTTP {code} {_error_text(raw)}"
                res = json.loads(raw or b"{}")
                state = (res.get("status") or {}).get("state", "")
        if state in ("SUCCEEDED", "PENDING", "RUNNING"):
            return None
        err = (res.get("status") or {}).get("error") or {}
        return f"{state or 'unknown state'}: {err.get('error_code', '')} {err.get('message', '')}".strip()
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _error_text(raw: bytes) -> str:
    try:
        j = json.loads(raw)
        return f"{j.get('error_code', '')} {j.get('message', '')}".strip()
    except Exception:
        return raw[:200].decode("utf-8", "replace")


def _put_file(local: Path, volume_path: str) -> Optional[str]:
    try:
        size = local.stat().st_size
        path = "/api/2.0/fs/files" + urllib.parse.quote(volume_path) + "?overwrite=true"
        with local.open("rb") as fh:
            code, raw = _request("PUT", path, content_type="application/octet-stream",
                                 timeout=max(60.0, size / 1_000_000), length=size, stream=fh)
        if 200 <= code < 300:
            return None
        return f"HTTP {code} {_error_text(raw)}"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- lesson upload

def _seconds(v: Any) -> Optional[float]:
    """"MM:SS", "HH:MM:SS", "SS.s" or a number to seconds."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        total = 0.0
        for part in str(v).strip().split(":"):
            total = total * 60 + float(part)
        return total
    except ValueError:
        return None


def _upload_worker(lesson_dir: Path, lesson_id: str) -> None:
    try:
        lj = lesson_dir / "lesson.json"
        lesson = json.loads(lj.read_text(encoding="utf-8")) if lj.is_file() else {}
        steps = lesson.get("steps") or []
        ends = [s for s in (_seconds(st.get("end")) for st in steps) if s is not None]
        _enqueue("lessons", {"lesson_id": lesson_id, "title": _as_str(lesson.get("title")),
                             "expert": _as_str(lesson.get("expert")),
                             "duration_s": max(ends) if ends else None, "created_at": _now_iso()})
        for i, st in enumerate(steps):
            _enqueue("steps", {"lesson_id": lesson_id, "n": _as_int(st.get("n")) or i + 1,
                               "title": _as_str(st.get("title")), "start_s": _seconds(st.get("start")),
                               "end_s": _seconds(st.get("end")), "check_type": _as_str(st.get("check_type")),
                               "check_question": _as_str(st.get("check_question"))})
        files = [lj] if lj.is_file() else []
        for sub, pattern in (("frames", "*.jpg"), ("captions", "*.vtt"), ("clips", "*.mp4")):
            files.extend(sorted((lesson_dir / sub).glob(pattern)))
        base = f"/Volumes/{_cfg['catalog']}/{_cfg['schema']}/lessons/{lesson_id}"
        ok = 0
        for f in files:
            try:
                if f.stat().st_size > MAX_FILE_BYTES:
                    log.warning("databricks upload skips %s (over 200 MB)", f.name)
                    continue
            except OSError:
                continue
            rel = f.relative_to(lesson_dir).as_posix()
            err = _put_file(f, f"{base}/{rel}")
            if err:
                _soft_fail(f"upload {rel}", err)
            else:
                ok += 1
                with _lock:
                    _stats["uploaded_files"] += 1
        log.info("databricks: uploaded %d/%d files of lesson %s", ok, len(files), lesson_id)
    except Exception as e:
        _soft_fail("upload", f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- coercion

def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _as_str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


# ---------------------------------------------------------------- CLI

def _ddl_statements() -> list[str]:
    """CREATE statements from the .sql file, comments stripped, target catalog.schema substituted."""
    text = SQL_FILE.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("--")]
    out = []
    for stmt in "\n".join(lines).split(";"):
        s = stmt.strip()
        if s.upper().startswith("CREATE"):
            out.append(s.replace("workspace.handover", f"`{_cfg['catalog']}`.`{_cfg['schema']}`"))
    return out


def _cli_init() -> int:
    print(SQL_FILE.read_text(encoding="utf-8"))
    if _config_error():
        print(f"-- not run: {_config_error()}")
        return 1
    if not _enabled():
        print("-- not run: DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_WAREHOUSE_ID not all set")
        return 0
    print(f"-- running {len(_ddl_statements())} statements on {_cfg['catalog']}.{_cfg['schema']} ...")
    bad = 0
    for s in _ddl_statements():
        head = " ".join(s.split()[:6])
        err = _execute(s, wait=True)
        print(f"--   {'ok  ' if err is None else 'FAIL'} {head}" + ("" if err is None else f": {_scrub(err)}"))
        bad += err is not None
    return 1 if bad else 0


def _cli_selftest() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="handover-dbx-")) / "events.jsonl"
    _cfg["jsonl"] = str(tmp)
    run_id = start_run("selftest", learner="selftest")
    emit("step_enter", step=0)
    emit("check", step=0, done="no", confidence=0.82, latency_ms=910, reason="seams still facing up")
    emit("advance", from_step=0, to_step=1, reason="button")
    emit("mistake", step=1, kind="behind", looks_like=0, confidence=0.86)
    end_run()
    lines = tmp.read_text(encoding="utf-8").splitlines() if tmp.is_file() else []
    print(f"run_id {run_id}")
    print(f"local JSONL {tmp}: {len(lines)} lines")
    for ln in lines:
        print("  " + ln)
    kinds = [json.loads(ln)["kind"] for ln in lines]
    ok = kinds == ["run_start", "step_enter", "check", "advance", "mistake", "run_end"]
    if _enabled():
        print("flushing to Databricks (up to 90 s for a cold warehouse) ...")
        drained = flush(90.0)
        print("flush", "done" if drained else "not finished")
        ok = ok and drained and status()["last_error"] is None
    else:
        print("Databricks not configured: local only" + (f" ({_config_error()})" if _config_error() else ""))
    print("status " + json.dumps(status(), indent=2))
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def _cli_tail(n: int = 20) -> int:
    path = _local_path()
    if not path.is_file():
        print(f"no events yet at {path}")
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        last = collections.deque(fh, maxlen=n)
    for ln in last:
        print(ln.rstrip("\n"))
    return 0


def _cli_warm() -> int:
    if not _enabled():
        print("Databricks not configured")
        return 1
    t0 = time.monotonic()
    err = _execute("SELECT 1", wait=True)
    print(f"warm: {'ok' if err is None else _scrub(err)} in {time.monotonic() - t0:.1f} s")
    return 0 if err is None else 1


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    if not log.handlers and not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                            datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(prog="python -m server.databricks", description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true", help="print the DDL; with credentials, run it")
    g.add_argument("--selftest", action="store_true", help="emit events to a temp JSONL; flush if configured")
    g.add_argument("--tail", action="store_true", help="print the last 20 local events")
    g.add_argument("--warm", action="store_true", help="SELECT 1 to start the warehouse before a demo")
    a = p.parse_args(argv)
    if a.init:
        return _cli_init()
    if a.selftest:
        return _cli_selftest()
    if a.warm:
        return _cli_warm()
    return _cli_tail()


if __name__ == "__main__":
    sys.exit(main())

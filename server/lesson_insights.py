"""Desktop lesson insights: recent local events plus a cached Databricks read.

Warehouse reads run in one background thread per lesson revision. Requests never wait for a cold warehouse.
Only the permission-checked aggregate route exposes this module; raw events never reach clients.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from server import databricks as db, library

TTL = 180.0
LIMIT = 20000
_lock = threading.Lock()
_cache: dict[tuple[str, str], dict[str, Any]] = {}


def _real_events(rows: list[dict]) -> list[dict]:
    excluded = {rid for rid, events in library.runs(rows).items() if any(
        e.get("check_mode") == "mock" or e.get("source") == "file" or e.get("camera_source") == "file"
        or e.get("attempt_kind") == "replay" for e in events)}
    return [e for e in rows if e.get("run_id") and str(e["run_id"]) not in excluded and not e.get("stale")]


def _read(lesson_id: str, since: str) -> list[dict]:
    statement = (f"SELECT event_id, run_id, lesson_id, step, kind, done, confidence, latency_ms, reason, "
                 f"from_step, to_step, mistake_kind, looks_like, extra, "
                 f"date_format(ts, \"yyyy-MM-dd'T'HH:mm:ss.SSS'Z'\") AS ts "
                 f"FROM {db._fq('events_real')} WHERE lesson_id = :lesson "
                 f"AND (:since = '' OR ts >= try_cast(:since AS TIMESTAMP)) ORDER BY ts LIMIT {LIMIT}")
    body = {"warehouse_id": db._cfg["warehouse"], "statement": statement,
            "parameters": [{"name": "lesson", "value": lesson_id, "type": "STRING"},
                           {"name": "since", "value": since, "type": "STRING"}],
            "wait_timeout": "10s", "on_wait_timeout": "CONTINUE", "format": "JSON_ARRAY"}
    code, raw = db._request("POST", "/api/2.0/sql/statements", json.dumps(body).encode())
    if code != 200:
        raise RuntimeError(f"warehouse HTTP {code}")
    result = json.loads(raw)
    deadline = time.monotonic() + 90
    while result.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        if time.monotonic() >= deadline:
            sid = result.get("statement_id", "")
            if sid:
                db._request("POST", f"/api/2.0/sql/statements/{sid}/cancel", b"{}")
            raise TimeoutError("warehouse read timed out")
        time.sleep(2)
        code, raw = db._request("GET", f"/api/2.0/sql/statements/{result['statement_id']}")
        if code != 200:
            raise RuntimeError(f"warehouse HTTP {code}")
        result = json.loads(raw)
    if result.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError("warehouse read failed")
    if result.get("manifest", {}).get("truncated") or result.get("result", {}).get("next_chunk_index") is not None:
        raise RuntimeError("warehouse response too large")
    rows = result.get("result", {}).get("data_array") or []
    if len(rows) >= LIMIT:
        raise RuntimeError("warehouse history exceeds read limit")
    names = [c["name"] for c in result.get("manifest", {}).get("schema", {}).get("columns", [])]
    return [flat for row in rows if (flat := library._flatten(dict(zip(names, row)))) is not None]


def _current_events(events: list[dict], lesson: dict) -> tuple[list[dict], int]:
    """Do not label a previous cut's step 5 with the current cut's step 5 title."""
    steps = lesson.get("steps", [])
    revision = library.lesson_revision(lesson)
    excluded = set()
    for run_id, rows in library.runs(events).items():
        for row in rows:
            if row.get("kind") == "run_start":
                if row.get("lesson_revision") and row["lesson_revision"] != revision:
                    excluded.add(run_id)
                total = library.as_int(row.get("total"))
                if total is not None and total != len(steps):
                    excluded.add(run_id)
            if row.get("kind") == "step_enter":
                index = library.as_int(row.get("step"))
                seconds = library.as_float(row.get("expert_seconds"))
                if index is not None and (index < 0 or index >= len(steps) or
                   (seconds is not None and abs(seconds - library.step_seconds(steps[index])) > 0.05)):
                    excluded.add(run_id)
    return [e for e in events if str(e.get("run_id")) not in excluded], len(excluded)


def _refresh(key: tuple[str, str]) -> None:
    try:
        events = _read(*key)
        with _lock:
            _cache[key].update(events=events, fetched_at=datetime.now(timezone.utc).isoformat(), error=False)
    except Exception:
        with _lock:
            _cache[key]["error"] = True
    finally:
        with _lock:
            _cache[key].update(busy=False, checked=time.monotonic())


def course(lesson_id: str, lesson: dict, since: str | None) -> dict:
    local = library.lesson_events(lesson_id, since)
    key = (lesson_id, since or "")
    enabled = db._enabled()
    with _lock:
        entry = _cache.setdefault(key, {"events": [], "checked": 0.0, "busy": False,
                                        "fetched_at": None, "error": False})
        if enabled and not entry["busy"] and time.monotonic() - entry["checked"] > TTL:
            entry["busy"] = True
            threading.Thread(target=_refresh, args=(key,), daemon=True, name="lesson-insights").start()
        snapshot = dict(entry)
    # A freshly completed local run appears immediately; cloud and local copies share event_id.
    merged: dict[str, dict] = {}
    for i, event in enumerate([*snapshot["events"], *local]):
        merged[str(event.get("event_id") or f"local-{i}")] = event
    events, previous_versions = _current_events(_real_events(list(merged.values())), lesson)
    events.sort(key=lambda e: str(e.get("ts") or ""))
    out = library.insights(lesson_id, lesson, since, events=events)
    for step, stats in zip(lesson.get("steps", []), out["steps"]):
        if step.get("check_type") == "manual":
            stats["manual_rate"] = {"value": None, "n": 0}
    out["sync"] = {"source": "databricks" if snapshot["fetched_at"] else "local",
                   "state": "refreshing" if snapshot["busy"] else "unavailable" if snapshot["error"] else "ready" if enabled else "local",
                   "updated_at": snapshot["fetched_at"]}
    out["previous_version_runs"] = previous_versions
    return out

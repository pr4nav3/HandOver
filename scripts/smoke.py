#!/usr/bin/env python3
"""End-to-end smoke check and live event monitor for a running HandOver hub.

    .venv/bin/python scripts/smoke.py run   [--base http://localhost:8000] [--lesson demo-v1]
    .venv/bin/python scripts/smoke.py watch [--base http://localhost:8000] [--log FILE]

run: lists lessons, selects one over /ws/ui, streams the lesson's own video into /ws/camera with
server.replay, and checks that the camera advances a step within 30 s, that Next works on a manual
step, and that the lesson reaches done. Prints a PASS/FAIL table; exit code 0 only when nothing failed.
It takes over the hub's one learn session, so do not run it during a live fold.

watch: prints one timestamped line per state, advance, mistake and error from /ws/ui (binary live
frames are skipped). Step numbers are shown 1-based, as on screen. --log appends every message as a
JSON line. Reconnects if the hub restarts. Ctrl+C stops it.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import websockets

REPO = Path(__file__).resolve().parent.parent
FIRST_ADVANCE_S = 30.0


# ---------------------------------------------------------------- helpers

def ws_url(base: str, path: str) -> str:
    p = urlsplit(base)
    scheme = "wss" if p.scheme == "https" else "ws"
    return urlunsplit((scheme, p.netloc, path, "", ""))


def get_json(base: str, path: str):
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=5) as r:
        return json.loads(r.read())


def download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


async def next_text(ws, timeout: float):
    """Next JSON text message, skipping binary live frames. None on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        try:
            msg = await asyncio.wait_for(ws.recv(), left)
        except asyncio.TimeoutError:
            return None
        if isinstance(msg, str):
            try:
                return json.loads(msg)
            except json.JSONDecodeError:
                continue


def now_hms() -> str:
    return dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def step_label(n: int | None, total: int | None) -> str:
    if n is None:
        return "?"
    if total is not None and n >= total:
        return "done"
    return f"step {n + 1}"


def fmt(msg: dict, total: int | None = None) -> str | None:
    """One compact line for a hub message. total (from the last state) lets an advance show "done"."""
    kind = msg.get("type")
    if kind == "state":
        if not msg.get("lesson_id"):
            return "state    no lesson selected" + ("  camera on" if msg.get("camera_connected") else "")
        total = msg.get("total") or 0
        status = msg.get("status", "?")
        where = f"all {total} steps" if status == "done" else f"step {msg.get('step', 0) + 1}/{total}"
        parts = [f"state    {msg['lesson_id']} {where} {status}"]
        cam = msg.get("camera")
        if cam:
            parts.append(f"cam {cam.get('name', '?')} ({cam.get('source', '?')})")
        else:
            parts.append("cam on" if msg.get("camera_connected") else "cam OFF")
        lc = msg.get("last_check")
        if lc:
            check = f"check {lc.get('done')} {lc.get('confidence', 0):.2f} {lc.get('latency_ms', 0)}ms"
            if lc.get("reason"):
                check += f' "{lc["reason"]}"'
            parts.append(check)
        if msg.get("check_offline"):
            parts.append(f"CHECKS OFF ({msg.get('check_offline_reason') or '?'})")
        if msg.get("mistake"):
            parts.append("mistake showing")
        return "  ".join(parts)
    if kind == "advance":
        return f"ADVANCE  {step_label(msg.get('from'), total)} -> {step_label(msg.get('to'), total)}  {msg.get('reason', '?')}"
    if kind == "mistake":
        looks = msg.get("looks_like")
        return (f"MISTAKE  step {msg.get('step', -1) + 1} {msg.get('kind', '?')}"
                f"{f' looks like step {looks + 1}' if isinstance(looks, int) else ''}"
                f"  \"{msg.get('message', '')}\"  {msg.get('confidence', 0):.2f} {msg.get('source', '?')}")
    if kind == "error":
        return f"ERROR    {msg.get('message', '')}"
    return f"{kind or '?':8s} {json.dumps(msg)[:120]}"


# ---------------------------------------------------------------- run

class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, result: str, name: str, detail: str = "") -> None:
        self.rows.append((result, name, detail))

    def failed(self) -> bool:
        return any(r == "FAIL" for r, _, _ in self.rows)

    def print(self, header: str) -> int:
        print()
        print(header)
        width = max((len(n) for _, n, _ in self.rows), default=10)
        for result, name, detail in self.rows:
            print(f"  {result:4s}  {name:{width}s}  {detail}")
        counted = [r for r, _, _ in self.rows if r != "SKIP"]
        passed = counted.count("PASS")
        verdict = "FAIL" if self.failed() else "PASS"
        print(f"{verdict} ({passed} of {len(counted)} passed"
              f"{', ' + str(len(self.rows) - len(counted)) + ' skipped' if len(counted) < len(self.rows) else ''})")
        return 1 if self.failed() else 0


def start_replay(video: Path, cam_url: str, fps: float, log_path: Path) -> subprocess.Popen:
    log = open(log_path, "wb")
    return subprocess.Popen(
        [sys.executable, "-m", "server.replay", str(video), "--url", cam_url, "--loop", "--fps", str(fps)],
        cwd=REPO, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
    )


def stop_replay(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


async def smoke(a: argparse.Namespace, rep: Report, tmp: Path) -> str:
    base = a.base.rstrip("/")
    # 1. lessons
    try:
        lessons = get_json(base, "/api/lessons")
    except (urllib.error.URLError, OSError, ValueError) as e:
        rep.add("FAIL", "hub reachable", f"GET /api/lessons: {e}")
        return "?"
    rep.add("PASS", "lessons listed", f"{len(lessons)} lesson(s): " + ", ".join(l["id"] for l in lessons)[:60])
    ids = [l["id"] for l in lessons]
    lesson_id = a.lesson or ("demo-v1" if "demo-v1" in ids else (ids[0] if ids else None))
    if lesson_id not in ids:
        rep.add("FAIL", "lesson found", f"{lesson_id!r} is not on the hub")
        return str(lesson_id)
    lesson = get_json(base, f"/api/lessons/{quote(lesson_id)}")
    steps = lesson.get("steps", [])
    total = len(steps)
    manual_steps = [i for i, s in enumerate(steps) if s.get("check_type") == "manual"]
    camera_steps = [i for i, s in enumerate(steps) if s.get("check_type", "camera") == "camera"]

    # 2. video for the fake camera
    if a.video:
        video = a.video
    else:
        video = tmp / Path(lesson.get("video") or "norm.mp4").name
        try:
            download(f"{base}/lessons/{quote(lesson_id)}/{lesson.get('video') or 'norm.mp4'}", video)
        except (urllib.error.URLError, OSError) as e:
            rep.add("FAIL", "lesson video", f"download failed: {e}")
            return lesson_id

    async with websockets.connect(ws_url(base, "/ws/ui"), max_size=None, open_timeout=5) as ws:
        # 3. select
        await next_text(ws, 5)  # the state sent on connect
        await ws.send(json.dumps({"type": "select_lesson", "id": lesson_id}))
        selected = None
        deadline = time.monotonic() + 5
        while selected is None and time.monotonic() < deadline:
            m = await next_text(ws, deadline - time.monotonic())
            if m is None:
                break
            if m.get("type") == "error":
                rep.add("FAIL", "lesson selected", m.get("message", ""))
                return lesson_id
            if (m.get("type") == "state" and m.get("lesson_id") == lesson_id and m.get("step") == 0
                    and m.get("status") != "done"):
                selected = m
        if selected is None:
            rep.add("FAIL", "lesson selected", "no state confirmed the selection in 5 s")
            return lesson_id
        rep.add("PASS", "lesson selected", f"{lesson_id}, {total} steps ({len(camera_steps)} camera, {len(manual_steps)} manual)")
        if total == 0:
            rep.add("SKIP", "camera advance", "lesson has no steps")
            return lesson_id

        # 4. fake camera
        proc = start_replay(video, ws_url(base, "/ws/camera"), a.fps, tmp / "replay.log")
        t0 = time.monotonic()
        cam_at = source = None
        first_cam_adv = None
        manual_sent: dict[int, float] = {}
        manual_ok = None
        done_at = None
        mistakes = 0
        try:
            while time.monotonic() - t0 < a.timeout:
                if first_cam_adv is None and time.monotonic() - t0 > FIRST_ADVANCE_S and camera_steps:
                    break
                if proc.poll() is not None:
                    rep.add("FAIL", "replay running", f"exited with {proc.returncode}; see output below")
                    print((tmp / "replay.log").read_text(errors="replace")[-2000:])
                    break
                m = await next_text(ws, 1.0)
                if m is None:
                    continue
                kind = m.get("type")
                el = time.monotonic() - t0
                if a.verbose:
                    line = fmt(m, total)
                    if line:
                        print(f"  {el:6.1f}s  {line}", flush=True)
                if kind == "state":
                    if m.get("camera_connected") and cam_at is None:
                        cam_at = el
                    if m.get("camera") and source != "file":  # first state may predate the hello
                        source = m["camera"].get("source")
                    if m.get("status") == "done":
                        done_at = el
                        break
                    step = m.get("step", 0)
                    if m.get("status") == "manual" and step not in manual_sent:
                        manual_sent[step] = el
                        await ws.send(json.dumps({"type": "next", "reason": "button", "from": step}))
                elif kind == "advance":
                    if m.get("reason") == "camera" and first_cam_adv is None:
                        first_cam_adv = (el, m.get("from"), m.get("to"))
                    if m.get("reason") == "button" and m.get("from") in manual_sent and manual_ok is None:
                        manual_ok = (m.get("from"), m.get("to"))
                elif kind == "mistake":
                    mistakes += 1
        finally:
            stop_replay(proc)

        el = time.monotonic() - t0
        rep.add("PASS" if cam_at is not None else "FAIL", "camera connected",
                f"after {cam_at:.1f} s" if cam_at is not None else "camera_connected never became true")
        if source is None:
            rep.add("SKIP", "recording banner", "hub sends no state.camera yet")
        else:
            rep.add("PASS" if source == "file" else "FAIL", "recording banner", f"camera.source = {source}")
        if not camera_steps:
            rep.add("SKIP", "camera advance", "lesson has no camera steps")
        elif first_cam_adv:
            t, frm, to = first_cam_adv
            rep.add("PASS", "camera advance", f"step {frm + 1} -> {step_label(to, total)} after {t:.1f} s")
        else:
            rep.add("FAIL", "camera advance", f"none within {FIRST_ADVANCE_S:.0f} s of the camera starting")
        if not manual_steps:
            rep.add("SKIP", "manual next", "lesson has no manual steps")
        elif manual_ok:
            frm, to = manual_ok
            rep.add("PASS", "manual next", f"step {frm + 1} -> {step_label(to, total)}")
        else:
            rep.add("FAIL", "manual next", "sent next on a manual step, no advance" if manual_sent
                    else "never reached a manual step")
        rep.add("PASS" if done_at is not None else "FAIL", "lesson done",
                f"after {done_at:.1f} s" if done_at is not None else f"not done after {el:.0f} s")
        if mistakes:
            rep.add("SKIP", "mistakes seen", f"{mistakes} (information only)")
    return lesson_id


def cmd_run(a: argparse.Namespace) -> int:
    rep = Report()
    with tempfile.TemporaryDirectory(prefix="handover-smoke-") as tmp:
        try:
            lesson_id = asyncio.run(smoke(a, rep, Path(tmp)))
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
            rep.add("FAIL", "websocket", f"{type(e).__name__}: {e}")
            lesson_id = a.lesson or "?"
    return rep.print(f"HandOver smoke  {a.base}  lesson {lesson_id}")


# ---------------------------------------------------------------- watch

async def watch(a: argparse.Namespace) -> None:
    log = open(a.log, "a", encoding="utf-8") if a.log else None
    delay = 1.0
    last_state = None
    total = None
    try:
        while True:
            try:
                async with websockets.connect(ws_url(a.base, "/ws/ui"), max_size=None, open_timeout=5) as ws:
                    print(f"{now_hms()}  connected {ws_url(a.base, '/ws/ui')}", flush=True)
                    delay = 1.0
                    async for raw in ws:
                        if not isinstance(raw, str):
                            continue
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if log:
                            log.write(json.dumps({"t": dt.datetime.now().isoformat(timespec="milliseconds"),
                                                  "msg": msg}) + "\n")
                            log.flush()
                        if msg.get("type") == "state":
                            total = msg.get("total")
                            if raw == last_state:
                                continue
                            last_state = raw
                        line = fmt(msg, total)
                        if line:
                            print(f"{now_hms()}  {line}", flush=True)
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                print(f"{now_hms()}  hub not reachable ({type(e).__name__}); retrying in {delay:.0f} s", flush=True)
            await asyncio.sleep(delay)
            delay = min(10.0, delay * 2)
    finally:
        if log:
            log.close()


def cmd_watch(a: argparse.Namespace) -> int:
    def on_term(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    try:
        asyncio.run(watch(a))
    except KeyboardInterrupt:
        print(f"{now_hms()}  stopped", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="scripts/smoke.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="end-to-end check against a running hub")
    r.add_argument("--base", default="http://localhost:8000")
    r.add_argument("--lesson", help="lesson id (default demo-v1, else the first lesson)")
    r.add_argument("--video", type=Path, help="video for the fake camera (default: the lesson's own norm.mp4)")
    r.add_argument("--fps", type=float, default=1.0)
    r.add_argument("--timeout", type=float, default=120.0, help="seconds to reach done (default 120)")
    r.add_argument("-v", "--verbose", action="store_true", help="print every event while running")
    w = sub.add_parser("watch", help="print every state, advance and mistake, one line each")
    w.add_argument("--base", default="http://localhost:8000")
    w.add_argument("--log", type=Path, help="append every message as a JSON line")
    a = ap.parse_args()
    return cmd_run(a) if a.cmd == "run" else cmd_watch(a)


if __name__ == "__main__":
    sys.exit(main())

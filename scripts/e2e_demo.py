#!/usr/bin/env python3
"""End-to-end test: the real learn screen in Chrome against a mock hub and the replay camera.

    .venv/bin/python scripts/e2e_demo.py [--headed] [--keep]        (Windows: .venv/Scripts/python.exe)

Builds web/ into a temp folder (never touches web/dist), copies lessons/demo-v1 into a temp lessons
folder with a common_mistake on step 2, starts the hub in mock mode on 8095 (no keys, no Databricks, events
to a temp file, HANDOVER_NO_NETWORK=1) with an injected "behind"
mistake on step 2, runs scripts/e2e/learn_flow.mjs in installed Chrome, and starts server.replay once
the page is up. Screenshots, flow.json, summary.json and the hub and replay logs go to
scripts/out/e2e-<time>/. Prints a PASS/FAIL table; exit code 0 only when every row passed.
Everything it starts is stopped at the end, by process group (taskkill /T on Windows). Ports 8095, 8096
and 5192 must be free. The browser is installed Chrome, else Edge (E2E_CHANNEL picks one).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WINDOWS = os.name == "nt"
PY = REPO / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
FLOW = REPO / "scripts" / "e2e" / "learn_flow.mjs"
LESSON = "demo-v1"
MISTAKE = "Flip it over first."
PORT, HTTPS_PORT, VITE_PORT = 8095, 8096, 5192
LOAD_LIMIT = 24


class Rows:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, status: str, name: str, secs: float | None = None, detail: str = "", **extra) -> None:
        self.rows.append({"name": name, "status": status, "ms": round((secs or 0) * 1000), "detail": detail, **extra})

    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.rows)


def http_get(url: str, timeout: float = 3) -> tuple[str, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.headers.get("Content-Type", ""), r.read()


def wait_http(url: str, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            http_get(url, 2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def port_free(port: int) -> bool:
    import socket
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


SECRET_ENV = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def isolated_env() -> dict:
    """This process's environment without model keys, Databricks credentials or HANDOVER_* settings, so the test
    hub never calls an outside service and only the settings given here apply."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("HANDOVER_", "DATABRICKS_")) and k not in SECRET_ENV}


def start(cmd: list[str], cwd: Path, log: Path, env: dict | None = None, pipe: bool = False,
          isolated: bool = False) -> subprocess.Popen:
    """Starts cmd in its own process group so teardown can kill everything it spawns. isolated: start from
    isolated_env() instead of the full environment."""
    out = subprocess.PIPE if pipe else open(log, "wb")
    base = isolated_env() if isolated else dict(os.environ)
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
    text = {"text": True, "encoding": "utf-8", "errors": "replace"} if pipe else {}
    return subprocess.Popen(cmd, cwd=cwd, env={**base, **(env or {})}, stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, **group, **text)


def stop(proc: subprocess.Popen | None, graceful: bool = False) -> None:
    """Stops proc and everything it spawned: SIGTERM then SIGKILL to the group. Windows: with graceful, Ctrl+Break
    to its process group first (the hub shuts down cleanly on it); then taskkill /T /F on the tree if it still
    runs (a browser started by node is not on the console, so only the tree kill reaches it)."""
    if proc is None or proc.poll() is not None:
        return
    if WINDOWS:
        if graceful:
            with contextlib.suppress(OSError):
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(5)
            if proc.poll() is not None:
                return
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
            proc.wait(wait)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            continue


def wait_for_load() -> None:
    if not hasattr(os, "getloadavg"):  # Windows
        return
    while True:
        load = os.getloadavg()[1]
        if load <= LOAD_LIMIT:
            return
        print(f"load {load:.0f} is over {LOAD_LIMIT}, waiting 30 s", flush=True)
        time.sleep(30)


def make_lessons(tmp: Path) -> Path:
    lessons = tmp / "lessons"
    shutil.copytree(REPO / "lessons" / LESSON, lessons / LESSON)
    f = lessons / LESSON / "lesson.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["steps"][1]["common_mistake"] = MISTAKE
    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return lessons


def link_dir(src: Path, dst: Path) -> None:
    """dst points at src: a symlink, or on Windows a directory junction (no admin rights needed)."""
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(src), str(dst))
    else:
        os.symlink(src, dst, target_is_directory=True)


def unlink_dir(link: Path) -> None:
    """Removes a link made by link_dir without touching what it points at."""
    if link.is_symlink() or (WINDOWS and link.is_junction()):
        (os.rmdir if WINDOWS else os.unlink)(link)


def build_web(tmp: Path, out: Path) -> tuple[Path, str]:
    """Copies web/ to tmp/web (no node_modules, dist or screenshots), links node_modules, builds there."""
    web = tmp / "web"
    shutil.copytree(REPO / "web", web, ignore=shutil.ignore_patterns("node_modules", "dist", "screenshots"))
    log = out / "web-build.log"
    how = "node_modules linked"
    npm = shutil.which("npm") or "npm"  # npm.cmd on Windows
    try:
        link_dir(REPO / "web" / "node_modules", web / "node_modules")
    except OSError:
        how = "npm ci in the temp copy"
        with open(log, "ab") as f:
            subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=web, stdout=f, stderr=subprocess.STDOUT,
                           check=True)
    with open(log, "ab") as f:
        subprocess.run([npm, "run", "build"], cwd=web, stdout=f, stderr=subprocess.STDOUT, check=True)
    if not (web / "dist" / "index.html").is_file():
        raise RuntimeError("build finished without dist/index.html")
    return web, how


def run_flow(app: str, out: Path, web: Path, headed: bool, on_ready, timeout: float) -> int | None:
    """Runs learn_flow.mjs, echoing its lines; calls on_ready() when it prints E2E_READY. None on timeout."""
    env = {"E2E_APP": app, "E2E_OUT": str(out), "E2E_WEB": str(REPO / "web"), "E2E_LESSON": LESSON,
           "E2E_MISTAKE": MISTAKE, "E2E_HEADED": "1" if headed else "0"}
    proc = start(["node", str(FLOW)], REPO, out / "flow.log", env, pipe=True)
    log = open(out / "flow.log", "w", encoding="utf-8")

    def pump() -> None:
        for line in proc.stdout:
            log.write(line)
            log.flush()
            line = line.rstrip("\n")
            if line == "E2E_READY":
                on_ready()
            else:
                print(f"  flow  {line}", flush=True)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        stop(proc)
        reader.join(5)
        log.close()
    return proc.returncode


def print_table(rows: list[dict], header: str) -> None:
    print()
    print(header)
    width = max(len(r["name"]) for r in rows)
    print(f"  {'':4s}  {'check':{width}s}  {'at':>6s}  {'took':>7s}  detail")
    for r in rows:
        at = f"{r['at_s']:.1f}s" if r.get("at_s") is not None else ""
        took = f"{r['ms'] / 1000:.1f}s" if r.get("ms") else ""
        print(f"  {r['status']:4s}  {r['name']:{width}s}  {at:>6s}  {took:>7s}  {r['detail']}")
    counted = [r for r in rows if r["status"] != "SKIP"]
    passed = sum(r["status"] == "PASS" for r in counted)
    skipped = len(rows) - len(counted)
    verdict = "FAIL" if any(r["status"] == "FAIL" for r in rows) else "PASS"
    print(f"{verdict} ({passed} of {len(counted)} passed{f', {skipped} skipped' if skipped else ''})")


def main() -> int:
    ap = argparse.ArgumentParser(prog="scripts/e2e_demo.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--headed", action="store_true", help="show the Chrome window")
    ap.add_argument("--keep", action="store_true", help="keep the temp folder (web build and lessons copy)")
    ap.add_argument("--timeout", type=float, default=240, help="seconds for the whole browser flow (default 240)")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # a cp1252 Windows console must not crash on a curly quote

    out = REPO / "scripts" / "out" / f"e2e-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="handover-e2e-"))
    rows = Rows()
    procs: dict[str, subprocess.Popen | None] = {"hub": None, "vite": None, "replay": None}
    base = f"http://localhost:{PORT}"

    try:
        busy = [p for p in (PORT, HTTPS_PORT, VITE_PORT) if not port_free(p)]
        if busy:
            rows.add("FAIL", "ports free", detail=f"in use: {', '.join(map(str, busy))}")
            return 1
        wait_for_load()

        t = time.monotonic()
        lessons = make_lessons(tmp)
        rows.add("PASS", "lessons copy", time.monotonic() - t, f"{LESSON} with step 2 common_mistake, in {lessons}")

        t = time.monotonic()
        try:
            web, how = build_web(tmp, out)
        except (subprocess.CalledProcessError, OSError, RuntimeError) as e:
            rows.add("FAIL", "web build", time.monotonic() - t, f"{e}; see {out / 'web-build.log'}")
            return 1
        rows.add("PASS", "web build", time.monotonic() - t, f"{how}, dist in the temp copy")

        t = time.monotonic()
        env = {"HANDOVER_PORT": str(PORT), "HANDOVER_HTTPS_PORT": str(HTTPS_PORT), "HANDOVER_CERTS": "/nonexistent",
               "HANDOVER_CHECK": "mock", "HANDOVER_MOCK_PASS_SECONDS": "6", "HANDOVER_MOCK_MISTAKE": "behind:1",
               "HANDOVER_LESSONS": str(lessons), "HANDOVER_WEB_DIST": str(web / "dist"),
               # never write into logs/events.jsonl, never build a real model client
               "HANDOVER_EVENTS_JSONL": str(tmp / "events.jsonl"), "HANDOVER_NO_NETWORK": "1",
               "HANDOVER_DATA": str(tmp / "data")}
        procs["hub"] = start([str(PY), "-m", "server.main"], REPO, out / "hub.log", env, isolated=True)
        if not wait_http(f"{base}/api/lessons", 30, procs["hub"]):
            rows.add("FAIL", "hub up", time.monotonic() - t, f"no answer on {base}; see {out / 'hub.log'}")
            return 1
        rows.add("PASS", "hub up", time.monotonic() - t, f"{base}, mock checks, mistake injected on step 2")

        # The hub serves the build when it supports HANDOVER_WEB_DIST; otherwise Vite serves it and proxies.
        t = time.monotonic()
        kind, _ = http_get(f"{base}/")
        app = base
        if "text/html" in kind:
            rows.add("PASS", "app served", time.monotonic() - t, "hub serves the temp build (HANDOVER_WEB_DIST)")
        else:
            app = f"http://localhost:{VITE_PORT}"
            vite = web / "node_modules" / ".bin" / ("vite.cmd" if WINDOWS else "vite")
            procs["vite"] = start([str(vite), "--port", str(VITE_PORT), "--strictPort"],
                                  web, out / "vite.log", {"VITE_API_TARGET": base})
            if not wait_http(app, 30, procs["vite"]):
                rows.add("FAIL", "app served", time.monotonic() - t, f"Vite did not start; see {out / 'vite.log'}")
                return 1
            rows.add("PASS", "app served", time.monotonic() - t, f"hub has no HANDOVER_WEB_DIST, Vite on {VITE_PORT}")

        replay_at: list[float] = []

        def on_ready() -> None:
            procs["replay"] = start([str(PY), "-m", "server.replay", f"lessons/{LESSON}/norm.mp4", "--loop",
                                     "--url", f"ws://localhost:{PORT}/ws/camera"], REPO, out / "replay.log")
            replay_at.append(time.monotonic())

        t = time.monotonic()
        code = run_flow(app, out, web, a.headed, on_ready, a.timeout)
        rp = procs["replay"]
        if not replay_at:
            rows.add("FAIL", "replay camera", detail="the page never became ready, replay not started")
        elif rp is not None and rp.poll() is not None:
            rows.add("FAIL", "replay camera", detail=f"exited with {rp.returncode}; see {out / 'replay.log'}")
        else:
            rows.add("PASS", "replay camera", detail=f"lessons/{LESSON}/norm.mp4 --loop, ran until the end")
        flow_file = out / "flow.json"
        if code is None:
            rows.add("FAIL", "browser flow", time.monotonic() - t, f"timed out after {a.timeout:g} s")
        if flow_file.is_file():
            rows.rows.extend(json.loads(flow_file.read_text(encoding="utf-8"))["rows"])
        elif code is not None:
            rows.add("FAIL", "browser flow", time.monotonic() - t, f"exit {code}, no flow.json; see {out / 'flow.log'}")
        return 1 if rows.failed() else 0
    except KeyboardInterrupt:
        rows.add("FAIL", "interrupted", detail="Ctrl+C")
        return 130
    finally:
        for name in ("replay", "vite", "hub"):
            stop(procs[name], graceful=name in ("replay", "hub"))
        if a.keep:
            print(f"temp folder kept: {tmp}")
        else:
            unlink_dir(tmp / "web" / "node_modules")  # never delete the real web/node_modules through the link
            shutil.rmtree(tmp, ignore_errors=True)
        (out / "summary.json").write_text(json.dumps(
            {"when": dt.datetime.now().isoformat(timespec="seconds"), "app": base, "lesson": LESSON,
             "passed": not rows.failed(), "rows": rows.rows}, indent=2) + "\n", encoding="utf-8")
        print_table(rows.rows, f"HandOver e2e  lesson {LESSON}  hub {base}")
        print(f"screenshots and logs: {out}")


if __name__ == "__main__":
    sys.exit(main())

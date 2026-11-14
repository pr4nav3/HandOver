#!/usr/bin/env python3
"""8 AM rehearsal counter: live hub events plus a tally of planted-flip catches against the bar.

    .venv/bin/python scripts/rehearsal.py [--base http://localhost:8000] [--log FILE] [--goal 18] [--of 20]

Runs `scripts/smoke.py watch --log FILE` and shows its lines. Press keys while folds run:
    t  start a try        c  caught (the planted flip was named)        m  missed
    u  undo the last c/m  q  quit and print the summary
c or m without t counts as a new try. A MISTAKE line from the hub prints a hint; the count is yours.
Every key press is also written to the log as a JSON line, next to the hub events.
Default log: scripts/out/rehearsal-<timestamp>.jsonl. Bar (docs/PLAN.md): 18 of 20, else step 5
becomes manual and the plant moves.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import select
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

HERE = Path(__file__).resolve().parent
lock = threading.Lock()


def say(text: str) -> None:
    with lock:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


class Tally:
    def __init__(self, goal: int, of: int, log: Path) -> None:
        self.goal, self.of, self.log = goal, of, log
        self.results: list[tuple[str, float]] = []  # ("caught"|"missed", seconds from start of try)
        self.started: float | None = None
        self.mistake_seen = False

    def mark(self, event: str, **extra) -> None:
        line = {"t": dt.datetime.now().isoformat(timespec="milliseconds"), "rehearsal": event}
        if event in ("start", "caught", "missed"):
            line["try"] = len(self.results) + (1 if event == "start" else 0)
        line.update(extra)
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def start(self) -> None:
        if self.started is not None:
            say(f"   try {len(self.results) + 1} already running; press c or m to finish it")
            return
        self.started, self.mistake_seen = time.monotonic(), False
        self.mark("start")
        say(f">> try {len(self.results) + 1} started")

    def finish(self, result: str) -> None:
        if self.started is None:
            self.started = time.monotonic()
        took = time.monotonic() - self.started
        self.results.append((result, took))
        self.started = None
        self.mark(result, seconds=round(took, 1))
        say(f">> try {len(self.results)}: {result.upper()} ({took:.0f} s)   {self.line()}")

    def undo(self) -> None:
        if not self.results:
            say("   nothing to undo")
            return
        result, _ = self.results.pop()
        self.mark("undo", removed=result)
        say(f">> undid try {len(self.results) + 1} ({result})   {self.line()}")

    def counts(self) -> tuple[int, int]:
        caught = sum(1 for r, _ in self.results if r == "caught")
        return caught, len(self.results) - caught

    def line(self) -> str:
        caught, missed = self.counts()
        done = caught + missed
        allowed = self.of - self.goal
        if caught >= self.goal:
            status = f"bar met ({self.goal} of {self.of})"
        elif missed > allowed:
            status = f"bar missed: {missed} misses, only {allowed} allowed. Make step 5 manual and move the plant"
        else:
            status = f"on track: need {self.goal - caught} more catches in {max(0, self.of - done)} tries"
        return f"[caught {caught}  missed {missed}  of {done}]  {status}"


def reader(proc: subprocess.Popen, tally: Tally) -> None:
    for raw in proc.stdout:
        text = raw.rstrip("\n")
        say("   " + text)
        if "MISTAKE" in text and not tally.mistake_seen:
            tally.mistake_seen = True
            say("   hint: the hub flagged a mistake. Press c if it named the planted flip.")


def main() -> int:
    ap = argparse.ArgumentParser(prog="scripts/rehearsal.py", description="8 AM rehearsal counter")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--log", type=Path, help="JSON lines log (default scripts/out/rehearsal-<timestamp>.jsonl)")
    ap.add_argument("--goal", type=int, default=18, help="catches needed (default 18)")
    ap.add_argument("--of", type=int, default=20, help="out of this many tries (default 20)")
    a = ap.parse_args()
    if not sys.stdin.isatty():
        print("rehearsal.py reads single key presses, so run it in a terminal.")
        return 2
    log = a.log
    if log is None:
        (HERE / "out").mkdir(exist_ok=True)
        log = HERE / "out" / f"rehearsal-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    tally = Tally(a.goal, a.of, log)

    proc = subprocess.Popen(
        [sys.executable, "-u", str(HERE / "smoke.py"), "watch", "--base", a.base, "--log", str(log)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1,
    )
    threading.Thread(target=reader, args=(proc, tally), daemon=True).start()
    say(f"Rehearsal: bar {a.goal} of {a.of}. Keys: t start, c caught, m missed, u undo, q quit.  Log: {log}")
    tally.mark("session_start", goal=a.goal, of=a.of, base=a.base)

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)  # single keys, no echo; output still prints normally
        while proc.poll() is None:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            key = os.read(fd, 1).decode(errors="ignore").lower()
            if key == "t":
                tally.start()
            elif key in ("c", "m"):
                tally.finish("caught" if key == "c" else "missed")
            elif key == "u":
                tally.undo()
            elif key == "q":
                break
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()

    caught, missed = tally.counts()
    tally.mark("session_end", caught=caught, missed=missed)
    say("")
    say("Rehearsal summary")
    for i, (r, took) in enumerate(tally.results, 1):
        say(f"  try {i:2d}  {r:6s}  {took:5.0f} s")
    say(f"  {tally.line()}")
    say(f"  log: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

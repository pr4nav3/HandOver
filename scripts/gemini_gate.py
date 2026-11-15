#!/usr/bin/env python3
"""Gemini latency check: time real two-image checks and write a latency verdict to a report.

    .venv/bin/python scripts/gemini_gate.py [--lesson lessons/demo-v1] [-n 20] [--step N] [--also-no]

Runs `python -m server.check --time REF LIVE QUESTION -n N` on one camera step of the lesson
(reference frame against itself, so the right answer is yes). --also-no runs a second pass with the
previous step's frame as the live image (the right answer is no). If server.check offers --compare,
that runs too. Writes scripts/out/gemini-gate-<timestamp>.md with p50, p90, errors and the verdict:

    median 2.0 s or less: pass
    2.0 to 2.5 s:         widen the motion gate
    over 2.5 s:           one confident yes plus Next

The live hub gives up on a call after 3 s; here the timeout is raised (default 10 s) so slow calls are
measured instead of cut off, and the report counts how many would have timed out live.
Always times Gemini (HANDOVER_CHECK_PROVIDER=gemini is pinned for the child), even when a Claude key exists.
Refuses without a key (GEMINI_API_KEY, GOOGLE_API_KEY, or the repo .env). The key is never printed.
--mock runs with HANDOVER_CHECK=mock to test this script; its report is marked as not a real measurement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"
LINE = re.compile(r"^\s*(\d+)\s+(yes|no|unsure)\s+conf\s+([\d.]+)\s+(\d+)\s+ms(?:\s+(.*))?$")
MATCH = re.compile(r"^\s*(\d+)\s+match\s+(\S+)\s+conf\s+([\d.]+)\s+(\d+)\s+ms(?:\s+(.*))?$")
ERROR_TAGS = {"timeout", "rate_limited", "error", "no_key"}
LIVE_TIMEOUT_MS = 3000


def have_key() -> bool:
    """True when a key is set. Only checks presence; the value is never read into output."""
    names = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if any(os.environ.get(n, "").strip() for n in names):
        return True
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip().removeprefix("export ").strip() in names and v.strip().strip("'\""):
                    return True
    return False


def pct(sorted_vals: list[int], p: float) -> int:
    return sorted_vals[min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1))))]


def verdict(p50_ms: float) -> str:
    if p50_ms <= 2000:
        return "PASS: median 2.0 s or less. Keep the default frame interval and debounce."
    if p50_ms <= 2500:
        return "WIDEN THE MOTION GATE: median between 2.0 and 2.5 s. Check less often, only on still frames."
    return "ONE CONFIDENT YES PLUS NEXT: median over 2.5 s. Advance on one confident yes; lean on Next."


def run_check(args: list[str], env: dict) -> tuple[int, str, str]:
    p = subprocess.run([sys.executable, "-m", "server.check", *args], cwd=REPO, env=env,
                       capture_output=True, text=True, errors="replace")
    return p.returncode, p.stdout, p.stderr


def scrub(text: str, env: dict) -> str:
    """Belt and braces: never let a key reach the report, even if a library echoes it."""
    for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if env.get(n):
            text = text.replace(env[n], "<key>")
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "<key>", text)


def summarize(name: str, expect: str, stdout: str, stderr: str) -> dict:
    rows = [LINE.match(l) for l in stdout.splitlines()]
    rows = [(m.group(2), float(m.group(3)), int(m.group(4)), (m.group(5) or "").strip()) for m in rows if m]
    lat = sorted(r[2] for r in rows)
    errors = [t for *_, t in rows if t in ERROR_TAGS]
    if not errors:  # older server.check: errors only show as log warnings
        errors = [l for l in stderr.splitlines() if "failed" in l or "timed out" in l]
    own = [l.removeprefix("verdict: ") for l in stdout.splitlines() if l.startswith("verdict: ")]
    return {
        "verdict": own[-1] if own else None,
        "name": name, "expect": expect, "n": len(rows),
        "p50": statistics.median(lat) if lat else None,
        "p90": pct(lat, 0.9) if lat else None, "max": lat[-1] if lat else None,
        "right": sum(1 for r in rows if r[0] == expect),
        "unsure": sum(1 for r in rows if r[0] == "unsure"),
        "over_live_timeout": sum(1 for x in lat if x > LIVE_TIMEOUT_MS),
        "errors": errors,
        "rate_limited": any(e == "rate_limited" or "429" in e or "RESOURCE_EXHAUSTED" in e for e in errors),
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="scripts/gemini_gate.py", description="Gemini latency check")
    ap.add_argument("--lesson", type=Path, default=REPO / "lessons" / "demo-v1", help="lesson folder")
    ap.add_argument("-n", type=int, default=20, help="calls per pass (default 20)")
    ap.add_argument("--step", type=int, help="1-based camera step to time (default: first camera step after step 1)")
    ap.add_argument("--also-no", action="store_true", help="second pass with the previous step's frame (expect no)")
    ap.add_argument("--timeout", type=float, default=10.0, help="seconds per call while measuring (default 10)")
    ap.add_argument("--mock", action="store_true", help="test this script without Gemini (report marked MOCK)")
    a = ap.parse_args()

    env = dict(os.environ)
    # This times Gemini: pin the provider, or auto would time Claude whenever ANTHROPIC_API_KEY is set.
    env["HANDOVER_CHECK_PROVIDER"] = "gemini"
    if a.mock:
        env["HANDOVER_CHECK"] = "mock"
        env["HANDOVER_MOCK_PASS_SECONDS"] = "0"
    else:
        env.pop("HANDOVER_CHECK", None)
        if not have_key():
            print("No Gemini key found, so the latency check cannot run.\n"
                  "Add GEMINI_API_KEY=... to .env at the repo root (or export GEMINI_API_KEY or GOOGLE_API_KEY),\n"
                  "then run this again. Nothing was called and no report was written.")
            return 2
    env["HANDOVER_CHECK_TIMEOUT"] = str(a.timeout)

    lesson_dir = a.lesson.resolve()
    try:
        lesson = json.loads((lesson_dir / "lesson.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read {lesson_dir / 'lesson.json'}: {e}")
        return 1
    steps = lesson.get("steps", [])
    cams = [i for i, s in enumerate(steps) if s.get("check_type", "camera") == "camera"]
    if a.step:
        k = a.step - 1
        if k not in cams:
            print(f"step {a.step} is not a camera step in {lesson_dir.name}")
            return 1
    else:
        later = [i for i in cams if i > 0]
        if not (later or cams):
            print(f"{lesson_dir.name} has no camera steps")
            return 1
        k = (later or cams)[0]
    frame = lambda i: lesson_dir / (steps[i].get("ref_frame") or f"frames/{i + 1:02d}.jpg")
    question = steps[k].get("check_question") or "Is this step finished?"
    model = "mock" if a.mock else env.get("HANDOVER_CHECK_MODEL", "gemini-3.5-flash-lite (default)")

    passes = [("same frame", "yes", frame(k))]
    if a.also_no and k > 0:
        passes.append(("previous step's frame", "no", frame(k - 1)))
    results, raw = [], []
    for name, expect, live in passes:
        print(f"timing {a.n} calls: step {k + 1} reference vs {name} (expect {expect}) ...", flush=True)
        code, out, err = run_check(["--time", str(frame(k)), str(live), question, "-n", str(a.n)], env)
        out, err = scrub(out, env), scrub(err, env)
        print(out, end="")
        if code != 0:
            print(err[-1500:])
            print(f"server.check exited with {code}; no report written.")
            return 1
        results.append(summarize(name, expect, out, err))
        raw.append((name, out, err))

    compare_note = "not available in server.check yet"
    _, help_out, _ = run_check(["--help"], env)
    if "--compare" in help_out:
        # Same shape as the live mistake check: references k-1, k, k+1, then the live frame.
        refs = [i for i in (k - 1, k, k + 1) if 0 <= i < len(steps)]
        labels = {i: "ABCDEFGH"[j] for j, i in enumerate(refs)}
        n_cmp = min(a.n, 5)
        print(f"timing {n_cmp} compare calls: refs " + ", ".join(f"{labels[i]}=step {i + 1}" for i in refs)
              + f", live = step {k + 1} (expect {labels[k]}) ...", flush=True)
        code, out, err = run_check(["--compare", *[str(frame(i)) for i in refs], str(frame(k)), "-n", str(n_cmp)], env)
        out = scrub(out, env)
        print(out, end="")
        hits = [m for m in (MATCH.match(l) for l in out.splitlines()) if m]
        right = sum(1 for m in hits if m.group(2) == labels[k])
        compare_note = (f"refs " + ", ".join(f"{labels[i]} = step {i + 1}" for i in refs)
                        + f"; live = step {k + 1}; right answer {labels[k]}: {right} of {len(hits)}\n" + out.strip("\n"))
        if code != 0:
            compare_note += "\n" + scrub(err, env).strip()[-1500:]

    main_r = results[0]
    seen = re.search(r"^model (\S+)", raw[0][1], re.M)
    if seen:
        model = seen.group(1)
    final = main_r["verdict"] or (verdict(main_r["p50"]) if main_r["p50"] is not None else "NO DATA")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    OUT.mkdir(exist_ok=True)
    report = OUT / f"gemini-gate-{stamp}.md"
    fmt_ms = lambda v: "n/a" if v is None else f"{v / 1000:.2f} s"
    lines = [
        f"# Gemini latency check, {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "**MOCK RUN: no Gemini calls were made. This is not a real measurement.**" if a.mock else "",
        "",
        f"- Model: `{model}`",
        f"- Lesson: `{lesson_dir.name}`, step {k + 1}: \"{steps[k].get('title', '')}\"",
        f"- Question: \"{question}\"",
        f"- Calls per pass: {a.n}; measuring timeout {a.timeout:g} s (the live hub uses 3 s)",
        "",
        f"## Verdict: {final}",
        "",
        "Rule: median 2.0 s or less passes; 2.0 to 2.5 s widens the motion gate; "
        "over 2.5 s means one confident yes plus Next.",
        "",
        "| Pass | Expect | Calls | p50 | p90 | Max | Right answer | Unsure | Over 3 s | Errors | 429 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['name']} | {r['expect']} | {r['n']} | {fmt_ms(r['p50'])} | {fmt_ms(r['p90'])} | "
                     f"{fmt_ms(r['max'])} | {r['right']} of {r['n']} | {r['unsure']} | {r['over_live_timeout']} | "
                     f"{len(r['errors'])} | {'yes' if r['rate_limited'] else 'no'} |")
    notes = []
    if any(r["rate_limited"] for r in results):
        notes.append("Rate limited (429) during the run: the live breaker would turn checks off for 30 s. "
                     "Check the limits page for this key before relying on it.")
    if any(r["errors"] for r in results):
        notes.append("Errors and timeouts count as unsure; their latency is included above.")
    if notes:
        lines += ["", "## Notes", *[f"- {n}" for n in notes]]
    lines += ["", "## Compare", "", "```", compare_note, "```", "", "## Raw output"]
    for name, out, err in raw:
        lines += ["", f"### {name}", "", "```", out.strip("\n"), *([l for l in err.splitlines() if "WARNING" in l][:20]), "```"]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nlatency verdict: {final}")
    print(f"report: {report.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

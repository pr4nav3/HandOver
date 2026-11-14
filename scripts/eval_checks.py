"""Score a lesson's camera check questions before a learner meets them.

    .venv/bin/python scripts/eval_checks.py lessons/demo-v1 [--n 1] [--next] [--mock] [--provider P]

For each camera step k it asks the real check (server.check.check_frame):
  own   reference k against itself          expect yes
  prev  reference k against reference k-1   expect no (step 1 has no previous)
  next  reference k against reference k+1   reported only, with --next; a later
        state may still satisfy the question, so neither answer is wrong

A step passes when every own probe is a confident yes (HANDOVER_MIN_CONF, 0.8)
and every prev probe is a no. Steps that fail are recommended "make manual".
A probe whose call errored (timeout, rate limit, no key) is left out of every
rate; a step with no answered probe is "not scored (errors)", and the run exits
1 when every call errored.
Prints a table and writes markdown to scripts/out/eval-<id>-<timestamp>.md.

--provider picks who answers: current (default: whatever the hub would use,
HANDOVER_CHECK_PROVIDER or auto, which is Claude when ANTHROPIC_API_KEY is
found, else Gemini), claude, or gemini. The report names the provider and model
that actually ran. Needs that provider's key (ANTHROPIC_API_KEY, or
GEMINI_API_KEY / GOOGLE_API_KEY, in the environment or the repo .env); the key
is never printed. --mock runs offline: identical images say yes, others no.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
from lesson_lint import resolve  # noqa: E402

KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
CLAUDE_KEY_NAMES = ("ANTHROPIC_API_KEY",)
PROVIDERS = ("current", "claude", "gemini")
ANSWERS = ("yes", "no", "unsure")


@dataclass
class Probe:
    kind: str  # own, prev, next
    done: str  # yes, no, unsure
    confidence: float
    latency_ms: int
    error: str | None = None  # timeout, rate_limited, error, no_key: the check never answered


@dataclass
class StepScore:
    n: int
    title: str
    question: str
    probes: list[Probe]
    min_conf: float

    def _of(self, kind: str) -> list[Probe]:
        """Probes of one kind that got an answer; errored probes say nothing about the question."""
        return [p for p in self.probes if p.kind == kind and p.error is None]

    def _has(self, kind: str) -> bool:
        return any(p.kind == kind for p in self.probes)

    @property
    def errors(self) -> int:
        return sum(p.error is not None for p in self.probes)

    @property
    def scored(self) -> bool:
        """At least one answered own probe, and one answered prev probe when step k-1 exists."""
        return bool(self._of("own")) and (not self._has("prev") or bool(self._of("prev")))

    @property
    def own_yes(self) -> float | None:
        own = self._of("own")
        return sum(p.done == "yes" and p.confidence >= self.min_conf for p in own) / len(own) if own else None

    @property
    def prev_no(self) -> float | None:
        prev = self._of("prev")
        return sum(p.done == "no" for p in prev) / len(prev) if prev else None

    @property
    def next_yes(self) -> float | None:
        nxt = self._of("next")
        return sum(p.done == "yes" for p in nxt) / len(nxt) if nxt else None

    @property
    def mean_conf(self) -> float | None:
        scored = [p.confidence for p in self._of("own") + self._of("prev")]
        return statistics.fmean(scored) if scored else None

    @property
    def mean_latency(self) -> float:
        return statistics.fmean(p.latency_ms for p in self.probes) if self.probes else 0.0

    @property
    def passed(self) -> bool:
        return self.scored and self.own_yes == 1.0 and (self.prev_no is None or self.prev_no == 1.0)

    @property
    def verdict(self) -> str:
        return "ok" if self.passed else "make manual" if self.scored else "not scored (errors)"


# ---------------------------------------------------------------- key

def has_key(environ: dict | None = None, env_file: Path | None = None, names: tuple = KEY_NAMES) -> bool:
    """True when a key (Gemini by default) is set in the environment or the .env file. Never returns or prints
    the key."""
    environ = os.environ if environ is None else environ
    if any(environ.get(k, "").strip() for k in names):
        return True
    env_file = REPO / ".env" if env_file is None else env_file
    if not env_file.is_file():
        return False
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if "=" not in line or line.startswith("#"):
            continue
        k, v = line.split("=", 1)
        if k.strip().removeprefix("export ").strip() in names and v.strip().strip("\"'"):
            return True
    return False


# ---------------------------------------------------------------- checkers

async def mock_check(ref: bytes, live: bytes, question: str) -> Probe:
    """Offline stand-in: yes 0.9 for the same image, no 0.85 otherwise."""
    if ref == live:
        return Probe("", "yes", 0.9, 0)
    return Probe("", "no", 0.85, 0)


def resolve_provider(choice: str) -> str:
    """claude or gemini: the provider the real check will use in this process. Pins HANDOVER_CHECK_PROVIDER
    for --provider claude or gemini; current leaves it as the hub would see it."""
    os.environ.pop("HANDOVER_CHECK", None)  # this process always uses the real check
    if choice in ("claude", "gemini"):
        os.environ["HANDOVER_CHECK_PROVIDER"] = choice
    sys.path.insert(0, str(REPO))
    from server import check

    return check.provider()


def provider_label() -> str:
    """The provider and model server.check will call, for example "claude claude-haiku-5-5"."""
    from server import check

    return f"{check.provider()} {check.active_model()}"


def real_checker():
    """Wrap server.check.check_frame (positional ref, live, question) into a Probe. Call resolve_provider first."""
    from server.check import check_frame

    async def run(ref: bytes, live: bytes, question: str) -> Probe:
        r = await check_frame(ref, live, question)
        return Probe("", str(r.done), float(r.confidence), int(r.latency_ms), getattr(r, "error", None))

    return run


# ---------------------------------------------------------------- evaluation

def load_steps(folder: Path) -> tuple[str, list[dict]]:
    data = json.loads((folder / "lesson.json").read_text(encoding="utf-8"))
    steps = data.get("steps", [])
    out = []
    for i, s in enumerate(steps, 1):
        out.append({
            "n": i,
            "title": s.get("title", ""),
            "type": s.get("check_type", "camera"),
            "question": (s.get("check_question", "Is this step finished?") or "").strip(),
            "frame": folder / (s.get("ref_frame") or f"frames/{i:02d}.jpg"),
        })
    return data.get("id", folder.name), out


async def evaluate(steps: list[dict], checker, n: int, with_next: bool, pause: float,
                   min_conf: float, progress=None) -> list[StepScore]:
    frames = {s["n"]: s["frame"].read_bytes() for s in steps if s["frame"].is_file()}
    scores = []
    for s in steps:
        if s["type"] != "camera" or not s["question"] or s["n"] not in frames:
            continue
        k = s["n"]
        pairs = [("own", frames[k])]
        if k - 1 in frames:
            pairs.append(("prev", frames[k - 1]))
        if with_next and k + 1 in frames:
            pairs.append(("next", frames[k + 1]))
        probes = []
        for kind, live in pairs:
            for _ in range(n):
                p = await checker(frames[k], live, s["question"])
                p.kind = kind
                probes.append(p)
                if progress:
                    progress(k, p)
                if pause:
                    await asyncio.sleep(pause)
        scores.append(StepScore(k, s["title"], s["question"], probes, min_conf))
    return scores


# ---------------------------------------------------------------- output

def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def table_rows(scores: list[StepScore], with_next: bool) -> tuple[list[str], list[list[str]]]:
    head = (["Step", "Own yes", "Prev no"] + (["Next yes"] if with_next else [])
            + ["Mean conf", "Latency", "Errors", "Verdict"])
    rows = []
    for s in scores:
        row = [f"{s.n} {s.title}".strip(), pct(s.own_yes), pct(s.prev_no)]
        if with_next:
            row.append(pct(s.next_yes))
        conf = "n/a" if s.mean_conf is None else f"{s.mean_conf:.2f}"
        row += [conf, f"{s.mean_latency:.0f} ms", str(s.errors), s.verdict]
        rows.append(row)
    return head, rows


def confusion(scores: list[StepScore]) -> dict:
    """Counts of answers for probes that expect yes (own) and no (prev)."""
    out = {"yes": {"yes": 0, "no": 0, "unsure": 0}, "no": {"yes": 0, "no": 0, "unsure": 0}}
    for s in scores:
        for p in s.probes:
            if p.kind in ("own", "prev") and p.error is None:
                out["yes" if p.kind == "own" else "no"][p.done if p.done in ANSWERS else "unsure"] += 1
    return out



def render_text(scores: list[StepScore], with_next: bool) -> str:
    head, rows = table_rows(scores, with_next)
    widths = [max(len(head[i]), *(len(r[i]) for r in rows)) for i in range(len(head))] if rows else [len(h) for h in head]
    lines = ["  ".join(h.ljust(w) for h, w in zip(head, widths)).rstrip()]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    return "\n".join(lines)


def render_markdown(lesson_id: str, mode: str, n: int, with_next: bool, scores: list[StepScore],
                    skipped: list[dict], stamp: str) -> str:
    head, rows = table_rows(scores, with_next)
    md = [f"# Check eval: {lesson_id}", "",
          f"- When: {stamp}", f"- Checker: {mode}", f"- Probes per pair: {n}",
          f"- Pass rule: every own probe is yes at confidence {scores[0].min_conf if scores else 0.8:.2f}+, "
          "every prev probe is no", ""]
    md += ["## Per step", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    md += ["| " + " | ".join(r) + " |" for r in rows]
    if skipped:
        md += ["", "Not scored: " + ", ".join(f"step {s['n']} ({s['why']})" for s in skipped) + "."]

    c = confusion(scores)
    md += ["", "## Confusion (own and prev probes)", "",
           "| Expected | Got yes | Got no | Got unsure |", "|---|---|---|---|",
           f"| yes (own) | {c['yes']['yes']} | {c['yes']['no']} | {c['yes']['unsure']} |",
           f"| no (prev) | {c['no']['yes']} | {c['no']['no']} | {c['no']['unsure']} |"]
    false_pass = c["no"]["yes"]
    md += ["", f"False passes (a previous state judged done): {false_pass}."]
    errors = [p.error for s in scores for p in s.probes if p.error]
    if errors:
        kinds = ", ".join(f"{k} {errors.count(k)}" for k in sorted(set(errors)))
        md += ["", f"Errored probes, left out of every rate above: {len(errors)} ({kinds}). "
               "Rerun later or with a larger --pause."]

    if with_next:
        md += ["", "Next probes are informational: a later state can still satisfy an earlier question."]

    failing = [s for s in scores if s.scored and not s.passed]
    unscored = [s for s in scores if not s.scored]
    md += ["", "## Recommendation", ""]
    if not failing and not unscored:
        md.append("Every scored step passed. Keep them as camera steps.")
    for s in unscored:
        md.append(f"- Step {s.n}: not scored, every probe it needed errored. No recommendation.")
    for s in failing:
        why = []
        if s.own_yes is not None and s.own_yes < 1.0:
            why.append(f"own yes {pct(s.own_yes)}")
        if s.prev_no is not None and s.prev_no < 1.0:
            why.append(f"prev no {pct(s.prev_no)}")
        md.append(f"- Step {s.n}: make manual, or rewrite the question ({', '.join(why)}). Question: \"{s.question}\"")
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None, checker=None) -> int:
    """checker: optional async (ref, live, question) -> Probe, used by tests in place of --mock."""
    ap = argparse.ArgumentParser(prog="eval_checks.py", description="Score a lesson's camera check questions.")
    ap.add_argument("lesson", help="lesson folder, for example lessons/demo-v1")
    ap.add_argument("--n", type=int, default=1, help="probes per image pair (default 1)")
    ap.add_argument("--next", action="store_true", help="also probe reference k against k+1 (reported separately)")
    ap.add_argument("--mock", action="store_true", help="offline: no model, identical images say yes")
    ap.add_argument("--provider", choices=PROVIDERS, default="current",
                    help="who answers: current (default, what the hub would use), claude, or gemini")
    ap.add_argument("--pause", type=float, default=None, help="seconds between model calls (default 1, mock 0)")
    ap.add_argument("--out", default=str(SCRIPTS / "out"), help="folder for the markdown report")
    a = ap.parse_args(argv)
    if a.n < 1:
        ap.error("--n must be 1 or more")

    folder = resolve(a.lesson)
    if not (folder / "lesson.json").is_file():
        print(f"eval_checks: {a.lesson}: no lesson.json there", file=sys.stderr)
        return 2
    try:
        lesson_id, steps = load_steps(folder)
    except (OSError, ValueError, AttributeError, TypeError) as e:
        print(f"eval_checks: lesson.json unreadable ({type(e).__name__}); run scripts/lesson_lint.py first",
              file=sys.stderr)
        return 2

    if checker is not None:
        mode = "injected (test)"
    elif a.mock:
        checker, mode = mock_check, "mock (offline)"
    else:
        prov = resolve_provider(a.provider)
        names = CLAUDE_KEY_NAMES if prov == "claude" else KEY_NAMES
        if not has_key(names=names):
            print(f"eval_checks: no {prov} key found. Set {' or '.join(names)} or add it to .env, "
                  "or run with --mock for an offline dry run.", file=sys.stderr)
            return 2
        checker = real_checker()
        mode = provider_label()
    pause = a.pause if a.pause is not None else (0.0 if a.mock or mode.startswith("injected") else 1.0)
    min_conf = float(os.environ.get("HANDOVER_MIN_CONF", "0.8"))

    skipped = []
    for s in steps:
        if s["type"] != "camera":
            skipped.append({"n": s["n"], "why": "manual"})
        elif not s["question"]:
            skipped.append({"n": s["n"], "why": "no question"})
        elif not s["frame"].is_file():
            skipped.append({"n": s["n"], "why": "frame missing"})

    def progress(k: int, p: Probe) -> None:
        err = f"  error: {p.error}" if p.error else ""
        print(f"  step {k} {p.kind:4s}  {p.done:6s}  conf {p.confidence:.2f}  {p.latency_ms} ms{err}", flush=True)

    print(f"{lesson_id}: scoring with {mode}")
    t0 = time.monotonic()
    scores = asyncio.run(evaluate(steps, checker, a.n, a.next, pause, min_conf, progress))
    print()
    print(render_text(scores, a.next) if scores else "No camera steps to score.")

    now = datetime.now()
    md = render_markdown(lesson_id, mode, a.n, a.next, scores, skipped, now.strftime("%Y-%m-%d %H:%M:%S"))
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"eval-{lesson_id}-{now.strftime('%Y%m%d-%H%M%S')}.md"
    out.write_text(md, encoding="utf-8")

    failing = [s.n for s in scores if s.scored and not s.passed]
    unscored = [s.n for s in scores if not s.scored]
    passed = sum(s.passed for s in scores)
    c = confusion(scores)
    print()
    print(f"{passed} of {len(scores)} steps pass, {c['no']['yes']} false passes, "
          f"{time.monotonic() - t0:.1f} s. Make manual: {', '.join(map(str, failing)) or 'none'}."
          + (f" Not scored (errors): {', '.join(map(str, unscored))}." if unscored else ""))
    print(f"Report: {out}")
    probes = [p for s in scores for p in s.probes]
    if probes and all(p.error for p in probes):
        print("eval_checks: every check call failed (timeout, rate limit or error); nothing was scored.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Accuracy and latency benchmark for the live camera check, on held-out images.

    .venv/bin/python scripts/accuracy.py --provider claude [--model claude-haiku-5-5] [--n 3]
        [--max-usd 0.50] [--no-prev-ref] [--debounce] [--lesson lessons/synthetic-fortune-teller-v1]
        [--variants DIR] [--seed 1001] [--flip-step 5] [--only 4,5]

For each camera step k it calls server.check.check_frame the way the hub does (reference k,
the previous step's reference as the "before" image unless --no-prev-ref), with a live image
that is never the reference itself: a jittered variant of state k from scripts/synth_folds.py
(or from --variants, files named state<k>_v<ii>.jpg).

  own   ref k vs a variant of state k        expect yes
  prev  ref k vs a variant of state k-1      expect no
  next  ref k vs a variant of state k+1      reported only
  flip  ref of --flip-step vs fresh variants of the state before it: a skipped flip,
        expect no
  cmp   server.check.compare_refs over references k-1, k, k+1 (what the mistake check does):
        on the flip variants while on --flip-step it should match the step before (behind);
        on each own variant it should match k (reported)

A "yes" is what the engine counts: done yes with confidence >= HANDOVER_MIN_CONF (0.8). A false
pass is a yes on an expect-no probe, the worst failure. --debounce adds the engine rule (2
consecutive yes) per step. --max-usd is a hard stop: before every call it checks spend.allow()
and the ledger's total since the run started. Writes scripts/out/accuracy-<provider>-<ts>.md and
a .json with every probe. Exit 1 when every call errored, else 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

DEFAULT_LESSON = REPO / "lessons" / "synthetic-fortune-teller-v1"
MIN_CONF = 0.8
DEBOUNCE_N = 2
FIRST_CALL_ESTIMATE_USD = 0.002  # used for the budget check before any call has been priced
COLUMNS = ("yes", "yes_low", "no", "unsure", "error")


@dataclass
class Task:
    kind: str  # own, prev, next, flip, cmp_flip, cmp_own
    step: int
    live: Path
    expect: object  # "yes", "no", None (report only), or a step number for compares
    question: str = ""
    ref: Optional[Path] = None
    prev_ref: Optional[Path] = None
    refs: list[tuple[int, Path]] = field(default_factory=list)


@dataclass
class Probe:
    kind: str
    step: int
    live: str
    expect: object
    done: str = "unsure"  # check: yes, no, unsure
    confidence: float = 0.0
    latency_ms: int = 0
    error: Optional[str] = None
    cost_usd: float = 0.0
    match: Optional[int] = None  # compares only
    reason: Optional[str] = None

    @property
    def is_compare(self) -> bool:
        return self.kind.startswith("cmp")

    def outcome(self, min_conf: float = MIN_CONF) -> str:
        """yes (what the engine counts), yes_low, no, unsure or error."""
        if self.error:
            return "error"
        if self.done == "yes":
            return "yes" if self.confidence >= min_conf else "yes_low"
        return self.done


# ---------------------------------------------------------------- lesson and plan

def load_lesson(folder: Path) -> list[dict]:
    data = json.loads((folder / "lesson.json").read_text(encoding="utf-8"))
    steps = []
    for s in data["steps"]:
        ref = s.get("ref_frame") or f"frames/{s['n']:02d}.jpg"
        steps.append({"n": s["n"], "title": s["title"], "camera": s.get("check_type") == "camera",
                      "question": s.get("check_question") or "", "ref": folder / ref})
    return steps


def variant(vdir: Path, state: int, i: int) -> Path:
    return vdir / f"state{state}_v{i:02d}.jpg"


def plan(steps: list[dict], vdir: Path, n: int, flip_step: Optional[int], prev_ref: bool = True,
         only: Optional[set[int]] = None) -> list[Task]:
    """Every probe to run, in order. Variants 0..n-1 feed own, prev and next; n..2n-1 feed the flip trap.
    only limits the run to those camera steps."""
    by_n = {s["n"]: s for s in steps}
    tasks: list[Task] = []

    def refs_around(k: int) -> list[tuple[int, Path]]:
        return [(j, by_n[j]["ref"]) for j in (k - 1, k, k + 1) if j in by_n]

    for s in steps:
        if not s["camera"] or (only and s["n"] not in only):
            continue
        k = s["n"]
        before = by_n[k - 1]["ref"] if prev_ref and (k - 1) in by_n else None
        common = {"question": s["question"], "ref": s["ref"], "prev_ref": before}
        for i in range(n):
            tasks.append(Task("own", k, variant(vdir, k, i), "yes", **common))
        if (k - 1) in by_n:
            for i in range(n):
                tasks.append(Task("prev", k, variant(vdir, k - 1, i), "no", **common))
        if (k + 1) in by_n:
            for i in range(n):
                tasks.append(Task("next", k, variant(vdir, k + 1, i), None, **common))
        if k == flip_step and (k - 1) in by_n:
            for i in range(n, 2 * n):
                tasks.append(Task("flip", k, variant(vdir, k - 1, i), "no", **common))
            for i in range(n, 2 * n):
                tasks.append(Task("cmp_flip", k, variant(vdir, k - 1, i), k - 1, question=s["question"],
                                  refs=refs_around(k)))
        if len(refs_around(k)) >= 2:
            for i in range(n):
                tasks.append(Task("cmp_own", k, variant(vdir, k, i), k, question=s["question"], refs=refs_around(k)))
    return tasks


# ---------------------------------------------------------------- budget

class Budget:
    """Hard stop on dollars: the ledger's total since the start plus the priciest call so far
    must stay under max_usd, and spend.allow() must be True. status is server.spend.status."""

    def __init__(self, max_usd: float, status: Optional[Callable] = None, guard: bool = True):
        self.max_usd = max_usd
        self.status = status
        self.guard = guard  # False for providers the ledger does not track (Gemini, fakes)
        self.start = self._total()
        self.priciest = 0.0

    def _total(self) -> float:
        return float(self.status().total_usd) if (self.guard and self.status) else 0.0

    def spent(self) -> float:
        return max(0.0, self._total() - self.start)

    def stop_reason(self) -> Optional[str]:
        if not self.guard or self.status is None:
            return None
        st = self.status()
        if st.blocked:
            return f"spend ledger blocked ({st.blocked})"
        next_call = self.priciest or FIRST_CALL_ESTIMATE_USD
        if self.spent() + next_call > self.max_usd:
            return f"--max-usd {self.max_usd:.2f} reached (spent {self.spent():.4f}, next call up to {next_call:.4f})"
        return None

    def note(self, cost: float) -> None:
        self.priciest = max(self.priciest, cost)


# ---------------------------------------------------------------- running

Checker = Callable[[bytes, bytes, str, Optional[bytes]], Awaitable[Probe]]
Comparer = Callable[[bytes, list[tuple[int, bytes]], str], Awaitable[Probe]]


def real_checker(timeout: Optional[float] = None) -> tuple[Checker, Comparer]:
    from server import check

    async def run_check(ref: bytes, live: bytes, question: str, prev: Optional[bytes]) -> Probe:
        r = await check.check_frame(ref, live, question, prev_ref=prev, timeout=timeout)
        return Probe("", 0, "", None, r.done, r.confidence, r.latency_ms, r.error, r.cost_usd, reason=r.reason)

    async def run_compare(live: bytes, refs: list[tuple[int, bytes]], question: str) -> Probe:
        m = await check.compare_refs(live, refs, question, timeout=timeout)
        return Probe("", 0, "", None, "", m.confidence, m.latency_ms, m.error, m.cost_usd, match=m.step)

    return run_check, run_compare


async def run(tasks: list[Task], checker: Checker, comparer: Comparer, budget: Budget,
              progress: Callable[[str], None] = lambda s: None) -> tuple[list[Probe], Optional[str]]:
    """Sequential, so latency is one call at a time like the hub. Returns probes and a stop reason."""
    cache: dict[Path, bytes] = {}

    def read(p: Optional[Path]) -> Optional[bytes]:
        if p is None:
            return None
        if p not in cache:
            cache[p] = p.read_bytes()
        return cache[p]

    probes: list[Probe] = []
    for i, t in enumerate(tasks, 1):
        why = budget.stop_reason()
        if why:
            return probes, why
        if t.kind.startswith("cmp"):
            r = await comparer(read(t.live), [(j, read(p)) for j, p in t.refs], t.question)  # type: ignore[misc]
        else:
            r = await checker(read(t.ref), read(t.live), t.question, read(t.prev_ref))  # type: ignore[arg-type]
        r.kind, r.step, r.live, r.expect = t.kind, t.step, t.live.name, t.expect
        budget.note(r.cost_usd)
        probes.append(r)
        got = f"match {r.match}" if r.kind.startswith("cmp") else f"{r.done} {r.confidence:.2f}"
        progress(f"[{i}/{len(tasks)}] step {t.step} {t.kind:8s} {t.live.name:16s} {got}"
                 f"{' ' + r.error if r.error else ''} {r.latency_ms} ms")
    return probes, None


# ---------------------------------------------------------------- math

def percentile(vals: list[int], q: float) -> Optional[int]:
    """Nearest-rank on sorted values; None when empty."""
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def confusion(probes: list[Probe], min_conf: float = MIN_CONF) -> dict[str, dict[str, int]]:
    """Rows expect yes / expect no (check probes with an expectation), columns COLUMNS."""
    m = {e: {c: 0 for c in COLUMNS} for e in ("yes", "no")}
    for p in probes:
        if not p.is_compare and p.expect in ("yes", "no"):
            m[p.expect][p.outcome(min_conf)] += 1  # type: ignore[index]
    return m


def yes_precision(m: dict[str, dict[str, int]]) -> Optional[float]:
    tp, fp = m["yes"]["yes"], m["no"]["yes"]
    return tp / (tp + fp) if tp + fp else None


def unsure_rate(probes: list[Probe]) -> Optional[float]:
    answered = [p for p in probes if not p.is_compare and not p.error]
    return sum(p.done == "unsure" for p in answered) / len(answered) if answered else None


def rate(probes: list[Probe], want: Callable[[Probe], bool]) -> tuple[int, int]:
    """(hits, answered) over probes that did not error."""
    ok = [p for p in probes if not p.error]
    return sum(want(p) for p in ok), len(ok)


def debounce_fires(outcomes: list[str], n: int = DEBOUNCE_N) -> int:
    """How often the engine's rule (n consecutive yes) would fire on this ordered sequence."""
    count = fires = 0
    for o in outcomes:
        count = count + 1 if o == "yes" else 0
        if count >= n:
            fires += 1
            count = 0
    return fires


def step_rows(probes: list[Probe], min_conf: float = MIN_CONF) -> list[dict]:
    rows = []
    for k in sorted({p.step for p in probes}):
        mine = [p for p in probes if p.step == k]

        def of(kind: str) -> list[Probe]:
            return [p for p in mine if p.kind == kind]

        own, prev, nxt, flip = of("own"), of("prev"), of("next"), of("flip")
        cmp_own, cmp_flip = of("cmp_own"), of("cmp_flip")
        is_yes = lambda p: p.outcome(min_conf) == "yes"  # noqa: E731
        row = {
            "step": k,
            "own_yes": rate(own, is_yes),
            "prev_no": rate(prev, lambda p: p.done == "no"),
            "prev_false_pass": rate(prev, is_yes),
            "next_yes": rate(nxt, is_yes),
            "flip_no": rate(flip, lambda p: p.done == "no"),
            "flip_false_pass": rate(flip, is_yes),
            "cmp_own": rate(cmp_own, lambda p: p.match == p.expect),
            "cmp_flip": rate(cmp_flip, lambda p: p.match == p.expect),
            "cmp_flip_matches": [p.match for p in cmp_flip if not p.error],
            "errors": sum(1 for p in mine if p.error),
        }
        neg = [p for p in prev + flip if not p.error]
        fp = sum(is_yes(p) for p in neg)
        single = fp / len(neg) if neg else None
        row["debounce"] = {
            "single_false_yes": single,
            "pair_if_independent": single ** 2 if single is not None else None,
            "fires_prev": debounce_fires([p.outcome(min_conf) for p in prev]),
            "fires_flip": debounce_fires([p.outcome(min_conf) for p in flip]),
            "own_pass_if_independent": (row["own_yes"][0] / row["own_yes"][1]) ** 2 if row["own_yes"][1] else None,
            "fires_own": debounce_fires([p.outcome(min_conf) for p in own]),
        }
        rows.append(row)
    return rows


def summarize(probes: list[Probe], min_conf: float = MIN_CONF) -> dict:
    checks = [p for p in probes if not p.is_compare]
    compares = [p for p in probes if p.is_compare]
    m = confusion(probes, min_conf)
    return {
        "rows": step_rows(probes, min_conf),
        "confusion": m,
        "yes_precision": yes_precision(m),
        "unsure_rate": unsure_rate(probes),
        "false_pass": (m["no"]["yes"], sum(m["no"].values()) - m["no"]["error"]),
        "check_latency": (percentile([p.latency_ms for p in checks if not p.error], 0.5),
                          percentile([p.latency_ms for p in checks if not p.error], 0.9)),
        "compare_latency": (percentile([p.latency_ms for p in compares if not p.error], 0.5),
                            percentile([p.latency_ms for p in compares if not p.error], 0.9)),
        "errors": sum(1 for p in probes if p.error),
        "calls": len(probes),
        "cost_sum": sum(p.cost_usd for p in probes),
    }


# ---------------------------------------------------------------- report

def frac(t: tuple[int, int]) -> str:
    return f"{t[0]}/{t[1]}" if t[1] else "n/a"


def pct(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{100 * v:.0f}%"


def ms(v: Optional[int]) -> str:
    return "n/a" if v is None else f"{v} ms"


def markdown(s: dict, meta: dict, steps: list[dict], debounce: bool) -> str:
    q = {st["n"]: st for st in steps}
    out = [
        f"# Camera check accuracy: {meta['provider']} {meta['model']}",
        "",
        "**Synthetic images.** Live images are Pillow renders from scripts/synth_folds.py, not photos. "
        "Re-test on real footage before trusting any number here.",
        "",
        f"- Lesson: `{meta['lesson']}`; held-out variants: `{meta['variants']}` (seed {meta['seed']})",
        f"- Before image (prev_ref): {'on' if meta['prev_ref'] else 'off'}; n per cell: {meta['n']}; "
        f"yes means confidence >= {meta['min_conf']}",
        f"- Calls: {s['calls']} ({s['errors']} errored); started {meta['started']}",
        f"- Cost: ${meta['ledger_delta']:.4f} by the spend ledger (${s['cost_sum']:.4f} summed per call); "
        f"cap --max-usd {meta['max_usd']:.2f}",
    ]
    if meta.get("stopped"):
        out.append(f"- **Stopped early:** {meta['stopped']}")
    out += [
        "",
        "## Summary",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Precision of yes (false passes are the worst failure) | {pct(s['yes_precision'])} |",
        f"| False passes (yes on an expect-no probe) | {frac(s['false_pass'])} |",
        f"| Unsure rate (answered checks) | {pct(s['unsure_rate'])} |",
        f"| Check latency p50 / p90 | {ms(s['check_latency'][0])} / {ms(s['check_latency'][1])} |",
        f"| Compare latency p50 / p90 | {ms(s['compare_latency'][0])} / {ms(s['compare_latency'][1])} |",
        "",
        "## Per step",
        "",
        "| Step | Question | own yes | prev said no | prev false pass | next yes (info) | flip said no | flip false pass | compare own = k | compare flip = behind |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in s["rows"]:
        k = r["step"]
        out.append(f"| {k} | {q[k]['question'] if k in q else ''} | {frac(r['own_yes'])} | {frac(r['prev_no'])} | "
                   f"{frac(r['prev_false_pass'])} | {frac(r['next_yes'])} | {frac(r['flip_no'])} | "
                   f"{frac(r['flip_false_pass'])} | {frac(r['cmp_own'])} | {frac(r['cmp_flip'])} |")
    m = s["confusion"]
    out += [
        "",
        "## Confusion (check calls with an expected answer; next probes left out)",
        "",
        "| Expected | yes (>= min conf) | yes (low conf) | no | unsure | error |",
        "|---|---|---|---|---|---|",
    ]
    for e in ("yes", "no"):
        out.append(f"| {e} | " + " | ".join(str(m[e][c]) for c in COLUMNS) + " |")
    flips = [r for r in s["rows"] if r["flip_no"][1] or r["cmp_flip"][1]]
    for r in flips:
        out += ["", f"## Flip trap (step {r['step']} shown the unflipped state {r['step'] - 1})", "",
                f"- check said no: {frac(r['flip_no'])}; false pass: {frac(r['flip_false_pass'])}",
                f"- compare_refs matched step {r['step'] - 1} (behind): {frac(r['cmp_flip'])}; "
                f"matches seen: {r['cmp_flip_matches']}"]
    if debounce:
        out += [
            "",
            f"## With the engine debounce ({DEBOUNCE_N} consecutive yes at >= {meta['min_conf']})",
            "",
            "Single = share of expect-no probes (prev and flip) answered yes. Real frames of one scene are "
            "correlated, so the true rate after debounce sits between the independent estimate (single squared) "
            "and single itself. Fired = times the rule fired on the probes in the order they ran.",
            "",
            "| Step | single false yes | false pass if independent | fired on prev | fired on flip | true pass if independent | fired on own |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in s["rows"]:
            d = r["debounce"]
            out.append(f"| {r['step']} | {pct(d['single_false_yes'])} | {pct(d['pair_if_independent'])} | "
                       f"{d['fires_prev']} | {d['fires_flip']} | {pct(d['own_pass_if_independent'])} | {d['fires_own']} |")
    out += ["", "## Misses", ""]
    misses = []
    for p in s.get("probes", []):
        if p.is_compare:
            if p.expect is not None and not p.error and p.match != p.expect:
                misses.append(f"- step {p.step} {p.kind} {p.live}: matched {p.match} ({p.confidence:.2f}), expected {p.expect}")
        elif p.expect in ("yes", "no") and not p.error:
            good = p.outcome(meta["min_conf"]) == "yes" if p.expect == "yes" else p.done == "no"
            if not good:
                misses.append(f"- step {p.step} {p.kind} {p.live}: {p.done} {p.confidence:.2f}, expected {p.expect}"
                              f"{' (reason: ' + p.reason + ')' if p.reason else ''}")
    out += misses or ["- none"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main

def ensure_variants(vdir: Path, n: int, seed: int) -> None:
    """Render 2n held-out variants per state with synth_folds if they are not there yet."""
    if all(variant(vdir, k, i).exists() for k in range(1, 9) for i in range(2 * n)):
        return
    import synth_folds
    synth_folds.write_set(vdir, 2 * n, seed, clean=False)


def configure(provider: str, model: Optional[str]) -> None:
    os.environ["HANDOVER_CHECK_PROVIDER"] = provider
    os.environ.pop("HANDOVER_CHECK", None)  # never measure mock mode by accident
    if model:
        os.environ["HANDOVER_CLAUDE_CHECK_MODEL" if provider == "claude" else "HANDOVER_CHECK_MODEL"] = model


def main(argv: Optional[list[str]] = None, checker: Optional[Checker] = None, comparer: Optional[Comparer] = None,
         status: Optional[Callable] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", choices=["claude", "gemini"], default="claude")
    ap.add_argument("--model", help="model id (default: the server's default for the provider)")
    ap.add_argument("--n", type=int, default=3, help="probes per cell")
    ap.add_argument("--max-usd", type=float, default=0.50, help="hard stop on spend for this run")
    ap.add_argument("--no-prev-ref", action="store_true", help="do not show the previous step's reference")
    ap.add_argument("--debounce", action="store_true", help="also simulate the engine's 2-yes rule")
    ap.add_argument("--lesson", type=Path, default=DEFAULT_LESSON)
    ap.add_argument("--variants", type=Path, help="folder of state<k>_v<ii>.jpg (rendered when missing)")
    ap.add_argument("--seed", type=int, default=1001, help="seed for rendered held-out variants")
    ap.add_argument("--flip-step", type=int, default=5)
    ap.add_argument("--only", help="comma-separated camera steps to run, for example 4,5")
    ap.add_argument("--timeout", type=float, help="per-call timeout override (default: HANDOVER_CHECK_TIMEOUT)")
    ap.add_argument("--out", type=Path, default=SCRIPTS / "out")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.n < 1:
        ap.error("--n must be at least 1")

    configure(a.provider, a.model)
    vdir = a.variants or (SCRIPTS / "out" / f"accuracy-variants-{a.seed}")
    ensure_variants(vdir, a.n, a.seed)
    steps = load_lesson(a.lesson)
    only = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None
    tasks = plan(steps, vdir, a.n, a.flip_step, prev_ref=not a.no_prev_ref, only=only)

    fake = checker is not None
    if not fake:
        checker, comparer = real_checker(a.timeout)
        from server import check, spend
        status = spend.status
        model = check.active_model()
    else:
        model = a.model or "fake"
    budget = Budget(a.max_usd, status, guard=(a.provider == "claude" and status is not None))
    started = datetime.now().astimezone()
    say = (lambda s: None) if a.quiet else (lambda s: print(s, flush=True))
    say(f"{len(tasks)} calls planned on {a.lesson.name} with {a.provider} {model}, "
        f"prev_ref {'off' if a.no_prev_ref else 'on'}, cap ${a.max_usd:.2f}")
    t0 = time.monotonic()
    probes, stopped = asyncio.run(run(tasks, checker, comparer, budget, say))  # type: ignore[arg-type]

    s = summarize(probes)
    s["probes"] = probes
    meta = {"provider": a.provider, "model": model, "lesson": str(a.lesson.relative_to(REPO) if a.lesson.is_relative_to(REPO) else a.lesson),
            "variants": str(vdir.relative_to(REPO) if vdir.is_relative_to(REPO) else vdir), "seed": a.seed,
            "prev_ref": not a.no_prev_ref, "n": a.n, "min_conf": MIN_CONF, "max_usd": a.max_usd,
            "started": started.isoformat(timespec="seconds"), "ledger_delta": budget.spent(),
            "stopped": stopped, "wall_s": round(time.monotonic() - t0, 1)}
    text = markdown(s, meta, steps, a.debounce)
    a.out.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    tag = "" if not a.no_prev_ref else "-noprev"
    md = a.out / f"accuracy-{a.provider}{tag}-{stamp}.md"
    md.write_text(text, encoding="utf-8")
    raw = {k: v for k, v in s.items() if k != "probes"} | {"meta": meta, "probes": [asdict(p) for p in probes]}
    md.with_suffix(".json").write_text(json.dumps(raw, indent=1, default=str), encoding="utf-8")
    if not a.quiet:
        print(text)
    print(f"wrote {md}")
    return 1 if probes and all(p.error for p in probes) else 0


if __name__ == "__main__":
    sys.exit(main())

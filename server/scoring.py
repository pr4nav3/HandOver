"""Learner performance rating per step and per run, from real learn events only.

Every step score is a weighted mean of up to five inputs, each scored 0 to 100. The response lists every input,
its raw value, its score, its weight and the rule, so a teacher or learner can see exactly how the number came
about. An input with no data is left out and the other weights are scaled up to fill its share. A step with
no data at all has score null and reason "not enough data"; nothing is guessed.

Inputs (weight, rule):
    time        0.30  your time on the step / the expert's clip length: 100 up to 1.5x, then down to 0 at 4x
    completion  0.30  camera verified 100 (also when the camera saw you were ahead), Next on a manual step 100,
                      Next on a camera step 60, skipped 0
    mistakes    0.15  100, minus 15 per mistake caught and then corrected, minus 40 per mistake left uncorrected
    retries     0.10  100, minus 20 per Back press on this step
    confidence  0.15  the check confidence at verification x 100 (camera-verified steps only)

Run score: the mean of the step scores that exist, 0 to 100. Label: Excellent (90 or more), Good (75 to 89),
Keep practicing (below 75). The tip comes from the weakest step: its common_mistake when the teacher wrote one,
else a hint built from that step's weakest input.
"""

from __future__ import annotations

from typing import Any, Optional

from server import library

WEIGHTS = {"time": 0.30, "completion": 0.30, "mistakes": 0.15, "retries": 0.10, "confidence": 0.15}
RULES = {
    "time": "100 up to 1.5x the expert's clip length, falling to 0 at 4x",
    "completion": "camera verified 100, Next on a manual step 100, Next on a camera step 60, skipped 0",
    "mistakes": "100 minus 15 per mistake caught and corrected, minus 40 per mistake left uncorrected",
    "retries": "100 minus 20 per Back press on this step",
    "confidence": "check confidence at verification x 100, camera-verified steps only",
}
NOT_ENOUGH = "not enough data"


def label(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    return "Keep practicing"


def time_score(ratio: float) -> int:
    if ratio <= 1.5:
        return 100
    return max(0, round(100 - (ratio - 1.5) * 40))


def _component(name: str, value: Any, score: Optional[int]) -> dict:
    return {"name": name, "input": value, "score": score, "weight": WEIGHTS[name], "used": score is not None,
            "rule": RULES[name]}


def _i(v: Any) -> Optional[int]:
    return library.as_int(v)


def score_step(i: int, step: dict, events: list[dict]) -> dict:
    """Score step index i (0-based) of one run's events (in order)."""
    n = step.get("n", i + 1)
    manual_step = step.get("check_type") == "manual"
    advances = [(k, r) for k, r in enumerate(events) if r.get("kind") == "advance"
                and _i(r.get("from_step")) is not None and _i(r.get("to_step")) is not None]
    entered = (any(r.get("kind") == "step_enter" and _i(r.get("step")) == i for r in events)
               or any(_i(r["to_step"]) == i for _, r in advances)
               or (i == 0 and any(r.get("kind") == "run_start" for r in events)))
    done_at, how = None, None
    for k, r in advances:
        frm, to = _i(r["from_step"]), _i(r["to_step"])
        if frm == i and to > i:
            done_at, how = k, ("camera" if r.get("reason") == "camera" else "manual")
            break
        if frm < i < to:
            done_at, how = k, ("camera_ahead" if r.get("reason") == "camera" else "skipped")
            break
    base = {"n": n, "title": step.get("title") or "", "check_type": step.get("check_type", "camera")}
    if how is None:
        reason = NOT_ENOUGH if not entered else "not finished in this run"
        return {**base, "score": None, "reason": reason, "completion": None, "components": []}

    spent = [library.as_float(r.get("step_seconds")) for _, r in advances if _i(r["from_step"]) == i]
    spent = [s for s in spent if s is not None]
    expert = library.step_seconds(step)
    ratio = round(sum(spent) / expert, 2) if spent and expert else None

    completion = {"camera": 100, "camera_ahead": 100, "manual": 100 if manual_step else 60, "skipped": 0}[how]

    mistake_idx = [k for k, r in enumerate(events) if r.get("kind") == "mistake" and _i(r.get("step")) == i]
    corrected = sum(1 for k in mistake_idx if k < done_at and how != "skipped")
    uncorrected = len(mistake_idx) - corrected
    mistakes = max(0, 100 - 15 * corrected - 40 * uncorrected)

    backs = sum(1 for _, r in advances if _i(r["from_step"]) == i and _i(r["to_step"]) < i)
    retries = max(0, 100 - 20 * backs)

    conf = None
    if how == "camera":
        yes = [library.as_float(r.get("confidence")) for k, r in enumerate(events[:done_at])
               if r.get("kind") == "check" and _i(r.get("step")) == i and r.get("done") == "yes"]
        yes = [c for c in yes if c is not None]
        conf = yes[-1] if yes else None

    components = [
        _component("time", {"seconds": round(sum(spent), 2) if spent else None, "expert_seconds": expert,
                            "ratio": ratio}, time_score(ratio) if ratio is not None else None),
        _component("completion", how, completion),
        _component("mistakes", {"caught": len(mistake_idx), "corrected": corrected}, mistakes),
        _component("retries", {"back_presses": backs}, retries),
        _component("confidence", conf, round(conf * 100) if conf is not None else None),
    ]
    used = [c for c in components if c["used"]]
    total_w = sum(c["weight"] for c in used)
    score = round(sum(c["weight"] * c["score"] for c in used) / total_w)
    return {**base, "score": score, "reason": None, "completion": how, "components": components}


def _tip(step: dict, scored: dict) -> Optional[str]:
    if (step.get("common_mistake") or "").strip():
        return f"Step {scored['n']}: {step['common_mistake'].strip()}"
    used = [c for c in scored["components"] if c["used"]]
    if not used:
        return None
    weakest = min(used, key=lambda c: c["score"])
    if weakest["score"] >= 100:
        return None
    n, value = scored["n"], weakest["input"]
    if weakest["name"] == "time":
        return f"Step {n} took {value['ratio']:.1f}x the expert's time. Watch the clip once more before you start it."
    if weakest["name"] == "completion":
        if value == "skipped":
            return f"Step {n} was skipped. Go back and do it with the camera watching."
        return f"Step {n} was finished with Next. Hold the result still in view so the camera can confirm it."
    if weakest["name"] == "mistakes":
        return (f"Step {n} had {value['caught']} mistake(s) caught. Compare your work with the end of the clip "
                f"before moving on.")
    if weakest["name"] == "retries":
        return f"You went back on step {n} {value['back_presses']} time(s). Watch the whole clip before starting it."
    return f"The camera was only {round(value * 100)}% sure on step {n}. Show the finished result clearly in good light."


def score_run(run_id: str, events: list[dict], lesson: dict) -> dict:
    """Per-step scores, the overall score and label, best and weakest step, and one tip."""
    steps = [s for s in lesson.get("steps") or [] if isinstance(s, dict)]
    scored = [score_step(i, s, events) for i, s in enumerate(steps)]
    have = [s for s in scored if s["score"] is not None]
    overall = round(sum(s["score"] for s in have) / len(have)) if have else None
    best = max(have, key=lambda s: s["score"]) if have else None
    weakest = min(have, key=lambda s: s["score"]) if have else None
    tip = _tip(steps[scored.index(weakest)], weakest) if weakest else None
    ts = [str(r.get("ts")) for r in events if r.get("ts")]
    return {
        "run_id": run_id, "lesson_id": events[0].get("lesson_id") if events else None,
        "learner": library.run_learner(events),
        "started_at": min(ts) if ts else None, "ended_at": max(ts) if ts else None,
        "finished": any(r.get("kind") == "run_done" for r in events),
        "score": overall, "label": label(overall), "reason": None if have else NOT_ENOUGH,
        "best_step": {"n": best["n"], "score": best["score"]} if best else None,
        "weakest_step": {"n": weakest["n"], "score": weakest["score"]} if weakest else None,
        "tip": tip, "weights": WEIGHTS, "steps": scored,
    }


def find_run(run_id: str) -> Optional[list[dict]]:
    events = library.runs(library.load_events()).get(run_id)
    return events or None


def summary(scored: dict) -> dict:
    return {k: scored[k] for k in ("run_id", "started_at", "ended_at", "finished", "score", "label", "reason",
                                   "best_step", "weakest_step", "tip")}


def step_averages(lesson_id: str, lesson: dict, since: Optional[str] = None,
                  learners: Optional[set] = None) -> list[dict]:
    """Mean step score over every run of this lesson (optionally only these learners' runs), with n, for insights."""
    all_runs = library.runs(library.lesson_events(lesson_id, since, learners))
    steps = [s for s in lesson.get("steps") or [] if isinstance(s, dict)]
    out = []
    for i, st in enumerate(steps):
        vals = [v for v in (score_step(i, st, evs)["score"] for evs in all_runs.values()) if v is not None]
        out.append({"n": st.get("n", i + 1), "value": round(sum(vals) / len(vals), 1) if vals else None,
                    "n_runs": len(vals)})
    return out

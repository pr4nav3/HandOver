"""Offline tests for synth_folds.py and accuracy.py. Run: .venv/bin/python scripts/test_accuracy.py

No network and no spend: the benchmark runs with fake checkers and a fake ledger.
"""

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import accuracy  # noqa: E402
import synth_folds  # noqa: E402

SMALL = (320, 180)


def diff(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def test_renderer_makes_8_distinct_states():
    imgs = [synth_folds.render(k, seed=3, size=SMALL)[0] for k in range(1, 9)]
    assert all(im.size == SMALL for im in imgs)
    for i in range(8):
        for j in range(i + 1, 8):
            d = diff(imgs[i], imgs[j])
            # 6 vs 7 differ only by a crease, the smallest real difference
            assert d > 0.3, f"states {i + 1} and {j + 1} look the same ({d:.2f})"


def test_crease_step_differs_from_the_flap_step():
    a = synth_folds.render(6, seed=3)[0]
    b = synth_folds.render(7, seed=3)[0]
    assert diff(a, b) > 0.1


def test_render_rejects_bad_state():
    for bad in (0, 9):
        try:
            synth_folds.render(bad, size=SMALL)
        except ValueError:
            continue
        raise AssertionError(f"state {bad} should be rejected")


def test_jitter_is_deterministic_with_a_seed():
    def jpeg(state, seed, v):
        return synth_folds.to_jpeg(synth_folds.render(state, seed=seed, variant=v, size=SMALL, hand_rate=1.0)[0])

    assert jpeg(4, 11, 2) == jpeg(4, 11, 2)
    assert jpeg(4, 11, 2) != jpeg(4, 12, 2)
    assert jpeg(4, 11, 2) != jpeg(4, 11, 3)
    assert synth_folds.jitter_params(5, 11, 0) == synth_folds.jitter_params(5, 11, 0)
    assert synth_folds.jitter_params(5, 11, 0) != synth_folds.jitter_params(5, 11, 1)


def test_variants_are_not_the_clean_reference():
    clean = synth_folds.render(4, seed=7, size=SMALL)[0]
    var = synth_folds.render(4, seed=7, variant=0, size=SMALL)[0]
    assert diff(clean, var) > 1.0


def test_write_set_manifest_marks_synthetic():
    with tempfile.TemporaryDirectory() as t:
        m = synth_folds.write_set(Path(t), 1, 5, size=SMALL)
        assert m["synthetic"] is True and len(m["images"]) == 16
        files = sorted(p.name for p in Path(t).glob("*.jpg"))
        assert "state1_clean.jpg" in files and "state8_v00.jpg" in files
        assert json.loads((Path(t) / "manifest.json").read_text())["seed"] == 5


def test_perspective_coeffs_round_trip():
    src = [(0, 0), (100, 0), (100, 100), (0, 100)]
    dst = [(10, 5), (120, 12), (110, 130), (3, 118)]
    c = synth_folds.perspective_coeffs(src, dst)
    for (sx, sy), d in zip(src, dst):
        x, y = synth_folds.apply_h(c, d)
        assert abs(x - sx) < 1e-6 and abs(y - sy) < 1e-6


# ---------------------------------------------------------------- accuracy math

def P(kind, step, expect, done="no", conf=0.9, error=None, match=None, ms=500, cost=0.0):
    return accuracy.Probe(kind, step, "x.jpg", expect, done, conf, ms, error, cost, match)


def test_outcome_counts_low_confidence_yes_separately():
    assert P("own", 2, "yes", "yes", 0.85).outcome() == "yes"
    assert P("own", 2, "yes", "yes", 0.7).outcome() == "yes_low"
    assert P("own", 2, "yes", "unsure", 0.0, error="timeout").outcome() == "error"


def test_confusion_precision_and_unsure():
    probes = [
        P("own", 2, "yes", "yes", 0.9), P("own", 2, "yes", "yes", 0.9), P("own", 2, "yes", "unsure", 0.4),
        P("prev", 2, "no", "no", 0.9), P("prev", 2, "no", "yes", 0.95),  # one false pass
        P("prev", 2, "no", "yes", 0.6),  # low-confidence yes: not a pass
        P("next", 2, None, "yes", 0.9),  # report only, not in the matrix
        P("cmp_own", 2, 2, "", 0.8, match=2),
    ]
    m = accuracy.confusion(probes)
    assert m["yes"] == {"yes": 2, "yes_low": 0, "no": 0, "unsure": 1, "error": 0}
    assert m["no"] == {"yes": 1, "yes_low": 1, "no": 1, "unsure": 0, "error": 0}
    assert abs(accuracy.yes_precision(m) - 2 / 3) < 1e-9
    assert abs(accuracy.unsure_rate(probes) - 1 / 7) < 1e-9
    s = accuracy.summarize(probes)
    assert s["false_pass"] == (1, 3)
    row = s["rows"][0]
    assert row["own_yes"] == (2, 3) and row["prev_no"] == (1, 3) and row["prev_false_pass"] == (1, 3)
    assert row["next_yes"] == (1, 1) and row["cmp_own"] == (1, 1)


def test_precision_none_without_yes():
    assert accuracy.yes_precision(accuracy.confusion([P("prev", 2, "no", "no")])) is None


def test_errors_are_left_out_of_rates():
    probes = [P("own", 4, "yes", "yes", 0.9), P("own", 4, "yes", "unsure", 0.0, error="timeout")]
    row = accuracy.summarize(probes)["rows"][0]
    assert row["own_yes"] == (1, 1) and row["errors"] == 1


def test_percentile_and_debounce():
    assert accuracy.percentile([], 0.5) is None
    assert accuracy.percentile([100, 300, 200], 0.5) == 200
    assert accuracy.percentile(list(range(1, 11)), 0.9) == 9
    assert accuracy.debounce_fires(["yes", "no", "yes"]) == 0
    assert accuracy.debounce_fires(["yes", "yes", "yes"]) == 1
    assert accuracy.debounce_fires(["yes", "yes", "yes", "yes"]) == 2
    assert accuracy.debounce_fires(["yes", "yes_low", "yes"]) == 0


def test_debounce_estimates():
    probes = [P("prev", 5, "no", "yes", 0.9), P("prev", 5, "no", "no"), P("flip", 5, "no", "yes", 0.9),
              P("flip", 5, "no", "yes", 0.9)]
    d = accuracy.summarize(probes)["rows"][0]["debounce"]
    assert abs(d["single_false_yes"] - 0.75) < 1e-9
    assert abs(d["pair_if_independent"] - 0.5625) < 1e-9
    assert d["fires_prev"] == 0 and d["fires_flip"] == 1


# ---------------------------------------------------------------- plan and end to end with fakes

def fake_lesson(tmp: Path) -> Path:
    folder = tmp / "lesson"
    (folder / "frames").mkdir(parents=True)
    steps = []
    for k in range(1, 9):
        img = synth_folds.render(k, seed=2, size=SMALL)[0]
        img.save(folder / "frames" / f"{k:02d}.jpg")
        cam = k in (2, 4, 5, 6, 8)
        steps.append({"n": k, "title": f"s{k}", "check_type": "camera" if cam else "manual",
                      "check_question": f"q{k}" if cam else "manual", "ref_frame": f"frames/{k:02d}.jpg"})
    (folder / "lesson.json").write_text(json.dumps({"id": "t", "steps": steps}))
    return folder


def test_plan_uses_held_out_variants_and_the_flip_trap():
    with tempfile.TemporaryDirectory() as t:
        folder = fake_lesson(Path(t))
        steps = accuracy.load_lesson(folder)
        tasks = accuracy.plan(steps, Path(t) / "v", 2, 5)
        assert all("_v" in x.live.name for x in tasks), "a live image must never be a reference"
        flip = [x for x in tasks if x.kind == "flip"]
        assert [x.live.name for x in flip] == ["state4_v02.jpg", "state4_v03.jpg"]
        assert all(x.ref.name == "05.jpg" and x.prev_ref.name == "04.jpg" for x in flip)
        cmp_flip = [x for x in tasks if x.kind == "cmp_flip"]
        assert all(x.expect == 4 and [j for j, _ in x.refs] == [4, 5, 6] for x in cmp_flip)
        prev2 = [x for x in tasks if x.kind == "prev" and x.step == 2]
        assert prev2[0].live.name == "state1_v00.jpg" and prev2[0].expect == "no"
        assert not [x for x in tasks if x.kind == "next" and x.step == 8]
        assert {x.step for x in accuracy.plan(steps, Path(t) / "v", 2, 5, only={4, 5})} == {4, 5}
        no_prev = accuracy.plan(steps, Path(t) / "v", 2, 5, prev_ref=False)
        assert all(x.prev_ref is None for x in no_prev)


@dataclass
class FakeStatus:
    total_usd: float
    blocked: object = None


class FakeLedger:
    def __init__(self):
        self.total = 0.0

    def status(self):
        return FakeStatus(self.total)


def make_fakes(ledger: FakeLedger, cost: float = 0.0):
    """An oracle that reads the state number out of the file bytes it was given."""
    names: dict[bytes, int] = {}

    async def checker(ref, live, question, prev):
        ledger.total += cost
        same = names.get(ref) == names.get(live)
        return accuracy.Probe("", 0, "", None, "yes" if same else "no", 0.9, 120, None, cost)

    async def comparer(live, refs, question):
        ledger.total += cost
        hit = [j for j, b in refs if names.get(b) == names.get(live)]
        return accuracy.Probe("", 0, "", None, "", 0.9, 150, None, cost, match=hit[0] if hit else None)

    return checker, comparer, names


def test_end_to_end_with_an_oracle_and_report():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        folder = fake_lesson(tmp)
        vdir = tmp / "v"
        synth_folds.write_set(vdir, 4, 9, size=SMALL, clean=False)
        ledger = FakeLedger()
        checker, comparer, names = make_fakes(ledger)
        for k in range(1, 9):
            names[(folder / "frames" / f"{k:02d}.jpg").read_bytes()] = k
            for i in range(4):
                names[accuracy.variant(vdir, k, i).read_bytes()] = k
        out = tmp / "out"
        rc = accuracy.main(["--lesson", str(folder), "--variants", str(vdir), "--n", "2", "--out", str(out),
                            "--debounce", "--quiet"], checker=checker, comparer=comparer, status=ledger.status)
        assert rc == 0
        md = next(out.glob("accuracy-claude-*.md")).read_text()
        assert "Synthetic images" in md and "Precision of yes" in md and "| 100% |" in md
        assert "Flip trap (step 5" in md and "debounce" in md
        raw = json.loads(next(out.glob("accuracy-claude-*.json")).read_text())
        assert raw["false_pass"] == [0, raw["false_pass"][1]] and raw["yes_precision"] == 1.0


def test_budget_stops_before_overspending():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        folder = fake_lesson(tmp)
        vdir = tmp / "v"
        synth_folds.write_set(vdir, 2, 9, size=SMALL, clean=False)
        ledger = FakeLedger()
        checker, comparer, _ = make_fakes(ledger, cost=0.01)
        out = tmp / "out"
        accuracy.main(["--lesson", str(folder), "--variants", str(vdir), "--n", "1", "--out", str(out),
                       "--max-usd", "0.035", "--quiet"], checker=checker, comparer=comparer, status=ledger.status)
        raw = json.loads(next(out.glob("*.json")).read_text())
        assert len(raw["probes"]) == 3 and "max-usd" in raw["meta"]["stopped"]
        assert ledger.total <= 0.035 + 1e-9


def test_budget_respects_a_blocked_ledger():
    b = accuracy.Budget(1.0, lambda: FakeStatus(0.0, "day"))
    assert "blocked" in b.stop_reason()
    assert accuracy.Budget(1.0, lambda: FakeStatus(0.0), guard=False).stop_reason() is None


def test_every_call_erroring_exits_1():
    async def broken(ref, live, q, prev):
        return accuracy.Probe("", 0, "", None, "unsure", 0.0, 3000, "timeout")

    async def broken_cmp(live, refs, q):
        return accuracy.Probe("", 0, "", None, "", 0.0, 3000, "timeout")

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        folder = fake_lesson(tmp)
        vdir = tmp / "v"
        synth_folds.write_set(vdir, 2, 9, size=SMALL, clean=False)
        rc = accuracy.main(["--lesson", str(folder), "--variants", str(vdir), "--n", "1", "--out", str(tmp / "o"),
                            "--quiet", "--provider", "gemini"], checker=broken, comparer=broken_cmp)
        assert rc == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

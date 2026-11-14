"""Tests for lesson_lint.py and eval_checks.py. Run: .venv/bin/python scripts/test_tools.py

Works on temporary copies; lessons/demo-v1 is only read.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
DEMO = REPO / "lessons" / "demo-v1"
sys.path.insert(0, str(SCRIPTS))

import eval_checks  # noqa: E402
import lesson_lint  # noqa: E402

CLEAN_QUESTIONS = {
    1: "Is there one bar in the middle of the frame?",
    2: "Are there two bars side by side?",
    4: "Are there four bars side by side?",
    5: "Are there five bars side by side?",
}


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8")


def copy_demo(tmp: Path, clean: bool = True) -> Path:
    """A copy of demo-v1 under tmp; with clean=True the questions avoid color words, so it lints all OK."""
    dst = tmp / "demo-v1"
    shutil.copytree(DEMO, dst)
    if clean:
        edit(dst, lambda d: [s.update(check_question=CLEAN_QUESTIONS[s["n"]]) for s in d["steps"]
                             if s["n"] in CLEAN_QUESTIONS])
    return dst


def edit(folder: Path, change) -> None:
    path = folder / "lesson.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def results(folder: Path) -> dict:
    return {c["check"]: (c["result"], c["detail"]) for c in lesson_lint.lint(folder).checks()}


def broken(change_files=None, change_json=None) -> dict:
    with tempfile.TemporaryDirectory() as t:
        folder = copy_demo(Path(t))
        if change_files:
            change_files(folder)
        if change_json:
            edit(folder, change_json)
        return results(folder)


# ---------------------------------------------------------------- lint

def test_demo_passes():
    p = run("lesson_lint.py", str(DEMO))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "0 FAIL" in p.stdout
    data = json.loads(run("lesson_lint.py", str(DEMO), "--json").stdout)
    assert data[0]["id"] == "demo-v1" and data[0]["counts"]["FAIL"] == 0


def test_demo_color_words_warn_and_strict_fails():
    r = results(DEMO)
    assert r["step 1 check"][0] == "WARN" and "blue" in r["step 1 check"][1]
    assert run("lesson_lint.py", str(DEMO), "--strict").returncode == 1


def test_clean_copy_all_ok():
    with tempfile.TemporaryDirectory() as t:
        folder = copy_demo(Path(t))
        rep = lesson_lint.lint(folder)
        assert rep.result() == "OK", lesson_lint.render(rep)
        assert run("lesson_lint.py", str(folder), "--strict").returncode == 0


def test_color_word_added_warns():
    def paint(d):
        d["steps"][1]["check_question"] = "Are there two bars on a green sheet?"
    r = broken(change_json=paint)
    assert r["step 2 check"][0] == "WARN" and "green" in r["step 2 check"][1]
    assert r["step 1 check"][0] == "OK"


def test_missing_clip_fails():
    with tempfile.TemporaryDirectory() as t:
        folder = copy_demo(Path(t))
        (folder / "clips" / "02.mp4").unlink()
        r = results(folder)
        assert r["step 2 files"][0] == "FAIL" and "clips/02.mp4 missing" in r["step 2 files"][1]
        p = run("lesson_lint.py", str(folder))
        assert p.returncode == 1 and "FAIL" in p.stdout


def test_bad_timestamps_fail():
    def swap(d):
        d["steps"][1]["start"], d["steps"][1]["end"] = "00:16", "00:08"
    r = broken(change_json=swap)
    assert r["timing"][0] == "FAIL" and "not before end" in r["timing"][1]

    r = broken(change_json=lambda d: d["steps"][2].update(start="soon"))
    assert r["timing"][0] == "FAIL" and "bad timestamp" in r["timing"][1]

    def overlap(d):
        d["steps"][2]["start"] = "00:12"
    r = broken(change_json=overlap)
    assert r["timing"][0] == "FAIL" and "before step 2 ends" in r["timing"][1]


def test_gap_warns_and_duration_mismatch_fails():
    r = broken(change_json=lambda d: d["steps"][2].update(start="00:17"))
    assert r["timing"][0] == "WARN" and "gap" in r["timing"][1]
    assert r["step 3 clip"][0] == "FAIL" and "start to end is 7.00 s" in r["step 3 clip"][1]


def test_bad_vtt_fails():
    r = broken(lambda f: (f / "captions" / "01.vtt").write_text("hello\n", encoding="utf-8"))
    assert r["step 1 captions"][0] == "FAIL" and "WEBVTT" in r["step 1 captions"][1]

    late = "WEBVTT\n\n00:00:01.000 --> 00:00:12.000\nToo long.\n"
    r = broken(lambda f: (f / "captions" / "01.vtt").write_text(late, encoding="utf-8"))
    assert r["step 1 captions"][0] == "FAIL" and "clip is 8.00 s" in r["step 1 captions"][1]

    garbled = "WEBVTT\n\n0:1 --> 00:00:02.000\nOops.\n"
    r = broken(lambda f: (f / "captions" / "01.vtt").write_text(garbled, encoding="utf-8"))
    assert r["step 1 captions"][0] == "FAIL" and "bad cue time" in r["step 1 captions"][1]


def test_bad_frames():
    from PIL import Image, ImageFilter

    def black(f):
        Image.new("RGB", (1280, 720), (3, 3, 3)).save(f / "frames" / "02.jpg", quality=90)

    def blurry(f):
        with Image.open(DEMO / "frames" / "02.jpg") as im:
            im.filter(ImageFilter.GaussianBlur(60)).save(f / "frames" / "02.jpg", quality=90)

    r = broken(black)
    assert r["step 2 frame"][0] == "FAIL" and "near-black" in r["step 2 frame"][1]
    r = broken(blurry)
    assert r["step 2 frame"][0] == "WARN" and "blurry" in r["step 2 frame"][1]
    r = broken(lambda f: (f / "frames" / "02.jpg").write_bytes(b"not a jpeg"))
    assert r["step 2 frame"][0] == "FAIL" and "does not decode" in r["step 2 frame"][1]


def test_questions_and_new_fields():
    def mess(d):
        s1, s3, s4, s5 = d["steps"][0], d["steps"][2], d["steps"][3], d["steps"][4]
        s1["check_question"] = ""
        s3["check_question"] = "Is it creased?"
        s4.update(ref_time="00:50", common_mistake=3, prerequisites=[4])
        s5["self_test"] = {"own": "maybe", "prev": "no", "ok": True}
        d["safety"] = ["Mind the spokes", ""]
    r = broken(change_json=mess)
    assert r["step 1 check"][0] == "FAIL"
    assert r["step 3 check"][0] == "WARN"
    assert r["step 4 fields"][0] == "FAIL"
    for words in ("ref_time", "common_mistake", "prerequisites"):
        assert words in r["step 4 fields"][1], r["step 4 fields"]
    assert r["step 5 fields"][0] == "FAIL" and "self_test" in r["step 5 fields"][1]
    assert r["top-level fields"][0] == "FAIL" and "safety" in r["top-level fields"][1]


def test_good_new_fields_pass():
    def add(d):
        d["safety"], d["tools"] = ["Keep fingers clear of the fold"], ["bone folder"]
        d["steps"][3].update(ref_time="00:31.5", common_mistake="Flip it over first.",
                             self_test={"own": "yes", "prev": "no", "ok": True})
    r = broken(change_json=add)
    assert r["top-level fields"][0] == "OK" and r["step 4 fields"][0] == "OK", r


def test_numbering_and_bad_json():
    r = broken(change_json=lambda d: d["steps"][1].update(n=7))
    assert r["step numbers"][0] == "FAIL"
    r = broken(lambda f: (f / "lesson.json").write_text("{nope", encoding="utf-8"))
    assert r["lesson.json"][0] == "FAIL"


# ---------------------------------------------------------------- eval

def test_eval_mock_on_demo():
    with tempfile.TemporaryDirectory() as t:
        p = run("eval_checks.py", str(DEMO), "--mock", "--next", "--out", t)
        assert p.returncode == 0, p.stdout + p.stderr
        assert "4 of 4 steps pass" in p.stdout
        reports = list(Path(t).glob("eval-demo-v1-*.md"))
        assert len(reports) == 1
        md = reports[0].read_text(encoding="utf-8")
        assert "| no (prev) | 0 | 3 | 0 |" in md and "step 3 (manual)" in md


def test_eval_recommends_manual():
    import asyncio

    async def always_yes(ref, live, q):
        return eval_checks.Probe("", "yes", 0.95, 5)

    _, steps = eval_checks.load_steps(DEMO)
    scores = asyncio.run(eval_checks.evaluate(steps, always_yes, 2, False, 0, 0.8))
    assert [s.n for s in scores] == [1, 2, 4, 5]
    assert scores[0].passed and not any(s.passed for s in scores[1:])
    md = eval_checks.render_markdown("demo-v1", "test", 2, False, scores, [], "now")
    assert "Step 2: make manual" in md and "False passes (a previous state judged done): 6." in md


def test_eval_key_detection_never_needs_a_real_key():
    with tempfile.TemporaryDirectory() as t:
        env_file = Path(t) / ".env"
        assert not eval_checks.has_key({}, env_file)
        env_file.write_text("# GEMINI_API_KEY=commented\nGEMINI_API_KEY=\n", encoding="utf-8")
        assert not eval_checks.has_key({}, env_file)
        env_file.write_text("export GOOGLE_API_KEY='x'\n", encoding="utf-8")
        assert eval_checks.has_key({}, env_file)
        assert eval_checks.has_key({"GEMINI_API_KEY": "x"}, Path(t) / "none")


def test_eval_errored_probes_are_not_wrong_answers():
    import asyncio

    async def rate_limited(ref, live, q):
        return eval_checks.Probe("", "unsure", 0.0, 3000, "rate_limited")

    _, steps = eval_checks.load_steps(DEMO)
    scores = asyncio.run(eval_checks.evaluate(steps, rate_limited, 1, False, 0, 0.8))
    assert all(not s.scored and not s.passed and s.verdict == "not scored (errors)" for s in scores)
    md = eval_checks.render_markdown("demo-v1", "test", 1, False, scores, [], "now")
    assert "make manual" not in md and "rate_limited 7" in md
    assert "| yes (own) | 0 | 0 | 0 |" in md

    calls = []

    async def flaky(ref, live, q):  # every other call times out; answers are otherwise right
        calls.append(1)
        if len(calls) % 2 == 0:
            return eval_checks.Probe("", "unsure", 0.0, 3000, "timeout")
        return await eval_checks.mock_check(ref, live, q)

    scores = asyncio.run(eval_checks.evaluate(steps, flaky, 2, False, 0, 0.8))
    assert all(s.passed and s.errors > 0 for s in scores), [(s.n, s.verdict) for s in scores]


def test_eval_exits_nonzero_when_every_call_errors():
    async def timeout(ref, live, q):
        return eval_checks.Probe("", "unsure", 0.0, 3000, "timeout")

    async def first_errors(ref, live, q):  # one errored probe, the rest answered
        first_errors.n = getattr(first_errors, "n", 0) + 1
        if first_errors.n == 1:
            return eval_checks.Probe("", "unsure", 0.0, 3000, "error")
        return await eval_checks.mock_check(ref, live, q)

    with tempfile.TemporaryDirectory() as t:
        assert eval_checks.main([str(DEMO), "--out", t], checker=timeout) == 1
        assert eval_checks.main([str(DEMO), "--out", t, "--n", "2"], checker=first_errors) == 0


def test_eval_null_ref_frame_uses_default():
    with tempfile.TemporaryDirectory() as t:
        folder = copy_demo(Path(t))
        edit(folder, lambda d: d["steps"][1].update(ref_frame=None))
        _, steps = eval_checks.load_steps(folder)
        assert steps[1]["frame"] == folder / "frames" / "02.jpg"
        p = run("eval_checks.py", str(folder), "--mock", "--out", t)
        assert p.returncode == 0 and "4 of 4 steps pass" in p.stdout, p.stdout + p.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

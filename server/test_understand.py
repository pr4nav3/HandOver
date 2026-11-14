"""Understanding tests: rubric schema and file, live request shape, guards, MistakeTracker timing, budget. No network.

Run: .venv/bin/python -m server.test_understand (or pytest if installed).

Hermetic like test_check: HANDOVER_NO_NETWORK=1, the real Claude client is replaced by one that fails the test,
a fake key and a temp spend ledger per test. Works on a temp copy of lessons/synthetic-fortune-teller-v1.
"""

import asyncio
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

_TMP = Path(tempfile.mkdtemp(prefix="handover-test-understand-"))
os.environ["HANDOVER_NO_NETWORK"] = "1"
os.environ["HANDOVER_CLAUDE_SPEND_FILE"] = str(_TMP / "spend.json")
os.environ.pop("HANDOVER_CHECK", None)
for _name in ("HANDOVER_UNDERSTAND_MODEL", "HANDOVER_UNDERSTAND_TIMEOUT", "HANDOVER_LIVE_MISTAKE_MIN_CONF",
              "HANDOVER_LIVE_MISTAKE_REPEAT", "HANDOVER_LIVE_MISTAKE_CLEAR", "HANDOVER_LIVE_MISTAKE_COOLDOWN_S",
              "HANDOVER_CLAUDE_CACHE"):
    os.environ.pop(_name, None)

import anthropic  # noqa: E402

from server import check, spend, understand  # noqa: E402
from server.understand import MistakeTracker, Understanding  # noqa: E402


def _no_real_claude():
    raise AssertionError("a test reached the real Claude client")


check._get_claude = _no_real_claude

LESSON = check.REPO / "lessons" / "synthetic-fortune-teller-v1"
CAMERA = [2, 4, 5, 6, 8]
_ids = itertools.count()


def _run(coro):
    return asyncio.run(coro)


def _restore(k, v):
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v


@contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        _restore(k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            _restore(k, v)


def _msg(text=None, stop="end_turn", usage=None, category=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
        stop_details=SimpleNamespace(category=category) if category else None,
        usage=usage or SimpleNamespace(input_tokens=2000, output_tokens=80, cache_read_input_tokens=0,
                                       cache_creation_input_tokens=0, cache_creation=None))


class _Fake:
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        out = self.behavior()
        if isinstance(out, BaseException):
            raise out
        if out == "hang":
            await asyncio.sleep(10)
        return out


@contextmanager
def claude(behavior, **extra_env):
    """A fake client, a fake key and a fresh temp ledger."""
    fake = _Fake(behavior)
    values = {"ANTHROPIC_API_KEY": "sk-ant-test-not-real",
              "HANDOVER_CLAUDE_SPEND_FILE": str(_TMP / f"spend-{next(_ids)}.json"), **extra_env}
    saved_get = check._get_claude
    check._get_claude = lambda: fake
    try:
        with env(**values):
            yield fake
    finally:
        check._get_claude = saved_get


def _lesson_copy(video: bool = True) -> Path:
    dst = _TMP / f"lesson-{next(_ids)}"
    (dst / "frames").mkdir(parents=True)
    for name in ("lesson.json", "extraction.json") + (("norm.mp4",) if video else ()):
        shutil.copy2(LESSON / name, dst / name)
    for f in (LESSON / "frames").glob("[0-9][0-9].jpg"):
        shutil.copy2(f, dst / "frames" / f.name)
    return dst


def _raw_step(n, **over):
    raw = {"n": n,
           "stages": [{"label": "first change", "cue": "one flap folded"}, {"label": "finished", "cue": "all flaps"}],
           "done_cue": "four flaps meet at the center",
           "mistakes": [{"label": "Corner Short", "sign": "gap at the center",
                         "hint": "push each corner all the way to the center", "severity": "medium"}],
           "region": {"x0": 0.2, "y0": 0.1, "x1": 0.8, "y1": 0.9}}
    raw.update(over)
    return raw


ENTRY = {"n": 4, "title": "Fold all four corners to center", "question": "Four flaps meeting at the center?",
         "stages": [{"label": "one corner", "cue": "one flap"}, {"label": "two corners", "cue": "two flaps"},
                    {"label": "all corners", "cue": "four flaps"}],
         "done_cue": "four flaps meet at the center",
         "mistakes": [{"label": "short of center", "sign": "gap in the middle", "hint": "Push corners to the center.",
                       "severity": "medium"},
                      {"label": "missed corner", "sign": "one square corner", "hint": "Fold the last corner in.",
                       "severity": "high"}],
         "region": {"x0": 0, "y0": 0, "x1": 1, "y1": 1}}


def _jpeg(color=(200, 50, 50)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "JPEG")
    return buf.getvalue()


KEYS = [_jpeg((10, 10, 10)), _jpeg((100, 100, 100)), _jpeg((200, 200, 200))]
PREV, LIVE = _jpeg((0, 0, 255)), _jpeg((0, 255, 0))


def _answer(**over) -> str:
    a = {"seen": "diamond with four flaps", "differs": "nothing", "stage": 2, "progress": 1.0, "mistake": "none",
         "mistake_confidence": 0.0, "done": "yes", "confidence": 0.92}
    a.update(over)
    return json.dumps(a)


# ---------------------------------------------------------------- rubric

def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_rubric_schema_is_flat_and_strict():
    schema = understand.rubric_schema()
    assert "$defs" not in json.dumps(schema)
    for node in _walk(schema):
        if isinstance(node, dict) and node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        if isinstance(node, dict):
            for bad in ("minimum", "maximum", "minItems", "maxItems", "default"):
                assert bad not in node, bad
    step = schema["properties"]["steps"]["items"]
    assert list(step["properties"]) == ["n", "stages", "done_cue", "mistakes", "region"]
    assert step["properties"]["mistakes"]["items"]["properties"]["severity"]["enum"] == ["low", "medium", "high"]


def test_build_rubric_writes_file_and_keyframes():
    d = _lesson_copy()
    steps = [_raw_step(2, stages=[{"label": f"s{i}", "cue": f"c{i}"} for i in range(6)]),
             _raw_step(4, mistakes=[{"label": "Corner Short", "sign": "a", "hint": "h", "severity": "huge"},
                                    {"label": "corner short", "sign": "dup", "hint": "h", "severity": "low"},
                                    {"label": "none", "sign": "x", "hint": "h", "severity": "low"},
                                    {"label": "b", "sign": "b", "hint": "h", "severity": "low"},
                                    {"label": "c", "sign": "c", "hint": "h", "severity": "low"},
                                    {"label": "d", "sign": "d", "hint": "h", "severity": "low"}]),
             _raw_step(5, region={"x0": 0.9, "y0": 0.1, "x1": 0.2, "y1": 0.9}),
             _raw_step(6, stages=[])]  # step 8 missing on purpose
    with claude(lambda: _msg(json.dumps({"steps": steps}))) as fake:
        rubric = _run(understand.build_rubric(d))
        ledger = spend.status()
    assert len(fake.calls) == 1 and ledger.total_calls == 1
    req = fake.calls[0]
    assert req["model"] == "claude-haiku-5-5"
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": understand.rubric_schema()}
    for k in ("temperature", "top_p", "top_k"):
        assert k not in req
    content = req["messages"][0]["content"]
    assert sum(b["type"] == "image" for b in content) == 3 * len(CAMERA)
    assert content[0]["text"].startswith("STEP 2: Fold corner to corner")
    # file and keyframes
    on_disk = json.loads((d / "rubric.json").read_text())
    assert on_disk == rubric and rubric["version"] == 1 and rubric["source"] == understand.lesson_signature(
        json.loads((d / "lesson.json").read_text()))
    assert [s["n"] for s in rubric["steps"]] == [2, 4, 5, 6]  # 8 missing: keeps the plain check
    for n in CAMERA:
        for x in "abc":
            assert (d / "frames" / f"{n:02d}_{x}.jpg").stat().st_size > 0
    by = {s["n"]: s for s in rubric["steps"]}
    assert len(by[2]["stages"]) == 4
    assert [m["label"] for m in by[4]["mistakes"]] == ["corner short", "b", "c"]
    assert by[4]["mistakes"][0]["severity"] == "medium"
    assert len(by[2]["mistakes"][0]["hint"].split()) <= 10
    assert by[5]["region"] == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    assert by[6]["stages"] == [{"label": "done", "cue": "four flaps meet at the center"}]
    # the synthetic video is static per step: START falls back to the previous reference, DONE is the reference
    assert by[4]["keyframe_sources"][0] == "prev_ref_frame" and by[4]["keyframe_sources"][2] == "ref_frame"
    assert (d / "frames" / "04_a.jpg").read_bytes() == (d / "frames" / "03.jpg").read_bytes()
    assert (d / "frames" / "04_c.jpg").read_bytes() == (d / "frames" / "04.jpg").read_bytes()
    assert understand.load_rubric(d, json.loads((d / "lesson.json").read_text())) == rubric


def test_build_rubric_keep_frames_and_no_video():
    d = _lesson_copy(video=False)
    for n in CAMERA:
        for x in "abc":
            (d / "frames" / f"{n:02d}_{x}.jpg").write_bytes(_jpeg((n * 20, 0, 0)))
    with claude(lambda: _msg(json.dumps({"steps": [_raw_step(n) for n in CAMERA]}))):
        rubric = _run(understand.build_rubric(d, resample=False))
    assert all(s["keyframe_sources"] == ["kept"] * 3 for s in rubric["steps"])
    assert (d / "frames" / "04_b.jpg").read_bytes() == _jpeg((80, 0, 0))


def test_build_rubric_refuses_without_budget_or_key():
    d = _lesson_copy(video=False)
    with claude(lambda: _msg("{}"), HANDOVER_CLAUDE_BUDGET_DAY_USD="0") as fake:
        try:
            _run(understand.build_rubric(d))
            raise AssertionError("expected a budget refusal")
        except RuntimeError as e:
            assert "spending limit" in str(e)
    assert fake.calls == []
    with env(ANTHROPIC_API_KEY=None):
        saved = check._read_env_file
        check._read_env_file = lambda: {}
        try:
            _run(understand.build_rubric(d))
            raise AssertionError("expected no_key")
        except RuntimeError as e:
            assert "no Claude key" in str(e)
        finally:
            check._read_env_file = saved


def test_build_rubric_refusal_and_truncation_are_errors_and_billed():
    for stop in ("refusal", "max_tokens"):
        d = _lesson_copy(video=False)
        with claude(lambda: _msg('{"steps": []}', stop=stop)):
            try:
                _run(understand.build_rubric(d))
                raise AssertionError("expected an error")
            except RuntimeError as e:
                assert "unusable" in str(e)
            assert spend.status().total_calls == 1  # the failed call is still in the ledger
        assert not (d / "rubric.json").exists()


def test_stale_rubric_is_ignored():
    d = _lesson_copy(video=False)
    with claude(lambda: _msg(json.dumps({"steps": [_raw_step(n) for n in CAMERA]}))):
        _run(understand.build_rubric(d))
    lesson = json.loads((d / "lesson.json").read_text())
    assert understand.load_rubric(d, lesson) is not None
    lesson["steps"][3]["end"] = "00:12.5"  # a recut
    assert understand.load_rubric(d, lesson) is None
    assert understand.load_rubric(d) is not None  # no lesson given: no staleness check
    (d / "rubric.json").write_text("{bad")
    assert understand.load_rubric(d) is None


# ---------------------------------------------------------------- live request shape

def test_live_request_shape():
    with claude(lambda: _msg(_answer())) as fake:
        u = _run(understand.understand_frame(ENTRY, KEYS, LIVE, PREV))
    assert u.error is None and u.done == "yes"
    req = fake.calls[0]
    for k in ("temperature", "top_p", "top_k", "stream"):
        assert k not in req
    assert req["thinking"] == {"type": "disabled"} and req["max_tokens"] == understand.LIVE_MAX_TOKENS
    assert req["output_config"]["effort"] == "low"
    schema = req["output_config"]["format"]["schema"]
    assert list(schema["properties"]) == ["seen", "differs", "stage", "progress", "mistake", "mistake_confidence",
                                          "done", "confidence"]
    assert schema["properties"]["mistake"]["enum"] == ["short of center", "missed corner", "none"]
    assert req["system"][0]["text"] == understand.UNDERSTAND_SYSTEM and "cache_control" not in req["system"][0]
    content = req["messages"][0]["content"]
    texts = [b["text"] for b in content if b["type"] == "text"]
    assert texts[0].startswith("Step: Fold all four corners") and "1. two corners: two flaps" in texts[0]
    assert [t.split(":")[0] for t in texts[1:]] == ["IMAGE BEFORE", "IMAGE START", "IMAGE MID", "IMAGE DONE",
                                                    "IMAGE LIVE", "Answer for IMAGE LIVE."]
    marked = [i for i, b in enumerate(content) if "cache_control" in b]
    assert len(marked) == 1
    i = marked[0]
    assert content[i]["type"] == "image" and content[i - 1]["text"] == "IMAGE DONE"  # last fixed block
    assert content[-2]["type"] == "image" and content[-3]["text"].startswith("IMAGE LIVE")  # LIVE last
    assert all("cache_control" not in b for b in understand._blocks.values())  # memo stays clean


def test_live_request_without_cache_and_before_dedupe():
    with claude(lambda: _msg(_answer()), HANDOVER_CLAUDE_CACHE="0") as fake:
        _run(understand.understand_frame(ENTRY, KEYS, LIVE, KEYS[0]))  # previous reference == START
    content = fake.calls[0]["messages"][0]["content"]
    assert not any("cache_control" in b for b in content)
    texts = [b["text"] for b in content if b["type"] == "text"]
    assert not any(t.startswith("IMAGE BEFORE") for t in texts)
    assert "IMAGE START (also BEFORE: the end of the previous step)" in texts
    assert sum(b["type"] == "image" for b in content) == 4  # START, MID, DONE, LIVE


def test_live_request_for_thinking_models():
    with claude(lambda: _msg(_answer())) as fake:
        _run(understand.understand_frame(ENTRY, KEYS[2:], LIVE, None, model="claude-sonnet-5-5"))
    req = fake.calls[0]
    assert req["model"] == "claude-sonnet-5-5" and "thinking" not in req
    assert req["max_tokens"] == understand.LIVE_THINKING_MAX_TOKENS
    texts = [b["text"] for b in req["messages"][0]["content"] if b["type"] == "text"]
    assert "IMAGE DONE" in texts and "IMAGE START" not in texts


# ---------------------------------------------------------------- guards

def _one(text, **kw):
    with claude(lambda: _msg(text) if isinstance(text, str) else text, **kw):
        return _run(understand.understand_frame(ENTRY, KEYS, LIVE, PREV))


def test_guards():
    u = _one(_answer(done="Yes", mistake="none"))
    assert (u.done, u.stage, u.progress, u.mistake) == ("yes", 2, 1.0, None) and u.reason is None
    u = _one(_answer(done="yes", differs="one flap still open"))
    assert u.done == "unsure" and u.reason == "one flap still open"
    u = _one(_answer(done="yes", mistake="Short Of Center", mistake_confidence=0.9))
    assert u.done == "unsure" and u.mistake == "short of center" and u.mistake_confidence == 0.9
    u = _one(_answer(done="no", stage=7, progress=1.7, confidence=1.3, mistake="tore the paper",
                     mistake_confidence=2))
    assert (u.stage, u.progress, u.confidence, u.mistake, u.mistake_confidence) == (-1, 1.0, 1.0, None, 0.0)
    u = _one(_answer(done="no", stage=-1, progress=-0.2))
    assert (u.stage, u.progress) == (-1, 0.0)
    u = _one(_answer(done="no", stage="two"))
    assert u.stage == -1 and u.error is None
    u = _one(_answer(done="no", stage=-1, mistake="missed corner", mistake_confidence=0.95))
    assert u.mistake is None and u.mistake_confidence == 0.0  # not started is not a mistake


def test_failures_count_as_errors():
    for resp, err in [(_msg(_answer(), stop="refusal", category="other"), "error"),
                      (_msg('{"seen": "diam', stop="max_tokens"), "error"),
                      (_msg("not json"), "error"),
                      (_msg(json.dumps({"done": "maybe", "confidence": 1})), "error")]:
        u = _one(resp)
        assert (u.done, u.confidence, u.error, u.stage, u.mistake) == ("unsure", 0.0, err, -1, None), resp
        assert u.cost_usd > 0  # billed even though unusable
    req = __import__("httpx2").Request("POST", "https://api.anthropic.com/v1/messages")
    rate = anthropic.RateLimitError("429", response=__import__("httpx2").Response(429, request=req), body=None)
    assert _one(rate).error == "rate_limited"
    with claude(lambda: "hang"):
        u = _run(understand.understand_frame(ENTRY, KEYS, LIVE, PREV, timeout=0.2))
    assert u.error == "timeout" and u.done == "unsure"


def test_budget_and_key_refusals_make_no_call():
    with claude(lambda: _msg(_answer()), HANDOVER_CLAUDE_BUDGET_TOTAL_USD="0") as fake:
        u = _run(understand.understand_frame(ENTRY, KEYS, LIVE, PREV))
    assert u.error == "budget" and fake.calls == []
    saved = check._read_env_file
    check._read_env_file = lambda: {}
    try:
        with env(ANTHROPIC_API_KEY=None):
            u = _run(understand.understand_frame(ENTRY, KEYS, LIVE, PREV))
    finally:
        check._read_env_file = saved
    assert u.error == "no_key"


def test_result_is_a_check_result_drop_in():
    u = _one(_answer(done="no", differs="one flap open", stage=1, progress=0.5, confidence=0.8))
    assert isinstance(u, check.CheckResult)
    d = u.as_dict()
    assert {"done", "confidence", "latency_ms", "reason"} <= set(d)
    assert (d["stage"], d["progress"], d["mistake"], d["mistake_confidence"]) == (1, 0.5, None, 0.0)
    b = check.Breaker(open_seconds=5)
    b.record(Understanding("unsure", 0.0, 0, error="budget"), 0.0)
    assert b.reason == "budget"
    deb = check.Debouncer(n=2, min_conf=0.8)
    assert not deb.feed(u.done, u.confidence)


def test_mock_mode():
    with env(HANDOVER_CHECK="mock", HANDOVER_MOCK_PASS_SECONDS="0"):
        u = _run(understand.understand_frame(ENTRY, KEYS, LIVE, PREV, step_started_at=0.0))
    assert (u.done, u.stage, u.progress, u.error) == ("yes", 2, 1.0, None)


# ---------------------------------------------------------------- MistakeTracker

def _u(mistake=None, conf=0.9, stage=0, error=None):
    return Understanding("no", 0.8, 100, error=error, stage=stage, mistake=mistake, mistake_confidence=conf)


def test_tracker_fires_on_two_in_a_row():
    t = MistakeTracker(min_conf=0.75, repeat=2, clear_after=2, cooldown_s=8)
    t.start_step(3, ENTRY)
    assert t.feed(_u("short of center"), 0.0) is None
    msg = t.feed(_u("short of center", 0.8), 1.0)
    assert msg == {"type": "mistake", "step": 3, "kind": "live", "label": "short of center",
                   "message": "Push corners to the center.", "confidence": 0.8, "source": "claude"}
    assert t.active == msg
    assert t.feed(_u("short of center"), 2.0) is None  # still active: no repeat message


def test_tracker_needs_confidence_and_consecutive():
    t = MistakeTracker(min_conf=0.75, repeat=2, clear_after=2, cooldown_s=8)
    t.start_step(3, ENTRY)
    assert t.feed(_u("short of center", 0.7), 0) is None
    assert t.feed(_u("short of center", 0.74), 1) is None  # below 0.75 twice
    assert t.feed(_u("short of center"), 2) is None
    assert t.feed(_u(None), 3) is None  # broken streak
    assert t.feed(_u("short of center"), 4) is None
    assert t.feed(_u("missed corner"), 5) is None  # a different label restarts the count
    assert t.feed(_u("not in the rubric"), 6) is None
    assert t.feed(_u("not in the rubric"), 7) is None
    assert t.feed(_u("missed corner", error="timeout"), 8) is None  # errors are skipped, never counted
    assert t.feed(_u("missed corner"), 9) is None
    assert t.feed(_u("missed corner", error="error"), 10) is None
    assert t.feed(_u("missed corner"), 11)["label"] == "missed corner"


def test_tracker_clears_when_gone_or_stage_advances():
    t = MistakeTracker(min_conf=0.75, repeat=2, clear_after=2, cooldown_s=8)
    t.start_step(3, ENTRY)
    t.feed(_u("short of center"), 0)
    assert t.feed(_u("short of center"), 1)
    t.feed(_u(None), 2)
    assert t.active is not None  # gone once
    t.feed(_u("short of center", stage=0), 3)  # back: the absence count restarts
    t.feed(_u(None), 4)
    assert t.active is not None
    t.feed(_u(None), 5)
    assert t.active is None  # gone twice in a row
    # stage advance clears at once
    t.start_step(4, ENTRY)
    t.feed(_u("missed corner", stage=1), 10)
    assert t.feed(_u("missed corner", stage=1), 11)
    t.feed(_u("missed corner", stage=2), 12)
    assert t.active is None


def test_tracker_cooldown_and_step_change():
    t = MistakeTracker(min_conf=0.75, repeat=2, clear_after=1, cooldown_s=8)
    t.start_step(3, ENTRY)
    t.feed(_u("short of center"), 0)
    assert t.feed(_u("short of center"), 1)
    t.feed(_u(None), 2)
    assert t.active is None
    t.feed(_u("short of center"), 3)
    assert t.feed(_u("short of center"), 4) is None  # 3 s after it fired: cooldown
    assert t.active is None
    assert t.feed(_u("short of center"), 9.0)  # 8 s after: fires again
    # step change: streak and active warning are dropped; cooldowns are per step
    t.start_step(5, ENTRY)
    assert t.active is None
    t.feed(_u("short of center"), 10)
    assert t.feed(_u("short of center"), 11)  # other step: not in the step 3 cooldown
    t.start_step(3, ENTRY)
    t.feed(_u("short of center"), 12)
    assert t.feed(_u("short of center"), 13) is None  # step 3 fired at 9.0: still cooling down
    t.reset()
    assert t.active is None and t.step == 3


def test_tracker_without_rubric_never_fires():
    t = MistakeTracker(min_conf=0.75, repeat=1, clear_after=1, cooldown_s=0)
    assert t.feed(_u("short of center"), 0) is None  # no step started
    t.start_step(2, None)
    assert t.feed(_u("short of center"), 1) is None


def test_settings_defaults_and_bounds():
    assert understand.setting("HANDOVER_UNDERSTAND_MODEL") == "claude-haiku-5-5"
    assert understand.setting("HANDOVER_UNDERSTAND_TIMEOUT") == 5.0
    t = MistakeTracker()
    assert (t.min_conf, t.repeat, t.clear_after, t.cooldown_s) == (0.75, 2, 2, 8.0)
    with env(HANDOVER_LIVE_MISTAKE_MIN_CONF="2", HANDOVER_LIVE_MISTAKE_REPEAT="3",
             HANDOVER_LIVE_MISTAKE_COOLDOWN_S="abc", HANDOVER_UNDERSTAND_TIMEOUT="0.01"):
        t = MistakeTracker()
        assert (t.min_conf, t.repeat, t.cooldown_s) == (0.75, 3, 8.0)  # out of range and bad: defaults
        assert understand._timeout() == 5.0 and understand._timeout(1.5) == 1.5


# ---------------------------------------------------------------- CLI and bench

def test_cli_rubric_offline_makes_no_paid_call():
    d = _lesson_copy(video=False)
    e = {**os.environ, "ANTHROPIC_API_KEY": "sk-ant-test-not-real", "HANDOVER_NO_NETWORK": "1",
         "HANDOVER_CLAUDE_SPEND_FILE": str(_TMP / "cli.json")}
    out = subprocess.run([sys.executable, "-m", "server.understand", "--rubric", str(d)], cwd=check.REPO, env=e,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "rubric call failed" in out.stdout and "sk-ant-test-not-real" not in out.stdout + out.stderr
    assert not (d / "rubric.json").exists()


def test_bench_metrics_and_hard_stop():
    sys.path.insert(0, str(check.REPO / "scripts"))
    import understand_bench as ub
    from accuracy import Budget

    rows = []
    for v in range(2):
        for name, p, stage, prog in [("start", 0.0, -1, 0.0), ("mid", 0.5, 0, 0.4), ("done", 1.0, 1, 1.0)]:
            rows.append(ub.Row("m", 4, name, "series", "geometry", v, p, stage, 2, prog,
                               "yes" if p == 1 else "no", 0.9))
        rows.append(ub.Row("m", 4, "short", "mistake", "geometry", v, None, 0, 2, 0.8, "no", 0.9,
                           "short of center", 0.9))

    def factory(step):
        t = MistakeTracker(min_conf=0.75, repeat=2, clear_after=2, cooldown_s=8)
        t.start_step(step, ENTRY)
        return t

    m = ub.metrics(rows, factory)
    assert m["progress_pairs_monotonic"] == (4, 4) and m["stage_exact"] == (6, 6)
    assert m["mistake_detected"] == (2, 2) and m["mistake_false_alarm"] == (0, 6)
    assert m["tracker_fired_on_planted"] == (1, 1) and m["tracker_false_fire_on_clean_series"] == (0, 2)
    assert m["understand_done"]["done_yes"] == (2, 2) and m["understand_done"]["false_pass_all"] == (0, 6)
    assert ub.expected_stage(0.85, 4) == 3 and ub.expected_stage(0.25, 4) == 0 and ub.expected_stage(0, 3) == -1
    # a budget below the first call estimate stops before any call
    with claude(lambda: _msg(_answer())) as fake:
        budget = Budget(0.001, status=spend.status)
        budget.priciest = ub.FIRST_CALL_ESTIMATE_USD
        frames = ub.plan()
        out, why = _run(ub.run_model("claude-haiku-5-5", _lesson_copy(video=False), frames, {}, 1, budget, True,
                                     {"steps": [dict(ENTRY, n=n, keyframes=[]) for n in CAMERA]}, lambda s: None))
    assert out == [] and "max-usd" in why and fake.calls == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

"""Teach pipeline tests: reference frames, recut rule, step 1 manual, safety and tools, self-test, CLI.

Run: .venv/bin/python -m server.test_teach (or pytest if installed). Works on copies of lessons/demo-v1 in a
temp folder and never touches the committed lesson. No network: extraction is faked and checks run in mock mode.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="handover-teach-test-"))
os.environ["HANDOVER_LESSONS"] = str(TMP / "lessons")
os.environ.pop("HANDOVER_TEACH_MOCK", None)
# Offline by default: no reference-question call and no automatic self-test reach a real model, even with a real
# key in .env (tests that exercise them unset this inside _env). Fixtures are 1 to 3 s steps, so the 6 s minimum
# step merge is off unless a test turns it on.
os.environ.setdefault("HANDOVER_NO_NETWORK", "1")
os.environ.setdefault("HANDOVER_MIN_STEP_S", "0")
for _name in ("HANDOVER_TRANSCRIBE", "HANDOVER_WHISPER_MODEL"):
    os.environ.pop(_name, None)
# No test may download a speech model: the real faster_whisper is blocked (imports fail, so teach falls back to
# frames only) and tests that need it install a fake. HANDOVER_TEST_REAL_WHISPER=1 runs the one real check.
_REAL_WHISPER = os.environ.get("HANDOVER_TEST_REAL_WHISPER") == "1"
if not _REAL_WHISPER:
    sys.modules["faster_whisper"] = None

from PIL import Image, ImageStat  # noqa: E402

from server import teach  # noqa: E402

DEMO = teach.REPO / "lessons" / "demo-v1"
DEMO_COLORS = [(0x1F, 0x6F, 0xEB), (0x2D, 0xA4, 0x4E), (0xBF, 0x87, 0x00), (0xCF, 0x22, 0x2E), (0x82, 0x50, 0xDF)]

_cache: dict = {}


def _ffmpeg(*args: str) -> None:
    subprocess.run([teach._bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _demo_copy(name: str) -> Path:
    """A copy of lessons/demo-v1, recut once with the current code (cached), under the temp lessons folder."""
    if "demo" not in _cache:
        d = TMP / "demo-base"
        shutil.copytree(DEMO, d, ignore=shutil.ignore_patterns(".recut_*"))
        teach.recut(d)
        _cache["demo"] = d
    dst = TMP / "lessons" / name
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(_cache["demo"], dst)
    return dst


def _read(d: Path) -> dict:
    return json.loads((d / "lesson.json").read_text(encoding="utf-8"))


def _write(d: Path, lesson: dict) -> None:
    (d / "lesson.json").write_text(json.dumps(lesson, indent=2), encoding="utf-8")


def _mean_rgb(path: Path) -> tuple:
    with Image.open(path) as im:
        return tuple(ImageStat.Stat(im.convert("RGB")).mean)


def _nearest_color(rgb) -> int:
    return min(range(len(DEMO_COLORS)), key=lambda i: sum((a - b) ** 2 for a, b in zip(rgb, DEMO_COLORS[i])))


# ---------------------------------------------------------------- normalize input streams

def test_audio_stream_skips_unsupported_iphone_track():
    original = teach._capture
    payload = {"streams": [
        {"index": 1, "codec_name": None},
        {"index": 2, "codec_name": "aac"},
    ]}

    class Result:
        stdout = json.dumps(payload)
        stderr = ""
        returncode = 0

    teach._capture = lambda _cmd: Result()
    try:
        assert teach.audio_stream_index(Path("iphone.mov")) == 2
        assert teach.has_audio(Path("iphone.mov"))
    finally:
        teach._capture = original


# ---------------------------------------------------------------- reference frames (M8)

def test_ref_frames_in_last_15_percent_and_not_black():
    d = _demo_copy("ref-frames")
    for i, s in enumerate(_read(d)["steps"]):
        a, b = teach.parse_time(s["start"]), teach.parse_time(s["end"])
        t = teach.parse_time(s["ref_time"])
        assert a + 0.85 * (b - a) - 0.1 <= t < b, (s["n"], s["ref_time"])
        frame = d / s["ref_frame"]
        assert frame.stat().st_size > 0
        rgb = _mean_rgb(frame)
        assert sum(rgb) / 3 > teach.DARK, (s["n"], rgb)
        # each demo step has its own background color: the frame must come from this step, not the next one
        assert _nearest_color(rgb) == i, (s["n"], rgb)
        with Image.open(frame) as im:
            assert im.size == (1920, 1080)
    assert not (d / ".recut_tmp").exists() and not (d / ".recut_old").exists()


def test_pick_prefers_the_still_moment():
    # 9 s of moving test pattern, then the last frame held for 1 s: the still second must win
    src = TMP / "still-end.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=9", "-vf", "tpad=stop_mode=clone:stop_duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src))
    t = teach.pick_ref_time(src, 0.0, 10.0)
    assert t is not None and 9.0 <= t < 10.0, t
    assert abs(t * 10 - round(t * 10)) < 1e-6  # on the 0.1 s grid lesson.json uses


def test_hint_wins_when_equally_still():
    # the demo's moving box runs at a constant speed, so every moment is equally still and the hint wins
    t = teach.pick_ref_time(DEMO / "norm.mp4", 0.0, 8.0, hint=5.0)
    assert t == 5.0, t
    # a hint outside the step is ignored
    t = teach.pick_ref_time(DEMO / "norm.mp4", 0.0, 8.0, hint=20.0)
    assert t is not None and 6.7 <= t < 8.0, t


# ---------------------------------------------------------------- recut rule

def test_ref_time_persisted_and_honored_by_recut():
    d = _demo_copy("ref-honor")
    lesson = _read(d)
    assert all(s.get("ref_time") for s in lesson["steps"])
    lesson["steps"][1]["ref_time"] = "00:10.0"   # inside step 2 (00:08 to 00:16)
    lesson["steps"][3]["ref_time"] = "00:02"     # outside step 4: a new one is chosen
    _write(d, lesson)
    out = teach.recut(d)
    assert out["steps"][1]["ref_time"] == "00:10"
    expect = TMP / "expect-10.jpg"
    teach._grab_frame(d / "norm.mp4", 10.0, expect)
    assert (d / "frames" / "02.jpg").read_bytes() == expect.read_bytes()
    t4 = teach.parse_time(out["steps"][3]["ref_time"])
    assert 24.0 <= t4 < 32.0, out["steps"][3]["ref_time"]
    assert _nearest_color(_mean_rgb(d / "frames" / "04.jpg")) == 3
    # a second recut keeps the persisted values
    again = teach.recut(d)
    assert [s["ref_time"] for s in again["steps"]] == [s["ref_time"] for s in out["steps"]]


def test_recut_keeps_unknown_and_new_fields():
    d = _demo_copy("keep-fields")
    lesson = _read(d)
    lesson["custom_top"] = {"a": [1, 2]}
    lesson["safety"], lesson["tools"] = ["Keep fingers clear."], ["Bone folder"]
    st = lesson["steps"][1]
    st["common_mistake"] = "Flip it over first."
    st["self_test"] = {"own": "yes", "prev": "no", "ok": True}
    st["x_note"] = "keep me"
    st["title"] = "Renamed by hand"
    _write(d, lesson)
    out = teach.recut(d)
    assert out["custom_top"] == {"a": [1, 2]}
    assert out["safety"] == ["Keep fingers clear."] and out["tools"] == ["Bone folder"]
    s2 = out["steps"][1]
    assert s2["common_mistake"] == "Flip it over first."
    assert s2["self_test"] == {"own": "yes", "prev": "no", "ok": True}
    assert s2["x_note"] == "keep me" and s2["title"] == "Renamed by hand"
    assert out["steps"][0]["check_type"] == "camera"  # recut never makes step 1 manual
    assert _read(d) == out


# ---------------------------------------------------------------- new extraction

def _fake_extraction() -> "teach.Extraction":
    return teach.Extraction(
        steps=[
            teach.Step(start="00:00", end="00:01", title="Lay it flat", check_question="Is there one square?",
                       prerequisites=[], ref_time="00:00.8", common_mistake=""),
            teach.Step(start="00:01", end="00:02", title="Fold in half", check_question="Is it a rectangle?",
                       prerequisites=[1], ref_time="00:01.9", common_mistake="  Flip it   over first. "),
            teach.Step(start="00:02", end="00:03", title="Fold corners", check_question="Are there four flaps?",
                       prerequisites=[2], ref_time="", common_mistake=""),
        ],
        transcript=[teach.Segment(start=0.2, end=0.9, text="Lay it flat.")],
        safety=["Mind the blade.", " mind the  blade. ", ""],
        tools=["Craft knife", "Ruler"],
    )


def _built_from_fake(lesson_id: str) -> Path:
    src = TMP / "fake-src.mp4"
    if not src.exists():
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(src))
    real = teach.extract
    teach.extract = lambda norm, progress=None: _fake_extraction()
    os.environ["HANDOVER_TEACH_PROVIDER"] = "gemini"
    try:
        teach.process_upload(src, lesson_id, "Fake lesson")
    finally:
        teach.extract = real
        os.environ.pop("HANDOVER_TEACH_PROVIDER", None)
    return teach.lessons_root() / lesson_id


def test_step_one_manual_only_on_new_extraction():
    d = _built_from_fake("first-manual")
    lesson = _read(d)
    kinds = [s["check_type"] for s in lesson["steps"]]
    assert kinds == ["manual", "camera", "camera"], kinds
    assert lesson["steps"][0]["check_question"] == ""
    assert lesson["steps"][1]["common_mistake"] == "Flip it over first."
    assert all(s["ref_time"] for s in lesson["steps"])
    # the author turns step 1 back into a camera step; recut must leave it that way
    lesson["steps"][0].update(check_type="camera", check_question="Is there one square?")
    _write(d, lesson)
    out = teach.recut(d)
    assert out["steps"][0]["check_type"] == "camera"
    assert out["steps"][0]["check_question"] == "Is there one square?"


def test_steps_file_is_not_changed_to_manual():
    d = TMP / "steps-file"
    shutil.copytree(DEMO, d)
    ex = teach._plan_extraction(40.0, d / "extraction.json")
    assert teach._is_manual(ex.steps[0].check_question) is False  # demo lesson keeps its camera step 1


def test_safety_and_tools_round_trip():
    d = _built_from_fake("safety-tools")
    lesson = _read(d)
    assert lesson["safety"] == ["Mind the blade."]
    assert lesson["tools"] == ["Craft knife", "Ruler"]
    stored = json.loads((d / "extraction.json").read_text(encoding="utf-8"))
    assert stored["safety"] == ["Mind the blade."] and stored["tools"] == ["Craft knife", "Ruler"]
    out = teach.recut(d)
    assert out["safety"] == ["Mind the blade."] and out["tools"] == ["Craft knife", "Ruler"]
    # old extraction files without the new fields still load
    old = teach.Extraction.model_validate_json((DEMO / "extraction.json").read_text(encoding="utf-8"))
    assert old.safety == [] and old.tools == [] and old.steps[0].ref_time == ""


def test_gemini_schema_requires_every_field():
    schema = teach.gemini_schema()
    assert list(schema["properties"]) == ["transcript", "steps", "safety", "tools"]  # narration first
    assert set(schema["required"]) == {"steps", "transcript", "safety", "tools"}
    step = schema["$defs"]["Step"]
    assert {"ref_time", "common_mistake", "check_question"} <= set(step["required"])
    seg = schema["$defs"]["_WireSegment"]["properties"]
    assert seg["start"]["type"] == "string" and seg["end"]["type"] == "string"

    def no_ref_siblings(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert set(node) == {"$ref"}, node
            for v in node.values():
                no_ref_siblings(v)
        elif isinstance(node, list):
            for v in node:
                no_ref_siblings(v)

    no_ref_siblings(schema)
    assert "never use color" in teach.PROMPT.lower() and '"MM:SS" timestamps' in teach.PROMPT


def test_segment_accepts_mmss_strings():
    seg = teach.Segment.model_validate({"start": "01:02.5", "end": 63, "text": "hi"})
    assert (seg.start, seg.end) == (62.5, 63.0)


def test_clips_have_a_keyframe_every_second():
    d = _demo_copy("keyframes")
    out = subprocess.run([teach._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                          "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(d / "clips" / "02.mp4")],
                         capture_output=True, text=True, encoding="utf-8")
    keys = [float(x.strip(",")) for x in out.stdout.split() if x.strip(",")]
    assert len(keys) >= 8, keys
    assert max(b - a for a, b in zip(keys, keys[1:])) <= 1.05, keys


def test_full_range_input_gives_tv_range_clips():
    src = TMP / "full-range.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=4", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuvj420p", str(src))

    def probe(path):
        out = subprocess.run([teach._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=pix_fmt,color_range,color_primaries,color_transfer,color_space",
                              "-of", "default=nw=1", str(path)], capture_output=True, text=True, encoding="utf-8")
        return dict(line.split("=", 1) for line in out.stdout.split())

    assert probe(src)["pix_fmt"] == "yuvj420p"
    steps = TMP / "full-range-steps.json"
    steps.write_text(json.dumps({"steps": [
        {"start": "00:00", "end": "00:02", "title": "A", "check_question": "Is it a square?", "prerequisites": []},
        {"start": "00:02", "end": "00:04", "title": "B", "check_question": "Is it folded?", "prerequisites": [1]},
    ], "transcript": []}), encoding="utf-8")
    teach.build([src], "full-range", "Full range", steps_json=steps)
    d = teach.lessons_root() / "full-range"
    expect = {"pix_fmt": "yuv420p", "color_range": "tv", "color_primaries": "bt709", "color_transfer": "bt709",
              "color_space": "bt709"}
    for f in (d / "norm.mp4", d / "clips" / "01.mp4", d / "clips" / "02.mp4"):
        assert probe(f) == expect, (f.name, probe(f))
    # a recut of an old lesson whose norm.mp4 is still full range also gives tv range clips
    shutil.copy(src, d / "norm.mp4")
    teach.recut(d)
    assert probe(d / "clips" / "01.mp4") == expect


# ---------------------------------------------------------------- extraction request (faked Gemini client)

class _FakeFiles:
    def __init__(self, log):
        self.log = log

    def upload(self, file):
        self.log["uploaded"] = Path(file).name
        return type("F", (), {"state": "ACTIVE", "name": "files/x", "uri": "gs://x", "mime_type": "video/mp4"})()

    def get(self, name):
        raise AssertionError("upload was already ACTIVE")

    def delete(self, name):
        self.log["deleted"] = name


def _fake_client(log):
    answer = {
        "transcript": [{"start": "00:01", "end": "00:03.5", "text": "Lay it flat."},
                       {"start": "bad", "end": "00:04", "text": "dropped"}],
        "steps": [{"start": "00:00", "end": "00:08", "title": "Lay it flat", "check_question": "Is it flat?",
                   "prerequisites": [], "ref_time": "00:07", "common_mistake": ""}],
        "safety": [], "tools": ["Paper"],
    }

    class Models:
        def generate_content(self, model, contents, config):
            part = contents[0].parts[0]
            log.update(model=model, part=part, config=config,
                       proxy_exists=(log["dir"] / "proxy.mp4").exists())
            return type("R", (), {"text": json.dumps(answer)})()

    class Client:
        def __init__(self, api_key, http_options):
            log["http_options"] = http_options
            self.models, self.files = Models(), _FakeFiles(log)

    return Client


def _extract_with_fake(d: Path, inline_limit: int):
    from google import genai
    from google.genai import types

    log = {"dir": d}
    real_client, real_limit, real_key = genai.Client, teach.INLINE_LIMIT, os.environ.get("GEMINI_API_KEY")
    genai.Client, teach.INLINE_LIMIT = _fake_client(log), inline_limit
    os.environ["GEMINI_API_KEY"] = "test-key-not-real"
    try:
        ex = teach.extract(d / "norm.mp4")
    finally:
        genai.Client, teach.INLINE_LIMIT = real_client, real_limit
        if real_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = real_key
    return ex, log, types


def test_extract_sends_small_proxy_inline():
    d = _demo_copy("extract-inline")
    ex, log, types = _extract_with_fake(d, teach.INLINE_LIMIT)
    part, cfg = log["part"], log["config"]
    assert log["proxy_exists"] and not (d / "proxy.mp4").exists()  # made for the call, deleted after
    assert part.inline_data is not None and part.file_data is None and "uploaded" not in log
    assert part.inline_data.mime_type == "video/mp4" and len(part.inline_data.data) < teach.INLINE_LIMIT
    assert part.video_metadata.fps == 2
    assert log["http_options"].api_version == "v1beta" and log["http_options"].timeout == 600_000
    assert cfg.max_output_tokens == 32768
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.HIGH
    assert cfg.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert [(s.start, s.end, s.text) for s in ex.transcript] == [(1.0, 3.5, "Lay it flat.")]
    assert ex.tools == ["Paper"] and ex.steps[0].ref_time == "00:07"


def test_extract_uses_files_api_for_big_proxy():
    d = _demo_copy("extract-files")
    _, log, _ = _extract_with_fake(d, 0)
    assert log["uploaded"] == "proxy.mp4" and log["deleted"] == "files/x"
    assert log["part"].file_data.file_uri == "gs://x" and log["part"].inline_data is None
    assert not (d / "proxy.mp4").exists()


def test_proxy_is_480p_10fps_same_length():
    d = _demo_copy("proxy")
    out = TMP / "proxy-check.mp4"
    teach.make_proxy(d / "norm.mp4", out)
    probe = subprocess.run([teach._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=height,r_frame_rate,start_time", "-of", "default=nw=1", str(out)],
                           capture_output=True, text=True, encoding="utf-8").stdout
    assert "height=480" in probe and "r_frame_rate=10/1" in probe, probe
    assert "start_time=0.000000" in probe, probe  # same clock as norm.mp4
    # only the last frame's length (1/10 s, rounded up) may differ at 10 fps
    assert abs(teach.probe_duration(out) - teach.probe_duration(d / "norm.mp4")) <= 0.25


# ---------------------------------------------------------------- self-test (S-T) and CLI

def _cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = teach.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_self_test_mock_writes_results():
    d = _demo_copy("self-test")
    prev = os.environ.get("HANDOVER_CHECK")
    os.environ["HANDOVER_CHECK"] = "mock"
    try:
        code, out, err = _cli("--self-test", str(d))
    finally:
        if prev is None:
            os.environ.pop("HANDOVER_CHECK", None)
        else:
            os.environ["HANDOVER_CHECK"] = prev
    assert code == 0, (out, err)
    assert "step 2: own yes" in out
    for s in _read(d)["steps"]:
        if s["check_type"] == "manual":
            assert "self_test" not in s
        else:
            assert s["self_test"] == {"own": "yes", "prev": "no", "ok": True, "mock": True}, s


def test_self_test_uses_its_own_timeout():
    from server import check

    d = _demo_copy("self-test-timeout")
    seen, real = [], check.check_frame

    async def fake(ref, live, question, *, step_started_at=None, prev_ref=None, timeout=None):
        seen.append(timeout)
        return check.CheckResult("yes" if live == ref else "no", 0.9, 1)

    env_before = dict(os.environ)
    check.check_frame = fake
    try:
        teach.self_test_lesson(d)
        os.environ["HANDOVER_SELFTEST_TIMEOUT"] = "25"
        teach.self_test_lesson(d)
    finally:
        check.check_frame = real
        os.environ.pop("HANDOVER_SELFTEST_TIMEOUT", None)
    assert seen[:8] == [10.0] * 8 and seen[8:] == [25.0] * 8, seen
    assert dict(os.environ) == env_before  # the self-test never touches the environment
    results = [s.get("self_test") for s in _read(d)["steps"]]
    # demo step 1 starts and ends on the same picture (its moving box wraps back to x=0), so the fake check,
    # which compares bytes, rightly fails it; steps 2, 4 and 5 compare against a different previous reference
    assert results[0] == {"own": "yes", "prev": "yes", "ok": False}, results
    assert [r["ok"] for r in (results[1], results[3], results[4])] == [True, True, True] and results[2] is None


def test_self_test_skips_failed_calls():
    from server import check

    d = _demo_copy("self-test-errors")
    lesson = _read(d)
    lesson["steps"][1]["self_test"] = {"own": "yes", "prev": "no", "ok": True}  # stale result from an old run
    _write(d, lesson)
    real = check.check_frame

    async def failing(ref, live, question, *, step_started_at=None, prev_ref=None, timeout=None):
        return check.CheckResult("unsure", 0.0, 10000, error="timeout")

    check.check_frame = failing
    try:
        code, out, err = _cli("--self-test", str(d))
    finally:
        check.check_frame = real
    assert code == 1, (out, err)
    assert "step 2: skipped, check failed (timeout)" in out and "check failed on steps 1, 2, 4, 5" in err
    assert all("self_test" not in s for s in _read(d)["steps"])  # never saved as a disagreement


def test_self_test_async_runs_on_a_loop():
    import asyncio

    d = _demo_copy("self-test-async")
    os.environ["HANDOVER_CHECK"] = "mock"
    try:
        lesson = asyncio.run(teach.self_test_lesson_async(d))
    finally:
        os.environ.pop("HANDOVER_CHECK", None)
    assert lesson["steps"][1]["self_test"]["ok"] is True and _read(d) == lesson


def test_tunables_come_from_config():
    import inspect

    from server import check, config

    assert "timeout" in inspect.signature(check.check_frame).parameters
    os.environ["HANDOVER_SELFTEST_TIMEOUT"] = "500"   # outside 0.1 to 120: config falls back to the default
    os.environ["HANDOVER_TEACH_MODEL"] = "some-free-model"
    os.environ["HANDOVER_TEACH_MOCK"] = "true"
    try:
        assert teach._selftest_timeout() == config.tunable("HANDOVER_SELFTEST_TIMEOUT").default == 10.0
        assert teach._model() == "some-free-model"
        code, out, _ = _cli(str(DEMO / "norm.mp4"), "--id", "mock-dry", "--dry-run")
        assert code == 0 and "3 steps" in out
    finally:
        for name in ("HANDOVER_SELFTEST_TIMEOUT", "HANDOVER_TEACH_MODEL", "HANDOVER_TEACH_MOCK"):
            os.environ.pop(name, None)
    assert teach._model() == config.tunable("HANDOVER_TEACH_MODEL").default


# ---------------------------------------------------------------- Claude fallback (fake client, fake budget)

@contextlib.contextmanager
def _env(**values):
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


NO_KEYS = dict(GEMINI_API_KEY=None, GOOGLE_API_KEY=None, ANTHROPIC_API_KEY=None, HANDOVER_TEACH_MOCK=None,
               HANDOVER_TEACH_PROVIDER=None)


@contextlib.contextmanager
def _no_env_file():
    real = teach._env_file
    teach._env_file = lambda: {}
    try:
        yield
    finally:
        teach._env_file = real


def test_provider_choice():
    with _no_env_file(), _env(**NO_KEYS):
        assert teach.teach_provider() == "mock"
        with _env(ANTHROPIC_API_KEY="sk-ant-fake"):
            assert teach.teach_provider() == "claude"
            with _env(GEMINI_API_KEY="g-fake"):
                assert teach.teach_provider() == "gemini"  # Gemini first: it hears the narration, free tier
                with _env(HANDOVER_TEACH_PROVIDER="claude"):
                    assert teach.teach_provider() == "claude"
                with _env(HANDOVER_TEACH_MOCK="1"):
                    assert teach.teach_provider() == "mock"
        with _env(HANDOVER_TEACH_PROVIDER="gemini"):
            assert teach.teach_provider() == "gemini"  # explicit choice; extract then reports the missing key


class _FakeSpend:
    def __init__(self, allow=True):
        self.allowed, self.calls = allow, []

    def allow(self):
        self.calls.append("allow")
        return self.allowed

    def record(self, model, usage):
        self.calls.append(("record", model, usage))


@contextlib.contextmanager
def _fake_claude(spend, answer=None, stop_reason="end_turn"):
    import sys

    import anthropic

    import server

    log = {"requests": []}
    answer = answer or {
        "steps": [{"start": "00:00", "end": "00:01.5", "title": "Lay it flat", "check_question": "Is it flat?",
                   "prerequisites": [], "ref_time": "00:01", "common_mistake": ""},
                  {"start": "00:01.5", "end": "00:03", "title": "Fold it", "check_question": "Is it folded?",
                   "prerequisites": [1], "ref_time": "", "common_mistake": "Flip it over first."}],
        "safety": [], "tools": ["Paper"],
    }

    class Messages:
        def create(self, **kw):
            log["requests"].append(kw)
            spend.calls.append("create")
            usage = type("U", (), {"input_tokens": 1000, "output_tokens": 200})()
            block = type("B", (), {"type": "text", "text": json.dumps(answer)})()
            return type("M", (), {"content": [block], "usage": usage, "stop_reason": stop_reason})()

    class Client:
        def __init__(self, api_key):
            log["api_key"] = api_key
            self.messages = Messages()

    real_client = anthropic.Anthropic
    had_attr, real_attr = hasattr(server, "spend"), getattr(server, "spend", None)
    real_mod = sys.modules.get("server.spend")
    anthropic.Anthropic = Client
    sys.modules["server.spend"] = spend
    server.spend = spend
    try:
        yield log
    finally:
        anthropic.Anthropic = real_client
        if real_mod is None:
            sys.modules.pop("server.spend", None)
        else:
            sys.modules["server.spend"] = real_mod
        if had_attr:
            server.spend = real_attr
        else:
            server.__dict__.pop("spend", None)


def test_claude_request_shape_and_budget():
    d = _demo_copy("claude-extract")
    spend = _FakeSpend()
    lines = []
    with _env(ANTHROPIC_API_KEY="sk-ant-fake", HANDOVER_CLAUDE_TEACH_MODEL=None), _fake_claude(spend) as log:
        ex = teach.extract_claude(d / "norm.mp4", lambda st, msg: lines.append(msg))
    (req,) = log["requests"]
    assert log["api_key"] == "sk-ant-fake"
    assert req["model"] == "claude-haiku-5-5" and req["max_tokens"] == 8000
    assert not {"temperature", "top_p", "top_k"} & set(req)
    fmt = req["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"steps", "safety", "tools"}
    blocks = req["messages"][0]["content"]
    labels, images = blocks[0:-1:2], blocks[1:-1:2]
    assert len(images) == 40 and all(b["type"] == "image" for b in images)  # 40 s video, about 1 fps
    assert [b["text"] for b in labels[:3]] == ["00:00", "00:01", "00:02"]
    assert blocks[-1]["type"] == "text" and "no audio" in blocks[-1]["text"].lower()
    assert spend.calls[0] == "allow" and spend.calls[1] == "create"
    assert spend.calls[2][0:2] == ("record", "claude-haiku-5-5")
    assert ex.transcript == [] and ex.tools == ["Paper"] and ex.steps[1].common_mistake == "Flip it over first."
    assert any("captions will be empty" in m for m in lines)
    assert not list(d.glob("proxy*"))


def test_claude_frames_are_capped_and_even():
    with tempfile.TemporaryDirectory() as tmp:
        frames = teach.sample_frames(DEMO / "norm.mp4", Path(tmp), max_frames=10)
    assert len(frames) == 10
    assert [round(t, 1) for t, _ in frames] == [0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.0, 32.0, 36.0]


def test_claude_respects_the_budget_and_missing_spend():
    import sys

    d = _demo_copy("claude-budget")
    spend = _FakeSpend(allow=False)
    with _env(ANTHROPIC_API_KEY="sk-ant-fake"), _fake_claude(spend) as log:
        try:
            teach.extract_claude(d / "norm.mp4")
            raise AssertionError("expected the budget to stop the call")
        except RuntimeError as e:
            assert "spending limit" in str(e)
        assert log["requests"] == [] and "create" not in spend.calls
        import server

        sys.modules["server.spend"] = None  # as if server/spend.py did not exist
        server.__dict__.pop("spend", None)
        try:
            teach.extract_claude(d / "norm.mp4")
            raise AssertionError("expected an error without spend.py")
        except RuntimeError as e:
            assert "spend.py is missing" in str(e)
        assert log["requests"] == []


def test_claude_lesson_has_empty_captions_and_scrubbed_errors():
    src = TMP / "claude-src.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(src))
    lines = []
    with _no_env_file(), _env(**{**NO_KEYS, "ANTHROPIC_API_KEY": "sk-ant-fake"}), _fake_claude(_FakeSpend()):
        lesson = teach.process_upload(src, "claude-lesson", "Claude lesson", lambda st, msg: lines.append(msg))
    d = teach.lessons_root() / "claude-lesson"
    assert [s["check_type"] for s in lesson["steps"]] == ["manual", "camera"]  # step 1 manual, as for Gemini
    assert all((d / s["captions"]).read_text(encoding="utf-8").strip() == "WEBVTT" for s in lesson["steps"])
    assert lesson["tools"] == ["Paper"] and any("no audio" in m for m in lines)
    with _no_env_file(), _env(**{**NO_KEYS, "ANTHROPIC_API_KEY": "sk-ant-secret-123"}):
        assert teach.scrub(f"bad key sk-ant-secret-123 in {d.as_posix()}") == "bad key *** in <lessons>/claude-lesson"
        spend = _FakeSpend()
        with _fake_claude(spend, stop_reason="refusal"):
            try:
                teach.process_upload(src, "claude-refused", "X")
                raise AssertionError("expected an error")
            except RuntimeError as e:
                assert "declined" in str(e) and str(TMP) not in str(e)


def test_sanitize_id_fits_the_read_rule():
    import re

    long_id = teach.sanitize_id("A" * 63 + " b" + "c" * 10)
    assert len(long_id) <= 64 and not long_id.endswith("-")
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", long_id)
    assert teach.sanitize_id("  My Lesson!! ") == "my-lesson"


def test_recut_empty_question_gets_contract_default():
    d = _demo_copy("default-question")
    lesson = _read(d)
    lesson["steps"][1]["check_question"] = ""          # camera step, no question
    lesson["steps"][3]["check_question"] = "manual"    # explicit manual
    _write(d, lesson)
    out = teach.recut(d)
    assert (out["steps"][1]["check_type"], out["steps"][1]["check_question"]) == ("camera", "Is this step finished?")
    assert (out["steps"][3]["check_type"], out["steps"][3]["check_question"]) == ("manual", "")
    assert out["steps"][2]["check_type"] == "manual"   # check_type manual stays manual


def test_job_errors_are_scrubbed():
    lessons = teach.lessons_root()
    os.environ["GEMINI_API_KEY"] = "AIzaFAKEKEY123"
    try:
        raw = f"boom AIzaFAKEKEY123 at {lessons}/x/norm.mp4 and {teach.REPO}/server/uploads/a.mov"
        assert teach.scrub(raw) == "boom *** at <lessons>/x/norm.mp4 and <repo>/server/uploads/a.mov"
        real = teach.build

        def fail(*a, **k):
            raise RuntimeError(raw)

        teach.build = fail
        try:
            teach.process_upload(Path("x.mov"), "x", "X")
            raise AssertionError("expected an error")
        except RuntimeError as e:
            assert "AIzaFAKEKEY123" not in str(e) and str(lessons) not in str(e) and str(teach.REPO) not in str(e)
        finally:
            teach.build = real
    finally:
        os.environ.pop("GEMINI_API_KEY", None)


def test_handover_ffmpeg_comes_first():
    real = teach._bin("ffmpeg")
    link_dir = TMP / "ffbin"
    link_dir.mkdir(exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        (link_dir / name).unlink(missing_ok=True)
        try:
            (link_dir / name).symlink_to(teach._bin(name))
        except OSError:  # Windows without the symlink privilege: a hard link works the same here
            os.link(teach._bin(name), link_dir / name)
    os.environ["HANDOVER_FFMPEG"] = str(link_dir / "ffmpeg")
    try:
        assert teach._bin("ffmpeg") == str(link_dir / "ffmpeg")
        assert teach._bin("ffprobe") == str(link_dir / "ffprobe")
        os.environ["HANDOVER_FFMPEG"] = str(link_dir / "missing")
        try:
            teach._bin("ffmpeg")
            raise AssertionError("expected an error")
        except RuntimeError as e:
            assert "HANDOVER_FFMPEG" in str(e)
    finally:
        os.environ.pop("HANDOVER_FFMPEG", None)
    assert teach._bin("ffmpeg") == real


def test_cli_dry_run_and_errors():
    d = _demo_copy("cli")
    before = (d / "lesson.json").read_bytes()
    code, out, _ = _cli("--recut", str(d), "--dry-run")
    assert code == 0 and "would cut 5 steps" in out and "00:08 to 00:16" in out
    assert (d / "lesson.json").read_bytes() == before
    code, _, err = _cli("--recut", str(TMP / "missing"))
    assert code == 2 and "no lesson.json" in err
    code, _, err = _cli(str(TMP / "nope.mp4"), "--id", "x")
    assert code == 2 and "video not found" in err
    code, _, err = _cli(str(DEMO / "norm.mp4"), "--id", "x", "--dry-run")
    assert code == 2 and "never calls Gemini" in err
    code, out, _ = _cli(str(DEMO / "norm.mp4"), "--id", "Dry Run", "--steps-json", str(DEMO / "extraction.json"),
                        "--dry-run")
    assert code == 0 and "5 steps from 40.0 s" in out
    assert not (teach.lessons_root() / "dry-run").exists()
    lesson = _read(d)
    lesson["steps"][2]["start"] = "nonsense"
    _write(d, lesson)
    code, _, err = _cli("--recut", str(d))
    assert code == 2 and "step 3" in err


# ---------------------------------------------------------------- local transcription (fake faster-whisper)

NARRATION = [(0.2, 1.4, " Lay it flat. "), (1.6, 2.8, "Now fold it.")]
_MISSING = object()


@contextlib.contextmanager
def _fake_whisper(segments=NARRATION, cached=True, fail_init=False):
    import types as pytypes

    log = {"inits": [], "calls": []}

    class Seg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class WhisperModel:
        def __init__(self, name, device="auto", compute_type="default", **kw):
            if fail_init:
                raise RuntimeError("could not download the model: no network")
            log["inits"].append((name, device, compute_type))

        def transcribe(self, audio, **kw):
            log["calls"].append((str(audio.dtype), len(audio), kw))
            return iter([Seg(*x) for x in segments]), None

    def download_model(name, local_files_only=False, **kw):
        if not cached:
            raise FileNotFoundError("not in the cache")
        return "/cache/" + name

    mod = pytypes.ModuleType("faster_whisper")
    mod.WhisperModel = WhisperModel
    utils = pytypes.ModuleType("faster_whisper.utils")
    utils.download_model = download_model
    mod.utils = utils
    saved = {k: sys.modules.get(k, _MISSING) for k in ("faster_whisper", "faster_whisper.utils")}
    sys.modules["faster_whisper"], sys.modules["faster_whisper.utils"] = mod, utils
    teach._whisper_models.clear()
    try:
        yield log
    finally:
        for k, v in saved.items():
            if v is _MISSING:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        teach._whisper_models.clear()


def _claude_src() -> Path:
    src = TMP / "claude-src.mp4"
    if not src.exists():
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=3", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(src))
    return src


def _audio_src() -> Path:
    src = TMP / "with-audio.mp4"
    if not src.exists():
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
    return src


def test_claude_prompts_carry_the_splitting_rules():
    for prompt in (teach.CLAUDE_PROMPT, teach.CLAUDE_NARRATED_PROMPT):
        low = prompt.lower()
        assert "flipping or turning the object over is always its own step" in low
        assert "crease-only step" in low and "check_question is exactly: manual" in low
        assert "the first step is the setup" in low and "state at the end of that step" in low
        assert "no filler steps" in low and "never use color" in low
    assert "never merge two narrated actions" in teach.CLAUDE_NARRATED_PROMPT.lower()
    assert "no audio" in teach.CLAUDE_PROMPT.lower() and "no audio" not in teach.CLAUDE_NARRATED_PROMPT.lower()


def test_model_steps_made_contiguous_and_creases_manual():
    def st(a, b, title, q="Is it folded?", pre=()):
        return teach.Step(start=a, end=b, title=title, check_question=q, prerequisites=list(pre))

    # the first e2e Haiku run: gaps (00:14 to 00:16, 00:22 to 00:25) and overlaps (00:41 vs 00:40)
    ex = teach.Extraction(transcript=[], steps=[
        st("00:00", "00:09", "Lay the sheet flat"), st("00:09", "00:14", "Fold corner to corner", pre=[1]),
        st("00:16", "00:22", "Fold and unfold the other diagonal", pre=[2]),
        st("00:25", "00:41", "Fold all four corners in", pre=[3]),
        st("00:40", "00:48", "Fold in half both ways and unfold", pre=[4]),
        st("00:48", "00:48.3", "Tiny", pre=[5]), st("00:48.3", "00:59", "Pinch the points", pre=[6]),
    ])
    out = teach._crease_steps_manual(teach._contiguous(ex))
    spans = [(s.start, s.end) for s in out.steps]
    assert spans == [("00:00", "00:09"), ("00:09", "00:16"), ("00:16", "00:25"), ("00:25", "00:40"),
                     ("00:40", "00:48.3"), ("00:48.3", "00:59")], spans  # the 0.3 s step is dropped
    assert out.steps[5].prerequisites == [] and out.steps[4].prerequisites == [4]
    manual = [teach._is_manual(s.check_question) for s in out.steps]
    assert manual == [False, False, True, False, True, False], manual
    assert not teach._CREASE_TITLE.search("Unfold the paper") and teach._CREASE_TITLE.search("Make a crease")


def test_merged_flip_is_split_at_the_narration():
    seg = teach.Segment
    ex = teach.Extraction(  # the second e2e Haiku run: the flip merged into step 4
        transcript=[seg(start=25.5, end=28.0, text="Fold all four corners to the center."),
                    seg(start=33.2, end=35.6, text="Now flip the whole thing over.")],
        steps=[teach.Step(start="00:00", end="00:25", title="Lay it flat", check_question="manual", prerequisites=[]),
               teach.Step(start="00:25", end="00:40", title="Fold all four corners into the center and flip over",
                          check_question="Is the smooth side up?", prerequisites=[1], ref_time="00:39",
                          common_mistake="Flip it over first."),
               teach.Step(start="00:40", end="00:48", title="Fold the new corners in", check_question="Q?",
                          prerequisites=[2])])
    out = teach._split_flips(ex).steps
    assert [(s.start, s.end, s.title) for s in out] == [
        ("00:00", "00:25", "Lay it flat"), ("00:25", "00:33.2", "Fold all four corners into the center"),
        ("00:33.2", "00:40", "Flip it over"), ("00:40", "00:48", "Fold the new corners in")]
    assert [s.prerequisites for s in out] == [[], [1], [2], [3]]
    assert out[1].check_question == "manual" and out[1].common_mistake == "" and out[1].ref_time == ""
    assert (out[2].check_question, out[2].ref_time, out[2].common_mistake) == \
        ("Is the smooth side up?", "00:39", "Flip it over first.")
    # an existing flip step, or a flip line near the step edges, is left alone
    alone = teach.Extraction(transcript=[seg(start=40.2, end=42.0, text="Flip it over.")], steps=[
        teach.Step(start="00:40", end="00:48", title="Flip it over", check_question="Q?", prerequisites=[])])
    assert teach._split_flips(alone) == alone
    late = teach.Extraction(transcript=[seg(start=31.7, end=33.0, text="Flip the whole thing over.")], steps=[
        teach.Step(start="00:25", end="00:34", title="Fold the corners in", check_question="Q?", prerequisites=[]),
        teach.Step(start="00:34", end="00:40", title="Flip the whole thing over", check_question="Q?",
                   prerequisites=[1])])
    assert teach._split_flips(late) == late  # no second flip step when the model's flip starts late


# ---------------------------------------------------------------- color guard

def _colored_extraction():
    return teach.Extraction(transcript=[], steps=[
        teach.Step(start="00:00", end="00:08", title="Lay it flat", check_question="manual", prerequisites=[]),
        teach.Step(start="00:08", end="00:16", title="Fold in half", check_question="Is it a big triangle?",
                   prerequisites=[1]),
        teach.Step(start="00:16", end="00:24", title="Flip it over", prerequisites=[2],
                   check_question="Is the plain blue side facing up as a diamond?"),
        teach.Step(start="00:24", end="00:32", title="Fold the corners", check_question="Is it green-colored?",
                   prerequisites=[3]),
    ])


def test_color_words_match_the_lint_list():
    import importlib.util

    spec = importlib.util.spec_from_file_location("lesson_lint_copy", teach.REPO / "scripts" / "lesson_lint.py")
    lint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lint)
    assert teach.COLOR_WORDS == lint.COLOR_WORDS
    assert teach.strip_colors("Is the plain blue side facing up as a diamond?") == \
        "Is the plain side facing up as a diamond?"
    assert teach.strip_colors("Is it green-colored?") == "manual"  # too little left to ask
    assert teach.strip_colors("Are there four flaps?") == "Are there four flaps?"


def test_color_guard_offline_strips_without_a_call():
    lines = []
    with _env(HANDOVER_NO_NETWORK="1", ANTHROPIC_API_KEY="sk-ant-fake"), _fake_claude(_FakeSpend()) as log:
        out = teach.guard_colors(_colored_extraction(), "claude", lambda st, m: lines.append(m))
    assert log["requests"] == []
    qs = [s.check_question for s in out.steps]
    assert qs == ["manual", "Is it a big triangle?", "Is the plain side facing up as a diamond?", "manual"], qs
    assert any("HANDOVER_NO_NETWORK=1" in m for m in lines)
    assert teach.guard_colors(teach.Extraction(transcript=[], steps=out.steps), "claude").steps == out.steps


def test_color_guard_rephrases_once_with_claude():
    spend = _FakeSpend()
    answer = {"questions": [{"n": 3, "question": "Is the smooth side facing up, shaped like a diamond?"},
                            {"n": 4, "question": "Is it still red?"}]}  # step 4 comes back with a color again
    lines = []
    with _env(HANDOVER_NO_NETWORK=None, ANTHROPIC_API_KEY="sk-ant-fake"), \
            _fake_claude(spend, answer=answer) as log:
        out = teach.guard_colors(_colored_extraction(), "claude", lambda st, m: lines.append(m))
    (req,) = log["requests"]  # one batched call for both offending questions
    text = req["messages"][0]["content"]
    assert "3. (step: Flip it over) Is the plain blue side" in text and "4. (step: Fold the corners)" in text
    assert "big triangle" not in text and "never color" in text
    assert req["output_config"]["format"]["type"] == "json_schema" and not {"temperature", "top_p"} & set(req)
    assert spend.calls[0] == "allow" and spend.calls[1] == "create" and spend.calls[2][0] == "record"
    qs = [s.check_question for s in out.steps]
    assert qs[2] == "Is the smooth side facing up, shaped like a diamond?" and qs[3] == "manual", qs
    assert any("Step 4: made manual" in m for m in lines)


def test_color_guard_falls_back_when_the_call_fails_or_budget_is_out():
    for spend, provider in ((_FakeSpend(allow=False), "claude"), (_FakeSpend(), "claude")):
        lines = []
        with _env(HANDOVER_NO_NETWORK=None, ANTHROPIC_API_KEY="sk-ant-fake"), _fake_claude(spend) as log:
            if spend.allowed:  # make the call itself fail
                import anthropic

                class Boom:
                    def __init__(self, api_key):
                        self.messages = self

                    def create(self, **kw):
                        raise RuntimeError("network down")

                anthropic.Anthropic = Boom
            out = teach.guard_colors(_colored_extraction(), provider, lambda st, m: lines.append(m))
        assert out.steps[2].check_question == "Is the plain side facing up as a diamond?"
        assert any("Rephrase call failed" in m for m in lines), lines
        assert log["requests"] == []


def test_color_guard_runs_in_the_claude_build():
    answer = {"steps": [
        {"start": "00:00", "end": "00:01.5", "title": "Lay it flat", "check_question": "Is it flat?",
         "prerequisites": [], "ref_time": "", "common_mistake": ""},
        {"start": "00:01.5", "end": "00:03", "title": "Turn the sheet", "prerequisites": [1], "ref_time": "",
         "check_question": "Is the blue side facing up now?", "common_mistake": ""}], "safety": [], "tools": []}
    with _no_env_file(), _env(**{**NO_KEYS, "ANTHROPIC_API_KEY": "sk-ant-fake", "HANDOVER_NO_NETWORK": "1"}), \
            _fake_claude(_FakeSpend(), answer=answer) as log:
        lesson = teach.process_upload(_claude_src(), "color-guard", "Color guard")
    assert len(log["requests"]) == 1  # the extraction only; offline, no rephrase call
    assert lesson["steps"][1]["check_question"] == "Is the side facing up now?"
    assert not any(teach.color_words(s["check_question"]) for s in lesson["steps"])


def test_color_guard_rephrases_with_gemini():
    from google import genai

    seen = {}

    class Models:
        def generate_content(self, model, contents, config):
            seen.update(model=model, contents=contents)
            return type("R", (), {"text": json.dumps({"questions": [
                {"n": 3, "question": "Is the smooth side up as a diamond?"},
                {"n": 4, "question": "Are four flaps folded to the center?"}]})})()

    class Client:
        def __init__(self, api_key, http_options):
            self.models = Models()

    real = genai.Client
    genai.Client = Client
    try:
        with _env(HANDOVER_NO_NETWORK=None, GEMINI_API_KEY="AIza-test-not-real"):
            out = teach.guard_colors(_colored_extraction(), "gemini")
    finally:
        genai.Client = real
    assert seen["model"] == teach._model() and "Is it green-colored?" in seen["contents"]
    assert [s.check_question for s in out.steps][2:] == ["Is the smooth side up as a diamond?",
                                                        "Are four flaps folded to the center?"]


def test_transcript_reaches_claude_and_captions():
    lines = []
    with _no_env_file(), _env(**{**NO_KEYS, "ANTHROPIC_API_KEY": "sk-ant-fake", "HANDOVER_TRANSCRIBE": None}), \
            _fake_whisper() as wlog, _fake_claude(_FakeSpend()) as clog:
        lesson = teach.process_upload(_claude_src(), "claude-narrated", "Narrated", lambda st, m: lines.append(m))
    blocks = clog["requests"][0]["messages"][0]["content"]
    assert blocks[0]["text"] == "Narration transcript:\n[00:00.2 to 00:01.4] Lay it flat.\n[00:01.6 to 00:02.8] Now fold it."
    assert "primary boundary signal" in blocks[-1]["text"] and "no audio" not in blocks[-1]["text"].lower()
    assert any(b["type"] == "image" for b in blocks)
    d = teach.lessons_root() / "claude-narrated"
    vtt1 = (d / lesson["steps"][0]["captions"]).read_text(encoding="utf-8")
    vtt2 = (d / lesson["steps"][1]["captions"]).read_text(encoding="utf-8")
    assert "00:00:00.200 --> 00:00:01.400\nLay it flat." in vtt1, vtt1
    assert "Now fold it." in vtt2 and "Now fold it." not in vtt1
    stored = json.loads((d / "extraction.json").read_text(encoding="utf-8"))
    assert [seg["text"] for seg in stored["transcript"]] == ["Lay it flat.", "Now fold it."]
    (dtype, samples, kw), = wlog["calls"]
    # 16 kHz mono float samples of norm.mp4 (3 s), so faster-whisper never opens a file itself
    assert dtype == "float32" and abs(samples - 48000) < 1600 and kw == {"vad_filter": True, "word_timestamps": True}
    assert any(m == "Transcribing narration" for m in lines)
    assert any(m.startswith("Transcribed 2 narration segments in ") for m in lines)
    assert any("2 narration lines" in m for m in lines)


def test_whisper_failure_falls_back_to_frames_only():
    d = _demo_copy("whisper-fallback")
    for ctx in (contextlib.nullcontext(), _fake_whisper(fail_init=True)):  # package missing, then download fails
        lines = []
        with _env(ANTHROPIC_API_KEY="sk-ant-fake", HANDOVER_TRANSCRIBE=None), ctx, _fake_claude(_FakeSpend()) as log:
            ex = teach.extract_claude(d / "norm.mp4", lambda st, m: lines.append(m))
        assert ex.transcript == [] and len(log["requests"]) == 1
        assert "no audio" in log["requests"][0]["messages"][0]["content"][-1]["text"].lower()
        assert any(m.startswith("Speech model unavailable") for m in lines), lines
        assert any("captions will be empty" in m for m in lines)


def test_whisper_model_loaded_once_and_download_announced():
    src = _audio_src()
    lines = []
    with _env(HANDOVER_WHISPER_MODEL=None), _fake_whisper(cached=False) as log:
        first = teach.transcribe(src, lambda st, m: lines.append(m))
        second = teach.transcribe(src, lambda st, m: lines.append(m))
    assert log["inits"] == [("small.en", "cpu", "int8")]  # one load per process
    assert len(log["calls"]) == 2 and first == second
    assert [(s.start, s.end, s.text) for s in first] == [(0.2, 1.4, "Lay it flat."), (1.6, 2.8, "Now fold it.")]
    assert sum("Downloading speech model small.en once, about 460 MB" in m for m in lines) == 1
    lines.clear()
    with _env(HANDOVER_WHISPER_MODEL="base.en"), _fake_whisper(cached=True) as log:
        teach.transcribe(src, lambda st, m: lines.append(m))
    assert log["inits"] == [("base.en", "cpu", "int8")] and not any("Downloading" in m for m in lines)


def test_gemini_transcribe_modes():
    src = _audio_src()
    gemini = teach.Extraction(transcript=[teach.Segment(start=0, end=1, text="from gemini")], steps=[])
    say = lambda st, m: None  # noqa: E731
    with _fake_whisper():
        with _env(HANDOVER_TRANSCRIBE=None):
            assert teach.transcribe_mode("gemini") == "model" and teach.transcribe_mode("claude") == "local"
            assert teach._gemini_transcript_mode(gemini, src, say).transcript[0].text == "from gemini"
        with _env(HANDOVER_TRANSCRIBE="local"):
            assert [s.text for s in teach._gemini_transcript_mode(gemini, src, say).transcript] == \
                ["Lay it flat.", "Now fold it."]
        with _env(HANDOVER_TRANSCRIBE="off"):
            assert teach._gemini_transcript_mode(gemini, src, say).transcript == []
            assert teach.transcribe_mode("claude") == "off"
    with _env(HANDOVER_TRANSCRIBE="local"):  # whisper unavailable: Gemini's transcript stays
        assert teach._gemini_transcript_mode(gemini, src, say).transcript[0].text == "from gemini"


def test_real_whisper_base_en():
    """Opt in: HANDOVER_TEST_REAL_WHISPER=1 downloads base.en (about 145 MB, free) and transcribes macOS speech."""
    if not _REAL_WHISPER:
        return
    import time

    aiff, clip = TMP / "say.aiff", TMP / "say.mp4"
    subprocess.run(["say", "-o", str(aiff), "Fold the paper in half. Now flip it over."], check=True)
    _ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=10", "-i", str(aiff), "-af", "apad",
            "-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip))
    lines = []
    with _env(HANDOVER_WHISPER_MODEL="base.en"):
        teach._whisper_models.clear()
        t0 = time.time()
        segs = teach.transcribe(clip, lambda st, m: lines.append(m))
        first = time.time() - t0
        t0 = time.time()
        teach.transcribe(clip)
        again = time.time() - t0
    words = " ".join(s.text for s in segs).lower()
    for w in ("fold", "paper", "half", "flip", "over"):
        assert w in words, words
    assert all(0 <= s.start < s.end <= 10.5 for s in segs)
    print(f"real whisper base.en: first call {first:.1f} s (includes any download and load), "
          f"second call {again:.1f} s; text: {words!r}; lines: {lines}")


# ---------------------------------------------------------------- minimum step length (HANDOVER_MIN_STEP_S)

def _st(a, b, title, q="Is it folded?", pre=(), ref="", mistake=""):
    return teach.Step(start=a, end=b, title=title, check_question=q, prerequisites=list(pre), ref_time=ref,
                      common_mistake=mistake)


def test_short_steps_merge_into_previous_and_first_into_next():
    ex = teach.Extraction(transcript=[], steps=[
        _st("00:00", "00:03", "Lay it flat", q="manual"),                       # short first step: into the next
        _st("00:03", "00:15", "Fold in half", q="Is it a rectangle?", pre=[1], mistake="Line up the edges."),
        _st("00:15", "00:19", "Unfold it", q="Is there one crease line?", pre=[2], ref="00:18.5"),  # into previous
        _st("00:19", "00:22", "Flip it over", q="Is the plain side up?", pre=[3]),      # short flip: never merged
        _st("00:22", "00:25", "Start the corners", pre=[4]),                     # previous is the flip: into the next
        _st("00:25", "00:40", "Fold the corners to the center", q="Are four flaps at the center?", pre=[5]),
    ])
    out = teach._merge_short_steps(ex, 6.0).steps
    assert [(s.start, s.end, s.title) for s in out] == [
        ("00:00", "00:19", "Fold in half"), ("00:19", "00:22", "Flip it over"),
        ("00:22", "00:40", "Fold the corners to the center")], out
    # the survivor was camera, so the merged step asks about the later step's (merged) end state
    assert out[0].check_question == "Is there one crease line?" and out[0].ref_time == "00:18.5"
    assert out[0].common_mistake == "Line up the edges."
    assert [s.prerequisites for s in out] == [[], [1], [2]]
    # merged camera only if the surviving (longer) step was camera
    ex = teach.Extraction(transcript=[], steps=[
        _st("00:00", "00:10", "Crease it both ways", q="manual"), _st("00:10", "00:12", "Press flat", pre=[1])])
    (only,) = teach._merge_short_steps(ex, 6.0).steps
    assert (only.start, only.end, only.title, only.check_question) == ("00:00", "00:12", "Crease it both ways", "manual")
    # a lone flip between two flips stays; 0 turns merging off
    flips = teach.Extraction(transcript=[], steps=[_st("00:00", "00:02", "Flip it over"),
                                                   _st("00:02", "00:04", "Flip it over again")])
    assert teach._merge_short_steps(flips, 6.0) == flips
    assert teach._merge_short_steps(ex, 0) == ex


def test_min_step_comes_from_the_env_and_runs_in_the_build():
    with _env(HANDOVER_MIN_STEP_S=None):
        assert teach.min_step_s() == 6.0
    with _env(HANDOVER_MIN_STEP_S="2.5"):
        assert teach.min_step_s() == 2.5
    with _env(HANDOVER_MIN_STEP_S="-1"):
        assert teach.min_step_s() == 6.0  # out of range: the default
    answer = {"steps": [
        {"start": "00:00", "end": "00:01", "title": "Lay it flat", "check_question": "manual",
         "prerequisites": [], "ref_time": "", "common_mistake": ""},
        {"start": "00:01", "end": "00:02.5", "title": "Fold it in half", "check_question": "Is it a rectangle?",
         "prerequisites": [1], "ref_time": "", "common_mistake": ""},
        {"start": "00:02.5", "end": "00:03", "title": "Press it", "check_question": "Is it flat?",
         "prerequisites": [2], "ref_time": "", "common_mistake": ""}], "safety": [], "tools": []}
    with _no_env_file(), _env(**{**NO_KEYS, "ANTHROPIC_API_KEY": "sk-ant-fake", "HANDOVER_MIN_STEP_S": "1.2"}), \
            _fake_claude(_FakeSpend(), answer=answer):
        lesson = teach.process_upload(_claude_src(), "min-step", "Min step")
    # the 0.5 s step merges into the step before it; step 1 (1 s, first) merges into the next
    assert [(s["start"], s["end"], s["title"]) for s in lesson["steps"]] == [("00:00", "00:03", "Fold it in half")]


# ---------------------------------------------------------------- recut swap on Windows (WinError 32)

def _swap_fixture(name: str, old_count: int, new_count: int) -> Path:
    d = TMP / "swap" / name
    shutil.rmtree(d, ignore_errors=True)
    for sub, ext in (("clips", "mp4"), ("captions", "vtt"), ("frames", "jpg")):
        (d / sub).mkdir(parents=True)
        (d / ".recut_tmp" / sub).mkdir(parents=True)
        for n in range(1, old_count + 1):
            (d / sub / f"{n:02d}.{ext}").write_text(f"old {n}", encoding="utf-8")
        for n in range(1, new_count + 1):
            (d / ".recut_tmp" / sub / f"{n:02d}.{ext}").write_text(f"new {n}", encoding="utf-8")
    return d


def test_swap_falls_back_to_copying_when_renames_are_refused():
    import pytest

    d = _swap_fixture("refused", old_count=3, new_count=2)
    real = Path.replace
    tries = []

    def refuse(self, target):
        if self.is_dir():
            tries.append(self.name)
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(self, target)

    lines = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", refuse)
        mp.setattr(teach, "SWAP_WAIT_S", 0.0)
        teach._swap_in(d, d / ".recut_tmp", lambda st, m: lines.append(m))
    assert tries.count("clips") == teach.SWAP_TRIES == 5  # retried 5 times before falling back
    for sub, ext in (("clips", "mp4"), ("captions", "vtt"), ("frames", "jpg")):
        assert sorted(f.name for f in (d / sub).iterdir()) == [f"01.{ext}", f"02.{ext}"]  # stale 03 removed
        assert (d / sub / f"02.{ext}").read_text(encoding="utf-8") == "new 2"
    assert not (d / ".recut_tmp").exists() and not (d / ".recut_old").exists()
    assert any("copied the new files" in m for m in lines)


def test_swap_retries_then_renames():
    import pytest

    d = _swap_fixture("busy-once", old_count=2, new_count=1)
    real, calls = Path.replace, []

    def busy_once(self, target):
        calls.append(self.name)
        if self.is_dir() and calls.count(self.name) == 1 and self.parent == d:
            raise PermissionError(32, "in use")
        return real(self, target)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", busy_once)
        mp.setattr(teach, "SWAP_WAIT_S", 0.0)
        teach._swap_in(d, d / ".recut_tmp")
    assert sorted(f.name for f in (d / "clips").iterdir()) == ["01.mp4"]
    assert (d / "clips" / "01.mp4").read_text(encoding="utf-8") == "new 1"
    assert not (d / ".recut_tmp").exists() and not (d / ".recut_old").exists()


def test_cut_removes_a_stale_recut_tmp():
    d = _demo_copy("stale-tmp")
    (d / ".recut_tmp" / "clips").mkdir(parents=True)
    (d / ".recut_tmp" / "clips" / "99.mp4").write_bytes(b"left over")
    (d / ".recut_tmp" / "junk.txt").write_text("x", encoding="utf-8")
    teach.recut(d)
    assert not (d / "clips" / "99.mp4").exists() and not (d / ".recut_tmp").exists()
    assert sorted(f.name for f in (d / "clips").iterdir()) == [f"{n:02d}.mp4" for n in range(1, 6)]


# ---------------------------------------------------------------- reference frames: pause after the step

def test_ref_frame_found_in_the_pause_after_the_step():
    # 6 s of motion, then the picture held still for 1.5 s: a step ending at 5 s has no still frame inside, so
    # the pause just after its end is used (written as a null ref_time, which recut finds again)
    src = TMP / "pause-after.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=6", "-vf", "tpad=stop_mode=clone:stop_duration=1.5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src))
    t = teach.pick_ref_time(src, 0.0, 5.0)
    assert t is not None and 6.0 <= t <= 7.5, t
    assert teach.pick_ref_time(src, 0.0, 5.0, extend=0) < 5.0  # the old rule alone stays inside the step
    t = teach.pick_ref_time(src, 0.0, 3.0)  # nothing still within 2.5 s: the stillest frame in the window
    assert t is not None and 2.5 <= t < 3.0, t
    clip, out = TMP / "pause-clip.mp4", TMP / "pause-ref.jpg"
    _ffmpeg("-i", str(src), "-t", "5", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip))
    assert teach._ref_frame(src, clip, out, 0.0, 5.0, "", False) is None and out.stat().st_size > 0


# ---------------------------------------------------------------- check questions from the reference frames

def test_questions_from_refs_replace_and_fall_back():
    import pytest

    d = _demo_copy("ref-questions")
    lesson = _read(d)
    lesson["steps"][2]["check_type"] = "manual"
    lesson["steps"][2]["check_question"] = ""
    _write(d, lesson)
    original = [s["check_question"] for s in lesson["steps"]]
    seen = []

    def boom(provider, items):
        seen.append((provider, items))
        raise RuntimeError("network down")

    lines = []
    with _env(HANDOVER_NO_NETWORK=None, ANTHROPIC_API_KEY="sk-ant-fake"), pytest.MonkeyPatch.context() as mp:
        mp.setattr(teach, "_ref_questions_call", boom)
        out = teach.questions_from_refs(d, _read(d), "claude", lambda st, m: lines.append(m))
    assert [s["check_question"] for s in out["steps"]] == original and _read(d) == lesson  # unchanged on failure
    assert any("keeping the extracted questions" in m for m in lines)
    (provider, items), = seen
    assert provider == "claude" and [it["n"] for it in items] == [1, 2, 4, 5]  # camera steps only
    assert all(it["before"][:2] == b"\xff\xd8" and it["done"][:2] == b"\xff\xd8" for it in items)
    by_n = {it["n"]: it for it in items}
    assert by_n[2]["before"] == by_n[1]["done"]  # BEFORE is the previous step's reference

    def answer(provider, items):
        return {1: "Is there one square with a diagonal crease?", 2: "Is it red now?", 5: "  Are four flaps   up? "}

    with _env(HANDOVER_NO_NETWORK=None, ANTHROPIC_API_KEY="sk-ant-fake"), pytest.MonkeyPatch.context() as mp:
        mp.setattr(teach, "_ref_questions_call", answer)
        out = teach.questions_from_refs(d, _read(d), "claude")
    qs = [s["check_question"] for s in _read(d)["steps"]]
    assert qs[0] == "Is there one square with a diagonal crease?" and qs[4] == "Are four flaps up?"
    assert qs[1] == original[1] and qs[3] == original[3] and qs[2] == ""  # color word / missing: old question kept
    # offline or the mock provider: no call at all
    for env, prov in ((dict(HANDOVER_NO_NETWORK="1"), "claude"), (dict(HANDOVER_NO_NETWORK=None), "mock")):
        with _env(**env), pytest.MonkeyPatch.context() as mp:
            mp.setattr(teach, "_ref_questions_call", boom)
            seen.clear()
            teach.questions_from_refs(d, _read(d), prov)
            assert seen == []


def test_questions_from_refs_claude_request():
    d = _demo_copy("ref-questions-claude")
    n_camera = sum(s["check_type"] != "manual" for s in _read(d)["steps"])
    answer = {"questions": [{"n": 2, "question": "Is the box at the right edge?"}]}
    spend = _FakeSpend()
    with _env(HANDOVER_NO_NETWORK=None, ANTHROPIC_API_KEY="sk-ant-fake"), _fake_claude(spend, answer=answer) as log:
        out = teach.questions_from_refs(d, _read(d), "claude")
    (req,) = log["requests"]  # one call for the whole lesson
    blocks = req["messages"][0]["content"]
    images = [b for b in blocks if b["type"] == "image"]
    assert len(images) == 2 * n_camera <= teach.CLAUDE_MAX_FRAMES
    assert blocks[0]["text"].startswith("Step 1: ") and blocks[0]["text"].endswith("BEFORE:")
    assert blocks[2]["text"] == "Step 1 DONE:" and "never mention" in blocks[-1]["text"].lower()
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert spend.calls[0] == "allow" and spend.calls[2][0] == "record"
    assert out["steps"][1]["check_question"] == "Is the box at the right edge?"


# ---------------------------------------------------------------- automatic self-test (HANDOVER_AUTO_SELFTEST)

def test_auto_self_test_makes_failing_steps_manual():
    import pytest

    d = _demo_copy("auto-selftest")
    calls = []

    async def fake_self_test(lesson_dir, progress=teach.noop):
        calls.append(lesson_dir)
        lesson = _read(lesson_dir)
        results = {2: {"own": "no", "prev": "no", "ok": False}, 4: {"own": "yes", "prev": "yes", "ok": False},
                   5: {"own": "yes", "prev": "no", "ok": True}}
        for s in lesson["steps"]:
            if s["n"] in results:
                s["self_test"] = results[s["n"]]
        progress("self-test", "step 2: own no 0.90, prev no 0.90  FAILED, suggest manual or a clearer question")
        return lesson, [1]

    env = dict(HANDOVER_NO_NETWORK=None, HANDOVER_CHECK=None, HANDOVER_CHECK_PROVIDER="claude",
               ANTHROPIC_API_KEY="sk-ant-fake", HANDOVER_AUTO_SELFTEST=None)
    lines = []
    with _env(**env), pytest.MonkeyPatch.context() as mp:
        mp.setattr(teach, "_self_test", fake_self_test)
        out = teach._auto_self_test(d, _read(d), lambda st, m: lines.append(m))
        assert len(calls) == 1
        by_n = {s["n"]: s for s in _read(d)["steps"]}
        assert by_n[2]["check_type"] == "manual" and by_n[2]["check_question"] == "" and by_n[2]["self_test"]["own"] == "no"
        assert by_n[4]["check_type"] == "camera" and by_n[5]["check_type"] == "camera"  # own passed: kept
        assert out == _read(d)
        assert any("step 2: own no" in m for m in lines) and any("Steps made manual" in m and "2" in m for m in lines)
        # off, offline, mock check: no self-test
        for extra in (dict(HANDOVER_AUTO_SELFTEST="0"), dict(HANDOVER_NO_NETWORK="1"), dict(HANDOVER_CHECK="mock")):
            with _env(**extra):
                teach._auto_self_test(d, _read(d))
        assert len(calls) == 1


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

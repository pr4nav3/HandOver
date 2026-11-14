"""Teach pipeline and server tests. Uses ffmpeg and a temp lessons folder; no network.

Run: .venv/bin/python -m server.test_server
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="handover-test-"))
os.environ["HANDOVER_LESSONS"] = str(TMP / "lessons")  # before importing server.main, which reads it once
os.environ["HANDOVER_TEACH_MOCK"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from server import main, teach  # noqa: E402

STEPS = {
    "steps": [
        {"start": "00:00", "end": "00:02", "title": "One", "check_question": "Is it red?", "prerequisites": []},
        {"start": "00:02", "end": "00:04", "title": "Two", "check_question": "manual", "prerequisites": [1]},
        {"start": "00:04", "end": "00:06", "title": "Three", "check_question": "Is it blue?", "prerequisites": [2]},
    ],
    "transcript": [{"start": 0.5, "end": 1.5, "text": "hello"}],
}


def _ffmpeg(*args: str) -> None:
    subprocess.run([teach._bin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _video(path: Path, seconds: int = 6, extra: tuple = ()) -> Path:
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=s=320x240:r=30:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", *extra, str(path))
    return path


def _probe(path: Path, field: str) -> str:
    out = subprocess.run([teach._bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries",
                          f"stream={field}", "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, encoding="utf-8")
    return out.stdout.strip()


_lesson_cache: dict = {}


def _lesson(lesson_id: str = "base") -> Path:
    """A built 3-step lesson (built once, copied per test)."""
    if "base" not in _lesson_cache:
        src = _video(TMP / "src.mp4")
        steps = TMP / "steps.json"
        steps.write_text(json.dumps(STEPS), encoding="utf-8")
        teach.build([src], "base", "Base", steps_json=steps)
        _lesson_cache["base"] = teach.lessons_root() / "base"
    if lesson_id == "base":
        return _lesson_cache["base"]
    dst = teach.lessons_root() / lesson_id
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(_lesson_cache["base"], dst)
    return dst


def _snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for sub in teach.SUBDIRS for p in sorted((d / sub).iterdir())}


# ---------------------------------------------------------------- timestamps (fix 2)

def test_fmt_mmss_keeps_tenths():
    assert teach.fmt_mmss(10.6) == "00:10.6" and teach.fmt_mmss(11.4) == "00:11.4"
    assert teach.fmt_mmss(22) == "00:22" and teach.fmt_mmss(61.0) == "01:01" and teach.fmt_mmss(-3) == "00:00"
    for v in (0.0, 10.6, 59.9, 75.3, 600.1):
        assert abs(teach.parse_time(teach.fmt_mmss(v)) - v) < 1e-9


def test_short_step_survives_cleaning():
    ex = teach.Extraction(steps=[
        teach.Step(start="00:00", end="00:10.6", title="a", check_question="q", prerequisites=[]),
        teach.Step(start="00:10.6", end="00:11.4", title="short", check_question="q", prerequisites=[1]),
        teach.Step(start="00:11.4", end="00:11.45", title="tiny", check_question="q", prerequisites=[2]),
    ], transcript=[])
    out = teach._clean_extraction(ex, 20.0)
    assert [(s.start, s.end) for s in out.steps] == [("00:00", "00:10.6"), ("00:10.6", "00:11.4")]


# ---------------------------------------------------------------- safe cut and recut (fix 1)

def test_recut_bad_timestamp_keeps_clips():
    d = _lesson("bad-ts")
    before, lesson_before = _snapshot(d), (d / "lesson.json").read_text(encoding="utf-8")
    lesson = json.loads(lesson_before)
    lesson["steps"][2]["start"] = "nonsense"
    (d / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
    try:
        teach.recut(d)
        raise AssertionError("recut should fail")
    except ValueError as e:
        assert "step 3" in str(e)
    assert _snapshot(d) == before
    assert not (d / ".recut_tmp").exists()


def test_cut_failure_midway_keeps_clips():
    d = _lesson("mid-fail")
    before = _snapshot(d)
    real, calls = teach._last_frame, []

    def flaky(clip, out):
        calls.append(clip)
        if len(calls) == 2:
            raise RuntimeError("simulated ffmpeg failure")
        real(clip, out)

    teach._last_frame = flaky
    try:
        teach.recut(d)
        raise AssertionError("recut should fail")
    except RuntimeError:
        pass
    finally:
        teach._last_frame = real
    assert _snapshot(d) == before
    assert not (d / ".recut_tmp").exists()


def test_recut_with_fractional_times():
    d = _lesson("frac")
    lesson = json.loads((d / "lesson.json").read_text(encoding="utf-8"))
    lesson["steps"][0]["end"] = lesson["steps"][1]["start"] = "00:01.5"
    (d / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
    out = teach.recut(d)
    assert (out["steps"][0]["end"], out["steps"][1]["start"]) == ("00:01.5", "00:01.5")
    assert abs(teach.probe_duration(d / "clips" / "01.mp4") - 1.5) < 0.15
    assert not (d / ".recut_tmp").exists() and not (d / ".recut_old").exists()


# ---------------------------------------------------------------- color (fix 8)

def test_normalize_tags_bt709():
    out = TMP / "sdr-norm.mp4"
    teach.normalize(_video(TMP / "sdr.mp4", 1), out)
    assert (_probe(out, "color_transfer"), _probe(out, "color_space"), _probe(out, "color_primaries")) == \
        ("bt709", "bt709", "bt709")


def test_normalize_hdr_input_converts_to_bt709():
    src = _video(TMP / "hdr.mp4", 1, ("-vf", "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
                                      "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"))
    assert teach.color_transfer(src) == "smpte2084"
    cmds, real = [], teach._run
    teach._run = lambda cmd: (cmds.append(cmd), real(cmd))
    try:
        teach.normalize(src, TMP / "hdr-norm.mp4")
    finally:
        teach._run = real
    vf = cmds[0][cmds[0].index("-vf") + 1]
    assert "in_color_matrix=bt2020:out_color_matrix=bt709" in vf
    assert _probe(TMP / "hdr-norm.mp4", "color_transfer") == "bt709"


# ---------------------------------------------------------------- engine (fixes 4, 6)

class FakeClient:
    def __init__(self):
        self.sent = []

    def push(self, msg, droppable=False):
        self.sent.append(msg)


def _ui(client, **msg):
    main.handle_ui_message(client, json.dumps(msg))


def test_stale_from_does_not_skip():
    _lesson()
    c = FakeClient()
    main.engine.ui = {c}
    main.engine.select("base")
    main.engine.go(1, "camera")  # camera advance while the user was on step 0
    _ui(c, type="next", reason="voice", **{"from": 0})  # stale: sent while showing step 0
    assert main.engine.step == 1
    _ui(c, type="back", **{"from": 0})
    assert main.engine.step == 1
    _ui(c, type="next", reason="button", **{"from": 1})
    assert main.engine.step == 2
    _ui(c, type="next")  # legacy form without from
    assert main.engine.done and main.engine.position() == 3
    _ui(c, type="back", **{"from": 2})  # done screen shows step total-1
    assert not main.engine.done and main.engine.step == 2
    main.engine.ui = set()


def test_status_does_not_flap_per_frame():
    """Many frames on a camera step with fast "no" answers: no "checking" status and no repeated states."""
    import asyncio

    _lesson()
    os.environ["HANDOVER_CHECK"], os.environ["HANDOVER_MOCK_PASS_SECONDS"] = "mock", "100"
    c = FakeClient()
    jpeg = (teach.lessons_root() / "base" / "frames" / "01.jpg").read_bytes()

    async def run():
        main.engine.select("base")  # step 0 is a camera step
        main.engine.ui = {c}
        main.engine.cameras = 1
        loop_task = asyncio.create_task(main.engine.check_loop())
        for _ in range(10):  # 2 frames a second for 5 s, mock check takes 0.6 s
            main.engine.on_frame(jpeg)
            await asyncio.sleep(0.5)
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        del os.environ["HANDOVER_CHECK"], os.environ["HANDOVER_MOCK_PASS_SECONDS"]
        main.engine.ui, main.engine.cameras = set(), 0
    states = [m for m in c.sent if isinstance(m, dict) and m.get("type") == "state"]
    assert all(m["status"] == "watching" for m in states), [m["status"] for m in states]
    assert len(states) == 1 and states[0]["last_check"]["done"] == "no", states  # first answer only


def test_state_has_rev():
    _lesson()
    main.engine.select("base")
    st = main.engine.state()
    expect = int((teach.lessons_root() / "base" / "lesson.json").stat().st_mtime_ns // 1_000_000)
    assert isinstance(st["rev"], int) and st["rev"] == expect


# ---------------------------------------------------------------- REST (fixes 1, 5, 6, 9)

client = TestClient(main.app)


def _wait_job(job: str) -> dict:
    for _ in range(300):
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def _uploads() -> set:
    return set(main.UPLOADS.iterdir()) if main.UPLOADS.exists() else set()


def test_recut_endpoint_bad_timestamp_and_rev():
    d = _lesson("api-recut")
    main.engine.select("api-recut")
    c = FakeClient()
    main.engine.ui = {c}
    before, rev0 = _snapshot(d), main.engine.rev
    original = (d / "lesson.json").read_text(encoding="utf-8")
    bad = json.loads(original)
    bad["steps"][1]["end"] = "zz:10"
    r = client.post("/api/lessons/api-recut/recut", json=bad)
    assert r.status_code == 400, r.text
    assert _snapshot(d) == before and (d / "lesson.json").read_text(encoding="utf-8") == original
    time.sleep(0.01)
    good = json.loads(original)
    good["steps"][0]["end"] = good["steps"][1]["start"] = "00:02.5"
    r = client.post("/api/lessons/api-recut/recut", json=good)
    assert r.status_code == 200, r.text
    states = [m for m in c.sent if isinstance(m, dict) and m.get("type") == "state"]
    assert states and states[-1]["rev"] != rev0 and states[-1]["rev"] == main.lesson_rev("api-recut")
    main.engine.ui = set()


def test_upload_sanitizes_id_and_cleans_up():
    before = _uploads()
    video = _video(TMP / "up.mp4", 3).read_bytes()
    r = client.post("/api/lesson", files={"file": ("up.mp4", video, "video/mp4")},
                    data={"title": "Up", "id": "My Lesson!"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "my-lesson"
    j = _wait_job(r.json()["job"])
    assert j["status"] == "done" and j["id"] == "my-lesson", j
    assert (teach.lessons_root() / "my-lesson" / "lesson.json").is_file()
    assert _uploads() == before  # upload file removed after the job

    r = client.post("/api/lesson", files={"file": ("up.mp4", video, "video/mp4")},
                    data={"title": "Up", "id": "MY_LESSON"})  # sanitizes to the same id
    assert r.status_code == 409, r.text


def test_failed_job_removes_partial_lesson():
    before = _uploads()
    r = client.post("/api/lesson", files={"file": ("junk.mov", b"not a video", "video/quicktime")},
                    data={"title": "Broken upload"})
    assert r.status_code == 200, r.text
    j = _wait_job(r.json()["job"])
    assert j["status"] == "error", j
    assert not (teach.lessons_root() / r.json()["id"]).exists()
    assert _uploads() == before


def test_upload_over_limit_is_413():
    before, limit = _uploads(), main.MAX_UPLOAD_BYTES
    main.MAX_UPLOAD_BYTES = 1000
    try:
        r = client.post("/api/lesson", files={"file": ("big.mp4", b"x" * 5000, "video/mp4")}, data={"title": "Big"})
    finally:
        main.MAX_UPLOAD_BYTES = limit
    assert r.status_code == 413, r.text
    assert _uploads() == before


def test_bin_missing_tool_message():
    try:
        teach._bin("definitely-not-a-real-tool")
        raise AssertionError("expected an error")
    except RuntimeError as e:
        assert "not found on PATH" in str(e)


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

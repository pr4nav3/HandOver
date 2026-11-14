"""Voiceover tests: the decision rule, script writer (fake Claude), speech fallbacks (fake engines), mixing,
captions, lesson.json field, undo and the CLI dry run.

Run: .venv/bin/python -m server.test_voice (or pytest if installed). Offline: Claude is a fake client, Kokoro
and `say` are fakes, and the spend ledger is a temp file. Mixing uses the local ffmpeg on copies of
lessons/demo-v1 in a temp folder; the committed lesson is never touched.
"""

import contextlib
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp(prefix="handover-voice-test-"))
os.environ["HANDOVER_CLAUDE_SPEND_FILE"] = str(TMP / "spend.json")
for _name in ("HANDOVER_VOICE", "HANDOVER_VOICE_SPEED", "HANDOVER_VOICEOVER", "HANDOVER_VOICE_SCRIPT_MODEL",
              "HANDOVER_CLAUDE_BUDGET_DAY_USD", "HANDOVER_CLAUDE_BUDGET_TOTAL_USD"):
    os.environ.pop(_name, None)

from server import spend, voice  # noqa: E402

voice._kokoro_failed = "blocked in tests"  # no test may download or load the real model
voice.KOKORO_DIR = TMP / "kokoro"
DEMO = voice.REPO / "lessons" / "demo-v1"


@contextlib.contextmanager
def env(**values):
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


@contextlib.contextmanager
def patched(obj, **attrs):
    saved = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(obj, k, v)


def demo_copy(name: str) -> Path:
    dst = TMP / name
    shutil.copytree(DEMO, dst)
    return dst


def steps_demo() -> list[dict]:
    return json.loads((DEMO / "lesson.json").read_text(encoding="utf-8"))["steps"]


def fake_synth(per_word: float = 0.35, fail: bool = False):
    """A stand-in for synthesize: a quiet tone whose length grows with the word count and shrinks with speed."""
    calls = []

    def synth(text, out, v=None, speed=None):
        calls.append((text, speed))
        if fail:
            return 0.0, "", ""
        seconds = max(0.3, len(text.split()) * per_word / float(speed or 1.0))
        n = int(seconds * voice.SAMPLE_RATE)
        frames = b"".join(int(8000 * math.sin(2 * math.pi * 220 * i / voice.SAMPLE_RATE)).to_bytes(2, "little", signed=True)
                          for i in range(n))
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(voice.SAMPLE_RATE)
            w.writeframes(frames)
        return n / voice.SAMPLE_RATE, "kokoro", v or "af_heart"

    synth.calls = calls
    return synth


class FakeClaude:
    """messages.create records its kwargs and returns a canned structured-output answer."""

    def __init__(self, answer, stop="end_turn"):
        self.kwargs = None
        self.answer = answer
        self.stop = stop
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=self.stop,
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=200,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))


def ffprobe(path: Path, *args: str) -> str:
    return subprocess.run([voice.ffmpeg_bin("ffprobe"), "-v", "error", *args, str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


def video_md5(path: Path) -> str:
    return subprocess.run([voice.ffmpeg_bin(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy",
                           "-f", "md5", "-"], capture_output=True, text=True, check=True).stdout.strip()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- decision

def test_needs_voiceover():
    steps = [{"start": "00:00", "end": "00:10"}, {"start": "00:10", "end": "00:20"}]
    assert voice.needs_voiceover([], steps)
    assert voice.needs_voiceover([{"start": 0, "end": 1, "text": "   "}], steps)
    # plenty of words but they cover 4 of 20 seconds
    short = [{"start": 0, "end": 2, "text": "one two three four five six"},
             {"start": 10, "end": 12, "text": "seven eight nine ten eleven twelve"}]
    assert voice.needs_voiceover(short, steps)
    # good coverage but only 2 words per step
    thin = [{"start": 0, "end": 9, "text": "fold here"}, {"start": 10, "end": 19, "text": "press down"}]
    assert voice.needs_voiceover(thin, steps)
    good = [{"start": "00:00", "end": "00:09", "text": "lay the sheet flat with the color down"},
            {"start": 10.5, "end": 19, "text": "now fold it neatly in half edge to edge"}]
    assert not voice.needs_voiceover(good, steps)
    # overlapping segments are not double counted
    overlap = [{"start": 0, "end": 3, "text": "a b c d e f"}, {"start": 0, "end": 3, "text": "g h i j k l"},
               {"start": 1, "end": 3, "text": "m n o p"}]
    assert voice.needs_voiceover(overlap, steps)
    # demo lesson: the expert talks over most of each step
    demo_tr = json.loads((DEMO / "extraction.json").read_text())["transcript"]
    assert not voice.needs_voiceover(demo_tr, steps_demo())


def test_should_voiceover_setting():
    steps = [{"start": 0, "end": 10}]
    good = [{"start": 0, "end": 9, "text": "lay the sheet flat with the color down please"}]
    with env(HANDOVER_VOICEOVER=None):
        assert voice.voiceover_setting() == "auto"
        assert voice.should_voiceover([], steps) and not voice.should_voiceover(good, steps)
    with env(HANDOVER_VOICEOVER="always"):
        assert voice.should_voiceover(good, steps)
    with env(HANDOVER_VOICEOVER="OFF"):
        assert not voice.should_voiceover([], steps)
    with env(HANDOVER_VOICEOVER="sometimes"):  # bad value: warns, uses auto
        assert voice.voiceover_setting() == "auto"


def test_settings_defaults_and_bounds():
    with env(HANDOVER_VOICE=None, HANDOVER_VOICE_SPEED=None, HANDOVER_VOICE_SCRIPT_MODEL=None):
        assert voice.default_voice() == "af_heart"
        assert voice.default_speed() == 1.0
        assert voice.script_model() == "claude-haiku-5-5"
    with env(HANDOVER_VOICE="af_bella", HANDOVER_VOICE_SPEED="1.1"):
        assert voice.default_voice() == "af_bella" and voice.default_speed() == 1.1
    with env(HANDOVER_VOICE_SPEED="3"):
        assert voice.default_speed() == 1.0


# ---------------------------------------------------------------- text

def test_clean_sentence_and_split():
    assert voice.clean_sentence("In this step, fold the sheet \u2014 carefully") == "Fold the sheet, carefully."
    assert voice.clean_sentence("now press  it down\u2013firmly!") == "Press it down, firmly!"
    assert voice.clean_sentence("keep it flat - like this") == "Keep it flat, like this."
    assert voice.clean_sentence("a well-made fold") == "A well-made fold."  # hyphenated words stay
    assert voice.split_sentences("Fold it. Press down! Is it flat?") == ["Fold it.", "Press down!", "Is it flat?"]
    assert voice.split_sentences("   ") == []
    for s in voice.split_sentences("Okay, so \u2014 fold. Here, press \u2013 hard."):
        assert "\u2014" not in s and "\u2013" not in s


def test_word_budget_and_fit():
    assert voice.word_budget(8.0) == 18
    assert voice.word_budget(1.0) == 4
    long = ["One two three four five six.", "Seven eight nine ten eleven twelve.", "More words here now."]
    assert voice._fit_words(long, 12) == long[:2]
    assert voice._fit_words(long, 3) == long[:1]  # the first sentence always stays
    assert len(voice._fit_words(long + ["x."], 100)) == 3


# ---------------------------------------------------------------- script writer

def _frames() -> list[list[Path]]:
    return [[DEMO / "frames" / f"{i:02d}.jpg", DEMO / "frames" / f"{i:02d}.jpg", DEMO / "frames" / "01.jpg"]
            for i in range(1, 6)]


def test_write_script_request_and_parse():
    answer = {"steps": [
        {"n": 1, "sentences": ["In this step, lay the blue sheet flat \u2014 color side down.", "Smooth it out."]},
        {"n": 2, "sentences": ["Fold it in half so the edges meet."]},
        {"n": 3, "sentences": ["Crease the fold hard, then open it again."]},
        {"n": 4, "sentences": ["Bring each corner to the center.", "Keep the points sharp.",
                               "Line them up with the crease.", "This sentence is one too many."]},
        # step 5 missing: falls back to its title
    ]}
    fake = FakeClaude(answer)
    steps = steps_demo()
    steps[3]["common_mistake"] = "Do not let the corners overlap."
    before = spend.status().total_calls
    with env(HANDOVER_VOICE_SCRIPT_MODEL=None):
        scripts = voice.write_script(steps, [], _frames(), client=fake)
    kw = fake.kwargs
    assert kw["model"] == "claude-haiku-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"] == voice.SCHEMA
    content = kw["messages"][0]["content"]
    images = [c for c in content if c["type"] == "image"]
    assert len(images) == 10, len(images)  # at most 2 per step
    import base64
    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(images[0]["source"]["data"])))
    assert max(img.size) == 512 and img.format == "JPEG"
    texts = "\n".join(c["text"] for c in content if c["type"] == "text")
    assert "Common mistake: Do not let the corners overlap." in texts
    assert "at most 18 words" in texts and "Done when: Is there one white bar" in texts
    assert "Done when: manual" not in texts and "expert's own words" not in texts  # no transcript sent
    assert spend.status().total_calls == before + 1 and voice.last_cost_usd > 0

    assert [s.n for s in scripts] == [1, 2, 3, 4, 5]
    assert scripts[0].sentences == ["Lay the blue sheet flat, color side down.", "Smooth it out."]
    assert len(scripts[3].sentences) == 3 and voice._words(scripts[3].narration) <= 18
    assert scripts[4].sentences == ["Open the finished shape."]
    assert all(s.seconds == 8.0 for s in scripts)
    for s in scripts:
        assert "\u2014" not in s.narration and "\u2013" not in s.narration


def test_write_script_sends_transcript_and_clip_lengths():
    fake = FakeClaude({"steps": [{"n": 1, "sentences": ["Lay it flat."]}]})
    tr = [{"start": "00:01", "end": "00:03", "text": "uh lay it  flat"}]
    voice.write_script([{"n": 1, "title": "Lay flat", "start": "00:00", "end": "00:08"}], tr, None,
                       clip_seconds=[4.0], client=fake)
    texts = "\n".join(c["text"] for c in fake.kwargs["messages"][0]["content"] if c["type"] == "text")
    assert "[1.0s to 3.0s] uh lay it flat" in texts
    assert "Clip length: 4.0 seconds, so at most 8 words" in texts


def test_write_script_budget_refusal():
    fake = FakeClaude({"steps": []})
    with env(HANDOVER_CLAUDE_BUDGET_DAY_USD="0"):
        try:
            voice.write_script(steps_demo(), [], None, client=fake)
            raise AssertionError("expected BudgetExceeded")
        except voice.BudgetExceeded as e:
            assert "budget" in str(e)
    assert fake.kwargs is None  # no call was made


def test_write_script_bad_answers():
    for fake in (FakeClaude("not json"), FakeClaude({"steps": []}, stop="refusal"),
                 FakeClaude({"nope": 1})):
        try:
            voice.write_script(steps_demo(), [], None, client=fake)
            raise AssertionError("expected VoiceError")
        except voice.VoiceError:
            pass


def test_write_script_without_key_never_leaks():
    with patched(voice, _anthropic_key=lambda: None):
        try:
            voice.write_script(steps_demo(), [], None)
            raise AssertionError("expected VoiceError")
        except voice.VoiceError as e:
            assert "ANTHROPIC_API_KEY" in str(e)


def test_fallback_scripts():
    steps = steps_demo()
    steps[0]["common_mistake"] = "keep the color side down"
    got = voice.fallback_scripts(steps)
    assert got[0].sentences == ["Lay the blue sheet flat.", "Keep the color side down."]
    assert got[1].sentences == ["Fold the sheet in half."]


# ---------------------------------------------------------------- speech

class FakeKokoro:
    def __init__(self):
        self.voice = None

    def get_voices(self):
        return ["af_heart", "af_bella"]

    def create(self, text, voice, speed, lang):
        import numpy as np
        self.voice = voice
        return np.full(int(24000 * 0.5 / speed), 0.1, dtype=np.float32), 24000


def test_speak_kokoro_path_and_unknown_voice():
    fk = FakeKokoro()
    with patched(voice, _kokoro=fk, _kokoro_failed=None):
        out = TMP / "k.wav"
        assert abs(voice.speak("Fold it in half.", out, "af_bella") - 0.5) < 0.01
        assert fk.voice == "af_bella" and voice.wav_seconds(out) > 0.49
        seconds, engine, used = voice.synthesize("Fold it.", out, "zz_nobody")
        assert engine == "kokoro" and used == "af_heart" and fk.voice == "af_heart"


def test_speak_falls_back_to_say_then_zero():
    def say_ok(text, out, speed):
        return 1.25, "Samantha"

    def boom(*a, **k):
        raise RuntimeError("no engine")

    with patched(voice, _speak_say=say_ok):
        assert voice.synthesize("Fold it.", TMP / "s.wav") == (1.25, "say", "Samantha")
    with patched(voice, _speak_say=boom):
        assert voice.speak("Fold it.", TMP / "z.wav") == 0.0
    assert voice.speak("", TMP / "e.wav") == 0.0


def test_best_say_voice_prefers_premium():
    listing = ("Albert              en_US    # Hello!\nSamantha            en_US    # Hello!\n"
               "Zoe (Premium)       en_US    # Hello!\nDaniel              en_GB    # Hello!\n")
    real = subprocess.run
    with patched(subprocess, run=lambda *a, **k: SimpleNamespace(stdout=listing)):
        assert voice.best_say_voice() == "Zoe (Premium)"
    with patched(subprocess, run=lambda *a, **k: SimpleNamespace(stdout=listing.replace("Zoe (Premium)", "Zed"))):
        assert voice.best_say_voice() == "Samantha"
    assert subprocess.run is real


def test_kokoro_files_are_pinned():
    model, voices = voice.KOKORO_FILES[voice.KOKORO_MODEL], voice.KOKORO_FILES[voice.KOKORO_VOICES]
    assert model[0] > 300_000_000 and voices[0] > 20_000_000
    assert all(len(d) == 64 for _, d in voice.KOKORO_FILES.values())


# ---------------------------------------------------------------- narration and mixing

def test_narrate_fits_and_times_cues():
    synth = fake_synth(per_word=0.3)
    work = TMP / "nar1"
    work.mkdir()
    nar = voice.narrate(["Fold it in half.", "Press the edge down."], 8.0, work, synth=synth)
    assert abs(voice.wav_seconds(nar.wav) - 8.0) < 0.001
    (a1, b1, t1), (a2, b2, t2) = nar.cues
    assert a1 == voice.LEAD_S and abs((b1 - a1) - 1.2) < 0.01
    assert abs(a2 - (b1 + voice.GAP_S)) < 0.001 and b2 <= 8.0 - voice.TAIL_S
    assert {s for _, s in synth.calls} == {1.0}  # fits at normal speed


def test_narrate_speeds_up_then_drops_sentences():
    synth = fake_synth(per_word=0.5)
    work = TMP / "nar2"
    work.mkdir()
    # 6 words = 3.0 s at 1.0, too long for 3 s of room; 2.73 s at 1.1 fits
    nar = voice.narrate(["One two three.", "Four five six."], 3.7, work, synth=synth)
    assert len(nar.cues) == 2 and max(s for _, s in synth.calls) == 1.1
    synth = fake_synth(per_word=0.5)
    work = TMP / "nar3"
    work.mkdir()
    nar = voice.narrate(["One two three four.", "Five six seven eight."], 3.0, work, synth=synth)
    assert len(nar.cues) == 1 and max(s for _, s in synth.calls) == 1.2
    work = TMP / "nar4"
    work.mkdir()
    assert voice.narrate(["Fold."], 3.0, work, synth=fake_synth(fail=True)) is None


def _scripts(lesson: Path) -> list:
    return [voice.StepScript(1, "Lay the blue sheet flat", 8.0, ["Lay the sheet flat.", "Color side down."]),
            voice.StepScript(2, "Fold the sheet in half", 8.0, ["Fold it in half, edge to edge."])]


def test_apply_voiceover_duck_and_undo():
    lesson = demo_copy("duck")
    clip, orig = lesson / "clips" / "01.mp4", lesson / "clips" / "01.orig.mp4"
    before_clip, before_vtt = sha(clip), (lesson / "captions" / "01.vtt").read_text()
    before_json = (lesson / "lesson.json").read_text()
    vmd5 = video_md5(clip)

    result = voice.apply_voiceover(lesson, _scripts(lesson), "duck", synth=fake_synth())
    assert result["voiced"] == [1, 2] and result["skipped"] == []
    assert result["voiceover"]["engine"] == "kokoro" and result["voiceover"]["voice"] == "af_heart"
    assert sha(orig) == before_clip and sha(clip) != before_clip
    assert video_md5(clip) == vmd5  # the video stream is copied bit for bit
    assert ffprobe(clip, "-select_streams", "a", "-show_entries", "stream=codec_name,sample_rate", "-of",
                   "csv=p=0") == "aac,48000"
    assert abs(float(ffprobe(clip, "-show_entries", "format=duration", "-of", "csv=p=0")) - 8.0) < 0.1
    data = clip.read_bytes()
    assert 0 < data.find(b"moov") < data.find(b"mdat")  # faststart: the index comes before the media

    vtt = (lesson / "captions" / "01.vtt").read_text()
    assert vtt.startswith("WEBVTT") and "Lay the sheet flat." in vtt and "Color side down." in vtt
    assert "00:00:00.400 --> " in vtt
    assert (lesson / "captions" / "01.orig.vtt").read_text() == before_vtt
    lj = json.loads((lesson / "lesson.json").read_text())
    assert lj["voiceover"]["mode"] == "duck" and lj["voiceover"]["model"] == "kokoro-v1.0"
    assert lj["steps"] == json.loads(before_json)["steps"]  # nothing else changed

    # running again starts from the original: the backup is untouched and voices do not stack
    voice.apply_voiceover(lesson, _scripts(lesson), "duck", synth=fake_synth())
    assert sha(orig) == before_clip and video_md5(clip) == vmd5

    assert voice.undo(lesson) == 2
    assert sha(clip) == before_clip and not orig.exists()
    assert (lesson / "captions" / "01.vtt").read_text() == before_vtt
    assert not (lesson / "captions" / "01.orig.vtt").exists()
    assert "voiceover" not in json.loads((lesson / "lesson.json").read_text())
    assert voice.undo(lesson) == 0  # a second undo is a no-op


def test_apply_voiceover_replace_and_silent_clip():
    lesson = demo_copy("replace")
    clip = lesson / "clips" / "02.mp4"
    silent = lesson / "clips" / "02.silent.mp4"
    subprocess.run([voice.ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip), "-an", "-c:v", "copy", str(silent)],
                   check=True)
    os.replace(silent, clip)
    result = voice.apply_voiceover(lesson, _scripts(lesson), "replace", synth=fake_synth())
    assert result["voiced"] == [1, 2]
    assert "audio" in ffprobe(clip, "-show_entries", "stream=codec_type", "-of", "csv=p=0")


def test_apply_voiceover_failure_keeps_clip():
    lesson = demo_copy("fail")
    clip = lesson / "clips" / "01.mp4"
    before = sha(clip)
    result = voice.apply_voiceover(lesson, _scripts(lesson), "duck", synth=fake_synth(fail=True))
    assert result == {"voiced": [], "skipped": [1, 2], "voiceover": None}
    assert sha(clip) == before and not (lesson / "clips" / "01.orig.mp4").exists()
    assert "voiceover" not in json.loads((lesson / "lesson.json").read_text())
    assert not list((lesson / "clips").glob("*.tmp.mp4"))


def test_duck_level_is_about_minus_18_db():
    """The background under the voice is the original turned down by about 18 dB."""
    lesson = demo_copy("level")
    clip = lesson / "clips" / "01.mp4"

    def mean_db(path: Path, start: float, length: float) -> float:
        err = subprocess.run([voice.ffmpeg_bin(), "-v", "info", "-ss", str(start), "-t", str(length), "-i", str(path),
                              "-map", "0:a", "-af", "volumedetect", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        return float(err.split("mean_volume:")[1].split("dB")[0])

    orig_db = mean_db(clip, 7.5, 0.45)  # the tail: no voice there, only the ducked original
    voice.apply_voiceover(lesson, _scripts(lesson)[:1], "duck", synth=fake_synth())
    ducked_db = mean_db(clip, 7.5, 0.45)
    assert -21 < ducked_db - orig_db < -15, (orig_db, ducked_db)


# ---------------------------------------------------------------- CLI

def test_cli_dry_run_without_key_uses_titles():
    lesson = demo_copy("cli")
    before = sha(lesson / "clips" / "01.mp4")
    out = io.StringIO()
    with patched(voice, _anthropic_key=lambda: None), contextlib.redirect_stdout(out):
        code = voice.main([str(lesson), "--dry-run"])
    text = out.getvalue()
    assert code == 0, text
    assert "using the step titles instead" in text and "Lay the blue sheet flat." in text
    assert "voiceover" not in json.loads((lesson / "lesson.json").read_text())
    assert sha(lesson / "clips" / "01.mp4") == before


def test_cli_undo_and_missing_lesson():
    lesson = demo_copy("cli-undo")
    voice.apply_voiceover(lesson, _scripts(lesson), "duck", synth=fake_synth())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert voice.main([str(lesson), "--undo"]) == 0
    assert "restored 2" in out.getvalue()
    with contextlib.redirect_stderr(io.StringIO()):
        assert voice.main([str(TMP / "nope")]) == 2


def test_no_dashes_in_source():
    src = Path(voice.__file__).read_text(encoding="utf-8")
    assert "\u2014" not in src and "\u2013" not in src


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

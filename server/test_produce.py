"""Course production tests: overlay images, filter graph strings, styles, captions, action regions (fake Claude),
and a real two-step render of a copy of lessons/demo-v1 checked with ffprobe.

Run: .venv/bin/python -m server.test_produce (or pytest if installed). Offline: HANDOVER_NO_NETWORK=1, Claude is a
fake client and the spend ledger is a temp file. Renders happen in a temp folder; the committed lesson is never
touched.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp(prefix="handover-produce-test-"))
os.environ["HANDOVER_CLAUDE_SPEND_FILE"] = str(TMP / "spend.json")
os.environ["HANDOVER_NO_NETWORK"] = "1"
for _name in ("HANDOVER_PRODUCE_MODEL", "HANDOVER_PRODUCE_JOBS", "HANDOVER_PRODUCE_FONT",
              "HANDOVER_CLAUDE_BUDGET_DAY_USD", "HANDOVER_CLAUDE_BUDGET_TOTAL_USD"):
    os.environ.pop(_name, None)

from PIL import Image  # noqa: E402

from server import produce as P  # noqa: E402

DEMO = P.REPO / "lessons" / "demo-v1"
L1080 = P.Layout(1920, 1080)


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


def demo_copy(name: str, steps: int = 0) -> Path:
    dst = TMP / name
    shutil.copytree(DEMO, dst)
    if steps:
        lesson = json.loads((dst / "lesson.json").read_text())
        lesson["steps"] = lesson["steps"][:steps]
        (dst / "lesson.json").write_text(json.dumps(lesson, indent=2))
    return dst


def ffprobe(path: Path) -> dict:
    out = subprocess.run([P.ffprobe(), "-v", "error", "-show_entries",
                          "stream=codec_type,pix_fmt,color_range,width,height:format=duration", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def plan(**kw) -> P.StepPlan:
    base = dict(n=2, total=5, title="Fold the corners in", clip=Path("/x/clips/02.mp4"), vtt=Path("/x/02.vtt"),
                first_frame=Path("/x/first.jpg"), probe=P.Probe(1920, 1080, 30.0, 8.0, True),
                region=(0.4, 0.3, 0.6, 0.6), key_time=5.0, frac0=0.2, frac1=0.4, style=P.normalize_style({}))
    base.update(kw)
    return P.StepPlan(**base)


def assets_for(p: P.StepPlan) -> dict:
    a = {"title": (Path("/w/title.png"), (900, 200)), "card": Path("/w/card.png"), "label": (Path("/w/l.png"),
         (500, 120)), "track": Path("/w/track.png"), "fill": Path("/w/fill.png"), "captions": [],
         "loudness": None}
    if P.ring_window(p):
        a["ring"] = (Path("/w/ring/%03d.png"), (700, 280))
    if p.style["title_cards"] == "overlay":
        a["veil"] = Path("/w/veil.png")
    return a


# ---------------------------------------------------------------- styles and themes

def test_style_defaults_and_cleaning():
    s = P.normalize_style(None)
    assert s == P.STYLE_DEFAULTS and s["theme"] == "system" and s["burn_captions"] is False
    s = P.normalize_style({"theme": "dark", "title_cards": False, "zoom": "yes", "accent": "#ff0000", "x": 1})
    assert s["theme"] == "system" and s["title_cards"] == "off" and s["zoom"] is True
    assert s["accent"] == "#FF0000" and "x" not in s
    assert P.normalize_style({"theme": "nope", "accent": "red"})["accent"] is None
    assert P.normalize_style({"theme": "light"})["theme"] == "system-light"
    assert P.normalize_style({"title_cards": "overlay"})["title_cards"] == "overlay"


def test_themes_follow_design_doc():
    assert len(P._LOOKS) == 14
    dark = P.card_theme(P.normalize_style({}))
    assert dark.bg == (0x13, 0x14, 0x16) and dark.accent == (0x8A, 0xA8, 0xFF) and not dark.light
    light = P.card_theme(P.normalize_style({"theme": "ivory-light"}))
    assert light.light and light.bg == (0xF4, 0xF1, 0xEA)
    # over video the dark look is used even when cards are light; always light themes stay light
    assert not P.overlay_theme(P.normalize_style({"theme": "ivory-light"})).light
    assert P.overlay_theme(P.normalize_style({"theme": "newsprint"})).light
    assert P.card_theme(P.normalize_style({"accent": "#112233"})).accent == (0x11, 0x22, 0x33)
    assert P.CAPTION_FILL == (0, 0, 0, 184)  # captionFill: black at 72%


# ---------------------------------------------------------------- overlay images

def test_ring_frames_sizes_and_fade():
    frames = P.ring_frames(300, 200, L1080, (138, 168, 255), 30.0)
    pad = P.ring_pad(L1080)
    assert len(frames) == 60
    assert all(f.size == (300 + 2 * pad, 200 + 2 * pad) and f.mode == "RGBA" for f in frames)
    alpha = [f.getchannel("A").getextrema()[1] for f in frames]
    assert alpha[0] < alpha[30] and alpha[-1] < alpha[30] and alpha[30] > 200
    assert frames[30].getpixel((frames[30].width // 2, frames[30].height // 2))[3] == 0  # hollow center


def test_tracks_follow_keyframes_and_graph_takes_several():
    keys = [(2.0, (0.2, 0.2, 0.4, 0.4)), (4.0, (0.6, 0.2, 0.8, 0.4))]
    assert P.track_box(keys, 1.0) == (0.2, 0.2, 0.4, 0.4)
    assert [round(v, 6) for v in P.track_box(keys, 3.0)] == [0.4, 0.2, 0.6, 0.4]
    assert P.track_box(keys, 9.0) == (0.6, 0.2, 0.8, 0.4)
    path = P.track_path(keys, 2.0, 4.0, 30.0)
    assert len(path) == 60 and path[0][0] < path[30][0] < path[-1][0]
    frames, (x, y) = P.track_frames(keys, 2.0, 4.0, L1080, (138, 168, 255), 30.0)
    assert len(frames) == 60 and x < 0.25 * 1920 and y < 0.2 * 1080 and len({f.size for f in frames}) == 1
    p = plan(tracks=[keys, [(6.0, (0.3, 0.3, 0.5, 0.6))]])
    assert P.ring_window(p) is None
    hl = P.highlight_tracks(p)
    assert [(a, b) for a, b, _ in hl] == [(2.0, 4.0), (6.0, 7.9)]  # a single keyframe holds for RING_S, inside the clip
    assert P.highlight_tracks(plan(tracks=[[(1.0, (0.0, 0.0, 1.0, 1.0))]])) == []
    assert P.highlight_tracks(plan(highlight=False)) == []
    one = P.highlight_tracks(plan())
    assert len(one) == 1 and one[0][:2] == (4.6, 6.6)
    a = assets_for(p)
    a["rings"] = [(Path("/w/ring0/%04d.png"), (300, 200), 2.0), (Path("/w/ring1/%04d.png"), (500, 300), 6.0)]
    text = P.step_graph(p, a).text()
    assert "setpts=PTS-STARTPTS+2.000/TB" in text and "setpts=PTS-STARTPTS+6.000/TB" in text
    assert text.count("overlay=x=300:y=200") == 1 and text.count("overlay=x=500:y=300") == 1
    o = {"track": [[1, 0.1, 0.1, 0.3, 0.3], [0.5, 0.2, 0.2, 0.4, 0.4]], "tracks": [[{"t": 2, "region": [0.5, 0.5, 0.7, 0.7]}], "bad"]}
    tr = P.step_tracks(o, 1920, 1080)
    assert [k[0] for k in tr[0].keys] == [0.5, 1.0] and tr[1].keys == [(2.0, (0.5, 0.5, 0.7, 0.7))]
    assert P.tracks_union(tr) == (0.1, 0.1, 0.7, 0.7)
    warn = P.step_tracks({"tracks": [{"keys": [[3, 0.1, 0.1, 0.4, 0.4]], "color": "#d12a2a", "label": " Be  careful "}]}, 1920, 1080)
    assert warn[0].color == (209, 42, 42) and warn[0].label == "Be careful"
    assert P.tracks_union(warn) is None  # a warning does not steer the push-in
    z, x, y = P.zoom_state((0.4, 0.3, 0.6, 0.6), 8.0, 8.0)
    assert abs(z - P.MAX_ZOOM) < 1e-6 and 0 <= x <= 1 - 1 / z and 0 <= y <= 1 - 1 / z
    assert P.zoom_state((0.4, 0.3, 0.6, 0.6), 8.0, 0.0) == (1.0, 0.0, 0.0) and P.zoom_state(None, 0.5, 0.2) == (1.0, 0.0, 0.0)
    assert P.zoomed_box((0.1, 0.1, 0.2, 0.2), (2.0, 0.1, 0.1)) == (0.0, 0.0, 0.2, 0.2)
    frames, (x, y) = P.track_frames(warn[0].keys, 3.0, 5.0, L1080, warn[0].color, 30.0, warn[0].label)
    assert len(frames) == 60 and y < 0.1 * 1080 - 40  # room above the box for the tag
    assert frames[30].getpixel((frames[30].width // 2, frames[30].height // 2))[3] == 0
    fz, (xz, yz) = P.track_frames(warn[0].keys, 3.0, 5.0, L1080, warn[0].color, 30.0, "", lambda t: (2.0, 0.0, 0.0))
    assert fz[0].width > frames[0].width  # the box is twice as big in the zoomed picture


def test_speedups_retime_clock_and_filter():
    sp = P._clean_speedups([[6, 46, 8], [50, 52, 2], [45, 47, 3], "x", [1, 1.1, 4], [60, 70, 100]])
    assert sp == [(6.0, 46.0, 8.0), (50.0, 52.0, 2.0)]
    assert P.retimed(3.0, sp) == 3.0 and abs(P.retimed(46.0, sp) - 11.0) < 1e-9 and abs(P.retimed(47.3, sp) - 12.3) < 1e-9
    assert abs(P.retimed(54.0, sp) - (54 - 35 - 1)) < 1e-9
    assert P.fast_windows(sp)[0] == (6.0, 11.0, 8.0)
    text = P.retime_filter(54.0, sp)
    assert text.count("trim=") == 5 and "setpts=(PTS-STARTPTS)/8" in text and "concat=n=5:v=1:a=0" in text
    assert text.endswith("[v]")
    img = P.fast_badge(8, L1080, P.overlay_theme(P.normalize_style({})))
    assert img.mode == "RGBA" and img.width > img.height > 30
    p = plan(fast=[(6.0, 11.0, 8.0)], style=P.normalize_style({"step_label": False}))
    assert P.label_window(p) is None
    a = assets_for(p)
    a["fast"] = [(Path("/w/fast0.png"), (200, 60), 6.0, 11.0)]
    g = P.step_graph(p, a).text()
    assert "fast0.png" in " ".join(" ".join(a) for a in P.step_graph(p, a).inputs) and "setpts=PTS-STARTPTS+6.000/TB" in g and "overlay=x='1664':y='56'" in g



def test_lower_third_caption_progress_sizes():
    th = P.overlay_theme(P.normalize_style({}))
    lt = P.lower_third(3, 8, "Fold all four corners to the center", L1080, th)
    assert lt.mode == "RGBA" and lt.width <= 1920 * 0.5 and 100 < lt.height < 200
    long = P.lower_third(3, 8, "A very long title " * 8, L1080, th)
    assert long.width <= 1920 * 0.5 + 1 and long.height < 230  # wrapped to two lines, not more
    cap = P.caption_image(["Bring every corner", "to the exact center."], L1080)
    assert cap.getpixel((cap.width // 2, 3))[3] == 184
    track, fill = P.progress_images(L1080, th)
    assert track.size == fill.size == (1920, P.progress_height(L1080)) == (1920, 4)
    small = P.Layout(1280, 720)
    assert P.progress_images(small, th)[0].size == (1280, 3)


def test_cards_and_outro_render():
    frame = DEMO / "frames" / "01.jpg"
    th = P.card_theme(P.normalize_style({}))
    bg = P.blurred_backdrop(frame, L1080, th)
    assert bg.size == (1920, 1080) and bg.mode == "RGB"
    card, title_y = P.title_card(frame, (900, 200), L1080, th)
    assert card.size == (1920, 1080) and card.mode == "RGB"
    assert card.getpixel((5, 5)) == th.bg  # solid paper, no blur or glow
    thumb_h = round(384 * 1080 / 1920)
    assert title_y == (1080 - (thumb_h + 36 + 200)) // 2 + thumb_h + 36
    block = P.title_block("Step 2", "Fold corner to corner into triangle", L1080, th)
    assert block.width <= 1920 * 0.74 + 10
    outro = P.outro_block([f"Step title number {i}" for i in range(14)], L1080, th)
    assert outro.width < 1920 and outro.height < 1080
    cover = P.cover_image(frame, "Fold a fortune teller", "8 steps", L1080, th)
    assert cover.size == (1920, 1080)
    portrait = P.cover_image(frame, "Fold a fortune teller", "8 steps", P.Layout(1080, 1920), th)
    assert portrait.size == (1080, 1920)


def test_wrap_and_balance():
    f = P.font(80, "bold")
    lines = P.wrap("Fold a fortune teller (synthetic renders)", f, 1400)
    assert len(lines) == 2
    balanced = P.balance(lines, f, 1400)
    assert " ".join(balanced) == " ".join(lines)
    assert max(P.text_width(x, f) for x in balanced) <= max(P.text_width(x, f) for x in lines)
    assert balanced[1] != "renders)"
    cut = P.wrap("word " * 80, f, 600, 2)
    assert len(cut) == 2 and cut[-1].endswith("…")


# ---------------------------------------------------------------- captions

def test_vtt_read_write_and_chunks():
    path = TMP / "c.vtt"
    path.write_text("WEBVTT\n\nNOTE x\n\n1\n00:00:00.500 --> 00:00:03.000 align:center\n<b>Hello</b> there\n\n"
                    "00:00:04.000 --> 00:00:07.000\n" + "long words here " * 20 + "\n")
    cues = P.read_vtt(path)
    assert [c.text for c in cues][0] == "Hello there" and cues[0].start == 0.5 and len(cues) == 2
    chunks = P.caption_chunks(cues, L1080)
    assert all(len(lines) <= 2 for _, _, lines in chunks) and len(chunks) > 2
    assert abs(chunks[-1][1] - 7.0) < 1e-6 and abs(chunks[1][0] - 4.0) < 1e-6
    P.write_vtt(TMP / "o.vtt", cues)
    assert P.read_vtt(TMP / "o.vtt")[0].text == "Hello there"
    assert P.read_vtt(TMP / "missing.vtt") == []


# ---------------------------------------------------------------- graph strings

def test_zoom_filters():
    zf = P.zoom_filters((0.4, 0.3, 0.6, 0.6), 1920, 1080, 8.0, 30)
    assert zf.startswith("scale=3840:2160:flags=bicubic,zoompan=z='1+0.3000*(")
    assert "s=1920x1080:fps=30" in zf and "d=1" in zf and "it/6.800" in zf
    assert P.zoom_filters((0.0, 0.0, 1.0, 1.0), 1920, 1080, 8.0) == ""   # whole frame: no push-in
    assert P.zoom_filters(None, 1920, 1080, 0.5) == ""                     # too short
    center = P.zoom_filters(None, 1920, 1080, 8.0)
    assert "z='1+0.0800*(" in center
    assert P.zoom_filters(None, 3840, 2160, 8.0).startswith("scale=3840:2160")  # never pre-scaled past 4K
    # a region near the edge: the end window stays inside the frame and keeps the region plus margin
    z = P.end_zoom((0.0, 0.0, 0.3, 0.3))
    assert abs(z - 1.3) < 1e-9


def test_step_graph_card_mode():
    p = plan()
    g = P.step_graph(p, assets_for(p))
    text = g.text()
    assert "xfade=transition=fade:duration=0.300:offset=0.900" in text
    assert "zoompan=" in text and "[vout]" in text and "[aout]" in text
    assert "adelay=delays=900:all=1" in text and "loudnorm" not in text  # silent or unmeasured: no loudnorm
    assert "fade=t=in:st=0:d=0.350:alpha=1" in text
    assert "setpts=PTS-STARTPTS+4.600/TB" in text  # ring 0.4 s before key_time 5.0
    assert text.endswith("[vout];[0:a]" + P.audio_chain(None, 0.9) + "[aout]")
    assert p.seconds == 8.9
    inputs = [" ".join(a) for a in g.inputs]
    assert inputs[0] == "-i /x/clips/02.mp4" and any("%03d.png" in a for a in inputs)
    assert "\u2014" not in text and "\u2013" not in text


def test_step_graph_overlay_and_off_modes():
    p = plan(style=P.normalize_style({"title_cards": "overlay"}), zoom=False, highlight=False)
    text = P.step_graph(p, assets_for(p)).text()
    assert "xfade" not in text and "zoompan" not in text and "%03d" not in text
    assert P.label_window(p) is None and p.lead == 0 and p.seconds == 8.0
    p = plan(style=P.normalize_style({"title_cards": "off"}), probe=P.Probe(1920, 1080, 30.0, 8.0, False))
    text = P.step_graph(p, assets_for(p)).text()
    assert "xfade" not in text and "anullsrc=r=48000:cl=stereo[aout]" in text
    assert P.label_window(p) == (0.0, 2.5)


def test_audio_chain_two_pass():
    m = {"input_i": -27.1, "input_tp": -9.0, "input_lra": 3.0, "input_thresh": -37.5, "target_offset": 0.4}
    chain = P.audio_chain(m, 0.0)
    assert "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-27.10" in chain and "linear=true" in chain
    assert "adelay" not in chain and chain.endswith(",apad")


def test_ring_window_rules():
    assert P.ring_window(plan()) == (4.6, 6.6)
    assert P.ring_window(plan(key_time=0.1)) == (0.3, 2.3)
    assert P.ring_window(plan(key_time=7.9)) == (5.9, 7.9)
    assert P.ring_window(plan(region=None)) is None                    # nothing honest to point at
    assert P.ring_window(plan(region=(0.1, 0.1, 0.9, 0.9))) is None    # a box around most of the frame
    assert P.ring_window(plan(highlight=False)) is None


def test_course_graph_and_chapters():
    g, length = P.course_graph([(Path("/a.mp4"), 5.0), (Path("/b.mp4"), 6.0)], Path("/i.png"),
                               (Path("/it.png"), (800, 200)), Path("/o.png"), (Path("/ot.png"), (900, 500)),
                               1920, 1080, 30)
    text = g.text()
    assert abs(length - (2.0 + 5.0 + 6.0 + 2.5 - 0.9)) < 1e-9
    assert "offset=1.700" in text and "offset=6.400" in text and "offset=12.100" in text
    assert text.count("acrossfade=d=0.300") == 3 and text.count("xfade=transition=fade") == 3
    starts = P.course_starts([5.0, 6.0])
    assert starts == [1.7, 6.4]
    P.write_chapters(TMP / "ch.vtt", ["One", "Two"], starts, length)
    cues = P.read_vtt(TMP / "ch.vtt")
    assert [c.text for c in cues] == ["1. One", "2. Two"] and cues[0].start == 0 and abs(cues[1].end - length) < 0.001


# ---------------------------------------------------------------- action regions

def test_clean_box_and_rubric():
    assert P._clean_box([0.1, 0.2, 0.5, 0.6]) == (0.1, 0.2, 0.5, 0.6)
    assert P._clean_box([192, 108, 960, 540], 1920, 1080) == (0.1, 0.1, 0.5, 0.5)
    assert P._clean_box({"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.3}) == (0.1, 0.1, 0.3, 0.4)
    assert P._clean_box([0.5, 0.5, 0.51, 0.9]) is None and P._clean_box("x") is None
    d = TMP / "rubric"
    d.mkdir()
    assert P.rubric_regions(d, 1920, 1080) is None
    (d / "rubric.json").write_text(json.dumps({"steps": [{"n": 1, "region": [0.2, 0.2, 0.6, 0.7]}, {"n": 2}]}))
    assert P.rubric_regions(d, 1920, 1080) == {1: (0.2, 0.2, 0.6, 0.7)}
    (d / "rubric.json").write_text(json.dumps({"2": {"bbox": {"x0": 96, "y0": 54, "x1": 960, "y1": 540}}}))
    assert P.rubric_regions(d, 1920, 1080) == {2: (0.05, 0.05, 0.5, 0.5)}


class FakeClient:
    def __init__(self, rows):
        self.calls = []
        self.rows = rows
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps({"steps": self.rows})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn",
                               usage={"input_tokens": 4000, "output_tokens": 300})


def test_find_regions_claude_cache_and_offline():
    lesson_dir = demo_copy("regions", steps=2)
    lesson = json.loads((lesson_dir / "lesson.json").read_text())
    probes = {s["n"]: P.probe(lesson_dir / s["clip"]) for s in lesson["steps"]}
    work = TMP / "regions-work"
    work.mkdir()
    # offline: no call, no regions
    got = P.find_regions(lesson_dir, lesson["steps"], probes, work, None)
    assert got["source"] == "none" and got["steps"] == {}
    rows = [{"n": 1, "x0": 100, "y0": 50, "x1": 300, "y1": 250, "key_time": 3.0},
            {"n": 2, "x0": 0, "y0": 0, "x1": 1, "y1": 1, "key_time": 99}]
    fake = FakeClient(rows)
    with env(HANDOVER_NO_NETWORK=None):
        got = P.find_regions(lesson_dir, lesson["steps"], probes, work, None, client=fake)
    assert got["source"] == "claude" and len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema"
    images = [c for c in call["messages"][0]["content"] if c["type"] == "image"]
    assert len(images) == 6  # start, middle, end for each step
    assert got["steps"]["1"]["region"] == [round(100 / 512, 4), round(50 / 288, 4), round(300 / 512, 4),
                                           round(250 / 288, 4)]
    assert got["steps"]["2"]["key_time"] is None  # outside the clip
    assert got["cost_usd"] > 0
    # same clips: the cached answer is reused, no second call
    with env(HANDOVER_NO_NETWORK=None):
        again = P.find_regions(lesson_dir, lesson["steps"], probes, work, got, client=fake)
    assert again is got and len(fake.calls) == 1
    # rubric wins over everything
    (lesson_dir / "rubric.json").write_text(json.dumps({"steps": [{"n": 2, "region": [0.1, 0.1, 0.4, 0.4]}]}))
    with env(HANDOVER_NO_NETWORK=None):
        r = P.find_regions(lesson_dir, lesson["steps"], probes, work, got, client=fake)
    assert r["source"] == "rubric" and r["steps"] == {"2": {"region": [0.1, 0.1, 0.4, 0.4], "key_time": None}}


def test_budget_blocks_the_call():
    lesson_dir = demo_copy("budget", steps=1)
    lesson = json.loads((lesson_dir / "lesson.json").read_text())
    probes = {1: P.probe(lesson_dir / "clips/01.mp4")}
    (TMP / "regions-budget").mkdir()
    fake = FakeClient([])
    with env(HANDOVER_NO_NETWORK=None, HANDOVER_CLAUDE_BUDGET_TOTAL_USD="0"):
        got = P.find_regions(lesson_dir, lesson["steps"], probes, TMP / "regions-budget", None, client=fake)
    assert got["source"] == "none" and fake.calls == []


def test_ref_time_wins_over_claude_key_time():
    lesson_dir = demo_copy("keys", steps=2)
    lesson = json.loads((lesson_dir / "lesson.json").read_text())
    lesson["steps"][0]["ref_time"] = "00:06"
    lesson["production"] = {"steps": {"2": {"key_time": 1.5, "zoom": False, "region": [0.1, 0.1, 0.3, 0.3]}}}
    probes = {s["n"]: P.probe(lesson_dir / s["clip"]) for s in lesson["steps"]}
    assist = {"steps": {"1": {"region": [0.2, 0.2, 0.4, 0.4], "key_time": 1.0},
                        "2": {"region": None, "key_time": 2.0}}}
    plans = P.build_plans(lesson_dir, lesson, P.normalize_style({}), probes, assist, TMP)
    assert plans[0].key_time == 6.0 and plans[0].region == (0.2, 0.2, 0.4, 0.4)
    assert plans[1].key_time == 1.5 and plans[1].zoom is False and plans[1].region == (0.1, 0.1, 0.3, 0.3)
    assert plans[0].frac0 == 0 and abs(plans[0].frac1 - 0.5) < 1e-6 and abs(plans[1].frac1 - 1) < 1e-6


# ---------------------------------------------------------------- real render

def test_real_render_two_steps():
    lesson_dir = demo_copy("render", steps=2)
    before = (lesson_dir / "clips" / "01.mp4").read_bytes()
    result = P.produce(lesson_dir, {"burn_captions": True}, jobs=2)
    for n in (1, 2):
        info = ffprobe(lesson_dir / "clips_produced" / f"{n:02d}.mp4")
        kinds = {s["codec_type"]: s for s in info["streams"]}
        assert kinds["video"]["pix_fmt"] == "yuv420p" and kinds["video"]["color_range"] == "tv"
        assert (kinds["video"]["width"], kinds["video"]["height"]) == (1920, 1080)
        assert "audio" in kinds
        assert abs(float(info["format"]["duration"]) - 8.9) < 0.1
        assert P.read_vtt(lesson_dir / "clips_produced" / f"{n:02d}.vtt")[0].start == 0.5 + 0.9
    course = ffprobe(lesson_dir / "produced" / "course.mp4")
    assert abs(float(course["format"]["duration"]) - (2 + 8.9 * 2 + 2.5 - 0.9)) < 0.15
    assert {s["codec_type"] for s in course["streams"]} == {"video", "audio"}
    assert Image.open(lesson_dir / "produced" / "cover.jpg").size == (1920, 1080)
    assert len(P.read_vtt(lesson_dir / "produced" / "chapters.vtt")) == 2
    assert (lesson_dir / "clips" / "01.mp4").read_bytes() == before  # originals untouched
    saved = json.loads((lesson_dir / "lesson.json").read_text())["production"]
    assert saved["burn_captions"] is True and saved["output"]["course"] == "produced/course.mp4"
    assert result["output"]["assist"] == "none" and result["cost_usd"] == 0
    assert not list(lesson_dir.glob(".produce_*"))
    st = P.status(lesson_dir)
    assert st["present"] and not st["stale"] and st["style"]["burn_captions"] is True

    # re-render one step with a new style: the other step's file is kept, the course is rebuilt
    kept = (lesson_dir / "clips_produced" / "01.mp4").read_bytes()
    P.produce(lesson_dir, {"title_cards": "off"}, steps=[2])
    assert (lesson_dir / "clips_produced" / "01.mp4").read_bytes() == kept
    assert abs(float(ffprobe(lesson_dir / "clips_produced" / "02.mp4")["format"]["duration"]) - 8.0) < 0.1
    # a clip that changes after the render makes the output stale
    os.utime(lesson_dir / "clips" / "01.mp4", (1, 1))
    assert P.status(lesson_dir)["stale"]


def test_failed_render_leaves_old_output():
    lesson_dir = demo_copy("fail", steps=1)
    P.produce(lesson_dir, jobs=1)
    old = (lesson_dir / "produced" / "course.mp4").read_bytes()
    real = P.render_course

    def boom(*a, **k):
        raise RuntimeError("ffmpeg failed")

    P.render_course = boom
    try:
        try:
            P.produce(lesson_dir, {"theme": "mono"})
            raise AssertionError("expected a failure")
        except RuntimeError:
            pass
    finally:
        P.render_course = real
    assert (lesson_dir / "produced" / "course.mp4").read_bytes() == old
    assert not list(lesson_dir.glob(".produce_*"))
    assert json.loads((lesson_dir / "lesson.json").read_text())["production"]["theme"] == "system"


def test_cli_usage():
    with contextlib.redirect_stderr(io.StringIO()):
        assert P.main([str(TMP / "nope")]) == 2
        lesson_dir = demo_copy("cli", steps=1)
        assert P.main([str(lesson_dir), "--accent", "blue"]) == 2
        try:
            P.main([str(lesson_dir), "--steps", "x"])
            raise AssertionError("expected a usage error")
        except SystemExit as e:
            assert e.code == 2


def test_no_dashes_in_sources():
    for path in (Path(P.__file__), Path(__file__), P.REPO / "server" / "docs" / "production.md"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "\u2014" not in text and "\u2013" not in text, path.name


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

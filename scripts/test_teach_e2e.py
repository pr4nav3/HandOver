"""Offline tests for the scoring math in teach_e2e.py. Run: .venv/bin/python scripts/test_teach_e2e.py

No network, no spend, no video: only WER, boundary matching, caption parsing and stage timing.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import teach_e2e as e  # noqa: E402


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


def test_words_normalize_case_punctuation_hyphens_and_digits():
    assert e.words("Fold it corner-to-corner, then 4 corners!") == \
        ["fold", "it", "corner", "to", "corner", "then", "four", "corners"]
    assert e.words("  ") == []
    assert e.words("Don't stop.") == ["don't", "stop"]


def test_wer_identical_is_zero():
    assert e.wer("Fold it in half.", "fold it in half") == (0, 4, 0.0)


def test_wer_counts_substitution_deletion_insertion():
    ref = "fold the paper in half"
    assert e.wer(ref, "fold the sheet in half")[:2] == (1, 5)  # one substitution
    assert e.wer(ref, "fold paper in half")[:2] == (1, 5)  # one deletion
    assert e.wer(ref, "fold the paper in half now")[:2] == (1, 5)  # one insertion
    errors, n, rate = e.wer(ref, "")
    assert (errors, n) == (5, 5) and close(rate, 1.0)


def test_wer_replace_block_counts_the_longer_side():
    # two reference words heard as three different words: 3 errors, not 2
    errors, n, _ = e.wer("a big triangle", "a pig try angle")
    assert (errors, n) == (3, 3)


def test_wer_empty_reference():
    assert e.wer("", "") == (0, 0, 0.0)
    assert e.wer("", "noise")[2] == 1.0


def test_boundary_errors_nearest_found_boundary():
    errs = e.boundary_errors([8.0, 15.0, 24.0], [7.5, 16.0, 24.0])
    assert [round(x, 6) for x in errs] == [0.5, 1.0, 0.0]


def test_boundary_errors_with_missing_and_extra_steps():
    # a merged step: 15.0 has no boundary of its own, so it is measured to the nearest one
    assert e.boundary_errors([8.0, 15.0, 24.0], [8.0, 24.0]) == [0.0, 7.0, 0.0]
    # an extra found boundary does not change the true ones
    assert e.boundary_errors([8.0], [3.0, 8.5, 12.0]) == [0.5]
    assert e.boundary_errors([8.0, 15.0], []) == [None, None]


def test_summarize():
    mean, mx = e.summarize([0.5, 1.0, 0.0])
    assert close(mean, 0.5) and close(mx, 1.0)
    assert e.summarize([None, None]) == (None, None)
    assert e.summarize([]) == (None, None)


def test_best_overlap_picks_the_step_covering_the_truth_window():
    spans = [(0, 8), (8, 15), (15, 24), (24, 31)]
    assert e.best_overlap((14.0, 23.0), spans) == 2
    assert e.best_overlap((40.0, 50.0), spans) is None
    assert e.overlap((0, 5), (4, 10)) == 1


def test_distance_to_speech():
    spoken = [(9.3, 11.9), (12.6, 14.1)]
    assert e.distance_to_speech(10.0, spoken) == 0.0
    assert close(e.distance_to_speech(5.4, spoken), 3.9)
    assert close(e.distance_to_speech(12.3, spoken), 0.3)
    assert e.distance_to_speech(3.0, []) == 0.0


def test_caption_drift_flags_segments_that_start_in_silence():
    spoken = [(1.36, 5.25), (9.33, 11.91), (40.43, 44.52)]
    # what faster-whisper wrote without word timestamps: the second segment starts 3.9 s early
    drift = e.caption_drift([(1.1, 5.4), (5.4, 12.03), (40.5, 42.76), (42.76, 44.42)], spoken)
    assert [round(d, 2) for d in drift] == [0.26, 3.93, 0.0, 0.0]


def test_flip_index_prefers_the_title_then_overlap():
    spans = [(0, 9), (9, 16), (16, 25), (25, 33), (33, 40)]
    steps = [{"title": "Place paper"}, {"title": "Fold triangle"}, {"title": "Fold diagonal"},
             {"title": "Fold four corners to center and flip over"}, {"title": "Fold new corners in"}]
    # the flip is merged into step 4; step 5 overlaps the true flip window more but is not the flip
    assert e.flip_index(steps, (30.7, 39.5), spans) == 3
    steps[3]["title"] = "Fold corners in"
    assert e.flip_index(steps, (30.7, 39.5), spans) == 4
    steps[2]["check_question"] = "Is the paper turned over?"
    assert e.flip_index(steps, (30.7, 39.5), spans) == 2


def test_vtt_cues():
    text = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nFold it\ncorner to corner.\n\n" \
           "00:00:04.000 --> 00:00:05.000\nPress down.\n"
    assert e.vtt_cues(text) == ["Fold it corner to corner.", "Press down."]
    assert e.vtt_cues("WEBVTT\n\n") == []


def test_stage_times_first_run_with_download():
    lines = [
        (0.1, "[normalizing] Converting video to 1080p 30 fps"),
        (4.0, "[extracting] Finding steps with claude-haiku-5-5 from frames"),
        (6.0, "[extracting] Downloading speech model small.en once, about 460 MB"),
        (40.0, "[extracting] Transcribing narration"),
        (52.0, "[extracting] Transcribed 12 narration segments in 46.0 s"),
        (52.5, "[extracting] Sending 60 frames and 12 narration lines to claude-haiku-5-5"),
        (60.0, "[cutting] Cutting 8 step clips"),
        (70.0, "[done] /tmp/x (70.0 s)"),
    ]
    st = e.stage_times(lines, 70.2)
    assert close(st["normalize"], 4.0) and close(st["prep"], 2.0) and close(st["download"], 34.0)
    assert close(st["transcribe"], 12.0) and close(st["claude"], 7.5) and close(st["cut"], 10.0)
    assert close(st["total"], 70.2)


def test_stage_times_cached_model_and_missing_done():
    lines = [
        (3.0, "[extracting] Finding steps with claude-haiku-5-5 from frames"),
        (5.0, "[extracting] Transcribing narration"),
        (9.0, "[extracting] Transcribed 12 narration segments in 4.0 s"),
        (9.2, "[extracting] Sending 60 frames and 12 narration lines to claude-haiku-5-5"),
        (15.0, "[cutting] Cutting 8 step clips"),
        (17.0, "[cutting] step 1 of 8 ..."),
    ]
    st = e.stage_times(lines, 21.0)
    assert st["download"] is None and close(st["prep"], 2.0)
    assert close(st["cut"], 6.0)  # no [done] line: the cut runs to the end


def test_stage_times_failed_transcription():
    lines = [(3.0, "[extracting] Finding steps with x"), (5.0, "[extracting] Transcribing narration")]
    st = e.stage_times(lines, 6.0)
    assert st["transcribe"] is None and st["claude"] is None and st["cut"] is None


def test_color_words():
    vocab = {"blue", "yellow", "colored"}
    assert e.color_words("Is the blue side up?", vocab) == ["blue"]
    assert e.color_words("Are four flaps folded in?", vocab) == []


def test_table_marks_pass_and_fail():
    t = e.table([("A", "1", "<= 2", True), ("B", "3", "<= 2", False)])
    assert "| A | 1 | <= 2 | PASS |" in t and "| B | 3 | <= 2 | FAIL |" in t


def test_narration_matches_eight_states_and_has_no_dashes():
    assert len(e.NARRATION) == 8 and all(1 <= len(s) <= 2 for s in e.NARRATION)
    text = " ".join(" ".join(s) for s in e.NARRATION)
    assert "\u2014" not in text and "\u2013" not in text
    assert "flip" in " ".join(e.NARRATION[e.FLIP_STEP - 1]).lower()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

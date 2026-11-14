"""Mistake policy tests. Run: .venv/bin/python -m server.test_mistake (or pytest if installed)."""

import os

from server.mistake import MistakeWatch, needs_confirmation

STEPS = [{"title": f"s{i}"} for i in range(6)]
STEPS[4] = {"title": "s4", "common_mistake": "Flip it over first."}


class _env:
    """Set env vars for one block, then restore them."""

    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _feed(w, step, results):
    return [w.on_result(step, d, t) for t, d in results]


def test_settle_timing():
    w = MistakeWatch()
    assert _feed(w, 2, [(0, "no"), (2, "no"), (4.9, "no")]) == [False] * 3
    assert w.on_result(2, "no", 5.0) is True


def test_unsure_breaks_streak():
    w = MistakeWatch()
    assert _feed(w, 2, [(0, "no"), (3, "unsure"), (4, "no"), (6, "no"), (8.9, "no")]) == [False] * 5
    assert w.on_result(2, "no", 9.0) is True  # streak restarted at 4


def test_yes_resets():
    w = MistakeWatch()
    assert _feed(w, 2, [(0, "no"), (4, "yes"), (5, "no"), (9.5, "no")]) == [False] * 4
    assert w.on_result(2, "no", 10.0) is True


def test_cooldown_per_step():
    w = MistakeWatch()
    assert w.on_result(1, "no", 0) is False
    assert w.on_result(1, "no", 5) is True
    assert _feed(w, 1, [(6, "no"), (10, "no"), (14.9, "no")]) == [False] * 3
    assert w.on_result(1, "no", 15) is True
    # another step has its own cooldown
    w.reset()
    assert w.on_result(2, "no", 15) is False
    assert w.on_result(2, "no", 20) is True
    # back on step 1 inside its cooldown: still blocked even after a full streak
    w.reset()
    assert _feed(w, 1, [(20, "no"), (24.9, "no")]) == [False, False]
    assert w.on_result(1, "no", 25) is True  # 10 s since the fire at 15


def test_step_change_resets_streak():
    w = MistakeWatch()
    assert _feed(w, 1, [(0, "no"), (4, "no")]) == [False, False]
    assert w.on_result(2, "no", 5) is False  # new step, streak starts at 5
    assert w.on_result(2, "no", 9.9) is False
    assert w.on_result(2, "no", 10) is True
    w.reset()
    assert w.on_result(3, "no", 11) is False


def test_behind_with_common_mistake():
    w = MistakeWatch()
    m = w.decide(4, 6, 3, 0.86, STEPS)
    assert m == {"type": "mistake", "step": 4, "kind": "behind", "looks_like": 3,
                 "message": "Flip it over first.", "confidence": 0.86, "source": "gemini"}
    assert needs_confirmation(m) is False


def test_behind_without_common_mistake():
    w = MistakeWatch()
    m = w.decide(3, 6, 2, 0.7, STEPS)
    assert m["kind"] == "behind" and m["looks_like"] == 2
    assert m["message"] == "This still looks like step 3."
    blank = [dict(s, common_mistake="") for s in STEPS]
    assert w.decide(4, 6, 3, 0.9, blank)["message"] == "This still looks like step 4."


def test_ahead():
    w = MistakeWatch()
    m = w.decide(2, 6, 3, 0.75, STEPS)
    assert m["kind"] == "ahead" and m["looks_like"] == 3 and m["message"] == "You're ahead."
    assert needs_confirmation(m) is True


def test_ahead_at_last_step_is_none():
    w = MistakeWatch()
    assert w.decide(5, 6, 6, 0.95, STEPS) is None


def test_low_confidence_and_other_matches():
    w = MistakeWatch()
    assert w.decide(4, 6, 3, 0.69, STEPS) is None
    assert w.decide(2, 6, 3, 0.5, STEPS) is None
    assert w.decide(4, 6, 4, 0.99, STEPS) is None
    assert w.decide(4, 6, None, 0.99, STEPS) is None
    assert w.decide(4, 6, 1, 0.99, STEPS) is None
    assert w.decide(0, 6, -1, 0.99, STEPS) is None


def test_min_conf_env():
    with _env(HANDOVER_MISTAKE_MIN_CONF="0.9"):
        w = MistakeWatch()
    assert w.min_conf == 0.9
    assert w.decide(4, 6, 3, 0.86, STEPS) is None
    for bad in ("junk", "1.5", "-0.1", "nan"):
        with _env(HANDOVER_MISTAKE_MIN_CONF=bad):
            assert MistakeWatch().min_conf == 0.7, bad


def test_settle_and_cooldown_env():
    w = MistakeWatch()
    assert (w.settle_s, w.cooldown_s) == (5.0, 10.0)
    with _env(HANDOVER_MISTAKE_SETTLE_S="2", HANDOVER_MISTAKE_COOLDOWN_S="3"):
        w = MistakeWatch()
        assert (w.settle_s, w.cooldown_s) == (2.0, 3.0)
        assert _feed(w, 1, [(0, "no"), (1.9, "no"), (2, "no"), (4.9, "no"), (5, "no")]) == \
            [False, False, True, False, True]
        assert (MistakeWatch(settle_s=7, cooldown_s=20).settle_s, MistakeWatch(cooldown_s=20).cooldown_s) == (7, 20)
    for settle, cooldown in [("0.4", "0.5"), ("61", "121"), ("x", "nan")]:
        with _env(HANDOVER_MISTAKE_SETTLE_S=settle, HANDOVER_MISTAKE_COOLDOWN_S=cooldown):
            w = MistakeWatch()
            assert (w.settle_s, w.cooldown_s) == (5.0, 10.0), (settle, cooldown)


def test_mock_behind_once():
    with _env(HANDOVER_CHECK="mock", HANDOVER_MOCK_MISTAKE="behind:4"):
        w = MistakeWatch()
        assert w.mock(3, 10) is None  # other step
        assert w.mock(4, 3.9) is None  # too early
        m = w.mock(4, 4.0, STEPS)
        assert m == {"type": "mistake", "step": 4, "kind": "behind", "looks_like": 3,
                     "message": "Flip it over first.", "confidence": 0.9, "source": "mock"}
        assert w.mock(4, 5.0, STEPS) is None  # once only
        assert MistakeWatch().mock(4, 4.0)["message"] == "This still looks like step 4."
        w.reset()  # a new visit to the step re-arms it
        assert w.mock(4, 4.0) is not None


def test_mock_ahead():
    with _env(HANDOVER_CHECK="mock", HANDOVER_MOCK_MISTAKE="Ahead:1"):
        m = MistakeWatch().mock(1, 4.5)
        assert m["kind"] == "ahead" and m["looks_like"] == 2 and m["message"] == "You're ahead."
        assert m["source"] == "mock" and needs_confirmation(m)


def test_mock_malformed_ignored():
    for raw in ["", "behind", "behind:", "behind:x", "sideways:2", "2", "behind:0"]:
        with _env(HANDOVER_CHECK="mock", HANDOVER_MOCK_MISTAKE=raw):
            w = MistakeWatch()
            assert all(w.mock(s, 100) is None for s in range(6)), raw


def test_mock_ignored_outside_mock_mode():
    with _env(HANDOVER_CHECK="gemini", HANDOVER_MOCK_MISTAKE="behind:4"):
        assert MistakeWatch().mock(4, 100) is None
    saved = os.environ.pop("HANDOVER_CHECK", None)
    try:
        with _env(HANDOVER_MOCK_MISTAKE="behind:4"):
            assert MistakeWatch().mock(4, 100) is None
    finally:
        if saved is not None:
            os.environ["HANDOVER_CHECK"] = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

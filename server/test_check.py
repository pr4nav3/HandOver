"""Debouncer and mock-check tests. Run: .venv/bin/python -m server.test_check (or pytest if installed)."""

import asyncio
import os
import time

from server.check import Debouncer, check_frame


def test_two_confident_yes_advance():
    d = Debouncer(n=2, min_conf=0.8)
    assert d.feed("yes", 0.9) is False
    assert d.feed("yes", 0.85) is True
    assert d.count == 0  # resets after firing


def test_no_and_unsure_reset():
    d = Debouncer(n=2, min_conf=0.8)
    for breaker in [("no", 0.9), ("unsure", 0.9), ("unsure", 0.0), ("yes", 0.79)]:
        assert d.feed("yes", 0.9) is False
        assert d.feed(*breaker) is False
        assert d.count == 0
        assert d.feed("yes", 0.9) is False
        d.reset()


def test_never_on_unsure():
    d = Debouncer(n=2, min_conf=0.8)
    assert not any(d.feed("unsure", 1.0) for _ in range(10))


def test_env_overrides():
    os.environ["HANDOVER_DEBOUNCE_N"], os.environ["HANDOVER_MIN_CONF"] = "3", "0.5"
    try:
        d = Debouncer()
        assert (d.n, d.min_conf) == (3, 0.5)
        assert [d.feed("yes", 0.6) for _ in range(3)] == [False, False, True]
    finally:
        del os.environ["HANDOVER_DEBOUNCE_N"], os.environ["HANDOVER_MIN_CONF"]


def test_mock_check():
    os.environ["HANDOVER_CHECK"], os.environ["HANDOVER_MOCK_PASS_SECONDS"] = "mock", "1"
    try:
        now = time.monotonic()
        early = asyncio.run(check_frame(b"r", b"l", "q", step_started_at=now))
        late = asyncio.run(check_frame(b"r", b"l", "q", step_started_at=now - 5))
        assert early.done == "no" and late.done == "yes" and late.confidence == 0.9
        assert 500 <= late.latency_ms < 1500
    finally:
        del os.environ["HANDOVER_CHECK"], os.environ["HANDOVER_MOCK_PASS_SECONDS"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

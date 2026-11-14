"""Check tests: debouncer, mock, breaker, error classes, reason, compare. No network.

Run: .venv/bin/python -m server.test_check (or pytest if installed).
"""

import asyncio
import io
import json
import os
import time
from contextlib import contextmanager
from types import SimpleNamespace

from google.genai import errors as genai_errors
from PIL import Image

from server import check
from server.check import Breaker, CheckResult, Debouncer, MatchResult, check_frame, compare_refs, trim_reason


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


# ---------------------------------------------------------------- breaker (fake clock)

OK = CheckResult("no", 0.9, 500)
ERR = CheckResult("unsure", 0.0, 100, error="error")
TIMEOUT = CheckResult("unsure", 0.0, 3000, error="timeout")
RATE = CheckResult("unsure", 0.0, 200, error="rate_limited")
NOKEY = CheckResult("unsure", 0.0, 0, error="no_key")


def test_breaker_opens_after_three_errors():
    b = Breaker(errors=3, open_seconds=30)
    assert b.allow(0) and not b.offline and b.reason is None
    b.record(ERR, 1)
    b.record(TIMEOUT, 2)
    assert not b.offline
    b.record(ERR, 3)
    assert b.offline and b.reason == "errors"
    assert not b.allow(10) and not b.allow(32.9)


def test_breaker_success_resets_count():
    b = Breaker(errors=3, open_seconds=30)
    b.record(ERR, 1)
    b.record(ERR, 2)
    b.record(OK, 3)
    b.record(ERR, 4)
    b.record(ERR, 5)
    assert not b.offline


def test_breaker_any_429_opens():
    b = Breaker(errors=3, open_seconds=30)
    b.record(RATE, 5)
    assert b.offline and b.reason == "rate_limited" and not b.allow(6)


def test_breaker_trial_success_closes():
    b = Breaker(errors=3, open_seconds=30)
    b.record(RATE, 0)
    assert not b.allow(29.9)
    assert b.allow(30) is True  # the one trial call
    assert b.allow(30.1) is False and b.allow(100) is False  # half-open until recorded
    assert b.offline and b.reason == "rate_limited"
    b.record(OK, 31)
    assert not b.offline and b.reason is None and b.allow(31)


def test_breaker_trial_failure_reopens():
    b = Breaker(errors=3, open_seconds=30)
    for t in (0, 1, 2):
        b.record(TIMEOUT, t)
    assert b.allow(32)
    b.record(ERR, 33)  # one failure on the trial is enough
    assert b.offline and b.reason == "errors"
    assert not b.allow(62.9) and b.allow(63)


def test_breaker_late_errors_do_not_extend():
    b = Breaker(errors=3, open_seconds=30)
    b.record(RATE, 0)
    b.record(ERR, 20)  # call started before it opened
    assert b.allow(30)


def test_breaker_no_key_stays_open():
    b = Breaker(errors=3, open_seconds=30)
    b.record(NOKEY, 0)
    assert b.offline and b.reason == "no_key"
    assert not b.allow(1000)
    b.record(OK, 1001)
    assert b.offline and b.reason == "no_key" and not b.allow(2000)


def test_breaker_env_seconds():
    os.environ["HANDOVER_BREAKER_SECONDS"] = "5"
    try:
        assert Breaker().open_seconds == 5.0
    finally:
        del os.environ["HANDOVER_BREAKER_SECONDS"]
    assert Breaker().open_seconds == 30.0


# ---------------------------------------------------------------- fake Gemini client

def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 24), (200, 200, 200)).save(buf, format="JPEG")
    return buf.getvalue()


class _FakeModels:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        out = self.behavior()
        if isinstance(out, BaseException):
            raise out
        if out == "hang":
            await asyncio.sleep(10)
        return SimpleNamespace(text=out)


@contextmanager
def fake_client(behavior, timeout: str = "3"):
    """Swap in a client whose generate_content returns or raises what behavior() gives."""
    models = _FakeModels(behavior)
    fake = SimpleNamespace(aio=SimpleNamespace(models=models))
    saved_get, saved_key = check._get_client, os.environ.get("GEMINI_API_KEY")
    check._get_client = lambda: fake
    os.environ["GEMINI_API_KEY"] = "fake-key-for-unit-test"  # passes the no_key fast path
    os.environ["HANDOVER_CHECK_TIMEOUT"] = timeout
    try:
        yield models
    finally:
        check._get_client = saved_get
        _restore("GEMINI_API_KEY", saved_key)
        del os.environ["HANDOVER_CHECK_TIMEOUT"]


def _restore(name: str, value) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _run(coro):
    return asyncio.run(coro)


def test_error_classification():
    img = _jpeg()
    cases = [
        (lambda: genai_errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}}), "rate_limited"),
        (lambda: genai_errors.ClientError(0, {"error": {"code": 0, "status": "RESOURCE_EXHAUSTED"}}), "rate_limited"),
        (lambda: genai_errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}), "error"),
        (lambda: genai_errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid.", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}), "no_key"),
        (lambda: genai_errors.ClientError(401, {"error": {"code": 401, "status": "UNAUTHENTICATED"}}), "no_key"),
        (lambda: genai_errors.ClientError(403, {"error": {"code": 403, "status": "PERMISSION_DENIED"}}), "no_key"),
        (lambda: genai_errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}), "error"),
        (lambda: RuntimeError("boom"), "error"),
        (lambda: "not json", "error"),
    ]
    for behavior, want in cases:
        with fake_client(behavior):
            r = _run(check_frame(img, img, "q"))
            m = _run(compare_refs(img, [(0, img), (1, img)]))
        assert (r.done, r.confidence, r.reason, r.error) == ("unsure", 0.0, None, want), (want, r)
        assert (m.step, m.confidence, m.error) == (None, 0.0, want), (want, m)


def test_invalid_key_opens_breaker_at_once():
    img = _jpeg()
    bad = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}
    with fake_client(lambda: genai_errors.ClientError(400, bad)):
        r = _run(check_frame(img, img, "q"))
    b = Breaker(errors=3, open_seconds=30)
    b.record(r, 0)
    assert r.error == "no_key" and b.offline and b.reason == "no_key" and not b.allow(1000)


def test_timeout_classification():
    img = _jpeg()
    with fake_client(lambda: "hang", timeout="0.2"):
        r = _run(check_frame(img, img, "q"))
        m = _run(compare_refs(img, [(3, img)]))
    assert r.error == "timeout" and r.done == "unsure" and r.confidence == 0.0 and r.latency_ms < 1500
    assert m.error == "timeout" and m.step is None


def _answer(differs: str, done: str = "no", conf: float = 0.82) -> str:
    return json.dumps({"seen": "square, white side up, two flaps", "differs": differs, "done": done, "confidence": conf})


def _texts(call) -> list[str]:
    return [p.text for p in call.contents[0].parts if p.text]


def _images(call) -> list:
    return [p for p in call.contents[0].parts if p.inline_data]


def test_timeout_override_per_call():
    """A per-call timeout wins over the env for that call only."""
    img = _jpeg()
    with fake_client(lambda: "hang", timeout="5") as _:
        t0 = time.monotonic()
        r = _run(check_frame(img, img, "q", timeout=0.2))
        m = _run(compare_refs(img, [(0, img)], timeout=0.2))
        fast = time.monotonic() - t0
    assert r.error == "timeout" and m.error == "timeout" and fast < 2.0
    assert os.environ.get("HANDOVER_CHECK_TIMEOUT") is None  # env never touched
    with fake_client(lambda: _answer("nothing", "yes", 0.9), timeout="0.2"):
        ok = _run(check_frame(img, img, "q", timeout=5))  # override can also be longer
    assert ok.error is None and ok.done == "yes"
    assert check._timeout() == 3.0 and check._timeout(7.5) == 7.5


def test_success_with_reason():
    img = _jpeg()
    text = _answer("Seams still facing up on the left flap, fold it.")
    with fake_client(lambda: text) as models:
        r = _run(check_frame(img, img, "Is it folded?"))
    assert (r.done, r.confidence, r.error) == ("no", 0.82, None)
    assert r.reason == "Seams still facing up on the left flap"
    assert r.as_dict() == {"done": "no", "confidence": 0.82, "latency_ms": r.latency_ms, "reason": r.reason}
    cfg = models.calls[0].config
    schema = cfg.response_json_schema
    assert list(schema["properties"]) == ["seen", "differs", "done", "confidence"]  # evidence first
    assert schema["required"] == ["seen", "differs", "done", "confidence"]
    assert cfg.media_resolution.name == "MEDIA_RESOLUTION_LOW"
    assert cfg.temperature is None


def test_differs_nothing_is_none():
    img = _jpeg()
    for differs in ("nothing", "Nothing.", "", "none"):
        with fake_client(lambda: _answer(differs, "yes", 0.9)):
            r = _run(check_frame(img, img, "q"))
        assert (r.done, r.reason) == ("yes", None), differs


def test_two_image_prompt():
    img = _jpeg()
    with fake_client(lambda: _answer("nothing")) as models:
        _run(check_frame(img, img, "Is the left flap folded to the center?"))
    call = models.calls[0]
    texts = _texts(call)
    assert texts[:2] == ["IMAGE A: DONE, the finished step", "IMAGE B: LIVE camera"]
    assert len(_images(call)) == 2
    assert check.RULE in texts[-1] and "Is the left flap folded" in texts[-1] and "BEFORE" not in texts[-1]


def test_prev_ref_three_image_prompt():
    img = _jpeg()
    with fake_client(lambda: _answer("nothing")) as models:
        _run(check_frame(img, img, "q", prev_ref=img))
    call = models.calls[0]
    texts = _texts(call)
    assert texts[:3] == [
        "IMAGE A: the object BEFORE this step (answer no if LIVE looks like this)",
        "IMAGE B: DONE, the finished step",
        "IMAGE C: LIVE camera",
    ]
    imgs = _images(call)
    assert len(imgs) == 3
    assert imgs[0].media_resolution is None and imgs[1].media_resolution is None
    assert imgs[2].media_resolution.level.name == "MEDIA_RESOLUTION_LOW"  # LIVE is last
    assert check.RULE in texts[-1] and check.BEFORE_RULE.strip() in texts[-1]


def test_live_res_env():
    img = _jpeg()
    os.environ["HANDOVER_CHECK_LIVE_RES"] = "medium"
    try:
        with fake_client(lambda: _answer("nothing")) as models:
            _run(check_frame(img, img, "q"))
    finally:
        del os.environ["HANDOVER_CHECK_LIVE_RES"]
    assert _images(models.calls[0])[-1].media_resolution.level.name == "MEDIA_RESOLUTION_MEDIUM"


def test_thinking_per_model():
    for model, want in [
        ("gemini-3.5-flash-lite", "MINIMAL"),
        ("gemini-3.8-flash", "LOW"),
        ("models/gemini-3.8-flash", "LOW"),
        ("gemini-4-flash", "LOW"),
    ]:
        tc = check._thinking(model)
        assert tc.thinking_level.name == want and tc.thinking_budget is None, model
    img = _jpeg()
    for model, want in [("gemini-3.5-flash-lite", "MINIMAL"), ("gemini-3.8-flash", "LOW")]:
        os.environ["HANDOVER_CHECK_MODEL"] = model
        try:
            with fake_client(lambda: _answer("nothing")) as models:
                _run(check_frame(img, img, "q"))
                _run(compare_refs(img, [(0, img)]))
        finally:
            del os.environ["HANDOVER_CHECK_MODEL"]
        for call in models.calls:
            assert call.model == model
            assert call.config.thinking_config.thinking_level.name == want
            assert call.config.thinking_config.thinking_budget is None
            assert call.config.temperature is None


def test_client_per_loop_without_retries():
    """Two asyncio.run calls in one process each get a working client; closed loops are dropped."""
    saved_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "fake-key-for-unit-test"

    async def grab():
        c1, c2 = check._get_client(), check._get_client()  # no network: building a client is local
        assert c1 is c2 and check._has_client()
        return c1

    try:
        a = _run(grab())
        b = _run(grab())
        assert a is not b
        assert a._api_client._http_options.retry_options is None
        assert a._api_client._async_httpx_client.is_closed  # closed by its own loop's shutdown
        pool = b._api_client._async_httpx_client._transport._pool  # keep-alive reached the pool
        import httpx2

        assert isinstance(b._api_client._async_httpx_client, httpx2.AsyncClient)
        assert pool._keepalive_expiry == 120 and pool._max_keepalive_connections == 4
        assert not check._has_client()  # outside any loop

        async def build_and_list():
            check._get_client()
            return [lp.is_closed() for lp in check._clients]

        assert _run(build_and_list()) == [False]  # closed loops pruned on each build
    finally:
        _restore("GEMINI_API_KEY", saved_key)
        check._clients.clear()


def test_two_asyncio_runs_both_work():
    """Separate asyncio.run calls in one process each succeed (like teach's self-test in a worker
    thread). The stand-in client fails, as the real SDK does, when used from another loop."""
    from google import genai

    img = _jpeg()
    built_on = []

    class _LoopBoundClient:
        def __init__(self, **kw):
            self.loop = asyncio.get_running_loop()
            built_on.append(self.loop)
            self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._gen))

        async def _gen(self, **kw):
            if asyncio.get_running_loop() is not self.loop:
                raise RuntimeError("Event loop is closed")
            return SimpleNamespace(text=_answer("nothing", "yes", 0.9))

    saved_cls, saved_key = genai.Client, os.environ.get("GEMINI_API_KEY")
    genai.Client = _LoopBoundClient
    os.environ["GEMINI_API_KEY"] = "fake-key-for-unit-test"
    try:
        r1 = _run(check_frame(img, img, "q"))
        r2 = _run(check_frame(img, img, "q"))

        async def twice():
            return [await check_frame(img, img, "q"), await check_frame(img, img, "q")]

        r3, r4 = _run(twice())
    finally:
        genai.Client = saved_cls
        _restore("GEMINI_API_KEY", saved_key)
        check._clients.clear()
    assert [(r.done, r.error) for r in (r1, r2, r3, r4)] == [("yes", None)] * 4
    assert len(built_on) == 3  # one client per loop, reused within a loop


def test_max_side_env():
    big = io.BytesIO()
    Image.new("RGB", (1280, 720), (10, 20, 30)).save(big, format="JPEG")
    data = big.getvalue()

    def long_side(b: bytes) -> int:
        return max(Image.open(io.BytesIO(b)).size)

    assert long_side(check.downscale_jpeg(data)) == 640
    os.environ["HANDOVER_CHECK_MAX_SIDE"] = "512"
    try:
        assert long_side(check.downscale_jpeg(data)) == 512
        assert long_side(check.downscale_jpeg(data, 320, 75)) == 320  # explicit size wins (main.py UI frames)
        os.environ["HANDOVER_CHECK_MAX_SIDE"] = "junk"
        assert long_side(check.downscale_jpeg(data)) == 640
    finally:
        del os.environ["HANDOVER_CHECK_MAX_SIDE"]


def test_trim_reason():
    assert trim_reason(None) is None and trim_reason("") is None and trim_reason("   ") is None
    assert trim_reason("flap not folded.") == "flap not folded"
    assert trim_reason("one two three four five six seven eight nine ten") == "one two three four five six seven eight"
    assert trim_reason("a\nb  c") == "a b c"
    assert trim_reason("one two three four five six seven eight nine ten eleven twelve thirteen", 12).endswith("twelve")


def test_no_key_skips_network():
    saved_env = {k: os.environ.pop(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if k in os.environ}
    saved_get, saved_read = check._get_client, check._read_env_file

    def _must_not_build():
        raise AssertionError("built a client without a key")

    check._get_client, check._read_env_file = _must_not_build, lambda: {}
    try:
        r = _run(check_frame(b"x", b"y", "q"))
        m = _run(compare_refs(b"x", [(0, b"r")]))
        assert (r.done, r.confidence, r.error, r.latency_ms) == ("unsure", 0.0, "no_key", 0)
        assert (m.step, m.error) == (None, "no_key")
    finally:
        check._get_client, check._read_env_file = saved_get, saved_read
        os.environ.update(saved_env)


# ---------------------------------------------------------------- compare

def test_compare_label_mapping():
    img = _jpeg()
    refs = [(3, img), (4, img), (5, img)]
    for label, want in [("A", 3), ("B", 4), ("C", 5), ("none", None), ("D", None), ("b", 4)]:
        with fake_client(lambda: json.dumps({"match": label, "confidence": 0.86})) as models:
            m = _run(compare_refs(img, refs, "Fold the flap"))
        assert (m.step, m.confidence, m.error) == (want, 0.86, None), (label, m)
    call = models.calls[0]
    assert call.config.response_json_schema["properties"]["match"]["enum"] == ["A", "B", "C", "none"]
    texts = [p.text for p in call.contents[0].parts if p.text]
    assert texts[:4] == ["Reference A", "Reference B", "Reference C", "Live camera now"]
    assert "Fold the flap" in texts[-1]
    assert sum(1 for p in call.contents[0].parts if p.inline_data) == 4


def test_compare_mock():
    os.environ["HANDOVER_CHECK"] = "mock"
    try:
        m = _run(compare_refs(b"l", [(0, b"a"), (1, b"b")]))
        assert m == MatchResult(None, 0.0, 0, None)
    finally:
        del os.environ["HANDOVER_CHECK"]


def test_gate_verdict():
    ok3 = [None] * 3
    assert "PASS" in check.gate_verdict([1000, 2000, 1500], ok3)
    assert "WIDEN" in check.gate_verdict([2100, 2400, 2200], ok3)
    assert "SLOW" in check.gate_verdict([2600, 3000, 2700], ok3)
    assert "NOT MEASURED" in check.gate_verdict([100, 100], ["error", "no_key"])
    # Half failing: fast failures must not drag the median into a PASS.
    half = check.gate_verdict([300, 3000, 300, 3000], ["error", "timeout", None, None])
    assert "PASS" not in half and "UNRELIABLE" in half and "2 of 4" in half
    # One failure in 20 is within 10%: verdict on successful calls, failure noted.
    one = check.gate_verdict([1200] * 19 + [3000], [None] * 19 + ["timeout"])
    assert one.startswith("verdict: PASS") and "1 of 20 calls failed (timeout 1)" in one
    # Median over successful calls only: two timeouts at 3 s do not count as latency.
    assert "PASS (median 1.00 s" in check.gate_verdict([1000] * 18 + [3000, 3000], [None] * 18 + ["timeout"] * 2)


def test_summarize_success_only():
    line = check.summarize([1000, 2000, 3000, 50], [None, None, "timeout", "rate_limited"])
    assert line.startswith("ok 2/4  p50 1500 ms") and "max 2000 ms" in line
    assert "failures: timeout 1, rate_limited 1" in line
    assert check.summarize([10, 20], ["error", "error"]) == "ok 0/2  no successful calls  failures: error 2"


def test_max_output_tokens_per_thinking():
    assert check._config({}, "gemini-3.8-flash").max_output_tokens == 1024
    assert check._config({}, "gemini-4-flash").max_output_tokens == 1024
    assert check._config({}, "gemini-3.5-flash-lite").max_output_tokens == 256


def test_generic_prompt_wording():
    for text in (check.PROMPT, check.RULE, check.BEFORE_RULE, json.dumps(check._answer_schema())):
        assert "paper" not in text and "flap" not in text, text
    assert "outline shape, orientation, visible parts" in check.PROMPT
    assert "orientation, visible parts" in check._answer_schema()["properties"]["seen"]["description"]


def test_breaker_force_open():
    b = Breaker(errors=3, open_seconds=30)
    b.force_open("no_key")
    assert b.offline and b.reason == "no_key" and not b.allow(10_000)
    b2 = Breaker(errors=3, open_seconds=30)
    b2.force_open("rate_limited", now=100)
    assert b2.reason == "rate_limited" and not b2.allow(129) and b2.allow(130)
    try:
        Breaker().force_open("errors")
        raise AssertionError("expected ValueError without now")
    except ValueError:
        pass


def test_bad_env_falls_back():
    """Typos in env vars fall back to defaults instead of crashing a check."""
    bad = {
        "HANDOVER_CHECK_TIMEOUT": "fast",
        "HANDOVER_BREAKER_SECONDS": "-5",
        "HANDOVER_DEBOUNCE_N": "0",
        "HANDOVER_MIN_CONF": "1.5",
        "HANDOVER_CHECK_LIVE_RES": "ultra",
        "HANDOVER_CHECK_MAX_SIDE": "10",
        "HANDOVER_MOCK_PASS_SECONDS": "soon",
    }
    os.environ.update(bad)
    try:
        assert check._timeout() == 3.0 and check._timeout(0) == 3.0 and check._timeout(9) == 9
        assert Breaker().open_seconds == 30.0
        d = Debouncer()
        assert (d.n, d.min_conf) == (2, 0.8)
        assert check._live_res().name == "MEDIA_RESOLUTION_LOW"
        assert check._max_side() == 640
        img = _jpeg()
        with fake_client(lambda: _answer("nothing", "yes", 0.9)):
            os.environ["HANDOVER_CHECK_TIMEOUT"] = "fast"  # fake_client set it; break it again
            r = _run(check_frame(img, img, "q"))
        assert r.error is None and r.done == "yes"
    finally:
        for k in bad:
            os.environ.pop(k, None)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

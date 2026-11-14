"""Check tests: debouncer, mock, breaker, error classes, reason, compare, both providers. No network.

Run: .venv/bin/python -m server.test_check (or pytest if installed).

Hermetic on purpose: a real Claude key may sit in .env, so this module pins the provider to
gemini (Claude tests opt in), replaces the real Claude client with one that fails the test,
and points the spend ledger at a temp file.
"""

import asyncio
import io
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
from google.genai import errors as genai_errors
from PIL import Image

from server import check, spend
from server.check import Breaker, CheckResult, Debouncer, MatchResult, check_frame, compare_refs, trim_reason

_TMP = Path(tempfile.mkdtemp(prefix="handover-test-check-"))
os.environ["HANDOVER_CHECK_PROVIDER"] = "gemini"
os.environ["HANDOVER_NO_NETWORK"] = "1"
os.environ["HANDOVER_CLAUDE_SPEND_FILE"] = str(_TMP / "spend.json")


def _no_real_claude():
    raise AssertionError("a test reached the real Claude client")


_real_get_claude = check._get_claude
check._get_claude = _no_real_claude


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
    saved_key, saved_nn = os.environ.get("GEMINI_API_KEY"), os.environ.pop("HANDOVER_NO_NETWORK", None)
    os.environ["GEMINI_API_KEY"] = "fake-key-for-unit-test"  # building a client is local; no call is made

    async def grab():
        c1, c2 = check._get_client(), check._get_client()  # no network: building a client is local
        assert c1 is c2 and check._has_client("gemini")
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
        assert not check._has_client("gemini")  # outside any loop

        async def build_and_list():
            check._get_client()
            return [lp.is_closed() for lp in check._clients]

        assert _run(build_and_list()) == [False]  # closed loops pruned on each build
    finally:
        _restore("GEMINI_API_KEY", saved_key)
        _restore("HANDOVER_NO_NETWORK", saved_nn)
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
    saved_nn = os.environ.pop("HANDOVER_NO_NETWORK", None)  # the stand-in replaces the real client class
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
        _restore("HANDOVER_NO_NETWORK", saved_nn)
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


def test_has_key():
    saved = {k: os.environ.pop(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if k in os.environ}
    saved_read = check._read_env_file
    try:
        check._read_env_file = lambda: {}
        assert check.has_key() is False
        check._read_env_file = lambda: {"GEMINI_API_KEY": "from-dotenv"}
        assert check.has_key() is True  # .env counts
        check._read_env_file = lambda: {}
        os.environ["GOOGLE_API_KEY"] = "from-env"
        assert check.has_key() is True
    finally:
        check._read_env_file = saved_read
        os.environ.pop("GOOGLE_API_KEY", None)
        os.environ.update(saved)


class _WarmModels:
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, []

    async def get(self, *, model):
        self.calls.append(model)
        out = self.behavior()
        if isinstance(out, BaseException):
            raise out
        if out == "hang":
            await asyncio.sleep(10)
        return SimpleNamespace(name=f"models/{model}")


@contextmanager
def warm_client(behavior):
    models = _WarmModels(behavior)
    saved_get, saved_key = check._get_client, os.environ.get("GEMINI_API_KEY")
    saved_nn = os.environ.get("HANDOVER_NO_NETWORK")
    check._get_client = lambda: SimpleNamespace(aio=SimpleNamespace(models=models))
    os.environ["GEMINI_API_KEY"] = "fake-key-for-unit-test"
    os.environ["HANDOVER_NO_NETWORK"] = "0"  # warm_up talks to the fake client
    try:
        yield models
    finally:
        check._get_client = saved_get
        _restore("GEMINI_API_KEY", saved_key)
        _restore("HANDOVER_NO_NETWORK", saved_nn)


def test_warm_up():
    with warm_client(lambda: "ok") as models:
        os.environ["HANDOVER_CHECK_MODEL"] = "gemini-3.8-flash"
        try:
            assert _run(check.warm_up()) is True
        finally:
            del os.environ["HANDOVER_CHECK_MODEL"]
    assert models.calls == ["gemini-3.8-flash"]
    cases = [
        lambda: genai_errors.ClientError(400, {"error": {"code": 400, "details": [{"reason": "API_KEY_INVALID"}]}}),
        lambda: genai_errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}),
        lambda: RuntimeError("network down"),
    ]
    for behavior in cases:
        with warm_client(behavior):
            assert _run(check.warm_up()) is False
    with warm_client(lambda: "hang"):
        t0 = time.monotonic()
        assert _run(check.warm_up(timeout=0.2)) is False
        assert time.monotonic() - t0 < 2
    with warm_client(lambda: "ok") as models:
        os.environ["HANDOVER_CHECK"] = "mock"
        try:
            assert _run(check.warm_up()) is False
        finally:
            del os.environ["HANDOVER_CHECK"]
    assert models.calls == []  # mock never touches the client


def test_warm_up_without_key_makes_no_call():
    saved = {k: os.environ.pop(k) for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY") if k in os.environ}
    saved_get, saved_read = check._get_client, check._read_env_file

    def _must_not_build():
        raise AssertionError("built a client without a key")

    check._get_client, check._read_env_file = _must_not_build, lambda: {}
    try:
        assert _run(check.warm_up()) is False
    finally:
        check._get_client, check._read_env_file = saved_get, saved_read
        os.environ.update(saved)


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
    assert list(call.config.response_json_schema["properties"]) == ["seen", "match", "confidence"]
    texts = [p.text for p in call.contents[0].parts if p.text]
    assert texts[:4] == ["Reference A", "Reference B", "Reference C", "LIVE: the camera now"]
    assert "Fold the flap" not in " ".join(texts)  # question-neutral
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


# ---------------------------------------------------------------- Claude provider (fake client)

_ledger_ids = itertools.count()
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, code: int):
    return cls(f"{code} test", response=httpx2.Response(code, request=_REQ), body=None)


def _claude_msg(text=None, stop="end_turn", usage=None, content=None, category=None):
    blocks = content if content is not None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=blocks, stop_reason=stop,
        stop_details=SimpleNamespace(category=category) if category else None,
        usage=usage or SimpleNamespace(input_tokens=1200, output_tokens=40, cache_read_input_tokens=0,
                                       cache_creation_input_tokens=0, cache_creation=None),
    )


class _FakeClaude:
    def __init__(self, behavior):
        self.behavior, self.calls, self.retrieved = behavior, [], []
        self.messages = SimpleNamespace(create=self._create)
        self.models = SimpleNamespace(retrieve=self._retrieve)

    async def _create(self, **kw):
        self.calls.append(kw)
        out = self.behavior()
        if isinstance(out, BaseException):
            raise out
        if out == "hang":
            await asyncio.sleep(10)
        return out

    async def _retrieve(self, model_id, **kw):
        self.retrieved.append((model_id, kw))
        out = self.behavior()
        if isinstance(out, BaseException):
            raise out
        return SimpleNamespace(id=model_id)

    async def close(self):
        pass


@contextmanager
def claude_client(behavior, timeout: str = "3", **extra_env):
    """Claude provider with a fake client, a fake key and a fresh temp ledger."""
    fake = _FakeClaude(behavior)
    env = {"HANDOVER_CHECK_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test-not-real",
           "HANDOVER_CHECK_TIMEOUT": timeout,
           "HANDOVER_CLAUDE_SPEND_FILE": str(_TMP / f"spend-{next(_ledger_ids)}.json"), **extra_env}
    saved_env = {k: os.environ.get(k) for k in env}
    saved_get = check._get_claude
    os.environ.update(env)
    check._get_claude = lambda: fake
    try:
        yield fake
    finally:
        check._get_claude = saved_get
        for k, v in saved_env.items():
            _restore(k, v)


def test_provider_selection():
    saved = {k: os.environ.get(k) for k in ("HANDOVER_CHECK_PROVIDER", "ANTHROPIC_API_KEY")}
    saved_read = check._read_env_file
    try:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        check._read_env_file = lambda: {}
        os.environ["HANDOVER_CHECK_PROVIDER"] = "auto"
        assert check.provider() == "gemini"  # no Claude key anywhere
        check._read_env_file = lambda: {"ANTHROPIC_API_KEY": "sk-ant-from-dotenv"}
        assert check.provider() == "claude"  # .env counts
        assert check.active_model() == "claude-haiku-5-5"
        check._read_env_file = lambda: {}
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-from-env"
        assert check.provider() == "claude" and check.has_key()
        os.environ["HANDOVER_CHECK_PROVIDER"] = "gemini"  # explicit choice wins over the key
        assert check.provider() == "gemini"
        os.environ["HANDOVER_CHECK_PROVIDER"] = "CLAUDE"
        os.environ.pop("ANTHROPIC_API_KEY")
        assert check.provider() == "claude" and not check.has_key()
        r = _run(check_frame(b"x", b"y", "q"))
        assert r.error == "no_key"  # claude chosen but no key: fail fast, no client built
    finally:
        check._read_env_file = saved_read
        for k, v in saved.items():
            _restore(k, v)


def _jpeg_sized(w: int, h: int, color=(10, 20, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


def _sent_size(block: dict) -> int:
    import base64
    return max(Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).size)


def test_claude_request_shape():
    img = _jpeg()
    with claude_client(lambda: _claude_msg(_answer("left flap open", "no", 0.86)), timeout="2.5") as fake:
        r = _run(check_frame(img, img, "Is the left flap folded?", prev_ref=img))
        led = spend.default_ledger().status()
    assert (r.done, r.confidence, r.reason, r.error) == ("no", 0.86, "left flap open", None)
    assert r.cost_usd == spend.cost("claude-haiku-5-5", {"input_tokens": 1200, "output_tokens": 40}) > 0
    assert led.day_calls == 1 and abs(led.day_usd - r.cost_usd) < 1e-12  # every call reaches the ledger
    kw = fake.calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["max_tokens"] == 256
    assert kw["thinking"] == {"type": "disabled"} and "stream" not in kw
    assert kw["output_config"]["effort"] == "low"
    fmt = kw["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert list(fmt["schema"]["properties"]) == ["differs", "done", "confidence"]  # lean, evidence first
    assert fmt["schema"]["required"] == ["differs", "done", "confidence"]
    assert fmt["schema"]["additionalProperties"] is False
    assert "4 words" in fmt["schema"]["properties"]["differs"]["description"]
    assert not {"temperature", "top_p", "top_k"} & set(kw), "sampling params are rejected on 2026-10-21"
    assert kw["timeout"] == 2.5  # the per-call timeout goes to the SDK
    # Fixed rules live in system, one text block.
    assert kw["system"] == [{"type": "text", "text": check.CLAUDE_SYSTEM}] and check.RULE in check.CLAUDE_SYSTEM
    content = kw["messages"][0]["content"]
    assert kw["messages"][0]["role"] == "user" and len(kw["messages"]) == 1  # no prefill
    kinds = [b["type"] if b["type"] != "text" else b["text"].split(":")[0] for b in content]
    assert kinds == ["IMAGE BEFORE", "image", "IMAGE DONE", "image", "Question", "IMAGE LIVE", "image",
                     check.CLAUDE_FINAL.split(":")[0]]
    q = content[4]
    assert q["text"] == "Question: Is the left flap folded?" and q["cache_control"] == {"type": "ephemeral"}
    assert [b for b in content if "cache_control" in b] == [q]  # one breakpoint, on the question
    images = [b for b in content if b["type"] == "image"]
    assert all(b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/jpeg" for b in images)


def test_claude_two_image_form_sizes_and_memo():
    step = _jpeg_sized(1600, 900, (1, 2, 3))
    live = _jpeg_sized(1600, 900, (200, 2, 3))
    with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9))) as fake:
        r1 = _run(check_frame(step, live, "q"))
        r2 = _run(check_frame(step, _jpeg_sized(1500, 900, (9, 9, 9)), "q"))
    assert r1.done == r2.done == "yes" and r1.reason is None
    c1, c2 = (call["messages"][0]["content"] for call in fake.calls)
    imgs1 = [b for b in c1 if b["type"] == "image"]
    assert len(imgs1) == 2  # DONE and LIVE, no BEFORE
    assert _sent_size(imgs1[0]) == 672 and _sent_size(imgs1[1]) == 640  # step 672 px, LIVE max side
    done1, done2 = c1[1], c2[1]
    assert done1 is done2  # memoized: byte-identical across calls, so the cache prefix matches
    assert "cache_control" not in done1  # a shared image dict never carries the breakpoint
    os.environ["HANDOVER_CHECK_MAX_SIDE"] = "560"
    try:
        with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9))) as fake:
            _run(check_frame(step, live, "q"))
    finally:
        del os.environ["HANDOVER_CHECK_MAX_SIDE"]
    imgs = [b for b in fake.calls[0]["messages"][0]["content"] if b["type"] == "image"]
    assert _sent_size(imgs[0]) == 672 and _sent_size(imgs[1]) == 560  # the env moves LIVE only


def test_claude_no_cache_switch():
    img = _jpeg()
    with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9)), HANDOVER_CLAUDE_CACHE="0") as fake:
        _run(check_frame(img, img, "q"))
    assert not [b for b in fake.calls[0]["messages"][0]["content"] if "cache_control" in b]


def test_claude_cache_read_tokens_reported():
    img = _jpeg()
    usage = SimpleNamespace(input_tokens=300, output_tokens=30, cache_read_input_tokens=900,
                            cache_creation_input_tokens=0, cache_creation=None)
    with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9), usage=usage)):
        r = _run(check_frame(img, img, "q"))
    assert r.cache_read_tokens == 900
    assert abs(r.cost_usd - spend.cost("claude-haiku-5-5", usage)) < 1e-12  # reads at 0.1x


def test_done_normalized_and_contradiction_guard():
    img = _jpeg()
    for raw, differs, want_done, want_reason in [
        (" Yes ", "nothing", "yes", None),
        ("NO", "flap open", "no", "flap open"),
        ("yes", "left flap still open", "unsure", "left flap still open"),  # says done, names a gap
    ]:
        text = json.dumps({"seen": "s", "differs": differs, "done": raw, "confidence": 0.9})
        with claude_client(lambda: _claude_msg(text)):
            r = _run(check_frame(img, img, "q"))
        assert (r.done, r.reason, r.error) == (want_done, want_reason, None), raw
        with fake_client(lambda: text):  # the guard is shared by both providers
            g = _run(check_frame(img, img, "q"))
        assert (g.done, g.reason) == (want_done, want_reason), raw


def test_claude_error_mapping():
    img = _jpeg()
    cases = [
        (lambda: _status_error(anthropic.AuthenticationError, 401), "no_key"),
        (lambda: _status_error(anthropic.PermissionDeniedError, 403), "no_key"),
        (lambda: _status_error(anthropic.RateLimitError, 429), "rate_limited"),
        (lambda: _status_error(anthropic.InternalServerError, 500), "error"),
        (lambda: _status_error(anthropic.InternalServerError, 529), "error"),
        (lambda: _status_error(anthropic.BadRequestError, 400), "error"),
        (lambda: _status_error(anthropic.NotFoundError, 404), "error"),
        (lambda: _status_error(anthropic.APIStatusError, 402), "error"),
        (lambda: anthropic.APITimeoutError(request=_REQ), "timeout"),
        (lambda: anthropic.APIConnectionError(request=_REQ), "error"),
        (lambda: RuntimeError("boom"), "error"),
        (lambda: _claude_msg("not json"), "error"),
    ]
    for behavior, want in cases:
        with claude_client(behavior):
            r = _run(check_frame(img, img, "q"))
            m = _run(compare_refs(img, [(0, img), (1, img)]))
        assert (r.done, r.confidence, r.reason, r.error) == ("unsure", 0.0, None, want), (want, r)
        assert (m.step, m.confidence, m.error) == (None, 0.0, want), (want, m)
    with claude_client(lambda: "hang", timeout="0.2"):
        t0 = time.monotonic()
        r = _run(check_frame(img, img, "q"))
        assert r.error == "timeout" and time.monotonic() - t0 < 2


def test_claude_refusal_and_truncation_are_errors_but_billed():
    img = _jpeg()
    for msg, why in [
        (_claude_msg("", stop="refusal", category="cyber"), "refusal"),
        (_claude_msg('{"seen": "a', stop="max_tokens"), "truncated"),
        (_claude_msg(content=[SimpleNamespace(type="thinking", thinking="")]), "no text"),
    ]:
        with claude_client(lambda: msg):
            r = _run(check_frame(img, img, "q"))
            led = spend.default_ledger().status()
        assert (r.done, r.error) == ("unsure", "error"), why
        assert r.cost_usd > 0 and led.day_calls == 1, why  # the tokens were billed, so they are counted


def test_claude_compare_labels():
    img = _jpeg()
    refs = [(3, img), (4, img), (5, img)]
    with claude_client(lambda: _claude_msg(json.dumps({"match": "B", "confidence": 0.8}))) as fake:
        m = _run(compare_refs(img, refs, "Fold the flap"))
    assert (m.step, m.confidence, m.error) == (4, 0.8, None) and m.cost_usd > 0
    kw = fake.calls[0]
    schema = kw["output_config"]["format"]["schema"]
    assert schema["properties"]["match"]["enum"] == ["A", "B", "C", "none"]
    assert schema["additionalProperties"] is False and kw["thinking"] == {"type": "disabled"}
    assert schema["required"] == ["seen", "match", "confidence"]  # evidence first
    texts = [b["text"] for b in kw["messages"][0]["content"] if b["type"] == "text"]
    assert texts[:4] == ["Reference A", "Reference B", "Reference C", "LIVE: the camera now"]
    assert "Fold the flap" not in " ".join(texts)  # question-neutral


def _spent_ledger(usd_target: float) -> None:
    """Fill the active temp ledger past usd_target with one big fake usage."""
    tokens = int(usd_target / 0.5 * 1_000_000) + 1_000  # haiku output tokens at $0.50 per MTok
    spend.default_ledger().record("claude-haiku-5-5", {"input_tokens": 0, "output_tokens": tokens})


def test_budget_day_cap_blocks_without_a_call():
    img = _jpeg()
    with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9)),
                       HANDOVER_CLAUDE_BUDGET_DAY_USD="0.01", HANDOVER_NO_NETWORK="0") as fake:
        assert _run(check_frame(img, img, "q")).error is None
        _spent_ledger(0.01)
        r = _run(check_frame(img, img, "q"))
        m = _run(compare_refs(img, [(0, img)]))
        warm = _run(check.warm_up())
    assert (r.done, r.confidence, r.error, r.latency_ms) == ("unsure", 0.0, "budget", 0)
    assert m.error == "budget" and warm is False
    assert len(fake.calls) == 1 and fake.retrieved == []  # nothing sent once the cap was hit


def test_budget_total_cap_blocks():
    img = _jpeg()
    with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9)),
                       HANDOVER_CLAUDE_BUDGET_TOTAL_USD="0.02") as fake:
        _spent_ledger(0.02)
        assert spend.default_ledger().status().blocked == "total"
        assert _run(check_frame(img, img, "q")).error == "budget"
    assert fake.calls == []


def test_gemini_ignores_the_claude_budget():
    img = _jpeg()
    os.environ["HANDOVER_CLAUDE_BUDGET_TOTAL_USD"] = "0"
    try:
        with fake_client(lambda: _answer("nothing", "yes", 0.9)):
            r = _run(check_frame(img, img, "q"))
    finally:
        del os.environ["HANDOVER_CLAUDE_BUDGET_TOTAL_USD"]
    assert r.error is None and r.cost_usd == 0.0


def test_breaker_budget_reason():
    budget = CheckResult("unsure", 0.0, 0, error="budget")
    b = Breaker(errors=3, open_seconds=30)
    b.record(budget, 0)
    assert b.offline and b.reason == "budget" and not b.allow(10)
    assert b.allow(30)  # trial: check_frame answers budget again without a request
    b.record(budget, 30)
    assert b.reason == "budget" and not b.allow(59)
    assert b.allow(60)
    b.record(CheckResult("no", 0.9, 400), 61)  # the date changed: a real answer closes it
    assert not b.offline and b.reason is None
    b.force_open("budget", now=100)
    assert b.reason == "budget"


def test_claude_warm_up():
    with claude_client(lambda: "ok", HANDOVER_NO_NETWORK="0") as fake:
        assert _run(check.warm_up(timeout=2)) is True
    assert fake.retrieved[0][0] == "claude-haiku-5-5" and fake.retrieved[0][1]["timeout"] == 2
    assert fake.calls == []  # metadata only, no billed message
    with claude_client(lambda: _status_error(anthropic.AuthenticationError, 401), HANDOVER_NO_NETWORK="0"):
        assert _run(check.warm_up()) is False


def test_claude_mock_mode_makes_no_call():
    os.environ["HANDOVER_CHECK"], os.environ["HANDOVER_MOCK_PASS_SECONDS"] = "mock", "0"
    try:
        with claude_client(lambda: _claude_msg(_answer("nothing"))) as fake:
            r = _run(check_frame(b"r", b"l", "q", step_started_at=time.monotonic() - 1))
            m = _run(compare_refs(b"l", [(0, b"a")]))
    finally:
        del os.environ["HANDOVER_CHECK"], os.environ["HANDOVER_MOCK_PASS_SECONDS"]
    assert r.done == "yes" and m.step is None and fake.calls == [] and r.cost_usd == 0


def test_redact_claude_keys():
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-api03-secretvalue"
    try:
        out = check._redact("auth failed for sk-ant-api03-secretvalue and sk-ant-other_key-123 ok")
    finally:
        _restore("ANTHROPIC_API_KEY", saved)
    assert "secretvalue" not in out and "other_key" not in out and out.count("***") == 2


def test_cli_refuses_when_budget_exhausted():
    ledger = _TMP / "cli-spend.json"
    spend.Ledger(ledger).record("claude-haiku-5-5", {"output_tokens": 1_000_000})  # $0.50
    env = {**os.environ, "HANDOVER_CHECK_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test-not-real",
           "HANDOVER_CLAUDE_SPEND_FILE": str(ledger), "HANDOVER_CLAUDE_BUDGET_DAY_USD": "0.10"}
    out = subprocess.run([sys.executable, "-m", "server.check", "--time", "a.jpg", "b.jpg", "q", "-n", "1"],
                         cwd=check.REPO, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "Refusing to run" in out.stdout and "sk-ant-test-not-real" not in out.stdout + out.stderr


def test_claude_thinking_per_model():
    img = _jpeg()
    seen = {}
    for model in ("claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5"):
        with claude_client(lambda: _claude_msg(_answer("nothing", "yes", 0.9)),
                           HANDOVER_CLAUDE_CHECK_MODEL=model) as fake:
            assert _run(check_frame(img, img, "q")).error is None
            _run(compare_refs(img, [(0, img)]))
        seen[model] = fake.calls
    for kw in seen["claude-haiku-5-5"]:
        assert kw["thinking"] == {"type": "disabled"} and kw["max_tokens"] == 256
    for model in ("claude-opus-5-5", "claude-sonnet-5-5"):  # disabled is a 400 there
        assert len(seen[model]) == 2
        for kw in seen[model]:
            assert "thinking" not in kw and kw["max_tokens"] == 1024, model
            assert kw["output_config"]["effort"] == "low" and kw["model"] == model
            assert not {"temperature", "top_p", "top_k"} & set(kw)


def test_no_network_switch():
    """HANDOVER_NO_NETWORK=1: warm_up is a no-op and real clients are never built."""
    assert os.environ.get("HANDOVER_NO_NETWORK") == "1" and check.no_network()
    with claude_client(lambda: "ok") as fake:
        assert _run(check.warm_up()) is False
    assert fake.retrieved == [] and fake.calls == []
    saved = {k: os.environ.get(k) for k in ("HANDOVER_CHECK_PROVIDER", "ANTHROPIC_API_KEY")}
    os.environ.update({"HANDOVER_CHECK_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test-not-real"})
    check._get_claude = _real_get_claude  # the real builder must refuse under the switch
    try:
        r = _run(check_frame(_jpeg(), _jpeg(), "q"))
    finally:
        check._get_claude = _no_real_claude
        for k, v in saved.items():
            _restore(k, v)
        check._clients.clear()
    assert r.error == "error" and r.cost_usd == 0  # nothing was sent


def test_httpx2_timeout_is_timeout():
    req = httpx2.Request("POST", "https://example.invalid")
    assert check.classify_error(httpx2.ReadTimeout("slow", request=req)) == "timeout"
    assert check.classify_error(httpx2.ConnectError("down", request=req)) == "error"


def test_sdk_load_is_outside_the_timeout():
    """A slow first SDK import must not turn a fast answer (here a 429) into a timeout."""
    img = _jpeg()
    real_load = check._load_sdk

    def slow_load(prov):
        time.sleep(0.5)
        real_load(prov)

    check._load_sdk = slow_load
    try:
        rate = genai_errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
        with fake_client(lambda: rate, timeout="0.3"):
            r = _run(check_frame(img, img, "q"))
    finally:
        check._load_sdk = real_load
    assert r.error == "rate_limited", r


# ---------------------------------------------------------------- latency defaults, neutral compare, bench

def test_claude_lean_form_is_default_and_full_still_parses():
    lean, full = check._claude_answer_schema(), check._claude_answer_schema("full")
    assert check.CLAUDE_FORM == "lean" and list(lean["properties"]) == ["differs", "done", "confidence"]
    assert list(full["properties"]) == ["seen", "differs", "done", "confidence"]
    assert check.CLAUDE_SYSTEM == check.CLAUDE_SYSTEMS["lean"] and '"seen"' not in check.CLAUDE_SYSTEM
    assert all(check.RULE in s for s in check.CLAUDE_SYSTEMS.values())
    assert '"seen"' in check.CLAUDE_SYSTEMS["full"]
    img = _jpeg()
    lean_text = json.dumps({"differs": "left flap open", "done": "no", "confidence": 0.9})
    with claude_client(lambda: _claude_msg(lean_text)) as fake:
        r = _run(check_frame(img, img, "q"))
    assert (r.done, r.reason, r.error) == ("no", "left flap open", None)
    assert fake.calls[0]["system"][0]["text"] == check.CLAUDE_SYSTEMS["lean"]
    contra = json.dumps({"differs": "flap open", "done": "yes", "confidence": 0.95})
    with claude_client(lambda: _claude_msg(contra)):
        assert _run(check_frame(img, img, "q")).done == "unsure"  # the guard still holds without seen


def test_compare_prompt_is_question_neutral():
    """The step question never reaches the compare prompt, on either provider."""
    img = _jpeg()
    refs = [(3, img), (4, img), (5, img)]
    secret = "Is the zebra-striped flap tucked under?"
    with fake_client(lambda: json.dumps({"seen": "s", "match": "A", "confidence": 0.9})) as models:
        _run(compare_refs(img, refs, secret))
        _run(compare_refs(img, refs, None))
    with_q, without_q = ([p.text for p in c.contents[0].parts if p.text] for c in models.calls)
    assert with_q == without_q and not any("zebra" in t for t in with_q)
    with claude_client(lambda: _claude_msg(json.dumps({"seen": "s", "match": "B", "confidence": 0.9}))) as fake:
        m1 = _run(compare_refs(img, refs, secret))
        m2 = _run(compare_refs(img, refs))
    assert m1.step == m2.step == 4
    t1, t2 = ([b["text"] for b in kw["messages"][0]["content"] if b["type"] == "text"] for kw in fake.calls)
    assert t1 == t2 and not any("zebra" in t for t in t1)
    prompt = t1[-1]
    assert "same physical state as LIVE" in prompt and "which side faces up" in prompt
    assert '"A"|"B"|"C"|"none"' in prompt and "Task step" not in prompt


def test_new_claude_refuses_offline():
    try:
        check._new_claude()
    except RuntimeError as e:
        assert "HANDOVER_NO_NETWORK" in str(e)
    else:
        raise AssertionError("built a real client under HANDOVER_NO_NETWORK=1")


def _bench_lesson(with_variants: bool) -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="bench-", dir=_TMP))
    (root / "frames").mkdir()
    steps = []
    for k, kind in ((1, "manual"), (2, "camera"), (3, "camera")):
        (root / "frames" / f"{k:02d}.jpg").write_bytes(_jpeg_sized(64, 48, (k * 40, 0, 0)))
        steps.append({"n": k, "check_type": kind, "check_question": f"question {k}", "ref_frame": f"frames/{k:02d}.jpg"})
    (root / "lesson.json").write_text(json.dumps({"steps": steps}))
    vdir = root / "variants"
    vdir.mkdir()
    if with_variants:
        for k in (1, 2, 3):
            for i in range(2):
                (vdir / f"state{k}_v{i:02d}.jpg").write_bytes(_jpeg_sized(1000, 600, (k * 40, i * 50, 9)))
    return root, vdir


def test_bench_probes_variants_and_fallback():
    root, vdir = _bench_lesson(True)
    probes, source = check.bench_probes(root, vdir, 2)
    assert [p.id for p in probes] == ["s2own0", "s2prev0", "s3own0", "s3prev0",
                                      "s2own1", "s2prev1", "s3own1", "s3prev1"]
    assert "held-out" in source
    by = {p.id: p for p in probes}
    assert by["s3own1"].live == (vdir / "state3_v01.jpg").read_bytes() and by["s3own1"].expect == "yes"
    assert by["s3prev1"].live == (vdir / "state2_v01.jpg").read_bytes() and by["s3prev1"].expect == "no"
    assert by["s3prev1"].prev == (root / "frames" / "02.jpg").read_bytes() and by["s3prev1"].question == "question 3"
    empty_root, empty_v = _bench_lesson(False)
    probes, source = check.bench_probes(empty_root, empty_v, 3)
    assert len(probes) == 4 and "reference frames" in source  # one round from the lesson's own frames


class _FakeStream:
    def __init__(self, msg):
        self.msg = msg

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def events():
            yield SimpleNamespace(type="message_start")
            yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="{"))
        return events()

    async def get_final_message(self):
        return self.msg


def test_run_bench_interleaves_arms_offline():
    root, vdir = _bench_lesson(True)
    probes, _ = check.bench_probes(root, vdir, 1)
    yes = lambda: _claude_msg(json.dumps({"differs": "nothing", "done": "yes", "confidence": 0.9}))  # noqa: E731
    cold = _FakeClaude(yes)
    built = []
    saved_new = check._new_claude
    check._new_claude = lambda: built.append(1) or cold
    try:
        with claude_client(yes) as fake:
            fake.messages.stream = lambda **kw: fake.calls.append({**kw, "_stream": True}) or _FakeStream(yes())
            out = _run(check.run_bench(probes, check.BENCH_ARMS, max_usd=1.0, pairs=2))
    finally:
        check._new_claude = saved_new
    arms = check.BENCH_ARMS
    rs = out["results"]
    assert len(rs) == len(arms) * len(probes) and out["stopped"] is None
    assert [r["arm"] for r in rs[:len(arms)]] == [a.name for a in arms]  # probe 0: arms in order
    assert rs[len(arms)]["arm"] == arms[1].name  # probe 1: the order rotates
    assert all(not r.get("error") for r in rs + out["pairs"]) and len(out["pairs"]) == 4
    assert len(built) == len(cold.calls) == 1 + len(probes)  # cold arm: a new client every call
    assert all("first_ms" in r for r in rs if r["arm"] == "streamed")
    calls = fake.calls + cold.calls
    assert len(calls) == len(arms) * (len(probes) + 1) + 4  # warm-ups, timed calls, 2 pairs of 2
    full = [c for c in calls if list(c["output_config"]["format"]["schema"]["properties"])[0] == "seen"]
    assert len(full) == 1 + len(probes)  # only the full-schema arm sends seen
    nocache = [c for c in calls if not any("cache_control" in b for b in c["messages"][0]["content"])]
    assert len(nocache) == 1 + len(probes)
    sizes = [_sent_size([b for b in c["messages"][0]["content"] if b["type"] == "image"][-1]) for c in calls]
    assert sizes.count(512) == 1 + len(probes) and sizes.count(640) == len(calls) - sizes.count(512)  # LIVE side
    table = check.bench_table(rs, arms)
    assert len(table) == 2 + len(arms) and "| default | 4/4 |" in table[2]
    assert table[2].split(" | ")[6:8] == ["2/2", "2/2"]  # own yes, prev false pass (the fake always says yes)
    assert abs(out["spent"] - sum(r["usd"] for r in rs + out["pairs"]) - sum(  # warm-ups counted too
        spend.cost("claude-haiku-5-5", {"input_tokens": 1200, "output_tokens": 40}) for _ in arms)) < 1e-9


def test_run_bench_max_usd_is_a_hard_stop():
    root, vdir = _bench_lesson(True)
    probes, _ = check.bench_probes(root, vdir, 2)
    per_call = spend.cost("claude-haiku-5-5", {"input_tokens": 1200, "output_tokens": 40})
    with claude_client(lambda: _claude_msg(json.dumps({"differs": "x", "done": "no", "confidence": 0.9}))) as fake:
        out = _run(check.run_bench(probes, check.BENCH_ARMS[:2], max_usd=0.0025, pairs=4))
        none = _run(check.run_bench(probes, check.BENCH_ARMS[:2], max_usd=0.001, pairs=4))
    assert out["stopped"] and "max-usd" in out["stopped"]
    assert out["spent"] <= 0.0025 and len(fake.calls) * per_call <= 0.0025 + 1e-12
    assert none["results"] == [] and none["spent"] == 0  # below the first-call estimate: nothing sent


def test_cli_bench_offline_makes_no_paid_call():
    root, vdir = _bench_lesson(True)
    env = {**os.environ, "HANDOVER_CHECK_PROVIDER": "claude", "ANTHROPIC_API_KEY": "sk-ant-test-not-real",
           "HANDOVER_CLAUDE_SPEND_FILE": str(_TMP / "cli-bench.json"), "HANDOVER_NO_NETWORK": "1"}
    out = subprocess.run([sys.executable, "-m", "server.check", "--bench", "--lesson", str(root),
                          "--variants", str(vdir), "--max-usd", "0.01"],
                         cwd=check.REPO, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "| Arm |" in out.stdout and "| default | 0/4 |" in out.stdout and "spent $0.0000" in out.stdout
    assert "sk-ant-test-not-real" not in out.stdout + out.stderr


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

"""Vision check: does the live camera frame show the finished state of a step?

One Gemini call per frame, comparing the live frame with the step's reference
frame. Also holds the Debouncer (2 confident yes in a row advance a step) and a
Breaker (turns checks off after repeated failures), compare_refs (which of a
few step references the live frame matches, for the mistake check) and a small
timing tool:

    python -m server.check --time REF.jpg LIVE.jpg "question" -n 20
    python -m server.check --compare REF_A.jpg REF_B.jpg REF_C.jpg LIVE.jpg -n 5

Env:
    GEMINI_API_KEY / GOOGLE_API_KEY  key (or repo-root .env). Never printed.
    HANDOVER_CHECK_MODEL             model id (default gemini-3.5-flash-lite)
    HANDOVER_CHECK=mock              no network; pass after N seconds on a step
    HANDOVER_MOCK_PASS_SECONDS       N for mock mode (default 6)
    HANDOVER_CHECK_TIMEOUT           seconds before a call counts as unsure (default 3)
    HANDOVER_DEBOUNCE_N              consecutive yes needed (default 2)
    HANDOVER_MIN_CONF                minimum confidence for a yes (default 0.8)
    HANDOVER_BREAKER_SECONDS         seconds the breaker stays open (default 30)
    HANDOVER_CHECK_LIVE_RES          low or medium media resolution for the live image (default low)
    HANDOVER_CHECK_MAX_SIDE          long side in pixels images are shrunk to before sending (default 640)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import re
import statistics
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from server import config

log = logging.getLogger("handover.check")

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_SIDE = 640  # default; HANDOVER_CHECK_MAX_SIDE overrides per call
KEEPALIVE_SECONDS = 120

Done = Literal["yes", "no", "unsure"]
CheckError = Literal["timeout", "rate_limited", "error", "no_key"]
OfflineReason = Literal["no_key", "rate_limited", "errors"]
REASON_MAX_WORDS = 8
SEEN_MAX_WORDS = 12


@dataclass
class CheckResult:
    done: Done
    confidence: float
    latency_ms: int
    reason: Optional[str] = None
    """Up to 8 words on what differs from the reference, shown to the learner."""
    error: Optional[CheckError] = None
    """Why the call failed (None on success). Feeds the Breaker; not sent to the UI."""

    def as_dict(self) -> dict:
        return {
            "done": self.done,
            "confidence": round(self.confidence, 3),
            "latency_ms": self.latency_ms,
            "reason": self.reason,
        }


@dataclass
class MatchResult:
    """Which reference the live frame matches best. step None means none of them (or a failure)."""

    step: Optional[int]
    confidence: float
    latency_ms: int
    error: Optional[CheckError] = None

    def as_dict(self) -> dict:
        return {"step": self.step, "confidence": round(self.confidence, 3), "latency_ms": self.latency_ms}


class _Answer(BaseModel):
    """Flat schema the model must answer with."""

    # Evidence first: the model describes LIVE and names the gap before it commits to done,
    # so the verdict rests on what it wrote. Field order is the order the model fills them.
    # Text fields are plain non-nullable strings (most reliable shape for structured output)
    # with defaults so a missing field still parses. The docstring above is sent to the model
    # as the schema description, so keep it short.

    seen: str = Field(default="", description="At most 12 words on LIVE: outline shape, orientation, visible parts")
    differs: str = Field(default="", description='At most 8 words on what LIVE lacks compared with DONE, or "nothing"')
    done: Literal["yes", "no", "unsure"] = Field(description="yes, no, or unsure")
    confidence: float = Field(ge=0, le=1, description="0 to 1")


def _answer_schema() -> dict:
    """All four fields required in the schema so the model always writes its evidence."""
    schema = _Answer.model_json_schema()
    schema["required"] = ["seen", "differs", "done", "confidence"]
    return schema


def trim_reason(text: Optional[str], max_words: int = REASON_MAX_WORDS) -> Optional[str]:
    """Keep the badge short even when the model ignores the word limit. Empty becomes None."""
    if not text:
        return None
    words = text.replace("\n", " ").split()
    if not words:
        return None
    out = " ".join(words[:max_words]).strip()
    return out.rstrip(".,;:") or None


def differs_to_reason(text: Optional[str]) -> Optional[str]:
    """The model writes "nothing" when LIVE matches DONE; the UI wants None then."""
    out = trim_reason(text)
    return None if out is None or out.lower() in ("nothing", "none", "n/a") else out


def is_mock() -> bool:
    return config.get("HANDOVER_CHECK") == "mock"


# ---------------------------------------------------------------- key / client

def _read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    path = REPO / ".env"
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export ").strip()
        out[k] = v.strip().strip('"').strip("'")
    return out


def _api_key() -> Optional[str]:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    env = _read_env_file()
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if env.get(name):
            return env[name]
    return None


# One client per event loop: the SDK's async connection pool belongs to the loop that first
# used it, and teach's self-test runs asyncio.run in a worker thread inside the hub process.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, object]" = weakref.WeakKeyDictionary()
_closers: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, object]" = weakref.WeakKeyDictionary()
_clients_lock = threading.Lock()


async def _close_at_loop_end(client):
    """Async generator the loop finalizes in shutdown_asyncgens (asyncio.run does this before
    closing). Closing the client there, while its loop still runs, stops the SDK's __del__
    from later trying to close these sockets on a dead loop and logging an error."""
    try:
        yield
    finally:
        try:
            await client.aio.aclose()
        except Exception as e:  # cleanup only; never fail a shutdown
            log.debug("client close failed: %s", type(e).__name__)


def _has_client() -> bool:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    with _clients_lock:
        return loop in _clients


def _pool_args() -> dict:
    """Keep idle connections for 120 s. httpx drops them after 5 s by default, and checks are
    often about 6 s apart, so every call would pay a fresh TLS handshake. The Limits object
    also tells the SDK which backend to use (httpx2 if installed, else httpx). Note: if aiohttp
    were installed the SDK would use it for async calls and these limits would not apply."""
    try:
        import httpx2 as httpx_mod
    except ImportError:
        import httpx as httpx_mod  # type: ignore[no-redef]
    return {"limits": httpx_mod.Limits(max_keepalive_connections=4, keepalive_expiry=KEEPALIVE_SECONDS)}


def _get_client():
    """Client for the running loop, built on first use and reused for the life of that loop.

    No retry_options on purpose: in google-genai 3.3, HttpOptions without retry_options makes
    one attempt (retry_args(None) stops after 1), while any HttpRetryOptions retries 429 up to
    5 times. A retried 429 would stall a frame and hide quota from the Breaker.
    """
    from google import genai
    from google.genai import types

    loop = asyncio.get_running_loop()
    with _clients_lock:
        # The client holds its loop, so weak keys alone never free it: drop closed loops by hand.
        for old in [lp for lp in _clients if lp.is_closed()]:
            del _clients[old]
            _closers.pop(old, None)
        client = _clients.get(loop)
        if client is None:
            key = _api_key()
            if not key:
                raise RuntimeError("no Gemini key: set GEMINI_API_KEY or add it to .env")
            client = genai.Client(
                api_key=key, http_options=types.HttpOptions(api_version="v1beta", async_client_args=_pool_args())
            )
            _clients[loop] = client
            closer = _close_at_loop_end(client)
            _closers[loop] = closer  # the loop only holds async generators weakly
            loop.create_task(closer.__anext__())  # first step registers it with this loop
        return client


def _redact(text: str) -> str:
    """Strip the key from anything we log, in case an exception message ever echoes it."""
    key = _api_key()
    return text.replace(key, "***") if key else text


def classify_error(e: BaseException) -> CheckError:
    """Map an exception to the Breaker's classes. 429 / RESOURCE_EXHAUSTED means quota, so back off at once;
    an invalid or unauthorized key counts as no_key."""
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    try:
        from google.genai import errors as genai_errors

        if isinstance(e, genai_errors.APIError):
            if e.code == 429 or (e.status or "").upper() == "RESOURCE_EXHAUSTED":
                return "rate_limited"
            # A bad or unauthorized key will never start working mid-session: report it as
            # no_key so the badge tells the truth and the breaker opens on the first call.
            if e.code in (401, 403) or (e.code == 400 and "API_KEY_INVALID" in str(e.details)):
                return "no_key"
            return "error"
    except ImportError:  # SDK missing: fall through to generic error
        pass
    try:
        import httpx

        if isinstance(e, httpx.TimeoutException):
            return "timeout"
    except ImportError:
        pass
    return "error"


def _no_key() -> bool:
    """True when this loop has no client yet and no key is configured: fail fast, no network call."""
    return not _has_client() and not _api_key()


# ---------------------------------------------------------------- images

def _max_side() -> int:
    """Read per call so the eval script can try 512 without a restart of anything else."""
    return int(config.get("HANDOVER_CHECK_MAX_SIDE"))  # type: ignore[arg-type]


def downscale_jpeg(data: bytes, max_side: Optional[int] = None, quality: int = 80) -> bytes:
    """Return a JPEG whose long side is at most max_side (None: HANDOVER_CHECK_MAX_SIDE or 640).
    Small images pass through."""
    from PIL import Image

    if max_side is None:
        max_side = _max_side()

    with Image.open(io.BytesIO(data)) as im:
        if max(im.size) <= max_side and im.format == "JPEG":
            return data
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


# ---------------------------------------------------------------- mock

_mock_ref_hash: Optional[str] = None
_mock_ref_since = 0.0


async def _mock_check(ref_jpeg: bytes, step_started_at: Optional[float]) -> CheckResult:
    """Pass once the step has been active long enough. step_started_at is time.monotonic()."""
    global _mock_ref_hash, _mock_ref_since
    t0 = time.monotonic()
    if step_started_at is None:
        # Fall back to tracking when the reference image last changed.
        h = hashlib.sha1(ref_jpeg).hexdigest()
        if h != _mock_ref_hash:
            _mock_ref_hash, _mock_ref_since = h, t0
        step_started_at = _mock_ref_since
    await asyncio.sleep(0.6)
    need = float(config.get("HANDOVER_MOCK_PASS_SECONDS"))  # type: ignore[arg-type]
    passed = time.monotonic() - step_started_at >= need
    ms = int((time.monotonic() - t0) * 1000)
    return CheckResult("yes", 0.9, ms) if passed else CheckResult("no", 0.85, ms)


# ---------------------------------------------------------------- real check

RULE = (
    "Answer yes only if every feature in the question is visible in LIVE. "
    "If any feature is missing or hidden answer no or unsure. "
    "Hands, shadows, background, rotation and scale do not matter."
)

PROMPT = (
    "Question: {question}\n\n"
    "{rule}{before}\n"
    'First write "seen": at most 12 words on LIVE (outline shape, orientation, visible parts). '
    'Then "differs": at most 8 words on what LIVE lacks compared with DONE, or "nothing". '
    'Then "done": yes, no, or unsure (unsure if the object is not visible or blurred), '
    'and "confidence" from 0 to 1.'
)

BEFORE_RULE = " If LIVE looks like IMAGE A (before this step), answer no."


def _thinking(model: str):
    """Fastest thinking level each model accepts: 3.8 and 4 models reject MINIMAL, so they get LOW.
    Never set thinking_budget alongside thinking_level."""
    from google.genai import types

    level = types.ThinkingLevel.LOW if _thinks_low(model) else types.ThinkingLevel.MINIMAL
    return types.ThinkingConfig(thinking_level=level)


def _thinks_low(model: str) -> bool:
    return bool(re.match(r"gemini-(3\.8|4)\b", model.removeprefix("models/")))


def _max_tokens(model: str) -> int:
    """LOW thinking spends output tokens on thoughts; 256 could cut the JSON off mid-answer."""
    return 1024 if _thinks_low(model) else 256


def _live_res():
    """Per-part resolution for the LIVE image; medium can help small details at some latency cost."""
    from google.genai import types

    if config.get("HANDOVER_CHECK_LIVE_RES") == "medium":
        return types.PartMediaResolutionLevel.MEDIA_RESOLUTION_MEDIUM
    return types.PartMediaResolutionLevel.MEDIA_RESOLUTION_LOW


def _config(schema: dict, model: str):
    """Shared request settings: JSON out, low media resolution and the lowest thinking level keep
    latency down. No temperature: it is deprecated and ignored on Gemini 3.x."""
    from google.genai import types

    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        thinking_config=_thinking(model),
        max_output_tokens=_max_tokens(model),
    )


def _model() -> str:
    return str(config.get("HANDOVER_CHECK_MODEL") or DEFAULT_MODEL)


def _timeout(override: Optional[float] = None) -> float:
    """Per-call override first, so a slow caller (teach's self-test) never changes the env
    for live checks running in the same process."""
    if override is not None and override > 0:
        return override
    return float(config.get("HANDOVER_CHECK_TIMEOUT"))  # type: ignore[arg-type]


async def _gemini_check(
    ref_jpeg: bytes, live_jpeg: bytes, question: str, prev_ref: Optional[bytes] = None
) -> tuple[Done, float, Optional[str]]:
    from google.genai import types

    srcs = [prev_ref, ref_jpeg, live_jpeg] if prev_ref is not None else [ref_jpeg, live_jpeg]
    imgs = await asyncio.gather(*(asyncio.to_thread(downscale_jpeg, b) for b in srcs))
    labels = ["IMAGE A: DONE, the finished step", "IMAGE B: LIVE camera"]
    if prev_ref is not None:
        labels = [
            "IMAGE A: the object BEFORE this step (answer no if LIVE looks like this)",
            "IMAGE B: DONE, the finished step",
            "IMAGE C: LIVE camera",
        ]
    parts = []
    for i, (label, img) in enumerate(zip(labels, imgs)):
        res = _live_res() if i == len(imgs) - 1 else None
        parts += [types.Part.from_text(text=label), types.Part.from_bytes(data=img, mime_type="image/jpeg", media_resolution=res)]
    before = BEFORE_RULE if prev_ref is not None else ""
    parts.append(types.Part.from_text(text=PROMPT.format(question=question.strip(), rule=RULE, before=before)))
    model = _model()
    resp = await _get_client().aio.models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)], config=_config(_answer_schema(), model)
    )
    ans = _Answer.model_validate(json.loads(resp.text or ""))
    log.debug("check seen: %s", trim_reason(ans.seen, SEEN_MAX_WORDS))
    return ans.done, float(ans.confidence), differs_to_reason(ans.differs)


async def check_frame(
    ref_jpeg: bytes,
    live_jpeg: bytes,
    question: str,
    *,
    step_started_at: Optional[float] = None,
    prev_ref: Optional[bytes] = None,
    timeout: Optional[float] = None,
) -> CheckResult:
    """Never raises. Any failure gives unsure with confidence 0 and an error class for the Breaker.

    prev_ref is the previous step's reference: shown as a "before" example so the model says
    no when nothing has changed yet. Ignored in mock mode. timeout overrides
    HANDOVER_CHECK_TIMEOUT for this call only.
    """
    if is_mock():
        return await _mock_check(ref_jpeg, step_started_at)
    if _no_key():
        return CheckResult("unsure", 0.0, 0, error="no_key")
    t0 = time.monotonic()
    err: Optional[CheckError] = None
    reason: Optional[str] = None
    secs = 0.0
    try:
        secs = _timeout(timeout)
        done, conf, reason = await asyncio.wait_for(_gemini_check(ref_jpeg, live_jpeg, question, prev_ref), secs)
    except Exception as e:  # timeout, network, quota, bad JSON, bad image
        err = classify_error(e)
        _log_failure("check", err, e, secs)
        done, conf, reason = "unsure", 0.0, None
    return CheckResult(done, max(0.0, min(1.0, conf)), int((time.monotonic() - t0) * 1000), reason, err)


def _log_failure(what: str, err: CheckError, e: BaseException, timeout: float) -> None:
    if err == "timeout":
        log.warning("%s timed out after %.1fs", what, timeout)
    else:
        log.warning("%s failed (%s): %s: %s", what, err, type(e).__name__, _redact(str(e))[:300])


# ---------------------------------------------------------------- compare (mistake check)

LABELS = "ABCDEFGH"

COMPARE_PROMPT = (
    "{context}"
    "Images {labels} are reference photos of finished steps of one task. The last image is the live camera now. "
    "Which labeled reference shows the same state as the live image? "
    "Ignore differences in background, lighting, hands, and camera angle. "
    'Answer "none" if the object is not visible or matches none of them. '
    'Reply as JSON: {{"match": {choices}, "confidence": 0 to 1}}.'
)


def _compare_schema(labels: list[str]) -> dict:
    """Flat schema with the allowed labels as an enum, so the answer always maps back to a step."""
    return {
        "type": "object",
        "properties": {
            "match": {"type": "string", "enum": [*labels, "none"], "description": "label of the best match, or none"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "0 to 1"},
        },
        "required": ["match", "confidence"],
    }


def parse_match(text: str, refs: list[tuple[int, bytes]]) -> tuple[Optional[int], float]:
    """Map the model's label (A, B, C...) back to the step index it stands for."""
    data = json.loads(text or "")
    label = str(data.get("match", "none")).strip().upper()
    conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    idx = LABELS.find(label) if len(label) == 1 else -1
    if idx < 0 or idx >= len(refs):
        return None, conf
    return refs[idx][0], conf


async def _gemini_compare(live_jpeg: bytes, refs: list[tuple[int, bytes]], question: Optional[str]) -> tuple[Optional[int], float]:
    from google.genai import types

    labels = list(LABELS[: len(refs)])
    images = await asyncio.gather(
        *(asyncio.to_thread(downscale_jpeg, b) for _, b in refs), asyncio.to_thread(downscale_jpeg, live_jpeg)
    )
    parts = []
    for label, img in zip(labels, images[:-1]):
        parts += [types.Part.from_text(text=f"Reference {label}"), types.Part.from_bytes(data=img, mime_type="image/jpeg")]
    parts += [types.Part.from_text(text="Live camera now"), types.Part.from_bytes(data=images[-1], mime_type="image/jpeg")]
    context = f"Task step: {question.strip()}\n\n" if question and question.strip() else ""
    choices = "|".join(f'"{x}"' for x in [*labels, "none"])
    parts.append(
        types.Part.from_text(text=COMPARE_PROMPT.format(context=context, labels=", ".join(labels), choices=choices))
    )
    model = _model()
    resp = await _get_client().aio.models.generate_content(
        model=model, contents=[types.Content(role="user", parts=parts)], config=_config(_compare_schema(labels), model)
    )
    return parse_match(resp.text or "", refs)


async def compare_refs(
    live_jpeg: bytes,
    refs: list[tuple[int, bytes]],
    question: Optional[str] = None,
    *,
    timeout: Optional[float] = None,
) -> MatchResult:
    """One multiple-choice call: which of refs (step index, jpeg) does the live frame match? Never raises.

    Mock mode returns no match; the mock mistake path lives in mistake.py. timeout overrides
    HANDOVER_CHECK_TIMEOUT for this call only.
    """
    if is_mock() or not refs:
        return MatchResult(None, 0.0, 0)
    if len(refs) > len(LABELS):
        raise ValueError(f"compare_refs takes at most {len(LABELS)} references")
    if _no_key():
        return MatchResult(None, 0.0, 0, error="no_key")
    t0 = time.monotonic()
    err: Optional[CheckError] = None
    secs = 0.0
    try:
        secs = _timeout(timeout)
        step, conf = await asyncio.wait_for(_gemini_compare(live_jpeg, refs, question), secs)
    except Exception as e:
        err = classify_error(e)
        _log_failure("compare", err, e, secs)
        step, conf = None, 0.0
    return MatchResult(step, conf, int((time.monotonic() - t0) * 1000), err)


# ---------------------------------------------------------------- breaker

class Breaker:
    """Stops Gemini calls after repeated failures so a dead network or spent quota does not
    stall the learner; they use Next while it is open.

    3 consecutive timeouts or errors, or any rate limit, open it for open_seconds. Then
    allow() returns True exactly once for a trial call; that call's result closes it
    (success) or opens it again (failure). A missing key opens it for good.
    Pure: the caller passes the time, so tests use a fake clock.
    """

    def __init__(self, errors: int = 3, open_seconds: Optional[float] = None):
        self.errors = errors
        self.open_seconds = (
            open_seconds if open_seconds is not None else float(config.get("HANDOVER_BREAKER_SECONDS"))  # type: ignore[arg-type]
        )
        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._reason: Optional[OfflineReason] = None
        self._opened_at = 0.0
        self._fails = 0

    @property
    def offline(self) -> bool:
        """True while open or waiting on the trial call."""
        return self._state != "closed"

    @property
    def reason(self) -> Optional[OfflineReason]:
        return self._reason if self.offline else None

    def allow(self, now: float) -> bool:
        if self._state == "closed":
            return True
        if self._state == "half_open" or self._reason == "no_key":
            return False
        if now - self._opened_at >= self.open_seconds:
            self._state = "half_open"
            return True
        return False

    def force_open(self, reason: OfflineReason, now: Optional[float] = None) -> None:
        """Open without waiting for failures, e.g. no_key at startup. no_key stays open for good;
        other reasons need now so the trial call comes open_seconds later."""
        if reason != "no_key" and now is None:
            raise ValueError("force_open needs now for reasons other than no_key")
        self._open(reason, now if now is not None else 0.0)

    def record(self, result: "CheckResult | MatchResult", now: float) -> None:
        err = result.error
        if self._reason == "no_key" and self.offline:
            return  # only a restart with a key fixes this
        if err is None:
            self._close()
        elif err == "no_key":
            self._open("no_key", now)
        elif err == "rate_limited":
            self._open("rate_limited", now)
        elif self._state == "half_open":
            self._open("errors", now)  # trial failed
        elif self._state == "closed":
            self._fails += 1
            if self._fails >= self.errors:
                self._open("errors", now)
        # timeout or error from a call started before it opened: keep the current window

    def _open(self, reason: OfflineReason, now: float) -> None:
        self._state, self._reason, self._opened_at, self._fails = "open", reason, now, 0

    def _close(self) -> None:
        self._state, self._reason, self._fails = "closed", None, 0


# ---------------------------------------------------------------- debouncer

class Debouncer:
    """Advance after n consecutive yes answers with confidence >= min_conf.

    Any no, unsure, or low-confidence yes resets the count.
    """

    def __init__(self, n: Optional[int] = None, min_conf: Optional[float] = None):
        self.n = n if n is not None else int(config.get("HANDOVER_DEBOUNCE_N"))  # type: ignore[arg-type]
        self.min_conf = min_conf if min_conf is not None else float(config.get("HANDOVER_MIN_CONF"))  # type: ignore[arg-type]
        self.count = 0

    def feed(self, done: str, confidence: float) -> bool:
        """Record one result. Returns True when the step should advance (and resets)."""
        if done == "yes" and confidence >= self.min_conf:
            self.count += 1
        else:
            self.count = 0
        if self.count >= self.n:
            self.count = 0
            return True
        return False

    def reset(self) -> None:
        self.count = 0


# ---------------------------------------------------------------- timing tool

def _percentile(sorted_vals: list[int], q: float) -> int:
    return sorted_vals[min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1))))]


MAX_FAIL_SHARE = 0.1  # more failures than this and the latency numbers say nothing about the gate


def _failures(errors: list[Optional[CheckError]]) -> str:
    counts = {k: errors.count(k) for k in ("timeout", "rate_limited", "error", "no_key") if errors.count(k)}
    return ", ".join(f"{k} {v}" for k, v in counts.items()) or "none"


def summarize(latencies: list[int], errors: list[Optional[CheckError]]) -> str:
    """One stats line. p50, p90 and max cover successful calls only: a 3 s timeout or a fast
    auth error is not a latency. Failures are listed separately by class."""
    ok = sorted(lat for lat, e in zip(latencies, errors) if e is None)
    head = f"ok {len(ok)}/{len(errors)}"
    if not ok:
        return f"{head}  no successful calls  failures: {_failures(errors)}"
    return (
        f"{head}  p50 {statistics.median(ok):.0f} ms  p90 {_percentile(ok, 0.9)} ms  max {ok[-1]} ms"
        f"  failures: {_failures(errors)}"
    )


def gate_verdict(latencies: list[int], errors: list[Optional[CheckError]]) -> str:
    """The 6 PM Gemini gate from docs/PLAN.md, on the median of successful calls. A run with
    more than 10% failures never passes: the failures are the finding, not the latency."""
    ok = [lat for lat, e in zip(latencies, errors) if e is None]
    failed = len(errors) - len(ok)
    if not ok:
        return f"verdict: NOT MEASURED, no successful calls ({_failures(errors)}); fix the errors first"
    if failed / len(errors) > MAX_FAIL_SHARE:
        return (
            f"verdict: UNRELIABLE, {failed} of {len(errors)} calls failed ({_failures(errors)}); "
            "fix the failures and run again before deciding the gate"
        )
    median_s = statistics.median(ok) / 1000
    if median_s <= 2.0:
        v = f"PASS (median {median_s:.2f} s <= 2.0 s): keep the motion gate as is"
    elif median_s <= 2.5:
        v = f"WIDEN GATE (median {median_s:.2f} s in 2.0 to 2.5 s): widen the motion gate"
    else:
        v = f"SLOW (median {median_s:.2f} s > 2.5 s): one confident yes plus Next"
    if failed:
        v += f"; {failed} of {len(errors)} calls failed ({_failures(errors)})"
    return "verdict: " + v


def _mode() -> str:
    return "mock" if is_mock() else _model()


async def time_checks(ref: Path, live: Path, question: str, n: int = 20) -> list[CheckResult]:
    ref_b, live_b = ref.read_bytes(), live.read_bytes()
    started = time.monotonic()
    results = []
    for i in range(n):
        r = await check_frame(ref_b, live_b, question, step_started_at=started)
        results.append(r)
        tail = f"  {r.error}" if r.error else (f"  {r.reason}" if r.reason else "")
        print(f"{i + 1:3d}  {r.done:6s}  conf {r.confidence:.2f}  {r.latency_ms} ms{tail}", flush=True)
    lat, errs = [r.latency_ms for r in results], [r.error for r in results]
    print(f"model {_mode()}  {summarize(lat, errs)}")
    print(gate_verdict(lat, errs))
    return results


async def time_compares(refs: list[Path], live: Path, n: int = 5) -> list[MatchResult]:
    ref_list = [(i, p.read_bytes()) for i, p in enumerate(refs)]
    live_b = live.read_bytes()
    results = []
    for i in range(n):
        r = await compare_refs(live_b, ref_list)
        results.append(r)
        label = LABELS[r.step] if r.step is not None else "none"
        tail = f"  {r.error}" if r.error else ""
        print(f"{i + 1:3d}  match {label:4s}  conf {r.confidence:.2f}  {r.latency_ms} ms{tail}", flush=True)
    print(f"model {_mode()}  compare {len(refs)} refs  {summarize([r.latency_ms for r in results], [r.error for r in results])}")
    return results


def _main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server.check")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--time", nargs=3, metavar=("REF", "LIVE", "QUESTION"), help="time check_frame")
    g.add_argument("--compare", nargs="+", metavar="IMG", help="REF_A [REF_B ...] LIVE: time compare_refs")
    ap.add_argument("-n", type=int, default=None, help="calls (default 20 for --time, 5 for --compare)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    if a.time:
        ref, live, q = a.time
        asyncio.run(time_checks(Path(ref), Path(live), q, a.n or 20))
    else:
        if not 2 <= len(a.compare) <= len(LABELS) + 1:
            ap.error(f"--compare takes 1 to {len(LABELS)} references plus the live image")
        *refs, live = (Path(x) for x in a.compare)
        asyncio.run(time_compares(refs, live, a.n or 5))


if __name__ == "__main__":
    _main()

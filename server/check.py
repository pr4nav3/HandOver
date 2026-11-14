"""Vision check: does the live camera frame show the finished state of a step?

One model call per frame, comparing the live frame with the step's reference
frame. Two providers sit behind the same interface: Claude (default when a Claude
key is found, guarded by the spend ledger in server/spend.py) and Gemini. Also holds the Debouncer (2 confident yes in a row advance a step) and a
Breaker (turns checks off after repeated failures), compare_refs (which of a
few step references the live frame matches, for the mistake check) and a small
timing tool:

    python -m server.check --time REF.jpg LIVE.jpg "question" -n 20
    python -m server.check --compare REF_A.jpg REF_B.jpg REF_C.jpg LIVE.jpg -n 5

Env (all registered in server/config.py):
    ANTHROPIC_API_KEY                Claude key (or repo-root .env). Never printed.
    GEMINI_API_KEY / GOOGLE_API_KEY  Gemini key (or repo-root .env). Never printed.
    HANDOVER_CHECK_PROVIDER          auto (default), claude or gemini
    HANDOVER_CLAUDE_CHECK_MODEL      Claude model id (default claude-haiku-5-5)
    HANDOVER_CHECK_MODEL             Gemini model id (default gemini-3.5-flash-lite)
    HANDOVER_NO_NETWORK=1            tests: no real client is built and warm_up does nothing
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
import base64
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

from server import config, spend

log = logging.getLogger("handover.check")

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.5-flash-lite"
CLAUDE_DEFAULT_MODEL = "claude-haiku-5-5"
STEP_MAX_SIDE = 672  # Claude: reference images (cached), a little sharper than LIVE
CLAUDE_JPEG_QUALITY = 85
CLAUDE_MAX_TOKENS = 256  # Haiku 5.x: thinking is disabled, so the whole budget is the JSON answer
CLAUDE_THINKING_MAX_TOKENS = 1024  # other models think (adaptive, effort low): leave room for it
MAX_SIDE = 640  # default; HANDOVER_CHECK_MAX_SIDE overrides per call
KEEPALIVE_SECONDS = 120

Done = Literal["yes", "no", "unsure"]
CheckError = Literal["timeout", "rate_limited", "error", "no_key", "budget"]
OfflineReason = Literal["no_key", "rate_limited", "errors", "budget"]
Provider = Literal["claude", "gemini"]
REASON_MAX_WORDS = 8
SEEN_MAX_WORDS = 8


@dataclass
class CheckResult:
    done: Done
    confidence: float
    latency_ms: int
    reason: Optional[str] = None
    """Up to 8 words on what differs from the reference, shown to the learner."""
    error: Optional[CheckError] = None
    """Why the call failed (None on success). Feeds the Breaker; not sent to the UI."""
    cost_usd: float = 0.0
    """What this call cost (Claude only; Gemini and mock are 0). Not sent to the UI."""
    cache_read_tokens: int = 0
    """Claude prompt-cache hits for this call, for the timing tool. Not sent to the UI."""

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
    cost_usd: float = 0.0

    def as_dict(self) -> dict:
        return {"step": self.step, "confidence": round(self.confidence, 3), "latency_ms": self.latency_ms}


class _Answer(BaseModel):
    """Flat schema the model must answer with."""

    # Evidence first: the model describes LIVE and names the gap before it commits to done,
    # so the verdict rests on what it wrote. Field order is the order the model fills them.
    # Text fields are plain non-nullable strings (most reliable shape for structured output)
    # with defaults so a missing field still parses. The docstring above is sent to the model
    # as the schema description, so keep it short.

    seen: str = Field(default="", description="At most 8 words on LIVE: outline shape, orientation, visible parts")
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


def _find_key(*names: str) -> Optional[str]:
    """Environment first, then <repo>/.env."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    env = _read_env_file()
    for name in names:
        if env.get(name):
            return env[name]
    return None


def _api_key() -> Optional[str]:
    """Gemini key."""
    return _find_key("GEMINI_API_KEY", "GOOGLE_API_KEY")


def _anthropic_key() -> Optional[str]:
    return _find_key("ANTHROPIC_API_KEY")


def provider() -> Provider:
    """Which provider runs the live check. auto: Claude when a Claude key is found, else Gemini."""
    p = config.get("HANDOVER_CHECK_PROVIDER")
    if p in ("claude", "gemini"):
        return p  # type: ignore[return-value]
    return "claude" if _anthropic_key() else "gemini"


def _key_for(prov: Provider) -> Optional[str]:
    return _anthropic_key() if prov == "claude" else _api_key()


def _claude_model() -> str:
    return str(config.get("HANDOVER_CLAUDE_CHECK_MODEL") or CLAUDE_DEFAULT_MODEL)


def active_model() -> str:
    """Model id of the active provider, for logs and the timing tool."""
    return _claude_model() if provider() == "claude" else _model()


# One client per event loop and provider: an SDK's async connection pool belongs to the loop
# that first used it, and teach's self-test runs asyncio.run in a worker thread inside the hub.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, object]]" = weakref.WeakKeyDictionary()
_closers: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, list]" = weakref.WeakKeyDictionary()
_clients_lock = threading.Lock()


async def _close_at_loop_end(client, close_of):
    """Async generator the loop finalizes in shutdown_asyncgens (asyncio.run does this before
    closing). Closing the client there, while its loop still runs, stops the SDK's __del__
    from later trying to close these sockets on a dead loop and logging an error."""
    try:
        yield
    finally:
        try:
            await close_of(client)()
        except Exception as e:  # cleanup only; never fail a shutdown
            log.debug("client close failed: %s", type(e).__name__)


def _has_client(prov: Optional[Provider] = None) -> bool:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    with _clients_lock:
        return (prov or provider()) in _clients.get(loop, {})


def _loop_client(prov: Provider, build, close_of):
    """Shared per-loop cache: build() makes the client, close_of(client) its async close."""
    loop = asyncio.get_running_loop()
    with _clients_lock:
        # A client holds its loop, so weak keys alone never free it: drop closed loops by hand.
        for old in [lp for lp in _clients if lp.is_closed()]:
            del _clients[old]
            _closers.pop(old, None)
        per_loop = _clients.setdefault(loop, {})
        client = per_loop.get(prov)
        if client is None:
            client = build()
            per_loop[prov] = client
            closer = _close_at_loop_end(client, close_of)
            _closers.setdefault(loop, []).append(closer)  # the loop only holds async generators weakly
            loop.create_task(closer.__anext__())  # first step registers it with this loop
        return client


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

    def build():
        if no_network():
            raise RuntimeError("HANDOVER_NO_NETWORK=1: not building a real Gemini client")
        key = _api_key()
        if not key:
            raise RuntimeError("no Gemini key: set GEMINI_API_KEY or add it to .env")
        return genai.Client(
            api_key=key, http_options=types.HttpOptions(api_version="v1beta", async_client_args=_pool_args())
        )

    return _loop_client("gemini", build, lambda c: c.aio.aclose)


def _get_claude():
    """AsyncAnthropic for the running loop, built once and reused.

    max_retries=0: the SDK retries 429 and 5xx twice by default, which would stall a frame
    and hide rate limits from the Breaker. Keep-alive 120 s for the same reason as Gemini;
    the SDK's own default client keeps idle connections only 5 s.
    """
    import anthropic
    import httpx2

    def build():
        if no_network():
            raise RuntimeError("HANDOVER_NO_NETWORK=1: not building a real Claude client")
        key = _anthropic_key()
        if not key:
            raise RuntimeError("no Claude key: set ANTHROPIC_API_KEY or add it to .env")
        http = anthropic.DefaultAsyncHttpxClient(
            limits=httpx2.Limits(max_connections=20, max_keepalive_connections=4, keepalive_expiry=KEEPALIVE_SECONDS)
        )
        return anthropic.AsyncAnthropic(api_key=key, max_retries=0, http_client=http)

    return _loop_client("claude", build, lambda c: c.close)


_KEY_PATTERNS = re.compile(r"sk-ant-[A-Za-z0-9_\-]+|AIza[0-9A-Za-z_\-]{20,}")


def _redact(text: str) -> str:
    """Strip keys from anything we log, in case an exception message ever echoes one."""
    for key in (_api_key(), _anthropic_key()):
        if key:
            text = text.replace(key, "***")
    return _KEY_PATTERNS.sub("***", text)


class _CheckFailure(Exception):
    """A response that arrived but cannot be used (refusal, truncation). cost_usd was spent."""

    def __init__(self, kind: CheckError, message: str, cost_usd: float = 0.0):
        super().__init__(message)
        self.kind, self.cost_usd = kind, cost_usd


def classify_error(e: BaseException) -> CheckError:
    """Map an exception to the Breaker's classes. 429 / RESOURCE_EXHAUSTED means quota, so back off at once;
    an invalid or unauthorized key counts as no_key."""
    if isinstance(e, _CheckFailure):
        return e.kind
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    try:
        import anthropic

        if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return "no_key"  # a bad key never starts working mid-session
        if isinstance(e, anthropic.RateLimitError):
            return "rate_limited"
        if isinstance(e, anthropic.APITimeoutError):  # subclass of APIConnectionError: check first
            return "timeout"
        if isinstance(e, anthropic.APIError):  # connection, 5xx, other statuses
            return "error"
    except ImportError:
        pass
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
    for mod in ("httpx2", "httpx"):  # both SDKs run on httpx2; httpx kept for older installs
        try:
            timeout_cls = __import__(mod).TimeoutException
        except (ImportError, AttributeError):
            continue
        if isinstance(e, timeout_cls):
            return "timeout"
    return "error"


_loaded: set[str] = set()


def _load_sdk(prov: Provider) -> None:
    """Import the provider SDK and Pillow before the timer starts. A cold first import on a
    busy Mac can take seconds, and inside the timeout it turned a real answer into "timeout"."""
    if prov in _loaded:
        return
    import PIL.Image  # noqa: F401

    if prov == "claude":
        import anthropic  # noqa: F401
    else:
        from google.genai import types  # noqa: F401
    _loaded.add(prov)


def no_network() -> bool:
    """HANDOVER_NO_NETWORK=1 (for tests): warm_up does nothing and no real SDK client is ever
    built, so a key in .env can never turn a test into a paid call. Fake clients still work."""
    return bool(config.get("HANDOVER_NO_NETWORK"))


def has_key() -> bool:
    """True if the active provider's key is in the environment or <repo>/.env. Lets the engine
    show "no_key" at startup without a failed call. Never returns or logs the key itself."""
    return bool(_key_for(provider()))


async def warm_up(timeout: float = 5.0) -> bool:
    """Open the pooled connection (DNS, TLS) at startup so the first real check is not slow.

    One cheap metadata call for the check model. False in mock mode, without a key, or on
    any failure (logged, key redacted). Never raises. Warms the client of the calling loop,
    so call it from the loop that will run the checks.
    """
    if is_mock() or no_network() or not has_key():
        return False
    prov = provider()
    if prov == "claude" and not spend.allow():
        return False
    t0 = time.monotonic()
    try:
        if prov == "claude":  # model metadata: free, and opens the pooled connection
            await asyncio.wait_for(_get_claude().models.retrieve(_claude_model(), timeout=timeout), timeout)
        else:
            await asyncio.wait_for(_get_client().aio.models.get(model=_model()), timeout)
    except Exception as e:
        err = classify_error(e)
        _log_failure("warm-up", err, e, timeout)
        return False
    log.info("%s warm-up ok in %d ms", prov, int((time.monotonic() - t0) * 1000))
    return True


def _no_key() -> bool:
    """True when this loop has no client yet and no key is configured: fail fast, no network call."""
    prov = provider()
    return not _has_client(prov) and not _key_for(prov)


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
    'First write "seen": at most 8 words on LIVE (outline shape, orientation, visible parts). '
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


TIMEOUT_GRACE = 0.25  # Claude: the SDK enforces the timeout; this outer bound only backs it up


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
    labels = _check_labels(prev_ref is not None)
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
    return _parse_answer(resp.text or "")


def _parse_answer(text: str) -> tuple[Done, float, Optional[str]]:
    """Validate the JSON answer. Confidence is clamped first: a 1.02 is a confident answer,
    not a reason to throw the whole result away."""
    data = json.loads(text or "")
    if isinstance(data, dict):
        if isinstance(data.get("confidence"), (int, float)):
            data["confidence"] = max(0.0, min(1.0, float(data["confidence"])))
        if isinstance(data.get("done"), str):
            data["done"] = data["done"].strip().lower()  # enums can come back as "Yes"
    ans = _Answer.model_validate(data)
    log.debug("check seen: %s", trim_reason(ans.seen, SEEN_MAX_WORDS))
    reason = differs_to_reason(ans.differs)
    done: Done = ans.done
    if done == "yes" and reason is not None:
        done = "unsure"  # it says done but names a difference: never advance on a contradiction
    return done, float(ans.confidence), reason


def _check_labels(with_before: bool) -> list[str]:
    if with_before:
        return [
            "IMAGE A: the object BEFORE this step (answer no if LIVE looks like this)",
            "IMAGE B: DONE, the finished step",
            "IMAGE C: LIVE camera",
        ]
    return ["IMAGE A: DONE, the finished step", "IMAGE B: LIVE camera"]


# ---------------------------------------------------------------- Claude

def _claude_answer_schema() -> dict:
    """Same evidence-first fields as Gemini, in the shape Claude structured outputs require:
    every field required, additionalProperties false, no numeric bounds (enforced on our side)."""
    props = {}
    for name, field in _Answer.model_fields.items():
        if name == "done":
            props[name] = {"type": "string", "enum": ["yes", "no", "unsure"], "description": field.description}
        elif name == "confidence":
            props[name] = {"type": "number", "description": field.description}
        else:
            props[name] = {"type": "string", "description": field.description}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _claude_image(jpeg: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(jpeg).decode("ascii")}}


_step_blocks: "dict[str, dict]" = {}
_STEP_BLOCKS_MAX = 64


def _step_block(jpeg: bytes) -> dict:
    """Image block for a reference (DONE or BEFORE), memoized by the source's sha1 so the bytes
    are identical on every call and the prompt cache matches. The dict is shared: never put
    cache_control (or anything else) on it."""
    key = hashlib.sha1(jpeg).hexdigest()
    block = _step_blocks.get(key)
    if block is None:
        block = _claude_image(downscale_jpeg(jpeg, STEP_MAX_SIDE, CLAUDE_JPEG_QUALITY))
        if len(_step_blocks) >= _STEP_BLOCKS_MAX:
            _step_blocks.pop(next(iter(_step_blocks)))
        _step_blocks[key] = block
    return block


CLAUDE_SYSTEM = (
    "You check whether a learner finished one step of a hands-on task, from photos. "
    "IMAGE DONE shows the finished step. IMAGE LIVE is the camera now. "
    "IMAGE BEFORE, when given, shows the object before this step: if LIVE looks like BEFORE, answer no. "
    + RULE + " "
    'First write "seen": at most 8 words on LIVE (outline shape, orientation, visible parts). '
    'Then "differs": at most 8 words on what LIVE lacks compared with DONE, or "nothing". '
    'Then "done": yes, no, or unsure (unsure if the object is not visible or blurred), '
    'and "confidence" from 0 to 1.'
)
CLAUDE_FINAL = "Answer for IMAGE LIVE."


def _cache_on() -> bool:
    return bool(config.get("HANDOVER_CLAUDE_CACHE"))


def _claude_check_content(ref_jpeg: bytes, live_jpeg: bytes, question: str, prev_ref: Optional[bytes]) -> list[dict]:
    """BEFORE, DONE, then the question with the cache breakpoint, then LIVE. Everything up to
    the question repeats for every frame of a step, so later calls read it from the cache."""
    content: list[dict] = []
    if prev_ref is not None:
        content += [{"type": "text", "text": "IMAGE BEFORE: the object before this step"}, _step_block(prev_ref)]
    content += [{"type": "text", "text": "IMAGE DONE: the finished step"}, _step_block(ref_jpeg)]
    q: dict = {"type": "text", "text": f"Question: {question.strip()}"}
    if _cache_on():
        q["cache_control"] = {"type": "ephemeral"}
    live = downscale_jpeg(live_jpeg, _max_side(), CLAUDE_JPEG_QUALITY)
    content += [q, {"type": "text", "text": "IMAGE LIVE: the camera now"}, _claude_image(live),
                {"type": "text", "text": CLAUDE_FINAL}]
    return content


def _claude_thinking_off(model: str) -> bool:
    """Haiku 5.x accepts thinking disabled at effort low to high. Opus 5.5 rejects disabled at
    any effort and Sonnet 5.5 wants between_tools, so other models keep adaptive thinking."""
    return model.removeprefix("anthropic.").startswith("claude-haiku-5")


def _claude_request(model: str, content: list[dict], schema: dict, secs: float,
                    system: Optional[str] = None) -> dict:
    """Effort low and JSON schema output for every model; thinking off where the model allows it.
    No streaming. No temperature, top_p or top_k: API version 2026-10-21 rejects them."""
    req: dict = {
        "model": model,
        "max_tokens": CLAUDE_MAX_TOKENS if _claude_thinking_off(model) else CLAUDE_THINKING_MAX_TOKENS,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        "timeout": secs,
    }
    if _claude_thinking_off(model):
        req["thinking"] = {"type": "disabled"}
    if system:
        req["system"] = [{"type": "text", "text": system}]
    return req


def _claude_text(resp, model: str) -> tuple[str, float]:
    """Record the spend, then return the JSON text. Refusals and truncated answers were
    billed but are unusable, so they raise _CheckFailure("error") with the cost attached."""
    usage = getattr(resp, "usage", None)
    usd = spend.record(model, usage)
    log.debug("claude usage: in %s, cache read %s, cache write %s, out %s",
              getattr(usage, "input_tokens", 0), getattr(usage, "cache_read_input_tokens", 0),
              getattr(usage, "cache_creation_input_tokens", 0), getattr(usage, "output_tokens", 0))
    stop = getattr(resp, "stop_reason", None)
    if stop == "refusal":
        details = getattr(resp, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        raise _CheckFailure("error", f"model refused (category {category})", usd)
    if stop in ("max_tokens", "model_context_window_exceeded"):
        raise _CheckFailure("error", f"answer cut off (stop_reason {stop})", usd)
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text, usd
    raise _CheckFailure("error", "no text block in the response", usd)


async def _claude_check(
    ref_jpeg: bytes, live_jpeg: bytes, question: str, prev_ref: Optional[bytes], secs: float
) -> tuple[Done, float, Optional[str], float, int]:
    content = await asyncio.to_thread(_claude_check_content, ref_jpeg, live_jpeg, question, prev_ref)
    model = _claude_model()
    resp = await _get_claude().messages.create(
        **_claude_request(model, content, _claude_answer_schema(), secs, system=CLAUDE_SYSTEM)
    )
    text, usd = _claude_text(resp, model)
    try:
        done, conf, reason = _parse_answer(text)
    except Exception as e:
        raise _CheckFailure("error", f"unparseable answer: {type(e).__name__}", usd) from e
    cached = int(getattr(getattr(resp, "usage", None), "cache_read_input_tokens", 0) or 0)
    return done, conf, reason, usd, cached


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
    prov = provider()
    if prov == "claude" and not spend.allow():
        return CheckResult("unsure", 0.0, 0, error="budget")  # no call made
    _load_sdk(prov)
    t0 = time.monotonic()
    err: Optional[CheckError] = None
    reason: Optional[str] = None
    usd = 0.0
    secs = 0.0
    cached = 0
    try:
        secs = _timeout(timeout)
        if prov == "claude":
            done, conf, reason, usd, cached = await asyncio.wait_for(
                _claude_check(ref_jpeg, live_jpeg, question, prev_ref, secs), secs + TIMEOUT_GRACE
            )
        else:
            done, conf, reason = await asyncio.wait_for(_gemini_check(ref_jpeg, live_jpeg, question, prev_ref), secs)
    except Exception as e:  # timeout, network, quota, refusal, bad JSON, bad image
        err = classify_error(e)
        usd = getattr(e, "cost_usd", 0.0)
        _log_failure("check", err, e, secs)
        done, conf, reason = "unsure", 0.0, None
    ms = int((time.monotonic() - t0) * 1000)
    return CheckResult(done, max(0.0, min(1.0, conf)), ms, reason, err, usd, cached)


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


def _claude_compare_schema(labels: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "match": {"type": "string", "enum": [*labels, "none"], "description": "label of the best match, or none"},
            "confidence": {"type": "number", "description": "0 to 1"},
        },
        "required": ["match", "confidence"],
        "additionalProperties": False,
    }


async def _claude_compare(
    live_jpeg: bytes, refs: list[tuple[int, bytes]], question: Optional[str], secs: float
) -> tuple[Optional[int], float, float]:
    labels = list(LABELS[: len(refs)])
    images = await asyncio.gather(
        *(asyncio.to_thread(downscale_jpeg, b) for _, b in refs), asyncio.to_thread(downscale_jpeg, live_jpeg)
    )
    content: list[dict] = []
    for label, img in zip(labels, images[:-1]):
        content += [{"type": "text", "text": f"Reference {label}"}, _claude_image(img)]
    content += [{"type": "text", "text": "Live camera now"}, _claude_image(images[-1])]
    context = f"Task step: {question.strip()}\n\n" if question and question.strip() else ""
    choices = "|".join(f'"{x}"' for x in [*labels, "none"])
    content.append({"type": "text", "text": COMPARE_PROMPT.format(context=context, labels=", ".join(labels), choices=choices)})
    model = _claude_model()
    resp = await _get_claude().messages.create(**_claude_request(model, content, _claude_compare_schema(labels), secs))
    text, usd = _claude_text(resp, model)
    try:
        step, conf = parse_match(text, refs)
    except Exception as e:
        raise _CheckFailure("error", f"unparseable answer: {type(e).__name__}", usd) from e
    return step, conf, usd


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
    prov = provider()
    if prov == "claude" and not spend.allow():
        return MatchResult(None, 0.0, 0, error="budget")
    _load_sdk(prov)
    t0 = time.monotonic()
    err: Optional[CheckError] = None
    usd = 0.0
    secs = 0.0
    try:
        secs = _timeout(timeout)
        if prov == "claude":
            step, conf, usd = await asyncio.wait_for(
                _claude_compare(live_jpeg, refs, question, secs), secs + TIMEOUT_GRACE
            )
        else:
            step, conf = await asyncio.wait_for(_gemini_compare(live_jpeg, refs, question), secs)
    except Exception as e:
        err = classify_error(e)
        usd = getattr(e, "cost_usd", 0.0)
        _log_failure("compare", err, e, secs)
        step, conf = None, 0.0
    return MatchResult(step, conf, int((time.monotonic() - t0) * 1000), err, usd)


# ---------------------------------------------------------------- breaker

class Breaker:
    """Stops model calls after repeated failures so a dead network or spent quota does not
    stall the learner; they use Next while it is open.

    3 consecutive timeouts or errors, or any rate limit, open it for open_seconds. Then
    allow() returns True exactly once for a trial call; that call's result closes it
    (success) or opens it again (failure). A missing key opens it for good.
    A spent Claude budget opens it with reason "budget". Its trial calls cost nothing:
    check_frame answers "budget" again without a request while the ledger says no, so it
    stays open until the date changes (day cap) or for good (total cap).
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
        elif err == "budget":
            self._open("budget", now)
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
    counts = {k: errors.count(k) for k in ("timeout", "rate_limited", "error", "no_key", "budget") if errors.count(k)}
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
    return "mock" if is_mock() else f"{provider()} {active_model()}"


def _cost_note(results: list) -> str:
    usd = sum(r.cost_usd for r in results)
    paid = [r.cost_usd for r in results if r.cost_usd]
    if not paid:
        return ""
    return f"  cost ${usd:.5f} total, ${usd / len(paid):.6f} per call"


def _budget_blocked() -> bool:
    """The CLI refuses up front instead of printing n budget failures."""
    if is_mock() or provider() != "claude" or spend.allow():
        return False
    print(spend.report())
    print("Refusing to run: the Claude budget is exhausted.")
    return True


async def time_checks(ref: Path, live: Path, question: str, n: int = 20, interleave: bool = False
                      ) -> list[CheckResult]:
    """n checks of one pair. interleave alternates cached and uncached calls (Claude) so both
    see the same network conditions, and prints the two sets separately."""
    ref_b, live_b = ref.read_bytes(), live.read_bytes()
    started = time.monotonic()
    results: list[CheckResult] = []
    modes: list[str] = []
    saved = os.environ.get("HANDOVER_CLAUDE_CACHE")
    print(f"provider {_mode()}  cache {'interleaved' if interleave else ('on' if _cache_on() else 'off')}", flush=True)
    try:
        for i in range(n):
            if interleave:
                os.environ["HANDOVER_CLAUDE_CACHE"] = "1" if i % 2 == 0 else "0"
            mode = "cache" if _cache_on() else "nocache"
            r = await check_frame(ref_b, live_b, question, step_started_at=started)
            results.append(r)
            modes.append(mode)
            tail = f"  {r.error}" if r.error else (f"  {r.reason}" if r.reason else "")
            cost = f"  ${r.cost_usd:.6f}  cache_read {r.cache_read_tokens}" if r.cost_usd else ""
            tag = f"  {mode}" if interleave else ""
            print(f"{i + 1:3d}  {r.done:6s}  conf {r.confidence:.2f}  {r.latency_ms} ms{cost}{tag}{tail}", flush=True)
    finally:
        if interleave:
            if saved is None:
                os.environ.pop("HANDOVER_CLAUDE_CACHE", None)
            else:
                os.environ["HANDOVER_CLAUDE_CACHE"] = saved
    groups = [("all", results)]
    if interleave:
        groups = [(m, [r for r, mm in zip(results, modes) if mm == m]) for m in ("cache", "nocache")]
    for name, rs in groups:
        if not rs:
            continue
        lat, errs = [r.latency_ms for r in rs], [r.error for r in rs]
        label = "" if name == "all" else f"  [{name}]"
        print(f"model {_mode()}{label}  {summarize(lat, errs)}{_cost_note(rs)}")
    lat, errs = [r.latency_ms for r in results], [r.error for r in results]
    print(gate_verdict(lat, errs))
    return results


async def time_compares(refs: list[Path], live: Path, n: int = 5) -> list[MatchResult]:
    ref_list = [(i, p.read_bytes()) for i, p in enumerate(refs)]
    live_b = live.read_bytes()
    results = []
    print(f"provider {_mode()}", flush=True)
    for i in range(n):
        r = await compare_refs(live_b, ref_list)
        results.append(r)
        label = LABELS[r.step] if r.step is not None else "none"
        tail = f"  {r.error}" if r.error else ""
        cost = f"  ${r.cost_usd:.6f}" if r.cost_usd else ""
        print(f"{i + 1:3d}  match {label:4s}  conf {r.confidence:.2f}  {r.latency_ms} ms{cost}{tail}", flush=True)
    stats = summarize([r.latency_ms for r in results], [r.error for r in results])
    print(f"model {_mode()}  compare {len(refs)} refs  {stats}{_cost_note(results)}")
    return results


def _main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server.check")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--time", nargs=3, metavar=("REF", "LIVE", "QUESTION"), help="time check_frame")
    g.add_argument("--compare", nargs="+", metavar="IMG", help="REF_A [REF_B ...] LIVE: time compare_refs")
    ap.add_argument("-n", type=int, default=None, help="calls (default 20 for --time, 5 for --compare)")
    cache = ap.add_mutually_exclusive_group()
    cache.add_argument("--no-cache", action="store_true", help="Claude: no prompt-cache breakpoint")
    cache.add_argument("--interleave", action="store_true", help="Claude: alternate cached and uncached calls")
    a = ap.parse_args()
    if a.no_cache:
        os.environ["HANDOVER_CLAUDE_CACHE"] = "0"
    logging.basicConfig(level=logging.INFO)
    for noisy in ("httpx", "httpx2", "anthropic", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # request lines are noise here
    if a.compare and not 2 <= len(a.compare) <= len(LABELS) + 1:
        ap.error(f"--compare takes 1 to {len(LABELS)} references plus the live image")
    if _budget_blocked():
        raise SystemExit(2)
    if a.time:
        ref, live, q = a.time
        asyncio.run(time_checks(Path(ref), Path(live), q, a.n or 20, interleave=a.interleave))
    else:
        *refs, live = (Path(x) for x in a.compare)
        asyncio.run(time_compares(refs, live, a.n or 5))


if __name__ == "__main__":
    _main()

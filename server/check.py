"""Vision check: does the live camera frame show the finished state of a step?

One Gemini call per frame, comparing the live frame with the step's reference
frame. Also holds the Debouncer (2 confident yes in a row advance a step) and a
small timing tool:

    python -m server.check --time REF.jpg LIVE.jpg "question" -n 20

Env:
    GEMINI_API_KEY / GOOGLE_API_KEY  key (or repo-root .env). Never printed.
    HANDOVER_CHECK_MODEL             model id (default gemini-3.5-flash-lite)
    HANDOVER_CHECK=mock              no network; pass after N seconds on a step
    HANDOVER_MOCK_PASS_SECONDS       N for mock mode (default 6)
    HANDOVER_CHECK_TIMEOUT           seconds before a call counts as unsure (default 8)
    HANDOVER_DEBOUNCE_N              consecutive yes needed (default 2)
    HANDOVER_MIN_CONF                minimum confidence for a yes (default 0.8)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("handover.check")

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MAX_SIDE = 640

Done = Literal["yes", "no", "unsure"]


@dataclass
class CheckResult:
    done: Done
    confidence: float
    latency_ms: int

    def as_dict(self) -> dict:
        return {"done": self.done, "confidence": round(self.confidence, 3), "latency_ms": self.latency_ms}


class _Answer(BaseModel):
    """Flat schema the model must answer with."""

    done: Literal["yes", "no", "unsure"] = Field(description="yes, no, or unsure")
    confidence: float = Field(ge=0, le=1, description="0 to 1")


def is_mock() -> bool:
    return os.environ.get("HANDOVER_CHECK", "").strip().lower() == "mock"


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


_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        key = _api_key()
        if not key:
            raise RuntimeError("no Gemini key: set GEMINI_API_KEY or add it to .env")
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(api_version="v1beta"))
    return _client


# ---------------------------------------------------------------- images

def downscale_jpeg(data: bytes, max_side: int = MAX_SIDE, quality: int = 80) -> bytes:
    """Return a JPEG whose long side is at most max_side. Small images pass through."""
    from PIL import Image

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
    need = float(os.environ.get("HANDOVER_MOCK_PASS_SECONDS", "6"))
    passed = time.monotonic() - step_started_at >= need
    ms = int((time.monotonic() - t0) * 1000)
    return CheckResult("yes", 0.9, ms) if passed else CheckResult("no", 0.85, ms)


# ---------------------------------------------------------------- real check

PROMPT = (
    "{question}\n\n"
    "Compare the live camera image with the reference image of the finished step. "
    'Answer "yes" only if the live view clearly shows the same finished state. '
    'Answer "no" if the object is visible but not in that state yet. '
    'Answer "unsure" if the object is not visible, blocked, or blurred. '
    "Ignore differences in background, lighting, hands, and camera angle. "
    'Reply as JSON: {{"done": "yes"|"no"|"unsure", "confidence": 0 to 1}}.'
)


async def _gemini_check(ref_jpeg: bytes, live_jpeg: bytes, question: str) -> tuple[Done, float]:
    from google.genai import types

    ref, live = await asyncio.gather(
        asyncio.to_thread(downscale_jpeg, ref_jpeg), asyncio.to_thread(downscale_jpeg, live_jpeg)
    )
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="Reference: what the finished step looks like"),
                types.Part.from_bytes(data=ref, mime_type="image/jpeg"),
                types.Part.from_text(text="Live camera now"),
                types.Part.from_bytes(data=live, mime_type="image/jpeg"),
                types.Part.from_text(text=PROMPT.format(question=question.strip())),
            ],
        )
    ]
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=_Answer.model_json_schema(),
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
        temperature=0,
        max_output_tokens=256,
    )
    model = os.environ.get("HANDOVER_CHECK_MODEL", DEFAULT_MODEL)
    resp = await _get_client().aio.models.generate_content(model=model, contents=contents, config=config)
    data = json.loads(resp.text or "")
    ans = _Answer.model_validate(data)
    return ans.done, float(ans.confidence)


async def check_frame(
    ref_jpeg: bytes, live_jpeg: bytes, question: str, *, step_started_at: Optional[float] = None
) -> CheckResult:
    """Never raises. Timeout or any error gives unsure with confidence 0."""
    if is_mock():
        return await _mock_check(ref_jpeg, step_started_at)
    t0 = time.monotonic()
    timeout = float(os.environ.get("HANDOVER_CHECK_TIMEOUT", "8"))
    try:
        done, conf = await asyncio.wait_for(_gemini_check(ref_jpeg, live_jpeg, question), timeout)
    except asyncio.TimeoutError:
        log.warning("check timed out after %.1fs", timeout)
        done, conf = "unsure", 0.0
    except Exception as e:  # network, quota, bad JSON, bad image
        log.warning("check failed: %s: %s", type(e).__name__, e)
        done, conf = "unsure", 0.0
    return CheckResult(done, max(0.0, min(1.0, conf)), int((time.monotonic() - t0) * 1000))


# ---------------------------------------------------------------- debouncer

class Debouncer:
    """Advance after n consecutive yes answers with confidence >= min_conf.

    Any no, unsure, or low-confidence yes resets the count.
    """

    def __init__(self, n: Optional[int] = None, min_conf: Optional[float] = None):
        self.n = n if n is not None else int(os.environ.get("HANDOVER_DEBOUNCE_N", "2"))
        self.min_conf = min_conf if min_conf is not None else float(os.environ.get("HANDOVER_MIN_CONF", "0.8"))
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

async def time_checks(ref: Path, live: Path, question: str, n: int = 20) -> list[CheckResult]:
    ref_b, live_b = ref.read_bytes(), live.read_bytes()
    started = time.monotonic()
    results = []
    for i in range(n):
        r = await check_frame(ref_b, live_b, question, step_started_at=started)
        results.append(r)
        print(f"{i + 1:3d}  {r.done:6s}  conf {r.confidence:.2f}  {r.latency_ms} ms", flush=True)
    lat = sorted(r.latency_ms for r in results)
    p50 = statistics.median(lat)
    p90 = lat[min(len(lat) - 1, int(round(0.9 * (len(lat) - 1))))]
    mode = "mock" if is_mock() else os.environ.get("HANDOVER_CHECK_MODEL", DEFAULT_MODEL)
    print(f"model {mode}  n={n}  p50 {p50:.0f} ms  p90 {p90} ms  max {lat[-1]} ms")
    return results


def _main() -> None:
    ap = argparse.ArgumentParser(prog="python -m server.check")
    ap.add_argument("--time", nargs=3, metavar=("REF", "LIVE", "QUESTION"), required=True)
    ap.add_argument("-n", type=int, default=20)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    ref, live, q = a.time
    asyncio.run(time_checks(Path(ref), Path(live), q, a.n))


if __name__ == "__main__":
    _main()

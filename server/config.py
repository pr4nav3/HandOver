"""Single source for every HANDOVER_* tunable: name, default, bounds, owner and meaning.

Modules read values through get(name) (or the env_* helpers) so a typo in an env var
can never crash the hub or silently push a value out of range: a bad value logs one
warning and falls back to the default. Values are read on every call, so tests and
tools can change the environment without restarting anything.

    python -m server.config     prints the registry and the current effective values

Secrets (the Gemini key) are only ever shown as "set" or "not set".
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Literal, Optional, Union

log = logging.getLogger("handover.config")

Kind = Literal["float", "int", "bool", "choice", "str", "path", "secret"]
Status = Literal["live", "proposed"]
Value = Union[float, int, bool, str, None]

_warned: set[tuple[str, str]] = set()
_warned_lock = threading.Lock()


def _warn_once(name: str, raw: str, why: str, default: object) -> None:
    """One warning per (name, bad value): values are read per call, often once a second."""
    with _warned_lock:
        if (name, raw) in _warned:
            return
        _warned.add((name, raw))
    log.warning("%s=%r %s; using default %r", name, raw, why, default)


def _raw(name: str) -> Optional[str]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def _bounded(name: str, raw: str, value: float, default, lo: Optional[float], hi: Optional[float]):
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        _warn_once(name, raw, f"is outside {_range(lo, hi)}", default)
        return default
    return value


def env_float(name: str, default: float, min: Optional[float] = None, max: Optional[float] = None) -> float:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        _warn_once(name, raw, "is not a number", default)
        return default
    if value != value or value in (float("inf"), float("-inf")):  # NaN or infinite
        _warn_once(name, raw, "is not a finite number", default)
        return default
    return _bounded(name, raw, value, default, min, max)


def env_int(name: str, default: int, min: Optional[int] = None, max: Optional[int] = None) -> int:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        _warn_once(name, raw, "is not a whole number", default)
        return default
    return _bounded(name, raw, value, default, min, max)


_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


def env_bool(name: str, default: bool) -> bool:
    raw = _raw(name)
    if raw is None:
        return default
    low = raw.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    _warn_once(name, raw, "is not one of 1/0, true/false, yes/no, on/off", default)
    return default


def env_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    """Case-insensitive; returns the canonical spelling from choices."""
    raw = _raw(name)
    if raw is None:
        return default
    for c in choices:
        if raw.lower() == c.lower():
            return c
    _warn_once(name, raw, f"is not one of {', '.join(choices)}", default)
    return default


def env_str(name: str, default: Optional[str]) -> Optional[str]:
    raw = _raw(name)
    return default if raw is None else raw


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class Tunable:
    name: str
    default: Value
    kind: Kind
    owner: str
    meaning: str
    min: Optional[float] = None
    max: Optional[float] = None
    choices: tuple[str, ...] = ()
    status: Status = "live"
    """live: code reads this env var today. proposed: a constant today; the owner adopts it via get()."""


T = Tunable
REGISTRY: tuple[Tunable, ...] = (
    # runtime
    T("HANDOVER_LESSONS", None, "path", "main.py", "lessons folder (default <repo>/lessons)"),
    T("HANDOVER_CERTS", None, "path", "main.py", "certs folder (default <repo>/certs)"),
    T("HANDOVER_PORT", 8000, "int", "main.py", "http port", 1, 65535),
    T("HANDOVER_HTTPS_PORT", 8443, "int", "main.py", "https port when certs exist", 1, 65535),
    T("HANDOVER_FFMPEG", None, "path", "teach.py, replay.py", "ffmpeg binary (default PATH, then Homebrew)"),
    T("HANDOVER_LOG_JSON", False, "bool", "main.py", "log one JSON object per line"),
    T("GEMINI_API_KEY", None, "secret", "check.py, teach.py", "Gemini key (or GOOGLE_API_KEY or <repo>/.env); Effective checks the environment only"),
    # check
    T("HANDOVER_CHECK", "gemini", "choice", "check.py", "gemini or mock (no network)", choices=("gemini", "mock")),
    T("HANDOVER_CHECK_MODEL", "gemini-3.5-flash-lite", "str", "check.py", "check model"),
    T("HANDOVER_CHECK_TIMEOUT", 3.0, "float", "check.py", "seconds before a check counts as a timeout", 0.1, 60),
    T("HANDOVER_CHECK_LIVE_RES", "low", "choice", "check.py", "media resolution of the live image",
      choices=("low", "medium")),
    T("HANDOVER_CHECK_MAX_SIDE", 640, "int", "check.py", "long side in pixels images are shrunk to", 64, 4096),
    T("HANDOVER_MOCK_PASS_SECONDS", 6.0, "float", "check.py", "mock mode passes after this many seconds on a step",
      0, 600),
    # breaker
    T("HANDOVER_BREAKER_SECONDS", 30.0, "float", "check.py", "seconds checks stay off after failures", 1, 3600),
    # debounce
    T("HANDOVER_DEBOUNCE_N", 2, "int", "check.py", "confident yes answers in a row to advance", 1, 10),
    T("HANDOVER_MIN_CONF", 0.8, "float", "check.py", "minimum confidence for a yes", 0, 1),
    # gate
    T("HANDOVER_GATE", True, "bool", "gate.py", "motion gate on (0 sends every frame)"),
    T("HANDOVER_GATE_MOTION", 0.02, "float", "gate.py", "hold while motion is above this fraction", 0, 1),
    T("HANDOVER_GATE_STILL", 0.005, "float", "gate.py", "a frame is still below this motion fraction", 0, 1),
    T("HANDOVER_GATE_STILL_FRAMES", 2, "int", "gate.py", "still frames in a row to count as settled", 1, 30),
    T("HANDOVER_GATE_CHANGE", 0.018, "float", "gate.py", "change vs the last checked frame to check again", 0, 1),
    T("HANDOVER_GATE_HEARTBEAT_S", 6.0, "float", "gate.py", "seconds between heartbeat checks", 0.5, 600),
    # mistake
    T("HANDOVER_MISTAKE_MIN_CONF", 0.7, "float", "mistake.py", "minimum compare confidence for behind or ahead",
      0, 1),
    T("HANDOVER_MOCK_MISTAKE", None, "str", "mistake.py",
      "test only, mock mode: behind:<step> or ahead:<step> (0-based)"),
    # engine
    T("HANDOVER_VERIFIED_HOLD", 0.8, "float", "main.py", "seconds the verified status shows before advancing",
      0, 10),
    T("HANDOVER_MISTAKE_PARALLEL", True, "bool", "main.py", "run the mistake compare alongside the normal check"),
    T("HANDOVER_MIN_FRAME_GAP", 0.2, "float", "main.py", "seconds between camera frames the hub accepts", 0, 5),
    T("HANDOVER_MAX_CAMERAS", 8, "int", "main.py", "camera connections allowed at once", 1, 64),
    T("HANDOVER_MAX_VIEWERS", 32, "int", "main.py", "UI connections allowed at once", 1, 256),
    T("HANDOVER_MAX_UPLOAD_MB", 2048, "int", "main.py", "largest teach upload in MB", 1, 16384, status="proposed"),
    T("HANDOVER_MAX_FRAME_MB", 2, "int", "main.py", "camera frames larger than this are ignored", 1, 64,
      status="proposed"),
    # teach
    T("HANDOVER_TEACH_MODEL", "gemini-3.8-flash", "str", "teach.py", "step extraction model"),
    T("HANDOVER_TEACH_MOCK", False, "bool", "teach.py", "no Gemini; three placeholder steps"),
    T("HANDOVER_SELFTEST_TIMEOUT", 10.0, "float", "teach.py", "seconds per teach-time self-test check", 0.1, 120),
)
del T

_BY_NAME = {t.name: t for t in REGISTRY}


def tunable(name: str) -> Tunable:
    return _BY_NAME[name]


def get(name: str) -> Value:
    """Effective value of a registered tunable, validated against its bounds or choices."""
    t = _BY_NAME[name]
    if t.kind == "float":
        return env_float(name, float(t.default), t.min, t.max)  # type: ignore[arg-type]
    if t.kind == "int":
        lo = int(t.min) if t.min is not None else None
        hi = int(t.max) if t.max is not None else None
        return env_int(name, int(t.default), lo, hi)  # type: ignore[arg-type]
    if t.kind == "bool":
        return env_bool(name, bool(t.default))
    if t.kind == "choice":
        return env_choice(name, str(t.default), t.choices)
    if t.kind == "secret":
        raise ValueError(f"{name} is a secret; read it where it is used, never through config.get")
    return env_str(name, t.default)  # type: ignore[arg-type]


# ---------------------------------------------------------------- table

def _range(lo: Optional[float], hi: Optional[float]) -> str:
    if lo is None and hi is None:
        return ""
    return f"{_fmt(lo) if lo is not None else ''} to {_fmt(hi) if hi is not None else ''}".strip()


def _fmt(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _effective(t: Tunable) -> str:
    if t.kind == "secret":
        return "set" if os.environ.get(t.name) or os.environ.get("GOOGLE_API_KEY") else "not set"
    return _fmt(get(t.name))


def table() -> str:
    """Markdown table of the registry with current effective values. Never prints a secret."""
    rows = [
        "| Var | Default | Effective | Range | Owner | Status | Meaning |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in REGISTRY:
        rng = " or ".join(t.choices) if t.choices else _range(t.min, t.max)
        cells = [f"`{t.name}`", _fmt(t.default), _effective(t), rng, t.owner, t.status, t.meaning]
        rows.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    print(table())

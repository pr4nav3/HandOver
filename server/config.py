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
from pathlib import Path
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
    T("HANDOVER_NO_NETWORK", False, "bool", "check.py",
      "tests: never build a real model client or warm up (fakes still work)"),
    T("HANDOVER_LOG_JSON", False, "bool", "main.py", "log one JSON object per line"),
    T("GEMINI_API_KEY", None, "secret", "check.py, teach.py",
      "Gemini key (or GOOGLE_API_KEY), from the environment or <repo>/.env"),
    T("ANTHROPIC_API_KEY", None, "secret", "check.py, teach.py",
      "Claude key, from the environment or <repo>/.env"),
    # check
    T("HANDOVER_CHECK", "gemini", "choice", "check.py", "gemini or mock (no network)", choices=("gemini", "mock")),
    T("HANDOVER_CHECK_PROVIDER", "auto", "choice", "check.py",
      "live check provider; auto picks claude when a Claude key is found, else gemini",
      choices=("auto", "claude", "gemini")),
    T("HANDOVER_CHECK_MODEL", "gemini-3.5-flash-lite", "str", "check.py", "Gemini check model"),
    T("HANDOVER_CLAUDE_CHECK_MODEL", "claude-haiku-5-5", "str", "check.py", "Claude check model"),
    T("HANDOVER_CHECK_TIMEOUT", 3.0, "float", "check.py", "seconds before a check counts as a timeout", 0.1, 60),
    T("HANDOVER_CHECK_LIVE_RES", "low", "choice", "check.py", "media resolution of the live image",
      choices=("low", "medium")),
    T("HANDOVER_CHECK_MAX_SIDE", 640, "int", "check.py", "long side in pixels images are shrunk to", 64, 4096),
    T("HANDOVER_MOCK_PASS_SECONDS", 6.0, "float", "check.py", "mock mode passes after this many seconds on a step",
      0, 600),
    # breaker
    T("HANDOVER_BREAKER_SECONDS", 30.0, "float", "check.py", "seconds checks stay off after failures", 1, 3600),
    # Claude budget
    T("HANDOVER_CLAUDE_CACHE", True, "bool", "check.py", "prompt-cache the step images and question (0 for timing)"),
    T("HANDOVER_CLAUDE_BUDGET_DAY_USD", 20.0, "float", "spend.py", "Claude spend allowed per local day, USD", 0, 10000),
    T("HANDOVER_CLAUDE_BUDGET_TOTAL_USD", 50.0, "float", "spend.py", "Claude spend allowed in total, USD", 0, 100000),
    T("HANDOVER_CLAUDE_SPEND_FILE", None, "path", "spend.py", "spend ledger (default <repo>/logs/claude_spend.json)"),
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
    T("HANDOVER_MISTAKE_SETTLE_S", 5.0, "float", "mistake.py",
      "seconds of settled consecutive no before the mistake compare runs", 0.5, 60),
    T("HANDOVER_MISTAKE_COOLDOWN_S", 10.0, "float", "mistake.py",
      "minimum seconds between mistake compares on one step", 1, 120),
    T("HANDOVER_MOCK_MISTAKE_AFTER_S", 4.0, "float", "mistake.py",
      "test only, mock mode: seconds on the step before the mock mistake fires", 0.5, 60),
    T("HANDOVER_MOCK_MISTAKE", None, "str", "mistake.py",
      "test only, mock mode: behind:<step> or ahead:<step> (0-based)"),
    # engine
    T("HANDOVER_VERIFIED_HOLD", 0.8, "float", "main.py", "seconds the verified status shows before advancing",
      0, 10),
    T("HANDOVER_MISTAKE_PARALLEL", True, "bool", "main.py", "run the mistake compare alongside the normal check"),
    T("HANDOVER_WHISPER_MODEL", "small.en", "str", "teach.py",
      "local faster-whisper model for narration transcripts (base.en faster, medium.en better)"),
    T("HANDOVER_TRANSCRIBE", "auto", "choice", "teach.py",
      "narration source: auto (local for Claude, model for Gemini), local (whisper), model (Gemini hears audio), off",
      choices=("auto", "local", "model", "off")),
    T("HANDOVER_VOICE_SCRIPT_MODEL", "claude-haiku-5-5", "str", "voice.py", "Claude model that writes voiceover scripts"),
    T("HANDOVER_VOICE", "af_heart", "str", "voice.py", "Kokoro voice for voiceovers (af_heart, af_bella, ...)"),
    T("HANDOVER_VOICE_SPEED", 0.95, "float", "voice.py", "voiceover speaking speed", 0.7, 1.3),
    T("HANDOVER_TTS_PROVIDER", "kokoro", "choice", "voice.py", "kokoro (local) or elevenlabs (needs ELEVENLABS_API_KEY; falls back to kokoro)",
      choices=("kokoro", "elevenlabs")),
    T("HANDOVER_ELEVEN_VOICE", "EXAVITQu4vr4xnSDxMaL", "str", "voice.py", "ElevenLabs voice id (default Sarah)"),
    T("HANDOVER_ELEVEN_MODEL", "eleven_multilingual_v2", "str", "voice.py", "ElevenLabs model id"),
    T("HANDOVER_VOICEOVER", "auto", "choice", "voice.py", "auto (only when narration is thin), always, off",
      choices=("auto", "always", "off")),
    T("HANDOVER_PRODUCE_MODEL", "claude-haiku-5-5", "str", "produce.py", "Claude model that marks action regions for produced videos"),
    T("HANDOVER_PRODUCE_JOBS", 3, "int", "produce.py", "parallel ffmpeg renders for produced videos", 1, 3),
    T("HANDOVER_PRODUCE_FONT", None, "str", "produce.py", "font file for produced video text; default the system SF font"),
    T("HANDOVER_DATA", None, "str", "library.py", "hub data folder (accounts, orgs, history); default <repo>/data"),
    T("HANDOVER_AUTH", "optional", "choice", "accounts.py", "optional: anonymous allowed; required: mutating routes need a token",
      choices=("optional", "required")),
    T("HANDOVER_TOKEN_DAYS", 30.0, "float", "accounts.py", "days a sign-in token stays valid", 0.0001, 365),
    T("HANDOVER_LOGIN_PER_MINUTE", 5, "int", "accounts.py", "login and invite code attempts per minute per name and IP", 1, 100),
    T("HANDOVER_HISTORY_DEPTH", 20, "int", "library.py", "editor undo snapshots kept per course", 1, 100),
    T("HANDOVER_EVENTS_JSONL", None, "str", "databricks.py", "local events mirror; default <repo>/logs/events.jsonl"),
    T("HANDOVER_UNDERSTAND", False, "bool", "main.py", "run real-time understanding beside the check (progress, stage, both-yes advance)"),
    T("HANDOVER_LIVE_MISTAKES", False, "bool", "main.py", "show live mistake warnings from understanding (advisory; off until tested on real footage)"),
    T("HANDOVER_UNDERSTAND_MODEL", "claude-haiku-5-5", "str", "understand.py", "Claude model for rubrics and live understanding"),
    T("HANDOVER_UNDERSTAND_TIMEOUT", 5.0, "float", "understand.py", "seconds before a live understanding call counts as unsure", 0.1, 60),
    T("HANDOVER_LIVE_MISTAKE_MIN_CONF", 0.75, "float", "understand.py", "minimum confidence for a live mistake", 0, 1),
    T("HANDOVER_LIVE_MISTAKE_REPEAT", 2, "int", "understand.py", "consecutive results naming a mistake before it fires", 1, 10),
    T("HANDOVER_LIVE_MISTAKE_CLEAR", 2, "int", "understand.py", "results without the mistake before it clears", 1, 10),
    T("HANDOVER_LIVE_MISTAKE_COOLDOWN_S", 8.0, "float", "understand.py", "seconds before the same live mistake can fire again", 0, 600),
    T("HANDOVER_MAX_INFLIGHT", 2, "int", "main.py", "checks at once on one step, each on a different settled frame", 1, 4),
    T("HANDOVER_FAST_PATH", True, "bool", "main.py", "one confident yes that names no difference advances alone"),
    T("HANDOVER_FAST_CONF", 0.92, "float", "main.py", "confidence the fast-path yes needs", 0.5, 1),
    T("HANDOVER_AHEAD_SKIP", False, "bool", "main.py", "let a doubly confirmed ahead result skip to step k+2"),
    T("HANDOVER_AHEAD_CONFIRM_N", 3, "int", "main.py",
      "confirmed ahead verdicts in a row for step k+1 that move the step to k+1 (reason ahead_confirm); 0 off", 0, 10),
    T("HANDOVER_AHEAD_CONFIRM_CONF", 0.8, "float", "main.py",
      "compare confidence an ahead verdict needs to count toward ahead_confirm", 0.5, 1),
    T("HANDOVER_UNDERSTAND_OVERRIDE_N", 3, "int", "main.py",
      "check yes answers in a row while understanding says no, before the check alone advances "
      "(reason understand_override); 0 off", 0, 10),
    T("HANDOVER_UNDERSTAND_OVERRIDE_CONF", 0.8, "float", "main.py",
      "confidence a check yes needs to count toward understand_override", 0.5, 1),
    T("HANDOVER_MOCK_LATENCY_MS", 600.0, "float", "latency_bench.py", "test only: stand-in check latency", 0, 10000),
    T("HANDOVER_HELLO_GRACE_MS", 300, "float", "main.py",
      "ms a new camera has to send hello before its first state broadcast", 0, 5000),
    T("HANDOVER_WEB_DIST", None, "str", "main.py", "folder with the built web app; default <repo>/web/dist"),
    T("HANDOVER_MIN_FRAME_GAP", 0.04, "float", "main.py",
      "seconds between camera frames the hub accepts (0.04 lets 15 fps senders through with jitter)", 0, 5),
    T("HANDOVER_CHECK_INTERVAL_S", 1.0, "float", "main.py",
      "seconds between frames offered to the vision model", 0.2, 10),
    T("HANDOVER_UI_FPS", 15, "int", "main.py", "live frames forwarded to each viewer per second, at most", 1, 30),
    T("HANDOVER_MAX_CAMERAS", 8, "int", "main.py", "camera connections allowed at once", 1, 64),
    T("HANDOVER_MAX_VIEWERS", 32, "int", "main.py", "UI connections allowed at once", 1, 256),
    T("HANDOVER_STARTUP_CLEANUP", False, "bool", "main.py",
      "delete stale upload leftovers at startup; unset only logs what it would remove", status="proposed"),
    T("HANDOVER_MAX_UPLOAD_MB", 2048, "int", "main.py", "largest teach upload in MB", 1, 16384, status="proposed"),
    T("HANDOVER_MAX_FRAME_MB", 2, "int", "main.py", "camera frames larger than this are ignored", 1, 64,
      status="proposed"),
    # teach
    T("HANDOVER_TEACH_MODEL", "gemini-3.8-flash", "str", "teach.py", "step extraction model"),
    T("HANDOVER_TEACH_MOCK", False, "bool", "teach.py", "no Gemini; three placeholder steps"),
    T("HANDOVER_TEACH_PROVIDER", "auto", "choice", "teach.py",
      "step extraction: gemini, claude, or auto (gemini with a Gemini key, else claude with ANTHROPIC_API_KEY, "
      "else placeholder steps)", choices=("gemini", "claude", "auto")),
    T("HANDOVER_CLAUDE_TEACH_MODEL", "claude-haiku-5-5", "str", "teach.py",
      "Claude model for step extraction (frames only, no audio)"),
    T("HANDOVER_SELFTEST_TIMEOUT", 10.0, "float", "teach.py", "seconds per teach-time self-test check", 0.1, 120),
    T("HANDOVER_MIN_STEP_S", 6.0, "float", "teach.py", "steps shorter than this are merged into a neighbour", 0.0, 600.0),
    T("HANDOVER_REF_TAIL", 0.25, "float", "teach.py",
      "fraction of a step, back from its end, searched for the stillest window when hands never leave the frame",
      0.05, 0.5),
    T("HANDOVER_TEACH_SAMPLE_S", 1.0, "float", "teach.py",
      "seconds between frames the vision boundary pass sees across the whole take", 0.25, 5.0),
    T("HANDOVER_TEACH_BOUNDARY_MODEL", "claude-sonnet-5-5", "str", "teach.py",
      "model that finds when each step is done (vision boundaries); falls back to claude-haiku-5-5"),
    T("HANDOVER_AUTO_SELFTEST", True, "bool", "teach.py",
      "run the self-test after every cut and recut; failing steps become manual"),
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


def _dotenv_names() -> set[str]:
    """Names with a non-empty value in <repo>/.env. Values are never kept or returned."""
    path = Path(__file__).resolve().parent.parent / ".env"
    names: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return names
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip().strip('"').strip("'"):
                names.add(k.strip().removeprefix("export ").strip())
    return names


def _effective(t: Tunable) -> str:
    if t.kind == "secret":
        names = (t.name, "GOOGLE_API_KEY") if t.name == "GEMINI_API_KEY" else (t.name,)
        if any(os.environ.get(n) for n in names):
            return "set (env)"
        if _dotenv_names() & set(names):
            return "set (.env)"
        return "not set"
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

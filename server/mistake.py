"""Mistake policy (M9): when to run the reference compare, and what to say after it.

Pure logic, no I/O. The engine feeds every check result for the current camera
step to MistakeWatch.on_result. After 5 s of settled consecutive "no" on one
step (at most once per 10 s per step) it returns True, and the engine runs one
multiple-choice compare over references k-1, k, k+1. The engine then passes the
best match to MistakeWatch.decide, which returns the contract `mistake`
message (CONTRACT.md 7.2) or None.

    behind  live frame matches step k-1: never moves the step; message is the
            step's common_mistake or "This still looks like step <k>."
    ahead   live frame matches step k+1: the engine must confirm with one normal
            check of step k+1 at >= AHEAD_CONFIRM_CONF before go(k + 2, "camera");
            message is "You're ahead."

Env (registered in server/config.py; bad values fall back to the default):
    HANDOVER_MISTAKE_MIN_CONF   minimum compare confidence for behind or ahead (default 0.7, range 0 to 1)
    HANDOVER_MISTAKE_SETTLE_S   seconds of settled consecutive no before the compare (default 5, range 0.5 to 60)
    HANDOVER_MISTAKE_COOLDOWN_S minimum seconds between compares on one step (default 10, range 1 to 120)
    HANDOVER_CHECK=mock         mock mode; the only time HANDOVER_MOCK_MISTAKE is read
    HANDOVER_MOCK_MISTAKE       test only: "behind:<step>" or "ahead:<step>" (0-based);
                                after MOCK_AFTER_S on that step, mock() returns the
                                mistake once per visit to that step, source "mock"
"""

from __future__ import annotations

from typing import Optional

from server import config
from server.check import is_mock

# An "ahead" match is acted on only after one normal check of step k+1 at this confidence.
AHEAD_CONFIRM_CONF = 0.8
# Seconds on the step before the HANDOVER_MOCK_MISTAKE hook fires.
MOCK_AFTER_S = 4.0
# Confidence reported by the mock hook.
MOCK_CONF = 0.9

AHEAD_MESSAGE = "You're ahead."


def _min_conf() -> float:
    """Minimum k-1 / k / k+1 compare confidence for a mistake. Registry value; a bad or out-of-range env value falls back to the default."""
    return config.env_float("HANDOVER_MISTAKE_MIN_CONF", 0.7, 0, 1)


def behind_message(step: int, steps: Optional[list[dict]]) -> str:
    """common_mistake of the current step, else the contract fallback."""
    custom = ""
    if steps and 0 <= step < len(steps):
        custom = (steps[step].get("common_mistake") or "").strip()
    return custom or f"This still looks like step {step}."  # looks_like + 1 == step


def _message(step: int, kind: str, looks_like: int, confidence: float, source: str,
             steps: Optional[list[dict]]) -> dict:
    text = behind_message(step, steps) if kind == "behind" else AHEAD_MESSAGE
    return {"type": "mistake", "step": step, "kind": kind, "looks_like": looks_like,
            "message": text, "confidence": round(float(confidence), 3), "source": source}


def needs_confirmation(mistake: dict) -> bool:
    """True for ahead: confirm with one normal check of step k+1 before go(k + 2, "camera")."""
    return mistake.get("kind") == "ahead"


class MistakeWatch:
    def __init__(self, settle_s: Optional[float] = None, cooldown_s: Optional[float] = None):
        """None reads the registry value; an explicit argument wins."""
        if settle_s is None:
            settle_s = config.env_float("HANDOVER_MISTAKE_SETTLE_S", 5.0, 0.5, 60)
        if cooldown_s is None:
            cooldown_s = config.env_float("HANDOVER_MISTAKE_COOLDOWN_S", 10.0, 1, 120)
        self.settle_s = settle_s
        self.cooldown_s = cooldown_s
        self.min_conf = _min_conf()
        self._step: Optional[int] = None
        self._no_since: Optional[float] = None
        self._last_fire: dict[int, float] = {}  # per step, kept across step changes
        self._mock_fired: Optional[int] = None  # step the mock hook fired on this visit

    def reset(self) -> None:
        """Call on every step change: drops the no-streak and re-arms the mock hook."""
        self._step = None
        self._no_since = None
        self._mock_fired = None

    def on_result(self, step: int, done: str, now: float) -> bool:
        """Feed every check result for the current camera step. True = run the compare now."""
        if step != self._step:
            self.reset()
            self._step = step
        if done != "no":  # yes resets, unsure breaks the streak
            self._no_since = None
            return False
        if self._no_since is None:
            self._no_since = now
        if now - self._no_since < self.settle_s:
            return False
        last = self._last_fire.get(step)
        if last is not None and now - last < self.cooldown_s:
            return False
        self._last_fire[step] = now
        return True

    def decide(self, step: int, total: int, match_step: Optional[int], confidence: float,
               steps: list[dict], source: str = "gemini") -> Optional[dict]:
        """Turn the compare result into the contract mistake message, or None."""
        if match_step is None or confidence < self.min_conf:
            return None
        if match_step == step - 1 and match_step >= 0:
            return _message(step, "behind", match_step, confidence, source, steps)
        if match_step == step + 1 and match_step < total:
            return _message(step, "ahead", match_step, confidence, source, steps)
        return None

    def mock(self, step: int, elapsed: float, steps: Optional[list[dict]] = None) -> Optional[dict]:
        """HANDOVER_MOCK_MISTAKE hook, mock mode only. Fires once per visit, after MOCK_AFTER_S."""
        if self._mock_fired == step or not is_mock():
            return None
        raw = (config.env_str("HANDOVER_MOCK_MISTAKE", None) or "").lower()
        kind, _, num = raw.partition(":")
        if kind not in ("behind", "ahead"):
            return None
        try:
            target = int(num)
        except ValueError:
            return None
        if target != step or elapsed < MOCK_AFTER_S:
            return None
        if kind == "behind" and step < 1:
            return None
        self._mock_fired = step
        looks_like = step - 1 if kind == "behind" else step + 1
        return _message(step, kind, looks_like, MOCK_CONF, "mock", steps)

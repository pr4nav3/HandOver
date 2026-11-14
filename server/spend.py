"""Claude spend ledger and budget guard: a hard cap on what Claude calls can cost.

Every Claude call (live checks and teach) asks allow() first and passes the response's
usage to record() afterwards. The ledger lives in <repo>/logs/claude_spend.json (logs/
is gitignored): daily totals keyed by local date plus an all-time total, in USD and
tokens. Writes are atomic (temp file, then rename) and serialized with a thread lock
and, where the OS has it, a file lock, so the hub and a CLI run at the same time do not
lose each other's calls.

Path: HANDOVER_CLAUDE_SPEND_FILE overrides the default. Caps (config.py): HANDOVER_CLAUDE_BUDGET_DAY_USD (default 20) and
HANDOVER_CLAUDE_BUDGET_TOTAL_USD (default 50). Once either is reached, allow() is False:
the day cap lifts at local midnight, the total cap never lifts unless raised.
A ledger that cannot be read blocks all calls (unknown spend is treated as over budget).

    python -m server.spend      prints today, the total, both caps and what is left
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from server import config

log = logging.getLogger("handover.spend")

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO / "logs" / "claude_spend.json"

# USD per million tokens: (input, output). Source: the Claude API docs (models.md and the
# Haiku 5.5 migration guide), checked 2026-11-14.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
HAIKU_LONG_PROMPT = 100_000  # above this many prompt tokens Haiku 5.5 bills $0.50 / $2.50
HAIKU_LONG_PRICES = (0.50, 2.50)
UNKNOWN_MODEL_PRICES = PRICES["claude-opus-5-5"]  # conservative: never undercount
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_5M_FACTOR = 1.25
CACHE_WRITE_1H_FACTOR = 2.0

Blocked = Literal["day", "total", "ledger"]
_FIELDS = ("usd", "calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def _get(usage: Any, name: str) -> int:
    """Usage may be the SDK object or a plain dict (teach, tests); missing fields count as 0."""
    v = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    return int(v or 0)


def cost(model: str, usage: Any) -> float:
    """USD for one response. Cache reads bill at 0.1x input, cache writes at 1.25x (5 min)
    or 2x (1 h); an unknown model bills at the Opus price."""
    inp, out = _get(usage, "input_tokens"), _get(usage, "output_tokens")
    read, write = _get(usage, "cache_read_input_tokens"), _get(usage, "cache_creation_input_tokens")
    split = usage.get("cache_creation") if isinstance(usage, dict) else getattr(usage, "cache_creation", None)
    w1h = _get(split, "ephemeral_1h_input_tokens") if split is not None else 0
    w5m = max(0, write - w1h)
    name = model.removeprefix("anthropic.")
    p_in, p_out = PRICES.get(name, UNKNOWN_MODEL_PRICES)
    if name == "claude-haiku-5-5" and inp + read + write > HAIKU_LONG_PROMPT:
        p_in, p_out = HAIKU_LONG_PRICES
    in_equiv = inp + read * CACHE_READ_FACTOR + w5m * CACHE_WRITE_5M_FACTOR + w1h * CACHE_WRITE_1H_FACTOR
    return (in_equiv * p_in + out * p_out) / 1_000_000


@dataclass(frozen=True)
class Status:
    date: str
    day_usd: float
    total_usd: float
    day_calls: int
    total_calls: int
    day_cap: float
    total_cap: float
    blocked: Optional[Blocked]

    @property
    def remaining_usd(self) -> float:
        """What can still be spent today: the smaller of both caps' headroom."""
        if self.blocked == "ledger":
            return 0.0
        return max(0.0, min(self.day_cap - self.day_usd, self.total_cap - self.total_usd))


def _empty() -> dict:
    return {f: 0 for f in _FIELDS} | {"usd": 0.0}


@contextlib.contextmanager
def _file_lock(path: Path):
    """Cross-process lock next to the ledger. fcntl exists on macOS and Linux; on Windows the
    thread lock alone still protects the hub process."""
    try:
        import fcntl
    except ImportError:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class Ledger:
    """Daily and all-time Claude spend in one JSON file. clock returns local wall time and is
    injectable so tests can cross midnight."""

    def __init__(self, path: Optional[Path] = None, clock: Callable[[], datetime] = lambda: datetime.now().astimezone()):
        self._path = Path(path) if path is not None else None
        self.clock = clock
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """Fixed path if given, else HANDOVER_CLAUDE_SPEND_FILE (read per call), else the default."""
        if self._path is not None:
            return self._path
        override = config.get("HANDOVER_CLAUDE_SPEND_FILE")
        return Path(str(override)).expanduser() if override else DEFAULT_PATH

    def _today(self) -> str:
        return self.clock().date().isoformat()

    def _load(self) -> Optional[dict]:
        """The ledger dict, a fresh one if the file does not exist, or None if it is unreadable."""
        if not self.path.exists():
            return {"version": 1, "days": {}, "total": _empty()}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("days"), dict) or not isinstance(data.get("total"), dict):
                raise ValueError("missing days or total")
            return data
        except (OSError, ValueError, AttributeError) as e:
            log.error("Claude spend ledger %s is unreadable (%s); blocking Claude calls until it is fixed",
                      self.path.name, type(e).__name__)
            return None

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".claude_spend.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def status(self) -> Status:
        day_cap = float(config.get("HANDOVER_CLAUDE_BUDGET_DAY_USD"))  # type: ignore[arg-type]
        total_cap = float(config.get("HANDOVER_CLAUDE_BUDGET_TOTAL_USD"))  # type: ignore[arg-type]
        today = self._today()
        with self._lock:
            data = self._load()
        if data is None:
            return Status(today, 0.0, 0.0, 0, 0, day_cap, total_cap, "ledger")
        day = data["days"].get(today, _empty())
        total = data["total"]
        day_usd, total_usd = float(day.get("usd", 0.0)), float(total.get("usd", 0.0))
        blocked: Optional[Blocked] = None
        if total_usd >= total_cap:
            blocked = "total"
        elif day_usd >= day_cap:
            blocked = "day"
        return Status(today, day_usd, total_usd, int(day.get("calls", 0)), int(total.get("calls", 0)),
                      day_cap, total_cap, blocked)

    def allow(self) -> bool:
        """True while both caps have headroom. Call before every Claude request."""
        return self.status().blocked is None

    def record(self, model: str, usage: Any) -> float:
        """Add one response's usage to today and the total. Returns its cost in USD.
        Never raises: a write failure is logged, and the next status() read decides."""
        usd = cost(model, usage)
        add = {
            "usd": usd,
            "calls": 1,
            "input_tokens": _get(usage, "input_tokens"),
            "output_tokens": _get(usage, "output_tokens"),
            "cache_read_tokens": _get(usage, "cache_read_input_tokens"),
            "cache_write_tokens": _get(usage, "cache_creation_input_tokens"),
        }
        try:
            with self._lock, _file_lock(self.path):
                data = self._load()
                if data is None:
                    return usd  # do not overwrite a ledger we cannot read
                today = self._today()
                day = data["days"].setdefault(today, _empty())
                for bucket in (day, data["total"]):
                    for k, v in add.items():
                        bucket[k] = bucket.get(k, 0) + v
                data["updated"] = self.clock().isoformat(timespec="seconds")
                self._write(data)
        except OSError as e:
            log.error("could not write the Claude spend ledger: %s", type(e).__name__)
        return usd


_default = Ledger()


def default_ledger() -> Ledger:
    return _default


def allow() -> bool:
    """True while today's and the all-time Claude spend are under their caps."""
    return _default.allow()


def record(model: str, usage: Any) -> float:
    """Count one Claude response (live check or teach). Returns its cost in USD."""
    return _default.record(model, usage)


def status() -> Status:
    return _default.status()


def report(s: Optional[Status] = None) -> str:
    s = s or status()
    state = {
        None: "open",
        "day": "blocked until local midnight (day cap reached)",
        "total": "blocked (total cap reached; raise HANDOVER_CLAUDE_BUDGET_TOTAL_USD to continue)",
        "ledger": "blocked (ledger unreadable; fix or move logs/claude_spend.json)",
    }[s.blocked]
    return "\n".join([
        f"Claude spend ({_default.path.relative_to(REPO) if _default.path.is_relative_to(REPO) else _default.path})",
        f"  today {s.date}: ${s.day_usd:.4f} in {s.day_calls} calls (cap ${s.day_cap:.2f})",
        f"  total:            ${s.total_usd:.4f} in {s.total_calls} calls (cap ${s.total_cap:.2f})",
        f"  remaining today:  ${s.remaining_usd:.4f}",
        f"  status: {state}",
    ])


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    print(report())

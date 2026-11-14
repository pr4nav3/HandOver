"""Spend ledger tests: pricing, persistence, atomic writes, caps, day rollover, locking, CLI.

Every test uses its own temp ledger; the real logs/claude_spend.json is never touched.
Run: .venv/bin/python -m server.test_spend (or pytest if installed).
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from server import spend
from server.spend import Ledger, cost

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="handover-test-spend-"))
os.environ["HANDOVER_CLAUDE_SPEND_FILE"] = str(TMP / "default.json")  # module-level ledger stays in TMP
_n = iter(range(10_000))


def fresh(name: str = "ledger") -> Path:
    return TMP / f"{name}-{next(_n)}.json"


class Clock:
    """Local wall time that tests can move across midnight."""

    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now


@contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-12


def test_pricing():
    m, k100 = 1_000_000, 100_000  # Haiku's short-prompt card applies up to 100K prompt tokens
    assert close(cost("claude-haiku-5-5", {"input_tokens": k100}), 0.10 / 10)
    assert close(cost("claude-haiku-5-5", {"output_tokens": m}), 0.50)
    assert close(cost("claude-sonnet-5-5", {"input_tokens": m, "output_tokens": m}), 12.0)
    assert close(cost("claude-opus-5-5", {"input_tokens": m, "output_tokens": m}), 24.0)
    assert close(cost("claude-made-up-9", {"input_tokens": m}), 4.0)  # unknown: Opus price
    assert close(cost("anthropic.claude-haiku-5-5", {"input_tokens": k100}), 0.01)  # Bedrock prefix
    # A typical live check: ~1200 tokens in, ~40 out.
    assert close(cost("claude-haiku-5-5", {"input_tokens": 1200, "output_tokens": 40}), 0.00014)


def test_cache_and_long_prompt_pricing():
    k = 10_000
    assert close(cost("claude-haiku-5-5", {"cache_read_input_tokens": k}), k * 0.10 * 0.1 / 1e6)
    assert close(cost("claude-haiku-5-5", {"cache_creation_input_tokens": k}), k * 0.10 * 1.25 / 1e6)
    split = SimpleNamespace(ephemeral_1h_input_tokens=k, ephemeral_5m_input_tokens=0)
    usage = SimpleNamespace(input_tokens=0, output_tokens=0, cache_read_input_tokens=0,
                            cache_creation_input_tokens=k, cache_creation=split)
    assert close(cost("claude-haiku-5-5", usage), k * 0.10 * 2.0 / 1e6)  # 1 hour writes: 2x
    # Over 100K prompt tokens Haiku 5.5 bills $0.50 / $2.50.
    assert close(cost("claude-haiku-5-5", {"input_tokens": 200_000, "output_tokens": 1_000_000}), 0.10 + 2.50)
    assert close(cost("claude-haiku-5-5", {"input_tokens": 100_000}), 0.01)  # exactly 100K: short card


def test_record_persists_and_sums():
    path = fresh()
    clock = Clock(datetime(2026, 11, 14, 15, 0).astimezone())
    a = Ledger(path, clock)
    usage = SimpleNamespace(input_tokens=1200, output_tokens=40, cache_read_input_tokens=5,
                            cache_creation_input_tokens=7, cache_creation=None)
    usd = a.record("claude-haiku-5-5", usage)
    a.record("claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 10})
    b = Ledger(path, clock)  # a new instance reads what the first wrote
    st = b.status()
    assert st.day_calls == st.total_calls == 2 and st.date == "2026-11-14"
    assert close(st.day_usd, usd + cost("claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 10}))
    data = json.loads(path.read_text())
    day = data["days"]["2026-11-14"]
    assert (day["input_tokens"], day["output_tokens"], day["cache_read_tokens"], day["cache_write_tokens"]) == \
        (2200, 50, 5, 7)
    assert data["total"]["calls"] == 2


def test_day_rollover_lifts_day_cap_only():
    path = fresh()
    clock = Clock(datetime(2026, 11, 14, 23, 59).astimezone())
    led = Ledger(path, clock)
    with env(HANDOVER_CLAUDE_BUDGET_DAY_USD="0.40", HANDOVER_CLAUDE_BUDGET_TOTAL_USD="1.00"):
        led.record("claude-haiku-5-5", {"output_tokens": 1_000_000})  # $0.50
        assert led.status().blocked == "day" and not led.allow()
        clock.now += timedelta(minutes=2)  # local midnight passes
        st = led.status()
        assert st.blocked is None and st.date == "2026-11-15" and st.day_usd == 0 and close(st.total_usd, 0.5)
        assert led.allow()
        led.record("claude-haiku-5-5", {"output_tokens": 1_000_000})
        assert led.status().blocked == "total"  # $1.00 total reached: the total cap never lifts
        clock.now += timedelta(days=3)
        assert led.status().blocked == "total" and not led.allow()
    data = json.loads(path.read_text())
    assert sorted(data["days"]) == ["2026-11-14", "2026-11-15"]


def test_caps_from_config_and_remaining():
    led = Ledger(fresh(), Clock(datetime(2026, 11, 14, 12, 0).astimezone()))
    st = led.status()
    assert (st.day_cap, st.total_cap) == (20.0, 50.0) and st.blocked is None
    assert close(st.remaining_usd, 20.0)
    with env(HANDOVER_CLAUDE_BUDGET_DAY_USD="lots"):  # a typo falls back to the default cap
        assert led.status().day_cap == 20.0
    led.record("claude-opus-5-5", {"output_tokens": 1_000_000})  # $20
    st = led.status()
    assert st.blocked == "day" and st.remaining_usd == 0.0


def test_unreadable_ledger_blocks_and_is_not_overwritten():
    path = fresh()
    path.write_text("{not json", encoding="utf-8")
    led = Ledger(path)
    assert led.status().blocked == "ledger" and not led.allow()
    led.record("claude-haiku-5-5", {"input_tokens": 10})
    assert path.read_text(encoding="utf-8") == "{not json"  # never reset to zero


def test_atomic_write_keeps_old_file_on_failure():
    path = fresh()
    led = Ledger(path)
    led.record("claude-haiku-5-5", {"input_tokens": 100})
    before = path.read_text(encoding="utf-8")
    real_replace = os.replace

    def broken_replace(src, dst):
        raise OSError("disk full")

    os.replace = broken_replace
    try:
        led.record("claude-haiku-5-5", {"input_tokens": 100})  # logged, never raised
    finally:
        os.replace = real_replace
    assert path.read_text(encoding="utf-8") == before
    leftovers = [p for p in path.parent.iterdir() if p.name.startswith(".claude_spend.") and p.suffix == ".tmp"]
    assert leftovers == []
    assert Ledger(path).status().total_calls == 1


def test_threads_do_not_lose_calls():
    path = fresh()
    led = Ledger(path)

    def work():
        for _ in range(25):
            led.record("claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 10})

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    st = Ledger(path).status()
    assert st.total_calls == 100
    assert close(st.total_usd, 100 * cost("claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 10}))


def test_processes_do_not_lose_calls():
    """The hub and a teach run are separate processes writing one ledger."""
    path = fresh()
    code = ("import sys; from pathlib import Path; from server.spend import Ledger\n"
            "led = Ledger(Path(sys.argv[1]))\n"
            "for _ in range(20): led.record('claude-haiku-5-5', {'input_tokens': 100})\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(path)], cwd=REPO) for _ in range(3)]
    assert all(p.wait(timeout=60) == 0 for p in procs)
    assert Ledger(path).status().total_calls == 60


def test_module_functions_use_the_configured_file():
    path = fresh("module")
    with env(HANDOVER_CLAUDE_SPEND_FILE=str(path)):
        assert spend.allow()
        usd = spend.record("claude-haiku-5-5", {"input_tokens": 1000})
        assert close(usd, 0.0001) and spend.status().total_calls == 1
        assert path.exists()


def test_cli_report_has_no_secrets():
    path = fresh("cli")
    Ledger(path).record("claude-haiku-5-5", {"input_tokens": 1200, "output_tokens": 40})
    key = "sk-ant-api03-must-not-print"
    out = subprocess.run([sys.executable, "-m", "server.spend"], cwd=REPO, capture_output=True, text=True,
                         timeout=60, env={**os.environ, "HANDOVER_CLAUDE_SPEND_FILE": str(path),
                                          "ANTHROPIC_API_KEY": key})
    assert out.returncode == 0, out.stderr
    assert key not in out.stdout + out.stderr
    for want in ("today", "total", "cap $20.00", "cap $50.00", "remaining today", "1 calls", "status: open"):
        assert want in out.stdout, (want, out.stdout)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

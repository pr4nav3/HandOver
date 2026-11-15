"""Config tests: env helpers, registry consistency, the printed table. No network.

Run: .venv/bin/python -m server.test_config (or pytest if installed).
"""

import logging
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from server import config
from server.config import REGISTRY, env_bool, env_choice, env_float, env_int, env_str

REPO = Path(__file__).resolve().parent.parent
VAR = "HANDOVER_TEST_CONFIG_VAR"


@contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v is not None})
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@contextmanager
def captured():
    h = _Capture()
    config.log.addHandler(h)
    config._warned.clear()
    try:
        yield h.messages
    finally:
        config.log.removeHandler(h)


def test_env_float():
    with env(**{VAR: None}):
        assert env_float(VAR, 3.0, 0.1, 60) == 3.0
    with env(**{VAR: "  "}):
        assert env_float(VAR, 3.0) == 3.0
    with env(**{VAR: "2.5"}):
        assert env_float(VAR, 3.0, 0.1, 60) == 2.5
    for bad in ("fast", "nan", "inf", "-1", "61"):
        with env(**{VAR: bad}):
            assert env_float(VAR, 3.0, 0.1, 60) == 3.0, bad


def test_env_int():
    with env(**{VAR: "4"}):
        assert env_int(VAR, 2, 1, 10) == 4
    for bad in ("2.5", "two", "0", "11"):
        with env(**{VAR: bad}):
            assert env_int(VAR, 2, 1, 10) == 2, bad


def test_env_bool():
    for raw, want in [("1", True), ("TRUE", True), ("yes", True), ("on", True),
                      ("0", False), ("false", False), ("No", False), ("off", False)]:
        with env(**{VAR: raw}):
            assert env_bool(VAR, not want) is want, raw
    with env(**{VAR: "maybe"}):
        assert env_bool(VAR, True) is True


def test_env_choice_and_str():
    with env(**{VAR: "MEDIUM"}):
        assert env_choice(VAR, "low", ("low", "medium")) == "medium"
    with env(**{VAR: "ultra"}):
        assert env_choice(VAR, "low", ("low", "medium")) == "low"
    with env(**{VAR: " gemini-x "}):
        assert env_str(VAR, None) == "gemini-x"
    with env(**{VAR: None}):
        assert env_str(VAR, "d") == "d"


def test_bad_value_warns_once():
    with captured() as msgs, env(**{VAR: "fast"}):
        for _ in range(5):
            env_float(VAR, 3.0)
        assert len(msgs) == 1 and VAR in msgs[0] and "3.0" in msgs[0]
    with captured() as msgs:
        with env(**{VAR: "fast"}):
            env_float(VAR, 3.0)
        with env(**{VAR: "slow"}):
            env_float(VAR, 3.0)
        assert len(msgs) == 2  # a new bad value warns again
    with captured() as msgs, env(**{VAR: "2"}):
        env_float(VAR, 3.0)
        assert msgs == []


def test_registry_consistent():
    names = [t.name for t in REGISTRY]
    assert len(names) == len(set(names))
    for t in REGISTRY:
        assert re.fullmatch(r"(HANDOVER_[A-Z0-9_]+|GEMINI_API_KEY|ANTHROPIC_API_KEY)", t.name), t.name
        assert t.meaning and t.owner, t.name
        assert "\u2014" not in t.meaning and "\u2013" not in t.meaning, t.name
        if t.kind in ("float", "int") and t.default is not None:
            assert t.min is None or t.default >= t.min, t.name
            assert t.max is None or t.default <= t.max, t.name
        if t.kind == "choice":
            assert t.default in t.choices, t.name
        if t.kind not in ("secret",):
            with env(**{t.name: None}):
                assert config.get(t.name) == t.default, t.name


def test_registry_covers_check_and_docs():
    """Every HANDOVER_* var named in check.py, main.py, the engine and check docs, or the contract's env table is
    registered."""
    known = {t.name for t in REGISTRY}
    for path in (REPO / "server" / "check.py", REPO / "server" / "main.py", REPO / "CONTRACT.md",
                 REPO / "server" / "docs" / "engine.md", REPO / "server" / "docs" / "checks.md"):
        found = set(re.findall(r"HANDOVER_[A-Z0-9_]+", path.read_text(encoding="utf-8")))
        # a name ending in "_" is a family written as HANDOVER_GATE_*
        missing = {n for n in found if n not in known and n != "HANDOVER_TEST_LOG" and not n.endswith("_")}
        assert not missing, (path.name, missing)



def test_recovery_tunables_registered_and_documented():
    """The ahead recovery and the understanding fallback: registered with their defaults and named in both docs."""
    want = {"HANDOVER_AHEAD_CONFIRM_N": 3, "HANDOVER_AHEAD_CONFIRM_CONF": 0.8,
            "HANDOVER_UNDERSTAND_OVERRIDE_N": 3, "HANDOVER_UNDERSTAND_OVERRIDE_CONF": 0.8}
    docs = "".join((REPO / "server" / "docs" / f).read_text(encoding="utf-8") for f in ("engine.md", "checks.md"))
    for name, default in want.items():
        assert config.tunable(name).default == default, name
        with env(**{name: None}):
            assert config.get(name) == default, name
        assert name in docs, name
    with env(HANDOVER_AHEAD_CONFIRM_N="11", HANDOVER_UNDERSTAND_OVERRIDE_CONF="0.2"):
        assert config.get("HANDOVER_AHEAD_CONFIRM_N") == 3 and config.get("HANDOVER_UNDERSTAND_OVERRIDE_CONF") == 0.8
    with env(HANDOVER_AHEAD_CONFIRM_N="0", HANDOVER_UNDERSTAND_OVERRIDE_N="0"):
        assert config.get("HANDOVER_AHEAD_CONFIRM_N") == 0 and config.get("HANDOVER_UNDERSTAND_OVERRIDE_N") == 0

CALL_RE = re.compile(
    r'config\.env_(float|int|bool|choice)\(\s*"(HANDOVER_[A-Z0-9_]+)"\s*,\s*([^,)]+)(?:,\s*([^,)]+))?(?:,\s*([^,)]+))?\)'
)
CONST_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*([^#\n]+)", re.M)


def _lit(text, consts=None):
    """A literal default or bound; a keyword (min=, max=) is dropped and a module constant is resolved."""
    text = re.sub(r"^\s*(min|max)\s*=", "", text).strip()
    if consts and text in consts:
        text = consts[text].strip()
    if text in ("True", "False"):
        return text == "True"
    try:
        return float(text)
    except ValueError:
        return text.strip("\"'")


def test_direct_env_calls_match_registry():
    """Modules that call config.env_* directly must use the registry's default and bounds,
    so python -m server.config never shows a value the code does not use."""
    for path in sorted((REPO / "server").glob("*.py")):
        if path.name.startswith("test_") or path.name == "config.py":
            continue
        source = path.read_text(encoding="utf-8")
        consts = dict(CONST_RE.findall(source))
        for kind, name, default, lo, hi in CALL_RE.findall(source):
            t = config.tunable(name)  # KeyError means unregistered
            where = f"{path.name}: {name}"
            assert t.kind == kind, (where, t.kind, kind)
            assert _lit(default, consts) == t.default, (where, default, t.default)
            if lo:
                assert _lit(lo, consts) == t.min, (where, lo, t.min)
            if hi:
                assert _lit(hi, consts) == t.max, (where, hi, t.max)


def test_live_view_and_teach_tunables_registered():
    """The check cadence, the frame gap for 15 fps cameras, the UI rate cap, and the two teach names."""
    want = {
        "HANDOVER_CHECK_INTERVAL_S": ("float", 1.0, 0.2, 10, "main.py"),
        "HANDOVER_MIN_FRAME_GAP": ("float", 0.04, 0, 5, "main.py"),
        "HANDOVER_UI_FPS": ("int", 15, 1, 30, "main.py"),
        "HANDOVER_MIN_STEP_S": ("float", 6.0, 0.0, 600.0, "teach.py"),
        "HANDOVER_AUTO_SELFTEST": ("bool", True, None, None, "teach.py"),
    }
    for name, (kind, default, lo, hi, owner) in want.items():
        t = config.tunable(name)
        assert (t.kind, t.default, t.min, t.max, t.owner) == (kind, default, lo, hi, owner), name
        with env(**{name: None}):
            assert config.get(name) == default, name
    with env(HANDOVER_CHECK_INTERVAL_S="0.1", HANDOVER_UI_FPS="31", HANDOVER_MIN_STEP_S="-1"):
        assert config.get("HANDOVER_CHECK_INTERVAL_S") == 1.0  # out of range: default
        assert config.get("HANDOVER_UI_FPS") == 15 and config.get("HANDOVER_MIN_STEP_S") == 6.0
    with env(HANDOVER_CHECK_INTERVAL_S="0.5", HANDOVER_UI_FPS="30", HANDOVER_AUTO_SELFTEST="0"):
        assert config.get("HANDOVER_CHECK_INTERVAL_S") == 0.5 and config.get("HANDOVER_UI_FPS") == 30
        assert config.get("HANDOVER_AUTO_SELFTEST") is False
    contract = (REPO / "CONTRACT.md").read_text(encoding="utf-8")
    for name in ("HANDOVER_CHECK_INTERVAL_S", "HANDOVER_MIN_STEP_S", "HANDOVER_AUTO_SELFTEST"):
        assert f"`{name}`" in contract, name


def test_check_reads_through_registry():
    """check.py and config agree: the registry bounds are what check.py enforces."""
    from server import check

    with env(HANDOVER_DEBOUNCE_N="0", HANDOVER_MIN_CONF="2", HANDOVER_CHECK_TIMEOUT="0.5",
             HANDOVER_CHECK_MAX_SIDE="512", HANDOVER_CHECK="MOCK"):
        d = check.Debouncer()
        assert (d.n, d.min_conf) == (2, 0.8)
        assert check._timeout() == 0.5 and check._max_side() == 512 and check.is_mock()


def test_secret_never_read_or_printed():
    try:
        config.get("GEMINI_API_KEY")
        raise AssertionError("secret readable through config.get")
    except ValueError:
        pass
    fake = "fake-secret-value-123"
    with env(GEMINI_API_KEY=fake):
        table = config.table()
        assert fake not in table
        row = next(r for r in table.splitlines() if "`GEMINI_API_KEY`" in r)
        assert "| set (env) |" in row


def test_cli_prints_table():
    fake = "fake-secret-value-456"
    out = subprocess.run(
        [sys.executable, "-m", "server.config"],
        cwd=REPO, capture_output=True, text=True, timeout=30,
        env={**os.environ, "GEMINI_API_KEY": fake, "HANDOVER_CHECK_TIMEOUT": "1.5", "HANDOVER_DEBOUNCE_N": "zero"},
    )
    assert out.returncode == 0, out.stderr
    assert fake not in out.stdout and fake not in out.stderr
    lines = out.stdout.splitlines()
    assert lines[0].startswith("| Var | Default | Effective |")
    assert len(lines) == len(REGISTRY) + 2
    timeout_row = next(r for r in lines if "`HANDOVER_CHECK_TIMEOUT`" in r)
    assert "| 3 | 1.5 |" in timeout_row
    assert "HANDOVER_DEBOUNCE_N" in out.stderr  # the bad value warned
    assert all(r.count("|") == 8 for r in lines), "a cell broke the table"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

"""Preflight: one command that checks the machine, the hub and the lessons before a session.

    .venv/bin/python scripts/preflight.py            the checklist (no money spent, no network calls to AI)
    .venv/bin/python scripts/preflight.py --probe    also one real check call on two lesson frames (costs money)
    .venv/bin/python scripts/preflight.py --fetch    git fetch origin main first, so ahead/behind is current
    .venv/bin/python scripts/preflight.py --json     machine-readable output

On Windows run it as .venv/Scripts/python.exe scripts/preflight.py; every check has a Windows path (netstat for
port owners, the UDP route trick for the LAN IP, GlobalMemoryStatusEx for memory) and the fixes name Windows commands.

Each line is OK (green), WARN (amber), FAIL (red) or SKIP (not applicable), with a fix
for anything that is not OK. The last line is READY, READY WITH WARNINGS or NOT READY.
Exit code: 0 for READY and READY WITH WARNINGS, 1 for NOT READY, 2 on bad usage.

Secrets are only ever shown as "set" or "not set"; the output is scrubbed of key values
as a second guard. Never writes anything. Runs in a few seconds without --probe.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"
_RANK = {SKIP: 0, OK: 0, WARN: 1, FAIL: 2}

IMPORTS = ("fastapi", "google.genai", "anthropic", "PIL")
SAMPLE_LESSONS = ("fortune-teller-v1",)  # lessons that must be present
SECRET_NAMES = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "DATABRICKS_TOKEN")
DATABRICKS_NAMES = ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID")
FFMPEG_MIN = (5, 1)
BUDGET_AMBER = 0.20  # amber when less than this share of a cap is left
PROBE_MIN_USD = 1.0
CERT_SOON_DAYS = 7
DISK_WARN_GB, DISK_FAIL_GB = 10.0, 2.0
MEM_WARN_PCT, MEM_FAIL_PCT = 20, 10
INTERFACES = ("en0", "en1", "en2", "bridge100")
WINDOWS = os.name == "nt"
INSTALL_FIX = "uv pip install -r server/requirements.lock"
PY_CMD = r".venv\Scripts\python.exe" if WINDOWS else ".venv/bin/python"
RUN_HUB = r"scripts\run_server.ps1" if WINDOWS else "scripts/run_server.sh"
FFMPEG_FIX = "winget install Gyan.FFmpeg" if WINDOWS else "brew install ffmpeg"
CERTS_FIX = ("mkcert -cert-file certs/cert.pem -key-file certs/key.pem <laptop IP> localhost 127.0.0.1"
             if WINDOWS else "scripts/certs.sh")
HUB_PORTS_NOTE = "the hub needs these ports free when it starts"
BUILD_FIX = "npm --prefix web ci && npm --prefix web run build"


@dataclass
class Row:
    area: str
    check: str
    status: str
    detail: str
    fix: str = ""
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------- small helpers (monkeypatched in tests)

def run(cmd: list[str], timeout: float = 5.0, cwd: Optional[Path] = None) -> tuple[int, str, str]:
    """(returncode, stdout, stderr). A missing program gives 127, a timeout 124. Never raises."""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=cwd)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out after {timeout:g} s"
    except OSError as e:
        return 126, "", f"{cmd[0]}: {type(e).__name__}"


def env_file(repo: Path = REPO) -> dict[str, str]:
    """KEY=VALUE pairs from <repo>/.env, same rules as server/databricks.py (_read_env_file): # comments,
    optional export and quotes; an unquoted value ends at " #", a quoted one at its closing quote. Kept as a
    copy, not an import, so preflight still runs when the server's imports are broken."""
    out: dict[str, str] = {}
    path = repo / ".env"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = env_value(v)
    return out


def env_value(raw: str) -> str:
    """One .env value, exactly as server/databricks.py _env_value reads it."""
    v = raw.strip()
    if v[:1] in ('"', "'"):
        end = v.find(v[0], 1)
        return v[1:end] if end > 0 else v[1:]
    hash_at = v.find(" #")
    if hash_at < 0:
        hash_at = v.find("\t#")
    return (v[:hash_at] if hash_at >= 0 else v).strip()


def is_set(name: str, repo: Path = REPO) -> bool:
    return bool(os.environ.get(name, "").strip() or env_file(repo).get(name, "").strip())


def secret_values(repo: Path = REPO) -> list[str]:
    """Every secret value we could know of, so the output can be scrubbed of them."""
    env = env_file(repo)
    vals = {os.environ.get(n, "").strip() for n in SECRET_NAMES} | {env.get(n, "").strip() for n in SECRET_NAMES}
    return sorted((v for v in vals if len(v) >= 6), key=len, reverse=True)


def scrub(text: str, secrets: list[str]) -> str:
    for v in secrets:
        text = text.replace(v, "[redacted]")
    return text


def try_import(name: str):
    """A server module, or None when it does not exist or fails to import."""
    try:
        return importlib.import_module(name)
    except Exception:
        return None



def route_ip() -> Optional[str]:
    """The address of the interface that routes outward, as server.main lan_ip() and run_server.ps1 find it.
    Connecting a UDP socket sends no packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def lan_ip() -> Optional[str]:
    """LAN or hotspot IP. Mac: same order as scripts/certs.sh (en0, en1, en2, bridge100, then ifconfig).
    Windows: the outward route, the address the hub prints and pairs with."""
    if WINDOWS:
        return route_ip()
    for ifc in INTERFACES:
        rc, out, _ = run(["ipconfig", "getifaddr", ifc], timeout=2)
        if rc == 0 and out.strip():
            return out.strip()
    rc, out, _ = run(["ifconfig"], timeout=2)
    if rc == 0:
        for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)", out):
            if not m.group(1).startswith("127."):
                return m.group(1)
    return None


def port(name: str = "HANDOVER_PORT", default: int = 8000) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        p = int(raw) if raw else default
        return p if 1 <= p <= 65535 else default
    except ValueError:
        return default


def https_port() -> int:
    return port("HANDOVER_HTTPS_PORT", 8443)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _dir_from_env(name: str, default: Path, repo: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else repo / p


def _short(text: str, n: int) -> str:
    """text cut at a word boundary to at most n characters, with ... when cut."""
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _money(v: float) -> str:
    return f"${v:.2f}" if v >= 0.01 or v == 0 else f"${v:.4f}"


# ---------------------------------------------------------------- 1. Python env

_ENV_SCRIPT = r"""
import importlib, json, sys
from importlib import metadata
out = {"python": sys.version.split()[0], "imports": {}, "versions": {}}
for m in sys.argv[1:]:
    try:
        importlib.import_module(m)
        out["imports"][m] = None
    except Exception as e:
        out["imports"][m] = type(e).__name__ + ": " + str(e)[:80]
for d in metadata.distributions():
    name = (d.metadata["Name"] or "").lower().replace("_", "-").replace(".", "-")
    if name:
        out["versions"][name] = d.version
print(json.dumps(out))
"""


def parse_lock(path: Path) -> dict[str, tuple[str, bool]]:
    """{normalized name: (version, has_marker)} from a uv/pip-compile lock."""
    pins: dict[str, tuple[str, bool]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return pins
    for line in lines:
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;]+)\s*(;.*)?$", line.strip())
        if m:
            pins[m.group(1).lower().replace("_", "-").replace(".", "-")] = (m.group(2), bool(m.group(3)))
    return pins


def check_python(repo: Path = REPO) -> list[Row]:
    A = "Python"
    py = next((c for c in (repo / ".venv" / "Scripts" / "python.exe", repo / ".venv" / "bin" / "python")
               if c.exists()), repo / ".venv" / "bin" / "python")
    if not py.exists():
        return [Row(A, "venv", FAIL, ".venv not found",
                    f"uv venv .venv --python 3.12 && {INSTALL_FIX}")]
    rc, out, err = run([str(py), "-c", _ENV_SCRIPT, *IMPORTS], timeout=20, cwd=repo)
    try:
        info = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [Row(A, "venv", FAIL, f"{PY_CMD} does not run ({(err.strip() or 'no output')[:80]})",
                    f"rm -rf .venv && uv venv .venv --python 3.12 && {INSTALL_FIX}")]
    rows = []
    if Path(sys.prefix).resolve() != (repo / ".venv").resolve():
        rows.append(Row(A, "interpreter", WARN, f"preflight runs under {sys.executable}, not .venv: "
                        "provider and budget lines may be wrong", f"{PY_CMD} scripts/preflight.py"))
    rows += [Row(A, "venv", OK if info["python"].startswith("3.12") else WARN,
                f".venv, Python {info['python']}",
                "" if info["python"].startswith("3.12") else "the lock is for Python 3.12: uv venv .venv --python 3.12")]
    bad = {m: e for m, e in info["imports"].items() if e}
    if bad:
        rows.append(Row(A, "imports", FAIL, "; ".join(f"{m} ({e})" for m, e in bad.items()), INSTALL_FIX))
    else:
        rows.append(Row(A, "imports", OK, ", ".join(IMPORTS)))
    pins = parse_lock(repo / "server" / "requirements.lock")
    if not pins:
        rows.append(Row(A, "lock pins", WARN, "server/requirements.lock missing or empty",
                        "pull main; the lock is committed"))
        return rows
    have = info["versions"]
    drift, missing = [], []
    for name, (ver, marker) in sorted(pins.items()):
        if name not in have:
            if not marker:  # packages with a platform marker may rightly be absent
                missing.append(name)
        elif have[name] != ver:
            drift.append(f"{name} {have[name]} (lock {ver})")
    if drift or missing:
        parts = drift + [f"{n} missing" for n in missing]
        shown = ", ".join(parts[:4]) + (f", and {len(parts) - 4} more" if len(parts) > 4 else "")
        rows.append(Row(A, "lock pins", WARN, f"{len(parts)} differ: {shown}", INSTALL_FIX,
                        {"drift": drift, "missing": missing}))
    else:
        rows.append(Row(A, "lock pins", OK, f"{len(pins)} packages match server/requirements.lock"))
    return rows


# ---------------------------------------------------------------- 2. ffmpeg

def find_tool(name: str) -> tuple[Optional[str], str]:
    """(path, problem). Same order as server/teach.py: HANDOVER_FFMPEG (ffprobe next to it), PATH, Homebrew."""
    override = os.environ.get("HANDOVER_FFMPEG", "").strip()
    if override:
        if not Path(override).is_file():
            return None, f"HANDOVER_FFMPEG points to {override}, which is not a file"
        if name == "ffmpeg":
            return override, ""
        sibling = Path(override).with_name(name + Path(override).suffix)
        if sibling.is_file():
            return str(sibling), ""
    found = shutil.which(name)
    if found:
        return found, ""
    brew = Path("/opt/homebrew/bin") / name
    if brew.is_file():
        return str(brew), ""
    return None, f"{name} not found on PATH or in /opt/homebrew/bin"


def parse_ff_version(text: str) -> Optional[tuple[int, int]]:
    m = re.search(r"version n?(\d+)\.(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def check_ffmpeg(repo: Path = REPO) -> list[Row]:
    rows = []
    for name in ("ffmpeg", "ffprobe"):
        path, problem = find_tool(name)
        if not path:
            rows.append(Row("Media", name, FAIL, problem, f"{FFMPEG_FIX} (or fix HANDOVER_FFMPEG)"))
            continue
        rc, out, err = run([path, "-version"], timeout=5)
        first = (out.strip().splitlines() or [""])[0]
        ver = parse_ff_version(first)
        if rc != 0:
            rows.append(Row("Media", name, FAIL, f"{path} does not run ({err.strip()[:60]})", "winget install Gyan.FFmpeg" if WINDOWS else "brew reinstall ffmpeg"))
        elif ver is None:
            rows.append(Row("Media", name, WARN, f"{path}, version unknown ({first[:40]})",
                            f"use a release build: {FFMPEG_FIX}"))
        elif ver < FFMPEG_MIN:
            rows.append(Row("Media", name, FAIL, f"{path}, version {ver[0]}.{ver[1]} (need 5.1 or newer)",
                            "winget upgrade Gyan.FFmpeg" if WINDOWS else "brew upgrade ffmpeg"))
        else:
            rows.append(Row("Media", name, OK, f"{ver[0]}.{ver[1]} at {path}"))
    return rows


# ---------------------------------------------------------------- 3. keys and providers

def check_keys(repo: Path = REPO) -> list[Row]:
    A = "Keys"
    rows = []
    claude = is_set("ANTHROPIC_API_KEY", repo)
    gemini = is_set("GEMINI_API_KEY", repo) or is_set("GOOGLE_API_KEY", repo)
    rows.append(Row(A, "Claude key", OK if claude else SKIP, "set" if claude else "not set",
                    "" if claude else "add ANTHROPIC_API_KEY to .env to use Claude"))
    rows.append(Row(A, "Gemini key", OK if gemini else SKIP, "set" if gemini else "not set",
                    "" if gemini else "add GEMINI_API_KEY to .env to use Gemini"))
    db = [n for n in DATABRICKS_NAMES if is_set(n, repo)]
    if len(db) == len(DATABRICKS_NAMES):
        rows.append(Row(A, "Databricks", OK, "set (host, token, warehouse)"))
    elif db:
        missing = ", ".join(n for n in DATABRICKS_NAMES if n not in db)
        rows.append(Row(A, "Databricks", WARN, f"partly set; missing {missing}",
                        f"add {missing} to .env (events still go to logs/events.jsonl)"))
    else:
        rows.append(Row(A, "Databricks", SKIP, "not set (events go to logs/events.jsonl only)",
                        "add DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_WAREHOUSE_ID to .env"))

    check = try_import("server.check")
    if check is None:
        rows.append(Row(A, "check provider", FAIL, "server/check.py does not import", INSTALL_FIX))
    elif check.is_mock():
        rows.append(Row(A, "check provider", WARN, "mock (HANDOVER_CHECK=mock): checks are fake",
                        "unset HANDOVER_CHECK for real checks"))
    else:
        prov = check.provider() if hasattr(check, "provider") else "gemini"
        model = check.active_model() if hasattr(check, "active_model") else check._model()
        if check.has_key():
            rows.append(Row(A, "check provider", OK, f"{prov} ({model})", data={"provider": prov, "model": model}))
        else:
            rows.append(Row(A, "check provider", FAIL, f"{prov}, but its key is not set: checks off, Next only",
                            "add ANTHROPIC_API_KEY or GEMINI_API_KEY to .env", {"provider": prov}))

    teach = try_import("server.teach")
    if teach is None:
        rows.append(Row(A, "teach provider", FAIL, "server/teach.py does not import", INSTALL_FIX))
    elif not hasattr(teach, "teach_provider"):
        rows.append(Row(A, "teach provider", SKIP, "server/teach.py has no provider switch"))
    else:
        tp = teach.teach_provider()
        if tp == "mock":
            rows.append(Row(A, "teach provider", WARN, "placeholder steps (no key or HANDOVER_TEACH_MOCK)",
                            "add GEMINI_API_KEY to .env before cutting a lesson"))
        else:
            note = " (frames only, no audio)" if tp == "claude" else ""
            rows.append(Row(A, "teach provider", OK, f"{tp}{note}", data={"provider": tp}))
    return rows


def claude_in_use() -> bool:
    check, teach = try_import("server.check"), try_import("server.teach")
    used = False
    if check is not None and hasattr(check, "provider") and not check.is_mock():
        used = check.provider() == "claude"
    if teach is not None and hasattr(teach, "teach_provider"):
        used = used or teach.teach_provider() == "claude"
    return used


# ---------------------------------------------------------------- 4. budget

def budget_rows(s: Any, in_use: bool) -> list[Row]:
    """Rows for a server.spend.Status. Red when exhausted and Claude is in use, amber under 20% left."""
    A = "Budget"
    if s.blocked == "ledger":
        return [Row(A, "Claude ledger", FAIL, "unreadable: all Claude calls are blocked",
                    "fix or move logs/claude_spend.json")]

    def share(used: float, cap: float) -> float:
        return 0.0 if cap <= 0 else max(0.0, (cap - used) / cap)

    def level(left: float) -> str:
        if left <= 0:
            return FAIL if in_use else WARN
        return WARN if left < BUDGET_AMBER else OK

    day_left, total_left = share(s.day_usd, s.day_cap), share(s.total_usd, s.total_cap)
    remaining = s.remaining_usd
    rows = [
        Row(A, "today", level(day_left),
            f"{_money(s.day_usd)} of {_money(s.day_cap)} ({s.day_calls} calls), {day_left:.0%} left",
            "" if day_left >= BUDGET_AMBER else "day cap lifts at local midnight; raise HANDOVER_CLAUDE_BUDGET_DAY_USD"),
        Row(A, "total", level(total_left),
            f"{_money(s.total_usd)} of {_money(s.total_cap)} ({s.total_calls} calls), {total_left:.0%} left",
            "" if total_left >= BUDGET_AMBER else "raise HANDOVER_CLAUDE_BUDGET_TOTAL_USD or switch to Gemini"),
    ]
    worst = max((r.status for r in rows), key=lambda st: _RANK[st])
    note = "" if in_use else " (Claude not in use)"
    rows.append(Row(A, "remaining", worst, f"{_money(remaining)} can be spent now{note}",
                    "" if worst == OK else "HANDOVER_CHECK_PROVIDER=gemini avoids Claude spend",
                    {"remaining_usd": round(remaining, 4), "day_usd": round(s.day_usd, 4),
                     "total_usd": round(s.total_usd, 4), "day_cap": s.day_cap, "total_cap": s.total_cap}))
    return rows


def check_budget(repo: Path = REPO) -> list[Row]:
    spend = try_import("server.spend")
    if spend is None or not hasattr(spend, "status"):
        why = "not present" if not (REPO / "server" / "spend.py").is_file() else "does not import here"
        return [Row("Budget", "Claude spend", SKIP, f"server/spend.py {why}")]
    try:
        s = spend.status()
    except Exception as e:
        return [Row("Budget", "Claude spend", FAIL, f"could not read the ledger ({type(e).__name__})",
                    "python -m server.spend")]
    return budget_rows(s, claude_in_use())


# ---------------------------------------------------------------- 5. live probe (only with --probe)

def probe_frames(lessons: Path) -> Optional[tuple[Path, Path, str]]:
    """(reference, live, question): a sample lesson's step 2 reference against its step 3 reference, so the
    expected answer is a real call on two different frames. Prefers the fortune teller."""
    for lid in (*SAMPLE_LESSONS, "demo-v1"):
        folder = lessons / lid
        try:
            data = json.loads((folder / "lesson.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        steps = [s for s in data.get("steps", []) if isinstance(s, dict)]
        cams = [s for s in steps if s.get("check_type", "camera") == "camera" and s.get("check_question")]
        if not cams:
            continue
        ref_step = cams[0]
        i = steps.index(ref_step)
        live_step = steps[i + 1] if i + 1 < len(steps) else steps[i - 1] if i > 0 else ref_step
        n_ref, n_live = steps.index(ref_step) + 1, steps.index(live_step) + 1
        ref = folder / (ref_step.get("ref_frame") or f"frames/{n_ref:02d}.jpg")
        live = folder / (live_step.get("ref_frame") or f"frames/{n_live:02d}.jpg")
        if ref.is_file() and live.is_file():
            return ref, live, str(ref_step["check_question"])
    return None


def check_probe(repo: Path = REPO) -> list[Row]:
    A = "Probe"
    check = try_import("server.check")
    if check is None:
        return [Row(A, "live check", FAIL, "server/check.py does not import", INSTALL_FIX)]
    if check.is_mock():
        return [Row(A, "live check", SKIP, "HANDOVER_CHECK=mock: nothing real to probe", "unset HANDOVER_CHECK")]
    if not check.has_key():
        return [Row(A, "live check", FAIL, "no key for the active provider", "add a key to .env")]
    prov = check.provider() if hasattr(check, "provider") else "gemini"
    spend = try_import("server.spend")
    if prov == "claude" and spend is not None and hasattr(spend, "status"):
        left = spend.status().remaining_usd
        if left < PROBE_MIN_USD:
            return [Row(A, "live check", FAIL, f"refused: only {_money(left)} of Claude budget left (need $1)",
                        "raise the cap or HANDOVER_CHECK_PROVIDER=gemini")]
    frames = probe_frames(_dir_from_env("HANDOVER_LESSONS", repo / "lessons", repo))
    if frames is None:
        return [Row(A, "live check", FAIL, "no sample lesson with two reference frames", "cut a lesson first")]
    ref, live, question = frames
    r = asyncio.run(check.check_frame(ref.read_bytes(), live.read_bytes(), question, timeout=10))
    cost = getattr(r, "cost_usd", 0.0)
    detail = (f"{prov}: {r.done} {r.confidence:.2f} in {r.latency_ms} ms, cost {_money(cost)}"
              f" ({ref.parent.parent.name} {ref.stem} vs {live.stem})")
    data = {"provider": prov, "done": r.done, "confidence": r.confidence, "latency_ms": r.latency_ms,
            "cost_usd": cost, "error": r.error}
    if r.error:
        return [Row(A, "live check", FAIL, f"{detail}, error {r.error}",
                    "check the key, the network and the provider status page", data)]
    slow = r.latency_ms > 2500
    return [Row(A, "live check", WARN if slow else OK, detail,
                "over the 2.5 s gate: widen the motion gate or lean on Next" if slow else "", data)]


# ---------------------------------------------------------------- 6. lessons

def load_lint(repo: Path = REPO):
    path = repo / "scripts" / "lesson_lint.py"
    if not path.is_file():
        path = REPO / "scripts" / "lesson_lint.py"
    try:
        spec = importlib.util.spec_from_file_location("lesson_lint", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    except Exception:
        return None


def check_lessons(repo: Path = REPO) -> list[Row]:
    A = "Lessons"
    lessons = _dir_from_env("HANDOVER_LESSONS", repo / "lessons", repo)
    lint = load_lint(repo)
    rows: list[Row] = []
    folders = sorted(p for p in lessons.iterdir() if p.is_dir() and not p.name.startswith(".")) \
        if lessons.is_dir() else []
    if not folders:
        rows.append(Row(A, "lessons", FAIL, f"no lesson folders in {lessons}", "cut one with scripts/new_lesson.sh"))
    for folder in folders:
        if not (folder / "lesson.json").is_file() and not (folder / "clips").is_dir():
            rows.append(Row(A, folder.name, SKIP, "not a lesson folder (no lesson.json)"))
            continue
        if lint is None:
            rows.append(Row(A, folder.name, SKIP, "scripts/lesson_lint.py does not import"))
            continue
        try:
            rep = lint.lint(folder)
        except Exception as e:
            rows.append(Row(A, folder.name, FAIL, f"lint crashed ({type(e).__name__})",
                            f"{PY_CMD} scripts/lesson_lint.py {folder}"))
            continue
        c, result = rep.counts(), rep.result()
        status = {"OK": OK, "WARN": WARN, "FAIL": FAIL}[result]
        detail = f"{c['OK']} OK, {c['WARN']} WARN, {c['FAIL']} FAIL"
        problems = [f"{r['check']}: {r['detail']}" for r in rep.checks() if r["result"] == result != "OK"]
        if problems:
            detail += f"; {_short(problems[0], 70)}" + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else "")
        rows.append(Row(A, folder.name, status, detail,
                        "" if status == OK else f"{PY_CMD} scripts/lesson_lint.py lessons/{folder.name}",
                        {"counts": c}))
    names = {f.name for f in folders if (f / "lesson.json").is_file()}
    for lid in SAMPLE_LESSONS:
        if lid in names:
            rows.append(Row(A, f"sample {lid}", OK, "present"))
        else:
            rows.append(Row(A, f"sample {lid}", FAIL, "missing",
                            f"cut it with scripts/new_lesson.sh --id {lid} --title \"...\" take.mov"))
    return rows


# ---------------------------------------------------------------- 7. web

_ASSET_RE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""")


def check_web(repo: Path = REPO) -> list[Row]:
    A = "Web"
    dist = _dir_from_env("HANDOVER_WEB_DIST", repo / "web" / "dist", repo)
    index = dist / "index.html"
    if not index.is_file():
        return [Row(A, "build", FAIL, f"{index} not found: the hub cannot serve the app", BUILD_FIX)]
    html = index.read_text(encoding="utf-8", errors="ignore")
    refs = [u for u in _ASSET_RE.findall(html) if not re.match(r"^(?:[a-z]+:|//|#)", u)]
    missing = [u for u in refs if not (dist / u.split("?")[0].lstrip("/")).is_file()]
    rows = []
    if missing:
        rows.append(Row(A, "build", FAIL, f"index.html points at missing files: {', '.join(missing[:3])}", BUILD_FIX))
    else:
        rows.append(Row(A, "build", OK, f"{len(refs)} assets referenced by index.html exist"))
    src = repo / "web" / "src"
    newest, newest_path = 0.0, None
    for p in [*(src.rglob("*") if src.is_dir() else []), repo / "web" / "index.html"]:
        try:
            if p.is_file() and p.stat().st_mtime > newest:
                newest, newest_path = p.stat().st_mtime, p
        except OSError:
            pass
    built = index.stat().st_mtime
    if newest_path is not None and newest > built + 1:
        rel = newest_path.relative_to(repo) if newest_path.is_relative_to(repo) else newest_path
        rows.append(Row(A, "fresh", WARN, f"{rel} changed after the last build", "npm --prefix web run build"))
    else:
        rows.append(Row(A, "fresh", OK, f"built {datetime.fromtimestamp(built):%H:%M %b %d}, newer than web/src"))
    return rows


# ---------------------------------------------------------------- 8. https certs

def parse_san(text: str) -> list[str]:
    return re.findall(r"IP Address:([0-9a-fA-F.:]+)", text)


def parse_enddate(text: str) -> Optional[datetime]:
    m = re.search(r"notAfter=(.+)", text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).strip().replace("  ", " "), "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def check_certs(repo: Path = REPO, ip: Optional[str] = None) -> list[Row]:
    A = "HTTPS"
    certs = _dir_from_env("HANDOVER_CERTS", repo / "certs", repo)
    cert, key = certs / "cert.pem", certs / "key.pem"
    if not cert.is_file() or not key.is_file():
        gone = " and ".join(p.name for p in (cert, key) if not p.is_file())
        return [Row(A, "certs", FAIL, f"{gone} missing: Safari /capture needs HTTPS",
                    "winget install FiloSottile.mkcert, mkcert -install, then " + CERTS_FIX if WINDOWS
                    else "brew install mkcert, then scripts/certs.sh")]
    rows = [Row(A, "certs", OK, f"cert.pem and key.pem in {certs.name}/")]
    rc, out, _ = run(["openssl", "x509", "-noout", "-ext", "subjectAltName", "-in", str(cert)], timeout=5)
    if rc != 0 or "IP Address" not in out:  # LibreSSL has no -ext
        rc, out, _ = run(["openssl", "x509", "-noout", "-text", "-in", str(cert)], timeout=5)
    sans = parse_san(out) if rc == 0 else []
    if rc != 0:
        rows.append(Row(A, "cert IP", WARN, "openssl could not read cert.pem", f"rerun {CERTS_FIX}"))
    elif ip is None:
        rows.append(Row(A, "cert IP", WARN, f"no LAN IP to compare (cert has {', '.join(sans) or 'no IPs'})",
                        "join Wi-Fi or the hotspot"))
    elif ip in sans:
        rows.append(Row(A, "cert IP", OK, f"covers {ip}"))
    else:
        rows.append(Row(A, "cert IP", FAIL, f"made for {', '.join(sans) or 'no IP'}, but this {'PC' if WINDOWS else 'Mac'} is {ip} now",
                        f"rerun {CERTS_FIX} (the network IP changed)"))
    rc, out, _ = run(["openssl", "x509", "-noout", "-enddate", "-in", str(cert)], timeout=5)
    end = parse_enddate(out) if rc == 0 else None
    if end is None:
        rows.append(Row(A, "cert expiry", WARN, "could not read the expiry date", f"rerun {CERTS_FIX}"))
    else:
        days = (end - datetime.now(timezone.utc)).days
        if days < 0:
            rows.append(Row(A, "cert expiry", FAIL, f"expired {end:%b %d %Y}", f"rerun {CERTS_FIX}"))
        elif days < CERT_SOON_DAYS:
            rows.append(Row(A, "cert expiry", WARN, f"expires {end:%b %d %Y} ({days} days)", f"rerun {CERTS_FIX}"))
        else:
            rows.append(Row(A, "cert expiry", OK, f"valid until {end:%b %d %Y}"))
    return rows


# ---------------------------------------------------------------- 9. hub

def http_json(url: str, timeout: float = 1.5) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (localhost only)
        return json.loads(r.read().decode("utf-8"))


async def _read_state(url: str, timeout: float = 2.0) -> dict:
    import websockets  # only needed when a hub is running

    async with websockets.connect(url, max_size=None, open_timeout=timeout) as ws:
        deadline = time.monotonic() + timeout
        while True:
            msg = await asyncio.wait_for(ws.recv(), max(0.1, deadline - time.monotonic()))
            if isinstance(msg, str):
                data = json.loads(msg)
                if data.get("type") == "state":
                    return data


def read_state(url: str, timeout: float = 2.0) -> dict:
    return asyncio.run(_read_state(url, timeout))


def hub_running(p: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", p), timeout=0.5):
            return True
    except OSError:
        return False


def check_hub(repo: Path = REPO, ip: Optional[str] = None) -> list[Row]:
    A = "Hub"
    p = port()
    if not hub_running(p):
        return [Row(A, "hub", SKIP, f"not running on port {p}", f"start it with {RUN_HUB}")]
    base = f"http://127.0.0.1:{p}"
    try:
        lessons = http_json(base + "/api/lessons")
    except (OSError, ValueError) as e:
        return [Row(A, "hub", FAIL, f"port {p} answers but /api/lessons failed ({type(e).__name__})",
                    f"another program may own port {p}: {owner_hint(p)}")]
    rows = [Row(A, "hub", OK, f"running on port {p}, {_count(len(lessons), 'lesson')}: "
                f"{', '.join(str(x.get('id')) for x in lessons[:5])}")]
    try:
        st = read_state(f"ws://127.0.0.1:{p}/ws/ui")
    except Exception as e:
        rows.append(Row(A, "ui socket", FAIL, f"/ws/ui gave no state ({type(e).__name__})",
                        f"restart the hub: {RUN_HUB}"))
        return rows
    lid = st.get("lesson_id")
    if lid:
        total, step = st.get("total", 0), st.get("step", 0)
        where = "done" if st.get("status") == "done" else f"step {step + 1} of {total}"
        rows.append(Row(A, "lesson", OK, f"{lid}, {where}, {st.get('status')}"))
    else:
        rows.append(Row(A, "lesson", OK, "none selected"))
    cam = st.get("camera") or {}
    if not st.get("camera_connected"):
        rows.append(Row(A, "camera", WARN, "not connected",
                        f"open the iPhone app, or https://{ip or '<laptop ip>'}:{https_port()}/capture in Safari"))
    elif cam.get("source") == "file":
        rows.append(Row(A, "camera", WARN, f"{cam.get('name')} (replay: the Recording banner shows)",
                        "connect the live camera before judging"))
    else:
        rows.append(Row(A, "camera", OK, f"{cam.get('name') or 'connected'} ({cam.get('source') or 'unknown'})"))
    if st.get("check_offline"):
        reason = st.get("check_offline_reason") or "unknown"
        hint = {"no_key": "add a key to .env and restart the hub", "rate_limited": "wait for the breaker or switch keys",
                "budget": "Claude budget is spent: HANDOVER_CHECK_PROVIDER=gemini"}.get(reason, "check the hub log")
        rows.append(Row(A, "checks", WARN, f"offline ({reason}): learner uses Next", hint))
    else:
        rows.append(Row(A, "checks", OK, "online"))
    return rows


# ---------------------------------------------------------------- 10. ports

def owner_hint(p: int) -> str:
    return f"netstat -ano | findstr :{p}" if WINDOWS else f"lsof -nP -iTCP:{p} -sTCP:LISTEN"


def listener_pids(p: int) -> list[int]:
    """PIDs listening on TCP port p (any address): netstat -ano on Windows, lsof elsewhere. [] when unknown."""
    if WINDOWS:
        rc, out, _ = run(["netstat", "-ano", "-p", "TCP"], timeout=5)
        pids: list[int] = []
        for line in out.splitlines() if rc == 0 else []:
            parts = line.split()
            # TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  42320 (the state word is localized, the :0 peer is not)
            if len(parts) >= 5 and parts[0] == "TCP" and parts[1].rsplit(":", 1)[-1] == str(p) \
                    and parts[2].rsplit(":", 1)[-1] == "0" and parts[-1].isdigit():
                pid = int(parts[-1])
                if pid and pid not in pids:
                    pids.append(pid)
        return pids
    rc, out, _ = run(["lsof", "-nP", f"-iTCP:{p}", "-sTCP:LISTEN", "-t"], timeout=3)
    return sorted({int(x) for x in out.split() if x.isdigit()}) if rc == 0 else []


def process_command(pid: int) -> str:
    """The command line of pid, or "" when it cannot be read."""
    if WINDOWS:
        rc, out, _ = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"], timeout=6)
    else:
        rc, out, _ = run(["ps", "-o", "command=", "-p", str(pid)], timeout=3)
    return out.strip() if rc == 0 else ""


def describe_command(cmd: str) -> str:
    """A command line as its program name, arguments and folder: 'python.exe -m server.main (in C:/Python312)'."""
    cmd = cmd.strip()
    if not cmd:
        return "command unknown"
    if cmd.startswith('"'):
        exe, _, rest = cmd[1:].partition('"')
    else:
        exe, _, rest = cmd.partition(" ")
    folder, name = os.path.split(exe)
    text = " ".join(f"{name or exe} {rest}".split())
    return _short(text, 60) + (f" (in {folder})" if folder else "")


def check_ports(repo: Path = REPO) -> list[Row]:
    """Who already listens on the hub's ports. A hub started from this checkout is OK; anything else (a stale
    hub from another folder or interpreter, another app) is named with its PID, since the new hub cannot bind."""
    A = "Ports"
    rows = []
    known: dict[int, str] = {}
    for name, p in (("http port", port()), ("https port", https_port())):
        pids = listener_pids(p)
        if not pids:
            rows.append(Row(A, name, OK, f"{p} is free" if can_bind("0.0.0.0", p) else f"{p} has no listener"))
            continue
        for pid in pids:
            if pid not in known:
                known[pid] = process_command(pid)
        cmds = {pid: known[pid] for pid in pids}
        ours = all("server.main" in c and str(repo).lower() in c.lower() for c in cmds.values())
        who = "; ".join(f"PID {pid}: {describe_command(c)}" for pid, c in cmds.items())
        if ours:
            rows.append(Row(A, name, OK, f"{p} held by this checkout's hub: {who}", data={"pids": pids}))
        else:
            kill = " ; ".join(f"Stop-Process -Id {pid}" if WINDOWS else f"kill {pid}" for pid in pids)
            rows.append(Row(A, name, WARN, f"{p} already held by {who}; {HUB_PORTS_NOTE}",
                            f"if it is a stale hub: {kill}", {"pids": pids}))
    return rows


# ---------------------------------------------------------------- 11. network

def can_bind(host: str, p: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, p))
        return True
    except OSError:
        return False
    finally:
        s.close()


def can_connect(host: str, p: int) -> bool:
    try:
        with socket.create_connection((host, p), timeout=0.5):
            return True
    except OSError:
        return False


def check_network(repo: Path = REPO, ip: Optional[str] = None) -> list[Row]:
    A = "Network"
    p = port()
    if ip is None:
        return [Row(A, "LAN IP", FAIL, f"no network IP: the phone cannot reach this {'PC' if WINDOWS else 'Mac'}",
                    "join Wi-Fi or the phone's hotspot")]
    rows = [Row(A, "LAN IP", OK, ip)]
    if hub_running(p):
        if can_connect(ip, p):
            rows.append(Row(A, "port", OK, f"hub answers on {ip}:{p}"))
        else:
            rows.append(Row(A, "port", FAIL, f"hub runs but not on {ip}:{p}",
                            "the hub must bind 0.0.0.0; " + ("allow Python on Private networks in Windows Defender Firewall"
                                                             if WINDOWS else "check the macOS firewall")))
    elif can_bind(ip, p):
        rows.append(Row(A, "port", OK, f"{ip}:{p} is free for the hub"))
    else:
        rows.append(Row(A, "port", FAIL, f"{ip}:{p} is taken by another program",
                        f"{owner_hint(p)}, or set HANDOVER_PORT"))
    rows.append(Row(A, "phone", OK, f"test from the phone: http://{ip}:{p}/ and https://{ip}:{https_port()}/capture"))
    return rows


# ---------------------------------------------------------------- 12. machine health

def win_memory_free_pct() -> Optional[int]:
    """Free physical memory in percent from GlobalMemoryStatusEx, or None."""
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                   [(n, ctypes.c_ulonglong) for n in ("total", "avail", "page_total", "page_avail", "virt_total",
                                                      "virt_avail", "ext_avail")]
    st = MemoryStatus()
    st.dwLength = ctypes.sizeof(MemoryStatus)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
            return None
    except (AttributeError, OSError):
        return None
    return 100 - int(st.dwMemoryLoad)


def check_health(repo: Path = REPO) -> list[Row]:
    if WINDOWS:
        A = "PC"
        rows = [Row(A, "load", SKIP, "no load average on Windows (watch Task Manager)")]
        pct = win_memory_free_pct()
        if pct is None:
            rows.append(Row(A, "memory", SKIP, "GlobalMemoryStatusEx unavailable"))
        else:
            lvl = FAIL if pct < MEM_FAIL_PCT else WARN if pct < MEM_WARN_PCT else OK
            rows.append(Row(A, "memory", lvl, f"{pct}% free", "" if lvl == OK else "quit apps, emulators and browsers"))
        rows.append(Row(A, "thermal", SKIP, "no thermal reading on Windows; keep the laptop on power"))
        rows += _disk_rows(A, repo)
        return rows
    A = "Mac"
    rows = []
    rc, out, _ = run(["sysctl", "-n", "vm.loadavg", "hw.ncpu"], timeout=2)
    nums = re.findall(r"\d+(?:\.\d+)?", out) if rc == 0 else []
    if len(nums) >= 4:
        load1, load5, cores = float(nums[0]), float(nums[1]), int(float(nums[-1]))
        lvl = FAIL if load5 > cores * 3 else WARN if load5 > cores * 1.5 else OK
        rows.append(Row(A, "load", lvl, f"{load1:.1f} now, {load5:.1f} over 5 min, {cores} cores",
                        "" if lvl == OK else "close builds, simulators and other agents"))
    else:
        rows.append(Row(A, "load", SKIP, "sysctl unavailable"))
    rc, out, _ = run(["memory_pressure", "-Q"], timeout=3)
    m = re.search(r"free percentage:\s*(\d+)%", out) if rc == 0 else None
    if m:
        pct = int(m.group(1))
        lvl = FAIL if pct < MEM_FAIL_PCT else WARN if pct < MEM_WARN_PCT else OK
        rows.append(Row(A, "memory", lvl, f"{pct}% free", "" if lvl == OK else "quit apps, simulators and browsers"))
    else:
        rows.append(Row(A, "memory", SKIP, "memory_pressure unavailable"))
    rc, out, _ = run(["pmset", "-g", "therm"], timeout=3)
    if rc != 0:
        rows.append(Row(A, "thermal", SKIP, "pmset unavailable"))
    else:
        limit = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", out)
        level = re.search(r"thermal warning level.*?(\d+)", out, re.I)
        if (limit and int(limit.group(1)) < 100) or (level and "No thermal" not in out):
            rows.append(Row(A, "thermal", WARN, "the Mac is throttling for heat", "let it cool; close heavy apps"))
        else:
            rows.append(Row(A, "thermal", OK, "no thermal warning"))
    return rows + _disk_rows(A, repo)


def _disk_rows(A: str, repo: Path) -> list[Row]:
    try:
        free = shutil.disk_usage(repo).free / 1e9
    except OSError:
        return [Row(A, "disk", SKIP, "could not read disk usage")]
    lvl = FAIL if free < DISK_FAIL_GB else WARN if free < DISK_WARN_GB else OK
    return [Row(A, "disk", lvl, f"{free:.0f} GB free on the repo volume",
                "" if lvl == OK else "remove old build output or raw footage you no longer need")]


# ---------------------------------------------------------------- 13. git

def check_git(repo: Path = REPO, fetch: bool = False) -> list[Row]:
    A = "Git"
    rc, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=3, cwd=repo)
    if rc != 0:
        return [Row(A, "repo", SKIP, "not a git checkout")]
    rows = [Row(A, "branch", OK, branch.strip())]
    rc, out, _ = run(["git", "status", "--porcelain"], timeout=5, cwd=repo)
    n = len([ln for ln in out.splitlines() if ln.strip()]) if rc == 0 else 0
    rows.append(Row(A, "changes", WARN if n else OK, f"{n} uncommitted" if n else "clean",
                    "commit them (small, real messages)" if n else ""))
    fetched = ""
    if fetch:
        frc, _, ferr = run(["git", "fetch", "origin", "main", "--quiet"], timeout=8, cwd=repo)
        fetched = "fetched just now" if frc == 0 else f"fetch failed ({ferr.strip()[:40]})"
    rc, out, _ = run(["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"], timeout=3, cwd=repo)
    nums = out.split()
    if rc != 0 or len(nums) != 2:
        rows.append(Row(A, "origin/main", WARN, "no origin/main to compare", "run with --fetch"))
        return rows
    behind, ahead = int(nums[0]), int(nums[1])
    when = fetched or "last fetch; --fetch to refresh"
    detail = f"{ahead} ahead, {behind} behind ({when})"
    rows.append(Row(A, "origin/main", WARN if behind else OK, detail,
                    "merge origin/main into this branch and run the app once" if behind else ""))
    return rows


# ---------------------------------------------------------------- run and render

def collect(repo: Path = REPO, probe: bool = False, fetch: bool = False) -> list[Row]:
    ip = lan_ip()
    jobs: list[Callable[[], list[Row]]] = [
        lambda: check_python(repo),
        lambda: check_ffmpeg(repo),
        lambda: check_keys(repo),
        lambda: check_budget(repo),
        *([lambda: check_probe(repo)] if probe else []),
        lambda: check_lessons(repo),
        lambda: check_web(repo),
        lambda: check_certs(repo, ip),
        lambda: check_hub(repo, ip),
        lambda: check_ports(repo),
        lambda: check_network(repo, ip),
        lambda: check_health(repo),
        lambda: check_git(repo, fetch),
    ]

    def guarded(job: Callable[[], list[Row]]) -> list[Row]:
        try:
            return job()
        except Exception as e:  # a broken check is a red line, never a crash
            return [Row("Preflight", "internal", FAIL, f"a check crashed: {type(e).__name__}: {str(e)[:80]}",
                        "report this; the other lines are still valid")]

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        results = list(pool.map(guarded, jobs))
    return [row for rows in results for row in rows]


def summarize(rows: list[Row]) -> tuple[str, int, dict]:
    counts = {k: sum(r.status == k for r in rows) for k in (OK, WARN, FAIL, SKIP)}
    if counts[FAIL]:
        return "NOT READY", 1, counts
    if counts[WARN]:
        return "READY WITH WARNINGS", 0, counts
    return "READY", 0, counts


_COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", SKIP: "\033[2m"}


def render(rows: list[Row], color: bool = False, elapsed: float = 0.0) -> str:
    def paint(text: str, status: str) -> str:
        return f"{_COLORS[status]}{text}\033[0m" if color else text

    width = max([5] + [len(r.check) for r in rows])
    out = [f"HandOver preflight  {datetime.now():%Y-%m-%d %H:%M}"]
    area = None
    for r in rows:
        if r.area != area:
            area = r.area
            out.append("")
            out.append(area)
        out.append(f"  {paint(r.status.ljust(4), r.status)}  {r.check.ljust(width)}  {r.detail}".rstrip())
        if r.fix and r.status != OK:
            out.append(f"  {' ' * 4}  {' ' * width}  fix: {r.fix}")
    verdict, _, c = summarize(rows)
    tally = f"{c[OK]} ok, {c[WARN]} warn, {c[FAIL]} fail, {c[SKIP]} skipped, {elapsed:.1f} s"
    status = FAIL if verdict == "NOT READY" else WARN if c[WARN] else OK
    out += ["", f"{paint(verdict, status)}  ({tally})"]
    return "\n".join(out)


def as_json(rows: list[Row], elapsed: float = 0.0) -> dict:
    verdict, code, counts = summarize(rows)
    return {
        "version": 1,
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": verdict,
        "exit_code": code,
        "counts": {k.lower(): v for k, v in counts.items()},
        "elapsed_ms": int(elapsed * 1000),
        "checks": [asdict(r) for r in rows],
    }


def main(argv: Optional[list[str]] = None, repo: Path = REPO) -> int:
    ap = argparse.ArgumentParser(prog="preflight.py", description="HandOver readiness checklist.")
    ap.add_argument("--probe", action="store_true", help="one real check call on two lesson frames (costs money)")
    ap.add_argument("--fetch", action="store_true", help="git fetch origin main before comparing")
    ap.add_argument("--json", action="store_true", help="print JSON")
    ap.add_argument("--no-color", action="store_true", help="plain text even on a terminal")
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    rows = collect(repo, probe=a.probe, fetch=a.fetch)
    elapsed = time.monotonic() - t0
    secrets = secret_values(repo)
    if a.json:
        text = json.dumps(as_json(rows, elapsed), indent=2)
    else:
        color = sys.stdout.isatty() and not a.no_color and not os.environ.get("NO_COLOR")
        text = render(rows, color=color, elapsed=elapsed)
    print(scrub(text, secrets))
    return summarize(rows)[1]


if __name__ == "__main__":
    sys.exit(main())

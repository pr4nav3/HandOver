"""Tests for preflight.py. Run: .venv/bin/python scripts/test_preflight.py

Each check runs against temporary fixtures with external commands monkeypatched. Nothing here
spends money or needs the network; lessons/demo-v1 is only read (copied into temp folders).
"""

import atexit
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
DEMO = REPO / "lessons" / "demo-v1"
sys.path.insert(0, str(SCRIPTS))

import preflight as pf  # noqa: E402

FAKE_KEY = "sk-ant-api03-PREFLIGHT-TEST-NEVER-PRINT-0123456789"
TOUCHED_ENV = ("HANDOVER_LESSONS", "HANDOVER_WEB_DIST", "HANDOVER_CERTS", "HANDOVER_FFMPEG", "HANDOVER_PORT",
               "HANDOVER_HTTPS_PORT", "HANDOVER_CHECK", "HANDOVER_CLAUDE_SPEND_FILE")


@contextlib.contextmanager
def patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


@contextlib.contextmanager
def env(**values):
    """Set (or with None, remove) environment variables; clears the path overrides preflight reads."""
    saved = {k: os.environ.get(k) for k in set(values) | set(TOUCHED_ENV)}
    for k in TOUCHED_ENV:
        os.environ.pop(k, None)
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


def fake_run(table):
    """run() replacement: table maps a command prefix (tuple) to (rc, stdout, stderr). Records calls."""
    calls = []

    def run(cmd, timeout=5.0, cwd=None):
        calls.append(list(cmd))
        for prefix, result in table.items():
            if tuple(cmd[:len(prefix)]) == prefix:
                return result(cmd) if callable(result) else result
        return 127, "", "not found"

    run.calls = calls
    return run


def by_check(rows):
    return {r.check: r for r in rows}


_TEMP: list[str] = []
atexit.register(lambda: [shutil.rmtree(d, ignore_errors=True) for d in _TEMP])


def tmp_repo() -> Path:
    d = tempfile.mkdtemp(prefix="preflight-test-")
    _TEMP.append(d)
    return Path(d)


# ---------------------------------------------------------------- 1. python

LOCK = """# header
fastapi==0.200.0
    # via -r server/requirements.txt
anthropic==1.17.0
colorama==0.4.6 ; sys_platform == 'win32'
google-genai==3.2.0
"""


def venv_repo(lock: str = LOCK) -> Path:
    repo = tmp_repo()
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").write_text("")
    (repo / "server").mkdir()
    (repo / "server" / "requirements.lock").write_text(lock)
    return repo


def env_answer(imports=None, versions=None, python="3.12.4"):
    out = {"python": python, "imports": imports or {m: None for m in pf.IMPORTS},
           "versions": versions or {"fastapi": "0.200.0", "anthropic": "1.17.0", "google-genai": "3.2.0"}}
    return 0, json.dumps(out) + "\n", ""


def test_python_all_match():
    repo = venv_repo()
    with patch(pf, "run", fake_run({(str(repo / ".venv/bin/python"),): env_answer()})):
        rows = by_check(pf.check_python(repo))
    assert rows["venv"].status == pf.OK and "3.12.4" in rows["venv"].detail
    assert rows["imports"].status == pf.OK
    assert rows["lock pins"].status == pf.OK, rows["lock pins"]  # colorama has a marker: absence is fine
    assert "4 packages" in rows["lock pins"].detail


def test_python_drift_and_import_failure():
    repo = venv_repo()
    answer = env_answer(imports={"fastapi": None, "google.genai": "ImportError: boom", "anthropic": None, "PIL": None},
                        versions={"fastapi": "0.201.0", "anthropic": "1.17.0"})
    with patch(pf, "run", fake_run({(str(repo / ".venv/bin/python"),): answer})):
        rows = by_check(pf.check_python(repo))
    assert rows["imports"].status == pf.FAIL and "google.genai" in rows["imports"].detail
    lock = rows["lock pins"]
    assert lock.status == pf.WARN and "fastapi 0.201.0 (lock 0.200.0)" in lock.detail
    assert "google-genai missing" in lock.detail and "requirements.lock" in lock.fix


def test_python_missing_venv():
    rows = pf.check_python(tmp_repo())
    assert rows[0].status == pf.FAIL and "uv venv" in rows[0].fix


def test_parse_lock():
    pins = pf.parse_lock(venv_repo() / "server" / "requirements.lock")
    assert pins["fastapi"] == ("0.200.0", False) and pins["colorama"] == ("0.4.6", True)


# ---------------------------------------------------------------- 2. ffmpeg

def test_ffmpeg_versions_and_override():
    d = tmp_repo()
    (d / "ffmpeg").write_text("")
    (d / "ffprobe").write_text("")
    with env(HANDOVER_FFMPEG=str(d / "ffmpeg")):
        assert pf.find_tool("ffmpeg") == (str(d / "ffmpeg"), "")
        assert pf.find_tool("ffprobe") == (str(d / "ffprobe"), "")
        for text, status in (("ffmpeg version 8.1.2 Copyright", pf.OK), ("ffmpeg version 5.1 x", pf.OK),
                             ("ffmpeg version 4.4.2", pf.FAIL), ("ffmpeg version N-1234-gabc", pf.WARN)):
            with patch(pf, "run", fake_run({(str(d / "ffmpeg"),): (0, text, ""), (str(d / "ffprobe"),): (0, text, "")})):
                rows = by_check(pf.check_ffmpeg())
            assert rows["ffmpeg"].status == status and rows["ffprobe"].status == status, (text, rows)
    with env(HANDOVER_FFMPEG=str(d / "nope")):
        rows = by_check(pf.check_ffmpeg())
        assert rows["ffmpeg"].status == pf.FAIL and "not a file" in rows["ffmpeg"].detail


# ---------------------------------------------------------------- 3. keys

def fake_check(mock=False, prov="claude", key=True):
    return SimpleNamespace(is_mock=lambda: mock, provider=lambda: prov, has_key=lambda: key,
                           active_model=lambda: f"{prov}-model")


def importer(**mods):
    return lambda name: mods.get(name.split(".")[-1])


def test_keys_set_not_set_and_providers():
    repo = tmp_repo()
    (repo / ".env").write_text(f"ANTHROPIC_API_KEY={FAKE_KEY}\nDATABRICKS_HOST=x\n")
    teach = SimpleNamespace(teach_provider=lambda: "claude")
    with env(GEMINI_API_KEY=None, GOOGLE_API_KEY=None, ANTHROPIC_API_KEY=None, DATABRICKS_TOKEN=None,
             DATABRICKS_HOST=None, DATABRICKS_WAREHOUSE_ID=None), \
            patch(pf, "try_import", importer(check=fake_check(), teach=teach)):
        rows = by_check(pf.check_keys(repo))
    assert rows["Claude key"].detail == "set" and rows["Gemini key"].detail == "not set"
    assert rows["Databricks"].status == pf.WARN and "DATABRICKS_TOKEN" in rows["Databricks"].detail
    assert rows["check provider"].status == pf.OK and "claude" in rows["check provider"].detail
    assert "frames only" in rows["teach provider"].detail
    assert FAKE_KEY not in repr(rows)


def test_keys_no_key_mock_and_placeholder_teach():
    repo = tmp_repo()
    teach = SimpleNamespace(teach_provider=lambda: "mock")
    with patch(pf, "try_import", importer(check=fake_check(prov="gemini", key=False), teach=teach)):
        rows = by_check(pf.check_keys(repo))
    assert rows["check provider"].status == pf.FAIL and "Next only" in rows["check provider"].detail
    assert rows["teach provider"].status == pf.WARN
    with patch(pf, "try_import", importer(check=fake_check(mock=True), teach=None)):
        rows = by_check(pf.check_keys(repo))
    assert rows["check provider"].status == pf.WARN and "mock" in rows["check provider"].detail
    assert rows["teach provider"].status == pf.FAIL  # teach.py does not import
    with patch(pf, "try_import", importer(check=fake_check(), teach=SimpleNamespace())):
        assert by_check(pf.check_keys(repo))["teach provider"].status == pf.SKIP  # no provider switch yet


def test_key_never_printed():
    """A real key in the environment and in .env never reaches text or JSON output, even if a row carried it."""
    repo = tmp_repo()
    (repo / ".env").write_text(f"GEMINI_API_KEY={FAKE_KEY}x\n")
    leaky = [pf.Row("Keys", "oops", pf.WARN, f"value {FAKE_KEY} and {FAKE_KEY}x", f"fix {FAKE_KEY}")]
    with env(ANTHROPIC_API_KEY=FAKE_KEY):
        for flag in ([], ["--json"]):
            out = io.StringIO()
            with patch(pf, "collect", lambda *a, **k: leaky + pf.check_keys(repo)), contextlib.redirect_stdout(out):
                pf.main(flag, repo=repo)
            text = out.getvalue()
            assert FAKE_KEY not in text and "[redacted]" in text, text
        # and a real run of every check with the key set
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pf.main(["--json"])
        assert FAKE_KEY not in out.getvalue()


# ---------------------------------------------------------------- 4. budget

def status(day=0.0, total=0.0, day_cap=20.0, total_cap=50.0, blocked=None):
    remaining = 0.0 if blocked == "ledger" else max(0.0, min(day_cap - day, total_cap - total))
    return SimpleNamespace(day_usd=day, total_usd=total, day_cap=day_cap, total_cap=total_cap, day_calls=3,
                           total_calls=9, blocked=blocked, remaining_usd=remaining)


def test_budget_levels():
    assert {r.status for r in pf.budget_rows(status(1, 2), True)} == {pf.OK}
    rows = by_check(pf.budget_rows(status(day=17), True))  # 15% of the day cap left
    assert rows["today"].status == pf.WARN and rows["remaining"].status == pf.WARN
    rows = by_check(pf.budget_rows(status(day=5, total=50, blocked="total"), True))
    assert rows["total"].status == pf.FAIL and rows["remaining"].detail.startswith("$0.00")
    rows = by_check(pf.budget_rows(status(total=50, blocked="total"), False))  # Claude not used: amber only
    assert rows["total"].status == pf.WARN and "not in use" in rows["remaining"].detail
    assert pf.budget_rows(status(blocked="ledger"), True)[0].status == pf.FAIL


def test_budget_skips_without_spend_module():
    with patch(pf, "try_import", lambda name: None):
        rows = pf.check_budget()
    assert rows[0].status == pf.SKIP and "spend.py" in rows[0].detail


def test_budget_reads_a_real_ledger():
    if pf.try_import("server.spend") is None:
        return  # spend.py not merged yet: covered by the skip test
    d = tmp_repo()
    today = datetime.now().astimezone().date().isoformat()
    ledger = {"version": 1, "days": {today: {"usd": 19.0, "calls": 5}}, "total": {"usd": 19.0, "calls": 5}}
    (d / "spend.json").write_text(json.dumps(ledger))
    with env(HANDOVER_CLAUDE_SPEND_FILE=str(d / "spend.json")):
        rows = by_check(pf.check_budget())
    assert rows["today"].status in (pf.WARN, pf.FAIL) and "$19.00 of $20.00" in rows["today"].detail
    assert rows["remaining"].data["remaining_usd"] == 1.0


# ---------------------------------------------------------------- 5. probe

def probe_mods(remaining, calls):
    async def check_frame(ref, live, q, timeout=None):
        calls.append((len(ref), len(live), q, timeout))
        return SimpleNamespace(done="yes", confidence=0.91, latency_ms=812, cost_usd=0.00021, error=None)

    check = fake_check()
    check.check_frame = check_frame
    return importer(check=check, spend=SimpleNamespace(status=lambda: status(day=20 - remaining)))


def lessons_repo(*ids) -> Path:
    repo = tmp_repo()
    (repo / "lessons").mkdir()
    for lid in ids:
        shutil.copytree(DEMO, repo / "lessons" / lid)
    return repo


def test_probe_refuses_under_one_dollar():
    calls = []
    with env(), patch(pf, "try_import", probe_mods(0.5, calls)):
        rows = pf.check_probe(lessons_repo("demo-v1"))
    assert rows[0].status == pf.FAIL and "refused" in rows[0].detail and calls == []


def test_probe_reports_latency_cost_and_result():
    calls = []
    with env(), patch(pf, "try_import", probe_mods(5.0, calls)):
        rows = pf.check_probe(lessons_repo("demo-v1"))
    r = rows[0]
    assert r.status == pf.OK and "812 ms" in r.detail and "yes 0.91" in r.detail and "$0.0002" in r.detail, r
    assert len(calls) == 1 and calls[0][3] == 10


def test_probe_frames_are_two_different_frames():
    ref, live, q = pf.probe_frames(lessons_repo("demo-v1") / "lessons")
    assert ref != live and ref.is_file() and live.is_file() and q


# ---------------------------------------------------------------- 6. lessons

def test_lessons_sample_missing_is_red():
    repo = lessons_repo("demo-v1")
    (repo / "lessons" / "templates").mkdir()
    with env():
        rows = by_check(pf.check_lessons(repo))
    assert rows["demo-v1"].status in (pf.OK, pf.WARN) and "OK" in rows["demo-v1"].detail
    assert rows["templates"].status == pf.SKIP
    for lid in pf.SAMPLE_LESSONS:
        r = rows[f"sample {lid}"]
        assert r.status == pf.FAIL and "scripts/new_lesson.sh" in r.fix


def test_lessons_sample_present_and_broken_lesson_fails():
    repo = lessons_repo(*pf.SAMPLE_LESSONS, "front-wheel-v1")
    (repo / "lessons" / "front-wheel-v1" / "clips" / "02.mp4").unlink()
    with env():
        rows = by_check(pf.check_lessons(repo))
    assert rows["sample fortune-teller-v1"].status == pf.OK
    assert rows["front-wheel-v1"].status == pf.FAIL and "lesson_lint.py" in rows["front-wheel-v1"].fix


def test_lessons_honors_handover_lessons():
    repo = lessons_repo()
    other = lessons_repo("fortune-teller-v1") / "lessons"
    with env(HANDOVER_LESSONS=str(other)):
        rows = by_check(pf.check_lessons(repo))
    assert rows["sample fortune-teller-v1"].status == pf.OK


# ---------------------------------------------------------------- 7. web

def web_repo(with_asset=True) -> Path:
    repo = tmp_repo()
    dist, src = repo / "web" / "dist", repo / "web" / "src"
    (dist / "assets").mkdir(parents=True)
    src.mkdir(parents=True)
    (src / "App.tsx").write_text("x")
    old = time.time() - 100
    os.utime(src / "App.tsx", (old, old))
    (dist / "index.html").write_text('<script src="/assets/a.js"></script><link href="/assets/a.css">'
                                     '<link rel="icon" href="data:,">')
    (dist / "assets" / "a.css").write_text("")
    if with_asset:
        (dist / "assets" / "a.js").write_text("")
    return repo


def test_web_ok_missing_asset_and_stale():
    with env():
        rows = by_check(pf.check_web(web_repo()))
        assert rows["build"].status == pf.OK and rows["fresh"].status == pf.OK
        rows = by_check(pf.check_web(web_repo(with_asset=False)))
        assert rows["build"].status == pf.FAIL and "/assets/a.js" in rows["build"].detail
        repo = web_repo()
        (repo / "web" / "src" / "App.tsx").write_text("newer")
        future = time.time() + 60
        os.utime(repo / "web" / "src" / "App.tsx", (future, future))
        rows = by_check(pf.check_web(repo))
        assert rows["fresh"].status == pf.WARN and "App.tsx" in rows["fresh"].detail
        assert pf.check_web(tmp_repo())[0].status == pf.FAIL
        alt = web_repo()
        with env(HANDOVER_WEB_DIST=str(alt / "web" / "dist")):
            assert pf.check_web(tmp_repo())[0].status == pf.OK


# ---------------------------------------------------------------- 8. certs

def cert_repo() -> Path:
    repo = tmp_repo()
    (repo / "certs").mkdir()
    (repo / "certs" / "cert.pem").write_text("cert")
    (repo / "certs" / "key.pem").write_text("key")
    return repo


def openssl(san_ips=("10.0.0.5", "127.0.0.1"), days=300, ext_ok=True):
    end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%b %d %H:%M:%S %Y GMT")
    san = "X509v3 Subject Alternative Name: \n    " + ", ".join(f"IP Address:{ip}" for ip in san_ips) + ", DNS:localhost"
    return fake_run({
        ("openssl", "x509", "-noout", "-ext"): (0, san, "") if ext_ok else (1, "", "unknown option -ext"),
        ("openssl", "x509", "-noout", "-text"): (0, "Certificate:\n " + san, ""),
        ("openssl", "x509", "-noout", "-enddate"): (0, f"notAfter={end}\n", ""),
    })


def test_certs_cases():
    repo = cert_repo()
    with env():
        with patch(pf, "run", openssl()):
            rows = by_check(pf.check_certs(repo, "10.0.0.5"))
        assert [rows[k].status for k in ("certs", "cert IP", "cert expiry")] == [pf.OK] * 3
        with patch(pf, "run", openssl()):
            r = by_check(pf.check_certs(repo, "192.168.1.9"))["cert IP"]
        assert r.status == pf.FAIL and "192.168.1.9" in r.detail and pf.CERTS_FIX in r.fix
        with patch(pf, "run", openssl(days=-2)):
            assert by_check(pf.check_certs(repo, "10.0.0.5"))["cert expiry"].status == pf.FAIL
        with patch(pf, "run", openssl(days=3)):
            assert by_check(pf.check_certs(repo, "10.0.0.5"))["cert expiry"].status == pf.WARN
        with patch(pf, "run", openssl(ext_ok=False)):  # LibreSSL: falls back to -text
            assert by_check(pf.check_certs(repo, "10.0.0.5"))["cert IP"].status == pf.OK
        rows = pf.check_certs(tmp_repo(), "10.0.0.5")
        assert rows[0].status == pf.FAIL and "mkcert" in rows[0].fix


# ---------------------------------------------------------------- 9. hub

def test_hub_not_running():
    with env(), patch(pf, "hub_running", lambda p: False):
        rows = pf.check_hub()
    assert rows[0].status == pf.SKIP and pf.RUN_HUB in rows[0].fix


def test_hub_state_rows():
    state = {"type": "state", "lesson_id": "fortune-teller-v1", "step": 3, "total": 8, "status": "watching",
             "camera_connected": True, "camera": {"name": "Replay: fold.mp4", "platform": "replay", "source": "file"},
             "check_offline": True, "check_offline_reason": "rate_limited"}
    with env(HANDOVER_PORT="8040"), patch(pf, "hub_running", lambda p: p == 8040), \
            patch(pf, "http_json", lambda url, timeout=1.5: [{"id": "fortune-teller-v1"}]), \
            patch(pf, "read_state", lambda url, timeout=2.0: state):
        rows = by_check(pf.check_hub(ip="10.0.0.5"))
    assert rows["hub"].status == pf.OK and "8040" in rows["hub"].detail and "1 lesson:" in rows["hub"].detail
    assert rows["lesson"].detail.startswith("fortune-teller-v1, step 4 of 8")
    assert rows["camera"].status == pf.WARN and "Recording" in rows["camera"].detail
    assert rows["checks"].status == pf.WARN and "rate_limited" in rows["checks"].detail
    state.update(camera_connected=False, camera=None, check_offline=False)
    with patch(pf, "hub_running", lambda p: True), patch(pf, "http_json", lambda url, timeout=1.5: []), \
            patch(pf, "read_state", lambda url, timeout=2.0: state):
        rows = by_check(pf.check_hub(ip="10.0.0.5"))
    assert rows["camera"].status == pf.WARN and "10.0.0.5" in rows["camera"].fix
    assert rows["checks"].status == pf.OK


# ---------------------------------------------------------------- 10. network

def test_network():
    with env():
        assert pf.check_network(ip=None)[0].status == pf.FAIL
        with patch(pf, "hub_running", lambda p: False), patch(pf, "can_bind", lambda h, p: True):
            rows = by_check(pf.check_network(ip="10.0.0.5"))
        assert rows["port"].status == pf.OK and "phone" in rows
        with patch(pf, "hub_running", lambda p: False), patch(pf, "can_bind", lambda h, p: False):
            assert by_check(pf.check_network(ip="10.0.0.5"))["port"].status == pf.FAIL
        with patch(pf, "hub_running", lambda p: True), patch(pf, "can_connect", lambda h, p: True):
            assert by_check(pf.check_network(ip="10.0.0.5"))["port"].status == pf.OK


def test_lan_ip_fallbacks():
    with patch(pf, "WINDOWS", False):
        _lan_ip_mac()
    with patch(pf, "WINDOWS", True), patch(pf, "route_ip", lambda: "172.20.10.2"):
        assert pf.lan_ip() == "172.20.10.2"


def _lan_ip_mac():
    run = fake_run({("ipconfig", "getifaddr", "en0"): (1, "", ""),
                    ("ipconfig", "getifaddr", "en1"): (0, "172.20.10.2\n", "")})
    with patch(pf, "run", run):
        assert pf.lan_ip() == "172.20.10.2"
    run = fake_run({("ifconfig",): (0, "inet 127.0.0.1 netmask\ninet 192.168.4.7 netmask", "")})
    with patch(pf, "run", run):
        assert pf.lan_ip() == "192.168.4.7"


# ---------------------------------------------------------------- 11. mac health

def test_health():
    with patch(pf, "WINDOWS", False):
        _health_mac()
    with patch(pf, "WINDOWS", True), patch(pf, "win_memory_free_pct", lambda: 8):
        rows = by_check(pf.check_health(REPO))
    assert rows["memory"].status == pf.FAIL and rows["load"].status == rows["thermal"].status == pf.SKIP
    assert rows["disk"].status in (pf.OK, pf.WARN, pf.FAIL)


def _health_mac():
    good = fake_run({("sysctl",): (0, "{ 3.1 2.9 2.5 }\n18\n", ""),
                     ("memory_pressure",): (0, "System-wide memory free percentage: 64%", ""),
                     ("pmset",): (0, "Note: No thermal warning level has been recorded", "")})
    with patch(pf, "run", good):
        rows = by_check(pf.check_health(REPO))
    assert [rows[k].status for k in ("load", "memory", "thermal", "disk")] == [pf.OK] * 4
    bad = fake_run({("sysctl",): (0, "{ 40.0 35.0 30.0 }\n18\n", ""),
                    ("memory_pressure",): (0, "System-wide memory free percentage: 8%", ""),
                    ("pmset",): (0, "CPU_Scheduler_Limit = 100\nCPU_Speed_Limit = 70\n", "")})
    with patch(pf, "run", bad):
        rows = by_check(pf.check_health(REPO))
    assert rows["load"].status == pf.WARN and rows["memory"].status == pf.FAIL and rows["thermal"].status == pf.WARN
    with patch(pf, "run", fake_run({})):
        rows = by_check(pf.check_health(REPO))
    assert rows["load"].status == rows["memory"].status == rows["thermal"].status == pf.SKIP


# ---------------------------------------------------------------- ports

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       42320
  TCP    0.0.0.0:8443           0.0.0.0:0              LISTENING       42320
  TCP    127.0.0.1:8000         127.0.0.1:51000        ESTABLISHED     9999
  TCP    0.0.0.0:18000          0.0.0.0:0              LISTENING       7
"""
STALE = r'"C:\Python312\python.exe" -m server.main'


def test_ports_name_a_stale_listener():
    run = fake_run({("netstat",): (0, NETSTAT, ""), ("powershell",): (0, STALE + "\n", "")})
    with env(), patch(pf, "WINDOWS", True), patch(pf, "run", run):
        assert pf.listener_pids(8000) == [42320] and pf.listener_pids(18) == []
        rows = by_check(pf.check_ports(REPO))
    for name, p in (("http port", "8000"), ("https port", "8443")):
        r = rows[name]
        assert r.status == pf.WARN and p in r.detail and "PID 42320" in r.detail, r
        assert "python.exe -m server.main" in r.detail and "Stop-Process -Id 42320" in r.fix
    assert sum(c[0] == "powershell" for c in run.calls) == 1  # one lookup per PID
    ours = f'"{REPO / ".venv" / "Scripts" / "python.exe"}" -m server.main'
    with env(), patch(pf, "WINDOWS", True), \
            patch(pf, "run", fake_run({("netstat",): (0, NETSTAT, ""), ("powershell",): (0, ours, "")})):
        assert by_check(pf.check_ports(REPO))["http port"].status == pf.OK
    with env(HANDOVER_PORT="8061", HANDOVER_HTTPS_PORT="8062"), patch(pf, "WINDOWS", False), \
            patch(pf, "run", fake_run({("lsof",): (1, "", "")})):
        rows = by_check(pf.check_ports(REPO))
    assert rows["http port"].status == rows["https port"].status == pf.OK
    with env(), patch(pf, "WINDOWS", False), \
            patch(pf, "run", fake_run({("lsof",): (0, "501\n", ""), ("ps",): (0, "/usr/bin/nc -l 8000\n", "")})):
        r = by_check(pf.check_ports(REPO))["http port"]
    assert r.status == pf.WARN and "PID 501: nc -l 8000 (in /usr/bin)" in r.detail and "kill 501" in r.fix


# ---------------------------------------------------------------- 12. git

def test_git():
    table = {("git", "rev-parse"): (0, "feature/server\n", ""), ("git", "status"): (0, " M a.py\n?? b.py\n", ""),
             ("git", "rev-list"): (0, "2\t5\n", ""), ("git", "fetch"): (0, "", "")}
    run = fake_run(table)
    with patch(pf, "run", run):
        rows = by_check(pf.check_git(REPO))
    assert rows["branch"].detail == "feature/server" and rows["changes"].detail == "2 uncommitted"
    assert rows["origin/main"].status == pf.WARN and "5 ahead, 2 behind" in rows["origin/main"].detail
    assert not any(c[:2] == ["git", "fetch"] for c in run.calls)
    run = fake_run(table)
    with patch(pf, "run", run):
        rows = by_check(pf.check_git(REPO, fetch=True))
    assert any(c[:2] == ["git", "fetch"] for c in run.calls) and "fetched just now" in rows["origin/main"].detail


# ---------------------------------------------------------------- output

def test_summary_and_exit_codes():
    ok = [pf.Row("A", "x", pf.OK, ""), pf.Row("A", "y", pf.SKIP, "")]
    assert pf.summarize(ok)[:2] == ("READY", 0)
    assert pf.summarize(ok + [pf.Row("A", "z", pf.WARN, "")])[:2] == ("READY WITH WARNINGS", 0)
    assert pf.summarize(ok + [pf.Row("A", "z", pf.FAIL, "")])[:2] == ("NOT READY", 1)


def test_json_shape():
    rows = [pf.Row("Keys", "Claude key", pf.OK, "set"), pf.Row("Web", "fresh", pf.WARN, "old", "rebuild")]
    out = io.StringIO()
    with patch(pf, "collect", lambda *a, **k: rows), contextlib.redirect_stdout(out):
        code = pf.main(["--json"])
    d = json.loads(out.getvalue())
    assert code == 0 and d["summary"] == "READY WITH WARNINGS" and d["exit_code"] == 0 and d["version"] == 1
    assert d["counts"] == {"ok": 1, "warn": 1, "fail": 0, "skip": 0}
    assert set(d["checks"][0]) == {"area", "check", "status", "detail", "fix", "data"}
    assert isinstance(d["elapsed_ms"], int) and d["generated"]


def test_text_render_aligned_and_fix_lines():
    rows = [pf.Row("Keys", "Claude key", pf.OK, "set"), pf.Row("Web", "fresh", pf.WARN, "old", "rebuild")]
    text = pf.render(rows)
    assert "\nKeys\n" in text and "\nWeb\n" in text and "fix: rebuild" in text
    assert text.splitlines()[-1].startswith("READY WITH WARNINGS")
    lines = [ln for ln in text.splitlines() if ln.startswith("  OK") or ln.startswith("  WARN")]
    assert len({ln.index("set") if "set" in ln else ln.index("old") for ln in lines}) == 1  # one detail column


def test_crashing_check_is_a_red_line():
    def boom(repo=None):
        raise RuntimeError("kaput")

    with patch(pf, "check_web", boom):
        rows = pf.collect(REPO)
    assert any(r.status == pf.FAIL and "kaput" in r.detail for r in rows)


def test_no_dashes_in_source():
    text = (SCRIPTS / "preflight.py").read_text(encoding="utf-8")
    assert "—" not in text and "–" not in text


def test_real_run_is_fast_and_dash_free():
    out = io.StringIO()
    t0 = time.monotonic()
    with contextlib.redirect_stdout(out):
        code = pf.main(["--no-color"])
    elapsed = time.monotonic() - t0
    text = out.getvalue()
    assert elapsed < 10, elapsed
    assert code in (0, 1) and text.splitlines()[-1].split("  ")[0] in ("READY", "READY WITH WARNINGS", "NOT READY")
    assert "—" not in text and "–" not in text and "\033[" not in text


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok", name)
            except Exception:
                failed += 1
                import traceback
                traceback.print_exc()
                print("FAIL", name)
    sys.exit(1 if failed else 0)

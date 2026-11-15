"""Tests for databricks_setup.py. Run: .venv/bin/python scripts/test_databricks_setup.py

Offline only: every HTTP call goes to a fake transport, sleep is a no-op, and urllib.request.urlopen is
replaced by a function that fails the test if anything reaches the network.
"""

import contextlib
import io
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import databricks_setup as ds  # noqa: E402

TOKEN = "dapi0123456789abcdef0123456789abcdef-NEVER-PRINT"
BAD_TOKEN = "f" * 64  # not a personal access token
HOST = "https://dbc-test-0000.cloud.databricks.com"
WAREHOUSE = "abcdef0123456789"

SETUP_SQL = """-- header; with a semicolon in a comment
CREATE SCHEMA IF NOT EXISTS workspace.handover
  COMMENT 'HandOver: lessons; and runs';
CREATE TABLE IF NOT EXISTS workspace.handover.events (
  event_id STRING COMMENT 'it''s a uuid',
  extra    STRING COMMENT 'JSON -- not a comment'
);
CREATE VOLUME IF NOT EXISTS workspace.handover.lessons COMMENT 'files';
SHOW TABLES IN workspace.handover;
SELECT (SELECT count(*) FROM workspace.handover.events) AS events;
"""


@contextlib.contextmanager
def patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def no_network(*a, **k):
    raise AssertionError("network call attempted")


class FakeHttp:
    """Answers the Warehouses and Statement Execution endpoints; records every call (with headers)."""

    def __init__(self, states=("RUNNING",), status=200, body=None, fail_sql=None, catalogs=(("workspace",),)):
        self.states = list(states)
        self.status, self.body, self.fail_sql, self.catalogs = status, body, fail_sql, catalogs
        self.calls = []
        self.statements = []
        self.started = False

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        if self.status != 200:
            return self.status, json.dumps(self.body or {}).encode()
        path = url[len(HOST):]
        if "/sql/warehouses/" in path and method == "GET":
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return 200, json.dumps({"name": "Serverless Starter Warehouse", "state": state}).encode()
        if path.endswith("/start"):
            self.started = True
            return 200, b"{}"
        if path == "/api/2.0/sql/statements":
            req = json.loads(body)
            stmt = req["statement"]
            self.statements.append((stmt, req.get("parameters")))
            if self.fail_sql and self.fail_sql in stmt:
                return 200, json.dumps({"statement_id": "s1", "status": {"state": "FAILED", "error": {
                    "error_code": "BAD", "message": f"boom {TOKEN}"}}}).encode()
            rows = [["0"] * 6]
            if stmt.startswith("SELECT current_catalog"):
                rows = [["workspace", "someone@example.com"]]
            elif stmt.startswith("SHOW CATALOGS"):
                rows = [list(c) for c in self.catalogs]
            elif stmt.startswith("SHOW VOLUMES"):
                rows = [["handover", "lessons"]]
            return 200, json.dumps({"statement_id": "s1", "status": {"state": "SUCCEEDED"},
                                    "result": {"data_array": rows}}).encode()
        return 404, b'{"error_code":"NOT_FOUND","message":"no route"}'


class FakeDb:
    """Stands in for server.databricks: counts uploads, flush always drains."""

    def __init__(self, target="workspace.handover"):
        self.target, self.uploaded, self.lessons = target, 0, []

    def status(self):
        return {"enabled": True, "config_error": None, "target": self.target, "uploaded_files": self.uploaded,
                "last_error": None}

    def upload_lesson_files(self, d, lesson_id):
        self.lessons.append(lesson_id)
        self.uploaded += ds.count_lesson_files(Path(d))

    def flush(self, timeout=10.0):
        return True


def make_env(tmp: Path, token=TOKEN, **extra) -> Path:
    lines = [f"DATABRICKS_HOST={HOST}", f"DATABRICKS_TOKEN={token}", f"DATABRICKS_WAREHOUSE_ID={WAREHOUSE}"]
    lines += [f"{k}={v}" for k, v in extra.items()]
    p = tmp / ".env"
    p.write_text("\n".join(lines) + "\n")
    return p


def make_lessons(tmp: Path) -> Path:
    root = tmp / "lessons"
    for lid in ("real-one", "demo-v1", "recut-me", "e2e-abc"):
        d = root / lid
        (d / "frames").mkdir(parents=True)
        (d / "lesson.json").write_text(json.dumps({"id": lid, "title": lid, "steps": []}))
        (d / "frames" / "01.jpg").write_bytes(b"x")
    (root / "templates").mkdir()
    return root


def ev(event_id, run_id, lesson="real-one", kind="advance", extra=None, ts="2026-11-14T22:00:00.000Z"):
    return json.dumps({"event_id": event_id, "run_id": run_id, "lesson_id": lesson, "kind": kind, "ts": ts,
                       "step": 0, "extra": json.dumps(extra) if extra else None})


def run_main(argv, http=None, env_file=None, environ=None, db=None, events=None, lessons=None):
    out = io.StringIO()
    tmp = Path(tempfile.mkdtemp())
    with patch(urllib.request, "urlopen", no_network):
        code = ds.main(argv, transport=http or FakeHttp(), sleep=lambda s: None,
                       env_file=env_file or make_env(tmp), environ=environ if environ is not None else {},
                       db=db or FakeDb(), events_path=events or tmp / "none.jsonl",
                       lessons_root=lessons or make_lessons(tmp), stream=out)
    return code, out.getvalue()


# ---------------------------------------------------------------- SQL handling

def test_split_sql_respects_quotes_and_comments():
    stmts = ds.split_sql(SETUP_SQL)
    assert len(stmts) == 5, stmts
    assert "lessons; and runs" in stmts[0]
    assert "it''s a uuid" in stmts[1] and "JSON -- not a comment" in stmts[1]
    assert not any("header" in s for s in stmts)


def test_setup_statements_substitute_catalog_and_schema():
    cfg = {"catalog": "cat_a", "schema": "sch_b"}
    stmts = ds.setup_statements(SETUP_SQL, cfg)
    assert [s.split()[1] for s in stmts] == ["SCHEMA", "TABLE", "VOLUME"]
    assert all("workspace.handover" not in s for s in stmts)
    assert "`cat_a`.`sch_b`.events" in stmts[1] and stmts[0].startswith("CREATE SCHEMA IF NOT EXISTS `cat_a`.`sch_b`")
    sql = ds.substitute("read_files('/Volumes/workspace/handover/lessons/*/lesson.json') workspace.handoverx", cfg)
    assert "/Volumes/cat_a/sch_b/lessons/" in sql and "workspace.handoverx" in sql


def test_real_sql_files_parse_and_every_filter_edit_applies():
    text, _ = ds.read_source("01_setup.sql")
    if text is not None:
        stmts = ds.setup_statements(text, {"catalog": "workspace", "schema": "handover"})
        assert len(stmts) == 6 and stmts[-1].startswith("CREATE VOLUME"), [ds.head(s) for s in stmts]
    text, _ = ds.read_source("02_dashboard_datasets.sql")
    if text is None:
        print("  (02_dashboard_datasets.sql not available; skipped)")
        return
    datasets = ds.parse_datasets(text)
    assert len(datasets) == 13 and "ds_check_offline" in datasets
    views = ds.view_statements(datasets, {"catalog": "c", "schema": "s"})
    assert len(views) == 26 and all(err is None for _, _, err in views), [e for _, _, e in views if e]
    real = {n: s for n, s, _ in views}
    assert "e.reason IS NOT NULL" in real["ds_check_offline_real"]
    assert "'$.error_kind') = 'timeout'" in real["ds_checks_real"]
    assert "e.done = 'unsure' AND e.confidence = 0" not in real["ds_checks_real"]
    assert "<> 'mock'" in real["ds_check_latency_by_step_real"]
    assert real["ds_check_latency_overall_real"].count("<> 'mock'") == 2
    for n, s in real.items():
        if n.endswith("_real"):
            assert "`c`.`s`.events " not in s and "`c`.`s`.runs " not in s, n
            assert "workspace.handover" not in s
    assert "`c`.`s`.events_real" in real["ds_runs_real"] and "`c`.`s`.runs_real" in real["ds_runs_real"]
    assert "`c`.`s`.events_real" not in real["ds_runs"]


def test_filter_edit_missing_is_reported_not_guessed():
    views = ds.view_statements({"ds_checks": "SELECT 1 FROM workspace.handover.events"},
                               {"catalog": "c", "schema": "s"})
    assert views[0][1] and views[1][1] is None and "changed" in views[1][2]


def test_filter_views_exclude_replay_mock_selftest():
    sql = "\n".join(s for _, s in ds.filter_views({"catalog": "c", "schema": "s"}))
    assert "= 'file'" in sql and "'$.check_mode') = 'mock'" in sql and "'selftest'" in sql
    assert "LEFT ANTI JOIN `c`.`s`.`runs_excluded`" in sql


# ---------------------------------------------------------------- event filters

def test_filter_events_drops_mock_replay_tests_and_no_run_id():
    lines = [
        ev("a1", "r1", kind="run_start", extra={"learner": "ana"}),
        ev("a2", "r1", kind="advance", ts="2026-11-14T22:00:05.000Z"),
        ev("a3", "r1", kind="run_end", ts="2026-11-14T22:00:09.000Z"),
        ev("a2", "r1"),  # duplicate event_id
        ev("b1", "r2", kind="run_start", extra={"source": "file"}),
        ev("b2", "r2"),
        ev("c1", "r3", kind="run_start", extra={"check_mode": "mock"}),
        ev("c2", "r4", kind="check", extra={"model": "mock", "error_kind": None}),
        ev("c3", "r4", kind="advance"),
        ev("c4", "r5", kind="mistake", extra={"source": "mock"}),
        ev("d1", "r6", lesson="recut-me"), ev("d2", "r6", lesson="delete-me"),
        ev("d3", "r6", lesson="test-upload"), ev("d4", "r6", lesson="e2e-xyz"),
        ev("e1", None), ev("e2", ""),
        "not json", "", json.dumps({"no": "id"}),
    ]
    kept, c = ds.filter_events(lines)
    assert [e["event_id"] for e in kept] == ["a1", "a2", "a3"], kept
    assert c == {"read": 18, "unreadable": 2, "no_run_id": 2, "test_lesson": 4, "replay": 2, "mock": 4,
                 "kept": 3}, c
    assert set(kept[0]) == set(ds.EVENT_COLS)
    runs = ds.runs_from_events(kept)
    assert runs == [{"run_id": "r1", "lesson_id": "real-one", "learner": "ana",
                     "started_at": "2026-11-14T22:00:00.000Z", "ended_at": "2026-11-14T22:00:09.000Z"}]


def test_real_lessons_skip_demo_and_test_ids():
    root = make_lessons(Path(tempfile.mkdtemp()))
    assert [d.name for d in ds.real_lessons(root)] == ["real-one"]


def test_env_file_rules_match_server_module():
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".env").write_text(f'export DATABRICKS_HOST=dbc-x.cloud.databricks.com/ # workspace\n'
                              f'DATABRICKS_TOKEN="{TOKEN}"\n# comment\nDATABRICKS_WAREHOUSE_ID={WAREHOUSE}\n')
    cfg = ds.load_config(tmp / ".env", {})
    assert cfg["host"] == "https://dbc-x.cloud.databricks.com" and cfg["token"] == TOKEN
    assert cfg["warehouse"] == WAREHOUSE and cfg["catalog"] == "workspace" and cfg["schema"] == "handover"
    bad, warn = ds.config_problems(cfg)
    assert bad == [] and any("https://" in w for w in warn)
    cfg = ds.load_config(tmp / ".env", {"DATABRICKS_HOST": "https://x.cloud.databricks.com/?o=1",
                                        "DATABRICKS_WAREHOUSE_ID": "/sql/1.0/warehouses/abc"})
    bad, _ = ds.config_problems(cfg)
    assert any("?o=" in b for b in bad) and any("after /warehouses/" in b for b in bad)


# ---------------------------------------------------------------- full runs on the fake HTTP layer

def test_full_setup_on_fake_http():
    http, db = FakeHttp(), FakeDb()
    code, out = run_main([], http=http, db=db)
    assert code == 0, out
    stmts = [s for s, _ in http.statements]
    assert stmts[0].startswith("SELECT current_catalog") and stmts[1].startswith("SHOW CATALOGS")
    assert any(s.startswith("CREATE OR REPLACE VIEW `workspace`.`handover`.`events_real`") for s in stmts)
    assert not any(s.startswith("MERGE") for s in stmts), "history must not upload by default"
    assert db.lessons == ["real-one"]
    assert "All steps ok." in out and "SELECT * FROM workspace.handover.ds_runs_real" in out
    assert f"{HOST}/explore/data/workspace/handover" in out
    assert TOKEN not in out and "dapi" not in out
    assert all(c[2]["Authorization"] == f"Bearer {TOKEN}" for c in http.calls)


def test_with_history_merges_filtered_events_in_batches():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "events.jsonl"
    lines = [ev(f"k{i}", f"run{i % 3}", ts=f"2026-11-14T22:{i // 60:02d}:{i % 60:02d}.000Z") for i in range(1200)]
    lines += [ev("m1", "mockrun", kind="check", extra={"model": "mock"}), ev("t1", "x", lesson="e2e-1")]
    path.write_text("\n".join(lines) + "\n")
    http = FakeHttp()
    code, out = run_main(["--with-history"], http=http, events=path)
    assert code == 0, out
    merges = [(s, p) for s, p in http.statements if s.startswith("MERGE")]
    assert len(merges) == 1 + 3  # one runs batch, 1200 events in batches of 500
    assert "ON t.`event_id` = s.`event_id` WHEN NOT MATCHED" in merges[1][0]
    sent = [r["event_id"] for _, p in merges[1:] for r in json.loads(p[0]["value"])]
    assert len(sent) == 1200 and "m1" not in sent and "t1" not in sent
    assert "1200 real events in 3 runs kept; left out 1 mock, 0 replay, 1 test lesson" in out


def test_warehouse_is_started_and_waited_for():
    http = FakeHttp(states=["STOPPED", "STARTING", "STARTING", "RUNNING"])
    code, out = run_main(["--skip-lessons"], http=http)
    assert code == 0 and http.started and "starting it" in out and "RUNNING" in out, out


def test_warehouse_timeout_stops_cleanly():
    http = FakeHttp(states=["STARTING"])
    t = [0.0]

    def clock():
        t[0] += 30
        return t[0]

    out = io.StringIO()
    tmp = Path(tempfile.mkdtemp())
    with patch(ds.time, "monotonic", clock), patch(urllib.request, "urlopen", no_network):
        code = ds.main(["--warehouse-timeout", "60"], transport=http, sleep=lambda s: None,
                       env_file=make_env(tmp), environ={}, db=FakeDb(), stream=out)
    text = out.getvalue()
    assert code == 1 and "still STARTING after 60 s" in text and "Stopped" in text, text
    assert len(http.calls) < 10


def test_401_with_non_pat_token_says_create_a_pat_once():
    tmp = Path(tempfile.mkdtemp())
    http = FakeHttp(status=401, body={"error_code": "401", "message": f"Credential was not sent {BAD_TOKEN}"})
    code, out = run_main([], http=http, env_file=make_env(tmp, token=BAD_TOKEN))
    assert code == 1
    assert ("token rejected: create a personal access token (starts with dapi) under User Settings > "
            "Developer > Access tokens") in out, out
    assert BAD_TOKEN not in out
    assert len(http.calls) == 1, "one validation attempt, no retries"


def test_token_never_printed_even_in_errors():
    for http in (FakeHttp(status=403, body={"message": f"token {TOKEN} lacks scope"}),
                 FakeHttp(fail_sql="CREATE TABLE"), FakeHttp(status=500, body={"message": f"Bearer {TOKEN}"})):
        code, out = run_main([], http=http)
        assert code != 0 and TOKEN not in out and TOKEN[4:20] not in out, out
    code, out = run_main(["--check"])
    assert TOKEN not in out and "value hidden" in out


def test_failed_statement_is_reported_and_run_continues():
    code, out = run_main([], http=FakeHttp(fail_sql="CREATE TABLE"))
    assert code == 1 and "FAIL schema, tables, Volume" in out and "Failed: schema, tables, Volume" in out
    assert "skipped: tables or Volume not ready" in out


def test_missing_catalog_is_created():
    http = FakeHttp(catalogs=())
    code, out = run_main(["--skip-lessons"], http=http)
    assert code == 0 and any(s.startswith("CREATE CATALOG IF NOT EXISTS `workspace`") for s, _ in http.statements)


def test_teardown_runs_cleanup_file_only():
    text, _ = ds.read_source("04_cleanup_test_data.sql")
    if text is None:
        print("  (04_cleanup_test_data.sql not available; skipped)")
        return
    http = FakeHttp()
    code, out = run_main(["--teardown-test-data"], http=http)
    stmts = [s for s, _ in http.statements]
    assert code == 0, out
    assert sum(s.startswith("DELETE FROM `workspace`.`handover`.") for s in stmts) == 6
    assert not any(s.startswith(("CREATE", "MERGE")) for s in stmts)


# ---------------------------------------------------------------- --check

def test_check_makes_no_requests_and_lists_what_is_missing():
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".env").write_text("OTHER=1\n")
    http = FakeHttp()
    code, out = run_main(["--check"], http=http, env_file=tmp / ".env")
    assert code == 1 and http.calls == [], out
    for name in ("DATABRICKS_HOST is not set", "DATABRICKS_TOKEN is not set", "DATABRICKS_WAREHOUSE_ID is not set"):
        assert name in out, out
    assert "NOT READY" in out
    code, out = run_main(["--check"], http=http, env_file=tmp / "missing.env")
    assert code == 1 and "does not exist" in out and http.calls == []


def test_check_ready_and_warns_on_non_pat_token():
    tmp = Path(tempfile.mkdtemp())
    http = FakeHttp()
    code, out = run_main(["--check"], http=http)
    assert code == 0 and "READY" in out and http.calls == []
    code, out = run_main(["--check"], http=http, env_file=make_env(tmp, token=BAD_TOKEN))
    assert code == 0 and "READY WITH WARNINGS" in out and "starts with dapi" in out and BAD_TOKEN not in out


def test_bad_config_stops_before_any_request():
    tmp = Path(tempfile.mkdtemp())
    http = FakeHttp()
    code, out = run_main([], http=http, env_file=make_env(tmp, DATABRICKS_SCHEMA="bad-name"))
    assert code == 2 and http.calls == [] and "DATABRICKS_SCHEMA" in out


def test_no_dashes_in_sources():
    for f in ("databricks_setup.py", "test_databricks_setup.py"):
        text = (SCRIPTS / f).read_text(encoding="utf-8")
        assert chr(0x2014) not in text and chr(0x2013) not in text, f


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

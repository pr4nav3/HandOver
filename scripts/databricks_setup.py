"""One-command Databricks setup for HandOver: warehouse, tables, Volume, dashboard views, lesson files.

Run from the repo root:
    .venv/bin/python scripts/databricks_setup.py                 set everything up (no old events)
    .venv/bin/python scripts/databricks_setup.py --with-history  also upload real events from logs/events.jsonl
    .venv/bin/python scripts/databricks_setup.py --check         no network: say exactly what is missing
    .venv/bin/python scripts/databricks_setup.py --teardown-test-data   run 04_cleanup_test_data.sql

Reads DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_WAREHOUSE_ID (and optional DATABRICKS_CATALOG,
DATABRICKS_SCHEMA) from the environment or the repo-root .env, with the same rules as server/databricks.py.
The token is never printed: every line of output is scrubbed.

Steps
    1. Check the values, then ask the warehouse for its state; start it and wait (--warehouse-timeout).
    2. Catalog (created only when missing and allowed), then 01_setup.sql: schema, four tables, Volume.
       Falls back to server/static/databricks_init.sql when Prayush's file is not available.
    3. Views: the 13 datasets of 02_dashboard_datasets.sql as ds_<name>, plus filtered ds_<name>_real views
       over events_real and runs_real (team review, Prayush item 8): no mock or replay runs, no selftest rows,
       check_offline only with a reason, latency without mock or errored checks, timed_out from
       error_kind = 'timeout'.
    4. With --with-history only: real events from logs/events.jsonl (MERGE on event_id, so a rerun adds
       nothing twice) and the runs rows they imply.
    5. Real lessons (lessons/<id>/lesson.json, not demo-v1 or test ids) through
       server.databricks.upload_lesson_files.
    6. Counts, then the dashboard and Genie next steps.

Prayush's SQL files are read from databricks/ in the working tree, else from git ref origin/prayush/story-dbx.
Free Edition has a daily compute quota: this script runs a few dozen statements in total, batches rows (500
per statement), polls every 5 s at most and cancels a statement it gives up on. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PRAYUSH_REFS = ("origin/prayush/story-dbx", "prayush/story-dbx")
PRAYUSH_DIR = REPO / "databricks"
PRANAV_DDL = REPO / "server" / "static" / "databricks_init.sql"
EVENTS_JSONL = REPO / "logs" / "events.jsonl"
LESSONS_DIR = REPO / "lessons"

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
WAREHOUSE_RE = re.compile(r"^[A-Za-z0-9]{8,64}$")
NOT_REAL_LESSONS = {"demo-v1", "recut-me", "delete-me", "test-upload", "selftest", "templates"}
TEST_LESSON_PREFIXES = ("e2e-", "synthetic-")  # synthetic renders are not real learner data
TOKEN_REJECTED = ("token rejected: create a personal access token (starts with dapi) under User Settings > "
                  "Developer > Access tokens")
NOT_PAT_HINT = ("DATABRICKS_TOKEN does not start with dapi, so it is probably not a personal access token; "
                "the API will likely answer 401. Create a personal access token (starts with dapi) under User "
                "Settings > Developer > Access tokens")
ROWS_PER_STATEMENT = 500
POLL_EVERY = 5.0
STATEMENT_TIMEOUT = 300.0
WAREHOUSE_POLL = 10.0

EVENT_COLS = ("event_id", "run_id", "lesson_id", "step", "ts", "kind", "done", "confidence", "latency_ms",
              "reason", "from_step", "to_step", "mistake_kind", "looks_like", "extra")
EVENT_TYPES = {"step": "INT", "confidence": "DOUBLE", "latency_ms": "INT", "from_step": "INT", "to_step": "INT",
               "looks_like": "INT", "ts": "TIMESTAMP"}
RUN_COLS = ("run_id", "lesson_id", "learner", "started_at", "ended_at")
RUN_TYPES = {"started_at": "TIMESTAMP", "ended_at": "TIMESTAMP"}


# ---------------------------------------------------------------- output (always scrubbed)

class Out:
    """Every line goes through scrub(), so the token cannot reach the terminal or a log."""

    def __init__(self, stream: Any = None) -> None:
        self.stream = stream
        self.secrets: list[str] = []

    def scrub(self, text: str) -> str:
        for s in self.secrets:
            if s:
                text = text.replace(s, "***")
        text = re.sub(r"dapi[0-9A-Za-z\-]{8,}", "***", text)
        return re.sub(r"(?i)bearer\s+\S+", "Bearer ***", text)

    def __call__(self, text: str = "") -> None:
        print(self.scrub(str(text)), file=self.stream or sys.stdout, flush=True)


# ---------------------------------------------------------------- config

def read_env_file(path: Path) -> dict[str, str]:
    """Same rules as server/databricks.py: KEY=VALUE lines, # comments, optional export, quotes, inline # comments."""
    out: dict[str, str] = {}
    try:
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = env_value(v)
    except OSError:
        pass
    return out


def env_value(raw: str) -> str:
    """As server/databricks.py: a quoted value is taken between its quotes; an unquoted one ends at " #"."""
    v = raw.strip()
    if v[:1] in ('"', "'"):
        end = v.find(v[0], 1)
        return v[1:end] if end > 0 else v[1:]
    hash_at = v.find(" #")
    if hash_at < 0:
        hash_at = v.find("\t#")
    return (v[:hash_at] if hash_at >= 0 else v).strip()


def load_config(env_file: Path = REPO / ".env", environ: Optional[dict] = None) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    file_vals = read_env_file(env_file)

    def get(name: str, default: str = "") -> tuple[str, str]:
        if environ.get(name):
            return environ[name].strip(), "environment"
        if file_vals.get(name):
            return file_vals[name].strip(), ".env"
        return default, "default" if default else "missing"

    cfg: dict[str, Any] = {"env_file": env_file, "env_file_exists": env_file.is_file(), "source": {}}
    for key, name, default in (("host", "DATABRICKS_HOST", ""), ("token", "DATABRICKS_TOKEN", ""),
                               ("warehouse", "DATABRICKS_WAREHOUSE_ID", ""),
                               ("catalog", "DATABRICKS_CATALOG", "workspace"),
                               ("schema", "DATABRICKS_SCHEMA", "handover")):
        cfg[key], cfg["source"][key] = get(name, default)
    raw_host = cfg["host"]
    host = raw_host.rstrip("/")
    if host and not host.startswith(("https://", "http://")):
        host = "https://" + host
    cfg["host"] = host
    cfg["raw_host"] = raw_host
    return cfg


def config_problems(cfg: dict) -> tuple[list[str], list[str]]:
    """(missing or invalid, warnings). Never includes the token's value."""
    bad: list[str] = []
    warn: list[str] = []
    names = {"host": "DATABRICKS_HOST", "token": "DATABRICKS_TOKEN", "warehouse": "DATABRICKS_WAREHOUSE_ID"}
    for key, name in names.items():
        if not cfg[key]:
            where = f"in {cfg['env_file']}" if cfg["env_file_exists"] else f"({cfg['env_file']} does not exist)"
            bad.append(f"{name} is not set: add {name}=... to the environment or the repo .env {where}")
    for key, name in names.items():
        v = cfg[key]
        if v and any(c.isspace() for c in v):
            bad.append(f"{name} contains a space")
    host = cfg["host"]
    if host and not any(" " in x for x in bad if x.startswith("DATABRICKS_HOST")):
        u = urllib.parse.urlsplit(host)
        if u.scheme != "https":
            bad.append("DATABRICKS_HOST must use https://")
        if not u.hostname or "." not in u.hostname:
            bad.append("DATABRICKS_HOST is not a host name, expected https://dbc-xxxxxxxx-xxxx.cloud.databricks.com")
        if u.path not in ("", "/") or u.query or u.fragment:
            bad.append("DATABRICKS_HOST must be only https:// and the host: drop the path and any ?o=... part")
        if cfg["raw_host"] and not cfg["raw_host"].startswith(("https://", "http://")):
            warn.append("DATABRICKS_HOST has no https://; it is added here and in server/databricks.py")
    tok = cfg["token"]
    if tok and not tok.startswith("dapi"):
        warn.append(NOT_PAT_HINT)
    wh = cfg["warehouse"]
    if wh and "/" in wh:
        bad.append("DATABRICKS_WAREHOUSE_ID should be only the id after /warehouses/ in the HTTP path")
    elif wh and not WAREHOUSE_RE.match(wh):
        bad.append("DATABRICKS_WAREHOUSE_ID should be letters and digits only (the id after /warehouses/)")
    for key in ("catalog", "schema"):
        if not IDENT_RE.match(cfg[key]):
            bad.append(f"DATABRICKS_{key.upper()} must be letters, digits and underscores")
    return bad, warn


def fq(cfg: dict) -> str:
    return f"`{cfg['catalog']}`.`{cfg['schema']}`"


# ---------------------------------------------------------------- Prayush's SQL files

def read_source(name: str, run: Callable = subprocess.run) -> tuple[Optional[str], str]:
    """(text, where it came from). Working tree databricks/<name>, else git show <ref>:databricks/<name>."""
    local = PRAYUSH_DIR / name
    if local.is_file():
        return local.read_text(encoding="utf-8"), f"databricks/{name}"
    for ref in PRAYUSH_REFS:
        try:
            p = run(["git", "-C", str(REPO), "show", f"{ref}:databricks/{name}"], capture_output=True,
                    text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout, f"{ref}:databricks/{name}"
    return None, f"databricks/{name} (not in the working tree or {PRAYUSH_REFS[0]})"


def split_sql(text: str) -> list[str]:
    """Statements in a SQL script: -- comments dropped, split on ; outside quotes and backticks."""
    out: list[str] = []
    buf: list[str] = []
    quote: Optional[str] = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == "'" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'`\"":
            quote = c
            buf.append(c)
        elif c == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif c == ";":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
        else:
            buf.append(c)
        i += 1
    s = "".join(buf).strip()
    if s:
        out.append(s)
    return out


def substitute(sql: str, cfg: dict) -> str:
    """workspace.handover -> the configured `catalog`.`schema`, also inside /Volumes/ paths."""
    sql = re.sub(r"(?<![\w`.])workspace\.handover(?![\w`])", fq(cfg), sql)
    return sql.replace("/Volumes/workspace/handover/", f"/Volumes/{cfg['catalog']}/{cfg['schema']}/")


def setup_statements(text: str, cfg: dict) -> list[str]:
    """Only the CREATE statements of 01_setup.sql (its SHOW and SELECT checks run in the verify step)."""
    return [substitute(s, cfg) for s in split_sql(text) if s.upper().startswith("CREATE")]


def parse_datasets(text: str) -> dict[str, str]:
    """{name: query} from 02_dashboard_datasets.sql, one per '-- @dataset <name>' block."""
    out: dict[str, str] = {}
    parts = re.split(r"^--\s*@dataset\s+(\w+)\s*$", text, flags=re.M)
    for name, body in zip(parts[1::2], parts[2::2]):
        stmts = split_sql(body)
        if stmts:
            out[name] = stmts[0]
    return out


# ---------------------------------------------------------------- filtered views (team review, Prayush item 8)

def json_field(field: str, alias: str = "") -> str:
    return f"get_json_object({alias}extra, '$.{field}')"


def clean_check(alias: str = "") -> str:
    """A real, answered check: not the mock checker and no error (timeout, rate_limited, error, no_key, budget)."""
    return f"(coalesce({json_field('model', alias)}, '') <> 'mock' AND {json_field('error_kind', alias)} IS NULL)"


def mock_or_replay_row(alias: str = "") -> str:
    a = alias
    return (f"({json_field('source', a)} IN ('file', 'mock') OR {json_field('check_mode', a)} = 'mock' "
            f"OR ({a}kind = 'check' AND {json_field('model', a)} = 'mock'))")


def filter_views(cfg: dict) -> list[tuple[str, str]]:
    """runs_excluded, events_real, runs_real. A run is left out when any of its events says replay
    (source file) or mock (check_mode mock, mock checker, mock mistake detector)."""
    t = fq(cfg)
    excluded = f"""CREATE OR REPLACE VIEW {t}.`runs_excluded`
COMMENT 'Runs left out of the *_real views: replay (source file) or mock checks'
AS SELECT run_id, replay, mock FROM (
  SELECT run_id,
         max(CASE WHEN {json_field('source')} = 'file' THEN 1 ELSE 0 END) = 1 AS replay,
         max(CASE WHEN {json_field('check_mode')} = 'mock' OR {json_field('source')} = 'mock'
                       OR (kind = 'check' AND {json_field('model')} = 'mock') THEN 1 ELSE 0 END) = 1 AS mock
  FROM {t}.`events`
  WHERE run_id IS NOT NULL
  GROUP BY run_id
) WHERE replay OR mock"""
    events = f"""CREATE OR REPLACE VIEW {t}.`events_real`
COMMENT 'events without mock or replay runs and without selftest rows; recovery advances count as camera'
AS SELECT e.* EXCEPT (reason),
  CASE WHEN e.reason IN ('ahead_confirm', 'understand_override') THEN 'camera' ELSE e.reason END AS reason,
  e.reason AS reason_detail
FROM {t}.`events` e
LEFT ANTI JOIN {t}.`runs_excluded` x ON x.run_id = e.run_id
WHERE coalesce(e.lesson_id, '') <> 'selftest' AND NOT coalesce({mock_or_replay_row('e.')}, false)"""
    runs = f"""CREATE OR REPLACE VIEW {t}.`runs_real`
COMMENT 'runs without mock or replay runs and without selftest rows'
AS SELECT r.* FROM {t}.`runs` r
LEFT ANTI JOIN {t}.`runs_excluded` x ON x.run_id = r.run_id
WHERE coalesce(r.lesson_id, '') <> 'selftest' AND coalesce(r.learner, '') <> 'selftest'"""
    return [("runs_excluded", excluded), ("events_real", events), ("runs_real", runs)]


# Exact text edits per dataset, applied to Prayush's query before the catalog substitution. If his file
# changes so that a pattern is gone, that one filtered view is reported and skipped, never guessed.
REAL_EDITS: dict[str, list[tuple[str, str]]] = {
    "ds_check_offline": [
        ("WHERE e.kind = 'check_offline'", "WHERE e.kind = 'check_offline' AND e.reason IS NOT NULL"),
    ],
    "ds_checks": [
        ("  e.latency_ms,\n", f"  CASE WHEN {clean_check('e.')} THEN e.latency_ms END AS latency_ms,\n"),
        ("CASE WHEN e.done = 'unsure' AND e.confidence = 0 THEN 1 ELSE 0 END AS timed_out",
         f"CASE WHEN {json_field('error_kind', 'e.')} = 'timeout' THEN 1 ELSE 0 END AS timed_out"),
    ],
    "ds_check_latency_by_step": [
        ("WHERE e.kind = 'check' AND e.latency_ms IS NOT NULL",
         f"WHERE e.kind = 'check' AND e.latency_ms IS NOT NULL AND {clean_check('e.')}"),
    ],
    "ds_check_latency_overall": [
        ("percentile(latency_ms, 0.5)", f"percentile(CASE WHEN {clean_check()} THEN latency_ms END, 0.5)"),
        ("percentile(latency_ms, 0.9)", f"percentile(CASE WHEN {clean_check()} THEN latency_ms END, 0.9)"),
        ("CASE WHEN done = 'unsure' AND confidence = 0 THEN 1.0 ELSE 0.0 END",
         f"CASE WHEN {json_field('error_kind')} = 'timeout' THEN 1.0 ELSE 0.0 END"),
    ],
}


def real_query(name: str, query: str) -> str:
    """Prayush's dataset over events_real and runs_real, plus the item 8 edits. Raises ValueError when an
    expected pattern is missing."""
    q = re.sub(r"\bworkspace\.handover\.(events|runs)\b", r"workspace.handover.\1_real", query)
    for old, new in REAL_EDITS.get(name, []):
        if old not in q:
            raise ValueError(f"{name}: 02_dashboard_datasets.sql changed, could not find {old.strip()!r}")
        q = q.replace(old, new)
    return q


def view_statements(datasets: dict[str, str], cfg: dict) -> list[tuple[str, Optional[str], Optional[str]]]:
    """[(view name, statement or None, error or None)] for every ds_<name> and ds_<name>_real."""
    t = fq(cfg)
    out: list[tuple[str, Optional[str], Optional[str]]] = []
    for name, query in datasets.items():
        out.append((name, f"CREATE OR REPLACE VIEW {t}.`{name}` AS\n{substitute(query, cfg)}", None))
        try:
            out.append((f"{name}_real", f"CREATE OR REPLACE VIEW {t}.`{name}_real` AS\n"
                                        f"{substitute(real_query(name, query), cfg)}", None))
        except ValueError as e:
            out.append((f"{name}_real", None, str(e)))
    return out


# ---------------------------------------------------------------- event history filters

def _extra(row: dict) -> dict:
    x = row.get("extra")
    if isinstance(x, dict):
        return x
    if isinstance(x, str) and x:
        try:
            v = json.loads(x)
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def is_test_lesson(lesson_id: Any) -> bool:
    lid = str(lesson_id or "")
    return lid in NOT_REAL_LESSONS or lid.startswith(TEST_LESSON_PREFIXES)


def row_is_mock(row: dict, x: dict) -> bool:
    return (x.get("check_mode") == "mock" or x.get("source") == "mock"
            or (row.get("kind") == "check" and x.get("model") == "mock"))


def filter_events(lines: Iterable[str]) -> tuple[list[dict], dict[str, int]]:
    """Real events from the local JSONL. Left out, in this order: unreadable lines, rows without run_id,
    test lessons (recut-me, delete-me, test-upload, selftest, e2e-*), whole replay runs (any event with
    source file) and whole mock runs (check_mode mock, mock checks or mock mistakes)."""
    rows: list[dict] = []
    counts = {"read": 0, "unreadable": 0, "no_run_id": 0, "test_lesson": 0, "replay": 0, "mock": 0, "kept": 0}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        counts["read"] += 1
        try:
            r = json.loads(line)
        except ValueError:
            counts["unreadable"] += 1
            continue
        if not isinstance(r, dict) or not r.get("event_id") or not r.get("kind"):
            counts["unreadable"] += 1
            continue
        rows.append(r)
    replay_runs: set = set()
    mock_runs: set = set()
    for r in rows:
        x = _extra(r)
        if r.get("run_id"):
            if x.get("source") == "file":
                replay_runs.add(r["run_id"])
            if row_is_mock(r, x):
                mock_runs.add(r["run_id"])
    kept: list[dict] = []
    seen: set = set()
    for r in rows:
        if not r.get("run_id"):
            counts["no_run_id"] += 1
        elif is_test_lesson(r.get("lesson_id")):
            counts["test_lesson"] += 1
        elif r["run_id"] in replay_runs:
            counts["replay"] += 1
        elif r["run_id"] in mock_runs:
            counts["mock"] += 1
        elif r["event_id"] in seen:
            continue
        else:
            seen.add(r["event_id"])
            kept.append({c: r.get(c) for c in EVENT_COLS})
    counts["kept"] = len(kept)
    return kept, counts


def runs_from_events(events: list[dict]) -> list[dict]:
    """One runs row per run_id: lesson, learner from run_start, started at run_start (or first event),
    ended at run_end when there is one."""
    runs: dict[str, dict] = {}
    for e in sorted(events, key=lambda r: str(r.get("ts") or "")):
        rid = e["run_id"]
        r = runs.setdefault(rid, {"run_id": rid, "lesson_id": e.get("lesson_id"), "learner": None,
                                  "started_at": e.get("ts"), "ended_at": None})
        if e.get("kind") == "run_start":
            r["started_at"] = e.get("ts")
            r["learner"] = _extra(e).get("learner") or r["learner"]
        elif e.get("kind") == "run_end":
            r["ended_at"] = e.get("ts")
        if not r["lesson_id"]:
            r["lesson_id"] = e.get("lesson_id")
    return list(runs.values())


def _source_select(cols: tuple, types: dict) -> str:
    struct = ", ".join(f"`{c}`: {'STRING' if types.get(c, 'STRING') == 'TIMESTAMP' else types.get(c, 'STRING')}"
                       for c in cols)
    select = ", ".join(f"CAST(`{c}` AS TIMESTAMP) AS `{c}`" if types.get(c) == "TIMESTAMP" else f"`{c}`"
                       for c in cols)
    return f"SELECT {select} FROM (SELECT inline(from_json(:rows, 'ARRAY<STRUCT<{struct}>>')))"


def merge_events_sql(cfg: dict) -> str:
    names = ", ".join(f"`{c}`" for c in EVENT_COLS)
    vals = ", ".join(f"s.`{c}`" for c in EVENT_COLS)
    return (f"MERGE INTO {fq(cfg)}.`events` t USING ({_source_select(EVENT_COLS, EVENT_TYPES)}) s "
            f"ON t.`event_id` = s.`event_id` WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({vals})")


def merge_runs_sql(cfg: dict) -> str:
    names = ", ".join(f"`{c}`" for c in RUN_COLS)
    vals = ", ".join(f"s.`{c}`" for c in RUN_COLS)
    return (f"MERGE INTO {fq(cfg)}.`runs` t USING ({_source_select(RUN_COLS, RUN_TYPES)}) s "
            f"ON t.`run_id` = s.`run_id` WHEN MATCHED THEN UPDATE SET "
            f"t.`ended_at` = coalesce(t.`ended_at`, s.`ended_at`), t.`learner` = coalesce(t.`learner`, s.`learner`) "
            f"WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({vals})")


def real_lessons(root: Path = LESSONS_DIR) -> list[Path]:
    if not root.is_dir():
        return []
    return [d for d in sorted(root.iterdir())
            if d.is_dir() and (d / "lesson.json").is_file() and d.name not in NOT_REAL_LESSONS and not d.name.startswith(TEST_LESSON_PREFIXES)
            and not d.name.startswith(TEST_LESSON_PREFIXES)]


# ---------------------------------------------------------------- HTTP

def urllib_transport(method: str, url: str, headers: dict, body: Optional[bytes], timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        except Exception:
            return e.code, b""


class ApiError(Exception):
    pass


class Api:
    """Statement Execution and Warehouses REST calls. `transport` and `sleep` are swapped in tests."""

    def __init__(self, cfg: dict, transport: Callable = urllib_transport, sleep: Callable = time.sleep,
                 clock: Optional[Callable] = None) -> None:
        self.cfg, self.transport, self.sleep = cfg, transport, sleep
        self.clock = clock or (lambda: time.monotonic())
        self.statements = 0

    def call(self, method: str, path: str, body: Optional[dict] = None, timeout: float = 60.0) -> dict:
        headers = {"Authorization": f"Bearer {self.cfg['token']}", "Content-Type": "application/json",
                   "User-Agent": "handover-setup/1.0"}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        try:
            code, raw = self.transport(method, self.cfg["host"] + path, headers, data, timeout)
        except urllib.error.URLError as e:
            raise ApiError(f"cannot reach {self.cfg['host']}: {getattr(e, 'reason', e)}. Check DATABRICKS_HOST "
                           "and the network") from None
        except (OSError, ValueError) as e:
            raise ApiError(f"cannot reach {self.cfg['host']}: {type(e).__name__}: {e}") from None
        if code == 401:
            detail = error_text(raw).removeprefix("401").strip()
            if not self.cfg["token"].startswith("dapi"):
                raise ApiError(f"HTTP 401 {detail}. {TOKEN_REJECTED}. The token in .env does not start "
                               "with dapi, so it is not one")
            raise ApiError(f"HTTP 401 {detail}. {TOKEN_REJECTED}; if it already is one, copy the whole "
                           "token again and check DATABRICKS_HOST is the workspace it came from")
        if code == 403:
            raise ApiError(f"HTTP 403: the token is not allowed to do this ({error_text(raw)}). It needs the sql "
                           "scope, and files for lesson uploads, or full access")
        try:
            res = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(f"HTTP {code}: the answer is not JSON. DATABRICKS_HOST may not be a Databricks "
                           "workspace URL") from None
        if not 200 <= code < 300:
            raise ApiError(f"HTTP {code} {error_text(raw)}".strip())
        return res if isinstance(res, dict) else {}

    # ------------------------------------------------ warehouse

    def warehouse(self) -> dict:
        try:
            return self.call("GET", f"/api/2.0/sql/warehouses/{urllib.parse.quote(self.cfg['warehouse'])}")
        except ApiError as e:
            if str(e).startswith(("HTTP 404", "HTTP 400")):
                raise ApiError(f"warehouse {self.cfg['warehouse']} not found ({e}). Copy the id after /warehouses/ "
                               "from SQL Warehouses > your warehouse > Connection details > HTTP path") from None
            raise

    def ensure_running(self, timeout: float, say: Callable[[str], None]) -> dict:
        info = self.warehouse()
        state = info.get("state", "")
        start = self.clock()
        started = False
        while state != "RUNNING":
            if state in ("DELETED", "DELETING"):
                raise ApiError(f"warehouse {info.get('name', '')} is {state}")
            if state in ("STOPPED",) and not started:
                say(f"      warehouse {info.get('name', '')!r} is STOPPED, starting it")
                self.call("POST", f"/api/2.0/sql/warehouses/{urllib.parse.quote(self.cfg['warehouse'])}/start", {})
                started = True
            if self.clock() - start > timeout:
                raise ApiError(f"warehouse still {state} after {timeout:.0f} s; try again, or start it in the UI "
                               "(SQL Warehouses), or raise --warehouse-timeout")
            self.sleep(WAREHOUSE_POLL)
            info = self.warehouse()
            new = info.get("state", "")
            if new != state:
                say(f"      warehouse {new} after {self.clock() - start:.0f} s")
            state = new
        return info

    # ------------------------------------------------ SQL

    def sql(self, statement: str, params: Optional[list] = None, timeout: float = STATEMENT_TIMEOUT) -> list:
        """Run one statement, wait for it, return data_array rows. Raises ApiError with the reason."""
        body: dict[str, Any] = {"warehouse_id": self.cfg["warehouse"], "statement": statement,
                                "wait_timeout": "30s", "on_wait_timeout": "CONTINUE",
                                "disposition": "INLINE", "format": "JSON_ARRAY"}
        if params:
            body["parameters"] = params
        self.statements += 1
        res = self.call("POST", "/api/2.0/sql/statements", body, timeout=60.0)
        state = (res.get("status") or {}).get("state", "")
        sid = res.get("statement_id")
        start = self.clock()
        while state in ("PENDING", "RUNNING") and sid:
            if self.clock() - start > timeout:
                try:
                    self.call("POST", f"/api/2.0/sql/statements/{urllib.parse.quote(sid)}/cancel", {})
                except ApiError:
                    pass
                raise ApiError(f"statement still {state} after {timeout:.0f} s; cancelled")
            self.sleep(POLL_EVERY)
            res = self.call("GET", f"/api/2.0/sql/statements/{urllib.parse.quote(sid)}")
            state = (res.get("status") or {}).get("state", "")
        if state != "SUCCEEDED":
            err = (res.get("status") or {}).get("error") or {}
            raise ApiError(f"{state or 'unknown state'}: {err.get('error_code', '')} {err.get('message', '')}".strip())
        return (res.get("result") or {}).get("data_array") or []


def error_text(raw: bytes) -> str:
    try:
        j = json.loads(raw)
        return f"{j.get('error_code', '')} {j.get('message', '')}".strip()
    except Exception:
        return raw[:200].decode("utf-8", "replace").strip()


def head(sql: str, words: int = 7) -> str:
    return " ".join(sql.split()[:words])


# ---------------------------------------------------------------- steps

class Setup:
    def __init__(self, cfg: dict, api: Api, say: Out, db: Any = None) -> None:
        self.cfg, self.api, self.say, self.db = cfg, api, say, db
        self.results: list[tuple[str, bool, str]] = []

    def record(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        self.say(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
        return ok

    def warehouse(self, timeout: float) -> bool:
        try:
            info = self.api.ensure_running(timeout, self.say)
            rows = self.api.sql("SELECT current_catalog(), current_user()")
            who = rows[0][1] if rows and len(rows[0]) > 1 else "?"
            return self.record("warehouse", True, f"{info.get('name', '')!r} RUNNING, signed in as {who}")
        except ApiError as e:
            return self.record("warehouse", False, str(e))

    def catalog(self) -> bool:
        cat = self.cfg["catalog"]
        try:
            if self.api.sql(f"SHOW CATALOGS LIKE '{cat}'"):
                return self.record("catalog", True, f"{cat} exists")
        except ApiError as e:
            return self.record("catalog", False, f"could not list catalogs: {e}")
        try:
            self.api.sql(f"CREATE CATALOG IF NOT EXISTS `{cat}`")
            return self.record("catalog", True, f"{cat} created")
        except ApiError as e:
            return self.record("catalog", False, f"{cat} does not exist and could not be created ({e}). On Free "
                                                  "Edition use the default catalog: remove DATABRICKS_CATALOG")

    def tables(self) -> bool:
        text, where = read_source("01_setup.sql")
        if text:
            stmts = setup_statements(text, self.cfg)
        elif PRANAV_DDL.is_file():
            where = str(PRANAV_DDL.relative_to(REPO))
            stmts = setup_statements(PRANAV_DDL.read_text(encoding="utf-8"), self.cfg)
        else:
            return self.record("schema, tables, Volume", False, f"no DDL found: {where}")
        self.say(f"      from {where}: {len(stmts)} statements")
        bad = 0
        for s in stmts:
            try:
                self.api.sql(s)
                self.say(f"      ok   {head(s)}")
            except ApiError as e:
                bad += 1
                self.say(f"      FAIL {head(s)}: {e}")
        return self.record("schema, tables, Volume", bad == 0, f"{len(stmts) - bad}/{len(stmts)} statements")

    def views(self) -> bool:
        text, where = read_source("02_dashboard_datasets.sql")
        if not text:
            return self.record("dashboard views", False, f"missing {where}")
        datasets = parse_datasets(text)
        plan: list[tuple[str, Optional[str], Optional[str]]] = [(n, s, None) for n, s in filter_views(self.cfg)]
        plan += view_statements(datasets, self.cfg)
        self.say(f"      from {where}: {len(datasets)} datasets, {len(plan)} views")
        bad = 0
        for name, stmt, err in plan:
            if stmt is not None:
                try:
                    self.api.sql(stmt)
                    continue
                except ApiError as e:
                    err = str(e)
            bad += 1
            self.say(f"      FAIL {name}: {err}")
        return self.record("dashboard views", bad == 0, f"{len(plan) - bad}/{len(plan)} views "
                           f"(ds_<name> as in the file, ds_<name>_real filtered)")

    def history(self, path: Path = EVENTS_JSONL) -> bool:
        if not path.is_file():
            return self.record("event history", True, f"nothing to upload: {path} does not exist")
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            events, counts = filter_events(fh)
        runs = runs_from_events(events)
        self.say("      " + history_summary(counts, len(runs)))
        try:
            for i in range(0, len(runs), ROWS_PER_STATEMENT):
                chunk = runs[i:i + ROWS_PER_STATEMENT]
                self.api.sql(merge_runs_sql(self.cfg), [{"name": "rows", "type": "STRING",
                                                          "value": json.dumps(chunk, default=str)}])
            for i in range(0, len(events), ROWS_PER_STATEMENT):
                chunk = events[i:i + ROWS_PER_STATEMENT]
                self.api.sql(merge_events_sql(self.cfg), [{"name": "rows", "type": "STRING",
                                                            "value": json.dumps(chunk, default=str)}])
        except ApiError as e:
            return self.record("event history", False, str(e))
        return self.record("event history", True, f"{len(events)} events and {len(runs)} runs merged "
                                                  "(already present event_ids were skipped)")

    def lessons(self, root: Path = LESSONS_DIR, wait: float = 180.0) -> bool:
        lessons = real_lessons(root)
        if not lessons:
            return self.record("lesson files", True, "no real lessons (lessons/<id>/lesson.json, not demo-v1)")
        db = self.db
        if db is None:
            try:
                from server import databricks as db  # type: ignore[no-redef]
            except Exception as e:
                return self.record("lesson files", False, f"cannot import server.databricks: {e}")
        st = db.status()
        if not st.get("enabled"):
            return self.record("lesson files", False, "server.databricks is not configured "
                                                      f"({st.get('config_error') or 'credentials not read'})")
        if st.get("target") != f"{self.cfg['catalog']}.{self.cfg['schema']}":
            return self.record("lesson files", False, f"server.databricks targets {st.get('target')}, this run "
                               f"targets {self.cfg['catalog']}.{self.cfg['schema']}")
        before_files, before_err = st.get("uploaded_files", 0), st.get("last_error")
        expected = sum(count_lesson_files(d) for d in lessons)
        self.say(f"      {', '.join(d.name for d in lessons)}: {expected} files to the Volume, plus lessons and "
                 "steps rows")
        for d in lessons:
            db.upload_lesson_files(d, d.name)
        deadline = time.monotonic() + wait
        for t in [t for t in threading.enumerate() if t.name == "databricks-upload"]:
            t.join(max(0.0, deadline - time.monotonic()))
        drained = db.flush(max(5.0, deadline - time.monotonic()))
        st = db.status()
        sent = st.get("uploaded_files", 0) - before_files
        err = st.get("last_error") if st.get("last_error") != before_err else None
        ok = sent == expected and drained and err is None
        detail = f"{sent}/{expected} files, lessons and steps rows {'sent' if drained else 'not all sent yet'}"
        if err:
            detail += f"; last error: {err}"
        return self.record("lesson files", ok, detail)

    def verify(self) -> bool:
        t = fq(self.cfg)
        try:
            rows = self.api.sql(f"SELECT (SELECT count(*) FROM {t}.`lessons`), (SELECT count(*) FROM {t}.`steps`), "
                                f"(SELECT count(*) FROM {t}.`runs`), (SELECT count(*) FROM {t}.`events`), "
                                f"(SELECT count(*) FROM {t}.`runs_real`), (SELECT count(*) FROM {t}.`events_real`)")
            vols = self.api.sql(f"SHOW VOLUMES IN {t}")
        except ApiError as e:
            return self.record("verify", False, str(e))
        c = rows[0] if rows else ["?"] * 6
        names = [r[-1] if len(r) == 1 else r[1] for r in vols if r]
        return self.record("verify", "lessons" in names,
                           f"lessons {c[0]}, steps {c[1]}, runs {c[2]} ({c[4]} real), events {c[3]} ({c[5]} real); "
                           f"Volume lessons {'present' if 'lessons' in names else 'MISSING'}")

    def teardown(self) -> bool:
        text, where = read_source("04_cleanup_test_data.sql")
        if not text:
            return self.record("teardown test data", False, f"missing {where}")
        stmts = [substitute(s, self.cfg) for s in split_sql(text)]
        self.say(f"      from {where}: {len(stmts)} statements")
        bad = 0
        for s in stmts:
            try:
                rows = self.api.sql(s)
                self.say(f"      ok   {head(s)}")
                if s.upper().startswith("SELECT"):
                    for r in rows[:20]:
                        self.say(f"           {r}")
            except ApiError as e:
                bad += 1
                self.say(f"      FAIL {head(s)}: {e}")
        return self.record("teardown test data", bad == 0, f"{len(stmts) - bad}/{len(stmts)} statements; "
                           "the first check row must be all zeros")


def count_lesson_files(d: Path) -> int:
    n = 1 if (d / "lesson.json").is_file() else 0
    for sub, pattern in (("frames", "*.jpg"), ("captions", "*.vtt"), ("clips", "*.mp4")):
        n += sum(1 for f in (d / sub).glob(pattern) if f.stat().st_size <= 200 * 1024**2)
    return n


def history_summary(counts: dict, runs: int) -> str:
    return (f"events.jsonl: {counts['read']} lines, {counts['kept']} real events in {runs} runs kept; left out "
            f"{counts['mock']} mock, {counts['replay']} replay, {counts['test_lesson']} test lesson, "
            f"{counts['no_run_id']} without run_id, {counts['unreadable']} unreadable")


def next_steps(cfg: dict, datasets: list[str]) -> list[str]:
    host, t = cfg["host"], f"{cfg['catalog']}.{cfg['schema']}"
    lines = [
        "Next steps (by hand, in the workspace; details in databricks/dashboard.md and genie.md):",
        f"  Workspace      {host}",
        f"  Catalog        {host}/explore/data/{cfg['catalog']}/{cfg['schema']}",
        f"  Warehouse      {host}/sql/warehouses/{cfg['warehouse']}",
        "",
        "  Dashboard 'HandOver learner runs' (sidebar > Dashboards > Create dashboard):",
        "    Data tab > Add SQL dataset, once per dataset, named as below, so dashboard.md's widgets apply as is:",
    ]
    lines += [f"      {d:<26} SELECT * FROM {t}.{d}_real" for d in datasets]
    lines += [
        "    The _real views leave out mock and replay runs and selftest rows; ds_<name> (no suffix) is",
        "    02_dashboard_datasets.sql unfiltered. Then build page 1 and page 2 per dashboard.md, one Lesson",
        "    filter per page on lesson_id, colors from its table.",
        "    Before judging: --teardown-test-data, refresh, Publish > Share with data permissions.",
        "    Free Edition quota: never set a refresh schedule; close editor tabs you do not use.",
        "",
        "  Genie 'HandOver learner runs' (sidebar > Genie > New):",
        f"    Data: {t}.lessons, steps, runs, events (or events_real and runs_real to leave out mock and replay).",
        "    Default warehouse: this one. Then joins, general instructions, Q1 to Q8 and the common questions",
        "    from genie.md section 2 to 4, and rehearse 'Which step do people get stuck on?' (section 5).",
        "",
        "  Warm the warehouse before a demo: .venv/bin/python -m server.databricks --warm",
    ]
    return lines


# ---------------------------------------------------------------- --check (no network)

def check(cfg: dict, say: Out, events_path: Path = EVENTS_JSONL, lessons_root: Path = LESSONS_DIR) -> int:
    bad, warn = config_problems(cfg)
    say("Databricks setup check (no network calls)")
    say(f"  .env           {cfg['env_file']} {'found' if cfg['env_file_exists'] else 'NOT FOUND'}")
    for key, name in (("host", "DATABRICKS_HOST"), ("token", "DATABRICKS_TOKEN"),
                      ("warehouse", "DATABRICKS_WAREHOUSE_ID")):
        if not cfg[key]:
            shown = "MISSING"
        elif key == "token":
            shown = f"set ({cfg['source'][key]}, value hidden)"
        else:
            shown = f"{cfg[key]} ({cfg['source'][key]})"
        say(f"  {name:<24} {shown}")
    say(f"  target         {cfg['catalog']}.{cfg['schema']}")
    for name in ("01_setup.sql", "02_dashboard_datasets.sql", "04_cleanup_test_data.sql", "dashboard.md", "genie.md"):
        text, where = read_source(name)
        say(f"  {name:<26} {'from ' + where if text else 'MISSING: ' + where}")
        if text is None and name == "01_setup.sql" and PRANAV_DDL.is_file():
            say(f"  {'':<26} fallback: {PRANAV_DDL.relative_to(REPO)}")
        elif text is None and name != "01_setup.sql":
            warn.append(f"{name} not found; the step that needs it will fail")
    text, _ = read_source("02_dashboard_datasets.sql")
    if text:
        datasets = parse_datasets(text)
        broken = [err for _, stmt, err in view_statements(datasets, cfg) if err]
        say(f"  views          {len(datasets)} datasets, {2 * len(datasets) - len(broken) + 3} views would be created")
        warn.extend(broken)
    lessons = real_lessons(lessons_root)
    say(f"  lessons        {', '.join(d.name for d in lessons) or 'none'} "
        f"({sum(count_lesson_files(d) for d in lessons)} files)")
    if events_path.is_file():
        with events_path.open("r", encoding="utf-8", errors="replace") as fh:
            events, counts = filter_events(fh)
        say(f"  --with-history {history_summary(counts, len(runs_from_events(events)))}")
    else:
        say(f"  --with-history nothing: {events_path} does not exist")
    for w in warn:
        say(f"  warning: {w}")
    if bad:
        say("NOT READY. Missing or invalid:")
        for b in bad:
            say(f"  - {b}")
        return 1
    say(f"READY{' WITH WARNINGS' if warn else ''}: run .venv/bin/python scripts/databricks_setup.py")
    return 0


# ---------------------------------------------------------------- main

def main(argv: Optional[list[str]] = None, transport: Callable = urllib_transport, sleep: Callable = time.sleep,
         env_file: Path = REPO / ".env", environ: Optional[dict] = None, db: Any = None,
         events_path: Path = EVENTS_JSONL, lessons_root: Path = LESSONS_DIR, stream: Any = None) -> int:
    p = argparse.ArgumentParser(prog="scripts/databricks_setup.py", description=__doc__.split("\n")[0])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="no network: say exactly what is missing")
    g.add_argument("--teardown-test-data", action="store_true", help="run 04_cleanup_test_data.sql and exit")
    p.add_argument("--with-history", action="store_true", help="also upload real events from logs/events.jsonl")
    p.add_argument("--skip-lessons", action="store_true", help="do not upload lesson files")
    p.add_argument("--warehouse-timeout", type=float, default=300.0, help="seconds to wait for the warehouse")
    a = p.parse_args(argv)

    cfg = load_config(env_file, environ)
    say = Out(stream)
    say.secrets.append(cfg["token"])
    if a.check:
        return check(cfg, say, events_path, lessons_root)

    bad, warn = config_problems(cfg)
    for w in warn:
        say(f"warning: {w}")
    if bad:
        say("Cannot start, fix these first (or run with --check):")
        for b in bad:
            say(f"  - {b}")
        return 2

    api = Api(cfg, transport=transport, sleep=sleep)
    s = Setup(cfg, api, say, db)
    say(f"Databricks setup: {cfg['host']}, warehouse {cfg['warehouse']}, target {cfg['catalog']}.{cfg['schema']}")

    if a.teardown_test_data:
        say("[1/2] warehouse")
        ok = s.warehouse(a.warehouse_timeout)
        if ok:
            say("[2/2] teardown test data")
            ok = s.teardown()
        say(f"{api.statements} SQL statements run")
        return 0 if ok else 1

    total = 7
    say(f"[1/{total}] warehouse")
    if not s.warehouse(a.warehouse_timeout):
        say("Stopped: nothing else can run without the warehouse.")
        return 1
    say(f"[2/{total}] catalog")
    if not s.catalog():
        say("Stopped: no catalog.")
        return 1
    say(f"[3/{total}] schema, tables, Volume")
    tables_ok = s.tables()
    say(f"[4/{total}] dashboard views")
    s.views()
    say(f"[5/{total}] event history")
    if not a.with_history:
        s.record("event history", True, "skipped (default); --with-history uploads real events from logs/events.jsonl")
    elif not tables_ok:
        s.record("event history", False, "skipped: tables not ready")
    else:
        s.history(events_path)
    say(f"[6/{total}] lesson files")
    if a.skip_lessons:
        s.record("lesson files", True, "skipped (--skip-lessons)")
    elif not tables_ok:
        s.record("lesson files", False, "skipped: tables or Volume not ready")
    else:
        s.lessons(lessons_root)
    say(f"[7/{total}] verify")
    s.verify()

    failed = [n for n, ok, _ in s.results if not ok]
    say("")
    say(f"{api.statements} SQL statements run. " + ("All steps ok." if not failed else f"Failed: {', '.join(failed)}."))
    say("")
    text, _ = read_source("02_dashboard_datasets.sql")
    for line in next_steps(cfg, list(parse_datasets(text)) if text else []):
        say(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Accounts, course library, editor, scoring and rating tests. Offline: temp lessons, data and events files,
a fake teach.recut, fake self-test and fake voice functions, and a minimal app with only routes_library.

Run: .venv/bin/python -m server.test_library (or pytest if installed).
"""

import asyncio
import contextlib
import itertools
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="handover-library-test-"))
LESSONS, DATA, EVENTS = TMP / "lessons", TMP / "data", TMP / "events.jsonl"
os.environ.update(HANDOVER_LESSONS=str(LESSONS), HANDOVER_DATA=str(DATA), HANDOVER_EVENTS_JSONL=str(EVENTS),
                  HANDOVER_NO_NETWORK="1", HANDOVER_CHECK="mock")
for _name in ("HANDOVER_AUTH", "HANDOVER_TOKEN_DAYS", "HANDOVER_LOGIN_PER_MINUTE", "HANDOVER_HISTORY_DEPTH"):
    os.environ.pop(_name, None)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import accounts, library, routes_library, scoring, teach, voice  # noqa: E402

app = FastAPI()
app.include_router(routes_library.router)
client = TestClient(app)

CALLS: dict[str, list] = {"recut": [], "publish": [], "changed": [], "upload": [], "selftest": []}
RECUT_FAIL: dict = {"error": None}
JOBS: dict[str, dict] = {}
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def fake_recut(d: Path, progress=None) -> dict:
    CALLS["recut"].append(Path(d).name)
    if RECUT_FAIL["error"] is not None:
        raise RECUT_FAIL["error"]
    lesson = json.loads((Path(d) / "lesson.json").read_text(encoding="utf-8"))
    for i, s in enumerate(lesson["steps"], start=1):
        s.update(n=i, clip=f"clips/{i:02d}.mp4", captions=f"captions/{i:02d}.vtt", ref_frame=f"frames/{i:02d}.jpg")
    (Path(d) / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
    return lesson


async def fake_self_test(d: Path, progress=None) -> dict:
    lesson = json.loads((Path(d) / "lesson.json").read_text(encoding="utf-8"))
    CALLS["selftest"].append([s.get("check_type") for s in lesson["steps"]])
    for s in lesson["steps"]:
        if s.get("check_type") != "manual":
            s["self_test"] = {"own": "yes", "prev": "no", "ok": True}
    (Path(d) / "lesson.json").write_text(json.dumps(lesson), encoding="utf-8")
    return lesson


async def fake_upload(file, title, id):
    lesson_id = id or title.lower().replace(" ", "-")
    job = f"job{len(CALLS['upload']) + 1}"
    CALLS["upload"].append((lesson_id, title))
    JOBS[job] = {"status": "queued", "id": lesson_id}
    return {"job": job, "id": lesson_id}


teach.recut = fake_recut
teach.self_test_lesson_async = fake_self_test
routes_library.configure(publish=lambda d, lid: CALLS["publish"].append(lid),
                         on_lesson_changed=lambda lid: CALLS["changed"].append(lid),
                         upload=fake_upload, job_status=lambda job: JOBS.get(job))


# ---------------------------------------------------------------- helpers

def reset() -> None:
    for p in (LESSONS, DATA):
        shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True)
    EVENTS.unlink(missing_ok=True)
    EVENTS.with_name(EVENTS.name + ".1").unlink(missing_ok=True)
    for v in CALLS.values():
        v.clear()
    RECUT_FAIL["error"] = None
    JOBS.clear()
    accounts.reset_rate_limits()
    accounts.reset_handoffs()
    accounts.now = time.time
    for name in ("HANDOVER_AUTH", "HANDOVER_TOKEN_DAYS", "HANDOVER_HISTORY_DEPTH"):
        os.environ.pop(name, None)


def make_lesson(lesson_id: str, steps: int = 3, title: str = "") -> Path:
    d = LESSONS / lesson_id
    for sub in ("clips", "captions", "frames"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(1, steps + 1):
        out.append({"n": i, "title": f"Step {i}", "start": library.fmt_time((i - 1) * 4),
                    "end": library.fmt_time(i * 4), "clip": f"clips/{i:02d}.mp4", "captions": f"captions/{i:02d}.vtt",
                    "ref_frame": f"frames/{i:02d}.jpg", "check_type": "manual" if i == 3 else "camera",
                    "check_question": "" if i == 3 else f"Is step {i} done?", "prerequisites": []})
        (d / "captions" / f"{i:02d}.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n\n",
                                                     encoding="utf-8")
        (d / "frames" / f"{i:02d}.jpg").write_bytes(JPEG + bytes([i]))
    (d / "lesson.json").write_text(json.dumps({"id": lesson_id, "title": title or lesson_id.title(),
                                               "video": "norm.mp4", "steps": out}), encoding="utf-8")
    return d


def lesson(lesson_id: str) -> dict:
    return json.loads((LESSONS / lesson_id / "lesson.json").read_text(encoding="utf-8"))


def test_repository_fixtures_are_hidden_only_from_the_real_library():
    assert not library.is_user_facing_lesson("demo-v1", library.REPO / "lessons")
    assert not library.is_user_facing_lesson("fortune-teller-v1", library.REPO / "lessons")
    assert library.is_user_facing_lesson("fortune-teller-v2", library.REPO / "lessons")
    assert library.is_user_facing_lesson("demo-v1", LESSONS), "test-specific lesson roots keep their fixtures"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def setup_owner(name: str = "Hana", passcode: str = "owner-pass") -> str:
    r = client.post("/api/auth/setup", json={"name": name, "passcode": passcode})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def add_user(owner: str, name: str, role: str) -> tuple[str, str]:
    """Creates a user and logs in. Returns (user id, token)."""
    r = client.post("/api/users", json={"name": name, "role": role, "passcode": f"{name}-pass"}, headers=auth(owner))
    assert r.status_code == 200, r.text
    accounts.reset_rate_limits()
    t = client.post("/api/auth/login", json={"name": name, "passcode": f"{name}-pass"})
    assert t.status_code == 200, t.text
    return r.json()["id"], t.json()["token"]


def make_course(lesson_id: str, owner_id: str, status: str = "draft", visibility: str = "only_me",
                access: tuple = (), steps: int = 3) -> None:
    make_lesson(lesson_id, steps)
    course = library.new_course(owner_id, lesson_id.title())
    course.update(status=status, visibility=visibility, access=[{"user_id": u, "role": r} for u, r in access])
    library.write_json(LESSONS / lesson_id / "course.json", course)


_ts = itertools.count()
KNOWN = ("event_id", "run_id", "lesson_id", "step", "ts", "kind", "done", "confidence", "latency_ms", "reason",
         "from_step", "to_step", "mistake_kind", "looks_like")


def ev(kind: str, run_id: str, lesson_id: str = "c1", **fields) -> dict:
    """One event as server/databricks.py writes it to the local JSONL (unknown fields in extra)."""
    row = {k: None for k in KNOWN}
    row.update(event_id=f"e{next(_ts)}", run_id=run_id, lesson_id=lesson_id, kind=kind,
               ts=f"2026-11-14T12:{next(_ts) // 60:02d}:{next(_ts) % 60:02d}.000Z")
    extra = {}
    for k, v in fields.items():
        if k in KNOWN:
            row[k] = v
        else:
            extra[k] = v
    row["extra"] = json.dumps(extra) if extra else None
    return row


def write_events(rows: list[dict]) -> None:
    with EVENTS.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def sample_run(run_id: str, learner: str, lesson_id: str = "c1") -> list[dict]:
    """A finished run with known numbers (see test_scoring_formula)."""
    e = lambda kind, **kw: ev(kind, run_id, lesson_id, **kw)  # noqa: E731
    return [
        e("run_start", step=0, learner=learner),
        e("step_enter", step=0, check_type="camera", expert_seconds=4.0),
        e("check", step=0, done="no", confidence=0.7, error_kind=None),
        e("check", step=0, done="yes", confidence=0.8, error_kind=None),
        e("advance", step=0, from_step=0, to_step=1, reason="camera", step_seconds=4.0),
        e("step_enter", step=1, check_type="camera"),
        e("check", step=1, done="unsure", confidence=0.0, error_kind="timeout"),
        e("mistake", step=1, mistake_kind="behind", looks_like=0, confidence=0.9),
        e("advance", step=1, from_step=1, to_step=0, reason="button", step_seconds=2.0),
        e("step_enter", step=0, check_type="camera"),
        e("advance", step=0, from_step=0, to_step=1, reason="button", step_seconds=1.0),
        e("step_enter", step=1, check_type="camera"),
        e("advance", step=1, from_step=1, to_step=2, reason="button", step_seconds=10.0),
        e("step_enter", step=2, check_type="manual"),
        e("advance", step=2, from_step=2, to_step=3, reason="button", step_seconds=6.0),
        e("run_done", total_seconds=23.0),
    ]


@contextlib.contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v is not None})
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------- accounts

def test_setup_login_logout():
    reset()
    r = client.get("/api/me")
    assert r.json() == {"user": None, "auth": "optional", "setup_needed": True}
    assert client.post("/api/auth/setup", json={"name": "Hana", "passcode": "abc"}).status_code == 400
    token = setup_owner()
    assert client.post("/api/auth/setup", json={"name": "Eve", "passcode": "abcdef"}).json() == \
        {"detail": "setup is already done"}
    me = client.get("/api/me", headers=auth(token)).json()
    assert me["user"]["role"] == "owner" and me["setup_needed"] is False
    stored = json.loads((DATA / "users.json").read_text())["users"][0]
    assert stored["passcode"].startswith("scrypt$") and "owner-pass" not in json.dumps(stored)
    assert token not in (DATA / "tokens.json").read_text()  # only a hash is stored
    if os.name == "posix":  # Windows has no mode bits; the file inherits the user profile's owner-only ACL
        assert oct((DATA / "users.json").stat().st_mode)[-3:] == "600"
    r = client.post("/api/auth/login", json={"name": "hana", "passcode": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "wrong name or passcode"
    r = client.post("/api/auth/login", json={"name": "  HANA ", "passcode": "owner-pass"})
    assert r.status_code == 200 and r.json()["user"]["name"] == "Hana" and r.json()["expires"].endswith("Z")
    t2 = r.json()["token"]
    assert client.post("/api/auth/logout", headers=auth(t2)).json() == {"ok": True}
    assert client.get("/api/me", headers=auth(t2)).json()["detail"] == "invalid or expired token"
    assert client.get("/api/me", headers={"Authorization": "Basic x"}).json()["detail"] == "bad authorization header"
    assert client.get("/api/me", headers=auth(token)).status_code == 200  # other sessions stay


def test_qr_handoff_is_approved_by_phone_and_redeemed_once_by_mac():
    reset()
    phone = setup_owner()
    started = client.post("/api/auth/handoff/start").json()
    claim = started["claim"]
    assert len(claim) >= 32 and phone not in claim

    assert client.post("/api/auth/handoff/redeem", json={"claim": claim}).json() == {"status": "pending"}
    approved = client.post("/api/auth/handoff/approve", json={"claim": claim}, headers=auth(phone))
    assert approved.status_code == 200 and approved.json()["approved"] is True

    redeemed = client.post("/api/auth/handoff/redeem", json={"claim": claim})
    assert redeemed.status_code == 200
    desktop = redeemed.json()["token"]
    assert desktop != phone and redeemed.json()["user"]["name"] == "Hana"
    assert client.get("/api/me", headers=auth(desktop)).json()["user"]["name"] == "Hana"
    assert client.post("/api/auth/handoff/redeem", json={"claim": claim}).status_code == 404


def test_qr_handoff_requires_signed_in_approval_and_expires():
    reset()
    setup_owner()
    claim = client.post("/api/auth/handoff/start").json()["claim"]
    assert client.post("/api/auth/handoff/approve", json={"claim": claim}).status_code == 401
    assert client.post("/api/auth/handoff/approve", json={"claim": "wrong"}).status_code == 401
    original = accounts.now
    accounts.now = lambda: original() + accounts.HANDOFF_TTL_S + 1
    try:
        assert client.post("/api/auth/handoff/redeem", json={"claim": claim}).status_code == 404
    finally:
        accounts.now = original


def test_login_rate_limit():
    reset()
    setup_owner()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"name": "Hana", "passcode": "bad"}).status_code == 401
    r = client.post("/api/auth/login", json={"name": "Hana", "passcode": "owner-pass"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    # the IP limit also covers other names
    assert client.post("/api/auth/login", json={"name": "Other", "passcode": "x"}).status_code == 429
    accounts.reset_rate_limits()
    with env(HANDOVER_LOGIN_PER_MINUTE="2"):
        assert accounts.login_allowed("a", "1.1.1.1") and accounts.login_allowed("a", "2.2.2.2")
        assert not accounts.login_allowed("A", "3.3.3.3")  # per name, any letter case
    accounts.reset_rate_limits()
    assert client.post("/api/auth/login", json={"name": "Hana", "passcode": "owner-pass"}).status_code == 200


def test_token_expiry():
    reset()
    with env(HANDOVER_TOKEN_DAYS="1"):
        token = setup_owner()
        assert client.get("/api/me", headers=auth(token)).json()["user"]["name"] == "Hana"
        real = time.time
        accounts.now = lambda: real() + 2 * 86400
        try:
            r = client.get("/api/me", headers=auth(token))
            assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        finally:
            accounts.now = real


def test_user_admin():
    reset()
    owner = setup_owner()
    tid, teacher = add_user(owner, "Tom", "teacher")
    assert client.get("/api/users", headers=auth(teacher)).json()["detail"] == "only the hub owner can manage users"
    assert client.get("/api/users").status_code == 401
    assert client.post("/api/users", json={"name": "tom", "role": "learner", "passcode": "abcd"},
                       headers=auth(owner)).status_code == 409
    assert client.post("/api/users", json={"name": "Lee", "role": "boss", "passcode": "abcd"},
                       headers=auth(owner)).json()["detail"] == "role must be owner, teacher or learner"
    names = [u["name"] for u in client.get("/api/users", headers=auth(owner)).json()]
    assert names == ["Hana", "Tom"]
    r = client.patch(f"/api/users/{tid}", json={"passcode": "new-pass"}, headers=auth(owner))
    assert r.status_code == 200
    assert client.get("/api/me", headers=auth(teacher)).status_code == 401  # reset signs out everywhere
    r = client.patch(f"/api/users/{tid}", json={"role": "learner"}, headers=auth(owner))
    assert r.json()["role"] == "learner"
    owner_id = client.get("/api/me", headers=auth(owner)).json()["user"]["id"]
    assert client.patch(f"/api/users/{owner_id}", json={"role": "teacher"},
                        headers=auth(owner)).json()["detail"] == "the hub needs at least one owner"
    assert client.delete(f"/api/users/{owner_id}", headers=auth(owner)).status_code == 409
    assert client.delete(f"/api/users/{tid}", headers=auth(owner)).json() == {"deleted": tid}
    assert client.delete(f"/api/users/{tid}", headers=auth(owner)).status_code == 404


# ---------------------------------------------------------------- permissions and browsing

def _people():
    owner = setup_owner()
    users = {"owner": owner}
    ids = {}
    for name, role in (("Tom", "teacher"), ("Eda", "teacher"), ("Lee", "learner"), ("Ola", "learner")):
        ids[name], users[name] = add_user(owner, name, role)
    return users, ids


def test_permissions_matrix():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"], "published", "shared", access=((ids["Eda"], "editor"), (ids["Lee"], "learner")))
    expect = {  # who: (view, edit, publish, manage)
        "owner": (True, True, True, True), "Tom": (True, True, True, True), "Eda": (True, True, False, False),
        "Lee": (True, False, False, False), "Ola": (False, False, False, False),
    }
    for who, (view, edit, publish, manage) in expect.items():
        r = client.get("/api/courses/c1", headers=auth(users[who]))
        if not view:
            assert r.status_code == 403 and r.json()["detail"] == "you do not have access to this course", who
            continue
        p = r.json()["permissions"]
        assert (p["can_edit"], p["can_publish"], p["can_manage"]) == (edit, publish, manage), (who, p)
    assert client.get("/api/courses/c1").status_code == 401
    # real calls
    assert client.patch("/api/courses/c1", json={"title": "Fold"}, headers=auth(users["Eda"])).status_code == 200
    assert client.patch("/api/courses/c1", json={"title": "X"}, headers=auth(users["Lee"])).json()["detail"] == \
        "only the course owner or an editor can edit this course"
    assert client.patch("/api/courses/c1", json={"visibility": "everyone"}, headers=auth(users["Eda"])).json()[
        "detail"] == "only the course owner can change who can see this course"
    assert client.post("/api/courses/c1/publish", headers=auth(users["Eda"])).json()["detail"] == \
        "only the course owner can publish this course"
    assert client.patch("/api/courses/c1", json={"owner_id": ids["Eda"]}, headers=auth(users["Tom"])).json()[
        "detail"] == "only the hub owner can change a course's owner"
    assert client.post("/api/courses/c1/edit/step", json={"n": 1, "title": "x"},
                       headers=auth(users["Lee"])).status_code == 403
    r = client.patch("/api/courses/c1", json={"owner_id": ids["Eda"]}, headers=auth(users["owner"]))
    assert r.json()["owner"]["name"] == "Eda"
    assert lesson("c1")["title"] == "Fold"  # the learn screen title follows the course title
    # draft: the learner on the access list loses sight of it
    client.post("/api/courses/c1/unpublish", headers=auth(users["owner"]))
    assert client.get("/api/courses/c1", headers=auth(users["Lee"])).status_code == 403


def test_visibility_filtering():
    reset()
    users, ids = _people()
    make_lesson("legacy")
    make_course("a", ids["Tom"], "published", "everyone")
    make_course("b", ids["Tom"], "published", "shared", access=((ids["Lee"], "learner"),))
    make_course("c", ids["Tom"], "draft", "everyone")
    make_course("d", ids["Tom"], "unlisted", "everyone")
    make_course("e", ids["Tom"], "published", "only_me", access=((ids["Eda"], "editor"),))

    def ids_of(token=None, **params):
        r = client.get("/api/courses", params=params, headers=auth(token) if token else {})
        assert r.status_code == 200, r.text
        return sorted(c["id"] for c in r.json())

    assert ids_of() == ["a", "legacy"]
    assert ids_of(users["Lee"]) == ["a", "b", "legacy"]
    assert ids_of(users["Lee"], filter="shared") == ["b"]
    assert ids_of(users["Eda"]) == ["a", "e", "legacy"]
    assert ids_of(users["Tom"], filter="mine") == ["a", "b", "c", "d", "e"]
    assert ids_of(users["owner"]) == ["a", "b", "c", "d", "e", "legacy"]
    assert ids_of(users["Tom"], filter="everyone") == ["a", "legacy"]
    assert ids_of(users["Tom"], status="draft") == ["c"]
    assert ids_of(users["Tom"], q="LEG") == ["legacy"]
    assert client.get("/api/courses/d").status_code == 200  # unlisted: open by link, not listed
    assert client.get("/api/courses", params={"filter": "nope"}).status_code == 400
    item = next(c for c in client.get("/api/courses").json() if c["id"] == "a")
    assert item["owner"]["name"] == "Tom" and item["steps"] == 3 and item["duration"] == 12.0
    assert item["cover_url"] == "/lessons/a/frames/01.jpg" and item["progress"] is None


def test_publish_and_version():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"])
    r = client.post("/api/courses/c1/publish", headers=auth(users["Tom"]))
    assert r.json()["status"] == "published" and r.json()["version"] == 1 and r.json()["published_at"]
    r = client.post("/api/courses/c1/publish", json={"status": "unlisted"}, headers=auth(users["Tom"]))
    assert (r.json()["status"], r.json()["version"]) == ("unlisted", 2)
    r = client.post("/api/courses/c1/unpublish", headers=auth(users["Tom"]))
    assert (r.json()["status"], r.json()["version"]) == ("draft", 2)
    assert client.post("/api/courses/c1/publish", json={"status": "draft"},
                       headers=auth(users["Tom"])).status_code == 400
    make_course("empty", ids["Tom"], steps=0)
    assert client.post("/api/courses/empty/publish", headers=auth(users["Tom"])).json()["detail"] == \
        "a course needs at least one step to publish"
    stored = json.loads((LESSONS / "c1" / "course.json").read_text())
    assert "steps" not in stored and stored["version"] == 2
    assert "version" not in lesson("c1")  # course metadata never goes into lesson.json


def test_cover():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"])
    h = auth(users["Tom"])
    r = client.patch("/api/courses/c1", json={"cover": "frames/02.jpg"}, headers=h)
    assert r.status_code == 200 and r.json()["cover"].startswith("covers/frame-")
    assert (LESSONS / "c1" / r.json()["cover"]).read_bytes() == (LESSONS / "c1/frames/02.jpg").read_bytes()
    for bad in ("../x.jpg", "lesson.json", "frames/09.jpg", "/etc/passwd"):
        assert client.patch("/api/courses/c1", json={"cover": bad}, headers=h).status_code == 400, bad
    r = client.post("/api/courses/c1/cover", files={"file": ("c.png", PNG, "image/png")}, headers=h)
    assert r.status_code == 200 and r.json()["cover"].endswith(".png")
    assert r.json()["cover_url"] == f"/lessons/c1/{r.json()['cover']}"
    r = client.post("/api/courses/c1/cover", files={"file": ("c.txt", b"hello", "text/plain")}, headers=h)
    assert r.json()["detail"] == "cover must be a JPEG, PNG or WebP image"


def test_create_course_flow():
    reset()
    users, ids = _people()
    r = client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")},
                    data={"title": "Bike wheel", "description": "Quick release"}, headers=auth(users["Tom"]))
    assert r.status_code == 200 and r.json() == {"job": "job1", "id": "bike-wheel"}
    assert not (LESSONS / "bike-wheel").exists()
    make_lesson("bike-wheel", title="Bike wheel")  # the teach job finishes
    JOBS["job1"]["status"] = "done"
    got = client.get("/api/courses/bike-wheel", headers=auth(users["Tom"])).json()["course"]
    assert got["owner"]["name"] == "Tom" and got["status"] == "draft" and got["description"] == "Quick release"
    assert client.get("/api/courses/bike-wheel", headers=auth(users["Lee"])).status_code == 403
    assert client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")}, data={"title": "L"},
                       headers=auth(users["Lee"])).json()["detail"] == \
        "learners cannot create courses; ask the hub owner for the teacher role"
    # a failed job drops its pending owner, so a later upload with the same id is not claimed
    client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")}, data={"title": "Gone"},
                headers=auth(users["Tom"]))
    JOBS["job2"]["status"] = "error"
    make_lesson("gone")
    assert client.get("/api/courses/gone").json()["course"]["legacy"] is True


# ---------------------------------------------------------------- editor

def test_edit_operations():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"], access=((ids["Eda"], "editor"),))
    h = auth(users["Eda"])

    def post(op, body, status=200):
        r = client.post(f"/api/courses/c1/edit/{op}", json=body, headers=h)
        assert r.status_code == status, (op, body, r.text)
        return r.json()

    # boundaries
    assert post("boundaries", {"steps": [{"n": 2, "start": "00:05", "end": 8}]})["recut"] is True
    assert CALLS["recut"] == ["c1"] and CALLS["publish"] == ["c1"] and CALLS["changed"] == ["c1"]
    assert (lesson("c1")["steps"][1]["start"], lesson("c1")["steps"][1]["end"]) == ("00:05", "00:08")
    assert post("boundaries", {"steps": [{"n": 2, "start": "00:03"}]}, 400)["detail"] == \
        "step 2 starts before step 1 ends"
    assert post("boundaries", {"steps": [{"n": 9, "start": 1}]}, 400)["detail"] == "no step 9"
    assert post("boundaries", {"steps": [{"n": 1, "end": "soon"}]}, 400)["detail"].startswith("step 1 end: bad")
    assert post("boundaries", {"steps": []}, 400)["detail"] == "steps must be a list of 1 to 50 entries"
    # split
    out = post("split", {"n": 1, "at": "00:02"})
    assert [s["title"] for s in out["lesson"]["steps"]] == ["Step 1", "Step 1 (part 2)", "Step 2", "Step 3"]
    assert [s["n"] for s in out["lesson"]["steps"]] == [1, 2, 3, 4]
    assert post("split", {"n": 1, "at": "00:01.9"}, 400)["detail"].startswith("at must be inside step 1")
    # merge
    out = post("merge", {"n": 1})
    assert len(out["lesson"]["steps"]) == 3 and out["lesson"]["steps"][0]["title"] == "Step 1"
    assert out["lesson"]["steps"][0]["end"] == "00:04"
    assert post("merge", {"n": 3}, 400)["detail"] == "step 3 is the last step; there is nothing after it to merge"
    # delete
    assert len(post("delete", {"n": 2})["lesson"]["steps"]) == 2
    post("delete", {"n": 1})
    assert post("delete", {"n": 1}, 400)["detail"] == "a lesson needs at least one step"
    recuts = len(CALLS["recut"])
    # step metadata: no recut (clips do not change)
    out = post("step", {"n": 1, "title": "Fold in half", "check_type": "manual"})
    assert out["recut"] is False and len(CALLS["recut"]) == recuts
    assert out["lesson"]["steps"][0]["check_question"] == ""
    out = post("step", {"n": 1, "check_type": "camera", "common_mistake": "Crease it hard"})
    assert out["lesson"]["steps"][0]["check_question"] == "Is this step finished?"
    assert post("step", {"n": 1, "check_type": "maybe"}, 400)["detail"] == "check_type must be camera or manual"
    assert post("step", {"n": 1}, 400)["detail"] == "nothing to change"
    assert post("step", {"n": 1, "title": ""}, 400)["detail"] == "title must be 1 to 120 characters"
    assert post("step", {"n": 1, "colour": "red"}, 400)["detail"] == "unknown field: colour"
    # captions: writes the file, no recut
    out = post("captions", {"n": 1, "cues": [{"start": 1.5, "end": "00:03", "text": "Fold it"},
                                             {"start": 0, "end": 1, "text": "Start flat"}]})
    assert out["recut"] is False and len(CALLS["recut"]) == recuts
    vtt = (LESSONS / "c1" / "captions" / "01.vtt").read_text()
    assert vtt == ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nStart flat\n\n"
                   "00:00:01.500 --> 00:00:03.000\nFold it\n\n")
    assert post("captions", {"n": 1, "cues": [{"start": 2, "end": 1, "text": "x"}]}, 400)["detail"].startswith("cue 1")
    assert post("captions", {"n": 1, "cues": [{"start": 0, "end": 1, "text": "a --> b"}]}, 400)["detail"] == \
        "cue 1 text cannot contain --> or blank lines"
    assert post("captions", {"n": 1, "cues": [{"start": 0, "end": 99, "text": "x"}]}, 400)["detail"].startswith("cue 1")
    # a failing recut restores lesson.json and leaves no history entry
    before, undo_before = lesson("c1"), client.get("/api/courses/c1", headers=h).json()["history"]["undo"]
    RECUT_FAIL["error"] = ValueError("step 1: bad timestamp: 'x'")
    got = post("boundaries", {"steps": [{"n": 1, "end": 11}]}, 400)["detail"]
    assert got == "step 1: bad timestamp: 'x'", (got, lesson("c1"))
    RECUT_FAIL["error"] = RuntimeError(f"ffmpeg broke in {LESSONS}/c1")
    assert post("boundaries", {"steps": [{"n": 1, "end": 11}]}, 500)["detail"] == \
        "recut failed: RuntimeError: ffmpeg broke in <lessons>/c1"
    RECUT_FAIL["error"] = None
    assert lesson("c1") == before
    assert client.get("/api/courses/c1", headers=h).json()["history"]["undo"] == undo_before
    # a recut or edit already running: 409
    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    routes_library.configure(lock=lock)
    try:
        assert post("step", {"n": 1, "title": "x"}, 409)["detail"] == "recut already running"
    finally:
        lock.release()
        routes_library.HUB.lock = None
    audit = [json.loads(line) for line in (DATA / "audit.jsonl").read_text().splitlines()]
    assert {a["op"] for a in audit if a["kind"] == "course_edit"} >= {"boundaries", "split", "merge", "delete",
                                                                      "step", "captions"}
    assert all(a["user_id"] == ids["Eda"] for a in audit if a["kind"] == "course_edit")


def test_selftest():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"])
    h = auth(users["Tom"])
    out = client.post("/api/courses/c1/edit/selftest", headers=h).json()
    assert [r["n"] for r in out["results"]] == [1, 2]  # step 3 is manual
    assert all(r["self_test"]["ok"] for r in out["results"])
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"])
    h = auth(users["Tom"])
    out = client.post("/api/courses/c1/edit/selftest", json={"n": 2}, headers=h).json()
    assert CALLS["selftest"] == [["manual", "camera", "manual"]]  # only step 2 was asked
    assert out["results"] == [{"n": 2, "self_test": {"own": "yes", "prev": "no", "ok": True}}]
    saved = lesson("c1")["steps"]
    assert [s["check_type"] for s in saved] == ["camera", "camera", "manual"]  # restored
    assert "self_test" not in saved[0] and saved[1]["self_test"]["ok"]
    r = client.post("/api/courses/c1/edit/selftest", json={"n": 3}, headers=h)
    assert r.json()["detail"] == "step 3 is manual; the self-test only runs on camera steps"


def test_voiceover_job_and_undo():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"])
    h = auth(users["Tom"])
    seen = {}
    saved = {k: getattr(voice, k) for k in ("_lesson_frames", "_lesson_transcript", "write_script",
                                             "apply_voiceover", "undo")}

    def fake_apply(d, scripts, mode, voice_name):
        seen.update(mode=mode, voice=voice_name, steps=[sc.n for sc in scripts])
        return {"voiced": [sc.n for sc in scripts], "skipped": [], "voiceover": {"mode": mode}}

    voice._lesson_frames = lambda d, steps, out: ([[] for _ in steps], [4.0 for _ in steps])
    voice._lesson_transcript = lambda d: []
    voice.write_script = lambda steps, transcript, frames, clip_seconds=None: (_ for _ in ()).throw(
        voice.VoiceError("no Claude key"))
    voice.apply_voiceover = fake_apply
    voice.undo = lambda d: 2
    # a context-managed client keeps one event loop alive between requests, as uvicorn does, so the
    # background job can still run after the request that started it has returned
    try:
        with TestClient(app) as c:
            assert c.post("/api/courses/c1/edit/voiceover", json={"mode": "loud"}, headers=h).status_code == 400
            assert c.post("/api/courses/c1/edit/voiceover", json={"steps": [7]}, headers=h).status_code == 400
            r = c.post("/api/courses/c1/edit/voiceover", json={"mode": "replace", "voice": "af_heart",
                                                               "steps": [1, 2]}, headers=h)
            assert r.status_code == 200, r.text
            job = r.json()["job"]
            for _ in range(250):
                j = c.get(f"/api/courses/c1/jobs/{job}", headers=h).json()
                if j["status"] in ("done", "error"):
                    break
                time.sleep(0.02)
            assert j["status"] == "done", j
            assert seen == {"mode": "replace", "voice": "af_heart", "steps": [1, 2]}
            assert j["result"]["note"] == "no Claude key; the step titles were read instead"
            assert j["result"]["scripts"] == [{"n": 1, "sentences": ["Step 1."]}, {"n": 2, "sentences": ["Step 2."]}]
            assert c.get("/api/courses/c1/jobs/nope", headers=h).status_code == 404
            assert c.post("/api/courses/c1/edit/voiceover/undo", headers=h).json()["restored"] == 2
            assert c.post("/api/courses/c1/edit/voiceover", headers=auth(users["Lee"])).status_code == 403
    finally:
        for k, v in saved.items():
            setattr(voice, k, v)


def test_undo_redo():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"])
    h = auth(users["Tom"])
    assert client.post("/api/courses/c1/edit/undo", headers=h).json()["detail"] == "nothing to undo"
    client.post("/api/courses/c1/edit/delete", json={"n": 2}, headers=h)
    assert len(lesson("c1")["steps"]) == 2
    recuts = len(CALLS["recut"])
    r = client.post("/api/courses/c1/edit/undo", headers=h).json()
    assert len(r["lesson"]["steps"]) == 3 and r["recut"] is True and len(CALLS["recut"]) == recuts + 1
    assert r["history"] == {"undo": 0, "redo": 1}
    r = client.post("/api/courses/c1/edit/redo", headers=h).json()
    assert len(r["lesson"]["steps"]) == 2 and r["history"] == {"undo": 1, "redo": 0}
    # captions undo puts the old file back, without a recut
    old = (LESSONS / "c1/captions/01.vtt").read_text()
    client.post("/api/courses/c1/edit/captions", json={"n": 1, "cues": [{"start": 0, "end": 1, "text": "New"}]},
                headers=h)
    assert "New" in (LESSONS / "c1/captions/01.vtt").read_text()
    r = client.post("/api/courses/c1/edit/undo", headers=h).json()
    assert r["recut"] is False and (LESSONS / "c1/captions/01.vtt").read_text() == old
    client.post("/api/courses/c1/edit/redo", headers=h)
    assert "New" in (LESSONS / "c1/captions/01.vtt").read_text()
    # a new edit clears redo; the stack keeps HANDOVER_HISTORY_DEPTH entries
    with env(HANDOVER_HISTORY_DEPTH="3"):
        for i in range(5):
            client.post("/api/courses/c1/edit/step", json={"n": 1, "title": f"T{i}"}, headers=h)
        hist = client.get("/api/courses/c1", headers=h).json()["history"]
        assert hist == {"undo": 3, "redo": 0}
    for _ in range(3):
        client.post("/api/courses/c1/edit/undo", headers=h)
    assert lesson("c1")["steps"][0]["title"] == "T1"
    assert (DATA / "history" / "c1" / "stack.json").is_file()


# ---------------------------------------------------------------- insights, scoring, ratings

def test_insights_zero_and_sample():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"], "published", "everyone")
    h = auth(users["Tom"])
    r = client.get("/api/courses/c1/insights", headers=h).json()
    assert r["enough_data"] is False and r["reason"] == "not enough data" and r["steps"] == []
    assert r["runs"] == {"started": 0, "finished": 0, "n": 0}
    assert r["ratings"] == {"average": None, "count": 0, "distribution": {str(k): 0 for k in range(1, 6)}}
    assert client.get("/api/courses/c1/insights", headers=auth(users["Lee"])).json()["detail"] == \
        "only the course owner, an editor or an admin of its organization can see insights"
    write_events(sample_run("r1", ids["Lee"]) + sample_run("r2", ids["Ola"]))
    write_events([ev("advance", "r9", "other", from_step=0, to_step=1, reason="camera", step_seconds=99)])
    r = client.get("/api/courses/c1/insights", headers=h).json()
    assert r["enough_data"] is True and r["runs"] == {"started": 2, "finished": 2, "n": 2}
    s1, s2, s3 = r["steps"]
    assert s1["median_seconds"] == {"value": 2.5, "n": 4} and s1["expert_seconds"] == 4.0
    assert s1["manual_rate"] == {"value": 0.5, "n": 4}
    assert s1["check_failure_rate"] == {"value": 0.0, "n": 4}
    assert s2["mistakes_caught"] == {"value": 2, "n": 4} and s2["back_presses"] == {"value": 2, "n": 4}
    assert s2["check_failure_rate"] == {"value": 1.0, "n": 2} and s2["manual_rate"] == {"value": 1.0, "n": 2}
    assert s3["median_seconds"] == {"value": 6.0, "n": 2}
    assert s1["score"] == {"value": 97.0, "n": 2} and s2["score"] == {"value": 60.0, "n": 2}
    # after a change to the step layout, older events no longer count (unless all=1)
    client.post("/api/courses/c1/edit/boundaries", json={"steps": [{"n": 1, "end": 3.5}]}, headers=h)
    assert client.get("/api/courses/c1/insights", headers=h).json()["enough_data"] is False
    assert client.get("/api/courses/c1/insights", params={"all": 1}, headers=h).json()["enough_data"] is True


def test_progress():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"], "published", "everyone")
    assert client.get("/api/courses/c1/progress").json()["reason"] == "sign in to track progress"
    assert client.get("/api/courses/c1/progress", headers=auth(users["Lee"])).json()["known"] is False
    write_events(sample_run("r1", ids["Lee"])[:5])  # stopped after step 1
    p = client.get("/api/courses/c1/progress", headers=auth(users["Lee"])).json()
    assert p["known"] and (p["runs"], p["completed"], p["last_steps_done"], p["total"]) == (1, 0, 1, 3)
    write_events(sample_run("r2", ids["Lee"]))
    p = client.get("/api/courses/c1/progress", headers=auth(users["Lee"])).json()
    assert (p["runs"], p["completed"], p["best_steps_done"], p["last_finished"]) == (2, 1, 3, True)
    item = next(c for c in client.get("/api/courses", headers=auth(users["Lee"])).json() if c["id"] == "c1")
    assert item["progress"]["completed"] == 1
    assert client.get("/api/courses/c1/progress", headers=auth(users["Ola"])).json()["known"] is False


def test_private_profile_analytics_are_real_aggregate_only():
    reset()
    users, ids = _people()
    assert client.get("/api/profile/analytics").status_code == 401
    assert client.get("/api/profile/analytics", headers=auth(users["Lee"])).json() == \
        {"known": False, "reason": "no runs yet", "runs": 0}
    rows = sample_run("r1", ids["Lee"])
    rows.insert(1, ev("camera_first_frame", "r1", source="glasses", platform="ios", connect_latency_ms=420))
    rows.append(ev("run_start", "mock-run", learner=ids["Lee"], check_mode="mock"))
    rows.append(ev("run_done", "mock-run", total_seconds=999))
    rows.extend(sample_run("other", ids["Ola"]))
    write_events(rows)
    a = client.get("/api/profile/analytics", headers=auth(users["Lee"])).json()
    assert a["known"] and (a["runs"], a["completed_runs"], a["courses_completed"]) == (1, 1, 1)
    assert a["completion_rate"] == 1.0 and a["minutes_practiced"] == 0.4
    assert (a["checks"], a["check_pass_rate"], a["check_errors"]) == (2, 0.5, 1)
    assert (a["camera_verified_steps"], a["manual_steps"], a["mistakes_caught"]) == (1, 3, 1)
    assert a["current_streak_days"] == 1 and a["camera_sources"] == ["glasses"]
    assert a["median_camera_ready_ms"] == 420
    assert "learner" not in a and "lesson_id" not in a and ids["Lee"] not in json.dumps(a)


def test_profile_analytics_reads_the_retained_event_rotation():
    reset()
    users, ids = _people()
    write_events(sample_run("older", ids["Lee"]))
    EVENTS.replace(EVENTS.with_name(EVENTS.name + ".1"))
    write_events(sample_run("newer", ids["Lee"]))
    a = client.get("/api/profile/analytics", headers=auth(users["Lee"])).json()
    assert (a["runs"], a["completed_runs"], a["courses_completed"], a["minutes_practiced"]) == (2, 2, 1, 0.8)


def _lesson_for_scoring(mistake: str = "Fold along the crease") -> dict:
    return {"steps": [
        {"n": 1, "title": "A", "start": "00:00", "end": "00:04", "check_type": "camera"},
        {"n": 2, "title": "B", "start": "00:04", "end": "00:08", "check_type": "camera", "common_mistake": mistake},
        {"n": 3, "title": "C", "start": "00:08", "end": "00:12", "check_type": "manual"},
    ]}


def test_scoring_formula():
    events = [library._flatten(r) for r in sample_run("r1", "u1")]
    out = scoring.score_run("r1", events, _lesson_for_scoring())
    s1, s2, s3 = out["steps"]
    # step 1: 5 s of 4 (1.25x) -> time 100; camera 100; no mistakes 100; no back 100; confidence 0.8 -> 80
    assert s1["completion"] == "camera" and s1["score"] == 97  # 30 + 30 + 15 + 10 + 12
    comp = {c["name"]: c for c in s1["components"]}
    assert comp["time"]["input"] == {"seconds": 5.0, "expert_seconds": 4.0, "ratio": 1.25}
    assert comp["confidence"]["input"] == 0.8 and comp["confidence"]["score"] == 80
    assert sum(c["weight"] for c in s1["components"]) == 1.0
    # step 2: 12 s of 4 (3x) -> 40; Next on a camera step 60; 1 mistake corrected 85; 1 back 80; no confidence
    comp = {c["name"]: c for c in s2["components"]}
    assert (comp["time"]["score"], comp["completion"]["score"], comp["mistakes"]["score"],
            comp["retries"]["score"]) == (40, 60, 85, 80)
    assert comp["confidence"]["used"] is False and comp["confidence"]["score"] is None
    assert s2["score"] == 60  # (12 + 18 + 12.75 + 8) / 0.85 = 59.7
    # step 3: manual step done with Next, 6 s of 4 (1.5x)
    assert s3["completion"] == "manual" and s3["score"] == 100
    assert out["score"] == 86 and out["label"] == "Good" and out["finished"] is True
    assert out["best_step"] == {"n": 3, "score": 100} and out["weakest_step"] == {"n": 2, "score": 60}
    assert out["tip"] == "Step 2: Fold along the crease"
    out = scoring.score_run("r1", events, _lesson_for_scoring(mistake=""))
    assert out["tip"] == "Step 2 took 3.0x the expert's time. Watch the clip once more before you start it."
    assert [scoring.label(s) for s in (95, 90, 89, 75, 74, None)] == \
        ["Excellent", "Excellent", "Good", "Good", "Keep practicing", None]


def test_scoring_not_enough_data():
    events = [library._flatten(r) for r in sample_run("r1", "u1")[:2]]
    out = scoring.score_run("r1", events, _lesson_for_scoring())
    assert [s["score"] for s in out["steps"]] == [None, None, None]
    assert [s["reason"] for s in out["steps"]] == ["not finished in this run", "not enough data", "not enough data"]
    assert (out["score"], out["label"], out["reason"], out["tip"]) == (None, None, "not enough data", None)
    assert scoring.score_run("r0", [], _lesson_for_scoring())["score"] is None


def test_runs_and_score_routes():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"], "published", "everyone")
    write_events(sample_run("r1", ids["Lee"]) + sample_run("r2", ids["Ola"]))
    runs = client.get("/api/courses/c1/runs", headers=auth(users["Lee"])).json()["runs"]
    assert [r["run_id"] for r in runs] == ["r1"] and runs[0]["score"] == 86
    assert client.get("/api/courses/c1/runs").status_code == 401
    assert client.get("/api/runs/r1/score", headers=auth(users["Lee"])).json()["label"] == "Good"
    assert client.get("/api/runs/r1/score", headers=auth(users["Ola"])).status_code == 403
    out = client.get("/api/runs/r1/score", headers=auth(users["Tom"])).json()
    assert out["learner"] == ids["Lee"] and out["lesson_changed_after_run"] is False
    assert client.get("/api/runs/nope/score", headers=auth(users["Tom"])).json()["detail"] == "run not found"
    assert client.get("/api/runs/bad%20id/score").json()["detail"] == "bad run id"


def test_ratings():
    reset()
    users, ids = _people()
    make_course("c1", ids["Tom"], "published", "shared", access=((ids["Lee"], "learner"), (ids["Eda"], "editor")))
    lee = auth(users["Lee"])
    assert client.post("/api/courses/c1/rating", json={"stars": 4}).status_code == 401
    assert client.post("/api/courses/c1/rating", json={"stars": 0}, headers=lee).json()["detail"] == \
        "stars must be a whole number from 1 to 5"
    assert client.post("/api/courses/c1/rating", json={"stars": True}, headers=lee).status_code == 400
    assert client.post("/api/courses/c1/rating", json={"stars": 3, "comment": "x" * 501}, headers=lee).json()[
        "detail"] == "comment must be at most 500 characters"
    r = client.post("/api/courses/c1/rating", json={"stars": 3, "comment": "Step 2 is fast"}, headers=lee)
    assert r.status_code == 200 and r.json()["summary"]["average"] == 3.0
    r = client.post("/api/courses/c1/rating", json={"stars": 5, "comment": "  "}, headers=lee)
    assert r.json()["summary"]["count"] == 1 and r.json()["rating"]["comment"] is None
    for who in ("Tom", "Eda"):
        assert client.post("/api/courses/c1/rating", json={"stars": 5}, headers=auth(users[who])).json()[
            "detail"] == "people who own or edit a course cannot rate it"
    assert client.post("/api/courses/c1/rating", json={"stars": 5}, headers=auth(users["Ola"])).json()[
        "detail"] == "you do not have access to this course"
    client.post("/api/courses/c1/rating", json={"stars": 2, "comment": "Too quick"}, headers=auth(users["owner"]))
    g = client.get("/api/courses/c1/ratings", headers=lee).json()
    assert (g["average"], g["count"], g["comments"], g["mine"]["stars"]) == (3.5, 2, None, 5)
    g = client.get("/api/courses/c1/ratings", headers=auth(users["Eda"])).json()
    assert [c["comment"] for c in g["comments"]] == ["Too quick"] and g["comments"][0]["name"] == "Hana"
    assert client.get("/api/courses/c1/insights", headers=auth(users["Tom"])).json()["ratings"]["count"] == 2
    assert client.delete("/api/courses/c1/rating", headers=lee).json()["summary"]["count"] == 1
    assert client.delete("/api/courses/c1/rating", headers=lee).json()["detail"] == "no rating to delete"


# ---------------------------------------------------------------- auth modes

def test_anonymous_optional_and_required_modes():
    reset()
    make_lesson("demo")
    # optional (default): the open flow works on legacy lessons, with no users at all
    assert client.get("/api/courses/demo").json()["permissions"]["can_edit"] is True
    assert client.post("/api/courses/demo/edit/step", json={"n": 1, "title": "Open"}).status_code == 200
    assert client.post("/api/courses/demo/publish").status_code == 401
    r = client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")}, data={"title": "Anon"})
    assert r.status_code == 200 and not (DATA / "pending" / "anon.json").exists()
    owner = setup_owner()
    tid, teacher = add_user(owner, "Tom", "teacher")
    make_course("mine", tid, "published", "everyone")
    assert client.post("/api/courses/mine/edit/step", json={"n": 1, "title": "x"}).status_code == 401
    assert client.get("/api/courses/mine").status_code == 200
    with env(HANDOVER_AUTH="required"):
        assert client.get("/api/me").json()["auth"] == "required"
        assert client.get("/api/courses/demo").status_code == 200  # reading stays open
        assert client.post("/api/courses/demo/edit/step", json={"n": 1, "title": "x"}).status_code == 401
        assert client.post("/api/courses/demo/edit/step", json={"n": 1, "title": "x"},
                           headers=auth(teacher)).json()["detail"] == \
            "only the hub owner can edit a lesson that has no course owner"
        assert client.post("/api/courses/demo/edit/step", json={"n": 1, "title": "x"},
                           headers=auth(owner)).status_code == 200
        assert client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")},
                           data={"title": "No"}).status_code == 401
    assert client.get("/api/courses/../etc").status_code in (400, 404)
    assert client.get("/api/courses/bad.id").json()["detail"] == "bad lesson id"
    assert client.get("/api/courses/missing").json()["detail"] == "lesson not found"


# ---------------------------------------------------------------- organizations

def _org(token: str, name: str = "Bike Club", **extra) -> dict:
    r = client.post("/api/orgs", json={"name": name, **extra}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _code(token: str, org_id: str, **body) -> str:
    r = client.post(f"/api/orgs/{org_id}/invites", json=body, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["code"]


def _join(token: str, code: str):
    accounts.reset_rate_limits()  # every test user shares one client IP
    return client.post("/api/orgs/join", json={"code": code}, headers=auth(token))


def test_org_create_get_patch_delete():
    reset()
    users, ids = _people()
    assert client.post("/api/orgs", json={"name": "X"}).status_code == 401
    org = _org(users["Lee"])  # any signed-in user, even a hub learner
    assert org["slug"] == "bike-club" and org["role"] == "org_admin" and org["owner"]["name"] == "Lee"
    assert org["members"] == [{"user_id": ids["Lee"], "name": "Lee", "role": "org_admin",
                               "joined": org["members"][0]["joined"]}] and org["invites"] == []
    assert _org(users["Tom"])["slug"] == "bike-club-2"
    assert client.post("/api/orgs", json={"name": "Y", "slug": "bike-club"}, headers=auth(users["Tom"])).json()[
        "detail"] == "that slug is taken"
    assert client.post("/api/orgs", json={"name": "Y", "slug": "Bad Slug"}, headers=auth(users["Tom"])).status_code == 400
    assert client.post("/api/orgs", json={"name": ""}, headers=auth(users["Tom"])).status_code == 400
    oid = org["id"]
    assert client.get(f"/api/orgs/{oid}").status_code == 401
    assert client.get(f"/api/orgs/{oid}", headers=auth(users["Ola"])).json()["detail"] == \
        "you are not a member of this organization"
    assert client.get(f"/api/orgs/{oid}", headers=auth(users["owner"])).status_code == 200  # hub owner sees all
    assert client.get("/api/orgs/nope", headers=auth(users["Lee"])).json()["detail"] == "organization not found"
    r = client.patch(f"/api/orgs/{oid}", json={"name": "Wheel Club", "slug": "wheels"}, headers=auth(users["Lee"]))
    assert (r.json()["name"], r.json()["slug"]) == ("Wheel Club", "wheels")
    mine = client.get("/api/orgs", headers=auth(users["Lee"])).json()
    assert [o["slug"] for o in mine["orgs"]] == ["wheels"] and mine["invites"] == []
    assert client.get("/api/orgs").status_code == 401
    # delete: creator or hub owner only; org courses go back to only_me
    make_course("c1", ids["Tom"], "published")
    client.post(f"/api/orgs/{oid}/invites", json={"username": "Tom", "role": "teacher"}, headers=auth(users["Lee"]))
    inv = client.get("/api/orgs", headers=auth(users["Tom"])).json()["invites"][0]
    client.post("/api/orgs/join", json={"invite_id": inv["id"]}, headers=auth(users["Tom"]))
    client.patch("/api/courses/c1", json={"org_id": oid, "visibility": "org"}, headers=auth(users["Tom"]))
    assert client.delete(f"/api/orgs/{oid}", headers=auth(users["Tom"])).json()["detail"] == \
        "only the organization's creator or the hub owner can delete it"
    assert client.delete(f"/api/orgs/{oid}", headers=auth(users["Lee"])).json() == {"deleted": oid}
    stored = json.loads((LESSONS / "c1" / "course.json").read_text())
    assert (stored["org_id"], stored["visibility"]) == (None, "only_me")


def test_org_invites_and_membership():
    reset()
    users, ids = _people()
    oid = _org(users["Tom"])["id"]
    lee, ola, eda = auth(users["Lee"]), auth(users["Ola"]), auth(users["Eda"])
    # single-use code: the code is shown once and only its hash is stored
    code = _code(users["Tom"], oid, role="learner")
    assert code not in (DATA / "orgs.json").read_text()
    assert client.post(f"/api/orgs/{oid}/invites", json={}, headers=lee).status_code == 403  # not a member
    assert _join(users["Lee"], code).json()["role"] == "learner"
    assert _join(users["Lee"], code).json()["detail"] == "invite code is not valid"  # used up
    assert _join(users["Ola"], "made-up").json()["detail"] == "invite code is not valid"
    assert client.post(f"/api/orgs/{oid}/invites", json={}, headers=lee).json()["detail"] == \
        "only an admin of this organization can do that"
    # multi-use code, then revoked
    multi = client.post(f"/api/orgs/{oid}/invites", json={"role": "teacher", "max_uses": None},
                        headers=auth(users["Tom"])).json()
    assert multi["max_uses"] is None and _join(users["Eda"], multi["code"]).json()["role"] == "teacher"
    assert _join(users["Eda"], multi["code"]).json()["detail"] == "you are already a member of this organization"
    assert client.delete(f"/api/orgs/{oid}/invites/{multi['id']}", headers=lee).status_code == 403
    assert client.delete(f"/api/orgs/{oid}/invites/{multi['id']}", headers=auth(users["Tom"])).status_code == 200
    assert _join(users["Ola"], multi["code"]).status_code == 404
    # expiry
    short = _code(users["Tom"], oid, expires_days=1)
    real = library.clock
    library.clock = lambda: real() + 2 * 86400
    try:
        assert _join(users["Ola"], short).status_code == 404
    finally:
        library.clock = real
    for bad in ({"role": "boss"}, {"expires_days": 0}, {"max_uses": 0}, {"username": "Ola", "max_uses": 2}):
        assert client.post(f"/api/orgs/{oid}/invites", json=bad, headers=auth(users["Tom"])).status_code == 400, bad
    # by username: shows up for the invitee, who can accept or decline
    assert client.post(f"/api/orgs/{oid}/invites", json={"username": "Nobody"},
                       headers=auth(users["Tom"])).json()["detail"] == "user not found"
    assert client.post(f"/api/orgs/{oid}/invites", json={"username": "lee"},
                       headers=auth(users["Tom"])).json()["detail"] == "that user is already a member"
    inv = client.post(f"/api/orgs/{oid}/invites", json={"username": "ola", "role": "learner"},
                      headers=auth(users["Tom"])).json()
    assert inv["user"]["name"] == "Ola" and "code" not in inv
    pending = client.get("/api/orgs", headers=ola).json()["invites"]
    assert [(i["id"], i["org"]["slug"]) for i in pending] == [(inv["id"], "bike-club")]
    assert client.post("/api/orgs/join", json={"invite_id": inv["id"]}, headers=lee).json()["detail"] == \
        "invite not found"  # addressed to someone else
    assert client.delete(f"/api/orgs/{oid}/invites/{inv['id']}", headers=ola).json() == {"deleted": inv["id"]}
    inv = client.post(f"/api/orgs/{oid}/invites", json={"username": "Ola"}, headers=auth(users["Tom"])).json()
    detail = client.get(f"/api/orgs/{oid}", headers=auth(users["Tom"])).json()
    # the used-up and revoked codes are gone; the 1-day code (still live in real time) and Ola's invite remain
    assert [(i["kind"], i.get("uses")) for i in detail["invites"]] == [("code", 0), ("user", None)]
    assert client.get(f"/api/orgs/{oid}", headers=lee).json()["invites"] is None  # admins only
    assert client.post("/api/orgs/join", json={"invite_id": inv["id"]}, headers=ola).json()["role"] == "learner"
    assert client.post("/api/orgs/join", json={"code": "x", "invite_id": "y"}, headers=ola).status_code == 400
    # roles, removal, leaving, and the last admin
    assert client.patch(f"/api/orgs/{oid}/members/{ids['Lee']}", json={"role": "teacher"}, headers=lee).status_code == 403
    assert client.patch(f"/api/orgs/{oid}/members/{ids['Lee']}", json={"role": "teacher"},
                        headers=auth(users["Tom"])).json() == {"user_id": ids["Lee"], "role": "teacher"}
    assert client.patch(f"/api/orgs/{oid}/members/{ids['Tom']}", json={"role": "learner"},
                        headers=auth(users["Tom"])).json()["detail"] == "the organization needs at least one admin"
    assert client.patch(f"/api/orgs/{oid}/members/nobody", json={"role": "learner"},
                        headers=auth(users["Tom"])).json()["detail"] == "member not found"
    assert client.post(f"/api/orgs/{oid}/leave", headers=auth(users["Tom"])).status_code == 409
    assert client.delete(f"/api/orgs/{oid}/members/{ids['Tom']}", headers=auth(users["Tom"])).status_code == 409
    assert client.delete(f"/api/orgs/{oid}/members/{ids['Ola']}", headers=auth(users["Tom"])).json() == \
        {"removed": ids["Ola"]}
    assert client.post(f"/api/orgs/{oid}/leave", headers=eda).json() == {"left": oid}
    assert client.post(f"/api/orgs/{oid}/leave", headers=eda).status_code == 403
    assert [m["name"] for m in client.get(f"/api/orgs/{oid}", headers=lee).json()["members"]] == ["Tom", "Lee"]
    # deleting a hub user removes their memberships
    client.delete(f"/api/users/{ids['Lee']}", headers=auth(users["owner"]))
    assert [m["name"] for m in client.get(f"/api/orgs/{oid}", headers=auth(users["Tom"])).json()["members"]] == ["Tom"]


def test_org_join_rate_limit():
    reset()
    users, ids = _people()
    accounts.reset_rate_limits()
    for _ in range(5):
        assert client.post("/api/orgs/join", json={"code": "guess"}, headers=auth(users["Lee"])).status_code == 404
    r = client.post("/api/orgs/join", json={"code": "guess"}, headers=auth(users["Ola"]))
    assert r.status_code == 429 and r.headers["retry-after"] == "60"  # the IP limit covers other users too


def test_org_permission_matrix():
    reset()
    users, ids = _people()
    # Eda: org_admin; Tom: org teacher (course owner); Lee: org learner; Ola: not a member
    oid = _org(users["Eda"])["id"]
    assert _join(users["Tom"], _code(users["Eda"], oid, role="teacher")).status_code == 200
    assert _join(users["Lee"], _code(users["Eda"], oid, role="learner")).status_code == 200
    r = client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")}, data={"title": "Wheel",
                    "org_id": oid}, headers=auth(users["Tom"]))
    assert r.status_code == 200
    make_lesson("wheel")
    JOBS["job1"]["status"] = "done"
    assert client.get("/api/courses/wheel", headers=auth(users["Tom"])).json()["course"]["org"]["id"] == oid
    # learners of the org cannot create in it; a hub learner who teaches in the org can
    assert client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")},
                       data={"title": "L", "org_id": oid}, headers=auth(users["Lee"])).json()["detail"] == \
        "only teachers and admins of this organization can create courses in it"
    assert client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")},
                       data={"title": "L", "org_id": oid}, headers=auth(users["Ola"])).status_code == 403
    assert client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")},
                       data={"title": "L", "org_id": "nope"}, headers=auth(users["Tom"])).status_code == 404
    accounts.update_user(ids["Lee"], role="learner")
    oid2 = _org(users["Lee"], "Lee Org")["id"]
    assert client.post("/api/courses", files={"file": ("t.mp4", b"x", "video/mp4")},
                       data={"title": "Lee Course", "org_id": oid2}, headers=auth(users["Lee"])).status_code == 200

    def can(who, path, method="get", **kw):
        r = getattr(client, method)(path, headers=auth(users[who]) if who else {}, **kw)
        return r.status_code

    # draft: only the course owner, org admin and hub owner see it
    expect_draft = {"owner": 200, "Eda": 200, "Tom": 200, "Lee": 403, "Ola": 403, None: 401}
    for who, code in expect_draft.items():
        assert can(who, "/api/courses/wheel") == code, (who, "draft")
    # published to the org: every member sees it, outsiders do not
    r = client.post("/api/courses/wheel/publish", json={"visibility": "org"}, headers=auth(users["Tom"]))
    assert r.json()["visibility"] == "org" and r.json()["status"] == "published"
    expect = {  # who: view, edit, insights, publish, unpublish
        "owner": (200, 200, 200, 200, 200), "Eda": (200, 403, 200, 403, 200), "Tom": (200, 200, 200, 200, 200),
        "Lee": (200, 403, 403, 403, 403), "Ola": (403, 403, 403, 403, 403), None: (401, 401, 401, 401, 401),
    }
    for who, (view, edit, insights, publish, unpublish) in expect.items():
        assert can(who, "/api/courses/wheel") == view, (who, "view")
        assert can(who, "/api/courses/wheel/edit/step", "post", json={"n": 1, "title": "T"}) == edit, (who, "edit")
        assert can(who, "/api/courses/wheel/insights") == insights, (who, "insights")
    perms = client.get("/api/courses/wheel", headers=auth(users["Eda"])).json()["permissions"]
    assert (perms["can_edit"], perms["can_unpublish"], perms["can_publish"], perms["can_see_insights"]) == \
        (False, True, False, True)
    for who, (view, edit, insights, publish, unpublish) in expect.items():
        assert can(who, "/api/courses/wheel/publish", "post") == publish, (who, "publish")
        assert can(who, "/api/courses/wheel/unpublish", "post") == unpublish, (who, "unpublish")
        client.post("/api/courses/wheel/publish", headers=auth(users["Tom"]))  # back to published for the next
    # moving a course into an org needs a teaching role there; org visibility needs an org
    make_course("solo", ids["Tom"], "published")
    assert client.patch("/api/courses/solo", json={"visibility": "org"}, headers=auth(users["Tom"])).json()[
        "detail"] == "org visibility needs an organization (org_id)"
    assert client.patch("/api/courses/solo", json={"org_id": oid2}, headers=auth(users["Tom"])).json()[
        "detail"] == "you can only move a course into an organization where you teach"
    assert client.patch("/api/courses/solo", json={"org_id": oid, "visibility": "org"},
                        headers=auth(users["Tom"])).json()["org"]["id"] == oid


def test_org_filters_insights_ratings_profile():
    reset()
    users, ids = _people()
    oid = _org(users["Tom"])["id"]
    _join(users["Lee"], _code(users["Tom"], oid))
    make_course("c1", ids["Tom"], "published", "org")
    course = json.loads((LESSONS / "c1" / "course.json").read_text())
    course["org_id"] = oid
    library.write_json(LESSONS / "c1" / "course.json", course)
    make_course("pub", ids["Tom"], "published", "everyone")
    make_course("draft", ids["Tom"])

    def ids_of(who=None, **params):
        return sorted(c["id"] for c in client.get("/api/courses", params=params,
                                                  headers=auth(users[who]) if who else {}).json())

    assert ids_of("Lee") == ["c1", "pub"] and ids_of("Lee", filter="orgs") == ["c1"]
    assert ids_of("Lee", org=oid) == ["c1"] and ids_of("Ola") == ["pub"] and ids_of("Ola", filter="orgs") == []
    org = client.get(f"/api/orgs/{oid}", headers=auth(users["Lee"])).json()
    assert [c["id"] for c in org["courses"]] == ["c1"]
    # org-scoped insights and ratings count only the org's members
    write_events(sample_run("r1", ids["Lee"]) + sample_run("r2", ids["Ola"]))
    client.post("/api/courses/c1/rating", json={"stars": 4, "comment": "good"}, headers=auth(users["Lee"]))
    library.set_rating("c1", ids["Ola"], 2, "outsider")  # e.g. rated before the course moved into the org
    full = client.get("/api/courses/c1/insights", headers=auth(users["Tom"])).json()
    scoped = client.get("/api/courses/c1/insights", params={"org": oid}, headers=auth(users["Tom"])).json()
    assert full["runs"]["n"] == 2 and scoped["runs"]["n"] == 1 and scoped["org"] == oid
    assert scoped["steps"][0]["median_seconds"]["n"] == 2 and scoped["ratings"]["count"] == 1
    r = client.get("/api/courses/c1/ratings", params={"org": oid}, headers=auth(users["Tom"])).json()
    assert (r["count"], r["average"], [c["comment"] for c in r["comments"]]) == (1, 4.0, ["good"])
    assert client.get("/api/courses/c1/ratings", headers=auth(users["Tom"])).json()["count"] == 2
    assert client.get("/api/courses/c1/insights", params={"org": "nope"},
                      headers=auth(users["Tom"])).status_code == 404
    other = _org(users["Ola"], "Other")["id"]
    assert client.get("/api/courses/c1/insights", params={"org": other}, headers=auth(users["Tom"])).json()[
        "detail"] == "you are not a member of this organization"
    # public profile: no private fields, only what the caller may see
    p = client.get(f"/api/users/{ids['Tom']}/public").json()
    assert set(p) == {"id", "name", "courses", "orgs"} and [c["id"] for c in p["courses"]] == ["pub"]
    assert p["orgs"] == []
    p = client.get(f"/api/users/{ids['Tom']}/public", headers=auth(users["Lee"])).json()
    assert sorted(c["id"] for c in p["courses"]) == ["c1", "pub"] and [o["id"] for o in p["orgs"]] == [oid]
    assert "passcode" not in json.dumps(p) and "role" not in json.dumps(p["courses"])
    assert client.get("/api/users/nobody/public").json()["detail"] == "user not found"


if __name__ == "__main__":
    try:
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok", name)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

"""Accounts, course library, publishing, editor, scoring and rating routes, as one APIRouter (prefix /api).

The hub wires it up in main.py:

    from server import routes_library
    app.include_router(routes_library.router)
    routes_library.configure(lock=lesson_write_lock, on_lesson_changed=engine.reload_if_active,
                             upload=upload_lesson, job_status=lambda job: jobs.get(job),
                             publish=lambda d, lesson_id: publish_lesson_files(lesson_id))

Everything works without configure() too (tests do that): the router then uses its own lock, no reload hook,
databricks.upload_lesson_files for publishing, and POST /api/courses answers 503 until an upload hook is set.
Reference: server/docs/library.md.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import importlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from server import accounts, library, scoring

log = logging.getLogger("handover.library")

router = APIRouter(prefix="/api")

MAX_BODY = 1024**2
MAX_STEPS = 50
MIN_STEP_S = 0.3
MAX_CUES = 300
MAX_COVER_BYTES = 5 * 1024**2
MAX_JOBS_KEPT = 50
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
VOICE_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
FILTERS = ("all", "mine", "shared", "orgs", "everyone")


# ---------------------------------------------------------------- hub hooks

class Hub:
    lock: Optional[asyncio.Lock] = None  # main.lesson_write_lock: recut, delete and every edit never overlap
    on_lesson_changed: Optional[Callable[[str], None]] = None  # main: engine.reload_if_active
    upload: Optional[Callable[..., Awaitable[dict]]] = None  # main.upload_lesson(file=, title=, id=)
    publish: Optional[Callable[[Path, str], None]] = None  # default: databricks.upload_lesson_files
    emit: Optional[Callable[[dict], None]] = None  # optional: gets every course_edit audit row


HUB = Hub()
_own_lock: Optional[asyncio.Lock] = None


def configure(*, lock: Optional[asyncio.Lock] = None, on_lesson_changed: Optional[Callable[[str], None]] = None,
              upload: Optional[Callable[..., Awaitable[dict]]] = None,
              job_status: Optional[Callable[[str], Optional[dict]]] = None,
              publish: Optional[Callable[[Path, str], None]] = None,
              emit: Optional[Callable[[dict], None]] = None) -> None:
    """Hand the router the hub's shared pieces. Arguments left out keep their current value."""
    for name, value in (("lock", lock), ("on_lesson_changed", on_lesson_changed), ("upload", upload),
                        ("publish", publish), ("emit", emit)):
        if value is not None:
            setattr(HUB, name, value)
    if job_status is not None:
        library.JOB_STATUS = job_status


def _lock() -> asyncio.Lock:
    global _own_lock
    if HUB.lock is not None:
        return HUB.lock
    if _own_lock is None:
        _own_lock = asyncio.Lock()
    return _own_lock


def _redact(text: str) -> str:
    """Absolute paths out of anything a client sees (the lessons folder as given and as resolved, then the repo)."""
    root = library.lessons_root()
    raw = os.environ.get("HANDOVER_LESSONS") or str(root)
    for path, label in ((root, "<lessons>"), (raw, "<lessons>"), (library.REPO, "<repo>")):
        text = text.replace(str(path), label)
    return text


def _publish_files(lesson_id: str) -> None:
    d = library.lesson_dir(lesson_id)
    try:
        if HUB.publish is not None:
            HUB.publish(d, lesson_id)
            return
        db = importlib.import_module("server.databricks")
        db.upload_lesson_files(d, lesson_id)  # returns at once; a no-op without Databricks credentials
    except Exception as e:
        log.warning("lesson upload after edit skipped: %s", type(e).__name__)


def _after_change(lesson_id: str, op: str, user: Optional[dict], files_changed: bool = True, **fields: Any) -> None:
    """After any successful change: audit line, hub event hook, engine reload, Databricks upload."""
    row = library.audit("course_edit", lesson_id, user, op=op, **fields)
    for hook, arg in ((HUB.emit, row), (HUB.on_lesson_changed if files_changed else None, lesson_id)):
        if hook is None:
            continue
        try:
            hook(arg)
        except Exception:
            log.exception("hub hook failed after %s on %s", op, lesson_id)
    if files_changed:
        _publish_files(lesson_id)


# ---------------------------------------------------------------- request helpers

async def _body(request: Request, required: bool = True) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "body is larger than 1 MB")
    if not raw.strip():
        if required:
            raise HTTPException(400, "body must be a JSON object")
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise HTTPException(400, "body must be JSON")
    if not isinstance(data, dict):
        raise HTTPException(400, "body must be a JSON object")
    return data


def _only(body: dict, allowed: tuple[str, ...]) -> None:
    for key in body:
        if key not in allowed:
            raise HTTPException(400, f"unknown field: {key}")


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(400, f"{name} must be a whole number")
    return value


def _text(value: Any, name: str, lo: int, hi: int) -> str:
    if not isinstance(value, str):
        raise HTTPException(400, f"{name} must be text")
    value = value.strip()
    if not lo <= len(value) <= hi:
        raise HTTPException(400, f"{name} must be {lo} to {hi} characters" if lo else f"{name} must be at most {hi} characters")
    return value


def _seconds(value: Any, name: str) -> float:
    try:
        return library.parse_time(value)
    except ValueError:
        raise HTTPException(400, f"{name}: bad timestamp: {value!r}")


def _steps(lesson: dict) -> list[dict]:
    steps = lesson.get("steps")
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        raise HTTPException(500, "lesson.json unreadable: steps")
    return steps


def _index(lesson: dict, n: Any) -> int:
    n = _int(n, "n")
    if not 1 <= n <= len(_steps(lesson)):
        raise HTTPException(400, f"no step {n}")
    return n - 1


def _renumber(steps: list[dict]) -> list[dict]:
    for i, s in enumerate(steps, start=1):
        s["n"] = i
    return steps


def _check_layout(steps: list[dict]) -> None:
    """Every step at least MIN_STEP_S long, none before 0, none starting before the previous one ends."""
    prev_end = None
    for i, s in enumerate(steps, start=1):
        a, b = _seconds(s.get("start"), f"step {i}"), _seconds(s.get("end"), f"step {i}")
        if a < 0:
            raise HTTPException(400, f"step {i} starts before 0")
        if b - a < MIN_STEP_S:
            raise HTTPException(400, f"step {i} is shorter than {MIN_STEP_S} s")
        if prev_end is not None and a < prev_end - 0.05:
            raise HTTPException(400, f"step {i} starts before step {i - 1} ends")
        prev_end = b


def _ctx(lesson_id: str, user: Optional[dict], action: str) -> tuple[dict, dict]:
    lesson = library.read_lesson(lesson_id)
    course = library.load_course(lesson_id, lesson)
    library.require(action, user, course)
    return lesson, course


def _busy(lock: asyncio.Lock) -> None:
    if lock.locked():
        raise HTTPException(409, "recut already running")


def _owner_out(course: dict, names: dict) -> Optional[dict]:
    oid = course.get("owner_id")
    return {"id": oid, "name": names.get(oid, "Deleted user")} if oid else None


def _course_out(lesson_id: str, lesson: dict, course: dict, names: Optional[dict] = None) -> dict:
    names = accounts.user_names() if names is None else names
    out = {k: course.get(k) for k in ("id", "title", "description", "cover", "status", "visibility", "created",
                                      "updated", "published_at", "version", "steps_changed_at", "legacy")}
    out["access"] = [{"user_id": a.get("user_id"), "name": names.get(a.get("user_id"), "Deleted user"),
                      "role": a.get("role")} for a in course.get("access") or [] if isinstance(a, dict)]
    out["owner"] = _owner_out(course, names)
    org = library.get_org(course.get("org_id"))
    out["org"] = {"id": org["id"], "name": org["name"], "slug": org["slug"]} if org else None
    out["cover_url"] = library.cover_url(lesson_id, course)
    out["steps"] = len(lesson.get("steps") or [])
    out["duration"] = library.lesson_duration(lesson)
    return out


# ---------------------------------------------------------------- accounts

@router.get("/me")
def me(user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    return {"user": user, "auth": library.auth_mode(), "setup_needed": not accounts.has_users()}


@router.get("/profile/analytics")
def profile_analytics(user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """The signed-in person's aggregate learning telemetry; never raw events or another learner's data."""
    if user is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    return library.learner_analytics(user["id"])


@router.post("/auth/setup")
async def auth_setup(request: Request) -> dict:
    body = await _body(request)
    _only(body, ("name", "passcode"))
    user = await asyncio.to_thread(accounts.setup_owner, body.get("name"), body.get("passcode"))
    log.info("hub owner created")
    return {"user": user, **accounts.issue_token(user["id"])}


@router.post("/auth/login")
async def auth_login(request: Request) -> dict:
    body = await _body(request)
    ip = request.client.host if request.client else "unknown"
    if not accounts.login_allowed(body.get("name"), ip):
        raise HTTPException(429, "too many login attempts; try again in a minute", headers={"Retry-After": "60"})
    user = await asyncio.to_thread(accounts.authenticate, body.get("name"), body.get("passcode"))
    if user is None:
        raise HTTPException(401, "wrong name or passcode")
    return {"user": user, **accounts.issue_token(user["id"])}


@router.post("/auth/logout")
def auth_logout(request: Request) -> dict:
    token = accounts.bearer(request)
    if token is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    accounts.revoke_token(token)
    return {"ok": True}


@router.post("/auth/handoff/start")
def auth_handoff_start() -> dict:
    """Create a two-minute, one-use QR claim. It carries no account or bearer token."""
    return accounts.start_handoff()


@router.post("/auth/handoff/approve")
async def auth_handoff_approve(request: Request, user: dict = Depends(accounts.require_user)) -> dict:
    body = await _body(request)
    _only(body, ("claim",))
    return accounts.approve_handoff(body.get("claim"), user["id"])


@router.post("/auth/handoff/redeem")
async def auth_handoff_redeem(request: Request) -> dict:
    body = await _body(request)
    _only(body, ("claim",))
    return accounts.redeem_handoff(body.get("claim")) or {"status": "pending"}


@router.get("/users")
def users_list(owner: dict = Depends(accounts.require_owner)) -> list:
    return accounts.list_users()


@router.post("/users")
async def users_create(request: Request, owner: dict = Depends(accounts.require_owner)) -> dict:
    body = await _body(request)
    _only(body, ("name", "role", "passcode"))
    return await asyncio.to_thread(accounts.create_user, body.get("name"), body.get("role"), body.get("passcode"))


@router.patch("/users/{user_id}")
async def users_update(user_id: str, request: Request, owner: dict = Depends(accounts.require_owner)) -> dict:
    body = await _body(request)
    _only(body, ("name", "role", "passcode"))
    if not body:
        raise HTTPException(400, "nothing to change")
    return await asyncio.to_thread(accounts.update_user, user_id, body.get("name"), body.get("role"),
                                   body.get("passcode"))


@router.delete("/users/{user_id}")
def users_delete(user_id: str, owner: dict = Depends(accounts.require_owner)) -> dict:
    accounts.delete_user(user_id)
    return {"deleted": user_id}


# ---------------------------------------------------------------- browse

@router.get("/courses")
def courses_list(filter: str = "all", q: str = "", status: Optional[str] = None, org: Optional[str] = None,
                 user: Optional[dict] = Depends(accounts.current_user)) -> list:
    if filter not in FILTERS:
        raise HTTPException(400, "filter must be all, mine, shared, orgs or everyone")
    if status is not None and status not in library.STATUSES:
        raise HTTPException(400, "status must be draft, published or unlisted")
    if len(q) > 100:
        raise HTTPException(400, "q must be at most 100 characters")
    needle = q.strip().lower()
    names = accounts.user_names()
    my_orgs = {o["id"] for o, _ in library.user_orgs(user["id"])} if user else set()
    out = []
    for lesson_id in library.lesson_ids():
        try:
            lesson = library.read_lesson(lesson_id)
            course = library.load_course(lesson_id, lesson)
        except HTTPException:
            continue
        if not library.listable(user, course):
            continue
        if filter == "mine" and not (user and course.get("owner_id") == user["id"]):
            continue
        if filter == "shared" and library.access_role(user, course) is None:
            continue
        if filter == "orgs" and course.get("org_id") not in my_orgs:
            continue
        if org is not None and course.get("org_id") != org:
            continue
        if filter == "everyone" and not (course["status"] == "published" and course["visibility"] == "everyone"):
            continue
        if status and course["status"] != status:
            continue
        if needle and not any(needle in str(course.get(k) or "").lower() for k in ("title", "description", "id")):
            continue
        item = {k: v for k, v in _course_out(lesson_id, lesson, course, names).items()
                if k in ("id", "title", "cover_url", "steps", "duration", "status", "visibility", "owner",
                         "updated", "legacy", "version", "org")}
        prog = library.progress(lesson_id, user, item["steps"]) if user else None
        item["progress"] = prog if prog and prog.get("known") else None
        out.append(item)
    out.sort(key=lambda c: str(c.get("updated") or ""), reverse=True)
    return out


@router.get("/courses/{lesson_id}")
def course_get(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    lesson, course = _ctx(lesson_id, user, "view")
    perms = library.permissions(user, course)
    return {"course": _course_out(lesson_id, lesson, course), "lesson": lesson, "permissions": perms,
            "history": library.history_counts(lesson_id) if perms["can_edit"] else None}


@router.get("/courses/{lesson_id}/progress")
def course_progress(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    lesson, _ = _ctx(lesson_id, user, "view")
    return library.progress(lesson_id, user, len(lesson.get("steps") or []))


# ---------------------------------------------------------------- create, sharing and publishing

@router.post("/courses")
async def course_create(file: UploadFile = File(...), title: str = Form(""), id: Optional[str] = Form(None),
                        description: str = Form(""), org_id: Optional[str] = Form(None),
                        user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """A draft from an uploaded take, through the hub's own upload job. Anonymous (optional mode) makes a legacy
    lesson, as POST /api/lesson does. With org_id the draft belongs to that organization."""
    org_id = org_id or None
    library.require_create(user, org_id)
    if HUB.upload is None:
        raise HTTPException(503, "uploads are not available")
    title = title.strip() or "Untitled lesson"
    if len(title) > 120:
        raise HTTPException(400, "title must be 1 to 120 characters")
    description = _text(description, "description", 0, 2000)
    result = await HUB.upload(file=file, title=title, id=id)
    if user is not None:
        course = library.new_course(user["id"], title, description)
        course["org_id"] = org_id
        library.add_pending(result["id"], result["job"], course)
    library.audit("course_create", result["id"], user, job=result["job"])
    return {"job": result["job"], "id": result["id"]}


def _cover(lesson_id: str, value: Any) -> Optional[str]:
    """A cover path: null, a covers/ image, or a frames/ image (copied into covers/ so a recut cannot change it)."""
    if value is None:
        return None
    path = library.safe_rel(lesson_id, value)
    if path is None or not value.startswith(("frames/", "covers/")) or path.suffix.lower() not in library.COVER_SUFFIXES:
        raise HTTPException(400, "cover must be an image in frames/ or covers/")
    if not path.is_file():
        raise HTTPException(400, "cover file not found")
    if value.startswith("covers/"):
        return value
    data = path.read_bytes()
    rel = f"covers/frame-{hashlib.sha256(data).hexdigest()[:12]}{path.suffix.lower()}"
    dest = library.lesson_dir(lesson_id) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file():
        shutil.copyfile(path, dest)
    return rel


def _access(course: dict, value: Any) -> list[dict]:
    if not isinstance(value, list) or len(value) > library.MAX_ACCESS:
        raise HTTPException(400, f"access must be a list of at most {library.MAX_ACCESS} entries")
    names = accounts.user_names()
    out: dict[str, dict] = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) - {"user_id", "role"}:
            raise HTTPException(400, "each access entry is {\"user_id\", \"role\"}")
        uid, role = entry.get("user_id"), entry.get("role")
        if uid not in names:
            raise HTTPException(400, f"unknown user: {uid}")
        if role not in library.ACCESS_ROLES:
            raise HTTPException(400, "access role must be editor or learner")
        if uid == course.get("owner_id"):
            raise HTTPException(400, "the course owner does not need an access entry")
        out[uid] = {"user_id": uid, "role": role}
    return list(out.values())


def _sharing(user: Optional[dict], course: dict, body: dict) -> dict:
    """Validated visibility and org_id changes (used by PATCH and publish). Moving a course into an org needs a
    teacher or admin role there; org visibility needs an org."""
    changes: dict[str, Any] = {}
    if "org_id" in body:
        oid = body["org_id"]
        if oid is not None:
            if library.get_org(oid) is None:
                raise HTTPException(400, "organization not found")
            if user.get("role") != "owner" and library.org_role(user, oid) not in ("org_admin", "teacher"):
                raise HTTPException(403, "you can only move a course into an organization where you teach")
        changes["org_id"] = oid
    if "visibility" in body:
        if body["visibility"] not in library.VISIBILITIES:
            raise HTTPException(400, "visibility must be only_me, shared, org or everyone")
        changes["visibility"] = body["visibility"]
    merged = {**course, **changes}
    if merged["visibility"] == "org" and not merged.get("org_id"):
        raise HTTPException(400, "org visibility needs an organization (org_id)")
    return changes


@router.patch("/courses/{lesson_id}")
async def course_patch(lesson_id: str, request: Request,
                       user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("title", "description", "cover", "visibility", "access", "owner_id", "org_id"))
    if not body:
        raise HTTPException(400, "nothing to change")
    lesson, course = _ctx(lesson_id, user, "view")
    if {"title", "description", "cover"} & set(body):
        library.require("edit", user, course)
    if {"visibility", "access", "org_id"} & set(body):
        library.require("manage", user, course)
    if "owner_id" in body:
        library.require("transfer", user, course)
    changes: dict[str, Any] = {}
    if "title" in body:
        changes["title"] = _text(body["title"], "title", 1, 120)
    if "description" in body:
        changes["description"] = _text(body["description"], "description", 0, 2000)
    changes.update(_sharing(user, course, body))
    if "owner_id" in body:
        oid = body["owner_id"]
        target = accounts.get_user(oid) if oid is not None else None
        if oid is not None and (target is None or target["role"] not in ("owner", "teacher")):
            raise HTTPException(400, "the new owner must be a hub owner or a teacher")
        changes["owner_id"] = oid
    if "access" in body:
        changes["access"] = _access({**course, **changes}, body["access"])
    if "cover" in body:
        changes["cover"] = _cover(lesson_id, body["cover"])
    if "title" in changes and changes["title"] != lesson.get("title"):
        lock = _lock()  # the learn screen reads lesson.json's title, so keep the two in step
        _busy(lock)
        async with lock:
            fresh = library.read_lesson(lesson_id)
            fresh["title"] = changes["title"]
            library.write_json(library.lesson_dir(lesson_id) / "lesson.json", fresh)
            lesson = fresh
    course.update(changes)
    library.save_course(lesson_id, course)
    _after_change(lesson_id, "patch", user, files_changed="title" in changes, fields=sorted(changes))
    return _course_out(lesson_id, lesson, course)


def _image_kind(data: bytes) -> Optional[str]:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


@router.post("/courses/{lesson_id}/cover")
async def course_cover(lesson_id: str, file: UploadFile = File(...),
                       user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    lesson, course = _ctx(lesson_id, user, "edit")
    data = await file.read(MAX_COVER_BYTES + 1)
    if len(data) > MAX_COVER_BYTES:
        raise HTTPException(413, "cover is larger than 5 MB")
    suffix = _image_kind(data)
    if suffix is None:
        raise HTTPException(400, "cover must be a JPEG, PNG or WebP image")
    rel = f"covers/cover-{hashlib.sha256(data).hexdigest()[:12]}{suffix}"
    dest = library.lesson_dir(lesson_id) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    course["cover"] = rel
    library.save_course(lesson_id, course)
    _after_change(lesson_id, "cover", user, files_changed=False)
    return _course_out(lesson_id, lesson, course)


@router.post("/courses/{lesson_id}/publish")
async def course_publish(lesson_id: str, request: Request,
                         user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request, required=False)
    _only(body, ("status", "visibility", "org_id"))
    status = body.get("status", "published")
    if status not in ("published", "unlisted"):
        raise HTTPException(400, "status must be published or unlisted")
    lesson, course = _ctx(lesson_id, user, "publish")
    if not lesson.get("steps"):
        raise HTTPException(400, "a course needs at least one step to publish")
    course.update(_sharing(user, course, body))  # e.g. {"visibility": "org", "org_id": ...} publishes to an org
    course.update(status=status, published_at=library.now_iso(), version=int(course.get("version") or 0) + 1)
    library.save_course(lesson_id, course)
    _after_change(lesson_id, "publish", user, files_changed=False, status=status, version=course["version"])
    return _course_out(lesson_id, lesson, course)


@router.post("/courses/{lesson_id}/unpublish")
def course_unpublish(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    lesson, course = _ctx(lesson_id, user, "moderate")
    course["status"] = "draft"
    library.save_course(lesson_id, course)
    _after_change(lesson_id, "unpublish", user, files_changed=False)
    return _course_out(lesson_id, lesson, course)


# ---------------------------------------------------------------- editor

def _recut(d: Path) -> dict:
    from server import teach  # looked up per call, so tests can replace teach.recut

    return teach.recut(d)


def _restore(lesson_id: str, snap: dict) -> None:
    d = library.lesson_dir(lesson_id)
    library.write_text(d / "lesson.json", snap["lesson"])
    for rel, text in (snap.get("files") or {}).items():
        path = library.safe_rel(lesson_id, rel)
        if path is None:
            continue
        if text is None:
            path.unlink(missing_ok=True)
        else:
            library.write_text(path, text)


async def _run_recut(lesson_id: str, before: dict) -> dict:
    """teach.recut in a worker thread; on failure lesson.json and the named files go back to `before`."""
    d = library.lesson_dir(lesson_id)
    try:
        return await asyncio.to_thread(_recut, d)
    except ValueError as e:
        _restore(lesson_id, before)
        raise HTTPException(400, _redact(str(e)))
    except Exception as e:
        _restore(lesson_id, before)
        msg = _redact(f"{type(e).__name__}: {e}")
        log.error("recut %s failed: %s", lesson_id, msg)
        raise HTTPException(500, f"recut failed: {msg}")


Prepare = Callable[[dict], tuple[Optional[dict], dict]]


async def _edit(lesson_id: str, user: Optional[dict], op: str, prepare: Prepare) -> dict:
    """The one path every editor operation takes: permission, lesson lock, validate (prepare), snapshot for
    undo, write, recut when the step timing changed, restore on failure, then hooks."""
    _ctx(lesson_id, user, "edit")
    lock = _lock()
    _busy(lock)
    async with lock:
        d = library.lesson_dir(lesson_id)
        lesson = library.read_lesson(lesson_id)
        new, files = prepare(copy.deepcopy(lesson))
        recut = new is not None and library.timing_key(new) != library.timing_key(lesson)
        if new is not None:
            new["id"] = lesson_id
            if recut:
                new.pop("voiceover", None)  # a recut rebuilds the clips without the voice
        before = library.snapshot(lesson_id, files)
        library.push_history(lesson_id, {**before, "op": op, "at": library.now_iso(),
                                         "user_id": user["id"] if user else None})
        try:
            for rel, text in files.items():
                library.write_text(library.safe_rel(lesson_id, rel), text)
            if new is not None:
                library.write_json(d / "lesson.json", new)
            result = await _run_recut(lesson_id, before) if recut else (new or lesson)
        except BaseException:
            _restore(lesson_id, before)
            library.drop_last_history(lesson_id)
            raise
        library.touch_course(lesson_id, steps_changed=recut)
    _after_change(lesson_id, op, user, recut=recut)
    return {"lesson": result, "history": library.history_counts(lesson_id), "recut": recut}


@router.post("/courses/{lesson_id}/edit/boundaries")
async def edit_boundaries(lesson_id: str, request: Request,
                          user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("steps",))
    items = body.get("steps")
    if not isinstance(items, list) or not items or len(items) > MAX_STEPS:
        raise HTTPException(400, f"steps must be a list of 1 to {MAX_STEPS} entries")

    def prepare(lesson: dict) -> tuple[dict, dict]:
        steps = _steps(lesson)
        seen = set()
        for item in items:
            if not isinstance(item, dict) or set(item) - {"n", "start", "end"}:
                raise HTTPException(400, "each entry is {\"n\", \"start\", \"end\"}")
            i = _index(lesson, item.get("n"))
            if i in seen:
                raise HTTPException(400, f"step {i + 1} is listed twice")
            seen.add(i)
            for key in ("start", "end"):
                if key in item:
                    steps[i][key] = library.fmt_time(_seconds(item[key], f"step {i + 1} {key}"))
            if "start" in item or "end" in item:
                steps[i].pop("ref_time", None)
                steps[i].pop("self_test", None)
        _check_layout(steps)
        return lesson, {}

    return await _edit(lesson_id, user, "boundaries", prepare)


DERIVED = ("clip", "captions", "ref_frame", "ref_time", "self_test")


@router.post("/courses/{lesson_id}/edit/split")
async def edit_split(lesson_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("n", "at"))

    def prepare(lesson: dict) -> tuple[dict, dict]:
        steps = _steps(lesson)
        i = _index(lesson, body.get("n"))
        if len(steps) >= MAX_STEPS:
            raise HTTPException(400, "too many steps")
        if "at" not in body:
            raise HTTPException(400, "at is required")
        at = _seconds(body["at"], "at")
        a, b = _seconds(steps[i].get("start"), f"step {i + 1}"), _seconds(steps[i].get("end"), f"step {i + 1}")
        if not a + MIN_STEP_S <= at <= b - MIN_STEP_S:
            raise HTTPException(400, f"at must be inside step {i + 1}, at least {MIN_STEP_S} s from each end")
        first = {k: v for k, v in steps[i].items() if k not in DERIVED}
        second = copy.deepcopy(first)
        first["end"] = second["start"] = library.fmt_time(at)
        second["title"] = f"{first.get('title') or f'Step {i + 1}'} (part 2)"
        steps[i:i + 1] = [first, second]
        _renumber(steps)
        _check_layout(steps)
        return lesson, {}

    return await _edit(lesson_id, user, "split", prepare)


@router.post("/courses/{lesson_id}/edit/merge")
async def edit_merge(lesson_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("n",))

    def prepare(lesson: dict) -> tuple[dict, dict]:
        steps = _steps(lesson)
        i = _index(lesson, body.get("n"))
        if i + 1 >= len(steps):
            raise HTTPException(400, f"step {i + 1} is the last step; there is nothing after it to merge")
        # The merged step ends where the second one ends, so it keeps that step's check and reference time,
        # and the first step's title and start.
        merged = {k: v for k, v in steps[i + 1].items() if k not in ("clip", "captions", "ref_frame", "self_test")}
        merged["start"] = steps[i].get("start")
        merged["title"] = steps[i].get("title") or merged.get("title") or ""
        steps[i:i + 2] = [merged]
        _renumber(steps)
        _check_layout(steps)
        return lesson, {}

    return await _edit(lesson_id, user, "merge", prepare)


@router.post("/courses/{lesson_id}/edit/delete")
async def edit_delete(lesson_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("n",))

    def prepare(lesson: dict) -> tuple[dict, dict]:
        steps = _steps(lesson)
        i = _index(lesson, body.get("n"))
        if len(steps) == 1:
            raise HTTPException(400, "a lesson needs at least one step")
        del steps[i]
        _renumber(steps)
        return lesson, {}

    return await _edit(lesson_id, user, "delete", prepare)


@router.post("/courses/{lesson_id}/edit/step")
async def edit_step(lesson_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("n", "title", "check_type", "check_question", "common_mistake"))
    if len(body) < 2:
        raise HTTPException(400, "nothing to change")

    def prepare(lesson: dict) -> tuple[dict, dict]:
        step = _steps(lesson)[_index(lesson, body.get("n"))]
        if "title" in body:
            step["title"] = _text(body["title"], "title", 1, 120)
        if "check_type" in body:
            if body["check_type"] not in ("camera", "manual"):
                raise HTTPException(400, "check_type must be camera or manual")
            step["check_type"] = body["check_type"]
        if "check_question" in body:
            step["check_question"] = _text(body["check_question"], "check_question", 0, 300)
        if "common_mistake" in body:
            step["common_mistake"] = _text(body["common_mistake"], "common_mistake", 0, 300)
        if step.get("check_type") == "manual":  # CONTRACT.md section 3
            step["check_question"] = ""
        elif not (step.get("check_question") or "").strip():
            step["check_question"] = library.DEFAULT_QUESTION
        if {"check_type", "check_question"} & set(body):
            step.pop("self_test", None)  # answered for the old question
        return lesson, {}

    return await _edit(lesson_id, user, "step", prepare)


@router.post("/courses/{lesson_id}/edit/captions")
async def edit_captions(lesson_id: str, request: Request,
                        user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("n", "cues"))
    cues = body.get("cues")
    if not isinstance(cues, list) or len(cues) > MAX_CUES:
        raise HTTPException(400, f"cues must be a list of at most {MAX_CUES} entries")

    def prepare(lesson: dict) -> tuple[None, dict]:
        i = _index(lesson, body.get("n"))
        step = _steps(lesson)[i]
        rel = str(step.get("captions") or f"captions/{i + 1:02d}.vtt")
        if not rel.startswith("captions/") or not rel.endswith(".vtt") or library.safe_rel(lesson_id, rel) is None:
            raise HTTPException(400, f"step {i + 1} has no captions file")
        length = library.step_seconds(step)
        rows = []
        for k, cue in enumerate(cues, start=1):
            if not isinstance(cue, dict) or set(cue) - {"start", "end", "text"}:
                raise HTTPException(400, "each cue is {\"start\", \"end\", \"text\"}")
            a, b = _seconds(cue.get("start"), f"cue {k} start"), _seconds(cue.get("end"), f"cue {k} end")
            if a < 0 or b <= a or (length is not None and b > length + 0.5):
                raise HTTPException(400, f"cue {k} must start at 0 or later, end after it starts, and end "
                                         f"within the clip")
            text = _text(cue.get("text"), f"cue {k} text", 1, 300)
            if "-->" in text or "\n\n" in text:
                raise HTTPException(400, f"cue {k} text cannot contain --> or blank lines")
            rows.append((a, b, text))
        rows.sort(key=lambda r: r[0])
        lines = ["WEBVTT", ""]
        for a, b, text in rows:
            lines += [f"{library.fmt_vtt(a)} --> {library.fmt_vtt(b)}", text, ""]
        return None, {rel: "\n".join(lines) + "\n"}

    return await _edit(lesson_id, user, "captions", prepare)


@router.post("/courses/{lesson_id}/edit/selftest")
async def edit_selftest(lesson_id: str, request: Request,
                        user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """teach.self_test_lesson_async for every camera step, or only step n (the others are hidden as manual
    for the run, so only that step's two check calls are made)."""
    body = await _body(request, required=False)
    _only(body, ("n",))
    _ctx(lesson_id, user, "edit")
    lock = _lock()
    _busy(lock)
    async with lock:
        from server import teach

        d = library.lesson_dir(lesson_id)
        lesson = library.read_lesson(lesson_id)
        only = _index(lesson, body["n"]) if "n" in body else None
        if only is not None and _steps(lesson)[only].get("check_type") == "manual":
            raise HTTPException(400, f"step {only + 1} is manual; the self-test only runs on camera steps")
        before = library.snapshot(lesson_id)
        library.push_history(lesson_id, {**before, "op": "selftest", "at": library.now_iso(),
                                         "user_id": user["id"] if user else None})
        try:
            if only is not None:
                trial = copy.deepcopy(lesson)
                for i, s in enumerate(_steps(trial)):
                    if i != only:
                        s["check_type"] = "manual"
                library.write_json(d / "lesson.json", trial)
            tested = await teach.self_test_lesson_async(d)
            if only is not None:
                final = copy.deepcopy(lesson)
                got = (tested.get("steps") or [{}] * len(_steps(final)))[only].get("self_test")
                final["steps"][only].pop("self_test", None)
                if got is not None:
                    final["steps"][only]["self_test"] = got
                library.write_json(d / "lesson.json", final)
                tested = final
        except Exception as e:
            _restore(lesson_id, before)
            library.drop_last_history(lesson_id)
            msg = _redact(f"{type(e).__name__}: {e}")
            log.error("self-test %s failed: %s", lesson_id, msg)
            raise HTTPException(500, f"self-test failed: {msg}")
        library.touch_course(lesson_id)
    _after_change(lesson_id, "selftest", user, step=None if only is None else only + 1)
    results = [{"n": s.get("n", i + 1), "self_test": s.get("self_test")} for i, s in enumerate(tested.get("steps") or [])
               if (only is None and s.get("check_type") != "manual") or i == only]
    return {"results": results, "lesson": tested, "history": library.history_counts(lesson_id)}


async def _apply_history(lesson_id: str, user: Optional[dict], direction: str) -> dict:
    _ctx(lesson_id, user, "edit")
    lock = _lock()
    _busy(lock)
    async with lock:
        target = library.peek_history(lesson_id, direction)
        if target is None:
            raise HTTPException(409, f"nothing to {direction}")
        current_lesson = library.read_lesson(lesson_id)
        current = {**library.snapshot(lesson_id, (target.get("files") or {}).keys()),
                   "op": target.get("op"), "at": library.now_iso(), "user_id": user["id"] if user else None}
        library.swap_history(lesson_id, direction, current)
        try:
            restored = json.loads(target["lesson"])
            recut = library.timing_key(restored) != library.timing_key(current_lesson)
            if recut:
                restored.pop("voiceover", None)
            elif "voiceover" in current_lesson:  # clips are untouched, so the voice in them stays
                restored["voiceover"] = current_lesson["voiceover"]
            else:
                restored.pop("voiceover", None)
            restored["id"] = lesson_id
            _restore(lesson_id, {"lesson": json.dumps(restored, indent=2, ensure_ascii=False) + "\n",
                                 "files": target.get("files") or {}})
            result = await _run_recut(lesson_id, current) if recut else restored
        except BaseException:
            _restore(lesson_id, current)
            library.unswap_history(lesson_id, direction, target)
            raise
        library.touch_course(lesson_id, steps_changed=recut)
    _after_change(lesson_id, direction, user, recut=recut, undone_op=target.get("op"))
    return {"lesson": result, "history": library.history_counts(lesson_id), "recut": recut}


@router.post("/courses/{lesson_id}/edit/undo")
async def edit_undo(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    return await _apply_history(lesson_id, user, "undo")


@router.post("/courses/{lesson_id}/edit/redo")
async def edit_redo(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    return await _apply_history(lesson_id, user, "redo")


# ---------------------------------------------------------------- voiceover jobs

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_tasks: set[asyncio.Task] = set()


def _set_job(job: str, **kw: Any) -> None:
    with _jobs_lock:
        _jobs[job].update(kw)


def _voice_work(d: Path, mode: str, voice_name: Optional[str], only: Optional[set[int]]) -> dict:
    from server import voice

    lesson = json.loads((d / "lesson.json").read_text(encoding="utf-8"))
    steps = [s for i, s in enumerate(lesson.get("steps") or []) if only is None or int(s.get("n", i + 1)) in only]
    transcript = voice._lesson_transcript(d)
    note = None
    with tempfile.TemporaryDirectory(prefix="handover-voice-frames-") as tmp:
        frames, seconds = voice._lesson_frames(d, steps, Path(tmp))
        try:
            scripts = voice.write_script(steps, transcript, frames, clip_seconds=seconds)
        except voice.VoiceError as e:
            scripts = voice.fallback_scripts(steps, seconds)
            note = f"{e}; the step titles were read instead"
    result = voice.apply_voiceover(d, scripts, mode, voice_name)
    return {**result, "note": note, "scripts": [{"n": sc.n, "sentences": list(sc.sentences)} for sc in scripts]}


async def _voice_job(job: str, lesson_id: str, user: Optional[dict], lock: asyncio.Lock, mode: str,
                     voice_name: Optional[str], only: Optional[set[int]]) -> None:
    """Runs with the lesson lock already held by the request; releases it when the work ends."""
    result = None
    try:
        try:
            _set_job(job, status="running", message="writing and speaking the narration")
            result = await asyncio.to_thread(_voice_work, library.lesson_dir(lesson_id), mode, voice_name, only)
            library.touch_course(lesson_id)
            _set_job(job, status="done", message="ready", result=result)
        finally:
            lock.release()
    except Exception as e:
        msg = _redact(f"{type(e).__name__}: {e}")[:400]
        log.error("voiceover job %s failed: %s", job, msg)
        _set_job(job, status="error", message=msg)
        return
    _after_change(lesson_id, "voiceover", user, voiced=result.get("voiced"))


@router.post("/courses/{lesson_id}/edit/voiceover")
async def edit_voiceover(lesson_id: str, request: Request,
                         user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request, required=False)
    _only(body, ("mode", "voice", "steps"))
    lesson, _ = _ctx(lesson_id, user, "edit")
    mode = body.get("mode", "duck")
    if mode not in ("duck", "replace"):
        raise HTTPException(400, "mode must be duck or replace")
    voice_name = body.get("voice")
    if voice_name is not None and (not isinstance(voice_name, str) or not VOICE_RE.match(voice_name)):
        raise HTTPException(400, "voice must be a voice name such as af_heart")
    only = None
    if "steps" in body:
        if not isinstance(body["steps"], list) or not body["steps"]:
            raise HTTPException(400, "steps must be a non-empty list of step numbers")
        only = {_index(lesson, n) + 1 for n in body["steps"]}
    lock = _lock()
    _busy(lock)
    await lock.acquire()  # free lock: taken at once, no other request can slip in between
    job = uuid.uuid4().hex[:12]
    with _jobs_lock:
        for old in list(_jobs)[:-MAX_JOBS_KEPT]:
            if _jobs[old]["status"] in ("done", "error"):
                del _jobs[old]
        _jobs[job] = {"job": job, "kind": "voiceover", "lesson_id": lesson_id, "status": "queued", "message": "",
                      "result": None, "created": library.now_iso()}
    task = asyncio.create_task(_voice_job(job, lesson_id, user, lock, mode, voice_name, only))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"job": job, "status": "queued"}


@router.get("/courses/{lesson_id}/jobs/{job}")
def course_job(lesson_id: str, job: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    _ctx(lesson_id, user, "edit")
    with _jobs_lock:
        found = _jobs.get(job)
        if found is None or found["lesson_id"] != lesson_id:
            raise HTTPException(404, "job not found")
        return dict(found)


@router.post("/courses/{lesson_id}/edit/voiceover/undo")
async def edit_voiceover_undo(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    _ctx(lesson_id, user, "edit")
    lock = _lock()
    _busy(lock)
    async with lock:
        from server import voice

        restored = await asyncio.to_thread(voice.undo, library.lesson_dir(lesson_id))
        library.touch_course(lesson_id)
    _after_change(lesson_id, "voiceover_undo", user, restored=restored)
    return {"restored": restored, "lesson": library.read_lesson(lesson_id)}


# ---------------------------------------------------------------- insights, runs and scores

def _org_scope(user: Optional[dict], org: Optional[str]) -> Optional[set]:
    """?org=<id>: only that org's members count. The caller must belong to the org (or own the hub)."""
    if org is None:
        return None
    if library.get_org(org) is None:
        raise HTTPException(404, "organization not found")
    if not (user and (user.get("role") == "owner" or library.org_role(user, org))):
        raise HTTPException(403, "you are not a member of this organization")
    return library.org_member_ids(org)


@router.get("/courses/{lesson_id}/insights")
def course_insights(lesson_id: str, all: bool = False, org: Optional[str] = None,
                    user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    lesson, course = _ctx(lesson_id, user, "insights")
    learners = _org_scope(user, org)
    since = None if all else course.get("steps_changed_at")
    out = library.insights(lesson_id, lesson, since, learners)
    scores = {s["n"]: s for s in scoring.step_averages(lesson_id, lesson, since, learners)}
    for s in out["steps"]:
        avg = scores.get(s["n"]) or {}
        s["score"] = {"value": avg.get("value"), "n": avg.get("n_runs", 0)}
    out["ratings"] = library.rating_summary(lesson_id, learners)
    out["org"] = org
    return out


@router.get("/courses/{lesson_id}/runs")
def course_runs(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    lesson, _ = _ctx(lesson_id, user, "view")
    if user is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    mine = [scoring.summary(scoring.score_run(rid, evs, lesson))
            for rid, evs in library.runs(library.lesson_events(lesson_id)).items()
            if library.run_learner(evs) == user["id"]]
    mine.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return {"runs": mine, "reason": None if mine else "no runs yet"}


@router.get("/runs/{run_id}/score")
def run_score(run_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(400, "bad run id")
    events = scoring.find_run(run_id)
    lesson_id = next((e.get("lesson_id") for e in events or [] if e.get("lesson_id")), None)
    if not events or not lesson_id:
        raise HTTPException(404, "run not found")
    lesson = library.read_lesson(lesson_id)
    course = library.load_course(lesson_id, lesson)
    learner = library.run_learner(events)
    if not (user and learner == user["id"]):
        library.require("insights", user, course)
    out = scoring.score_run(run_id, events, lesson)
    changed = course.get("steps_changed_at")
    out["lesson_changed_after_run"] = bool(changed and out["started_at"] and out["started_at"] < changed)
    return out


# ---------------------------------------------------------------- ratings

@router.get("/courses/{lesson_id}/ratings")
def course_ratings(lesson_id: str, org: Optional[str] = None,
                   user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    _, course = _ctx(lesson_id, user, "view")
    scope = _org_scope(user, org)
    data = {uid: r for uid, r in library.load_ratings(lesson_id).items() if scope is None or uid in scope}
    out = library.rating_summary(lesson_id, scope)
    out["org"] = org
    out["mine"] = data.get(user["id"]) if user else None
    if library.allowed("insights", user, course):
        names = accounts.user_names()
        rows = [{"user_id": uid, "name": names.get(uid, "Deleted user"), "stars": r.get("stars"),
                 "comment": r.get("comment"), "updated": r.get("updated")}
                for uid, r in data.items() if r.get("comment")]
        out["comments"] = sorted(rows, key=lambda r: str(r["updated"] or ""), reverse=True)
    else:
        out["comments"] = None
    return out


@router.post("/courses/{lesson_id}/rating")
async def course_rate(lesson_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("stars", "comment"))
    _, course = _ctx(lesson_id, user, "rate")
    stars = body.get("stars")
    if isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= 5:
        raise HTTPException(400, "stars must be a whole number from 1 to 5")
    comment = body.get("comment")
    if comment is not None:
        comment = _text(comment, "comment", 0, 500) or None
    mine = library.set_rating(lesson_id, user["id"], stars, comment)
    library.audit("course_rating", lesson_id, user, stars=stars)
    return {"rating": mine, "summary": library.rating_summary(lesson_id)}


@router.delete("/courses/{lesson_id}/rating")
def course_unrate(lesson_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    if user is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    _ctx(lesson_id, user, "view")
    if not library.delete_rating(lesson_id, user["id"]):
        raise HTTPException(404, "no rating to delete")
    return {"deleted": True, "summary": library.rating_summary(lesson_id)}


# ---------------------------------------------------------------- organizations

MAX_ORGS_PER_USER = 50
INVITE_DAYS = {"code": 7.0, "user": 30.0}


def _unauthorized() -> HTTPException:
    return HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})


def _find_org(orgs: list[dict], org_id: str) -> dict:
    org = next((o for o in orgs if o["id"] == org_id), None)
    if org is None:
        raise HTTPException(404, "organization not found")
    return org


def _org_gate(user: Optional[dict], org: dict, admin: bool = False) -> Optional[str]:
    """The caller's role in the org. Hub owner passes every check. 401, or 403 for non-members and non-admins."""
    if user is None:
        raise _unauthorized()
    role = next((m["role"] for m in org["members"] if m.get("user_id") == user["id"]), None)
    if user.get("role") == "owner":
        return role
    if role is None:
        raise HTTPException(403, "you are not a member of this organization")
    if admin and role != "org_admin":
        raise HTTPException(403, "only an admin of this organization can do that")
    return role


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "org"


def _admins(org: dict) -> int:
    return sum(1 for m in org["members"] if m.get("role") == "org_admin")


def _invite_live(inv: dict) -> bool:
    if inv.get("revoked") or float(inv.get("expires") or 0) <= library.clock():
        return False
    return inv.get("kind") != "code" or inv.get("max_uses") is None or inv.get("uses", 0) < inv["max_uses"]


def _invite_out(inv: dict, names: dict) -> dict:
    out = {k: inv.get(k) for k in ("id", "kind", "role", "created", "max_uses", "uses")}
    out["expires"] = accounts._iso(float(inv["expires"]))
    out["created_by"] = names.get(inv.get("created_by"), "Deleted user")
    if inv.get("kind") == "user":
        out["user"] = {"id": inv.get("user_id"), "name": names.get(inv.get("user_id"), "Deleted user")}
        out.pop("max_uses"), out.pop("uses")
    return out


def _org_summary(org: dict, role: Optional[str]) -> dict:
    return {"id": org["id"], "name": org["name"], "slug": org["slug"], "created": org.get("created"),
            "members": len(org["members"]), "role": role}


def _org_detail(org: dict, user: dict) -> dict:
    names = accounts.user_names()
    role = next((m["role"] for m in org["members"] if m.get("user_id") == user["id"]), None)
    is_admin = role == "org_admin" or user.get("role") == "owner"
    courses = []
    for lesson_id in library.lesson_ids():
        try:
            lesson = library.read_lesson(lesson_id)
            course = library.load_course(lesson_id, lesson)
        except HTTPException:
            continue
        if course.get("org_id") == org["id"] and library.listable(user, course):
            item = _course_out(lesson_id, lesson, course, names)
            courses.append({k: item[k] for k in ("id", "title", "cover_url", "steps", "status", "visibility",
                                                 "owner", "updated")})
    return {**_org_summary(org, role),
            "owner": {"id": org.get("owner_id"), "name": names.get(org.get("owner_id"), "Deleted user")},
            "members": [{"user_id": m["user_id"], "name": names.get(m["user_id"], "Deleted user"),
                         "role": m["role"], "joined": m.get("joined")} for m in org["members"]],
            "courses": courses,
            "invites": [_invite_out(i, names) for i in org["invites"] if _invite_live(i)] if is_admin else None}


@router.get("/orgs")
def orgs_mine(user: dict = Depends(accounts.require_user)) -> dict:
    """My organizations, and invites addressed to me by name that I have not answered yet."""
    names = accounts.user_names()
    mine = [_org_summary(o, role) for o, role in library.user_orgs(user["id"])]
    invites = [{**_invite_out(i, names), "org": {"id": o["id"], "name": o["name"], "slug": o["slug"]}}
               for o in library.load_orgs() for i in o["invites"]
               if i.get("kind") == "user" and i.get("user_id") == user["id"] and _invite_live(i)]
    return {"orgs": sorted(mine, key=lambda o: o["name"].lower()), "invites": invites}


@router.post("/orgs")
async def org_create(request: Request, user: dict = Depends(accounts.require_user)) -> dict:
    body = await _body(request)
    _only(body, ("name", "slug"))
    name = _text(body.get("name"), "name", 1, 60)
    with library.LOCK:
        orgs = library.read_orgs()
        if sum(1 for o in orgs if o.get("owner_id") == user["id"]) >= MAX_ORGS_PER_USER:
            raise HTTPException(429, "too many organizations")
        taken = {o["slug"] for o in orgs}
        if "slug" in body:
            slug = body["slug"]
            if not isinstance(slug, str) or not library.SLUG_RE.match(slug):
                raise HTTPException(400, "slug must be 1 to 40 lowercase letters, digits and dashes")
            if slug in taken:
                raise HTTPException(409, "that slug is taken")
        else:
            base, slug, i = _slugify(name), _slugify(name), 2
            while slug in taken:
                slug, i = f"{base[:36]}-{i}", i + 1
        t = library.now_iso()
        org = {"id": uuid.uuid4().hex, "name": name, "slug": slug, "owner_id": user["id"], "created": t,
               "members": [{"user_id": user["id"], "role": "org_admin", "joined": t}], "invites": []}
        orgs.append(org)
        library.save_orgs(orgs)
    library.audit("org_create", "-", user, org_id=org["id"])
    return _org_detail(org, user)


@router.get("/orgs/{org_id}")
def org_get(org_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    org = _find_org(library.load_orgs(), org_id)
    _org_gate(user, org)
    return _org_detail(org, user)


@router.patch("/orgs/{org_id}")
async def org_patch(org_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("name", "slug"))
    if not body:
        raise HTTPException(400, "nothing to change")
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        _org_gate(user, org, admin=True)
        if "name" in body:
            org["name"] = _text(body["name"], "name", 1, 60)
        if "slug" in body:
            slug = body["slug"]
            if not isinstance(slug, str) or not library.SLUG_RE.match(slug):
                raise HTTPException(400, "slug must be 1 to 40 lowercase letters, digits and dashes")
            if any(o["slug"] == slug and o["id"] != org_id for o in orgs):
                raise HTTPException(409, "that slug is taken")
            org["slug"] = slug
        library.save_orgs(orgs)
    return _org_detail(org, user)


@router.delete("/orgs/{org_id}")
def org_delete(org_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """Only the org's creator or the hub owner. Its courses go back to only_me with no org, so nothing that
    was shared with the org becomes visible to anyone else."""
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        _org_gate(user, org)
        if user.get("role") != "owner" and org.get("owner_id") != user["id"]:
            raise HTTPException(403, "only the organization's creator or the hub owner can delete it")
        library.save_orgs([o for o in orgs if o["id"] != org_id])
        for lesson_id in library.lesson_ids():
            stored = library.read_json(library.course_path(lesson_id), None, "course.json")
            if isinstance(stored, dict) and stored.get("org_id") == org_id:
                stored["org_id"] = None
                if stored.get("visibility") == "org":
                    stored["visibility"] = "only_me"
                stored["updated"] = library.now_iso()
                library.write_json(library.course_path(lesson_id), stored)
    library.audit("org_delete", "-", user, org_id=org_id)
    return {"deleted": org_id}


@router.post("/orgs/join")
async def org_join(request: Request, user: dict = Depends(accounts.require_user)) -> dict:
    """Join with an invite code, or accept an invite sent to me by name ({"invite_id"})."""
    body = await _body(request)
    _only(body, ("code", "invite_id"))
    if ("code" in body) == ("invite_id" in body):
        raise HTTPException(400, "send either code or invite_id")
    if "code" in body:
        ip = request.client.host if request.client else "unknown"
        if not accounts.join_allowed(user["id"], ip):
            raise HTTPException(429, "too many join attempts; try again in a minute", headers={"Retry-After": "60"})
        code = body["code"]
        digest = hashlib.sha256(code.strip().encode("utf-8")).hexdigest() if isinstance(code, str) else ""
    with library.LOCK:
        orgs = library.read_orgs()
        found = None
        for org in orgs:
            for inv in org["invites"]:
                if not _invite_live(inv):
                    continue
                if "code" in body and inv.get("kind") == "code" and \
                        hmac.compare_digest(str(inv.get("code_hash")), digest):
                    found = (org, inv)
                elif "invite_id" in body and inv.get("kind") == "user" and inv.get("id") == body["invite_id"] \
                        and inv.get("user_id") == user["id"]:
                    found = (org, inv)
        if found is None:
            raise HTTPException(404, "invite code is not valid" if "code" in body else "invite not found")
        org, inv = found
        if any(m.get("user_id") == user["id"] for m in org["members"]):
            raise HTTPException(409, "you are already a member of this organization")
        org["members"].append({"user_id": user["id"], "role": inv["role"], "joined": library.now_iso()})
        if inv["kind"] == "code":
            inv["uses"] = inv.get("uses", 0) + 1
            inv.setdefault("used_by", []).append(user["id"])
        else:
            org["invites"].remove(inv)
        library.save_orgs(orgs)
    library.audit("org_join", "-", user, org_id=org["id"], role=inv["role"])
    return _org_summary(org, inv["role"])


@router.post("/orgs/{org_id}/invites")
async def org_invite(org_id: str, request: Request, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """{"username", "role"} invites one user by name; {"role", "expires_days", "max_uses"} makes a code.
    The code is in this response only; the hub stores just its hash."""
    body = await _body(request)
    _only(body, ("username", "role", "expires_days", "max_uses"))
    role = body.get("role", "learner")
    if role not in library.ORG_ROLES:
        raise HTTPException(400, "role must be org_admin, teacher or learner")
    kind = "user" if "username" in body else "code"
    days = body.get("expires_days", INVITE_DAYS[kind])
    if isinstance(days, bool) or not isinstance(days, (int, float)) or not 0.01 <= days <= 90:
        raise HTTPException(400, "expires_days must be a number from 0.01 to 90")
    inv = {"id": uuid.uuid4().hex[:12], "kind": kind, "role": role, "created": library.now_iso(),
           "created_by": user["id"] if user else None, "expires": library.clock() + float(days) * 86400}
    code = None
    if kind == "user":
        if "max_uses" in body:
            raise HTTPException(400, "max_uses is only for invite codes")
        target = accounts.find_user_by_name(body["username"])
        if target is None:
            raise HTTPException(404, "user not found")
        inv["user_id"] = target["id"]
    else:
        max_uses = body.get("max_uses", 1)
        if max_uses is not None and (isinstance(max_uses, bool) or not isinstance(max_uses, int)
                                     or not 1 <= max_uses <= 1000):
            raise HTTPException(400, "max_uses must be a whole number from 1 to 1000, or null for no limit")
        code = secrets.token_urlsafe(12)
        inv.update(code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(), max_uses=max_uses, uses=0, used_by=[])
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        _org_gate(user, org, admin=True)
        if kind == "user":
            if any(m.get("user_id") == inv["user_id"] for m in org["members"]):
                raise HTTPException(409, "that user is already a member")
            org["invites"] = [i for i in org["invites"] if not (i.get("kind") == "user"
                                                               and i.get("user_id") == inv["user_id"])]
        org["invites"] = [i for i in org["invites"] if _invite_live(i)]  # tidy expired and used-up ones
        org["invites"].append(inv)
        library.save_orgs(orgs)
    out = _invite_out(inv, accounts.user_names())
    if code is not None:
        out["code"] = code
    return out


@router.delete("/orgs/{org_id}/invites/{invite_id}")
def org_invite_delete(org_id: str, invite_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """An admin revokes any invite; the invited user may decline their own."""
    if user is None:
        raise _unauthorized()
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        inv = next((i for i in org["invites"] if i.get("id") == invite_id), None)
        own = inv is not None and inv.get("kind") == "user" and inv.get("user_id") == user["id"]
        if not own:
            _org_gate(user, org, admin=True)
        if inv is None:
            raise HTTPException(404, "invite not found")
        org["invites"].remove(inv)
        library.save_orgs(orgs)
    return {"deleted": invite_id}


@router.post("/orgs/{org_id}/leave")
def org_leave(org_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        role = _org_gate(user, org)
        if role is None:
            raise HTTPException(403, "you are not a member of this organization")
        if role == "org_admin" and _admins(org) == 1:
            raise HTTPException(409, "the organization needs at least one admin")
        org["members"] = [m for m in org["members"] if m.get("user_id") != user["id"]]
        library.save_orgs(orgs)
    return {"left": org_id}


def _member(org: dict, user_id: str) -> dict:
    m = next((m for m in org["members"] if m.get("user_id") == user_id), None)
    if m is None:
        raise HTTPException(404, "member not found")
    return m


@router.patch("/orgs/{org_id}/members/{user_id}")
async def org_member_role(org_id: str, user_id: str, request: Request,
                          user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    body = await _body(request)
    _only(body, ("role",))
    if body.get("role") not in library.ORG_ROLES:
        raise HTTPException(400, "role must be org_admin, teacher or learner")
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        _org_gate(user, org, admin=True)
        m = _member(org, user_id)
        if m["role"] == "org_admin" and body["role"] != "org_admin" and _admins(org) == 1:
            raise HTTPException(409, "the organization needs at least one admin")
        m["role"] = body["role"]
        library.save_orgs(orgs)
    return {"user_id": user_id, "role": m["role"]}


@router.delete("/orgs/{org_id}/members/{user_id}")
def org_member_remove(org_id: str, user_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    with library.LOCK:
        orgs = library.read_orgs()
        org = _find_org(orgs, org_id)
        _org_gate(user, org, admin=True)
        m = _member(org, user_id)
        if m["role"] == "org_admin" and _admins(org) == 1:
            raise HTTPException(409, "the organization needs at least one admin")
        org["members"].remove(m)
        library.save_orgs(orgs)
    return {"removed": user_id}


# ---------------------------------------------------------------- public profile

@router.get("/users/{user_id}/public")
def user_public(user_id: str, user: Optional[dict] = Depends(accounts.current_user)) -> dict:
    """Name, the courses they own that the caller may see, and the orgs the caller shares with them.
    No role, passcode, dates or private memberships."""
    target = accounts.get_user(user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    names = accounts.user_names()
    courses = []
    for lesson_id in library.lesson_ids():
        try:
            lesson = library.read_lesson(lesson_id)
            course = library.load_course(lesson_id, lesson)
        except HTTPException:
            continue
        if course.get("owner_id") == user_id and course["status"] != "draft" and library.listable(user, course):
            item = _course_out(lesson_id, lesson, course, names)
            courses.append({k: item[k] for k in ("id", "title", "cover_url", "steps", "duration", "updated")})
    mine = {o["id"] for o, _ in library.user_orgs(user["id"])} if user else set()
    hub_owner = bool(user and user.get("role") == "owner")
    orgs = [{"id": o["id"], "name": o["name"], "slug": o["slug"]} for o, _ in library.user_orgs(user_id)
            if hub_owner or o["id"] in mine]
    return {"id": target["id"], "name": target["name"], "courses": courses, "orgs": orgs}

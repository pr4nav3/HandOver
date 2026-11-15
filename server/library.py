"""Course library: course metadata, edit history, ratings, permissions and learn-event stats. Stdlib only.

Everything lives in plain files, written atomically (temp file, then rename) under one lock:

    <lessons>/<id>/course.json          course metadata (owner, title, status, sharing, version); never inside lesson.json
    <lessons>/<id>/covers/              cover images (a chosen frame is copied here so a recut cannot change it)
    <data>/users.json, tokens.json      accounts (server/accounts.py)
    <data>/pending/<id>.json            owner and title of a course whose teach job is still running
    <data>/history/<id>/stack.json      the last HANDOVER_HISTORY_DEPTH lesson.json snapshots for undo and redo
    <data>/ratings/<id>.json            one star rating per learner
    <data>/audit.jsonl                  one line per course change (who, what, when)

<data> is HANDOVER_DATA (default <repo>/data). A lesson folder without course.json, or a course.json whose
owner_id is null, is "legacy": owned by nobody, readable per its status and visibility (everyone, by default),
and editable by the hub owner, or by anyone while HANDOVER_AUTH=optional (no sign-in needed).

Learn events are read from the local mirror server/databricks.py writes (HANDOVER_EVENTS_JSONL, default
<repo>/logs/events.jsonl). Only real events count; nothing here invents a number.
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import HTTPException

from server import config

log = logging.getLogger("handover.library")

REPO = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
USER_ID_RE = re.compile(r"^[a-f0-9]{8,64}$")

STATUSES = ("draft", "published", "unlisted")
VISIBILITIES = ("only_me", "shared", "org", "everyone")
ACCESS_ROLES = ("editor", "learner")
COVER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
MAX_ACCESS = 200
DEFAULT_QUESTION = "Is this step finished?"  # same as teach.DEFAULT_QUESTION (CONTRACT.md section 3)
INTERNAL_LESSON_IDS = frozenset({"demo-v1", "fortune-teller-v1", "synthetic-fortune-teller-v1"})

# ---------------------------------------------------------------- settings

# Defaults used until these names are in config.REGISTRY; once registered there, config.get wins.
_SETTINGS: dict[str, tuple[str, Any, tuple]] = {
    "HANDOVER_DATA": ("str", None, ()),
    "HANDOVER_AUTH": ("choice", "optional", ("optional", "required")),
    "HANDOVER_TOKEN_DAYS": ("float", 30.0, (0.0001, 365.0)),
    "HANDOVER_LOGIN_PER_MINUTE": ("int", 5, (1, 100)),
    "HANDOVER_HISTORY_DEPTH": ("int", 20, (1, 100)),
    "HANDOVER_EVENTS_JSONL": ("str", None, ()),
}


def setting(name: str) -> Any:
    try:
        return config.get(name)
    except KeyError:
        kind, default, extra = _SETTINGS[name]
        if kind == "float":
            return config.env_float(name, default, *extra)
        if kind == "int":
            return config.env_int(name, default, *extra)
        if kind == "choice":
            return config.env_choice(name, default, extra)
        return config.env_str(name, default)


def auth_mode() -> str:
    """HANDOVER_AUTH: "optional" (default; anonymous callers keep the open flow, no sign-in) or "required"."""
    return str(setting("HANDOVER_AUTH"))


def data_dir() -> Path:
    raw = setting("HANDOVER_DATA")
    return Path(str(raw)).expanduser().resolve() if raw else REPO / "data"


def lessons_root() -> Path:
    try:
        raw = config.get("HANDOVER_LESSONS")
    except KeyError:
        raw = os.environ.get("HANDOVER_LESSONS")
    return Path(str(raw) if raw else REPO / "lessons").resolve()


def events_path() -> Path:
    raw = setting("HANDOVER_EVENTS_JSONL")
    return Path(str(raw)).expanduser() if raw else REPO / "logs" / "events.jsonl"


# ---------------------------------------------------------------- files

LOCK = threading.RLock()
"""One lock for every file this module and accounts.py write. Writes are small and fast."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_json(path: Path, data: Any, private: bool = False) -> None:
    """Atomic: a unique temp file in the same folder, fsync, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        if private:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path, default: Any, what: str) -> Any:
    """The parsed file, `default` when it does not exist, 500 when it exists but cannot be read (never treated
    as empty: an unreadable users file must not reopen first-run setup)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as e:
        log.error("%s unreadable: %s", what, type(e).__name__)
        raise HTTPException(500, f"{what} unreadable")


def append_jsonl(path: Path, row: dict) -> None:
    try:
        with LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError as e:
        log.warning("could not append to %s: %s", path.name, e)


# ---------------------------------------------------------------- lessons

def lesson_dir(lesson_id: str) -> Path:
    if not isinstance(lesson_id, str) or not ID_RE.match(lesson_id):
        raise HTTPException(400, "bad lesson id")
    return lessons_root() / lesson_id


def read_lesson(lesson_id: str) -> dict:
    """lesson.json with the same errors as main.read_lesson."""
    path = lesson_dir(lesson_id) / "lesson.json"
    if not path.is_file():
        raise HTTPException(404, "lesson not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"lesson.json unreadable: {type(e).__name__}")
    if not isinstance(data, dict):
        raise HTTPException(500, "lesson.json unreadable: not an object")
    return data


def lesson_ids() -> list[str]:
    root = lessons_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and ID_RE.match(d.name) and (d / "lesson.json").is_file()
                  and is_user_facing_lesson(d.name, root))


def is_user_facing_lesson(lesson_id: str, root: Optional[Path] = None) -> bool:
    """Hide repository fixtures without changing lesson IDs in test-specific roots."""
    active_root = (root or lessons_root()).resolve()
    return active_root != (REPO / "lessons").resolve() or lesson_id not in INTERNAL_LESSON_IDS


def parse_time(value: Any) -> float:
    """Seconds from a number, "MM:SS", "MM:SS.s" or "HH:MM:SS" (teach.parse_time). ValueError when unreadable."""
    if isinstance(value, bool):
        raise ValueError(f"bad timestamp: {value!r}")
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"bad timestamp: {value!r}")
        return float(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"bad timestamp: {value!r}")
    total = 0.0
    try:
        for part in value.strip().split(":"):
            total = total * 60 + float(part)
    except ValueError:
        raise ValueError(f"bad timestamp: {value!r}") from None
    if total != total or total in (float("inf"), float("-inf")):
        raise ValueError(f"bad timestamp: {value!r}")
    return total


def fmt_time(seconds: float) -> str:
    """ "MM:SS" or "MM:SS.s", like teach.fmt_mmss."""
    tenths = max(0, int(round(seconds * 10)))
    m, rem = divmod(tenths, 600)
    s, t = divmod(rem, 10)
    return f"{m:02d}:{s:02d}" + (f".{t}" if t else "")


def fmt_vtt(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def step_seconds(step: dict) -> Optional[float]:
    try:
        return max(0.0, parse_time(step.get("end")) - parse_time(step.get("start")))
    except (ValueError, AttributeError):
        return None


def lesson_duration(lesson: dict) -> Optional[float]:
    steps = lesson.get("steps") or []
    try:
        return round(parse_time(steps[-1]["end"]) - parse_time(steps[0]["start"]), 1) if steps else 0.0
    except (ValueError, KeyError, TypeError, IndexError):
        return None


def timing_key(lesson: dict) -> list:
    """What a recut depends on: step count, boundaries and chosen reference times."""
    return [(s.get("start"), s.get("end"), s.get("ref_time")) for s in lesson.get("steps") or []
            if isinstance(s, dict)]


def safe_rel(lesson_id: str, rel: Any) -> Optional[Path]:
    """A path inside the lesson folder from a relative string, or None when it escapes or is malformed."""
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or "\\" in rel or len(rel) > 200:
        return None
    if any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    base = lesson_dir(lesson_id).resolve()
    path = (base / rel).resolve()
    return path if base in path.parents else None


# ---------------------------------------------------------------- courses

def course_path(lesson_id: str) -> Path:
    return lesson_dir(lesson_id) / "course.json"


def pending_path(lesson_id: str) -> Path:
    return data_dir() / "pending" / f"{lesson_id}.json"


JOB_STATUS = None
"""Optional callable(job_id) -> job dict or None (the hub's in-memory teach jobs); set by routes_library.configure."""


def _finalize_pending(lesson_id: str) -> None:
    """A course created by POST /api/courses gets its course.json once its teach job has written lesson.json.
    A pending entry whose job failed is dropped, so a later upload with the same id is not claimed."""
    p = pending_path(lesson_id)
    if not p.is_file():
        return
    with LOCK:
        pending = read_json(p, None, "pending course")
        if not isinstance(pending, dict):
            p.unlink(missing_ok=True)
            return
        job = JOB_STATUS(pending.get("job")) if JOB_STATUS and pending.get("job") else None
        if job and job.get("status") == "error":
            p.unlink(missing_ok=True)
            return
        if not (lesson_dir(lesson_id) / "lesson.json").is_file():
            return
        if not course_path(lesson_id).is_file():
            course = pending.get("course") or {}
            course["updated"] = now_iso()
            write_json(course_path(lesson_id), course)
        p.unlink(missing_ok=True)


def add_pending(lesson_id: str, job: str, course: dict) -> None:
    with LOCK:
        write_json(pending_path(lesson_id), {"job": job, "created": now_iso(), "course": course})
    _finalize_pending(lesson_id)


def new_course(owner_id: Optional[str], title: str, description: str = "") -> dict:
    t = now_iso()
    return {"owner_id": owner_id, "title": title, "description": description, "cover": None,
            "status": "draft", "visibility": "only_me", "access": [], "created": t, "updated": t,
            "published_at": None, "version": 0, "steps_changed_at": None, "org_id": None}


def _mtime_iso(path: Path) -> Optional[str]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="milliseconds") \
            .replace("+00:00", "Z")
    except OSError:
        return None


def load_course(lesson_id: str, lesson: Optional[dict] = None) -> dict:
    """The stored course, or the legacy defaults when course.json does not exist. Always has every field plus
    "id" and "legacy" (no owner)."""
    _finalize_pending(lesson_id)
    stored = read_json(course_path(lesson_id), None, "course.json")
    if lesson is None:
        lesson = read_lesson(lesson_id)
    updated = _mtime_iso(lesson_dir(lesson_id) / "lesson.json")
    base = {"owner_id": None, "title": str(lesson.get("title") or lesson_id), "description": "", "cover": None,
            "status": "published", "visibility": "everyone", "access": [], "created": None, "updated": updated,
            "published_at": None, "version": 0, "steps_changed_at": None, "org_id": None}
    if isinstance(stored, dict):
        base.update({k: v for k, v in stored.items() if k in base})
        if base["status"] not in STATUSES:
            base["status"] = "draft"
        if base["visibility"] not in VISIBILITIES:
            base["visibility"] = "only_me"
        if not isinstance(base["access"], list):
            base["access"] = []
    base["id"] = lesson_id
    base["legacy"] = base["owner_id"] is None
    base["stored"] = isinstance(stored, dict)
    return base


def save_course(lesson_id: str, course: dict) -> dict:
    out = {k: v for k, v in course.items() if k not in ("id", "legacy", "stored")}
    out["updated"] = now_iso()
    with LOCK:
        write_json(course_path(lesson_id), out)
    course.update(out, stored=True, legacy=out.get("owner_id") is None)
    return course


def touch_course(lesson_id: str, steps_changed: bool = False) -> None:
    """After a lesson edit: bump updated (and steps_changed_at, so insights skip events for the old steps).
    A legacy lesson without course.json stays without one."""
    with LOCK:
        stored = read_json(course_path(lesson_id), None, "course.json")
        if not isinstance(stored, dict):
            return
        stored["updated"] = now_iso()
        if steps_changed:
            stored["steps_changed_at"] = stored["updated"]
        write_json(course_path(lesson_id), stored)


def cover_url(lesson_id: str, course: dict) -> Optional[str]:
    """/lessons/<id>/<cover> when the cover file exists, else the first reference frame, else None."""
    for rel in (course.get("cover"), "frames/01.jpg"):
        path = safe_rel(lesson_id, rel) if rel else None
        if path is not None and path.is_file():
            return f"/lessons/{lesson_id}/{rel}"
    return None


def access_role(user: Optional[dict], course: dict) -> Optional[str]:
    if not user:
        return None
    for entry in course.get("access") or []:
        if isinstance(entry, dict) and entry.get("user_id") == user["id"]:
            return entry.get("role") if entry.get("role") in ACCESS_ROLES else None
    return None


# ---------------------------------------------------------------- organizations

ORG_ROLES = ("org_admin", "teacher", "learner")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_orgs_cache: dict = {"key": None, "orgs": []}


def clock() -> float:
    """Wall clock for invite expiry; tests replace it."""
    return time.time()


def orgs_path() -> Path:
    return data_dir() / "orgs.json"


def read_orgs() -> list[dict]:
    """orgs.json, uncached; call under LOCK when you are going to change and save it."""
    data = read_json(orgs_path(), {"orgs": []}, "orgs.json")
    orgs = data.get("orgs") if isinstance(data, dict) else None
    if not isinstance(orgs, list):
        raise HTTPException(500, "orgs.json unreadable")
    for org in orgs:
        org.setdefault("members", [])
        org.setdefault("invites", [])
    return [o for o in orgs if isinstance(o, dict) and o.get("id")]


def save_orgs(orgs: list[dict]) -> None:
    with LOCK:
        write_json(orgs_path(), {"orgs": orgs}, private=True)
        _orgs_cache["key"] = None


def load_orgs() -> list[dict]:
    """Read-only view, parsed once per file change (permission checks ask for it once per course)."""
    path = orgs_path()
    try:
        st = path.stat()
    except OSError:
        return []
    key = (str(path), st.st_size, st.st_mtime_ns)
    with LOCK:
        if _orgs_cache["key"] != key:
            _orgs_cache.update(key=key, orgs=read_orgs())
        return _orgs_cache["orgs"]


def get_org(org_id: Any) -> Optional[dict]:
    return next((o for o in load_orgs() if o["id"] == org_id), None) if isinstance(org_id, str) else None


def org_role(user: Optional[dict], org_id: Any) -> Optional[str]:
    """The user's role in this org (org_admin, teacher, learner), or None."""
    org = get_org(org_id) if user else None
    if org is None:
        return None
    return next((m["role"] for m in org["members"] if m.get("user_id") == user["id"]), None)


def user_orgs(user_id: str) -> list[tuple[dict, str]]:
    return [(o, m["role"]) for o in load_orgs() for m in o["members"] if m.get("user_id") == user_id]


def org_member_ids(org_id: str) -> set[str]:
    org = get_org(org_id)
    return {m["user_id"] for m in org["members"]} if org else set()


def remove_user_everywhere(user_id: str) -> None:
    """A deleted user leaves every org and loses pending invites addressed to them."""
    with LOCK:
        orgs = read_orgs()
        changed = False
        for org in orgs:
            kept = [m for m in org["members"] if m.get("user_id") != user_id]
            invites = [i for i in org["invites"] if i.get("user_id") != user_id]
            if len(kept) != len(org["members"]) or len(invites) != len(org["invites"]):
                org["members"], org["invites"], changed = kept, invites, True
        if changed:
            save_orgs(orgs)


# ---------------------------------------------------------------- permissions (the one place)

ACTIONS = ("view", "edit", "publish", "moderate", "manage", "transfer", "insights", "rate")
DENIED = {
    "view": "you do not have access to this course",
    "edit": "only the course owner or an editor can edit this course",
    "edit_legacy": "only the hub owner can edit a lesson that has no course owner",
    "publish": "only the course owner can publish this course",
    "moderate": "only the course owner or an admin of its organization can unpublish this course",
    "manage": "only the course owner can change who can see this course",
    "transfer": "only the hub owner can change a course's owner",
    "insights": "only the course owner, an editor or an admin of its organization can see insights",
    "rate": "people who own or edit a course cannot rate it",
    "create": "learners cannot create courses; ask the hub owner for the teacher role",
    "create_org": "only teachers and admins of this organization can create courses in it",
}


def relation(user: Optional[dict], course: dict) -> str:
    """hub_owner > course_owner > editor > learner (access list) > signed_in > anonymous."""
    if not user:
        return "anonymous"
    if user.get("role") == "owner":
        return "hub_owner"
    if course.get("owner_id") and course.get("owner_id") == user["id"]:
        return "course_owner"
    return access_role(user, course) or "signed_in"


def allowed(action: str, user: Optional[dict], course: dict) -> bool:
    rel = relation(user, course)
    legacy = course.get("owner_id") is None
    in_org = org_role(user, course.get("org_id")) if course.get("org_id") else None
    if rel == "hub_owner":
        if action == "rate":  # the hub owner may rate courses they neither own nor edit
            return course.get("owner_id") != user["id"] and access_role(user, course) != "editor"
        return True
    if action == "view":
        if rel in ("course_owner", "editor") or in_org == "org_admin":
            return True
        if course["status"] == "draft":
            return False
        if course["visibility"] == "everyone":
            return True
        if course["visibility"] == "shared":
            return rel == "learner"
        return course["visibility"] == "org" and in_org is not None
    if action in ("edit", "insights"):
        if legacy:
            return auth_mode() == "optional"
        return rel in ("course_owner", "editor") or (action == "insights" and in_org == "org_admin")
    if action in ("publish", "manage"):
        return rel == "course_owner"
    if action == "moderate":
        return rel == "course_owner" or in_org == "org_admin"
    if action == "rate":
        return user is not None and rel not in ("course_owner", "editor") and allowed("view", user, course)
    if action == "transfer":
        return False
    raise ValueError(f"unknown action {action}")


def require(action: str, user: Optional[dict], course: dict) -> None:
    """Raise 401 for an anonymous caller who would need to sign in, else 403 with the action's message."""
    if allowed(action, user, course):
        return
    if user is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    if action == "edit" and course.get("owner_id") is None:
        raise HTTPException(403, DENIED["edit_legacy"])
    if action == "view" or not allowed("view", user, course):
        raise HTTPException(403, DENIED["view"])
    raise HTTPException(403, DENIED[action])


def require_create(user: Optional[dict], org_id: Optional[str] = None) -> None:
    """Hub owner and teachers create courses; in an org, its teachers and admins do (whatever their hub role).
    Anonymous callers only while HANDOVER_AUTH=optional, and never into an org."""
    if user is None:
        if auth_mode() == "optional" and not org_id:
            return
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    if org_id:
        if get_org(org_id) is None:
            raise HTTPException(404, "organization not found")
        if user.get("role") != "owner" and org_role(user, org_id) not in ("org_admin", "teacher"):
            raise HTTPException(403, DENIED["create_org"])
        return
    if user.get("role") not in ("owner", "teacher"):
        raise HTTPException(403, DENIED["create"])


def listable(user: Optional[dict], course: dict) -> bool:
    """Visible in GET /api/courses: viewable, and unlisted courses only for the people they are shared with."""
    if not allowed("view", user, course):
        return False
    if course["status"] != "unlisted":
        return True
    return (relation(user, course) in ("hub_owner", "course_owner", "editor", "learner")
            or org_role(user, course.get("org_id")) == "org_admin")


def permissions(user: Optional[dict], course: dict) -> dict:
    return {"can_view": allowed("view", user, course), "can_edit": allowed("edit", user, course),
            "can_publish": allowed("publish", user, course), "can_unpublish": allowed("moderate", user, course),
            "can_manage": allowed("manage", user, course), "can_transfer": allowed("transfer", user, course),
            "can_see_insights": allowed("insights", user, course), "can_rate": allowed("rate", user, course)}


# ---------------------------------------------------------------- edit history (undo and redo)

def history_path(lesson_id: str) -> Path:
    return data_dir() / "history" / lesson_id / "stack.json"


def _stack(lesson_id: str) -> dict:
    data = read_json(history_path(lesson_id), None, "edit history")
    if not isinstance(data, dict):
        data = {}
    return {"undo": list(data.get("undo") or []), "redo": list(data.get("redo") or [])}


def history_counts(lesson_id: str) -> dict:
    s = _stack(lesson_id)
    return {"undo": len(s["undo"]), "redo": len(s["redo"])}


def snapshot(lesson_id: str, files: Iterable[str] = ()) -> dict:
    """The current lesson.json text plus the named lesson files (relative paths) for an undo entry."""
    d = lesson_dir(lesson_id)
    out = {"lesson": (d / "lesson.json").read_text(encoding="utf-8"), "files": {}}
    for rel in files:
        p = safe_rel(lesson_id, rel)
        out["files"][rel] = p.read_text(encoding="utf-8") if p is not None and p.is_file() else None
    return out


def push_history(lesson_id: str, entry: dict) -> None:
    """A new edit: its before-state goes on the undo stack (capped) and the redo stack is cleared."""
    depth = int(setting("HANDOVER_HISTORY_DEPTH"))
    with LOCK:
        s = _stack(lesson_id)
        s["undo"] = (s["undo"] + [entry])[-depth:]
        s["redo"] = []
        write_json(history_path(lesson_id), s)


def drop_last_history(lesson_id: str) -> None:
    """Take back the entry push_history just added (the edit failed after all)."""
    with LOCK:
        s = _stack(lesson_id)
        if s["undo"]:
            s["undo"].pop()
            write_json(history_path(lesson_id), s)


def peek_history(lesson_id: str, direction: str) -> Optional[dict]:
    """The entry the next undo (or redo) would restore, without changing the stacks."""
    s = _stack(lesson_id)[direction]
    return s[-1] if s else None


def swap_history(lesson_id: str, direction: str, current: dict) -> Optional[dict]:
    """Undo (direction "undo") or redo: pops the target entry and pushes `current` on the other stack.
    Returns the target, or None when there is nothing to undo or redo."""
    other = "redo" if direction == "undo" else "undo"
    depth = int(setting("HANDOVER_HISTORY_DEPTH"))
    with LOCK:
        s = _stack(lesson_id)
        if not s[direction]:
            return None
        target = s[direction].pop()
        s[other] = (s[other] + [current])[-depth:]
        write_json(history_path(lesson_id), s)
    return target


def unswap_history(lesson_id: str, direction: str, target: dict) -> None:
    """Put the stacks back after a failed undo or redo."""
    other = "redo" if direction == "undo" else "undo"
    with LOCK:
        s = _stack(lesson_id)
        if s[other]:
            s[other].pop()
        s[direction].append(target)
        write_json(history_path(lesson_id), s)


def audit(kind: str, lesson_id: str, user: Optional[dict], **fields: Any) -> dict:
    row = {"ts": now_iso(), "kind": kind, "lesson_id": lesson_id, "user_id": user["id"] if user else None,
           **fields}
    append_jsonl(data_dir() / "audit.jsonl", row)
    return row


# ---------------------------------------------------------------- ratings

def ratings_path(lesson_id: str) -> Path:
    return data_dir() / "ratings" / f"{lesson_id}.json"


def load_ratings(lesson_id: str) -> dict:
    data = read_json(ratings_path(lesson_id), {}, "ratings")
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def set_rating(lesson_id: str, user_id: str, stars: int, comment: Optional[str]) -> dict:
    with LOCK:
        data = load_ratings(lesson_id)
        t = now_iso()
        old = data.get(user_id) or {}
        data[user_id] = {"stars": stars, "comment": comment, "created": old.get("created") or t, "updated": t}
        write_json(ratings_path(lesson_id), data)
        return data[user_id]


def delete_rating(lesson_id: str, user_id: str) -> bool:
    with LOCK:
        data = load_ratings(lesson_id)
        if user_id not in data:
            return False
        del data[user_id]
        write_json(ratings_path(lesson_id), data)
        return True


def rating_summary(lesson_id: str, users: Optional[set] = None) -> dict:
    """Average, count and distribution; `users` limits it to those raters (an org's members)."""
    stars = [int(r["stars"]) for uid, r in load_ratings(lesson_id).items()
             if r.get("stars") in (1, 2, 3, 4, 5) and (users is None or uid in users)]
    return {"average": round(sum(stars) / len(stars), 2) if stars else None, "count": len(stars),
            "distribution": {str(k): stars.count(k) for k in range(1, 6)}}


# ---------------------------------------------------------------- learn events

_events_cache: dict = {"key": None, "rows": []}


def _flatten(raw: dict) -> Optional[dict]:
    """One JSONL line (databricks.py mirror format, or a hub event) as a flat dict with from_step/to_step."""
    if not isinstance(raw, dict) or not raw.get("kind"):
        return None
    row = dict(raw)
    extra = row.pop("extra", None)
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError:
            extra = None
    if isinstance(extra, dict):
        for k, v in extra.items():
            if row.get(k) is None:
                row[k] = v
    if row.get("from_step") is None and "from" in row:
        row["from_step"] = row.get("from")
    if row.get("to_step") is None and "to" in row:
        row["to_step"] = row.get("to")
    if not row.get("run_id"):
        row["run_id"] = row.get("hub_run_id")
    return row


def load_events() -> list[dict]:
    """Every retained event in the current and rotated local mirrors, parsed once per file change.

    The uploader keeps one ``.1`` file when the 50 MB mirror rotates. Reading it first preserves profile history
    across that rotation. Unreadable files/lines are skipped; analytics endpoints never fail the app over a
    damaged optional mirror.
    """
    path = events_path()
    paths = (path.with_name(path.name + ".1"), path)
    found = []
    for source in paths:
        try:
            st = source.stat()
        except OSError:
            continue
        found.append((source, st))
    if not found:
        return []
    key = tuple((str(source), st.st_size, st.st_mtime_ns) for source, st in found)
    with LOCK:
        if _events_cache["key"] == key:
            return _events_cache["rows"]
    rows = []
    for source, _ in found:
        try:
            with source.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        row = _flatten(json.loads(line))
                    except ValueError:
                        continue
                    if row is not None:
                        rows.append(row)
        except OSError:
            continue
    with LOCK:
        _events_cache.update(key=key, rows=rows)
    return rows


def lesson_events(lesson_id: str, since: Optional[str] = None, learners: Optional[set] = None) -> list[dict]:
    """Events of one lesson, optionally from `since` on and only from runs whose learner is in `learners`."""
    rows = [r for r in load_events() if r.get("lesson_id") == lesson_id and (not since or str(r.get("ts") or "") >= since)]
    if learners is None:
        return rows
    keep = {rid for rid, evs in runs(rows).items() if run_learner(evs) in learners}
    return [r for r in rows if r.get("run_id") and str(r["run_id"]) in keep]


def runs(events: list[dict]) -> dict[str, list[dict]]:
    """Events grouped by run id, in file order. Events without a run id are not part of any run."""
    out: dict[str, list[dict]] = {}
    for r in events:
        if r.get("run_id"):
            out.setdefault(str(r["run_id"]), []).append(r)
    return out


def run_learner(events: list[dict]) -> Optional[str]:
    """Who did the run: run_start's learner (databricks.start_run(lesson_id, learner)) or user_id field."""
    for r in events:
        for key in ("learner", "user_id"):
            if r.get(key):
                return str(r[key])
    return None


def as_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def as_float(v: Any) -> Optional[float]:
    try:
        f = float(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None
    return f if f is not None and f == f else None


def progress(lesson_id: str, user: Optional[dict], total: int) -> dict:
    """The caller's own progress from real run events. known is false when there is no run tagged with them."""
    if not user:
        return {"known": False, "reason": "sign in to track progress", "runs": 0, "total": total}
    mine = {rid: evs for rid, evs in runs(lesson_events(lesson_id)).items() if run_learner(evs) == user["id"]}
    if not mine:
        return {"known": False, "reason": "no runs yet", "runs": 0, "total": total}
    summaries = []
    for evs in mine.values():
        reached = [as_int(r.get("to_step")) for r in evs if r.get("kind") == "advance"]
        steps_done = min(max([x for x in reached if x is not None] or [0]), total)
        finished = any(r.get("kind") == "run_done" for r in evs) or (total > 0 and steps_done >= total)
        summaries.append({"steps_done": steps_done, "finished": finished, "last_at": max(str(r.get("ts") or "") for r in evs)})
    summaries.sort(key=lambda s: s["last_at"])
    last = summaries[-1]
    return {"known": True, "runs": len(summaries), "completed": sum(s["finished"] for s in summaries),
            "best_steps_done": max(s["steps_done"] for s in summaries), "last_steps_done": last["steps_done"],
            "last_finished": last["finished"], "last_at": last["last_at"], "total": total}


def _event_time(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def learner_analytics(user_id: str) -> dict:
    """Private, aggregate-only learning stats for one signed-in person.

    The answer contains no event text, frame data, device identifiers, or course/learner identifiers. Mock runs
    are excluded explicitly. Rates carry their denominators so clients never imply accuracy from no data.
    """
    mine = []
    for evs in runs(load_events()).values():
        if run_learner(evs) != user_id:
            continue
        start = next((e for e in evs if e.get("kind") == "run_start"), {})
        if str(start.get("check_mode") or "").lower() == "mock":
            continue
        mine.append(evs)
    if not mine:
        return {"known": False, "reason": "no runs yet", "runs": 0}

    completed = [evs for evs in mine if any(e.get("kind") == "run_done" for e in evs)]
    stopped = [evs for evs in mine if any(e.get("kind") == "run_stop" for e in evs)]
    checks = [e for evs in mine for e in evs if e.get("kind") == "check" and not e.get("stale")]
    useful_checks = [e for e in checks if not e.get("error_kind") and e.get("done") in ("yes", "no", "unsure")]
    forward = [e for evs in mine for e in evs if e.get("kind") == "advance"
               and (as_int(e.get("to_step")) or 0) > (as_int(e.get("from_step")) or 0)]
    camera = [e for e in forward if e.get("reason") not in ("button", "voice")]
    manual = [e for e in forward if e.get("reason") in ("button", "voice")]
    mistakes = [e for evs in mine for e in evs if e.get("kind") == "mistake"]
    durations = []
    for evs in mine:
        outcome = next((e for e in reversed(evs) if e.get("kind") in ("run_done", "run_stop")), {})
        value = as_float(outcome.get("total_seconds") if outcome.get("kind") == "run_done"
                         else outcome.get("elapsed_seconds"))
        if value is not None and value >= 0:
            durations.append(value)
    completed_lessons = {str(e.get("lesson_id")) for evs in completed for e in evs if e.get("lesson_id")}
    completed_days = {t.date() for evs in completed for t in [_event_time(max(
        (str(e.get("ts") or "") for e in evs), default=""))] if t is not None}
    today = datetime.now(timezone.utc).date()
    cursor = today if today in completed_days else today - timedelta(days=1)
    streak = 0
    while cursor in completed_days:
        streak += 1
        cursor -= timedelta(days=1)
    latencies = [v for v in (as_float(e.get("latency_ms")) for e in useful_checks) if v is not None and v >= 0]
    readiness = [v for v in (as_float(e.get("connect_latency_ms")) for evs in mine for e in evs
                              if e.get("kind") == "camera_first_frame") if v is not None and v >= 0]
    sources = sorted({str(e.get("source") or e.get("camera_source")) for evs in mine for e in evs
                      if (e.get("source") or e.get("camera_source")) not in (None, "", "unknown")})
    pass_n = sum(1 for e in useful_checks if e.get("done") == "yes")
    return {
        "known": True, "reason": None, "runs": len(mine), "completed_runs": len(completed),
        "completion_rate": _rate(len(completed), len(mine)), "courses_completed": len(completed_lessons),
        "minutes_practiced": round(sum(durations) / 60, 1), "active_days": len(completed_days),
        "current_streak_days": streak, "checks": len(useful_checks),
        "check_pass_rate": _rate(pass_n, len(useful_checks)),
        "check_errors": sum(1 for e in checks if e.get("error_kind")),
        "avg_check_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "camera_verified_steps": len(camera), "manual_steps": len(manual), "mistakes_caught": len(mistakes),
        "replays": sum(1 for evs in mine for e in evs
                       if e.get("kind") == "run_start" and e.get("attempt_kind") == "replay"),
        "interruptions": len(stopped), "camera_sources": sources,
        "median_camera_ready_ms": round(statistics.median(readiness)) if readiness else None,
    }


def _median(values: list[float]) -> Optional[float]:
    return round(statistics.median(values), 2) if values else None


def _rate(hits: int, n: int) -> Optional[float]:
    return round(hits / n, 3) if n else None


def insights(lesson_id: str, lesson: dict, since: Optional[str] = None, learners: Optional[set] = None) -> dict:
    """Per-step stats from real events, each with its sample count n. A metric with n = 0 is null.
    Events before `since` (the last change to the step layout) are left out, because their step numbers
    point at steps that no longer exist."""
    steps = [s for s in lesson.get("steps") or [] if isinstance(s, dict)]
    events = lesson_events(lesson_id, since, learners)
    by_run = runs(events)
    out_steps = []
    for i, st in enumerate(steps):
        forward = [r for r in events if r.get("kind") == "advance" and as_int(r.get("from_step")) == i
                   and (as_int(r.get("to_step")) or 0) > i]
        times = [t for t in (as_float(r.get("step_seconds")) for r in forward) if t is not None]
        manual = sum(1 for r in forward if r.get("reason") in ("button", "voice"))
        visits = sum(1 for r in events if r.get("kind") == "step_enter" and as_int(r.get("step")) == i)
        mistakes = sum(1 for r in events if r.get("kind") == "mistake" and as_int(r.get("step")) == i)
        checks = [r for r in events if r.get("kind") == "check" and as_int(r.get("step")) == i]
        failed = sum(1 for r in checks if r.get("error_kind"))
        backs = sum(1 for r in events if r.get("kind") == "advance" and as_int(r.get("from_step")) == i
                    and (as_int(r.get("to_step")) if as_int(r.get("to_step")) is not None else i) < i)
        out_steps.append({
            "n": st.get("n", i + 1), "title": st.get("title") or "",
            "expert_seconds": step_seconds(st),
            "median_seconds": {"value": _median(times), "n": len(times)},
            "manual_rate": {"value": _rate(manual, len(forward)), "n": len(forward)},
            "mistakes_caught": {"value": mistakes if visits else None, "n": visits},
            "check_failure_rate": {"value": _rate(failed, len(checks)), "n": len(checks)},
            "back_presses": {"value": backs if visits else None, "n": visits},
        })
    started = sum(1 for r in events if r.get("kind") == "run_start")
    finished = sum(1 for r in events if r.get("kind") == "run_done")
    has_data = any(s["median_seconds"]["n"] or s["manual_rate"]["n"] or s["check_failure_rate"]["n"]
                   or s["mistakes_caught"]["n"] for s in out_steps)
    return {"enough_data": has_data, "reason": None if has_data else "not enough data",
            "since": since, "runs": {"started": started, "finished": finished, "n": len(by_run)},
            "steps": out_steps if has_data else []}

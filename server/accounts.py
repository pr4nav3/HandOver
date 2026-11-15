"""Hub accounts: users, scrypt passcodes, bearer tokens and login rate limits. Stdlib only.

Users live in <data>/users.json, tokens in <data>/tokens.json (only a SHA-256 of each token is stored), both
written atomically under library.LOCK with mode 600. No seed users: the first owner is created by
POST /api/auth/setup, which works only while there are no users at all.

Roles: owner (runs the hub, manages users, can do everything), teacher (creates and owns courses),
learner (takes courses). Settings: HANDOVER_TOKEN_DAYS (30), HANDOVER_LOGIN_PER_MINUTE (5),
HANDOVER_AUTH (optional or required), HANDOVER_DATA.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request

from server import library

ROLES = ("owner", "teacher", "learner")
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LEN = 2**14, 8, 1, 32
NAME_MAX = 40
PASSCODE_MIN, PASSCODE_MAX = 4, 128
NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")
WINDOW_S = 60.0
HANDOFF_TTL_S = 120.0


def now() -> float:
    """Wall clock for token expiry; tests replace it."""
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------- passcodes

def hash_passcode(passcode: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(passcode.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_passcode(passcode: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(passcode.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, bytes.fromhex(digest))


_DUMMY_HASH = hash_passcode(secrets.token_hex(8))  # unknown names cost the same time as wrong passcodes


# ---------------------------------------------------------------- users

def _users_path():
    return library.data_dir() / "users.json"


def _tokens_path():
    return library.data_dir() / "tokens.json"


def _load_users() -> list[dict]:
    data = library.read_json(_users_path(), {"users": []}, "users.json")
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, list):
        raise HTTPException(500, "users.json unreadable")
    return [u for u in users if isinstance(u, dict) and u.get("id")]


def _save_users(users: list[dict]) -> None:
    library.write_json(_users_path(), {"users": users}, private=True)


def public(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "role": user["role"], "created": user.get("created")}


def has_users() -> bool:
    return bool(_load_users())


def list_users() -> list[dict]:
    return [public(u) for u in _load_users()]


def get_user(user_id: Optional[str]) -> Optional[dict]:
    if not user_id:
        return None
    return next((public(u) for u in _load_users() if u["id"] == user_id), None)


def find_user_by_name(name: object) -> Optional[dict]:
    """The user with this name (any letter case, spaces collapsed), or None."""
    if not isinstance(name, str):
        return None
    wanted = " ".join(name.split()).lower()
    return next((public(u) for u in _load_users() if u["name"].lower() == wanted), None)


def user_names() -> dict[str, str]:
    return {u["id"]: u["name"] for u in _load_users()}


def clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise HTTPException(400, "name must be text")
    name = " ".join(name.split())
    if not name or len(name) > NAME_MAX or not NAME_RE.match(name):
        raise HTTPException(400, f"name must be 1 to {NAME_MAX} characters")
    return name


def check_passcode(passcode: object) -> str:
    if not isinstance(passcode, str) or not PASSCODE_MIN <= len(passcode) <= PASSCODE_MAX:
        raise HTTPException(400, f"passcode must be {PASSCODE_MIN} to {PASSCODE_MAX} characters")
    return passcode


def check_role(role: object) -> str:
    if role not in ROLES:
        raise HTTPException(400, "role must be owner, teacher or learner")
    return str(role)


def _create(users: list[dict], name: str, role: str, passcode: str) -> dict:
    if any(u["name"].lower() == name.lower() for u in users):
        raise HTTPException(409, "a user with that name already exists")
    user = {"id": uuid.uuid4().hex, "name": name, "role": role, "passcode": hash_passcode(passcode),
            "created": library.now_iso()}
    users.append(user)
    _save_users(users)
    return user


def setup_owner(name: object, passcode: object) -> dict:
    """First run only: creates the hub owner while there are no users. 409 afterwards."""
    name, passcode = clean_name(name), check_passcode(passcode)
    with library.LOCK:
        users = _load_users()
        if users:
            raise HTTPException(409, "setup is already done")
        return public(_create(users, name, "owner", passcode))


def create_user(name: object, role: object, passcode: object) -> dict:
    name, role, passcode = clean_name(name), check_role(role), check_passcode(passcode)
    with library.LOCK:
        return public(_create(_load_users(), name, role, passcode))


def _owners(users: list[dict]) -> int:
    return sum(1 for u in users if u["role"] == "owner")


def update_user(user_id: str, name: object = None, role: object = None, passcode: object = None) -> dict:
    """Rename, change role or reset passcode. A passcode reset signs the user out everywhere.
    The last owner cannot be demoted."""
    with library.LOCK:
        users = _load_users()
        user = next((u for u in users if u["id"] == user_id), None)
        if user is None:
            raise HTTPException(404, "user not found")
        if name is not None:
            name = clean_name(name)
            if any(u["name"].lower() == name.lower() and u["id"] != user_id for u in users):
                raise HTTPException(409, "a user with that name already exists")
            user["name"] = name
        if role is not None:
            role = check_role(role)
            if user["role"] == "owner" and role != "owner" and _owners(users) == 1:
                raise HTTPException(409, "the hub needs at least one owner")
            user["role"] = role
        if passcode is not None:
            user["passcode"] = hash_passcode(check_passcode(passcode))
        _save_users(users)
        if passcode is not None:
            revoke_user_tokens(user_id)
        return public(user)


def delete_user(user_id: str) -> None:
    """Removes the user, their tokens and their org memberships. Their courses keep owner_id; the hub owner can
    transfer them."""
    with library.LOCK:
        users = _load_users()
        user = next((u for u in users if u["id"] == user_id), None)
        if user is None:
            raise HTTPException(404, "user not found")
        if user["role"] == "owner" and _owners(users) == 1:
            raise HTTPException(409, "the hub needs at least one owner")
        _save_users([u for u in users if u["id"] != user_id])
        revoke_user_tokens(user_id)
        library.remove_user_everywhere(user_id)


def authenticate(name: object, passcode: object) -> Optional[dict]:
    """The user for this name (any letter case) and passcode, else None. Same work either way."""
    if not isinstance(name, str) or not isinstance(passcode, str) or len(passcode) > PASSCODE_MAX:
        return None
    wanted = " ".join(name.split()).lower()
    user = next((u for u in _load_users() if u["name"].lower() == wanted), None)
    ok = verify_passcode(passcode, user["passcode"] if user else _DUMMY_HASH)
    return public(user) if user and ok else None


# ---------------------------------------------------------------- tokens

def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_tokens() -> dict:
    data = library.read_json(_tokens_path(), {"tokens": {}}, "tokens.json")
    tokens = data.get("tokens") if isinstance(data, dict) else None
    return tokens if isinstance(tokens, dict) else {}


def _save_tokens(tokens: dict) -> None:
    t = now()
    live = {k: v for k, v in tokens.items() if isinstance(v, dict) and float(v.get("expires", 0)) > t}
    library.write_json(_tokens_path(), {"tokens": live}, private=True)


def issue_token(user_id: str) -> dict:
    token = secrets.token_urlsafe(32)
    t = now()
    expires = t + float(library.setting("HANDOVER_TOKEN_DAYS")) * 86400
    with library.LOCK:
        tokens = _load_tokens()
        tokens[_digest(token)] = {"user_id": user_id, "created": t, "expires": expires}
        _save_tokens(tokens)
    return {"token": token, "expires": _iso(expires)}


def resolve_token(token: str) -> Optional[dict]:
    if not token or len(token) > 256:
        return None
    entry = _load_tokens().get(_digest(token))
    if not isinstance(entry, dict) or float(entry.get("expires", 0)) <= now():
        return None
    return get_user(entry.get("user_id"))


def revoke_token(token: str) -> None:
    with library.LOCK:
        tokens = _load_tokens()
        if tokens.pop(_digest(token), None) is not None:
            _save_tokens(tokens)


def revoke_user_tokens(user_id: str) -> None:
    with library.LOCK:
        tokens = _load_tokens()
        kept = {k: v for k, v in tokens.items() if not (isinstance(v, dict) and v.get("user_id") == user_id)}
        if len(kept) != len(tokens):
            _save_tokens(kept)


# ---------------------------------------------------------------- one-scan account handoff

# Pairing secrets are short lived and memory-only. The QR contains this high-entropy secret, never a bearer
# token. A signed-in phone approves it; the Mac that created the QR redeems it once for an independent token.
_handoffs: dict[str, dict] = {}


def _clean_handoffs() -> None:
    t = now()
    for digest, entry in list(_handoffs.items()):
        if not isinstance(entry, dict) or float(entry.get("expires", 0)) <= t:
            _handoffs.pop(digest, None)


def start_handoff() -> dict:
    claim = secrets.token_urlsafe(32)
    expires = now() + HANDOFF_TTL_S
    with library.LOCK:
        _clean_handoffs()
        _handoffs[_digest(claim)] = {"expires": expires, "user_id": None}
    return {"claim": claim, "expires": _iso(expires)}


def approve_handoff(claim: object, user_id: str) -> dict:
    if not isinstance(claim, str) or not 32 <= len(claim) <= 128:
        raise HTTPException(404, "pairing code expired; show a new code on the Mac")
    with library.LOCK:
        _clean_handoffs()
        entry = _handoffs.get(_digest(claim))
        if not isinstance(entry, dict):
            raise HTTPException(404, "pairing code expired; show a new code on the Mac")
        entry["user_id"] = user_id
        return {"approved": True, "expires": _iso(float(entry["expires"]))}


def redeem_handoff(claim: object) -> Optional[dict]:
    """Consume an approved handoff and return a fresh device token. None means the phone has not approved yet."""
    if not isinstance(claim, str) or not 32 <= len(claim) <= 128:
        raise HTTPException(404, "pairing code expired; show a new code on the Mac")
    with library.LOCK:
        _clean_handoffs()
        digest = _digest(claim)
        entry = _handoffs.get(digest)
        if not isinstance(entry, dict):
            raise HTTPException(404, "pairing code expired; show a new code on the Mac")
        user_id = entry.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return None
        _handoffs.pop(digest, None)
    user = get_user(user_id)
    if user is None:
        raise HTTPException(404, "account no longer exists")
    return {"status": "approved", "user": user, **issue_token(user_id)}


def reset_handoffs() -> None:
    """Tests and hub teardown: handoffs never survive a process."""
    with library.LOCK:
        _handoffs.clear()


# ---------------------------------------------------------------- login rate limit

_attempts: dict[str, collections.deque] = {}


def reset_rate_limits() -> None:
    with library.LOCK:
        _attempts.clear()


def rate_allowed(keys: list[str]) -> bool:
    """Counts one attempt against every key (HANDOVER_LOGIN_PER_MINUTE each, sliding minute). False when any
    key is already at the limit; a refused attempt is not counted."""
    limit = int(library.setting("HANDOVER_LOGIN_PER_MINUTE"))
    t = time.monotonic()
    with library.LOCK:
        for key in list(_attempts):
            q = _attempts[key]
            while q and t - q[0] >= WINDOW_S:
                q.popleft()
            if not q:
                del _attempts[key]
        if any(len(_attempts.get(k, ())) >= limit for k in keys):
            return False
        for k in keys:
            _attempts.setdefault(k, collections.deque()).append(t)
    return True


def login_allowed(name: object, ip: str) -> bool:
    """A login attempt, limited per name (any letter case) and per IP."""
    keys = [f"ip:{ip}"]
    if isinstance(name, str):
        keys.append("name:" + " ".join(name.split()).lower()[:NAME_MAX])
    return rate_allowed(keys)


def join_allowed(user_id: str, ip: str) -> bool:
    """An org invite code attempt, limited per user and per IP, apart from logins."""
    return rate_allowed([f"join-ip:{ip}", f"join-user:{user_id}"])


# ---------------------------------------------------------------- FastAPI dependencies

def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("bad authorization header")
    return token.strip()


def current_user(request: Request) -> Optional[dict]:
    """The signed-in user, or None for an anonymous caller. A token that is sent but invalid or expired is
    always 401 (so a client drops it), whatever HANDOVER_AUTH says."""
    token = bearer(request)
    if token is None:
        return None
    user = resolve_token(token)
    if user is None:
        raise _unauthorized("invalid or expired token")
    return user


def mutation_guard(user: Optional[dict] = Depends(current_user)) -> Optional[dict]:
    """For the hub's other mutating routes: anonymous is fine while HANDOVER_AUTH=optional, else 401."""
    if user is None and library.auth_mode() == "required":
        raise _unauthorized("sign in required")
    return user


def require_user(user: Optional[dict] = Depends(current_user)) -> dict:
    if user is None:
        raise _unauthorized("sign in required")
    return user


def require_owner(user: dict = Depends(require_user)) -> dict:
    if user["role"] != "owner":
        raise HTTPException(403, "only the hub owner can manage users")
    return user

# Library, accounts, organizations and editor API

Accounts, a course library, organizations, publishing, a lesson editor with undo, learner scores and course ratings. Everything is LAN-local, stored in plain files, standard library only. No seed data: the first owner is created by an explicit setup call.

Code: `server/accounts.py` (users, tokens, rate limits), `server/library.py` (files, courses, orgs, permissions, history, ratings, events), `server/scoring.py` (scores), `server/routes_library.py` (the routes). Tests: `.venv/bin/python -m server.test_library`.

## Settings

| Var | Default | Meaning |
|---|---|---|
| `HANDOVER_DATA` | `<repo>/data` | hub data folder (accounts, orgs, history, ratings, audit). Keep it out of git |
| `HANDOVER_AUTH` | `optional` | `optional`: anonymous callers keep the open flow on legacy lessons (no sign-in needed). `required`: every change needs a token; public reads stay open |
| `HANDOVER_TOKEN_DAYS` | 30 | sign-in token lifetime in days (0.0001 to 365) |
| `HANDOVER_LOGIN_PER_MINUTE` | 5 | login attempts per name and per IP per minute; the same limit applies to org invite codes per user and per IP (1 to 100) |
| `HANDOVER_HISTORY_DEPTH` | 20 | undo snapshots kept per course (1 to 100) |
| `HANDOVER_EVENTS_JSONL` | `<repo>/logs/events.jsonl` | learn events read for progress, insights and scores (the file `server/databricks.py` writes) |
| `HANDOVER_LESSONS` | `<repo>/lessons` | lessons folder (existing setting) |

## Wiring in main.py

```python
from server import routes_library
app.include_router(routes_library.router)
routes_library.configure(lock=lesson_write_lock, on_lesson_changed=engine.reload_if_active,
                         upload=upload_lesson, job_status=lambda job: jobs.get(job),
                         publish=lambda d, lesson_id: publish_lesson_files(lesson_id))
```

| Hook | Used for | Without it |
|---|---|---|
| `lock` | every edit, undo, self-test and voiceover holds the same lock as recut and delete | the router's own lock (edits still never overlap each other) |
| `on_lesson_changed(id)` | the engine reloads an active lesson after an edit | no reload |
| `upload(file=, title=, id=)` | `POST /api/courses` reuses the hub's upload job | 503 `uploads are not available` |
| `job_status(job)` | a pending course whose teach job failed is dropped | pending courses finalize whenever lesson.json appears |
| `publish(dir, id)` | lesson files to Databricks after an edit | `databricks.upload_lesson_files` (a no-op without credentials) |
| `emit(row)` | optional: every `course_edit` audit row | audit file only |

`accounts.mutation_guard` is a FastAPI dependency for the hub's older mutating routes (`POST /api/lesson`, recut, delete): it returns 401 for anonymous callers only when `HANDOVER_AUTH=required`.

## Files

```
<lessons>/<id>/course.json        course metadata (never inside lesson.json)
<lessons>/<id>/covers/            cover images; a chosen frame is copied here so a recut cannot change it
<data>/users.json                 users with scrypt passcode hashes (mode 600)
<data>/tokens.json                SHA-256 of each sign-in token, with expiry (mode 600)
<data>/orgs.json                  organizations, members, invites (only a SHA-256 of each code) (mode 600)
<data>/pending/<id>.json          owner of a course whose teach job is still running
<data>/history/<id>/stack.json    undo and redo snapshots of lesson.json (plus caption files when edited)
<data>/ratings/<id>.json          one rating per user
<data>/audit.jsonl                one line per change: ts, kind, lesson_id, user_id, op
```

Every write is a temp file in the same folder, fsync, then rename, under one lock. An unreadable users, tokens or orgs file is a 500, never treated as empty, so setup can never reopen by accident.

### course.json

| Field | Type | Notes |
|---|---|---|
| `owner_id` | string or null | null means legacy (owned by nobody) |
| `org_id` | string or null | the organization the course belongs to |
| `title`, `description` | string | title is also written to lesson.json so the learn screen matches |
| `cover` | string or null | relative path in `covers/` |
| `status` | `draft`, `published`, `unlisted` | unlisted: open by link, not listed |
| `visibility` | `only_me`, `shared`, `org`, `everyone` | |
| `access` | `[{"user_id", "role": "editor" or "learner"}]` | |
| `created`, `updated`, `published_at` | ISO time | |
| `version` | int | +1 on every publish |
| `steps_changed_at` | ISO time or null | set when step timing changes; insights skip older events |

A lesson folder without course.json is legacy: status `published`, visibility `everyone`, no owner.

## Permissions

Decided in one place, `library.allowed()`. An anonymous caller who is refused gets 401 `sign in required`; anyone else gets 403 with the message in the last column.

Roles, strongest first: hub owner, course owner, course editor, org admin (of the course's org), org teacher, org learner or access-list learner, signed in, anonymous.

| Action | Hub owner | Course owner | Editor | Org admin | Org teacher or learner, access learner | Signed in | Anonymous | 403 message |
|---|---|---|---|---|---|---|---|---|
| view a draft | yes | yes | yes | yes | no | no | no | `you do not have access to this course` |
| view, published `everyone` | yes | yes | yes | yes | yes | yes | yes | |
| view, published `shared` | yes | yes | yes | yes | access learners only | no | no | same |
| view, published `org` | yes | yes | yes | yes | org members only | no | no | same |
| view, published `only_me` | yes | yes | yes | yes | no | no | no | same |
| edit (editor routes, title, description, cover) | yes | yes | yes | no | no | no | no | `only the course owner or an editor can edit this course` |
| insights | yes | yes | yes | yes | no | no | no | `only the course owner, an editor or an admin of its organization can see insights` |
| publish | yes | yes | no | no | no | no | no | `only the course owner can publish this course` |
| unpublish | yes | yes | no | yes | no | no | no | `only the course owner or an admin of its organization can unpublish this course` |
| sharing (visibility, access, org_id) | yes | yes | no | no | no | no | no | `only the course owner can change who can see this course` |
| change owner | yes | no | no | no | no | no | no | `only the hub owner can change a course's owner` |
| rate | yes, unless owner or editor | no | no | if they can view | if they can view | if they can view | no | `people who own or edit a course cannot rate it` |
| create a course | yes | | | in that org | org teachers in that org | hub teachers | optional mode only (legacy) | `learners cannot create courses; ask the hub owner for the teacher role`, or `only teachers and admins of this organization can create courses in it` |

Legacy lessons: edit and insights are open to everyone while `HANDOVER_AUTH=optional` (no sign-in needed); with `required`, only the hub owner (`only the hub owner can edit a lesson that has no course owner`).

Organizations:

| Action | Hub owner | Org admin | Org teacher | Org learner | Not a member | Anonymous |
|---|---|---|---|---|---|---|
| create an org | yes | yes | yes | yes | yes | no |
| see the org, members, courses | yes | yes | yes | yes | no | no |
| see pending invites | yes | yes | no | no | no | no |
| rename, invite, revoke, change roles, remove members | yes | yes | no | no | no | no |
| delete the org | yes | its creator only | no | no | no | no |
| leave | | yes, unless the last admin | yes | yes | | |
| create courses in the org, move a course into it | yes | yes | yes | no | no | no |

## Errors

FastAPI style: status plus `{"detail": "<message>"}`. Shared ones:

| Status | detail |
|---|---|
| 400 | `bad lesson id`, `body must be JSON`, `body must be a JSON object`, `unknown field: <name>`, `nothing to change`, `no step <n>` |
| 401 | `sign in required`, `invalid or expired token`, `bad authorization header` (with `WWW-Authenticate: Bearer`) |
| 404 | `lesson not found`, `organization not found` |
| 409 | `recut already running` (a recut, delete or edit holds the lesson lock) |
| 413 | `body is larger than 1 MB` |
| 500 | `lesson.json unreadable: <reason>`, `<file> unreadable` |

A token that is sent but invalid is always 401, even in optional mode, so the client drops it.

## Accounts

| Route | Who | Request | Response | Errors |
|---|---|---|---|---|
| `GET /api/me` | anyone | | `{"user": User or null, "auth": "optional" or "required", "setup_needed": bool}` | |
| `POST /api/auth/setup` | anyone, only while there are no users | `{"name", "passcode"}` | `{"user", "token", "expires"}` (the owner) | 409 `setup is already done`; 400 `name must be 1 to 40 characters`, `passcode must be 4 to 128 characters` |
| `POST /api/auth/login` | anyone | `{"name", "passcode"}`; name in any letter case | `{"user", "token", "expires"}` | 401 `wrong name or passcode`; 429 `too many login attempts; try again in a minute` with `Retry-After: 60` |
| `POST /api/auth/logout` | signed in | | `{"ok": true}` | 401 |
| `GET /api/users` | hub owner | | `[User]` | 403 `only the hub owner can manage users` |
| `POST /api/users` | hub owner | `{"name", "role", "passcode"}` | User | 409 `a user with that name already exists`; 400 `role must be owner, teacher or learner` |
| `PATCH /api/users/{id}` | hub owner | any of `name`, `role`, `passcode` | User. A passcode reset signs the user out everywhere | 404 `user not found`; 409 `the hub needs at least one owner` |
| `DELETE /api/users/{id}` | hub owner | | `{"deleted": id}`; tokens and org memberships go too; courses keep their owner_id | 404; 409 `the hub needs at least one owner` |
| `GET /api/users/{id}/public` | anyone | | `{"id", "name", "courses": [...], "orgs": [...]}` | 404 `user not found` |

User: `{"id", "name", "role", "created"}`. Tokens are 256-bit random, stored as SHA-256. Passcodes use scrypt (n 16384, r 8, p 1, 16-byte salt); an unknown name costs the same work as a wrong passcode.

The public profile lists courses the person owns that the caller may see (never drafts), and only orgs the caller shares with them (the hub owner sees all). No role, dates or passcode data.

## Library

| Route | Who | Request | Response |
|---|---|---|---|
| `GET /api/courses` | anyone | query `filter` = `all`, `mine`, `shared`, `orgs`, `everyone`; `org` = org id; `q` (title, description, id); `status` | `[Summary]`, newest `updated` first |
| `GET /api/courses/{id}` | view | | `{"course", "lesson", "permissions", "history": {"undo", "redo"} or null}` |
| `GET /api/courses/{id}/progress` | view | | see Progress |
| `POST /api/courses` | create | multipart `file`, `title`, optional `id`, `description`, `org_id` | `{"job", "id"}`; poll `GET /api/jobs/{job}` |
| `PATCH /api/courses/{id}` | edit for title, description, cover; sharing for visibility, access, org_id; hub owner for owner_id | any of those fields | Course |
| `POST /api/courses/{id}/cover` | edit | multipart `file`: JPEG, PNG or WebP, up to 5 MB | Course |
| `POST /api/courses/{id}/publish` | publish | optional `{"status": "published" or "unlisted", "visibility", "org_id"}` | Course, `version` +1 |
| `POST /api/courses/{id}/unpublish` | unpublish | | Course, status `draft` |

Summary: `id, title, cover_url, steps, duration, status, visibility, owner {id, name} or null, org {id, name, slug} or null, updated, legacy, version, progress` (`progress` only when the caller has runs, else null). `cover_url` falls back to `frames/01.jpg`.

Course adds `description, cover, access [{user_id, name, role}], created, published_at, steps_changed_at`.

Permissions: `can_view, can_edit, can_publish, can_unpublish, can_manage, can_transfer, can_see_insights, can_rate`.

Errors: `filter must be all, mine, shared, orgs or everyone`; `visibility must be only_me, shared, org or everyone`; `org visibility needs an organization (org_id)`; `you can only move a course into an organization where you teach`; `cover must be an image in frames/ or covers/`; `cover file not found`; `cover must be a JPEG, PNG or WebP image`; `unknown user: <id>`; `access role must be editor or learner`; `the course owner does not need an access entry`; `the new owner must be a hub owner or a teacher`; `a course needs at least one step to publish`; `status must be published or unlisted`; 503 `uploads are not available`.

Publishing to an organization: `POST /api/courses/{id}/publish {"visibility": "org", "org_id": "<org>"}` (or set them with PATCH first). Its members then see it in the library and under `filter=orgs`.

`POST /api/courses` by a signed-in teacher writes a pending entry; course.json (draft, `only_me`, owner = caller) appears once the teach job has written lesson.json. Anonymous callers in optional mode get a legacy lesson, as with `POST /api/lesson`.

## Editor

Every operation: permission `edit`, then the lesson lock (409 when busy), then validation, then a snapshot for undo, then the write. When step timing changed, `teach.recut` runs in a worker thread; if it fails, lesson.json and any edited files go back and the undo entry is removed. On success: audit line, engine reload, Databricks upload.

Response for all of them: `{"lesson": <lesson.json>, "history": {"undo", "redo"}, "recut": bool}`.

| Route | Body | Recut | Errors |
|---|---|---|---|
| `POST .../edit/boundaries` | `{"steps": [{"n", "start"?, "end"?}]}`, times as seconds or `MM:SS(.s)` | yes | `steps must be a list of 1 to 50 entries`, `step <n> is listed twice`, `step <n> <key>: bad timestamp: ...`, `step <n> starts before 0`, `step <n> is shorter than 0.3 s`, `step <n> starts before step <n-1> ends` |
| `POST .../edit/split` | `{"n", "at"}` | yes | `at must be inside step <n>, at least 0.3 s from each end`, `too many steps` |
| `POST .../edit/merge` | `{"n"}`: merges n with n+1 | yes | `step <n> is the last step; there is nothing after it to merge` |
| `POST .../edit/delete` | `{"n"}` | yes | `a lesson needs at least one step` |
| `POST .../edit/step` | `{"n", "title"?, "check_type"?, "check_question"?, "common_mistake"?}` | no | `check_type must be camera or manual`, `title must be 1 to 120 characters`, text limits 300 |
| `POST .../edit/captions` | `{"n", "cues": [{"start", "end", "text"}]}` (seconds within the clip) | no | `cue <k> must start at 0 or later, end after it starts, and end within the clip`, `cue <k> text cannot contain --> or blank lines` |
| `POST .../edit/selftest` | `{"n"?}` | no | `step <n> is manual; the self-test only runs on camera steps`; 500 `self-test failed: <reason>` |
| `POST .../edit/voiceover` | `{"mode": "duck" or "replace", "voice"?, "steps"?: [n]}` | no | `mode must be duck or replace`, `voice must be a voice name such as af_heart` |
| `POST .../edit/voiceover/undo` | | no | |
| `POST .../edit/undo`, `.../edit/redo` | | when timing differs | 409 `nothing to undo`, `nothing to redo` |
| `GET .../jobs/{job}` | | | 404 `job not found` |

Notes:
- Split: both halves keep the step's check fields; the second is titled `<title> (part 2)`. Merge: the merged step keeps the first step's title and start, and the second step's end, check and reference time (it ends in that step's finished state).
- Step edits: a manual step gets an empty question; a camera step with none gets `Is this step finished?`. Changing the check removes the old `self_test`.
- Self-test: returns `{"results": [{"n", "self_test"}], "lesson", "history"}`. With `n`, the other steps are hidden as manual for the run, so only that step's two check calls are made.
- Voiceover: returns `{"job", "status": "queued"}`. The job holds the lesson lock until done and reports `{"status", "message", "result": {"voiced", "skipped", "voiceover", "note", "scripts"}}`. Without a Claude key the step titles are read (`note` says so).
- A recut rebuilds clips, so edits that recut drop the lesson's `voiceover` field; voice it again afterwards. An undo without a recut keeps the current voiceover.
- Recut also rewrites captions from the transcript, so hand-edited captions on a step are replaced by the next recut.

## Progress, insights, runs and scores

All numbers come from real learn events. A learner's runs are found by the `learner` field of `run_start` (from `databricks.start_run(lesson_id, learner)`); runs without one belong to nobody.

| Route | Who | Response |
|---|---|---|
| `GET /api/courses/{id}/progress` | view | `{"known": false, "reason": "sign in to track progress" or "no runs yet", "runs": 0, "total"}` or `{"known": true, "runs", "completed", "best_steps_done", "last_steps_done", "last_finished", "last_at", "total"}` |
| `GET /api/courses/{id}/insights` | insights | query `all=1` includes events from before the last step change; `org=<id>` counts only that org's members (the caller must be a member) |
| `GET /api/courses/{id}/runs` | view, signed in | `{"runs": [Run summary], "reason": null or "no runs yet"}` (the caller's own runs) |
| `GET /api/runs/{run_id}/score` | the run's learner, or insights on the course | full score, plus `lesson_changed_after_run` |

Insights response:

```json
{"enough_data": true, "reason": null, "since": null, "org": null,
 "runs": {"started": 2, "finished": 2, "n": 2},
 "ratings": {"average": 4.0, "count": 1, "distribution": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0}},
 "steps": [{"n": 1, "title": "Fold", "expert_seconds": 4.0,
            "median_seconds": {"value": 2.5, "n": 4}, "manual_rate": {"value": 0.5, "n": 4},
            "mistakes_caught": {"value": 2, "n": 4}, "check_failure_rate": {"value": 0.0, "n": 4},
            "back_presses": {"value": 0, "n": 4}, "score": {"value": 97.0, "n": 2}}]}
```

- `median_seconds`: time on the step before moving forward. `manual_rate`: share of forward moves by Next or voice. `check_failure_rate`: share of checks that errored or timed out. `mistakes_caught` and `back_presses`: counts, n = visits. `score`: mean step score over runs.
- Any metric with n = 0 is null. With no data at all: `enough_data: false`, `reason: "not enough data"`, `steps: []`.

Errors: 400 `bad run id`; 404 `run not found`; 403 `you are not a member of this organization`.

### Score formula

Each step input is scored 0 to 100. Inputs with no data are left out and the other weights scale up. The response lists every input with its raw value, score, weight, `used` flag and rule.

| Input | Weight | Rule |
|---|---|---|
| time | 0.30 | time on the step / expert clip length: 100 up to 1.5x, then down to 0 at 4x |
| completion | 0.30 | camera verified 100 (also when the camera saw the learner was ahead), Next on a manual step 100, Next on a camera step 60, skipped 0 |
| mistakes | 0.15 | 100, minus 15 per mistake caught and corrected, minus 40 per mistake left uncorrected |
| retries | 0.10 | 100, minus 20 per Back press on the step |
| confidence | 0.15 | check confidence at verification x 100, camera-verified steps only |

A step never reached has score null, reason `not enough data`; one reached but not finished has reason `not finished in this run`.

Run: score = mean of step scores that exist. Label: `Excellent` at 90 or more, `Good` 75 to 89, `Keep practicing` below 75. `best_step` and `weakest_step` are `{"n", "score"}`. `tip`: the weakest step's `common_mistake` when there is one, else a hint from its weakest input (for example `Step 2 took 3.0x the expert's time. Watch the clip once more before you start it.`), else null. With no step scores: `score`, `label` and `tip` are null and `reason` is `not enough data`.

## Ratings

| Route | Who | Request | Response | Errors |
|---|---|---|---|---|
| `GET /api/courses/{id}/ratings` | view | query `org=<id>` counts only that org's members | `{"average" or null, "count", "distribution", "mine", "comments", "org"}`; `comments` (`[{user_id, name, stars, comment, updated}]`) only for those with insights, else null | |
| `POST /api/courses/{id}/rating` | rate | `{"stars": 1 to 5, "comment"?: up to 500}` | `{"rating", "summary"}`; one per user, posting again updates it | `stars must be a whole number from 1 to 5`, `comment must be at most 500 characters` |
| `DELETE /api/courses/{id}/rating` | signed in | | `{"deleted": true, "summary"}` | 404 `no rating to delete` |

## Organizations

| Route | Who | Request | Response | Errors |
|---|---|---|---|---|
| `GET /api/orgs` | signed in | | `{"orgs": [{id, name, slug, created, members, role}], "invites": [invites sent to me by name]}` | |
| `POST /api/orgs` | signed in | `{"name", "slug"?}` | Org; the caller is its admin and creator | `that slug is taken`, `slug must be 1 to 40 lowercase letters, digits and dashes`; 429 `too many organizations` (50 per creator) |
| `GET /api/orgs/{id}` | members, hub owner | | Org | 403 `you are not a member of this organization` |
| `PATCH /api/orgs/{id}` | org admin | `{"name"?, "slug"?}` | Org | 403 `only an admin of this organization can do that` |
| `DELETE /api/orgs/{id}` | creator, hub owner | | `{"deleted"}`; its courses go back to `only_me` with no org | 403 `only the organization's creator or the hub owner can delete it` |
| `POST /api/orgs/{id}/invites` | org admin | by name: `{"username", "role"?, "expires_days"?}` (30 days). Code: `{"role"?, "expires_days"?, "max_uses"?}` (7 days, 1 use; `null` = no limit) | Invite; a code invite includes `code`, shown only here | `user not found`, `that user is already a member`, `role must be org_admin, teacher or learner`, `expires_days must be a number from 0.01 to 90`, `max_uses must be a whole number from 1 to 1000, or null for no limit` |
| `DELETE /api/orgs/{id}/invites/{invite}` | org admin, or the invitee to decline | | `{"deleted"}` | 404 `invite not found` |
| `POST /api/orgs/join` | signed in | `{"code"}` or `{"invite_id"}` | `{id, name, slug, created, members, role}` | 404 `invite code is not valid`, `invite not found`; 409 `you are already a member of this organization`; 429 `too many join attempts; try again in a minute`; 400 `send either code or invite_id` |
| `POST /api/orgs/{id}/leave` | member | | `{"left"}` | 409 `the organization needs at least one admin` |
| `PATCH /api/orgs/{id}/members/{user}` | org admin | `{"role"}` | `{"user_id", "role"}` | 404 `member not found`; 409 last admin |
| `DELETE /api/orgs/{id}/members/{user}` | org admin | | `{"removed"}` | 404; 409 last admin |

Org: `{id, name, slug, created, members: [{user_id, name, role, joined}], role, owner {id, name}, courses: [courses the caller may see], invites: [live invites] or null}`. Invite: `{id, kind: "code" or "user", role, created, created_by, expires, max_uses, uses}` (user invites have `user` instead of the counts). Expired, used-up and revoked invites stop working at once and are not listed.

#!/usr/bin/env bash
# Turn one or more expert takes into a lesson folder (M14), then show how to fix step times.
#
#   scripts/new_lesson.sh --id fortune-teller-v1 --title "Fold a fortune teller" take1.mov [take2.mov ...]
#   scripts/new_lesson.sh --mock --id test-v1 --title "Test" clip.mp4     # no Gemini: three placeholder steps
#
# Runs server.teach: normalize each take, join them in order, find steps with Gemini, cut clips,
# captions and reference frames. Then prints the step table and the exact recut command.
# Lessons go to $HANDOVER_LESSONS, else <repo>/lessons. An existing lesson id is never overwritten.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}

ID="" TITLE="" MOCK=0
TAKES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --id) ID="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    --mock) MOCK=1; shift ;;
    -h|--help) usage 0 ;;
    --) shift; TAKES+=("$@"); break ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) TAKES+=("$1"); shift ;;
  esac
done

[ -n "$ID" ] || { echo "missing --id (for example --id fortune-teller-v1)" >&2; usage; }
[ ${#TAKES[@]} -gt 0 ] || { echo "give at least one take (video file)" >&2; usage; }
[ -n "$TITLE" ] || TITLE="$ID"

# Same cleaning as the upload endpoint (CONTRACT.md section 2), so the folder name is known up front.
CLEAN="$(printf '%s' "$ID" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//; s/-{2,}/-/g')"
if ! printf '%s' "$CLEAN" | grep -Eq '^[a-z0-9][a-z0-9_-]{0,63}$'; then
  echo "lesson id '$ID' is not usable; use letters, digits and dashes" >&2
  exit 2
fi
[ "$CLEAN" = "$ID" ] || echo "note: lesson id cleaned to '$CLEAN'"

LESSONS="${HANDOVER_LESSONS:-$ROOT/lessons}"
DIR="$LESSONS/$CLEAN"
if [ -e "$DIR" ]; then
  echo "$DIR already exists. Pick a new id (for example ${CLEAN%-v*}-v2) or remove that folder by hand first." >&2
  exit 1
fi

ABS=()
for t in "${TAKES[@]}"; do
  [ -f "$t" ] || { echo "no such file: $t" >&2; exit 1; }
  ABS+=("$(cd "$(dirname "$t")" && pwd)/$(basename "$t")")
done

echo "Lesson   $CLEAN  \"$TITLE\""
echo "Takes    ${#ABS[@]} (joined in this order)"
for t in "${ABS[@]}"; do echo "         $t"; done
echo "Steps    $([ "$MOCK" = 1 ] && echo 'mock: three placeholder steps, no Gemini' || echo 'Gemini')"
echo

ARGS=("${ABS[0]}" --id "$CLEAN" --title "$TITLE")
[ ${#ABS[@]} -gt 1 ] && ARGS+=(--concat "${ABS[@]:1}")
cd "$ROOT"
if [ "$MOCK" = 1 ]; then
  HANDOVER_TEACH_MOCK=1 "$PY" -m server.teach "${ARGS[@]}"
else
  "$PY" -m server.teach "${ARGS[@]}"
fi

[ -f "$DIR/lesson.json" ] || { echo "teach finished but $DIR/lesson.json is missing" >&2; exit 1; }

echo
"$PY" - "$DIR/lesson.json" <<'PY'
import json, sys
lesson = json.load(open(sys.argv[1], encoding="utf-8"))
rows = [("#", "Start", "End", "Check", "Title", "Question")]
for s in lesson.get("steps", []):
    q = s.get("check_question") or ""
    rows.append((str(s.get("n")), s.get("start", ""), s.get("end", ""), s.get("check_type", "camera"),
                 s.get("title", ""), q if len(q) <= 50 else q[:47] + "..."))
w = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
for i, r in enumerate(rows):
    print("  " + "  ".join(c.ljust(w[j]) for j, c in enumerate(r)).rstrip())
    if i == 0:
        print("  " + "  ".join("-" * x for x in w))
PY

REL="$DIR"
case "$DIR" in "$ROOT"/*) REL="${DIR#"$ROOT"/}" ;; esac
cat <<EOF

Check the clips:   open "$DIR/clips"
Fix a step time:   edit "start" and "end" (MM:SS or MM:SS.s) in $REL/lesson.json, then
  .venv/bin/python -m server.teach --recut "$REL"
Hub running?       curl -X POST http://localhost:8000/api/lessons/$CLEAN/recut
Recut keeps the old files if any timestamp is bad, so it is safe to retry.
EOF

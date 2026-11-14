#!/usr/bin/env bash
# Builds lessons/demo-v1 from a generated 40 s test video, without Gemini. It is a test pattern, not a real
# lesson: titles, questions and captions say so.
# Each 8 s segment has its own background color, N white bars for step N, and its own tone.
# (This ffmpeg build has no drawtext, so the step number is shown as bars.)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FFMPEG="$(command -v ffmpeg || echo /opt/homebrew/bin/ffmpeg)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

colors=(0x1f6feb 0x2da44e 0xbf8700 0xcf222e 0x8250df)
tones=(330 392 440 523 587)
inputs=()
filters=""
joins=""
for i in 0 1 2 3 4; do
  n=$((i + 1))
  inputs+=(-f lavfi -i "color=c=${colors[$i]}:s=1920x1080:r=30:d=8")
  inputs+=(-f lavfi -i "sine=frequency=${tones[$i]}:sample_rate=48000:duration=8")
  boxes=""
  for b in $(seq 1 $n); do
    boxes+="drawbox=x=$((560 + (b - 1) * 170)):y=390:w=120:h=300:color=white:t=fill,"
  done
  # a small box that moves left to right so the clip is not a still image
  filters+="[$((i * 2)):v]${boxes}drawbox=x='mod(t*240,1800)':y=900:w=120:h=60:color=black@0.6:t=fill[v$i];"
  joins+="[v$i][$((i * 2 + 1)):a]"
done
filters+="${joins}concat=n=5:v=1:a=1[v][a]"

"$FFMPEG" -hide_banner -loglevel error -y "${inputs[@]}" -filter_complex "$filters" \
  -map "[v]" -map "[a]" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -c:a aac "$TMP/demo.mp4"

cat > "$TMP/steps.json" <<'JSON'
{
  "steps": [
    {"start": "00:00", "end": "00:08", "title": "Pattern 1", "check_question": "Does the frame show one white bar?", "prerequisites": []},
    {"start": "00:08", "end": "00:16", "title": "Pattern 2", "check_question": "Does the frame show two white bars?", "prerequisites": [1]},
    {"start": "00:16", "end": "00:24", "title": "Pattern 3", "check_question": "manual", "prerequisites": [2]},
    {"start": "00:24", "end": "00:32", "title": "Pattern 4", "check_question": "Does the frame show four white bars?", "prerequisites": [3]},
    {"start": "00:32", "end": "00:40", "title": "Pattern 5", "check_question": "Does the frame show five white bars?", "prerequisites": [4]}
  ],
  "transcript": [
    {"start": 0.5, "end": 3.5, "text": "Test pattern step 1."},
    {"start": 4.0, "end": 7.5, "text": "Test pattern step 1."},
    {"start": 8.5, "end": 12.0, "text": "Test pattern step 2."},
    {"start": 13.0, "end": 17.0, "text": "Test pattern step 2."},
    {"start": 17.5, "end": 23.5, "text": "Test pattern step 3."},
    {"start": 24.5, "end": 31.5, "text": "Test pattern step 4."},
    {"start": 32.5, "end": 39.5, "text": "Test pattern step 5."}
  ]
}
JSON

cd "$ROOT"
rm -rf "${HANDOVER_LESSONS:-$ROOT/lessons}/demo-v1"
"$ROOT/.venv/bin/python" -m server.teach "$TMP/demo.mp4" --id demo-v1 --title "Test pattern (not a real lesson)" --steps-json "$TMP/steps.json"

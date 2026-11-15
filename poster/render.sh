#!/bin/sh
# Renders poster.html to poster.pdf (24 x 36 in, one page, vector text and diagram)
# and poster.png (1800 x 2700 preview). Fonts are local (fonts/), so no network is needed.
set -e
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
URL="file://$PWD/poster.html"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 \
  --print-to-pdf="$PWD/poster.pdf" "$URL" 2>/dev/null
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=8000 \
  --window-size=2304,3456 --force-device-scale-factor=0.78125 \
  --screenshot="$PWD/poster.png" "$URL" 2>/dev/null
python3 - <<'EOF'
import re
pdf = open("poster.pdf", "rb").read()
pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
box = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", pdf)
w, h = (float(box.group(3)) / 72, float(box.group(4)) / 72) if box else (0, 0)
print(f"pages: {pages}  size: {w:.2f} x {h:.2f} in")
if pages != 1 or abs(w - 24) > 0.02 or abs(h - 36) > 0.02:
    raise SystemExit("poster.pdf is not one 24 x 36 in page")
EOF

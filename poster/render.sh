#!/bin/sh
# Renders poster.html to poster.pdf (24 x 36 in, one page) and poster.png (1800 x 2700 preview).
set -e
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
URL="file://$PWD/poster.html"
"$CHROME" --headless=new --disable-gpu --no-pdf-header-footer --virtual-time-budget=8000 \
  --print-to-pdf="$PWD/poster.pdf" "$URL"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=8000 \
  --window-size=2304,3456 --force-device-scale-factor=0.78125 \
  --screenshot="$PWD/poster.png" "$URL"
echo "pages: $(python3 -c "import re;print(len(re.findall(rb'/Type\s*/Page[^s]', open('poster.pdf','rb').read())))")"

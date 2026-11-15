# HandOver poster

24 x 36 in portrait, one page. Source is `poster.html` (Inter from Google Fonts, system fallback). Images live in `img/`.

## Re-render

```
poster/render.sh
```

This writes `poster.pdf` (24 x 36 in, one page) and `poster.png` (1800 x 2700 preview) with headless Google Chrome, and prints the PDF page count. It must say `pages: 1`. Set `CHROME=/path/to/chrome` to use another Chrome binary. Render while online so Inter loads. Offline, the page falls back to the system font and lines may wrap differently.

The page is laid out in px on a 2304 x 3456 canvas (96 px per inch). Every size in `poster.html` uses that canvas.

## Print

- Print `poster.pdf` at 100% on 24 x 36 in stock, with no scaling and no borders. Matte paper keeps the screenshots readable under hall lights.
- For a letter or tabloid proof, print the PDF with "Fit to page". The text was sized so it is still readable at that scale.
- Check one proof before the big print. The off-white background is `#fafaf9`. Some print shops add margins, so ask them for full bleed or accept a thin white edge.

## Fill in before printing

1. **Devpost QR code.** Bottom right, the dashed box `.qr .box`. Replace its text with `<img src="img/qr.png" style="width:100%;height:100%">`. Generate the QR from the final Devpost URL, black on transparent, at least 600 px square.
2. **Median check latency.** Footer, `Median check latency __ s`. Use the M1 measurement (`python -m server.check --time`) or the dashboard's `latency_ms` median. If there is no real number, delete the whole `Measured` row (`<dt>` and `<dd>`). Never guess.
3. **Screenshots.** Everything in `img/` comes from `web/screenshots/` and shows the mock lesson (colored bars), not real footage. Once the fortune teller or bike lesson is cut, retake these at 1440 x 900 (hero at 1920 x 1080), keep the file names, and re-render:
   - `img/learn.png`: Learn mid-lesson, 1920 x 1080 (hero). The three numbered pins are placed by percentage in the HTML. Recheck them: 1 = live camera, 2 = expert clip, 3 = just above the status badge.
   - `img/record.png`: the "New lesson" card from the Teach start screen (cropped).
   - `img/steps.png`: Teach screen with the timeline and step cards, full frame.
   - `img/verified.png`: Learn with the green "Verified" badge, full frame.
   - `img/done.png`: the "Lesson complete" card, tightly cropped. Pranav's branch has a newer done screen with a per-step table (Expert vs You). If it ships, screenshot that card, and change the caption under "A record of the run" to match what it shows.
   - A Databricks dashboard screenshot could replace the hand-built "Ask Genie" card if the dashboard is ready and looks clean.

## Content checks (team rules)

- No "first", no "only", no training-time savings, no user counts.
- Glasses: the poster only says the expert records on Meta glasses. It makes no live-streaming claim. Keep it that way unless the 8 PM glasses gate passed.
- Comparisons name only Dozuki and Retrocausal.
- "Skip a step and it says so" depends on the catch (M9 + W6) shipping. If it did not ship, change that cell's title and text, or replace the cell.
- The privacy line says the hub never writes camera frames to disk. That matches the plan and M15. Make sure the privacy test lands before judging.

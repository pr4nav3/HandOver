# HandOver poster

24 x 36 in portrait, one page. Source is `poster.html`, styled like the web app ("Field manual, cream": paper `#f1ece1`, navy ink `#15213b`, cobalt `#1F49D6`, Barlow Condensed and Public Sans, same tokens as `web/src/styles.css`).

```
poster.html   the poster (2304 x 3456 CSS px canvas, 96 px per inch; 24 pt = 32 px, 28 pt = 37 px).
              Smallest text: 31 px (23 pt) in the diagram boxes; everything else is 32 px or more.
poster.pdf    print file, 24 x 36 in, one page, fonts embedded, text and diagram are vector
poster.png    1800 x 2700 preview
render.sh     builds both
fonts/        Barlow Condensed 500/600/700, Public Sans 400 to 700 (woff2, SIL OFL, from @fontsource)
img/          learn-mistake.png (hero), ft-frame-01..09.jpg (fortune teller v2 reference frames), qr-repo.svg
```

## Re-render

```
poster/render.sh
```

Uses headless Google Chrome (`CHROME=/path/to/chrome` to override). It prints `pages: 1  size: 24.00 x 36.00 in` and fails if either is wrong. Fonts are local, so it works offline. After any text change, check `poster.png` for overflow: every section has a fixed slot, and the footer must not touch the diagram.

## Where the images come from

- `img/learn-mistake.png`: the real web UI (commit 3442003 styling) with the real `lessons/fortune-teller-v2` lesson (the live demo), shot at 1280 x 860 with device scale 2.5 against the web mock server (`web/mock/mock-server.mjs`, run from a copy outside the repo). The mock feeds the lesson's own reference frames as the camera, so the "You" pane shows the step 2 reference frame and the mistake card is a mock `behind` message using step 3's `common_mistake`. The top bar (which said "Mock iPhone") is cropped off. To retake: run the mock and Vite as described at the top of `web/e2e/screenshots.mjs`, open `#/learn/fortune-teller-v2`, go to step 3, send a `behind` mistake, screenshot, crop the top 142 device px (`ffmpeg -vf crop=3200:2008:0:142`). The landscape v2 clips leave empty space under the step title; that is the real layout.
- `img/ft-frame-NN.jpg`: `lessons/fortune-teller-v2/frames/NN.jpg` (1934 x 1080), a 1040 x 1040 crop around the paper scaled to 608, `ffmpeg -i frames/NN.jpg -vf crop=1040:1040:420:20,scale=608:608 -q:v 2`. Camera tiles (blue border and number) follow each step's `check_type`: 1, 2, 3, 5, 6, 7 and 9 are camera, 4 and 8 manual.
- `img/qr-repo.svg`: made locally with segno (`segno.make(url, error='m')`) for `https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer`. The same SVG is pasted inline in the footer. It decodes from the 1800 px preview.

## Swap in later

- **Bike lesson frames.** The front wheel lesson (`lessons/front-wheel-v1`) was not in the repo when this was made, so its card is text only (from `lessons/templates/front-wheel.steps.json`), tagged Showcase because the live demo is the fortune teller. Once it is cut, you can replace the card's `<p>` with 3 to 5 of its `frames/NN.jpg` (crop square, as above). Keep the card's height: 373 px for the whole row.
- **Databricks dashboard screenshot.** There is no slot on purpose; the Data lane of the diagram describes the layer. If a clean dashboard or Genie screenshot exists and you want it, the least disruptive swap is the hero callouts row (`figcaption` under the hero, about 1160 x 150 px) or replacing the Genie box text. Anything taller pushes the footer off the page: re-render and check.
- **Bike step list.** The card text follows `lessons/templates/front-wheel.steps.json` (brakes, wheel off, rim, spokes, tire, wheel back on, spin). If the final take differs, edit `.bike p`.

## Print

- Print `poster.pdf` at 100% on 24 x 36 in, no scaling. Matte stock keeps the screenshot readable under hall lights.
- The background is a flat cream `#f1ece1`, printed edge to edge. Ask the shop for full bleed, or accept a thin white edge. Text keeps at least 0.5 in from every edge; the progress bar along the top edge is decoration and can be trimmed.
- For a proof, print with "Fit to page" on letter or tabloid.

## Content rules (team)

- No "first", no "only", no savings figure, no user counts, no past-winner claims. Numbers on the poster all come from the repo: 9 steps and the 3:08 take (`lessons/fortune-teller-v2/norm.mp4`, 188 s), 0.92 (`HANDOVER_FAST_CONF`), 4 tables (`databricks/01_setup.sql`).
- The live check is "Claude Haiku or Gemini" (`HANDOVER_CHECK_PROVIDER=auto`: Claude when an Anthropic key is present, else Gemini). It compares before, done reference and live frames. Lesson extraction is one Gemini call; narration is written by Claude and spoken by Kokoro.
- Glasses appear only as the expert's recorder ("Meta glasses or any camera"). The learner camera is a phone (HandOver app or browser page). Do not add glasses as a live learner camera unless it was demoed.
- No voice "next" claim. The six fixed cues (`web/public/voice`: done, ahead, still on the step, checks off, camera lost, lesson complete) are in the lesson voice. The per-step mistake line is spoken by browser speech (`web/src/cues.ts`).
- Privacy text follows `docs/PRIVACY.md`.

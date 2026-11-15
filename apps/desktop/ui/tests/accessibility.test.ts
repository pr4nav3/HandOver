import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("interactive ratings expose radio state and one keyboard tab stop", () => {
  return readFile(new URL("../src/components.ts", import.meta.url), "utf8").then((source) => {
    assert.match(source, /data-stars="\$\{n\}" role="radio"/);
    assert.match(source, /aria-checked="\$\{n === value\}"/);
    assert.match(source, /tabindex="\$\{n === \(value \|\| 1\) \? 0 : -1\}"/);
  });
});

test("desktop shell has a main landmark and a global reduced-motion path", async () => {
  const main = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.match(main, /<main class="main"/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation-duration:\s*0\.01ms/);
});

test("navigation calls the catalog Lessons and Home stays within the app viewport", async () => {
  const main = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  const browse = await readFile(new URL("../src/views/browse.ts", import.meta.url), "utf8");
  const home = await readFile(new URL("../src/views/home.ts", import.meta.url), "utf8");
  const teach = await readFile(new URL("../src/views/teach.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.match(main, /icons\.grid, "Lessons"/);
  assert.match(browse, /pageHead\("Lessons"\)/);
  assert.doesNotMatch(`${main}\n${browse}`, /Browse All/);
  assert.match(css, /body\[data-screen="home"\] #content\s*{\s*overflow:\s*hidden/);
  assert.match(css, /\.home-page\s*{[\s\S]*?height:\s*100%[\s\S]*?overflow:\s*hidden/);
  assert.doesNotMatch(home, /class="card how"|class="option-cards home-actions"/);
  assert.match(teach, /Upload a Video[\s\S]*Choose a File/);
});

test("Learn layout and tutorial controls expose keyboard and assistive semantics", async () => {
  const learn = await readFile(new URL("../src/views/learn.ts", import.meta.url), "utf8");
  const main = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(learn, /role="separator"[^>]+aria-orientation="vertical"/);
  assert.match(learn, /class="tutorial-scrubber"[^>]+aria-label="Tutorial position"/);
  assert.match(learn, /class="tutorial-cc on"[^>]+aria-pressed="true"/);
  assert.match(learn, /class="hold-step"[^>]+aria-pressed="false"/);
  assert.match(learn, /class="badge watching camera-verdict"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(learn, /<details class="steps-disclosure">/);
  assert.match(learn, /class="step-count" role="status" aria-live="polite"/);
  assert.doesNotMatch(learn, /class="progress" role="progressbar"/);
  assert.match(main, /key\.toLowerCase\(\) === "k"/);
  assert.match(main, /key\.toLowerCase\(\) === "h"/);
  assert.match(main, /key\.toLowerCase\(\) === "c"/);
});

test("Learn videos fill their columns inside flat panels and there is no goal card", async () => {
  const learn = await readFile(new URL("../src/views/learn.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.doesNotMatch(learn, /class="goal panel"/);
  assert.doesNotMatch(learn, /When this step is done/);
  const live = css.match(/\n\.live\s*{[^}]*}/)?.[0] ?? "";
  const clip = css.match(/\n\.clip\s*{[^}]*}/)?.[0] ?? "";
  assert.match(live, /flex:\s*1 1 auto/);
  assert.match(clip, /flex:\s*1 1 auto/);
  assert.doesNotMatch(clip, /aspect-ratio/);
  assert.match(clip, /background:\s*var\(--panel\)/);
});

test("Learn keeps the camera column on manual steps and centers the waiting state", async () => {
  const learn = await readFile(new URL("../src/views/learn.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.match(learn, /livePane\.hidden = false/);
  assert.match(learn, /classList\.toggle\("manual-focus", !!manualStep\)/);
  assert.doesNotMatch(learn, /class="badge-wrap feedback-card/);
  assert.match(css, /\.live\.waiting\s*{[^}]*flex:\s*0 0 auto/);
  assert.match(css, /\.live\.waiting\s*{[^}]*margin:\s*auto 0/);
  assert.match(css, /\.live\.waiting \.placeholder/);
});

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
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.match(main, /icons\.grid, "Lessons"/);
  assert.match(browse, /pageHead\("Lessons"\)/);
  assert.doesNotMatch(`${main}\n${browse}`, /Browse All/);
  assert.match(css, /body\[data-screen="home"\] #content\s*{\s*overflow:\s*hidden/);
  assert.match(css, /\.home-page\s*{[\s\S]*?height:\s*100%[\s\S]*?overflow:\s*hidden/);
});

test("Learn layout and tutorial controls expose keyboard and assistive semantics", async () => {
  const learn = await readFile(new URL("../src/views/learn.ts", import.meta.url), "utf8");
  const main = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(learn, /role="separator"[^>]+aria-orientation="vertical"/);
  assert.match(learn, /class="tutorial-scrubber"[^>]+aria-label="Tutorial position"/);
  assert.match(learn, /class="hold-step"[^>]+aria-pressed="false"/);
  assert.match(learn, /class="badge-wrap feedback-card[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(learn, /<details class="steps-disclosure">/);
  assert.match(learn, /class="progress" role="progressbar"/);
  assert.match(main, /key\.toLowerCase\(\) === "k"/);
  assert.match(main, /key\.toLowerCase\(\) === "h"/);
});

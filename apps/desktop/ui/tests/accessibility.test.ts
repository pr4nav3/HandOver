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

test("Learn layout and tutorial controls expose keyboard and assistive semantics", async () => {
  const learn = await readFile(new URL("../src/views/learn.ts", import.meta.url), "utf8");
  const main = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(learn, /role="separator"[^>]+aria-orientation="vertical"/);
  assert.match(learn, /class="tutorial-scrubber"[^>]+aria-label="Tutorial position"/);
  assert.match(learn, /class="hold-step"[^>]+aria-pressed="false"/);
  assert.match(learn, /class="badge-wrap feedback-card[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(main, /key\.toLowerCase\(\) === "k"/);
  assert.match(main, /key\.toLowerCase\(\) === "h"/);
});

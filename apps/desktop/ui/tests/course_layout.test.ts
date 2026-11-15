import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("course detail uses matched viewport columns with internally scrolling steps", async () => {
  const course = await readFile(new URL("../src/views/course.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");

  assert.match(course, /class="detail-intro"/);
  assert.match(course, /class="detail-start"/);
  assert.match(course, /class="detail-foot"/);
  assert.match(css, /body\[data-screen="course"\] #content\s*\{\s*overflow:\s*hidden/);
  assert.match(css, /\.detail\s*\{[\s\S]*?height:\s*100%[\s\S]*?align-items:\s*stretch/);
  assert.match(css, /\.detail-right \.steps-list\s*\{[\s\S]*?flex:\s*1[\s\S]*?overflow-y:\s*auto/);
  assert.match(css, /\.detail-start\s*\{[\s\S]*?margin-top:\s*auto/);
});

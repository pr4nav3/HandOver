import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("pairing keeps its live status without a duplicate context card", async () => {
  const source = await readFile(new URL("../src/views/pair.ts", import.meta.url), "utf8");
  assert.match(source, /Camera connected/);
  assert.doesNotMatch(source, /pair-context|pairingContext/);
});

test("iPhone and Meta are equal primary camera choices", async () => {
  const source = await readFile(new URL("../src/views/pair.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.match(source, /camera-primary-options/);
  assert.match(source, /"phone", icons\.phone, "Phone Camera"/);
  assert.match(source, /"glasses", icons\.glasses, "Meta Glasses"/);
  assert.match(css, /\.camera-primary-options\s*\{[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\)/);
});

test("pairing asks for one scan instead of a setup checklist", async () => {
  const source = await readFile(new URL("../src/views/pair.ts", import.meta.url), "utf8");
  assert.match(source, /Scan with your phone/);
  assert.doesNotMatch(source, /PHONE_STEPS|GLASSES_STEPS|pair-steps/);
});

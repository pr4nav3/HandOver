import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("pairing keeps connection and account context visible", async () => {
  const source = await readFile(new URL("../src/views/pair.ts", import.meta.url), "utf8");
  assert.match(source, /Ready on \$\{hub\}/);
  assert.match(source, /Signed in as \$\{app\.me\.user\.name\}/);
  assert.match(source, /Your iPhone sign-in syncs here/);
});

test("iPhone and Meta are equal primary camera choices", async () => {
  const source = await readFile(new URL("../src/views/pair.ts", import.meta.url), "utf8");
  const css = await readFile(new URL("../src/styles/app.css", import.meta.url), "utf8");
  assert.match(source, /camera-primary-options/);
  assert.match(source, /"phone", icons\.phone, "iPhone Camera"/);
  assert.match(source, /"glasses", icons\.glasses, "Meta Glasses"/);
  assert.match(css, /\.camera-primary-options\s*\{[\s\S]*grid-template-columns:\s*repeat\(2/);
});

test("pairing asks for one scan instead of a setup checklist", async () => {
  const source = await readFile(new URL("../src/views/pair.ts", import.meta.url), "utf8");
  assert.match(source, /Scan with the iPhone Camera/);
  assert.doesNotMatch(source, /PHONE_STEPS|GLASSES_STEPS|pair-steps/);
});

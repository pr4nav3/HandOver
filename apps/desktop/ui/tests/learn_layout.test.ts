import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_LEARN_LAYOUT,
  MAX_CAMERA_PERCENT,
  MIN_CAMERA_PERCENT,
  layoutFromLeftPercent,
  leftPercent,
  readLearnLayout,
  sanitizeLearnLayout,
  writeLearnLayout,
} from "../src/learn_layout.ts";

test("Learn defaults give the tutorial substantially more space", () => {
  assert.equal(DEFAULT_LEARN_LAYOUT.cameraPercent, 38);
  assert.equal(leftPercent(DEFAULT_LEARN_LAYOUT), 38);
  assert.ok(100 - DEFAULT_LEARN_LAYOUT.cameraPercent >= 60);
});

test("resizing is bounded and remains camera-relative after swapping", () => {
  assert.equal(layoutFromLeftPercent(2, false).cameraPercent, MIN_CAMERA_PERCENT);
  assert.equal(layoutFromLeftPercent(98, false).cameraPercent, MAX_CAMERA_PERCENT);
  assert.deepEqual(layoutFromLeftPercent(72, true), { cameraPercent: 28, tutorialFirst: true });
  assert.equal(leftPercent({ cameraPercent: 28, tutorialFirst: true }), 72);
});

test("corrupt stored layouts safely recover and valid layouts persist", () => {
  assert.deepEqual(sanitizeLearnLayout({ cameraPercent: "nope", tutorialFirst: "yes" }), DEFAULT_LEARN_LAYOUT);
  assert.deepEqual(readLearnLayout({ getItem: () => "{" }), DEFAULT_LEARN_LAYOUT);

  let stored = "";
  writeLearnLayout({ cameraPercent: 44.26, tutorialFirst: true }, { setItem: (_key, value) => (stored = value) });
  assert.deepEqual(JSON.parse(stored), { cameraPercent: 44.3, tutorialFirst: true });
});

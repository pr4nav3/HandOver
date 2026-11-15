import assert from "node:assert/strict";
import test from "node:test";

import type { ProfileAnalytics } from "../src/api.ts";
import { activityDetails, cameraSourceName, percent, practiceTime } from "../src/profile_metrics.ts";

test("profile values are concise and denominator-safe", () => {
  assert.equal(practiceTime(8.2), "8m");
  assert.equal(practiceTime(86.5), "1h 27m");
  assert.equal(percent(0.875), "88%");
  assert.equal(percent(null), "");
  assert.equal(cameraSourceName("glasses"), "Meta glasses");
});

test("profile details omit rates without checks and keep real zero counts", () => {
  const base: ProfileAnalytics = { known: true, reason: null, runs: 2, camera_verified_steps: 0, mistakes_caught: 0 };
  assert.deepEqual(activityDetails(base).map((detail) => detail.text), [
    "0 steps verified by camera",
    "0 mistakes caught before moving on",
  ]);
  const checked = { ...base, checks: 8, check_pass_rate: 0.75, camera_sources: ["phone", "glasses"] };
  const details = activityDetails(checked).map((detail) => detail.text);
  assert.ok(details.includes("75% of 8 camera checks passed"));
  assert.ok(details.includes("Practiced with a phone and Meta glasses"));
});

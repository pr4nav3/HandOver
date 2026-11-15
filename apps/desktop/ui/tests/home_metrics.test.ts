import assert from "node:assert/strict";
import test from "node:test";

import type { ProfileAnalytics } from "../src/api.ts";
import { homeMetrics } from "../src/home_metrics.ts";
import type { LocalProgress } from "../src/state.ts";

test("home analytics uses only real signed-in aggregates", () => {
  const analytics: ProfileAnalytics = {
    known: true,
    reason: null,
    runs: 5,
    completed_runs: 3,
    minutes_practiced: 42,
    camera_verified_steps: 11,
  };
  assert.deepEqual(homeMetrics(analytics, {}), [
    { value: 3, label: "Completed runs" },
    { value: "42m", label: "Practiced" },
    { value: 11, label: "Camera verified" },
  ]);
});

test("home analytics falls back to this device without inventing data", () => {
  const progress: Record<string, LocalProgress> = {
    done: { id: "done", title: "Done", step: 4, total: 4, done: true, updated: 1, runs: 2, how: ["camera", "hand", "camera"] },
    active: { id: "active", title: "Active", step: 1, total: 4, done: false, updated: 2, runs: 0, how: ["camera"] },
  };
  assert.deepEqual(homeMetrics(undefined, progress), [
    { value: 2, label: "Completed runs" },
    { value: 1, label: "In progress" },
    { value: 3, label: "Camera verified" },
  ]);
});

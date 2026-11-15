import assert from "node:assert/strict";
import test from "node:test";

import type { HubState, Step } from "../src/api.ts";
import { learnFeedback } from "../src/learn_feedback.ts";

const step: Step = {
  n: 1, title: "Fold", start: "0", end: "1", clip: "clip.mp4", captions: "clip.vtt",
  ref_frame: "done.jpg", check_type: "camera", check_question: "Done?", common_mistake: "",
};

function state(phase = "watching"): HubState {
  return {
    lesson_id: "lesson", rev: 1, step: 0, total: 3, status: "watching", last_check: null,
    camera_connected: true, check_offline: false, check_offline_reason: null, position: 0,
    offline_label: null, check_reason: null, observation: { phase, frame_age_ms: 82, camera_fps: 14.8 },
  };
}

test("live phases say what is happening and what to do next", () => {
  assert.deepEqual(["moving", "settling", "checking"].map((phase) => learnFeedback(state(phase), step).title),
    ["Keep going", "Hold it there", "Checking this step"]);
  assert.equal(learnFeedback(state("settling"), step).metric, "15 fps · Live");
});

test("held and verified states take precedence over frame phases", () => {
  const held = state("verified");
  held.held = true;
  assert.equal(learnFeedback(held, step).phase, "held");
  held.held = false;
  assert.equal(learnFeedback(held, step).phase, "verified");
});

test("no camera and manual steps have direct next actions", () => {
  const disconnected = state();
  disconnected.camera_connected = false;
  assert.match(learnFeedback(disconnected, step).action, /phone, computer, or Meta glasses/);
  const manual = learnFeedback(state(), { ...step, check_type: "manual" });
  assert.match(manual.action, /use Next/);
  assert.doesNotMatch(`${manual.title} ${manual.action}`, /paper|fold/i);
});

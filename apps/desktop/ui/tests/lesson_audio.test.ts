import assert from "node:assert/strict";
import test from "node:test";

import { replaceLessonPlayback, stopLessonPlayback, type LessonMedia } from "../src/lesson_audio.ts";

test("closing Learn hard-stops speech and detaches tutorial media", () => {
  const calls: string[] = [];
  const media: LessonMedia = {
    src: "hub://lesson/step-1.mp4",
    currentTime: 42,
    pause: () => calls.push("pause"),
    removeAttribute: (name) => calls.push(`remove:${name}`),
    load: () => calls.push("load"),
  };

  stopLessonPlayback(media, { cancel: () => calls.push("speech") });

  assert.equal(media.currentTime, 0);
  assert.deepEqual(calls, ["speech", "pause", "remove:src", "load"]);
});

test("next step detaches old audio before assigning and loading the new clip", () => {
  const calls: string[] = [];
  let source = "step-1.mp4";
  const media: LessonMedia = {
    get src() {
      return source;
    },
    set src(value: string) {
      source = value;
      calls.push(`src:${value}`);
    },
    currentTime: 9,
    pause: () => calls.push("pause"),
    removeAttribute: (name) => {
      calls.push(`remove:${name}`);
      if (name === "src") source = "";
    },
    load: () => calls.push("load"),
  };

  replaceLessonPlayback(media, "step-2.mp4", { cancel: () => calls.push("speech") });

  assert.equal(media.currentTime, 0);
  assert.equal(source, "step-2.mp4");
  assert.deepEqual(calls, ["speech", "pause", "remove:src", "load", "src:step-2.mp4", "load"]);
});

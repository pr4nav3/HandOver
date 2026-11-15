import assert from "node:assert/strict";
import test from "node:test";

import { userFacingLessons } from "../src/lesson_visibility.ts";

test("built-in fixtures never appear in user-facing lesson lists", () => {
  const lessons = [
    { id: "demo-v1" },
    { id: "fortune-teller-v1" },
    { id: "synthetic-fortune-teller-v1" },
    { id: "fortune-teller-v2" },
    { id: "front-wheel-v1" },
  ];
  assert.deepEqual(userFacingLessons(lessons).map((lesson) => lesson.id), ["fortune-teller-v2", "front-wheel-v1"]);
});

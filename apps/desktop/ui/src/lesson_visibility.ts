/** Built-in fixtures used by automated checks, never shown as real lessons. */
export const PLACEHOLDER_LESSON_IDS = new Set([
  "demo-v1",
  "fortune-teller-v1",
  "synthetic-fortune-teller-v1",
]);

export const userFacingLessons = <T extends { id: string }>(lessons: T[]): T[] =>
  lessons.filter((lesson) => !PLACEHOLDER_LESSON_IDS.has(lesson.id));

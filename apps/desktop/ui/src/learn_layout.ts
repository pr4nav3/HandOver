// Persisted, bounded layout for the live Learn workspace. Keeping the arithmetic here makes
// pointer and keyboard resizing use exactly the same rules and keeps corrupted local storage
// from producing an unusable split.

export interface LearnLayout {
  /** Width of the learner camera, regardless of which side it is on. */
  cameraPercent: number;
  /** When true, the expert tutorial is shown before the learner camera. */
  tutorialFirst: boolean;
}

export const LEARN_LAYOUT_KEY = "handover.learnLayout.v1";
export const DEFAULT_LEARN_LAYOUT: Readonly<LearnLayout> = { cameraPercent: 38, tutorialFirst: false };
export const MIN_CAMERA_PERCENT = 24;
export const MAX_CAMERA_PERCENT = 62;

const finite = (value: unknown, fallback: number) => {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
};

export const clampCameraPercent = (value: unknown): number =>
  Math.round(Math.min(MAX_CAMERA_PERCENT, Math.max(MIN_CAMERA_PERCENT, finite(value, DEFAULT_LEARN_LAYOUT.cameraPercent))) * 10) / 10;

export function sanitizeLearnLayout(value: unknown): LearnLayout {
  const v = value && typeof value === "object" ? (value as Partial<LearnLayout>) : {};
  return {
    cameraPercent: clampCameraPercent(v.cameraPercent),
    tutorialFirst: v.tutorialFirst === true,
  };
}

/** Percentage occupied by the visually left panel. */
export const leftPercent = (layout: LearnLayout): number =>
  layout.tutorialFirst ? 100 - layout.cameraPercent : layout.cameraPercent;

/** Converts a dragged left-panel width back to the camera's width. */
export const layoutFromLeftPercent = (left: number, tutorialFirst: boolean): LearnLayout =>
  sanitizeLearnLayout({ cameraPercent: tutorialFirst ? 100 - left : left, tutorialFirst });

export function readLearnLayout(storage: Pick<Storage, "getItem"> = localStorage): LearnLayout {
  try {
    return sanitizeLearnLayout(JSON.parse(storage.getItem(LEARN_LAYOUT_KEY) ?? "null"));
  } catch {
    return { ...DEFAULT_LEARN_LAYOUT };
  }
}

export function writeLearnLayout(layout: LearnLayout, storage: Pick<Storage, "setItem"> = localStorage) {
  storage.setItem(LEARN_LAYOUT_KEY, JSON.stringify(sanitizeLearnLayout(layout)));
}

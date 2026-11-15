import type { ProfileAnalytics } from "./api";

export const practiceTime = (minutes: number | undefined): string => {
  if (minutes === undefined || !Number.isFinite(minutes)) return "";
  const rounded = Math.max(0, Math.round(minutes));
  if (rounded < 60) return `${rounded}m`;
  const hours = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
};

export const percent = (rate: number | null | undefined): string =>
  rate === null || rate === undefined || !Number.isFinite(rate) ? "" : `${Math.round(Math.max(0, Math.min(1, rate)) * 100)}%`;

export const cameraSourceName = (source: string): string => {
  switch (source.toLowerCase()) {
    case "glasses":
      return "Meta glasses";
    case "phone":
    case "ios":
    case "android":
      return "a phone";
    case "desktop":
    case "browser":
    case "webcam":
      return "a computer camera";
    default:
      return "a camera";
  }
};

export interface ActivityDetail {
  kind: "camera" | "checks" | "mistakes" | "replays" | "sources";
  text: string;
}

/** Human-facing details only when the aggregate has a real denominator/value. */
export function activityDetails(value: ProfileAnalytics): ActivityDetail[] {
  const out: ActivityDetail[] = [];
  if (value.camera_verified_steps !== undefined)
    out.push({ kind: "camera", text: `${value.camera_verified_steps} step${value.camera_verified_steps === 1 ? "" : "s"} verified by camera` });
  if (value.checks && value.check_pass_rate !== null && value.check_pass_rate !== undefined)
    out.push({ kind: "checks", text: `${percent(value.check_pass_rate)} of ${value.checks} camera checks passed` });
  if (value.mistakes_caught !== undefined)
    out.push({ kind: "mistakes", text: `${value.mistakes_caught} mistake${value.mistakes_caught === 1 ? "" : "s"} caught before moving on` });
  if (value.replays)
    out.push({ kind: "replays", text: `${value.replays} replay${value.replays === 1 ? "" : "s"} used to practice again` });
  if (value.camera_sources?.length)
    out.push({ kind: "sources", text: `Practiced with ${value.camera_sources.map(cameraSourceName).join(" and ")}` });
  return out;
}

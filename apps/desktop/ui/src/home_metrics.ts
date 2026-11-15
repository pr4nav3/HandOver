import type { ProfileAnalytics } from "./api";
import type { LocalProgress } from "./state";

export interface HomeMetric {
  value: string | number;
  label: string;
}

const compactMinutes = (minutes: number): string => {
  const rounded = Math.max(0, Math.round(minutes));
  if (rounded < 60) return `${rounded}m`;
  const hours = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
};

/** Three quiet, denominator-safe facts for Home. Nothing is estimated. */
export function homeMetrics(
  analytics: ProfileAnalytics | null | undefined,
  progress: Record<string, LocalProgress>,
): HomeMetric[] {
  if (analytics?.known) {
    const metrics: HomeMetric[] = [];
    if (analytics.completed_runs !== undefined)
      metrics.push({ value: analytics.completed_runs, label: analytics.completed_runs === 1 ? "Completed run" : "Completed runs" });
    else metrics.push({ value: analytics.runs, label: analytics.runs === 1 ? "Run" : "Runs" });
    if (analytics.minutes_practiced !== undefined)
      metrics.push({ value: compactMinutes(analytics.minutes_practiced), label: "Practiced" });
    if (analytics.camera_verified_steps !== undefined)
      metrics.push({ value: analytics.camera_verified_steps, label: "Camera verified" });
    return metrics.slice(0, 3);
  }

  const values = Object.values(progress);
  const completed = values.reduce((sum, item) => sum + (item.done ? item.runs : 0), 0);
  const active = values.filter((item) => !item.done && item.step > 0).length;
  const camera = values.reduce(
    (sum, item) => sum + (item.how?.filter((method) => method === "camera").length ?? 0),
    0,
  );
  return [
    { value: completed, label: completed === 1 ? "Completed run" : "Completed runs" },
    { value: active, label: "In progress" },
    { value: camera, label: "Camera verified" },
  ];
}

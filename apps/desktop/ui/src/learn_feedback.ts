import type { HubState, Step } from "./api";

export type LearnFeedbackTone = "idle" | "active" | "good" | "caution";

export interface LearnFeedback {
  phase: string;
  label: string;
  title: string;
  action: string;
  tone: LearnFeedbackTone;
  metric: string;
}

function metric(state: HubState): string {
  const fps = state.observation?.camera_fps;
  const age = state.observation?.frame_age_ms;
  const parts: string[] = [];
  if (typeof fps === "number" && Number.isFinite(fps) && fps > 0) parts.push(`${fps < 10 ? fps.toFixed(1) : Math.round(fps)} fps`);
  if (typeof age === "number" && Number.isFinite(age) && age >= 0) {
    parts.push(age < 1_000 ? "Live" : `${Math.max(1, Math.round(age / 1_000))} s behind`);
  }
  return parts.join(" · ");
}

const offlineAction = (state: HubState) => {
  switch (state.check_offline_reason) {
    case "no_key": return "Camera checks are unavailable. Complete the fold, then use Next.";
    case "rate_limited": return "Checks will resume shortly. You can use Next in the meantime.";
    case "errors": return "Checks are reconnecting. You can keep going with Next.";
    case "budget": return "Camera checks are off. Complete the fold, then use Next.";
    default: return state.offline_label || "Complete the fold, then use Next.";
  }
};

/** Calm, action-first copy for the large live feedback card. */
export function learnFeedback(state: HubState | null, step: Step | null, flashVerified = false): LearnFeedback {
  const liveMetric = state ? metric(state) : "";
  const result = (phase: string, label: string, title: string, action: string, tone: LearnFeedbackTone): LearnFeedback =>
    ({ phase, label, title, action, tone, metric: liveMetric });

  if (!state || !step) return result("idle", "Getting ready", "Loading this step", "The tutorial will begin in a moment.", "idle");
  if (state.status === "done") return result("done", "Complete", "Lesson finished", "Your progress has been saved.", "good");
  if (state.held) return result("held", "Step held", "Take your time", "Feedback stays live. Release Hold when you want automatic advance.", "caution");
  if (flashVerified || state.status === "verified" || state.observation?.phase === "verified")
    return result("verified", "Verified", "That fold is right", "The next step is coming up.", "good");
  if (state.status === "manual" || step.check_type === "manual")
    return result("manual", "You decide", "Match the finished view", "When your paper matches the reference, use Next.", "idle");
  if (state.check_offline)
    return result("offline", "Checks off", "Keep following the tutorial", offlineAction(state), "caution");
  if (!state.camera_connected || state.observation?.phase === "waiting_camera")
    return result("waiting_camera", "No camera", "Connect a camera", "Use your phone, computer, or Meta glasses to get live feedback.", "caution");

  switch (state.observation?.phase) {
    case "waiting_frame":
      return result("waiting_frame", "Finding the paper", "Bring the fold into view", "Keep your hands and the whole paper inside the camera frame.", "active");
    case "moving":
      return result("moving", "Tracking", "Keep folding", "Finish the motion, then hold the paper still.", "active");
    case "settling":
      return result("settling", "Almost ready", "Hold it there", "Keep the finished fold still for a moment.", "active");
    case "checking":
      return result("checking", "Checking", "Checking this fold", "Keep the finished fold clearly in view.", "active");
    case "watching":
    case "idle":
    default:
      if (state.status === "checking")
        return result("checking", "Checking", "Checking this fold", "Keep the finished fold clearly in view.", "active");
      return result("watching", "Watching", "Complete this step", "Follow the tutorial, then hold your result in view.", "idle");
  }
}

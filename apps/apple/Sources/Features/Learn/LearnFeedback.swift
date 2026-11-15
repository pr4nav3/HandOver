import SwiftUI

/// Action-first live feedback beside the tutorial. The hub phase is intentionally translated into plain
/// language so learners always know both what HandOver is doing and what they should do next.
struct LearnFeedback: Equatable, Sendable {
    var phase: String
    var status: LearnStatus
    var title: String
    var action: String
    var metric: String?

    var tone: HOTone {
        switch phase {
        case "verified", "done": .good
        case "moving", "settling", "checking", "waiting_frame": .accent
        case "held", "offline", "waiting_camera": .caution
        default: status.tone
        }
    }

    static func resolve(state: HubState, step: Step?, status: LearnStatus) -> LearnFeedback {
        let metric = liveMetric(state.observation)
        func make(_ phase: String, _ status: LearnStatus, _ title: String, _ action: String) -> LearnFeedback {
            LearnFeedback(phase: phase, status: status, title: title, action: action, metric: metric)
        }

        if state.isDone { return make("done", .done, "Lesson finished", "Your progress has been saved.") }
        if state.held { return make("held", status, "Take your time", "Feedback stays live. Release Hold when you want automatic advance.") }
        if status == .verified || state.observation?.phase == "verified" {
            return make("verified", .verified, "That fold is right", "The next step is coming up.")
        }
        if status == .manual {
            return make("manual", status, "Match the finished view", "When your paper matches the reference, tap Next.")
        }
        if status == .checksOff {
            return make("offline", status, "Keep following the tutorial", LearnStatus.offlineMeta(state.checkOfflineReason))
        }
        if status == .simulated {
            return make("simulated", status, "Complete this step", "This test run moves on after a short timer.")
        }
        if status == .noCamera || state.observation?.phase == "waiting_camera" {
            return make("waiting_camera", .noCamera, "Connect a camera", "Use your phone, computer, or Meta glasses for live feedback.")
        }

        switch state.observation?.phase {
        case "waiting_frame":
            return make("waiting_frame", .watching, "Bring the fold into view", "Keep your hands and the whole paper inside the camera frame.")
        case "moving":
            return make("moving", .watching, "Keep folding", "Finish the motion, then hold the paper still.")
        case "settling":
            return make("settling", .checking, "Hold it there", "Keep the finished fold still for a moment.")
        case "checking":
            return make("checking", .checking, "Checking this fold", "Keep the finished fold clearly in view.")
        default:
            if status == .checking {
                return make("checking", status, "Checking this fold", "Keep the finished fold clearly in view.")
            }
            return make("watching", .watching, "Complete this step", "Follow the tutorial, then hold your result in view.")
        }
    }

    static func liveMetric(_ observation: HubState.Observation?) -> String? {
        guard let observation else { return nil }
        var parts: [String] = []
        if let fps = observation.cameraFPS, fps.isFinite, fps > 0 {
            parts.append(fps < 10 ? String(format: "%.1f fps", fps) : "\(Int(fps.rounded())) fps")
        }
        if let age = observation.frameAgeMs, age >= 0 {
            parts.append(age < 1_000 ? "Live" : "\(max(1, Int((Double(age) / 1_000).rounded()))) s behind")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

struct LearnFeedbackCard: View {
    var feedback: LearnFeedback
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.xs) {
            HStack(spacing: HOSpace.s) {
                StatusBadge(status: feedback.status)
                    .accessibilityHidden(true)
                Spacer(minLength: 0)
                if let metric = feedback.metric {
                    Text(metric)
                        .font(theme.fonts.caption.monospacedDigit())
                        .foregroundStyle(theme.colors.ink2)
                        .lineLimit(1)
                }
            }
            Text(feedback.title)
                .font(theme.fonts.title)
                .foregroundStyle(theme.colors.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(feedback.action)
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(HOSpace.m)
        .background(feedback.tone.wash(theme.colors), in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
            .strokeBorder(feedback.tone.color(theme.colors).opacity(0.24), lineWidth: HOLine.width))
        .contentTransition(.opacity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(feedback.status.label). \(feedback.title). \(feedback.action)")
        .accessibilityAddTraits(.updatesFrequently)
    }
}

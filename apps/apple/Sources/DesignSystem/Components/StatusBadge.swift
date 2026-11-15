import SwiftUI

/// What the Learn status badge says (DESIGN.md 3.1, SCREENS.md 7.8).
enum LearnStatus: String, CaseIterable, Hashable, Sendable {
    case watching, checking, verified, manual, done, checksOff, simulated, noCamera

    /// The badge for a state, by the precedence in DESIGN.md 3.1: done, then verified (also while the client
    /// holds its flash after a camera advance), then manual, then checks off, then simulated, then no camera,
    /// then checking, then watching. Simulated shows only when the hub says `check_mode` is mock; it is never
    /// guessed.
    static func resolve(_ state: HubState, step: Step?, flashVerified: Bool = false) -> LearnStatus {
        if state.isDone { return .done }
        if state.status == .verified || flashVerified { return .verified }
        if state.status == .manual || step?.isManual == true { return .manual }
        if state.checkOffline { return .checksOff }
        if state.checkMode == .mock { return .simulated }
        if !state.cameraConnected { return .noCamera }
        if state.status == .checking { return .checking }
        return .watching
    }

    var label: String {
        switch self {
        case .watching: "Watching"
        case .checking: "Checking"
        case .verified: "Verified"
        case .manual: "Tap Next when done"
        case .done: "Done"
        case .checksOff: "Checks off, use Next"
        case .simulated: "Simulated checks"
        case .noCamera: "No camera"
        }
    }

    /// Shown instead of the dot at accessibility text sizes.
    var symbol: String {
        switch self {
        case .watching: "eye"
        case .checking: "viewfinder"
        case .verified: "checkmark.circle.fill"
        case .manual: "hand.tap"
        case .done: "checkmark.seal.fill"
        case .checksOff: "exclamationmark.triangle"
        case .simulated: "testtube.2"
        case .noCamera: "video.slash"
        }
    }

    var tone: HOTone {
        switch self {
        case .watching, .noCamera: .idle
        case .checking: .accent
        case .verified, .done: .good
        case .manual: .neutral
        case .checksOff, .simulated: .caution
        }
    }

    var voiceOver: String {
        switch self {
        case .watching: "Status: watching for this step"
        case .checking: "Status: checking"
        case .verified: "Status: verified"
        case .manual: "Status: manual step. Tap Next when done"
        case .done: "Status: lesson done"
        case .checksOff: "Status: checks off. Use Next"
        case .simulated: "Status: simulated checks, not real"
        case .noCamera: "Status: no camera connected"
        }
    }

    /// The `footnote` lines beside the badge (SCREENS.md 7.8): latency or why checks are off, then the check
    /// reason only when the newest check said no with confidence 0.7 or more.
    static func meta(_ status: LearnStatus, state: HubState) -> [String] {
        switch status {
        case .watching, .checking:
            guard state.cameraConnected, let check = state.lastCheck, check.latencyMs > 0 else { return [] }
            var lines = ["Last check \(Self.seconds(check.latencyMs))"]
            if check.done == .no, let reason = check.shownReason, !reason.isEmpty { lines.append(reason) }
            return lines
        case .checksOff: return [offlineMeta(state.checkOfflineReason)]
        case .simulated: return ["Test mode. Steps pass on a timer."]
        case .noCamera: return ["Connect a camera to check steps."]
        case .verified, .manual, .done: return []
        }
    }

    static func offlineMeta(_ reason: HubState.OfflineReason?) -> String {
        switch reason {
        case .noKey?: "No check key on the hub."
        case .rateLimited?: "Too many checks. Trying again soon."
        case .errors?: "Checks failed. Trying again soon."
        case .budget?: "Check spending limit reached."
        default: "Checks are off. Use Next to move on."
        }
    }

    /// "0.9 s" from milliseconds, one decimal.
    static func seconds(_ ms: Int) -> String {
        let tenths = Int((Double(ms) / 100).rounded())
        return "\(tenths / 10).\(tenths % 10) s"
    }
}

/// A capsule: dot, then label, in the tone's wash (DESIGN.md 3.1). Over video it becomes a glass capsule with
/// white text and the dot in the tone color. At accessibility sizes the symbol replaces the dot.
struct StatusBadge: View {
    var status: LearnStatus
    var overVideo = false
    @Environment(\.theme) private var theme
    @Environment(\.dynamicTypeSize) private var typeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let tone = status.tone
        let content = HStack(spacing: 6) {
            if typeSize.isAccessibilitySize || status == .verified {
                Image(systemName: status.symbol)
                    .symbolEffect(.bounce, options: .nonRepeating, value: reduceMotion ? false : status == .verified)
                    .foregroundStyle(overVideo ? tone.onVideo : tone.text(theme.colors))
                    .accessibilityHidden(true)
            } else {
                StatusDot(color: overVideo ? tone.onVideo : tone.color(theme.colors))
            }
            Text(status.label)
                .contentTransition(.opacity)
                .foregroundStyle(overVideo ? Color.white : tone.text(theme.colors))
                .lineLimit(2)
        }
        .font(theme.fonts.badge)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .frame(minHeight: HOSize.badge)

        Group {
            if overVideo {
                content.hoGlassCapsule()
            } else {
                content.background(tone.wash(theme.colors), in: Capsule())
            }
        }
        .hoAnimation(HOMotion.snappy, value: status)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(status.voiceOver)
    }
}

#Preview("Every badge") {
    VStack(alignment: .leading, spacing: 10) {
        ForEach(LearnStatus.allCases, id: \.self) { StatusBadge(status: $0) }
    }
    .padding()
    .hoPaperBackground()
    .handOverTheme(.system, dark: false)
}

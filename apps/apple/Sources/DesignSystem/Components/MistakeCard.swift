import SwiftUI

/// The three mistakes the hub can raise. `behind` and `ahead` are CONTRACT.md section 7; `live` comes from the
/// real-time understanding work (server/understand.py: a known mistake seen while the step is under way).
enum MistakeKind: Hashable, Sendable {
    /// The live frame still looks like an earlier step. `looksLike` is 0-based.
    case behind(looksLike: Int)
    /// The hub saw the next step done and has already advanced.
    case ahead
    /// A known mistake is happening right now on this step.
    case live

    /// Maps the wire message. A `behind` whose `looks_like` is the current step cannot be a real behind (that
    /// would mean it looks like itself), so it is read as a live mistake: that is how a `kind: "live"` message
    /// arrives while the Core enum knows only behind and ahead.
    init(_ m: MistakeMessage) {
        switch m.kind {
        case .ahead: self = .ahead
        case .behind: self = m.looksLike < m.step ? .behind(looksLike: m.looksLike) : .live
        }
    }

    var isBehind: Bool {
        if case .behind = self { return true }
        return false
    }
}

/// Shown when the hub reports a mistake for the current step (DESIGN.md 3.2, SCREENS.md 7.9). Caution wash over
/// `raised`, a caution hairline at 40%, the triangle, the hub's message verbatim, then quiet buttons.
struct MistakeCard: View {
    var kind: MistakeKind
    var message: String
    /// iPhone uses the control radius; iPad and Mac the card radius.
    var compact = true
    /// iPhone landscape floats it over the clip as a dark glass panel.
    var overVideo = false
    var onShowStep: (Int) -> Void = { _ in }
    var onDismiss: () -> Void = {}
    @Environment(\.theme) private var theme

    /// The message, with the contract's fallbacks when the hub sent none.
    var shownMessage: String {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        switch kind {
        case .behind(let looksLike): return "This still looks like step \(looksLike + 1)."
        case .ahead: return "You're ahead."
        case .live: return "Check your work against the clip."
        }
    }

    var body: some View {
        let radius = compact ? HORadius.control : HORadius.card
        let ink = overVideo ? Color.white : theme.colors.ink
        let caution = overVideo ? HOTone.caution.onVideo : theme.colors.caution
        let message = HStack(alignment: .firstTextBaseline, spacing: HOSpace.s) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(caution)
                .accessibilityHidden(true)
            Text(shownMessage)
                .font(theme.fonts.headline)
                .foregroundStyle(ink)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        let buttons = HStack(spacing: HOSpace.s) {
            switch kind {
            case .behind(let looksLike):
                Button("Show Step \(looksLike + 1)") { Haptics.tap(); onShowStep(looksLike) }
                Button("I'm Fine") { Haptics.tap(); onDismiss() }
            case .ahead, .live:
                Button("OK") { Haptics.tap(); onDismiss() }
            }
        }
        .buttonStyle(HOButtonStyle(.quiet, size: .small, onVideo: overVideo))
        // iPad and Mac keep the buttons on the message's line when it fits; iPhone stacks them under it.
        let content = Group {
            if compact {
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    message.frame(maxWidth: .infinity, alignment: .leading)
                    HStack { Spacer(minLength: 0); buttons }
                }
            } else {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: HOSpace.m) { message; Spacer(minLength: HOSpace.m); buttons }
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        message.frame(maxWidth: .infinity, alignment: .leading)
                        HStack { Spacer(minLength: 0); buttons }
                    }
                }
            }
        }
        .padding(HOSpace.m)

        Group {
            if overVideo {
                content.hoGlassPanel(radius: radius)
            } else {
                let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
                content
                    .background(theme.colors.cautionWash, in: shape)
                    .background(theme.colors.raised, in: shape)
                    .overlay(shape.strokeBorder(theme.colors.caution.opacity(0.4), lineWidth: HOLine.width))
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Mistake. \(shownMessage)")
        .accessibilityAddTraits(.isStaticText)
    }
}

#Preview("Mistake cards") {
    VStack(spacing: 12) {
        MistakeCard(kind: .behind(looksLike: 2), message: "Flip it over first.")
        MistakeCard(kind: .ahead, message: "You're ahead.")
        MistakeCard(kind: .live, message: "Crease along the line, not past it.")
    }
    .padding()
    .hoPaperBackground()
    .handOverTheme(.system, dark: false)
}

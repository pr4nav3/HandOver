import SwiftUI

/// The lesson's steps with the learner's status (DESIGN.md 3.20): a header with a progress ring and "3 of 8
/// done", then one row per step with its thumbnail (frames/NN.jpg), number and title, expert time ("You" time
/// once done this run) and a status symbol. Tapping a row jumps there (`goto`); jumping forward past
/// unfinished steps asks first. Used in the Learn sidebar (iPad, Mac) and the Steps sheet (iPhone).
struct CourseView: View {
    var lesson: Lesson
    var statuses: [StepStatus]
    /// Seconds this run per step, when timed.
    var yourSeconds: [Int: Double] = [:]
    /// 0-based current step, nil when done or not started.
    var current: Int?
    /// Number, title and symbol only (the Mac sidebar).
    var compact = false
    var thumbnail: (Step) -> CGImage? = { _ in nil }
    var onGoto: (Int) -> Void
    @Environment(\.theme) private var theme
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var confirmSkip: Int?

    var doneCount: Int { statuses.filter(\.isDone).count }

    /// True when going to `index` would pass steps that are not done (SCREENS.md 6).
    static func needsSkipConfirm(to index: Int, current: Int?, statuses: [StepStatus]) -> Bool {
        guard let current, index > current else { return false }
        return (current..<index).contains { i in statuses.indices.contains(i) && !statuses[i].isDone }
    }

    var body: some View {
        HOScroll {
            VStack(alignment: .leading, spacing: 0) {
                header
                ForEach(Array(lesson.steps.enumerated()), id: \.offset) { i, step in
                    Button { tap(i) } label: { row(i, step) }
                        .buttonStyle(HORowButtonStyle())
                    if i < lesson.steps.count - 1 {
                        Rectangle().fill(theme.colors.line).frame(height: HOLine.width)
                            .padding(.leading, compact ? HOSpace.l : HOSpace.l + 20 + HOSpace.m)
                    }
                }
            }
        }
        .confirmationDialog(confirmSkip.map { "Skip to Step \($0 + 1)?" } ?? "",
                            isPresented: Binding(get: { confirmSkip != nil }, set: { if !$0 { confirmSkip = nil } }),
                            titleVisibility: .visible, presenting: confirmSkip) { index in
            Button("Skip") { onGoto(index) }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("Steps you skip are marked as skipped.")
        }
    }

    private func tap(_ i: Int) {
        guard i != current else { return }
        Haptics.tap()
        if Self.needsSkipConfirm(to: i, current: current, statuses: statuses) {
            confirmSkip = i
        } else {
            onGoto(i)
        }
    }

    private var header: some View {
        HStack(spacing: HOSpace.s) {
            Text("Steps")
                .font(theme.fonts.section)
                .foregroundStyle(theme.colors.ink2)
            Spacer()
            let total = max(lesson.steps.count, 1)
            ProgressRing(fraction: Double(doneCount) / Double(total), size: 20,
                         completed: doneCount == lesson.steps.count && !lesson.steps.isEmpty)
            Text("\(doneCount) of \(lesson.steps.count) done")
                .font(theme.fonts.footnote.monospacedDigit())
                .foregroundStyle(theme.colors.ink2)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.s)
        .accessibilityElement(children: .combine)
    }

    private func row(_ i: Int, _ step: Step) -> some View {
        let status = statuses.indices.contains(i) ? statuses[i] : .notStarted
        let isCurrent = i == current
        let expert: Double? = {
            guard let s = step.startSeconds, let e = step.endSeconds, e > s else { return nil }
            return e - s
        }()
        var meta: [String] = []
        if let expert { meta.append("Expert \(HOTime.clock(expert))") }
        if status.isDone, let yours = yourSeconds[i] { meta.append("You \(HOTime.clock(yours))") }
        let title = step.title.isEmpty ? "Step \(i + 1)" : step.title

        return HStack(alignment: .center, spacing: HOSpace.m) {
            Image(systemName: status.symbol)
                .font(.system(size: 20))
                .foregroundStyle(status.color(theme.colors))
                .frame(width: 20)
                .accessibilityHidden(true)
            if !compact && !(typeSize.isAccessibilitySize) {
                thumb(step)
            }
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                HStack(alignment: .firstTextBaseline, spacing: HOSpace.xs) {
                    Text("\(i + 1)")
                        .font(theme.fonts.bodyMedium.monospacedDigit())
                        .fontDesign(.rounded)
                        .foregroundStyle(isCurrent ? theme.colors.accentInk : theme.colors.ink2)
                    Text(title)
                        .font(theme.fonts.bodyMedium)
                        .foregroundStyle(isCurrent ? theme.colors.accentInk : theme.colors.ink)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                if !compact, !meta.isEmpty {
                    Text(meta.joined(separator: "   "))
                        .font(theme.fonts.callout.monospacedDigit())
                        .foregroundStyle(theme.colors.ink2)
                }
                if typeSize.isAccessibilitySize {
                    Text(status.word).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, compact ? HOSpace.s : HOSpace.m)
        .frame(minHeight: compact ? HOSize.touch : 64)
        .background(isCurrent ? theme.colors.accentSoft : Color.clear)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(i + 1). \(title)")
        .accessibilityValue(([status.word] + meta).joined(separator: ", "))
        .accessibilityAddTraits(isCurrent ? [.isButton, .isSelected] : .isButton)
    }

    private func thumb(_ step: Step) -> some View {
        ZStack {
            theme.colors.stage
            if let image = thumbnail(step) {
                Image(decorative: image, scale: 1).resizable().aspectRatio(contentMode: .fill)
            }
        }
        .frame(width: 72, height: 40)
        .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
    }
}

#Preview("Course") {
    let lesson = PreviewHub.fortuneTeller.lesson
    CourseView(lesson: lesson, statuses: [.doneByHand, .doneByCamera, .current, .notStarted, .notStarted],
               yourSeconds: [0: 6, 1: 11], current: 2, onGoto: { _ in })
        .hoPaperBackground()
        .handOverTheme(.system, dark: false)
}

import SwiftUI

/// The end of a lesson (SCREENS.md 8): the score ring, stats, best and weakest step, one tip, the per-step
/// breakdown, and Practice the Weakest Step and Start Over. The hub's score is used when it has one for this
/// run; otherwise every number comes from this device's record, and what cannot be computed says
/// "Not enough data". The summary is frozen at the moment the lesson finished.
struct DoneView: View {
    var summary: RunSummary
    var lessonId: String?
    /// The hub's run id, when known. Core does not receive one yet, so this is usually nil.
    var runId: String?
    var onGoto: (Int) -> Void
    var onStartOver: () -> Void
    var onLibrary: (() -> Void)?
    /// Previews and snapshots skip the network, the rating prompt and the ring animation.
    var isStill = false
    @Environment(AppModel.self) private var model
    @Environment(\.theme) private var theme
    @State private var hubScore: HubRunScore?
    @State private var showRating = false
    @State private var showParts = false
    @State private var practiceStep: Int?
    @State private var toast: ToastItem?

    private var canAct: Bool { model.connection.isConnected || isStill }

    /// The score and label to show: the hub's when present, else the local one.
    private var shownScore: Int? { hubScore?.score ?? summary.score }
    private var shownLabel: String? { hubScore?.score != nil ? hubScore?.label : nil }
    private var weakest: Int? {
        if let n = hubScore?.weakestStep?.n { return n - 1 }
        return summary.weakest
    }
    private var best: Int? {
        if let n = hubScore?.bestStep?.n, n - 1 != weakest { return n - 1 }
        return summary.best
    }
    private var tip: String { hubScore?.tip ?? summary.tip }

    var body: some View {
        GeometryReader { geo in
            let wide = geo.size.width >= 760
            HOScroll {
                if wide {
                    HStack(alignment: .top, spacing: HOSpace.xl) {
                        VStack(spacing: HOSpace.l) { summaryColumn }
                            .frame(width: 380)
                        breakdown.frame(maxWidth: .infinity)
                    }
                    .padding(HOSpace.xl)
                } else {
                    VStack(spacing: HOSpace.l) {
                        summaryColumn
                        breakdown
                    }
                    .padding(HOSpace.l)
                }
            }
        }
        .hoPaperBackground()
        .hoToast($toast)
        .task {
            guard !isStill else { return }
            Haptics.success()
            if let runId, let hub = model.hub {
                hubScore = await DoneAPI.score(hub: hub, runId: runId)
            }
        }
        .task {
            guard !isStill, let lessonId, !DoneAPI.ratingOffered(lessonId) else { return }
            try? await Task.sleep(for: .seconds(2))
            DoneAPI.markRatingOffered(lessonId)
            showRating = true
        }
        .sheet(isPresented: $showRating) {
            RatingSheet(lessonId: lessonId) { outcome in
                switch outcome {
                case .sent: toast = ToastItem(text: "Thanks. Rating sent.", symbol: "checkmark.circle.fill", tone: .good)
                case .needsSignIn: toast = ToastItem(text: "Sign in to rate this lesson.")
                case .unsupported: toast = ToastItem(text: "This hub does not take ratings yet.")
                case .failed: toast = ToastItem(text: "The rating did not send.", symbol: "exclamationmark.triangle",
                                                tone: .caution)
                }
            }
            .presentationDetents([.medium])
        }
        .sheet(isPresented: $showParts) {
            ScoreParts(parts: summary.scoreParts)
                .presentationDetents([.medium])
        }
        .confirmationDialog(practiceStep.map { "Practice Step \($0 + 1)" } ?? "",
                            isPresented: Binding(get: { practiceStep != nil }, set: { if !$0 { practiceStep = nil } }),
                            titleVisibility: .hidden, presenting: practiceStep) { step in
            Button("Practice Step \(step + 1)") { onGoto(step) }
            Button("Cancel", role: .cancel) {}
        }
    }

    // MARK: - Left column

    @ViewBuilder
    private var summaryColumn: some View {
        VStack(spacing: HOSpace.s) {
            Button { if !summary.scoreParts.isEmpty { showParts = true } } label: {
                ScoreRing(score: shownScore, label: shownLabel, animateIn: !isStill)
            }
            .buttonStyle(.plain)
            .disabled(summary.scoreParts.isEmpty || hubScore?.score != nil)
            .accessibilityHint(summary.scoreParts.isEmpty ? "" : "Shows how the score works")
            Text("Lesson complete")
                .hoFont(.display, theme)
                .foregroundStyle(theme.colors.ink)
                .padding(.top, HOSpace.s)
            Text(summary.lessonTitle)
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink2)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, HOSpace.l)

        stats
        bestAndWeakest
        tipCard
        buttons
    }

    private var stats: some View {
        VStack(spacing: HOSpace.m) {
            HStack(alignment: .top, spacing: HOSpace.s) {
                stat("Your time", summary.runSeconds.map { HOTime.clock($0) })
                stat("Expert", summary.expertSeconds.map { HOTime.clock($0) })
                stat("Checked by camera", "\(summary.checkedByCamera) of \(summary.cameraSteps)")
            }
            Rectangle().fill(theme.colors.line).frame(height: HOLine.width)
            HStack(alignment: .top, spacing: HOSpace.s) {
                stat("Marked done", "\(summary.markedDone)")
                stat("Mistakes caught", "\(summary.mistakes)")
                if summary.skipped > 0 {
                    stat("Skipped", "\(summary.skipped)")
                } else {
                    Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
                }
            }
        }
        .padding(HOSpace.l)
        .hoCard()
    }

    private func stat(_ label: String, _ value: String?) -> some View {
        VStack(spacing: HOSpace.xxs) {
            if let value {
                Text(value)
                    .font(theme.fonts.numeral)
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
            } else {
                Text("Not enough data")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
                    .frame(minHeight: 34)
            }
            Text(label)
                .font(theme.fonts.caption)
                .foregroundStyle(theme.colors.ink2)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label), \(value ?? "not enough data")")
    }

    @ViewBuilder
    private var bestAndWeakest: some View {
        if let weakest, summary.lines.indices.contains(weakest) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: HOSpace.m) { stepCards(weakest: weakest) }
                VStack(spacing: HOSpace.m) { stepCards(weakest: weakest) }
            }
        } else {
            HStack(spacing: HOSpace.s) {
                Image(systemName: "chart.bar").foregroundStyle(theme.colors.ink2).accessibilityHidden(true)
                Text("Not enough data to compare steps.")
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                Spacer(minLength: 0)
            }
            .padding(HOSpace.l)
            .hoCard()
        }
    }

    @ViewBuilder
    private func stepCards(weakest: Int) -> some View {
        if let best, summary.lines.indices.contains(best) {
            stepCard("Best step", symbol: "star", tone: .good, index: best, reason: summary.bestReason(best))
        }
        stepCard("Practice this", symbol: "arrow.counterclockwise", tone: .caution, index: weakest,
                 reason: summary.weakestReason(weakest))
    }

    private func stepCard(_ title: String, symbol: String, tone: HOTone, index: Int, reason: String) -> some View {
        let line = summary.lines[index]
        return VStack(alignment: .leading, spacing: HOSpace.xs) {
            Label(title, systemImage: symbol)
                .font(theme.fonts.section)
                .foregroundStyle(tone.text(theme.colors))
            Text("Step \(line.n). \(line.title)")
                .font(theme.fonts.headline)
                .foregroundStyle(theme.colors.ink)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Text(reason)
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(HOSpace.l)
        .hoCard()
        .accessibilityElement(children: .combine)
    }

    private var tipCard: some View {
        HStack(alignment: .firstTextBaseline, spacing: HOSpace.s) {
            Image(systemName: "lightbulb").foregroundStyle(theme.colors.accentInk).accessibilityHidden(true)
            Text(tip)
                .font(theme.fonts.body)
                .foregroundStyle(theme.colors.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(HOSpace.l)
        .hoCard()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Tip. \(tip)")
    }

    private var buttons: some View {
        VStack(spacing: HOSpace.s) {
            if let weakest {
                Button("Practice the Weakest Step") { onGoto(weakest) }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                Button("Start Over") { onStartOver() }
                    .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
            } else {
                Button("Start Over") { onStartOver() }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            }
            if let onLibrary {
                Button("Back to Library") { onLibrary() }
                    .buttonStyle(HOButtonStyle(.quiet))
            }
        }
        .disabled(!canAct)
    }

    // MARK: - Breakdown

    private var breakdown: some View {
        let longest = summary.lines.flatMap { [$0.yours ?? 0, $0.expert ?? 0] }.max() ?? 0
        return VStack(alignment: .leading, spacing: 0) {
            Text("Steps")
                .font(theme.fonts.section)
                .foregroundStyle(theme.colors.ink2)
                .padding(.horizontal, HOSpace.l)
                .padding(.vertical, HOSpace.s)
            ForEach(summary.lines) { line in
                Button { Haptics.tap(); practiceStep = line.index } label: {
                    breakdownRow(line, longest: longest)
                }
                .buttonStyle(HORowButtonStyle())
                .disabled(!canAct)
                if line.index < summary.lines.count - 1 {
                    Rectangle().fill(theme.colors.line).frame(height: HOLine.width).padding(.leading, HOSpace.l)
                }
            }
        }
        .padding(.bottom, HOSpace.xs)
        .hoCard()
    }

    private func breakdownRow(_ line: RunSummary.Line, longest: Double) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            HStack(alignment: .firstTextBaseline, spacing: HOSpace.s) {
                Text("\(line.n)")
                    .font(theme.fonts.bodyMedium.monospacedDigit())
                    .fontDesign(.rounded)
                    .foregroundStyle(theme.colors.ink2)
                Text(line.title)
                    .font(theme.fonts.bodyMedium)
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(1)
                Spacer(minLength: HOSpace.s)
                if line.mistakes > 0 {
                    Text("\(line.mistakes) mistake\(line.mistakes == 1 ? "" : "s")")
                        .font(theme.fonts.footnote)
                        .foregroundStyle(theme.colors.caution)
                }
            }
            TimeBar(yours: line.yours, expert: line.expert, longest: longest)
            Label(line.how == .current ? StepStatus.notStarted.word : line.how.word,
                  systemImage: line.how == .current ? StepStatus.notStarted.symbol : line.how.symbol)
                .font(theme.fonts.footnote)
                .foregroundStyle(line.how.color(theme.colors))
                .labelStyle(.titleAndIcon)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(line.n). \(TimeBar.spoken(yours: line.yours, expert: line.expert)) \(line.how.word). "
                            + (line.mistakes == 0 ? "No mistakes." : "\(line.mistakes) mistake\(line.mistakes == 1 ? "" : "s")."))
    }
}

/// "How the score works": the three parts as plain sentences (SCREENS.md 20.2).
private struct ScoreParts: View {
    var parts: [String]
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: HOSpace.m) {
                ForEach(parts, id: \.self) { part in
                    Text(part).font(theme.fonts.body).foregroundStyle(theme.colors.ink)
                }
                Text("Half the score is camera checks, three tenths is pace and one fifth is avoiding mistakes. With no camera steps to count, pace and mistakes share it.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                Spacer()
            }
            .padding(HOSpace.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .navigationTitle("How the score works")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }
}

/// "Rate this lesson" (SCREENS.md 9): offered once per lesson, skippable.
struct RatingSheet: View {
    var lessonId: String?
    var onResult: (DoneAPI.RatingOutcome) -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var stars = 0
    @State private var comment = ""
    @State private var sending = false

    var body: some View {
        VStack(spacing: HOSpace.l) {
            Text("Rate this lesson").hoFont(.title, theme).foregroundStyle(theme.colors.ink)
            StarRating(rating: $stars)
            TextField("What helped or got in the way? (optional)", text: $comment, axis: .vertical)
                .lineLimit(2...4)
                .font(theme.fonts.body)
                .padding(HOSpace.m)
                .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
                    .strokeBorder(theme.colors.lineStrong, lineWidth: HOLine.width))
                .onChange(of: comment) { _, new in if new.count > 500 { comment = String(new.prefix(500)) } }
            VStack(spacing: HOSpace.s) {
                Button("Send") { send() }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .disabled(stars == 0 || sending)
                Button("Not Now") { dismiss() }
                    .buttonStyle(HOButtonStyle(.quiet))
            }
            Text("The lesson's owner sees your rating and comment with your name.")
                .font(theme.fonts.footnote)
                .foregroundStyle(theme.colors.ink2)
                .multilineTextAlignment(.center)
        }
        .padding(HOSpace.xl)
        .hoPaperBackground()
    }

    private func send() {
        guard let hub = model.hub, let lessonId else {
            onResult(.failed)
            dismiss()
            return
        }
        sending = true
        Task {
            let outcome = await DoneAPI.rate(hub: hub, lessonId: lessonId, stars: stars, comment: comment)
            if outcome == .sent { Haptics.success() }
            onResult(outcome)
            dismiss()
        }
    }
}

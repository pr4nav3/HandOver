import SwiftUI

/// The Make course sheet (SCREENS.md 11 and 13): title, then upload and the hub's stages, then the finished
/// lesson as a timeline. Closing it does not stop the hub.
struct MakeCourseView: View {
    @Bindable var flow: UploadFlow
    var hub: HubURL?
    var onReview: (String) -> Void = { _ in }
    var onTryAsLearner: (String) -> Void = { _ in }
    var onClose: () -> Void = {}
    @Environment(\.theme) private var theme
    @FocusState private var titleFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                switch flow.phase {
                case .idle, .titling: titling
                case .uploading, .processing, .failed: progress
                case .finished: finished
                }
            }
            .padding(HOSpace.xl)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .background(theme.colors.paper)
        .navigationTitle(navigationTitle)
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                if flow.phase == .titling || flow.phase == .idle {
                    Button("Cancel") {
                        flow.reset()
                        onClose()
                    }
                } else if flow.phase != .uploading {
                    Button("Done") {
                        if flow.phase == .finished || flow.phase == .failed { flow.reset() }
                        onClose()
                    }
                }
            }
        }
        .onChange(of: flow.finishCount) { Haptics.success() }
        .onChange(of: flow.failCount) { Haptics.error() }
        .interactiveDismissDisabled(flow.phase == .uploading)
    }

    private var navigationTitle: String {
        switch flow.phase {
        case .idle, .titling: "Make Course"
        case .finished: "Ready"
        default: flow.title
        }
    }

    // MARK: - Title

    private var titling: some View {
        VStack(alignment: .leading, spacing: HOSpace.l) {
            if let video = flow.video {
                HStack(spacing: HOSpace.m) {
                    Image(systemName: "film")
                        .font(.title3)
                        .foregroundStyle(theme.colors.ink2)
                        .frame(width: HOSize.tile, height: HOSize.tile)
                        .background(theme.colors.well, in: RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(video.name).font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink).lineLimit(1)
                        if let size = video.sizeText {
                            Text(size).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                        }
                    }
                }
                .raisedCard(radius: HORadius.control, padding: HOSpace.m)
            }
            VStack(alignment: .leading, spacing: HOSpace.s) {
                Text("Title").sectionHeaderStyle(theme)
                TextField("Title", text: $flow.title, prompt: Text("Fold a fortune teller"))
                    .textFieldStyle(.plain)
                    .font(theme.fonts.body)
                    .padding(.horizontal, HOSpace.m)
                    .frame(minHeight: HOSize.control)
                    .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
                        .strokeBorder(theme.colors.lineStrong, lineWidth: HOLine.width))
                    .focused($titleFocused)
                    .submitLabel(.go)
                    .onSubmit { flow.start() }
                Text("One video of the whole task works best. Talk through each step as you do it.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
            }
            Button { flow.start() } label: {
                Text("Make Course").frame(maxWidth: .infinity)
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .disabled(flow.video == nil)
            .keyboardShortcut(.defaultAction)
        }
        .onAppear { titleFocused = true }
    }

    // MARK: - Upload and stages

    private var progress: some View {
        VStack(alignment: .leading, spacing: HOSpace.l) {
            Text(flow.title.isEmpty ? "New lesson" : flow.title)
                .hoFont(.title, theme)
                .foregroundStyle(theme.colors.ink)
            VStack(alignment: .leading, spacing: HOSpace.m) {
                ForEach(flow.rows) { row in TeachStageRowView(row: row) }
            }
            .raisedCard()
            if flow.phase == .failed, let failure = flow.failure {
                Label {
                    Text(failure).foregroundStyle(theme.colors.ink)
                } icon: {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(theme.colors.bad)
                }
                .font(theme.fonts.body)
                HStack(spacing: HOSpace.m) {
                    Button { flow.retry() } label: { Text("Try Again").frame(maxWidth: .infinity) }
                        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    Button {
                        flow.reset()
                        onClose()
                    } label: { Text("Done").frame(maxWidth: .infinity) }
                        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                }
            } else if flow.phase == .uploading {
                Button("Cancel", role: .cancel) { flow.cancelUpload() }
                    .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                    .frame(maxWidth: .infinity)
            } else {
                Text("You can leave this screen. The hub keeps working.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                Button { onClose() } label: { Text("Done").frame(maxWidth: .infinity) }
                    .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
            }
        }
    }

    // MARK: - Finished

    private var finished: some View {
        VStack(alignment: .leading, spacing: HOSpace.l) {
            Label {
                Text("Your lesson is ready").hoFont(.title, theme).foregroundStyle(theme.colors.ink)
            } icon: {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.colors.good)
                    .symbolEffect(.bounce, value: flow.finishCount)
            }
            if let lesson = flow.lesson {
                Text(CourseFormat.meta(steps: lesson.steps.count, duration: CourseFormat.duration(of: lesson)))
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                LessonTimelineView(lesson: lesson, hub: hub)
            }
            if let id = flow.lessonId {
                VStack(spacing: HOSpace.m) {
                    Button { onReview(id) } label: { Text("Review Steps").frame(maxWidth: .infinity) }
                        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    Button { onTryAsLearner(id) } label: { Text("Try It as a Learner").frame(maxWidth: .infinity) }
                        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                }
            }
        }
    }
}

/// One stage: its symbol, words, the hub's message, and the upload bar.
struct TeachStageRowView: View {
    var row: TeachStageRow
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: HOSpace.m) {
            symbol.frame(width: 22)
            VStack(alignment: .leading, spacing: HOSpace.xs) {
                Text(row.text)
                    .font(theme.fonts.body)
                    .foregroundStyle(row.state == .pending ? theme.colors.ink2 : theme.colors.ink)
                    .contentTransition(.numericText())
                if let progress = row.progress {
                    ProgressView(value: progress).tint(theme.colors.accent)
                }
                if let detail = row.detail {
                    Text(detail).font(theme.fonts.footnote)
                        .foregroundStyle(row.state == .failed ? theme.colors.bad : theme.colors.ink2)
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(stateWord)
    }

    @ViewBuilder private var symbol: some View {
        switch row.state {
        case .active: ProgressView().controlSize(.small)
        case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.colors.good)
        case .pending: Image(systemName: "circle").foregroundStyle(theme.colors.ink3)
        case .failed: Image(systemName: "xmark.circle.fill").foregroundStyle(theme.colors.bad)
        }
    }

    private var stateWord: String {
        switch row.state {
        case .active: "In progress"
        case .done: "Done"
        case .pending: "Not started"
        case .failed: "Failed"
        }
    }
}

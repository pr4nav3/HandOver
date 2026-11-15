import SwiftUI

/// The course editor (SCREENS.md 14): steps, the player and timeline, the inspector, lesson details, undo and
/// redo (Command Z, Shift Command Z), the autosave indicator, Preview and Publish. Three columns on iPad and Mac;
/// on iPhone the player, timeline and steps stack and the inspector opens as a sheet.
struct EditorView: View {
    var lessonId: String
    var preview: EditorStore?

    init(lessonId: String, preview: EditorStore? = nil) {
        self.lessonId = lessonId
        self.preview = preview
    }

    var body: some View {
        AccountScope { EditorScreen(store: preview ?? EditorStore(lessonId: lessonId), isPreview: preview != nil) }
    }
}

private struct EditorScreen: View {
    @State var store: EditorStore
    var isPreview: Bool
    @Environment(AppModel.self) private var app
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var playhead: Double?
    @State private var showInspector = false
    @State private var showDetails = false
    @State private var showPublish = false
    @State private var launcher = LessonLauncher()
    @State private var confirmMerge = false

    var body: some View {
        Group {
            switch store.phase {
            case .loading:
                HOEmptyState(title: "Loading lesson", loading: true)
            case .failed(let message):
                HOEmptyState(symbol: "exclamationmark.triangle", title: "Can't open the editor", message: message) {
                    Button("Try Again") { Task { await store.load() } }.buttonStyle(HOButtonStyle(.primary))
                }
            case .loaded:
                if isCompact { compact } else { regular }
            }
        }
        .background(theme.colors.paper)
        .navigationTitle(store.course?.title ?? (store.lesson.title.isEmpty ? "Editor" : store.lesson.title))
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar { toolbar }
        .safeAreaInset(edge: .top) { banner }
        .task(id: app.hub) {
            guard !isPreview, let hub = app.hub, let hubClient = app.client else { return }
            let recut = RecutEditorService(id: store.lessonId, hub: hubClient)
            if accounts.hub == hub && accounts.support == .unavailable {
                store.use(service: recut, account: nil, hub: hub)
            } else {
                let account = accounts.courseClient(for: hub)
                store.use(service: CourseEditorService(id: store.lessonId, client: account), fallback: recut,
                          account: account, hub: hub)
            }
            await store.load()
        }
        .onDisappear { Task { await store.flushPending() } }
        .sheet(isPresented: $showInspector) {
            NavigationStack {
                EditorStepInspector(store: store, index: store.selection, hub: app.hub)
                    .navigationTitle("Step \(store.selection + 1)")
                    #if os(iOS)
                    .navigationBarTitleDisplayMode(.inline)
                    #endif
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showInspector = false } } }
            }
            .presentationDetents([.large])
        }
        .sheet(isPresented: $showDetails) {
            NavigationStack {
                LessonDetailsForm(store: store, hub: app.hub)
                    .navigationTitle("Lesson Details")
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showDetails = false } } }
            }
            #if os(macOS)
            .frame(minWidth: 460, minHeight: 520)
            #endif
        }
        .sheet(isPresented: $showPublish) {
            EditorPublishSheet(store: store, canPublishToEveryone: accounts.isOwner)
        }
        .confirmationDialog(mergeTitle, isPresented: $confirmMerge, titleVisibility: .visible) {
            Button("Merge") { Task { await store.perform(.merge(n: store.selection + 1)) } }
        } message: {
            Text("Step \(store.selection + 1)'s title is kept, and step \(store.selection + 2)'s check.")
        }
        .lessonLauncher(launcher)
    }

    /// iPhone layout. The Mac reports regular, so it keeps its own layout; snapshots ask for compact.
    private var isCompact: Bool { sizeClass == .compact }

    // MARK: - Layouts

    private var regular: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                stepList
                Divider().overlay(theme.colors.line)
                stepActions.padding(HOSpace.m)
            }
            .frame(width: 280)
            .background(theme.colors.raised)
            Divider().overlay(theme.colors.line)
            ScrollView {
                VStack(alignment: .leading, spacing: HOSpace.l) {
                    player
                    EditorTimeline(store: store, playhead: $playhead)
                    selectedSummary
                }
                .padding(HOSpace.xl)
            }
            .frame(maxWidth: .infinity)
            Divider().overlay(theme.colors.line)
            EditorStepInspector(store: store, index: store.selection, hub: app.hub)
                .frame(width: 320)
        }
    }

    private var compact: some View {
        GeometryReader { geo in
            compactList(short: HOLayout.isShort(geo.size.height), height: geo.size.height)
        }
    }

    /// On a short screen (iPhone landscape) the player keeps to 60% of the height, so the timeline and the steps
    /// are in view without scrolling past a screen-sized video.
    private func compactList(short: Bool, height: CGFloat) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.l) {
                guide
                player
                    .frame(maxHeight: short ? height * 0.6 : nil)
                    .frame(maxWidth: .infinity)
                EditorTimeline(store: store, playhead: $playhead)
                stepActions
                Text("Steps").sectionHeaderStyle(theme)
                VStack(spacing: 0) {
                    ForEach(Array(store.lesson.steps.enumerated()), id: \.element.id) { index, step in
                        Button {
                            store.selection = index
                            showInspector = true
                        } label: {
                            EditorStepRow(step: step, index: index, selected: store.selection == index,
                                          lessonId: store.lessonId, revision: store.revision)
                        }
                        .buttonStyle(.plain)
                        if index < store.lesson.steps.count - 1 { Divider().overlay(theme.colors.line) }
                    }
                }
                .hoCard()
                if let next = nextLine {
                    Text(next)
                        .font(theme.fonts.footnote)
                        .foregroundStyle(theme.colors.ink2)
                        .padding(.horizontal, HOSpace.xs)
                }
            }
            .padding(HOSpace.l)
        }
    }

    /// One line on what this screen is for (iPhone, where there is no inspector column to explain it).
    private var guide: some View {
        Text(store.permissions.canEdit
             ? "Check each step. Tap one to fix its title, times or how it is checked. Changes save on their own."
             : "You can watch these steps. Only the lesson's editors can change them.")
            .font(theme.fonts.callout)
            .foregroundStyle(theme.colors.ink2)
            .fixedSize(horizontal: false, vertical: true)
    }

    /// What to do once the steps look right.
    private var nextLine: String? {
        guard store.capabilities.course, store.permissions.canPublish else {
            return store.permissions.canEdit ? "Tap More, then Preview, to try it as a learner." : nil
        }
        return store.course?.status == .draft
            ? "When the steps look right, tap Publish so learners can find it."
            : "Tap Update to change who can find it."
    }

    private var stepList: some View {
        ScrollViewReader { proxy in
            List(selection: Binding(get: { store.selection }, set: { if let new = $0 { store.selection = new } })) {
                Section {
                    ForEach(Array(store.lesson.steps.enumerated()), id: \.element.id) { index, step in
                        EditorStepRow(step: step, index: index, selected: store.selection == index,
                                      lessonId: store.lessonId, revision: store.revision)
                            .tag(index)
                            .id(index)
                            .listRowInsets(EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0))
                            .listRowBackground(Color.clear)
                    }
                } header: {
                    HStack {
                        Text("Steps").sectionHeaderStyle(theme)
                        Spacer()
                        Button("Details") { showDetails = true }.buttonStyle(.borderless).font(theme.fonts.callout)
                    }
                }
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
            .onChange(of: store.selection) { _, index in withAnimation { proxy.scrollTo(index) } }
        }
    }

    private var stepActions: some View {
        HStack(spacing: HOSpace.s) {
            Button("Split", systemImage: "scissors") {
                guard let point = splitPoint else { return }
                Task { await store.perform(.split(n: store.selection + 1, at: point)) }
            }
            .disabled(splitPoint == nil || store.isBusy)
            .help(splitPoint == nil ? "Too short to split here." : "Split at the playhead")
            Button("Merge", systemImage: "arrow.triangle.merge") {
                if needsMergeConfirm { confirmMerge = true } else {
                    Task { await store.perform(.merge(n: store.selection + 1)) }
                }
            }
            .disabled(store.selection + 1 >= store.lesson.steps.count || store.isBusy)
            Spacer()
        }
        .buttonStyle(HOButtonStyle(.secondary, size: .small))
        .labelStyle(.titleAndIcon)
        .disabled(!store.permissions.canEdit)
    }

    /// The playhead when it is inside the selected step, else its middle.
    private var splitPoint: Double? {
        guard let step = store.selectedStep, let a = step.startSeconds, let b = step.endSeconds else { return nil }
        let point = playhead.flatMap { (a...b).contains($0) ? $0 : nil } ?? (a + b) / 2
        return EditorBoundarySnap.canSplit(step, at: point) ? (point * 10).rounded() / 10 : nil
    }

    private var needsMergeConfirm: Bool {
        let steps = store.lesson.steps
        let i = store.selection
        guard steps.indices.contains(i + 1) else { return false }
        return !steps[i].isManual && !steps[i + 1].isManual && steps[i].checkQuestion != steps[i + 1].checkQuestion
    }

    private var mergeTitle: String { "Merge Steps \(store.selection + 1) and \(store.selection + 2)?" }

    @ViewBuilder private var player: some View {
        if let step = store.selectedStep, let hub = app.hub {
            TeachClipPlayer(url: hub.fileURL(lesson: store.lessonId, path: step.clip, rev: store.revision), autoplay: false)
        } else {
            TeachClipPlayer(url: nil)
        }
    }

    @ViewBuilder private var selectedSummary: some View {
        if let step = store.selectedStep {
            VStack(alignment: .leading, spacing: HOSpace.xs) {
                Text("\(store.selection + 1). \(step.title)").font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                Text("\(step.start) to \(step.end), \(step.isManual ? "Manual" : "Camera check")")
                    .font(theme.fonts.callout.monospacedDigit())
                    .foregroundStyle(theme.colors.ink2)
            }
        }
    }

    // MARK: - Toolbar and banner

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button("Undo", systemImage: "arrow.uturn.backward") { Task { await store.undo() } }
                .keyboardShortcut("z", modifiers: .command)
                .disabled(!store.canUndo)
            Button("Redo", systemImage: "arrow.uturn.forward") { Task { await store.redo() } }
                .keyboardShortcut("z", modifiers: [.command, .shift])
                .disabled(!store.canRedo)
        }
        ToolbarItem(placement: .status) { EditorSaveIndicator(state: store.save) { store.retrySave() } }
        ToolbarItem(placement: .primaryAction) {
            Menu("More", systemImage: "ellipsis.circle") {
                Button("Preview", systemImage: "play") { launcher.start(store.lessonId, model: app) }
                Button("Lesson Details", systemImage: "info.circle") { showDetails = true }
                Button("Save Now", systemImage: "checkmark") { Task { await store.flushPending() } }
                    .keyboardShortcut("s", modifiers: .command)
            }
        }
        if store.capabilities.course && store.permissions.canPublish {
            ToolbarItem(placement: .confirmationAction) {
                Button(store.course?.status == .draft ? "Publish" : "Update") { showPublish = true }
                    .buttonStyle(.borderedProminent)
            }
        }
    }

    @ViewBuilder private var banner: some View {
        if let message = store.banner {
            HOBanner(symbol: "exclamationmark.triangle.fill", tone: .bad, text: message, actionTitle: "Dismiss") {
                store.dismissBanner()
            }
                .padding(.horizontal, HOSpace.l)
                .padding(.top, HOSpace.s)
        }
    }
}

/// "Saving", "Saved", "Updating clips", "Saved on this device only", or "Could not save" with Try Again.
struct EditorSaveIndicator: View {
    var state: EditorSaveState
    var retry: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        if let text = state.text {
            HStack(spacing: HOSpace.xs) {
                if state == .saving || state == .updatingClips { ProgressView().controlSize(.mini) }
                Text(text)
                    .font(theme.fonts.footnote)
                    .foregroundStyle(isFailure ? theme.colors.bad : theme.colors.ink2)
                if isFailure { Button("Try Again", action: retry).font(theme.fonts.footnote).buttonStyle(.borderless) }
            }
            .fixedSize()
            .accessibilityElement(children: .combine)
        }
    }

    private var isFailure: Bool { if case .failed = state { true } else { false } }
}

/// A step in the editor list (DESIGN.md 3.10 step row): number tile, thumbnail, title, times and check.
struct EditorStepRow: View {
    var step: Step
    var index: Int
    var selected: Bool
    var lessonId: String
    var revision: Int
    @Environment(AppModel.self) private var app
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.s) {
            Text("\(index + 1)")
                .font(.system(.callout, design: .rounded).weight(.semibold).monospacedDigit())
                .foregroundStyle(selected ? theme.colors.accentInk : theme.colors.ink2)
                .frame(width: 24, height: 24)
                .background(Circle().fill(TeachStepHues.color(index, theme: theme).opacity(0.18)))
            HubImage(app.hub.map { $0.fileURL(lesson: lessonId, path: step.refFrame, rev: revision) })
                .frame(width: 72, height: 40)
                .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(step.title.isEmpty ? "Step \(index + 1)" : step.title)
                    .font(theme.fonts.bodyMedium)
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(2)
                HStack(spacing: HOSpace.xs) {
                    Image(systemName: step.isManual ? "hand.tap" : "viewfinder")
                        .accessibilityLabel(step.isManual ? "Manual" : "Camera check")
                    Text(meta)
                }
                .font(theme.fonts.caption.monospacedDigit())
                .foregroundStyle(theme.colors.ink2)
                .lineLimit(1)
            }
            Spacer(minLength: 0)
            if step.selfTest?.ok == false {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(theme.colors.caution)
                    .accessibilityLabel("Failed its test")
            }
        }
        .padding(.horizontal, HOSpace.m)
        .padding(.vertical, HOSpace.s)
        .background(selected ? theme.colors.accentSoft : .clear,
                    in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var meta: String {
        let a = CourseFormat.duration(step.startSeconds) ?? step.start
        let b = CourseFormat.duration(step.endSeconds) ?? step.end
        return "\(a) to \(b)"
    }
}

/// The preview fortune teller lesson in the editor, with every section shown.
enum EditorPreview {
    @MainActor
    static func store() -> EditorStore {
        let lesson = PreviewHub.fortuneTeller.lesson
        let store = EditorStore(lessonId: lesson.id)
        var withTest = lesson
        withTest.steps[1].selfTest = Step.SelfTest(own: .yes, prev: .no, ok: true, mock: false)
        store.preview(lesson: withTest,
                      course: Course(id: lesson.id, title: lesson.title, steps: lesson.steps.count, status: .draft),
                      permissions: CoursePermissions(canEdit: true, canPublish: true, canManage: true),
                      cues: [1: [EditorCaptionCue(start: 0.5, end: 3.2, text: "Fold one corner to the opposite corner."),
                                 EditorCaptionCue(start: 3.6, end: 7.4, text: "Crease it firmly along the edge.")]])
        store.selection = 1
        return store
    }
}

#Preview("Editor") {
    NavigationStack { EditorView(lessonId: "fortune-teller-v1", preview: EditorPreview.store()) }
        .environment(AppModel.preview())
        .environment(AccountStore.preview())
}

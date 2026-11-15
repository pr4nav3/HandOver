import SwiftUI

/// Home (SCREENS.md 5 and 21): how HandOver works, Learn and Teach, Continue, then every lesson this person may see as cards or rows, search,
/// filters (Everyone, Mine, Shared with Me, My Orgs), pull to refresh, and empty states. Falls back to
/// `GET /api/lessons` on hubs without the course routes.
struct LibraryView: View {
    var preview: LibraryStore?

    init(preview: LibraryStore? = nil) { self.preview = preview }

    var body: some View {
        AccountScope { LibraryScreen(store: preview ?? LibraryStore()) }
    }
}

private struct LibraryScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(LearnFlow.self) private var flow: LearnFlow?
    @AppStorage(HowItWorks.hiddenKey) private var howItWorksHidden = false
    @State private var store: LibraryStore
    @State private var launcher = LessonLauncher()
    @State private var pendingDelete: CourseCardItem?
    @State private var showTeach = false
    @State private var actionError: String?

    init(store: LibraryStore = LibraryStore()) {
        _store = State(initialValue: store)
    }

    var body: some View {
        content
            .navigationTitle("Home")
            .searchable(text: $store.query, prompt: "Search lessons")
            .onChange(of: store.query) { store.queryChanged() }
            .onChange(of: store.filter) { Task { await store.reload() } }
            .refreshable {
                HubImageCache.shared.clear()
                await store.reload()
            }
            .task(id: reloadKey) {
                if model.isPreview {
                    if store.items.isEmpty { store.preview(items: LibraryPreview.items(model: model), source: .legacy) }
                    return
                }
                store.use(.live(model: model, accounts: accounts))
                await store.reload()
            }
            .toolbar {
                if howItWorksHidden {
                    ToolbarItem(placement: .primaryAction) {
                        Button("How It Works", systemImage: "questionmark.circle") {
                            withAnimation(HOMotion.layout) { howItWorksHidden = false }
                        }
                    }
                }
                #if os(macOS)
                ToolbarItem {
                    Button("Refresh", systemImage: "arrow.clockwise") { Task { await store.reload() } }
                        .keyboardShortcut("r")
                }
                #endif
            }
            .navigationDestination(for: CourseRoute.self) { route in
                switch route {
                case .detail(let id): LessonDetailView(lessonId: id)
                case .editor(let id): EditorView(lessonId: id)
                }
            }
            .lessonLauncher(launcher)
            .sheet(isPresented: $showTeach) {
                NavigationStack {
                    TeachView()
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) { Button("Close") { showTeach = false } }
                        }
                }
            }
            .confirmationDialog(pendingDelete.map { "Delete \($0.title)?" } ?? "",
                                isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }),
                                titleVisibility: .visible, presenting: pendingDelete) { item in
                Button("Delete Lesson", role: .destructive) {
                    Haptics.warning()
                    delete(item)
                }
            } message: { _ in
                Text("This removes the lesson and its clips from the hub. Learners lose access.")
            }
            .alert("Could not delete", isPresented: Binding(get: { actionError != nil }, set: { if !$0 { actionError = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(actionError ?? "")
            }
    }

    private var reloadKey: String {
        "\(model.hub?.description ?? "")|\(String(describing: accounts.support))|\(accounts.user?.id ?? "")"
    }

    @ViewBuilder private var content: some View {
        if model.hub == nil {
            noHub
        } else if case .failed(let message) = store.phase, store.items.isEmpty {
            HOEmptyState(symbol: "wifi.exclamationmark", title: "Can't load lessons", message: message) {
                Button("Try Again") { Task { await store.reload() } }
                    .buttonStyle(HOButtonStyle(.secondary))
            }
        } else if store.phase == .loading && store.items.isEmpty {
            HOEmptyState(title: "Loading lessons", loading: true)
        } else if store.isEmpty {
            empty
        } else {
            list
        }
    }

    private var noHub: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                if !howItWorksHidden { howItWorks }
                VStack(spacing: HOSpace.m) {
                    HOEmptyState(symbol: "desktopcomputer", title: "Connect to your hub",
                                 message: "The hub is HandOver running on a computer near you. It has the lessons.") {
                        Button("Open Settings") { flow?.section = .settings }
                            .buttonStyle(HOButtonStyle(.primary, size: .large))
                    }
                }
            }
            .padding(.horizontal, margin)
            .padding(.vertical, HOSpace.l)
            .frame(maxWidth: 1200)
            .frame(maxWidth: .infinity)
        }
        .background(theme.colors.paper)
    }

    private var howItWorks: some View {
        HowItWorksCard {
            withAnimation(HOMotion.layout) { howItWorksHidden = true }
        }
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    @ViewBuilder private var empty: some View {
        if store.isSearching {
            HOEmptyState(symbol: "magnifyingglass", title: "No results for \u{201C}\(store.lastQuery)\u{201D}",
                         message: "Check the spelling or try fewer words.")
        } else if canTeach {
            HOEmptyState(symbol: "film.stack", title: "No lessons yet",
                         message: "Record a task once and HandOver turns it into steps.") {
                Button("Make a Lesson") { showTeach = true }
                    .buttonStyle(HOButtonStyle(.primary))
            }
        } else {
            HOEmptyState(symbol: "film.stack", title: "No lessons yet",
                         message: "When someone shares a lesson on this hub, it shows up here.")
        }
    }

    private var list: some View {
        ScrollViewReader { proxy in
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                if !store.isSearching {
                    if let flow, flow.isRunning { runningRow(flow) }
                    OnboardingHomeCard(onTeach: canTeach ? { flow?.section = .teach } : nil)
                    if !howItWorksHidden { howItWorks }
                    actions { withAnimation(HOMotion.layout) { proxy.scrollTo(Self.lessonsAnchor, anchor: .top) } }
                }
                if store.showsFilters && accounts.isSignedIn {
                    Picker("Show", selection: $store.filter) {
                        ForEach(CourseFilter.allCases) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .onChange(of: store.filter) { Haptics.tap() }
                }
                if !store.continueItems.isEmpty && !store.isSearching {
                    section("Continue") { continueRow }
                }
                section(store.isSearching ? "Results" : "Lessons") { allLessons }
                    .id(Self.lessonsAnchor)
            }
            .padding(.horizontal, margin)
            .padding(.vertical, HOSpace.l)
            .frame(maxWidth: 1200)
            .frame(maxWidth: .infinity)
        }
        .background(theme.colors.paper)
        }
    }

    private static let lessonsAnchor = "lessons"

    /// Learn a Lesson and Teach a Lesson, side by side.
    private func actions(showLessons: @escaping () -> Void) -> some View {
        HStack(spacing: HOSpace.m) {
            HomeActionButton(symbol: "graduationcap", title: "Learn a Lesson", line: "Pick one below", primary: true,
                             action: showLessons)
            if canTeach {
                HomeActionButton(symbol: "video.badge.plus", title: "Teach a Lesson", line: "Record a task once") {
                    showTeach = true
                }
            }
        }
    }

    /// Back to the lesson in progress.
    private func runningRow(_ flow: LearnFlow) -> some View {
        Button { Haptics.tap(); flow.section = .learn } label: {
            HStack(spacing: HOSpace.m) {
                SymbolTile(symbol: "play.fill")
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text("Lesson in progress").font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                    Text(model.lesson?.title ?? "Tap to go back to it.")
                        .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2).lineLimit(1)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(theme.colors.ink3)
            }
            .raisedCard()
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens Learn")
    }

    private var margin: CGFloat { isCompact ? HOSpace.l : HOSpace.xl }

    private var isCompact: Bool {
        #if os(iOS)
        sizeClass == .compact
        #else
        false
        #endif
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            Text(title).sectionHeaderStyle(theme)
            content()
        }
    }

    @ViewBuilder private var continueRow: some View {
        if isCompact {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: HOSpace.m) {
                    ForEach(store.continueItems) { item in
                        Button { resume(item) } label: { CourseCardView(item: item, continueStyle: true) }
                            .buttonStyle(.plain)
                            .frame(width: 260)
                            .contextMenu { menu(item) }
                    }
                }
            }
            .scrollClipDisabled()
        } else {
            grid(store.continueItems, continueStyle: true)
        }
    }

    @ViewBuilder private var allLessons: some View {
        if isCompact {
            VStack(spacing: 0) {
                ForEach(Array(store.items.enumerated()), id: \.element.id) { index, item in
                    NavigationLink(value: CourseRoute.detail(item.id)) { CourseRowView(item: item) }
                        .buttonStyle(.plain)
                        .contextMenu { menu(item) }
                    if index < store.items.count - 1 {
                        Divider().overlay(theme.colors.line).padding(.leading, HOSpace.l + 64 + HOSpace.m)
                    }
                }
            }
            .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
        } else {
            grid(store.items, continueStyle: false)
        }
    }

    private func grid(_ items: [CourseCardItem], continueStyle: Bool) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 240, maximum: 380), spacing: HOSpace.l, alignment: .top)],
                  alignment: .leading, spacing: HOSpace.xl) {
            ForEach(items) { item in
                Group {
                    if continueStyle {
                        Button { resume(item) } label: { CourseCardView(item: item, continueStyle: true) }
                    } else {
                        NavigationLink(value: CourseRoute.detail(item.id)) { CourseCardView(item: item) }
                    }
                }
                .buttonStyle(.plain)
                .contextMenu { menu(item) }
            }
        }
    }

    @ViewBuilder private func menu(_ item: CourseCardItem) -> some View {
        Button("Start", systemImage: "play") { launcher.start(item.id, model: model) }
        NavigationLink(value: CourseRoute.detail(item.id)) { Label("Lesson Details", systemImage: "info.circle") }
        if canEdit(item) {
            NavigationLink(value: CourseRoute.editor(item.id)) { Label("Edit", systemImage: "pencil") }
        }
        if canDelete(item) {
            Divider()
            Button("Delete Lesson", systemImage: "trash", role: .destructive) { pendingDelete = item }
        }
    }

    private func resume(_ item: CourseCardItem) {
        launcher.start(item.id, at: item.progress?.lastStepsDone, model: model)
    }

    private func delete(_ item: CourseCardItem) {
        guard let client = model.client else { return }
        Task {
            do {
                try await client.delete(id: item.id)
                store.remove(item.id)
            } catch {
                actionError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
        }
    }

    // MARK: - Who may do what (SCREENS.md 24). Hubs without accounts let everyone do everything.

    private var noAccounts: Bool { !accounts.support.hasAccounts }
    private var canTeach: Bool { noAccounts || (accounts.user.map { $0.role != .learner } ?? false) }

    private func canEdit(_ item: CourseCardItem) -> Bool {
        noAccounts || accounts.isOwner || (item.ownerId != nil && item.ownerId == accounts.user?.id)
    }

    private func canDelete(_ item: CourseCardItem) -> Bool { canEdit(item) }
}

/// Library contents for previews and snapshots, built from the preview hub.
enum LibraryPreview {
    @MainActor
    static func items(model: AppModel) -> [CourseCardItem] {
        guard let hub = model.hub else { return [] }
        let lesson = PreviewHub.fortuneTeller.lesson
        return [
            CourseCardItem(id: lesson.id, title: lesson.title,
                           covers: CourseMedia.coverCandidates(hub: hub, lessonId: lesson.id, coverURL: nil),
                           steps: lesson.steps.count, duration: CourseFormat.duration(of: lesson), status: .published,
                           progress: CourseProgress(lastStepsDone: 2, total: lesson.steps.count)),
            CourseCardItem(id: "bike-wheel-v1", title: "Take off a quick-release front wheel",
                           covers: CourseMedia.coverCandidates(hub: hub, lessonId: "bike-wheel-v1", coverURL: nil),
                           steps: 6, status: .draft),
        ]
    }
}

/// "How it works" in three steps, dismissible; the "?" button brings it back.
struct HowItWorksCard: View {
    var onHide: () -> Void
    @Environment(\.theme) private var theme

    static let steps: [(symbol: String, title: String, line: String)] = [
        ("list.bullet.rectangle", "Pick a lesson", "An expert recorded it as short step clips."),
        ("camera", "Choose a camera", "This phone propped up, Meta glasses, or another device."),
        ("checkmark.circle", "Follow along", "The hub tells you when each step is done."),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            HStack {
                Text("How it works").font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button { Haptics.tap(); onHide() } label: {
                    Image(systemName: "xmark").font(.footnote.weight(.semibold)).foregroundStyle(theme.colors.ink2)
                        .frame(width: HOSize.touch, height: HOSize.touch)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(-HOSpace.s)
                .accessibilityLabel("Hide How It Works")
            }
            ForEach(Array(Self.steps.enumerated()), id: \.offset) { index, step in
                HStack(alignment: .top, spacing: HOSpace.m) {
                    SymbolTile(symbol: step.symbol, side: 36)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(index + 1). \(step.title)").font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
                        Text(step.line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .accessibilityElement(children: .combine)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .raisedCard()
    }
}

enum HowItWorks {
    static let hiddenKey = "handover.home.howItWorksHidden"
}

/// A large Home action: symbol, title and one line.
struct HomeActionButton: View {
    let symbol: String
    let title: String
    let line: String
    var primary = false
    let action: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        Button { Haptics.tap(); action() } label: {
            VStack(alignment: .leading, spacing: HOSpace.s) {
                Image(systemName: symbol)
                    .font(.title2.weight(.medium))
                    .foregroundStyle(primary ? theme.colors.onAccent : theme.colors.accentInk)
                    .frame(height: 32, alignment: .leading)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(theme.fonts.headline)
                        .foregroundStyle(primary ? theme.colors.onAccent : theme.colors.ink)
                    Text(line).font(theme.fonts.footnote)
                        .foregroundStyle(primary ? theme.colors.onAccent.opacity(0.85) : theme.colors.ink2)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 96, alignment: .topLeading)
            .padding(HOSpace.l)
            .background(primary ? theme.colors.accent : theme.colors.raised,
                        in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                .strokeBorder(primary ? Color.clear : theme.colors.line, lineWidth: HOLine.width))
            .contentShape(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

#Preview("Library") {
    NavigationStack { LibraryView() }
        .environment(AppModel.preview())
        .environment(AccountStore.preview())
}

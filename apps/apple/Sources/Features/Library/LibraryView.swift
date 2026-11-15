import SwiftUI

/// The Library (SCREENS.md 5 and 21): Continue, every lesson this person may see as cards or rows, search,
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
            .navigationTitle("Library")
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
            HOEmptyState(symbol: "desktopcomputer", title: "No hub", message: "Connect to a hub in Settings to see its lessons.")
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
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
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
                section(store.isSearching ? "Results" : "All Lessons") { allLessons }
            }
            .padding(.horizontal, margin)
            .padding(.vertical, HOSpace.l)
            .frame(maxWidth: 1200)
            .frame(maxWidth: .infinity)
        }
        .background(theme.colors.paper)
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

#Preview("Library") {
    NavigationStack { LibraryView() }
        .environment(AppModel.preview())
        .environment(AccountStore.preview())
}

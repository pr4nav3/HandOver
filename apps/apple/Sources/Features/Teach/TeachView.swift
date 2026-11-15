import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// Teach home (SCREENS.md 11): Record a Take, Choose from Photos, Choose from Files (drop a video on Mac), and
/// the person's own lessons with their status. Picking a video opens the Make course sheet.
struct TeachView: View {
    /// Fixed lessons for previews and snapshots.
    var preview: LibraryStore?

    var body: some View {
        AccountScope { TeachScreen(preset: preview) }
    }
}

/// A picked video, copied out of Photos into a temporary file the upload can read.
struct TeachVideoTransfer: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .movie) { received in
            let folder = FileManager.default.temporaryDirectory.appending(path: "handover-picked", directoryHint: .isDirectory)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let name = received.file.lastPathComponent.isEmpty ? "video.mov" : received.file.lastPathComponent
            let target = folder.appending(path: "\(UUID().uuidString.prefix(8))-\(name)")
            try FileManager.default.copyItem(at: received.file, to: target)
            return TeachVideoTransfer(url: target)
        }
    }
}

private struct TeachScreen: View {
    var preset: LibraryStore?
    @Environment(AppModel.self) private var model
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var flow = UploadFlow()
    @State private var lessons: LibraryStore
    @State private var launcher = LessonLauncher()
    @State private var showSheet = false
    @State private var showImporter = false
    @State private var showRecorder = false
    @State private var photoItem: PhotosPickerItem?
    @State private var preparing = false
    @State private var pickError: String?
    @State private var pickTitle = "Can't open that video"
    @State private var editing: String?
    @State private var dropTargeted = false

    init(preset: LibraryStore?) {
        self.preset = preset
        _lessons = State(initialValue: preset ?? LibraryStore())
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                Text("Show a task once. HandOver turns it into a lesson anyone can follow.")
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                    .fixedSize(horizontal: false, vertical: true)
                if model.hub == nil { noHubBanner }
                options
                if showsHowItWorks { howItWorks }
                yourLessons
            }
            .padding(.horizontal, isCompact ? HOSpace.l : HOSpace.xl)
            .padding(.vertical, HOSpace.l)
            .frame(maxWidth: 1100)
            .frame(maxWidth: .infinity)
        }
        .background(theme.colors.paper)
        .navigationTitle("Teach")
        .overlay { if preparing { preparingOverlay } }
        .overlay { if dropTargeted { dropOverlay } }
        .dropDestination(for: URL.self) { urls, _ in
            guard let url = urls.first(where: { UTType(filenameExtension: $0.pathExtension)?.conforms(to: .movie) == true })
            else { return false }
            picked(TeachPickedVideo(url: url))
            return true
        } isTargeted: { dropTargeted = $0 }
        .onChange(of: photoItem) { _, item in if let item { load(item) } }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.movie, .mpeg4Movie, .quickTimeMovie]) { result in
            switch result {
            case .success(let url): picked(TeachPickedVideo(url: url))
            case .failure(let error):
                pickTitle = "Can't open that video"
                pickError = "\(error.localizedDescription) Try a different video."
            }
        }
        .sheet(isPresented: $showSheet) {
            NavigationStack {
                MakeCourseView(flow: flow, hub: model.hub,
                               onReview: { id in
                                   showSheet = false
                                   flow.reset()
                                   editing = id
                               },
                               onTryAsLearner: { id in
                                   showSheet = false
                                   flow.reset()
                                   launcher.start(id, model: model)
                               },
                               onClose: { showSheet = false })
            }
            #if os(macOS)
            .frame(minWidth: 520, minHeight: 560)
            #endif
        }
        #if os(iOS)
        .fullScreenCover(isPresented: $showRecorder) { recorder }
        #else
        .sheet(isPresented: $showRecorder) { recorder.frame(minWidth: 900, minHeight: 640) }
        #endif
        .alert(pickTitle, isPresented: Binding(get: { pickError != nil }, set: { if !$0 { pickError = nil } })) {
            Button("OK", role: .cancel) {}
        } message: { Text(pickError ?? "") }
        .navigationDestination(for: CourseRoute.self) { route in
            switch route {
            case .detail(let id): LessonDetailView(lessonId: id)
            case .editor(let id): EditorView(lessonId: id)
            }
        }
        .navigationDestination(item: $editing) { EditorView(lessonId: $0) }
        .lessonLauncher(launcher)
        .task(id: reloadKey) {
            guard !model.isPreview else { return }
            flow.use(.live(model: model, accounts: accounts))
            lessons.use(.live(model: model, accounts: accounts))
            lessons.filter = accounts.isSignedIn ? .mine : .everyone
            await lessons.reload()
        }
        .onChange(of: flow.phase) { _, phase in
            if phase == .finished { Task { await lessons.reload() } }
        }
    }

    private var recorder: some View {
        RecordView(onMakeCourse: { url, title in
            showRecorder = false
            picked(TeachPickedVideo(url: url, name: url.lastPathComponent))
            flow.title = title
            flow.start()
        }, onImport: { url in
            showRecorder = false
            picked(TeachPickedVideo(url: url))
        })
    }

    private var reloadKey: String {
        "\(model.hub?.description ?? "")|\(String(describing: accounts.support))|\(accounts.user?.id ?? "")"
    }

    /// iPhone layout. The Mac reports regular, so it keeps its own layout; snapshots ask for compact.
    private var isCompact: Bool { sizeClass == .compact }

    // MARK: - Options

    /// The two ways to make a lesson (SCREENS.md 11): record now, or use a video you already have.
    @ViewBuilder private var options: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            Text("Make a Lesson").sectionHeaderStyle(theme)
            let cards = Group {
                OptionCard(symbol: "record.circle", title: "Record Now", line: recordLine) { showRecorder = true }
                pickCard
            }
            if isCompact {
                VStack(spacing: HOSpace.m) { cards }
            } else {
                HStack(alignment: .top, spacing: HOSpace.l) { cards }
            }
        }
    }

    /// Photos and Files on iPhone and iPad; a file or a drop on the Mac.
    @ViewBuilder private var pickCard: some View {
        #if os(iOS)
        VStack(alignment: .leading, spacing: HOSpace.m) {
            OptionCardHeader(symbol: "film", title: "Use a Video You Have",
                             line: "One video of the whole task, with you talking through it.")
            HStack(spacing: HOSpace.s) {
                PhotosPicker(selection: $photoItem, matching: .videos, preferredItemEncoding: .current) {
                    Label("Photos", systemImage: "photo.on.rectangle").frame(maxWidth: .infinity)
                }
                .buttonStyle(HOButtonStyle(.secondary, fullWidth: true))
                Button { showImporter = true } label: {
                    Label("Files", systemImage: "folder").frame(maxWidth: .infinity)
                }
                .buttonStyle(HOButtonStyle(.secondary, fullWidth: true))
            }
        }
        .raisedCard()
        #else
        OptionCard(symbol: "film", title: "Use a Video You Have",
                   line: "Choose a file, or drop a video on this window.") {
            showImporter = true
        }
        #endif
    }

    private var recordLine: String {
        #if os(iOS)
        GlassesFeature.isEnabled
            ? "Film the task with this \(DeviceWord.noun) or your Ray-Ban Meta glasses. Talk through each step."
            : "Film the task with this \(DeviceWord.noun). Talk through each step as you go."
        #else
        "Film the task with this Mac's camera or your iPhone. Talk through each step."
        #endif
    }

    private var noHubBanner: some View {
        HOBanner(symbol: "desktopcomputer", tone: .caution,
                 text: "Connect to a hub in Settings first. The hub is the HandOver app running on a laptop near you.")
    }

    // MARK: - How it works

    /// Shown until the first lesson exists: what happens after the video goes up.
    private var showsHowItWorks: Bool {
        lessons.items.isEmpty && !flow.isWorking && flow.phase != .failed
            && (lessons.phase == .loaded || model.isPreview || model.hub == nil)
    }

    private var howItWorks: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            Text("What Happens Next").sectionHeaderStyle(theme)
            VStack(alignment: .leading, spacing: HOSpace.l) {
                HowItWorksRow(number: 1, title: "Your video goes to the hub",
                              line: "The hub is the HandOver app running on a laptop near you.")
                HowItWorksRow(number: 2, title: "HandOver makes the steps",
                              line: "It finds where each step starts, cuts a clip for each one, and adds captions.")
                HowItWorksRow(number: 3, title: "You check them in the editor",
                              line: "Fix any title or time, then publish so learners can find it.")
            }
            .raisedCard()
        }
    }

    // MARK: - Your lessons

    @ViewBuilder private var yourLessons: some View {
        if flow.isWorking || flow.phase == .failed || !lessons.items.isEmpty {
            VStack(alignment: .leading, spacing: HOSpace.s) {
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text("Your Lessons").sectionHeaderStyle(theme)
                    Text("Open a lesson to edit its steps, timing, and checks.")
                        .font(theme.fonts.footnote)
                        .foregroundStyle(theme.colors.ink2)
                }
                if flow.isWorking || flow.phase == .failed {
                    Button { showSheet = true } label: { processingRow }.buttonStyle(.plain)
                }
                if !lessons.items.isEmpty {
                    VStack(spacing: 0) {
                        ForEach(Array(lessons.items.enumerated()), id: \.element.id) { index, item in
                            NavigationLink(value: CourseRoute.editor(item.id)) { TeachLessonRow(item: item) }
                                .buttonStyle(.plain)
                            if index < lessons.items.count - 1 {
                                Divider().overlay(theme.colors.line).padding(.leading, HOSpace.l + 64 + HOSpace.m)
                            }
                        }
                    }
                    .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                        .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
                }
            }
        }
    }

    private var processingRow: some View {
        HStack(spacing: HOSpace.m) {
            Image(systemName: "film")
                .foregroundStyle(theme.colors.ink2)
                .frame(width: 64, height: 40)
                .background(theme.colors.well, in: RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(flow.title.isEmpty ? "New lesson" : flow.title)
                    .font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink).lineLimit(1)
                Text(flow.rows.last(where: { $0.state != .pending })?.text ?? "")
                    .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
            }
            Spacer()
            CourseStatusBadge(kind: flow.phase == .failed ? .failed : .processing)
        }
        .padding(HOSpace.m)
        .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
            .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
    }

    private var preparingOverlay: some View {
        ProgressView("Preparing video")
            .padding(HOSpace.xl)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous))
    }

    private var dropOverlay: some View {
        RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous)
            .strokeBorder(theme.colors.accent, style: StrokeStyle(lineWidth: 2, dash: [8, 6]))
            .background(theme.colors.accentSoft, in: RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous))
            .overlay(Text("Drop a video to make a lesson").font(theme.fonts.headline).foregroundStyle(theme.colors.accentInk))
            .padding(HOSpace.l)
            .allowsHitTesting(false)
    }

    // MARK: - Picking

    private func load(_ item: PhotosPickerItem) {
        preparing = true
        Task {
            defer {
                preparing = false
                photoItem = nil
            }
            do {
                pickTitle = "Can't open that video"
                guard let video = try await item.loadTransferable(type: TeachVideoTransfer.self) else {
                    pickError = "That item is not a video. Pick a video instead."
                    return
                }
                picked(TeachPickedVideo(url: video.url))
            } catch {
                pickError = "\(error.localizedDescription) Try a different video."
            }
        }
    }

    private func picked(_ video: TeachPickedVideo) {
        guard !flow.isWorking else {
            pickTitle = "One lesson at a time"
            pickError = "A lesson is still uploading. When it finishes, pick the next video."
            return
        }
        flow.pick(video)
        showSheet = true
    }
}

/// A big Teach option (SCREENS.md 11): symbol tile, title, one line.
private struct OptionCard: View {
    var symbol: String
    var title: String
    var line: String
    var action: () -> Void

    var body: some View {
        Button(action: action) { OptionCardLabel(symbol: symbol, title: title, line: line) }
            .buttonStyle(.plain)
    }
}

private struct OptionCardLabel: View {
    var symbol: String
    var title: String
    var line: String
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .center, spacing: HOSpace.m) {
            OptionCardHeader(symbol: symbol, title: title, line: line)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(theme.colors.ink3)
                .accessibilityHidden(true)
        }
        .raisedCard()
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

/// Symbol tile, title and one line: the top of a Teach option card.
private struct OptionCardHeader: View {
    var symbol: String
    var title: String
    var line: String
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .top, spacing: HOSpace.m) {
            SymbolTile(symbol: symbol, side: 44)
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text(title).font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                Text(line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
    }
}

/// A numbered line in What Happens Next.
private struct HowItWorksRow: View {
    var number: Int
    var title: String
    var line: String
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .top, spacing: HOSpace.m) {
            Text("\(number)")
                .font(.system(.subheadline, design: .rounded).weight(.semibold))
                .foregroundStyle(theme.colors.accentInk)
                .frame(width: 28, height: 28)
                .background(theme.colors.accentSoft, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text(title).font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
                Text(line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Step \(number): \(title). \(line)")
    }
}

/// A lesson row in Teach: always shows its status, since this is the teacher's own list.
private struct TeachLessonRow: View {
    var item: CourseCardItem
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.m) {
            HubImage(item.covers, symbol: "film")
                .frame(width: 64, height: 40)
                .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text(item.title).font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink).lineLimit(2)
                Text(item.meta).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
            }
            Spacer(minLength: 0)
            if let status = item.status { CourseStatusBadge(status) }
            Label("Edit", systemImage: "pencil")
                .font(theme.fonts.footnote.weight(.semibold))
                .foregroundStyle(theme.colors.accentInk)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the editor")
    }
}

#Preview("Teach") {
    NavigationStack { TeachView() }
        .environment(AppModel.preview())
        .environment(AccountStore.preview())
}

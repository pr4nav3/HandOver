import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// Teach home (SCREENS.md 11): Record a Take, Choose from Photos, Choose from Files (drop a video on Mac), and
/// the person's own lessons with their status. Picking a video opens the Make course sheet.
struct TeachView: View {
    var body: some View {
        AccountScope { TeachScreen() }
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
    @Environment(AppModel.self) private var model
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var flow = UploadFlow()
    @State private var lessons = LibraryStore()
    @State private var launcher = LessonLauncher()
    @State private var showSheet = false
    @State private var showImporter = false
    @State private var showRecorder = false
    @State private var photoItem: PhotosPickerItem?
    @State private var preparing = false
    @State private var pickError: String?
    @State private var editing: String?
    @State private var dropTargeted = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                options
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
            case .failure(let error): pickError = error.localizedDescription
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
        .alert("Can't open that video", isPresented: Binding(get: { pickError != nil }, set: { if !$0 { pickError = nil } })) {
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

    private var isCompact: Bool {
        #if os(iOS)
        sizeClass == .compact
        #else
        false
        #endif
    }

    // MARK: - Options

    @ViewBuilder private var options: some View {
        let cards = Group {
            OptionCard(symbol: "record.circle", title: "Record a Take", line: recordLine) { showRecorder = true }
            #if os(iOS)
            PhotosPicker(selection: $photoItem, matching: .videos, preferredItemEncoding: .current) {
                OptionCardLabel(symbol: "photo.on.rectangle", title: "Choose from Photos",
                                line: "Pick a video you already recorded.")
            }
            .buttonStyle(.plain)
            OptionCard(symbol: "folder", title: "Choose from Files", line: "Pick a video from Files or a drive.") {
                showImporter = true
            }
            #else
            OptionCard(symbol: "folder", title: "Choose a File", line: "Or drop a video on this window.") {
                showImporter = true
            }
            #endif
        }
        if isCompact {
            VStack(spacing: HOSpace.m) { cards }
        } else {
            HStack(alignment: .top, spacing: HOSpace.l) { cards }
        }
        if model.hub == nil {
            Label("Connect to a hub in Settings to make lessons.", systemImage: "desktopcomputer")
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink2)
        }
    }

    private var recordLine: String {
        #if os(iOS)
        GlassesFeature.isEnabled
            ? "Use this iPhone or your Ray-Ban Meta glasses. Talk through each step."
            : "Use this iPhone and talk through each step."
        #else
        "Use this Mac's camera or Continuity Camera."
        #endif
    }

    // MARK: - Your lessons

    @ViewBuilder private var yourLessons: some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            Text("Your Lessons").sectionHeaderStyle(theme)
            if flow.isWorking || flow.phase == .failed {
                Button { showSheet = true } label: { processingRow }.buttonStyle(.plain)
            }
            if lessons.items.isEmpty && !flow.isWorking {
                if lessons.phase == .loaded || model.isPreview {
                    HOEmptyState(symbol: "video.badge.plus", title: "No lessons yet",
                                 message: "Record a task once while you talk through it. HandOver cuts it into steps.")
                }
            } else if !lessons.items.isEmpty {
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
                guard let video = try await item.loadTransferable(type: TeachVideoTransfer.self) else {
                    pickError = "That item is not a video."
                    return
                }
                picked(TeachPickedVideo(url: video.url))
            } catch {
                pickError = error.localizedDescription
            }
        }
    }

    private func picked(_ video: TeachPickedVideo) {
        guard !flow.isWorking else {
            pickError = "A lesson is still uploading. Wait for it to finish, then pick the next video."
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
        HStack(alignment: .top, spacing: HOSpace.m) {
            Image(systemName: symbol)
                .font(.title2)
                .foregroundStyle(theme.colors.accentInk)
                .frame(width: 44, height: 44)
                .background(theme.colors.accentSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text(title).font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                Text(line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .raisedCard()
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
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
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(theme.colors.ink3)
                .accessibilityHidden(true)
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

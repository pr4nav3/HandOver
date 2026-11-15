@preconcurrency import AVFoundation
import AVKit
import PhotosUI
import SwiftUI

/// Record a take (SCREENS.md 12), with the feel of the Camera app: full screen and dark, the shutter, a red timer
/// pill, the narration meter, a white blink on start (not with Reduce Motion), heavy and medium impacts on start
/// and stop, pause and resume, then a review sheet with "Make Course". On iPhone it also offers "Recorded on
/// your glasses? Import it", and, behind a feature flag, the glasses as a source. On Mac it records from the
/// built-in camera, Continuity Camera or Desk View.
struct RecordView: View {
    var onMakeCourse: (URL, String) -> Void
    /// A video imported from Photos; the caller asks for its title.
    var onImport: (URL) -> Void
    @State private var model: RecordModel
    @State private var glasses: GlassesController?
    private let previewLayer: AVCaptureVideoPreviewLayer?
    private let isPreview: Bool

    init(onMakeCourse: @escaping (URL, String) -> Void, onImport: @escaping (URL) -> Void) {
        self.onMakeCourse = onMakeCourse
        self.onImport = onImport
        let recorder = CameraRecorder()
        previewLayer = recorder.previewLayer
        _model = State(initialValue: RecordModel(engine: recorder))
        _glasses = State(initialValue: GlassesFeature.isEnabled ? GlassesController.make() : nil)
        isPreview = false
    }

    /// Previews and snapshots: a model without a camera.
    init(preview model: RecordModel, glasses: GlassesController? = nil) {
        onMakeCourse = { _, _ in }
        onImport = { _ in }
        previewLayer = nil
        _model = State(initialValue: model)
        _glasses = State(initialValue: glasses)
        isPreview = true
    }

    var body: some View {
        RecordScreen(model: model, glasses: glasses, previewLayer: previewLayer, isPreview: isPreview,
                     onMakeCourse: onMakeCourse, onImport: onImport, phoneEngine: model.engine)
    }
}

private struct RecordScreen: View {
    enum Source: String, CaseIterable { case phone, glasses }

    @Bindable var model: RecordModel
    var glasses: GlassesController?
    var previewLayer: AVCaptureVideoPreviewLayer?
    var isPreview: Bool
    var onMakeCourse: (URL, String) -> Void
    var onImport: (URL) -> Void
    /// The phone camera, to come back to from the glasses.
    var phoneEngine: any RecordCaptureEngine

    @Environment(\.dismiss) private var dismiss
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.openURL) private var openURL
    @State private var source: Source = .phone
    @State private var blink = false
    @State private var confirmClose = false
    @State private var showReview = false
    @State private var importItem: PhotosPickerItem?
    @State private var importing = false
    @State private var thumbnail: CGImage?
    /// Why the recorder moved from the glasses to the phone camera on its own.
    @State private var fallbackNotice: String?

    var body: some View {
        GeometryReader { geo in
            let landscape = geo.size.width > geo.size.height * 1.15
            ZStack {
                theme.colors.stage.ignoresSafeArea()
                preview.ignoresSafeArea()
                Color.white.opacity(blink ? 0.85 : 0).ignoresSafeArea().allowsHitTesting(false)
                if landscape { landscapeControls } else { portraitControls }
                if let overlay = accessOverlay { overlay }
                if importing { ProgressView("Preparing video").padding(HOSpace.xl).hoGlassPanel() }
            }
        }
        .environment(\.colorScheme, .dark)
        .preferredColorScheme(.dark)
        .statusBarHiddenIfiOS()
        .task {
            guard !isPreview else { return }
            await model.prepare()
        }
        .onDisappear {
            model.shutdown()
            glasses?.stop()
        }
        .onChange(of: model.startCount) {
            Haptics.impact(.heavy)
            guard !reduceMotion else { return }
            blink = true
            withAnimation(.easeOut(duration: 0.25)) { blink = false }
        }
        .onChange(of: model.stopCount) { Haptics.impact(.medium) }
        .onChange(of: model.phase) { _, phase in
            if phase == .review { showReview = true }
        }
        .onChange(of: model.latestTake) { _, take in
            guard let take else { thumbnail = nil; return }
            Task { thumbnail = await RecordTakeThumbnail.make(take.url) }
        }
        .onChange(of: importItem) { _, item in if let item { importVideo(item) } }
        .onChange(of: glasses?.state) { _, state in
            guard source == .glasses, let state, GlassesFallback.shouldFallBack(state) else { return }
            fallBackToPhone(state == .lost ? "Glasses disconnected." : "\(state.title).")
        }
        .task(id: glassesConnectKey) {
            // No frame within 15 s of connecting counts as a failure too.
            guard source == .glasses, glasses?.state == .connecting else { return }
            try? await Task.sleep(for: GlassesFallback.connectTimeout)
            if !Task.isCancelled, source == .glasses, glasses?.state == .connecting {
                fallBackToPhone("No video arrived from the glasses.")
            }
        }
        .overlay(alignment: .top) {
            if let fallbackNotice {
                HOBanner(symbol: "eyeglasses", tone: .caution, text: fallbackNotice, actionTitle: "OK") {
                    self.fallbackNotice = nil
                }
                .padding(.horizontal, HOSpace.l)
                .padding(.top, 64)
            }
        }
        .confirmationDialog("Stop and discard this take?", isPresented: $confirmClose, titleVisibility: .visible) {
            Button("Discard", role: .destructive) {
                Haptics.warning()
                Task {
                    await model.discardRecording()
                    dismiss()
                }
            }
            Button("Keep Recording", role: .cancel) {}
        }
        .sheet(isPresented: $showReview, onDismiss: { model.keepAndContinue() }) {
            if let take = model.latestTake {
                ReviewTakeSheet(take: take,
                                onMakeCourse: { title in
                                    showReview = false
                                    onMakeCourse(take.url, title)
                                },
                                onRecordAgain: {
                                    showReview = false
                                    model.discardLatest()
                                })
            }
        }
        #if os(iOS)
        .onCameraCaptureEvent { event in
            // Volume buttons start and stop, as in the Camera app.
            if event.phase == .ended { Task { await model.shutter() } }
        }
        #endif
    }

    // MARK: - Preview

    @ViewBuilder private var preview: some View {
        if source == .glasses, let glasses {
            if let frame = glasses.frame {
                Image(decorative: frame, scale: 1).resizable().aspectRatio(contentMode: .fit)
            } else {
                theme.colors.stage
            }
        } else if let previewLayer {
            RecordCameraPreview(layer: previewLayer)
        } else {
            theme.colors.stage
        }
    }

    // MARK: - Layouts

    private var portraitControls: some View {
        VStack(spacing: HOSpace.m) {
            topBar
            if model.isRecording { meter }
            Spacer()
            if source == .glasses, let glasses {
                if glasses.state.isStreaming {
                    RecordGlassesChip(state: glasses.state)
                } else {
                    RecordGlassesCard(controller: glasses) { source = .phone }
                        .padding(.horizontal, HOSpace.l)
                }
            }
            if model.takes.isEmpty && !model.isRecording && model.phase == .ready {
                Text("Say each step out loud as you do it. Pause between steps.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(.white.opacity(0.7))
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, HOSpace.xl)
            }
            if !model.isRecording { glassesImport }
            if glasses != nil && !model.isRecording { sourceSwitcher }
            bottomRow
        }
        .padding(.vertical, HOSpace.m)
    }

    private var landscapeControls: some View {
        HStack {
            VStack(alignment: .leading) {
                closeButton
                Spacer()
                if !model.isRecording { glassesImport }
            }
            Spacer()
            VStack(spacing: HOSpace.s) {
                if model.isRecording {
                    RecordTimerPill(elapsed: { model.elapsed() }, paused: model.phase == .paused)
                    meter
                } else if model.takes.isEmpty && model.phase == .ready {
                    Text("Say each step out loud as you do it. Pause between steps.")
                        .font(theme.fonts.footnote)
                        .foregroundStyle(.white.opacity(0.7))
                        .padding(.horizontal, HOSpace.m)
                        .padding(.vertical, HOSpace.xs)
                        .hoGlassCapsule()
                }
                Spacer()
            }
            Spacer()
            VStack(spacing: HOSpace.xl) {
                trailingButton
                RecordShutterButton(mode: shutterMode) { Task { await model.shutter() } }
                lastTakeButton
            }
        }
        .padding(HOSpace.l)
    }

    private var topBar: some View {
        ZStack {
            if model.isRecording {
                RecordTimerPill(elapsed: { model.elapsed() }, paused: model.phase == .paused)
            }
            HStack {
                closeButton
                Spacer()
                trailingButton
            }
        }
        .padding(.horizontal, HOSpace.l)
    }

    private var closeButton: some View {
        Button {
            if model.isRecording { confirmClose = true } else { dismiss() }
        } label: {
            Image(systemName: "xmark").font(.body.weight(.semibold)).foregroundStyle(.white)
                .frame(width: HOSize.iconButton, height: HOSize.iconButton)
                .hoGlassCapsule(interactive: true)
                .frame(width: HOSize.touch, height: HOSize.touch)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Close")
        .keyboardShortcut(.cancelAction)
    }

    /// Pause and resume while recording; the camera menu on Mac when idle.
    @ViewBuilder private var trailingButton: some View {
        if model.isRecording && model.engine.canPause && source == .phone {
            Button {
                if model.phase == .paused { model.resume() } else { model.pause() }
                Haptics.tap()
            } label: {
                Image(systemName: model.phase == .paused ? "play.fill" : "pause.fill")
                    .font(.body.weight(.semibold)).foregroundStyle(.white)
                    .frame(width: HOSize.iconButton, height: HOSize.iconButton)
                    .hoGlassCapsule(interactive: true)
                    .frame(width: HOSize.touch, height: HOSize.touch)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(model.phase == .paused ? "Resume recording" : "Pause recording")
        } else {
            #if os(macOS)
            if model.cameras.count > 1 && !model.isRecording {
                Menu {
                    ForEach(model.cameras) { camera in
                        Button {
                            Task { await model.select(camera) }
                        } label: {
                            Label(camera.name, systemImage: model.camera == camera ? "checkmark" : camera.symbol)
                        }
                    }
                } label: {
                    Label(model.camera?.name ?? "Camera", systemImage: "video")
                        .foregroundStyle(.white)
                        .padding(.horizontal, HOSpace.m)
                        .frame(height: HOSize.iconButton)
                        .hoGlassCapsule(interactive: true)
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .fixedSize()
                .accessibilityLabel("Camera")
            } else {
                Color.clear.frame(width: HOSize.touch, height: HOSize.touch)
            }
            #else
            Color.clear.frame(width: HOSize.touch, height: HOSize.touch)
            #endif
        }
    }

    private var meter: some View {
        VStack(spacing: HOSpace.xs) {
            if model.withAudio {
                RecordLevelMeter(levels: model.levels)
                if model.isSilent {
                    Text("No sound. Check the mic.").font(theme.fonts.footnote).foregroundStyle(.white.opacity(0.7))
                }
            } else {
                Label("Recording without sound", systemImage: "mic.slash")
                    .font(theme.fonts.footnote).foregroundStyle(.white.opacity(0.7))
            }
        }
    }

    private var bottomRow: some View {
        HStack {
            lastTakeButton.frame(maxWidth: .infinity)
            RecordShutterButton(mode: shutterMode) { Task { await model.shutter() } }
            flipButton.frame(maxWidth: .infinity)
        }
        .padding(.horizontal, HOSpace.xl)
    }

    private var shutterMode: RecordShutterButton.Mode {
        switch model.phase {
        case .recording, .paused: .recording
        case .finishing: .finishing
        case .ready, .review: source == .glasses && !(glasses?.state.isStreaming ?? false) ? .disabled : .ready
        default: .disabled
        }
    }

    @ViewBuilder private var lastTakeButton: some View {
        if model.latestTake != nil && !model.isRecording {
            Button { showReview = true } label: {
                Group {
                    if let thumbnail {
                        Image(decorative: thumbnail, scale: 1).resizable().aspectRatio(contentMode: .fill)
                    } else {
                        Image(systemName: "film").foregroundStyle(.white.opacity(0.7))
                    }
                }
                .frame(width: 48, height: 48)
                .background(Color(white: 0.15))
                .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous).strokeBorder(.white.opacity(0.6), lineWidth: 1))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Last take, \(RecordModel.clock(model.latestTake?.duration ?? 0))")
        } else {
            Color.clear.frame(width: 48, height: 48)
        }
    }

    @ViewBuilder private var flipButton: some View {
        #if os(iOS)
        if source == .phone && model.cameras.count > 1 && !model.isRecording {
            Button {
                guard let current = model.camera, let index = model.cameras.firstIndex(of: current) else { return }
                Task { await model.select(model.cameras[(index + 1) % model.cameras.count]) }
            } label: {
                Image(systemName: "arrow.triangle.2.circlepath.camera")
                    .font(.title3).foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .hoGlassCapsule(interactive: true)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Flip camera")
        } else {
            Color.clear.frame(width: 48, height: 48)
        }
        #else
        Color.clear.frame(width: 48, height: 48)
        #endif
    }

    private var sourceSwitcher: some View {
        Picker("Source", selection: $source) {
            Label("iPhone", systemImage: "iphone").tag(Source.phone)
            Label("Glasses", systemImage: "eyeglasses").tag(Source.glasses)
        }
        .pickerStyle(.segmented)
        .frame(maxWidth: 260)
        .disabled(model.isRecording)
        .onChange(of: source) { _, new in
            Haptics.tap()
            guard !isPreview else { return }
            Task {
                if new == .glasses, let glasses {
                    fallbackNotice = nil
                    await model.use(engine: GlassesCaptureEngine(controller: glasses))
                } else {
                    await model.use(engine: phoneEngine)
                }
            }
        }
    }

    /// "Recorded on your glasses? Import it": Meta glasses clips land in Photos through the Meta AI app.
    @ViewBuilder private var glassesImport: some View {
        #if os(iOS)
        PhotosPicker(selection: $importItem, matching: .videos, preferredItemEncoding: .current) {
            GlassesImportLabel()
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Recorded on your glasses? Import it from Photos")
        #endif
    }

    private func importVideo(_ item: PhotosPickerItem) {
        importing = true
        Task {
            defer {
                importing = false
                importItem = nil
            }
            guard let video = try? await item.loadTransferable(type: TeachVideoTransfer.self) else { return }
            onImport(video.url)
        }
    }

    private var glassesConnectKey: String { "\(source)|\(String(describing: glasses?.state))" }

    /// Moves to the phone camera when the glasses fail. A take in progress is kept (it stops and opens in review);
    /// the camera never changes silently: the banner says what happened.
    private func fallBackToPhone(_ why: String) {
        Haptics.warning()
        Task {
            if model.isRecording {
                await model.stopRecording()
                fallbackNotice = "\(why) The take so far is kept. Switched to the iPhone camera."
            } else {
                fallbackNotice = "\(why) Switched to the iPhone camera."
            }
            glasses?.stop()
            source = .phone
        }
    }

    // MARK: - Permissions and errors (SCREENS.md 12.3)

    private var accessOverlay: AnyView? {
        switch model.phase {
        case .needsAccess(let camera, let microphone):
            if camera {
                return AnyView(notice(symbol: "video.slash", text: "HandOver needs the camera to record a take.") {
                    Button("Open Settings") { openSettings(camera: true) }.buttonStyle(HOButtonStyle(.primary))
                })
            }
            if microphone {
                return AnyView(notice(symbol: "mic.slash",
                                      text: "HandOver needs the microphone to record your narration. Steps are found from what you say.") {
                    VStack(spacing: HOSpace.s) {
                        Button("Open Settings") { openSettings(camera: false) }.buttonStyle(HOButtonStyle(.primary))
                        Button("Record Without Sound") { Task { await model.continueWithoutSound() } }
                            .buttonStyle(HOButtonStyle(.quiet, onVideo: true))
                        Text("Without narration, HandOver can only guess the steps.")
                            .font(theme.fonts.footnote).foregroundStyle(.white.opacity(0.7))
                    }
                })
            }
            return nil
        case .failed(let message):
            return AnyView(notice(symbol: "exclamationmark.triangle", text: message) {
                Button("Try Again") { Task { await model.prepare() } }.buttonStyle(HOButtonStyle(.secondary))
            })
        default:
            return nil
        }
    }

    private func notice<Actions: View>(symbol: String, text: String, @ViewBuilder actions: () -> Actions) -> some View {
        VStack(spacing: HOSpace.m) {
            Image(systemName: symbol).font(.largeTitle.weight(.light)).foregroundStyle(.white.opacity(0.8))
            Text(text).font(theme.fonts.body).foregroundStyle(.white).multilineTextAlignment(.center)
                .frame(maxWidth: 320)
            actions()
        }
        .padding(HOSpace.xl)
    }

    private func openSettings(camera: Bool) {
        #if os(iOS)
        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        #else
        let pane = camera ? "Privacy_Camera" : "Privacy_Microphone"
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") { openURL(url) }
        #endif
    }
}

/// The compact glasses chip once frames arrive (SCREENS.md 12.2): measured size and rate, a good dot, and the
/// Experimental label.
struct RecordGlassesChip: View {
    var state: GlassesState
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.s) {
            Circle().fill(theme.colors.good).frame(width: 7, height: 7)
            Text(state.title)
            Text(GlassesFeature.experimentalLabel)
                .font(theme.fonts.badge)
                .padding(.horizontal, HOSpace.xs + 2)
                .padding(.vertical, 2)
                .overlay(Capsule().strokeBorder(.white.opacity(0.5), lineWidth: 1))
        }
        .font(theme.fonts.callout.monospacedDigit())
        .foregroundStyle(.white)
        .padding(.horizontal, HOSpace.m)
        .frame(minHeight: HOSize.controlSmall)
        .hoGlassCapsule()
        .accessibilityElement(children: .combine)
    }
}

/// "Recorded on your glasses? Import it" in a glass capsule.
struct GlassesImportLabel: View {
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.s) {
            Image(systemName: "eyeglasses")
            Text("Recorded on your glasses? ") + Text("Import it").fontWeight(.semibold)
        }
        .font(theme.fonts.callout)
        .foregroundStyle(.white)
        .padding(.horizontal, HOSpace.m)
        .frame(minHeight: HOSize.controlSmall)
        .hoGlassCapsule(interactive: true)
    }
}

/// Review take (SCREENS.md 12.4): plays the take, a title, "Make Course", "Record Again" and Share.
struct ReviewTakeSheet: View {
    var take: RecordTake
    var onMakeCourse: (String) -> Void
    var onRecordAgain: () -> Void
    @State private var title: String
    @State private var confirmDiscard = false
    @State private var player: AVPlayer
    @Environment(\.theme) private var theme

    init(take: RecordTake, onMakeCourse: @escaping (String) -> Void, onRecordAgain: @escaping () -> Void) {
        self.take = take
        self.onMakeCourse = onMakeCourse
        self.onRecordAgain = onRecordAgain
        _title = State(initialValue: RecordModel.defaultTitle(take.recordedAt))
        _player = State(initialValue: AVPlayer(url: take.url))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: HOSpace.l) {
                    VideoPlayer(player: player)
                        .aspectRatio(16 / 9, contentMode: .fit)
                        .clipShape(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
                    Text(RecordModel.clock(take.duration)).font(theme.fonts.callout.monospacedDigit())
                        .foregroundStyle(theme.colors.ink2)
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        Text("Title").sectionHeaderStyle(theme)
                        TextField("Title", text: $title)
                            .textFieldStyle(.roundedBorder)
                    }
                    Button("Make Course") { onMakeCourse(title) }
                        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                        .keyboardShortcut(.defaultAction)
                    Button("Record Again") { confirmDiscard = true }
                        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                    ShareLink(item: take.url) { Label("Share", systemImage: "square.and.arrow.up") }
                        .buttonStyle(HOButtonStyle(.quiet, fullWidth: true))
                }
                .padding(HOSpace.l)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("Review Take")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .confirmationDialog("Discard this take?", isPresented: $confirmDiscard, titleVisibility: .visible) {
                Button("Discard", role: .destructive) {
                    Haptics.warning()
                    onRecordAgain()
                }
            }
            .onDisappear { player.pause() }
        }
        #if os(iOS)
        .presentationDetents([.large])
        #else
        .frame(minWidth: 520, minHeight: 560)
        #endif
    }
}

private extension View {
    @ViewBuilder func statusBarHiddenIfiOS() -> some View {
        #if os(iOS)
        statusBarHidden()
        #else
        self
        #endif
    }
}

/// A camera that is not there, for previews and snapshots.
@MainActor
final class RecordPreviewEngine: RecordCaptureEngine {
    var level: Float = 0.4
    func requestAccess() async -> RecordCaptureAccess { RecordCaptureAccess(camera: true, microphone: true) }
    func start(camera: RecordCamera?, withAudio: Bool) async throws {}
    func stopSession() {}
    func startRecording(to url: URL) throws {}
    func stopRecording() async throws -> URL { URL(fileURLWithPath: "/dev/null") }
    var canPause: Bool { true }
    func pauseRecording() {}
    func resumeRecording() {}
    func audioLevel() -> Float? { level }
    func cameras() -> [RecordCamera] { [RecordCamera(id: "back", name: "Back Camera", kind: .back)] }
}

#Preview("Record, idle") {
    let model = RecordModel(engine: RecordPreviewEngine())
    model.preview(phase: .ready)
    return RecordView(preview: model)
}

#Preview("Record, recording") {
    let model = RecordModel(engine: RecordPreviewEngine())
    model.preview(phase: .recording, elapsed: 42, levels: (0..<24).map { Float(abs(sin(Double($0) / 3))) * 0.8 })
    return RecordView(preview: model)
}

#Preview("Record, glasses") {
    let model = RecordModel(engine: RecordPreviewEngine())
    model.preview(phase: .ready)
    return RecordView(preview: model, glasses: GlassesController(state: .notRegistered))
}

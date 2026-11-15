import AVFoundation
import SwiftUI
#if os(iOS)
import GameController
import UIKit
#endif

/// The core screen (SCREENS.md 7): the expert's clip and the learner's camera, the step, the status badge, the
/// mistake card and Back and Next. iPhone portrait (and iPad under 700 points wide) shows the clip large with
/// the camera as a FaceTime style tile; landscape, iPad and Mac show them side by side.
///
/// `LearnRunScreen` passes `usesOwnCamera` and the preview it draws when this device (or its glasses) is the
/// camera; with it on, the live pane shows that preview instead of the hub's forwarded frames.
struct LearnView: View {
    @Binding var usesOwnCamera: Bool
    var ownCameraPreview: AnyView?
    /// Shows the X. It asks "End this lesson?" first while a lesson is under way.
    var onClose: (() -> Void)?
    var onLibrary: (() -> Void)?
    /// Adds "Change Camera" to the More menu.
    var onChangeCamera: (() -> Void)?
    /// A banner about the camera (glasses fell back, another device took over, waiting for the other camera).
    var notice: LearnNotice?
    /// The live pane's chip when this device sends its own frames (for example "Glasses").
    var ownChip: SourceChip?

    @Environment(AppModel.self) private var model
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.learnLayoutOverride) private var layoutOverride
    #if os(iOS)
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    #endif
    @State private var layout: LearnLayout = .pip

    @State private var clips: ClipController
    @State private var recorder = RunRecorder()
    @State private var result: StepResult?
    @State private var resultID = 0
    @State private var flashVerified = false
    @State private var flashID = 0
    @State private var holdChecking = false
    @State private var checkingSince: Date?
    @State private var lastFrame: CGImage?
    @State private var showSteps = false
    @State private var sidebarOpen: Bool?
    @State private var toast: ToastItem?
    @State private var doneSummary: RunSummary?
    @State private var confirmClose = false
    @State private var seenFirstState = false
    @State private var shownMistake: MistakeMessage?
    @State private var guide = SpokenGuide.shared

    @AppStorage(LearnSettings.captionsKey) private var captionsOn = true
    @AppStorage(LearnSettings.stepResultsKey) private var stepResultsOn = true
    @AppStorage(LearnSettings.speakMistakesKey) private var speakMistakes = LearnSettings.speakMistakesDefault
    @AppStorage(LearnSettings.pipCornerKey) private var pipCornerRaw = PiPCorner.bottomTrailing.rawValue
    @AppStorage(LearnSettings.liveLargeKey) private var liveLarge = false
    @AppStorage(LearnSettings.pipHiddenKey) private var pipHidden = false
    @AppStorage(LearnSettings.clipFirstKey) private var clipFirst = false

    init(usesOwnCamera: Binding<Bool> = .constant(false), ownCameraPreview: AnyView? = nil,
         onClose: (() -> Void)? = nil, onLibrary: (() -> Void)? = nil, onChangeCamera: (() -> Void)? = nil,
         notice: LearnNotice? = nil, ownChip: SourceChip? = nil, clips: ClipController? = nil,
         recorder: RunRecorder? = nil) {
        _usesOwnCamera = usesOwnCamera
        self.ownCameraPreview = ownCameraPreview
        self.onClose = onClose
        self.onLibrary = onLibrary
        self.onChangeCamera = onChangeCamera
        self.notice = notice
        self.ownChip = ownChip
        _clips = State(initialValue: clips ?? ClipController())
        _recorder = State(initialValue: recorder ?? RunRecorder())
    }

    // MARK: - Derived

    private var state: HubState { model.state }
    private var lesson: Lesson? { model.lesson }
    private var step: Step? { model.currentStep }
    private var hasLesson: Bool { state.hasLesson && lesson != nil }
    private var mistakeKind: MistakeKind? { model.mistake.map(MistakeKind.init) }
    private var resolvedStatus: LearnStatus { LearnStatus.resolve(state, step: step, flashVerified: flashVerified) }
    /// The badge on screen: the resolved status, or Checking while it is held for its 0.6 s minimum.
    private var shownStatus: LearnStatus { holdChecking ? .checking : resolvedStatus }
    private var isLastStep: Bool { state.total > 0 && state.step == state.total - 1 && !state.isDone }

    /// Progress (0 to 1) and stage from the real-time understanding work, when the hub sends them. The Core
    /// state does not decode these fields yet, so this is nil and nothing shows until it does.
    private var understanding: (progress: Double?, stage: String?)? { nil }

    private var pipCorner: Binding<PiPCorner> {
        Binding { PiPCorner(rawValue: pipCornerRaw) ?? .bottomTrailing } set: { pipCornerRaw = $0.rawValue }
    }

    private var liveSource: LiveSource {
        if !model.connection.isConnected && !model.isPreview { return .reconnecting }
        if usesOwnCamera, let ownCameraPreview { return .own(ownCameraPreview) }
        if let frame = model.frame { return .hub(frame.image) }
        if lastFrame != nil, !state.cameraConnected { return .lost(lastFrame) }
        return state.cameraConnected ? .lost(nil) : .waiting
    }

    private var sourceChip: SourceChip? {
        if usesOwnCamera, let ownChip { return ownChip }
        return SourceChip.from(camera: state.camera, ownCamera: usesOwnCamera)
    }

    private func url(_ path: String?) -> URL? { path.flatMap { model.mediaURL($0) } }

    /// iPhone landscape (and any short window on a touch device).
    private var isCompactHeight: Bool {
        #if os(iOS)
        verticalSizeClass == .compact
        #else
        false
        #endif
    }

    // MARK: - Body

    var body: some View {
        GeometryReader { geo in
            let layout = layoutOverride ?? LearnLayout.pick(size: geo.size, compactHeight: isCompactHeight)
            ZStack {
                switch layout {
                case .pip: pipLayout(screen: geo.size)
                case .sideBySide(phone: true): phoneLandscapeLayout(size: geo.size)
                case .sideBySide(phone: false): sideBySideLayout(size: geo.size)
                }
                if let doneSummary {
                    DoneView(summary: doneSummary, lessonId: state.lessonId, runId: nil,
                             onGoto: { model.goto(step: $0) }, onStartOver: { model.goto(step: 0) },
                             onLibrary: onLibrary, isStill: clips.isStill)
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom))
                        .zIndex(2)
                }
            }
            .animation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion), value: doneSummary != nil)
            .onChange(of: layout, initial: true) { _, new in self.layout = new }
        }
        .hoPaperBackground()
        .hoToast($toast)
        .background(shortcuts)
        #if os(iOS)
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .statusBarHidden(false)
        #endif
        .navigationTitle(lesson?.title ?? "Learn")
        .sheet(isPresented: $showSteps) { stepsSheet }
        .confirmationDialog("End this lesson?", isPresented: $confirmClose, titleVisibility: .visible) {
            Button("End Lesson", role: .destructive) { onClose?() }
            Button("Keep Going", role: .cancel) {}
        } message: {
            Text("You go back to Home. You can start it again any time.")
        }
        .onChange(of: state, initial: true) { old, new in stateChanged(from: old, to: new) }
        .onChange(of: model.session.cameraAdvances) { _, _ in cameraAdvanced() }
        .onChange(of: model.mistake) { _, new in mistakeChanged(new) }
        .onChange(of: guide.isSpeaking) { _, speaking in clips.isDucked = speaking }
        .onChange(of: model.connection) { _, new in recorder.connection(new.isConnected, at: Date()) }
        .onChange(of: model.frame?.receivedAt) { _, _ in if let f = model.frame { lastFrame = f.image } }
        .onChange(of: state.lessonId) { _, _ in lastFrame = nil }
        .onChange(of: model.session.lastError) { _, new in
            if let new {
                toast = ToastItem(text: new, symbol: "exclamationmark.triangle", tone: .caution)
                model.clearError()
            }
        }
        .onChange(of: clipKey, initial: true) { _, _ in updateClip() }
        .onChange(of: preloadKey, initial: true) { _, _ in preloadNext() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, doneSummary == nil { clips.resume() } else if phase == .background { clips.pause() }
        }
        .task(id: resolvedStatus) { await settleStatus() }
        .task(id: resultID) {
            guard result != nil else { return }
            try? await Task.sleep(for: .seconds(1.5))
            withAnimation(HOMotion.resolve(HOMotion.snappy, reduceMotion: reduceMotion)) { result = nil }
        }
        .task(id: flashID) {
            guard flashVerified else { return }
            try? await Task.sleep(for: .seconds(1.8))
            flashVerified = false
        }
        .onAppear {
            #if os(iOS)
            UIApplication.shared.isIdleTimerDisabled = true
            #endif
        }
        .onDisappear {
            #if os(iOS)
            UIApplication.shared.isIdleTimerDisabled = false
            #endif
            clips.stop()
            guide.stop()
        }
    }

    // MARK: - iPhone portrait

    @ViewBuilder
    private func pipLayout(screen: CGSize) -> some View {
        let clipIsTile = liveLarge
        VStack(spacing: 0) {
            progressBar(tappable: false).padding(.horizontal, HOSpace.l).padding(.top, HOSpace.xs)
            topBar(onVideo: false).padding(.horizontal, HOSpace.l)
            banner.padding(.horizontal, HOSpace.l)
            GeometryReader { pane in
                let size = pane.size
                let tile = tileSize(screen: screen, pane: size, clipIsTile: clipIsTile)
                let inset = !clipIsTile && !pipHidden && !pipCorner.wrappedValue.isTop ? tile.height + HOSpace.xs : 0
                ZStack {
                    if clipIsTile { live(radius: HORadius.card) } else { clip(radius: HORadius.card, tile: false, captionInset: inset) }
                    if !pipHidden {
                        PiPTile(container: size, tileSize: tile,
                                corner: pipCorner, label: clipIsTile ? "Expert clip" : "Your camera",
                                onSwap: swap, onHide: { pipHidden = true }) {
                            if clipIsTile { clip(radius: HORadius.pip, tile: true) } else { live(radius: HORadius.pip, tile: true) }
                        }
                    } else {
                        showPreviewButton(in: size)
                    }
                    clipOverlays(showRecording: !clipIsTile)
                }
                .hoAnimation(HOMotion.layout, value: liveLarge)
            }
            .frame(minHeight: screen.height * 0.4)
            .padding(.horizontal, HOSpace.l)
            .padding(.top, HOSpace.s)
            if clipIsTile, captionsOn, let caption = clips.caption {
                CaptionBar(text: caption)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, HOSpace.xs)
                    .background(theme.colors.stage)
                    .padding(.horizontal, HOSpace.l)
            }
            stepInfo(oneLine: false)
                .padding(.horizontal, HOSpace.l)
                .padding(.top, HOSpace.m)
            mistakeSlot(compact: true, overVideo: false)
                .padding(.horizontal, HOSpace.l)
            controlsTray(compactBack: true)
                .padding(.horizontal, HOSpace.l)
                .padding(.vertical, HOSpace.m)
        }
        .hoAnimation(HOMotion.layout, value: model.mistake != nil)
    }

    private func tileSize(screen: CGSize, pane: CGSize, clipIsTile: Bool) -> CGSize {
        let width = min(pane.width * 0.45, max(HOSize.pipMinWidth, screen.width * HOSize.pipFraction))
        let aspect: CGFloat
        if clipIsTile {
            aspect = 16 / 9
        } else if let f = model.frame?.size, f.height > 0 {
            aspect = f.width / f.height
        } else {
            aspect = 3 / 4
        }
        return CGSize(width: width, height: min(pane.height * 0.5, width / aspect))
    }

    private func showPreviewButton(in size: CGSize) -> some View {
        let corner = pipCorner.wrappedValue
        let c = corner.center(tile: CGSize(width: HOSize.touch, height: HOSize.touch), in: size, inset: HOSpace.m)
        return Button { Haptics.tap(); pipHidden = false } label: { Image(systemName: "pip.exit") }
            .buttonStyle(HOIconButtonStyle(onVideo: true))
            .accessibilityLabel("Show Preview")
            .position(c)
    }

    private func swap() {
        withAnimation(HOMotion.resolve(HOMotion.layout, reduceMotion: reduceMotion)) { liveLarge.toggle() }
    }

    // MARK: - iPhone landscape

    /// The clip large on the leading side; a column on the trailing side with End, Steps and More, the live
    /// camera tile, the step and its status (scrolls when the text is long), and Back and Next. Everything sits
    /// inside the safe area, so the Dynamic Island and the home indicator never cover a control. Swap puts the
    /// camera in the large pane and the clip in the tile, as on iPhone portrait.
    @ViewBuilder
    private func phoneLandscapeLayout(size: CGSize) -> some View {
        let column = LearnLayout.phoneColumnWidth(for: size.width)
        let clipIsTile = liveLarge
        HStack(alignment: .top, spacing: HOSpace.m) {
            VStack(spacing: HOSpace.s) {
                progressBar(tappable: false)
                banner
                ZStack(alignment: .bottom) {
                    if clipIsTile {
                        live(radius: HORadius.card)
                    } else {
                        clip(radius: HORadius.card, tile: false, hideCaption: model.mistake != nil && !state.isDone)
                    }
                    clipOverlays(showRecording: !clipIsTile)
                    mistakeSlot(compact: true, overVideo: true).padding(HOSpace.s)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .layoutPriority(1)
            }
            VStack(alignment: .leading, spacing: HOSpace.s) {
                landscapeTopRow
                landscapeTile(width: column, maxHeight: size.height * 0.42, clipIsTile: clipIsTile)
                ScrollView {
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        // The status and its reason come before the general hint, so they show without scrolling.
                        stepInfo(oneLine: false, showsHint: false)
                        badgeBlock.frame(maxWidth: .infinity, alignment: .leading)
                        hintLine.frame(maxWidth: .infinity, alignment: .leading)
                        if clipIsTile, captionsOn, let caption = clips.caption {
                            Text(caption)
                                .font(theme.fonts.footnote)
                                .foregroundStyle(theme.colors.ink2)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityHidden(true)
                        }
                    }
                }
                .scrollBounceBehavior(.basedOnSize)
                .frame(maxHeight: .infinity, alignment: .top)
                navButtons(compactBack: true, minNext: nil)
            }
            .frame(width: column)
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.s)
        .hoAnimation(HOMotion.layout, value: model.mistake != nil)
        .hoAnimation(HOMotion.layout, value: liveLarge)
    }

    /// End, the guide indicator, Steps and More. End is always first, so it never moves off screen.
    private var landscapeTopRow: some View {
        HStack(spacing: HOSpace.xs) {
            if let onClose { closeButton(onClose, onVideo: false) }
            Spacer(minLength: 0)
            SpokenGuideIndicator(guide: guide)
            Button { Haptics.tap(); showSteps = true } label: { Image(systemName: "list.bullet") }
                .buttonStyle(HOIconButtonStyle())
                .accessibilityLabel("Steps")
                .disabled(lesson == nil)
            moreMenu
        }
        .frame(minHeight: HOSize.touch)
    }

    /// The small pane in the column: the live camera (or the clip after Swap). Tap to swap.
    private func landscapeTile(width: CGFloat, maxHeight: CGFloat, clipIsTile: Bool) -> some View {
        let aspect = clipIsTile ? 16 / 9 : LearnLayout.liveAspect(frame: model.frame?.size, ownCamera: usesOwnCamera,
                                                                  landscape: true)
        return Group {
            if clipIsTile { clip(radius: HORadius.pip, tile: true) } else { live(radius: HORadius.pip) }
        }
        .frame(width: width, height: min(maxHeight, width / aspect))
        .overlay(RoundedRectangle(cornerRadius: HORadius.pip, style: .continuous)
            .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
        .contentShape(RoundedRectangle(cornerRadius: HORadius.pip, style: .continuous))
        .onTapGesture {
            Haptics.tap()
            swap()
        }
        .accessibilityElement(children: .ignore)
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel("\(clipIsTile ? "Expert clip" : "Your camera"), small. Double tap to swap.")
        .accessibilityAction { swap() }
    }

    // MARK: - Side by side (iPad and Mac)

    @ViewBuilder
    private func sideBySideLayout(size: CGSize) -> some View {
        let margin = HOSpace.xl
        let gap = HOSpace.l
        let sidebar = (sidebarOpen ?? (size.width >= LearnLayout.sidebarWidthThreshold)) && lesson != nil
        HStack(alignment: .top, spacing: HOSpace.l) {
            if sidebar {
                courseList(compact: true)
                    .frame(width: 300)
                    .hoCard(radius: HORadius.panel)
                    .padding(.vertical, margin)
                    .transition(.move(edge: .leading).combined(with: .opacity))
            }
            VStack(spacing: HOSpace.m) {
                progressBar(tappable: true)
                topBar(onVideo: false)
                banner
                HStack(spacing: gap) {
                    if clipFirst {
                        clipColumn
                        live(radius: HORadius.panel).aspectRatio(Self.paneAspect, contentMode: .fit)
                    } else {
                        live(radius: HORadius.panel).aspectRatio(Self.paneAspect, contentMode: .fit)
                        clipColumn
                    }
                }
                .frame(maxWidth: .infinity)
                .layoutPriority(1)
                stepInfo(oneLine: false).frame(maxWidth: .infinity, alignment: .leading)
                Spacer(minLength: 0)
                mistakeSlot(compact: false, overVideo: false)
                controlsTray(compactBack: false)
            }
            .padding(.horizontal, sidebar ? 0 : margin)
            .padding(.trailing, sidebar ? margin : 0)
            .padding(.vertical, margin)
        }
        .hoAnimation(HOMotion.layout, value: sidebar)
        .hoAnimation(HOMotion.layout, value: model.mistake != nil)
    }

    private var clipColumn: some View {
        ZStack(alignment: .bottom) {
            clip(radius: HORadius.panel, tile: false)
            clipOverlays(showRecording: false)
        }
        .aspectRatio(Self.paneAspect, contentMode: .fit)
    }

    /// Side by side panes are 4:3 at most, so the two videos take the room; video inside is aspect fit.
    static let paneAspect: CGFloat = 4 / 3

    // MARK: - Regions

    private func progressBar(tappable: Bool) -> some View {
        StepProgressBar(total: hasLesson ? state.total : 0, current: state.position,
                        mistakeOnCurrent: mistakeKind?.isBehind == true,
                        onGoto: tappable && hasLesson && model.connection.isConnected ? { model.goto(step: $0) } : nil)
    }

    private func topBar(onVideo: Bool) -> some View {
        HStack(spacing: HOSpace.s) {
            if let onClose { closeButton(onClose, onVideo: onVideo) }
            Text(lesson?.title ?? "Learn")
                .font(theme.fonts.headline)
                .foregroundStyle(theme.colors.ink)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: onClose == nil ? .leading : .center)
                .accessibilityAddTraits(.isHeader)
            SpokenGuideIndicator(guide: guide)
            Button {
                Haptics.tap()
                if layout == .sideBySide(phone: false) {
                    withAnimation(HOMotion.resolve(HOMotion.layout, reduceMotion: reduceMotion)) {
                        sidebarOpen = !(sidebarOpen ?? true)
                    }
                } else {
                    showSteps = true
                }
            } label: { Image(systemName: "list.bullet") }
                .buttonStyle(HOIconButtonStyle())
                .accessibilityLabel("Steps")
                .disabled(lesson == nil)
            moreMenu
        }
        .frame(minHeight: HOSize.touch)
    }

    private func closeButton(_ close: @escaping () -> Void, onVideo: Bool) -> some View {
        Button {
            Haptics.tap()
            if hasLesson && !state.isDone { confirmClose = true } else { close() }
        } label: { Image(systemName: "xmark") }
            .buttonStyle(HOIconButtonStyle(onVideo: onVideo))
            .keyboardShortcut(.cancelAction)
            .accessibilityLabel("End lesson")
    }

    private var moreMenu: some View {
        Menu {
            Toggle("Captions", isOn: $captionsOn)
            Toggle("Mute Clip", isOn: Binding(get: { clips.isMuted }, set: { clips.isMuted = $0 }))
            Toggle("Spoken Guidance", isOn: Binding(get: { guide.isEnabled }, set: { guide.isEnabled = $0 }))
            Button("Swap Videos", systemImage: "arrow.left.arrow.right") { swapVideos() }
            if let onChangeCamera {
                Button("Change Camera", systemImage: "camera") { onChangeCamera() }
            }
            Divider()
            Button("Restart Lesson", systemImage: "arrow.counterclockwise") { model.goto(step: 0) }
                .disabled(!hasLesson || !model.connection.isConnected)
        } label: {
            Image(systemName: "ellipsis")
                .font(.body.weight(.medium))
                .foregroundStyle(theme.colors.ink)
                .frame(width: HOSize.iconButton, height: HOSize.iconButton)
                .background(theme.colors.raised, in: Circle())
                .overlay(Circle().strokeBorder(theme.colors.line, lineWidth: HOLine.width))
                .frame(width: HOSize.touch, height: HOSize.touch)
                .contentShape(Rectangle())
        }
        .menuIndicator(.hidden)
        .buttonStyle(.plain)
        .accessibilityLabel("More")
    }

    private func swapVideos() {
        withAnimation(HOMotion.resolve(HOMotion.layout, reduceMotion: reduceMotion)) {
            clipFirst.toggle()
            liveLarge.toggle()
        }
    }

    @ViewBuilder
    private var banner: some View {
        if model.hub != nil, !model.connection.isConnected, !model.isPreview {
            HOBanner(symbol: "arrow.clockwise", text: "Reconnecting to the hub.")
                .transition(reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity))
        } else if let notice, !state.isDone {
            HOBanner(symbol: notice.symbol, tone: notice.tone, text: notice.text, actionTitle: notice.actionTitle,
                     action: notice.action)
                .transition(reduceMotion ? .opacity : .move(edge: .top).combined(with: .opacity))
        }
    }

    private func clip(radius: CGFloat, tile: Bool, captionInset: CGFloat = 0, hideCaption: Bool = false) -> some View {
        ClipPane(clips: clips, poster: MediaImages.shared.image(url(step?.refFrame)), radius: radius,
                 hasLesson: hasLesson && !state.isDone, stepNumber: step.map { $0.n },
                 captionsOn: captionsOn, showsCaption: !tile && !hideCaption, isTile: tile,
                 captionBottomInset: captionInset)
    }

    private func live(radius: CGFloat, tile: Bool = false) -> some View {
        LivePane(source: liveSource, chip: sourceChip, radius: radius, isTile: tile)
    }

    /// Pills and the step result moment over the clip pane.
    @ViewBuilder
    private func clipOverlays(showRecording: Bool) -> some View {
        let pills = videoPills(showRecording: showRecording)
        ZStack(alignment: .top) {
            VStack(alignment: .leading, spacing: HOSpace.xs) {
                ForEach(pills, id: \.text) { pill in
                    VideoPill(symbol: pill.symbol, text: pill.text, tone: .caution, recordDot: pill.recordDot)
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(HOSpace.s)
            .allowsHitTesting(false)
            if let result {
                StepResultMoment(result: result)
                    .padding(.top, pills.isEmpty ? HOSpace.m : HOSpace.m + 34 * CGFloat(pills.count))
                    .padding(.horizontal, HOSpace.l)
                    .transition(reduceMotion ? .opacity : .scale(scale: 0.96).combined(with: .opacity))
                    .id(resultID)
                    .allowsHitTesting(false)
            }
        }
    }

    struct Pill: Equatable {
        var symbol: String
        var text: String
        var recordDot = false
    }

    /// "Mock checks" when the hub's check mode is mock, "Checks off: <reason>" while checks are off, and
    /// "Recording" when frames come from a file and the live pane's own chip is not on screen.
    static func pills(for state: HubState, showRecording: Bool) -> [Pill] {
        var out: [Pill] = []
        if state.checkMode == .mock { out.append(Pill(symbol: "testtube.2", text: "Mock checks")) }
        if state.checkOffline {
            out.append(Pill(symbol: "exclamationmark.triangle", text: "Checks off: \(offlinePillReason(state.checkOfflineReason))"))
        }
        if showRecording, state.camera?.source == .file || state.camera?.platform == .replay {
            out.append(Pill(symbol: "film", text: "Recording", recordDot: true))
        }
        return out
    }

    static func offlinePillReason(_ reason: HubState.OfflineReason?) -> String {
        switch reason {
        case .noKey?: "No API key"
        case .budget?: "AI budget reached"
        case .rateLimited?: "Rate limited"
        case .errors?: "Check errors"
        default: "Unavailable"
        }
    }

    private func videoPills(showRecording: Bool) -> [Pill] {
        hasLesson && !state.isDone ? Self.pills(for: state, showRecording: showRecording) : []
    }

    private func stepInfo(oneLine: Bool, showsHint: Bool = true) -> some View {
        let title = step.map { $0.title.isEmpty ? "Step \($0.n)" : $0.title }
        return Group {
            if oneLine {
                Text(stepCountText + (title.map { ": \($0)" } ?? ""))
                    .font(theme.fonts.callout.weight(.medium))
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(1)
                    .truncationMode(.tail)
            } else {
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text(stepCountText)
                        .font(theme.fonts.footnote)
                        .foregroundStyle(theme.colors.ink2)
                    Text(title ?? (hasLesson ? " " : "Pick a lesson on Home."))
                        .hoFont(.stepTitle, theme)
                        .foregroundStyle(theme.colors.ink)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .contentTransition(.opacity)
                    if showsHint { hintLine }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .contentShape(Rectangle())
        .gesture(DragGesture(minimumDistance: 24).onEnded { value in
            let dx = value.translation.width, dy = value.translation.height
            if dx > 80, abs(dy) < 60, model.canGoBack { model.back() }
            if dy < -50, abs(dx) < 60, lesson != nil { showSteps = true }
        })
        .accessibilityElement(children: .combine)
        .accessibilityHint(model.canGoBack ? "Swipe right for the previous step" : "")
        .hoAnimation(HOMotion.clip, value: state.step)
    }

    @ViewBuilder
    private var hintLine: some View {
        if let hint = Self.nextHint(shownStatus), hasLesson, step != nil {
            Text(hint)
                .font(theme.fonts.footnote)
                .foregroundStyle(theme.colors.ink2)
                .lineLimit(2)
                .contentTransition(.opacity)
        }
    }

    /// One line under the step title saying what to do now.
    static func nextHint(_ status: LearnStatus) -> String? {
        switch status {
        case .watching, .checking: "Do this step. HandOver moves on when it sees it done."
        case .verified: "Step done. The next one is coming up."
        case .manual, .checksOff, .noCamera: "Do this step, then tap Next."
        case .simulated, .done: nil
        }
    }

    private var stepCountText: String {
        guard hasLesson, state.total > 0 else { return hasLesson ? "Loading lesson" : "No lesson selected" }
        return "Step \(min(state.step + 1, state.total)) of \(state.total)"
    }

    @ViewBuilder
    private func mistakeSlot(compact: Bool, overVideo: Bool) -> some View {
        if let m = model.mistake, let kind = mistakeKind, !state.isDone {
            MistakeCard(kind: kind, message: m.message, compact: compact, overVideo: overVideo,
                        onShowStep: { model.goto(step: $0) }, onDismiss: { model.dismissMistake() })
                .padding(.top, overVideo ? 0 : HOSpace.m)
                .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                .id("\(m.step)|\(m.message)")
        }
    }

    private var badgeBlock: some View {
        VStack(alignment: .leading, spacing: HOSpace.xxs) {
            HStack(spacing: HOSpace.s) {
                StatusBadge(status: shownStatus)
                    .accessibilityAddTraits(.updatesFrequently)
                if let u = understanding { UnderstandingIndicator(progress: u.progress, stage: u.stage) }
            }
            ForEach(Array(LearnStatus.meta(shownStatus, state: state).enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                    .lineLimit(2)
            }
        }
    }

    private func controlsTray(compactBack: Bool) -> some View {
        HStack(alignment: .center, spacing: HOSpace.m) {
            badgeBlock.frame(maxWidth: .infinity, alignment: .leading)
            navButtons(compactBack: compactBack, minNext: compactBack ? nil : 160)
        }
    }

    @ViewBuilder
    private func navButtons(compactBack: Bool, minNext: CGFloat?) -> some View {
        HStack(alignment: .top, spacing: HOSpace.s) {
            if state.position > 0 && hasLesson {
                Button { model.back() } label: {
                    if compactBack {
                        Image(systemName: "chevron.left").frame(width: 20)
                    } else {
                        Label("Back", systemImage: "chevron.left")
                    }
                }
                .buttonStyle(HOButtonStyle(.secondary, size: .large))
                .keyboardShortcut(.leftArrow, modifiers: [])
                .disabled(!model.canGoBack)
                .accessibilityLabel("Back")
                .accessibilityHint(model.connection.isConnected ? "" : "Waiting for the hub")
            }
            VStack(spacing: HOSpace.xxs) {
                Button(isLastStep ? "Finish" : "Next") { model.next() }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: minNext == nil))
                    .frame(minWidth: minNext)
                    .keyboardShortcut(.rightArrow, modifiers: [])
                    .disabled(!model.canGoNext || !hasLesson)
                    .accessibilityHint(model.connection.isConnected ? "" : "Waiting for the hub")
                if showsKeyboardHint {
                    Text("or press Right Arrow")
                        .font(theme.fonts.caption)
                        .foregroundStyle(theme.colors.ink2)
                }
            }
            .frame(maxWidth: minNext == nil ? .infinity : nil)
        }
    }

    private var showsKeyboardHint: Bool {
        guard layout == .sideBySide(phone: false) else { return false }
        #if os(macOS)
        return true
        #else
        return GCKeyboard.coalesced != nil
        #endif
    }

    private func courseList(compact: Bool) -> some View {
        Group {
            if let lesson {
                CourseView(lesson: lesson, statuses: courseStatuses(lesson),
                           yourSeconds: yourSeconds, current: state.isDone ? nil : state.step, compact: compact,
                           thumbnail: { MediaImages.shared.image(url($0.refFrame)) },
                           onGoto: { i in
                               model.goto(step: i)
                               showSteps = false
                           })
            }
        }
    }

    /// This run's statuses; before the first state arrives, the current step is still marked current.
    private func courseStatuses(_ lesson: Lesson) -> [StepStatus] {
        var out = recorder.lessonId == lesson.id && recorder.steps.count == lesson.steps.count
            ? recorder.statuses() : Array(repeating: .notStarted, count: lesson.steps.count)
        if !state.isDone, out.indices.contains(state.step) { out[state.step] = .current }
        return out
    }

    private var yourSeconds: [Int: Double] {
        var out: [Int: Double] = [:]
        for i in recorder.steps.indices { if let s = recorder.seconds(i) { out[i] = s } }
        return out
    }

    private var stepsSheet: some View {
        NavigationStack {
            courseList(compact: false)
                .hoPaperBackground()
                .navigationTitle("Steps")
                #if os(iOS)
                .navigationBarTitleDisplayMode(.inline)
                #endif
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { showSteps = false } }
                }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    /// Space for Next; R replay, M mute, C captions, S swap. Right and Left Arrow are on the buttons.
    private var shortcuts: some View {
        ZStack {
            Button("Next") { if model.canGoNext { model.next() } }.keyboardShortcut(.space, modifiers: [])
            Button("Replay Clip") { clips.replay() }.keyboardShortcut("r", modifiers: [])
            Button("Mute Clip") { clips.isMuted.toggle() }.keyboardShortcut("m", modifiers: [])
            Button("Captions") { captionsOn.toggle() }.keyboardShortcut("c", modifiers: [])
            Button("Swap Videos") { swapVideos() }.keyboardShortcut("s", modifiers: [])
        }
        .opacity(0)
        .frame(width: 0, height: 0)
        .accessibilityHidden(true)
        .allowsHitTesting(false)
    }

    // MARK: - Events

    private var clipKey: String {
        "\(state.lessonId ?? "")|\(state.rev)|\(state.step)|\(state.isDone)|\(lesson?.id ?? "")"
    }

    private var preloadKey: String {
        "\(clipKey)|\(state.nextClip ?? "")"
    }

    private func updateClip() {
        guard let step, hasLesson, !state.isDone else {
            if state.isDone { clips.pause() } else { clips.show(clip: nil, captions: nil) }
            return
        }
        clips.show(clip: url(step.clip), captions: url(step.captions))
        _ = MediaImages.shared.image(url(step.refFrame))
    }

    /// Preloads the next step's clip: `state.next_clip` once the hub has a confident yes, else step + 1.
    private func preloadNext() {
        guard let lesson, hasLesson, !state.isDone else { return }
        let next: Step? = {
            if let path = state.nextClip { return lesson.steps.first { $0.clip == path } }
            return lesson.steps.indices.contains(state.step + 1) ? lesson.steps[state.step + 1] : nil
        }()
        let clipPath = state.nextClip ?? next?.clip
        clips.preload(clip: url(clipPath), captions: url(next?.captions))
        if let next { _ = MediaImages.shared.image(url(next.refFrame)) }
    }

    private func stateChanged(from old: HubState, to new: HubState) {
        let change = recorder.observe(new, advance: model.lastAdvance, at: Date())
        let firstState = !seenFirstState
        seenFirstState = true
        if new.isDone, doneSummary == nil, let lesson, new.lessonId == lesson.id {
            doneSummary = RunSummary(recorder: recorder, lesson: lesson)
            clips.pause()
            AccessibilityNotification.Announcement("Lesson done").post()
            guide.say("Lesson complete", kind: .done)
            return
        }
        if !new.isDone, doneSummary != nil {
            doneSummary = nil
            clips.resume()
        }
        guard !firstState, old.lessonId == new.lessonId else {
            if new.hasLesson { speakStep() }
            return
        }
        if old.position != new.position, change?.reason != .camera {
            Haptics.impact(.medium)
        }
        if let change, let reason = change.reason, change.to < new.total, stepResultsOn, let lesson,
           lesson.steps.indices.contains(change.from) {
            let s = lesson.steps[change.from]
            let expert: Double? = {
                guard let a = s.startSeconds, let b = s.endSeconds, b > a else { return nil }
                return b - a
            }()
            let r = StepResult.make(yours: change.visitSeconds, expert: expert, mistakesFixed: change.mistakes,
                                    byCamera: reason == .camera)
            withAnimation(HOMotion.resolve(HOMotion.snappy, reduceMotion: reduceMotion)) {
                result = r
                resultID += 1
            }
            AccessibilityNotification.Announcement(r.text).post()
            guide.say("Nice.", kind: .result)
        }
        if old.step != new.step || old.position != new.position { speakStep() }
    }

    /// "Step 5. Flip the paper over."
    static func spokenStep(_ step: Step) -> String {
        let title = step.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return "Step \(step.n)." }
        let end = title.last.map { ".!?".contains($0) } ?? false
        return "Step \(step.n). \(title)\(end ? "" : ".")"
    }

    private func speakStep() {
        guard let step, !state.isDone else { return }
        guide.say(Self.spokenStep(step), kind: .step)
    }

    private func cameraAdvanced() {
        guard !model.isPreview || !clips.isStill else { return }
        Chime.shared.play()
        Haptics.success()
        flashVerified = true
        flashID += 1
        AccessibilityNotification.Announcement("Verified").post()
    }

    private func mistakeChanged(_ new: MistakeMessage?) {
        guard let new, new != shownMistake else {
            shownMistake = new
            return
        }
        shownMistake = new
        recorder.observe(mistake: new)
        Haptics.warning()
        let text = MistakeCard(kind: MistakeKind(new), message: new.message).shownMessage
        AccessibilityNotification.Announcement("Mistake. \(text)").post()
        if guide.isEnabled {
            guide.say(text, kind: .mistake)
        } else if speakMistakes {
            guide.sayMistake(text)
        }
    }

    /// Holds Checking at least 0.6 s once shown, so it never flickers.
    private func settleStatus() async {
        let target = resolvedStatus
        holdChecking = false
        if target == .checking {
            if checkingSince == nil { checkingSince = Date() }
            return
        }
        guard let since = checkingSince else { return }
        checkingSince = nil
        let left = 0.6 - Date().timeIntervalSince(since)
        guard left > 0 else { return }
        holdChecking = true
        try? await Task.sleep(for: .seconds(left))
        if !Task.isCancelled { holdChecking = false }
    }
}

/// Which arrangement Learn uses for its size.
enum LearnLayout: Equatable {
    case pip
    /// `phone` is iPhone landscape: one controls row, the mistake card over the clip, no sidebar.
    case sideBySide(phone: Bool)

    static let sideBySideMinWidth: CGFloat = 700
    static let sidebarWidthThreshold: CGFloat = {
        #if os(macOS)
        1000
        #else
        1100
        #endif
    }()

    /// The layout for this platform. `compactHeight` is the vertical size class being compact (iPhone landscape).
    static func pick(size: CGSize, compactHeight: Bool = false) -> LearnLayout {
        #if os(macOS)
        return .sideBySide(phone: false)
        #else
        return pickTouch(size: size, compactHeight: compactHeight)
        #endif
    }

    /// iPhone and iPad: a short, wide space (iPhone landscape) gets the phone side by side layout; a wide, tall
    /// one (iPad) the full side by side; anything taller than wide the PiP layout.
    static func pickTouch(size: CGSize, compactHeight: Bool) -> LearnLayout {
        let wide = size.width > size.height
        if wide && (compactHeight || size.height < phoneHeightLimit) { return .sideBySide(phone: true) }
        if size.width >= sideBySideMinWidth { return .sideBySide(phone: false) }
        return wide ? .sideBySide(phone: true) : .pip
    }

    /// Below this height a wide space is a phone on its side.
    static let phoneHeightLimit: CGFloat = 500

    /// The trailing column on iPhone landscape: a third of the width, kept between 240 and 320 points so the
    /// controls fit and the clip keeps most of the screen.
    static func phoneColumnWidth(for width: CGFloat) -> CGFloat {
        min(320, max(240, (width * 0.36).rounded()))
    }

    /// The live tile's shape: the picture's own shape when frames arrive, else this device's camera held the
    /// same way as the screen (16:9 on its side, 9:16 upright), else 4:3.
    static func liveAspect(frame: CGSize?, ownCamera: Bool, landscape: Bool) -> CGFloat {
        if !ownCamera, let frame, frame.width > 0, frame.height > 0 { return frame.width / frame.height }
        if ownCamera { return landscape ? 16 / 9 : 9 / 16 }
        return 4 / 3
    }
}

extension EnvironmentValues {
    /// Pins Learn's layout (snapshot tests render the iPhone layouts on the Mac).
    @Entry var learnLayoutOverride: LearnLayout? = nil
}

/// A small ring and the stage words from the real-time understanding work.
struct UnderstandingIndicator: View {
    var progress: Double?
    var stage: String?
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.xs) {
            if let progress { ProgressRing(fraction: progress, size: 18) }
            if let stage, !stage.isEmpty {
                Text(stage).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2).lineLimit(1)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel([progress.map { "Step progress \(Int(($0 * 100).rounded())) percent" }, stage]
            .compactMap { $0 }.joined(separator: ", "))
    }
}

#Preview("Learn, playing") {
    LearnView().environment(AppModel.preview(playing: true)).handOverTheme(.system)
}

#Preview("Learn, mistake") {
    LearnView(clips: .still(caption: "Fold the top layer back over the flap."))
        .environment(AppModel.preview(startAt: 9))
        .handOverTheme(.system)
}

#Preview("Learn, checks off") {
    LearnView(clips: .still(caption: nil)).environment(AppModel.preview(startAt: 10)).handOverTheme(.ivory)
}

/// A banner on Learn about the camera.
struct LearnNotice {
    var symbol: String
    var tone: HOTone = .caution
    var text: String
    var actionTitle: String?
    var action: () -> Void = {}
}

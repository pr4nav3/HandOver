import SwiftUI

@main
struct HandOverApp: App {
    @State private var model: AppModel
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // Meta requires the toolkit to be configured once at app launch, before registration callbacks or
        // device discovery. The no-op implementation keeps the shared Mac target unchanged.
        GlassesToolkitHooks.configure()
        // `-demo` runs on the scripted PreviewHub: no network, no saved hubs touched (screenshots, demos).
        let demo = ProcessInfo.processInfo.arguments.contains("-demo")
        // The viewer socket asks for no live frames when this device is the camera (`/ws/ui?frames=0`).
        let model = demo ? AppModel.preview(playing: true)
            : AppModel(makeTransport: { URLSessionTransport(url: LiveFrames.adjust($0)) })
        if !demo { model.reconnectToLastHub() }
        _model = State(initialValue: model)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .handOverSetup()
                .handOverTheme()
                .environment(model)
                .onChange(of: scenePhase) { _, phase in
                    guard AppAudioLifecycle.shouldHardStop(isActive: phase == .active) else { return }
                    // Process-wide backstop for routes that disappear before their local onDisappear runs.
                    SpokenGuide.shared.endLessonAudio()
                    Chime.shared.stop()
                }
        }
        #if os(macOS)
        .defaultSize(width: 1100, height: 720)
        #endif
    }
}

/// Kept pure so the app/background contract has a deterministic regression test. Both `.inactive` (Home,
/// app switcher, window close) and `.background` must stop; waiting only for background caused orphan speech.
enum AppAudioLifecycle {
    static func shouldHardStop(isActive: Bool) -> Bool { !isActive }
}

/// Links from the Meta AI app carry a `metaWearablesAction` query item.
enum GlassesLink {
    static func isMetaCallback(_ url: URL) -> Bool {
        URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
            .contains { $0.name == "metaWearablesAction" } ?? false
    }
}

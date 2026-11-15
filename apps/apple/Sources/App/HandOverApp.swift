import SwiftUI

@main
struct HandOverApp: App {
    @State private var model: AppModel

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
        }
        #if os(macOS)
        .defaultSize(width: 1100, height: 720)
        #endif
    }
}

/// Links from the Meta AI app carry a `metaWearablesAction` query item.
enum GlassesLink {
    static func isMetaCallback(_ url: URL) -> Bool {
        URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
            .contains { $0.name == "metaWearablesAction" } ?? false
    }
}

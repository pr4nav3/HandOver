import SwiftUI

@main
struct HandOverApp: App {
    @State private var model: AppModel

    init() {
        // `-demo` runs on the scripted PreviewHub: no network, no saved hubs touched (screenshots, demos).
        let demo = ProcessInfo.processInfo.arguments.contains("-demo")
        let model = demo ? AppModel.preview(playing: true) : AppModel()
        if !demo { model.reconnectToLastHub() }
        _model = State(initialValue: model)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .onOpenURL { url in
                    // handover://connect?hub=... links and QR codes that open the app.
                    model.connect(text: url.absoluteString)
                }
        }
        #if os(macOS)
        .defaultSize(width: 1100, height: 720)
        #endif
    }
}

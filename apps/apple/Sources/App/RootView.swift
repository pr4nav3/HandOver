import SwiftUI

/// The navigation shell: tabs on iPhone, a sidebar on iPad and Mac. Feature builders replace the screens,
/// not this shell. It owns the `LearnFlow` (open tab, camera choice, the running lesson) and the camera sheet.
struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var flow: LearnFlow
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    #endif

    init(flow: LearnFlow = LearnFlow()) {
        _flow = State(initialValue: flow)
    }

    var body: some View {
        shell
            .environment(flow)
            .sheet(isPresented: Binding(get: { flow.showCameraSheet }, set: { if !$0 { flow.cancelSheet() } })) {
                CameraChoiceSheet()
                    .environment(model)
                    .environment(flow)
            }
            .onAppear {
                let model = self.model
                flow.onFramesPreferenceChange = { [weak model] in
                    guard let model, !model.isPreview, let hub = model.hub else { return }
                    model.connect(to: hub)
                }
            }
            .onChange(of: model.state.lessonId) { _, new in
                // The lesson was deleted or the hub restarted with none: nothing left to follow.
                // A late null from our own End, after Start on a new lesson, is ignored (see hubLessonChanged).
                if flow.hubLessonChanged(to: new), model.connection.isConnected, !model.isPreview { flow.end() }
            }
            .onOpenURL(perform: open)
    }

    @ViewBuilder private var shell: some View {
        #if os(iOS)
        // iPhone always uses tabs: the larger iPhones report a regular width in landscape, and swapping the shell
        // on rotation would rebuild every screen (ending the camera and the clip mid-lesson).
        if UIDevice.current.userInterfaceIdiom == .phone || sizeClass == .compact {
            tabs
        } else {
            split
        }
        #else
        split
        #endif
    }

    private var tabs: some View {
        TabView(selection: $flow.section) {
            ForEach(AppSection.allCases) { place in
                Tab(place.title, systemImage: place.symbol, value: place) {
                    NavigationStack { place.screen }
                }
            }
        }
    }

    private var split: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: selection) { place in
                Label(place.title, systemImage: place.symbol)
                    .tag(place)
            }
            .navigationTitle("HandOver")
            #if os(macOS)
            .navigationSplitViewColumnWidth(min: 180, ideal: 200)
            #endif
        } detail: {
            NavigationStack { flow.section.screen }
        }
    }

    /// The sidebar always has one place selected.
    private var selection: Binding<AppSection?> {
        Binding { flow.section } set: { if let new = $0 { flow.section = new } }
    }

    /// Deep links are handled beside the navigation state they affect. A desktop pairing QR may include a
    /// camera intent, so the same scan both connects to the hub and opens the requested live source.
    private func open(_ url: URL) {
        if GlassesLink.isMetaCallback(url) {
            GlassesController.handle(url: url)
            return
        }
        guard url.host() != "join", let hub = HubURL(parsing: url.absoluteString) else { return }
        model.connect(to: hub)
        if let intent = CameraLaunchIntent(url: url) { flow.openCamera(intent) }
    }
}

#Preview("Shell") {
    RootView().environment(AppModel.preview())
}

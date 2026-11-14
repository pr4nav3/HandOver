import SwiftUI

/// The navigation shell: tabs on iPhone, a sidebar on iPad and Mac. Feature builders replace the screens,
/// not this shell.
struct RootView: View {
    @State private var section: AppSection = .library
    #if os(iOS)
    @Environment(\.horizontalSizeClass) private var sizeClass
    #endif

    var body: some View {
        #if os(iOS)
        if sizeClass == .compact {
            tabs
        } else {
            split
        }
        #else
        split
        #endif
    }

    private var tabs: some View {
        TabView(selection: $section) {
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
            NavigationStack { section.screen }
        }
    }

    /// The sidebar always has one place selected.
    private var selection: Binding<AppSection?> {
        Binding { section } set: { if let new = $0 { section = new } }
    }
}

#Preview("Shell") {
    RootView().environment(AppModel.preview())
}

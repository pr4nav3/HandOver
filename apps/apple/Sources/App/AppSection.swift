import SwiftUI

/// The app's top-level places, in sidebar and tab order.
enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case library, learn, teach, camera, orgs, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .library: "Home"
        case .learn: "Learn"
        case .teach: "Teach"
        case .orgs: "Organizations"
        case .camera: "Be the Camera"
        case .settings: "Settings"
        }
    }

    var symbol: String {
        switch self {
        case .library: "house"
        case .learn: "play.rectangle"
        case .teach: "video.badge.plus"
        case .orgs: "person.3"
        case .camera: "video.circle"
        case .settings: "gearshape"
        }
    }

    /// The feature screen for this place. Each lives in Sources/Features/<Name>/.
    @MainActor @ViewBuilder
    var screen: some View {
        switch self {
        case .library: LibraryView()
        case .learn: LearnTab()
        case .teach: TeachView()
        case .orgs: OrgsListView()
        case .camera: CameraView()
        case .settings: SettingsView()
        }
    }
}

import SwiftUI

/// The app's top-level places, in sidebar and tab order.
enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case library, learn, teach, camera, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .library: "Library"
        case .learn: "Learn"
        case .teach: "Teach"
        case .camera: "Camera"
        case .settings: "Settings"
        }
    }

    var symbol: String {
        switch self {
        case .library: "books.vertical"
        case .learn: "play.rectangle"
        case .teach: "video.badge.plus"
        case .camera: "camera"
        case .settings: "gearshape"
        }
    }

    /// The feature screen for this place. Each lives in Sources/Features/<Name>/.
    @MainActor @ViewBuilder
    var screen: some View {
        switch self {
        case .library: LibraryView()
        case .learn: LearnView()
        case .teach: TeachView()
        case .camera: CameraView()
        case .settings: SettingsView()
        }
    }
}

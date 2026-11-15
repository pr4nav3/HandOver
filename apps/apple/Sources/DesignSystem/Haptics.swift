import SwiftUI
#if os(iOS)
import UIKit
#endif

/// Vibeflux's haptics helper (DESIGN.md 4), plus the two impacts HandOver uses for step changes and recording.
/// One haptic per real event the person can see: never per retry, per check or per state message.
/// Settings, Haptics off silences all of them; the system "System Haptics" switch is respected by UIKit.
/// The Mac has no haptics here.
@MainActor
enum Haptics {
    static let storageKey = "handover.haptics"

    /// False when the person turned haptics off in Settings. On by default.
    static var isEnabled: Bool {
        UserDefaults.standard.object(forKey: storageKey) as? Bool ?? true
    }

    enum Weight: Sendable {
        case light, medium, heavy
    }

    #if os(iOS)
    static func tap() { guard isEnabled else { return }; UISelectionFeedbackGenerator().selectionChanged() }
    static func soft() {
        guard isEnabled else { return }
        UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.7)
    }
    static func success() { guard isEnabled else { return }; UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { guard isEnabled else { return }; UINotificationFeedbackGenerator().notificationOccurred(.warning) }
    static func error() { guard isEnabled else { return }; UINotificationFeedbackGenerator().notificationOccurred(.error) }
    /// Step change by Next, Back or goto (medium); record start (heavy).
    static func impact(_ weight: Weight) {
        guard isEnabled else { return }
        let style: UIImpactFeedbackGenerator.FeedbackStyle = switch weight {
        case .light: .light
        case .medium: .medium
        case .heavy: .heavy
        }
        UIImpactFeedbackGenerator(style: style).impactOccurred()
    }
    #else
    static func tap() {}
    static func soft() {}
    static func success() {}
    static func warning() {}
    static func error() {}
    static func impact(_ weight: Weight) {}
    #endif
}

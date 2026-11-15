import Foundation

/// Built-in fixtures used by automated checks, never shown as real lessons.
enum LessonVisibility {
    static let placeholderIDs: Set<String> = [
        "demo-v1",
        "fortune-teller-v1",
        "synthetic-fortune-teller-v1",
    ]

    static func isUserFacing(_ id: String) -> Bool {
        !placeholderIDs.contains(id)
    }
}

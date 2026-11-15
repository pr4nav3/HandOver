import Foundation

/// The passcode hint from SCREENS.md 25.4. It describes how easy the passcode is to guess, never a promise
/// of security. The hub accepts 4 to 128 characters (`server/accounts.py`).
enum PasscodeStrength: Int, Comparable, Sendable {
    case tooShort = 0, easy, okay, strong

    static let minimum = 4
    static let maximum = 128

    init(_ passcode: String) {
        let chars = Array(passcode)
        guard chars.count >= Self.minimum else {
            self = .tooShort
            return
        }
        if Set(chars).count == 1 || Self.isRun(chars) || chars.count < 6 {
            self = .easy
        } else if chars.count >= 8, chars.contains(where: \.isLetter), chars.contains(where: \.isNumber) {
            self = .strong
        } else {
            self = .okay
        }
    }

    /// Filled segments out of 3.
    var segments: Int { rawValue }

    var hint: String {
        switch self {
        case .tooShort: "At least 4 characters."
        case .easy: "Easy to guess. Anyone nearby could try it."
        case .okay: "OK for a shared workshop hub."
        case .strong: "Hard to guess."
        }
    }

    static func < (a: Self, b: Self) -> Bool { a.rawValue < b.rawValue }

    /// 1234, 4321, abcd, dcba: every character one step from the last, the same way.
    private static func isRun(_ chars: [Character]) -> Bool {
        let values = chars.compactMap { $0.lowercased().unicodeScalars.first?.value }
        guard values.count == chars.count, values.count >= 3 else { return false }
        let steps = zip(values.dropFirst(), values).map { Int($0) - Int($1) }
        return steps.allSatisfy { $0 == 1 } || steps.allSatisfy { $0 == -1 }
    }
}

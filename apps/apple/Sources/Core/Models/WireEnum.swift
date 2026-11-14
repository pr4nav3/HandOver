import Foundation

/// A string enum from the hub. A value this app does not know reads as `fallback` instead of failing
/// the whole message (CONTRACT.md: readers ignore what they do not know).
protocol WireEnum: RawRepresentable, CaseIterable, Codable, Hashable, Sendable where RawValue == String {
    static var fallback: Self { get }
}

extension WireEnum {
    init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: raw) ?? .fallback
    }

    init(wire raw: String?) {
        self = raw.flatMap(Self.init(rawValue:)) ?? .fallback
    }
}

/// yes, no or unsure: a check answer, and the teach-time self-test answers.
enum Verdict: String, WireEnum {
    case yes, no, unsure
    static let fallback = Verdict.unsure
}

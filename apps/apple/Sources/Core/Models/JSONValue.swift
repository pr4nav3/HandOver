import Foundation

/// Any JSON value. Lessons keep the fields this app does not know in it, so a recut (which replaces
/// lesson.json with the body we send) never drops what a newer hub or another client wrote.
enum JSONValue: Codable, Equatable, Hashable, Sendable {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: any Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let v = try? c.decode(Bool.self) {
            self = .bool(v)
        } else if let v = try? c.decode(Int.self) {
            self = .int(v)
        } else if let v = try? c.decode(Double.self) {
            self = .double(v)
        } else if let v = try? c.decode(String.self) {
            self = .string(v)
        } else if let v = try? c.decode([JSONValue].self) {
            self = .array(v)
        } else {
            self = .object(try c.decode([String: JSONValue].self))
        }
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        }
    }
}

/// A coding key made from any string, for reading and writing the unknown fields.
struct AnyKey: CodingKey, Hashable {
    let stringValue: String
    var intValue: Int? { nil }
    init(_ string: String) { stringValue = string }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}

extension KeyedDecodingContainer where Key == AnyKey {
    /// Every field whose name is not in `known`.
    func extras(excluding known: Set<String>) throws -> [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        for key in allKeys where !known.contains(key.stringValue) {
            out[key.stringValue] = try decode(JSONValue.self, forKey: key)
        }
        return out
    }
}

extension KeyedEncodingContainer where Key == AnyKey {
    mutating func encode(extras: [String: JSONValue]) throws {
        for (name, value) in extras.sorted(by: { $0.key < $1.key }) {
            try encode(value, forKey: AnyKey(name))
        }
    }
}

import Foundation

/// An org invite code as a person types, pastes or scans it.
///
/// The hub makes codes with `secrets.token_urlsafe(12)`: 16 characters of letters (both cases), digits, `-`
/// and `_`, and compares them exactly. So letter case and dashes are kept; only whitespace (from the grouped
/// display "K7qM 2x-A ...") is dropped. Accepted forms:
/// - the bare code, grouped or not
/// - `handover://join?code=<code>&hub=<address>` (the QR and share link), also with `host` and `port`
/// - any http(s) URL with a `code` query item
struct InviteCode: Equatable, Sendable {
    static let allowed = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    static let minLength = 6
    static let maxLength = 64

    let code: String
    /// The hub the code belongs to, when the link carried one.
    let hub: HubURL?

    init?(parsing raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if text.contains("://") {
            guard let parts = URLComponents(string: text), let items = parts.queryItems,
                  let code = items.first(where: { $0.name == "code" })?.value,
                  let clean = Self.clean(code) else { return nil }
            self.code = clean
            hub = Self.hub(from: items)
                ?? (parts.scheme?.lowercased().hasPrefix("http") == true ? HubURL(parsing: text) : nil)
            return
        }
        guard let clean = Self.clean(text) else { return nil }
        code = clean
        hub = nil
    }

    init(code: String, hub: HubURL?) {
        self.code = code
        self.hub = hub
    }

    /// "K7qM2xPA9bc_d-Ef" as "K7qM 2xPA 9bc_ d-Ef", for reading aloud and copying by eye.
    static func grouped(_ code: String, size: Int = 4) -> String {
        var out = ""
        for (i, ch) in code.enumerated() {
            if i > 0, i % size == 0 { out.append(" ") }
            out.append(ch)
        }
        return out
    }

    /// VoiceOver reads one character at a time: "K 7 q M ...".
    static func spoken(_ code: String) -> String {
        code.map { ch -> String in
            switch ch {
            case "-": "dash"
            case "_": "underscore"
            default: ch.isLetter ? (ch.isUppercase ? "capital \(ch)" : String(ch)) : String(ch)
            }
        }.joined(separator: " ")
    }

    /// The link to share and to put in the QR: opens the app, connects to the hub and joins.
    static func link(code: String, hub: HubURL?) -> URL {
        var c = URLComponents()
        c.scheme = HubURL.linkScheme
        c.host = "join"
        var items = [URLQueryItem(name: "code", value: code)]
        if let hub { items.append(URLQueryItem(name: "hub", value: hub.base.absoluteString)) }
        c.queryItems = items
        return c.url ?? URL(string: "handover://join")!
    }

    /// True for `handover://join...` links, which the join flow handles instead of a plain connect.
    static func isJoinLink(_ url: URL) -> Bool {
        url.scheme?.lowercased() == HubURL.linkScheme && url.host()?.lowercased() == "join"
    }

    private static func clean(_ raw: String) -> String? {
        let code = String(raw.filter { !$0.isWhitespace })
        guard (minLength...maxLength).contains(code.count), code.allSatisfy(allowed.contains) else { return nil }
        return code
    }

    private static func hub(from items: [URLQueryItem]) -> HubURL? {
        if let hub = items.first(where: { $0.name == "hub" })?.value, let parsed = HubURL(parsing: hub) { return parsed }
        guard let host = items.first(where: { $0.name == "host" })?.value, !host.isEmpty else { return nil }
        let port = items.first(where: { $0.name == "port" })?.value.flatMap(Int.init) ?? HubURL.defaultPort
        let bracketed = host.contains(":") ? "[\(host)]" : host
        return HubURL(parsing: "\(bracketed):\(port)")
    }
}

/// Choices in the New Code form (SCREENS.md 22.5). The hub accepts 0.01 to 90 days and 1 to 1000 uses or no
/// limit, so "Never" is the hub's longest, 90 days, and says so.
enum InviteExpiry: Double, CaseIterable, Identifiable, Sendable {
    case hour = 0.041666666666666664
    case day = 1
    case week = 7
    case month = 30
    case longest = 90

    var id: Double { rawValue }

    var title: String {
        switch self {
        case .hour: "In 1 Hour"
        case .day: "In 1 Day"
        case .week: "In 7 Days"
        case .month: "In 30 Days"
        case .longest: "In 90 Days"
        }
    }
}

enum InviteUses: Int, CaseIterable, Identifiable, Sendable {
    case one = 1
    case ten = 10
    case fifty = 50
    case unlimited = 0

    var id: Int { rawValue }
    var maxUses: Int? { self == .unlimited ? nil : rawValue }

    var title: String {
        switch self {
        case .one: "Single Use"
        case .ten: "10 Uses"
        case .fifty: "50 Uses"
        case .unlimited: "No Limit"
        }
    }
}

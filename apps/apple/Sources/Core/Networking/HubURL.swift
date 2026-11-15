import Foundation

/// Where a hub lives: scheme, host and port, nothing else. Every REST, socket and file URL is built
/// from it.
///
/// `HubURL(parsing:)` accepts what a person might type or scan:
/// - a bare host or IP: `192.168.1.20` (port 8000, the hub's default), `mac.local:8000`, `[fe80::1]:8000`
/// - an http, https, ws or wss URL with any path, for example `ws://192.168.1.20:8000/ws/camera`
/// - the capture page QR, `https://<ip>:8443/capture?pair=4821`: the hub's https port uses a self-signed
///   certificate the app cannot trust, so this maps to plain http on port 8000 of the same host
/// - a `handover://` link: `handover://connect?hub=<url-encoded address>` or `handover://<host>[:port]`
struct HubURL: Hashable, Codable, Sendable, CustomStringConvertible {
    static let defaultPort = 8000
    static let defaultHTTPSPort = 8443
    static let linkScheme = "handover"

    /// `http://host:port` or `https://host:port`, no path.
    let base: URL

    init?(parsing raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains(where: \.isWhitespace) else { return nil }
        guard let base = HubURL.normalize(text, depth: 0) else { return nil }
        self.base = base
    }

    private init(base: URL) { self.base = base }

    var host: String { base.host() ?? "" }
    var port: Int { base.port ?? (base.scheme == "https" ? 443 : 80) }
    var isSecure: Bool { base.scheme == "https" }
    /// "192.168.1.20:8000", for lists and settings.
    var displayName: String {
        let h = host.contains(":") ? "[\(host)]" : host
        return "\(h):\(port)"
    }
    var description: String { base.absoluteString }

    var uiSocket: URL { socketURL(path: "/ws/ui") }
    var cameraSocket: URL { socketURL(path: "/ws/camera") }

    /// `/api/...` on this hub.
    func api(_ path: String) -> URL {
        base.appending(path: "api").appending(path: path)
    }

    /// A lesson file such as a clip, caption or reference frame. Pass the state's `rev` so a recut lesson
    /// is never served from a cache (`?v=<rev>`).
    func fileURL(lesson id: String, path: String, rev: Int? = nil) -> URL {
        var url = base.appending(path: "lessons").appending(path: id)
        for part in path.split(separator: "/") where !part.isEmpty && part != "." && part != ".." {
            url = url.appending(path: String(part))
        }
        if let rev { url = url.appending(queryItems: [URLQueryItem(name: "v", value: String(rev))]) }
        return url
    }

    /// The link that opens this hub in the app, for sharing or a QR code.
    var link: URL {
        var c = URLComponents()
        c.scheme = Self.linkScheme
        c.host = "connect"
        c.queryItems = [URLQueryItem(name: "hub", value: base.absoluteString)]
        return c.url ?? base
    }

    /// A one-scan pairing link that also opens the requested camera on the phone.
    func cameraLink(_ intent: CameraLaunchIntent) -> URL {
        guard var c = URLComponents(url: link, resolvingAgainstBaseURL: false) else { return link }
        c.queryItems = (c.queryItems ?? []) + [URLQueryItem(name: "camera", value: intent.rawValue)]
        return c.url ?? link
    }

    private func socketURL(path: String) -> URL {
        var c = URLComponents(url: base, resolvingAgainstBaseURL: false) ?? URLComponents()
        c.scheme = isSecure ? "wss" : "ws"
        c.path = path
        return c.url ?? base
    }

    private static func normalize(_ text: String, depth: Int) -> URL? {
        let lower = text.lowercased()
        if lower.hasPrefix(linkScheme + "://") {
            guard depth == 0 else { return nil }
            return fromLink(text)
        }
        let schemes = ["http://", "https://", "ws://", "wss://"]
        let hasScheme = schemes.contains { lower.hasPrefix($0) }
        if !hasScheme, lower.contains("://") { return nil }
        guard var c = URLComponents(string: hasScheme ? text : "http://" + text) else { return nil }
        guard let host = c.host, !host.isEmpty else { return nil }
        let scheme = c.scheme?.lowercased() ?? "http"
        let secure = scheme == "https" || scheme == "wss"
        // The capture page QR points at the https port; the app talks to the plain port instead.
        if secure, c.port == defaultHTTPSPort, c.path.lowercased().hasPrefix("/capture") {
            c.scheme = "http"
            c.port = defaultPort
        } else {
            c.scheme = secure ? "https" : "http"
            if !hasScheme, c.port == nil { c.port = defaultPort }
        }
        if let port = c.port, !(1...65535).contains(port) { return nil }
        if !host.contains(":") { c.host = host.lowercased() }  // leave IPv6 literals as written
        c.user = nil
        c.password = nil
        c.path = ""
        c.query = nil
        c.fragment = nil
        return c.url
    }

    /// `handover://connect?hub=<address>` or `handover://<host>[:port]`.
    private static func fromLink(_ text: String) -> URL? {
        guard let c = URLComponents(string: text) else { return nil }
        if let hub = c.queryItems?.first(where: { $0.name == "hub" })?.value, !hub.isEmpty {
            return normalize(hub, depth: 1)
        }
        guard let host = c.host, !host.isEmpty, host != "connect" else { return nil }
        let bracketed = host.contains(":") ? "[\(host)]" : host
        return normalize(c.port.map { "\(bracketed):\($0)" } ?? bracketed, depth: 1)
    }

    // Stored as the plain base string, so saved recents stay readable.
    init(from decoder: any Decoder) throws {
        let text = try decoder.singleValueContainer().decode(String.self)
        guard let parsed = HubURL(parsing: text) else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "bad hub address"))
        }
        self = parsed
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.singleValueContainer()
        try c.encode(base.absoluteString)
    }
}

/// An optional action carried beside the hub address in a pairing QR. The desktop app uses this so one scan
/// can connect the phone and open the right camera instead of making the person find Be the Camera afterward.
enum CameraLaunchIntent: String, Equatable, Sendable {
    case phone
    case glasses

    init?(url: URL) {
        guard url.scheme?.lowercased() == HubURL.linkScheme,
              url.host()?.lowercased() == "connect",
              let value = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
                .first(where: { $0.name == "camera" })?.value else { return nil }
        self.init(rawValue: value.lowercased())
    }
}

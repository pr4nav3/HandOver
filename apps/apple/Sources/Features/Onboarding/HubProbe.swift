import Foundation

/// What the connection test found at an address (SCREENS.md 3.3).
enum HubProbeResult: Equatable, Sendable {
    /// A HandOver hub: how many lessons, and what it says about accounts (nil: no account routes).
    case hub(lessons: Int, me: MeResponse?)
    /// Something answered, but it is not HandOver.
    case notAHub
    /// Nothing answered.
    case unreachable(String)
    /// iOS blocked the local network for this app.
    case localNetworkDenied
}

/// The connection test: `GET /api/lessons` must be a JSON array (or `GET /` must say it is HandOver), then
/// `GET /api/me` tells whether the hub has accounts.
struct HubProbe: Sendable {
    var timeout: TimeInterval = 6
    var session: URLSession?

    func run(_ hub: HubURL, token: String? = nil) async -> HubProbeResult {
        let session = self.session ?? {
            let c = URLSessionConfiguration.ephemeral
            c.timeoutIntervalForRequest = timeout
            c.waitsForConnectivity = false
            return URLSession(configuration: c)
        }()
        do {
            let (data, response) = try await session.data(from: hub.api("lessons"))
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let lessons = status == 200 ? (try? JSONDecoder().decode([LessonSummary].self, from: data)) : nil
            if lessons == nil, !(await saysHandOver(hub, session: session)) { return .notAHub }
            let me = try? await AccountClient(hub: hub, token: token, session: session).me()
            return .hub(lessons: lessons?.count ?? 0, me: me)
        } catch {
            if Self.isLocalNetworkDenied(error) { return .localNetworkDenied }
            return .unreachable((error as? URLError)?.localizedDescription ?? error.localizedDescription)
        }
    }

    /// `GET /` answers `{"app": "HandOver"}` without the built web app, or the web app's page with it.
    private func saysHandOver(_ hub: HubURL, session: URLSession) async -> Bool {
        guard let (data, _) = try? await session.data(from: hub.base) else { return false }
        if let body = try? JSONDecoder().decode([String: JSONValue].self, from: data), body["app"] == .string("HandOver") {
            return true
        }
        return String(decoding: data.prefix(4096), as: UTF8.self).contains("HandOver")
    }

    /// iOS reports a blocked local network as "not connected" with the path's reason in the error.
    static func isLocalNetworkDenied(_ error: any Error) -> Bool {
        let ns = error as NSError
        guard ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNotConnectedToInternet || ns.code == NSURLErrorCannotConnectToHost
        else { return false }
        let path = ns.userInfo["_NSURLErrorNWPathKey"].map { String(describing: $0) } ?? ""
        return path.localizedCaseInsensitiveContains("local network prohibited")
    }
}

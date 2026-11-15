import Foundation
import Observation

/// The connection test and the connect moment (SCREENS.md 3.3 and 25.3), used by onboarding and Settings.
/// Tests the address first, so a wrong one never replaces the hub in use.
@MainActor
@Observable
final class HubConnector {
    enum Phase: Equatable {
        case idle
        case testing(HubURL)
        case connected(HubURL, lessons: Int)
        case failed(HubURL, HubProbeResult)

        var hub: HubURL? {
            switch self {
            case .idle: nil
            case .testing(let h), .connected(let h, _), .failed(let h, _): h
            }
        }
    }

    private(set) var phase: Phase = .idle

    @ObservationIgnored private let probe: HubProbe
    @ObservationIgnored private var task: Task<Void, Never>?

    init(probe: HubProbe = HubProbe()) {
        self.probe = probe
    }

    /// Tests `hub`; on success connects the app, holds the success state 1.2 s, then calls `then` with what
    /// the hub said about accounts (nil: no accounts).
    func test(_ hub: HubURL, app: AppModel, accounts: AccountStore,
              then: @escaping @MainActor (MeResponse?) async -> Void = { _ in }) {
        task?.cancel()
        phase = .testing(hub)
        task = Task {
            let result = await probe.run(hub, token: TokenStore().token(for: hub))
            guard !Task.isCancelled else { return }
            guard case .hub(let lessons, let me) = result else {
                phase = .failed(hub, result)
                Haptics.error()
                return
            }
            app.connect(to: hub)
            accounts.follow(hub)
            phase = .connected(hub, lessons: lessons)
            Haptics.success()
            AccessibilityNotificationPoster.announce("Connected to \(hub.host).")
            try? await Task.sleep(for: .seconds(1.2))
            guard !Task.isCancelled else { return }
            await then(me)
        }
    }

    func reset() {
        task?.cancel()
        phase = .idle
    }

    func setPreview(_ phase: Phase) { self.phase = phase }
}

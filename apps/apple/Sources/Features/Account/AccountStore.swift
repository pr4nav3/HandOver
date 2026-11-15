import Foundation
import Observation
import SwiftUI

/// Accounts on the hub in use: whether the hub has them at all (feature-detected with `GET /api/me`), who is
/// signed in, and the token in the Keychain. Screens read it from the environment; `AccountScope` puts the
/// shared one there when the app did not.
@MainActor
@Observable
final class AccountStore {
    /// What the hub says about accounts.
    enum Support: Equatable, Sendable {
        /// Not asked yet, or no hub.
        case unknown
        case checking
        /// An older hub without account routes: everyone sees everything, nothing to sign in to.
        case unavailable
        /// The hub has accounts. `setupNeeded` is true while it has no users (first-run owner setup).
        case available(setupNeeded: Bool, signInRequired: Bool)
        /// The hub did not answer; try again later.
        case unreachable(String)

        var hasAccounts: Bool {
            if case .available = self { return true }
            return false
        }

        var setupNeeded: Bool {
            if case .available(let setup, _) = self { return setup }
            return false
        }
    }

    static let shared = AccountStore()

    private(set) var hub: HubURL?
    private(set) var support: Support = .unknown
    private(set) var user: HubUser?
    /// The client for the hub in use, carrying the token when signed in.
    private(set) var client: AccountClient?
    /// The avatar look for the signed-in person (or this device on hubs without accounts).
    private(set) var avatar = AvatarChoice()

    var isSignedIn: Bool { user != nil }
    var isOwner: Bool { user?.role == .owner }

    @ObservationIgnored private let tokens: TokenStore
    @ObservationIgnored private let avatars: AvatarStore
    @ObservationIgnored private var refreshTask: Task<Void, Never>?
    @ObservationIgnored private let makeClient: @Sendable (HubURL, String?) -> AccountClient

    init(tokens: TokenStore = TokenStore(), avatars: AvatarStore = AvatarStore(),
         makeClient: @escaping @Sendable (HubURL, String?) -> AccountClient = { AccountClient(hub: $0, token: $1) }) {
        self.tokens = tokens
        self.avatars = avatars
        self.makeClient = makeClient
    }

    /// Follows the app's hub: loads that hub's token and asks the hub about accounts. Safe to call often.
    func follow(_ hub: HubURL?) {
        guard hub != self.hub || support == .unknown else { return }
        self.hub = hub
        user = nil
        refreshTask?.cancel()
        guard let hub else {
            client = nil
            support = .unknown
            avatar = avatars.load(key: nil)
            return
        }
        client = makeClient(hub, tokens.token(for: hub))
        avatar = avatars.load(key: avatarKey)
        refreshTask = Task { await refresh() }
    }

    /// Asks `GET /api/me` again. A stored token the hub no longer accepts is dropped.
    func refresh() async {
        guard let client, let hub else { return }
        if support == .unknown { support = .checking }
        do {
            guard let me = try await client.me() else {
                guard hub == self.hub else { return }
                support = .unavailable
                user = nil
                return
            }
            guard hub == self.hub else { return }
            support = .available(setupNeeded: me.setupNeeded, signInRequired: me.signInRequired)
            setUser(me.user)
        } catch HubError.http(let status, _) where status == 401 {
            guard hub == self.hub else { return }
            tokens.delete(for: hub)
            await client.setToken(nil)
            setUser(nil)
            await refreshAnonymously()
        } catch is CancellationError {
        } catch {
            guard hub == self.hub else { return }
            support = .unreachable(error.friendlyMessage)
        }
    }

    private func refreshAnonymously() async {
        guard let client, let me = try? await client.me() else { return }
        support = .available(setupNeeded: me.setupNeeded, signInRequired: me.signInRequired)
    }

    /// First-run owner setup: creates the hub owner and signs in as them.
    func setupOwner(name: String, passcode: String) async throws {
        guard let client else { throw HubError.unreachable("No hub.") }
        let answer = try await client.setup(name: name, passcode: passcode)
        await adopt(answer)
    }

    func signIn(name: String, passcode: String) async throws {
        guard let client else { throw HubError.unreachable("No hub.") }
        let answer = try await client.login(name: name, passcode: passcode)
        await adopt(answer)
    }

    /// Signs out on the hub (best effort) and forgets the token here.
    func signOut() async {
        guard let hub, let client else { return }
        try? await client.logout()
        tokens.delete(for: hub)
        await client.setToken(nil)
        setUser(nil)
        await refreshAnonymously()
    }

    /// The person's own progress from real runs on this hub.
    func progress() async throws -> [CourseProgressItem] {
        guard let client else { return [] }
        return try await client.courses()
    }

    // MARK: - Avatar

    func setAvatarColor(_ index: Int) {
        avatar.colorIndex = index
        avatars.save(avatar, key: avatarKey)
    }

    /// Stores a photo on this device only, downscaled. Nil removes it.
    func setAvatarPhoto(_ data: Data?) {
        avatar.photo = data.flatMap(AvatarStore.downscaled)
        avatars.save(avatar, key: avatarKey)
    }

    private var avatarKey: String? {
        guard let hub else { return nil }
        return hub.base.absoluteString + "|" + (user?.id ?? "device")
    }

    private func adopt(_ answer: SignInResponse) async {
        guard let hub, let client else { return }
        tokens.save(answer.token, for: hub)
        await client.setToken(answer.token)
        support = .available(setupNeeded: false, signInRequired: support.signInRequiredValue)
        setUser(answer.user)
    }

    private func setUser(_ new: HubUser?) {
        user = new
        avatar = avatars.load(key: avatarKey)
    }

    // MARK: - Previews and tests

    /// A store that never touches the network or Keychain.
    static func preview(user: HubUser? = HubUser(id: "u1", name: "Sam Rivera", role: .owner),
                        support: Support = .available(setupNeeded: false, signInRequired: false)) -> AccountStore {
        let store = AccountStore(tokens: TokenStore(service: "com.soham109.handover.preview"),
                                 avatars: AvatarStore(defaults: UserDefaults(suiteName: "handover.preview.avatars") ?? .standard,
                                                      folder: nil))
        store.support = support
        store.user = user
        store.hub = HubURL(parsing: "192.168.1.20:8000")
        return store
    }
}

private extension AccountStore.Support {
    var signInRequiredValue: Bool {
        if case .available(_, let required) = self { return required }
        return false
    }
}

/// Puts the shared `AccountStore` into the environment when nothing above did, and keeps it on the app's hub.
struct AccountScope<Content: View>: View {
    @Environment(AppModel.self) private var model
    @Environment(AccountStore.self) private var injected: AccountStore?
    @ViewBuilder var content: Content

    var body: some View {
        let store = injected ?? AccountStore.shared
        content
            .environment(store)
            .task(id: model.hub) { if !model.isPreview { store.follow(model.hub) } }
    }
}

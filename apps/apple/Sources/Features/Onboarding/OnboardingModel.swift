import Foundation
import Observation
import SwiftUI

/// Runs the onboarding flow: keeps `OnboardingProgress` saved and does the work behind each step
/// (the connection test, connecting the app, checking for organizations after sign-in).
@MainActor
@Observable
final class OnboardingModel {
    private(set) var progress: OnboardingProgress
    /// The connection test and connect moment, shared with Settings.
    let connector: HubConnector

    var step: OnboardingStep { progress.next }
    var isFinished: Bool { progress.finished }

    @ObservationIgnored private let store: OnboardingStore

    init(store: OnboardingStore = OnboardingStore(), connector: HubConnector = HubConnector()) {
        self.store = store
        self.connector = connector
        progress = store.load()
    }

    // MARK: - Steps

    func finishWelcome() { update { $0.finishWelcome() } }

    func complete(_ step: OnboardingStep, skipped: Bool = false) { update { $0.complete(step, skipped: skipped) } }

    func choose(role: LearnerRole) { update { $0.choose(role: role) } }

    func back() {
        if step == .ownerSetup || step == .account { connector.reset() }
        update { $0.goBack() }
    }

    func ownerTaken() { update { $0.ownerTaken() } }

    func replayWelcome() { update { $0.replayWelcome() } }

    func hideHomeCard() { update { $0.hideHomeCard() } }

    /// Settings, About, Show Welcome Again is the only way back in once finished.
    func reset() {
        progress = OnboardingProgress()
        store.save(progress)
    }

    // MARK: - Connect

    /// Tests the address, connects the app, and after the success hold moves to the account step that fits.
    func test(_ hub: HubURL, app: AppModel, accounts: AccountStore) {
        connector.test(hub, app: app, accounts: accounts) { [weak self] me in
            guard let self else { return }
            let kind: OnboardingHubKind = me == nil ? .open : (me?.setupNeeded == true ? .needsOwner : .accounts)
            self.update { $0.connected(kind: kind, signInOptional: !(me?.signInRequired ?? false)) }
            if me?.user != nil { await self.signedIn(madeAccount: false, accounts: accounts) }
        }
    }

    /// After sign-in or owner setup: offers Join an Organization when the hub has organizations and the
    /// person is in none yet.
    func signedIn(madeAccount: Bool, accounts: AccountStore) async {
        var offered: Bool?
        if let client = accounts.client {
            do {
                let mine = try await client.myOrgs()
                offered = mine.orgs.isEmpty
            } catch {
                offered = false
            }
        }
        update { $0.signedIn(madeAccount: madeAccount, orgsOffered: offered) }
    }

    private func update(_ change: (inout OnboardingProgress) -> Void) {
        change(&progress)
        store.save(progress)
    }

    // MARK: - Previews and snapshots

    static func preview(_ progress: OnboardingProgress, phase: HubConnector.Phase = .idle) -> OnboardingModel {
        let suite = "handover.preview.onboarding"
        UserDefaults.standard.removePersistentDomain(forName: suite)
        let model = OnboardingModel(store: OnboardingStore(defaults: UserDefaults(suiteName: suite) ?? .standard))
        model.progress = progress
        model.connector.setPreview(phase)
        return model
    }
}

/// VoiceOver announcements from non-view code.
enum AccessibilityNotificationPoster {
    @MainActor static func announce(_ text: String) {
        AccessibilityNotification.Announcement(text).post()
    }
}

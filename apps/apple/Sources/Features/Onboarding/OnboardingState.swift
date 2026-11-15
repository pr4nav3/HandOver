import Foundation

/// The onboarding steps, in flow order (SCREENS.md 25.1).
enum OnboardingStep: String, Codable, CaseIterable, Sendable {
    case welcome, connect, ownerSetup, account, profile, joinOrg, role, theme, done

    /// Required steps show no Skip or Not Now.
    var isRequired: Bool {
        switch self {
        case .connect, .ownerSetup, .account: true
        default: false
        }
    }
}

/// What the person picked on the role page. Only changes what Home shows first; never a permission.
enum LearnerRole: String, Codable, CaseIterable, Sendable {
    case learn, teach, both
}

/// Accounts on the hub, as far as onboarding needs to know.
enum OnboardingHubKind: String, Codable, Sendable {
    /// No account routes: skip the account steps.
    case open
    /// Accounts on, no users yet: owner setup.
    case needsOwner
    /// Accounts on, users exist: sign in.
    case accounts
}

/// Onboarding progress, saved after every step so a quit resumes where it left off (SCREENS.md 25.11).
/// The next step is always computed from what is done, never stored, so a hub that changes (for example
/// someone else finishing owner setup) is handled by the same rules.
struct OnboardingProgress: Codable, Equatable, Sendable {
    var welcomeSeen = false
    var connected = false
    var hubKind: OnboardingHubKind?
    var signedIn = false
    /// The hub lets anonymous people in (`auth` is optional), so the account step may be passed with Not Now.
    var signInOptional = false
    var accountSkipped = false
    /// True when this device made the account (owner setup or sign up), so the avatar page applies.
    var madeAccount = false
    var profileDone = false
    /// Nil until known: true when the hub has organizations and the person is not in one yet.
    var orgsOffered: Bool?
    var orgDone = false
    var role: LearnerRole?
    var roleDone = false
    var themeDone = false
    var finished = false
    /// Optional steps passed with Not Now, for the Home "Finish setting up" card.
    var skipped: Set<OnboardingStep> = []

    /// The step to show now.
    var next: OnboardingStep {
        if finished { return .done }
        if !welcomeSeen { return .welcome }
        if !connected { return .connect }
        if !signedIn, !accountSkipped {
            switch hubKind {
            case .needsOwner?: return .ownerSetup
            case .accounts?: return .account
            case .open?, nil: break
            }
        }
        if signedIn, madeAccount, !profileDone { return .profile }
        if signedIn, orgsOffered == true, !orgDone { return .joinOrg }
        if !roleDone { return .role }
        if !themeDone { return .theme }
        return .done
    }

    /// The steps this person will see after the welcome pages, in order, for "Step 2 of 5".
    var visibleSteps: [OnboardingStep] {
        var steps: [OnboardingStep] = [.connect]
        switch hubKind {
        case .needsOwner?: steps += [.ownerSetup, .profile]
        case .accounts?:
            steps.append(.account)
            if madeAccount { steps.append(.profile) }
        case .open?, nil: break
        }
        if hubKind != .open, orgsOffered == true { steps.append(.joinOrg) }
        steps += [.role, .theme]
        return steps
    }

    /// "Step 2 of 5", or nil on the welcome pages and when done.
    var stepLabel: String? {
        let step = next
        guard step != .welcome, step != .done, let index = visibleSteps.firstIndex(of: step) else { return nil }
        return "Step \(index + 1) of \(visibleSteps.count)"
    }

    /// Where Back goes from the current step, or nil when there is no Back. Back never crosses a finished
    /// sign-in, so nobody is signed out by going back.
    var backTarget: OnboardingStep? {
        let step = next
        switch step {
        case .welcome, .done: return nil
        case .connect: return .welcome
        case .ownerSetup, .account: return .connect
        default:
            let steps = visibleSteps
            guard let i = steps.firstIndex(of: step), i > 0 else { return nil }
            let previous = steps[i - 1]
            if previous.isRequired && (previous != .connect || signedIn) { return nil }
            return previous
        }
    }

    // MARK: - Events

    mutating func finishWelcome() {
        welcomeSeen = true
        if next == .done { finished = true }
    }

    mutating func connected(kind: OnboardingHubKind, signInOptional optional: Bool = true) {
        connected = true
        hubKind = kind
        signInOptional = optional
        accountSkipped = false
        if kind == .open {
            signedIn = false
            orgsOffered = false
        }
    }

    mutating func signedIn(madeAccount made: Bool, orgsOffered offered: Bool?) {
        signedIn = true
        madeAccount = made
        orgsOffered = offered
        if hubKind == .needsOwner, !made { hubKind = .accounts }
    }

    /// Someone else finished owner setup first: sign in instead.
    mutating func ownerTaken() { hubKind = .accounts }

    mutating func complete(_ step: OnboardingStep, skipped wasSkipped: Bool = false) {
        switch step {
        case .welcome: welcomeSeen = true
        case .profile: profileDone = true
        case .joinOrg: orgDone = true
        case .role: roleDone = true
        case .theme: themeDone = true
        case .done: finished = true
        case .account:
            guard signInOptional else { return }
            accountSkipped = true
        case .connect, .ownerSetup: return
        }
        if wasSkipped { skipped.insert(step) } else { skipped.remove(step) }
        if next == .done { finished = true }
    }

    mutating func choose(role: LearnerRole) { self.role = role }

    /// Goes back one step by marking the target unfinished.
    mutating func goBack() {
        guard let target = backTarget else { return }
        switch target {
        case .welcome: welcomeSeen = false
        case .connect:
            connected = false
            hubKind = nil
            orgsOffered = nil
            accountSkipped = false
        case .profile: profileDone = false
        case .joinOrg: orgDone = false
        case .role: roleDone = false
        case .theme: themeDone = false
        case .ownerSetup, .account, .done: break
        }
    }

    /// Runs the welcome pages again (Settings, About, Show Welcome Again) without touching anything else.
    mutating func replayWelcome() {
        welcomeSeen = false
        finished = false
    }
}

/// Saves `OnboardingProgress` in UserDefaults.
struct OnboardingStore: @unchecked Sendable {
    static let key = "handover.onboarding"
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    /// The saved progress. An install from before onboarding existed (it already has saved hubs) counts as
    /// finished, so nobody who already uses the app is sent through it.
    func load() -> OnboardingProgress {
        if let data = defaults.data(forKey: Self.key),
           let saved = try? JSONDecoder().decode(OnboardingProgress.self, from: data) { return saved }
        var fresh = OnboardingProgress()
        if defaults.data(forKey: HubRecents.key) != nil {
            fresh.welcomeSeen = true
            fresh.connected = true
            fresh.roleDone = true
            fresh.themeDone = true
            fresh.finished = true
        }
        return fresh
    }

    /// Settings, About, Show Welcome Again: the welcome pages show on the next launch.
    func replayWelcome() {
        var p = load()
        p.replayWelcome()
        save(p)
    }

    func save(_ progress: OnboardingProgress) {
        defaults.set(try? JSONEncoder().encode(progress), forKey: Self.key)
    }
}

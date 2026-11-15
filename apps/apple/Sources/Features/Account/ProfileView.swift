import SwiftUI

/// The signed-in person (SCREENS.md 4.3): avatar and name, progress from real runs on this hub, completed and
/// in-progress lessons, Edit Picture and Sign Out. Every number comes from `GET /api/courses`; with no runs
/// there are no numbers at all.
struct ProfileView: View {
    @Environment(AppModel.self) private var app
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @State private var courses: [CourseProgressItem]?
    @State private var loadError: String?
    @State private var analytics: ProfileAnalytics?
    @State private var analyticsLoaded = false
    @State private var analyticsError: String?
    @State private var confirmSignOut = false
    @State private var editingPicture = false
    @State private var signingIn = false

    /// Fixed data for previews and snapshots.
    var preset: [CourseProgressItem]?
    /// Fixed aggregate data for previews and screenshots. It is always visibly labeled as sample data.
    var presetAnalytics: ProfileAnalytics?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                if let user = accounts.user {
                    header(user)
                    progressSection
                    Button("Sign Out", role: .destructive) { Haptics.tap(); confirmSignOut = true }
                        .buttonStyle(HOButtonStyle(.destructive, size: .large, fullWidth: true))
                } else if accounts.support.hasAccounts {
                    HOEmptyState(symbol: "person.crop.circle", title: "Not signed in",
                                 message: "Sign in to see your progress on this hub.") {
                        Button("Sign In") { Haptics.tap(); signingIn = true }
                            .buttonStyle(HOButtonStyle(.primary))
                    }
                    .frame(minHeight: 320)
                } else {
                    HOEmptyState(symbol: "person.crop.circle", title: "No accounts on this hub",
                                 message: "Everyone here shares one session, so there is no personal progress to show.")
                        .frame(minHeight: 320)
                }
            }
            .padding(HOSpace.l)
            .frame(maxWidth: 680)
            .frame(maxWidth: .infinity)
        }
        .hoPaperBackground()
        .navigationTitle("Profile")
        .task(id: accounts.user?.id) { await load() }
        .refreshable { await load() }
        .confirmationDialog("Sign out of \(accounts.hub?.host ?? "this hub")?", isPresented: $confirmSignOut,
                            titleVisibility: .visible) {
            Button("Sign Out", role: .destructive) {
                Haptics.warning()
                Task { await accounts.signOut() }
            }
        } message: {
            Text("Your progress stays on the hub.")
        }
        .sheet(isPresented: $editingPicture) { pictureSheet }
        .sheet(isPresented: $signingIn) { SignInSheet() }
    }

    private func header(_ user: HubUser) -> some View {
        HStack(spacing: HOSpace.l) {
            Button { Haptics.tap(); editingPicture = true } label: {
                AvatarView(name: user.name, choice: accounts.avatar, size: 64)
                    .overlay(alignment: .bottomTrailing) {
                        Image(systemName: "pencil.circle.fill")
                            .font(.title3)
                            .symbolRenderingMode(.palette)
                            .foregroundStyle(theme.colors.onAccent, theme.colors.accent)
                            .offset(x: 2, y: 2)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Edit Picture")
            VStack(alignment: .leading, spacing: HOSpace.xs) {
                Text(user.name).hoFont(.title, theme).foregroundStyle(theme.colors.ink)
                HStack(spacing: HOSpace.s) {
                    RolePill(text: user.roleTitle)
                    if showsSampleData { RolePill(text: "Sample data", quiet: true) }
                    if let host = accounts.hub?.host {
                        Text("Account on \(host)").font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                            .lineLimit(1)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(HOSpace.l)
        .hoCard()
    }

    @ViewBuilder
    private var progressSection: some View {
        let items = shownCourses
        VStack(alignment: .leading, spacing: HOSpace.s) {
            SectionHeader("Activity")
            activity

            SectionHeader("Lessons").padding(.top, HOSpace.m)
            if let loadError, items == nil {
                HOBanner(symbol: "wifi.exclamationmark", text: loadError, actionTitle: "Try Again") { Task { await load() } }
            } else if let items {
                let tracked = items.filter { $0.progress != nil }
                if tracked.isEmpty {
                    HOEmptyState(symbol: "chart.bar", title: "No progress yet",
                                 message: "Open a lesson from Home. When you finish it, your results show up here.")
                        .frame(minHeight: 220)
                        .hoCard()
                } else {
                    list("In Progress", tracked.filter { $0.progress?.lastFinished == false }, done: false)
                    list("Completed", tracked.filter { $0.progress?.lastFinished == true }, done: true)
                }
            } else {
                HOEmptyState(title: "Loading", loading: true).frame(minHeight: 160)
            }
        }
    }

    @ViewBuilder
    private var activity: some View {
        if let value = shownAnalytics {
            if value.known {
                analyticsCards(value)
            } else {
                HOEmptyState(symbol: "chart.bar", title: "No activity yet",
                             message: "Finish your first lesson and truthful practice insights will appear here.")
                    .frame(minHeight: 190)
                    .hoCard()
            }
        } else if let analyticsError {
            HOBanner(symbol: "wifi.exclamationmark", text: analyticsError, actionTitle: "Try Again") {
                Task { await load() }
            }
        } else if preset != nil {
            HOEmptyState(symbol: "chart.bar", title: "No activity yet",
                         message: "Finish your first lesson and truthful practice insights will appear here.")
                .frame(minHeight: 190)
                .hoCard()
        } else if analyticsLoaded {
            HOBanner(symbol: "chart.bar.xaxis", text: "Detailed activity is not available on this hub.")
        } else {
            HOEmptyState(title: "Loading activity", loading: true).frame(minHeight: 140)
        }
    }

    private func analyticsCards(_ value: ProfileAnalytics) -> some View {
        VStack(spacing: HOSpace.s) {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 126), spacing: HOSpace.xs)], spacing: HOSpace.xs) {
                metric("\(value.runs)", value.runs == 1 ? "Run" : "Runs", symbol: "play.circle")
                if let completed = value.completedRuns {
                    metric("\(completed)", completed == 1 ? "Completed run" : "Completed runs", symbol: "checkmark.circle")
                }
                if let minutes = value.minutesPracticed {
                    metric(Self.practiceTime(minutes), "Practiced", symbol: "clock")
                }
                if let streak = value.currentStreakDays {
                    metric("\(streak)", streak == 1 ? "Day streak" : "Day streak", symbol: "flame")
                }
            }
            let details = detailLines(value)
            if !details.isEmpty {
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    ForEach(Array(details.enumerated()), id: \.offset) { _, line in
                        Label(line.text, systemImage: line.symbol)
                            .font(theme.fonts.callout)
                            .foregroundStyle(theme.colors.ink2)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(HOSpace.l)
                .hoCard()
            }
        }
    }

    private func metric(_ value: String, _ label: String, symbol: String) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.xxs) {
            Image(systemName: symbol).font(theme.fonts.callout).foregroundStyle(theme.colors.accentInk)
            Text(value).font(theme.fonts.numeral).foregroundStyle(theme.colors.ink)
            Text(label).font(theme.fonts.caption).foregroundStyle(theme.colors.ink2)
        }
        .frame(maxWidth: .infinity, minHeight: 92, alignment: .leading)
        .padding(HOSpace.m)
        .hoCard()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label), \(value)")
    }

    private func detailLines(_ value: ProfileAnalytics) -> [(text: String, symbol: String)] {
        var lines: [(String, String)] = []
        if let verified = value.cameraVerifiedSteps {
            lines.append(("\(verified) step\(verified == 1 ? "" : "s") verified by camera", "camera.viewfinder"))
        }
        if let rate = value.checkPassRate, let checks = value.checks, checks > 0 {
            lines.append(("\(Int((rate * 100).rounded()))% of \(checks) camera checks passed", "checkmark.seal"))
        }
        if let mistakes = value.mistakesCaught {
            lines.append(("\(mistakes) mistake\(mistakes == 1 ? "" : "s") caught before moving on", "exclamationmark.triangle"))
        }
        if let replays = value.replays, replays > 0 {
            lines.append(("\(replays) replay\(replays == 1 ? "" : "s") used to practice again", "arrow.counterclockwise"))
        }
        if let sources = value.cameraSources, !sources.isEmpty {
            lines.append(("Practiced with " + sources.map(Self.cameraSourceName).joined(separator: " and "), "video"))
        }
        return lines
    }

    @ViewBuilder
    private func list(_ title: String, _ items: [CourseProgressItem], done: Bool) -> some View {
        if !items.isEmpty {
            SectionHeader(title).padding(.top, HOSpace.m)
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                    if index > 0 { Divider().padding(.leading, HOSpace.l) }
                    HORow(title: item.title, meta: meta(item, done: done)) {
                        EmptyView()
                    } trailing: {
                        if done {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.colors.good)
                                .accessibilityLabel("Completed")
                        } else {
                            ProgressRing(fraction: item.progress?.fraction ?? 0, size: 20)
                        }
                    }
                }
            }
            .hoCard()
        }
    }

    private func meta(_ item: CourseProgressItem, done: Bool) -> String {
        guard let p = item.progress else { return "" }
        let runs = p.runs == 1 ? "1 run" : "\(p.runs) runs"
        if done { return p.completed == 1 ? "1 completed run" : "\(p.completed) completed runs" }
        return "\(p.lastStepsDone) of \(p.total) steps complete, \(runs)"
    }

    private var pictureSheet: some View {
        NavigationStack {
            AvatarEditor(name: accounts.user?.name ?? "")
                .padding(HOSpace.xl)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .hoPaperBackground()
                .navigationTitle("Picture")
                #if os(iOS)
                .navigationBarTitleDisplayMode(.inline)
                #endif
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("Done") { editingPicture = false } }
                }
        }
        .presentationDetents([.medium])
    }

    private func load() async {
        guard preset == nil, !app.isPreview, accounts.user != nil else { return }
        async let courseRequest = accounts.progress()
        async let analyticsRequest = accounts.profileAnalytics()
        do { courses = try await courseRequest; loadError = nil }
        catch is CancellationError { return }
        catch { loadError = error.friendlyMessage }
        do { analytics = try await analyticsRequest; analyticsError = nil; analyticsLoaded = true }
        catch is CancellationError { return }
        catch { analyticsError = error.friendlyMessage; analyticsLoaded = true }
    }

    private var shownCourses: [CourseProgressItem]? {
        if let preset { return preset }
        if app.isPreview { return Self.sampleCourses }
        return courses
    }

    private var shownAnalytics: ProfileAnalytics? {
        if preset != nil { return presetAnalytics }
        if app.isPreview { return .sample }
        return analytics
    }

    private var showsSampleData: Bool { presetAnalytics != nil || (preset == nil && app.isPreview) }

    private static let sampleCourses: [CourseProgressItem] = [
        .init(id: "sample-origami", title: "Fold a fortune teller", steps: 8,
              progress: .init(runs: 3, completed: 2, bestStepsDone: 8, lastStepsDone: 8,
                              lastFinished: true, total: 8)),
        .init(id: "sample-bike", title: "Replace a bicycle tube", steps: 7,
              progress: .init(runs: 1, completed: 0, bestStepsDone: 4, lastStepsDone: 4,
                              lastFinished: false, total: 7)),
    ]

    static func practiceTime(_ minutes: Double) -> String {
        let rounded = max(0, Int(minutes.rounded()))
        if rounded < 60 { return "\(rounded)m" }
        let hours = rounded / 60, remainder = rounded % 60
        return remainder == 0 ? "\(hours)h" : "\(hours)h \(remainder)m"
    }

    static func cameraSourceName(_ source: String) -> String {
        switch source.lowercased() {
        case "glasses": "Meta glasses"
        case "phone", "ios", "android": "a phone"
        case "desktop", "browser", "webcam": "a computer camera"
        default: "a camera"
        }
    }
}

/// A small role badge in the accent wash ("Owner", "Admin", "Teacher").
struct RolePill: View {
    let text: String
    var quiet = false
    @Environment(\.theme) private var theme

    var body: some View {
        Text(text)
            .font(theme.fonts.badge)
            .foregroundStyle(quiet ? theme.colors.ink2 : theme.colors.accentInk)
            .padding(.horizontal, HOSpace.s)
            .frame(minHeight: HOSize.badge)
            .background(quiet ? theme.colors.well : theme.colors.accentSoft, in: Capsule())
    }
}

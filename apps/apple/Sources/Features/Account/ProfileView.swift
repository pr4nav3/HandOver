import SwiftUI

/// The signed-in person (SCREENS.md 4.3): avatar and name, progress from real runs on this hub, completed and
/// in-progress lessons, Edit Picture and Sign Out. Every number comes from `GET /api/courses`; with no runs
/// there are no numbers at all.
struct ProfileView: View {
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @State private var courses: [CourseProgressItem]?
    @State private var loadError: String?
    @State private var confirmSignOut = false
    @State private var editingPicture = false
    @State private var signingIn = false

    /// Fixed data for previews and snapshots.
    var preset: [CourseProgressItem]?

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
                    Text(accounts.hub?.host ?? "").font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(HOSpace.l)
        .hoCard()
    }

    @ViewBuilder
    private var progressSection: some View {
        let items = preset ?? courses
        VStack(alignment: .leading, spacing: HOSpace.s) {
            SectionHeader("Progress")
            if let loadError, items == nil {
                HOBanner(symbol: "wifi.exclamationmark", text: loadError, actionTitle: "Try Again") { Task { await load() } }
            } else if let items {
                let tracked = items.filter { $0.progress != nil }
                if tracked.isEmpty {
                    HOEmptyState(symbol: "chart.bar", title: "No progress yet",
                                 message: "Finish a lesson and your results show up here.")
                        .frame(minHeight: 220)
                        .hoCard()
                } else {
                    stats(tracked)
                    list("Completed", tracked.filter { ($0.progress?.completed ?? 0) > 0 }, done: true)
                    list("In Progress", tracked.filter { ($0.progress?.completed ?? 0) == 0 }, done: false)
                }
            } else {
                HOEmptyState(title: "Loading", loading: true).frame(minHeight: 160)
            }
        }
    }

    private func stats(_ tracked: [CourseProgressItem]) -> some View {
        let done = tracked.filter { ($0.progress?.completed ?? 0) > 0 }.count
        let runs = tracked.reduce(0) { $0 + ($1.progress?.runs ?? 0) }
        let steps = tracked.reduce(0) { $0 + ($1.progress?.bestStepsDone ?? 0) }
        return HStack(spacing: 0) {
            stat("\(done)", done == 1 ? "Lesson done" : "Lessons done")
            Divider().frame(height: 40)
            stat("\(steps)", steps == 1 ? "Step reached" : "Steps reached")
            Divider().frame(height: 40)
            stat("\(runs)", runs == 1 ? "Run" : "Runs")
        }
        .padding(.vertical, HOSpace.l)
        .hoCard()
    }

    private func stat(_ value: String, _ label: String) -> some View {
        VStack(spacing: HOSpace.xxs) {
            Text(value).font(theme.fonts.numeral).foregroundStyle(theme.colors.ink)
            Text(label).font(theme.fonts.caption).foregroundStyle(theme.colors.ink2)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
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
        if done { return p.completed == p.runs ? "Finished, \(runs)" : "Finished \(p.completed) of \(runs)" }
        return "Step \(p.lastStepsDone) of \(p.total), \(runs)"
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
        guard preset == nil, accounts.user != nil else { return }
        do {
            courses = try await accounts.progress()
            loadError = nil
        } catch is CancellationError {
        } catch {
            loadError = error.friendlyMessage
        }
    }
}

/// A small role badge in the accent wash ("Owner", "Admin", "Teacher").
struct RolePill: View {
    let text: String
    @Environment(\.theme) private var theme

    var body: some View {
        Text(text)
            .font(theme.fonts.badge)
            .foregroundStyle(theme.colors.accentInk)
            .padding(.horizontal, HOSpace.s)
            .frame(minHeight: HOSize.badge)
            .background(theme.colors.accentSoft, in: Capsule())
    }
}

import SwiftUI

/// One lesson's detail: from `GET /api/courses/{id}` (with permissions and ratings), or `GET /api/lessons/{id}`
/// on hubs without the course routes.
@MainActor
@Observable
final class LessonDetailModel {
    enum Phase: Equatable { case loading, loaded, failed(String) }

    let lessonId: String
    private(set) var phase: Phase = .loading
    private(set) var course: Course?
    private(set) var lesson: Lesson?
    private(set) var permissions = CoursePermissions.open
    private(set) var ratings: RatingSummary?

    init(lessonId: String) { self.lessonId = lessonId }

    init(preview lesson: Lesson, course: Course? = nil, ratings: RatingSummary? = nil,
         permissions: CoursePermissions = .open) {
        lessonId = lesson.id
        self.lesson = lesson
        self.course = course
        self.ratings = ratings
        self.permissions = permissions
        phase = .loaded
    }

    func load(account: AccountClient?, hub: HubClient?) async {
        if lesson == nil { phase = .loading }
        if let account {
            do {
                let detail = try await account.courseDetail(id: lessonId)
                course = detail.course
                lesson = detail.lesson
                permissions = detail.permissions
                phase = .loaded
                ratings = try? await account.ratings(id: lessonId)
                return
            } catch let error as HubError where error.isMissingRoute {
                // An older hub: read the lesson file instead.
            } catch is CancellationError {
                return
            } catch {
                phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
                return
            }
        }
        guard let hub else { return }
        do {
            lesson = try await hub.lesson(id: lessonId)
            permissions = .open
            phase = .loaded
        } catch is CancellationError {
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    var cameraChecked: Int { lesson?.steps.filter { !$0.isManual }.count ?? 0 }
    var resumeStep: Int? {
        guard let p = course?.progress, p.isInProgress else { return nil }
        return p.lastStepsDone
    }
}

/// Lesson detail (SCREENS.md 6): cover, title, description, meta, safety and tools, Start or Continue, the steps
/// with thumbnails and expert times, and the rating summary. Two columns on iPad and Mac.
struct LessonDetailView: View {
    var lessonId: String
    var preview: LessonDetailModel?

    init(lessonId: String, preview: LessonDetailModel? = nil) {
        self.lessonId = lessonId
        self.preview = preview
    }

    var body: some View {
        AccountScope { LessonDetailScreen(model: preview ?? LessonDetailModel(lessonId: lessonId)) }
    }
}

private struct LessonDetailScreen: View {
    @Environment(AppModel.self) private var app
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State var model: LessonDetailModel
    @State private var launcher = LessonLauncher()
    @State private var showFullDescription = false

    var body: some View {
        Group {
            switch model.phase {
            case .loading:
                HOEmptyState(title: "Loading lesson", loading: true)
            case .failed(let message):
                HOEmptyState(symbol: "exclamationmark.triangle", title: "Can't open this lesson", message: message) {
                    Button("Try Again") { Task { await load() } }.buttonStyle(HOButtonStyle(.secondary))
                }
            case .loaded:
                if let lesson = model.lesson { loaded(lesson) }
            }
        }
        .background(theme.colors.paper)
        .navigationTitle(model.course?.title ?? model.lesson?.title ?? "Lesson")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            if model.permissions.canEdit {
                ToolbarItem(placement: .primaryAction) {
                    NavigationLink(value: CourseRoute.editor(model.lessonId)) { Label("Edit", systemImage: "pencil") }
                }
            }
        }
        .task(id: app.hub) { if !app.isPreview { await load() } }
        .lessonLauncher(launcher)
    }

    private func load() async {
        guard let hub = app.hub else { return }
        let noAccounts = accounts.hub == hub && accounts.support == .unavailable
        await model.load(account: noAccounts ? nil : accounts.courseClient(for: hub), hub: app.client)
    }

    private var isCompact: Bool {
        #if os(iOS)
        sizeClass == .compact
        #else
        false
        #endif
    }

    @ViewBuilder private func loaded(_ lesson: Lesson) -> some View {
        if isCompact {
            ScrollView {
                VStack(alignment: .leading, spacing: HOSpace.xl) {
                    summary(lesson)
                    steps(lesson)
                }
                .padding(HOSpace.l)
            }
        } else {
            ScrollView {
                HStack(alignment: .top, spacing: HOSpace.xl) {
                    summary(lesson).frame(width: 360)
                    steps(lesson).frame(maxWidth: .infinity)
                }
                .padding(HOSpace.xl)
                .frame(maxWidth: 1100)
                .frame(maxWidth: .infinity)
            }
        }
    }

    private func summary(_ lesson: Lesson) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.l) {
            if let hub = app.hub {
                CourseCover(covers: CourseMedia.coverCandidates(hub: hub, lessonId: lesson.id,
                                                                coverURL: model.course?.coverURL))
            }
            VStack(alignment: .leading, spacing: HOSpace.s) {
                Text(model.course?.title ?? lesson.title)
                    .hoFont(.display, theme)
                    .foregroundStyle(theme.colors.ink)
                if let text = model.course?.description, !text.isEmpty {
                    Text(text)
                        .font(theme.fonts.body)
                        .foregroundStyle(theme.colors.ink2)
                        .lineLimit(showFullDescription ? nil : 4)
                    if !showFullDescription && text.count > 180 {
                        Button("More") { showFullDescription = true }
                            .buttonStyle(.plain)
                            .foregroundStyle(theme.colors.accentInk)
                    }
                }
                meta(lesson)
            }
            if let ratings = model.ratings, ratings.count > 0 { CourseRatingLine(summary: ratings) }
            if !lesson.safety.isEmpty || !lesson.tools.isEmpty { beforeYouStart(lesson) }
            startButtons
        }
    }

    private func meta(_ lesson: Lesson) -> some View {
        let parts = [
            "\(lesson.steps.count) \(lesson.steps.count == 1 ? "step" : "steps")",
            CourseFormat.duration(CourseFormat.duration(of: lesson)).map { "\($0) expert time" },
            model.cameraChecked > 0 ? "\(model.cameraChecked) checked by camera" : nil,
        ].compactMap { $0 }
        return HStack(spacing: HOSpace.s) {
            ForEach(Array(parts.enumerated()), id: \.offset) { index, part in
                if index > 0 {
                    Circle().fill(theme.colors.ink3).frame(width: 3, height: 3).accessibilityHidden(true)
                }
                Text(part)
            }
        }
        .font(theme.fonts.callout)
        .foregroundStyle(theme.colors.ink2)
        .accessibilityElement(children: .combine)
    }

    private func beforeYouStart(_ lesson: Lesson) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            Text("Before you start").font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
            ForEach(lesson.safety, id: \.self) { line in
                Label {
                    Text(line).foregroundStyle(theme.colors.ink)
                } icon: {
                    Image(systemName: "exclamationmark.shield").foregroundStyle(theme.colors.caution)
                }
                .font(theme.fonts.body)
            }
            if !lesson.tools.isEmpty {
                Label {
                    Text("Tools: \(lesson.tools.joined(separator: ", "))").foregroundStyle(theme.colors.ink)
                } icon: {
                    Image(systemName: "wrench.and.screwdriver").foregroundStyle(theme.colors.ink2)
                }
                .font(theme.fonts.body)
            }
        }
        .raisedCard()
    }

    private var startButtons: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            startButtonRow
            CameraChoiceRow()
            Text("Follow each clip. HandOver watches your hands and moves on when a step is done.")
                .font(theme.fonts.footnote)
                .foregroundStyle(theme.colors.ink2)
        }
    }

    @ViewBuilder private var startButtonRow: some View {
        if let resume = model.resumeStep {
            HStack(spacing: HOSpace.m) {
                Button { launcher.start(model.lessonId, at: resume, model: app) } label: {
                    Text("Continue at Step \(resume + 1)").frame(maxWidth: .infinity)
                }
                .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                Button { launcher.start(model.lessonId, at: 0, model: app) } label: {
                    Text("Start Over").frame(maxWidth: .infinity)
                }
                .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
            }
        } else {
            Button { launcher.start(model.lessonId, model: app) } label: {
                Text("Start Lesson").frame(maxWidth: .infinity)
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .disabled(model.lesson?.steps.isEmpty ?? true)
        }
    }

    private func steps(_ lesson: Lesson) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            Text("Steps").sectionHeaderStyle(theme)
            VStack(spacing: 0) {
                ForEach(Array(lesson.steps.enumerated()), id: \.element.id) { index, step in
                    Button { launcher.start(lesson.id, at: index, model: app) } label: {
                        StepSummaryRow(step: step, index: index, lessonId: lesson.id)
                    }
                    .buttonStyle(.plain)
                    if index < lesson.steps.count - 1 {
                        Divider().overlay(theme.colors.line).padding(.leading, HOSpace.l + 72 + HOSpace.m)
                    }
                }
            }
            .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
        }
    }
}

/// A step in the course view: thumbnail, number and title, expert time, and how it is checked.
struct StepSummaryRow: View {
    var step: Step
    var index: Int
    var lessonId: String
    @Environment(AppModel.self) private var app
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.m) {
            HubImage(app.hub.map { CourseMedia.frame(hub: $0, lessonId: lessonId, step: step) }, symbol: "photo")
                .frame(width: 72, height: 40)
                .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text("\(index + 1). \(step.title.isEmpty ? "Step \(index + 1)" : step.title)")
                    .font(theme.fonts.bodyMedium)
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                HStack(spacing: HOSpace.s) {
                    if let expert = CourseFormat.duration(CourseFormat.expertSeconds(step)) {
                        Text("Expert \(expert)")
                    }
                    Label(step.isManual ? "Manual" : "Camera check",
                          systemImage: step.isManual ? "hand.tap" : "viewfinder")
                        .labelStyle(.titleAndIcon)
                }
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink2)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(theme.colors.ink3)
                .accessibilityHidden(true)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Starts the lesson at this step")
    }
}

#Preview("Lesson detail") {
    let lesson = PreviewHub.fortuneTeller.lesson
    NavigationStack {
        LessonDetailView(lessonId: lesson.id, preview: LessonDetailModel(
            preview: lesson,
            course: Course(id: lesson.id, title: lesson.title,
                           description: "Fold a square sheet into a paper fortune teller, one crease at a time.",
                           steps: lesson.steps.count, status: .published),
            ratings: RatingSummary(average: 4.6, count: 12)))
    }
    .environment(AppModel.preview())
    .environment(AccountStore.preview())
}

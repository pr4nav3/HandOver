import Foundation
import Observation

/// The course editor's state (SCREENS.md 14 and 15): the lesson, the selected step, history counts, the
/// autosave indicator, caption cues, and every action. Text fields save 1 s after the last keystroke; timing
/// edits save at once and show "Updating clips" while the hub cuts again.
@MainActor
@Observable
final class EditorStore {
    enum Phase: Equatable { case loading, loaded, failed(String) }

    let lessonId: String
    private(set) var phase: Phase = .loading
    private(set) var lesson = Lesson(id: "", title: "")
    private(set) var course: Course?
    private(set) var permissions = CoursePermissions.open
    private(set) var history = HistoryCounts()
    private(set) var capabilities = EditorCapabilities.recutOnly
    private(set) var save: EditorSaveState = .idle
    /// A hub error to show in a banner, verbatim.
    private(set) var banner: String?
    var selection: Int = 0
    /// Caption cues per step index, loaded from captions/NN.vtt.
    private(set) var cues: [Int: [EditorCaptionCue]] = [:]
    /// The self-test running for this step index.
    private(set) var testing: Int?
    private(set) var voiceBusy = false
    private(set) var produceBusy = false
    /// Orgs where the person may publish (Admin or Teacher).
    private(set) var teachOrgs: [EditorPublishPlan.OrgOption] = []
    /// Bumped whenever the hub cut the clips again, so players and frames reload (`?v=`).
    private(set) var revision = 0
    /// Bumped on each snap, for the selection haptic.
    private(set) var snapCount = 0
    /// Bumped after a publish, for the success haptic and toast.
    private(set) var publishCount = 0

    @ObservationIgnored private var service: (any EditorService)?
    @ObservationIgnored private var fallback: (any EditorService)?
    @ObservationIgnored private var account: AccountClient?
    @ObservationIgnored private var hub: HubURL?
    @ObservationIgnored private var pendingFields: [Int: EditorStepFields] = [:]
    @ObservationIgnored private var pendingCaptions: [Int: [EditorCaptionCue]] = [:]
    @ObservationIgnored private var pendingDetails: [String: JSONValue] = [:]
    @ObservationIgnored private var saveTask: Task<Void, Never>?
    @ObservationIgnored let debounce: Duration

    init(lessonId: String, debounce: Duration = .seconds(1)) {
        self.lessonId = lessonId
        self.debounce = debounce
    }

    var selectedStep: Step? { lesson.steps.indices.contains(selection) ? lesson.steps[selection] : nil }
    var canUndo: Bool { history.undo > 0 && !isBusy }
    var canRedo: Bool { history.redo > 0 && !isBusy }
    /// While the hub cuts the clips again, the timeline is read only.
    var isBusy: Bool { save == .updatingClips }
    var layout: TeachTimelineLayout { TeachTimelineLayout(steps: lesson.steps) }
    var snapEdges: [Double] { EditorBoundarySnap.edges(steps: lesson.steps, cues: cues) }
    var voiceover: VoiceoverInfo? { VoiceoverInfo(lesson: lesson) }
    var style: ProductionStyle { ProductionStyle(lesson: lesson) }

    // MARK: - Loading

    /// `fallback` takes over when the hub has no editor routes (it answers 404 "Not Found").
    func use(service: any EditorService, fallback: (any EditorService)? = nil, account: AccountClient?, hub: HubURL?) {
        self.service = service
        self.fallback = fallback
        self.account = account
        self.hub = hub
    }

    func load() async {
        guard let service else { return }
        phase = .loading
        do {
            let snapshot: EditorSnapshot
            do {
                snapshot = try await service.load()
            } catch let error as HubError where error.isMissingRoute {
                guard let fallback else { throw error }
                self.service = fallback
                self.fallback = nil
                snapshot = try await fallback.load()
            }
            adopt(snapshot)
            phase = .loaded
            await loadCues()
            await loadOrgs()
        } catch {
            phase = .failed(Self.describe(error))
        }
    }

    private func adopt(_ snapshot: EditorSnapshot) {
        lesson = snapshot.lesson
        course = snapshot.course
        permissions = snapshot.permissions
        history = snapshot.history
        capabilities = snapshot.capabilities
        selection = min(selection, max(0, lesson.steps.count - 1))
    }

    /// Reads every step's captions file (for snapping and the captions editor).
    func loadCues() async {
        guard let hub else { return }
        let id = lessonId
        let paths = lesson.steps.enumerated().map { ($0.offset, hub.fileURL(lesson: id, path: $0.element.captions)) }
        var found: [Int: [EditorCaptionCue]] = [:]
        await withTaskGroup(of: (Int, [EditorCaptionCue]?).self) { group in
            for (index, url) in paths {
                group.addTask {
                    var request = URLRequest(url: url)
                    request.cachePolicy = .reloadIgnoringLocalCacheData
                    guard let (data, response) = try? await URLSession.shared.data(for: request),
                          (response as? HTTPURLResponse)?.statusCode == 200,
                          let text = String(data: data, encoding: .utf8) else { return (index, nil) }
                    return (index, WebVTT.parse(text))
                }
            }
            for await (index, list) in group { if let list { found[index] = list } }
        }
        cues = found
    }

    private func loadOrgs() async {
        guard let account, capabilities.course else { return }
        struct Mine: Decodable {
            struct Org: Decodable { var id: String; var name: String; var members: Int?; var role: String? }
            var orgs: [Org]
        }
        guard let mine: Mine = try? await account.request("GET", "orgs") else { return }
        teachOrgs = mine.orgs.filter { $0.role == "org_admin" || $0.role == "teacher" }
            .map { EditorPublishPlan.OrgOption(id: $0.id, name: $0.name, members: $0.members ?? 0) }
    }

    // MARK: - Edits

    /// Runs one edit now (timing edits, split, merge, delete).
    func perform(_ op: EditOp) async {
        guard let service, !isBusy else { return }
        await flushPending()
        save = op.recuts ? .updatingClips : .saving
        do {
            let outcome = try await service.apply(op, to: lesson)
            apply(outcome)
            if case .split(let n, _) = op { selection = n }  // the new second half, ready to rename
            if case .delete(let n) = op { selection = max(0, min(n - 2, lesson.steps.count - 1)) }
            if op.recuts { await loadCues() }
        } catch {
            fail(error)
        }
    }

    func undo() async {
        guard let service, canUndo else { return }
        await flushPending()
        save = .updatingClips
        do {
            apply(try await service.undo(from: lesson))
            await loadCues()
        } catch {
            fail(error)
        }
    }

    func redo() async {
        guard let service, canRedo else { return }
        await flushPending()
        save = .updatingClips
        do {
            apply(try await service.redo(from: lesson))
            await loadCues()
        } catch {
            fail(error)
        }
    }

    private func apply(_ outcome: EditOutcome) {
        if outcome.recut { revision += 1 }
        lesson = outcome.lesson
        history = outcome.history
        selection = min(selection, max(0, lesson.steps.count - 1))
        save = .saved
        banner = nil
    }

    private func fail(_ error: any Error) {
        let message = Self.describe(error)
        if let hubError = error as? HubError, case .unreachable = hubError {
            save = .offline
        } else {
            save = .failed(message)
        }
        banner = message
    }

    func dismissBanner() { banner = nil }

    /// "Try Again" after "Could not save": sends what is still waiting.
    func retrySave() {
        save = .idle
        scheduleSave()
    }

    // MARK: - Text fields (autosave)

    /// Changes a step's title, check or common mistake on this device at once, and on the hub 1 s later.
    func update(step index: Int, _ fields: EditorStepFields) {
        guard lesson.steps.indices.contains(index), !fields.isEmpty else { return }
        if let title = fields.title { lesson.steps[index].title = title }
        if let type = fields.checkType {
            lesson.steps[index].checkType = type
            lesson.steps[index].selfTest = nil
        }
        if let question = fields.checkQuestion {
            lesson.steps[index].checkQuestion = question
            lesson.steps[index].selfTest = nil
        }
        if let mistake = fields.commonMistake { lesson.steps[index].commonMistake = mistake }
        pendingFields[index] = (pendingFields[index] ?? EditorStepFields()).merged(with: fields)
        // A check type change is a deliberate tap: save it now rather than after a pause.
        scheduleSave(immediately: fields.checkType != nil)
    }

    func update(captions list: [EditorCaptionCue], step index: Int) {
        cues[index] = list
        pendingCaptions[index] = list
        scheduleSave()
    }

    /// Title and description (course routes).
    func update(title: String? = nil, description: String? = nil) {
        if let title {
            lesson.title = title
            course?.title = title
            pendingDetails["title"] = .string(title)
        }
        if let description {
            course?.description = description
            pendingDetails["description"] = .string(description)
        }
        scheduleSave()
    }

    private func scheduleSave(immediately: Bool = false) {
        saveTask?.cancel()
        save = .saving
        let delay = immediately ? Duration.zero : debounce
        saveTask = Task { [weak self] in
            if delay > .zero { try? await Task.sleep(for: delay) }
            guard !Task.isCancelled else { return }
            await self?.flushPending()
        }
    }

    /// Sends every waiting text change. Called by the debounce, before structural edits, and on close.
    func flushPending() async {
        guard let service else { return }
        let fields = pendingFields
        let captions = pendingCaptions
        let details = pendingDetails
        pendingFields = [:]
        pendingCaptions = [:]
        pendingDetails = [:]
        guard !fields.isEmpty || !captions.isEmpty || !details.isEmpty else {
            if save == .saving { save = .saved }
            return
        }
        save = .saving
        do {
            for (index, f) in fields.sorted(by: { $0.key < $1.key }) where !f.isEmpty {
                let outcome = try await service.apply(.step(n: index + 1, f), to: lesson)
                history = outcome.history
                mergeServerStep(outcome.lesson, index: index)
            }
            for (index, list) in captions.sorted(by: { $0.key < $1.key }) {
                let clean = list.filter { !$0.text.trimmingCharacters(in: .whitespaces).isEmpty }
                let outcome = try await service.apply(.captions(n: index + 1, clean), to: lesson)
                history = outcome.history
            }
            if !details.isEmpty, let account {
                course = try await account.patchCourse(id: lessonId, details)
            }
            save = .saved
            banner = nil
        } catch {
            // Keep what did not reach the hub, so "Try Again" sends it.
            for (k, v) in fields { pendingFields[k] = v.merged(with: pendingFields[k] ?? EditorStepFields()) }
            for (k, v) in captions where pendingCaptions[k] == nil { pendingCaptions[k] = v }
            for (k, v) in details where pendingDetails[k] == nil { pendingDetails[k] = v }
            fail(error)
        }
    }

    /// The hub's answer for one step, without undoing keystrokes typed since the request left.
    private func mergeServerStep(_ server: Lesson, index: Int) {
        guard server.steps.indices.contains(index), lesson.steps.indices.contains(index) else { return }
        let local = lesson.steps[index]
        var merged = server.steps[index]
        if pendingFields[index]?.title != nil { merged.title = local.title }
        if pendingFields[index]?.checkQuestion != nil { merged.checkQuestion = local.checkQuestion }
        if pendingFields[index]?.commonMistake != nil { merged.commonMistake = local.commonMistake }
        lesson.steps[index] = merged
    }

    // MARK: - Timeline

    /// Where a dragged boundary between step `index` and `index + 1` lands.
    func placeBoundary(after index: Int, at proposed: Double, free: Bool) -> EditorBoundarySnap.Result? {
        guard lesson.steps.indices.contains(index + 1), let lower = lesson.steps[index].startSeconds,
              let upper = lesson.steps[index + 1].endSeconds else { return nil }
        return EditorBoundarySnap.place(proposed, lower: lower, upper: upper, edges: snapEdges, free: free)
    }

    func noteSnap() { snapCount += 1 }

    /// Commits a boundary drag: step `index` ends and step `index + 1` starts at `time`.
    func moveBoundary(after index: Int, to time: Double) async {
        guard lesson.steps.indices.contains(index + 1) else { return }
        if let end = lesson.steps[index].endSeconds, abs(end - time) < 0.05 { return }
        await perform(.boundary(n: index + 1, start: nil, end: time, next: (n: index + 2, start: time)))
    }

    /// Start and end of a step typed in the inspector.
    func setTimes(step index: Int, start: Double?, end: Double?) async {
        guard lesson.steps.indices.contains(index) else { return }
        var next: (n: Int, start: Double)?
        if let end, lesson.steps.indices.contains(index + 1) { next = (index + 2, end) }
        await perform(.boundary(n: index + 1, start: start, end: end, next: next))
        if let start, index > 0, lesson.steps.indices.contains(index - 1),
           let prevEnd = lesson.steps[index - 1].endSeconds, prevEnd > start {
            await perform(.boundary(n: index, start: nil, end: start, next: nil))
        }
    }

    // MARK: - Self-test

    func testQuestion(step index: Int) async {
        guard let account, capabilities.selfTest, lesson.steps.indices.contains(index) else { return }
        await flushPending()
        testing = index
        defer { testing = nil }
        do {
            let answer = try await account.selfTest(course: lessonId, n: index + 1)
            if let result = answer.results.first(where: { $0.n == index + 1 }) {
                lesson.steps[index].selfTest = result.selfTest
            }
            if let h = answer.history { history = h }
        } catch {
            fail(error)
        }
    }

    // MARK: - Voiceover

    func regenerateVoiceover(step index: Int, voice: String?) async {
        guard let account, capabilities.voiceover else { return }
        await flushPending()
        voiceBusy = true
        defer { voiceBusy = false }
        do {
            let job = try await account.voiceover(course: lessonId, steps: [index + 1], voice: voice)
            let done = try await account.waitForCourseJob(course: lessonId, job: job)
            if done.status == "error" { throw HubError.http(status: 500, detail: done.message ?? "Voiceover failed.") }
            lesson = try await account.courseDetail(id: lessonId).lesson
        } catch {
            fail(error)
        }
    }

    func removeVoiceover() async {
        guard let account, capabilities.voiceover else { return }
        voiceBusy = true
        defer { voiceBusy = false }
        do {
            lesson = try await account.removeVoiceover(course: lessonId)
        } catch {
            fail(error)
        }
    }

    // MARK: - Production

    func rerender(_ style: ProductionStyle) async {
        guard let account, capabilities.production else { return }
        produceBusy = true
        defer { produceBusy = false }
        do {
            let job = try await account.produce(course: lessonId, style: style)
            let done = try await account.waitForCourseJob(course: lessonId, job: job)
            if done.status == "error" { throw HubError.http(status: 500, detail: done.message ?? "Rendering failed.") }
            lesson.extra["production"] = style.json
        } catch {
            fail(error)
        }
    }

    // MARK: - Cover

    /// Uses a step's frame as the cover (the hub copies it, so a recut cannot change it).
    func useFrameAsCover(step index: Int) async {
        guard let account, lesson.steps.indices.contains(index) else { return }
        await patch(["cover": .string(lesson.steps[index].refFrame)], with: account)
    }

    func removeCover() async {
        guard let account else { return }
        await patch(["cover": .null], with: account)
    }

    func uploadCover(_ file: URL) async {
        guard let account, let hub else { return }
        save = .saving
        do {
            let auth = await account.authorization
            course = try await CourseUpload.send(to: hub.api("courses").appending(path: lessonId).appending(path: "cover"),
                                                 file: file, fields: [], authorization: auth, timeout: 60) { _ in }
            save = .saved
        } catch {
            fail(error)
        }
    }

    private func patch(_ fields: [String: JSONValue], with account: AccountClient) async {
        save = .saving
        do {
            course = try await account.patchCourse(id: lessonId, fields)
            save = .saved
        } catch {
            fail(error)
        }
    }

    // MARK: - Publish and access

    func publishPlan(canPublishToEveryone: Bool) -> EditorPublishPlan? {
        guard let course else { return nil }
        return EditorPublishPlan(course: course, lesson: lesson, teachOrgs: teachOrgs, canPublishToEveryone: canPublishToEveryone)
    }

    /// Publishes (or updates) to an audience. Only Me and People with Access publish as unlisted-capable too:
    /// the hub's visibility decides who finds it.
    func publish(to audience: EditorPublishPlan.Audience, unlisted: Bool) async -> Bool {
        guard let account else { return false }
        await flushPending()
        save = .saving
        do {
            course = try await account.publish(id: lessonId, status: EditorPublishPlan.status(unlisted: unlisted),
                                               visibility: audience.visibility, orgId: audience.orgId)
            save = .saved
            publishCount += 1
            return true
        } catch {
            fail(error)
            return false
        }
    }

    func unpublish() async {
        guard let account else { return }
        save = .saving
        do {
            course = try await account.unpublish(id: lessonId)
            save = .saved
        } catch {
            fail(error)
        }
    }

    func setAccess(_ list: [Course.Access]) async {
        guard let account else { return }
        let body: JSONValue = .array(list.map { .object(["user_id": .string($0.userId), "role": .string($0.role.rawValue)]) })
        await patch(["access": body], with: account)
    }

    /// People on the hub to add to the access list (hub owners only; others type nothing and see the list).
    func hubPeople() async -> [HubUser] {
        guard let account else { return [] }
        return (try? await account.hubUsers()) ?? []
    }

    // MARK: - Previews

    func preview(lesson: Lesson, course: Course? = nil, permissions: CoursePermissions = .open,
                 capabilities: EditorCapabilities = .full, cues: [Int: [EditorCaptionCue]] = [:], save: EditorSaveState = .saved,
                 history: HistoryCounts = HistoryCounts(undo: 2, redo: 0)) {
        self.lesson = lesson
        self.course = course
        self.permissions = permissions
        self.capabilities = capabilities
        self.cues = cues
        self.save = save
        self.history = history
        phase = .loaded
    }

    static func describe(_ error: any Error) -> String {
        if let hubError = error as? HubError {
            if hubError.isPermission { return "You do not have permission to do that. Ask the lesson's owner to make you an editor." }
            if case .unreachable = hubError { return hubError.friendly }
        }
        return (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}

import Foundation
import Synchronization
import Testing
@testable import HandOver

private func lesson(_ times: [(String, String)], manual: Set<Int> = []) -> Lesson {
    Lesson(id: "l", title: "L", steps: times.enumerated().map { i, t in
        Step(n: i + 1, title: "Step \(i + 1)", start: t.0, end: t.1, checkType: manual.contains(i) ? .manual : .camera)
    })
}

struct BoundarySnapTests {
    @Test func snapsToTheNearestCueEdgeWithinTheWindow() {
        let r = EditorBoundarySnap.place(10.3, lower: 0, upper: 30, edges: [9.0, 10.05, 10.6, 20])
        #expect(r == .init(time: 10.05, snapped: true))
    }

    @Test func outsideTheWindowLandsOnTenths() {
        let r = EditorBoundarySnap.place(14.27, lower: 0, upper: 30, edges: [13.5, 15])
        #expect(r == .init(time: 14.3, snapped: false))
    }

    @Test func freePlacementIgnoresEdges() {
        let r = EditorBoundarySnap.place(10.32, lower: 0, upper: 30, edges: [10.3], free: true)
        #expect(r == .init(time: 10.3, snapped: false))
        #expect(EditorBoundarySnap.place(10.32, lower: 0, upper: 30, edges: [10.4], free: true).snapped == false)
    }

    @Test func neverMakesAStepShorterThanTheMinimum() {
        #expect(EditorBoundarySnap.place(0.1, lower: 0, upper: 10, edges: []).time == 0.5)
        #expect(EditorBoundarySnap.place(9.9, lower: 0, upper: 10, edges: []).time == 9.5)
        // An edge that would leave a too-short neighbor is not a snap target.
        #expect(EditorBoundarySnap.place(0.4, lower: 0, upper: 10, edges: [0.2]) == .init(time: 0.5, snapped: false))
    }

    @Test func cueEdgesAreMadeAbsolute() {
        let l = lesson([("00:00", "00:08"), ("00:08", "00:16")])
        let edges = EditorBoundarySnap.edges(steps: l.steps, cues: [1: [EditorCaptionCue(start: 0.5, end: 4, text: "a")]])
        #expect(edges == [8.5, 12])
    }

    @Test func splitNeedsRoomOnBothSides() {
        let step = Step(n: 1, start: "00:10", end: "00:12")
        #expect(EditorBoundarySnap.canSplit(step, at: 11))
        #expect(!EditorBoundarySnap.canSplit(step, at: 10.3))
        #expect(!EditorBoundarySnap.canSplit(step, at: 11.8))
    }
}

@MainActor
struct TeachClipLoadingTests {
    @Test func editorUsesAShortBufferWithoutStallWaiting() {
        #expect(TeachClipLoadPolicy.preferredForwardBufferDuration < 0.5)
        #expect(!TeachClipLoadPolicy.waitsToMinimizeStalling)
    }

    @Test func repeatedStepSelectionReusesTheAsset() {
        let url = URL(string: "http://127.0.0.1:8000/lessons/example/clips/01.mp4?v=4")!
        #expect(TeachClipAssetCache.shared.asset(for: url) === TeachClipAssetCache.shared.asset(for: url))
    }
}

struct UndoStackTests {
    @Test func undoAndRedoWalkTheHistory() {
        var stack = EditorUndoStack<Int>()
        stack.record(1)
        stack.record(2)
        #expect(stack.counts == HistoryCounts(undo: 2, redo: 0))
        #expect(stack.undo(from: 3) == 2)
        #expect(stack.undo(from: 2) == 1)
        #expect(stack.undo(from: 1) == nil)
        #expect(stack.redo(from: 1) == 2)
        #expect(stack.counts == HistoryCounts(undo: 1, redo: 1))
    }

    @Test func aNewChangeClearsRedo() {
        var stack = EditorUndoStack<Int>()
        stack.record(1)
        _ = stack.undo(from: 2)
        #expect(stack.canRedo)
        stack.record(1)
        #expect(!stack.canRedo)
    }

    @Test func keepsOnlyTheLimit() {
        var stack = EditorUndoStack<Int>(limit: 3)
        for i in 0..<10 { stack.record(i) }
        #expect(stack.undoStates == [7, 8, 9])
    }

    @Test func dropLastTakesBackAFailedChange() {
        var stack = EditorUndoStack<Int>()
        stack.record(1)
        stack.record(2)
        stack.dropLast()
        #expect(stack.undoStates == [1])
    }
}

struct LessonEditTests {
    private let base = lesson([("00:00", "00:06"), ("00:06", "00:14"), ("00:14", "00:31")], manual: [0])

    @Test func splitRenumbersAndNamesThePart() throws {
        let out = try LessonEdits.apply(.split(n: 2, at: 10), to: base)
        #expect(out.steps.map(\.n) == [1, 2, 3, 4])
        #expect(out.steps[1].end == "00:10" && out.steps[2].start == "00:10")
        #expect(out.steps[2].title == "Step 2 (part 2)")
        #expect(out.steps[3].clip == "clips/04.mp4" && out.steps[2].refFrame == "frames/03.jpg")
        #expect(throws: LessonEdits.Failure.tooShort) { try LessonEdits.apply(.split(n: 2, at: 6.2), to: base) }
    }

    @Test func mergeKeepsFirstTitleAndSecondCheck() throws {
        var l = base
        l.steps[1].checkQuestion = "Q2"
        l.steps[2].checkQuestion = "Q3"
        let out = try LessonEdits.apply(.merge(n: 2), to: l)
        #expect(out.steps.count == 2)
        #expect(out.steps[1].title == "Step 2" && out.steps[1].checkQuestion == "Q3")
        #expect(out.steps[1].start == "00:06" && out.steps[1].end == "00:31")
        #expect(throws: LessonEdits.Failure.lastStep) { try LessonEdits.apply(.merge(n: 3), to: base) }
    }

    @Test func manualStepsLoseTheirQuestion() throws {
        let out = try LessonEdits.apply(.step(n: 2, EditorStepFields(checkType: .manual)), to: base)
        #expect(out.steps[1].checkQuestion == "")
        let back = try LessonEdits.apply(.step(n: 2, EditorStepFields(checkType: .camera)), to: out)
        #expect(back.steps[1].checkQuestion == "Is this step finished?")
    }

    @Test func boundaryMovesBothNeighbors() throws {
        let out = try LessonEdits.apply(.boundary(n: 1, start: nil, end: 7.5, next: (n: 2, start: 7.5)), to: base)
        #expect(out.steps[0].end == "00:07.5" && out.steps[1].start == "00:07.5")
    }

    @Test func cannotDeleteTheOnlyStep() {
        #expect(throws: LessonEdits.Failure.onlyStep) { try LessonEdits.apply(.delete(n: 1), to: lesson([("00:00", "00:05")])) }
    }
}

struct WebVTTTests {
    @Test func readsAndWritesTheHubsFormat() {
        let text = "WEBVTT\n\n00:00:00.500 --> 00:00:04.000\nFold it.\n\n00:00:05.000 --> 00:00:08.250 align:start\nCrease it.\n"
        let cues = WebVTT.parse(text)
        #expect(cues.map(\.text) == ["Fold it.", "Crease it."])
        #expect(cues[1].end == 8.25)
        #expect(WebVTT.parse(WebVTT.write(cues)) == cues)
        #expect(WebVTT.format(3725.5) == "01:02:05.500")
    }
}

@MainActor
struct PublishPlanTests {
    private let course = Course(id: "l", title: "L", status: .draft, visibility: .onlyMe)

    @Test func audiencesFollowWhatThePersonMayDo() {
        let plan = EditorPublishPlan(course: course, lesson: lesson([("00:00", "00:05")]),
                               teachOrgs: [.init(id: "o1", name: "Bike Club", members: 1)], canPublishToEveryone: false)
        #expect(plan.audiences.map(\.title) == ["Only Me", "People with Access", "Publish to Bike Club"])
        #expect(plan.audiences[2].detail == "1 member")
        #expect(plan.audiences[2].visibility == .org && plan.audiences[2].orgId == "o1")
        let owner = EditorPublishPlan(course: course, lesson: lesson([("00:00", "00:05")]), teachOrgs: [], canPublishToEveryone: true)
        #expect(owner.audiences.last?.visibility == .everyone)
    }

    @Test func checklistWarnsAboutWeakChecks() {
        var l = lesson([("00:00", "00:05"), ("00:05", "00:09"), ("00:09", "00:12")], manual: [0])
        l.steps[1].checkQuestion = " "
        l.steps[2].selfTest = Step.SelfTest(own: .yes, prev: .yes, ok: false, mock: false)
        let plan = EditorPublishPlan(course: course, lesson: l, teachOrgs: [], canPublishToEveryone: false)
        #expect(plan.steps == 3 && plan.camera == 2 && plan.manual == 1)
        #expect(plan.warnings == ["Step 2 has no check question.", "Step 3 failed its test."])
        #expect(plan.primaryTitle == "Publish" && plan.canPublish)
    }

    @Test func publishedCoursesUpdateAndKeepTheirAudience() {
        let published = Course(id: "l", title: "L", status: .unlisted, visibility: .org, org: OrgRef(id: "o2", name: "Shop"))
        let plan = EditorPublishPlan(course: published, lesson: lesson([("00:00", "00:05")]),
                               teachOrgs: [.init(id: "o1", name: "A", members: 2), .init(id: "o2", name: "Shop", members: 5)],
                               canPublishToEveryone: false)
        #expect(plan.primaryTitle == "Update")
        #expect(plan.current(published)?.orgId == "o2")
        #expect(EditorPublishPlan.status(unlisted: true) == .unlisted && EditorPublishPlan.status(unlisted: false) == .published)
    }

    @Test func emptyLessonsCannotPublish() {
        let plan = EditorPublishPlan(course: course, lesson: Lesson(id: "l", title: "L"), teachOrgs: [], canPublishToEveryone: false)
        #expect(!plan.canPublish)
    }
}

/// Records every edit the store sends.
@MainActor
private final class FakeEditorService: EditorService {
    var applied: [EditOp] = []
    var current: Lesson
    var history = HistoryCounts()
    var failNext: HubError?

    init(_ lesson: Lesson) { current = lesson }

    func load() async throws -> EditorSnapshot {
        EditorSnapshot(lesson: current, course: nil, permissions: .open, history: history, capabilities: .full)
    }

    func apply(_ op: EditOp, to lesson: Lesson) async throws -> EditOutcome {
        if let failNext {
            self.failNext = nil
            throw failNext
        }
        applied.append(op)
        if case .captions = op {} else { current = try LessonEdits.apply(op, to: current) }
        history.undo += 1
        return EditOutcome(lesson: current, history: history, recut: op.recuts)
    }

    func undo(from lesson: Lesson) async throws -> EditOutcome { EditOutcome(lesson: current, history: history, recut: true) }
    func redo(from lesson: Lesson) async throws -> EditOutcome { EditOutcome(lesson: current, history: history, recut: true) }
}

@MainActor
struct EditorStoreTests {
    @Test func typingSavesOnceAfterThePause() async throws {
        let service = FakeEditorService(lesson([("00:00", "00:05"), ("00:05", "00:09")]))
        let store = EditorStore(lessonId: "l", debounce: .milliseconds(40))
        store.use(service: service, account: nil, hub: nil)
        await store.load()
        store.update(step: 1, EditorStepFields(title: "F"))
        store.update(step: 1, EditorStepFields(title: "Fo"))
        store.update(step: 1, EditorStepFields(commonMistake: "Flip it"))
        store.update(step: 1, EditorStepFields(title: "Fold"))
        #expect(store.save == .saving)
        #expect(store.lesson.steps[1].title == "Fold", "edits show at once")
        try await eventually("saved") { await store.save == .saved }
        #expect(service.applied == [.step(n: 2, EditorStepFields(title: "Fold", commonMistake: "Flip it"))])
    }

    @Test func structuralEditsSendWaitingTextFirst() async {
        let service = FakeEditorService(lesson([("00:00", "00:05"), ("00:05", "00:09")]))
        let store = EditorStore(lessonId: "l", debounce: .seconds(10))
        store.use(service: service, account: nil, hub: nil)
        await store.load()
        store.update(step: 0, EditorStepFields(title: "Lay it flat"))
        await store.perform(.split(n: 2, at: 7))
        #expect(service.applied.count == 2)
        #expect(service.applied.first == .step(n: 1, EditorStepFields(title: "Lay it flat")))
        #expect(store.lesson.steps.count == 3)
        #expect(store.selection == 2, "the new part is selected for renaming")
        #expect(store.revision == 1, "a recut reloads clips and frames")
    }

    @Test func failedSaveKeepsTheChangeForTryAgain() async throws {
        let service = FakeEditorService(lesson([("00:00", "00:05")]))
        service.failNext = .http(status: 409, detail: "recut already running")
        let store = EditorStore(lessonId: "l", debounce: .milliseconds(10))
        store.use(service: service, account: nil, hub: nil)
        await store.load()
        store.update(step: 0, EditorStepFields(checkQuestion: "Is it flat?"))
        try await eventually("failed") { if case .failed = await store.save { return true } else { return false } }
        #expect(store.banner == "recut already running")
        store.retrySave()
        try await eventually("saved") { await store.save == .saved }
        #expect(service.applied == [.step(n: 1, EditorStepFields(checkQuestion: "Is it flat?"))])
    }

    @Test func unreachableHubSaysSavedOnThisDeviceOnly() async {
        let service = FakeEditorService(lesson([("00:00", "00:05"), ("00:05", "00:09")]))
        service.failNext = .unreachable("offline")
        let store = EditorStore(lessonId: "l")
        store.use(service: service, account: nil, hub: nil)
        await store.load()
        await store.perform(.merge(n: 1))
        #expect(store.save == .offline)
        #expect(store.save.text == "Saved on this device only")
    }

    @Test func boundaryDragUsesTheSnapRules() async {
        let service = FakeEditorService(lesson([("00:00", "00:08"), ("00:08", "00:16")]))
        let store = EditorStore(lessonId: "l")
        store.use(service: service, account: nil, hub: nil)
        await store.load()
        store.preview(lesson: service.current, capabilities: .full, cues: [1: [EditorCaptionCue(start: 0.5, end: 3, text: "x")]])
        #expect(store.placeBoundary(after: 0, at: 8.3, free: false) == .init(time: 8.5, snapped: true))
        #expect(store.placeBoundary(after: 1, at: 9, free: false) == nil, "no boundary after the last step")
        await store.moveBoundary(after: 0, to: 8.5)
        #expect(service.applied == [.boundary(n: 1, start: nil, end: 8.5, next: (n: 2, start: 8.5))])
    }

    @Test func fallsBackToRecutOnOlderHubs() async {
        @MainActor final class Missing: EditorService {
            func load() async throws -> EditorSnapshot { throw HubError.http(status: 404, detail: "Not Found") }
            func apply(_ op: EditOp, to lesson: Lesson) async throws -> EditOutcome { fatalError() }
            func undo(from lesson: Lesson) async throws -> EditOutcome { fatalError() }
            func redo(from lesson: Lesson) async throws -> EditOutcome { fatalError() }
        }
        let recut = RecutEditorService(id: "l", fetch: { _ in lesson([("00:00", "00:05")]) }, recut: { _, l in l })
        let store = EditorStore(lessonId: "l")
        store.use(service: Missing(), fallback: recut, account: nil, hub: nil)
        await store.load()
        #expect(store.phase == .loaded)
        #expect(store.capabilities == .recutOnly)
    }
}

@MainActor
struct RecutEditorServiceTests {
    @Test func keepsUndoOnThisDevice() async throws {
        let sent = Mutex<[Lesson]>([])
        let service = RecutEditorService(id: "l", fetch: { _ in lesson([("00:00", "00:05"), ("00:05", "00:09")]) },
                                         recut: { _, l in sent.withLock { $0.append(l) }; return l })
        let start = try await service.load().lesson
        let renamed = try await service.apply(.step(n: 1, EditorStepFields(title: "Lay it flat")), to: start)
        #expect(renamed.history == HistoryCounts(undo: 1, redo: 0))
        let undone = try await service.undo(from: renamed.lesson)
        #expect(undone.lesson.steps[0].title == "Step 1")
        #expect(undone.history == HistoryCounts(undo: 0, redo: 1))
        let redone = try await service.redo(from: undone.lesson)
        #expect(redone.lesson.steps[0].title == "Lay it flat")
        #expect(sent.withLock { $0.count } == 3, "every change goes through recut")
    }

    @Test func aFailedRecutLeavesNoHistory() async throws {
        let service = RecutEditorService(id: "l", fetch: { _ in lesson([("00:00", "00:05"), ("00:05", "00:09")]) },
                                         recut: { _, _ in throw HubError.http(status: 400, detail: "step 2: bad timestamp") })
        let start = try await service.load().lesson
        await #expect(throws: HubError.self) { try await service.apply(.merge(n: 1), to: start) }
        #expect(service.stack.counts == HistoryCounts())
    }

    @Test func captionsNeedTheEditorRoutes() async throws {
        let service = RecutEditorService(id: "l", fetch: { _ in lesson([("00:00", "00:05")]) }, recut: { _, l in l })
        let start = try await service.load().lesson
        await #expect(throws: LessonEdits.Failure.notSupported) { try await service.apply(.captions(n: 1, []), to: start) }
    }
}

struct EditorDecodingTests {
    @Test func productionStyleAndVoiceoverReadFromTheLesson() throws {
        let json = """
        {"id":"l","title":"L","steps":[],"production":{"theme":"ivory","title_cards":false,"zoom":false,"burn_captions":true},
         "voiceover":{"voice":"bf_emma","steps":[2,3]}}
        """
        let l = try JSONDecoder().decode(Lesson.self, from: Data(json.utf8))
        let style = ProductionStyle(lesson: l)
        #expect(style.theme == "ivory" && style.titleCards == .off && !style.zoom && style.highlight && style.burnCaptions)
        let voice = try #require(VoiceoverInfo(lesson: l))
        #expect(voice.voice == "bf_emma" && voice.covers(step: 2) && !voice.covers(step: 1))
        #expect(EditorVoiceCatalog.name("bf_emma") == "Emma (UK English)")
        #expect(VoiceoverInfo(lesson: Lesson(id: "x", title: "x")) == nil)
    }

    @Test func courseDetailDecodes() throws {
        let json = """
        {"course":{"id":"l","title":"L","description":"d","status":"unlisted","visibility":"org","org":{"id":"o","name":"Shop","slug":"shop"},
          "access":[{"user_id":"u2","name":"Kim","role":"editor"}],"owner":{"id":"u1","name":"Sam"}},
         "lesson":{"id":"l","title":"L","steps":[{"n":1,"start":"00:00","end":"00:03"}]},
         "permissions":{"can_view":true,"can_edit":true,"can_publish":true,"can_manage":false},
         "history":{"undo":3,"redo":1}}
        """
        let d = try JSONDecoder().decode(CourseDetail.self, from: Data(json.utf8))
        #expect(d.course.status == .unlisted && d.course.visibility == .org && d.course.org?.name == "Shop")
        #expect(d.course.access.first?.role == .editor)
        #expect(d.permissions.canEdit && d.permissions.canPublish && !d.permissions.canManage)
        #expect(d.history == HistoryCounts(undo: 3, redo: 1))
        #expect(d.lesson.steps.count == 1)
    }

    @Test func missingRoutesAreToldApartFromMissingCourses() {
        #expect(HubError.http(status: 404, detail: "Not Found").isMissingRoute)
        #expect(!HubError.http(status: 404, detail: "lesson not found").isMissingRoute)
        #expect(HubError.http(status: 403, detail: "x").isPermission)
    }
}

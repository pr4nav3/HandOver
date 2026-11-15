import Foundation
import Synchronization
import Testing
@testable import HandOver

/// Make course: stage mapping (SCREENS.md 13) and the upload flow.
struct StageMappingTests {
    private func states(_ rows: [TeachStageRow]) -> [String] { rows.map { "\($0.stage.rawValue):\($0.state)" } }

    @Test func uploadingShowsOnlyTheMeasuredPercent() {
        let rows = ProcessingStages.rows(uploadProgress: 0.426, job: nil)
        #expect(rows.first?.text == "Uploading 42%")
        #expect(rows.first?.progress == 0.426)
        #expect(rows.dropFirst().allSatisfy { $0.state == .pending && $0.progress == nil }, "no invented percentages")
    }

    @Test func queuedLeavesOnceTheHubStarts() {
        let queued = ProcessingStages.rows(uploadProgress: nil, job: Job(status: .queued, id: "x"))
        #expect(states(queued) == ["upload:done", "queued:active", "normalizing:pending", "extracting:pending", "cutting:pending"])
        let working = ProcessingStages.rows(uploadProgress: nil, job: Job(status: .extracting, message: "reading the transcript", id: "x"))
        #expect(states(working) == ["upload:done", "normalizing:done", "extracting:active", "cutting:pending"])
        #expect(working.first { $0.stage == .extracting }?.detail == "reading the transcript", "the hub's message, verbatim")
        #expect(working.first { $0.stage == .normalizing }?.text == "Video prepared")
    }

    @Test func doneCountsTheStepsFound() {
        let rows = ProcessingStages.rows(uploadProgress: nil, job: Job(status: .done, id: "x"), stepsFound: 5)
        #expect(rows.allSatisfy { $0.state == .done })
        #expect(rows.first { $0.stage == .extracting }?.text == "5 steps found")
        #expect(rows.first { $0.stage == .cutting }?.text == "Clips cut")
    }

    @Test func errorMarksTheStageThatWasRunning() {
        let rows = ProcessingStages.rows(uploadProgress: nil, job: Job(status: .error, message: "no speech found", id: "x"),
                                         lastStage: .extracting)
        let failed = rows.first { $0.state == .failed }
        #expect(failed?.stage == .extracting)
        #expect(failed?.detail == "no speech found")
        #expect(rows.first { $0.stage == .cutting }?.state == .pending)
    }

    @Test func busyHubIsSaidPlainly() {
        #expect(ProcessingStages.friendly("too many jobs") == "The hub is busy with other lessons. Try again when one finishes.")
        #expect(ProcessingStages.friendly("video is larger than 2 GB") == "video is larger than 2 GB")
    }
}

/// A scripted hub for the upload flow.
private final class FakeUploadHub: Sendable {
    let jobs: Mutex<[Result<Job, HubError>]>
    let uploads = Mutex(0)
    let uploadError: HubError?

    init(jobs: [Result<Job, HubError>], uploadError: HubError? = nil) {
        self.jobs = Mutex(jobs)
        self.uploadError = uploadError
    }

    var backend: UploadFlow.Backend {
        UploadFlow.Backend(
            upload: { [self] _, title, progress in
                uploads.withLock { $0 += 1 }
                progress(0.5)
                progress(1)
                if let uploadError { throw uploadError }
                return UploadReceipt(job: "j1", id: title.lowercased().replacingOccurrences(of: " ", with: "-"))
            },
            job: { [self] _ in
                let next = jobs.withLock { $0.count > 1 ? $0.removeFirst() : $0[0] }
                return try next.get()
            },
            lesson: { id in Lesson(id: id, title: "T", steps: [Step(n: 1, start: "00:00", end: "00:05"),
                                                              Step(n: 2, start: "00:05", end: "00:09")]) })
    }
}

@MainActor
struct UploadFlowTests {
    private let video = TeachPickedVideo(url: URL(fileURLWithPath: "/tmp/Fold_a-fortune teller.mov"), bytes: 1_000_000)

    @Test func titleComesFromTheFileName() {
        #expect(video.suggestedTitle == "Fold a fortune teller")
    }

    @Test func uploadsThenFollowsTheJobToTheLesson() async throws {
        let hub = FakeUploadHub(jobs: [.success(Job(status: .normalizing, id: "fold")),
                                       .success(Job(status: .extracting, id: "fold")),
                                       .success(Job(status: .cutting, id: "fold")),
                                       .success(Job(status: .done, id: "fold"))])
        let flow = UploadFlow(backend: hub.backend, pollInterval: .milliseconds(5))
        flow.pick(video)
        #expect(flow.phase == .titling)
        flow.title = "  Fold  "
        flow.start()
        #expect(flow.phase == .uploading)
        try await eventually("finished") { await flow.phase == .finished }
        #expect(flow.lesson?.steps.count == 2)
        #expect(flow.finishCount == 1 && flow.failCount == 0)
        #expect(flow.title == "Fold")
        #expect(flow.rows.allSatisfy { $0.state == .done })
        #expect(flow.rows.first { $0.stage == .extracting }?.text == "2 steps found")
    }

    @Test func jobErrorFailsOnTheRightRowAndRetryUploadsAgain() async throws {
        let hub = FakeUploadHub(jobs: [.success(Job(status: .extracting, id: "f")),
                                       .success(Job(status: .error, message: "no speech found", id: "f"))])
        let flow = UploadFlow(backend: hub.backend, pollInterval: .milliseconds(5))
        flow.pick(video)
        flow.start()
        try await eventually("failed") { await flow.phase == .failed }
        #expect(flow.failure == "no speech found")
        #expect(flow.rows.first { $0.state == .failed }?.stage == .extracting)
        flow.retry()
        try await eventually("second upload") { hub.uploads.withLock { $0 } == 2 }
    }

    @Test func lostJobAfterAHubRestart() async throws {
        let hub = FakeUploadHub(jobs: [.failure(.http(status: 404, detail: "job not found"))])
        let flow = UploadFlow(backend: hub.backend, pollInterval: .milliseconds(5))
        flow.pick(video)
        flow.start()
        try await eventually("failed") { await flow.phase == .failed }
        #expect(flow.failure == "The hub restarted and lost this job. Upload the video again.")
    }

    @Test func givesUpAfterMissedPolls() async throws {
        let hub = FakeUploadHub(jobs: [.failure(.unreachable("timed out"))])
        let flow = UploadFlow(backend: hub.backend, pollInterval: .milliseconds(2), maxMissedPolls: 3)
        flow.pick(video)
        flow.start()
        try await eventually("failed") { await flow.phase == .failed }
        #expect(flow.failure == "Lost contact with the hub. Check that it is running, then upload again.")
    }

    @Test func uploadErrorsReadPlainly() async throws {
        let hub = FakeUploadHub(jobs: [.success(Job(status: .done, id: "x"))],
                                uploadError: .http(status: 429, detail: "too many jobs"))
        let flow = UploadFlow(backend: hub.backend, pollInterval: .milliseconds(5))
        flow.pick(video)
        flow.start()
        try await eventually("failed") { await flow.phase == .failed }
        #expect(flow.failure == "The hub is busy with other lessons. Try again when one finishes.")
        #expect(flow.rows.first?.state == .failed, "the upload row is the one that failed")
    }

    @Test func noNewPickWhileWorking() async throws {
        let hub = FakeUploadHub(jobs: [.success(Job(status: .queued, id: "x"))])
        let flow = UploadFlow(backend: hub.backend, pollInterval: .milliseconds(50))
        flow.pick(video)
        flow.start()
        try await eventually("processing") { await flow.phase == .processing }
        flow.pick(TeachPickedVideo(url: URL(fileURLWithPath: "/tmp/other.mov")))
        #expect(flow.video == video)
        flow.reset()
        #expect(flow.phase == .idle)
    }
}

/// Library: the course list, and the fallback to `GET /api/lessons` on older hubs.
@MainActor
struct LibraryStoreTests {
    private let hub = HubURL(parsing: "hub.local:8000")!

    @Test func fallsBackToTheLessonListOnAnOlderHub() async {
        let store = LibraryStore(backend: LibraryStore.Backend(
            hub: hub,
            courses: { _, _ in throw HubError.http(status: 404, detail: "Not Found") },
            lessons: { [LessonSummary(id: "a", title: "Fold a crane", steps: 3), LessonSummary(id: "b", title: "Tie a knot", steps: 2)] },
            lesson: { id in Lesson(id: id, title: id, steps: [Step(n: 1, start: "00:00", end: "01:05")]) }))
        await store.reload()
        #expect(store.source == .legacy)
        #expect(store.items.map(\.id) == ["a", "b"])
        #expect(!store.showsFilters)
        #expect(store.items[0].covers.last?.absoluteString == "http://hub.local:8000/lessons/a/frames/01.jpg")
        store.query = "knot"
        await store.reload()
        #expect(store.items.map(\.id) == ["b"], "legacy search runs on this device")
    }

    @Test func placeholderLessonsStayOutOfLiveLists() async {
        let summaries = [
            LessonSummary(id: "demo-v1", title: "Fixture", steps: 1),
            LessonSummary(id: "fortune-teller-v2", title: "Fortune teller", steps: 9),
        ]
        let store = LibraryStore(backend: LibraryStore.Backend(
            hub: hub,
            courses: { _, _ in throw HubError.http(status: 404, detail: "Not Found") },
            lessons: { summaries },
            lesson: { id in Lesson(id: id, title: id) }))
        await store.reload()
        #expect(store.items.map(\.id) == ["fortune-teller-v2"])
    }

    @Test func coursesCarryStatusProgressAndContinue() async throws {
        let json = """
        [{"id":"a","title":"A","cover_url":"/lessons/a/covers/c.jpg","steps":4,"duration":61.2,"status":"draft",
          "visibility":"only_me","owner":{"id":"u1","name":"Sam"},"progress":{"runs":1,"completed":0,"last_steps_done":2,
          "last_finished":false,"total":4}},
         {"id":"b","title":"B","steps":2,"status":"published","visibility":"everyone","progress":null}]
        """
        let courses = try JSONDecoder().decode([Course].self, from: Data(json.utf8))
        let store = LibraryStore(backend: LibraryStore.Backend(hub: hub, courses: { _, _ in courses },
                                                               lessons: { [] }, lesson: { _ in Lesson(id: "", title: "") }))
        await store.reload()
        #expect(store.source == .courses && store.showsFilters)
        #expect(store.items[0].badge == .draft && store.items[1].badge == nil)
        #expect(store.items[0].meta == "4 steps, 1:01")
        #expect(store.continueItems.map(\.id) == ["a"])
        #expect(store.items[0].covers.first?.absoluteString == "http://hub.local:8000/lessons/a/covers/c.jpg")
        #expect(store.items[0].ownerId == "u1")
    }

    @Test func otherErrorsAreShownNotHidden() async {
        let store = LibraryStore(backend: LibraryStore.Backend(
            hub: hub, courses: { _, _ in throw HubError.unreachable("The request timed out.") },
            lessons: { [] }, lesson: { _ in Lesson(id: "", title: "") }))
        await store.reload()
        #expect(store.phase == .failed("Can't reach the hub. The request timed out."))
    }

    @Test func durationsFormat() {
        #expect(CourseFormat.duration(0) == "0:00")
        #expect(CourseFormat.duration(192.4) == "3:12")
        #expect(CourseFormat.duration(3849) == "1:04:09")
        #expect(CourseFormat.duration(nil) == nil)
        #expect(CourseFormat.meta(steps: 1, duration: nil) == "1 step")
        #expect(RatingSummary(average: 4.56, count: 12).line == "4.6 from 12 ratings")
        #expect(RatingSummary(average: nil, count: 0).line == nil)
    }
}

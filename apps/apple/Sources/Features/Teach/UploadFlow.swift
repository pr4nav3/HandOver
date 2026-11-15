import Foundation
import Observation

/// A video picked to become a lesson.
struct TeachPickedVideo: Equatable, Sendable {
    var url: URL
    var name: String
    var bytes: Int64?

    init(url: URL, name: String? = nil, bytes: Int64? = nil) {
        self.url = url
        self.name = name ?? url.lastPathComponent
        self.bytes = bytes ?? TeachPickedVideo.size(of: url)
    }

    /// The title field's starting text: the file name without its extension, as Teach.tsx does.
    var suggestedTitle: String {
        let base = (name as NSString).deletingPathExtension
        let cleaned = base.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: "-", with: " ")
            .trimmingCharacters(in: .whitespaces)
        return cleaned.isEmpty ? "" : cleaned
    }

    var sizeText: String? {
        bytes.map { ByteCountFormatter.string(fromByteCount: $0, countStyle: .file) }
    }

    static func size(of url: URL) -> Int64? {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        return (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize).map(Int64.init)
    }
}

/// Upload, then the hub's job, then the finished lesson (SCREENS.md 11 and 13). One flow per Teach screen; it
/// keeps going when its sheet closes ("The hub keeps working").
@MainActor
@Observable
final class UploadFlow {
    enum Phase: Equatable {
        case idle
        /// Waiting for a title.
        case titling
        case uploading
        case processing
        case finished
        case failed
    }

    struct Backend: Sendable {
        var upload: @Sendable (_ file: URL, _ title: String, _ progress: @escaping @Sendable (Double) -> Void) async throws -> UploadReceipt
        var job: @Sendable (String) async throws -> Job
        var lesson: @Sendable (String) async throws -> Lesson
    }

    private(set) var phase: Phase = .idle
    private(set) var video: TeachPickedVideo?
    var title = ""
    private(set) var uploadProgress: Double = 0
    private(set) var job: Job?
    private(set) var lastStage: Job.Status?
    private(set) var receipt: UploadReceipt?
    private(set) var lesson: Lesson?
    /// What went wrong, in words to show.
    private(set) var failure: String?
    /// Bumped once per finish and per failure, for haptics.
    private(set) var finishCount = 0
    private(set) var failCount = 0

    /// Polls in a row that may fail before the flow gives up (SCREENS.md 13).
    let maxMissedPolls: Int
    let pollInterval: Duration

    @ObservationIgnored private var backend: Backend?
    @ObservationIgnored private var task: Task<Void, Never>?

    init(backend: Backend? = nil, pollInterval: Duration = .seconds(1), maxMissedPolls: Int = 30) {
        self.backend = backend
        self.pollInterval = pollInterval
        self.maxMissedPolls = maxMissedPolls
    }

    func use(_ backend: Backend?) { self.backend = backend }

    var rows: [TeachStageRow] {
        ProcessingStages.rows(uploadProgress: phase == .uploading || (phase == .failed && job == nil) ? uploadProgress : nil,
                              job: job, lastStage: lastStage, stepsFound: lesson?.steps.count,
                              uploadFailed: phase == .failed && job == nil)
    }

    var isWorking: Bool { phase == .uploading || phase == .processing }
    var lessonId: String? { receipt?.id ?? job?.id }

    /// A video was picked: ask for a title.
    func pick(_ video: TeachPickedVideo) {
        guard !isWorking else { return }
        reset()
        self.video = video
        title = video.suggestedTitle
        phase = .titling
    }

    /// "Make Course": upload with the title, then follow the job.
    func start() {
        guard let video, let backend, !isWorking else { return }
        let name = title.trimmingCharacters(in: .whitespacesAndNewlines)
        title = name.isEmpty ? video.suggestedTitle : String(name.prefix(120))
        uploadProgress = 0
        job = nil
        lastStage = nil
        receipt = nil
        lesson = nil
        failure = nil
        phase = .uploading
        let title = self.title
        let report: @Sendable (Double) -> Void = { [weak self] p in
            Task { @MainActor in self?.uploaded(p) }
        }
        task = Task { [weak self] in
            do {
                let receipt = try await backend.upload(video.url, title.isEmpty ? "Untitled lesson" : title, report)
                guard let self, !Task.isCancelled else { return }
                self.receipt = receipt
                self.uploadProgress = 1
                self.phase = .processing
                self.job = Job(status: .queued, id: receipt.id)
                await self.follow(receipt.job, backend: backend)
            } catch is CancellationError {
            } catch {
                self?.fail(Self.describe(error))
            }
        }
    }

    private func uploaded(_ fraction: Double) {
        guard phase == .uploading else { return }
        uploadProgress = max(uploadProgress, min(1, fraction))
    }

    /// "Try Again" after a failure re-uploads the same video.
    func retry() {
        guard phase == .failed, video != nil else { return }
        start()
    }

    /// Stops the upload (Cancel) and returns to the title step.
    func cancelUpload() {
        guard phase == .uploading else { return }
        task?.cancel()
        task = nil
        uploadProgress = 0
        phase = .titling
    }

    /// Forgets everything (Done after a finish or failure, or a new pick).
    func reset() {
        task?.cancel()
        task = nil
        phase = .idle
        video = nil
        title = ""
        uploadProgress = 0
        job = nil
        lastStage = nil
        receipt = nil
        lesson = nil
        failure = nil
    }

    private func follow(_ jobId: String, backend: Backend) async {
        var missed = 0
        while !Task.isCancelled {
            do {
                let current = try await backend.job(jobId)
                missed = 0
                if current.status != .error && current.status != .done { lastStage = current.status }
                job = current
                switch current.status {
                case .done:
                    lesson = try? await backend.lesson(current.id.isEmpty ? (receipt?.id ?? "") : current.id)
                    phase = .finished
                    finishCount += 1
                    return
                case .error:
                    fail(current.message.isEmpty ? "The hub could not make this lesson." : ProcessingStages.friendly(current.message))
                    return
                default:
                    break
                }
            } catch is CancellationError {
                return
            } catch let error as HubError where error.status == 404 {
                fail("The hub restarted and lost this job. Upload the video again.")
                return
            } catch {
                missed += 1
                if missed >= maxMissedPolls {
                    fail("Lost contact with the hub. Check that it is running, then upload again.")
                    return
                }
            }
            try? await Task.sleep(for: pollInterval)
        }
    }

    private func fail(_ message: String) {
        failure = message
        phase = .failed
        failCount += 1
    }

    static func describe(_ error: any Error) -> String {
        let text = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        return ProcessingStages.friendly(text)
    }

    /// Puts the flow in a state for previews and snapshots.
    func preview(phase: Phase, video: TeachPickedVideo? = nil, title: String = "", progress: Double = 0, job: Job? = nil,
                 lastStage: Job.Status? = nil, lesson: Lesson? = nil, failure: String? = nil) {
        self.phase = phase
        self.video = video
        self.title = title
        uploadProgress = progress
        self.job = job
        self.lastStage = lastStage
        self.lesson = lesson
        self.failure = failure
        if let job { receipt = UploadReceipt(job: "preview", id: job.id) }
    }
}

extension UploadFlow.Backend {
    /// The live backend: `POST /api/courses` when the hub has course routes and someone is signed in (so the
    /// draft gets an owner), else `POST /api/lesson` through `HubClient.upload`. Jobs and lessons come from the
    /// legacy routes, which every hub has.
    @MainActor
    static func live(model: AppModel, accounts: AccountStore) -> UploadFlow.Backend? {
        guard let hub = model.hub, let client = model.client else { return nil }
        let signedIn = accounts.hub == hub && accounts.isSignedIn
        let account = accounts.courseClient(for: hub)
        return UploadFlow.Backend(
            upload: { file, title, progress in
                // Asked first, so a large take is never sent twice to a hub without the course routes.
                if signedIn, await account.hasRoute("courses") {
                    let auth = await account.authorization
                    return try await CourseUpload.send(to: hub.api("courses"), file: file,
                                                       fields: [("title", title)], authorization: auth,
                                                       progress: progress)
                }
                return try await client.upload(video: file, title: title, progress: progress)
            },
            job: { try await client.job($0) },
            lesson: { try await client.lesson(id: $0) })
    }
}

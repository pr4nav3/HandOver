import Foundation

/// The stage list on the Make course screen (SCREENS.md 13). Honest: a stage is done only when the hub moved
/// past it, the hub's own `message` shows under the active row, and the only percentage is the upload's,
/// measured from bytes sent.
struct TeachStageRow: Identifiable, Equatable, Sendable {
    enum State: Equatable, Sendable { case pending, active, done, failed }

    enum Stage: String, Sendable, CaseIterable {
        case upload, queued, normalizing, extracting, cutting
    }

    var stage: Stage
    var state: State
    var text: String
    /// The hub's message under the active row, or its error text on the failed row.
    var detail: String?
    /// 0...1, only for the upload.
    var progress: Double?

    var id: String { stage.rawValue }
}

enum ProcessingStages {
    /// The rows for the current upload and job.
    /// - Parameters:
    ///   - uploadProgress: 0...1 while the body goes out; nil once the hub answered with a job.
    ///   - job: the newest job answer, nil before the upload finished.
    ///   - lastStage: the last working status the hub reported, so an `error` marks the right row.
    ///   - stepsFound: the finished lesson's step count, for "5 steps found".
    ///   - uploadFailed: the upload itself failed (before any job existed).
    static func rows(uploadProgress: Double?, job: Job?, lastStage: Job.Status? = nil,
                     stepsFound: Int? = nil, uploadFailed: Bool = false) -> [TeachStageRow] {
        let order: [TeachStageRow.Stage] = [.upload, .queued, .normalizing, .extracting, .cutting]
        let current: TeachStageRow.Stage
        var failed = false
        if let job {
            switch job.status {
            case .done: current = .cutting
            case .error:
                failed = true
                current = stage(for: lastStage ?? .queued)
            default: current = stage(for: job.status)
            }
        } else {
            current = .upload
            failed = uploadFailed
        }
        let finished = job?.status == .done
        let currentIndex = order.firstIndex(of: current) ?? 0
        var rows: [TeachStageRow] = []
        for (index, stage) in order.enumerated() {
            let state: TeachStageRow.State
            if finished || index < currentIndex {
                state = .done
            } else if index == currentIndex {
                state = failed ? .failed : .active
            } else {
                state = .pending
            }
            // "Waiting for the hub" has no done text: once the hub starts, the row leaves.
            if stage == .queued && state == .done { continue }
            var row = TeachStageRow(stage: stage, state: state, text: text(stage, state, uploadProgress, stepsFound))
            if stage == .upload, state == .active { row.progress = uploadProgress ?? 0 }
            if (state == .active || state == .failed), stage != .upload, let message = job?.message,
               !message.trimmingCharacters(in: .whitespaces).isEmpty {
                row.detail = message
            }
            rows.append(row)
        }
        return rows
    }

    static func stage(for status: Job.Status) -> TeachStageRow.Stage {
        switch status {
        case .queued: .queued
        case .normalizing: .normalizing
        case .extracting: .extracting
        case .cutting, .done: .cutting
        case .error: .queued
        }
    }

    static func text(_ stage: TeachStageRow.Stage, _ state: TeachStageRow.State, _ progress: Double?, _ steps: Int?) -> String {
        let done = state == .done
        switch stage {
        case .upload:
            if done { return "Uploaded" }
            let percent = Int(((progress ?? 0) * 100).rounded(.down))
            return state == .failed ? "Upload failed" : "Uploading \(percent)%"
        case .queued:
            return "Waiting for the hub"
        case .normalizing:
            return done ? "Video prepared" : "Preparing video"
        case .extracting:
            guard done else { return "Finding steps" }
            if let steps { return "\(steps) \(steps == 1 ? "step" : "steps") found" }
            return "Steps found"
        case .cutting:
            return done ? "Clips cut" : "Cutting clips"
        }
    }

    /// Hub errors in the words SCREENS.md 11 asks for; anything else verbatim.
    static func friendly(_ message: String) -> String {
        if message.localizedCaseInsensitiveContains("too many jobs") {
            return "The hub is busy with other lessons. Try again when one finishes."
        }
        return message
    }
}

import CoreGraphics
import Foundation
import Testing
@testable import HandOver

@MainActor
struct CaptionCuesTests {
    @Test func parsesCuesTagsAndSettings() {
        let vtt = CaptionCues(parsing: """
        WEBVTT
        Kind: captions

        NOTE written by the teach pipeline

        1
        00:00:00.500 --> 00:00:04.000 line:90% align:center
        <v Expert>Fold the corner</v> &amp; crease it.

        00:05.000 --> 00:08.250
        Flip it over.
        Then press flat.
        """)
        #expect(vtt.cues.count == 2)
        #expect(vtt.cues[0] == .init(start: 0.5, end: 4, text: "Fold the corner & crease it."))
        #expect(vtt.cues[1].text == "Flip it over.\nThen press flat.")
        #expect(vtt.text(at: 0.2) == nil)
        #expect(vtt.text(at: 1) == "Fold the corner & crease it.")
        #expect(vtt.text(at: 4.5) == nil, "between cues")
        #expect(vtt.text(at: 8.25) == nil, "end is exclusive")
    }

    @Test func toleratesCRLFAndSkipsBadCues() {
        let vtt = CaptionCues(parsing: "WEBVTT\r\n\r\n00:00:01.000 --> 00:00:00.500\r\nbackwards\r\n\r\nxx --> yy\r\nbad\r\n\r\n00:00:02,000 --> 00:00:03,000\r\nok\r\n")
        #expect(vtt.cues == [.init(start: 2, end: 3, text: "ok")])
    }

    @Test func readsTheRepoDemoCaptions() throws {
        let url = TestPaths.repo.appending(path: "lessons/demo-v1/captions/02.vtt")
        let vtt = CaptionCues(parsing: try String(contentsOf: url, encoding: .utf8))
        #expect(vtt.cues.count == 2)
        #expect(vtt.text(at: 6) == "Test pattern step 2.")
    }

    @Test func overlappingCuesJoin() {
        let vtt = CaptionCues(cues: [.init(start: 0, end: 4, text: "a"), .init(start: 2, end: 5, text: "b")])
        #expect(vtt.text(at: 3) == "a\nb")
    }
}

@MainActor
struct ClipControllerTests {
    @Test func stopClearsVisiblePlaybackState() {
        let clips = ClipController.still(caption: "Fold the corner.")
        #expect(clips.phase == .playing)
        #expect(clips.caption == "Fold the corner.")
        clips.isDucked = true
        clips.stop()
        #expect(clips.phase == .idle)
        #expect(clips.caption == nil)
        #expect(clips.slots.allSatisfy { $0 == nil })
        #expect(!clips.isDucked)
    }
}

@MainActor
struct StatusBadgeTests {
    func state(_ status: HubState.Status = .watching, camera: Bool = true, offline: Bool = false,
               mode: HubState.CheckMode? = .gemini, step: Int = 1) -> HubState {
        HubState(lessonId: "l", rev: 1, step: step, total: 4, status: status, cameraConnected: camera,
                 checkOffline: offline, checkOfflineReason: offline ? .budget : nil, checkMode: mode)
    }
    let cameraStep = Step(n: 2, start: "0", end: "5")
    let manualStep = Step(n: 2, start: "0", end: "5", checkType: .manual)

    @Test func precedence() {
        #expect(LearnStatus.resolve(state(.done, offline: true), step: manualStep) == .done)
        #expect(LearnStatus.resolve(state(.verified, offline: true), step: cameraStep) == .verified)
        #expect(LearnStatus.resolve(state(.watching), step: cameraStep, flashVerified: true) == .verified)
        #expect(LearnStatus.resolve(state(.watching, offline: true), step: manualStep) == .manual)
        #expect(LearnStatus.resolve(state(.checking, camera: false, offline: true, mode: .mock), step: cameraStep) == .checksOff)
        #expect(LearnStatus.resolve(state(.checking, camera: false, mode: .mock), step: cameraStep) == .simulated)
        #expect(LearnStatus.resolve(state(.checking, camera: false), step: cameraStep) == .noCamera)
        #expect(LearnStatus.resolve(state(.checking), step: cameraStep) == .checking)
        #expect(LearnStatus.resolve(state(.watching), step: cameraStep) == .watching)
    }

    @Test func simulatedIsNeverGuessed() {
        #expect(LearnStatus.resolve(state(mode: nil), step: cameraStep) == .watching)
    }

    @Test func metaLines() {
        var s = state()
        s.lastCheck = .init(done: .no, confidence: 0.82, latencyMs: 910, reason: "corners not lined up")
        #expect(LearnStatus.meta(.watching, state: s) == ["Last check 0.9 s", "corners not lined up"])
        s.lastCheck = .init(done: .no, confidence: 0.6, latencyMs: 1260, reason: "low confidence")
        #expect(LearnStatus.meta(.watching, state: s) == ["Last check 1.3 s"], "reason only at 0.7 or more")
        #expect(LearnStatus.meta(.checksOff, state: state(offline: true)) == ["Check spending limit reached."])
        #expect(LearnStatus.offlineMeta(.noKey) == "No check key on the hub.")
        #expect(LearnStatus.offlineMeta(HubState.OfflineReason(rawValue: "new")) == "Checks are off. Use Next to move on.")
        #expect(LearnStatus.meta(.verified, state: s).isEmpty)
    }

    @Test func pills() {
        var s = state(offline: true, mode: .mock)
        s.checkOfflineReason = .noKey
        s.camera = CameraInfo(name: "clip.mp4", platform: .replay, source: .file)
        let pills = LearnView.pills(for: s, showRecording: true)
        #expect(pills.map(\.text) == ["Mock checks", "Checks off: No API key", "Recording"])
        #expect(LearnView.offlinePillReason(.budget) == "AI budget reached")
        #expect(LearnView.pills(for: state(), showRecording: true).isEmpty)
    }

    @Test func noDashesInCopy() {
        var strings = LearnStatus.allCases.flatMap { [$0.label, $0.voiceOver] }
        strings += StepStatus.allCases.map(\.word)
        strings += ["Not enough data", "Lesson complete"]
        for s in strings { #expect(!s.contains("\u{2014}") && !s.contains("\u{2013}"), "\(s)") }
    }
}

@MainActor
struct MistakeKindTests {
    @Test func mapsWireKinds() {
        let behind = MistakeMessage(step: 3, kind: .behind, looksLike: 2, message: "Flip it over first.", confidence: 0.9, source: "gemini")
        #expect(MistakeKind(behind) == .behind(looksLike: 2))
        let ahead = MistakeMessage(step: 3, kind: .ahead, looksLike: 4, message: "You're ahead.", confidence: 0.9, source: "gemini")
        #expect(MistakeKind(ahead) == .ahead)
    }

    @Test func liveMistakeReadsAsLive() throws {
        // A live mistake has no looks_like, so it decodes as kind behind with looks_like == step.
        let json = #"{"type":"mistake","step":2,"kind":"live","label":"overfold","message":"Crease along the line.","confidence":0.8,"source":"gemini"}"#
        guard case .mistake(let m) = HubMessage.decode(text: json) else {
            Issue.record("did not decode")
            return
        }
        #expect(MistakeKind(m) == .live)
        #expect(MistakeCard(kind: .live, message: m.message).shownMessage == "Crease along the line.")
        #expect(MistakeCard(kind: .behind(looksLike: 1), message: " ").shownMessage == "This still looks like step 2.")
    }
}

@MainActor
struct RunRecorderTests {
    let t0 = Date(timeIntervalSince1970: 1_000_000)
    func at(_ s: Double) -> Date { t0.addingTimeInterval(s) }
    func state(_ step: Int, total: Int = 4, status: HubState.Status = .watching, offline: Bool = false) -> HubState {
        HubState(lessonId: "l", rev: 1, step: step, total: total, status: status, cameraConnected: true,
                 checkOffline: offline)
    }

    @Test func timesAndExits() {
        var r = RunRecorder()
        r.observe(state(0), advance: nil, at: at(0))
        let a1 = Advance(from: 0, to: 1, reason: .button)
        let c1 = r.observe(state(1), advance: a1, at: at(6))
        #expect(c1 == .init(from: 0, to: 1, reason: .button, visitSeconds: 6, mistakes: 0))
        let a2 = Advance(from: 1, to: 2, reason: .camera)
        r.observe(state(2), advance: a2, at: at(16))
        r.observe(state(1), advance: a2, at: at(20))  // back: no exit recorded, stale advance ignored
        r.observe(state(2), advance: a2, at: at(23))  // stale advance matches from 1 to 2 again: still camera
        r.observe(state(3), advance: nil, at: at(30))  // goto forward: skipped
        #expect(r.statuses() == [.doneByHand, .doneByCamera, .skipped, .current])
        #expect(r.seconds(1) == 13, "summed across visits")
        #expect(r.seconds(2) == 11)
    }

    @Test func aheadAdvanceCountsTheJumpedStepAsCamera() {
        var r = RunRecorder()
        r.observe(state(1), advance: nil, at: at(0))
        let change = r.observe(state(3), advance: Advance(from: 1, to: 3, reason: .camera), at: at(9))
        #expect(change?.reason == .camera)
        #expect(r.statuses() == [.notStarted, .doneByCamera, .doneByCamera, .current])
    }

    @Test func shortVisitsHaveNoTimeAndDoneSetsFinish() {
        var r = RunRecorder()
        r.observe(state(0, total: 2), advance: nil, at: at(0))
        let c = r.observe(state(1, total: 2), advance: Advance(from: 0, to: 1, reason: .button), at: at(0.4))
        #expect(c?.visitSeconds == nil)
        r.observe(HubState(lessonId: "l", rev: 1, step: 1, total: 2, status: .done), advance: Advance(from: 1, to: 2, reason: .camera), at: at(9))
        #expect(r.isDone)
        #expect(r.finishedAt == at(9))
        #expect(r.statuses() == [.doneByHand, .doneByCamera])
    }

    @Test func mistakesCountOncePerVisitAndAheadIsNotOne() {
        var r = RunRecorder()
        r.observe(state(2), advance: nil, at: at(0))
        let m = MistakeMessage(step: 2, kind: .behind, looksLike: 1, message: "Flip it over first.", confidence: 0.9, source: "g")
        r.observe(mistake: m)
        r.observe(mistake: m)
        r.observe(mistake: MistakeMessage(step: 2, kind: .ahead, looksLike: 3, message: "You're ahead.", confidence: 0.9, source: "g"))
        #expect(r.steps[2].mistakes == 1)
        let change = r.observe(state(3), advance: Advance(from: 2, to: 3, reason: .camera), at: at(5))
        #expect(change?.mistakes == 1)
    }

    @Test func checksOffAndDisconnects() {
        var r = RunRecorder()
        r.observe(state(0), advance: nil, at: at(0))
        r.observe(state(0, offline: true), advance: nil, at: at(1))
        #expect(r.steps[0].checksOff)
        r.connection(false, at: at(2))
        r.connection(true, at: at(5))
        #expect(!r.interrupted, "3 s is not an interruption")
        let c = r.observe(state(1), advance: Advance(from: 0, to: 1, reason: .button), at: at(10))
        #expect(c?.visitSeconds == nil, "a visit with a disconnect shows no time")
        #expect(r.seconds(0) == 7, "time away is not charged")
        r.connection(false, at: at(11))
        r.connection(true, at: at(30))
        #expect(r.interrupted)
    }

    @Test func newLessonResets() {
        var r = RunRecorder()
        r.observe(state(2), advance: nil, at: at(0))
        r.observe(HubState(lessonId: "other", rev: 1, step: 0, total: 3), advance: nil, at: at(5))
        #expect(r.lessonId == "other")
        #expect(r.statuses() == [.current, .notStarted, .notStarted])
    }
}

@MainActor
struct StepResultTests {
    @Test func copyRules() {
        #expect(StepResult.make(yours: 12, expert: 20, mistakesFixed: 0, byCamera: true)
            == .init(symbol: "hare", text: "Nice. 12 s, faster than the expert."))
        #expect(StepResult.make(yours: 21, expert: 20, mistakesFixed: 0, byCamera: false).text
            == "Done. 21 s, about the expert's time.")
        #expect(StepResult.make(yours: 65, expert: 20, mistakesFixed: 0, byCamera: false).text == "Done in 1:05.")
        #expect(StepResult.make(yours: 65, expert: 20, mistakesFixed: 2, byCamera: true).text == "Done. 2 mistakes fixed.")
        #expect(StepResult.make(yours: 65, expert: 20, mistakesFixed: 1, byCamera: true).text == "Done. 1 mistake fixed.")
        #expect(StepResult.make(yours: nil, expert: 20, mistakesFixed: 0, byCamera: true)
            == .init(symbol: "checkmark.circle", text: "Verified."))
        #expect(StepResult.make(yours: nil, expert: nil, mistakesFixed: 0, byCamera: false).text == "Done.")
    }

    @Test func timeWords() {
        #expect(HOTime.short(9.4) == "9 s")
        #expect(HOTime.short(59.6) == "1:00")
        #expect(HOTime.clock(100) == "1:40")
        #expect(HOTime.spoken(65) == "1 minute 5 seconds")
        #expect(LearnStatus.seconds(910) == "0.9 s")
    }
}

@MainActor
struct PiPTests {
    let size = CGSize(width: 360, height: 500)

    @Test func snapsToTheQuadrantOfThePredictedEnd() {
        #expect(PiPCorner.nearest(to: CGPoint(x: 10, y: 10), in: size) == .topLeading)
        #expect(PiPCorner.nearest(to: CGPoint(x: 300, y: 40), in: size) == .topTrailing)
        #expect(PiPCorner.nearest(to: CGPoint(x: 20, y: 480), in: size) == .bottomLeading)
        #expect(PiPCorner.nearest(to: CGPoint(x: 900, y: 900), in: size) == .bottomTrailing, "a throw past the edge")
    }

    @Test func restingCentersKeepTheInset() {
        let tile = CGSize(width: 108, height: 144)
        #expect(PiPCorner.topLeading.center(tile: tile, in: size, inset: 12) == CGPoint(x: 66, y: 84))
        #expect(PiPCorner.bottomTrailing.center(tile: tile, in: size, inset: 12) == CGPoint(x: 294, y: 416))
    }
}

@MainActor
struct ProgressAndCourseTests {
    @Test func segments() {
        #expect(StepProgressBar.segments(total: 0, current: 0, mistake: false) == [.upcoming])
        #expect(StepProgressBar.segments(total: 4, current: 2, mistake: true) == [.done, .done, .currentMistake, .upcoming])
        #expect(StepProgressBar.segments(total: 3, current: 3, mistake: false) == [.done, .done, .done])
    }

    @Test func skipConfirmOnlyWhenPassingUnfinishedSteps() {
        let s: [StepStatus] = [.doneByHand, .current, .notStarted, .notStarted]
        #expect(CourseView.needsSkipConfirm(to: 3, current: 1, statuses: s))
        #expect(!CourseView.needsSkipConfirm(to: 0, current: 1, statuses: s), "going back")
        let done: [StepStatus] = [.current, .doneByCamera, .doneByCamera, .notStarted]
        #expect(CourseView.needsSkipConfirm(to: 3, current: 0, statuses: done), "the current step is not done")
        #expect(!CourseView.needsSkipConfirm(to: 2, current: nil, statuses: done))
    }

    @Test func scoreLabels() {
        #expect(ScoreRing.label(for: 85) == "Excellent")
        #expect(ScoreRing.label(for: 84) == "Good")
        #expect(ScoreRing.label(for: 59) == "Keep practicing")
        #expect(ScoreRing.tone(for: "Good") == .accent)
    }
}

@MainActor
struct RunSummaryTests {
    let t0 = Date(timeIntervalSince1970: 2_000_000)
    let lesson = PreviewHub.fortuneTeller.lesson  // 5 steps: 6, 8, 17, 5, 22 s; steps 1 and 5 manual

    func run(_ events: (inout RunRecorder, (Double) -> Date) -> Void) -> RunSummary {
        var r = RunRecorder()
        events(&r) { self.t0.addingTimeInterval($0) }
        return RunSummary(recorder: r, lesson: lesson)
    }

    func s(_ step: Int, done: Bool = false, offline: Bool = false) -> HubState {
        HubState(lessonId: lesson.id, rev: 1, step: step, total: 5, status: done ? .done : .watching,
                 cameraConnected: true, checkOffline: offline)
    }

    @Test func fullRunScoresByTheRules() {
        let summary = run { r, at in
            r.observe(s(0), advance: nil, at: at(0))
            r.observe(s(1), advance: Advance(from: 0, to: 1, reason: .button), at: at(6))   // 6 vs 6
            r.observe(mistake: MistakeMessage(step: 1, kind: .behind, looksLike: 0, message: "", confidence: 0.9, source: "g"))
            r.observe(s(2), advance: Advance(from: 1, to: 2, reason: .camera), at: at(22))  // 16 vs 8
            r.observe(s(3), advance: Advance(from: 2, to: 3, reason: .camera), at: at(39))  // 17 vs 17
            r.observe(s(4), advance: Advance(from: 3, to: 4, reason: .button), at: at(49))  // 10 vs 5, camera step by hand
            r.observe(s(4, done: true), advance: Advance(from: 4, to: 5, reason: .button), at: at(71))  // 22 vs 22
        }
        #expect(summary.runSeconds == 71)
        #expect(summary.expertSeconds == 58)
        #expect(summary.checkedByCamera == 2 && summary.cameraSteps == 3)
        #expect(summary.markedDone == 3 && summary.mistakes == 1 && summary.skipped == 0)
        // Checked 2/3; pace mean(1, .5, 1, .5, 1) = .8; clean 1 - 1/5 = .8.
        // 100 * (.5 * .6667 + .3 * .8 + .2 * .8) = 73.3
        #expect(summary.score == 73)
        #expect(summary.scoreParts == ["2 of 3 camera steps checked by camera.", "Your pace was 80% of the expert's.",
                                       "1 mistake in 5 steps."])
        #expect(summary.weakest == 1, "most mistakes")
        #expect(summary.best == 2, "camera verified, no mistakes, lowest ratio")
        #expect(summary.tip == "On step 2, watch for this: Line the corners up exactly before creasing.")
        #expect(summary.weakestReason(1) == "1 mistake, 0:16 against 0:08.")
        #expect(summary.bestReason(2) == "Checked by camera in 17 s.")
    }

    @Test func notEnoughDataWhenTooFewTimes() {
        let summary = run { r, at in
            r.observe(s(0), advance: nil, at: at(0))
            r.observe(s(4), advance: nil, at: at(5))
            r.observe(s(4, done: true), advance: Advance(from: 4, to: 5, reason: .button), at: at(30))
        }
        #expect(summary.score == nil)
        #expect(summary.best == nil && summary.weakest == nil)
        #expect(summary.skipped == 4)
        #expect(summary.tip == "You skipped step 1. Try it once so the camera can check it.")
    }

    @Test func interruptedRunHasNoScoreOrRunTime() {
        let summary = run { r, at in
            r.observe(s(0), advance: nil, at: at(0))
            r.connection(false, at: at(1))
            r.connection(true, at: at(20))
            for i in 1...4 { r.observe(s(i), advance: Advance(from: i - 1, to: i, reason: .button), at: at(20 + Double(i) * 6)) }
            r.observe(s(4, done: true), advance: Advance(from: 4, to: 5, reason: .button), at: at(60))
        }
        #expect(summary.interrupted)
        #expect(summary.score == nil && summary.runSeconds == nil)
    }

    @Test func checkedPartIsDroppedWhenChecksWereOff() {
        let lines = [RunSummary.Line(index: 0, n: 1, title: "a", isCameraStep: true, expert: 10, yours: 10, how: .doneByHand,
                                     mistakes: 0, checksOff: true, commonMistake: ""),
                     RunSummary.Line(index: 1, n: 2, title: "b", isCameraStep: false, expert: 10, yours: 20, how: .doneByHand,
                                     mistakes: 0, checksOff: false, commonMistake: "")]
        let (score, parts) = RunSummary.score(lines: lines, interrupted: false)
        // 100 * (.6 * .75 + .4 * 1) = 85
        #expect(score == 85)
        #expect(parts.count == 2)
        #expect(RunSummary.tip(lines: lines, weakest: 1) == "Checks were off for part of this run, so try again for a full score.")
    }

    @Test func runIdValidation() {
        #expect(DoneAPI.isValidRunId("r_20261114-abc"))
        #expect(!DoneAPI.isValidRunId("../etc"))
        #expect(!DoneAPI.isValidRunId(""))
    }
}

@MainActor
struct SpeechQueueTests {
    let t0 = Date(timeIntervalSince1970: 3_000_000)
    func at(_ s: Double) -> Date { t0.addingTimeInterval(s) }

    @Test func neverOverlaps() {
        var q = SpeechQueue()
        #expect(q.enqueue("Step 1. Lay it flat.", kind: .step, at: at(0))?.text == "Step 1. Lay it flat.")
        #expect(q.enqueue("Nice.", kind: .result, at: at(0.5)) == nil, "waits while one is speaking")
        #expect(q.speaking?.text == "Step 1. Lay it flat.")
        #expect(q.finished(at: at(2))?.text == "Nice.")
        #expect(q.finished(at: at(3)) == nil)
        #expect(q.speaking == nil)
    }

    @Test func noRepeatsWithinThreeSeconds() {
        var q = SpeechQueue()
        _ = q.enqueue("Flip it over first.", kind: .mistake, at: at(0))
        #expect(q.enqueue("Flip it over first.", kind: .mistake, at: at(0.2)) == nil, "already speaking")
        _ = q.finished(at: at(1.5))
        #expect(q.enqueue("Flip it over first.", kind: .mistake, at: at(2.9)) == nil, "started 2.9 s ago")
        #expect(q.enqueue("Flip it over first.", kind: .mistake, at: at(3.1))?.text == "Flip it over first.")
    }

    @Test func waitingDuplicatesAreDropped() {
        var q = SpeechQueue()
        _ = q.enqueue("a", kind: .step, at: at(0))
        _ = q.enqueue("b", kind: .step, at: at(0))
        _ = q.enqueue("b", kind: .step, at: at(10))
        #expect(q.pending.map(\.text) == ["b"])
    }

    @Test func mistakesJumpAheadAndTheLineStaysShort() {
        var q = SpeechQueue()
        _ = q.enqueue("Step 2.", kind: .step, at: at(0))
        _ = q.enqueue("Nice.", kind: .result, at: at(0))
        _ = q.enqueue("Step 3.", kind: .step, at: at(0))
        _ = q.enqueue("Step 4.", kind: .step, at: at(0))
        _ = q.enqueue("Flip it over first.", kind: .mistake, at: at(0))
        #expect(q.pending.count == SpeechQueue.maxPending)
        #expect(q.pending.first?.text == "Flip it over first.")
        #expect(q.pending.contains { $0.text == "Step 4." }, "the oldest step line goes first")
    }

    @Test func emptyTextIsIgnoredAndClearStops() {
        var q = SpeechQueue()
        #expect(q.enqueue("  ", kind: .step, at: at(0)) == nil)
        _ = q.enqueue("a", kind: .step, at: at(0))
        _ = q.enqueue("b", kind: .step, at: at(0))
        q.clear()
        #expect(q.speaking == nil && q.pending.isEmpty)
    }

    @Test func spokenStepAndGlassesRoute() {
        #expect(LearnView.spokenStep(Step(n: 5, title: "Flip the paper over", start: "0", end: "1")) == "Step 5. Flip the paper over.")
        #expect(LearnView.spokenStep(Step(n: 2, title: "Done?", start: "0", end: "1")) == "Step 2. Done?")
        #expect(LearnView.spokenStep(Step(n: 3, start: "0", end: "1")) == "Step 3.")
        #expect(SpokenGuide.looksLikeGlasses("Ray-Ban Meta"))
        #expect(!SpokenGuide.looksLikeGlasses("AirPods Pro"))
    }
}

package com.handover.app.ui.teach

import com.handover.app.ui.library.RawJob

// Honest processing progress (SCREENS.md section 13): a stage appears only once the hub reports it, shows as
// done only when the hub moves past it, and carries the hub's own message. No invented percentages.

/** A processing stage the hub can report, with the words for it. */
enum class Stage(val active: String, val done: String) {
    Upload("Uploading", "Uploaded"),
    Queued("Waiting for the hub", "Started"),
    Normalizing("Preparing video", "Video prepared"),
    Transcribing("Transcribing narration", "Narration transcribed"),
    Extracting("Finding steps", "Steps found"),
    Cutting("Cutting clips", "Clips cut"),
    SelfTest("Testing check questions", "Check questions tested"),
    Rubric("Studying each step", "Steps studied"),
    Waiting("Waiting for the computer to free up", "Started rendering"),
    Rendering("Making the course video", "Course video made"),
    Voiceover("Writing voiceover", "Voiceover added"),
    Other("Working", "Done"),
}

enum class RowState { Active, Done, Failed }

/** One row of the stage list. [label] is set for [Stage.Other], from the hub's status word. */
data class StageRow(
    val stage: Stage,
    val state: RowState,
    val message: String = "",
    val label: String? = null,
    /** 0 to 1, only when the hub reports progress. */
    val progress: Double? = null,
) {
    fun text(stepsFound: Int? = null): String = when {
        stage == Stage.Other -> label ?: stage.active
        state == RowState.Done && stage == Stage.Extracting && stepsFound != null -> if (stepsFound == 1) "1 step found" else "$stepsFound steps found"
        state == RowState.Done -> stage.done
        else -> stage.active
    }
}

/** The stage for a hub status and message. The hub reports transcription inside `extracting` by its message. */
fun stageOf(status: String, message: String): Stage = when (status.lowercase()) {
    "queued" -> Stage.Queued
    "normalizing" -> Stage.Normalizing
    "transcribing" -> Stage.Transcribing
    "extracting" -> if (message.startsWith("Transcrib") || message.startsWith("Downloading speech model")) Stage.Transcribing else Stage.Extracting
    "cutting" -> Stage.Cutting
    "self-test", "selftest", "self_test" -> Stage.SelfTest
    "rubric" -> Stage.Rubric
    "waiting" -> Stage.Waiting
    "rendering", "assist", "producing" -> Stage.Rendering
    "voiceover" -> Stage.Voiceover
    else -> Stage.Other
}

/**
 * Folds one job status into the rows. A new stage closes every open row and opens its own; the same stage
 * only updates its message. `done` closes everything; `error` marks the open row failed with the hub's text.
 */
fun List<StageRow>.observe(job: RawJob): List<StageRow> {
    val status = job.status.lowercase()
    if (status == "done") return map { if (it.state == RowState.Active) it.copy(state = RowState.Done, message = "", progress = null) else it }
    if (status == "error") {
        val open = indexOfLast { it.state == RowState.Active }
        return if (open >= 0) mapIndexed { i, r -> if (i == open) r.copy(state = RowState.Failed, message = job.message) else r }
        else this + StageRow(Stage.Other, RowState.Failed, job.message, label = "Processing failed")
    }
    val stage = stageOf(status, job.message)
    val label = if (stage == Stage.Other) status.replace('_', ' ').replace('-', ' ').replaceFirstChar { it.uppercase() } else null
    val current = lastOrNull { it.state == RowState.Active }
    if (current != null && current.stage == stage && current.label == label) {
        return map { if (it === current) it.copy(message = job.message, progress = job.progress?.coerceIn(0.0, 1.0)) else it }
    }
    val closed = map { if (it.state == RowState.Active) it.copy(state = RowState.Done, message = "", progress = null) else it }
    // A stage the hub returns to (it reports `extracting` again after transcribing) moves to the end, once.
    val row = StageRow(stage, RowState.Active, job.message, label, job.progress?.coerceIn(0.0, 1.0))
    return closed.filterNot { it.stage == stage && it.label == label } + row
}

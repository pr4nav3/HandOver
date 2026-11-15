package com.handover.app.ui.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Redo
import androidx.compose.material.icons.automirrored.outlined.Undo
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.automirrored.outlined.CallMerge
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ContentCut
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.FolderOff
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.RecordVoiceOver
import androidx.compose.material.icons.outlined.Remove
import androidx.compose.material.icons.outlined.Verified
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.handover.app.core.Answer
import com.handover.app.core.CheckType
import com.handover.app.core.HubUrl
import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.ui.library.Badge
import com.handover.app.ui.library.CourseApi
import com.handover.app.ui.library.EmptyState
import com.handover.app.ui.library.HOCard
import com.handover.app.ui.library.HubImage
import com.handover.app.ui.library.LocalPreviewImages
import com.handover.app.ui.library.PrimaryButton
import com.handover.app.ui.library.QuietButton
import com.handover.app.ui.library.SecondaryButton
import com.handover.app.ui.library.SectionHeader
import com.handover.app.ui.library.SegmentedRow
import com.handover.app.ui.library.Tone
import com.handover.app.ui.library.clock
import com.handover.app.ui.library.rememberHaptics
import com.handover.app.ui.library.statusLabel
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver

/** File URLs for the editor's pictures and clips, so the stateless content needs no hub. */
data class EditorUrls(val clip: (Step, Long) -> String?, val frame: (Step, Long) -> String?)

@Composable
fun EditorScreen(hub: HubUrl, lessonId: String, modifier: Modifier = Modifier, onClose: () -> Unit, onPreview: () -> Unit = {}) {
    val editor: EditorViewModel = viewModel(key = "editor-${hub.display}-$lessonId") { EditorViewModel(CourseApi.forHub(hub), lessonId) }
    val ui by editor.state.collectAsStateWithLifecycle()
    val api = CourseApi.forHub(hub)
    val urls = remember(api, lessonId) {
        EditorUrls(
            clip = { s, rev -> s.clip?.let { api.fileUrl(lessonId, it, rev) } },
            frame = { s, rev -> s.refFrame?.let { api.fileUrl(lessonId, it, rev) } },
        )
    }
    EditorContent(ui, urls, editor, modifier, onClose, onPreview)
}

/** The editor's actions, so previews can pass a stand-in. */
interface EditorActions {
    fun select(i: Int) {}
    fun dragBoundary(k: Int, t: Double) {}
    fun commitBoundary(k: Int, t: Double) {}
    fun split(i: Int, at: Double) {}
    fun merge(i: Int) {}
    fun delete(i: Int) {}
    fun rename(i: Int, title: String) {}
    fun setCheckType(i: Int, type: CheckType) {}
    fun setQuestion(i: Int, question: String) {}
    fun setMistake(i: Int, text: String) {}
    fun saveCaptions(i: Int, cues: List<Cue>) {}
    fun testQuestion(i: Int) {}
    fun regenerateVoiceover(i: Int) {}
    fun undo() {}
    fun redo() {}
    fun retrySave() {}
    fun dismissBanner() {}
    fun load() {}
    fun publish(audience: String, toOrg: Boolean, unlisted: Boolean, done: (String?) -> Unit) {}
}

private class VmActions(private val vm: EditorViewModel) : EditorActions {
    override fun select(i: Int) = vm.select(i)
    override fun dragBoundary(k: Int, t: Double) = vm.dragBoundary(k, t)
    override fun commitBoundary(k: Int, t: Double) = vm.commitBoundary(k, t)
    override fun split(i: Int, at: Double) = vm.split(i, at)
    override fun merge(i: Int) = vm.merge(i)
    override fun delete(i: Int) = vm.delete(i)
    override fun rename(i: Int, title: String) = vm.rename(i, title)
    override fun setCheckType(i: Int, type: CheckType) = vm.setCheckType(i, type)
    override fun setQuestion(i: Int, question: String) = vm.setQuestion(i, question)
    override fun setMistake(i: Int, text: String) = vm.setMistake(i, text)
    override fun saveCaptions(i: Int, cues: List<Cue>) = vm.saveCaptions(i, cues)
    override fun testQuestion(i: Int) = vm.testQuestion(i)
    override fun regenerateVoiceover(i: Int) = vm.regenerateVoiceover(i)
    override fun undo() = vm.undo()
    override fun redo() = vm.redo()
    override fun retrySave() = vm.retrySave()
    override fun dismissBanner() = vm.dismissBanner()
    override fun load() = vm.load()
    override fun publish(audience: String, toOrg: Boolean, unlisted: Boolean, done: (String?) -> Unit) = vm.publish(audience, toOrg, unlisted, done)
}

@Composable
private fun EditorContent(ui: EditorUi, urls: EditorUrls, vm: EditorViewModel, modifier: Modifier, onClose: () -> Unit, onPreview: () -> Unit) {
    val actions = remember(vm) { VmActions(vm) }
    EditorContent(ui, urls, actions, modifier, onClose, onPreview)
}

/**
 * The course editor (SCREENS.md section 14), stateless. Two panes at 840 dp and wider (player, timeline and
 * steps on the left, the inspector on the right); one stacked column on phones.
 */
@Composable
fun EditorContent(ui: EditorUi, urls: EditorUrls, actions: EditorActions, modifier: Modifier = Modifier, onClose: () -> Unit = {}, onPreview: () -> Unit = {}) {
    val c = HandOver.colors
    var publishing by rememberSaveable { mutableStateOf(false) }
    Column(modifier.fillMaxSize().background(c.paper)) {
        EditorBar(ui, actions, onClose, onPreview, onPublish = { publishing = true })
        val lesson = ui.lesson
        when {
            lesson == null && ui.loading -> EmptyState(null, "Loading lesson", loading = true)
            lesson == null -> EmptyState(Icons.Outlined.FolderOff, "This lesson cannot be opened", ui.loadError, tone = Tone.Bad) { SecondaryButton("Try Again", actions::load) }
            else -> {
                ui.banner?.let { Banner(it, actions::dismissBanner) }
                BoxWithConstraints(Modifier.fillMaxSize()) {
                    val wide = maxWidth >= 840.dp
                    var playhead by remember { mutableStateOf<Double?>(null) }
                    if (wide) {
                        Row(Modifier.fillMaxSize().padding(horizontal = HOSpace.xl), horizontalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
                            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(bottom = HOSpace.xl)) {
                                Workspace(ui, lesson, urls, actions, playhead) { playhead = it }
                            }
                            Column(Modifier.width(360.dp).verticalScroll(rememberScrollState()).padding(bottom = HOSpace.xl)) {
                                Inspector(ui, actions)
                            }
                        }
                    } else {
                        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(bottom = HOSpace.xxl)) {
                            Workspace(ui, lesson, urls, actions, playhead) { playhead = it }
                            Inspector(ui, actions)
                        }
                    }
                }
            }
        }
    }
    if (publishing && ui.course != null) PublishSheet(ui, actions) { publishing = false }
}

@Composable
private fun EditorBar(ui: EditorUi, actions: EditorActions, onClose: () -> Unit, onPreview: () -> Unit, onPublish: () -> Unit) {
    val c = HandOver.colors
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        // Phones: the badge moves under the title and Preview goes into More, so nothing is squeezed.
        val compact = maxWidth < 600.dp
        var more by remember { mutableStateOf(false) }
        Row(Modifier.fillMaxWidth().padding(horizontal = HOSpace.xs, vertical = HOSpace.xs), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back", tint = c.ink) }
            Column(Modifier.weight(1f)) {
                Text(ui.lesson?.title ?: "Edit Lesson", style = HandOver.type.headline, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SaveLabel(ui.save, actions::retrySave)
                    if (compact) ui.course?.let { course -> statusLabel(course.status)?.let { Spacer(Modifier.width(HOSpace.s)); Badge(it) } }
                }
            }
            if (!compact) ui.course?.let { course -> statusLabel(course.status)?.let { Badge(it); Spacer(Modifier.width(HOSpace.xs)) } }
            IconButton(onClick = actions::undo, enabled = ui.canUndo && !ui.busy) {
                Icon(Icons.AutoMirrored.Outlined.Undo, "Undo", tint = if (ui.canUndo && !ui.busy) c.ink else c.ink3)
            }
            IconButton(onClick = actions::redo, enabled = ui.canRedo && !ui.busy) {
                Icon(Icons.AutoMirrored.Outlined.Redo, "Redo", tint = if (ui.canRedo && !ui.busy) c.ink else c.ink3)
            }
            if (ui.lesson != null) {
                if (compact) {
                    Box {
                        IconButton(onClick = { more = true }) { Icon(Icons.Outlined.MoreVert, "More", tint = c.ink) }
                        DropdownMenu(expanded = more, onDismissRequest = { more = false }) {
                            DropdownMenuItem(text = { Text("Preview") }, onClick = { more = false; onPreview() })
                        }
                    }
                } else QuietButton("Preview", onPreview)
            }
            if (ui.features.publish) {
                PrimaryButton(if (ui.course?.status == "draft") "Publish" else "Update", onPublish, large = false, modifier = Modifier.padding(end = HOSpace.s))
            }
        }
    }
}

@Composable
private fun SaveLabel(save: SaveState, onRetry: () -> Unit) {
    val c = HandOver.colors
    val (text, color) = when (save) {
        SaveState.Idle -> return
        SaveState.Saving -> "Saving" to c.ink2
        SaveState.UpdatingClips -> "Updating clips" to c.ink2
        SaveState.Saved -> "Saved" to c.ink2
        is SaveState.Failed -> "Could not save" to c.bad
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = HandOver.type.footnote, color = color)
        if (save is SaveState.Failed) Text(
            "Try Again", style = HandOver.type.footnote, color = c.accentInk,
            modifier = Modifier.padding(start = HOSpace.s).clickable(role = Role.Button, onClick = onRetry),
        )
    }
}

@Composable
private fun Banner(text: String, onDismiss: () -> Unit) {
    val c = HandOver.colors
    HOCard(Modifier.fillMaxWidth().padding(horizontal = HOSpace.l, vertical = HOSpace.s), radius = HORadius.control, padding = HOSpace.m) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.ErrorOutline, null, Modifier.size(20.dp), tint = c.caution)
            Spacer(Modifier.width(HOSpace.s))
            Text(text, style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.weight(1f), maxLines = 3)
            QuietButton("OK", onDismiss)
        }
    }
}

/** Player, timeline, split, merge and delete, then the step list. */
@Composable
private fun ColumnScope.Workspace(ui: EditorUi, lesson: Lesson, urls: EditorUrls, actions: EditorActions, playhead: Double?, onPlayhead: (Double?) -> Unit) {
    val c = HandOver.colors
    val i = ui.selected
    val step = lesson.steps.getOrNull(i)
    var clipPos by remember(i) { mutableStateOf(0.0) }
    val cue = ui.cues.getOrNull(i)?.firstOrNull { clipPos >= it.start && clipPos < it.end }?.text
    ClipPlayer(
        url = step?.let { urls.clip(it, ui.rev) },
        poster = listOfNotNull(step?.let { urls.frame(it, ui.rev) }),
        caption = cue,
        label = "Clip for step ${i + 1}",
        modifier = Modifier.widthIn(max = 720.dp).fillMaxWidth().align(Alignment.CenterHorizontally).aspectRatio(16f / 9f).clip(RoundedCornerShape(HORadius.card)),
        onPosition = { p -> clipPos = p; onPlayhead(step?.let { it.startSeconds() + p }) },
    )
    Spacer(Modifier.height(HOSpace.l))
    StepTimeline(
        lesson = lesson,
        selected = i,
        editable = !ui.busy,
        snaps = ui.snaps,
        playhead = playhead,
        onSelect = actions::select,
        onDrag = actions::dragBoundary,
        onDragEnd = actions::commitBoundary,
    )
    Spacer(Modifier.height(HOSpace.s))
    val splitAt = step?.let { s -> playhead?.takeIf { lesson.canSplit(i, it) } ?: ((s.startSeconds() + s.endSeconds()) / 2).takeIf { lesson.canSplit(i, it) } }
    var confirmDelete by remember { mutableStateOf(false) }
    var confirmMerge by remember { mutableStateOf(false) }
    Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        SecondaryButton("Split", { splitAt?.let { actions.split(i, it) } }, enabled = splitAt != null && !ui.busy, icon = Icons.Outlined.ContentCut)
        SecondaryButton("Merge", {
            val next = lesson.steps.getOrNull(i + 1)
            if (step != null && next != null && step.checkQuestion != next.checkQuestion && step.checkQuestion.isNotBlank() && next.checkQuestion.isNotBlank()) confirmMerge = true else actions.merge(i)
        }, enabled = i < lesson.steps.size - 1 && !ui.busy, icon = Icons.AutoMirrored.Outlined.CallMerge)
        SecondaryButton("Delete", { confirmDelete = true }, enabled = lesson.steps.size > 1 && !ui.busy, icon = Icons.Outlined.Delete, destructive = true)
    }
    if (splitAt == null && step != null) Text("Too short to split here.", style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(top = HOSpace.xs))
    SectionHeader("Steps")
    lesson.steps.forEachIndexed { k, s -> EditorStepRow(k, s, k == i, urls.frame(s, ui.rev)) { actions.select(k) } }
    if (confirmDelete) Confirm(
        "Delete Step ${i + 1}?", "Its clip is removed from the lesson. You can undo this.", "Delete Step",
        onConfirm = { confirmDelete = false; actions.delete(i) }, onDismiss = { confirmDelete = false },
    )
    if (confirmMerge) Confirm(
        "Merge Steps ${i + 1} and ${i + 2}?", "Step ${i + 2}'s question is kept, because the merged step ends where it ends.", "Merge",
        onConfirm = { confirmMerge = false; actions.merge(i) }, onDismiss = { confirmMerge = false },
    )
}

@Composable
private fun Confirm(title: String, message: String, action: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(message) },
        confirmButton = { TextButton(onClick = onConfirm) { Text(action) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** DESIGN.md 3.10 step row: number tile, thumbnail 72 x 40, title, "0:42 to 1:03, Camera check" or "Manual". */
@Composable
private fun EditorStepRow(i: Int, step: Step, selected: Boolean, frame: String?, onClick: () -> Unit) {
    val c = HandOver.colors
    val meta = "${clock(step.startSeconds())} to ${clock(step.endSeconds())}, " + if (step.checkType == CheckType.Camera) "Camera check" else "Manual"
    Row(
        Modifier.fillMaxWidth().heightIn(min = 60.dp).clip(RoundedCornerShape(HORadius.control))
            .background(if (selected) c.accentSoft else Color.Transparent)
            .clickable(onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = "Step ${i + 1}, ${step.title}, $meta" + if (selected) ", selected" else "" }
            .padding(HOSpace.s),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(32.dp).clip(RoundedCornerShape(9.dp)).background(if (selected) c.raised else c.well), contentAlignment = Alignment.Center) {
            Text("${i + 1}", style = HandOver.type.headline, color = if (selected) c.accentInk else c.ink)
        }
        Spacer(Modifier.width(HOSpace.m))
        HubImage(listOfNotNull(frame), Modifier.width(72.dp).height(40.dp).clip(RoundedCornerShape(HORadius.small)))
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(step.title.ifBlank { "Untitled step" }, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(meta, style = HandOver.type.callout, color = c.ink2)
        }
    }
}

// ------------------------------------------------------------ inspector

@Composable
private fun ColumnScope.Inspector(ui: EditorUi, actions: EditorActions) {
    val c = HandOver.colors
    val lesson = ui.lesson ?: return
    val i = ui.selected
    val step = lesson.steps.getOrNull(i) ?: return
    SectionHeader("Step ${i + 1}")
    CommitField(
        key = "title-$i", value = step.title, label = "Step title", placeholder = "Fold the corners to the center",
        footer = "Short and doable. Start with a verb.", onCommit = { actions.rename(i, it) },
    )

    SectionHeader("Time")
    HOCard(Modifier.fillMaxWidth(), radius = HORadius.control) {
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
            TimeRow("Start", step.startSeconds(), enabled = i > 0 && !ui.busy) { delta -> actions.commitBoundary(i - 1, step.startSeconds() + delta) }
            TimeRow("End", step.endSeconds(), enabled = i < lesson.steps.size - 1 && !ui.busy) { delta -> actions.commitBoundary(i, step.endSeconds() + delta) }
            Text("Length ${clock(step.endSeconds() - step.startSeconds())}", style = HandOver.type.callout, color = c.ink2)
        }
    }

    SectionHeader("How it is checked")
    SegmentedRow(listOf(CheckType.Camera, CheckType.Manual), step.checkType, { if (it == CheckType.Camera) "Camera" else "Manual" }, { actions.setCheckType(i, it) })
    if (i == 0 && step.checkType == CheckType.Camera) {
        Text("Step 1 is often better as Manual: the camera has nothing to compare to yet.", style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(top = HOSpace.s))
    }
    if (step.checkType == CheckType.Camera) {
        Spacer(Modifier.height(HOSpace.m))
        CommitField(
            key = "question-$i", value = step.checkQuestion, label = "Check question",
            placeholder = "Is the paper folded into a small square with four flaps?",
            footer = "Ask about shape and folds you can see, not color.", onCommit = { actions.setQuestion(i, it) }, lines = 3,
        )
        if (ui.features.selfTest) {
            Spacer(Modifier.height(HOSpace.s))
            val test = ui.selfTests[i]
            SecondaryButton(if (test?.running == true) "Testing" else "Test This Question", { actions.testQuestion(i) }, enabled = test?.running != true && !ui.busy, icon = Icons.Outlined.Verified)
            val result = test?.result ?: step.selfTest
            when {
                test?.running == true -> Row(Modifier.padding(top = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = c.ink2)
                    Spacer(Modifier.width(HOSpace.s))
                    Text("Asking the check on two frames", style = HandOver.type.footnote, color = c.ink2)
                }
                test?.error != null -> Text(test.error, style = HandOver.type.footnote, color = c.bad, modifier = Modifier.padding(top = HOSpace.s))
                result != null -> SelfTestCard(result, fresh = test?.result != null, onMakeManual = { actions.setCheckType(i, CheckType.Manual) })
            }
        }
    }

    SectionHeader("Common mistake")
    CommitField(
        key = "mistake-$i", value = step.commonMistake, label = "What do people get wrong here?", placeholder = "Flip it over first.",
        footer = "Shown and spoken when the learner is still on the step before.", onCommit = { actions.setMistake(i, it) }, lines = 2,
    )

    if (ui.features.captions) CaptionsEditor(i, ui.cues.getOrNull(i).orEmpty(), step, ui.busy, actions)

    if (ui.features.voiceover) {
        SectionHeader("Voiceover")
        val v = ui.voice[i]
        Row(verticalAlignment = Alignment.CenterVertically) {
            SecondaryButton(if (v?.running == true) "Regenerating" else "Regenerate Voiceover", { actions.regenerateVoiceover(i) }, enabled = v?.running != true && !ui.busy, icon = Icons.Outlined.RecordVoiceOver)
            if (v?.running == true) { Spacer(Modifier.width(HOSpace.s)); CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = c.ink2) }
        }
        v?.message?.takeIf { !v.running }?.let { Text(it, style = HandOver.type.footnote, color = if (v.failed) c.bad else c.ink2, modifier = Modifier.padding(top = HOSpace.xs)) }
        Text("Rewrites and re-speaks this step's narration.", style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(top = HOSpace.xs))
    }
}

@Composable
private fun TimeRow(label: String, seconds: Double, enabled: Boolean, onNudge: (Double) -> Unit) {
    val c = HandOver.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = HandOver.type.body, color = c.ink, modifier = Modifier.width(56.dp))
        Text(formatEditorTime(seconds), style = HandOver.type.code.copy(fontSize = HandOver.type.body.fontSize), color = c.ink, modifier = Modifier.weight(1f))
        if (enabled) {
            IconButton(onClick = { onNudge(-0.1) }) { Icon(Icons.Outlined.Remove, "$label 0.1 seconds earlier", tint = c.ink) }
            IconButton(onClick = { onNudge(0.1) }) { Icon(Icons.Outlined.Add, "$label 0.1 seconds later", tint = c.ink) }
        }
    }
}

@Composable
private fun SelfTestCard(result: com.handover.app.core.SelfTest, fresh: Boolean, onMakeManual: () -> Unit) {
    val c = HandOver.colors
    val works = result.works()
    HOCard(Modifier.fillMaxWidth().padding(top = HOSpace.s), radius = HORadius.control) {
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.xs)) {
            if (!fresh) Text("Last tested", style = HandOver.type.section, color = c.ink2)
            AnswerRow("On this step's frame", result.own, expected = Answer.Yes)
            AnswerRow("On the previous step's frame", result.prev, expected = Answer.No)
            Spacer(Modifier.height(HOSpace.xs))
            Text(
                if (works) "Works. The question tells this step apart." else "Might misfire. Try a more specific question, or make this step Manual.",
                style = HandOver.type.callout, color = c.ink,
            )
            if (result.mock) Text("Simulated check. This result does not test the question.", style = HandOver.type.footnote, color = c.caution)
            if (!works) QuietButton("Make Manual", onMakeManual)
        }
    }
}

@Composable
private fun AnswerRow(label: String, answer: Answer, expected: Answer) {
    val c = HandOver.colors
    val word = when (answer) { Answer.Yes -> "Yes"; Answer.No -> "No"; Answer.Unsure -> "Unsure" }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = HandOver.type.callout, color = c.ink2, modifier = Modifier.weight(1f))
        Badge(word, if (answer == expected) Tone.Good else Tone.Caution)
    }
}

@Composable
private fun CaptionsEditor(i: Int, saved: List<Cue>, step: Step, busy: Boolean, actions: EditorActions) {
    val c = HandOver.colors
    var draft by remember(i, saved) { mutableStateOf(saved) }
    SectionHeader("Captions")
    if (draft.isEmpty()) Text("No caption lines on this step.", style = HandOver.type.callout, color = c.ink2)
    draft.forEachIndexed { k, cue ->
        Row(Modifier.fillMaxWidth().padding(vertical = HOSpace.xxs), verticalAlignment = Alignment.CenterVertically) {
            Text(formatEditorTime(cue.start), style = HandOver.type.code, color = c.ink2, modifier = Modifier.width(64.dp))
            HOTextField(cue.text, { t -> draft = draft.mapIndexed { j, x -> if (j == k) x.copy(text = t) else x } }, Modifier.weight(1f), placeholder = "Caption line")
            IconButton(onClick = { draft = draft.filterIndexed { j, _ -> j != k } }) { Icon(Icons.Outlined.Delete, "Delete line ${k + 1}", tint = c.ink2) }
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s), modifier = Modifier.padding(top = HOSpace.xs)) {
        QuietButton("Add Line", {
            val length = step.endSeconds() - step.startSeconds()
            val start = (draft.lastOrNull()?.end ?: 0.0).coerceAtMost((length - 1.0).coerceAtLeast(0.0))
            draft = draft + Cue(start, (start + 2.0).coerceAtMost(length), "")
        }, icon = Icons.Outlined.Add)
        if (draft != saved) SecondaryButton("Save Captions", { actions.saveCaptions(i, draft) }, enabled = !busy)
    }
    Text("Captions show under the expert's clip.", style = HandOver.type.footnote, color = c.ink2)
}

/** A field that saves when focus leaves it or Done is pressed: one undo step per edit, not per letter. */
@Composable
private fun CommitField(key: String, value: String, label: String, placeholder: String, footer: String?, onCommit: (String) -> Unit, lines: Int = 1) {
    val c = HandOver.colors
    var text by remember(key, value) { mutableStateOf(value) }
    Text(label, style = HandOver.type.section, color = c.ink2, modifier = Modifier.padding(bottom = HOSpace.xs))
    HOTextField(
        text, { text = it },
        Modifier.fillMaxWidth().onFocusChanged { if (!it.isFocused && text != value) onCommit(text) },
        placeholder = placeholder, lines = lines, onDone = { if (text != value) onCommit(text) },
    )
    if (footer != null) Text(footer, style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(top = HOSpace.xs))
}

@Composable
private fun HOTextField(value: String, onChange: (String) -> Unit, modifier: Modifier, placeholder: String, lines: Int = 1, onDone: () -> Unit = {}) {
    val c = HandOver.colors
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        modifier = modifier,
        placeholder = { Text(placeholder, color = c.ink3) },
        singleLine = lines == 1,
        minLines = 1,
        maxLines = lines,
        textStyle = HandOver.type.body.copy(color = c.ink),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        shape = RoundedCornerShape(HORadius.control),
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = c.raised, unfocusedContainerColor = c.raised,
            focusedBorderColor = c.accent, unfocusedBorderColor = c.lineStrong,
        ),
    )
}

// ------------------------------------------------------------ publish

/**
 * Publish sheet (SCREENS.md 15.2): Only Me, People with Access, one "Publish to <org>" row per org where the
 * person is Admin or Teacher, Everyone on This Hub; Unlisted; a read-only checklist; Publish or Update.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PublishSheet(ui: EditorUi, actions: EditorActions, onDismiss: () -> Unit) {
    val c = HandOver.colors
    val course = ui.course ?: return
    val lesson = ui.lesson ?: return
    val haptics = rememberHaptics()
    val inOrg = course.visibility == "org" && course.orgId != null
    var audience by remember { mutableStateOf(if (inOrg) course.orgId!! else course.visibility) }
    var toOrg by remember { mutableStateOf(inOrg) }
    var unlisted by remember { mutableStateOf(course.status == "unlisted") }
    var sending by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = c.raised) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(bottom = HOSpace.xl)) {
            Text("Publish ${lesson.title}", style = HandOver.type.title, color = c.ink)
            SectionHeader("Who can find it")
            AudienceRow("Only Me", null, audience == "only_me" && !toOrg) { audience = "only_me"; toOrg = false }
            AudienceRow("People with Access", null, audience == "shared" && !toOrg) { audience = "shared"; toOrg = false }
            ui.orgs.forEach { org ->
                AudienceRow("Publish to ${org.name}", org.members?.let { if (it == 1) "1 member" else "$it members" }, toOrg && audience == org.id) { audience = org.id; toOrg = true }
            }
            AudienceRow("Everyone on This Hub", null, audience == "everyone" && !toOrg) { audience = "everyone"; toOrg = false }
            if (toOrg) ui.orgs.firstOrNull { it.id == audience }?.let {
                Text("Members of ${it.name} see it on their Home and on the org page.", style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(top = HOSpace.xs))
            }
            Spacer(Modifier.height(HOSpace.m))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Unlisted", style = HandOver.type.body, color = c.ink)
                    Text("Not shown on Home. Share the link instead.", style = HandOver.type.footnote, color = c.ink2)
                }
                Switch(unlisted, { unlisted = it }, colors = SwitchDefaults.colors(checkedTrackColor = c.accent, checkedThumbColor = c.onAccent))
            }
            SectionHeader("Checklist")
            val camera = lesson.steps.count { it.checkType == CheckType.Camera }
            Text("${lesson.steps.size} steps, $camera checked by camera, ${lesson.steps.size - camera} manual", style = HandOver.type.callout, color = c.ink)
            lesson.steps.forEachIndexed { k, s ->
                if (s.checkType == CheckType.Camera && s.checkQuestion.isBlank()) Text("Step ${k + 1} has no check question.", style = HandOver.type.callout, color = c.caution)
                if (s.selfTest?.ok == false) Text("Step ${k + 1} failed its test.", style = HandOver.type.callout, color = c.caution)
            }
            error?.let { Text(it, style = HandOver.type.footnote, color = c.bad, modifier = Modifier.padding(top = HOSpace.s)) }
            Spacer(Modifier.height(HOSpace.l))
            PrimaryButton(if (course.status == "draft") "Publish" else "Update", {
                sending = true
                error = null
                actions.publish(audience, toOrg, unlisted) { problem ->
                    sending = false
                    if (problem == null) { haptics.success(); onDismiss() } else { haptics.error(); error = problem }
                }
            }, Modifier.fillMaxWidth(), enabled = !sending)
            QuietButton("Cancel", onDismiss, Modifier.align(Alignment.CenterHorizontally))
        }
    }
}

@Composable
private fun AudienceRow(title: String, meta: String?, selected: Boolean, onClick: () -> Unit) {
    val c = HandOver.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(RoundedCornerShape(HORadius.control))
            .selectable(selected, role = Role.RadioButton, onClick = onClick).padding(horizontal = HOSpace.xs),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected, null, colors = RadioButtonDefaults.colors(selectedColor = c.accent))
        Spacer(Modifier.width(HOSpace.s))
        Column(Modifier.weight(1f)) {
            Text(title, style = HandOver.type.body, color = c.ink)
            if (meta != null) Text(meta, style = HandOver.type.footnote, color = c.ink2)
        }
    }
}

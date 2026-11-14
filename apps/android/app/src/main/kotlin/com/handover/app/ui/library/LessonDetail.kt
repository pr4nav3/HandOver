package com.handover.app.ui.library

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.FolderOff
import androidx.compose.material.icons.outlined.HealthAndSafety
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.handover.app.core.CheckType
import com.handover.app.core.HubException
import com.handover.app.core.HubState
import com.handover.app.core.HubUrl
import com.handover.app.core.Lesson
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.Locale

data class LessonDetailUi(
    val loading: Boolean = true,
    val lesson: Lesson? = null,
    val description: String? = null,
    val covers: List<String> = emptyList(),
    val canEdit: Boolean = false,
    val ratings: RatingSummary? = null,
    val notFound: Boolean = false,
    val error: String? = null,
    /** Reference frame URL per step, in order. */
    val frames: List<String> = emptyList(),
)

/** Lesson detail data: `/api/courses/{id}` when the hub has it, else `/api/lessons/{id}`. Ratings when present. */
class LessonDetailViewModel(private val backend: CourseBackend, private val lessonId: String) : ViewModel() {
    private val _state = MutableStateFlow(LessonDetailUi())
    val state: StateFlow<LessonDetailUi> = _state.asStateFlow()

    init { load() }

    fun load() {
        _state.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            try {
                val detail = backend.course(lessonId)
                val lesson = detail?.lesson ?: backend.lesson(lessonId)
                val ratings = if (detail != null) runCatching { backend.ratings(lessonId) }.getOrNull() else null
                val covers = listOfNotNull(detail?.course?.coverUrl?.let { backend.absoluteUrl(it) }) +
                    listOf(backend.fileUrl(lessonId, "produced/cover.jpg"), backend.fileUrl(lessonId, "frames/01.jpg"))
                _state.value = LessonDetailUi(
                    loading = false,
                    lesson = lesson,
                    description = detail?.course?.description?.takeIf { it.isNotBlank() },
                    covers = covers.distinct(),
                    // No library API means no accounts: everyone may edit, as the web app allows today.
                    canEdit = detail?.permissions?.canEdit ?: true,
                    ratings = ratings?.takeIf { it.count > 0 && it.average != null },
                    frames = lesson.steps.map { backend.fileUrl(lessonId, it.refFrame ?: "frames/%02d.jpg".format(it.n)) },
                )
            } catch (e: CancellationException) {
                throw e
            } catch (e: HubException) {
                _state.update { it.copy(loading = false, notFound = e.status == 404, error = e.plainWords()) }
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, error = e.plainWords()) }
            }
        }
    }
}

@Composable
fun LessonDetailScreen(
    hub: HubUrl,
    lessonId: String,
    session: HubState?,
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
    onStart: (step: Int) -> Unit,
    onEdit: () -> Unit,
) {
    val detail: LessonDetailViewModel = viewModel(key = "detail-${hub.display}-$lessonId") { LessonDetailViewModel(CourseApi.forHub(hub), lessonId) }
    val ui by detail.state.collectAsStateWithLifecycle()
    val current = session?.takeIf { it.lessonId == lessonId && !it.done }?.step
    LessonDetailContent(ui, current, modifier, onBack, onStart, onEdit, detail::load)
}

/** Stateless Lesson detail (SCREENS.md section 6). [currentStep] is the hub's step when this lesson is mid-run. */
@Composable
fun LessonDetailContent(
    ui: LessonDetailUi,
    currentStep: Int?,
    modifier: Modifier = Modifier,
    onBack: () -> Unit = {},
    onStart: (step: Int) -> Unit = {},
    onEdit: () -> Unit = {},
    onRetry: () -> Unit = {},
) {
    val c = HandOver.colors
    var confirmSkip by remember { mutableStateOf<Int?>(null) }
    Column(modifier.fillMaxSize().background(c.paper)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = HOSpace.xs, vertical = HOSpace.xs), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back", tint = c.ink) }
            Text(ui.lesson?.title.orEmpty(), style = HandOver.type.headline, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (ui.canEdit && ui.lesson != null) QuietButton("Edit", onEdit, icon = Icons.Outlined.Edit)
        }
        val lesson = ui.lesson
        when {
            lesson == null && ui.loading -> EmptyState(null, "Loading lesson", loading = true)
            lesson == null && ui.notFound -> EmptyState(Icons.Outlined.FolderOff, "Lesson not found", "It may have been deleted on the hub.") { SecondaryButton("Back to Library", onBack) }
            lesson == null -> EmptyState(Icons.Outlined.FolderOff, "This lesson cannot be opened", ui.error, tone = Tone.Bad) { SecondaryButton("Try Again", onRetry) }
            else -> BoxWithConstraints(Modifier.fillMaxSize()) {
                val wide = maxWidth >= 700.dp
                val margin = if (wide) HOSpace.xl else HOSpace.l
                val summary = @Composable { m: Modifier -> Summary(ui, lesson, currentStep, m, onStart) }
                val steps = @Composable { m: Modifier ->
                    StepsList(ui, lesson, currentStep, m) { step ->
                        if (currentStep != null && step > currentStep) confirmSkip = step else onStart(step)
                    }
                }
                if (wide) {
                    Row(Modifier.fillMaxSize().padding(horizontal = margin), horizontalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
                        summary(Modifier.width(360.dp).verticalScroll(rememberScrollState()).padding(bottom = HOSpace.xl))
                        steps(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(bottom = HOSpace.xl))
                    }
                } else {
                    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = margin).padding(bottom = HOSpace.xxl)) {
                        summary(Modifier)
                        steps(Modifier)
                    }
                }
            }
        }
    }
    confirmSkip?.let { step ->
        AlertDialog(
            onDismissRequest = { confirmSkip = null },
            title = { Text("Skip to Step ${step + 1}?") },
            text = { Text("Steps you skip are marked as skipped.") },
            confirmButton = { TextButton(onClick = { confirmSkip = null; onStart(step) }) { Text("Skip") } },
            dismissButton = { TextButton(onClick = { confirmSkip = null }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun Summary(ui: LessonDetailUi, lesson: Lesson, currentStep: Int?, modifier: Modifier, onStart: (Int) -> Unit) {
    val c = HandOver.colors
    Column(modifier) {
        HubImage(ui.covers, Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(HORadius.card)), contentDescription = "Cover")
        Spacer(Modifier.height(HOSpace.l))
        Text(lesson.title, style = HandOver.type.display, color = c.ink)
        ui.description?.let {
            Spacer(Modifier.height(HOSpace.xs))
            Text(it, style = HandOver.type.body, color = c.ink2, maxLines = 4, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.height(HOSpace.s))
        val camera = lesson.steps.count { it.checkType == CheckType.Camera }
        val parts = listOfNotNull(
            if (lesson.steps.size == 1) "1 step" else "${lesson.steps.size} steps",
            lesson.durationSeconds()?.let { "${clock(it)} expert time" },
            if (camera > 0) "$camera checked by camera" else null,
        )
        MetaRow(parts)
        ui.ratings?.let { r ->
            Spacer(Modifier.height(HOSpace.s))
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.semantics(mergeDescendants = true) {}) {
                Stars(r.average ?: 0.0)
                Spacer(Modifier.width(HOSpace.s))
                Text(
                    "${String.format(Locale.US, "%.1f", r.average)} from ${r.count} ${if (r.count == 1) "rating" else "ratings"}",
                    style = HandOver.type.callout, color = c.ink2,
                )
            }
        }
        if (lesson.safety.isNotEmpty() || lesson.tools.isNotEmpty()) {
            Spacer(Modifier.height(HOSpace.l))
            HOCard(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                    Text("Before you start", style = HandOver.type.headline, color = c.ink)
                    lesson.safety.forEach { line ->
                        Row {
                            Icon(Icons.Outlined.HealthAndSafety, null, Modifier.size(20.dp), tint = c.caution)
                            Spacer(Modifier.width(HOSpace.s))
                            Text(line, style = HandOver.type.callout, color = c.ink)
                        }
                    }
                    if (lesson.tools.isNotEmpty()) Text("Tools: " + lesson.tools.joinToString(", "), style = HandOver.type.callout, color = c.ink2)
                }
            }
        }
        Spacer(Modifier.height(HOSpace.l))
        if (currentStep != null && currentStep > 0) {
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                PrimaryButton("Continue at Step ${currentStep + 1}", { onStart(currentStep) }, Modifier.weight(1f))
                SecondaryButton("Start Over", { onStart(0) }, large = true)
            }
        } else {
            PrimaryButton("Start Lesson", { onStart(0) }, Modifier.fillMaxWidth(), enabled = lesson.steps.isNotEmpty())
        }
    }
}

/** Parts separated by small dots in `ink3`, never dashes (SCREENS.md section 6). */
@Composable
private fun MetaRow(parts: List<String>) {
    val c = HandOver.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        parts.forEachIndexed { i, part ->
            if (i > 0) Box(Modifier.padding(horizontal = HOSpace.s).size(3.dp).clip(CircleShape).background(c.ink3))
            Text(part, style = HandOver.type.callout, color = c.ink2, maxLines = 1)
        }
    }
}

@Composable
private fun Stars(average: Double) {
    val c = HandOver.colors
    Row(Modifier.semantics { contentDescription = "Rating, ${String.format(Locale.US, "%.1f", average)} of 5 stars" }) {
        (1..5).forEach { i ->
            val filled = average >= i - 0.25
            Icon(if (filled) Icons.Filled.Star else Icons.Outlined.StarOutline, null, Modifier.size(16.dp), tint = if (filled) c.accent else c.ink3)
        }
    }
}

/** DESIGN.md 3.20: status, thumbnail, number and title, "Expert 0:21". */
@Composable
private fun StepsList(ui: LessonDetailUi, lesson: Lesson, currentStep: Int?, modifier: Modifier, onTap: (Int) -> Unit) {
    val c = HandOver.colors
    Column(modifier) {
        SectionHeader("Steps")
        lesson.steps.forEachIndexed { i, step ->
            val current = currentStep == i
            val expert = step.seconds()?.let { "Expert ${clock(it)}" }
            Row(
                Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(RoundedCornerShape(HORadius.control))
                    .background(if (current) c.accentSoft else androidx.compose.ui.graphics.Color.Transparent)
                    .clickable { onTap(i) }
                    .semantics(mergeDescendants = true) { contentDescription = "Step ${i + 1}. ${step.title}. ${if (current) "Current" else "Not started"}" + (expert?.let { ". $it" } ?: "") }
                    .padding(horizontal = HOSpace.s, vertical = HOSpace.s),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(if (current) Icons.Filled.PlayCircle else Icons.Outlined.Circle, null, Modifier.size(20.dp), tint = if (current) c.accent else c.ink3)
                Spacer(Modifier.width(HOSpace.m))
                HubImage(listOfNotNull(ui.frames.getOrNull(i)), Modifier.width(72.dp).height(40.dp).clip(RoundedCornerShape(HORadius.small)))
                Spacer(Modifier.width(HOSpace.m))
                Column(Modifier.weight(1f)) {
                    Text("${i + 1}. ${step.title}", style = HandOver.type.bodyMedium, color = if (current) c.accentInk else c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    if (expert != null) Text(expert, style = HandOver.type.callout, color = c.ink2)
                }
            }
        }
    }
}

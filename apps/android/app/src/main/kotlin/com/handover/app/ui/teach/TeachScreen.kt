package com.handover.app.ui.teach

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material.icons.outlined.FiberManualRecord
import androidx.compose.material.icons.outlined.VideoCall
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.core.Lesson
import com.handover.app.core.UploadSource
import com.handover.app.ui.editor.ClipPlayer
import com.handover.app.ui.editor.EditorScreen
import com.handover.app.ui.editor.StepTimeline
import com.handover.app.ui.library.CourseApi
import com.handover.app.ui.library.EmptyState
import com.handover.app.ui.library.HOCard
import com.handover.app.ui.library.LessonRow
import com.handover.app.ui.library.PrimaryButton
import com.handover.app.ui.library.QuietButton
import com.handover.app.ui.library.SecondaryButton
import com.handover.app.ui.library.SectionHeader
import com.handover.app.ui.library.Tone
import com.handover.app.ui.library.rememberHaptics
import com.handover.app.ui.record.RecordScreen
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Teach (SCREENS.md sections 11 to 13): record a take or pick a video, name it, upload it, follow the hub's
 * processing, then see the steps on a timeline. Opens the course editor and the recorder inside this tab.
 * [onStartLesson] lets the shell show Learn after "Try It as a Learner".
 */
@Composable
fun TeachScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier, onStartLesson: (String) -> Unit = {}) {
    val hub = state.hub
    if (hub == null) {
        EmptyState(Icons.Outlined.VideoCall, "No hub yet", "Connect to a hub to make lessons.", modifier)
        return
    }
    val api = CourseApi.forHub(hub)
    val teach: TeachViewModel = viewModel(key = "teach-${hub.display}") { TeachViewModel(api) }
    val ui by teach.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var recording by rememberSaveable { mutableStateOf(false) }
    var editing by rememberSaveable { mutableStateOf<String?>(null) }

    val photo = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri?.let { uploadSource(context, it) }?.let { teach.pick(it) }
    }
    val file = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { uploadSource(context, it) }?.let { teach.pick(it) }
    }
    val pickVideo = { photo.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.VideoOnly)) }

    val editId = editing
    if (editId != null) {
        BackHandler { editing = null; teach.loadLessons() }
        EditorScreen(hub, editId, modifier, onClose = { editing = null; teach.loadLessons() }, onPreview = { vm.selectLesson(editId); onStartLesson(editId) })
        return
    }
    TeachContent(
        ui = ui,
        modifier = modifier,
        fileUrl = { id, path -> api.fileUrl(id, path) },
        onRecord = { recording = true },
        onPhotos = pickVideo,
        onFiles = { file.launch(arrayOf("video/*")) },
        onOpen = { editing = it },
        onTitle = teach::setTitle,
        onMake = teach::makeCourse,
        onCancelUpload = teach::cancelUpload,
        onRetry = teach::retry,
        onDone = teach::finish,
        onReview = { ui.lessonId?.let { editing = it }; teach.finish() },
        onTry = { ui.lessonId?.let { vm.selectLesson(it); onStartLesson(it) } },
    )
    if (recording) {
        Dialog(
            onDismissRequest = { recording = false },
            properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false, dismissOnBackPress = false),
        ) {
            RecordScreen(
                onClose = { recording = false },
                onTake = { take ->
                    recording = false
                    teach.pick(UploadSource.of(take), "Lesson " + SimpleDateFormat("MMM d", Locale.US).format(Date()))
                },
                onImport = { recording = false; pickVideo() },
            )
        }
    }
}

/** A picked video as an upload, with the name and size the system reports (the hub needs the length). */
private fun uploadSource(context: Context, uri: Uri): UploadSource? {
    val resolver = context.contentResolver
    var name = "video.mp4"
    var size = -1L
    resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
        if (c.moveToFirst()) {
            c.getColumnIndex(OpenableColumns.DISPLAY_NAME).takeIf { it >= 0 }?.let { name = c.getString(it) ?: name }
            c.getColumnIndex(OpenableColumns.SIZE).takeIf { it >= 0 && !c.isNull(it) }?.let { size = c.getLong(it) }
        }
    }
    if (size <= 0) size = resolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1
    if (size <= 0) return null
    return UploadSource(name, resolver.getType(uri) ?: "video/mp4", size) { resolver.openInputStream(uri) ?: error("The video could not be opened.") }
}

/** Stateless Teach, for previews and screenshot tests. */
@Composable
fun TeachContent(
    ui: TeachUi,
    modifier: Modifier = Modifier,
    fileUrl: (String, String) -> String = { _, p -> p },
    onRecord: () -> Unit = {},
    onPhotos: () -> Unit = {},
    onFiles: () -> Unit = {},
    onOpen: (String) -> Unit = {},
    onTitle: (String) -> Unit = {},
    onMake: () -> Unit = {},
    onCancelUpload: () -> Unit = {},
    onRetry: () -> Unit = {},
    onDone: () -> Unit = {},
    onReview: () -> Unit = {},
    onTry: () -> Unit = {},
) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    LaunchedEffect(ui.phase) {
        when (ui.phase) {
            TeachPhase.Ready -> haptics.success()
            TeachPhase.Failed -> haptics.error()
            else -> Unit
        }
    }
    when (ui.phase) {
        TeachPhase.Naming -> BackHandler(onBack = onDone)
        TeachPhase.Uploading -> BackHandler(onBack = onCancelUpload)
        TeachPhase.Processing, TeachPhase.Ready, TeachPhase.Failed -> BackHandler(onBack = onDone)
        TeachPhase.Home -> Unit
    }
    BoxWithConstraints(modifier.fillMaxSize().background(c.paper)) {
        val wide = maxWidth >= 600.dp
        val margin = if (wide) HOSpace.xl else HOSpace.l
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = margin).padding(bottom = HOSpace.xxl),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            val column = Modifier.widthIn(max = if (ui.phase == TeachPhase.Home) 960.dp else 560.dp).fillMaxWidth()
            when (ui.phase) {
                TeachPhase.Home -> Home(ui, column, wide, onRecord, onPhotos, onFiles, onOpen)
                TeachPhase.Naming -> Naming(ui, column, onTitle, onMake, onDone)
                else -> Processing(ui, column, fileUrl, onCancelUpload, onRetry, onDone, onReview, onTry)
            }
        }
    }
}

@Composable
private fun Home(ui: TeachUi, modifier: Modifier, wide: Boolean, onRecord: () -> Unit, onPhotos: () -> Unit, onFiles: () -> Unit, onOpen: (String) -> Unit) {
    val c = HandOver.colors
    Column(modifier) {
        Spacer(Modifier.height(HOSpace.xl))
        Text("Teach", style = HandOver.type.largeTitle, color = c.ink)
        Spacer(Modifier.height(HOSpace.l))
        val cards = listOf(
            Triple(Icons.Outlined.FiberManualRecord, "Record a Take", "Use this phone's camera. Talk through each step as you do it.") to onRecord,
            Triple(Icons.Outlined.PhotoLibrary, "Choose from Photos", "Pick a video you already recorded.") to onPhotos,
            Triple(Icons.Outlined.Folder, "Choose from Files", "Pick a video from Files or a drive.") to onFiles,
        )
        if (wide) {
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                cards.forEach { (t, action) -> OptionCard(t.first, t.second, t.third, action, Modifier.weight(1f)) }
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                cards.forEach { (t, action) -> OptionCard(t.first, t.second, t.third, action, Modifier.fillMaxWidth()) }
            }
        }
        Spacer(Modifier.height(HOSpace.m))
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(HORadius.control)).clickable(role = Role.Button, onClick = onPhotos)
                .padding(vertical = HOSpace.s),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Outlined.PhotoLibrary, null, Modifier.size(20.dp), tint = c.accentInk)
            Spacer(Modifier.width(HOSpace.s))
            Column {
                Text("Recorded on glasses? Import it", style = HandOver.type.bodyMedium, color = c.accentInk)
                Text("Ray-Ban Meta videos reach this phone's gallery through the Meta AI app.", style = HandOver.type.footnote, color = c.ink2)
            }
        }
        SectionHeader("Your Lessons")
        val lessons = ui.lessons
        when {
            lessons == null -> Box(Modifier.fillMaxWidth().height(96.dp), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(24.dp), color = c.ink2, strokeWidth = 2.5.dp)
            }
            lessons.isEmpty() -> EmptyState(
                Icons.Outlined.VideoCall, "No lessons yet", "Record a task once while you talk through it. HandOver cuts it into steps.",
                Modifier.heightIn(min = 240.dp),
            )
            else -> lessons.forEach { LessonRow(it) { onOpen(it.id) } }
        }
    }
}

@Composable
private fun OptionCard(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, line: String, onClick: () -> Unit, modifier: Modifier) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    HOCard(
        modifier.clip(RoundedCornerShape(HORadius.card)).clickable(role = Role.Button) { haptics.tap(); onClick() }
            .semantics(mergeDescendants = true) { contentDescription = "$title. $line" },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(44.dp).clip(RoundedCornerShape(12.dp)).background(c.accentSoft), contentAlignment = Alignment.Center) {
                Icon(icon, null, Modifier.size(24.dp), tint = if (title == "Record a Take") c.record else c.accentInk)
            }
            Spacer(Modifier.width(HOSpace.m))
            Column {
                Text(title, style = HandOver.type.headline, color = c.ink)
                Text(line, style = HandOver.type.callout, color = c.ink2)
            }
        }
    }
}

@Composable
private fun Naming(ui: TeachUi, modifier: Modifier, onTitle: (String) -> Unit, onMake: () -> Unit, onCancel: () -> Unit) {
    val c = HandOver.colors
    Column(modifier) {
        Row(Modifier.padding(top = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onCancel) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Cancel", tint = c.ink) }
            Text("Make Course", style = HandOver.type.headline, color = c.ink)
        }
        Spacer(Modifier.height(HOSpace.l))
        HOCard(Modifier.fillMaxWidth()) {
            Text(ui.video?.fileName.orEmpty(), style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(sizeLabel(ui.video?.length ?: 0), style = HandOver.type.callout, color = c.ink2)
        }
        Spacer(Modifier.height(HOSpace.l))
        Text("Title", style = HandOver.type.section, color = c.ink2)
        Spacer(Modifier.height(HOSpace.xs))
        OutlinedTextField(
            value = ui.title,
            onValueChange = onTitle,
            placeholder = { Text("Fold a fortune teller", color = c.ink3) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences, imeAction = ImeAction.Done),
            shape = RoundedCornerShape(HORadius.control),
            colors = OutlinedTextFieldDefaults.colors(focusedContainerColor = c.raised, unfocusedContainerColor = c.raised, focusedBorderColor = c.accent, unfocusedBorderColor = c.lineStrong),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(HOSpace.xs))
        Text("One video of the whole task works best. Talk through each step as you do it.", style = HandOver.type.footnote, color = c.ink2)
        Spacer(Modifier.height(HOSpace.xl))
        PrimaryButton("Make Course", onMake, Modifier.fillMaxWidth(), enabled = ui.title.isNotBlank())
        QuietButton("Cancel", onCancel, Modifier.align(Alignment.CenterHorizontally))
    }
}

/** "214.3 MB". */
fun sizeLabel(bytes: Long): String = when {
    bytes >= 1_000_000_000 -> String.format(Locale.US, "%.1f GB", bytes / 1e9)
    bytes >= 1_000_000 -> String.format(Locale.US, "%.1f MB", bytes / 1e6)
    else -> String.format(Locale.US, "%.0f KB", bytes / 1e3)
}

@Composable
private fun Processing(
    ui: TeachUi,
    modifier: Modifier,
    fileUrl: (String, String) -> String,
    onCancelUpload: () -> Unit,
    onRetry: () -> Unit,
    onDone: () -> Unit,
    onReview: () -> Unit,
    onTry: () -> Unit,
) {
    val c = HandOver.colors
    val ready = ui.phase == TeachPhase.Ready
    Column(modifier) {
        Spacer(Modifier.height(HOSpace.xl))
        Text(if (ready) "Your lesson is ready" else ui.title, style = HandOver.type.title, color = c.ink)
        if (ready) Text(ui.title, style = HandOver.type.callout, color = c.ink2)
        Spacer(Modifier.height(HOSpace.l))
        val lesson = ui.lesson
        if (ready && lesson != null && lesson.steps.isNotEmpty()) {
            ReadyTimeline(lesson, ui.lessonId.orEmpty(), fileUrl)
            Spacer(Modifier.height(HOSpace.l))
        }
        HOCard(Modifier.fillMaxWidth(), radius = HORadius.card) {
            Column(verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                ui.rows.forEach { row -> StageRowView(row, ui, lesson?.steps?.size) }
            }
        }
        if (ui.phase == TeachPhase.Uploading) {
            Spacer(Modifier.height(HOSpace.s))
            Text("${ui.video?.fileName.orEmpty()}, ${sizeLabel(ui.total)}", style = HandOver.type.footnote, color = c.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.height(HOSpace.l))
        when (ui.phase) {
            TeachPhase.Uploading -> SecondaryButton("Cancel", onCancelUpload, Modifier.fillMaxWidth())
            TeachPhase.Processing -> {
                Text("You can leave this screen. The hub keeps working.", style = HandOver.type.footnote, color = c.ink2)
                Spacer(Modifier.height(HOSpace.m))
                SecondaryButton("Done", onDone, Modifier.fillMaxWidth())
            }
            TeachPhase.Failed -> {
                ui.error?.let { Text(it, style = HandOver.type.callout, color = c.bad) }
                Spacer(Modifier.height(HOSpace.m))
                PrimaryButton("Try Again", onRetry, Modifier.fillMaxWidth())
                QuietButton("Done", onDone, Modifier.align(Alignment.CenterHorizontally))
            }
            TeachPhase.Ready -> {
                PrimaryButton("Review Steps", onReview, Modifier.fillMaxWidth())
                Spacer(Modifier.height(HOSpace.s))
                SecondaryButton("Try It as a Learner", onTry, Modifier.fillMaxWidth(), large = true)
                QuietButton("Done", onDone, Modifier.align(Alignment.CenterHorizontally))
            }
            else -> Unit
        }
    }
}

@Composable
private fun StageRowView(row: StageRow, ui: TeachUi, stepsFound: Int?) {
    val c = HandOver.colors
    val text = if (row.stage == Stage.Upload && row.state == RowState.Active) "Uploading ${ui.percent}%" else row.text(stepsFound)
    Row(verticalAlignment = Alignment.Top, modifier = Modifier.semantics(mergeDescendants = true) {}) {
        Box(Modifier.size(22.dp), contentAlignment = Alignment.Center) {
            when (row.state) {
                RowState.Active -> CircularProgressIndicator(Modifier.size(18.dp), color = c.accent, strokeWidth = 2.dp)
                RowState.Done -> Icon(Icons.Filled.CheckCircle, "Done", Modifier.size(22.dp), tint = c.good)
                RowState.Failed -> Icon(Icons.Filled.Cancel, "Failed", Modifier.size(22.dp), tint = c.bad)
            }
        }
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(text, style = HandOver.type.body, color = if (row.state == RowState.Failed) c.bad else c.ink)
            if (row.stage == Stage.Upload && row.state == RowState.Active) {
                Spacer(Modifier.height(HOSpace.xs))
                LinearProgressIndicator(progress = { ui.percent / 100f }, Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)), color = c.accent, trackColor = c.well, drawStopIndicator = {})
            }
            row.progress?.let {
                Spacer(Modifier.height(HOSpace.xs))
                LinearProgressIndicator(progress = { it.toFloat() }, Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)), color = c.accent, trackColor = c.well, drawStopIndicator = {})
            }
            if (row.message.isNotBlank() && row.state != RowState.Done) {
                Text(row.message, style = HandOver.type.footnote, color = c.ink2, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** The finished lesson: the selected step's clip, then the colored timeline with frames; tap a step to play it. */
@Composable
private fun ReadyTimeline(lesson: Lesson, lessonId: String, fileUrl: (String, String) -> String) {
    val c = HandOver.colors
    var selected by rememberSaveable { mutableStateOf(0) }
    val step = lesson.steps.getOrNull(selected) ?: return
    ClipPlayer(
        url = step.clip?.let { fileUrl(lessonId, it) },
        poster = listOfNotNull(step.refFrame?.let { fileUrl(lessonId, it) }),
        label = "Clip for step ${selected + 1}",
        modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(HORadius.card)),
    )
    Spacer(Modifier.height(HOSpace.s))
    Text("Step ${selected + 1} of ${lesson.steps.size}", style = HandOver.type.footnote, color = c.ink2)
    Text(step.title, style = HandOver.type.headline, color = c.ink)
    Spacer(Modifier.height(HOSpace.m))
    StepTimeline(
        lesson = lesson,
        selected = selected,
        thumbnails = lesson.steps.map { s -> s.refFrame?.let { fileUrl(lessonId, it) }.orEmpty() },
        onSelect = { selected = it },
    )
}


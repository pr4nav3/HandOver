package com.handover.app.ui.library

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import android.content.Context
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.HelpOutline
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.heading
import androidx.core.content.edit
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.editor.EditorScreen
import com.handover.app.ui.start.CameraChoice
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.Hairline
import com.handover.app.ui.theme.HandOver

/**
 * Home (SCREENS.md 21 with Library 5): a dismissible How it works card, Learn a Lesson and Teach a
 * Lesson, Continue for runs in progress, then the hub's lessons with search and filters. Pushes Lesson
 * detail and the course editor inside this tab.
 *
 * [onStart] starts a lesson at a step through the shell's start flow (the camera sheet the first time).
 * [onTeach] is null for people who cannot teach. [onLearn] opens the running lesson or the lesson picker.
 */
@Composable
fun LibraryScreen(
    state: AppState,
    vm: AppViewModel,
    modifier: Modifier = Modifier,
    onStart: (id: String, step: Int) -> Unit = { _, _ -> },
    onTeach: (() -> Unit)? = {},
    onLearn: () -> Unit = {},
    onBeTheCamera: () -> Unit = {},
    camera: CameraChoice? = null,
    onChangeCamera: () -> Unit = {},
) {
    val hub = state.hub
    if (hub == null) {
        EmptyState(Icons.Outlined.WifiOff, "Not connected yet", "The hub is HandOver running on a computer nearby. Connect to it in Settings to see its lessons.", modifier)
        return
    }
    val context = LocalContext.current
    val library: LibraryViewModel = viewModel(key = "library-${hub.display}") { LibraryViewModel(CourseApi.forHub(hub)) }
    val ui by library.state.collectAsStateWithLifecycle()
    var open by rememberSaveable { mutableStateOf<String?>(null) }
    var editing by rememberSaveable { mutableStateOf<String?>(null) }
    var guide by remember { mutableStateOf(HomeGuide.shown(context)) }

    val session = state.session
    LaunchedEffect(session?.lessonId, session?.step, session?.done) {
        library.setSession(session?.lessonId, session?.step ?: 0, session?.total ?: 0, session?.done ?: true)
    }

    val editId = editing
    val openId = open
    when {
        editId != null -> {
            BackHandler { editing = null; library.refresh() }
            EditorScreen(hub, editId, modifier, onClose = { editing = null; library.refresh() }, onPreview = { onStart(editId, 0) })
        }
        openId != null -> {
            BackHandler { open = null }
            LessonDetailScreen(
                hub = hub,
                lessonId = openId,
                session = session?.takeIf { state.lessonRunning },
                modifier = modifier,
                onBack = { open = null },
                onStart = { step -> onStart(openId, step) },
                onEdit = { editing = openId },
                camera = camera,
                onChangeCamera = onChangeCamera,
            )
        }
        else -> LibraryContent(
            ui = ui,
            modifier = modifier,
            onRefresh = library::refresh,
            onQuery = library::setQuery,
            onFilter = library::setFilter,
            onOpen = { open = it },
            onContinue = { item, step -> onStart(item.id, step) },
            onTeach = onTeach,
            home = HomeUi(
                guide = guide,
                running = state.lesson?.title?.takeIf { state.lessonRunning && session?.done == false },
            ),
            onGuide = { show -> guide = show; HomeGuide.setShown(context, show) },
            onLearn = onLearn,
            onBeTheCamera = onBeTheCamera,
        )
    }
}

/** What Home adds above the lessons. [running] is the title of the lesson in progress on the hub, if any. */
data class HomeUi(val guide: Boolean = true, val running: String? = null)

/** Whether the How it works card shows. Dismissed once, it stays away until the help button reopens it. */
object HomeGuide {
    private const val KEY = "home_guide_dismissed"
    fun shown(context: Context) = !context.getSharedPreferences("handover", Context.MODE_PRIVATE).getBoolean(KEY, false)
    fun setShown(context: Context, shown: Boolean) =
        context.getSharedPreferences("handover", Context.MODE_PRIVATE).edit { putBoolean(KEY, !shown) }
}

/** The Library body, stateless so previews and screenshot tests draw every state. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryContent(
    ui: LibraryUiState,
    modifier: Modifier = Modifier,
    onRefresh: () -> Unit = {},
    onQuery: (String) -> Unit = {},
    onFilter: (LibraryFilter) -> Unit = {},
    onOpen: (String) -> Unit = {},
    onContinue: (LibraryItem, Int) -> Unit = { _, _ -> },
    onTeach: (() -> Unit)? = {},
    home: HomeUi = HomeUi(),
    onGuide: (Boolean) -> Unit = {},
    onLearn: () -> Unit = {},
    onBeTheCamera: () -> Unit = {},
) {
    val c = HandOver.colors
    BoxWithConstraints(modifier.fillMaxSize().background(c.paper)) {
        val wide = maxWidth >= 600.dp
        val margin = if (wide) HOSpace.xl else HOSpace.l
        PullToRefreshBox(isRefreshing = ui.refreshing, onRefresh = onRefresh, modifier = Modifier.fillMaxSize()) {
            LazyVerticalGrid(
                columns = if (wide) GridCells.Adaptive(240.dp) else GridCells.Fixed(1),
                contentPadding = PaddingValues(start = margin, end = margin, bottom = HOSpace.xxl),
                horizontalArrangement = Arrangement.spacedBy(HOSpace.l),
                verticalArrangement = Arrangement.spacedBy(if (wide) HOSpace.l else 0.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Column(Modifier.padding(top = HOSpace.l)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Home", style = HandOver.type.largeTitle, color = c.ink, modifier = Modifier.weight(1f).semantics { heading() })
                            HOButton("Be the Camera", onBeTheCamera, kind = ButtonKind.Secondary, size = ButtonSize.Small, icon = Icons.Outlined.CameraAlt)
                            if (!home.guide) IconButton(onClick = { onGuide(true) }) { Icon(Icons.AutoMirrored.Outlined.HelpOutline, "How it works", tint = c.ink2) }
                        }
                        Text(
                            if (home.running != null) "A lesson is running. Tap Learn to join in." else "Pick a lesson to learn, or teach one of your own.",
                            style = HandOver.type.callout, color = c.ink2,
                        )
                        if (home.guide) {
                            Spacer(Modifier.height(HOSpace.l))
                            HowItWorksCard(onDismiss = { onGuide(false) }, modifier = Modifier.widthIn(max = 720.dp))
                        }
                        Spacer(Modifier.height(HOSpace.l))
                        Row(Modifier.widthIn(max = 720.dp).height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                            ActionCard(
                                Icons.Outlined.School, "Learn a Lesson",
                                home.running?.let { "Now: $it" } ?: "Follow an expert, step by step.",
                                onLearn, Modifier.weight(1f).fillMaxHeight(), primary = true,
                            )
                            if (onTeach != null) ActionCard(Icons.Outlined.Videocam, "Teach a Lesson", "Record a task once. HandOver cuts it into steps.", onTeach, Modifier.weight(1f).fillMaxHeight())
                        }
                    }
                }
                val continues = ui.continueItems
                if (continues.isNotEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }) { SectionHeader("Continue") }
                    item(span = { GridItemSpan(maxLineSpan) }) {
                        LazyRow(horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                            items(continues, key = { it.first.id }) { (item, step) -> ContinueCard(item, step) { onContinue(item, step) } }
                        }
                    }
                }
                if (ui.all.isNotEmpty()) item(span = { GridItemSpan(maxLineSpan) }) {
                    Column {
                        SectionHeader("Lessons")
                        Box(Modifier.widthIn(max = 560.dp)) { SearchField(ui.query, onQuery) }
                        if (ui.filters.isNotEmpty()) {
                            Spacer(Modifier.height(HOSpace.m))
                            SegmentedRow(ui.filters, ui.filter, { it.label }, onFilter)
                        }
                        Spacer(Modifier.height(if (wide) HOSpace.xs else HOSpace.s))
                    }
                }
                val items = ui.items
                when {
                    ui.loading && ui.all.isEmpty() -> item(span = { GridItemSpan(maxLineSpan) }) { EmptyState(null, "Loading lessons", loading = true, modifier = Modifier.heightIn(min = 360.dp)) }
                    ui.error != null && ui.all.isEmpty() -> item(span = { GridItemSpan(maxLineSpan) }) {
                        EmptyState(Icons.Outlined.WifiOff, "Cannot reach the hub", ui.error, Modifier.heightIn(min = 360.dp), tone = Tone.Caution) {
                            PrimaryButton("Try Again", onRefresh)
                        }
                    }
                    ui.all.isEmpty() -> item(span = { GridItemSpan(maxLineSpan) }) {
                        EmptyState(
                            Icons.Outlined.Movie, "No lessons yet",
                            if (onTeach != null) "Record a task once and HandOver turns it into steps." else "When someone teaches a lesson on this hub, it shows up here.",
                            Modifier.heightIn(min = 280.dp),
                        ) {
                            if (onTeach != null) SecondaryButton("Make a Lesson", onTeach)
                        }
                    }
                    items.isEmpty() -> item(span = { GridItemSpan(maxLineSpan) }) {
                        EmptyState(Icons.Outlined.Search, "No results for \"${ui.query.trim()}\"", "Check the spelling or try fewer words.", Modifier.heightIn(min = 320.dp))
                    }
                    else -> {
                        items(items, key = { it.id }) { item ->
                            if (wide) LessonCard(item) { onOpen(item.id) } else LessonRow(item) { onOpen(item.id) }
                        }
                    }
                }
            }
        }
    }
}

/** The three steps a first-time person needs, dismissible; the help button in the header brings it back. */
@Composable
fun HowItWorksCard(onDismiss: () -> Unit, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(HORadius.card)
    Column(modifier.fillMaxWidth().clip(shape).background(c.raised).border(Hairline, c.line, shape).padding(start = HOSpace.l, bottom = HOSpace.l)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("How it works", style = HandOver.type.headline, color = c.ink, modifier = Modifier.weight(1f).semantics { heading() })
            IconButton(onClick = onDismiss) { Icon(Icons.Outlined.Close, "Hide how it works", tint = c.ink3) }
        }
        Column(Modifier.padding(end = HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
            GuideStep(1, "Pick a lesson", "An expert recorded it once, cut into short steps.")
            GuideStep(2, "Choose a camera", "This phone, Meta glasses, or another device watches your hands.")
            GuideStep(3, "Follow along", "Watch each clip and do the step. The hub tells you when each step is done.")
        }
    }
}

@Composable
private fun GuideStep(n: Int, title: String, line: String) {
    val c = HandOver.colors
    Row(verticalAlignment = Alignment.Top) {
        Box(Modifier.size(28.dp).background(c.accentSoft, CircleShape), contentAlignment = Alignment.Center) {
            Text("$n", style = HandOver.type.bodyMedium, color = c.accentInk)
        }
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(title, style = HandOver.type.bodyMedium, color = c.ink)
            Text(line, style = HandOver.type.callout, color = c.ink2)
        }
    }
}

/** One of Home's two big actions. The primary one is filled with the accent wash. */
@Composable
private fun ActionCard(icon: ImageVector, title: String, line: String, onClick: () -> Unit, modifier: Modifier = Modifier, primary: Boolean = false) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(HORadius.card)
    Column(
        modifier.heightIn(min = 120.dp).clip(shape).background(if (primary) c.accent else c.raised)
            .then(if (primary) Modifier else Modifier.border(Hairline, c.line, shape))
            .clickable(onClickLabel = title, onClick = onClick).padding(HOSpace.l),
    ) {
        val ink = if (primary) c.onAccent else c.ink
        Icon(icon, null, tint = if (primary) c.onAccent else c.accentInk, modifier = Modifier.size(28.dp))
        Spacer(Modifier.height(HOSpace.l))
        Text(title, style = HandOver.type.headline, color = ink)
        Text(line, style = HandOver.type.footnote, color = if (primary) c.onAccent.copy(alpha = 0.85f) else c.ink2, maxLines = 3, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun SearchField(query: String, onQuery: (String) -> Unit) {
    val c = HandOver.colors
    OutlinedTextField(
        value = query,
        onValueChange = onQuery,
        placeholder = { Text("Search lessons", color = c.ink3) },
        leadingIcon = { Icon(Icons.Outlined.Search, null, tint = c.ink3) },
        trailingIcon = if (query.isNotEmpty()) {
            { IconButton(onClick = { onQuery("") }) { Icon(Icons.Outlined.Close, "Clear search", tint = c.ink2) } }
        } else null,
        singleLine = true,
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        shape = RoundedCornerShape(HORadius.control),
        colors = OutlinedTextFieldDefaults.colors(
            focusedContainerColor = c.raised, unfocusedContainerColor = c.raised,
            focusedBorderColor = c.accent, unfocusedBorderColor = c.lineStrong,
        ),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** DESIGN.md 3.10 lesson row: cover 64 x 40, title, "8 steps, 3:12", a badge and a completed mark. */
@Composable
fun LessonRow(item: LibraryItem, onClick: () -> Unit) {
    val c = HandOver.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 64.dp).clip(RoundedCornerShape(HORadius.control)).clickable(onClick = onClick)
            .semantics { contentDescription = "${item.title}, ${stepsMeta(item.steps, item.duration)}" + (item.badge?.let { ", $it" } ?: "") }
            .padding(vertical = HOSpace.m),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        HubImage(item.covers, Modifier.width(64.dp).height(40.dp).clip(RoundedCornerShape(HORadius.small)))
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(item.title, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(stepsMeta(item.steps, item.duration), style = HandOver.type.callout, color = c.ink2)
        }
        item.badge?.let { Spacer(Modifier.width(HOSpace.s)); Badge(it) }
        if (item.completed) {
            Spacer(Modifier.width(HOSpace.s))
            Icon(Icons.Filled.CheckCircle, "Completed", Modifier.size(20.dp), tint = c.good)
        }
    }
}

/** The grid card on wide screens: cover 16:9, title, meta, badge. */
@Composable
fun LessonCard(item: LibraryItem, onClick: () -> Unit) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(HORadius.card)
    Column(
        Modifier.clip(shape).background(c.raised).border(Hairline, c.line, shape).clickable(onClick = onClick)
            .semantics { contentDescription = "${item.title}, ${stepsMeta(item.steps, item.duration)}" + (item.badge?.let { ", $it" } ?: "") },
    ) {
        Box {
            HubImage(item.covers, Modifier.fillMaxWidth().aspectRatio(16f / 9f))
            if (item.completed) {
                Icon(Icons.Filled.CheckCircle, "Completed", Modifier.align(Alignment.TopEnd).padding(HOSpace.s).size(22.dp).clip(CircleShape).background(c.raised), tint = c.good)
            }
        }
        Column(Modifier.padding(HOSpace.m)) {
            Text(item.title, style = HandOver.type.headline, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis, minLines = 2)
            Spacer(Modifier.height(HOSpace.xs))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stepsMeta(item.steps, item.duration), style = HandOver.type.callout, color = c.ink2, modifier = Modifier.weight(1f))
                item.badge?.let { Badge(it) }
            }
        }
    }
}

/** Continue card (SCREENS.md section 5): cover, title, "Step 4 of 8", a ring over the cover. */
@Composable
private fun ContinueCard(item: LibraryItem, step: Int, onClick: () -> Unit) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(HORadius.card)
    val label = "Step ${step + 1} of ${item.steps}"
    Column(
        Modifier.width(260.dp).clip(shape).background(c.raised).border(Hairline, c.line, shape).clickable(onClick = onClick)
            .semantics { contentDescription = "Continue ${item.title}, $label" },
    ) {
        Box {
            HubImage(item.covers, Modifier.fillMaxWidth().aspectRatio(16f / 9f))
            Box(Modifier.align(Alignment.TopEnd).padding(HOSpace.s).size(36.dp).clip(CircleShape).background(c.raised.copy(alpha = 0.92f)), contentAlignment = Alignment.Center) {
                ProgressRing(if (item.steps > 0) step.toFloat() / item.steps else 0f, size = 24.dp, stroke = 3.5.dp)
            }
        }
        Column(Modifier.padding(HOSpace.m)) {
            Text(item.title, style = HandOver.type.headline, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis, minLines = 2)
            Text(label, style = HandOver.type.callout, color = c.ink2)
        }
    }
}

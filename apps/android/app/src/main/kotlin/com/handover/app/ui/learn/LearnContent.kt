package com.handover.app.ui.learn

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Headphones
import androidx.compose.material.icons.automirrored.outlined.VolumeUp
import androidx.compose.material.icons.rounded.Check
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Science
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.handover.app.core.Mistake
import com.handover.app.ui.components.Banner
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.CaptionBar
import com.handover.app.ui.components.Corner
import com.handover.app.ui.components.EmptyState
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.IconCircleButton
import com.handover.app.ui.components.MistakeCard
import com.handover.app.ui.components.Pill
import com.handover.app.ui.components.PipHost
import com.handover.app.ui.components.Segment
import com.handover.app.ui.components.StatusBlock
import com.handover.app.ui.components.StepProgressBar
import com.handover.app.ui.components.StepResultMoment
import com.handover.app.ui.components.StepResultToast
import com.handover.app.ui.components.Tone
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.paper

/** Everything Learn draws, as one value, so every state has a preview and a screenshot. */
data class LearnUi(
    val hasLesson: Boolean,
    val lessonTitle: String = "",
    val stepIndex: Int = 0,
    val total: Int = 0,
    val stepTitle: String = "",
    val segments: List<Segment> = emptyList(),
    val badge: BadgeState = BadgeState.Watching,
    val meta: String? = null,
    val reason: String? = null,
    val mistake: Mistake? = null,
    val mockChecks: Boolean = false,
    /** "Checks off: <reason>", or null. */
    val checksOffPill: String? = null,
    val canBack: Boolean = false,
    val canNext: Boolean = false,
    val isLastStep: Boolean = false,
    val reconnecting: Boolean = false,
    val loading: Boolean = false,
    val moment: StepResultMoment? = null,
    /** True when the learner's camera is the large pane in portrait. */
    val swapped: Boolean = false,
    val corner: Corner = Corner.BottomRight,
    val captionsOn: Boolean = true,
    val muted: Boolean = false,
    val usingThisPhone: Boolean = false,
    /** The current caption, for the bar under the large pane when the clip is the small tile. */
    val caption: String? = null,
    /** The learner camera's aspect (width over height), for the tile's shape. */
    val liveAspect: Float = 16f / 9f,
    /** The Bluetooth output's name (the glasses or headphones) when audio goes there, else null. */
    val audioRoute: String? = null,
    val speaking: Boolean = false,
    val spokenGuidance: Boolean = false,
    val verbosity: Verbosity = Verbosity.Standard,
)

interface LearnActions {
    fun next() {}
    fun back() {}
    fun dismissMistake() {}
    fun showStep(index: Int) {}
    fun swap() {}
    fun corner(c: Corner) {}
    fun toggleCaptions() {}
    fun toggleMute() {}
    fun restart() {}
    fun useThisPhone(on: Boolean) {}
    fun momentGone() {}
    fun spokenGuidance(on: Boolean) {}
    fun verbosity(v: Verbosity) {}
}

/**
 * Learn's layout (SCREENS.md 7). Phone portrait: the expert clip large and the learner's camera as
 * a floating tile; landscape and tablets: side by side, live on the left. The badge, mistake card,
 * Back and Next sit in the bottom third. [clip] and [live] draw the two panes.
 */
@Composable
fun LearnContent(
    ui: LearnUi,
    actions: LearnActions,
    clip: @Composable (Modifier, compact: Boolean, captionsInPane: Boolean) -> Unit,
    live: @Composable (Modifier, compact: Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    BoxWithConstraints(modifier.fillMaxSize().paper()) {
        val sideBySide = maxWidth > maxHeight || maxWidth >= 700.dp
        val tablet = maxWidth >= 700.dp && maxHeight >= 500.dp
        if (!ui.hasLesson) {
            Column(Modifier.fillMaxSize().padding(HOSpace.l)) {
                StepProgressBar(emptyList(), Modifier.padding(top = HOSpace.s))
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    EmptyState(
                        if (ui.loading) "Loading lesson" else "No lesson selected",
                        if (ui.loading) null else "Pick a lesson in the Library to start.",
                        icon = Icons.Outlined.School, loading = ui.loading,
                    )
                }
            }
        } else if (sideBySide) {
            SideBySide(ui, actions, clip, live, tablet)
        } else {
            Portrait(ui, actions, clip, live)
        }
    }
}

@Composable
private fun TopBar(ui: LearnUi, actions: LearnActions) {
    val c = HandOver.colors
    var menu by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().heightIn(min = HOSize.touch), verticalAlignment = Alignment.CenterVertically) {
        Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
            Text(ui.lessonTitle, style = HandOver.type.headline, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false).semantics { heading() })
            if (ui.mockChecks) {
                Spacer(Modifier.width(HOSpace.s))
                Pill("Mock checks", Tone.Caution, icon = Icons.Outlined.Science)
            }
            if (ui.checksOffPill != null) {
                Spacer(Modifier.width(HOSpace.s))
                Pill(ui.checksOffPill, Tone.Caution, icon = Icons.Outlined.WarningAmber)
            }
        }
        if (ui.audioRoute != null) {
            // Where spoken guidance and the clip play: the glasses or headphones. Accent while speaking.
            Pill(
                ui.audioRoute, if (ui.speaking && ui.spokenGuidance) Tone.Accent else Tone.Neutral,
                Modifier.widthIn(max = 150.dp).semantics { contentDescription = "Audio on ${ui.audioRoute}" + if (ui.speaking) ", speaking" else "" },
                icon = if (ui.spokenGuidance) Icons.AutoMirrored.Outlined.VolumeUp else Icons.Outlined.Headphones,
            )
        }
        Box {
            IconCircleButton(Icons.Outlined.MoreVert, "More", { menu = true })
            DropdownMenu(menu, { menu = false }) {
                DropdownMenuItem(text = { Text(if (ui.captionsOn) "Captions Off" else "Captions On") }, onClick = { menu = false; actions.toggleCaptions() })
                DropdownMenuItem(text = { Text(if (ui.muted) "Unmute Clip" else "Mute Clip") }, onClick = { menu = false; actions.toggleMute() })
                DropdownMenuItem(text = { Text("Swap Videos") }, onClick = { menu = false; actions.swap() })
                DropdownMenuItem(text = { Text(if (ui.usingThisPhone) "Stop Using This Phone" else "Use This Phone as Camera") }, onClick = { menu = false; actions.useThisPhone(!ui.usingThisPhone) })
                DropdownMenuItem(text = { Text(if (ui.spokenGuidance) "Spoken Guidance Off" else "Spoken Guidance On") }, onClick = { menu = false; actions.spokenGuidance(!ui.spokenGuidance) })
                if (ui.spokenGuidance) {
                    Verbosity.entries.forEach { v ->
                        DropdownMenuItem(
                            text = { Text("Say: ${v.title}") },
                            trailingIcon = { if (v == ui.verbosity) Icon(Icons.Rounded.Check, null) },
                            onClick = { menu = false; actions.verbosity(v) },
                        )
                    }
                }
                DropdownMenuItem(text = { Text("Restart Lesson") }, onClick = { menu = false; actions.restart() })
            }
        }
    }
}

/** Swipe right on the step info or controls goes Back a step (the system back gesture never does). */
@Composable
private fun Modifier.swipeBack(enabled: Boolean, onBack: () -> Unit): Modifier {
    val threshold = with(LocalDensity.current) { 72.dp.toPx() }
    var total by remember { mutableFloatStateOf(0f) }
    return if (!enabled) this else pointerInput(Unit) {
        detectHorizontalDragGestures(
            onDragStart = { total = 0f },
            onDragEnd = { if (total > threshold) onBack(); total = 0f },
        ) { _, dx -> total += dx }
    }
}

@Composable
private fun StepInfo(ui: LearnUi, oneLine: Boolean = false) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    AnimatedContent(ui.stepIndex to ui.stepTitle, transitionSpec = { fadeIn(HOMotion.clip(reduce)) togetherWith fadeOut(HOMotion.clip(reduce)) }, label = "step") { (i, title) ->
        if (oneLine) {
            Text("Step ${i + 1} of ${ui.total}: $title", style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
        } else {
            Column {
                Text("Step ${i + 1} of ${ui.total}", style = HandOver.type.footnote, color = c.ink2)
                Text(title, style = HandOver.type.stepTitle, color = c.ink, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun NavButtons(ui: LearnUi, actions: LearnActions, nextModifier: Modifier) {
    if (ui.canBack || ui.stepIndex > 0) {
        HOButton(
            null, actions::back, kind = ButtonKind.Secondary, size = ButtonSize.Large, enabled = ui.canBack,
            icon = Icons.AutoMirrored.Rounded.ArrowBack, label = "Back", haptic = HOHaptic.Tap,
            modifier = Modifier.size(HOSize.controlLarge),
        )
        Spacer(Modifier.width(HOSpace.s))
    }
    HOButton(if (ui.isLastStep) "Finish" else "Next", actions::next, nextModifier, ButtonKind.Primary, ButtonSize.Large, enabled = ui.canNext)
}

@Composable
private fun MistakeSlot(ui: LearnUi, actions: LearnActions, onVideo: Boolean = false, modifier: Modifier = Modifier) {
    val reduce = HandOver.reduceMotion
    AnimatedVisibility(
        ui.mistake != null, modifier,
        enter = if (reduce) fadeIn(HOMotion.reduced()) else slideInVertically(HOMotion.panel(reduce)) { -it / 3 } + fadeIn(HOMotion.panel(reduce)),
        exit = fadeOut(HOMotion.reduced()),
    ) {
        val m = ui.mistake ?: return@AnimatedVisibility
        MistakeCard(m, { actions.showStep(m.looksLike) }, actions::dismissMistake, onVideo = onVideo)
    }
}

@Composable
private fun Portrait(
    ui: LearnUi,
    actions: LearnActions,
    clip: @Composable (Modifier, Boolean, Boolean) -> Unit,
    live: @Composable (Modifier, Boolean) -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(horizontal = HOSpace.l)) {
        StepProgressBar(ui.segments, Modifier.padding(top = HOSpace.s))
        TopBar(ui, actions)
        if (ui.reconnecting) Banner("Reconnecting to the hub.", Icons.Outlined.Refresh, Tone.Caution, Modifier.padding(bottom = HOSpace.s))
        Box(Modifier.weight(1f).fillMaxWidth()) {
            PipHost(
                large = { m -> if (ui.swapped) live(m, false) else clip(m, false, true) },
                small = { m -> if (ui.swapped) clip(m, true, false) else live(m, true) },
                smallAspect = if (ui.swapped) 16f / 9f else ui.liveAspect,
                corner = ui.corner, onCorner = actions::corner, onSwap = actions::swap,
                smallLabel = if (ui.swapped) "Expert clip" else "Your camera",
                modifier = Modifier.fillMaxSize(),
            )
            StepResultToast(ui.moment, actions::momentGone, Modifier.align(Alignment.TopCenter).padding(top = HOSpace.m).widthIn(max = 360.dp))
        }
        if (ui.swapped && ui.captionsOn && ui.caption != null) {
            Box(Modifier.fillMaxWidth().padding(top = HOSpace.xs).background(HandOver.colors.stage, RoundedCornerShape(HORadius.small)), contentAlignment = Alignment.Center) {
                CaptionBar(ui.caption)
            }
        }
        Column(Modifier.fillMaxWidth().swipeBack(ui.canBack, actions::back)) {
            Spacer(Modifier.height(HOSpace.m))
            StepInfo(ui)
            MistakeSlot(ui, actions, modifier = Modifier.padding(top = HOSpace.m))
            Row(Modifier.fillMaxWidth().padding(top = HOSpace.m, bottom = HOSpace.m), verticalAlignment = Alignment.CenterVertically) {
                StatusBlock(ui.badge, ui.meta, ui.reason, Modifier.weight(1f).padding(end = HOSpace.s))
                NavButtons(ui, actions, Modifier.fillMaxWidth(0.5f).widthIn(min = 140.dp))
            }
        }
    }
}

@Composable
private fun SideBySide(
    ui: LearnUi,
    actions: LearnActions,
    clip: @Composable (Modifier, Boolean, Boolean) -> Unit,
    live: @Composable (Modifier, Boolean) -> Unit,
    tablet: Boolean,
) {
    val gap = if (tablet) HOSpace.l else HOSpace.m
    val radius = if (tablet) HORadius.panel else HORadius.card
    val margin = if (tablet) HOSpace.xl else HOSpace.l
    Column(Modifier.fillMaxSize().padding(horizontal = margin)) {
        StepProgressBar(ui.segments, Modifier.padding(top = HOSpace.s))
        TopBar(ui, actions)
        if (ui.reconnecting) Banner("Reconnecting to the hub.", Icons.Outlined.Refresh, Tone.Caution, Modifier.padding(bottom = HOSpace.s))
        Row(Modifier.weight(1f).fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(gap)) {
            val livePane: @Composable (Modifier) -> Unit = { m -> live(m.clip(RoundedCornerShape(radius)), false) }
            val clipPane: @Composable (Modifier) -> Unit = { m ->
                Box(m) {
                    // On a phone the mistake card floats over the bottom of the clip; the caption steps aside meanwhile.
                    clip(Modifier.fillMaxSize().clip(RoundedCornerShape(radius)), false, tablet || ui.mistake == null)
                    StepResultToast(ui.moment, actions::momentGone, Modifier.align(Alignment.TopCenter).padding(top = HOSpace.m))
                    if (!tablet) MistakeSlot(ui, actions, onVideo = true, modifier = Modifier.align(Alignment.BottomCenter).padding(HOSpace.s))
                }
            }
            if (ui.swapped) {
                clipPane(Modifier.weight(1f).fillMaxHeight()); livePane(Modifier.weight(1f).fillMaxHeight())
            } else {
                livePane(Modifier.weight(1f).fillMaxHeight()); clipPane(Modifier.weight(1f).fillMaxHeight())
            }
        }
        if (tablet) {
            Row(Modifier.fillMaxWidth().padding(top = HOSpace.l).swipeBack(ui.canBack, actions::back), verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    StepInfo(ui)
                    MistakeSlot(ui, actions, modifier = Modifier.padding(top = HOSpace.m).widthIn(max = 560.dp))
                }
                Spacer(Modifier.width(HOSpace.xl))
                Column(horizontalAlignment = Alignment.End) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        StatusBlock(ui.badge, ui.meta, ui.reason, Modifier.padding(end = HOSpace.l).widthIn(max = 260.dp))
                        NavButtons(ui, actions, Modifier.widthIn(min = 200.dp))
                    }
                }
            }
            Spacer(Modifier.height(HOSpace.xl))
        } else {
            Row(Modifier.fillMaxWidth().padding(vertical = HOSpace.s).swipeBack(ui.canBack, actions::back), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) { StepInfo(ui, oneLine = true) }
                Spacer(Modifier.width(HOSpace.m))
                StatusBlock(ui.badge, null, null, Modifier.padding(end = HOSpace.m))
                NavButtons(ui, actions, Modifier.widthIn(min = 160.dp))
            }
        }
    }
}

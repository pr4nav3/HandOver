package com.handover.app.ui.done

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.TouchApp
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material.icons.automirrored.outlined.Redo
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.Format
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.HOCard
import com.handover.app.ui.components.ScoreRing
import com.handover.app.ui.components.Stat
import com.handover.app.ui.components.TimeBar
import com.handover.app.ui.components.Tone
import com.handover.app.ui.components.card
import com.handover.app.ui.components.toneText
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.paper

private const val NO_DATA = "Not enough data"

/**
 * The Done screen, SCREENS.md 8. Every number comes from [model], which comes only from events
 * this device saw (or the hub's score). Missing data reads "Not enough data".
 */
@Composable
fun DoneScreen(
    model: DoneModel,
    connected: Boolean,
    onPracticeWeakest: (Int) -> Unit,
    onStartOver: () -> Unit,
    onPracticeStep: (Int) -> Unit,
    modifier: Modifier = Modifier,
    /** Back to Home, ending the lesson on this phone. Null hides the button (previews). */
    onFinish: (() -> Unit)? = null,
) {
    BoxWithConstraints(modifier.fillMaxSize().paper()) {
        val wide = maxWidth >= 700.dp
        if (wide) {
            Row(Modifier.fillMaxSize().padding(HOSpace.xl), horizontalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
                Column(Modifier.width(380.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
                    Summary(model)
                    Buttons(model, connected, onPracticeWeakest, onStartOver, onFinish)
                }
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    Breakdown(model, onPracticeStep)
                }
            }
        } else {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l, vertical = HOSpace.xl),
                verticalArrangement = Arrangement.spacedBy(HOSpace.l),
            ) {
                Summary(model)
                Breakdown(model, onPracticeStep)
                Buttons(model, connected, onPracticeWeakest, onStartOver, onFinish)
            }
        }
    }
}

@Composable
private fun Summary(model: DoneModel) {
    val c = HandOver.colors
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        ScoreRing(model.score, model.label)
        Spacer(Modifier.height(HOSpace.l))
        Text("Lesson complete", style = HandOver.type.display, color = c.ink, textAlign = TextAlign.Center, modifier = Modifier.semantics { heading() })
        Text(model.lessonTitle, style = HandOver.type.callout, color = c.ink2, textAlign = TextAlign.Center, maxLines = 2)
        if (model.source == ScoreSource.Hub) {
            Text("Score from the hub", style = HandOver.type.caption, color = c.ink2, modifier = Modifier.padding(top = 2.dp))
        }
    }
    StatGrid(model)
    BestAndWeakest(model)
    HOCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.Top) {
            Icon(Icons.Outlined.Lightbulb, null, tint = c.ink2, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(HOSpace.s))
            Text(model.tip, style = HandOver.type.body, color = c.ink)
        }
    }
}

@Composable
private fun StatGrid(model: DoneModel) {
    val cells = buildList {
        add((model.runSeconds?.let { Format.clock(it) } ?: NO_DATA) to "Your time")
        add((model.expertSeconds?.let { Format.clock(it) } ?: NO_DATA) to "Expert")
        add("${model.checkedByCamera} of ${model.cameraSteps}" to "Checked by camera")
        add("${model.markedDone}" to "Marked done")
        add("${model.mistakes}" to "Mistakes caught")
        if (model.skipped > 0) add("${model.skipped}" to "Skipped")
    }
    Column(Modifier.fillMaxWidth().card().padding(vertical = HOSpace.m), verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
        cells.chunked(3).forEach { row ->
            Row(Modifier.fillMaxWidth()) {
                row.forEach { (v, l) -> Stat(v, l, Modifier.weight(1f).padding(horizontal = HOSpace.xs), valueIsWords = v == NO_DATA) }
                repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

@Composable
private fun BestAndWeakest(model: DoneModel) {
    val c = HandOver.colors
    if (model.best == null && model.weakest == null) {
        HOCard(Modifier.fillMaxWidth()) { Text("Not enough data to compare steps.", style = HandOver.type.callout, color = c.ink2) }
        return
    }
    val stack = LocalDensity.current.fontScale >= 1.5f
    val cards: List<Pair<String, Pick>> = listOfNotNull(model.best?.let { "Best step" to it }, model.weakest?.let { "Practice this" to it })
    if (stack || cards.size == 1) {
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.m)) { cards.forEach { (t, p) -> PickCard(t, p, Modifier.fillMaxWidth()) } }
    } else {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) { cards.forEach { (t, p) -> PickCard(t, p, Modifier.weight(1f)) } }
    }
}

@Composable
private fun PickCard(title: String, pick: Pick, modifier: Modifier) {
    val c = HandOver.colors
    HOCard(modifier.heightIn(min = 112.dp), padding = HOSpace.m) {
        Text(title, style = HandOver.type.section, color = c.ink2)
        Spacer(Modifier.height(HOSpace.xs))
        Text("Step ${pick.n}. ${pick.title}", style = HandOver.type.headline, color = c.ink, maxLines = 3, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(HOSpace.xs))
        Text(pick.reason, style = HandOver.type.footnote, color = c.ink2)
    }
}

@Composable
private fun Breakdown(model: DoneModel, onPracticeStep: (Int) -> Unit) {
    val c = HandOver.colors
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
    Text("Steps", style = HandOver.type.section, color = c.ink2, modifier = Modifier.padding(start = HOSpace.xs, top = HOSpace.xs).semantics { heading() })
    Column(Modifier.fillMaxWidth().card()) {
        model.steps.forEachIndexed { i, s ->
            StepRow(s, model.timeScale, onPracticeStep)
            if (i < model.steps.size - 1) Box(Modifier.fillMaxWidth().padding(start = HOSpace.l).height(com.handover.app.ui.theme.Hairline).background(c.line))
        }
    }
    }
}

private data class How(val icon: ImageVector, val words: String, val tone: Tone)

private fun how(s: StepView): How = when (s.completion) {
    Completion.Camera -> How(Icons.Outlined.CheckCircle, "Checked by camera", Tone.Good)
    Completion.Hand -> How(Icons.Outlined.TouchApp, "Marked done", Tone.Neutral)
    Completion.Skipped -> How(Icons.AutoMirrored.Outlined.Redo, "Skipped", Tone.Caution)
    null -> How(Icons.Outlined.Circle, "Not started", Tone.Idle)
}

@Composable
private fun StepRow(s: StepView, scale: Double, onPracticeStep: (Int) -> Unit) {
    val c = HandOver.colors
    var menu by remember { mutableStateOf(false) }
    val h = how(s)
    val spoken = buildString {
        append("Step ${s.n}. ")
        append(if (s.seconds != null) "You ${s.seconds.toInt()} seconds" else "No time")
        if (s.expert != null) append(", expert ${s.expert.toInt()} seconds")
        append(". ${h.words}. ")
        append(if (s.mistakes == 0) "No mistakes." else "${Format.count(s.mistakes, "mistake")}.")
    }
    Box {
        Column(
            Modifier.fillMaxWidth().clickable(onClickLabel = "Practice Step ${s.n}") { menu = true }
                .padding(horizontal = HOSpace.l, vertical = HOSpace.m).clearAndSetSemantics { contentDescription = spoken },
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${s.n}", style = HandOver.type.headline, color = c.ink2, modifier = Modifier.widthIn(min = 24.dp))
                Text(s.title, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            }
            TimeBar(s.seconds, s.expert, scale, Modifier.padding(start = 24.dp))
            Row(Modifier.padding(start = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(h.icon, null, tint = toneText(h.tone), modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(4.dp))
                Text(h.words, style = HandOver.type.footnote, color = toneText(h.tone))
                if (s.mistakes > 0) {
                    Spacer(Modifier.width(HOSpace.m))
                    Text(Format.count(s.mistakes, "mistake"), style = HandOver.type.footnote, color = c.caution)
                }
            }
        }
        DropdownMenu(menu, { menu = false }) {
            DropdownMenuItem(text = { Text("Practice Step ${s.n}") }, onClick = { menu = false; onPracticeStep(s.index) })
        }
    }
}

@Composable
private fun Buttons(model: DoneModel, connected: Boolean, onPracticeWeakest: (Int) -> Unit, onStartOver: () -> Unit, onFinish: (() -> Unit)?) {
    Column(Modifier.fillMaxWidth().padding(top = HOSpace.s), verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        val weakest = model.weakest
        if (weakest != null) {
            HOButton("Practice the Weakest Step", { onPracticeWeakest(weakest.index) }, Modifier.fillMaxWidth(), ButtonKind.Primary, ButtonSize.Large, enabled = connected)
        }
        HOButton("Start Over", onStartOver, Modifier.fillMaxWidth(), if (weakest == null) ButtonKind.Primary else ButtonKind.Secondary, ButtonSize.Large, enabled = connected)
        if (onFinish != null) HOButton("Back to Home", onFinish, Modifier.fillMaxWidth(), ButtonKind.Quiet, ButtonSize.Large)
        if (!connected) Text("Waiting for the hub.", style = HandOver.type.footnote, color = HandOver.colors.ink2, modifier = Modifier.align(Alignment.CenterHorizontally))
    }
}

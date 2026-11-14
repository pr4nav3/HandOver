package com.handover.app.ui.onboarding

import android.net.Uri
import android.view.TextureView
import androidx.annotation.DrawableRes
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import com.handover.app.R
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.QuietButton
import com.handover.app.ui.components.StatusBadge
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline
import com.handover.app.ui.theme.paper
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.absoluteValue

/** The real frames of lessons/synthetic-fortune-teller-v1, bundled so the pages work before any hub. */
val SampleFrames = listOf(
    R.drawable.onboarding_frame_01, R.drawable.onboarding_frame_02, R.drawable.onboarding_frame_03, R.drawable.onboarding_frame_04,
    R.drawable.onboarding_frame_05, R.drawable.onboarding_frame_06, R.drawable.onboarding_frame_07, R.drawable.onboarding_frame_08,
)

/** The sample lesson's step 4 title, used by the theme preview. */
const val SampleStep4 = "Fold all four corners to center"

private data class Welcome(val title: String, val line: String, val spoken: String, val button: String)

private val Pages = listOf(
    Welcome("An expert does it once", "They record the task on their phone or Ray-Ban Meta glasses and talk through each step.", "A sample lesson playing, with a recording indicator", "Continue"),
    Welcome("We turn it into steps", "HandOver finds where each step starts and ends, cuts a clip for each one, and adds captions.", "The lesson split into 8 steps on a timeline", "Continue"),
    Welcome("Your camera follows along", "Point a phone at your work. When a step looks done, the next clip starts.", "Your camera beside the expert's clip. The status changes to verified.", "Continue"),
    Welcome("You get a score and a tip", "See how each step went against the expert, and what to practice next.", "A score ring and a time bar for each step", "Get Started"),
)

/**
 * The four welcome pages (SCREENS.md 25.2): a pager with the illustration in the top 55%, title,
 * line, page dots and one primary button. Skip at the top. The illustration lags the text a little
 * while swiping (0.6x parallax), and every animation plays once per appearance.
 */
@Composable
fun WelcomePages(onDone: () -> Unit, initialPage: Int = 0, settle: Boolean = false) {
    val pager = rememberPagerState(initialPage) { Pages.size }
    val scope = rememberCoroutineScope()
    val c = HandOver.colors
    Box(Modifier.fillMaxSize().paper().statusBarsPadding().navigationBarsPadding()) {
        HorizontalPager(pager, Modifier.fillMaxSize()) { i ->
            WelcomePage(i, pager, settle)
        }
        QuietButton("Skip", onDone, size = ButtonSize.Regular, modifier = Modifier.align(Alignment.TopEnd).padding(HOSpace.s))
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(HOSpace.l), horizontalAlignment = Alignment.CenterHorizontally) {
            Row(Modifier.padding(bottom = HOSpace.l).semantics { contentDescription = "Page ${pager.currentPage + 1} of ${Pages.size}" }, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                repeat(Pages.size) { i -> Box(Modifier.size(7.dp).background(if (i == pager.currentPage) c.ink else c.ink3, CircleShape)) }
            }
            PrimaryButton(Pages[pager.currentPage].button, {
                if (pager.currentPage == Pages.lastIndex) onDone() else scope.launch { pager.animateScrollToPage(pager.currentPage + 1) }
            }, fullWidth = true)
        }
    }
}

@Composable
private fun WelcomePage(index: Int, pager: PagerState, settle: Boolean) {
    val page = Pages[index]
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    val visible = pager.currentPage == index
    // Fade in on first appearance: picture, then text 80 ms later (DESIGN.md 7.3).
    val pic = remember { Animatable(if (reduce || settle) 1f else 0f) }
    val text = remember { Animatable(if (reduce || settle) 1f else 0f) }
    LaunchedEffect(visible) {
        if (!visible) return@LaunchedEffect
        launch { pic.animateTo(1f, tween(300, easing = FastOutSlowInEasing)) }
        delay(80)
        text.animateTo(1f, tween(300, easing = FastOutSlowInEasing))
    }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val offset = (pager.currentPage - index) + pager.currentPageOffsetFraction
        val illustrationHeight = minOf(maxHeight * 0.55f, 360.dp)
        Column(Modifier.fillMaxSize().semantics(mergeDescendants = true) { }, horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier.fillMaxWidth().height(illustrationHeight).padding(top = 56.dp, start = HOSpace.xl, end = HOSpace.xl)
                    .graphicsLayer {
                        alpha = pic.value
                        // The picture moves at 0.6x of the page: shift it back by 0.4 of the offset.
                        if (!reduce) translationX = offset * size.width * 0.4f
                    }
                    .clearAndSetSemantics { contentDescription = page.spoken },
                contentAlignment = Alignment.Center,
            ) {
                when (index) {
                    0 -> RecordIllustration(visible, settle)
                    1 -> StepsIllustration(visible, settle)
                    2 -> FollowIllustration(visible, settle)
                    else -> ScoreIllustration(visible, settle)
                }
            }
            Column(
                Modifier.padding(horizontal = HOSpace.xl).padding(top = HOSpace.xl).graphicsLayer { alpha = text.value },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(page.title, style = HandOver.type.display, color = c.ink, textAlign = TextAlign.Center, maxLines = 2)
                Spacer(Modifier.height(HOSpace.s))
                Text(page.line, style = HandOver.type.body, color = c.ink2, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 340.dp))
            }
        }
    }
}

/** A rounded 16:9 pane on `stage`. */
@Composable
private fun StagePane(modifier: Modifier = Modifier, radius: Dp = HORadius.card, content: @Composable () -> Unit) {
    Box(modifier.aspectRatio(16f / 9f).clip(RoundedCornerShape(radius)).background(HandOver.colors.stage), contentAlignment = Alignment.Center) { content() }
}

@Composable
private fun Frame(@DrawableRes id: Int, modifier: Modifier = Modifier) {
    Image(painterResource(id), null, contentScale = ContentScale.Crop, modifier = modifier.fillMaxSize())
}

/** Page 1: the sample clip on a loop (muted), "Sample lesson, rendered", and a Recording capsule with a live waveform. */
@Composable
private fun RecordIllustration(visible: Boolean, settle: Boolean) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    var playing by remember { mutableStateOf(!reduce) }
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        StagePane(Modifier.fillMaxWidth()) {
            Frame(SampleFrames[1])
            if (playing && visible && !LocalInspectionMode.current && !settle) SampleClip()
            if (!playing) {
                Icon(Icons.Outlined.PlayCircle, "Play sample clip", tint = Color.White, modifier = Modifier.size(48.dp).clip(CircleShape).clickable { playing = true })
            }
        }
        Text("Sample lesson, rendered", style = HandOver.type.caption, color = c.ink2)
        Spacer(Modifier.height(HOSpace.xs))
        Row(
            Modifier.background(c.raised, CircleShape).border(Hairline, c.line, CircleShape).padding(horizontal = HOSpace.m, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(9.dp).background(c.record, CircleShape))
            Spacer(Modifier.width(HOSpace.s))
            Text("Recording", style = HandOver.type.badge, color = c.ink)
            Spacer(Modifier.width(HOSpace.m))
            Waveform(animate = visible && !reduce && !settle)
        }
    }
}

/** Five bars that rise and fall in turn while the page is visible (the iOS variable color effect). */
@Composable
private fun Waveform(animate: Boolean) {
    val c = HandOver.colors
    val heights = listOf(0.45f, 0.8f, 1f, 0.7f, 0.4f)
    val phase = if (animate) {
        val t = rememberInfiniteTransition(label = "wave")
        t.animateFloat(0f, 1f, infiniteRepeatable(tween(1100, easing = LinearEasing), RepeatMode.Restart), label = "phase").value
    } else 0f
    Canvas(Modifier.size(34.dp, 16.dp)) {
        val w = 3.dp.toPx()
        val gap = (size.width - w * 5) / 4
        heights.forEachIndexed { i, h ->
            val lit = if (animate) ((phase * 5).toInt() == i) else false
            val bh = size.height * h
            drawRoundRect(
                c.ink.copy(alpha = if (lit) 1f else 0.45f), Offset(i * (w + gap), (size.height - bh) / 2), Size(w, bh), CornerRadius(w / 2),
            )
        }
    }
}

/** The bundled clip 02, muted and looping, drawn into a TextureView over its own first frame. */
@Composable
private fun SampleClip() {
    val context = LocalContext.current
    val player = remember {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(Uri.parse("android.resource://${context.packageName}/${R.raw.onboarding_clip_02}")))
            volume = 0f
            repeatMode = Player.REPEAT_MODE_ONE
            playWhenReady = true
            prepare()
        }
    }
    DisposableEffect(Unit) { onDispose { player.release() } }
    AndroidView({ TextureView(it).also { v -> player.setVideoTextureView(v) } }, Modifier.fillMaxSize())
}

/** Page 2: eight real step tiles with number pills, and a timeline that fills left to right. */
@Composable
private fun StepsIllustration(visible: Boolean, settle: Boolean) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    val fills = remember { List(8) { Animatable(if (reduce || settle) 1f else 0f) } }
    LaunchedEffect(visible) {
        if (!visible || reduce || settle) return@LaunchedEffect
        fills.forEachIndexed { i, a -> launch { delay(120L * i); a.animateTo(1f, tween(350, easing = FastOutSlowInEasing)) } }
    }
    Column(verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
        listOf(0..3, 4..7).forEach { range ->
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                range.forEach { i ->
                    Box(Modifier.weight(1f).aspectRatio(16f / 10f).clip(RoundedCornerShape(HORadius.small)).background(c.stage)) {
                        Frame(SampleFrames[i])
                        Text(
                            "${i + 1}", style = HandOver.type.caption.copy(fontWeight = FontWeight.SemiBold), color = Color.White,
                            modifier = Modifier.align(Alignment.TopStart).padding(4.dp).background(Color.Black.copy(alpha = 0.6f), CircleShape).padding(horizontal = 6.dp),
                        )
                    }
                }
            }
        }
        // The timeline: eight equal 3 s spans, the lesson's real step layout.
        Row(Modifier.fillMaxWidth().height(28.dp).clip(RoundedCornerShape(HORadius.small)).background(c.well).padding(3.dp), horizontalArrangement = Arrangement.spacedBy(3.dp)) {
            fills.forEachIndexed { i, a ->
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    Box(
                        Modifier.fillMaxHeight().fillMaxWidth(a.value).clip(RoundedCornerShape(5.dp))
                            .background(if (i == 0) c.accent else c.raised).border(Hairline, c.line, RoundedCornerShape(5.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (a.value > 0.6f) Text("${i + 1}", style = HandOver.type.caption, color = if (i == 0) c.onAccent else c.ink2)
                    }
                }
            }
        }
        Text("8 steps, 3 s each", style = HandOver.type.caption, color = c.ink2, modifier = Modifier.align(Alignment.CenterHorizontally))
    }
}

/** Page 3: your camera beside the expert's step 3, and the badge turning Watching to Verified. */
@Composable
private fun FollowIllustration(visible: Boolean, settle: Boolean) {
    val c = HandOver.colors
    var verified by remember { mutableStateOf(settle) }
    LaunchedEffect(visible) {
        if (!visible || settle) return@LaunchedEffect
        verified = false
        delay(1_200)
        verified = true
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
        Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) {
            Box(Modifier.weight(1f).aspectRatio(3f / 4f).clip(RoundedCornerShape(HORadius.card)).background(c.stage), contentAlignment = Alignment.Center) {
                Canvas(Modifier.fillMaxSize().padding(14.dp)) {
                    val arm = size.minDimension * 0.18f
                    val s = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round)
                    val col = Color.White.copy(alpha = 0.7f)
                    listOf(Offset(0f, 0f) to Offset(1f, 1f), Offset(size.width, 0f) to Offset(-1f, 1f), Offset(0f, size.height) to Offset(1f, -1f), Offset(size.width, size.height) to Offset(-1f, -1f)).forEach { (p, d) ->
                        drawLine(col, p, Offset(p.x + d.x * arm, p.y), s.width, StrokeCap.Round)
                        drawLine(col, p, Offset(p.x, p.y + d.y * arm), s.width, StrokeCap.Round)
                    }
                }
                Icon(Icons.Outlined.Videocam, null, tint = Color.White.copy(alpha = 0.7f), modifier = Modifier.size(44.dp))
                Text("Your camera", style = HandOver.type.caption, color = Color.White.copy(alpha = 0.7f), modifier = Modifier.align(Alignment.BottomCenter).padding(10.dp))
            }
            Box(Modifier.weight(1f).aspectRatio(3f / 4f).clip(RoundedCornerShape(HORadius.card)).background(c.stage)) {
                Frame(SampleFrames[2])
                Text("Expert, step 3", style = HandOver.type.caption, color = Color.White, modifier = Modifier.align(Alignment.BottomCenter).padding(10.dp).background(c.captionFill, CircleShape).padding(horizontal = 8.dp, vertical = 2.dp))
            }
        }
        StatusBadge(if (verified) BadgeState.Verified else BadgeState.Watching)
    }
}

/** Page 4: an empty score ring that draws to 70% and three time bars, with no figures (there is no run yet). */
@Composable
private fun ScoreIllustration(visible: Boolean, settle: Boolean) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    val ring = remember { Animatable(if (reduce || settle) 0.7f else 0f) }
    val bars = remember { List(3) { Animatable(if (reduce || settle) 1f else 0f) } }
    LaunchedEffect(visible) {
        if (!visible || reduce || settle) return@LaunchedEffect
        delay(200)
        launch { ring.animateTo(0.7f, tween(600, easing = FastOutSlowInEasing)) }
        bars.forEachIndexed { i, a -> launch { delay(80L * i); a.animateTo(1f, tween(250, easing = FastOutSlowInEasing)) } }
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
        Box(Modifier.size(132.dp), contentAlignment = Alignment.Center) {
            Canvas(Modifier.fillMaxSize()) {
                val w = 12.dp.toPx()
                val inset = w / 2
                val arc = Size(size.width - w, size.height - w)
                drawArc(c.well, -90f, 360f, false, Offset(inset, inset), arc, style = Stroke(w))
                drawArc(c.accent, -90f, 360f * ring.value, false, Offset(inset, inset), arc, style = Stroke(w, cap = StrokeCap.Round))
            }
            Text("Your score", style = HandOver.type.footnote, color = c.ink2)
        }
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
            listOf(0.9f to 0.75f, 0.6f to 0.7f, 0.8f to 0.55f).forEachIndexed { i, (expert, you) ->
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Box(Modifier.fillMaxWidth(expert * bars[i].value).height(6.dp).background(c.ink3, RoundedCornerShape(HORadius.small)))
                    Box(Modifier.fillMaxWidth(you * bars[i].value).height(6.dp).background(c.accent, RoundedCornerShape(HORadius.small)))
                }
            }
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(HORadius.control)).background(c.raised).border(Hairline, c.line, RoundedCornerShape(HORadius.control)).padding(HOSpace.s),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Outlined.Lightbulb, null, tint = c.caution, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("One tip, from your own run.", style = HandOver.type.caption, color = c.ink2)
            }
        }
    }
}

/** True for [index] when [pager] has settled on it (helps tests). */
fun PagerState.isOn(index: Int) = (currentPage - index + currentPageOffsetFraction).absoluteValue < 0.01f

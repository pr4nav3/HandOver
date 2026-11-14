package com.handover.app.ui.components

import android.content.Context
import android.media.AudioManager
import android.net.Uri
import android.view.TextureView
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ClosedCaption
import androidx.compose.material.icons.outlined.ClosedCaptionDisabled
import androidx.compose.material.icons.outlined.Replay
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material.icons.automirrored.outlined.VolumeOff
import androidx.compose.material.icons.automirrored.outlined.VolumeUp
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.common.text.CueGroup
import androidx.media3.exoplayer.ExoPlayer
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import kotlinx.coroutines.delay

/** A step clip and its captions, as full URLs (with `?v=<rev>`). */
data class ClipSource(val video: String, val captions: String?)

enum class ClipPhase { Loading, Playing, Error }

/**
 * Two ExoPlayers, so the next step's clip is already buffered when the step changes (DESIGN.md
 * 3.4, double buffered). The front player loops the current clip; the back one holds the next
 * clip (from `state.next_clip`) paused at its first frame. Captions are a side-loaded WebVTT track;
 * ExoPlayer hands the cues over and the app draws them in its own caption bar.
 */
@Stable
class ClipDeck(context: Context) {
    private val players = Array(2) { i -> build(context, i) }
    private val loaded = arrayOfNulls<String>(2)

    var front by mutableIntStateOf(0)
        private set

    /** Whether each player has drawn its first frame for what it holds; the cross-fade waits for it. */
    val firstFrame = mutableStateListOf(false, false)

    var caption by mutableStateOf<String?>(null)
        private set
    var aspect by mutableFloatStateOf(16f / 9f)
        private set
    var phase by mutableStateOf(ClipPhase.Loading)
        private set

    private var playing = true

    fun player(i: Int): Player = players[i]

    /** Shows [clip] on the front player. Reloads only when the URL changes, never on other redraws. */
    fun show(clip: ClipSource?) {
        if (clip == null) {
            players.forEach { it.stop(); it.clearMediaItems() }
            loaded.fill(null)
            caption = null
            return
        }
        if (loaded[front] == clip.video) return
        val back = 1 - front
        if (loaded[back] != clip.video) load(back, clip)
        players[front].pause()
        front = back
        players[back].seekTo(0)
        players[back].playWhenReady = playing
        refreshFromFront()
    }

    /** Buffers [clip] on the back player so the next step starts at once. */
    fun preload(clip: ClipSource?) {
        if (clip == null || loaded[front] == clip.video) return
        val back = 1 - front
        if (loaded[back] == clip.video) return
        load(back, clip)
        players[back].playWhenReady = false
    }

    /** Muted, ducked to 25% while spoken guidance talks, or full. */
    fun setVolume(muted: Boolean, ducked: Boolean) = players.forEach { it.volume = if (muted) 0f else if (ducked) 0.25f else 1f }

    /** Plays the front clip, or pauses it (background, Done screen). */
    fun setPlaying(on: Boolean) {
        playing = on
        players[front].playWhenReady = on
    }

    fun replay() {
        players[front].seekTo(0)
        players[front].playWhenReady = true
    }

    fun retry() {
        val p = players[front]
        phase = ClipPhase.Loading
        p.prepare()
        p.playWhenReady = playing
    }

    fun release() = players.forEach { it.release() }

    private fun load(i: Int, clip: ClipSource) {
        val item = MediaItem.Builder().setUri(clip.video).setMediaId(clip.video).apply {
            clip.captions?.let {
                setSubtitleConfigurations(
                    listOf(
                        MediaItem.SubtitleConfiguration.Builder(Uri.parse(it))
                            .setMimeType(MimeTypes.TEXT_VTT).setLanguage("en").setSelectionFlags(C.SELECTION_FLAG_DEFAULT).build(),
                    ),
                )
            }
        }.build()
        loaded[i] = clip.video
        firstFrame[i] = false
        players[i].setMediaItem(item)
        players[i].prepare()
    }

    private fun refreshFromFront() {
        val p = players[front]
        caption = p.currentCues.cues.joinToString("\n") { it.text?.toString().orEmpty() }.trim().ifEmpty { null }
        p.videoSize.takeIf { it.width > 0 && it.height > 0 }?.let { aspect = it.width * it.pixelWidthHeightRatio / it.height }
        phase = when {
            p.playerError != null -> ClipPhase.Error
            firstFrame[front] -> ClipPhase.Playing
            else -> ClipPhase.Loading
        }
    }

    private fun build(context: Context, i: Int): ExoPlayer = ExoPlayer.Builder(context).build().apply {
        repeatMode = Player.REPEAT_MODE_ONE
        trackSelectionParameters = trackSelectionParameters.buildUpon().setPreferredTextLanguage("en").build()
        addListener(object : Player.Listener {
            override fun onCues(cueGroup: CueGroup) {
                if (front == i) caption = cueGroup.cues.joinToString("\n") { it.text?.toString().orEmpty() }.trim().ifEmpty { null }
            }

            override fun onVideoSizeChanged(videoSize: VideoSize) {
                if (front == i && videoSize.width > 0 && videoSize.height > 0) aspect = videoSize.width * videoSize.pixelWidthHeightRatio / videoSize.height
            }

            override fun onRenderedFirstFrame() {
                firstFrame[i] = true
                if (front == i) phase = ClipPhase.Playing
            }

            override fun onPlayerError(error: PlaybackException) {
                if (front == i) phase = ClipPhase.Error
            }
        })
    }
}

/** A deck for the composition, released when it leaves. Null in previews. */
@Composable
fun rememberClipDeck(): ClipDeck? {
    if (LocalInspectionMode.current) return null
    val context = LocalContext.current
    val deck = remember { ClipDeck(context.applicationContext) }
    DisposableEffect(deck) { onDispose { deck.release() } }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner, deck) {
        val obs = LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_STOP) deck.player(deck.front).pause()
        }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    return deck
}

/** True when the phone is on silent or vibrate: the clip then starts muted (DESIGN.md 3.4). */
fun isPhoneSilent(context: Context): Boolean =
    context.getSystemService(AudioManager::class.java)?.ringerMode?.let { it != AudioManager.RINGER_MODE_NORMAL } ?: false

/**
 * The expert clip pane: black `stage`, video aspect fit, the app's caption bar at the bottom, and
 * Replay, Mute and Captions in a glass capsule that appears on tap and hides after 3 s.
 * With [deck] null (previews, screenshots) it draws [still] instead of video.
 */
@Composable
fun ClipPlayer(
    deck: ClipDeck?,
    clip: ClipSource?,
    next: ClipSource?,
    stepNumber: Int,
    modifier: Modifier = Modifier,
    radius: Dp = HORadius.card,
    playing: Boolean = true,
    muted: Boolean = false,
    /** Spoken guidance is talking: the clip drops to 25%. */
    ducked: Boolean = false,
    captionsOn: Boolean = true,
    /** Draw captions inside the pane. False when the caller shows them under it instead. */
    captionsInPane: Boolean = true,
    compact: Boolean = false,
    onToggleMute: () -> Unit = {},
    onToggleCaptions: () -> Unit = {},
    still: ImageBitmap? = null,
    stillCaption: String? = null,
) {
    val reduce = HandOver.reduceMotion
    if (deck != null) {
        LaunchedEffect(deck, clip?.video) { deck.show(clip) }
        LaunchedEffect(deck, next?.video) { deck.preload(next) }
        LaunchedEffect(deck, playing) { deck.setPlaying(playing) }
        LaunchedEffect(deck, muted, ducked) { deck.setVolume(muted, ducked) }
    }
    var controls by remember { mutableStateOf(false) }
    LaunchedEffect(controls) { if (controls) { delay(3_000); controls = false } }
    val caption = deck?.caption ?: stillCaption
    val phase = deck?.phase ?: ClipPhase.Playing
    val shape = RoundedCornerShape(radius)
    Box(
        modifier
            .clip(shape)
            .background(HandOver.colors.stage)
            .clickable(remember { MutableInteractionSource() }, indication = null, enabled = !compact) { controls = !controls }
            .semantics {
                contentDescription = "Expert clip for step $stepNumber"
                stateDescription = listOfNotNull(if (phase == ClipPhase.Playing && playing) "playing" else "paused", caption?.takeIf { captionsOn }).joinToString(", ")
            },
        contentAlignment = Alignment.Center,
    ) {
        when {
            clip == null && still == null -> Text("No lesson selected", style = HandOver.type.callout, color = Color.White.copy(alpha = 0.6f))
            deck == null -> still?.let { Image(it, null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize()) }
            else -> {
                val f = deck.front
                BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    val paneWider = maxHeight.value > 0 && maxWidth / maxHeight > deck.aspect
                    Box(Modifier.aspectRatio(deck.aspect, matchHeightConstraintsFirst = paneWider)) {
                        for (i in 0..1) {
                            // The cross-fade waits for the new clip's first frame; until then the old one stays.
                            val visible = (i == f && deck.firstFrame[i]) || (i != f && !deck.firstFrame[f] && deck.firstFrame[i])
                            val a by animateFloatAsState(if (visible) 1f else 0f, HOMotion.clip(reduce), label = "clip$i")
                            AndroidView(
                                factory = { ctx -> TextureView(ctx).also { (deck.player(i) as ExoPlayer).setVideoTextureView(it) } },
                                modifier = Modifier.fillMaxSize().alpha(a),
                            )
                        }
                    }
                }
            }
        }
        if (deck != null && phase == ClipPhase.Loading && clip != null) {
            var late by remember(clip.video) { mutableStateOf(false) }
            LaunchedEffect(clip.video) { delay(500); late = true }
            if (late) CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
        }
        if (phase == ClipPhase.Error) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                Icon(Icons.Outlined.WarningAmber, null, tint = Color.White.copy(alpha = 0.6f), modifier = Modifier.size(28.dp))
                Text("Clip did not load.", style = HandOver.type.callout, color = Color.White)
                HOButton("Try Again", { deck?.retry() }, kind = ButtonKind.Glass, size = ButtonSize.Small)
            }
        }
        if (captionsOn && captionsInPane && caption != null && phase != ClipPhase.Error) {
            val pad = if (compact) HOSpace.xs else HOSpace.m
            CaptionBar(caption, Modifier.align(Alignment.BottomCenter).padding(start = pad, end = pad, top = pad, bottom = pad + LocalPipClearance.current), compact = compact)
        }
        AnimatedVisibility(controls && !compact, Modifier.align(Alignment.TopEnd).padding(HOSpace.s), enter = fadeIn(), exit = fadeOut()) {
            Row(Modifier.glass().padding(horizontal = HOSpace.xs)) {
                IconCircleButton(Icons.Outlined.Replay, "Replay", { deck?.replay(); controls = true }, onVideo = true, diameter = 32.dp)
                IconCircleButton(if (muted) Icons.AutoMirrored.Outlined.VolumeOff else Icons.AutoMirrored.Outlined.VolumeUp, if (muted) "Unmute" else "Mute", { onToggleMute(); controls = true }, onVideo = true, diameter = 32.dp)
                IconCircleButton(if (captionsOn) Icons.Outlined.ClosedCaption else Icons.Outlined.ClosedCaptionDisabled, if (captionsOn) "Captions Off" else "Captions On", { onToggleCaptions(); controls = true }, onVideo = true, diameter = 32.dp)
            }
        }
    }
}

/** The caption bar: 72% black, small radius, white semibold text, centered, at most 2 lines. */
@Composable
fun CaptionBar(text: String, modifier: Modifier = Modifier, compact: Boolean = false) {
    val c = HandOver.colors
    Text(
        text,
        style = if (compact) HandOver.type.caption.copy(textAlign = TextAlign.Center) else HandOver.type.captionText,
        color = c.captionInk,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
        modifier = modifier
            .widthIn(max = 560.dp)
            .background(c.captionFill, RoundedCornerShape(HORadius.small))
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

package com.handover.app.ui.editor

import android.view.TextureView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import com.handover.app.ui.library.HubImage
import com.handover.app.ui.library.QuietButton
import com.handover.app.ui.theme.HandOver

/**
 * A step clip on the black stage (DESIGN.md 3.4), looping, aspect fit. Shows [poster] until the first frame
 * and in previews. Captions are drawn by the caller from [caption] so they look the same on every platform.
 */
@Composable
fun ClipPlayer(
    url: String?,
    poster: List<String>,
    modifier: Modifier = Modifier,
    caption: String? = null,
    label: String = "Expert clip",
    /** Seconds into the clip, about five times a second while playing. */
    onPosition: (Double) -> Unit = {},
) {
    var failed by remember(url) { mutableStateOf(false) }
    var showing by remember(url) { mutableStateOf(false) }
    var attempt by remember(url) { mutableStateOf(0) }
    val inPreview = LocalInspectionMode.current
    Box(modifier.background(Color.Black).semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
        if (!inPreview && url != null && !failed) {
            val context = LocalContext.current
            val player = remember(url, attempt) {
                ExoPlayer.Builder(context).build().apply {
                    repeatMode = Player.REPEAT_MODE_ONE
                    setMediaItem(MediaItem.fromUri(url))
                    playWhenReady = true
                    prepare()
                }
            }
            DisposableEffect(player) {
                val listener = object : Player.Listener {
                    override fun onRenderedFirstFrame() { showing = true }
                    override fun onPlayerError(error: PlaybackException) { failed = true }
                }
                player.addListener(listener)
                onDispose { player.removeListener(listener); player.release() }
            }
            LaunchedEffect(player) {
                while (true) {
                    onPosition(player.currentPosition / 1000.0)
                    kotlinx.coroutines.delay(200)
                }
            }
            AndroidView(factory = { ctx -> TextureView(ctx).also { player.setVideoTextureView(it) } }, modifier = Modifier.fillMaxSize(), update = { player.setVideoTextureView(it) })
        }
        if (!showing || failed) HubImage(poster, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
        if (failed) {
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.6f)), contentAlignment = Alignment.Center) {
                androidx.compose.foundation.layout.Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Outlined.ErrorOutline, null, Modifier.size(28.dp), tint = Color.White.copy(alpha = 0.6f))
                    Text("Clip did not load.", color = Color.White, style = HandOver.type.callout)
                    QuietButton("Try Again", { failed = false; showing = false; attempt++ }, color = Color.White)
                }
            }
        }
        if (!caption.isNullOrBlank()) {
            Text(
                caption,
                style = HandOver.type.captionText,
                color = HandOver.colors.captionInk,
                textAlign = TextAlign.Center,
                maxLines = 2,
                modifier = Modifier.align(Alignment.BottomCenter).padding(12.dp).clip(RoundedCornerShape(8.dp))
                    .background(HandOver.colors.captionFill).padding(horizontal = 8.dp, vertical = 4.dp),
            )
        }
    }
    LaunchedEffect(url) { failed = false }
}
